from typing import Any
from uuid import UUID, uuid4
from datetime import datetime, date
from sqlmodel import SQLModel, Field, Column
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from config import settings

# Cross-platform JSON type: JSONB on PostgreSQL, JSON/Text fallback on SQLite
JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")

class Tenant(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    domain: str = Field(max_length=255, unique=True, index=True)
    clerk_org_id: str | None = Field(default=None, max_length=255, unique=True, index=True)
    billing_plan: str = Field(default="free", max_length=50)
    free_invoices_remaining: int = Field(default_factory=lambda: settings.DEFAULT_FREE_INVOICES_LIMIT)
    # Gap 118: when the free allowance above next refills. routers/invoices.py
    # only ever decrements free_invoices_remaining, so without this the "50
    # invoices/month" free tier was really 50 invoices for the lifetime of the
    # account. NULL means "the cycle clock has not started yet" -- true for
    # every row predating the migration and for a tenant that has never been on
    # the free plan -- and is seeded, without granting a refill, the first time
    # services/billing_lifecycle.refresh_free_quota() sees the tenant.
    free_quota_reset_at: datetime | None = Field(default=None)
    payu_customer_id: str | None = Field(default=None, max_length=255)
    payu_subscription_id: str | None = Field(default=None, max_length=255)
    # Gap 71: end of the currently-paid-for billing cycle. PayU's classic API
    # has no subscription object, so this is the only record that a paid plan
    # was ever paid *for a period* rather than once. Extended by
    # services/billing_lifecycle.extend_paid_through() on every verified
    # payment; NULL means "never paid" (free tier) or a legacy pre-Gap-71 row,
    # neither of which may be lapsed -- see is_lapsed().
    paid_through: datetime | None = Field(default=None)
    # BE Gap 264: the user explicitly asked to stop renewing, recorded
    # separately from paid_through/billing_plan so the two questions ("when
    # does access end" and "did the tenant choose that or just go idle")
    # don't collapse into one signal. Does not itself change billing_plan or
    # paid_through -- access continues exactly as already designed until
    # paid_through, and services/billing_lifecycle.py's existing sweep still
    # owns the actual downgrade. NULL means no cancellation is pending.
    cancel_requested_at: datetime | None = Field(default=None)
    # Feature 16: Service Flow toggles
    receive_invoices_enabled: bool = Field(default=True)   # Inbound (AP) — on by default, preserves existing behaviour
    send_invoices_enabled: bool = Field(default=False)     # Outbound (AR) — opt-in, requires pro_combined plan
    outbound_sender_email: str | None = Field(default=None, max_length=255)  # Legacy Gap 125 Reply-To placeholder; Email Setup uses TenantEmailSender sets
    # Gap 184: programmatic API key for this tenant. The raw key is NEVER stored
    # -- only a PBKDF2-HMAC-SHA256 digest of it (`api_key_hash`) plus the
    # per-key random `api_key_salt` it was derived with, so a database dump
    # cannot be replayed as credentials. `api_key_prefix` is the leading,
    # deliberately non-secret slice of the raw key (`inv_live_` + 6 chars),
    # kept only so the UI can show *which* key is active without being able to
    # reconstruct it; the raw value exists in exactly one response, the one that
    # created or rotated it (same "shown once" rule as WebhookSubscription.secret).
    # NULL across all of these means "this tenant has never issued a key".
    api_key_hash: str | None = Field(default=None, max_length=255)
    api_key_salt: str | None = Field(default=None, max_length=64)
    api_key_prefix: str | None = Field(default=None, max_length=32, index=True)
    api_key_rotated_at: datetime | None = Field(default=None)
    # Last time the key successfully authenticated a request. Purely
    # observational (lets an Admin spot a key that is still in use before
    # rotating it, or one that has never been used at all).
    api_key_last_used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Invoice(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    batch_id: UUID | None = Field(default=None, index=True)
    file_path: str = Field(max_length=1024)
    file_hash: str | None = Field(default=None, index=True, max_length=64)

    vendor_name: str | None = Field(default=None)
    subtotal: float | None = Field(default=None)
    grand_total: float | None = Field(default=None)
    invoice_number: str | None = Field(default=None)
    invoice_date: date | None = Field(default=None)
    due_date: date | None = Field(default=None)
    tax_amount: float | None = Field(default=None)
    po_number: str | None = Field(default=None)
    # Gap 195: nullable self-reference, set only on status=DUPLICATE rows
    # (see routers/invoices.py::_ingest_single_file's duplicate branch) --
    # gives webhook subscribers and any future UI a structured pointer to
    # the original invoice instead of the prose inside sa_alerts.
    duplicate_of_invoice_id: UUID | None = Field(default=None, foreign_key="invoice.id", nullable=True, index=True)
    status: str = Field(default="PROCESSING")
    sa_alerts: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    tags: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    items: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    coordinates: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    field_confidence: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    # Gap 178: Doc Intelligence prebuilt-invoice structured fields (JSON), used
    # as the PDF-side reference when checking extraction completeness. Not the
    # PDF binary — that stays in blob storage via file_path.
    source_document_json: dict | None = Field(default=None, sa_column=Column(JSON_VARIANT, nullable=True))
    currency: str | None = Field(default=None)
    discount_percent: float | None = Field(default=None)
    discount_amount: float | None = Field(default=None)
    taxes: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    discounts: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    deductions: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    tax_ids: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    payment_instructions: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    references: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    addresses: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    compliance_metadata: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)
    # Gap 192: soft delete. NULL = live; set to utcnow() hides the row from
    # product queries while preserving the Invoice + AuditLog compliance trail.
    deleted_at: datetime | None = Field(default=None, index=True)

    # FE Gaps 81/84: stuck-invoice reconciliation bookkeeping. `last_enqueued_at`
    # is when a queue message was last *sent* for this invoice (upload time, or
    # the last reconciliation re-enqueue) -- staleness has to be measured from
    # that, not from created_at, or a re-enqueued invoice would look permanently
    # overdue and be re-enqueued on every sweep. `processing_attempts` bounds how
    # many times the sweep will retry before giving up and marking it FAILED,
    # so a genuinely unprocessable file can't be requeued forever.
    last_enqueued_at: datetime | None = Field(default=None)
    processing_attempts: int = Field(default=0)

    # Feature 2.1 (Outbound Invoice Ingestion, Task 2.1.1): flow_direction
    # distinguishes a vendor's invoice addressed to this tenant (INBOUND,
    # every existing row's default -- unaffected) from this tenant's own
    # invoice addressed to their customer (OUTBOUND). customer_name is the AR
    # mirror of vendor_name, populated only for OUTBOUND rows. customer_id is
    # reserved for future customer-record linking -- unused in v1, no
    # customer-facing portal exists yet.
    flow_direction: str = Field(default="INBOUND", max_length=20)
    customer_name: str | None = Field(default=None)
    customer_id: UUID | None = Field(default=None)
    # Feature 8.1 (Outbound Dashboard) Task 8.1.1, bundled in here since
    # Feature 2.1's own confirm-send endpoint needs sent_at immediately --
    # set when the outbound confirm-send/mark-paid endpoints actually fire
    # those transitions, never estimated.
    sent_at: datetime | None = Field(default=None)
    paid_at: datetime | None = Field(default=None)
    # Gap 126: when the `outbound_invoice.overdue` webhook was fired for this
    # invoice by the scheduled sweep (services/outbound_overdue.py). NULL means
    # "never fired". This is bookkeeping for the sweep only -- overdue itself
    # stays a virtual, read-time computation (Feature 7.1/8.1: SENT past
    # due_date); no OVERDUE value is ever written to `status`. Without this
    # column the daily sweep would re-fire the same event for the same invoice
    # every single day it stays unpaid.
    overdue_notified_at: datetime | None = Field(default=None)
    # Gap 125: email (or UI) submitter — process-complete staff notify target.
    # Never used to email end customers from the app.
    submitted_by_email: str | None = Field(default=None, max_length=255)

    # FE Gap 29: dashboard/list filters are always tenant-scoped plus one of
    # status/date/vendor, so composite indexes led by tenant_id (rather than
    # single-column ones) are what the query planner actually uses here.
    __table_args__ = (
        sa.Index("ix_invoice_tenant_status", "tenant_id", "status"),
        sa.Index("ix_invoice_tenant_invoice_date", "tenant_id", "invoice_date"),
        sa.Index("ix_invoice_tenant_vendor_name", "tenant_id", "vendor_name"),
        sa.Index("ix_invoice_tenant_flow_direction", "tenant_id", "flow_direction"),
    )


class TenantConnection(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    provider: str  # e.g., 'google_drive', 'salesforce'
    encrypted_access_token: str
    encrypted_refresh_token: str | None = Field(default=None)
    token_expiry: datetime
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Salesforce's REST API base is per-org (unlike Google Drive's fixed
    # www.googleapis.com) -- Salesforce returns this in every token response
    # (initial exchange and refresh alike), so it must be stored per-connection
    # to make any later API call. Unused by google_drive.
    instance_url: str | None = Field(default=None)

class ChatSession(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    title: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ChatMessage(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(index=True)
    role: str = Field(max_length=50)  # 'user' or 'assistant'
    content: str
    generated_sql: str | None = Field(default=None)
    citations: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # Feature 18 (Gap 231): which invoices actually fed this reply, captured at
    # answer time. Before this column, only the RAG route left any row identity
    # behind (via `citations[].invoice_id`); the SQL route set `citations = []`
    # and returned nothing but `generated_sql` plus a markdown table string --
    # so for an aggregate answer like "total spend across 40 invoices" there was
    # literally nothing to build a "which invoice was wrong?" picker from, which
    # is exactly what the wrong-data triage flow needs.
    #
    # Best-effort by construction (see agents/query_agent.py::_harvest_invoice_ids):
    # an empty list means "we could not determine the row set", never "no rows
    # were involved". The triage API treats empty as "ask the user which invoice"
    # rather than asserting a claim it can't back.
    result_invoice_ids: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # Gap 280: Queue-based Async Chat Architecture
    # Lifecycle status: 'queued' | 'processing' | 'completed' | 'failed'
    status: str = Field(default="completed", max_length=32)
    job_id: str | None = Field(default=None, index=True, max_length=64)
    error_message: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ChatFeedback(SQLModel, table=True):
    __tablename__ = "chat_feedback"
    # Gap 54: signal-only per-answer thumbs up/down, tied to that turn's
    # generated_sql/citations via message_id. One vote per message -- voting
    # again overwrites rather than accumulating, so `message_id` is unique.
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    session_id: UUID = Field(index=True)
    message_id: UUID = Field(index=True, unique=True)
    vote: str = Field(max_length=10)  # "up" or "down"
    # Feature 18 (Gap 232): a thumbs-down is no longer signal-only -- it is the
    # entry point to the chat-correction triage flow, and the three reasons below
    # route to three structurally different destinations:
    #   wrong_data          -> auto-diff against the stored DB value; may end up
    #                          redirecting into the *extraction* flow instead if
    #                          the stored data (not the reply) is what's wrong
    #   wrong_interpretation-> a TenantChatRule about the agent's own reasoning
    #   bad_tone            -> TenantChatSettings, not a rule at all
    # NULL on every pre-Feature-18 row and on any thumbs-up (a positive vote has
    # no reason to give), which is why it stays nullable rather than defaulted.
    reason: str | None = Field(default=None, max_length=32)
    # Optional free text. Deliberately secondary context only -- never the
    # primary input to rule generation, so a blank note can't produce a rule and
    # a prose note can't quietly become one.
    note: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, foreign_key="tenant.id", nullable=True)
    email: str = Field(max_length=255, unique=True, index=True)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    role: str = Field(max_length=50)
    clerk_user_id: str = Field(max_length=255, unique=True, index=True)
    # Feature 1.1 (Granular RBAC, Task 1.1.1): per-area permissions, least
    # privilege by default. These are our own data, deliberately NOT sourced
    # from the Clerk JWT -- an Admin grants them via the Admin console and the
    # effect is immediate on the next request without a re-login.
    # A user with all three False is the original design's "Viewer": Dashboard
    # + Chat + Help only. Admin implies all three (resolved in
    # dependencies.get_tenant_context, not stored redundantly here).
    can_train: bool = Field(default=False, nullable=False)
    can_audit: bool = Field(default=False, nullable=False)
    can_load: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime | None = Field(default=None)

class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    invoice_id: UUID = Field(index=True)
    actor_user_id: UUID = Field(foreign_key="users.id")
    actor_role: str = Field(max_length=50)
    action: str = Field(max_length=255)
    details: dict | None = Field(default=None, sa_column=Column(JSON_VARIANT))
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExtractionTemplate(SQLModel, table=True):
    __tablename__ = "extraction_templates"
    # Two scopes share this table (feature_10_trainer.md):
    #   - vendor_name IS NULL  -> the tenant's single "Global" template (scope #1)
    #   - vendor_name set       -> a per-vendor template (scope #2 / #3)
    # Feature 7.1 (Outbound Auditor) Task 7.1.1 adds flow_direction so an
    # outbound Global rule (vendor_name IS NULL, flow_direction="OUTBOUND")
    # can coexist with the tenant's existing inbound Global rule without
    # colliding on the old tenant-only partial unique index -- both
    # constraints below now include flow_direction for that reason.
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "vendor_name", "flow_direction", name="uq_extraction_templates_tenant_vendor"),
        sa.Index(
            "uq_extraction_templates_tenant_global",
            "tenant_id",
            "flow_direction",
            unique=True,
            postgresql_where=sa.text("vendor_name IS NULL"),
            sqlite_where=sa.text("vendor_name IS NULL"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    vendor_name: str | None = Field(default=None, max_length=255)
    flow_direction: str = Field(default="INBOUND", max_length=20)
    rules: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    version: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExtractionTemplateVersion(SQLModel, table=True):
    """Append-only history of every committed/rolled-back ExtractionTemplate change.

    Lets the Trainer's Rule History drawer show what changed and revert it
    (feature_10_trainer.md Task 10.10). One row is written on each commit and each
    rollback, capturing the rules value at that version plus who/when.
    """
    __tablename__ = "extraction_template_versions"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    template_id: UUID = Field(index=True, foreign_key="extraction_templates.id")
    tenant_id: UUID = Field(index=True)
    vendor_name: str | None = Field(default=None, max_length=255)
    version: int
    rules: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    changed_by: str | None = Field(default=None, max_length=255)
    changed_at: datetime = Field(default_factory=datetime.utcnow)


class TenantChatSettings(SQLModel, table=True):
    """Feature 18 (Gap 230): the tenant's Chat response style, in its own table.

    Replaces the storage location Gap 221 originally shipped: the style dict used
    to live inside the Global INBOUND `ExtractionTemplate` row's
    `rules["chat_style"]`. That was a reasonable place for it when the Global row
    was the natural home for tenant-wide Trainer state -- but Feature 18 removes
    Global-scope rule *creation* from the Trainer, so the Global row is no longer
    something a user ever opens or edits, and hanging live chat configuration off
    a row nobody visits (and which is otherwise about *extraction* rules, not
    chat behaviour) is exactly the kind of coupling this redesign exists to undo.

    The migration copies existing `rules["chat_style"]` dicts across and
    deliberately **leaves the source key in place** -- it is tenant data, and a
    non-destructive move means a rollback of this deploy loses nothing.

    Shaped after `TenantAutopilotConfig` (one row per tenant, enforced by a
    UNIQUE on `tenant_id`). It deliberately does NOT carry a `tenant.id` foreign
    key, matching the closer analogues for tenant-scoped config that this table
    actually sits alongside (`ExtractionTemplate`, `WebhookSubscription`,
    `ChatSession`), all of which use a plain indexed `tenant_id`.
    """
    __tablename__ = "tenant_chat_settings"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_tenant_chat_settings_tenant"),
        sa.Index("idx_tenant_chat_settings_tenant", "tenant_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    # 'brief' | 'balanced' | 'detailed'
    response_length: str = Field(default="balanced", max_length=20)
    # 'formal' | 'conversational' | 'technical'
    tone: str = Field(default="conversational", max_length=20)
    custom_instructions: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantChatRule(SQLModel, table=True):
    """Feature 18 (Gap 232): one committed chat-behaviour rule.

    Structurally separate from `ExtractionTemplate.rules["constraints"]`, and
    that separation is the point rather than an implementation detail: a chat
    rule is about how the *answering agent* should reason, filter or scope a
    question ("also search line-item descriptions", "invoices received means
    INBOUND"). It has nothing to teach the extraction pipeline, and letting the
    two share a table is how "the trainer taught chat something weird" and "the
    trainer taught extraction something weird" became the same, undiagnosable
    class of bug. Nothing in this table is ever read by the extraction agent, and
    nothing in `ExtractionTemplate` is ever read by `_chat_rules_block()`.

    `category` is one of a fixed vocabulary (see
    `services/chat_rules.py::CHAT_RULE_CATEGORIES`) -- structured pick, not free
    text. `pattern` is the specific thing the category applies to (e.g. the term
    that should have been included). `context_text` is optional secondary colour
    from the user, never the primary input.
    """
    __tablename__ = "tenant_chat_rules"
    __table_args__ = (
        sa.Index("idx_tenant_chat_rules_tenant_enabled", "tenant_id", "enabled"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    category: str = Field(max_length=64)
    pattern: str = Field(default="", max_length=500)
    context_text: str = Field(default="", max_length=2000)
    created_by: str | None = Field(default=None, max_length=255)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantEmailSender(SQLModel, table=True):
    """Authorized tenant-owned emails that may submit PDFs to the global app mailbox.

    One platform mailbox (EMAIL_APP_ADDRESS). Webhook resolves tenant_id and
    direction from From → this row (`email_set` inbound|outbound). `email` is
    globally unique so one sender maps to exactly one tenant/set.
    """
    __tablename__ = "tenant_email_senders"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_tenant_email_senders_email"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenant.id")
    email: str = Field(index=True, max_length=255)
    email_set: str = Field(default="inbound", max_length=20, index=True)  # inbound | outbound
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DroppedInboundEmail(SQLModel, table=True):
    """Gap 124 item 6: one inbound-mail POST that never became an invoice.

    Every rejection path in `routers/email_ingestion.py::email_mailintegration_webhook`
    used to end at a `logger.warning` and a 200 with `status: dropped` — the mail
    vanished with no trace anyone outside the container logs could see, which is
    the worst possible failure mode for a channel whose whole job is unattended
    ingestion. Each of those paths now also writes a row here, and
    `routers/admin.py::list_dropped_emails` renders them in the Admin console.

    `tenant_id` is nullable on purpose: the mailbox is platform-wide, so the
    tenant is only known once the From address has been matched against
    `tenant_email_senders`. A request rejected *before* that point (bad shared
    secret, oversized body, unparseable multipart, unregistered sender) belongs
    to no tenant at all. `sender_domain` is stored alongside so those
    unattributed rows can still be surfaced to the one tenant they plausibly
    concern — see list_dropped_emails for that visibility rule.

    Deliberately not an `AuditLog`: that table requires a real
    `actor_user_id` FK (a human who acted on an invoice) and an `invoice_id`.
    A dropped mail has neither — there is no actor and, by definition, no
    invoice.
    """
    __tablename__ = "dropped_inbound_emails"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    # One of services.inbound_mail_security.DROP_REASONS.
    reason: str = Field(max_length=64, index=True)
    detail: str = Field(default="", max_length=1024)
    from_email: str | None = Field(default=None, max_length=320, index=True)
    to_email: str | None = Field(default=None, max_length=320)
    # Lowercased domain half of from_email, denormalised so the Admin list can
    # filter unattributed rows without re-parsing every address in SQL.
    sender_domain: str | None = Field(default=None, max_length=255, index=True)
    filename: str | None = Field(default=None, max_length=512)
    # Declared Content-Length of the POST, or the measured attachment byte
    # total when the request was rejected after parsing. NULL when neither is
    # known (e.g. a malformed request with no Content-Length header).
    content_length: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class WebhookSubscription(SQLModel, table=True):
    """Feature 15 (Task 15.1): a tenant-registered HTTP endpoint that receives
    real-time invoice status-change notifications instead of polling the API.

    `secret` is generated server-side on create and used to HMAC-sign every
    delivery (`X-Webhook-Signature`) -- never returned by the API after
    creation. `subscribed_events` is a subset of: invoice.completed,
    invoice.audit_required, invoice.paid, invoice.rejected,
    outbound_invoice.sent, outbound_invoice.overdue, outbound_invoice.paid.
    `consecutive_failures` drives Task 15.5's auto-disable-after-10 rule;
    reset to 0 on any successful delivery.

    Gap 194: failure tracking is now counted per *event type* in
    `event_failure_counts` ({event_type: consecutive failures}), not as one
    flat counter. `consecutive_failures` is kept as the denormalised
    max(event_failure_counts.values()) so the existing settings-page health
    warning and the public API shape are unchanged, but the auto-disable
    decision reads the per-event map -- see
    services/webhooks.record_delivery_result().
    """
    __tablename__ = "webhook_subscriptions"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    target_url: str = Field(max_length=2048)
    secret: str = Field(max_length=255)
    subscribed_events: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    enabled: bool = Field(default=True)
    consecutive_failures: int = Field(default=0)
    event_failure_counts: dict = Field(default_factory=dict, sa_column=Column(JSON_VARIANT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookDeliveryLog(SQLModel, table=True):
    """Gap 194: one row per completed delivery *attempt series* (the 3-attempt
    retry sequence in services/webhooks._deliver_with_retry counts as one row,
    with `attempts` recording how many HTTP calls it took).

    Before this table existed there was no way, from inside the product, to
    answer "did this event actually fire?" -- delivery errors are swallowed by
    design so an invoice operation never fails because a subscriber is down,
    which meant a completely broken fan-out looked identical to a clean one.

    `error` is a short diagnostic string (transport error text, or the HTTP
    status line for a non-2xx). Never contains the payload or the signing
    secret. Rows are tenant-scoped so the settings UI can read them under the
    normal tenant context.
    """
    __tablename__ = "webhook_delivery_logs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    subscription_id: UUID = Field(index=True)
    event_type: str = Field(max_length=100)
    success: bool = Field(default=False)
    status_code: int | None = Field(default=None)
    attempts: int = Field(default=0)
    duration_ms: int | None = Field(default=None)
    error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# Feature 13: Tenant Autopilot — Ingestion & Scheduled Sync
# Stores per-tenant cloud folder sync configuration. One config row per tenant
# (enforced via UNIQUE on tenant_id). Supports Google Drive and Salesforce as
# source types. trigger_mode is 'interval' (minutes) or 'cron' (cron expression).
# flow_direction mirrors Invoice.flow_direction: INBOUND (AP) or OUTBOUND (AR).
class TenantAutopilotConfig(SQLModel, table=True):
    __tablename__ = "tenant_autopilot_configs"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_autopilot_config_tenant"),
        sa.Index("idx_autopilot_config_tenant", "tenant_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id")
    # 'gdrive' | 'salesforce'
    source_type: str = Field(max_length=50)
    # Google Drive Folder ID or Salesforce Directory ID
    source_ref: str = Field(max_length=1024)
    # 'INBOUND' (AP — invoices coming in) | 'OUTBOUND' (AR — invoices going out)
    flow_direction: str = Field(default="INBOUND", max_length=10)
    # 'interval' (run every N minutes) | 'cron' (cron expression e.g. '0 * * * *')
    trigger_mode: str = Field(max_length=20)
    # cron expression string OR interval in minutes as a string (e.g. '60')
    trigger_value: str = Field(max_length=100)
    # array of email strings to notify on sync completion
    notify_emails: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # if True, sync notification emails include a manual audit approval link
    send_approval_links: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Feature 13: Tenant Autopilot — Deduplication Ledger
# One row per file processed (or attempted) by Autopilot — both scheduled and
# manual "Sync Now" runs. Two-layer deduplication:
#   Layer 1: source_file_id match (same file seen before by ID)
#   Layer 2: content_hash match (same PDF bytes, even if renamed/moved)
# status values: 'SUCCESS' | 'SKIPPED_DUPLICATE' | 'FAILED'
class TenantAutopilotLog(SQLModel, table=True):
    __tablename__ = "tenant_autopilot_logs"
    __table_args__ = (
        # Composite index: dedup layer 1 lookup (tenant + file ID)
        sa.Index("idx_autopilot_log_tenant_file", "tenant_id", "source_file_id"),
        # Index for dedup layer 2 lookup (content hash across tenant)
        sa.Index("idx_autopilot_log_hash", "content_hash"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id", index=True)
    # 'gdrive' | 'salesforce' | 'manual' (for manually triggered syncs)
    source_type: str = Field(max_length=50)
    # Google Drive fileId or Salesforce record ID
    source_file_id: str = Field(max_length=255)
    # SHA-256 hash of raw document bytes — reuses email attachment dedup logic
    content_hash: str = Field(max_length=64)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    # 'SUCCESS' | 'SKIPPED_DUPLICATE' | 'FAILED'
    status: str = Field(max_length=50)
    # populated only on FAILED rows — stores the exception message
    error_detail: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Feature 23 (AI Control Tower) — Phase 3: golden-set evaluation results
# ---------------------------------------------------------------------------

class AgentEvalRun(SQLModel, table=True):
    """One graded golden-set question, for one agent/path, at one point in time.

    Phase 1 answers "what did this call cost"; this table answers "was the answer
    any good", and — because every row is timestamped — "is it getting worse".
    `ChatFeedback` (Gap 54) only records what a user happened to vote on; this is
    the same fixed question set re-asked on a schedule, which is what makes a
    quality *trend* readable rather than a shifting sample.

    `agent_name` uses the same vocabulary as Phase 1's `llm_agent_call` events
    (`chat.*`, `sage.*`, `extraction.*`), so cost telemetry and quality rows join
    on one name. Phase 3's own runs add two path-level names that identify a whole
    turn rather than a single call site: `chat.default_path` (`run_query_agent()`)
    and `sage.agentic_path` (`run_agentic_sage()`).

    The `pass` column is spelled that way in SQL deliberately (it is not a reserved
    word in Postgres or SQLite) but `pass` is a Python keyword, so the attribute is
    `passed` and the column name is pinned via `sa_column`.

    **Two populations live in this table since Gap 304 half (2) (2026-08-24)**, and
    `run_source` is the only thing that tells them apart:

      * `golden` — one graded question from the fixed bank, written by
        `scripts/run_agent_eval.py`. Carries its own `question`/`actual_answer`
        text, because a golden case's text is test data the repo owns.
      * `production` — one real end-user chat turn, scored by
        `services/online_quality_judge.py`. Carries **no question or answer text
        at all**: it is scores plus `message_id`, which points at the
        `chatmessage` row that already holds the text. Duplicating a customer's
        question into an analytics table is a second copy of the same personal
        data with its own retention story, and the founder's decision was that
        this table never gets one.

    That is why `question`/`actual_answer` became nullable and why the
    `ck_agent_eval_run_text_or_message` CHECK exists: nullable alone would have
    quietly allowed a golden row with no text, which is a corrupt row. The check
    keeps the golden invariant ("a bank row carries its text") while allowing the
    production shape ("a live row carries a pointer instead").

    Every consumer that trends the golden bank must filter on `run_source`, or it
    blends two populations that are not comparable — production rows can never
    have `accuracy_score`/`context_score` (both need a reference answer) and their
    `pass` is decided on fewer dimensions. See
    `services/ops_digest_collect.py::_eval_window_stats`.
    """
    __tablename__ = "agent_eval_run"
    __table_args__ = (
        # The two questions this table exists to answer, both of them a scan by
        # time: "how did agent X trend" and "what happened on day D".
        sa.Index("idx_agent_eval_run_agent_time", "agent_name", "run_at"),
        sa.Index("idx_agent_eval_run_tenant_time", "tenant_id", "run_at"),
        # Gap 304 half (2): every consumer of this table now has to say which
        # population it means, and the ops digest asks for exactly this pair
        # (one source, one time window) twice per run.
        sa.Index("idx_agent_eval_run_source_time", "run_source", "run_at"),
        # A golden row without its text is a corrupt row; a production row with
        # text is a privacy regression. One constraint, both directions.
        sa.CheckConstraint(
            "message_id IS NOT NULL OR (question IS NOT NULL AND actual_answer IS NOT NULL)",
            name="ck_agent_eval_run_text_or_message",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_name: str = Field(max_length=100, index=True)
    run_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    #: Which population this row belongs to — `golden` or `production` (Gap 304
    #: half (2)). Defaults to `golden` so every pre-existing row and every
    #: existing writer keeps its meaning without a data migration; only the
    #: online judge ever writes `production`. Deliberately a plain string rather
    #: than an enum, matching `telemetry.RUN_SOURCE_*` (which also has a
    #: `predeploy` value; the DB only needs the population, not the schedule).
    run_source: str = Field(
        default="golden",
        max_length=20,
        sa_column=sa.Column(
            "run_source", sa.String(length=20), nullable=False, server_default="golden", index=True
        ),
    )

    #: The `chatmessage.id` this score belongs to, on production rows only.
    #: NULL on every golden row (a bank case is not a chat message). No FK on
    #: purpose, matching this table's own `tenant_id`: the score is a
    #: measurement that must survive its subject being deleted, and a cascade
    #: from `chatmessage` would silently rewrite quality history when a user
    #: deletes a thread.
    message_id: UUID | None = Field(default=None, index=True)

    # Nullable since Gap 304 half (2) — production rows carry `message_id`
    # instead. See the class docstring and the CHECK above.
    question: str | None = Field(default=None)
    # NULL where the golden case has no single reference answer to compare
    # against (a clarification-shaped case, a greeting). Accuracy is then not
    # scored at all rather than scored against a guess.
    expected_answer: str | None = Field(default=None)
    # Nullable since Gap 304 half (2), same reason as `question` above.
    actual_answer: str | None = Field(default=None)

    # NOT the same predicate on both populations, and a chart that compares the
    # two pass rates without saying so is wrong: a `golden` row's pass is decided
    # over faithfulness + relevance + accuracy, a `production` row's over
    # faithfulness + relevance only, because accuracy needs a reference answer
    # that live traffic does not have. Both come from the same `decide_pass()`,
    # which only grades the dimensions that produced a number -- the difference
    # is in the inputs, not the rule. Filter by `run_source` before averaging.
    passed: bool = Field(
        default=False,
        sa_column=sa.Column("pass", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # All three are nullable on purpose: a judge that could not be reached, or a
    # case with no reference answer, must leave the score absent rather than
    # record a 0.0 that reads as "scored, and terrible".
    faithfulness_score: float | None = Field(default=None)
    relevance_score: float | None = Field(default=None)
    accuracy_score: float | None = Field(default=None)

    # Component-level scores (added 2026-08-21, migration `c4a91e77b208`).
    # Feature 23's "component-level scoring, not one blended number": the three
    # above say *that* an answer was bad, these three say *which stage* to fix.
    # Same nullable-means-not-scored contract, and deliberately NOT averaged into
    # anything -- the workbook plots three separate trend lines, because an
    # average of a retrieval score and a tax-reasoning score is not a quantity.
    #
    #   context_score       deterministic: fetched invoice ids vs. the golden
    #                       case's known-correct set (F1). No LLM judge.
    #   orchestration_score mechanical: figures in the answer that trace to a
    #                       fetched field or an arithmetic combination of them,
    #                       over total figures. No LLM judge.
    #   persona_score       LLM-judged domain reasoning (tax components, RCM,
    #                       status semantics, category judgement). NULL on every
    #                       turn that required no domain judgement, which is most
    #                       of them -- read the denominator before the level.
    context_score: float | None = Field(default=None)
    orchestration_score: float | None = Field(default=None)
    persona_score: float | None = Field(default=None)

    # Wall-clock for the whole turn, and how many real model round-trips it took.
    # `llm_call_count` is counted from Phase 1's own `llm_agent_call` events, not
    # estimated — it is the number Feature 21's cost/latency question turns on.
    latency_ms: float = Field(default=0.0)
    llm_call_count: int = Field(default=0)

    tenant_id: UUID = Field(index=True)
    # Free text: the case id, the route/tools taken, and any reason a score is
    # absent. Deliberately not a structured column set — this is for a human
    # reading one row, the structured signal is the scores above.
    notes: str | None = Field(default=None)


class RoleMapper:
    """
    Enterprise Role & Permission Engine (Gap 108).
    Maps any 3rd-party IDP string to internal application roles and default permission flags.
    """
    ROLE_ALIAS_MAP = {
        "org:admin": "Admin",
        "admin": "Admin",
        "org_admin": "Admin",
        "org:trainer": "Trainer",
        "trainer": "Trainer",
        "org_trainer": "Trainer",
        "org:auditor": "Auditor",
        "auditor": "Auditor",
        "org:member": "Viewer",
        "member": "Viewer",
        "viewer": "Viewer",
    }

    ROLE_PERMISSION_DEFAULTS = {
        "Admin":   {"can_train": True,  "can_audit": True,  "can_load": True},
        "Trainer": {"can_train": True,  "can_audit": False, "can_load": False},
        "Auditor": {"can_train": False, "can_audit": True,  "can_load": False},
        "Viewer":  {"can_train": False, "can_audit": False, "can_load": False},
    }

    @classmethod
    def normalize_role(cls, raw_role: str | None) -> str:
        """Translates raw strings (e.g. 'org:trainer', 'trainer') into internal DB roles ('Trainer')."""
        if not raw_role:
            return "Viewer"
        clean_key = str(raw_role).strip().lower()
        return cls.ROLE_ALIAS_MAP.get(clean_key, raw_role.title() if raw_role else "Viewer")

    @classmethod
    def resolve_permissions(cls, role: str, user: Any = None) -> tuple[bool, bool, bool]:
        """Resolves (can_train, can_audit, can_load) for any role."""
        if role == "Admin":
            return True, True, True

        defaults = cls.ROLE_PERMISSION_DEFAULTS.get(role, cls.ROLE_PERMISSION_DEFAULTS["Viewer"])
        can_train = getattr(user, "can_train", None) if user else None
        can_audit = getattr(user, "can_audit", None) if user else None
        can_load  = getattr(user, "can_load", None)  if user else None

        res_train = can_train if can_train is not None else defaults["can_train"]
        res_audit = can_audit if can_audit is not None else defaults["can_audit"]
        res_load  = can_load  if can_load  is not None  else defaults["can_load"]

        return bool(res_train), bool(res_audit), bool(res_load)

# ---------------------------------------------------------------------------
# Feature 19 / Feature Website 5: Support Ticket & Inquiry Engine
# ---------------------------------------------------------------------------

class SupportTicket(SQLModel, table=True):
    """
    Persists all inbound support interactions:
      - WEBSITE_CONTACT  : public /contact form submissions from invoice-website
      - HELP_CHATBOT     : AI-escalated tickets from invoice-fe Help Center
      - DIRECT_TICKET    : manually raised tickets from Help Center chat header

    ticket_number is the human-visible reference:
      - INQ-YYYY-XXXXXXXX  for website contact inquiries (source=WEBSITE_CONTACT)
      - TICK-YYYY-XXXXXXXX for app support tickets (source=HELP_CHATBOT / DIRECT_TICKET)

    The suffix is 8 uppercase hex characters from `secrets.token_hex(4)` -- see
    routers/support.py::_generate_ticket_number. Gap 251: this replaced a
    4-digit `randint(1000, 9999)` suffix, whose 9,000 values per year per prefix
    could be exhausted by a few thousand unauthenticated POSTs, after which
    every new ticket failed. The current keyspace is 4.29 billion per year per
    prefix, and exhaustion now surfaces as a 503 rather than an uncaught 500.
    """
    __tablename__ = "supportticket"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    ticket_number: str = Field(max_length=32, unique=True, index=True)

    # Tenant + user — nullable because website contact submissions are anonymous
    tenant_id: UUID | None = Field(default=None, nullable=True, index=True)
    user_id: UUID | None = Field(default=None, nullable=True)
    user_email: str = Field(max_length=255, index=True)
    user_name: str | None = Field(default=None, max_length=255)

    # Submission source & classification
    source: str = Field(default="WEBSITE_CONTACT", max_length=32)  # WEBSITE_CONTACT | HELP_CHATBOT | DIRECT_TICKET
    category: str = Field(default="GENERAL", max_length=64)         # SALES | TECHNICAL_SUPPORT | BILLING | PARTNERSHIP | GENERAL
    priority: str = Field(default="NORMAL", max_length=32)          # LOW | NORMAL | URGENT

    # Content
    subject: str = Field(max_length=255)
    description: str
    company_name: str | None = Field(default=None, max_length=255)

    # For chatbot-escalated tickets — the full conversation transcript is attached
    chat_transcript: list = Field(default=[], sa_column=Column(JSON_VARIANT))

    # Lifecycle
    status: str = Field(default="OPEN", max_length=32)  # OPEN | IN_PROGRESS | RESOLVED | CLOSED
    admin_notes: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
