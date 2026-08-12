"""Add duplicate_of_invoice_id to invoice (Gap 195: webhook duplicate event + reference).

Nullable self-reference to invoice.id, set only on status=DUPLICATE rows
(routers/invoices.py::_ingest_single_file's duplicate branch). Gives webhook
subscribers and any future UI a structured pointer to the original invoice
instead of the prose message previously buried inside sa_alerts.

Revision ID: fe6371baa50d
Revises: 82a8f00b564d
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "fe6371baa50d"
down_revision: Union[str, None] = "82a8f00b564d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice",
        sa.Column("duplicate_of_invoice_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_invoice_duplicate_of_invoice_id"), "invoice", ["duplicate_of_invoice_id"], unique=False
    )
    op.create_foreign_key(
        "fk_invoice_duplicate_of_invoice_id_invoice",
        "invoice",
        "invoice",
        ["duplicate_of_invoice_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_invoice_duplicate_of_invoice_id_invoice", "invoice", type_="foreignkey")
    op.drop_index(op.f("ix_invoice_duplicate_of_invoice_id"), table_name="invoice")
    op.drop_column("invoice", "duplicate_of_invoice_id")
