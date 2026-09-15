"""BE Gaps 553 and 559: two tenant-led composite indexes for the audit flow's hot reads.

Gap 553 — `audit_logs` had only single-column indexes (tenant_id, invoice_id), while three
reads filter by tenant + action + time: rule-suggestion pattern detection
(`routers/audit.py::_detect_correction_pattern`), the extraction-quality rollup
(`services/extraction_quality_rollup.py`) and the dashboards' AI scores. Postgres scanned
every audit row of the tenant (5,000-row evidence: 2,501 rows removed by filter).
  -> ix_audit_logs_tenant_action_timestamp (tenant_id, action, timestamp)

Gap 559 — the invoice queues (`GET /invoices`, `GET /outbound-dashboard/invoices`) filter
tenant + direction and sort newest first with OFFSET; no index covered `created_at`, so every
page sorted the tenant's rows in memory.
  -> ix_invoice_tenant_flow_created_at (tenant_id, flow_direction, created_at)
  Postgres reads it backwards for ORDER BY created_at DESC, so no DESC column is needed.
  The `X-Total-Count` query still counts every matching row; that is not changed here.

Index-only and add-only: no column and no data change. Both indexes are built CONCURRENTLY so
the live tables keep accepting writes while they build. CREATE INDEX CONCURRENTLY cannot run
inside a transaction, so this runs in Alembic's autocommit block — anything the same upgrade run
did before this revision is committed first. A CONCURRENTLY build that fails leaves an INVALID
index behind, which IF NOT EXISTS would silently keep; upgrade drops such a leftover first, so a
retry rebuilds it.

Founder ruling 2026-09-15 (4B): shipped now instead of waiting for the extraction branch
`be-gaps-523-531-extraction-production-readiness-and-audit-closures`, which adds `a1b2c3f30005`
on the same parent. Whichever of the two merges second must repoint its `down_revision` (or add
a merge revision) so `alembic heads` shows a single head again.

Revision ID: c553d559e0a1
Revises: a1b2c3f30004
Create Date: 2026-09-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "c553d559e0a1"
down_revision: Union[str, None] = "a1b2c3f30004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (index name, table, columns) — `models.py` declares the same two indexes.
_INDEXES = (
    ("ix_audit_logs_tenant_action_timestamp", "audit_logs", ("tenant_id", "action", "timestamp")),
    ("ix_invoice_tenant_flow_created_at", "invoice", ("tenant_id", "flow_direction", "created_at")),
)


def _drop_invalid_leftover(name: str, table: str) -> None:
    if context.is_offline_mode():
        return
    invalid = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
            "WHERE c.relname = :name AND NOT i.indisvalid"
        ),
        {"name": name},
    ).first()
    if invalid:
        op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns in _INDEXES:
            _drop_invalid_leftover(name, table)
            op.create_index(name, table, list(columns), postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, _columns in reversed(_INDEXES):
            op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)
