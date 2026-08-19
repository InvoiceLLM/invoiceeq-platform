import json
import logging
from datetime import datetime
from uuid import uuid4, UUID
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from typing import Optional

from pydantic import BaseModel, Field

from dependencies import get_tenant_context, get_db_session, require_can_load, TenantContext
from models import Invoice, Tenant, User
from services.storage import upload_pdf_to_blob_storage
from services.staff_notify import notify_auditor_action
from services.invoice_visibility import invoice_not_deleted
from azure.storage.queue import QueueClient
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outbound-invoices", tags=["Outbound Invoices"])


class OutboundNotifyPayload(BaseModel):
    notify_emails: Optional[list[str]] = Field(
        default=None,
        description="Subset of the tenant outbound authorized set to notify (Gap 125). Never customers.",
    )


def _submitter_email_from_context(db_session: Session, context: TenantContext) -> str | None:
    if not context.db_user_id:
        return None
    user = db_session.get(User, context.db_user_id)
    if not user or not user.email:
        return None
    return str(user.email).strip().lower() or None


def _dispatch_outbound_webhook(db_session: Session, invoice: Invoice, event_type: str) -> None:
    """Feature 15 (Task 15.4): fires right after the commit that actually
    changed the status. `outbound_invoice.overdue` still has no call site here,
    and correctly so -- overdue is a virtual, read-time-only computation
    (Feature 7.1/8.1), not a status transition, so there is no commit in this
    router to hang it off. Gap 126 gave it the scheduled trigger it needed
    instead: services/outbound_overdue.py, run daily by
    scripts/sweep_outbound_overdue.py. Overdue is still never written to
    `Invoice.status`."""
    try:
        from services.webhooks import dispatch_webhook_event
        dispatch_webhook_event(db_session, invoice.tenant_id, event_type, {
            "invoice_id": str(invoice.id),
            "status": invoice.status,
            "customer_name": invoice.customer_name,
            "grand_total": invoice.grand_total,
            # Gap 215: same fix as the inbound dispatch sites -- a bare
            # grand_total is ambiguous on a blended multi-currency tenant.
            "currency": invoice.currency or "USD",
        })
    except Exception as we:
        logger.error("Webhook dispatch failed for outbound invoice %s: %s", invoice.id, we)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_outbound_invoice(
    file: UploadFile = File(...),
    # Feature 1.1 (Task 1.1.2): AR-side mirror of the inbound upload gate.
    # confirm-send / mark-paid below are deliberately left ungated in this pass
    # -- they are outbound *lifecycle* transitions, not ingestion, and were not
    # in the approved scope.
    context: TenantContext = Depends(require_can_load),
    db_session: Session = Depends(get_db_session),
):
    """Feature 2.1, Task 2.1.5: upload the tenant's own invoice to be sent to
    a customer. Gated on the Send Invoices toggle -- upload-only, no in-app
    invoice creation/generation (see feature_17_invoice_builder.md)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid file format: {file.filename}. Only PDF is allowed.")

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    if not tenant.send_invoices_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Send Invoices is not enabled for this tenant. Enable it in Settings first.",
        )

    invoice_id = uuid4()
    batch_id = uuid4()

    try:
        file_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to read file {file.filename}: {str(e)}")

    try:
        file_path = await run_in_threadpool(
            upload_pdf_to_blob_storage, file_bytes, str(context.tenant_id), str(invoice_id)
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to store file {file.filename}: {str(e)}")

    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        file_path=file_path,
        flow_direction="OUTBOUND",
        status="UPLOADED",
        submitted_by_email=_submitter_email_from_context(db_session, context),
    )
    db_session.add(db_invoice)
    await run_in_threadpool(db_session.commit)
    db_session.refresh(db_invoice)

    try:
        settings = get_settings()
        if settings.AZURE_STORAGE_CONNECTION_STRING:
            queue_client = QueueClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
            )
            queue_client.send_message(json.dumps({
                "task": "process_outbound_invoice",
                "kwargs": {"batch_id": str(batch_id), "file_path": file_path, "tenant_id": str(context.tenant_id)},
            }))
            # Gap 81: see routers/invoices.py -- the reconciliation sweep
            # measures staleness from this stamp, not from created_at.
            db_invoice.last_enqueued_at = datetime.utcnow()
            db_invoice.processing_attempts = 1
            db_session.add(db_invoice)
            await run_in_threadpool(db_session.commit)
        else:
            logger.error(
                "AZURE_STORAGE_CONNECTION_STRING missing -- outbound invoice %s was stored but never "
                "queued and will sit at UPLOADED until the reconciliation sweep re-enqueues it.",
                invoice_id,
            )
    except Exception as e:
        # Gap 81: promoted from warning. Azurite/Azure accepting an upload while
        # the queue send fails is precisely the silent-forever case this gap was
        # about -- the request still returns 201, so the log line is the only
        # signal that exists.
        logger.error(
            "Failed to dispatch outbound extraction queue task for invoice %s -- it will remain at "
            "UPLOADED until the reconciliation sweep re-enqueues it: %s",
            invoice_id, e,
        )

    return {"batch_id": str(batch_id), "invoice_id": str(invoice_id)}


@router.put("/{invoice_id}/confirm-send", status_code=status.HTTP_200_OK)
async def confirm_send_outbound_invoice(
    invoice_id: UUID,
    payload: OutboundNotifyPayload | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 2.1 + Gap 125: VERIFIED/NEEDS_REVIEW → SENT. Staff notify only
    (registered outbound set); never emails the end customer."""
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

    if invoice.status not in ("VERIFIED", "NEEDS_REVIEW"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm-send an invoice with status '{invoice.status}'. Must be VERIFIED or NEEDS_REVIEW.",
        )

    notify_emails = (payload.notify_emails if payload else None)
    try:
        # Validate before mutating so a bad list doesn't leave a half-sent state.
        from services.staff_notify import validate_notify_emails
        validate_notify_emails(
            db_session, tenant_id=invoice.tenant_id, email_set="outbound", notify_emails=notify_emails,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve

    invoice.status = "SENT"
    invoice.sent_at = datetime.utcnow()
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    _dispatch_outbound_webhook(db_session, invoice, "outbound_invoice.sent")
    email_notify = notify_auditor_action(
        db_session, invoice, action_label="Confirm Send (SENT)", notify_emails=notify_emails,
    )

    return {
        "success": True,
        "status": invoice.status,
        "sent_at": invoice.sent_at.isoformat(),
        "email_notify": email_notify,
    }


@router.put("/{invoice_id}/mark-paid", status_code=status.HTTP_200_OK)
async def mark_outbound_invoice_paid(
    invoice_id: UUID,
    payload: OutboundNotifyPayload | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """SENT → PAID + optional staff notify (Gap 125)."""
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

    if invoice.status != "SENT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot mark an invoice with status '{invoice.status}' as paid. Must be SENT.",
        )

    notify_emails = (payload.notify_emails if payload else None)
    try:
        from services.staff_notify import validate_notify_emails
        validate_notify_emails(
            db_session, tenant_id=invoice.tenant_id, email_set="outbound", notify_emails=notify_emails,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve

    invoice.status = "PAID"
    invoice.paid_at = datetime.utcnow()
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    _dispatch_outbound_webhook(db_session, invoice, "outbound_invoice.approved")
    email_notify = notify_auditor_action(
        db_session, invoice, action_label="Mark Paid", notify_emails=notify_emails,
    )

    return {
        "success": True,
        "status": invoice.status,
        "paid_at": invoice.paid_at.isoformat(),
        "email_notify": email_notify,
    }
