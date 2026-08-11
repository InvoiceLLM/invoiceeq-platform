"""
Gap 121: scheduled half of free-tier quota refill.

dependencies.get_tenant_context_allow_unpaid() already refills a due free
tenant lazily on their next request. That covers active users, but not an idle
tenant who exhausts their 50 and stops showing up — their free_invoices_remaining
stays stale for any reporting query reading the column.

This script closes that hole. Idempotent: an in-cycle tenant is not refilled
again. Tenants with NULL free_quota_reset_at are skipped (clock starts on first
live request, not via this sweep).

Usage:
    uv run python scripts/sweep_free_quotas.py [--dry-run]

Prefer scripts/sweep_billing_lifecycle.py in scheduled jobs (runs lapse + free).
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
    is_free_quota_due,
    sweep_free_quotas,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refill free-tier quotas whose cycle has elapsed.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report who would be refilled without writing anything.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        if args.dry_run:
            candidates = session.exec(
                select(Tenant).where(
                    Tenant.billing_plan == FREE_PLAN,
                    Tenant.free_quota_reset_at.is_not(None),  # type: ignore[union-attr]
                )
            ).all()
            due = [tenant for tenant in candidates if is_free_quota_due(tenant)]
            for tenant in due:
                logger.info(
                    "[dry-run] would refill tenant=%s (%s) remaining=%s reset_at=%s",
                    tenant.id, tenant.domain, tenant.free_invoices_remaining, tenant.free_quota_reset_at,
                )
            logger.info("[dry-run] %s of %s free tenant(s) are due for refill.", len(due), len(candidates))
            return 0

        refilled = sweep_free_quotas(session)
        for tenant in refilled:
            logger.info(
                "Refilled tenant=%s (%s) remaining=%s",
                tenant.id, tenant.domain, tenant.free_invoices_remaining,
            )
        logger.info("Sweep complete: %s tenant(s) refilled.", len(refilled))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
