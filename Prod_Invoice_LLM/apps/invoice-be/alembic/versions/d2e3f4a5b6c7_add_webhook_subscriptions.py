"""add webhook_subscriptions table

Revision ID: d2e3f4a5b6c7
Revises: c4d5e6f7a8b9
Create Date: 2026-07-29

Feature 15 (Outbound Webhooks) Task 15.1: WebhookSubscription lets a tenant
register an HTTP endpoint to receive real-time invoice status-change
notifications instead of polling the API.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('target_url', sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False),
        sa.Column('secret', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('subscribed_events', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_subscriptions_tenant_id'), 'webhook_subscriptions', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_subscriptions_tenant_id'), table_name='webhook_subscriptions')
    op.drop_table('webhook_subscriptions')
