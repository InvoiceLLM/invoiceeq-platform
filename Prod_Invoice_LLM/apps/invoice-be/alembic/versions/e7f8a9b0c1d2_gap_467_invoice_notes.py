"""BE Gap 467: invoice.notes — the printed notes/terms/remarks block.

Gap 463 shipped `BuildRequest.notes` with no column behind it, so the value
lived only in `Invoice.builder_intent`: never read back off the generated PDF,
and never inherited by a clone of a clone. This gap widens
`OutboundInvoiceExtractionSchema` to read the block and adds the column that
stores it, so `notes` behaves like every other printed field on this table.

One nullable column, additive, no backfill: every existing row keeps NULL, which
means "no notes block was read" and never "the invoice printed none".

down_revision `d5e6f7a8b9c0` confirmed as the single head by a real
`ScriptDirectory.get_heads()` call immediately before writing this file
(`alembic.exe` is blocked on this machine; the Python API is used instead) —
same check the two preceding migrations record.

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
Create Date: 2026-09-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice", sa.Column("notes", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("invoice", "notes")
