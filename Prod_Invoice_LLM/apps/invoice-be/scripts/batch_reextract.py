"""BE Gap 529: Batch re-extraction CLI for historical or failed documents.

Allows operators to reprocess invoices or documents in bulk when models,
prompts, OCR routing, or extraction schemas are updated.

Usage:
    python scripts/batch_reextract.py --tenant-id <uuid> [--status FAILED] [--limit 50] [--dry-run]
    python scripts/batch_reextract.py --invoice-id <uuid> [--dry-run]
    python scripts/batch_reextract.py --all-tenants --status EXTRACT_FAILED --limit 20
"""

import argparse
import logging
import os
import sys
from uuid import UUID
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402
from database import engine  # noqa: E402
from models import Invoice, Document  # noqa: E402
from config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def reprocess_invoices(
    session: Session,
    tenant_id: UUID | None,
    status_filter: str,
    limit: int,
    dry_run: bool,
    invoice_id: UUID | None = None,
) -> int:
    query = select(Invoice)
    if invoice_id:
        query = query.where(Invoice.id == invoice_id)
    else:
        if tenant_id:
            query = query.where(Invoice.tenant_id == tenant_id)
        if status_filter and status_filter.upper() != "ALL":
            query = query.where(Invoice.status == status_filter.upper())

    query = query.where(Invoice.deleted_at.is_(None)).limit(limit)
    rows = session.exec(query).all()

    logger.info("Found %d matching Invoice records for reprocessing.", len(rows))
    if not rows:
        return 0

    reprocessed_count = 0
    settings = get_settings()

    for inv in rows:
        logger.info(
            "[%s] Invoice %s (status=%s, file=%s, created_at=%s)",
            "DRY-RUN" if dry_run else "PROCESS",
            inv.id,
            inv.status,
            inv.file_path,
            inv.created_at,
        )
        if dry_run:
            continue

        try:
            # Re-enqueue by setting status back to PROCESSING and incrementing attempts
            inv.status = "PROCESSING"
            inv.last_enqueued_at = datetime.utcnow()
            inv.processing_attempts = (inv.processing_attempts or 0) + 1
            session.add(inv)
            reprocessed_count += 1
        except Exception as e:
            logger.error("Failed to re-enqueue invoice %s: %s", inv.id, e)

    if not dry_run:
        session.commit()
        logger.info("Successfully re-enqueued %d invoices for reprocessing.", reprocessed_count)

    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch re-extraction utility for historical invoices/documents.")
    parser.add_argument("--tenant-id", help="UUID of tenant to restrict extraction to.")
    parser.add_argument("--all-tenants", action="store_true", help="Allow running across all tenants.")
    parser.add_argument("--status", default="FAILED", help="Filter by status (FAILED, EXTRACT_FAILED, PROCESSING, ALL).")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of rows to re-enqueue (default 50).")
    parser.add_argument("--invoice-id", help="Single specific invoice UUID to reprocess.")
    parser.add_argument("--dry-run", action="store_true", help="Report matching rows without modifying database.")

    args = parser.parse_args()

    if not args.tenant_id and not args.invoice_id and not args.all_tenants:
        logger.error("Must specify --tenant-id, --invoice-id, or --all-tenants.")
        return 1

    parsed_tenant_id = None
    if args.tenant_id:
        try:
            parsed_tenant_id = UUID(args.tenant_id)
        except ValueError:
            logger.error("Invalid UUID format for --tenant-id: %r", args.tenant_id)
            return 1

    parsed_invoice_id = None
    if args.invoice_id:
        try:
            parsed_invoice_id = UUID(args.invoice_id)
        except ValueError:
            logger.error("Invalid UUID format for --invoice-id: %r", args.invoice_id)
            return 1

    with Session(engine) as session:
        reprocess_invoices(
            session=session,
            tenant_id=parsed_tenant_id,
            status_filter=args.status,
            limit=args.limit,
            dry_run=args.dry_run,
            invoice_id=parsed_invoice_id,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
