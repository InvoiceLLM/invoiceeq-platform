"""Feature 26 Phase 5 (Gaps 447/448): match_policies + document_comparisons.

`match_policies` is one tolerance band per tenant; absent means the zero band,
which is exactly the behaviour that existed before the table. `document_comparisons`
keeps each comparison as a record so a finding is visible outside chat scrollback.

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a0b1c2
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a1b2c3d4"
down_revision: Union[str, None] = "d4e5f6a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "match_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_tolerance_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_tolerance_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("date_tolerance_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_policies_tenant_id", "match_policies", ["tenant_id"], unique=True)

    op.create_table(
        "document_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("payload", _JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "invoice_id", "attachment_id", "session_id", "created_at"):
        op.create_index(f"ix_document_comparisons_{col}", "document_comparisons", [col])


def downgrade() -> None:
    op.drop_table("document_comparisons")
    op.drop_index("ix_match_policies_tenant_id", table_name="match_policies")
    op.drop_table("match_policies")
