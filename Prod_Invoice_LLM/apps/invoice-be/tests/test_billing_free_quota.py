"""
Tests for Gap 118 (free-tier quota refills monthly instead of being a lifetime
cap) and Gap 117 (scripts/grant_test_plan.py's non-production guard).

Written against the same shape as tests/test_billing_lapse.py, because the
production code is the same shape: Gap 118 is Gap 71's date-driven state change
run in the opposite direction. As there, the assertions are on persisted state
transitions and their absence, not just on helper return values -- the bug was
never that a helper returned the wrong thing, it was that nothing wrote the
column at all.

Coverage
--------
Date arithmetic (is_free_quota_due / advance_free_quota_reset_at)
1.  NULL free_quota_reset_at is never due (pre-migration rows, and tenants who
    have never been on the free plan).
2.  A non-free plan is never due even with a long-past reset date.
3.  Before the deadline is not due; on/after it is.
4.  Advancing from unset lands exactly one cycle out.
5.  Advancing from a stale date keeps the original anniversary instead of
    drifting to "now + cycle".
6.  ...including when several whole cycles have been missed.

Refill (refresh_free_quota)
7.  A due free tenant is refilled to DEFAULT_FREE_INVOICES_LIMIT and persisted.
8.  A free tenant with no clock yet has it seeded WITHOUT a refill -- this is
    what stops the deploy itself from being a mass grant of 50 invoices.
9.  A free tenant inside its cycle is untouched.
10. Paid and unpaid plans are never refilled ('unpaid' especially: refilling it
    would undo Gap 71's demotion).
11. Refilling twice in the same cycle doesn't stack.

Integration with the request path
12. A due free tenant is refilled on its next request, no upload needed.
13. ...and can then actually upload again after having been exhausted, which is
    the user-visible bug this gap was about.
14. An exhausted free tenant inside its cycle still gets 402 "Limit reached".
15. A tenant demoted to 'unpaid' on the very same request is not handed a fresh
    free allowance by the refill that runs right after the lapse check.

Gap 117 (grant_test_plan.py)
16. The guard refuses the default/production ENVIRONMENT.
17. The guard refuses an unrecognised ENVIRONMENT rather than assuming dev.
18. The guard accepts known non-production names, case/whitespace insensitively.
19. The guard refuses a "dev" environment that is nonetheless running PAYU_MODE
    live.
20. resolve_tenant() finds a tenant by id and by domain, and returns None for
    an unknown value of either shape.
21. The granted plan is one PAID_PLANS accepts, and the grant reuses
    extend_paid_through() so it lands N whole cycles out.
"""
import importlib.util
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from config import settings
from dependencies import MOCK_TENANT_ID, get_db_session
from main import app
from models import Tenant
from services.billing_lifecycle import (
    LAPSED_PLAN,
    advance_free_quota_reset_at,
    extend_paid_through,
    is_free_quota_due,
    refresh_free_quota,
    sweep_free_quotas,
)

# scripts/ is not a package (it is a folder of standalone entrypoints, see
# sweep_lapsed_billing.py), so it is loaded by path rather than imported.
_GRANT_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "grant_test_plan.py"
_spec = importlib.util.spec_from_file_location("grant_test_plan", _GRANT_SCRIPT_PATH)
grant_test_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grant_test_plan)

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


CYCLE = timedelta(days=settings.FREE_QUOTA_CYCLE_DAYS)


def _seed_tenant(
    db_session: Session,
    tenant_id: UUID = MOCK_TENANT_ID,
    plan: str = "free",
    remaining: int = 0,
    free_quota_reset_at: datetime | None = None,
    paid_through: datetime | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id,
        name="Test Workspace",
        domain=f"{tenant_id}.example.com",
        billing_plan=plan,
        free_invoices_remaining=remaining,
        free_quota_reset_at=free_quota_reset_at,
        paid_through=paid_through,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _pdf(name: str = "invoice.pdf") -> tuple[str, tuple[str, BytesIO, str]]:
    return ("files", (name, BytesIO(b"%PDF-1.4 test"), "application/pdf"))


# ---------------------------------------------------------------------------
# 1-3. is_free_quota_due
# ---------------------------------------------------------------------------

def test_null_reset_at_is_never_due():
    """Every row predating the migration has NULL here. Treating it as due
    would hand the whole free tier an extra 50 invoices on deploy."""
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="free", free_quota_reset_at=None)
    assert is_free_quota_due(tenant) is False


