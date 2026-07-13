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
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    vendor_name: str = Field(max_length=255)
    rules: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


