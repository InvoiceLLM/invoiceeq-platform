"""
Feature 13: Tenant Autopilot — API Router (routers/autopilot.py)

Endpoints:
  GET  /api/v1/autopilot/config   — fetch current tenant autopilot config
  PUT  /api/v1/autopilot/config   — upsert tenant autopilot config
  POST /api/v1/autopilot/sync     — trigger immediate manual sync ("Sync Now")
  GET  /api/v1/autopilot/history  — paginated list of sync RUNS (Gap 427)
  GET  /api/v1/autopilot/history/{batch_id}/files — one run's per-file detail
  GET  /api/v1/autopilot/history/legacy/files     — files of the pre-Gap-427
                                                    "no batch_id" legacy bucket
"""
import logging
from uuid import UUID
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import case
from sqlmodel import Session, func, select

from database import get_session
from dependencies import get_tenant_context, TenantContext
from models import TenantAutopilotConfig, TenantAutopilotLog
from services.autopilot_sync import run_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/autopilot", tags=["Autopilot"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AutopilotConfigPayload(BaseModel):
    """Request body for PUT /autopilot/config"""
    source_type: str          # 'gdrive' (Gap 334 removed 'salesforce')
    source_ref: str           # Google Drive folder ID
    flow_direction: str = "INBOUND"   # 'INBOUND' | 'OUTBOUND'
    trigger_mode: str         # 'interval' | 'cron'
    trigger_value: str        # e.g. '60' (minutes) or '0 * * * *' (cron)
    notify_emails: list[str] = []
    send_approval_links: bool = False


class AutopilotConfigResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    source_type: str
    source_ref: str
    flow_direction: str
    trigger_mode: str
    trigger_value: str
    notify_emails: list
    send_approval_links: bool
    created_at: datetime
    updated_at: datetime


class AutopilotSyncResponse(BaseModel):
    """Response from POST /autopilot/sync"""
    processed: int
    skipped: int
    failed: int
    # Gap 343: the run stopped because the tenant's free-tier allowance ran out,
    # not because anything went wrong. Defaulted so an older client (and the
    # scheduled job, which reads no response at all) is unaffected.
    quota_exhausted: bool = False
    message: str


class AutopilotLogEntry(BaseModel):
    """One FILE inside a sync run — the drill-down row.

    Gap 427: `source_type` moved off this model and up onto the run, where it
    actually belongs (every file in a run comes from the same source). Gained
    `source_file_name`, which is the whole point of the drill-down — the raw
    `source_file_id` is a Google Drive identifier no human can read, and it was
    previously the only thing the history table had to show.
    """
    id: UUID
    source_file_id: str
    source_file_name: Optional[str] = None
    content_hash: str
    ingested_at: datetime
    status: str
    error_detail: Optional[str] = None


class AutopilotRunEntry(BaseModel):
    """One RUN in the sync history table (Gap 427).

    `batch_id` and `trigger` are nullable for exactly one reason: the single
    synthetic bucket that holds every log row written before run tracking
    existed. A real run always has both.
    """
    batch_id: Optional[str] = None
    trigger: Optional[str] = None
    source_type: str
    started_at: datetime
    finished_at: datetime
    files_seen: int
    imported: int
    skipped: int
    failed: int
    # 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'NO_NEW_FILES'
    status: str


class AutopilotHistoryResponse(BaseModel):
    items: list[AutopilotRunEntry]
    total: int
    page: int
    page_size: int


class AutopilotRunFilesResponse(BaseModel):
    """Response for GET /autopilot/history/{batch_id}/files — not paginated.

    One run's file count is bounded by what a single sync cycle listed, which is
    small enough to return whole; paginating it would add a second cursor to the
    UI for no benefit.
    """
    items: list[AutopilotLogEntry]


# ---------------------------------------------------------------------------
# GET /autopilot/config
# ---------------------------------------------------------------------------

