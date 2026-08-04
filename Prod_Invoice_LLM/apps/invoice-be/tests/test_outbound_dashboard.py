"""Tests for Feature 8.1 Task 8.1.2 (Outbound Dashboard metrics):
routers/outbound_dashboard.py::get_outbound_dashboard_metrics(). Mirrors
test_dashboard.py's style/fixtures, with the direction-isolation cases that
only matter on the AR side."""
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

client = TestClient(app)

METRICS_URL = "/api/v1/outbound-dashboard/metrics"


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


def _outbound(**kwargs):
    """An OUTBOUND invoice with the boilerplate filled in."""
    kwargs.setdefault("id", uuid4())
    kwargs.setdefault("tenant_id", MOCK_TENANT_ID)
    kwargs.setdefault("file_path", f"mock/out-{uuid4()}.pdf")
    kwargs.setdefault("flow_direction", "OUTBOUND")
    kwargs.setdefault("sa_alerts", [])
    return Invoice(**kwargs)


def populate_mock_outbound_invoices(db_session):
    """A diverse outbound set, plus the two rows that must never be counted:
    another tenant's outbound invoice, and this tenant's own inbound one."""
    db_session.add(_outbound(
        customer_name="Vertex Industries", grand_total=1000.0,
        invoice_date=date(2026, 6, 20), status="PAID",
        sent_at=datetime(2026, 6, 20, 12, 0, 0), paid_at=datetime(2026, 6, 30, 12, 0, 0),
    ))
    db_session.add(_outbound(
        customer_name="Northwind Ltd", grand_total=500.0,
        invoice_date=date(2026, 6, 22), status="NEEDS_REVIEW",
        sa_alerts=[{"type": "math_mismatch", "message": "totals do not reconcile"}],
    ))
    db_session.add(_outbound(
        customer_name="Vertex Industries", grand_total=250.0,
        invoice_date=date(2026, 6, 25), status="VERIFIED",
    ))
    db_session.add(_outbound(
        customer_name="Northwind Ltd", grand_total=300.0,
        invoice_date=date(2026, 6, 26), status="SENT",
        due_date=date.today() - timedelta(days=5),  # overdue
        sent_at=datetime(2026, 6, 26, 9, 0, 0),
    ))
    # Another tenant's outbound invoice -- tenant isolation.
    db_session.add(_outbound(
        tenant_id=uuid4(), customer_name="Northwind Ltd", grand_total=9999.0,
        invoice_date=date(2026, 6, 22), status="PAID",
    ))
    # This tenant's own INBOUND invoice -- direction isolation. This is the
    # whole point of the feature: an AP invoice must never be reported as a
    # receivable.
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/in.pdf",
        flow_direction="INBOUND", vendor_name="Hardware Depot", grand_total=7777.0,
        invoice_date=date(2026, 6, 21), status="PAID", sa_alerts=[],
    ))
    db_session.commit()


# ── Aggregate correctness ─────────────────────────────────────────────────────

def test_aggregate_metrics(db_session):
    """Primary aggregate mathematics, with both isolation rows excluded."""
    populate_mock_outbound_invoices(db_session)

    response = client.get(METRICS_URL)
    assert response.status_code == 200
    data = response.json()

    # 1000 + 500 + 250 + 300 = 2050. Neither 9999 (other tenant) nor 7777
    # (inbound) may appear.
    assert data["total_invoiced_out"] == 2050.0
    assert data["amount_collected"] == 1000.0
    # UPLOADED/VERIFIED/NEEDS_REVIEW/SENT: 500 + 250 + 300
    assert data["outstanding_receivables"] == 1050.0
    # Only the SENT row past its due date
    assert data["at_risk_receivables"] == 300.0
    # Every bucket accounted for -- no money belongs to nothing
    assert data["amount_collected"] + data["outstanding_receivables"] == data["total_invoiced_out"]
    assert data["active_alerts_count"] == 1

    assert data["invoices_by_status"] == {"PAID": 1, "NEEDS_REVIEW": 1, "VERIFIED": 1, "SENT": 1}

    top_customers = data["top_customers"]
    assert len(top_customers) == 2
    assert top_customers[0]["customer_name"] == "Vertex Industries"
    assert top_customers[0]["amount"] == 1250.0
    assert top_customers[1]["customer_name"] == "Northwind Ltd"
    assert top_customers[1]["amount"] == 800.0

    revenue = data["revenue_over_time"]
    assert len(revenue) == 4
    assert revenue[0]["date"] == "2026-06-20"
    assert revenue[0]["amount"] == 1000.0
    assert revenue[-1]["date"] == "2026-06-26"
    assert revenue[-1]["amount"] == 300.0


