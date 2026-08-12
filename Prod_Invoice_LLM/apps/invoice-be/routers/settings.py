"""
Feature 16: Settings — Service Flow endpoint.
Gap 184: Settings — programmatic API key (security) endpoints.

Routes
------
GET  /api/v1/settings/vendor-flow              — readable by any authenticated role
PUT  /api/v1/settings/vendor-flow              — Admin only; enforces billing plan + outbound set gate
GET  /api/v1/settings/security/api-key         — key metadata only (never the key itself)
POST /api/v1/settings/security/api-key/rotate  — Admin only; issues a new key, invalidates the old one
GET  /api/v1/settings/security/api-key/verify  — authenticated BY the API key; lets an
                                                 integrator confirm a key works
"""
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel

from dependencies import (
    get_api_key_context,
    get_tenant_context,
    get_db_session,
    TenantContext,
)
from models import Tenant, TenantEmailSender
from services.api_keys import (
    generate_api_key,
    generate_salt,
    hash_api_key,
    key_prefix,
    masked_display,
)

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


# --- Gap 184: programmatic API key ----------------------------------------


class ApiKeyStatus(BaseModel):
    """
    What the Security settings page is allowed to know about the live key.

    `key_prefix`/`masked_key` are the non-secret leading characters only. There
    is deliberately no field here that could carry the key itself: the raw value
    exists in exactly one response in the whole API (ApiKeyRotateResponse).
    """
    has_key: bool
    key_prefix: str | None = None
    masked_key: str | None = None
    rotated_at: datetime | None = None
    last_used_at: datetime | None = None
    can_rotate: bool = False


class ApiKeyRotateResponse(ApiKeyStatus):
    """The one and only response that carries a raw key. See rotate_api_key()."""
    api_key: str


def _api_key_status(tenant: Tenant, context: TenantContext) -> ApiKeyStatus:
    return ApiKeyStatus(
        has_key=bool(tenant.api_key_hash),
        key_prefix=tenant.api_key_prefix,
        masked_key=masked_display(tenant.api_key_prefix),
        rotated_at=tenant.api_key_rotated_at,
        last_used_at=tenant.api_key_last_used_at,
        can_rotate=context.role == "Admin",
    )


@router.get("/security/api-key", response_model=ApiKeyStatus)
async def get_api_key_status(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """
    Metadata about this tenant's API key. Readable by any authenticated role
    (a non-Admin still needs to see whether an integration key exists and when
    it was last used); `can_rotate` tells the UI whether to offer the button.

    `has_key=False` is a real state, not an error -- a tenant that has never
    rotated has no key. The frontend renders an "issue a key" prompt for it,
    which is what Gap 184's hardcoded `inv_live_9f8a...` string was hiding.
    """
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return _api_key_status(tenant, context)


@router.post("/security/api-key/rotate", response_model=ApiKeyRotateResponse)
async def rotate_api_key(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """
    Admin-only. Issue a new API key and invalidate the previous one.

    The same endpoint issues the first key and rotates a later one -- there is
    one key per tenant, so "create" and "rotate" are the same write. Overwriting
    hash+salt+prefix in a single commit is what revokes the old key: nothing
    remains to verify the previous digest against, so any request still carrying
    it 401s from the next request onward.

    The raw key in this response is the only time it is ever transmitted. It is
    not stored, not logged, and cannot be re-read -- a caller who loses it has
    to rotate again. The log line below records the prefix only, on purpose.
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can rotate the API key.",
        )

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    raw_key = generate_api_key()
    salt = generate_salt()

    tenant.api_key_hash = hash_api_key(raw_key, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw_key)
    tenant.api_key_rotated_at = datetime.utcnow()
    # A freshly issued key has never authenticated anything; carrying the old
    # key's last-used timestamp forward would misreport the new one as in use.
    tenant.api_key_last_used_at = None
    tenant.updated_at = datetime.utcnow()

    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    logger.info(
        "API key rotated for tenant=%s by user=%s (prefix=%s)",
        context.tenant_id, context.user_id, tenant.api_key_prefix,
    )

    status_payload = _api_key_status(tenant, context)
    return ApiKeyRotateResponse(**status_payload.model_dump(), api_key=raw_key)


class ApiKeyIdentity(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    role: str
    billing_plan: str


@router.get("/security/api-key/verify", response_model=ApiKeyIdentity)
async def verify_api_key_endpoint(
    context: TenantContext = Depends(get_api_key_context),
):
    """
    Authenticated by the API key itself (`X-API-Key` or `Authorization: Bearer
    <key>`), not by a Clerk session -- this is the one route that exercises the
    programmatic auth path end to end, so an integrator can confirm a key works
    before wiring it into anything.

    It returns identity only (which tenant the key resolved to, and the role
    key-auth runs as), never tenant data: Gap 184 is about authentication, and
    widening what key-auth can *read* is a separate, deliberate decision.
    """
    return ApiKeyIdentity(
        tenant_id=str(context.tenant_id),
        tenant_name=context.tenant_name,
        role=context.role,
        billing_plan=context.billing_plan,
    )
