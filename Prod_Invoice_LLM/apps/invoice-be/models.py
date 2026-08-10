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
    # Feature 16: Service Flow toggles
    receive_invoices_enabled: bool = Field(default=True)   # Inbound (AP) — on by default, preserves existing behaviour
    send_invoices_enabled: bool = Field(default=False)     # Outbound (AR) — opt-in, requires pro_combined plan
    outbound_sender_email: str | None = Field(default=None, max_length=255)  # Legacy Gap 125 Reply-To placeholder; Email Setup uses TenantEmailSender sets
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Invoice(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    batch_id: UUID | None = Field(default=None, index=True)
    file_path: str = Field(max_length=1024)
    file_hash: str | None = Field(default=None, index=True, max_length=64)

    vendor_name: str | None = Field(default=None)
    grand_total: float | None = Field(default=None)
    invoice_number: str | None = Field(default=None)
    invoice_date: date | None = Field(default=None)
    due_date: date | None = Field(default=None)
    tax_amount: float | None = Field(default=None)
    po_number: str | None = Field(default=None)
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
    """
    __tablename__ = "webhook_subscriptions"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    target_url: str = Field(max_length=2048)
    secret: str = Field(max_length=255)
    subscribed_events: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    enabled: bool = Field(default=True)
    consecutive_failures: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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



