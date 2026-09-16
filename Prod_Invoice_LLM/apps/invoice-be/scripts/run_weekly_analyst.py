"""Feature 33 Task 33.16 — Weekly ATLAS Analyst Job Runner.

WHAT THIS SCRIPT DOES
---------------------
Runs every Monday at 06:00 UTC (via caj-analyst-weekly-dev Container App Job).
Queries all active tenants and enqueues / executes an ATLAS tenant-scope run
for each tenant with clearance="exec" and clearance="ops".
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select

from database import engine
from models import Tenant
from queue_worker.analyst_handlers import enqueue_analyst_job, run_tenant_analyst
from config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("weekly_analyst")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run weekly ATLAS analyst job across tenants.")
    parser.add_argument("--sync", action="store_true", help="Run synchronously instead of enqueuing to Redis.")
    parser.add_argument("--limit", type=int, default=None, help="Cap on tenants to process.")
    args = parser.parse_args()

    settings = get_settings()
    logger.info("Starting weekly ATLAS analyst sweep (sync=%s, limit=%s)", args.sync, args.limit)

    with Session(engine) as session:
        # Pull distinct tenants from DB
        stmt = select(Tenant.id)
        if args.limit:
            stmt = stmt.limit(args.limit)
        tenant_ids = session.exec(stmt).all()

        logger.info("Found %d tenants to process", len(tenant_ids))

        success_count = 0
        error_count = 0

        for t_id in tenant_ids:
            try:
                if args.sync:
                    logger.info("Running sync tenant analyst for %s", t_id)
                    run_tenant_analyst(tenant_id=t_id, db_session=session, clearance="ops")
                    run_tenant_analyst(tenant_id=t_id, db_session=session, clearance="exec")
                else:
                    logger.info("Enqueuing analyst job for %s", t_id)
                    enqueue_analyst_job(tenant_id=t_id, clearance="ops")
                    enqueue_analyst_job(tenant_id=t_id, clearance="exec")
                success_count += 1
            except Exception as exc:
                logger.error("Error processing tenant %s: %s", t_id, exc, exc_info=True)
                error_count += 1

    logger.info("Weekly ATLAS sweep finished: %d succeeded, %d failed", success_count, error_count)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
