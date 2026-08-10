"""
Feature 16: Settings — Service Flow endpoint.

Routes
------
GET  /api/v1/settings/vendor-flow   — readable by any authenticated role
PUT  /api/v1/settings/vendor-flow   — Admin only; enforces billing plan + outbound set gate
"""
import logging
import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Tenant, TenantEmailSender

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


class VendorFlowSettings(BaseModel):
    receive_invoices_enabled: bool
    send_invoices_enabled: bool
    outbound_sender_email: str | None
    billing_plan: str
    outbound_authorized_count: int = 0


class VendorFlowUpdateRequest(BaseModel):
    receive_invoices_enabled: bool | None = None
    send_invoices_enabled: bool | None = None
    outbound_sender_email: str | None = None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _outbound_set_count(db_session: Session, tenant_id) -> int:
    rows = db_session.exec(
        select(TenantEmailSender).where(
            TenantEmailSender.tenant_id == tenant_id,
            TenantEmailSender.email_set == "outbound",
        )
    ).all()
    return len(rows)


@router.get("/vendor-flow", response_model=VendorFlowSettings)
async def get_vendor_flow_settings(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    return VendorFlowSettings(
        receive_invoices_enabled=tenant.receive_invoices_enabled,
        send_invoices_enabled=tenant.send_invoices_enabled,
        outbound_sender_email=tenant.outbound_sender_email,
        billing_plan=tenant.billing_plan,
        outbound_authorized_count=_outbound_set_count(db_session, tenant.id),
    )


@router.put("/vendor-flow", response_model=VendorFlowSettings)
async def update_vendor_flow_settings(
    payload: VendorFlowUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """
    Admin-only. Enabling send_invoices requires:
    - ≥1 TenantEmailSender with email_set=outbound (400 otherwise)
    - billing_plan == pro_combined (402 otherwise)
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can modify Service Flow settings.",
        )

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    new_receive = (
        payload.receive_invoices_enabled
        if payload.receive_invoices_enabled is not None
        else tenant.receive_invoices_enabled
    )
    new_send = (
        payload.send_invoices_enabled
        if payload.send_invoices_enabled is not None
        else tenant.send_invoices_enabled
    )
    new_email = (
        payload.outbound_sender_email
        if payload.outbound_sender_email is not None
        else tenant.outbound_sender_email
    )

    if new_email is not None and not _valid_email(new_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="outbound_sender_email is not a valid email address.",
        )

    outbound_count = _outbound_set_count(db_session, tenant.id)

    if new_send:
        if outbound_count < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "At least one outbound authorized email must be registered under "
                    "Settings → Email before enabling send_invoices_enabled."
                ),
            )
        if tenant.billing_plan != "pro_combined":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    "Sending invoices requires the Pro Combined plan (₹8,999/month). "
                    "Please upgrade your subscription."
                ),
            )

    tenant.receive_invoices_enabled = new_receive
    tenant.send_invoices_enabled = new_send
    tenant.outbound_sender_email = new_email

    from datetime import datetime
    tenant.updated_at = datetime.utcnow()

    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    logger.info(
        "Service Flow settings updated for tenant=%s by user=%s: receive=%s send=%s outbound_set=%s",
        context.tenant_id, context.user_id,
        tenant.receive_invoices_enabled, tenant.send_invoices_enabled, outbound_count,
    )

    return VendorFlowSettings(
        receive_invoices_enabled=tenant.receive_invoices_enabled,
        send_invoices_enabled=tenant.send_invoices_enabled,
        outbound_sender_email=tenant.outbound_sender_email,
        billing_plan=tenant.billing_plan,
        outbound_authorized_count=outbound_count,
    )
