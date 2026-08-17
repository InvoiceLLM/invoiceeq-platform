"""
Feature 19 / FE Feature 15: Support AI Agent & Platform Troubleshooting Engine.

This agent evaluates user inquiries about platform functionality, configuration,
or errors. It prioritizes providing immediate, actionable, step-by-step solutions
to user questions first.

When the agent detects:
  1. Severe unresolvable operational errors (e.g., 504 gateway timeout, database failure, PayU billing exception)
  2. Explicit user requests to raise a ticket or speak to support engineering

It returns `suggest_escalation=True` along with structured `escalation_context`
(category, priority, subject, error_code) so the UI can present an actionable
1-click `[ 🎫 Raise Support Ticket from this Issue ]` card.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform Documentation Knowledge Base
# ---------------------------------------------------------------------------

KNOWLEDGE_TOPICS: list[dict[str, Any]] = [
    {
        "id": "account_auth",
        "keywords": [
            "password", "forgot", "login", "reset", "id", "credentials", "mfa",
            "2fa", "otp", "account", "sign in", "signin", "sso", "clerk", "email change", "profile"
        ],
        "category": "GENERAL",
        "title": "Account, Login & Password Reset",
        "guidance": (
            "### Password Reset & Account Recovery Steps\n\n"
            "If you forgot your password or need to reset your login credentials:\n\n"
            "1. **Navigate to the Reset Page**: Go to the login screen and click **'Forgot Password?'** or visit `/forgot-password` directly.\n"
            "2. **Enter Your Registered Email**: Type the email address linked to your organisation account and click **Send Verification Code**.\n"
            "3. **Check Your Inbox**: Enter the 6-digit one-time code sent to your email.\n"
            "4. **Set a New Password**: Enter your new secure password (minimum 8 characters with numbers and symbols) and submit.\n\n"
            "💡 *Tip: If your organisation uses Google or Microsoft Single Sign-On (SSO), you can sign in directly using the **Continue with Google/Microsoft** button on `/login` without needing a password.*"
        ),
    },
    {
        "id": "trainer",
        "keywords": [
            "train", "trainer", "vendor rule", "template", "prompt", "bounding box",
            "chat correction", "commit", "sandbox", "extraction rule", "rule history"
        ],
        "category": "TRAINER",
        "title": "AI Trainer & Extraction Rules",
        "guidance": (
            "### AI Trainer Sandbox Guide\n\n"
            "1. **Accessing the Trainer**: Navigate to `/trainer` from the left sidebar (available on Pro & Pro Combined plans).\n"
            "2. **Training Modes**:\n"
            "   - **Global Scope**: Teaches business rules across all vendors (e.g. strict GST/VAT checksums).\n"
            "   - **Vendor-Specific Scope**: Select an existing vendor or upload a new invoice sample to customize layout extraction.\n"
            "3. **Chat Corrections**: Type your corrections in plain language in the right-side chat panel (e.g., *'The line total should exclude freight fees'*). SAGE generates a live preview diff.\n"
            "4. **Committing Changes**: Click **Review & Commit** to save the rule into production extraction."
        ),
    },
    {
        "id": "auditor",
        "keywords": [
            "auditor", "audit", "alert", "line item", "mismatch", "verification",
            "reject", "paid", "review", "duplicate", "flagged", "confidence"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Auditor Review Console",
        "guidance": (
            "### Resolving Flagged Invoices in Auditor\n\n"
            "1. **Workspace Layout**: The console features 3 synchronized panels: **PDF Viewer** (left) → **Extracted Fields & Lines** (center) → **Alert Console** (right).\n"
            "2. **Alert Severity Levels**:\n"
            "   - 🔴 **Blocker**: Calculation mismatches or unverified vendor bank accounts.\n"
            "   - 🟡 **Warning**: Low confidence extractions or unusual date formats.\n"
            "   - 🔵 **Info**: General compliance checks.\n"
            "3. **Taking Action**: Click a field to edit value inline, click **Dismiss** on false alerts with a reason, or click **Mark as Paid** / **Reject**."
        ),
    },
    {
        "id": "email_ingestion",
        "keywords": [
            "email", "inbound", "forwarding", "sendgrid", "mail", "mailbox",
            "attachment", "parser", "auto ingest"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Inbound & Outbound Email Ingestion",
        "guidance": (
            "### Email Ingestion Setup\n\n"
            "1. **Dedicated Mailbox**: Forward PDF invoices directly to your tenant's assigned mailbox address (configured in `/settings/service-flow`).\n"
            "2. **Supported Formats**: Single and multi-page PDF documents up to 25 MB.\n"
            "3. **Automatic Scanning**: Inbound emails are OCR-scanned and queued for AI extraction within 15 seconds."
        ),
    },
    {
        "id": "connectors_webhooks",
        "keywords": [
            "webhook", "connector", "salesforce", "google drive", "api key",
            "integration", "event", "hmac", "secret", "erp"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Connectors & Webhooks",
        "guidance": (
            "### Connectors & Webhook Integration\n\n"
            "1. **Cloud Folders**: Connect Google Drive or Salesforce in `/settings/connectors` for automated folder polling.\n"
            "2. **Webhook Subscriptions**: Register webhook URLs in `/settings/webhooks` to receive real-time notifications for `invoice.completed`, `invoice.audit_required`, and `invoice.rejected`.\n"
            "3. **HMAC Verification**: All payloads are signed with SHA256 in the `X-InvoiceAI-Signature` header."
        ),
    },
    {
        "id": "billing",
        "keywords": [
            "billing", "plan", "pricing", "payu", "pro", "upgrade", "subscription",
            "checkout", "quota", "50 invoices", "invoice limit", "card"
        ],
        "category": "BILLING",
        "title": "Subscriptions & Billing",
        "guidance": (
            "### Subscriptions & Quotas\n\n"
            "1. **Free Tier**: 50 invoices/month with automated OCR extraction and standard audit queue.\n"
            "2. **Pro Plan ($49/mo)**: Unlimited invoices, AI Trainer Sandbox, custom vendor rules, and webhooks.\n"
            "3. **Pro Combined ($89/mo)**: Adds outbound AR invoice generation and customer compliance rules.\n"
            "4. **Upgrade**: Visit `/settings/subscriptions` and click **Change Subscription Plan** to complete checkout via PayU."
        ),
    },
    {
        "id": "export_reports",
        "keywords": [
            "export", "download", "csv", "excel", "json", "report", "analytics", "data"
        ],
        "category": "GENERAL",
        "title": "Exporting Data & Reports",
        "guidance": (
            "### Exporting Invoices & Reports\n\n"
            "1. **From Dashboard / Invoices**: Navigate to `/invoices`, select the invoices you wish to export, and click **Export CSV** or **Export JSON** from the top actions bar.\n"
            "2. **Auditor Summary**: Filter by status (`PAID`, `REJECTED`, `AUDIT_REQUIRED`) to export audit logs with reconciliation notes."
        ),
    },
]

# Known severe error patterns that warrant direct ticket escalation
ERROR_TRIGGERS: list[dict[str, Any]] = [
    {
        "pattern": r"(504|gateway\s*timeout|batch\s*sync\s*timeout)",
        "category": "TECHNICAL_SUPPORT",
        "priority": "URGENT",
        "subject": "System Timeout / Batch Sync Failure (Error 504)",
        "error_code": "ERR_GATEWAY_TIMEOUT_504",
        "message": (
            "### ⚠️ Gateway Timeout (504) Detected\n\n"
            "**Troubleshooting Steps**:\n"
            "1. Check if the external ERP endpoint or cloud folder is currently reachable.\n"
            "2. Ensure the batch file size is within the 25 MB limit.\n"
            "3. Refresh `/invoices` to check if queued background jobs resume."
        ),
    },
    {
        "pattern": r"(500|internal\s*server\s*error|database\s*connection\s*error)",
        "category": "TECHNICAL_SUPPORT",
        "priority": "URGENT",
        "subject": "Server Exception / Internal Error 500",
        "error_code": "ERR_INTERNAL_SERVER_500",
        "message": (
            "### ⚠️ Internal Server Error (500) Detected\n\n"
            "**Troubleshooting Steps**:\n"
            "1. Try reloading the active page or clearing your browser cache.\n"
            "2. Verify that your organisation session token is active in `/settings`."
        ),
    },
    {
        "pattern": r"(payu\s*error|payment\s*failed|double\s*charge|checkout\s*crash)",
        "category": "BILLING",
        "priority": "URGENT",
        "subject": "Payment Processing / Checkout Error",
        "error_code": "ERR_PAYU_BILLING_FAILURE",
        "message": (
            "### ⚠️ Payment Processing Issue Detected\n\n"
            "**Troubleshooting Steps**:\n"
            "1. Confirm that your bank card is authorized for 3D Secure / OTP transactions.\n"
            "2. Check if your current subscription shows as active under `/settings/subscriptions`."
        ),
    },
]


# ---------------------------------------------------------------------------
# Core Evaluation Function
# ---------------------------------------------------------------------------

def evaluate_support_query(
    message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Evaluates a user query and returns:
      - answer: Markdown guidance for the user with solutions first
      - suggest_escalation: bool
      - escalation_context: dict with category, priority, subject, error_code (or None)
    """
    clean_query = (message or "").strip()
    if not clean_query:
        return {
            "answer": "Hello! I am SAGE, your AI Support Assistant. Ask me anything about using Invoice AI, resetting passwords, configuring rules, or resolving errors.",
            "suggest_escalation": False,
            "escalation_context": None,
        }

    lower_query = clean_query.lower()

    # 1. Match against Knowledge Base Topics FIRST (so questions like password reset give direct solutions)
    matched_topics: list[tuple[int, dict[str, Any]]] = []
    for topic in KNOWLEDGE_TOPICS:
        score = sum(1 for kw in topic["keywords"] if kw in lower_query)
        if score > 0:
            matched_topics.append((score, topic))

    if matched_topics:
        matched_topics.sort(key=lambda x: x[0], reverse=True)
        best_topic = matched_topics[0][1]
        return {
            "answer": best_topic["guidance"],
            "suggest_escalation": False,
            "escalation_context": None,
        }

    # 2. Check for explicit severe error triggers
    for err in ERROR_TRIGGERS:
        if re.search(err["pattern"], lower_query):
            return {
                "answer": (
                    f"{err['message']}\n\n"
                    "If the above steps do not resolve the issue, you can escalate this directly "
                    "to our technical support team using the button below. Your diagnostics will be pre-filled."
                ),
                "suggest_escalation": True,
                "escalation_context": {
                    "category": err["category"],
                    "priority": err["priority"],
                    "subject": err["subject"],
                    "error_code": err["error_code"],
                },
            }

    # 3. Check for explicit human support requests
    if re.search(r"(human|agent|raise\s*ticket|support\s*ticket|contact\s*support|speak\s*to\s*someone|talk\s*to\s*human)", lower_query):
        return {
            "answer": (
                "I would be glad to connect you with our engineering and support team!\n\n"
                "Click the **Raise Support Ticket** button below to submit your inquiry directly to `Application@infinevocloud.com`."
            ),
            "suggest_escalation": True,
            "escalation_context": {
                "category": "TECHNICAL_SUPPORT",
                "priority": "NORMAL",
                "subject": clean_query[:80],
                "error_code": None,
            },
        }

    # 4. General fallback: helpful guidance with optional escalation bridge
    return {
        "answer": (
            "Here is how you can resolve this or find more details:\n\n"
            "1. **Explore the Knowledge Base Guides tab** above for step-by-step illustrated walkthroughs on **AI Trainer Rules**, **Auditor Console**, and **Connectors**.\n"
            "2. **Check App Settings**: Review your account and organisation settings in `/settings`.\n\n"
            "If you need personalized assistance from our engineering team, click below to raise a support ticket."
        ),
        "suggest_escalation": True,
        "escalation_context": {
            "category": "GENERAL",
            "priority": "NORMAL",
            "subject": clean_query[:80],
            "error_code": None,
        },
    }
