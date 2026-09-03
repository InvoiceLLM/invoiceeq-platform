"""add invoice supersede columns for the resubmission replace workflow

Revision ID: 7565ee1120cb
Revises: dfcfbb60ef1c
Create Date: 2026-09-03

Gap 429 (Phase 2 of the parked-invoice workflow). Adds the three columns the
"replace a NEEDS_RESUBMISSION invoice with a corrected one" flow needs.

Shape deliberately mirrors two existing precedents rather than inventing one:

  * `supersedes_invoice_id` copies `duplicate_of_invoice_id` (Gap 195) --
    a nullable, indexed, self-referencing FK to invoice.id.
  * `superseded_at` copies `deleted_at` (Gap 192) -- a nullable timestamp that
    drives a visibility predicate, so the hot-path check stays a cheap
    `IS NULL` and never a subquery.

DIRECTION, and why it is not symmetric. `superseded_at` lives on the OLD
(replaced) row because that is what every list/aggregate query has to filter
on. `supersedes_invoice_id` lives on the NEW (replacement) row pointing back.
The forward link old -> new is therefore an indexed lookup rather than a
stored column, which keeps the two sides from disagreeing.

WHY NOT REUSE `deleted_at`. Setting `deleted_at` on a superseded invoice would
have made every existing `invoice_not_deleted()` call site exclude it for free,
with no code change. Rejected deliberately: `routers/invoices.py` and
`routers/documents.py` both document an intended restore path ("retains chunks
on soft-delete so a restore path stays possible"), and a restore built later
would silently resurrect superseded invoices into live aggregates. A separate
column keeps "the user deleted this" and "this was replaced" distinguishable.

No data migration: every existing row is un-superseded, which is exactly what
NULL means here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7565ee1120cb"
down_revision: Union[str, None] = "dfcfbb60ef1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice",
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_invoice_superseded_at"), "invoice", ["superseded_at"], unique=False
    )

    op.add_column(
        "invoice",
        sa.Column("supersedes_invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_invoice_supersedes_invoice_id"),
        "invoice",
        ["supersedes_invoice_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_invoice_supersedes_invoice_id",
        "invoice",
        "invoice",
        ["supersedes_invoice_id"],
        ["id"],
    )

    op.add_column(
        "invoice",
        sa.Column("resubmission_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoice", "resubmission_reason")
    op.drop_constraint("fk_invoice_supersedes_invoice_id", "invoice", type_="foreignkey")
    op.drop_index(op.f("ix_invoice_supersedes_invoice_id"), table_name="invoice")
    op.drop_column("invoice", "supersedes_invoice_id")
    op.drop_index(op.f("ix_invoice_superseded_at"), table_name="invoice")
    op.drop_column("invoice", "superseded_at")
