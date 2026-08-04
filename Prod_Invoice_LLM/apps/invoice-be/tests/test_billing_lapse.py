"""
Tests for Gap 71: billing lapse enforcement (services/billing_lifecycle.py plus
its two call sites -- routers/billing.py's payment path and dependencies.py's
per-request check).

The gap this covers is specifically that the *enforcement* half of billing was
dead code: the 402 gate existed and worked, but nothing ever set
billing_plan='unpaid', so a tenant could pay once and keep paid access forever.
These tests therefore assert on state transitions and their absence, not just
on helper return values.

Coverage
--------
Date arithmetic (extend_paid_through / is_lapsed)
1.  A first payment sets paid_through one cycle from now.
2.  Renewing early extends from the existing paid_through, not from now, so
    already-paid days are not lost.
3.  Renewing after expiry extends from now, not from the stale date, so a
    tenant doesn't buy a cycle that is already in the past.
4.  paid_through NULL is never lapsed (free tenants and pre-migration rows).
5.  A non-paid plan is never lapsed even with a long-past paid_through.
6.  Inside the grace window is not yet lapsed.
7.  Past the grace window is lapsed.

Enforcement (enforce_lapse / sweep_lapsed_tenants)
8.  enforce_lapse demotes a lapsed tenant to 'unpaid' and persists it.
9.  enforce_lapse is a no-op for a current tenant.
10. The sweep demotes only the lapsed tenants and leaves the others alone.
11. The sweep is idempotent -- a second run demotes nobody.

Integration with the request path
12. A verified PayU success sets paid_through (regression guard for the
    original gap: an upgrade with no date is unenforceable).
13. A lapsed tenant is demoted on its next request and gets a 402.
14. ...and the demotion is durable in the database, not just in the response.
15. A tenant inside grace is not demoted by a request.
16. Checkout stays reachable for an unpaid tenant -- otherwise lapse would be a
    one-way door with no way to pay again.
"""
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import routers.billing as billing
from config import settings
from dependencies import MOCK_TENANT_ID, get_db_session
from main import app
from models import Tenant
from services.billing_lifecycle import (
    LAPSED_PLAN,
    enforce_lapse,
    extend_paid_through,
    is_lapsed,
    sweep_lapsed_tenants,
)

TEST_KEY = "testmerchantkey"
TEST_SALT = "testmerchantsalt"

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)


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


@pytest.fixture(autouse=True)
def payu_credentials(monkeypatch):
    monkeypatch.setattr(billing.settings, "PAYU_MERCHANT_KEY", TEST_KEY)
    monkeypatch.setattr(billing.settings, "PAYU_MERCHANT_SALT", TEST_SALT)
    monkeypatch.setattr(billing.settings, "PAYU_MODE", "test")
    monkeypatch.setattr(billing.settings, "BACKEND_PUBLIC_URL", "https://website.example.com")
    monkeypatch.setattr(billing.settings, "PUBLIC_APP_URL", "https://website.example.com")
    yield


def _seed_tenant(
    db_session: Session,
    tenant_id: UUID = MOCK_TENANT_ID,
    plan: str = "pro",
    paid_through: datetime | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id,
        name="Test Workspace",
        domain=f"{tenant_id}.example.com",
        billing_plan=plan,
        paid_through=paid_through,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _lapsed_at(days_past_grace: int) -> datetime:
    """A paid_through far enough in the past to be past the grace window."""
    return datetime.utcnow() - timedelta(days=settings.BILLING_GRACE_PERIOD_DAYS + days_past_grace)


# ---------------------------------------------------------------------------
# 1-3. extend_paid_through
# ---------------------------------------------------------------------------

def test_first_payment_sets_one_cycle_from_now():
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="pro")
    now = datetime(2026, 8, 4, 12, 0, 0)

    result = extend_paid_through(tenant, now=now)

    assert result == now + timedelta(days=settings.BILLING_CYCLE_DAYS)
    assert tenant.paid_through == result


def test_early_renewal_extends_from_existing_paid_through():
    """Paying 5 days early must add a cycle to the *remaining* period, not
    restart it from today -- otherwise renewing early silently costs the tenant
    the days they had already bought."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    still_valid_until = now + timedelta(days=5)
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="pro", paid_through=still_valid_until)

    result = extend_paid_through(tenant, now=now)

    assert result == still_valid_until + timedelta(days=settings.BILLING_CYCLE_DAYS)


def test_late_renewal_extends_from_now_not_the_stale_date():
    """The mirror case: paying 40 days late must not buy a cycle that has
    already elapsed."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    expired = now - timedelta(days=40)
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="pro", paid_through=expired)

    result = extend_paid_through(tenant, now=now)

    assert result == now + timedelta(days=settings.BILLING_CYCLE_DAYS)


# ---------------------------------------------------------------------------
# 4-7. is_lapsed
# ---------------------------------------------------------------------------

def test_null_paid_through_is_never_lapsed():
    """Free tenants and every row that existed before the Gap 71 migration have
    NULL here. Lapsing them would lock out real customers on deploy."""
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="pro", paid_through=None)
    assert is_lapsed(tenant) is False


@pytest.mark.parametrize("plan", ["free", "unpaid", "active"])
def test_non_paid_plans_never_lapse(plan):
    tenant = Tenant(
        name="T", domain="t.example.com", billing_plan=plan,
        paid_through=datetime.utcnow() - timedelta(days=365),
    )
    assert is_lapsed(tenant) is False


