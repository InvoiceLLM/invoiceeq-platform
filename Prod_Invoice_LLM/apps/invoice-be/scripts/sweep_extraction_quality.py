"""
BE Gap 688: Scheduled extraction quality sweep script.

Computes field correction rates and alert precision from AuditLog human edits
for all active tenants and writes telemetry events/metrics to Application Insights.
Logs "HIGH CORRECTION RATE ALERT" when a critical field's correction rate is above
the threshold over at least 5 resolves.

The 15% default is PROVISIONAL, not a measured baseline: the tracker asks for a
baseline "established from current data", and the dev database was stopped when this
was written. Replace it once real rollups exist. No Azure Monitor rule keys on the log
line yet -- that is part of the infra pass (see the Gap 688 plan entry).

Usage:
    python scripts/sweep_extraction_quality.py [--days 7] [--tenant-id <uuid>] [--dry-run]
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402
from database import engine  # noqa: E402
from models import AuditLog  # noqa: E402
from services.extraction_quality_rollup import (  # noqa: E402
    field_correction_rollup,
    alert_precision_rollup,
)
from telemetry import track_extraction_quality_rollup  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sweep_extraction_quality")

CRITICAL_FIELDS = frozenset({"grand_total", "tax_amount", "vendor_name", "subtotal", "invoice_date"})
DEFAULT_CORRECTION_THRESHOLD = 0.15  # 15% threshold


def sweep_tenant_quality(
    session: Session,
    tenant_id: UUID,
    since: datetime,
    dry_run: bool = False,
    alert_threshold: float = DEFAULT_CORRECTION_THRESHOLD,
) -> dict:
    """Computes rollups for one tenant and emits telemetry."""
    field_rollups = field_correction_rollup(session, tenant_id, since=since)
    alert_rollups = alert_precision_rollup(session, tenant_id, since=since)

    high_correction_alerts = []

    for item in field_rollups:
        field_name = item["field"]
        correction_count = item["correction_count"]
        total_resolves = item["total_resolves"]
        rate = item["correction_rate"] or 0.0

        if not dry_run:
            track_extraction_quality_rollup(
                tenant_id=str(tenant_id),
                field=field_name,
                correction_count=correction_count,
                total_resolves=total_resolves,
                correction_rate=rate,
            )

        if field_name in CRITICAL_FIELDS and rate > alert_threshold and total_resolves >= 5:
            msg = (
                f"HIGH CORRECTION RATE ALERT: Field '{field_name}' correction rate {rate * 100:.1f}% "
                f"exceeds {alert_threshold * 100:.0f}% baseline for tenant {tenant_id} "
                f"({correction_count}/{total_resolves} resolves modified)."
            )
            logger.warning(msg)
            high_correction_alerts.append(msg)
        else:
            logger.info(
                "Tenant %s field %s: %d/%d corrections (%.1f%%)",
                tenant_id, field_name, correction_count, total_resolves, rate * 100,
            )

    # Alert precision reaches the logs too (the first version computed it and dropped it).
    for row in alert_rollups:
        logger.info(
            "Tenant %s alert %s: %d dismissed (%d with a correction), precision=%s",
            tenant_id, row.get("alert_type"), row.get("total_dismissed", 0),
            row.get("dismissed_with_correction", 0), row.get("precision"),
        )

    return {
        "tenant_id": str(tenant_id),
        "field_rollups": field_rollups,
        "alert_rollups": alert_rollups,
        "high_correction_alerts": high_correction_alerts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep extraction quality rollups across tenants.")
    parser.add_argument("--days", type=int, default=7, help="Window size in days (default: 7)")
    parser.add_argument("--tenant-id", help="Filter to one specific tenant UUID.")
    parser.add_argument("--dry-run", action="store_true", help="Compute rollups without emitting telemetry.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_CORRECTION_THRESHOLD,
        help="Alert threshold for critical field correction rate (default: 0.15)",
    )
    args = parser.parse_args()

    since = datetime.utcnow() - timedelta(days=args.days)
    logger.info("Starting extraction quality sweep (window: last %d days since %s)", args.days, since.isoformat())

    with Session(engine) as session:
        if args.tenant_id:
            try:
                tenant_ids = [UUID(args.tenant_id)]
            except ValueError:
                logger.error("--tenant-id must be a valid UUID, got %r", args.tenant_id)
                return 2
        else:
            # Discover distinct tenants from recent AuditLogs
            stmt = select(AuditLog.tenant_id).where(AuditLog.timestamp >= since).distinct()
            tenant_ids = [t for t in session.exec(stmt).all() if t is not None]

        logger.info("Sweeping %d active tenant(s)...", len(tenant_ids))
        total_alerts = 0
        for tid in tenant_ids:
            try:
                res = sweep_tenant_quality(
                    session,
                    tid,
                    since=since,
                    dry_run=args.dry_run,
                    alert_threshold=args.threshold,
                )
                total_alerts += len(res["high_correction_alerts"])
            except Exception as e:
                logger.error("Error sweeping extraction quality for tenant %s: %s", tid, e)

        logger.info(
            "Extraction quality sweep complete for %d tenant(s). High-correction alerts: %d.",
            len(tenant_ids), total_alerts,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
