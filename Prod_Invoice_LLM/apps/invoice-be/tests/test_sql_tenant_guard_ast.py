"""Gap 414 (C1) — tenant isolation must be decided on the parse tree.

The regex layer (`execute_generated_sql` Safety Check 3) asks only whether the
text `tenant_id = '<tenant>'` appears. `... WHERE tenant_id = '<t>' OR 1=1`
satisfies it and returns every tenant's rows. These tests pin the second layer:
the predicate must actually *bind*.

Hard rule 2: the execution half runs against real Postgres (`DATABASE_URL`), and
skips loudly rather than silently falling back to SQLite.
"""
import os
from uuid import uuid4

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents.query_agent import (  # noqa: E402
    assert_tenant_isolation_on_ast,
    execute_generated_sql,
)

TENANT = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"

BASE = "SELECT id, invoice_number, total_amount FROM invoice"

ACCEPTED = [
    pytest.param(f"{BASE} WHERE tenant_id = '{TENANT}'", id="bare-predicate"),
    pytest.param(
        f"{BASE} WHERE tenant_id = '{TENANT}' AND status = 'PAID'",
        id="and-extra-filter",
    ),
    pytest.param(
        f"{BASE} WHERE status = 'PAID' AND tenant_id = '{TENANT}'",
        id="and-predicate-second",
    ),
    pytest.param(
        f"{BASE} WHERE (tenant_id = '{TENANT}') AND (total_amount > 0 OR status = 'PAID')",
        id="parens-and-nested-or",
    ),
    pytest.param(
        f"{BASE} WHERE tenant_id = '{TENANT}' AND (status = 'PAID' OR status = 'OVERDUE')",
        id="or-inside-and",
    ),
    pytest.param(
        f"SELECT i.invoice_number, item.value ->> 'description' AS d "
        f"FROM invoice i, LATERAL jsonb_array_elements(i.line_items) AS item "
        f"WHERE i.tenant_id = '{TENANT}'",
        id="lateral-jsonb-line-items",
    ),
]

REJECTED = [
    pytest.param(f"{BASE} WHERE tenant_id = '{TENANT}' OR 1=1", id="THE-GAP-or-true"),
    pytest.param(
        f"{BASE} WHERE tenant_id = '{TENANT}' OR total_amount > 0",
        id="or-unguarded-branch",
    ),
    pytest.param(
        f"{BASE} WHERE (tenant_id = '{TENANT}') OR (status = 'PAID')",
        id="or-parenthesised",
    ),
    pytest.param(f"{BASE} WHERE NOT tenant_id = '{TENANT}'", id="negated-guard"),
    pytest.param(f"{BASE}", id="no-where-clause"),
    pytest.param(f"{BASE} WHERE tenant_id = '{OTHER}'", id="other-tenant"),
    pytest.param(
        f"SELECT id FROM invoice WHERE tenant_id = '{TENANT}' AND total_amount > "
        f"(SELECT AVG(total_amount) FROM invoice)",
        id="subquery-without-predicate",
    ),
    pytest.param("SELECT this is not sql (((", id="unparseable-fails-closed"),
]


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
@pytest.mark.parametrize("sql", ACCEPTED)
def test_tenant_bound_sql_is_accepted(sql, dialect):
    assert_tenant_isolation_on_ast(sql, TENANT, dialect)


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
@pytest.mark.parametrize("sql", REJECTED)
def test_sql_the_engine_can_satisfy_without_the_tenant_is_rejected(sql, dialect):
    with pytest.raises(ValueError) as excinfo:
        assert_tenant_isolation_on_ast(sql, TENANT, dialect)
    message = str(excinfo.value)
    assert message.startswith("Access Denied")
    # The rejection must never carry the statement back to the caller.
    assert "SELECT" not in message.upper().replace("ACCESS DENIED", "")


def test_subquery_repeating_the_predicate_is_accepted():
    """The subquery rule rejects an *unguarded* subquery, not every subquery."""
    sql = (
        f"SELECT id FROM invoice WHERE tenant_id = '{TENANT}' AND total_amount > "
        f"(SELECT AVG(total_amount) FROM invoice WHERE tenant_id = '{TENANT}')"
    )
    assert_tenant_isolation_on_ast(sql, TENANT, "postgresql")


def test_cte_reference_is_not_treated_as_an_unguarded_table():
    sql = (
        f"WITH paid AS (SELECT id, total_amount FROM invoice "
        f"WHERE tenant_id = '{TENANT}' AND status = 'PAID') "
        f"SELECT COUNT(*) FROM paid"
    )
    assert_tenant_isolation_on_ast(sql, TENANT, "postgresql")


# --------------------------------------------------------------------------
# Hard rule 2 — the same shapes through execute_generated_sql on real Postgres.
# --------------------------------------------------------------------------

_DB_URL = os.environ.get("DATABASE_URL", "")
_IS_POSTGRES = _DB_URL.startswith("postgresql")

postgres_only = pytest.mark.skipif(
    not _IS_POSTGRES,
    reason=(
        "Hard rule 2: this assertion is only evidence on Postgres. "
        "Set DATABASE_URL to the dev Postgres and re-run."
    ),
)


@pytest.fixture(scope="module")
def pg_session():
    from sqlmodel import Session, create_engine

    engine = create_engine(_DB_URL)
    with Session(engine) as session:
        yield session


@postgres_only
def test_or_true_is_refused_before_it_reaches_postgres(pg_session):
    """The shape that started Gap 414 must not execute at all."""
    tenant = str(uuid4())
    with pytest.raises(ValueError) as excinfo:
        execute_generated_sql(
            f"SELECT id FROM invoice WHERE tenant_id = '{tenant}' OR 1=1",
            tenant,
            pg_session,
        )
    assert str(excinfo.value).startswith("Access Denied")


@postgres_only
def test_a_tenant_bound_query_still_executes_on_postgres(pg_session):
    """Regression witness: the new layer does not reject correct SQL."""
    tenant = str(uuid4())
    out = execute_generated_sql(
        f"SELECT id, invoice_number FROM invoice WHERE tenant_id = '{tenant}' LIMIT 5",
        tenant,
        pg_session,
    )
    # An unknown tenant has no rows; the point is that it ran, not what it found.
    assert isinstance(out, str)
