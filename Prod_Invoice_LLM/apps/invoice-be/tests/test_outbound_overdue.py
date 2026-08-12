"""
Tests for Gap 126: the scheduled `outbound_invoice.overdue` sweep
(services/outbound_overdue.py, driven by scripts/sweep_outbound_overdue.py).

The two things that actually matter about a sweep like this:

Candidate selection -- it must agree exactly with the read-time overdue rule
routers/outbound_dashboard.py applies (OUTBOUND + SENT + due_date strictly in
the past), or a tenant gets webhooks for invoices their dashboard doesn't call
overdue:
1.  A SENT outbound invoice past its due date is a candidate and fires the event.
2.  Due today is not overdue yet (strict `<`, same boundary as the dashboard).
3.  A future due date is not a candidate.
4.  A NULL due_date can never be overdue.
5.  Non-SENT statuses (PAID, UPLOADED, ...) are never candidates, however old.
6.  INBOUND invoices are never candidates -- this is an AR-only event.
7.  tenant_id scoping, for a single-tenant run.

Idempotency -- an unpaid invoice is overdue again tomorrow, and every day after,
so "fires once" is the entire reason overdue_notified_at exists:
8.  Running the sweep twice fires exactly once.
9.  An invoice already carrying overdue_notified_at is skipped outright.
10. The marker is stamped even when delivery fails, so a broken endpoint cannot
    turn into a daily re-delivery loop.
11. One tenant's dispatch blowing up does not starve the invoices after it.

Plus the payload shape (12) and the no-subscriptions case (13).
"""
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import services.outbound_overdue as overdue
from models import Invoice

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")

TODAY = date(2026, 8, 12)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def dispatched(monkeypatch):
    """Record dispatch_webhook_event calls instead of delivering them.

    Patched on the sweep module (which imports the symbol directly), so the
    tenant/event/payload the sweep actually builds stays under test -- that
    payload is what a subscriber sees.
    """
    calls: list[tuple] = []

    def _fake_dispatch(session, tenant_id, event_type, payload):
        calls.append((tenant_id, event_type, payload))

    monkeypatch.setattr(overdue, "dispatch_webhook_event", _fake_dispatch)
    return calls


def _seed_invoice(
    db_session: Session,
    status: str = "SENT",
    direction: str = "OUTBOUND",
    due_days_ago: int | None = 5,
    tenant_id: UUID = TENANT_ID,
    overdue_notified_at: datetime | None = None,
    customer_name: str = "Acme Corp",
    grand_total: float = 1200.50,
    currency: str = "USD",
) -> Invoice:
    invoice = Invoice(
        tenant_id=tenant_id,
        batch_id=uuid4(),
        file_path=f"blob://{uuid4()}.pdf",
        status=status,
        flow_direction=direction,
        due_date=None if due_days_ago is None else TODAY - timedelta(days=due_days_ago),
        customer_name=customer_name,
        grand_total=grand_total,
        currency=currency,
        overdue_notified_at=overdue_notified_at,
    )
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


# ---------------------------------------------------------------------------
# Candidate selection -- must match the read-time rule exactly
# ---------------------------------------------------------------------------


def test_sent_invoice_past_due_fires_event(db_session, dispatched):
    invoice = _seed_invoice(db_session, due_days_ago=5)

    notified = overdue.sweep_overdue_invoices(db_session, today=TODAY)

    assert [inv.id for inv in notified] == [invoice.id]
    assert len(dispatched) == 1
    tenant_id, event_type, _payload = dispatched[0]
    assert tenant_id == TENANT_ID
    assert event_type == "outbound_invoice.overdue"

    db_session.refresh(invoice)
    assert invoice.overdue_notified_at is not None
    # The sweep must not invent an OVERDUE status -- overdue stays virtual.
    assert invoice.status == "SENT"


def test_due_today_is_not_overdue_yet(db_session, dispatched):
    """Same boundary as routers/outbound_dashboard.py's is_overdue: strictly
    past due_date. Off-by-one here means notifying customers a day early."""
    _seed_invoice(db_session, due_days_ago=0)

    assert overdue.sweep_overdue_invoices(db_session, today=TODAY) == []
    assert dispatched == []


def test_future_due_date_is_not_a_candidate(db_session, dispatched):
    _seed_invoice(db_session, due_days_ago=-7)

    assert overdue.sweep_overdue_invoices(db_session, today=TODAY) == []
    assert dispatched == []


def test_missing_due_date_can_never_be_overdue(db_session, dispatched):
    _seed_invoice(db_session, due_days_ago=None)

    assert overdue.sweep_overdue_invoices(db_session, today=TODAY) == []
    assert dispatched == []


@pytest.mark.parametrize("status", ["PAID", "UPLOADED", "REJECTED", "NEEDS_REVIEW"])
def test_non_sent_statuses_are_never_candidates(db_session, dispatched, status):
    _seed_invoice(db_session, status=status, due_days_ago=90)

    assert overdue.sweep_overdue_invoices(db_session, today=TODAY) == []
    assert dispatched == []


