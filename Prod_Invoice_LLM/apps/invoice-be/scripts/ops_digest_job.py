"""Feature 24 (Ops Digest Agent) — the scheduled entrypoint.

Runs every 6 hours as `caj-ops-digest-dev`, a `Microsoft.App/jobs` resource
declared in `infra/08-apps.bicep` over `modules/compute/scheduled-job.bicep` —
the same module and the same pattern as the outbound-overdue sweep.

Cadence, stated rather than left vague
--------------------------------------
``0 1,7,13,19 * * *`` (UTC), i.e. **01:00 / 07:00 / 13:00 / 19:00 UTC** =
06:30 / 12:30 / 18:30 / 00:30 IST. Four runs a day is "a few times a day" per the
feature doc, and each one covers exactly the six hours since the last, so
``OPS_DIGEST_WINDOW_HOURS`` (6) and the cron are the same number by
construction — a window shorter than the schedule silently loses whatever
happened in the gap, and a longer one repeats items in consecutive digests.

The odd hours are deliberate: `caj-overdue-sweep-dev` is on ``0 2 * * *`` and the
cost sweep is intended for a daily slot, so 01:00 keeps the digest off the same
minute as another job on the same Container Apps environment.

Run:
    python scripts/ops_digest_job.py                 # collect, synthesise, deliver
    python scripts/ops_digest_job.py --dry-run       # everything except delivery
    python scripts/ops_digest_job.py --no-llm        # skip synthesis (raw items only)
    python scripts/ops_digest_job.py --json          # machine-readable result
    python scripts/ops_digest_job.py --window-hours 24
    python scripts/ops_digest_job.py --print-channel # just show where it would go

Exit codes: 0 = a digest was produced (delivered, or dry-run). 1 = the run could
not produce a digest at all. A *partial* run — Resource Graph 403'd, or the LLM
was unreachable — is deliberately exit 0: the digest still went out saying so,
and turning that into a failed job execution would replace one visible problem
with two.

Skipping empty digests
----------------------
A window in which nothing fired, nothing moved and every source collected
cleanly produces no message at all by default (``--send-empty`` overrides).
Four "nothing to report" messages a day is exactly the noise this feature exists
to remove. The `ops_digest_run` telemetry event is emitted either way, so a
silent channel and a dead job are still distinguishable.

Feature 23's online-eval signals ride this job (Gap 305)
-------------------------------------------------------
`services/online_eval_signals.py::emit_online_signals()` had **zero callers** —
its five signals are computed in SQL over Postgres and a workbook cannot query
Postgres, so without a scheduled emitter the online panel renders empty forever
and that empty state means "nothing has run", not "nothing is wrong".

This job is the caller rather than a new `Microsoft.App/jobs` resource because it
already runs on the only cadence that fits (every 6h) and already reads the same
signals through `services/ops_digest_collect.py::_collect_online_signal_items()`;
a job of its own would need its own bicep, its own image pull and its own
deployment, for one `track_online_signal()` call per signal.

Two properties this placement has to hold, both easy to get wrong:

* It emits **after** `configure_telemetry()`. `track_online_signal()` logs
  through `invoice_be_telemetry`, and that logger only reaches `customEvents`
  once the exporter is attached — emitting at collection time would produce
  stdout lines and nothing in Application Insights.
* It is emitted for **every** run, including `--dry-run` and a clean window that
  delivers nothing, for the same reason `ops_digest_run` is: the events are the
  evidence the measurement happened, not a notification.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402
from services.ops_digest import OpsDigestResult, run_ops_digest  # noqa: E402
from services.ops_digest_delivery import deliver_digest, resolve_critical_channel  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ops_digest_job")


def configure_telemetry() -> bool:
    """Attach the Azure Monitor exporter, exactly as `scripts/sweep_azure_cost.py` does.

    Same non-obvious reason, repeated here rather than cross-referenced because
    it is the kind of thing that gets deleted as boilerplate:
    `telemetry._emit_event()` logs through the `invoice_be_telemetry` logger, and
    that logger only carries an Application Insights handler because
    `configure_azure_monitor()` put one there. A job that skips this still emits
    to stdout (and so to `ContainerAppConsoleLogs_CL`), but nothing reaches
    `customEvents` however correctly the connection string is wired.
    """
    from utils.logging_config import setup_structured_logging

    setup_structured_logging(service_name="ops-digest-agent")

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is not set — the run event will be "
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
        logger.warning("Telemetry flush failed, the run event may be lost: %s", exc)


def _open_session():
    """A DB session for the AI-eval source, or None with a logged reason.

    None rather than a raised exception: the cost and alert sources do not need
    Postgres, and a digest missing its quality section is far better than no
    digest at all. `collect_all()` records the absence as a collection error, so
    it shows up in the delivered message rather than being invisible.
    """
    try:
        from sqlmodel import Session  # noqa: PLC0415

        from database import engine  # noqa: PLC0415

        return Session(engine)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ops digest: no database session (%s) — quality findings skipped", exc)
        return None


def _compute_online_signals(session, window_start, window_end):
    """`(signals, window_days)` for this digest's own window, or `(None, None)`.

    Gap 305's caller. Recomputed here rather than lifted off the collection pass:
    `_collect_online_signal_items()` keeps only the *breached* signals and throws
    the `OnlineEvalSignals` object away, and threading it back out would mean
    changing `DigestCollection`, `build_digest()` and `OpsDigestResult` to carry
    a field only this line reads. The recomputation is five windowed reads of
    `chat_message`/`chat_feedback`/`agent_eval_run` over six hours — cheap next
    to the LLM synthesis call this job already makes.

    The window is taken from the result rather than rebuilt from the arguments,
    so the emitted events describe exactly the window the digest reported, and
    `window_days` is the same fractional value `_collect_online_signal_items()`
    passes (a 6-hour window is 0.25 days).

    Never raises: a failure here must cost nothing but these events.
    """
    if session is None:
        return None, None
    try:
        from services.online_eval_signals import compute_online_signals  # noqa: PLC0415

        # `chat_message.created_at` / `agent_eval_run.run_at` are naive UTC.
        # Same boundary conversion as `ops_digest_collect._as_naive_utc()`:
        # a tz-aware bound raises on Postgres and compares wrong on SQLite.
        naive_end = (
            window_end
            if window_end.tzinfo is None
            else window_end.astimezone(timezone.utc).replace(tzinfo=None)
        )
        window_days = max((window_end - window_start).total_seconds() / 86400.0, 0.01)
        return compute_online_signals(session, window_days=window_days, now=naive_end), window_days
    except Exception as exc:  # noqa: BLE001
        logger.warning("Online-eval signals could not be computed, none emitted: %s", exc)
        return None, None


def _emit_online_signals(signals, window_days) -> int:
    """Mirror the computed window onto Application Insights. Never raises.

    Separate from the `ops_digest_run` emission and deliberately after it: the
    run event is the evidence this job executed at all, and a broken signal
    mirror must not be able to cost it.
    """
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect Azure alerts, cost and AI-eval findings, write an LLM digest, deliver it."
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=None,
        help="How far back to look. Defaults to OPS_DIGEST_WINDOW_HOURS (6).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything including the LLM call, but deliver nothing.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the synthesis call. Items are listed with their component hints only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the whole result as JSON instead of the rendered digest.",
    )
    parser.add_argument(
        "--send-empty",
        action="store_true",
        help="Deliver even when the window is completely clean (default: skip).",
    )
    parser.add_argument(
        "--print-channel",
        action="store_true",
        help="Resolve and print where a digest would be delivered, then exit.",
    )
    args = parser.parse_args()

    if args.print_channel:
        channel = resolve_critical_channel()
        print(f"Action group:  {channel.action_group_name or '(none resolved)'}")
        print(f"Resolved via:  {channel.source or 'n/a'}")
        print(f"Webhooks:      {len(channel.webhook_urls)}")
        for url in channel.webhook_urls:
            print(f"  - {url.split('?', 1)[0]}")
        print(f"Emails:        {', '.join(channel.email_addresses) or '(none)'}")
        if channel.error:
            print(f"Error:         {channel.error}")
        return 0 if not channel.is_empty else 1

    session = _open_session()
    online_signals = None
    online_window_days = None
    try:
        result: OpsDigestResult = run_ops_digest(
            session,
            window_hours=args.window_hours,
            use_llm=not args.no_llm,
        )
        # Computed while the session is still open; emitted further down, once
        # the exporter is attached (see the module docstring, Gap 305).
        online_signals, online_window_days = _compute_online_signals(
            session, result.window_start, result.window_end
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Ops digest run failed: %s", exc, exc_info=True)
        return 1
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - closing a broken session must not mask the run
                pass

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(result.subject)
        print()
        print(result.body)

    window_hours = (
        args.window_hours
        if args.window_hours is not None
        else float(settings.OPS_DIGEST_WINDOW_HOURS)
    )

    delivery = None
    if args.dry_run:
        logger.info("Dry run — digest rendered, nothing delivered.")
    elif result.is_empty and not args.send_empty:
        logger.info("Clean window and no collection errors — nothing delivered (--send-empty to override).")
    else:
        delivery = deliver_digest(result.subject, result.body)
        if delivery.any_delivered:
            logger.info("Digest delivered to: %s", ", ".join(delivery.delivered))
        else:
            logger.warning(
                "Digest was NOT delivered. skipped=%s errors=%s",
                delivery.skipped,
                delivery.errors,
            )

    exporter_attached = configure_telemetry()
    try:
        from telemetry import track_ops_digest_run

        track_ops_digest_run(
            window_hours=window_hours,
            items_collected=result.item_count + result.critical_count,
            critical_count=result.critical_count,
            needs_decision_count=len(result.needs_decision),
            self_resolved_count=len(result.self_resolved),
            collection_errors=len(result.collection_errors),
            llm_calls=result.synthesis.llm_calls,
            synthesis_error=result.synthesis.error,
            delivered_to=",".join(delivery.delivered) if delivery else ("dry-run" if args.dry_run else "skipped"),
            delivery_errors=len(delivery.errors) if delivery else 0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not emit the ops_digest_run event: %s", exc)

    _emit_online_signals(online_signals, online_window_days)

    if exporter_attached:
        _flush_telemetry()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
