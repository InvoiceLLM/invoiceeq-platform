"""rename razorpay columns to payu on tenant

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-31

Payment provider decision, second pass (2026-07-31): PayU, not Razorpay --
Razorpay's signup also turned out to gate basic account creation behind PAN
(even for test mode), unlike PayU which ships public sandbox test
credentials usable with zero account, and whose real Merchant Key/Salt were
verified working end-to-end against PayU's live test environment same day.
Feature 11 (routers/billing.py) was never built under the Razorpay name
either, so -- same as the Stripe->Razorpay rename before it -- this is a
pure column rename, no data migration needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('tenant', 'razorpay_customer_id', new_column_name='payu_customer_id')
    op.alter_column('tenant', 'razorpay_subscription_id', new_column_name='payu_subscription_id')


def downgrade() -> None:
    op.alter_column('tenant', 'payu_customer_id', new_column_name='razorpay_customer_id')
    op.alter_column('tenant', 'payu_subscription_id', new_column_name='razorpay_subscription_id')
