"""
Gap 71: the "other half" of the billing lifecycle.

`routers/billing.py` moves a tenant *forward* onto a paid plan when a payment
verifies. Nothing ever moved one *backward* when a cycle lapsed without a new
payment -- so `dependencies.get_tenant_context()`'s 402 gate, which is real and
correct, could never fire. A tenant could pay once and keep paid-tier access
indefinitely.

PayU's classic hash-based API has no subscription object and no
"subscription.cancelled" webhook to react to (see feature_11_billing.md for the
provider decision), so lapse is necessarily *inferred from a date*, not
received as an event. This module owns that date arithmetic in one place so the
two callers -- the lazy per-request check in dependencies.py and the batch
sweep in scripts/sweep_lapsed_billing.py -- can never drift apart on what
"lapsed" means.

Two deliberate non-behaviours:

* `paid_through IS NULL` is never lapsed. NULL means "never completed a paid
  checkout" -- true for every free-tier tenant and for every pre-Gap-71 row.
  Treating NULL as lapsed would have locked out real paying customers the
  moment the migration landed.
* Only PAID_PLANS lapse. `free` has its own enforcement (the
  `free_invoices_remaining` quota in routers/invoices.py), and the mock
  `active` plan exists only for the test/dev auth fallback.

Gap 118 added the free tier's mirror image to this same module. Lapse moves a
paid tenant *down* when a date passes; the free-quota refill moves a free
tenant's allowance back *up* when a date passes. Same inputs (a column on
Tenant plus a cycle length from settings), same two call-site story (lazy in
dependencies.py; a batch sweep for idle tenants, which is Gap 121 and does not
exist yet), so they live together rather than in a second module that would
inevitably drift on the date arithmetic.
"""
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, select

from config import settings
from models import Tenant

logger = logging.getLogger(__name__)

# Plans that are paid for a period and can therefore lapse. Kept in sync with
# routers/billing.py::PLAN_AMOUNTS by intent: anything a tenant can check out
# for is something they can stop paying for.
PAID_PLANS = {"pro", "pro_combined"}

# What a lapsed tenant is demoted to. Deliberately "unpaid" and not "free":
# "free" would silently hand them a fresh 50-invoice quota as a reward for not
# paying. "unpaid" is the state dependencies.get_tenant_context() already
# blocks with a 402.
LAPSED_PLAN = "unpaid"

# Gap 118: the only plan whose invoice allowance refills on a cycle. Paid plans
# have no `free_invoices_remaining` enforcement at all (routers/invoices.py
# checks it only when billing_plan == "free"), and "unpaid" must not refill --
# see the LAPSED_PLAN comment above for why that would be backwards.
FREE_PLAN = "free"


def extend_paid_through(tenant: Tenant, now: datetime | None = None) -> datetime:
    """
    Push `tenant.paid_through` forward by one billing cycle and return the new
    value. Does not commit -- the caller owns the transaction.

    Extends from whichever is later, `now` or the existing `paid_through`, so a
    tenant who renews early keeps the days they already paid for instead of
    having them silently reset. Mutates the tenant in place.
    """
    now = now or datetime.utcnow()
    base = tenant.paid_through if tenant.paid_through and tenant.paid_through > now else now
    tenant.paid_through = base + timedelta(days=settings.BILLING_CYCLE_DAYS)
    return tenant.paid_through


def lapse_deadline(tenant: Tenant) -> datetime | None:
    """The instant after which this tenant counts as lapsed, grace included."""
    if tenant.paid_through is None:
        return None
    return tenant.paid_through + timedelta(days=settings.BILLING_GRACE_PERIOD_DAYS)


def is_lapsed(tenant: Tenant, now: datetime | None = None) -> bool:
    """
    True when this tenant is on a paid plan whose paid-for period (plus grace)
    has passed. See the module docstring for why NULL and non-paid plans are
    excluded.
    """
    if tenant.billing_plan not in PAID_PLANS:
        return False
    deadline = lapse_deadline(tenant)
    if deadline is None:
        return False
    return (now or datetime.utcnow()) > deadline


def enforce_lapse(tenant: Tenant, db_session: Session, now: datetime | None = None) -> bool:
    """
    If `tenant` has lapsed, demote it to LAPSED_PLAN and commit. Returns whether
    a demotion actually happened.

    Persisting the demotion (rather than computing "lapsed" on the fly every
    request) is what makes this observable: the tenant row itself shows the
    state, so support/admin queries and the existing 402 gate both see the same
    thing without needing to re-derive it.
    """
    if not is_lapsed(tenant, now):
        return False

    previous_plan = tenant.billing_plan
    tenant.billing_plan = LAPSED_PLAN
    tenant.updated_at = datetime.utcnow()
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    logger.warning(
        "Billing lapse enforced: tenant=%s plan %s -> %s (paid_through=%s, grace=%sd)",
        tenant.id,
        previous_plan,
        LAPSED_PLAN,
        tenant.paid_through,
        settings.BILLING_GRACE_PERIOD_DAYS,
    )
    return True


