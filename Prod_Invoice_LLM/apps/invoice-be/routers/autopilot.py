"""
Feature 13: Tenant Autopilot — API Router (routers/autopilot.py)

Endpoints:
  GET  /api/v1/autopilot/config   — fetch current tenant autopilot config
  PUT  /api/v1/autopilot/config   — upsert tenant autopilot config
  POST /api/v1/autopilot/sync     — trigger immediate manual sync ("Sync Now")
  GET  /api/v1/autopilot/history  — paginated sync run log
"""
import logging
from uuid import UUID
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlmodel import Session, select

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
    """One row in the sync history table"""
    id: UUID
    source_type: str
    source_file_id: str
    content_hash: str
    ingested_at: datetime
    status: str
    error_detail: Optional[str] = None


class AutopilotHistoryResponse(BaseModel):
    items: list[AutopilotLogEntry]
    total: int
    page: int
    page_size: int


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
        summary = run_sync(context.tenant_id, db_session)
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
# GET /autopilot/history  — Sync run log
# ---------------------------------------------------------------------------

@router.get("/history", response_model=AutopilotHistoryResponse)
def get_autopilot_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_session),
):
    """
    Returns a paginated list of all Autopilot sync log entries for this tenant,
    ordered by most recent first. Used to render the Sync History table in the UI.
    """
    offset = (page - 1) * page_size

    # Total count
    all_logs = db_session.exec(
        select(TenantAutopilotLog).where(
            TenantAutopilotLog.tenant_id == context.tenant_id
        )
    ).all()
    total = len(all_logs)

    # Paginated results, newest first
    logs = db_session.exec(
        select(TenantAutopilotLog)
        .where(TenantAutopilotLog.tenant_id == context.tenant_id)
        .order_by(TenantAutopilotLog.ingested_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(page_size)
    ).all()

    return AutopilotHistoryResponse(
        items=[
            AutopilotLogEntry(
                id=log.id,
                source_type=log.source_type,
                source_file_id=log.source_file_id,
                content_hash=log.content_hash,
                ingested_at=log.ingested_at,
                status=log.status,
                error_detail=log.error_detail,
            )
            for log in logs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
