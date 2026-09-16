"""Tests for Feature 33 Tasks 33.13, 33.14, 33.14a — Forecast Engine & FP&A Capabilities."""
from datetime import date, datetime, timedelta
from uuid import uuid4
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from models import Fact, Invoice
from services.forecast import (
    Forecast,
    ForecastLine,
    Recurrence,
    detect_recurrence,
    forecast,
    project_pnl,
    scenario,
    cap_pnl_by_period,
    cap_margin_per_customer,
    cap_margin_per_item,
    cap_budget_variance,
    cap_expense_category_trend,
)


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_detect_recurrence_monthly(test_db):
    tenant_id = uuid4()
    # Create 3 monthly payment facts for same counterparty
    base_date = date(2026, 6, 1)
    for i in range(3):
        f = Fact(
            tenant_id=tenant_id,
            kind="payment_event",
            subject_kind="payment",
            subject_id=f"pay-{i}",
            counterparty_id="Shree Packaging",
            as_of=base_date + timedelta(days=30 * i),
            figures={"amount": 45000.0, "currency": "INR"},
        )
        test_db.add(f)
    test_db.commit()

    recs = detect_recurrence(tenant_id, db_session=test_db)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.counterparty == "Shree Packaging"
    assert rec.amount == 45000.0
    assert rec.currency == "INR"
    assert rec.period_days == 30
    assert rec.occurrences == 3


def test_forecast_multi_tier(test_db):
    tenant_id = uuid4()
    today = date.today()

    # 1. Certain tier: Inbound invoice (outflow) + Outbound invoice (inflow)
    inv_in = Invoice(
        tenant_id=tenant_id,
        invoice_number="INV-IN-1",
        vendor_name="ABC Logistics",
        flow_direction="INBOUND",
        grand_total=10000.0,
        currency="INR",
        invoice_date=today,
        due_date=today + timedelta(days=10),
        file_path="dummy.pdf",
    )
    inv_out = Invoice(
        tenant_id=tenant_id,
        invoice_number="INV-OUT-1",
        customer_name="Kaveri Enterprises",
        flow_direction="OUTBOUND",
        grand_total=25000.0,
        currency="INR",
        invoice_date=today,
        due_date=today + timedelta(days=15),
        file_path="dummy.pdf",
    )
    test_db.add(inv_in)
    test_db.add(inv_out)

    # 2. Committed tier: PO commitment fact
    po_fact = Fact(
        tenant_id=tenant_id,
        kind="commitment",
        subject_kind="purchase_order",
        subject_id="PO-100",
        counterparty_id="Raw Materials Ltd",
        as_of=today + timedelta(days=20),
        figures={"total_amount": 5000.0, "currency": "INR"},
    )
    test_db.add(po_fact)
    test_db.commit()

    fc = forecast(tenant_id, clearance="ops", horizon_days=60, db_session=test_db)
    assert "INR" in fc.currencies
    lines = fc.lines_by_currency["INR"]
    assert len(lines) >= 3

    tiers = {l.tier for l in lines}
    assert "certain" in tiers
    assert "committed" in tiers

    # Check net certain cash position: 25000 - 10000 = 15000
    assert fc.cash_position_by_currency["INR"] == 15000.0


def test_scenario_modelling(test_db):
    tenant_id = uuid4()
    today = date.today()

    inv_out = Invoice(
        tenant_id=tenant_id,
        invoice_number="INV-OUT-1",
        customer_name="Kaveri",
        flow_direction="OUTBOUND",
        grand_total=20000.0,
        currency="INR",
        due_date=today + timedelta(days=10),
        file_path="dummy.pdf",
    )
    test_db.add(inv_out)
    test_db.commit()

    base_fc = forecast(tenant_id, db_session=test_db)
    orig_due = base_fc.lines_by_currency["INR"][0].due_date

    # What-if: Kaveri pays 20 days late
    sc = scenario(base_fc, {"counterparty": "Kaveri", "delay_days": 20})
    sc_due = sc.lines_by_currency["INR"][0].due_date
    assert sc_due == orig_due + timedelta(days=20)


def test_fpa_capabilities_stubs(test_db):
    tenant_id = uuid4()
    ctx = {"tenant_id": str(tenant_id), "clearance": "ops"}

    # When period accounts are absent -> NOT_CHECKED
    card = cap_pnl_by_period(None, test_db, ctx)
    assert card.card == "pnl_by_period"
    assert card.status == "NOT_CHECKED"

    card_marg = cap_margin_per_customer(None, test_db, ctx)
    assert card_marg.card == "margin_per_customer"
    assert card_marg.status == "NOT_CHECKED"
