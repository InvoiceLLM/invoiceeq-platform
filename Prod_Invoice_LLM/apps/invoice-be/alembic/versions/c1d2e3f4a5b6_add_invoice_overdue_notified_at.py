"""Add overdue_notified_at to invoices (Gap 126 overdue webhook sweep).

Nullable with no backfill on purpose: NULL means "the overdue webhook has never
been fired for this invoice". Backfilling a timestamp onto already-overdue rows
would silently suppress the first real notification for every invoice that was
overdue before this shipped; leaving them NULL means the first sweep after
deploy fires once for each of them and then never again.

Branching note: this revision was written off `f9a0b1c2d3e4`, the single head at
the time. Other concurrent workstreams in this repo branched off that same head
in parallel (the dropped-inbound-emails and tenant-api-key migrations), so
`alembic heads` will report several heads until whoever lands last linearizes
them or adds a merge revision. The revision id here is deliberately distinct
from those, so nothing collides on id -- only on parent.

Revision ID: c1d2e3f4a5b6
Revises: f9a0b1c2d3e4
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice",
        sa.Column("overdue_notified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoice", "overdue_notified_at")
