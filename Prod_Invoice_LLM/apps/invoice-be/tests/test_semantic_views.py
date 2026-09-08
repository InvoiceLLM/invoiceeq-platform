"""Feature 30 tasks 30.3 / 30.4 — the semantic views and the metric layer.

Verification plan 30.3-30.4: "Views created; row counts equal base-table
aggregates on the seeded tenant; `query_metric()` without `tenant_id` raises;
AST guard rejects metric SQL missing the parameter."

Postgres only, and not incidentally: the views use `date_trunc`, `ARRAY_AGG`,
`CURRENT_DATE` arithmetic and `= ANY(:param)`, none of which SQLite has. There is
no version of this test that means anything on SQLite.
"""
import os
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import Invoice  # noqa: E402
from services import semantic_views as sv  # noqa: E402


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


@pytest.fixture(name="seeded")
def seeded_fixture(pg_session):
    """One tenant with a deliberately awkward ledger.

    Every exclusion the views promise has a row that tests it: a soft-deleted
    invoice, a DUPLICATE, an OUTBOUND invoice, a paid overdue-looking invoice.
    """
    tenant_id = uuid4()
    other = uuid4()
    rows = [
        # vendor A: two live inbound invoices in March, one of them overdue
        dict(invoice_number="A-1", vendor_name="Shree Packaging Pvt Ltd", grand_total=100000.0,
             tax_amount=18000.0, subtotal=82000.0, invoice_date=date(2026, 3, 1),
             due_date=date(2026, 3, 31), po_number="PO-1"),
        dict(invoice_number="A-2", vendor_name="Shree Packaging Pvt Ltd", grand_total=23200.0,
             tax_amount=3200.0, subtotal=20000.0, invoice_date=date(2026, 3, 15),
             due_date=date(2026, 4, 15), po_number="PO-1"),
        # vendor B, different month
        dict(invoice_number="B-1", vendor_name="Bharat Steels", grand_total=50000.0,
             tax_amount=9000.0, subtotal=41000.0, invoice_date=date(2026, 2, 10),
             due_date=date(2026, 3, 10), po_number="PO-2"),
        # excluded: soft-deleted
        dict(invoice_number="X-DEL", vendor_name="Shree Packaging Pvt Ltd", grand_total=999999.0,
             invoice_date=date(2026, 3, 2), due_date=date(2026, 3, 3), po_number="PO-1",
             deleted_at=datetime.utcnow()),
        # excluded: duplicate
        dict(invoice_number="X-DUP", vendor_name="Shree Packaging Pvt Ltd", grand_total=888888.0,
             invoice_date=date(2026, 3, 3), due_date=date(2026, 3, 4), po_number="PO-1",
             status="DUPLICATE"),
        # excluded from spend/3-way (outbound), included in tax_summary as OUTBOUND
        dict(invoice_number="X-OUT", customer_name="Acme Customer", grand_total=70000.0,
             tax_amount=12600.0, subtotal=57400.0, invoice_date=date(2026, 3, 4),
             due_date=date(2026, 3, 5), flow_direction="OUTBOUND"),
        # excluded from overdue: paid
        dict(invoice_number="X-PAID", vendor_name="Bharat Steels", grand_total=1000.0,
             invoice_date=date(2026, 1, 1), due_date=date(2026, 1, 2),
             paid_at=datetime.utcnow(), status="PAID"),
    ]
    for r in rows:
        pg_session.add(
            Invoice(tenant_id=tenant_id, file_path=f"test/{r['invoice_number']}.pdf",
                    currency="INR", **r)
        )
    # A second tenant, same vendor name, so every isolation assertion is real.
    pg_session.add(
        Invoice(tenant_id=other, file_path="test/other.pdf", invoice_number="O-1",
                vendor_name="Shree Packaging Pvt Ltd", grand_total=5000000.0,
                invoice_date=date(2026, 3, 1), due_date=date(2026, 3, 2),
                po_number="PO-1", currency="INR")
    )
    pg_session.commit()

    yield {"tenant_id": tenant_id, "other": other}

    for t in (tenant_id, other):
        for inv in pg_session.exec(select(Invoice).where(Invoice.tenant_id == t)).all():
            pg_session.delete(inv)
    pg_session.commit()


# --- 30.3: the views exist and mean what they say --------------------------


@pytest.mark.parametrize("view", ["v_vendor_spend", "v_overdue", "v_tax_summary", "v_3way_match"])
def test_the_view_exists(pg_session, view):
    assert pg_session.execute(text(f"SELECT count(*) FROM {view}")).scalar() is not None


def test_vendor_spend_equals_the_base_table_aggregate(pg_session, seeded):
    """The view's number and a hand-written aggregate must agree, or the view is
    an opinion rather than a definition."""
    tenant = str(seeded["tenant_id"])
    view_total = pg_session.execute(
        text("SELECT SUM(total_amount) FROM v_vendor_spend WHERE tenant_id = :t"),
        {"t": tenant},
    ).scalar()
    base_total = pg_session.execute(
        text(
            "SELECT SUM(COALESCE(grand_total,0)) FROM invoice "
            "WHERE tenant_id = :t AND deleted_at IS NULL AND status <> 'DUPLICATE' "
            "AND flow_direction = 'INBOUND' AND invoice_date IS NOT NULL"
        ),
        {"t": tenant},
    ).scalar()
    assert float(view_total) == float(base_total)
    # 100000 + 23200 + 50000 + 1000 (the paid one is spend, it is just not overdue)
    assert float(view_total) == 174200.0


