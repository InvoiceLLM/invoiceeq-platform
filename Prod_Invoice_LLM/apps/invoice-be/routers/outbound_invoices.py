import json
import logging
from datetime import datetime
from uuid import uuid4, UUID
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, Tenant
from services.storage import upload_pdf_to_blob_storage
from azure.storage.queue import QueueClient
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outbound-invoices", tags=["Outbound Invoices"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_outbound_invoice(
    file: UploadFile = File(...),
    context: TenantContext = Depends(get_tenant_context),
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
        else:
            logger.warning("AZURE_STORAGE_CONNECTION_STRING missing, skipped queueing outbound invoice %s.", invoice_id)
    except Exception as e:
        logger.warning("Failed to dispatch outbound extraction queue task: %s", e)

    return {"batch_id": str(batch_id), "invoice_id": str(invoice_id)}


@router.put("/{invoice_id}/confirm-send", status_code=status.HTTP_200_OK)
async def confirm_send_outbound_invoice(
    invoice_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 2.1, Task 2.1.5: VERIFIED (or corrected NEEDS_REVIEW) -> SENT.
    The actual email-send call is a separate concern (feature_16_settings.md's
    outbound_sender_email) -- this endpoint only finalizes the pre-send review
    step and stamps sent_at for Feature 8.1's average_days_to_payment metric."""
    statement = select(Invoice).where(
        Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id, Invoice.flow_direction == "OUTBOUND",
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

    if invoice.status not in ("VERIFIED", "NEEDS_REVIEW"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm-send an invoice with status '{invoice.status}'. Must be VERIFIED or NEEDS_REVIEW.",
        )

    invoice.status = "SENT"
    invoice.sent_at = datetime.utcnow()
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    return {"success": True, "status": invoice.status, "sent_at": invoice.sent_at.isoformat()}