def test_empty_tenant_returns_zeroes_not_error(db_session):
    """No outbound invoices at all -- every figure zero, accuracy defaults to
    100 rather than dividing by zero."""
    response = client.get(METRICS_URL)
    assert response.status_code == 200
    data = response.json()

    assert data["total_invoiced_out"] == 0.0
    assert data["amount_collected"] == 0.0
    assert data["outstanding_receivables"] == 0.0
    assert data["at_risk_receivables"] == 0.0
    assert data["average_days_to_payment"] == 0.0
    assert data["verification_accuracy"] == 100.0
    assert data["top_customers"] == []
    assert data["revenue_over_time"] == []
    assert data["invoices_by_status"] == {}


def test_no_combined_or_net_figure_in_response(db_session):
    """Design constraint from both feature docs: the net/combined AP-vs-AR
    comparison is Chat-only and must not leak onto this screen."""
    populate_mock_outbound_invoices(db_session)

    data = client.get(METRICS_URL).json()
    for forbidden in ("net_position", "net_cash_position", "combined_total", "total_invoiced"):
        assert forbidden not in data


# ── Tenant + direction isolation ──────────────────────────────────────────────

def test_tenant_isolation(db_session):
    """Another tenant's outbound invoices are invisible here."""
    other_tenant = uuid4()
    db_session.add(_outbound(tenant_id=other_tenant, customer_name="Foreign Co", grand_total=5000.0, status="PAID"))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    assert data["total_invoiced_out"] == 0.0
    assert data["top_customers"] == []


def test_direction_isolation(db_session):
    """An INBOUND invoice for this same tenant must not be counted as a
    receivable -- without the flow_direction predicate this endpoint would
    silently re-report the tenant's AP spend as AR revenue."""
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/in.pdf",
        flow_direction="INBOUND", vendor_name="Hardware Depot", grand_total=4321.0,
        status="PAID", sa_alerts=[],
    ))
    db_session.add(_outbound(customer_name="Vertex Industries", grand_total=100.0, status="PAID"))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    assert data["total_invoiced_out"] == 100.0
    assert data["amount_collected"] == 100.0
    assert [c["customer_name"] for c in data["top_customers"]] == ["Vertex Industries"]


# ── average_days_to_payment ───────────────────────────────────────────────────

def test_average_days_to_payment_only_when_both_timestamps_exist(db_session):
    """Only rows with both sent_at and paid_at contribute. The others are
    excluded from the average, never estimated."""
    # 10 days, both timestamps -> counts
    db_session.add(_outbound(
        customer_name="A Co", grand_total=100.0, status="PAID",
        sent_at=datetime(2026, 6, 1, 0, 0, 0), paid_at=datetime(2026, 6, 11, 0, 0, 0),
    ))
    # sent_at only -> excluded
    db_session.add(_outbound(
        customer_name="B Co", grand_total=100.0, status="SENT",
        sent_at=datetime(2026, 6, 1, 0, 0, 0),
    ))
    # paid_at only (legacy/backfilled row) -> excluded
    db_session.add(_outbound(
        customer_name="C Co", grand_total=100.0, status="PAID",
        paid_at=datetime(2026, 6, 11, 0, 0, 0),
    ))
    # neither -> excluded
    db_session.add(_outbound(customer_name="D Co", grand_total=100.0, status="UPLOADED"))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    # Average over the single qualifying row only -- not 10/4, not 10/2
    assert data["average_days_to_payment"] == 10.0


