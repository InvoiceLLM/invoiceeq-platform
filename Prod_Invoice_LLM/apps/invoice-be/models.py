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
    billing_plan: str = Field(default="free", max_length=50)
    free_invoices_remaining: int = Field(default_factory=lambda: settings.DEFAULT_FREE_INVOICES_LIMIT)
    stripe_customer_id: str | None = Field(default=None, max_length=255)
    stripe_subscription_id: str | None = Field(default=None, max_length=255)
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

    # FE Gap 29: dashboard/list filters are always tenant-scoped plus one of
    # status/date/vendor, so composite indexes led by tenant_id (rather than
    # single-column ones) are what the query planner actually uses here.
    __table_args__ = (
        sa.Index("ix_invoice_tenant_status", "tenant_id", "status"),
        sa.Index("ix_invoice_tenant_invoice_date", "tenant_id", "invoice_date"),
        sa.Index("ix_invoice_tenant_vendor_name", "tenant_id", "vendor_name"),
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
    # A composite unique keeps one row per (tenant, vendor); a partial unique index
    # keeps at most one Global (NULL-vendor) row per tenant, since SQL treats NULLs
    # as distinct and would otherwise allow many.
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "vendor_name", name="uq_extraction_templates_tenant_vendor"),
        sa.Index(
            "uq_extraction_templates_tenant_global",
            "tenant_id",
            unique=True,
            postgresql_where=sa.text("vendor_name IS NULL"),
            sqlite_where=sa.text("vendor_name IS NULL"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    vendor_name: str | None = Field(default=None, max_length=255)
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


