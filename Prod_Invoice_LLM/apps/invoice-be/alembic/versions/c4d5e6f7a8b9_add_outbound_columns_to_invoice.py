"""add outbound columns to invoice and extraction_template

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-29

Feature 2.1 (Outbound Invoice Ingestion) Task 2.1.1: flow_direction
distinguishes a vendor's invoice addressed to this tenant (INBOUND, every
existing row's default) from this tenant's own invoice addressed to their
customer (OUTBOUND). customer_name is the AR mirror of vendor_name.
customer_id is reserved for future customer-record linking, unused in v1.

Feature 7.1 (Outbound Auditor) Task 7.1.1, bundled into this same migration
since Feature 2.1's own extract_node wiring needs it immediately: adds
flow_direction to extraction_templates so an outbound Global rule can
coexist with the tenant's inbound Global rule. The existing tenant-only
partial unique index (one Global row per tenant) is replaced with a
tenant+flow_direction version -- every existing row defaults to INBOUND, so
this is a no-op for current data, just makes room for a second, OUTBOUND
Global row per tenant going forward.

Feature 8.1 (Outbound Dashboard) Task 8.1.1, also bundled in: sent_at/paid_at
on Invoice, needed immediately by Feature 2.1's own confirm-send endpoint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Invoice: Task 2.1.1 ---
    op.add_column(
        'invoice',
        sa.Column('flow_direction', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='INBOUND')
    )
    op.add_column(
        'invoice',
        sa.Column('customer_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
    )
    op.add_column(
        'invoice',
        sa.Column('customer_id', sa.Uuid(), nullable=True)
    )
    op.create_index(op.f('ix_invoice_tenant_flow_direction'), 'invoice', ['tenant_id', 'flow_direction'], unique=False)

    # --- Invoice: Task 8.1.1 ---
    op.add_column('invoice', sa.Column('sent_at', sa.DateTime(), nullable=True))
    op.add_column('invoice', sa.Column('paid_at', sa.DateTime(), nullable=True))

    # --- ExtractionTemplate: Task 7.1.1 ---
    op.add_column(
        'extraction_templates',
        sa.Column('flow_direction', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='INBOUND')
    )
    op.drop_index('uq_extraction_templates_tenant_global', table_name='extraction_templates')
    op.drop_constraint('uq_extraction_templates_tenant_vendor', 'extraction_templates', type_='unique')
    op.create_unique_constraint(
        'uq_extraction_templates_tenant_vendor', 'extraction_templates', ['tenant_id', 'vendor_name', 'flow_direction']
    )
    op.create_index(
        'uq_extraction_templates_tenant_global', 'extraction_templates', ['tenant_id', 'flow_direction'],
        unique=True, postgresql_where=sa.text('vendor_name IS NULL'), sqlite_where=sa.text('vendor_name IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_extraction_templates_tenant_global', table_name='extraction_templates')
    op.drop_constraint('uq_extraction_templates_tenant_vendor', 'extraction_templates', type_='unique')
    op.create_unique_constraint(
        'uq_extraction_templates_tenant_vendor', 'extraction_templates', ['tenant_id', 'vendor_name']
    )
    op.create_index(
        'uq_extraction_templates_tenant_global', 'extraction_templates', ['tenant_id'],
        unique=True, postgresql_where=sa.text('vendor_name IS NULL'), sqlite_where=sa.text('vendor_name IS NULL'),
    )
    op.drop_column('extraction_templates', 'flow_direction')

    op.drop_column('invoice', 'paid_at')
    op.drop_column('invoice', 'sent_at')

    op.drop_index(op.f('ix_invoice_tenant_flow_direction'), table_name='invoice')
    op.drop_column('invoice', 'customer_id')
    op.drop_column('invoice', 'customer_name')
    op.drop_column('invoice', 'flow_direction')
