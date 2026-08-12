"""
Gaps 119 + 121: one scheduled entrypoint for both billing lifecycle sweeps.

Runs paid-plan lapse demotion then free-tier quota refill, in that order
(lapse first so a tenant demoted to 'unpaid' cannot be handed a free refill
in the same pass — refresh_free_quota already no-ops non-free, but ordering
matches the lazy path in dependencies.py).

Usage:
    uv run python scripts/sweep_billing_lifecycle.py [--dry-run]

Azure Container Apps Job (infra/modules/compute/billing-lifecycle-job.bicep)
invokes this script daily.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from database import engine  # noqa: E402
from models import Tenant  # noqa: E402
from services.billing_lifecycle import (  # noqa: E402
    FREE_PLAN,
    PAID_PLANS,
    is_free_quota_due,
    is_lapsed,
    sweep_free_quotas,
    sweep_lapsed_tenants,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run paid lapse demotion then free-tier quota refill (Gaps 119/121)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report who would change without writing anything.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        if args.dry_run:
            paid = session.exec(
                select(Tenant).where(
                    Tenant.billing_plan.in_(PAID_PLANS),  # type: ignore[attr-defined]
                    Tenant.paid_through.is_not(None),  # type: ignore[union-attr]
                )
            ).all()
            lapsed = [t for t in paid if is_lapsed(t)]
            for tenant in lapsed:
                logger.info(
                    "[dry-run] would demote tenant=%s (%s) plan=%s paid_through=%s",
                    tenant.id, tenant.domain, tenant.billing_plan, tenant.paid_through,
                )
            logger.info("[dry-run] lapse: %s of %s paid tenant(s).", len(lapsed), len(paid))

            free = session.exec(
                select(Tenant).where(
                    Tenant.billing_plan == FREE_PLAN,
                    Tenant.free_quota_reset_at.is_not(None),  # type: ignore[union-attr]
                )
            ).all()
            due = [t for t in free if is_free_quota_due(t)]
            for tenant in due:
                logger.info(
                    "[dry-run] would refill tenant=%s (%s) remaining=%s reset_at=%s",
                    tenant.id, tenant.domain, tenant.free_invoices_remaining, tenant.free_quota_reset_at,
                )
            logger.info("[dry-run] free refill: %s of %s free tenant(s).", len(due), len(free))
            return 0

        demoted = sweep_lapsed_tenants(session)
        for tenant in demoted:
            logger.info("Demoted tenant=%s (%s) -> unpaid", tenant.id, tenant.domain)

        refilled = sweep_free_quotas(session)
        for tenant in refilled:
            logger.info(
                "Refilled tenant=%s (%s) remaining=%s",
                tenant.id, tenant.domain, tenant.free_invoices_remaining,
            )

        logger.info(
            "Billing lifecycle sweep complete: %s demoted, %s refilled.",
            len(demoted),
            len(refilled),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