@pytest.mark.parametrize("plan", ["pro", "pro_combined", "unpaid", "active"])
def test_non_free_plans_are_never_due(plan):
    tenant = Tenant(
        name="T", domain="t.example.com", billing_plan=plan,
        free_quota_reset_at=datetime.utcnow() - timedelta(days=365),
    )
    assert is_free_quota_due(tenant) is False


def test_due_only_once_the_deadline_has_arrived():
    now = datetime(2026, 8, 4, 12, 0, 0)
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="free", free_quota_reset_at=now)

    assert is_free_quota_due(tenant, now=now - timedelta(seconds=1)) is False
    assert is_free_quota_due(tenant, now=now) is True
    assert is_free_quota_due(tenant, now=now + timedelta(days=1)) is True


# ---------------------------------------------------------------------------
# 4-6. advance_free_quota_reset_at
# ---------------------------------------------------------------------------

def test_advance_from_unset_is_one_cycle_out():
    now = datetime(2026, 8, 4, 12, 0, 0)
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="free")

    assert advance_free_quota_reset_at(tenant, now=now) == now + CYCLE
    assert tenant.free_quota_reset_at == now + CYCLE


def test_advance_keeps_the_original_anniversary():
    """Advancing must move to the next boundary of the *existing* schedule, not
    reset the schedule to whenever the tenant happened to come back -- otherwise
    a tenant's refill date drifts later every time they are idle."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    due = now - timedelta(days=1)
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="free", free_quota_reset_at=due)

    assert advance_free_quota_reset_at(tenant, now=now) == due + CYCLE


def test_advance_skips_whole_missed_cycles_in_one_pass():
    now = datetime(2026, 8, 4, 12, 0, 0)
    due = now - 3 * CYCLE - timedelta(days=1)
    tenant = Tenant(name="T", domain="t.example.com", billing_plan="free", free_quota_reset_at=due)

    result = advance_free_quota_reset_at(tenant, now=now)

    assert result == due + 4 * CYCLE
    assert result > now


# ---------------------------------------------------------------------------
# 7-11. refresh_free_quota
# ---------------------------------------------------------------------------

def test_due_tenant_is_refilled_and_persisted(db_session):
    tenant = _seed_tenant(
        db_session, remaining=0, free_quota_reset_at=datetime.utcnow() - timedelta(days=1)
    )

    assert refresh_free_quota(tenant, db_session) is True

    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.free_invoices_remaining == settings.DEFAULT_FREE_INVOICES_LIMIT
    assert reloaded.free_quota_reset_at > datetime.utcnow()


def test_unset_clock_is_seeded_without_granting_a_refill(db_session):
    """The migration deliberately backfills nothing, so the first sighting of a
    tenant must start the clock and leave the balance alone. If this ever
    started returning True, deploying would silently top every free tenant in
    the database back up to 50."""
    tenant = _seed_tenant(db_session, remaining=7, free_quota_reset_at=None)

    assert refresh_free_quota(tenant, db_session) is False

    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.free_invoices_remaining == 7
    assert reloaded.free_quota_reset_at is not None
    assert reloaded.free_quota_reset_at > datetime.utcnow()


def test_tenant_inside_its_cycle_is_untouched(db_session):
    tenant = _seed_tenant(
        db_session, remaining=3, free_quota_reset_at=datetime.utcnow() + timedelta(days=5)
    )

    assert refresh_free_quota(tenant, db_session) is False
    assert db_session.get(Tenant, tenant.id).free_invoices_remaining == 3


@pytest.mark.parametrize("plan", ["pro", "pro_combined", "unpaid", "active"])
def test_non_free_plans_are_never_refilled(db_session, plan):
    """'unpaid' matters most here: it is what Gap 71 demotes a lapsed payer to,
    and refilling it would quietly hand them a free tier as a reward."""
    tenant = _seed_tenant(
        db_session, tenant_id=uuid4(), plan=plan, remaining=0,
        free_quota_reset_at=datetime.utcnow() - timedelta(days=365),
    )

    assert refresh_free_quota(tenant, db_session) is False

    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.free_invoices_remaining == 0
    assert reloaded.free_quota_reset_at is not None  # untouched, not seeded


def test_second_refresh_in_the_same_cycle_is_a_noop(db_session):
    tenant = _seed_tenant(
        db_session, remaining=0, free_quota_reset_at=datetime.utcnow() - timedelta(days=1)
    )

    assert refresh_free_quota(tenant, db_session) is True
    tenant.free_invoices_remaining -= 4
    db_session.add(tenant)
    db_session.commit()

    assert refresh_free_quota(tenant, db_session) is False
    assert db_session.get(Tenant, tenant.id).free_invoices_remaining == (
        settings.DEFAULT_FREE_INVOICES_LIMIT - 4
    )


# ---------------------------------------------------------------------------
# 12-15. The per-request lazy check
# ---------------------------------------------------------------------------

def test_due_tenant_is_refilled_on_the_next_request(db_session):
    tenant = _seed_tenant(
        db_session, remaining=0, free_quota_reset_at=datetime.utcnow() - timedelta(days=1)
    )

    client.get("/api/v1/dashboard/metrics")

    db_session.expire_all()
    assert db_session.get(Tenant, tenant.id).free_invoices_remaining == (
        settings.DEFAULT_FREE_INVOICES_LIMIT
    )


def test_exhausted_tenant_can_upload_again_after_the_cycle_turns(db_session):
    """The user-visible bug: before this gap, a free tenant that hit 0 was
    permanently blocked, because nothing ever put the counter back."""
    tenant = _seed_tenant(
        db_session, remaining=0, free_quota_reset_at=datetime.utcnow() - timedelta(days=1)
    )

    # Same stubs test_ingestion.py uses -- blob storage and the queue are not
    # what this test is about.
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient"):
        mock_storage.return_value = "mock/path/invoice.pdf"
        response = client.post("/api/v1/invoices/upload", files=[_pdf()])

    assert response.status_code == 201
    db_session.expire_all()
    # Refilled to 50 by the dependency, then decremented by this one upload.
    assert db_session.get(Tenant, tenant.id).free_invoices_remaining == (
        settings.DEFAULT_FREE_INVOICES_LIMIT - 1
    )


def test_exhausted_tenant_inside_its_cycle_is_still_blocked(db_session):
    """The refill must not become a way around the quota -- inside the cycle the
    402 has to keep firing exactly as before."""
    _seed_tenant(db_session, remaining=0, free_quota_reset_at=datetime.utcnow() + timedelta(days=5))

    response = client.post("/api/v1/invoices/upload", files=[_pdf()])

    assert response.status_code == 402
    assert response.json()["detail"] == "Limit reached"


def test_lapsed_tenant_is_not_handed_a_free_allowance_by_the_refill(db_session):
    """refresh_free_quota() runs immediately after enforce_lapse() in the same
    request. A tenant demoted to 'unpaid' on that very request must stay
    blocked, not fall through into the free tier."""
    tenant = _seed_tenant(
        db_session, plan="pro", remaining=0,
        paid_through=datetime.utcnow() - timedelta(days=settings.BILLING_GRACE_PERIOD_DAYS + 1),
        free_quota_reset_at=datetime.utcnow() - timedelta(days=1),
    )

    response = client.get("/api/v1/dashboard/metrics")

    assert response.status_code == 402
    db_session.expire_all()
    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.billing_plan == LAPSED_PLAN
    assert reloaded.free_invoices_remaining == 0


# ---------------------------------------------------------------------------
# 16-21. Gap 117: scripts/grant_test_plan.py
# ---------------------------------------------------------------------------

def test_guard_refuses_production():
    with pytest.raises(grant_test_plan.EnvironmentRefusal):
        grant_test_plan.assert_non_production(environment="production", payu_mode="test")


def test_guard_refuses_an_unrecognised_environment():
    """Fail closed on a typo or a name nobody thought of, rather than assuming
    anything that isn't literally 'production' is safe."""
    with pytest.raises(grant_test_plan.EnvironmentRefusal):
        grant_test_plan.assert_non_production(environment="prod-eu", payu_mode="test")


