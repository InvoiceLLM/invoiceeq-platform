"""Add deleted_at to invoice for Gap 192 soft deletes.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_invoice_deleted_at", "invoice", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_invoice_deleted_at", table_name="invoice")
    op.drop_column("invoice", "deleted_at")