def test_inside_grace_window_is_not_lapsed():
    """A payment landing a day late must not lock the tenant out."""
    tenant = Tenant(
        name="T", domain="t.example.com", billing_plan="pro",
        paid_through=datetime.utcnow() - timedelta(days=max(settings.BILLING_GRACE_PERIOD_DAYS - 1, 0)),
    )
    assert is_lapsed(tenant) is False


def test_past_grace_window_is_lapsed():
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="pro", paid_through=_lapsed_at(1))
    assert is_lapsed(tenant) is True


# ---------------------------------------------------------------------------
# 8-11. enforce_lapse / sweep_lapsed_tenants
# ---------------------------------------------------------------------------

def test_enforce_lapse_demotes_and_persists(db_session):
    tenant = _seed_tenant(db_session, plan="pro_combined", paid_through=_lapsed_at(1))

    assert enforce_lapse(tenant, db_session) is True

    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.billing_plan == LAPSED_PLAN


def test_enforce_lapse_is_a_noop_for_a_current_tenant(db_session):
    tenant = _seed_tenant(db_session, plan="pro", paid_through=datetime.utcnow() + timedelta(days=10))

    assert enforce_lapse(tenant, db_session) is False
    assert db_session.get(Tenant, tenant.id).billing_plan == "pro"


def test_sweep_demotes_only_the_lapsed(db_session):
    lapsed = _seed_tenant(db_session, tenant_id=uuid4(), plan="pro", paid_through=_lapsed_at(2))
    current = _seed_tenant(db_session, tenant_id=uuid4(), plan="pro_combined",
                           paid_through=datetime.utcnow() + timedelta(days=3))
    free = _seed_tenant(db_session, tenant_id=uuid4(), plan="free", paid_through=None)

    demoted = sweep_lapsed_tenants(db_session)

    assert [t.id for t in demoted] == [lapsed.id]
    assert db_session.get(Tenant, current.id).billing_plan == "pro_combined"
    assert db_session.get(Tenant, free.id).billing_plan == "free"


def test_sweep_is_idempotent(db_session):
    _seed_tenant(db_session, tenant_id=uuid4(), plan="pro", paid_through=_lapsed_at(2))

    assert len(sweep_lapsed_tenants(db_session)) == 1
    assert sweep_lapsed_tenants(db_session) == []


# ---------------------------------------------------------------------------
# 12. Payment sets the date (the missing piece the gap was about)
# ---------------------------------------------------------------------------

def test_verified_payment_sets_paid_through(db_session, monkeypatch):
    tenant = _seed_tenant(db_session, plan="free", paid_through=None)

    txnid = "txn_lapse_test_1"
    amount = "4999.00"
    productinfo = "InvoiceAI-pro"
    firstname = "Test"
    email = "billing@example.com"
    udf1 = str(tenant.id)
    response_hash = billing._response_hash("success", txnid, amount, productinfo, firstname, email, udf1)

    async def _fake_verify(_txnid):
        return "success"

    monkeypatch.setattr(billing, "_verify_payment_with_payu", _fake_verify)

    response = client.post(
        "/api/v1/billing/payu/success",
        data={
            "txnid": txnid, "status": "success", "amount": amount,
            "productinfo": productinfo, "firstname": firstname, "email": email,
            "udf1": udf1, "hash": response_hash,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.billing_plan == "pro"
    assert reloaded.paid_through is not None
    # One cycle forward, within a minute of "now" -- exact equality would race
    # the clock between the request and this assertion.
    expected = datetime.utcnow() + timedelta(days=settings.BILLING_CYCLE_DAYS)
    assert abs((reloaded.paid_through - expected).total_seconds()) < 60


# ---------------------------------------------------------------------------
# 13-16. The per-request lazy check
# ---------------------------------------------------------------------------

def test_lapsed_tenant_is_402d_on_the_next_request(db_session):
    _seed_tenant(db_session, plan="pro", paid_through=_lapsed_at(1))

    response = client.get("/api/v1/dashboard/metrics")

    assert response.status_code == 402
    assert "unpaid" in response.json()["detail"].lower()


def test_lapse_demotion_is_durable_not_just_a_response_code(db_session):
    """The whole point of persisting rather than computing on the fly: the
    tenant row itself has to show the state so support/reporting queries agree
    with the API."""
    tenant = _seed_tenant(db_session, plan="pro", paid_through=_lapsed_at(1))

    client.get("/api/v1/dashboard/metrics")

    db_session.expire_all()
    assert db_session.get(Tenant, tenant.id).billing_plan == LAPSED_PLAN


def test_tenant_inside_grace_is_not_demoted_by_a_request(db_session):
    tenant = _seed_tenant(
        db_session, plan="pro",
        paid_through=datetime.utcnow() - timedelta(days=max(settings.BILLING_GRACE_PERIOD_DAYS - 1, 0)),
    )

    response = client.get("/api/v1/dashboard/metrics")

    assert response.status_code != 402
    db_session.expire_all()
    assert db_session.get(Tenant, tenant.id).billing_plan == "pro"


def test_checkout_stays_reachable_for_an_unpaid_tenant(db_session):
    """Without this, lapse is a one-way door: every endpoint 402s including the
    one that takes the payment, so the tenant can never get back."""
    _seed_tenant(db_session, plan="unpaid", paid_through=_lapsed_at(1))

    response = client.post("/api/v1/billing/create-checkout-session", json={"plan": "pro"})

    assert response.status_code == 200
    assert response.json()["amount"] == "4999.00"
