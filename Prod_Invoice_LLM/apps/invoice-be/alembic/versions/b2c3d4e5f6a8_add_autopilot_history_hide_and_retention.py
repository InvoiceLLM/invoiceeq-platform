"""add autopilot history hide + retention (logs.hidden_at, configs.history_retention_days)

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-04

Gap 429. Sync history could neither be hidden by the user nor pruned over time:
`tenant_autopilot_logs` grew forever, and every row a tenant had ever written
was permanently visible in the Sync History screen.

Two columns:
  - `tenant_autopilot_logs.hidden_at`   -- soft delete. NULL = visible.
  - `tenant_autopilot_configs.history_retention_days` -- how long NOISE rows
    (SKIPPED_DUPLICATE / FAILED / NO_NEW_FILES) are kept before
    `prune_autopilot_history()` hard-deletes them. Bounded 7..365 by the API.

Why hiding is a SOFT delete and SUCCESS rows are never pruned: this table is
not only the history read model, it is also
  (a) dedup layer 1 -- `source_file_id` + `status == 'SUCCESS'`,
  (b) dedup layer 2 -- `content_hash` + `status == 'SUCCESS'`, and
  (c) the incremental-poll watermark -- `max(ingested_at)` over SUCCESS rows,
all in `services/autopilot_sync.py::run_sync()`. Hard-deleting a SUCCESS row
would make Autopilot re-download and re-import an invoice it had already
ingested, and re-listing from a reset watermark would do it in bulk. So the
user's "delete this from my history" is a display-level hide, and retention
only ever removes rows that carry no dedup meaning.

`history_retention_days` is added with a server_default of '90' so existing
rows get a value in the same statement (the column is NOT NULL in the model),
and the server_default is then dropped -- the ORM supplies the default for new
rows, and leaving a database-side default behind would let a future insert that
omits the column silently disagree with the model.

down_revision verified against a real `alembic heads` run immediately before
writing this file (single head `a1b2c3d4e5f7`, the Gap 427 migration), not
assumed -- see be_features_tracker.md Gap 60 for the multi-head incident this
guards against.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_autopilot_logs",
        sa.Column("hidden_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tenant_autopilot_configs",
        sa.Column(
            "history_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="90",
        ),
    )
    op.alter_column(
        "tenant_autopilot_configs",
        "history_retention_days",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("tenant_autopilot_configs", "history_retention_days")
    op.drop_column("tenant_autopilot_logs", "hidden_at")
