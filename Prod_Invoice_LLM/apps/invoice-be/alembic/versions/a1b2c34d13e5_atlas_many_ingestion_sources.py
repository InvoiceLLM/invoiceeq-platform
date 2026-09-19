"""Feature 34 (ATLAS) task 34.13 — a tenant may have many ingestion sources (D43).

`uq_autopilot_config_tenant` made `tenant_autopilot_configs` one row per tenant,
which is one ingestion source per tenant. D13's promise ("most invoices arrive by
themselves") was therefore unreachable for a customer who receives in a Drive
folder *and* a shared mailbox, and ATLAS's Loader lines — which are per ingestion
source (§2.3, D22) — had nothing to be per.

Three changes, all additive in the dev sense (no data is moved, nothing is
back-filled, no column is dropped):

1. **Drop `uq_autopilot_config_tenant`.** Many configs per tenant.
2. **`tenant_autopilot_logs.source_config_id`** — which configured source wrote
   this row. Nullable, because every row written before this column existed
   belongs to the tenant's only source and is not worth guessing at; NULL means
   "written before sources were distinguishable", never "no source". Indexed
   with `tenant_id` because every read is already tenant-scoped (the same
   reasoning as `idx_autopilot_log_tenant_batch`, Gap 427).
3. **`uq_autopilot_config_tenant_source`** on (tenant_id, source_type,
   source_ref) — the constraint that replaces the dropped one. Registering the
   same Drive folder twice would double-ingest every file in it, and the old
   UNIQUE was accidentally preventing that. No existing row can violate it: the
   constraint being dropped guaranteed at most one row per tenant.

`down_revision` is `e6f7a8b9c0d1`, confirmed as the single head by
`alembic heads` immediately before writing this file.

Revision ID: a1b2c34d13e5
Revises: e6f7a8b9c0d1
Create Date: 2026-09-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c34d13e5"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Many ingestion sources per tenant (D43).
    op.drop_constraint(
        "uq_autopilot_config_tenant", "tenant_autopilot_configs", type_="unique"
    )

    # 2. Ingestion paths carry a source id.
    op.add_column(
        "tenant_autopilot_logs",
        sa.Column("source_config_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "idx_autopilot_log_tenant_source",
        "tenant_autopilot_logs",
        ["tenant_id", "source_config_id"],
    )

    # 3. The same folder may not be registered twice.
    op.create_unique_constraint(
        "uq_autopilot_config_tenant_source",
        "tenant_autopilot_configs",
        ["tenant_id", "source_type", "source_ref"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_autopilot_config_tenant_source", "tenant_autopilot_configs", type_="unique"
    )
    op.drop_index("idx_autopilot_log_tenant_source", table_name="tenant_autopilot_logs")
    op.drop_column("tenant_autopilot_logs", "source_config_id")
    op.create_unique_constraint(
        "uq_autopilot_config_tenant", "tenant_autopilot_configs", ["tenant_id"]
    )
