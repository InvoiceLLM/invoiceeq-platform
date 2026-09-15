"""Admin-only change history for one invoice (founder request 2026-09-15, raised with BE Gap 532).

Every saved decision or correction already writes an `AuditLog` row — who, role, when, and each
field's old → new value — and BE Gap 550 keeps those rows when an invoice is deleted, but nothing
showed them to anyone. This router reads them back, newest first, for the "Change history" panel
on the inbound and outbound review consoles.

Read-only, and only for a signed-in Admin (API keys are not admitted). A refused correction saves
nothing and writes no row, so it does not appear (founder ruling 2026-09-15: saved changes only).

Its own router, not a route on `routers/audit.py`: that router's gate admits `actions`-scoped API
keys and non-Admin auditors, and its own comment says a read view must not inherit that gate.
"""
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from dependencies import TenantContext, get_db_session, get_tenant_context
from models import AuditLog, Invoice, User
from services.invoice_visibility import invoice_not_deleted

router = APIRouter(prefix="/audit-history", tags=["Audit"])


def require_admin_session(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Admin can view an invoice's change history.",
        )
    return context


@router.get("/{invoice_id}")
async def get_invoice_change_history(
    invoice_id: UUID,
    limit: int = Query(200, ge=1, le=500),
    context: TenantContext = Depends(require_admin_session),
    db_session: Session = Depends(get_db_session),
):
    """The invoice's saved changes, newest first: who made each one, when, and what it changed."""
    invoice_exists = db_session.exec(
        select(Invoice.id).where(
            Invoice.id == invoice_id,
            Invoice.tenant_id == context.tenant_id,
            invoice_not_deleted(),
        )
    ).first()
    if invoice_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found or access denied.")

    rows = db_session.exec(
        select(AuditLog, User)
        .join(User, AuditLog.actor_user_id == User.id, isouter=True)
        .where(AuditLog.tenant_id == context.tenant_id, AuditLog.invoice_id == invoice_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
    ).all()
    return {"invoice_id": str(invoice_id), "entries": [_entry(log, actor) for log, actor in rows]}


def _entry(log: AuditLog, actor: User | None) -> dict:
    details = log.details or {}
    recorded_dismissals = details.get("dismissed_alerts")
    actor_name = " ".join(part for part in (actor.first_name, actor.last_name) if part) if actor else ""
    timestamp = log.timestamp if log.timestamp.tzinfo else log.timestamp.replace(tzinfo=timezone.utc)
    return {
        "id": str(log.id),
        "timestamp": timestamp.isoformat(),
        "action": log.action,
        "actor_email": actor.email if actor else None,
        "actor_name": actor_name or None,
        "actor_role": log.actor_role,
        "auth_method": details.get("auth_method"),
        "api_key_prefix": details.get("api_key_prefix"),
        "previous_status": details.get("previous_status"),
        "target_status": details.get("target_status"),
        "reject_reason": details.get("reject_reason"),
        "corrections": details.get("corrections") or {},
        # Rows written before BE Gap 537 recorded only the raw dismissal input.
        "dismissed_alerts": recorded_dismissals if recorded_dismissals is not None else details.get("dismissed_alerts_input") or [],
        "raised_alerts": details.get("raised_alerts") or [],
        "notify_emails": details.get("notify_emails") or [],
    }
