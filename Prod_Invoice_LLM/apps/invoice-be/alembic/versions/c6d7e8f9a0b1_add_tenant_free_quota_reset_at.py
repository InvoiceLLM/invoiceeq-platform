"""add free_quota_reset_at to tenants (Gap 118: monthly free-tier refill)

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-08-04

Gap 118. `routers/invoices.py` decrements `free_invoices_remaining` on every
free-tier upload and nothing ever put it back, so the free tier advertised as
"50 invoices a month" was really 50 invoices for the lifetime of the account.
Refilling needs a date to refill *from*, and there was none.

Nullable with no server_default, and no backfill, for the same reason Gap 71's
`paid_through` migration (a4b5c6d7e8f9) chose that shape. NULL is meaningful
here: "the cycle clock has not started for this tenant yet." Backfilling every
existing row to `now()` would hand every free tenant an immediate extra 50
invoices on deploy; backfilling to a past date would be inventing a cycle
anniversary we never observed. Instead `refresh_free_quota()` seeds the column
one cycle out the first time it sees the tenant, *without* refilling the
counter -- so an existing tenant keeps whatever balance they have and gets
their first refill one full cycle later.

down_revision is b5c6d7e8f9a0 (add_invoice_reconciliation_columns), the single
head at time of writing -- see be_features_tracker.md Gap 60 for the multi-head
incident this guards against.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("free_quota_reset_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant", "free_quota_reset_at")
