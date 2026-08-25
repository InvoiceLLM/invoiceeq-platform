"""Feature 23 (Gap 305) — the scheduled emitter for the five online-eval signals.

`services/online_eval_signals.py::compute_online_signals()` reads real chat
traffic out of Postgres (`chat_message`, `chat_feedback`, `agent_eval_run`) and
`emit_online_signals()` mirrors that computed window onto Application Insights as
one `online_eval_signal` event per signal. The mirror exists because the consumer
is an Azure Monitor workbook, and a workbook cannot query Postgres — its data
sources are Logs, Azure Resource Graph, ARM and ADX. Without a scheduled emitter
the online panel renders empty forever, and that empty state reads as "nothing is
wrong" while actually meaning "nothing has run".

Provenance, stated rather than left to `git log`
-----------------------------------------------
This caller was built on 2026-08-24 inside `scripts/ops_digest_job.py`, Feature
24's ops-digest agent, because that job already ran on a six-hour cadence and
already read these same signals. Feature 24 was superseded as over-scoped on
2026-08-25 and its code deleted; this file is the extraction of the part that was
still wanted. It is deliberately the same shape as `scripts/sweep_azure_cost.py`
— the other "compute in-process, mirror to telemetry, exit" job in this repo.

Run:
    python scripts/emit_online_signals_job.py                    # compute + emit
    python scripts/emit_online_signals_job.py --dry-run          # compute, print, emit nothing
    python scripts/emit_online_signals_job.py --json             # machine-readable window
    python scripts/emit_online_signals_job.py --window-hours 24

Exit codes: 0 = a window was computed (and emitted, or dry-run). 1 = no window
could be computed at all — no database session, or the SQL failed. A run with no
session deliberately emits **nothing** rather than five zero-denominator events:
"measured, nothing found" and "never measured" must not render identically on a
panel.

Two properties this file has to hold, both easy to get wrong
------------------------------------------------------------
* It emits **after** `configure_telemetry()`. `track_online_signal()` logs
  through the `invoice_be_telemetry` logger, and that logger only reaches
  `customEvents` once the Azure Monitor exporter is attached — emitting before
  that produces stdout lines and nothing in Application Insights, a state
  indistinguishable from the emitter not existing.
* `window_days` is **fractional** and must stay a float. A six-hour window is
  0.25 days; `telemetry.track_online_signal()` used to cast it with `int()`,
  which turned every event this job produces into a zero-length window (fixed
  2026-08-24, pinned by a test).

Not deployed. There is no `Microsoft.App/jobs` resource for this file — the same
state it was in inside the digest job, which was also never deployed. Scheduling
it means another `module` block in `infra/08-apps.bicep` over
`modules/compute/scheduled-job.bicep` with
`command: ['python', 'scripts/emit_online_signals_job.py']`; it needs
`APPLICATIONINSIGHTS_CONNECTION_STRING` (for the mirror to reach `customEvents`)
and the database secrets that module already passes, and nothing else.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("emit_online_signals_job")


def configure_telemetry() -> bool:
    """Attach the Azure Monitor exporter, exactly as `scripts/sweep_azure_cost.py` does.

    Not boilerplate, and repeated here rather than cross-referenced because it is
    the kind of thing that gets deleted as such: `telemetry._emit_event()` logs
    through the `invoice_be_telemetry` logger, and that logger only carries an
    Application Insights handler because `configure_azure_monitor()` put one
    there. A job that skips this still emits to stdout (and so to
    `ContainerAppConsoleLogs_CL`), but nothing reaches `customEvents` however
    correctly the connection string is wired.

    Returns True when the exporter is attached, so the caller can say which of
    the two destinations the run actually reached instead of assuming.
    """
    from utils.logging_config import setup_structured_logging

    setup_structured_logging(service_name="online-eval-signals")

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is not set — the signal events will be "
            "structured stdout JSON only (still queryable via ContainerAppConsoleLogs_CL)."
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


def _flush_telemetry() -> None:
    """The OTel exporter batches on a timer; a job that exits drops the batch."""
    try:
        from opentelemetry._logs import get_logger_provider

        force_flush = getattr(get_logger_provider(), "force_flush", None)
        if force_flush is not None:
            force_flush(30000)
    except Exception as exc:  # pragma: no cover - SDK internals
        logger.warning("Telemetry flush failed, the signal events may be lost: %s", exc)


def _open_session():
    """A DB session, or None with a logged reason.

    None rather than a raised exception so the "never measured" case is reported
    as itself — `main()` turns it into exit 1 and emits nothing.
    """
    try:
        from sqlmodel import Session  # noqa: PLC0415

        from database import engine  # noqa: PLC0415

        return Session(engine)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No database session (%s) — no signals can be computed", exc)
        return None


def _compute_online_signals(session, window_hours: float):
    """`(signals, window_days)` for the window ending now, or `(None, None)`.

    Never raises: a failure here costs the events and nothing else.
    """
    if session is None:
        return None, None
    try:
        from services.online_eval_signals import compute_online_signals  # noqa: PLC0415

        # `chat_message.created_at` / `agent_eval_run.run_at` are naive UTC. A
        # tz-aware bound raises on Postgres and compares wrong on SQLite, so the
        # boundary is converted once, here.
        window_end = datetime.now(timezone.utc).replace(tzinfo=None)
        window_days = max(window_hours / 24.0, 0.01)
        return compute_online_signals(session, window_days=window_days, now=window_end), window_days
    except Exception as exc:  # noqa: BLE001
        logger.warning("Online-eval signals could not be computed, none emitted: %s", exc)
        return None, None


def _emit_online_signals(signals, window_days) -> int:
    """Mirror the computed window onto Application Insights. Never raises."""
    if signals is None:
        return 0
    try:
        from services.online_eval_signals import emit_online_signals  # noqa: PLC0415

        emitted = emit_online_signals(signals, window_days=window_days)
        logger.info(
            "Emitted %d online_eval_signal events (window_days=%.4f, breached=%s).",
            emitted,
            window_days or 0.0,
            ", ".join(s.name for s in signals.breaches) or "none",
        )
        return emitted
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not emit the online_eval_signal events: %s", exc)
        return 0


def _print_human(signals, window_days: float) -> None:
    start = signals.window_start.isoformat()
    end = signals.window_end.isoformat()
    print(f"Window:      {start} → {end}  ({window_days:.4f} days)")
    print(f"Tenant:      {signals.tenant_id or '(all tenants)'}")
    print()
    for signal in signals.signals:
        value = "n/a" if signal.value is None else f"{signal.value:.3f}"
        flag = "BREACHED" if signal.breached else ""
        print(
            f"  {signal.name:<24} {value:>7}  "
            f"({signal.numerator}/{signal.denominator}, {signal.confidence}) {flag}"
        )
    breaches = ", ".join(s.name for s in signals.breaches)
    print(f"\nBreached:    {breaches or '(none)'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the five online-eval signals over real chat traffic and mirror them to telemetry."
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=6.0,
        help="How far back to look, in hours (default 6).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the window, but emit no telemetry events.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the window as JSON instead of a human-readable summary.",
    )
    args = parser.parse_args()

    session = _open_session()
    try:
        signals, window_days = _compute_online_signals(session, args.window_hours)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - closing a broken session must not mask the run
                pass

    if signals is None:
        logger.error(
            "No window was computed — nothing emitted. Five zero-denominator events "
            "would report 'measured, nothing found' for a window nothing was measured in."
        )
        return 1

    if args.json:
        print(json.dumps(signals.as_dict(), indent=2, default=str))
    else:
        _print_human(signals, window_days)

    if args.dry_run:
        logger.info("Dry run — window computed, nothing emitted.")
        return 0

    # Ordering is load-bearing, see the module docstring: the exporter has to be
    # attached before the first `track_online_signal()` call, not after.
    exporter_attached = configure_telemetry()
    _emit_online_signals(signals, window_days)
    if exporter_attached:
        _flush_telemetry()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
