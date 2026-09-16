"""BE Gaps 553 and 559: the two audit-flow indexes are declared in the models exactly as the migration
builds them, and the hot reads they exist for can use them.

The query-plan checks run on in-memory SQLite: they show the index answers the filter and the ORDER BY
without a separate sort. The Postgres EXPLAIN spot check could not run (Docker down; founder chose
code-level closure).
"""
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

import models  # noqa: F401  (registers every table on SQLModel.metadata)

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "c553d559e0a1_audit_flow_indexes.py"


def _migration():
    spec = importlib.util.spec_from_file_location("audit_flow_indexes_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _query_plan(sql: str) -> str:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        return " | ".join(str(row[-1]) for row in connection.execute(text(f"EXPLAIN QUERY PLAN {sql}")))


def test_the_models_declare_the_indexes_the_migration_builds():
    migration = _migration()
    declared = {
        index.name: (table.name, [column.name for column in index.columns])
        for table in SQLModel.metadata.tables.values()
        for index in table.indexes
    }
    for name, table, columns in migration._INDEXES:
        assert declared[name] == (table, list(columns))
    assert migration.down_revision == "a1b2c3f30004"


def test_pattern_detection_reads_the_audit_log_index_without_sorting():
    plan = _query_plan(
        "SELECT details FROM audit_logs WHERE tenant_id = 'tenant' AND action = 'RESOLVE_INVOICE' "
        "AND timestamp >= '2026-01-01' ORDER BY timestamp DESC LIMIT 500"
    )
    assert "ix_audit_logs_tenant_action_timestamp" in plan, plan
    assert "TEMP B-TREE" not in plan, plan


def test_an_invoice_queue_page_reads_the_created_at_index_without_sorting():
    plan = _query_plan(
        "SELECT id FROM invoice WHERE tenant_id = 'tenant' AND flow_direction = 'INBOUND' "
        "AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 10 OFFSET 40"
    )
    assert "ix_invoice_tenant_flow_created_at" in plan, plan
    assert "TEMP B-TREE" not in plan, plan
