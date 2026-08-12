"""
Gap 126: scheduled entrypoint for the `outbound_invoice.overdue` webhook.

Overdue is a read-time computation (Feature 7.1/8.1), so no request path ever
"becomes" overdue and no hook point could fire the event. This script is the
scheduled trigger that does -- see services/outbound_overdue.py for why the
marker column exists and why the sweep is at-most-once.

Idempotent and safe to re-run: `sweep_overdue_invoices()` stamps
`Invoice.overdue_notified_at`, and an invoice with that column set is no longer
a candidate on any later pass.

Usage:
    uv run python scripts/sweep_outbound_overdue.py [--dry-run]

Runs daily in Azure via the Container Apps job `caj-overdue-sweep-<env>`
(infra/modules/compute/scheduled-job.bicep, wired in infra/08-apps.bicep). Kept
as a plain standalone entrypoint -- exactly like scripts/sweep_lapsed_billing.py
-- so it can equally be driven by cron, Task Scheduler, or run by hand during an
incident, with no scheduler-specific code in it.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session  # noqa: E402

from database import engine  # noqa: E402
from services.outbound_overdue import (  # noqa: E402
    find_overdue_invoices,
    sweep_overdue_invoices,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fire outbound_invoice.overdue for invoices past their due date."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which invoices would be notified without dispatching or writing anything.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        if args.dry_run:
            candidates = find_overdue_invoices(session)
            for invoice in candidates:
                logger.info(
                    "[dry-run] would fire outbound_invoice.overdue for invoice=%s tenant=%s "
                    "customer=%s due_date=%s total=%s",
                    invoice.id, invoice.tenant_id, invoice.customer_name,
                    invoice.due_date, invoice.grand_total,
                )
            logger.info("[dry-run] %s invoice(s) are newly overdue.", len(candidates))
            return 0

        notified = sweep_overdue_invoices(session)
        for invoice in notified:
            logger.info(
                "Fired outbound_invoice.overdue for invoice=%s tenant=%s due_date=%s",
                invoice.id, invoice.tenant_id, invoice.due_date,
            )
        logger.info("Sweep complete: %s invoice(s) notified.", len(notified))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
