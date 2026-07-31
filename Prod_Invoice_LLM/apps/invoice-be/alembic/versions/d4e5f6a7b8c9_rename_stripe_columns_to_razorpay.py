"""rename stripe columns to razorpay on tenant

Revision ID: d4e5f6a7b8c9
Revises: a7b8c9d0e1f2
Create Date: 2026-07-31

Payment provider decision (2026-07-31): Razorpay, not Stripe -- Stripe
stopped onboarding new India-domiciled merchants in 2022, and this
platform's billing is India-priced/India-entity. Feature 11
(routers/billing.py) was never built, so these two columns have never
been written to in any real deployment -- pure rename, no data migration
needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('tenant', 'stripe_customer_id', new_column_name='razorpay_customer_id')
    op.alter_column('tenant', 'stripe_subscription_id', new_column_name='razorpay_subscription_id')


def downgrade() -> None:
    op.alter_column('tenant', 'razorpay_customer_id', new_column_name='stripe_customer_id')
    op.alter_column('tenant', 'razorpay_subscription_id', new_column_name='stripe_subscription_id')
