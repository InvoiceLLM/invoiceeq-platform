"""invoice dashboard filter indexes

FE Gap 29: the dashboard/list endpoints filter every query by tenant_id plus
one of status/invoice_date/vendor_name, but only tenant_id had an index.
Adds composite (tenant_id, X) indexes, led by tenant_id since that's always
present, so the planner can actually use them for the common filter shapes.

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6a7
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_invoice_tenant_status", "invoice", ["tenant_id", "status"])
    op.create_index("ix_invoice_tenant_invoice_date", "invoice", ["tenant_id", "invoice_date"])
    op.create_index("ix_invoice_tenant_vendor_name", "invoice", ["tenant_id", "vendor_name"])


def downgrade() -> None:
    op.drop_index("ix_invoice_tenant_vendor_name", table_name="invoice")
    op.drop_index("ix_invoice_tenant_invoice_date", table_name="invoice")
    op.drop_index("ix_invoice_tenant_status", table_name="invoice")
