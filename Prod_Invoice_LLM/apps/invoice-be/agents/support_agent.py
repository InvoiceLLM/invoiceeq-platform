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

A plain miss is a third, separate state (BE Gap 254): `suggest_escalation=False`
with `low_confidence=True`. It used to set `suggest_escalation=True`, which
rendered an unanswered question in the same red "Issue Diagnosis & Recommended
Escalation" framing as a genuine detected incident. The two are not the same
claim, so they no longer share a flag — but a miss still needs *some* way to
raise a ticket, which is what `low_confidence` drives in the UI.
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
            "password", "forgot", "login", "reset", "credentials", "mfa",
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
            "webhook", "connector", "google drive", "api key",
            "integration", "event", "hmac", "secret", "erp"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Connectors & Webhooks",
        "guidance": (
            "### Connectors & Webhook Integration\n\n"
            "1. **Cloud Folders**: Connect Google Drive in `/settings/connectors` for automated folder polling.\n"
            "2. **Webhook Subscriptions**: Register webhook URLs in `/settings/webhooks` to receive real-time notifications for `invoice.completed`, `invoice.audit_required`, and `invoice.rejected`.\n"
            "3. **HMAC Verification**: All payloads are signed with SHA256 in the `X-InvoiceAI-Signature` header."
        ),
    },
    {
        "id": "billing",
        # "payu" and "checkout" are deliberately NOT keywords here (Gap 254).
        # KB topics are matched before ERROR_TRIGGERS and return early, so either
        # of them made `ERR_PAYU_BILLING_FAILURE` unreachable: "payu error on
        # checkout", "my payment failed at checkout" and "checkout crash" all
        # returned the pricing article instead of the payment-failure
        # troubleshooting card. Pre-existing bug, not introduced by Gap 254's
        # topic expansion; see test_error_triggers_are_not_shadowed_by_kb_keywords
        # for the standing screen that keeps it from coming back.
        "keywords": [
            "billing", "plan", "pricing", "pro", "upgrade", "subscription",
            "quota", "50 invoices", "invoice limit", "card"
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
        # "data" was a keyword here until Gap 254. Word-boundary matching does
        # nothing for it -- it is a genuine whole word -- so "is my data
        # encrypted at rest?" tied 1-1 against `security_retention` on hit count
        # and Python's stable sort handed the win to whichever topic sits earlier
        # in this list, returning the CSV-export guide for a security question.
        # Too generic to keep; the seven below still cover the topic fully.
        "keywords": [
            "export", "download", "csv", "excel", "json", "report", "analytics"
        ],
        "category": "GENERAL",
        "title": "Exporting Data & Reports",
        "guidance": (
            "### Exporting Invoices & Reports\n\n"
            "1. **From Dashboard / Invoices**: Navigate to `/invoices`, select the invoices you wish to export, and click **Export CSV** or **Export JSON** from the top actions bar.\n"
            "2. **Auditor Summary**: Filter by status (`PAID`, `REJECTED`, `AUDIT_REQUIRED`) to export audit logs with reconciliation notes."
        ),
    },
    {
        "id": "ingestion_upload",
        "keywords": [
            "upload", "ingest", "import", "bulk", "formats", "pdf", "limit", "size", "pages"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Uploading & Ingestion Limits",
        "guidance": (
            "### Uploading & Ingestion Limits\n\n"
            "1. **Supported Formats**: We support PDF documents (both vector and scanned OCR).\n"
            "2. **Size Limits**: Individual files must be under 25 MB. For bulk uploads, limit batches to 100 pages total to prevent timeouts.\n"
            "3. **How to Ingest**: Upload directly via the dashboard **'Upload'** button, or send/forward files to your tenant's custom ingestion email address found in `/settings/service-flow`."
        ),
    },
    {
        "id": "invoice_statuses",
        "keywords": [
            "status", "lifecycle", "processing", "audit_required", "audit required", "verified",
            "needs_review", "needs review", "sent", "paid"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Understanding Invoice Statuses",
        "guidance": (
            "### Understanding Invoice Statuses\n\n"
            "Each invoice in the system flows through a structured lifecycle:\n\n"
            "- **Inbound (Received Bills)**:\n"
            "  - `PROCESSING`: The file is undergoing OCR parsing and AI extraction.\n"
            "  - `AUDIT_REQUIRED`: Flagged by compliance rules (e.g. total mismatch or duplicate check) and requires manual verification.\n"
            "  - `COMPLETED`: Successfully extracted and verified with no unresolved blocker alerts.\n\n"
            "- **Outbound (Sent Invoices)**:\n"
            "  - `NEEDS_REVIEW`: Awaiting final check before sending.\n"
            "  - `VERIFIED` / `SENT`: Validated and dispatched to the customer.\n"
            "  - `PAID`: Marked as settled."
        ),
    },
    {
        "id": "dashboard_analytics",
        "keywords": [
            "dashboard", "analytics", "graph", "chart", "reports", "spend", "trend", "metrics", "summary"
        ],
        "category": "GENERAL",
        "title": "Dashboard & Analytics Overview",
        "guidance": (
            "### Dashboard & Analytics Overview\n\n"
            "The main dashboard provides real-time financial visibility and operations metrics:\n\n"
            "1. **Metrics Summary**: View total invoices processed, distinct vendor count, and aggregate spend broken down by currency.\n"
            "2. **Trend Analytics**: Visual graphs show month-over-month spend patterns, AP/AR flow comparisons, and processing speed metrics.\n"
            "3. **Auditor Queue Load**: Track outstanding `AUDIT_REQUIRED` queues and processing throughput metrics."
        ),
    },
    {
        "id": "user_management",
        "keywords": [
            "invite", "user", "member", "team", "permission", "role", "admin", "remove user", "delete user"
        ],
        "category": "GENERAL",
        "title": "User Management & Permissions",
        "guidance": (
            "### User Management & Permissions\n\n"
            "Manage your organisation's team members and access control:\n\n"
            "1. **Access Settings**: Go to `/settings/organisation` (Admin privileges required).\n"
            # Gap 337: the three roles are Admin, Auditor and Trainer. This copy
            # is live and customer-facing (Help Center chatbot), and it named a
            # "Viewer" role that no longer exists.
            "2. **Inviting Members**: Click **Invite User**, enter their email address, and select a role (`Admin`, `Auditor`, or `Trainer`). An invite link will be sent via Clerk.\n"
            "3. **Role Capabilities**:\n"
            "   - **Admin**: Full access to billing, user invites, webhooks, and AI Trainer.\n"
            "   - **Auditor**: Can edit, verify, approve, and reject invoices in the Auditor console.\n"
            "   - **Trainer**: Can create and manage extraction rules in the AI Trainer. No audit or approval rights.\n"
            "4. **Everyone**: Dashboard, Chat and Help are available to every member regardless of role; a member with no role assigned yet sees only those three."
        ),
    },
    {
        "id": "security_retention",
        "keywords": [
            "security", "encryption", "retention", "gdpr", "compliance", "data security", "storage",
            "encrypt", "at rest", "tls"
        ],
        "category": "GENERAL",
        "title": "Data Security & Retention Compliance",
        "guidance": (
            "### Data Security & Retention Compliance\n\n"
            "Your data security and compliance are built into our architecture:\n\n"
            "1. **Encryption**: All invoice documents and extracted metadata are encrypted at rest using AES-256 (Azure Managed Keys) and in transit using TLS 1.3.\n"
            "2. **Data Isolation**: Multi-tenant database schema isolation ensures that your invoices are strictly private to your Clerk Organization context.\n"
            "3. **Retention Policy**: Inbound files and audit history are retained in storage for 7 years to meet standard tax audit requirements, unless a custom deletion/retention window is configured for your tenant."
        ),
    },
    {
        "id": "autopilot",
        "keywords": [
            "autopilot", "automation", "deduplication", "sync now", "folder sync", "scheduled sync"
        ],
        "category": "TECHNICAL_SUPPORT",
        "title": "Tenant Autopilot & Scheduled Ingestion",
        "guidance": (
            "### Tenant Autopilot & Scheduled Ingestion\n\n"
            "Autopilot automates the bulk ingestion of invoices from cloud folders:\n\n"
            "1. **Folder Connection**: Connect your Google Drive folder in `/settings/connectors`.\n"
            "2. **Scheduled Syncs**: The background sweep runs automatically on a scheduled cron interval (Azure Container Apps Jobs) to fetch newly added files.\n"
            "3. **Deduplication Ledger**: To prevent duplicate processing and charges, Autopilot performs two-layer validation matching both **file IDs** and **SHA-256 content hashes** in `tenant_autopilot_logs`.\n"
            "4. **Manual Sync**: Click **Sync Now** inside the dashboard to trigger an immediate folder sweep.\n"
            "5. **Notifications**: Enable `notify_emails` or `send_approval_links` in config to receive detailed SendGrid email reports with review links when a sync completes."
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

MIN_KEYWORD_LENGTH = 3


def _score_topic(topic: dict[str, Any], lower_query: str) -> tuple[int, int]:
    """(number of keywords matched, total length of those keywords).

    The second element is the tie-break, and it exists because hit count alone
    is not a confidence measure (Gap 254): a topic can win on one very generic
    single-word hit while a topic with a longer, more specific phrase match ties
    it and loses only because it sits later in `KNOWLEDGE_TOPICS`. Total matched
    length is a cheap proxy for specificity -- `"at rest"`/`"data security"` beat
    a bare `"data"`/`"report"` -- and it removes the de-facto "first topic in the
    list wins every tie" behaviour that made `account_auth` the wrong-answer
    default.

    Word boundaries, not substring: `kw in lower_query` matched `"id"` inside
    "confidence"/"provide" and `"pro"` inside "processing". `MIN_KEYWORD_LENGTH`
    keeps a 1-2 character keyword from being added back later and silently
    reintroducing that class.
    """
    matched = [
        kw for kw in topic["keywords"]
        if len(kw) >= MIN_KEYWORD_LENGTH and re.search(rf"\b{re.escape(kw)}\b", lower_query)
    ]
    return len(matched), sum(len(kw) for kw in matched)


_FOLLOW_UP_PHRASES = (
    "how do i do that",
    "how to do that",
    "how do i do this",
    "how to do this",
    "tell me more",
    "explain that",
    "explain this",
    "what are the steps",
    "can you elaborate",
    "show me how",
    "how does that work",
    "what next",
    "and then",
)


def _topic_by_id(topic_id: str | None) -> dict[str, Any] | None:
    if not topic_id:
        return None
    for topic in KNOWLEDGE_TOPICS:
        if topic["id"] == topic_id:
            return topic
    return None


def _is_anaphoric_follow_up(query: str) -> bool:
    q = query.lower().strip().rstrip("?.!")
    return any(phrase in q for phrase in _FOLLOW_UP_PHRASES)


def _topic_result(topic: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": topic["guidance"],
        "topic_id": topic["id"],
        "suggest_escalation": False,
        "low_confidence": False,
        "escalation_context": None,
    }


def evaluate_support_query(
    message: str,
    history: list[dict[str, Any]] | None = None,
    last_topic_id: str | None = None,
) -> dict[str, Any]:
    """
    Evaluates a user query and returns:
      - answer: Markdown guidance for the user with solutions first
      - suggest_escalation: bool — a real incident was detected, or the user
        explicitly asked for a human. Drives the red "Issue Diagnosis" card.
      - low_confidence: bool — no article matched at all. Drives a neutral
        "didn't find an answer, raise a ticket?" affordance in the UI, which is
        deliberately NOT the same thing as a diagnosed incident.
      - escalation_context: dict with category, priority, subject, error_code (or None)

    `history` is accepted for interface stability but is not read for topic
    resolution — only `last_topic_id` (echoed from the prior assistant turn and
    stored by the FE) can resolve a short anaphoric follow-up such as
    "how do I do that?". Re-matching against the assistant's own prior guidance
    text was rejected because the guidance blobs are keyword-dense (Gap 256).
    """
    clean_query = (message or "").strip()
    if not clean_query:
        return {
            "answer": "Hello! I am SAGE, your AI Support Assistant. Ask me anything about using Invoice AI, resetting passwords, configuring rules, or resolving errors.",
            "topic_id": None,
            "suggest_escalation": False,
            "low_confidence": False,
            "escalation_context": None,
        }

    lower_query = clean_query.lower()

    # 1. Match against Knowledge Base Topics FIRST with word boundaries & length constraints
    matched_topics: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for topic in KNOWLEDGE_TOPICS:
        score = _score_topic(topic, lower_query)
        if score[0] > 0:
            matched_topics.append((score, topic))

    if matched_topics:
        matched_topics.sort(key=lambda x: x[0], reverse=True)
        return _topic_result(matched_topics[0][1])

    # 2. Anaphoric follow-up against the prior matched topic (BE Gap 256).
    prior_topic = _topic_by_id(last_topic_id)
    if prior_topic and _is_anaphoric_follow_up(clean_query):
        return _topic_result(prior_topic)

    # 3. Check for explicit severe error triggers
    for err in ERROR_TRIGGERS:
        if re.search(err["pattern"], lower_query):
            return {
                "answer": (
                    f"{err['message']}\n\n"
                    "If the above steps do not resolve the issue, you can escalate this directly "
                    "to our technical support team using the button below. Your diagnostics will be pre-filled."
                ),
                "topic_id": None,
                "suggest_escalation": True,
                "low_confidence": False,
                "escalation_context": {
                    "category": err["category"],
                    "priority": err["priority"],
                    "subject": err["subject"],
                    "error_code": err["error_code"],
                },
            }

    # 4. Check for explicit human support requests
    if re.search(r"(human|agent|raise\s*ticket|support\s*ticket|contact\s*support|speak\s*to\s*someone|talk\s*to\s*human)", lower_query):
        return {
            "answer": (
                "I would be glad to connect you with our engineering and support team!\n\n"
                "Click the **Raise Support Ticket** button below to submit your inquiry directly to `Application@infinevocloud.com`."
            ),
            "topic_id": None,
            "suggest_escalation": True,
            "low_confidence": False,
            "escalation_context": {
                "category": "TECHNICAL_SUPPORT",
                "priority": "NORMAL",
                "subject": clean_query[:80],
                "error_code": None,
            },
        }

    # 5. General fallback: an honest miss. `suggest_escalation` stays False so the
    # UI does not frame an unanswered question as a diagnosed incident, and
    # `low_confidence` is set so it can still offer a plain "raise a ticket"
    # affordance instead of silently offering nothing (see SupportChatWindow.tsx).
    return {
        "answer": (
            "I couldn't find a specific help article matching your question. Here is where you can look:\n\n"
            "1. **Explore the Knowledge Base Guides tab** above for step-by-step illustrated walkthroughs on **AI Trainer Rules**, **Auditor Console**, and **Connectors**.\n"
            "2. **Check App Settings**: Review your account and organisation settings in `/settings`.\n\n"
            "If you still need help, feel free to ask to speak to support or request a ticket, and I will connect you."
        ),
        "topic_id": None,
        "suggest_escalation": False,
        "low_confidence": True,
        "escalation_context": {
            "category": "TECHNICAL_SUPPORT",
            "priority": "NORMAL",
            "subject": clean_query[:80],
            "error_code": None,
        },
    }