def test_average_days_to_payment_averages_multiple_rows(db_session):
    """Two qualifying rows (10 and 4 days) average to 7."""
    db_session.add(_outbound(
        customer_name="A Co", grand_total=100.0, status="PAID",
        sent_at=datetime(2026, 6, 1, 0, 0, 0), paid_at=datetime(2026, 6, 11, 0, 0, 0),
    ))
    db_session.add(_outbound(
        customer_name="B Co", grand_total=100.0, status="PAID",
        sent_at=datetime(2026, 6, 1, 0, 0, 0), paid_at=datetime(2026, 6, 5, 0, 0, 0),
    ))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    assert data["average_days_to_payment"] == 7.0


def test_average_days_to_payment_zero_when_nothing_qualifies(db_session):
    """No row has both timestamps -> 0.0, not a crash and not a guess."""
    db_session.add(_outbound(customer_name="A Co", grand_total=100.0, status="SENT",
                             sent_at=datetime(2026, 6, 1, 0, 0, 0)))
    db_session.commit()

    assert client.get(METRICS_URL).json()["average_days_to_payment"] == 0.0


# ── verification_accuracy ─────────────────────────────────────────────────────

def test_verification_accuracy_counts_only_decided_invoices(db_session):
    """3 decided rows, 1 of them alerted -> 66.7%. The UPLOADED row hasn't
    been judged yet and must not count against the score."""
    db_session.add(_outbound(customer_name="A Co", grand_total=100.0, status="VERIFIED"))
    db_session.add(_outbound(customer_name="B Co", grand_total=100.0, status="PAID"))
    db_session.add(_outbound(
        customer_name="C Co", grand_total=100.0, status="NEEDS_REVIEW",
        sa_alerts=[{"type": "math_mismatch", "message": "x"}],
    ))
    db_session.add(_outbound(customer_name="D Co", grand_total=100.0, status="UPLOADED"))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    assert data["verification_accuracy"] == 66.7
    assert data["active_alerts_count"] == 1


def test_verification_accuracy_uses_alerts_not_current_status(db_session):
    """An invoice corrected out of NEEDS_REVIEW and sent still carries its
    alerts, so it must not be scored as a clean first pass."""
    db_session.add(_outbound(
        customer_name="A Co", grand_total=100.0, status="SENT",
        sa_alerts=[{"type": "math_mismatch", "message": "x"}],
    ))
    db_session.commit()

    assert client.get(METRICS_URL).json()["verification_accuracy"] == 0.0


# ── Overdue (at_risk_receivables) ─────────────────────────────────────────────

def test_at_risk_receivables_overdue_boundary(db_session):
    """Read-time overdue: SENT and strictly past due_date. Due today isn't
    overdue yet, and a missing due_date can't be."""
    db_session.add(_outbound(customer_name="Yesterday Co", grand_total=100.0, status="SENT",
                             due_date=date.today() - timedelta(days=1)))
    db_session.add(_outbound(customer_name="Today Co", grand_total=200.0, status="SENT",
                             due_date=date.today()))
    db_session.add(_outbound(customer_name="Future Co", grand_total=400.0, status="SENT",
                             due_date=date.today() + timedelta(days=7)))
    db_session.add(_outbound(customer_name="NoDate Co", grand_total=800.0, status="SENT"))
    db_session.commit()

    assert client.get(METRICS_URL).json()["at_risk_receivables"] == 100.0


def test_at_risk_receivables_excludes_paid_past_due(db_session):
    """A PAID invoice that happens to be past its due date was collected --
    it is not at risk."""
    db_session.add(_outbound(customer_name="Paid Late Co", grand_total=100.0, status="PAID",
                             due_date=date.today() - timedelta(days=30)))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    assert data["at_risk_receivables"] == 0.0
    assert data["amount_collected"] == 100.0


