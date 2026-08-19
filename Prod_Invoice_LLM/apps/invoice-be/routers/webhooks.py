import logging
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import WebhookDeliveryLog, WebhookSubscription
from services.webhooks import validate_webhook_target_url, InvalidWebhookUrlError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Feature 15: the full set of events a subscription can register for.
# Gap 260: renamed invoice.paid → invoice.approved and
# outbound_invoice.paid → outbound_invoice.approved to reflect that
# the trigger is approval/verification, not payment settlement.
ALLOWED_EVENT_TYPES = {
    "invoice.processing",
    "invoice.completed",
    "invoice.audit_required",
    "invoice.duplicate",
    "invoice.approved",
    "invoice.rejected",
    "outbound_invoice.sent",
    "outbound_invoice.overdue",
    "outbound_invoice.approved",
}


class WebhookSubscriptionCreate(BaseModel):
    target_url: str
    subscribed_events: list[str] = Field(default=[])


class WebhookSubscriptionUpdate(BaseModel):
    target_url: Optional[str] = None
    subscribed_events: Optional[list[str]] = None
    enabled: Optional[bool] = None


def _validate_event_types(subscribed_events: list[str]) -> None:
    invalid = set(subscribed_events) - ALLOWED_EVENT_TYPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown event type(s): {sorted(invalid)}. Allowed: {sorted(ALLOWED_EVENT_TYPES)}",
        )


def _to_public_dict(sub: WebhookSubscription) -> dict:
    """Never include `secret` after creation -- it's only returned once, on POST."""
    return {
        "id": sub.id,
        "target_url": sub.target_url,
        "subscribed_events": sub.subscribed_events,
        "enabled": sub.enabled,
        "consecutive_failures": sub.consecutive_failures,
        # Gap 194: per-event-type consecutive failure counts. Lets the settings
        # page say *which* event is failing instead of just "this endpoint has
        # failed N times", and mirrors the granularity the auto-disable rule
        # now uses (services/webhooks.record_delivery_result).
        "event_failure_counts": sub.event_failure_counts or {},
        "created_at": sub.created_at,
        "updated_at": sub.updated_at,
    }


@router.get("")
async def list_webhooks(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    subs = db_session.exec(
        select(WebhookSubscription).where(WebhookSubscription.tenant_id == context.tenant_id)
    ).all()
    return [_to_public_dict(s) for s in subs]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookSubscriptionCreate,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    _validate_event_types(payload.subscribed_events)
    try:
        validate_webhook_target_url(payload.target_url)
    except InvalidWebhookUrlError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Generated server-side, never accepted from the client -- this is the
    # only response that will ever include it.
    secret = secrets.token_hex(32)

    sub = WebhookSubscription(
        tenant_id=context.tenant_id,
        target_url=payload.target_url,
        secret=secret,
        subscribed_events=payload.subscribed_events,
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)

    result = _to_public_dict(sub)
    result["secret"] = secret
    return result


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookSubscriptionUpdate,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    sub = db_session.exec(
        select(WebhookSubscription).where(
            WebhookSubscription.id == webhook_id, WebhookSubscription.tenant_id == context.tenant_id
        )
    ).first()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found.")

    if payload.target_url is not None:
        try:
            validate_webhook_target_url(payload.target_url)
        except InvalidWebhookUrlError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        sub.target_url = payload.target_url

    if payload.subscribed_events is not None:
        _validate_event_types(payload.subscribed_events)
        sub.subscribed_events = payload.subscribed_events

    if payload.enabled is not None:
        sub.enabled = payload.enabled
        # Task 15.5: re-enabling gives the subscription a clean slate rather
        # than immediately re-tripping the auto-disable threshold on the
        # very next delivery attempt with a stale failure count. Gap 194: the
        # per-event map is the counter that actually drives auto-disable now,
        # so it has to be cleared too -- clearing only the denormalised total
        # would leave the subscription one failed delivery from re-disabling.
        if payload.enabled:
            sub.consecutive_failures = 0
            sub.event_failure_counts = {}

    from datetime import datetime
    sub.updated_at = datetime.utcnow()

    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return _to_public_dict(sub)


@router.get("/{webhook_id}/deliveries")
async def list_webhook_deliveries(
    webhook_id: UUID,
    limit: int = Query(default=25, ge=1, le=100),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Gap 194: recent delivery attempts for one subscription, newest first.

    Delivery errors are swallowed by design (a subscriber being down must never
    fail the invoice operation that fired the event), so before this endpoint
    existed a completely broken fan-out was indistinguishable from a clean one
    from anywhere inside the product. Tenant-scoped through the same
    `tenant_id` check as every other route here, so one tenant can't read
    another's delivery history by guessing a subscription id.
    """
    sub = db_session.exec(
        select(WebhookSubscription).where(
            WebhookSubscription.id == webhook_id, WebhookSubscription.tenant_id == context.tenant_id
        )
    ).first()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found.")

    logs = db_session.exec(
        select(WebhookDeliveryLog)
        .where(
            WebhookDeliveryLog.subscription_id == webhook_id,
            WebhookDeliveryLog.tenant_id == context.tenant_id,
        )
        .order_by(WebhookDeliveryLog.created_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": log.id,
            "event_type": log.event_type,
            "success": log.success,
            "status_code": log.status_code,
            "attempts": log.attempts,
            "duration_ms": log.duration_ms,
            "error": log.error,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    sub = db_session.exec(
        select(WebhookSubscription).where(
            WebhookSubscription.id == webhook_id, WebhookSubscription.tenant_id == context.tenant_id
        )
    ).first()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found.")

    # Gap 194: webhook_delivery_logs has no FK to the subscription (it outlives
    # individual delivery attempts and is written from the queue worker), so
    # its rows have to be cleared explicitly or they'd be unreachable orphans
    # once the subscription they describe is gone.
    for log in db_session.exec(
        select(WebhookDeliveryLog).where(
            WebhookDeliveryLog.subscription_id == webhook_id,
            WebhookDeliveryLog.tenant_id == context.tenant_id,
        )
    ).all():
        db_session.delete(log)

    db_session.delete(sub)
    db_session.commit()