@pytest.mark.parametrize("environment", ["dev", "Development", "  local  ", "STAGING", "qa"])
def test_guard_accepts_known_non_production_names(environment):
    assert grant_test_plan.assert_non_production(environment=environment, payu_mode="test") == (
        environment.strip().lower()
    )


def test_guard_refuses_live_payu_even_when_environment_says_dev():
    """Defence in depth against the realistic accident: exporting
    ENVIRONMENT=dev in a shell pointed at the production database."""
    with pytest.raises(grant_test_plan.EnvironmentRefusal):
        grant_test_plan.assert_non_production(environment="dev", payu_mode="live")


def test_resolve_tenant_by_id_and_by_domain(db_session):
    tenant = _seed_tenant(db_session, tenant_id=uuid4())

    assert grant_test_plan.resolve_tenant(db_session, str(tenant.id)).id == tenant.id
    assert grant_test_plan.resolve_tenant(db_session, tenant.domain).id == tenant.id
    assert grant_test_plan.resolve_tenant(db_session, str(uuid4())) is None
    assert grant_test_plan.resolve_tenant(db_session, "nobody.example.com") is None


def test_grant_moves_the_tenant_onto_a_paid_plan_for_n_cycles(db_session):
    """Mirrors what main() does to the row, without driving argparse/the real
    engine: the plan must be one PAID_PLANS accepts (so is_lapsed() can see it)
    and paid_through must land N whole BILLING_CYCLE_DAYS out."""
    tenant = _seed_tenant(db_session, tenant_id=uuid4(), plan="free")
    cycles = grant_test_plan.DEFAULT_CYCLES

    assert "pro_combined" in grant_test_plan.PAID_PLANS
    tenant.billing_plan = "pro_combined"
    for _ in range(cycles):
        extend_paid_through(tenant)
    db_session.add(tenant)
    db_session.commit()

    reloaded = db_session.get(Tenant, tenant.id)
    assert reloaded.billing_plan == "pro_combined"
    expected = datetime.utcnow() + cycles * timedelta(days=settings.BILLING_CYCLE_DAYS)
    assert abs((reloaded.paid_through - expected).total_seconds()) < 60
    # And the granted tenant is genuinely not lapsed, which is the entire point.
    assert reloaded.paid_through > datetime.utcnow()


