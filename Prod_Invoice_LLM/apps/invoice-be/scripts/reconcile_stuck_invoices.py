"""
FE Gap 81: reconciliation sweep for invoices stalled in a non-terminal status.

An invoice sits at PROCESSING (inbound) / UPLOADED (outbound) from the moment
it is uploaded until the worker finishes with it. If the worker is down, dies
mid-message, or the enqueue silently failed, nothing ever moves it again --
Azurite/Azure will happily accept a message with zero consumers, and the upload
endpoint still returns 201. This sweep is the thing that notices.

Usage:
    uv run python scripts/reconcile_stuck_invoices.py [--dry-run]
    uv run python scripts/reconcile_stuck_invoices.py --invoice-id <uuid>

`--invoice-id` force-requeues one specific invoice regardless of age or how many
attempts it has already used. That mode exists for operator recovery of an
already-stuck record -- concretely, the 2026-07-29 outbound invoice
(d5fb23dc-fc5d-491a-a287-1aba39e7f2eb) that was still frozen at UPLOADED four
days later because its queue message was genuinely gone: worker restarts in
between drained everything else in the queue and never touched it, so no amount
of process supervision would ever have recovered it.

Intended to run every few minutes. No scheduler exists in this repo, so this is
a standalone entrypoint an Azure Container Apps job, cron, or Task Scheduler can
drive without any code change.
"""
import argparse
import logging
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session  # noqa: E402

from database import engine  # noqa: E402
from services.invoice_reconciliation import (  # noqa: E402
    find_stuck_invoices,
    force_requeue,
    reconcile_stuck_invoices,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-enqueue or fail invoices stuck mid-processing.")
    parser.add_argument("--dry-run", action="store_true", help="Report without enqueueing or writing.")
    parser.add_argument(
        "--invoice-id",
        help="Force-requeue this specific invoice, ignoring age and attempt count.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        if args.invoice_id:
            try:
                invoice_id = UUID(args.invoice_id)
            except ValueError:
                logger.error("--invoice-id must be a UUID, got %r", args.invoice_id)
                return 2
            if args.dry_run:
                logger.info("[dry-run] would force-requeue invoice %s", invoice_id)
                return 0
            return 0 if force_requeue(session, invoice_id) else 1

        if args.dry_run:
            stuck = find_stuck_invoices(session)
            for invoice in stuck:
                logger.info(
                    "[dry-run] stuck: id=%s direction=%s status=%s attempts=%s last_enqueued=%s created=%s",
                    invoice.id, invoice.flow_direction, invoice.status,
                    invoice.processing_attempts, invoice.last_enqueued_at, invoice.created_at,
                )
            logger.info("[dry-run] %s stuck invoice(s).", len(stuck))
            return 0

        result = reconcile_stuck_invoices(session)
        logger.info(
            "Reconciliation complete: %s re-enqueued, %s marked FAILED.",
            len(result["requeued"]), len(result["failed"]),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
