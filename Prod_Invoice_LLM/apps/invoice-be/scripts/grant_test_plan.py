"""
Gap 117: grant a tenant a paid plan on a deployed non-production environment,
for QA, without going through a real PayU checkout.

`dependencies.MOCK_BILLING_PLAN = "active"` only helps when ALLOW_MOCK_AUTH is
on, i.e. local dev with no real Clerk auth. On a deployed dev environment --
real Clerk, real tokens -- a tenant's plan comes from exactly one place:
routers/billing.py's verified PayU callback. So testing anything gated on
'pro'/'pro_combined' (outbound/Vendor Flow, the 402 gate, plan-scoped settings)
meant running a full PayU sandbox checkout, by hand, per tenant, every time a
cycle lapsed. The /admin console added in Gap 104 edits a user's *role*, never
`billing_plan`, so it is no help either.

This script is the missing QA affordance: it writes the same two columns the
PayU callback writes (`billing_plan`, `paid_through`) directly, reusing
services/billing_lifecycle.extend_paid_through() so the date arithmetic can
never drift from the real payment path. `payu_subscription_id` is deliberately
NOT set -- there is no transaction, and forging a txnid would make a
hand-granted plan indistinguishable from a paid one in support queries.

Safety
------
Two independent guards, both of which must pass:

1. `settings.ENVIRONMENT` must name a known non-production environment.
   That setting defaults to "production" (see config.py), so an environment
   that never declared itself refuses -- the unsafe state is the one you have
   to opt into.
2. `settings.PAYU_MODE` must not be "live". This is defence in depth against
   the obvious failure mode of guard 1: someone exporting ENVIRONMENT=dev in a
   shell that is pointed at the production database. PAYU_MODE is a value a
   real production deployment must have set to "live" for payments to work at
   all, so it is a much harder signal to fake by accident.

Neither is a security boundary -- anyone who can run this already has the
database credentials. They are there to stop an accident, and they are why this
script never becomes an API endpoint.

Usage:
    uv run python scripts/grant_test_plan.py --tenant acme.example.com --plan pro
    uv run python scripts/grant_test_plan.py --tenant <uuid> --plan pro_combined --cycles 12
    uv run python scripts/grant_test_plan.py --tenant acme.example.com --plan pro --dry-run
"""
import argparse
import logging
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from config import settings  # noqa: E402
from database import engine  # noqa: E402
from models import Tenant  # noqa: E402
from services.billing_lifecycle import PAID_PLANS, extend_paid_through  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Environments this script will run against. Anything not on this list --
# including the "production" default and including a typo -- is refused.
NON_PRODUCTION_ENVIRONMENTS = {"dev", "development", "local", "test", "testing", "qa", "staging"}

# How many BILLING_CYCLE_DAYS periods to grant by default. 12 (~1 year at the
# default 30-day cycle) is far enough out that a QA tenant never lapses
# mid-test-run, while still going through extend_paid_through() one cycle at a
# time rather than inventing a separate "far future" date format here.
DEFAULT_CYCLES = 12


class EnvironmentRefusal(RuntimeError):
    """Raised when the current environment is not one this script may touch."""


def assert_non_production(environment: str | None = None, payu_mode: str | None = None) -> str:
    """
    Hard-fail unless this process is pointed at a non-production environment.

    Returns the normalised environment name when it is safe to proceed; raises
    EnvironmentRefusal otherwise. Split out from main() so the guard itself is
    directly testable -- a safety check nothing exercises is not a safety check.
    """
    resolved = (environment if environment is not None else settings.ENVIRONMENT).strip().lower()
    mode = (payu_mode if payu_mode is not None else settings.PAYU_MODE).strip().lower()

    if resolved not in NON_PRODUCTION_ENVIRONMENTS:
        raise EnvironmentRefusal(
            f"Refusing to run: ENVIRONMENT={resolved!r} is not a known non-production "
            f"environment ({', '.join(sorted(NON_PRODUCTION_ENVIRONMENTS))}). "
            "This script mutates billing state directly and must never touch production. "
            "If this really is a dev/QA environment, set ENVIRONMENT explicitly."
        )

    if mode == "live":
        raise EnvironmentRefusal(
            f"Refusing to run: ENVIRONMENT={resolved!r} claims non-production but "
            "PAYU_MODE='live', which only a real production deployment should have. "
            "Check which database this process is actually pointed at."
        )

    return resolved


def resolve_tenant(db_session: Session, identifier: str) -> Tenant | None:
    """
    Find a tenant by id or domain. Tried in that order: a value that parses as a
    UUID is only ever looked up as an id, so a domain can never be silently
    matched against something that just happens to look like one.
    """
    try:
        tenant_id = UUID(identifier)
    except ValueError:
        return db_session.exec(select(Tenant).where(Tenant.domain == identifier)).first()
    return db_session.get(Tenant, tenant_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grant a tenant a paid plan on a non-production environment (QA only).",
    )
    parser.add_argument("--tenant", required=True, help="Tenant id (UUID) or domain.")
    parser.add_argument(
        "--plan",
        required=True,
        choices=sorted(PAID_PLANS),
        help="Target plan.",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=DEFAULT_CYCLES,
        help=f"How many billing cycles of access to grant (default {DEFAULT_CYCLES}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args()

    if args.cycles < 1:
        logger.error("--cycles must be at least 1.")
        return 2

    try:
        environment = assert_non_production()
    except EnvironmentRefusal as exc:
        logger.error("%s", exc)
        return 1

    with Session(engine) as session:
        tenant = resolve_tenant(session, args.tenant)
        if not tenant:
            logger.error("No tenant found for %r (tried id, then domain).", args.tenant)
            return 1

        previous_plan = tenant.billing_plan
        previous_paid_through = tenant.paid_through

        if args.dry_run:
            logger.info(
                "[dry-run] env=%s tenant=%s (%s): plan %s -> %s, paid_through %s -> +%s cycle(s)",
                environment, tenant.id, tenant.domain, previous_plan, args.plan,
                previous_paid_through, args.cycles,
            )
            return 0

        tenant.billing_plan = args.plan
        # Reuse the real payment path's arithmetic, one cycle at a time, so a
        # granted plan is indistinguishable in shape from a paid one (and so
        # extend_paid_through() stays the single definition of "one cycle").
        for _ in range(args.cycles):
            extend_paid_through(tenant)
        session.add(tenant)
        session.commit()
        session.refresh(tenant)

        logger.info(
            "Granted on env=%s: tenant=%s (%s) plan %s -> %s, paid_through %s -> %s (%s cycle(s) of %sd)",
            environment, tenant.id, tenant.domain, previous_plan, tenant.billing_plan,
            previous_paid_through, tenant.paid_through, args.cycles, settings.BILLING_CYCLE_DAYS,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
