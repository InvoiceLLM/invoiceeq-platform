"""Feature 20 Area 1 — pull real Azure spend and mirror it into telemetry.

This is the scheduled half of `services/azure_cost.py`. It exists as a job
rather than an API endpoint for three reasons, all of them properties of the
data source rather than preferences:

  * The Cost Management API is heavily throttled per subscription (429s were
    routine while building this), so a per-request lookup behind a dashboard
    would be throttled by its own callers.
  * The underlying usage data only refreshes a few times a day. A daily pull
    loses nothing.
  * The two consumers of this data read it in two different ways, and a
    scheduled emission serves both: an Azure Workbook panel can only query
    Log Analytics / App Insights (it cannot call this application at all), and
    the planned Ops Digest Agent (Feature 24) runs *inside* this codebase and
    can call `collect_cost_snapshot()` directly in-process.

Run:
    python scripts/sweep_azure_cost.py                 # collect + emit telemetry
    python scripts/sweep_azure_cost.py --dry-run       # collect, print, emit nothing
    python scripts/sweep_azure_cost.py --json          # machine-readable snapshot
    python scripts/sweep_azure_cost.py --days 14

Scheduled shape (not deployed yet -- see the feature doc): another `module`
block in `infra/08-apps.bicep` over `modules/compute/scheduled-job.bicep` with
`command: ['python', 'scripts/sweep_azure_cost.py']`, the same pattern the
outbound-overdue sweep already uses. That module already passes `AZURE_CLIENT_ID`
and `APPLICATIONINSIGHTS_CONNECTION_STRING`, which is exactly what this needs;
it would additionally need `AZURE_SUBSCRIPTION_ID` and
`AZURE_COST_RESOURCE_GROUP` as plain env values.

Exit codes: 0 = a snapshot was collected (possibly partial), 1 = nothing usable
(unconfigured scope, or no credential). A partial snapshot is deliberately a
success: losing a whole day of cost history because one of five calls was
throttled would defeat the point of collecting daily.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.azure_cost import (  # noqa: E402
    AzureCostError,
    CostSnapshot,
    collect_cost_snapshot,
    emit_cost_snapshot_telemetry,
    is_configured,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sweep_azure_cost")


def configure_telemetry() -> bool:
    """Attach the Azure Monitor exporter, the way `main.py` does at import.

    Not optional boilerplate, and worth spelling out: `telemetry._emit_event()`
    logs through the `invoice_be_telemetry` logger, and that logger only carries
    an Application Insights handler because `configure_azure_monitor()` put one
    there. A standalone script that skips this step still *emits* — the record
    propagates to root and Feature 19's `StructuredJsonFormatter` writes it to
    stdout as JSON, so it lands in `ContainerAppConsoleLogs_CL` — but nothing
    ever reaches the `customEvents` table, no matter how correctly
    `APPLICATIONINSIGHTS_CONNECTION_STRING` is wired into the job.

    Returns True when the exporter is attached, so the caller can say which of
    the two destinations the run actually reached instead of assuming.
    """
    from utils.logging_config import setup_structured_logging

    setup_structured_logging(service_name="azure-cost-sweep")

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is not set — events will be written "
            "as structured stdout JSON only (still queryable via ContainerAppConsoleLogs_CL)."
        )
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            logger_name="invoice_be_telemetry",
        )
        return True
    except Exception as exc:  # pragma: no cover - exporter/SDK availability
        logger.warning("Could not configure Azure Monitor: %s", exc)
        return False


def _print_human(snapshot: CostSnapshot) -> None:
    currency = snapshot.currency or "?"
    print(f"Scope:           {snapshot.scope}")
    print(f"Collected at:    {snapshot.generated_at.isoformat()}")
    print(f"Month to date:   {snapshot.month_to_date_total:,.2f} {currency}")
    latest = snapshot.latest_day
    if latest:
        print(f"Latest day:      {latest.usage_date.isoformat()}  {latest.amount:,.2f} {currency}")
    change = snapshot.day_over_day_change_pct
    if change is not None:
        print(f"Day over day:    {change:+.1f}%")
    if snapshot.budget:
        budget = snapshot.budget
        print(
            f"Budget:          {budget.name} = {budget.amount:,.2f} {budget.currency} "
            f"({budget.time_grain}); spent {budget.current_spend:,.2f} "
            f"({budget.percent_used}%), forecast {budget.forecast_spend:,.2f} "
            f"({budget.percent_forecast}%)"
        )
    if snapshot.forecast:
        forecast = snapshot.forecast
        print(
            f"Month-end:       {forecast.projected_total:,.2f} {forecast.currency} projected "
            f"({forecast.actual_to_date:,.2f} actual + {forecast.forecast_remaining:,.2f} forecast)"
        )
    if snapshot.by_service:
        print("\nSpend by service (month to date):")
        for item in snapshot.by_service:
            print(f"  {item.amount:12,.2f} {item.currency}  {item.name}")
    if snapshot.by_resource_type:
        print("\nSpend by resource type (month to date):")
        for item in snapshot.by_resource_type:
            print(f"  {item.amount:12,.2f} {item.currency}  {item.name}")
    if snapshot.errors:
        print("\nPartial collection — the following failed:")
        for error in snapshot.errors:
            print(f"  ! {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect real Azure spend and emit it as telemetry.")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Length of the daily trend window, in days (default 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query Azure and print the result, but emit no telemetry events.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the snapshot as JSON instead of a human-readable summary.",
    )
    parser.add_argument(
        "--no-forecast",
        action="store_true",
        help="Skip the forecast call (one fewer request against a throttled API).",
    )
    args = parser.parse_args()

    if not is_configured():
        logger.error(
            "AZURE_SUBSCRIPTION_ID and AZURE_COST_RESOURCE_GROUP are not both set; "
            "nothing to query."
        )
        return 1

    try:
        snapshot = collect_cost_snapshot(
            trend_days=args.days,
            include_forecast=not args.no_forecast,
        )
    except AzureCostError as exc:
        logger.error("Azure cost collection failed: %s", exc)
        return 1

    if args.json:
        print(json.dumps(snapshot.to_dict(), indent=2))
    else:
        _print_human(snapshot)

    if args.dry_run:
        logger.info("Dry run — no telemetry emitted.")
        return 0

    exporter_attached = configure_telemetry()
    emitted = emit_cost_snapshot_telemetry(snapshot)
    logger.info(
        "Emitted %s Azure cost telemetry events to %s (%s collection error(s)).",
        emitted,
        "Application Insights + stdout" if exporter_attached else "stdout only",
        len(snapshot.errors),
    )
    if exporter_attached:
        # The OTel exporter batches on a background timer. `main.py` is a
        # long-lived server so it never has to think about this; a job process
        # that exits seconds after emitting would drop the whole batch.
        try:
            from opentelemetry._logs import get_logger_provider

            force_flush = getattr(get_logger_provider(), "force_flush", None)
            if force_flush is not None:
                force_flush(30000)
                logger.info("Flushed pending telemetry to Application Insights.")
        except Exception as exc:  # pragma: no cover - SDK internals
            logger.warning("Telemetry flush failed, events may be lost: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
