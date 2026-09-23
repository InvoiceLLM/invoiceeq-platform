"""add ix_invoice_tenant_completed_at (BE Gap 724)

Revision ID: f3a4b5c6d724
Revises: f3a4b5c6d7e8
Create Date: 2026-09-23

REBASED 2026-09-23. This was written against `e2f3a4b5c720`, and BE Gap 721
landed `f3a4b5c6d7e8` on the same parent while this branch was in flight --
two heads, and `alembic upgrade head` refuses to run with two. Re-parented
onto theirs rather than adding a merge revision: this migration adds one
index and depends on nothing that one touches, so a straight line is both
correct and the thing a reader can follow. Safe to re-parent because this
revision has never been applied to any database; theirs already has been
(its tracker entry records `alembic upgrade head` against dev Postgres),
so it must come first.

WHY. BE Gap 724 adds `completed_since` to `GET /invoices`, the incremental-sync
read an integration polls on a schedule: "everything in this workspace that
finished after <timestamp>". Without an index that query is a full tenant scan
on every poll, and it gets slower as the customer gets bigger -- the worst shape
of performance bug, because it looks fine on the day it ships.

WHY THESE TWO COLUMNS, IN THIS ORDER. `tenant_id` first because every query on
this table is tenant-scoped and that prefix is what keeps one customer's scan
off another's rows. `completed_at` second because it is the range predicate.
Deliberately NOT a third `flow_direction` column: the direction filter is
optional on that endpoint, and a three-column index cannot serve the
`flow_direction=ALL` case -- which is precisely the case a sync uses.

CONCURRENTLY is NOT used. It cannot run inside Alembic's transaction, and this
table is small enough at current volumes that a brief lock at deploy time is the
honest trade. Revisit if `invoice` grows past a few million rows.

`completed_at` is nullable (an invoice still processing has none). Postgres
indexes NULLs, and the query always supplies a lower bound, so those rows are
skipped by the predicate rather than needing a partial index.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d724"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_invoice_tenant_completed_at",
        "invoice",
        ["tenant_id", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_invoice_tenant_completed_at", table_name="invoice")
