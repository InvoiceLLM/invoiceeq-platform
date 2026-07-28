"""add_tenant_vendor_flow_settings

Revision ID: e1f2a3b4c5d6
Revises: f3a9c7b21d84
Create Date: 2026-07-28

Feature 16: Add three new columns to the 'tenant' table:
  - receive_invoices_enabled (BOOLEAN, NOT NULL, DEFAULT TRUE)
  - send_invoices_enabled    (BOOLEAN, NOT NULL, DEFAULT FALSE)
  - outbound_sender_email    (VARCHAR(255), NULLABLE)

Defaults ensure no behaviour change for existing tenants.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = 'f3a9c7b21d84'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tenant',
        sa.Column('receive_invoices_enabled', sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        'tenant',
        sa.Column('send_invoices_enabled', sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        'tenant',
        sa.Column('outbound_sender_email', sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('tenant', 'outbound_sender_email')
    op.drop_column('tenant', 'send_invoices_enabled')
    op.drop_column('tenant', 'receive_invoices_enabled')