def sweep_lapsed_tenants(db_session: Session, now: datetime | None = None) -> list[Tenant]:
    """
    Batch form of enforce_lapse() for a scheduled job
    (scripts/sweep_lapsed_billing.py). Returns the tenants that were demoted.

    Exists alongside the per-request lazy check rather than instead of it: the
    lazy check only fires for tenants who are actively making requests, so an
    idle lapsed tenant would otherwise sit on a paid plan in the database
    indefinitely -- invisible to any billing/reporting query that reads the
    column rather than re-deriving it.
    """
    now = now or datetime.utcnow()
    candidates = db_session.exec(
        select(Tenant).where(
            Tenant.billing_plan.in_(PAID_PLANS),  # type: ignore[attr-defined]
            Tenant.paid_through.is_not(None),     # type: ignore[union-attr]
        )
    ).all()

    demoted = [tenant for tenant in candidates if enforce_lapse(tenant, db_session, now)]
    logger.info("Billing lapse sweep: %s candidate(s) checked, %s demoted.", len(candidates), len(demoted))
    return demoted


# ---------------------------------------------------------------------------
# Gap 118: free-tier quota refill -- the mirror image of the lapse logic above.
# ---------------------------------------------------------------------------


def free_quota_deadline(tenant: Tenant) -> datetime | None:
    """
    The instant at which this tenant's free allowance refills, or None when the
    question doesn't apply (not on the free plan, or the cycle clock has never
    been started for this row).
    """
    if tenant.billing_plan != FREE_PLAN:
        return None
    return tenant.free_quota_reset_at


def is_free_quota_due(tenant: Tenant, now: datetime | None = None) -> bool:
    """
    True when this free-plan tenant's allowance has reached its refill date.

    NULL `free_quota_reset_at` is deliberately False, not True -- exactly as
    NULL `paid_through` is never lapsed. It means "no cycle has been observed
    for this tenant yet", so treating it as due would hand every pre-migration
    row an immediate extra allowance the moment this deployed.
    """
    deadline = free_quota_deadline(tenant)
    if deadline is None:
        return False
    return (now or datetime.utcnow()) >= deadline


def advance_free_quota_reset_at(tenant: Tenant, now: datetime | None = None) -> datetime:
    """
    Move `tenant.free_quota_reset_at` to the next boundary strictly in the
    future and return it. Does not commit -- the caller owns the transaction.

    Unset (or somehow in the future already) means start one cycle from now.
    Otherwise it advances by whole cycles from the existing date rather than
    resetting to `now + cycle`, so a tenant who was idle for three months lands
    back on their original monthly anniversary instead of having it silently
    drift to whenever they happened to come back. This is the same
    "extend from the existing date, not from now" intent as
    extend_paid_through(), applied to a date that may be many cycles stale.
    """
    now = now or datetime.utcnow()
    cycle = timedelta(days=settings.FREE_QUOTA_CYCLE_DAYS)
    current = tenant.free_quota_reset_at
    if current is None or current > now:
        tenant.free_quota_reset_at = now + cycle
        return tenant.free_quota_reset_at

    elapsed_cycles = (now - current) // cycle
    tenant.free_quota_reset_at = current + (elapsed_cycles + 1) * cycle
    return tenant.free_quota_reset_at


def refresh_free_quota(tenant: Tenant, db_session: Session, now: datetime | None = None) -> bool:
    """
    Refill a free-plan tenant's invoice allowance if its cycle has elapsed, and
    commit. Returns whether an actual refill happened.

    Three distinct outcomes, only one of which is a refill:

    * Not on the free plan -> nothing at all. Paid plans don't consult
      `free_invoices_remaining`, and 'unpaid' must never be handed a fresh
      allowance (that is the whole reason LAPSED_PLAN isn't 'free').
    * On the free plan with no cycle clock yet -> seed
      `free_quota_reset_at` one cycle out and commit, but leave the counter
      alone, and return False. Whatever balance the tenant already has is
      theirs; they simply get their first refill one full cycle from now. This
      is what makes the migration backfill-free and stops the deploy itself
      from being a mass grant of 50 invoices.
    * On the free plan and past the deadline -> counter back to
      DEFAULT_FREE_INVOICES_LIMIT, deadline advanced, commit, return True.

    Like enforce_lapse(), the result is persisted rather than derived on read,
    so `free_invoices_remaining` in the database is always the number
    routers/invoices.py will actually enforce.
    """
    if tenant.billing_plan != FREE_PLAN:
        return False

    if tenant.free_quota_reset_at is None:
        advance_free_quota_reset_at(tenant, now)
        tenant.updated_at = datetime.utcnow()
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)
        logger.info(
            "Free quota cycle started: tenant=%s remaining=%s next_reset=%s",
            tenant.id,
            tenant.free_invoices_remaining,
            tenant.free_quota_reset_at,
        )
        return False

    if not is_free_quota_due(tenant, now):
        return False

    previous_remaining = tenant.free_invoices_remaining
    tenant.free_invoices_remaining = settings.DEFAULT_FREE_INVOICES_LIMIT
    advance_free_quota_reset_at(tenant, now)
    tenant.updated_at = datetime.utcnow()
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    logger.info(
        "Free quota refilled: tenant=%s remaining %s -> %s (next_reset=%s, cycle=%sd)",
        tenant.id,
        previous_remaining,
        tenant.free_invoices_remaining,
        tenant.free_quota_reset_at,
        settings.FREE_QUOTA_CYCLE_DAYS,
    )
    return True