def test_deleted_and_duplicate_rows_are_excluded(pg_session, seeded):
    rows = pg_session.execute(
        text("SELECT SUM(invoice_count) FROM v_vendor_spend WHERE tenant_id = :t"),
        {"t": str(seeded["tenant_id"])},
    ).scalar()
    assert int(rows) == 4  # A-1, A-2, B-1, X-PAID; not X-DEL, X-DUP, X-OUT


def test_overdue_is_computed_from_due_date_not_stored(pg_session, seeded):
    rows = sv.query_metric("overdue", seeded["tenant_id"], pg_session)
    numbers = {r["invoice_number"] for r in rows}
    assert "X-PAID" not in numbers  # paid_at set
    assert "A-1" in numbers and "B-1" in numbers
    assert all(r["days_overdue"] > 0 for r in rows)
    # No invoice anywhere stores the status the view derives.
    assert all(r["status"] != "OVERDUE" for r in rows)


def test_three_way_match_groups_by_po(pg_session, seeded):
    rows = sv.query_metric("three_way_match", seeded["tenant_id"], pg_session, po_number="PO-1")
    assert len(rows) == 1
    assert rows[0]["invoice_count"] == 2
    assert float(rows[0]["invoiced_amount"]) == 123200.0
    assert set(rows[0]["invoice_numbers"]) == {"A-1", "A-2"}


# --- 30.4: the metric layer and its tenant guard ---------------------------


def test_query_metric_without_a_tenant_raises(pg_session):
    with pytest.raises(sv.MetricError):
        sv.query_metric("vendor_spend", None, pg_session)
    with pytest.raises(sv.MetricError):
        sv.query_metric("vendor_spend", "", pg_session)


def test_unknown_metric_and_unknown_filter_raise(pg_session, seeded):
    with pytest.raises(sv.MetricError):
        sv.query_metric("no_such_metric", seeded["tenant_id"], pg_session)
    with pytest.raises(sv.MetricError):
        sv.query_metric("vendor_spend", seeded["tenant_id"], pg_session, sneaky="1=1")


def test_every_registered_metric_carries_the_tenant_parameter():
    """Guard 2, asserted here as well as at import: a metric added without
    `:tenant_id` is a cross-tenant read waiting for its first caller."""
    for name, metric in sv.METRICS.items():
        assert ":tenant_id" in metric.sql, name
        for fname, fragment in metric.filters.items():
            assert ":" in fragment, f"{name}.{fname}"
    sv._validate_registry()  # must not raise


def test_a_metric_missing_the_parameter_is_rejected_by_the_guard():
    """The negative case for `_validate_registry()`."""
    broken = sv.Metric(
        name="broken", view="v_overdue", definition="unscoped",
        sql="SELECT 1 FROM v_overdue WHERE 1 = 1",
    )
    original = dict(sv.METRICS)
    sv.METRICS["broken"] = broken
    try:
        with pytest.raises(RuntimeError):
            sv._validate_registry()
    finally:
        sv.METRICS.clear()
        sv.METRICS.update(original)


def test_a_metric_never_returns_another_tenants_rows(pg_session, seeded):
    ours = sv.query_metric(
        "vendor_spend", seeded["tenant_id"], pg_session, vendor_name="Shree Packaging Pvt Ltd"
    )
    theirs = sv.query_metric(
        "vendor_spend", seeded["other"], pg_session, vendor_name="Shree Packaging Pvt Ltd"
    )
    assert sum(float(r["total_amount"]) for r in ours) == 123200.0
    assert sum(float(r["total_amount"]) for r in theirs) == 5000000.0


def test_vendor_names_filter_takes_the_vendor_masters_whole_output(pg_session, seeded):
    rows = sv.query_metric(
        "vendor_spend",
        seeded["tenant_id"],
        pg_session,
        vendor_names=["Shree Packaging Pvt Ltd", "Bharat Steels"],
    )
    assert {r["vendor_name"] for r in rows} == {"Shree Packaging Pvt Ltd", "Bharat Steels"}


def test_an_empty_result_is_an_answer_not_an_error(pg_session, seeded):
    rows = sv.query_metric(
        "vendor_spend", seeded["tenant_id"], pg_session, vendor_name="Nobody Ltd"
    )
    assert rows == []


def test_metric_definitions_are_available_without_the_sql():
    definitions = sv.metric_definitions()
    assert set(definitions) == set(sv.METRICS)
    assert "duplicate" in definitions["vendor_spend"]
    assert all("SELECT" not in d for d in definitions.values())


@pytest.mark.parametrize(
    "question,expected",
    [
        ("what is overdue from Shree Packaging?", "overdue"),
        ("how much GST did we pay in March?", "tax_summary"),
        ("how much did we spend with Bharat Steels?", "vendor_spend"),
        ("what did we bill against PO-1? three way", "three_way_match"),
        ("who signed the contract?", None),
    ],
)
def test_preferred_metric_is_deterministic(question, expected):
    assert sv.preferred_metric_for(question) == expected
