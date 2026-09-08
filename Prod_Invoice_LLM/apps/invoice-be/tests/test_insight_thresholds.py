"""Feature 30 task 30.0g — threshold constants and the per-tenant override.

Real Postgres only (hard rule 2). The behaviour under test is a row in
`tenant_insight_setting` beating a constant, and a UUID-keyed WHERE clause is
exactly what SQLite gets wrong in this repo.

Verification plan 30.0g: "override for one tenant changes only that tenant's
threshold".
"""
import os
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import TenantInsightSetting  # noqa: E402
from services import insight_thresholds as it  # noqa: E402


@pytest.fixture(name="pg_session")
def pg_session_fixture():
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="tenants")
def tenants_fixture(pg_session):
    """Two throwaway tenants; every override written under either is removed."""
    a, b = uuid4(), uuid4()
    yield a, b
    for row in pg_session.exec(
        select(TenantInsightSetting).where(TenantInsightSetting.tenant_id.in_([a, b]))
    ).all():
        pg_session.delete(row)
    pg_session.commit()


def test_shipped_defaults_are_the_r9_r5_numbers():
    """The five numbers rulings R9 and R5 fixed, asserted as values not as keys.

    A test that only checked the names would pass after somebody retuned
    `bank_amount_tolerance` to 100 -- which is the change that most needs to be
    noticed, because it silently widens what counts as a payment match.
    """
    assert it.THRESHOLDS["over_invoicing_pairs"] == 3
    assert it.THRESHOLDS["quote_drift_invoices"] == 2
    assert it.THRESHOLDS["repeat_short_delivery_challans"] == 3
    assert it.THRESHOLDS["bank_amount_tolerance"] == 1
    assert it.THRESHOLDS["bank_date_tolerance_days"] == 5


def test_threshold_without_session_returns_the_constant():
    assert it.threshold("bank_date_tolerance_days") == 5.0
    assert it.threshold("bank_date_tolerance_days", tenant_id=uuid4()) == 5.0


def test_unknown_name_raises_rather_than_defaulting():
    with pytest.raises(it.UnknownThresholdError):
        it.threshold("no_such_threshold")
    with pytest.raises(it.UnknownThresholdError):
        it.set_threshold("no_such_threshold", uuid4(), 1.0, db_session=None)


def test_override_applies_to_one_tenant_only(pg_session, tenants):
    tenant_a, tenant_b = tenants

    it.set_threshold(
        "over_invoicing_pairs", tenant_a, 7.0, pg_session, updated_by="test@example.com"
    )

    assert it.threshold("over_invoicing_pairs", tenant_a, pg_session) == 7.0
    # The whole point of R9's "with per-tenant override": tenant B is untouched.
    assert it.threshold("over_invoicing_pairs", tenant_b, pg_session) == 3.0
    # And an unrelated threshold on the overriding tenant is still the default.
    assert it.threshold("quote_drift_invoices", tenant_a, pg_session) == 2.0


def test_override_is_an_upsert_not_a_second_row(pg_session, tenants):
    tenant_a, _ = tenants
    it.set_threshold("quote_drift_invoices", tenant_a, 4.0, pg_session)
    it.set_threshold("quote_drift_invoices", tenant_a, 5.0, pg_session)

    rows = pg_session.exec(
        select(TenantInsightSetting).where(
            TenantInsightSetting.tenant_id == tenant_a,
            TenantInsightSetting.name == "quote_drift_invoices",
        )
    ).all()
    assert len(rows) == 1
    assert it.threshold("quote_drift_invoices", tenant_a, pg_session) == 5.0


def test_all_thresholds_reports_the_tenant_view(pg_session, tenants):
    """30.12 renders this: the user is owed the number their gate actually used."""
    tenant_a, tenant_b = tenants
    it.set_threshold("bank_amount_tolerance", tenant_a, 2.5, pg_session)

    seen_a = it.all_thresholds(tenant_a, pg_session)
    seen_b = it.all_thresholds(tenant_b, pg_session)

    assert set(seen_a) == set(it.THRESHOLDS)
    assert seen_a["bank_amount_tolerance"] == 2.5
    assert seen_b["bank_amount_tolerance"] == 1.0