# ── Filters ───────────────────────────────────────────────────────────────────

def test_metrics_filters(db_session):
    """Each filter narrows the aggregate scope, direction predicate intact."""
    populate_mock_outbound_invoices(db_session)

    # 1. By customer
    data = client.get(METRICS_URL, params={"customer_name": "Vertex Industries"}).json()
    assert data["total_invoiced_out"] == 1250.0
    assert len(data["top_customers"]) == 1

    # 2. By date range
    data = client.get(METRICS_URL, params={"start_date": "2026-06-21", "end_date": "2026-06-24"}).json()
    assert data["total_invoiced_out"] == 500.0
    assert data["outstanding_receivables"] == 500.0

    # 3. By status
    data = client.get(METRICS_URL, params={"status": "PAID"}).json()
    assert data["total_invoiced_out"] == 1000.0
    assert data["amount_collected"] == 1000.0

    # 4. Status filter is case-insensitive, matching the list endpoint
    data = client.get(METRICS_URL, params={"status": "paid"}).json()
    assert data["total_invoiced_out"] == 1000.0


def test_unknown_customer_name_grouping(db_session):
    """A row whose customer_name was never extracted still has to appear in
    the ranking rather than vanishing from the totals."""
    db_session.add(_outbound(grand_total=100.0, status="SENT"))
    db_session.commit()

    data = client.get(METRICS_URL).json()
    assert data["top_customers"] == [{"customer_name": "Unknown Customer", "amount": 100.0}]
    assert data["total_invoiced_out"] == 100.0


def test_outbound_ai_score_metrics(db_session):
    """Verify outbound AI extraction accuracy and alert response accuracy computations."""
    # 1. Outbound invoice with 1 field correction.
    # Total fields = 7. Corrected = 1. Field extraction = 6 / 7 = 85.7%
    inv1_id = uuid4()
    inv1 = _outbound(
        id=inv1_id,
        status="NEEDS_REVIEW",
        grand_total=100.0,
        sa_alerts=[]
    )
    db_session.add(inv1)
    db_session.commit()

    # Resolve it as VERIFIED with corrections
    payload1 = {
        "status": "PAID",
        "corrections": {"grand_total": 90.0}
    }
    res = client.put(f"/api/v1/audit/resolve/{inv1_id}", json=payload1)
    assert res.status_code == 200

    # 2. Outbound invoice with 2 alerts, 1 dismissed, 1 not dismissed.
    # Dismissed = False alarm (1), Not dismissed = Correct alert (1).
    # Alert accuracy = 1 / 2 = 50.0%
    inv2_id = uuid4()
    inv2 = _outbound(
        id=inv2_id,
        status="NEEDS_REVIEW",
        sa_alerts=[{"type": "math_mismatch", "message": "totals do not reconcile"}, {"type": "date_mismatch", "message": "due date before invoice date"}]
    )
    db_session.add(inv2)
    db_session.commit()

    payload2 = {
        "status": "PAID",
        "dismissed_alerts": ["totals do not reconcile"]
    }
    res = client.put(f"/api/v1/audit/resolve/{inv2_id}", json=payload2)
    assert res.status_code == 200

    # Retrieve metrics
    response = client.get(METRICS_URL)
    assert response.status_code == 200
    data = response.json()

    assert "ai_field_extraction" in data
    assert "ai_alert_response" in data

    # Expected field extraction:
    # Invoice 1: 1 correction out of 7 fields -> 6 correct.
    # Invoice 2: 0 corrections -> 7 correct.
    # Total fields = 14. Total correct = 13. Accuracy = 13 / 14 = 92.857%
    assert abs(data["ai_field_extraction"] - 92.857) < 0.1

    # Expected alert response:
    # Invoice 2 has 2 alerts. 1 is dismissed (false alarm). 1 remains (correct alert).
    # Alert accuracy = 1 / 2 = 50.0%
    assert data["ai_alert_response"] == 50.0

