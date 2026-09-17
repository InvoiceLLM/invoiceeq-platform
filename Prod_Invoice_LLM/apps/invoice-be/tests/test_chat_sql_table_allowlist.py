"""BE Gap 569: the chat SQL route may read only the `invoice` table.

The tenant guard (Gap 414) binds a generated query to the asking tenant's rows but not to a table, so a
query could read any tenant-scoped table — reproduced on in-memory SQLite on 2026-09-15: a webhook signing
secret and audit history came back through `execute_generated_sql`. Every chat SQL prompt describes the
`invoice` table only.
"""
import os
from uuid import uuid4

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import models  # noqa: E402,F401  (registers every table on SQLModel.metadata)
from agents.query_agent import (  # noqa: E402
    _CHAT_SQL_READABLE_TABLES,
    _LINE_ITEM_RULE_POSTGRES,
    _LINE_ITEM_RULE_SQLITE,
    assert_reads_only_allowed_tables,
    execute_generated_sql,
)
from models import AuditLog, Invoice, WebhookSubscription  # noqa: E402

TENANT = "11111111-2222-3333-4444-555555555555"
GUARD = f"tenant_id = '{TENANT}'"


def _rule_6d_example(rule: str) -> str:
    return next(line for line in rule.splitlines() if line.startswith("SELECT ")).replace("{tenant_id}", TENANT)


ALLOWED = [
    pytest.param(f"SELECT id, invoice_number FROM invoice WHERE {GUARD}", "postgresql", id="plain"),
    pytest.param(f"SELECT i.vendor_name FROM public.invoice AS i WHERE i.{GUARD}", "postgresql", id="public-schema-and-alias"),
    pytest.param(
        f"WITH paid AS (SELECT id FROM invoice WHERE {GUARD} AND status = 'PAID') SELECT COUNT(*) FROM paid",
        "postgresql", id="cte-reference",
    ),
    pytest.param(
        f"SELECT id FROM invoice WHERE {GUARD} AND grand_total > (SELECT AVG(grand_total) FROM invoice WHERE {GUARD})",
        "postgresql", id="subquery-on-invoice",
    ),
    pytest.param(_rule_6d_example(_LINE_ITEM_RULE_POSTGRES), "postgresql", id="rule-6d-postgres-lateral"),
    pytest.param(_rule_6d_example(_LINE_ITEM_RULE_SQLITE), "sqlite", id="rule-6d-sqlite-json-each"),
]

REFUSED = [
    pytest.param(f"SELECT target_url, secret FROM webhook_subscriptions WHERE {GUARD}", "postgresql", id="webhook-secret"),
    pytest.param(f"SELECT action, details FROM audit_logs WHERE {GUARD}", "sqlite", id="audit-history"),
    pytest.param(f"SELECT email, role FROM users WHERE {GUARD}", "postgresql", id="users"),
    pytest.param(
        f"SELECT id FROM invoice WHERE {GUARD} AND id IN (SELECT invoice_id FROM audit_logs WHERE {GUARD})",
        "postgresql", id="subquery-into-another-table",
    ),
    pytest.param(
        f"SELECT i.invoice_number, s.title FROM invoice i JOIN chatsession s ON s.tenant_id = i.tenant_id WHERE i.{GUARD}",
        "postgresql", id="join-to-another-table",
    ),
    pytest.param(
        f"WITH leak AS (SELECT secret FROM webhook_subscriptions WHERE {GUARD}) SELECT * FROM leak",
        "postgresql", id="another-table-inside-a-cte",
    ),
    pytest.param(f"SELECT table_name FROM information_schema.tables WHERE {GUARD}", "postgresql", id="information-schema"),
    pytest.param(f"SELECT relname FROM pg_catalog.pg_class WHERE {GUARD}", "postgresql", id="pg-catalog"),
    pytest.param(f"SELECT id FROM other_schema.invoice WHERE {GUARD}", "postgresql", id="invoice-in-another-schema"),
    pytest.param("SELECT this is not sql (((", "postgresql", id="unparseable-fails-closed"),
]


@pytest.mark.parametrize("sql,dialect", ALLOWED)
def test_queries_that_read_only_the_invoice_table_are_allowed(sql, dialect):
    assert_reads_only_allowed_tables(sql, dialect)


@pytest.mark.parametrize("sql,dialect", REFUSED)
def test_queries_that_read_any_other_table_are_refused(sql, dialect):
    with pytest.raises(ValueError) as excinfo:
        assert_reads_only_allowed_tables(sql, dialect)
    assert str(excinfo.value).startswith("Access Denied")
    assert "SELECT" not in str(excinfo.value).upper().replace("ACCESS DENIED", "")


@pytest.mark.parametrize(
    "table_name", sorted(name for name in SQLModel.metadata.tables if name not in _CHAT_SQL_READABLE_TABLES)
)
def test_every_other_table_in_the_schema_is_refused(table_name):
    with pytest.raises(ValueError):
        assert_reads_only_allowed_tables(f"SELECT * FROM {table_name} WHERE {GUARD}", "postgresql")


def test_a_webhook_secret_and_audit_history_cannot_be_read_through_chat_sql():
    """The reproduction: before the fix both queries returned their rows."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    tenant = uuid4()
    predicate = f"(tenant_id = '{tenant}' OR tenant_id = '{tenant.hex}')"
    with Session(engine) as session:
        session.add(WebhookSubscription(tenant_id=tenant, target_url="https://hooks.example/acme", secret="whsec_live_SECRET123"))
        session.add(AuditLog(
            tenant_id=tenant, invoice_id=uuid4(), actor_user_id=uuid4(), actor_role="Admin", action="RESOLVE_INVOICE",
            details={"corrections": {"grand_total": {"old": 100, "new": 120}}},
        ))
        session.add(Invoice(tenant_id=tenant, file_path="mock/invoice.pdf", invoice_number="INV-569", sa_alerts=[]))
        session.commit()

        for sql in (
            f"SELECT target_url, secret FROM webhook_subscriptions WHERE {predicate}",
            f"SELECT action, details FROM audit_logs WHERE {predicate}",
        ):
            with pytest.raises(ValueError) as excinfo:
                execute_generated_sql(sql, str(tenant), session)
            assert str(excinfo.value).startswith("Access Denied")
            assert "whsec" not in str(excinfo.value)

        assert "INV-569" in execute_generated_sql(f"SELECT invoice_number FROM invoice WHERE {predicate}", str(tenant), session)


def test_forbidden_functions_are_refused_gap574():
    """BE Gap 574: pg_sleep, pg_read_file and other administrative functions are rejected."""
    tenant = uuid4()
    for func_sql in [
        f"SELECT pg_sleep(30), id FROM invoice WHERE tenant_id = '{tenant}'",
        f"SELECT pg_read_file('foo'), id FROM invoice WHERE tenant_id = '{tenant}'",
        f"SELECT pg_ls_dir('.'), id FROM invoice WHERE tenant_id = '{tenant}'",
    ]:
        with pytest.raises(ValueError) as excinfo:
            assert_reads_only_allowed_tables(func_sql, "postgresql", tenant_id=str(tenant))
        assert "Access Denied" in str(excinfo.value)

