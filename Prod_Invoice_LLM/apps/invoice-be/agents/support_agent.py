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

Gap 403: a query that scores zero keyword hits against `KNOWLEDGE_TOPICS` and
isn't an error trigger or an explicit human-help request now gets one more
chance — a semantic (vector) match against the same topic set — before it is
allowed to become a generic miss. This does not touch the keyword pass, the
error triggers, or the human-help path at all: those are all checked first and
are exactly as deterministic as before. See `_vector_match_topic()` below.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any

from chroma_client import get_chroma_client, get_embeddings

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


# ---------------------------------------------------------------------------
# Gap 403: semantic (vector) fallback over KNOWLEDGE_TOPICS
# ---------------------------------------------------------------------------
#
# Only reached when the keyword pass above scores zero hits AND the query is
# not an error trigger or an explicit human-help request (both checked first
# in evaluate_support_query() — see the ordering note there for why). This is
# a shared, non-tenant collection: platform documentation is identical for
# every tenant, unlike chroma_client.py's per-tenant invoice-chunk collections
# (Gap 55), so there is nothing to isolate.

_SUPPORT_COLLECTION_NAME = "support_knowledge_topics"
_SUPPORT_VERSION_DOC_ID = "__content_version__"
_support_collection_lock = threading.Lock()
_support_collection_seeded = False

# Gap 430: derived by measurement, not chosen. Method mirrors Gap 244's --
# embed every topic, run a labelled set of real paraphrases, and place the
# cutoff between the hardest genuine match and the closest false positive.
#
# Measured against the real BAAI/bge-m3 model with the prose embedding text
# below (`scripts/measure_support_retrieval.py`; full output in the Gap 430
# tracker entry). The previous value, 0.35, was a guess set stricter than this
# repo's own already-measured invoice-chunk threshold (0.49) and was
# **unreachable** -- genuine matches sit at 0.31-0.53, so the vector fallback
# could never fire at all. It shipped dead.
#
# THE BANDS OVERLAP, and that is why there are two constants rather than one.
# Measured: hardest genuine match 0.5320; closest false positive 0.5228
# ("how do I train for a marathon" -> the AI *Trainer* topic, on the word
# "train"). No single distance separates them.
#
# 0.52 sits just below that false positive, so every measured negative is
# rejected on distance alone. The deliberate cost: one genuine query
# ("what do the different states on a bill actually mean", 0.5320) now returns
# no answer. That trade is taken knowingly -- answering a marathon-training
# question with the AI Trainer guide is a worse product than saying nothing,
# and the neutral "didn't find an answer" card still offers a ticket.
SUPPORT_RELEVANCE_DISTANCE_THRESHOLD = 0.52

# Gap 430: a match must also beat the runner-up by this much.
#
# This is what actually catches wrong-topic answers, and the measurement is
# unusually clean: every correct match had a runner-up gap of >= 0.0193, while
# both wrong-topic cases sat at 0.0061 and 0.0052 -- a 3x separation. 0.012 is
# the midpoint of that gap.
#
# A first guess of 0.03 was wrong in the other direction: it would have
# rejected genuine matches at 0.0193 and 0.0228. Set from the data, not taste.
SUPPORT_RELEVANCE_MARGIN = 0.012


def _topic_embedding_text(topic: dict[str, Any]) -> str:
    """Text embedded to represent a topic: title plus the prose answer.

    Gap 430 changed this from title + keyword list. Embedding a bag of
    keywords made a question match whichever bag shared vocabulary rather than
    the topic that actually answers it -- the ranking inversion above. The
    `guidance` prose is real language about the real subject, which is what a
    sentence-embedding model is built to compare a question against.

    The keywords are deliberately NOT appended as well. They are optimised for
    the exact-match pass in `_score_topic()`, and mixing them back in here
    reintroduces exactly the vocabulary-collision effect this change removes.
    """
    return f"{topic['title']}\n\n{topic['guidance']}"


