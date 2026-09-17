"""BE Gap 674: Add freight_amount column to invoice and documents tables.

Adds nullable freight_amount to:
  - invoice
  - documents

Dev add-only rule compliant: all columns are strictly nullable with no destructive backfills.
Historical rows remain NULL.

Revision ID: b2c3d4e5f674
Revises: a1b2c3d4e684
Create Date: 2026-09-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f674"
down_revision: Union[str, None] = "a1b2c3d4e684"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BE Gap 674: Add freight_amount column to invoice table
    op.add_column("invoice", sa.Column("freight_amount", sa.Float(), nullable=True))

    # BE Gap 674: Add freight_amount column to documents table
    op.add_column("documents", sa.Column("freight_amount", sa.Float(), nullable=True))


def downgrade() -> None:
    # BE Gap 674: Drop freight_amount column from documents table
    op.drop_column("documents", "freight_amount")

    # BE Gap 674: Drop freight_amount column from invoice table
    op.drop_column("invoice", "freight_amount")
