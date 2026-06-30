import logging
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from datetime import datetime

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, AuditLog
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Audit"])

class AuditResolutionPayload(BaseModel):
    status: str = Field(..., description="Target status: PAID or REJECTED")
    dismissed_alerts: Optional[List[str]] = Field(default=None, description="Alert messages, types, or IDs to dismiss")

@router.put("/resolve/{invoice_id}")
async def resolve_audit_invoice(
    invoice_id: UUID,
    payload: AuditResolutionPayload,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Enables manual auditor override actions: dismiss alerts, update invoice status 
    to PAID or REJECTED, and log the action to the audit logs.
    """
    # 1. Validate status
    target_status = payload.status.upper()
    if target_status not in ["PAID", "REJECTED"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target status '{payload.status}'. Must be PAID or REJECTED."
        )

    # 2. Retrieve the target invoice with tenant isolation scope
    statement = select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id)
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )

    # 3. Dismiss specified warnings
    previous_alerts = list(invoice.sa_alerts or [])
    dismissed_list = payload.dismissed_alerts or []
    
    new_alerts = []
    for alert in previous_alerts:
        if isinstance(alert, str):
            if alert not in dismissed_list:
                new_alerts.append(alert)
        elif isinstance(alert, dict):
            alert_id = alert.get("id")
            alert_type = alert.get("type")
            alert_msg = alert.get("message")
            if (alert_id not in dismissed_list) and (alert_type not in dismissed_list) and (alert_msg not in dismissed_list):
                new_alerts.append(alert)
        else:
            new_alerts.append(alert)
            
    # Assign the new list (needs to be a new list object so SQLModel/SQLAlchemy registers the update)
    invoice.sa_alerts = new_alerts
    invoice.status = target_status
    db_session.add(invoice)

    # 4. Save audit log record
    log_details = {
        "target_status": target_status,
        "dismissed_alerts_input": dismissed_list,
        "previous_alerts": previous_alerts,
        "remaining_alerts": new_alerts
    }
    
    audit_log = AuditLog(
        tenant_id=context.tenant_id,
        invoice_id=invoice_id,
        actor_user_id=context.user_id,
        actor_role=context.role,
        action="RESOLVE_INVOICE",
        details=log_details,
        timestamp=datetime.utcnow()
    )
    db_session.add(audit_log)
    
    # 5. Commit transaction
    db_session.commit()
    
    return {"success": True}