# ---------------------------------------------------------------------------
# Gap 121: sweep_free_quotas (idle free tenants)
# ---------------------------------------------------------------------------

def test_sweep_free_quotas_refills_only_due_tenants(db_session):
    due = _seed_tenant(
        db_session,
        tenant_id=uuid4(),
        remaining=0,
        free_quota_reset_at=datetime.utcnow() - timedelta(days=1),
    )
    not_due = _seed_tenant(
        db_session,
        tenant_id=uuid4(),
        remaining=3,
        free_quota_reset_at=datetime.utcnow() + timedelta(days=5),
    )
    no_clock = _seed_tenant(
        db_session,
        tenant_id=uuid4(),
        remaining=0,
        free_quota_reset_at=None,
    )
    paid = _seed_tenant(
        db_session,
        tenant_id=uuid4(),
        plan="pro",
        remaining=0,
        free_quota_reset_at=datetime.utcnow() - timedelta(days=1),
    )

    refilled = sweep_free_quotas(db_session)

    assert [t.id for t in refilled] == [due.id]
    assert db_session.get(Tenant, due.id).free_invoices_remaining == settings.DEFAULT_FREE_INVOICES_LIMIT
    assert db_session.get(Tenant, not_due.id).free_invoices_remaining == 3
    assert db_session.get(Tenant, no_clock.id).free_quota_reset_at is None
    assert db_session.get(Tenant, paid.id).billing_plan == "pro"


def test_sweep_free_quotas_is_idempotent(db_session):
    _seed_tenant(
        db_session,
        tenant_id=uuid4(),
        remaining=0,
        free_quota_reset_at=datetime.utcnow() - timedelta(days=1),
    )

    assert len(sweep_free_quotas(db_session)) == 1
    assert sweep_free_quotas(db_session) == []
