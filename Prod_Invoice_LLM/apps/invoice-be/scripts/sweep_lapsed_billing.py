"""
Gap 71: scheduled half of billing lapse enforcement.

dependencies.get_tenant_context_allow_unpaid() already demotes a lapsed tenant
lazily, on that tenant's next request. That covers every tenant who is actively
using the product, but not one who simply stops showing up -- their row would
sit on 'pro'/'pro_combined' forever, so any billing/reporting query reading
billing_plan (rather than re-deriving lapse from paid_through itself) would
overstate active paid tenants.

This script closes that hole. It is idempotent and safe to re-run: a tenant
already on 'unpaid' is no longer in PAID_PLANS, so it is not a candidate on the
next pass.

Usage:
    uv run python scripts/sweep_lapsed_billing.py [--dry-run]

Intended to run daily. No scheduler exists in this repo yet, so it is
deliberately a standalone entrypoint rather than a task registered with one --
it can be driven by an Azure Container Apps scheduled job, cron, or Task
Scheduler without any code change.
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
    PAID_PLANS,
    is_lapsed,
    sweep_lapsed_tenants,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Demote tenants whose paid billing cycle has lapsed.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report who would be demoted without writing anything.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        if args.dry_run:
            candidates = session.exec(
                select(Tenant).where(
                    Tenant.billing_plan.in_(PAID_PLANS),  # type: ignore[attr-defined]
                    Tenant.paid_through.is_not(None),     # type: ignore[union-attr]
                )
            ).all()
            lapsed = [tenant for tenant in candidates if is_lapsed(tenant)]
            for tenant in lapsed:
                logger.info(
                    "[dry-run] would demote tenant=%s (%s) plan=%s paid_through=%s",
                    tenant.id, tenant.domain, tenant.billing_plan, tenant.paid_through,
                )
            logger.info("[dry-run] %s of %s paid tenant(s) have lapsed.", len(lapsed), len(candidates))
            return 0

        demoted = sweep_lapsed_tenants(session)
        for tenant in demoted:
            logger.info("Demoted tenant=%s (%s) -> unpaid", tenant.id, tenant.domain)
        logger.info("Sweep complete: %s tenant(s) demoted.", len(demoted))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
