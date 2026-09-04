"""add run identity columns to tenant_autopilot_logs (batch_id, trigger, source_file_name)

Revision ID: a1b2c3d4e5f7
Revises: dfcfbb60ef1c
Create Date: 2026-09-04

Gap 427. `services/autopilot_sync.py::run_sync()` already minted a per-run
`batch_id` and stamped it on the `Invoice` rows it created, but never on its own
`tenant_autopilot_logs` rows -- so `GET /autopilot/history` had no notion of a
"run" and could only page over individual files, which is what made the FE Sync
History table a wall of raw Drive file IDs.

Three nullable columns, no backfill:
  - `batch_id`   -- which run wrote this row.
  - `trigger`    -- 'manual' (Sync Now) or 'scheduled' (the ACA job).
  - `source_file_name` -- the human-readable name, captured at ingest.

All three are nullable *and stay nullable* because existing rows genuinely
cannot be back-filled: the run a historical row belonged to was never recorded
anywhere, and Drive file names are not recoverable from a fileId we no longer
have a token scoped to. `GET /autopilot/history` collapses every
`batch_id IS NULL` row into one synthetic "before run tracking" entry rather
than inventing batch ids here.

The composite index matches the read path the new endpoint actually uses --
GROUP BY batch_id within one tenant, and "all rows of this batch for this
tenant" for the per-run file drill-down. The two existing indexes on this table
(`idx_autopilot_log_tenant_file`, `idx_autopilot_log_hash`) serve the dedup
lookups and neither one covers this.

down_revision verified against a real `alembic heads` run immediately before
writing this file (single head `dfcfbb60ef1c`), not assumed -- see
be_features_tracker.md Gap 60 for the multi-head incident this guards against.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'dfcfbb60ef1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_autopilot_logs",
        sa.Column("batch_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "tenant_autopilot_logs",
        sa.Column("trigger", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "tenant_autopilot_logs",
        sa.Column("source_file_name", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "idx_autopilot_log_tenant_batch",
        "tenant_autopilot_logs",
        ["tenant_id", "batch_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_autopilot_log_tenant_batch", table_name="tenant_autopilot_logs")
    op.drop_column("tenant_autopilot_logs", "source_file_name")
    op.drop_column("tenant_autopilot_logs", "trigger")
    op.drop_column("tenant_autopilot_logs", "batch_id")