@router.get("/config", response_model=AutopilotConfigResponse | None)
def get_autopilot_config(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """
    Returns the current Autopilot configuration for this tenant.
    Returns null (204) if no configuration has been saved yet.
    """
    config = db_session.exec(
        select(TenantAutopilotConfig).where(
            TenantAutopilotConfig.tenant_id == context.tenant_id
        )
    ).first()

    if not config:
        return None

    return AutopilotConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        source_type=config.source_type,
        source_ref=config.source_ref,
        flow_direction=config.flow_direction,
        trigger_mode=config.trigger_mode,
        trigger_value=config.trigger_value,
        notify_emails=config.notify_emails or [],
        send_approval_links=config.send_approval_links,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ---------------------------------------------------------------------------
# PUT /autopilot/config
# ---------------------------------------------------------------------------

@router.put("/config", response_model=AutopilotConfigResponse)
def upsert_autopilot_config(
    payload: AutopilotConfigPayload,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """
    Creates or fully replaces the Autopilot configuration for this tenant.
    Only one config is allowed per tenant (upsert on tenant_id).
    """
    # Validate source_type
    valid_sources = {"gdrive"}  # Gap 334 removed "salesforce"
    if payload.source_type not in valid_sources:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"source_type must be one of: {sorted(valid_sources)}",
        )

    # Validate flow_direction
    if payload.flow_direction not in ("INBOUND", "OUTBOUND"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="flow_direction must be 'INBOUND' or 'OUTBOUND'",
        )

    # Validate trigger_mode
    if payload.trigger_mode not in ("interval", "cron"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="trigger_mode must be 'interval' or 'cron'",
        )

    existing = db_session.exec(
        select(TenantAutopilotConfig).where(
            TenantAutopilotConfig.tenant_id == context.tenant_id
        )
    ).first()

    now = datetime.utcnow()

    if existing:
        # Update in place
        existing.source_type = payload.source_type
        existing.source_ref = payload.source_ref
        existing.flow_direction = payload.flow_direction
        existing.trigger_mode = payload.trigger_mode
        existing.trigger_value = payload.trigger_value
        existing.notify_emails = payload.notify_emails
        existing.send_approval_links = payload.send_approval_links
        existing.updated_at = now
        db_session.add(existing)
        db_session.commit()
        db_session.refresh(existing)
        config = existing
    else:
        config = TenantAutopilotConfig(
            tenant_id=context.tenant_id,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            flow_direction=payload.flow_direction,
            trigger_mode=payload.trigger_mode,
            trigger_value=payload.trigger_value,
            notify_emails=payload.notify_emails,
            send_approval_links=payload.send_approval_links,
        )
        db_session.add(config)
        db_session.commit()
        db_session.refresh(config)

    logger.info("Autopilot config saved for tenant %s", context.tenant_id)

    return AutopilotConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        source_type=config.source_type,
        source_ref=config.source_ref,
        flow_direction=config.flow_direction,
        trigger_mode=config.trigger_mode,
        trigger_value=config.trigger_value,
        notify_emails=config.notify_emails or [],
        send_approval_links=config.send_approval_links,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /autopilot/sync  — Manual "Sync Now" trigger
# ---------------------------------------------------------------------------

@router.post("/sync", response_model=AutopilotSyncResponse)
def trigger_sync(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """
    Triggers an immediate manual Autopilot sync for this tenant.
    Uses the exact same engine as the scheduled ACA Job.
    Returns a summary of files processed, skipped, and failed.
    """
    try:
        # Gap 427: 'manual' is stamped on every log row this run writes, so the
        # history table can tell a human pressing Sync Now apart from the
        # unattended scheduled job.
        summary = run_sync(context.tenant_id, db_session, trigger="manual")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("Autopilot manual sync failed for tenant %s: %s", context.tenant_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(exc)}",
        )

    quota_exhausted = bool(summary.get("quota_exhausted"))
    message = (
        f"Sync complete. {summary['processed']} new file(s) imported, "
        f"{summary['skipped']} skipped (duplicate), "
        f"{summary['failed']} failed."
    )
    if quota_exhausted:
        # Gap 343: a run that stopped on quota is not a failure the user should
        # go debugging -- say what actually happened and what fixes it.
        message += (
            " Stopped early: this workspace's free-tier invoice allowance is "
            "used up. Remaining files will be picked up after the monthly "
            "refill, or immediately on a paid plan."
        )

    return AutopilotSyncResponse(
        processed=summary["processed"],
        skipped=summary["skipped"],
        failed=summary["failed"],
        quota_exhausted=quota_exhausted,
        message=message,
    )


# ---------------------------------------------------------------------------
# GET /autopilot/history  — Sync RUNS (Gap 427)
# ---------------------------------------------------------------------------
#
# This endpoint used to return one item per *file* — date, source, raw Google
# Drive file ID, status — which made the FE Sync History table an unreadable
# wall of opaque identifiers with no way to tell one sync from the next. It now
# returns one item per *run*, derived by grouping tenant_autopilot_logs on the
# batch_id that services/autopilot_sync.py stamps on every row it writes; the
# per-file detail moved to the drill-down endpoint below.
#
# This is a deliberate breaking change to the response shape. The FE
# (FE Gap 428) is being rewritten against exactly this contract in parallel.
#
# Run totals are DERIVED from the file rows rather than stored in a summary row
# of their own: a summary row would be a second copy of the same facts that can
# drift out of agreement with the rows it summarizes, and a run's rows are all
# written inside the same run anyway.

def _derive_run_status(imported: int, skipped: int, failed: int, no_new: int) -> str:
    """Collapse a run's per-file statuses into one run-level status.

    The rules, in the order they are checked:
      - a run whose only row is the NO_NEW_FILES marker -> NO_NEW_FILES
      - any failure alongside any success/skip           -> PARTIAL
      - failures and nothing else                        -> FAILED
      - anything else (including a run where every file was a duplicate and
        nothing was imported)                            -> SUCCESS

    "Every file skipped" is SUCCESS, not an empty or failed run: dedup working
    correctly is the system doing its job, and `imported: 0` alongside a
    non-zero `skipped` already tells the user what happened.
    """
    if no_new and not (imported or skipped or failed):
        return "NO_NEW_FILES"
    if failed and (imported or skipped):
        return "PARTIAL"
    if failed:
        return "FAILED"
    return "SUCCESS"


def _status_count(status_value: str):
    """SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) — one grouped count per status.

    Used instead of four separate queries so the whole history page is a single
    GROUP BY round-trip, and wrapped in COALESCE so an empty group reads as 0
    rather than NULL.
    """
    return func.coalesce(
        func.sum(case((TenantAutopilotLog.status == status_value, 1), else_=0)), 0
    )


def _run_aggregate_columns():
    """The aggregate expressions every run row (real or legacy) is built from."""
    return (
        func.min(TenantAutopilotLog.ingested_at).label("started_at"),
        func.max(TenantAutopilotLog.ingested_at).label("finished_at"),
        _status_count("SUCCESS").label("imported"),
        _status_count("SKIPPED_DUPLICATE").label("skipped"),
        _status_count("FAILED").label("failed"),
        _status_count("NO_NEW_FILES").label("no_new"),
        func.max(TenantAutopilotLog.source_type).label("source_type"),
        func.max(TenantAutopilotLog.trigger).label("trigger"),
    )


def _row_to_run(row, batch_id, trigger) -> "AutopilotRunEntry":
    imported = int(row.imported or 0)
    skipped = int(row.skipped or 0)
    failed = int(row.failed or 0)
    no_new = int(row.no_new or 0)
    return AutopilotRunEntry(
        batch_id=batch_id,
        trigger=trigger,
        source_type=row.source_type or "",
        started_at=row.started_at,
        finished_at=row.finished_at,
        # The NO_NEW_FILES marker is not a file, so it must not be counted as
        # one — a run that found nothing reports files_seen: 0, not 1.
        files_seen=imported + skipped + failed,
        imported=imported,
        skipped=skipped,
        failed=failed,
        status=_derive_run_status(imported, skipped, failed, no_new),
    )


@router.get("/history", response_model=AutopilotHistoryResponse)
def get_autopilot_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """
    Returns this tenant's Autopilot sync history as a paginated list of RUNS,
    newest first. Drill into one run's files with
    `GET /autopilot/history/{batch_id}/files`.

    Rows written before Gap 427 added `batch_id` carry no run identity and can
    never be assigned one, so they are collapsed into a SINGLE synthetic item
    with `batch_id: null` and `trigger: null`, always ordered last — one
    "before run tracking" bucket rather than thousands of one-file pseudo-runs.
    Its files come from `GET /autopilot/history/legacy/files`.
    """
    offset = (page - 1) * page_size
    tenant_filter = TenantAutopilotLog.tenant_id == context.tenant_id
    has_batch = TenantAutopilotLog.batch_id.is_not(None)  # type: ignore[union-attr]
    no_batch = TenantAutopilotLog.batch_id.is_(None)  # type: ignore[union-attr]

    # Gap 360's rule still applies: nothing is materialized just to be counted.
    total_runs = int(
        db_session.exec(
            select(func.count(func.distinct(TenantAutopilotLog.batch_id))).where(
                tenant_filter, has_batch
            )
        ).one()
    )

    legacy_exists = (
        db_session.exec(
            select(TenantAutopilotLog.id).where(tenant_filter, no_batch).limit(1)
        ).first()
        is not None
    )

    total = total_runs + (1 if legacy_exists else 0)

    run_rows = db_session.exec(
        select(TenantAutopilotLog.batch_id, *_run_aggregate_columns())
        .where(tenant_filter, has_batch)
        .group_by(TenantAutopilotLog.batch_id)
        .order_by(func.min(TenantAutopilotLog.ingested_at).desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    items = [_row_to_run(row, str(row.batch_id), row.trigger) for row in run_rows]

    # The legacy bucket sits at index `total_runs` in the full ordering, i.e.
    # immediately after the last real run — so it belongs on this page only if
    # this page's window actually reaches that far and still has room.
    if legacy_exists and offset + page_size > total_runs and len(items) < page_size:
        legacy_row = db_session.exec(
            select(*_run_aggregate_columns()).where(tenant_filter, no_batch)
        ).one()
        items.append(_row_to_run(legacy_row, None, None))

    return AutopilotHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def _to_file_entry(log: TenantAutopilotLog) -> "AutopilotLogEntry":
    return AutopilotLogEntry(
        id=log.id,
        source_file_id=log.source_file_id,
        source_file_name=log.source_file_name,
        content_hash=log.content_hash,
        ingested_at=log.ingested_at,
        status=log.status,
        error_detail=log.error_detail,
    )


# ---------------------------------------------------------------------------
# GET /autopilot/history/legacy/files  — the pre-Gap-427 bucket's files
# ---------------------------------------------------------------------------
#
# Declared BEFORE the /{batch_id}/files route below on purpose: FastAPI matches
# routes in declaration order, and "legacy" is not a UUID, so with the order
# reversed this path would be swallowed by the parameterized route and rejected
# as a malformed UUID instead of reaching this handler.

@router.get("/history/legacy/files", response_model=AutopilotRunFilesResponse)
def get_legacy_run_files(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """Files belonging to the synthetic `batch_id: null` legacy run bucket."""
    logs = db_session.exec(
        select(TenantAutopilotLog)
        .where(
            TenantAutopilotLog.tenant_id == context.tenant_id,
            TenantAutopilotLog.batch_id.is_(None),  # type: ignore[union-attr]
        )
        .order_by(TenantAutopilotLog.ingested_at.desc())  # type: ignore[union-attr]
    ).all()
    return AutopilotRunFilesResponse(items=[_to_file_entry(log) for log in logs])


# ---------------------------------------------------------------------------
# GET /autopilot/history/{batch_id}/files  — one run's per-file detail
# ---------------------------------------------------------------------------

@router.get("/history/{batch_id}/files", response_model=AutopilotRunFilesResponse)
def get_run_files(
    batch_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """
    Returns every log row written by one sync run, newest first (matching the
    ordering of the runs list itself).

    Tenant-scoped in the WHERE clause, not merely looked up by batch_id: a
    batch_id is a bare UUID in the URL and this filter is the only thing
    standing between one tenant and another tenant's file names. An unknown
    batch_id and another tenant's batch_id both return 404 — deliberately
    indistinguishable, so this endpoint cannot be used to probe which run ids
    exist.
    """
    logs = db_session.exec(
        select(TenantAutopilotLog)
        .where(
            TenantAutopilotLog.tenant_id == context.tenant_id,
            TenantAutopilotLog.batch_id == batch_id,
        )
        .order_by(TenantAutopilotLog.ingested_at.desc())  # type: ignore[union-attr]
    ).all()

    if not logs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync run not found.",
        )

    return AutopilotRunFilesResponse(items=[_to_file_entry(log) for log in logs])
