"""add paid_through to tenants (Gap 71: billing lapse enforcement)

Revision ID: a4b5c6d7e8f9
Revises: f6a7b8c9d0e1
Create Date: 2026-08-04

Gap 71. PayU's classic hash-based API has no subscription/recurring object, so
nothing in the system recorded that a paid plan was paid *for a period* --
`payu_subscription_id` only stores the last txnid. Without a date to compare
against, the 402 gate in dependencies.get_tenant_context() could never fire and
a tenant who stopped paying kept full paid access forever.

Nullable with no server_default on purpose. NULL is a meaningful state here:
"this tenant has never completed a paid checkout." Backfilling existing paid
rows to a date would either lapse them immediately (locking out a real paying
customer on deploy) or grant an arbitrary free extension; is_lapsed() instead
treats NULL as never-lapsed, so existing rows keep working until their next
payment sets a real date.

down_revision taken from the actual single head at time of writing
(f6a7b8c9d0e1, the Feature 1.1 RBAC migration) -- see be_features_tracker.md
Gap 60 for the multi-head incident this guards against.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("paid_through", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant", "paid_through")
