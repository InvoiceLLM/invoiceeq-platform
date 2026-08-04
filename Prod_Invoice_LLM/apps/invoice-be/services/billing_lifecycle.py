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
