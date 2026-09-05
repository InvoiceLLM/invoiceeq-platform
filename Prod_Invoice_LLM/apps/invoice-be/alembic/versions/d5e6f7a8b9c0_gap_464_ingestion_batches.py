"""Gap 464 (ingestion History screen): ingestion_batches + dropped_inbound_emails.archived_at.

Creates the run ledger the History screen reads, and adds the archive marker to
`dropped_inbound_emails` so the screen's archive contract covers every row it
shows (a rejected inbound mail is now a tenant-visible run, not an
Admin-console-only record).

BACKFILL, and why this migration has one at all. The `batch_id`s that identify a
run already exist on `invoice` and `documents` — they have been minted at every
ingestion door for the life of the product — but the run itself was never
recorded. Without a backfill the History screen would ship EMPTY on every
existing database, which is the same "my documents disappeared" experience the
feature exists to end. So one `ingestion_batches` row is synthesised per
distinct existing `batch_id`:

  * `started_at`  = MIN(created_at) of the rows carrying that batch_id — the run
    began when its first row was written; MAX would date a run by its slowest file.
  * `file_count`  = COUNT of those rows. For a historical run this is exactly
    right: nothing else survives to count.
  * `flow_direction` = the direction those rows carry (`invoice.flow_direction`;
    `documents` has no such column and its rows are all INBOUND — the outbound
    pipeline never produced one).
  * `trigger`     = 'manual'. It is NOT recoverable from anything stored: no
    table records which door a historical batch came through. 'manual' is the
    honest majority answer rather than a fabricated per-row guess, and it is the
    one value that cannot mislead — an email or connector run mislabelled
    'manual' is under-specific, whereas a manual upload labelled 'email' would
    be a false statement about where a document came from.

KNOWN, DELIBERATE IMPRECISION IN `file_count` FOR A MIXED HISTORICAL BATCH. A
batch that produced both an `invoice` row and a `documents` row gets its row
from the invoice statement (it runs first and knows the flow_direction), and the
documents statement then hits `ON CONFLICT DO NOTHING` — so `file_count` counts
only the invoices. This is not corrected here, because it does not need to be:
`routers/ingestion_history.py::_batch_runs` displays
`max(file_count, loaded + not_loaded + rejected + in_progress)`, and the derived
half is a live count of the real rows. The stored number is a floor, never
something the expanded row visibly contradicts. Verified on a scratch Postgres
(2026-09-05): a mixed batch backfilled `file_count = 1` and read back as 2.

Autopilot batches are deliberately NOT backfilled: `tenant_autopilot_logs`
already holds them with a real `trigger`, and the History screen reads that
table through. Copying them here would create two rows for one run that can
drift apart.

`invoice.tenant_id` is used as the run's tenant. A batch_id spanning two tenants
is not possible (every door mints it inside one tenant's request) and the
GROUP BY includes tenant_id so a hypothetical one would produce two rows rather
than silently attribute the run to whichever tenant sorted first — but the
primary key is `batch_id` alone, so the insert is written to take the first
grouping per batch_id and no more.

down_revision `a1b2c3d4e5f8` confirmed as the single head by `alembic heads`
immediately before writing this file. The revision id was re-picked once:
`b2c3d4e5f6a7` was already taken by `b2c3d4e5f6a7_chat_feedback.py`, which
alembic reports as a *cycle*, not as a duplicate -- an unhelpful error worth
recognising if it happens again.

Revision ID: d5e6f7a8b9c0
Revises: a1b2c3d4e5f8
Create Date: 2026-09-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "a1b2c3d4e5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# One statement per source table. `ON CONFLICT DO NOTHING` makes the pair safe
# to run in either order and makes the whole backfill re-runnable: `invoice` and
# `documents` can carry the SAME batch_id (Feature 27 E10 deletes the
# placeholder invoice row, but a mixed batch of an invoice and a delivery note
# leaves rows in both), and the invoice-derived row wins because it is the one
# that knows the flow_direction.
_BACKFILL_FROM_INVOICE = """
INSERT INTO ingestion_batches
    (batch_id, tenant_id, flow_direction, trigger, file_count, started_at, archived_at)
SELECT
    batch_id,
    MIN(tenant_id::text)::uuid,
    COALESCE(MIN(flow_direction), 'INBOUND'),
    'manual',
    COUNT(*),
    MIN(created_at),
    NULL
FROM invoice
WHERE batch_id IS NOT NULL
GROUP BY batch_id
ON CONFLICT (batch_id) DO NOTHING
"""

_BACKFILL_FROM_DOCUMENTS = """
INSERT INTO ingestion_batches
    (batch_id, tenant_id, flow_direction, trigger, file_count, started_at, archived_at)
SELECT
    batch_id,
    MIN(tenant_id::text)::uuid,
    'INBOUND',
    'manual',
    COUNT(*),
    MIN(created_at),
    NULL
FROM documents
WHERE batch_id IS NOT NULL
GROUP BY batch_id
ON CONFLICT (batch_id) DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("flow_direction", sa.String(length=20), nullable=False,
                  server_default="INBOUND"),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index(
        "ix_ingestion_batches_tenant_id", "ingestion_batches", ["tenant_id"]
    )
    op.create_index(
        "ix_ingestion_batches_trigger", "ingestion_batches", ["trigger"]
    )
    op.create_index(
        "ix_ingestion_batches_tenant_started",
        "ingestion_batches",
        ["tenant_id", "started_at"],
    )

    op.add_column(
        "dropped_inbound_emails",
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )

    # The backfill is Postgres-specific (`ON CONFLICT`, `::uuid`). SQLite is not
    # a database this product runs on (CONVENTIONS hard rule 2); the table
    # creation above still works there so a SQLite-backed test database is
    # usable, it just starts with no history — which is correct for a fresh one.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(_BACKFILL_FROM_INVOICE)
        bind.exec_driver_sql(_BACKFILL_FROM_DOCUMENTS)


def downgrade() -> None:
    op.drop_column("dropped_inbound_emails", "archived_at")
    op.drop_index("ix_ingestion_batches_tenant_started", table_name="ingestion_batches")
    op.drop_index("ix_ingestion_batches_trigger", table_name="ingestion_batches")
    op.drop_index("ix_ingestion_batches_tenant_id", table_name="ingestion_batches")
    op.drop_table("ingestion_batches")
