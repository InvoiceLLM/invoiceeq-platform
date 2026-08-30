"""add sandbox_tenants + widget_tokens (Feature 25 / Gaps 340 & 341)

Revision ID: b1c2d3e4f5a6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-30

Two new tables, one per gap. They are in one revision because they land in one
change and neither depends on the other; splitting them would add a second
un-applied revision to the Azure-dev backlog for no benefit.

`sandbox_tenants` (Gap 340) marks a `Tenant` row as a throwaway-but-real sandbox
workspace reachable by an `inv_test_` key. Row existence IS the marker -- see the
model docstring for why this is a table rather than nullable columns on `tenant`.
`claimed_at IS NULL` is the compare-and-set predicate the claim transaction turns
on, and it is indexed for the global unclaimed-cap count that runs on every
issuance; `expires_at` is indexed for the reaper's sweep.

`widget_tokens` (Gap 341) holds chat-only tokens meant to be embedded in a
customer's own website's client-side code. Deliberately NOT stored in
`tenant.api_key_hash`/`api_key_salt`/`api_key_prefix`: those are
one-key-per-tenant by design, a widget token is a different trust level
entirely, and there can be several per tenant. `token_prefix` is UNIQUE (unlike
`tenant.api_key_prefix`, which is only indexed) because it is the sole lookup
key across all tenants and two rows sharing one would make resolution
ambiguous.

**No backfill and no data migration.** Nothing existing becomes a sandbox tenant
or gains a widget token; both tables start empty, and every predicate in the
feature reads "no row" as "not a sandbox" / "no widget access", which is the
fail-closed answer.

down_revision f0a1b2c3d4e5 confirmed as the single head by an actual
`alembic heads` run, not by reading files (be_features_tracker.md Gap 60 is the
multi-head incident this check exists for).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_VARIANT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "sandbox_tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "claimed_by_clerk_org_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "chat_messages_used", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "issued_from_ip", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_sandbox_tenant"),
    )
    op.create_index("idx_sandbox_tenant_tenant_id", "sandbox_tenants", ["tenant_id"])
    op.create_index("idx_sandbox_tenant_claimed", "sandbox_tenants", ["claimed_at"])
    op.create_index("idx_sandbox_tenant_expires", "sandbox_tenants", ["expires_at"])

    op.create_table(
        "widget_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "token_hash", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "token_salt", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "token_prefix", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column(
            "label",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=False,
            server_default="Chat widget",
        ),
        sa.Column("allowed_origins", _JSON_VARIANT, nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_widget_token_prefix", "widget_tokens", ["token_prefix"], unique=True
    )
    op.create_index("idx_widget_token_tenant", "widget_tokens", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_widget_token_tenant", table_name="widget_tokens")
    op.drop_index("idx_widget_token_prefix", table_name="widget_tokens")
    op.drop_table("widget_tokens")

    op.drop_index("idx_sandbox_tenant_expires", table_name="sandbox_tenants")
    op.drop_index("idx_sandbox_tenant_claimed", table_name="sandbox_tenants")
    op.drop_index("idx_sandbox_tenant_tenant_id", table_name="sandbox_tenants")
    op.drop_table("sandbox_tenants")
