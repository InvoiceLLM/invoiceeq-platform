"""Tests for Feature 8.1 Task 8.1.2: GET /outbound-dashboard/metrics.
Mirrors test_dashboard.py's conventions for the inbound endpoint."""
from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, Tenant

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

client = TestClient(app)


def _seed_tenant(db_session) -> Tenant:
    tenant = Tenant(
        id=MOCK_TENANT_ID, name="Test Workspace", domain="test.example.com",
        billing_plan="pro_combined", send_invoices_enabled=True,
        outbound_sender_email="ar@test.example.com",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _outbound_invoice(**kwargs):
    defaults = dict(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=f"mock/{uuid4()}.pdf",
        flow_direction="OUTBOUND", customer_name="Acme Corp", grand_total=1000.0,
        sa_alerts=[],
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


import pytest


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


def test_outbound_metrics_totals_and_status_breakdown(db_session):
    _seed_tenant(db_session)
    today = date.today()

    db_session.add_all([
        _outbound_invoice(status="PAID", grand_total=1000.0, customer_name="Acme Corp"),
        _outbound_invoice(status="SENT", grand_total=500.0, customer_name="Acme Corp", due_date=today - timedelta(days=5)),  # overdue
        _outbound_invoice(status="SENT", grand_total=300.0, customer_name="Beta Ltd", due_date=today + timedelta(days=10)),  # not overdue
        _outbound_invoice(status="NEEDS_REVIEW", grand_total=200.0, customer_name="Beta Ltd", sa_alerts=[{"type": "x"}]),
        _outbound_invoice(status="VERIFIED", grand_total=150.0, customer_name="Beta Ltd"),
        # A different tenant's invoice must never leak into these totals.
        _outbound_invoice(tenant_id=uuid4(), status="PAID", grand_total=99999.0),
    ])
    db_session.commit()

    response = client.get("/api/v1/outbound-dashboard/metrics")
    assert response.status_code == 200
    data = response.json()

    assert data["total_invoiced_out"] == 2150.0  # 1000+500+300+200+150
    assert data["amount_collected"] == 1000.0
    assert data["outstanding_receivables"] == 1000.0  # SENT(500+300) + NEEDS_REVIEW(200) -- not VERIFIED, not PAID
    assert data["at_risk_receivables"] == 500.0  # only the overdue SENT invoice
    assert data["invoices_by_status"]["PAID"] == 1
    assert data["invoices_by_status"]["SENT"] == 2
    assert data["invoices_by_status"]["NEEDS_REVIEW"] == 1
    assert data["invoices_by_status"]["VERIFIED"] == 1

    top_customers = {c["customer_name"]: c["amount"] for c in data["top_customers"]}
    assert top_customers["Acme Corp"] == 1500.0
    assert top_customers["Beta Ltd"] == 650.0


def test_outbound_metrics_verification_accuracy_and_days_to_payment(db_session):
    _seed_tenant(db_session)
    sent = datetime(2026, 7, 1, 12, 0, 0)
    paid = datetime(2026, 7, 6, 12, 0, 0)  # 5 days later

    db_session.add_all([
        _outbound_invoice(status="VERIFIED", sa_alerts=[]),
        _outbound_invoice(status="NEEDS_REVIEW", sa_alerts=[{"type": "duplicate_invoice_number"}]),
        _outbound_invoice(status="PAID", sa_alerts=[], sent_at=sent, paid_at=paid),
        # Missing sent_at -- must be excluded from the average, not estimated.
        _outbound_invoice(status="PAID", sa_alerts=[], paid_at=paid),
        # UPLOADED hasn't reached verification yet -- excluded from the accuracy denominator.
        _outbound_invoice(status="UPLOADED", sa_alerts=[]),
    ])
    db_session.commit()

    response = client.get("/api/v1/outbound-dashboard/metrics")
    assert response.status_code == 200
    data = response.json()

    # 4 processed invoices (VERIFIED/NEEDS_REVIEW/PAID x2), 1 with alerts -> 75% accuracy.
    assert data["verification_accuracy"] == 75.0
    assert data["average_days_to_payment"] == 5.0


def test_outbound_metrics_filters_by_customer_and_status(db_session):
    _seed_tenant(db_session)
    db_session.add_all([
        _outbound_invoice(status="PAID", customer_name="Acme Corp", grand_total=100.0),
        _outbound_invoice(status="SENT", customer_name="Acme Corp", grand_total=200.0),
        _outbound_invoice(status="PAID", customer_name="Beta Ltd", grand_total=9999.0),
    ])
    db_session.commit()

    response = client.get("/api/v1/outbound-dashboard/metrics?customer_name=Acme Corp&status=PAID")
    assert response.status_code == 200
    data = response.json()
    assert data["total_invoiced_out"] == 100.0
    assert data["invoices_by_status"] == {"PAID": 1}


def test_outbound_metrics_empty_tenant_returns_zeros(db_session):
    _seed_tenant(db_session)
    response = client.get("/api/v1/outbound-dashboard/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_invoiced_out"] == 0.0
    assert data["amount_collected"] == 0.0
    assert data["outstanding_receivables"] == 0.0
    assert data["at_risk_receivables"] == 0.0
    assert data["verification_accuracy"] == 100.0
    assert data["average_days_to_payment"] == 0.0
    assert data["top_customers"] == []
    assert data["invoices_by_status"] == {}
