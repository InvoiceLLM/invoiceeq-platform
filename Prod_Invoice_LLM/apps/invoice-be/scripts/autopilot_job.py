"""
Feature 13: Tenant Autopilot — ACA Job Script (scripts/autopilot_job.py)

Entry point for the Azure Container Apps Job (cron-triggered in production).

For local development / manual testing:
    uv run python scripts/autopilot_job.py

In production, this script is packaged into the same Docker image as the
main backend and invoked by an Azure Container Apps Job on the configured
cron schedule. The ACA Job cron replaces Celery Beat — see feature_13_autopilot.md.

Exit codes:
    0 — all tenants synced successfully (or none configured)
    1 — one or more tenants failed; errors are logged
"""

import logging
import sys
import os

# Ensure the invoice-be package root is on sys.path when the script is called
# directly (e.g. python scripts/autopilot_job.py) without the package installed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_session
from services.autopilot_sync import run_sync_for_all_due_tenants

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("autopilot_job")


def main() -> int:
    """
    Runs the Autopilot sync for all configured tenants.
    Returns exit code 0 (success) or 1 (partial/total failure).
    """
    logger.info("=== Autopilot ACA Job starting ===")

    # Use a generator-style session so the DB connection is properly closed.
    db_gen = get_session()
    db_session = next(db_gen)

    had_error = False
    try:
        run_sync_for_all_due_tenants(db_session)
    except Exception as exc:
        logger.error("Autopilot job top-level failure: %s", exc, exc_info=True)
        had_error = True
    finally:
        try:
            next(db_gen)  # Advance generator to trigger the finally/close in get_session
        except StopIteration:
            pass

    logger.info("=== Autopilot ACA Job finished ===")
    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
