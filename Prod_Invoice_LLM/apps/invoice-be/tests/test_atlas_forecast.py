"""Feature 34 / task 34.9 — the forecast as a warning with levers.

Spec: `docs/feature_34_atlas.md` §7.5 · `atlas_discussion.md` **D15**, **D44**.

Real Postgres only (hard rule 2) — `tests/atlas_pg.py` is the guard, and it
**fails rather than skips** on a configured-but-unreachable database (BE Gap
697).

What is asserted, and why each one is here
------------------------------------------
1. **The forecast states which assumption it used.** §7.5: "deterministic and
   honest are separate properties", and the second one is the one that gets
   dropped. `Forecast.assumption` is required on the contract and its words are
   asserted on the wire.
2. **A day, not a net position.** The whole reason the walk is day by day is
   that money arriving on the 28th does not help a payment run on the 22nd. The
   test builds exactly that shape: net-positive over the month, short on one day.
3. **The levers actually close the gap**, because they are chosen by arithmetic
   and not by being interesting. A chase set that does not reach the shortfall is
   dropped rather than offered as a partial fix.
4. **Nothing is emitted when the balance is unknown.** No statement, no starting
   point; a walk from zero would report every tenant as short on day one, and
   "unknown" must not render as "short".
5. **Nothing is emitted when there is no shortfall.** A line saying "you are
   fine" is the false-positive volume §5.2 says trains a user to stop reading.
6. **The Auditor sees it** (D44, reversing D2). Asserted as the capability on the
   line, which is the only place that reversal lives.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import Invoice, Tenant
from services.atlas_capabilities import AtlasCapability
from services.atlas_forecast import (
    DUE_DATE_ASSUMPTION,
    forecast_recommendations,
    shortfalls,
)
from services.atlas_skills import SkillContext
from tests.atlas_pg import open_session, unique_tag

TODAY = date.today()


@pytest.fixture(scope="module")
def pg_session():
    session = open_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg(pg_session):
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-cast-{tag}", domain=f"atlas-cast-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _inv(session, written, tenant, *, flow: str, status: str, total: float, due_in: int, vendor="Kumar Supplies"):
    inv = Invoice(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status=status,
        flow_direction=flow,
        currency="INR",
        invoice_number=uuid4().hex[:6].upper(),
        vendor_name=vendor,
        grand_total=total,
        due_date=TODAY + timedelta(days=due_in),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def _ctx(tenant) -> SkillContext:
    return SkillContext(tenant_id=tenant.id, today=TODAY)


def test_short_on_a_day_even_when_the_month_nets_out_fine(pg):
    """§7.5's actual question. Out on day 3, in on day 20 — the month is
    positive and the 3rd is not, and a net-position forecast would say nothing.
    """
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=150000.0, due_in=3)
    _inv(session, written, tenant, flow="OUTBOUND", status="SENT", total=400000.0, due_in=20, vendor="Sharma & Co")

    found = shortfalls(session, _ctx(tenant), balances={"INR": Decimal("100000")})
    assert len(found) == 1
    assert found[0].on_date == TODAY + timedelta(days=3)
    assert found[0].amount == Decimal("50000")


def test_nothing_is_emitted_when_the_balance_is_unknown(pg):
    """"Unknown" and "short" must not render the same."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=150000.0, due_in=3)
    assert shortfalls(session, _ctx(tenant), balances={}) == []


def test_nothing_is_emitted_when_there_is_no_shortfall(pg):
    """Agreement is not work — the standing picture is the Slice B cash line."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=1000.0, due_in=3)
    assert shortfalls(session, _ctx(tenant), balances={"INR": Decimal("500000")}) == []


def test_a_resolved_invoice_is_not_a_payable(pg):
    """A PAID invoice has already left the balance the statement reported;
    counting it again would forecast the same money leaving twice."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="PAID", total=900000.0, due_in=2)
    assert shortfalls(session, _ctx(tenant), balances={"INR": Decimal("100000")}) == []