def test_inbound_invoices_are_never_candidates(db_session, dispatched):
    """AR-only event. An inbound (vendor) invoice past its due date is the
    tenant's own payable, not something to notify their webhook about."""
    _seed_invoice(db_session, direction="INBOUND", due_days_ago=30)

    assert overdue.sweep_overdue_invoices(db_session, today=TODAY) == []
    assert dispatched == []


def test_tenant_scoped_sweep_ignores_other_tenants(db_session, dispatched):
    mine = _seed_invoice(db_session, tenant_id=TENANT_ID)
    _seed_invoice(db_session, tenant_id=OTHER_TENANT_ID)

    notified = overdue.sweep_overdue_invoices(db_session, today=TODAY, tenant_id=TENANT_ID)

    assert [inv.id for inv in notified] == [mine.id]
    assert len(dispatched) == 1


# ---------------------------------------------------------------------------
# Idempotency -- the reason overdue_notified_at exists
# ---------------------------------------------------------------------------


def test_second_sweep_does_not_refire(db_session, dispatched):
    """The invoice is still SENT and still past due on the next run (and every
    run after that) -- without the marker this would be a daily re-delivery."""
    _seed_invoice(db_session, due_days_ago=5)

    first = overdue.sweep_overdue_invoices(db_session, today=TODAY)
    second = overdue.sweep_overdue_invoices(db_session, today=TODAY)

    assert len(first) == 1
    assert second == []
    assert len(dispatched) == 1


def test_sweep_on_a_later_day_still_does_not_refire(db_session, dispatched):
    _seed_invoice(db_session, due_days_ago=5)

    overdue.sweep_overdue_invoices(db_session, today=TODAY)
    later = overdue.sweep_overdue_invoices(db_session, today=TODAY + timedelta(days=30))

    assert later == []
    assert len(dispatched) == 1


def test_already_notified_invoice_is_skipped(db_session, dispatched):
    _seed_invoice(db_session, due_days_ago=5, overdue_notified_at=datetime(2026, 8, 1))

    assert overdue.find_overdue_invoices(db_session, today=TODAY) == []
    assert overdue.sweep_overdue_invoices(db_session, today=TODAY) == []
    assert dispatched == []


def test_marker_is_stamped_even_when_dispatch_raises(db_session, monkeypatch):
    """A failing endpoint must not become a re-delivery loop: the sweep is
    at-most-once by design (marker committed before dispatch)."""
    invoice = _seed_invoice(db_session, due_days_ago=5)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("subscriber lookup exploded")

    monkeypatch.setattr(overdue, "dispatch_webhook_event", _boom)

    notified = overdue.sweep_overdue_invoices(db_session, today=TODAY)

    assert [inv.id for inv in notified] == [invoice.id]
    db_session.refresh(invoice)
    assert invoice.overdue_notified_at is not None
    assert overdue.find_overdue_invoices(db_session, today=TODAY) == []


def test_one_failing_dispatch_does_not_starve_the_rest(db_session, monkeypatch):
    first = _seed_invoice(db_session, due_days_ago=9, customer_name="First")
    second = _seed_invoice(db_session, due_days_ago=8, customer_name="Second")

    seen: list[str] = []

    def _fail_first(_session, _tenant_id, _event_type, payload):
        seen.append(payload["invoice_id"])
        if payload["invoice_id"] == str(first.id):
            raise RuntimeError("delivery blew up")

    monkeypatch.setattr(overdue, "dispatch_webhook_event", _fail_first)

    notified = overdue.sweep_overdue_invoices(db_session, today=TODAY)

    assert {inv.id for inv in notified} == {first.id, second.id}
    assert set(seen) == {str(first.id), str(second.id)}


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_payload_carries_the_overdue_specific_fields(db_session, dispatched):
    invoice = _seed_invoice(db_session, due_days_ago=12)

    overdue.sweep_overdue_invoices(db_session, today=TODAY)

    _tenant_id, _event_type, payload = dispatched[0]
    assert payload["invoice_id"] == str(invoice.id)
    assert payload["status"] == "SENT"
    assert payload["customer_name"] == "Acme Corp"
    assert payload["grand_total"] == 1200.50
    assert payload["currency"] == "USD"
    assert payload["due_date"] == str(TODAY - timedelta(days=12))
    assert payload["days_overdue"] == 12


def test_no_subscriptions_still_marks_the_invoice(db_session):
    """Real dispatch_webhook_event (not the fake): with no WebhookSubscription
    rows it is a no-op, and the invoice must still be marked so the candidate
    set doesn't grow forever for tenants who never subscribe."""
    invoice = _seed_invoice(db_session, due_days_ago=3)

    notified = overdue.sweep_overdue_invoices(db_session, today=TODAY)

    assert [inv.id for inv in notified] == [invoice.id]
    db_session.refresh(invoice)
    assert invoice.overdue_notified_at is not None
