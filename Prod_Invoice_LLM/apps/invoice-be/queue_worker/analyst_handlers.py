"""Feature 33 Task 33.15 — Analyst Handlers: Tenant-Scope & Weekly-Job Triggers.

WHAT THIS MODULE DOES
---------------------
This is the queue_worker entry point for ATLAS tenant-scope runs.  The
attachment-scope entry point already exists (``handle_insight_job`` in
``queue_worker/handlers.py``).  This module adds:

1. ``handle_analyst_job``  — processes a single ``"analyst"`` task message
   from the Redis chat_tasks_queue.  Called by ``main_worker._process_redis_chat_tasks``
   when ``data.get("task") == "analyst"``.

2. ``enqueue_analyst_job``  — helper: pushes one analyst job onto the Redis
   queue.  Used by the weekly cron (Task 33.16) and by the event triggers
   (new attachment extracted, threshold crossed) to fan out per-tenant runs.

3. ``run_tenant_analyst``  — the synchronous function that actually calls
   ``run_analyst(scope="tenant", …)``, persists ``TodayItem`` rows via
   ``persist_today_items()``, persists ``InputRequest`` rows, and logs the
   outcome.  Separated from the handler so it can be called directly in tests
   without touching Redis.

CONCURRENCY / FAIL-SAFE RULES
------------------------------
* Every exit path must complete the job.  A browser waiting on SSE must not be
  left hanging.  (Same rule as ``handle_insight_job``.)
* ``run_analyst()`` never raises — it catches internally and returns an
  ``AnalystResult`` with ``result.error`` set.  The handler logs that error and
  marks the job failed but does NOT re-raise.
* The handler acquires no locks itself.  Per-tenant fair-share throttling is
  handled by ``main_worker._acquire_tenant_slot`` / ``_release_tenant_slot``
  before the handler is called.

PERSIST CONTRACT (Task 33.17 companion)
-----------------------------------------
``run_tenant_analyst()`` calls ``persist_today_items()`` and
``persist_input_requests()`` from ``agents/analyst_agent.py`` after the loop
completes.  Those functions write to the ``today_item`` and ``input_request``
tables respectively.  This module does NOT duplicate that logic.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis helpers (same pattern as queue_worker.handlers._get_redis_sync)
# ---------------------------------------------------------------------------


def _get_redis():
    """Return a synchronous Redis client or None if unavailable."""
    try:
        import redis  # noqa: PLC0415
        from config import get_settings  # noqa: PLC0415
        settings = get_settings()
        if settings.REDIS_URL:
            return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("analyst_handlers: Redis unavailable: %s", exc)
    return None


_ANALYST_QUEUE_KEY = "chat_tasks_queue"


# ---------------------------------------------------------------------------
# Public: enqueue_analyst_job()
# ---------------------------------------------------------------------------


def enqueue_analyst_job(
    tenant_id: Any,
    clearance: str = "ops",
    since: Optional[datetime] = None,
    job_id: Optional[str] = None,
) -> str:
    """Push one analyst job onto the Redis task queue.  Returns the job_id.

    The payload shape is the same as the other entries on ``chat_tasks_queue``
    (``task``, ``job_id``, ``tenant_id``), so ``main_worker._process_redis_chat_tasks``
    can dispatch it with a single ``data.get("task") == "analyst"`` check.

    ``since`` is serialised as an ISO-8601 string and deserialised by the
    handler.  None means full scan.

    Never raises — a Redis failure is logged and the job_id is returned so the
    caller can record it even if the job was not actually enqueued.
    """
    job_id = job_id or str(uuid4())
    payload: dict = {
        "task": "analyst",
        "job_id": job_id,
        "tenant_id": str(tenant_id),
        "clearance": clearance,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }
    if since is not None:
        payload["since"] = since.isoformat()

    try:
        r = _get_redis()
        if r:
            r.lpush(_ANALYST_QUEUE_KEY, json.dumps(payload))
            logger.info(
                "analyst_handlers: enqueued analyst job %s for tenant %s (clearance=%s)",
                job_id, tenant_id, clearance,
            )
        else:
            logger.warning(
                "analyst_handlers: Redis unavailable — analyst job %s NOT enqueued for tenant %s",
                job_id, tenant_id,
            )
    except Exception as exc:
        logger.error(
            "analyst_handlers: failed to enqueue job %s for tenant %s: %s",
            job_id, tenant_id, exc,
        )
    return job_id


# ---------------------------------------------------------------------------
# Public: handle_analyst_job()
# ---------------------------------------------------------------------------


def handle_analyst_job(
    job_id: str,
    tenant_id: str,
    clearance: str = "ops",
    since: Optional[str] = None,          # ISO-8601 string from the queue payload
) -> None:
    """Queue-worker handler for ``task = "analyst"`` messages.

    Called by ``main_worker._process_redis_chat_tasks`` after the ``analyst``
    task type check.  Deserialises ``since``, resolves the DB session, and
    delegates to ``run_tenant_analyst()``.

    Every exit path is covered — the job is completed or failed before returning.
    """
    from services.chat_queue import ChatQueueService  # noqa: PLC0415

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            logger.warning(
                "analyst_handlers: invalid since value %r for job %s — doing full scan",
                since, job_id,
            )

    try:
        from database import engine  # noqa: PLC0415
        from sqlmodel import Session  # noqa: PLC0415

        with Session(engine) as session:
            result = run_tenant_analyst(
                tenant_id=tenant_id,
                db_session=session,
                clearance=clearance,
                since=since_dt,
                job_id=job_id,
            )

        # Report outcome
        outcome_payload: dict = {
            "tenant_id": tenant_id,
            "card_count": len(result.cards) if result else 0,
            "narration_count": len(result.narration) if result else 0,
            "input_request_count": len(result.input_requests) if result else 0,
            "plan_source": result.plan_source if result else "unknown",
            "error": result.error if result else None,
        }

        if result and result.error:
            ChatQueueService.fail_job(job_id, tenant_id, result.error)
        else:
            ChatQueueService.complete_job(job_id, tenant_id, outcome_payload)

        logger.info(
            "analyst_handlers: job %s completed for tenant %s — %d cards, %d requests",
            job_id,
            tenant_id,
            outcome_payload["card_count"],
            outcome_payload["input_request_count"],
        )

    except Exception as exc:
        logger.error(
            "analyst_handlers: job %s failed for tenant %s: %s",
            job_id, tenant_id, exc, exc_info=True,
        )
        try:
            ChatQueueService.fail_job(job_id, tenant_id, str(exc))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public: run_tenant_analyst()
# ---------------------------------------------------------------------------


def run_tenant_analyst(
    tenant_id: Any,
    db_session: Any,
    clearance: str = "ops",
    since: Optional[datetime] = None,
    job_id: Optional[str] = None,
) -> Any:
    """Run the ATLAS loop for tenant scope and persist the results.

    This is the single synchronous function that:
    1. Builds an ``AnalystScope(kind="tenant", …)``
    2. Calls ``run_analyst()``
    3. Persists ``TodayItem`` rows via ``persist_today_items()``
    4. Persists ``InputRequest`` rows via ``persist_input_requests()``
    5. Returns the ``AnalystResult``

    Never raises — all errors are captured in ``result.error`` or logged.

    Parameters
    ----------
    tenant_id:
        The tenant UUID (string or UUID).
    db_session:
        Active SQLAlchemy / SQLModel session.
    clearance:
        ``"ops"`` or ``"exec"``.
    since:
        If given, the loop only considers events after this datetime.  None = full scan.
    job_id:
        For logging / correlation only.  Not persisted.
    """
    from agents.analyst_agent import AnalystScope, Budget, run_analyst  # noqa: PLC0415

    scope = AnalystScope(
        kind="tenant",
        tenant_id=str(tenant_id),
        clearance=clearance,
        since=since,
    )
    budget = Budget.for_scope("tenant")  # follow_ups=3, sentences=6

    logger.info(
        "run_tenant_analyst: starting — tenant=%s clearance=%s since=%s job=%s",
        tenant_id, clearance, since, job_id,
    )

    result = run_analyst(scope, db_session, budget=budget)

    if result.error:
        logger.error(
            "run_tenant_analyst: run_analyst returned error for tenant %s: %s",
            tenant_id, result.error,
        )
        return result

    # Persist TodayItems
    try:
        _persist_today_items(result, db_session)
    except Exception as exc:
        logger.error(
            "run_tenant_analyst: persist_today_items failed for tenant %s: %s",
            tenant_id, exc, exc_info=True,
        )

    # Persist InputRequests
    try:
        _persist_input_requests(result, db_session)
    except Exception as exc:
        logger.error(
            "run_tenant_analyst: persist_input_requests failed for tenant %s: %s",
            tenant_id, exc, exc_info=True,
        )

    logger.info(
        "run_tenant_analyst: done — tenant=%s cards=%d narration=%d requests=%d",
        tenant_id,
        len(result.cards),
        len(result.narration),
        len(result.input_requests),
    )
    return result


# ---------------------------------------------------------------------------
# Private: persist helpers
# ---------------------------------------------------------------------------


def _persist_today_items(result: Any, db_session: Any) -> None:
    """Write TodayItem rows for each finding in the result.

    Section mapping:
    - FINDING cards → ``"findings"`` section
    - narration sentences → ``"summary"`` section (one row per sentence)
    - Empty graph → one ``"summary"`` row with the empty-graph text

    Clears previously generated (non-cleared) items for this tenant+run so the
    Today screen always reflects the latest loop output, not an accumulation.
    Only clears rows created by ATLAS (cleared_at IS NULL).  User-dismissed
    (cleared_at IS NOT NULL) rows are preserved — the user's action is the
    source of truth.

    Fails loudly (re-raises to caller) so the handler can log it.
    """
    from models import TodayItem  # noqa: PLC0415
    from sqlmodel import select  # noqa: PLC0415

    scope = result.scope
    tenant_id_str = str(scope.tenant_id)
    clearance = scope.clearance

    # ── Delete stale ATLAS-generated rows for this tenant ──────────────────
    existing = db_session.exec(
        select(TodayItem).where(
            TodayItem.tenant_id == UUID(tenant_id_str),
            TodayItem.clearance == clearance,
            TodayItem.cleared_at == None,  # noqa: E711 — SQLModel == None is IS NULL
        )
    ).all()
    for row in existing:
        db_session.delete(row)
    db_session.flush()

    rows_to_add: list = []
    now = datetime.utcnow()

    # ── Finding rows ────────────────────────────────────────────────────────
    for card in result.cards:
        for finding in getattr(card, "findings", []):
            title = finding.get("title", "")
            seeded = finding.get("seeded_question") or _seeded_from_finding(finding)
            severity = _severity_from_finding(finding)
            meta = {
                "card": getattr(card, "card", ""),
                "impact_amount": finding.get("impact_amount"),
                "currency": finding.get("currency", "INR"),
                "status": getattr(card, "status", ""),
            }
            rows_to_add.append(
                TodayItem(
                    tenant_id=UUID(tenant_id_str),
                    section="findings",
                    clearance=clearance,
                    text=title,
                    seeded_question=seeded,
                    severity=severity,
                    meta=meta,
                    created_at=now,
                    updated_at=now,
                )
            )

    # ── Summary / narration rows ─────────────────────────────────────────────
    for sentence in result.narration:
        rows_to_add.append(
            TodayItem(
                tenant_id=UUID(tenant_id_str),
                section="summary",
                clearance=clearance,
                text=sentence,
                severity=3,
                created_at=now,
                updated_at=now,
            )
        )

    # ── Empty-graph row ─────────────────────────────────────────────────────
    if result.empty_graph and not rows_to_add:
        rows_to_add.append(
            TodayItem(
                tenant_id=UUID(tenant_id_str),
                section="summary",
                clearance=clearance,
                text="I read your documents — no issues found.",
                severity=5,
                created_at=now,
                updated_at=now,
            )
        )

    for row in rows_to_add:
        db_session.add(row)

    db_session.commit()
    logger.info(
        "_persist_today_items: wrote %d TodayItem rows for tenant %s",
        len(rows_to_add),
        tenant_id_str,
    )


def _persist_input_requests(result: Any, db_session: Any) -> None:
    """Upsert InputRequest rows from result.input_requests.

    An InputRequest is keyed on ``(tenant_id, kind)``.  If an unfulfilled row
    already exists for this kind it is updated in place so the ``created_at``
    timestamp reflects when this kind was FIRST flagged as missing, not the
    most recent loop.  Fulfilled rows (``fulfilled_at IS NOT NULL``) are left
    alone — the user uploaded the document.

    Fails loudly (re-raises to caller).
    """
    from models import InputRequest  # noqa: PLC0415
    from sqlmodel import select  # noqa: PLC0415

    scope = result.scope
    tenant_id_str = str(scope.tenant_id)
    clearance = scope.clearance

    for missing in result.input_requests:
        kind = missing.kind

        # Check for an existing unfulfilled row
        existing = db_session.exec(
            select(InputRequest).where(
                InputRequest.tenant_id == UUID(tenant_id_str),
                InputRequest.kind == kind,
                InputRequest.fulfilled_at == None,  # noqa: E711
            )
        ).first()

        # Render the phrase using the phrasing contract
        try:
            from services.dependency import render_input_request  # noqa: PLC0415
            phrase = render_input_request(missing)
        except Exception as exc:
            logger.warning("_persist_input_requests: render failed for %r: %s", kind, exc)
            phrase = kind.replace("_", " ").title()

        if existing is not None:
            # Update fields that may have changed (new unlock value, phrase)
            existing.phrase = phrase
            if missing.unlock_value is not None:
                existing.unlock_amount = float(missing.unlock_value)
            if missing.unlock_currency:
                existing.unlock_currency = missing.unlock_currency
            if missing.unlock_count is not None:
                existing.unlock_count = missing.unlock_count
            db_session.add(existing)
        else:
            row = InputRequest(
                tenant_id=UUID(tenant_id_str),
                kind=kind,
                phrase=phrase,
                unlock_amount=float(missing.unlock_value) if missing.unlock_value is not None else None,
                unlock_currency=missing.unlock_currency or "INR",
                unlock_count=missing.unlock_count,
                clearance=clearance,
            )
            db_session.add(row)

    db_session.commit()
    logger.info(
        "_persist_input_requests: upserted %d InputRequest rows for tenant %s",
        len(result.input_requests),
        tenant_id_str,
    )


# ---------------------------------------------------------------------------
# Private: derive metadata from findings
# ---------------------------------------------------------------------------


def _severity_from_finding(finding: dict) -> int:
    """Map impact magnitude to a 1-5 severity integer.

    1 = critical (> ₹10L), 2 = high, 3 = medium (default), 4 = low, 5 = info.
    Uses ``impact_amount`` if present; else maps confidence/level hints.
    """
    amt = finding.get("impact_amount")
    if amt is not None:
        try:
            f = float(amt)
            if f >= 1_000_000:
                return 1
            if f >= 100_000:
                return 2
            if f >= 10_000:
                return 3
            if f >= 1_000:
                return 4
            return 5
        except (TypeError, ValueError):
            pass
    # fall back to level hints
    level = str(finding.get("level", "") or finding.get("severity", "")).lower()
    if level in ("critical", "high"):
        return 1
    if level == "medium":
        return 3
    if level in ("low", "info"):
        return 5
    return 3  # default


def _seeded_from_finding(finding: dict) -> Optional[str]:
    """Derive a seeded question from a finding dict for the Today → chat jump."""
    title = finding.get("title", "")
    vendor = finding.get("vendor_name") or finding.get("party_name")
    po = finding.get("po_number")

    if not title:
        return None
    if vendor and po:
        return f"Tell me about {title} for {vendor} (PO {po})"
    if vendor:
        return f"Tell me more about {title} for {vendor}"
    return f"Tell me more about {title}"