def test_the_line_states_its_assumption_and_its_doubt(pg):
    """§7.5, and §5.1: a forecast presented as certain is the prohibition."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=150000.0, due_in=3)

    found = shortfalls(session, _ctx(tenant), balances={"INR": Decimal("100000")})
    line = forecast_recommendations(found, tenant_id=tenant.id, today=TODAY)[0]

    assert line.forecast is not None
    assert line.forecast.assumption == DUE_DATE_ASSUMPTION
    assert line.certainty.value == "uncertain"
    assert line.why.doubt and "due dates" in line.why.doubt
    # D44: the Auditor sees it. That reversal of D2 lives in this one value.
    assert line.capability is AtlasCapability.AUDIT


def test_the_levers_cover_the_gap_and_name_what_to_do(pg):
    """Chosen by arithmetic, not by being interesting."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=150000.0, due_in=3, vendor="Vendor A")
    _inv(session, written, tenant, flow="OUTBOUND", status="SENT", total=80000.0, due_in=10, vendor="Sharma & Co")

    found = shortfalls(session, _ctx(tenant), balances={"INR": Decimal("100000")})
    line = forecast_recommendations(found, tenant_id=tenant.id, today=TODAY)[0]
    kinds = {lever.kind for lever in line.forecast.levers}

    # 50,000 short; Sharma's 80,000 is due after the short day, so chasing it
    # covers the gap, and Vendor A's 150,000 is deferrable and big enough.
    assert "chase_receivable" in kinds
    assert "delay_payable" in kinds
    assert all(lever.amount_rendered.strip() for lever in line.forecast.levers)


def test_a_chase_set_that_cannot_cover_the_gap_is_not_offered(pg):
    """Honest rather than tidy: a partial fix presented as a lever is a lever
    that does not work, and the user finds out after doing the chasing."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=500000.0, due_in=3)
    _inv(session, written, tenant, flow="OUTBOUND", status="SENT", total=1000.0, due_in=10, vendor="Sharma & Co")

    found = shortfalls(session, _ctx(tenant), balances={"INR": Decimal("100000")})
    line = forecast_recommendations(found, tenant_id=tenant.id, today=TODAY)[0]
    assert "chase_receivable" not in {lever.kind for lever in line.forecast.levers}


def test_the_forecast_reaches_the_wire_with_its_levers(pg):
    """The FE lays out a date, a number and a list; prose it had to parse would
    be a field the two sides agree about by accident."""
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED", total=150000.0, due_in=3, vendor="Vendor A")
    _inv(session, written, tenant, flow="OUTBOUND", status="SENT", total=80000.0, due_in=10, vendor="Sharma & Co")
    balance = _balance(tenant)
    session.add(balance)
    session.commit()
    written.append(balance)

    context = TenantContext(
        tenant_id=tenant.id,
        user_id="clerk-auditor",
        role="Auditor",
        billing_plan="active",
        can_audit=True,
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_tenant_context] = lambda: context
    body = TestClient(app).get("/api/v1/atlas/lines").json()

    forecast_lines = [line for line in body["lines"] if line["skill"] == "cash_shortfall_with_levers"]
    assert len(forecast_lines) == 1
    forecast = forecast_lines[0]["forecast"]
    assert forecast["on_date"]
    assert forecast["shortfall_rendered"]
    assert forecast["assumption"] == DUE_DATE_ASSUMPTION
    assert forecast["levers"]


def _balance(tenant):
    """One bank statement line, so the walk has a starting point."""
    from models import BankStatementLine

    return BankStatementLine(
        tenant_id=tenant.id,
        # Not a FK, just NOT NULL: a statement line belongs to an attachment and
        # this test is not exercising that join.
        attachment_id=uuid4(),
        statement_date=TODAY,
        line_date=TODAY,
        narration="opening balance",
        balance=100000.0,
    )


# ═════════════════════════════════════════════════════════════════════════════
# BE Gap 714 — the lever label names the party
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "customer",
    ["Chase Customer 846807", "100200 Exports", "Sharma & Co 4409"],
)
def test_a_lever_may_name_a_party_whose_name_carries_digits(pg, customer):
    """BE Gap 714.

    `Lever.label` is prose -- `Recommendation.prose()` includes it -- and it is
    composed as "Chase <the customer's stored name> early". The digits in that
    name are an identifier copied out of the record, not a figure anybody
    computed, and before `verbatim_references()` they raised
    `InventedNumberError` and took the entire forecast line with them.
    """
    session, tenant, written = pg
    _inv(session, written, tenant, flow="INBOUND", status="AUDIT_REQUIRED",
         total=150000.0, due_in=3, vendor="Vendor A")
    _inv(session, written, tenant, flow="OUTBOUND", status="SENT",
         total=80000.0, due_in=10, vendor=customer)

    found = shortfalls(session, _ctx(tenant), balances={"INR": Decimal("100000")})
    lines = forecast_recommendations(found, tenant_id=tenant.id, today=TODAY)

    assert lines, "the shortfall produced no line at all"
    line = lines[0]
    labels = [lever.label for lever in line.forecast.levers]
    assert any(customer in label for label in labels)

    # Re-validated the way `routers/atlas.py::_validated` does at the wire.
    from services.atlas_contract import validate_recommendation

    validate_recommendation(line)
