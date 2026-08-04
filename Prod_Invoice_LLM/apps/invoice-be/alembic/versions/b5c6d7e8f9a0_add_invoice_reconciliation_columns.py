"""add last_enqueued_at / processing_attempts to invoice (FE Gaps 81+84)

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-04

FE Gap 81 (worker never picks the message up -> invoice frozen at its upload
status forever) needs a reconciliation sweep that can re-enqueue a stalled
invoice. Two things that sweep cannot do without state on the row:

* Measure staleness. `created_at` is wrong to measure from once an invoice has
  been re-enqueued -- it would stay "overdue" forever and be re-enqueued on
  every single pass. `last_enqueued_at` is the real clock: when a message was
  last put on the queue for this invoice.
* Stop. A file the worker genuinely cannot process (Gap 84's corrupted PDF)
  would otherwise be requeued indefinitely. `processing_attempts` bounds it,
  after which the sweep marks the invoice FAILED like any other terminal error.

`last_enqueued_at` is nullable with no backfill: NULL means "no re-enqueue has
happened", and the sweep falls back to `created_at` for those rows -- which is
exactly right for every invoice uploaded before this migration, including the
still-stuck 2026-07-29 one this work has to recover.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice", sa.Column("last_enqueued_at", sa.DateTime(), nullable=True))
    op.add_column(
        "invoice",
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("invoice", "processing_attempts")
    op.drop_column("invoice", "last_enqueued_at")