def _topics_content_fingerprint() -> str:
    """Hash of everything that goes into the index.

    Gap 430 bug fix. Seeding used to be guarded by `collection.count() == 0`,
    so once a collection existed it was **never re-seeded** -- editing
    `KNOWLEDGE_TOPICS`, or changing `_topic_embedding_text()` as this gap does,
    left the index serving the old vectors forever, in every environment, with
    no error and no way to notice. Any future edit to the knowledge base would
    silently do nothing.
    """
    payload = " || ".join(f"{t['id']}::{_topic_embedding_text(t)}" for t in KNOWLEDGE_TOPICS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_support_collection():
    """Returns the shared support-topics Chroma collection, seeding or
    **re-seeding** it from `KNOWLEDGE_TOPICS` whenever the content changes.

    Gap 430: the previous version seeded only `if collection.count() == 0`, so
    an existing collection was never refreshed. Editing a topic, adding one, or
    changing how topics are embedded left the index serving stale vectors
    permanently and silently. The fingerprint below is stored as a sentinel
    document inside the collection itself (rather than collection metadata,
    which Chroma fixes at creation time), so a mismatch on any process start
    triggers a full rebuild.
    """
    global _support_collection_seeded
    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=_SUPPORT_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    if _support_collection_seeded:
        return collection

    with _support_collection_lock:
        if _support_collection_seeded:
            return collection

        fingerprint = _topics_content_fingerprint()
        stored = None
        try:
            found = collection.get(ids=[_SUPPORT_VERSION_DOC_ID])
            metas = (found or {}).get("metadatas") or []
            if metas:
                stored = (metas[0] or {}).get("fingerprint")
        except Exception:  # pragma: no cover - treated as "needs seeding"
            stored = None

        if stored != fingerprint:
            texts = [_topic_embedding_text(t) for t in KNOWLEDGE_TOPICS]
            ids = [t["id"] for t in KNOWLEDGE_TOPICS]
            # Drop anything from a previous content version, including topics
            # that no longer exist -- an upsert alone would leave a deleted
            # topic in the index answering questions forever.
            try:
                existing = (collection.get() or {}).get("ids") or []
                stale = [i for i in existing if i not in ids and i != _SUPPORT_VERSION_DOC_ID]
                if stale:
                    collection.delete(ids=stale)
            except Exception:  # pragma: no cover - best effort
                logger.warning("Gap 430: could not prune stale support topics", exc_info=True)

            embeddings = get_embeddings(texts)
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=[{"topic_id": t["id"]} for t in KNOWLEDGE_TOPICS],
            )
            # Sentinel last: if anything above fails we do not record the new
            # version, so the next process retries rather than trusting a
            # half-written index.
            collection.upsert(
                ids=[_SUPPORT_VERSION_DOC_ID],
                embeddings=[[0.0] * len(embeddings[0])],
                documents=["support knowledge base content version marker"],
                metadatas=[{"fingerprint": fingerprint, "topic_id": _SUPPORT_VERSION_DOC_ID}],
            )
            logger.info(
                "Gap 430: support knowledge index seeded/refreshed (%d topics, fingerprint %s)",
                len(ids), fingerprint[:12],
            )

        _support_collection_seeded = True
    return collection


def _vector_match_topic(query: str) -> dict[str, Any] | None:
    """Semantic fallback for a query that scored zero keyword hits. Returns
    the best-matching topic dict if it clears
    `SUPPORT_RELEVANCE_DISTANCE_THRESHOLD`, else None.

    Any Chroma/embedding failure degrades to None (falls through to the
    existing miss path) rather than raising — a vector-search outage must not
    break the Support Assistant, it should only cost this one enhancement.
    This collection is always freshly created with `hnsw:space=cosine` by
    `_get_support_collection()` above, so unlike `query_invoice_chunks()`
    there is no pre-existing non-cosine collection to normalize distances for.
    """
    try:
        collection = _get_support_collection()
        query_embedding = get_embeddings([query])
        # Gap 430: 3, not 1 -- the margin check needs a runner-up, and the
        # content-version sentinel may occupy one slot.
        results = collection.query(query_embeddings=query_embedding, n_results=3)
    except Exception:
        logger.warning("Gap 430 vector fallback failed; treating as a miss", exc_info=True)
        return None

    ids = (results.get("ids") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    # Drop the content-version sentinel: it is a zero vector carrying no
    # meaning, and letting it rank would be a silent wrong answer.
    ranked = [(d, i) for i, d in zip(ids, distances) if i != _SUPPORT_VERSION_DOC_ID]
    if not ranked:
        return None

    best_distance, best_id = ranked[0]
    if best_distance > SUPPORT_RELEVANCE_DISTANCE_THRESHOLD:
        return None

    # Gap 430: the margin guard. Two topics scoring near-identically means the
    # question does not clearly belong to either, and answering with whichever
    # won by a hair is how a confidently wrong article gets shown. Returning
    # nothing routes the user to the neutral "didn't find an answer" card,
    # which is honest and still offers a ticket.
    if len(ranked) > 1 and (ranked[1][0] - best_distance) < SUPPORT_RELEVANCE_MARGIN:
        logger.info(
            "Gap 430: ambiguous support match (%s %.4f vs %s %.4f) -- returning no answer",
            best_id, best_distance, ranked[1][1], ranked[1][0],
        )
        return None

    logger.info("Gap 430: support topic %s matched at distance %.4f", best_id, best_distance)
    return _topic_by_id(best_id)


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

    # 5. Gap 403: semantic fallback. Deliberately placed after error triggers and
    # the explicit human-help check above, not before them — those two guarantees
    # (a genuine incident always escalates, an explicit ask for a human always
    # escalates) must stay exactly as deterministic as they were, unaffected by
    # embedding-model behaviour. This step only gets a query that has already
    # failed every keyword-based check; it exists to give that query one more,
    # semantic chance before it becomes a generic miss.
    vector_topic = _vector_match_topic(clean_query)
    if vector_topic:
        return _topic_result(vector_topic)

    # 6. General fallback: an honest miss. `suggest_escalation` stays False so the
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
