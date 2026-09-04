"""Feature 26 Phase 5.9 (Gap 453): auto_golden_cases.

A thumbs-down is promoted into the evaluation bank automatically. Unique on
message_id so a second thumbs-down on the same reply cannot create a second case.

Revision ID: f6a1b2c3d4e5
Revises: e5f6a1b2c3d4
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, None] = "e5f6a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auto_golden_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reported_answer", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="auto:thumbs_down"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auto_golden_cases_tenant_id", "auto_golden_cases", ["tenant_id"])
    op.create_index("ix_auto_golden_cases_message_id", "auto_golden_cases", ["message_id"], unique=True)
    op.create_index("ix_auto_golden_cases_source", "auto_golden_cases", ["source"])
    op.create_index("ix_auto_golden_cases_active", "auto_golden_cases", ["active"])
    op.create_index("ix_auto_golden_cases_created_at", "auto_golden_cases", ["created_at"])


def downgrade() -> None:
    op.drop_table("auto_golden_cases")
