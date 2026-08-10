import json
import re
import logging
from uuid import UUID, uuid4
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from pydantic import BaseModel, EmailStr, field_validator
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from config import get_settings
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import Tenant, TenantEmailSender, Invoice
from routers.invoices import _ingest_single_file
from services.storage import upload_pdf_to_blob_storage
from azure.storage.queue import QueueClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email Ingestion"])

EmailSet = Literal["inbound", "outbound"]

EMAIL_CLEAN_PATTERN = re.compile(r"<([^>]+)>")


class EmailSenderCreate(BaseModel):
    email: EmailStr
    email_set: EmailSet = "inbound"

    @field_validator("email_set")
    @classmethod
    def _normalize_set(cls, v: str) -> str:
        return v.strip().lower()


def _mailbox_address() -> str:
    settings = get_settings()
    addr = (settings.EMAIL_APP_ADDRESS or "").strip().lower()
    if addr:
        return addr
    domain = (settings.EMAIL_APP_DOMAIN or "invoiceeq.app").strip().lower()
    return f"invoices@{domain}"


def _normalize_email_header(value: str) -> str:
    cleaned = value.strip().lower()
    match = EMAIL_CLEAN_PATTERN.search(cleaned)
    if match:
        return match.group(1).strip().lower()
    return cleaned


def _serialize_sender(s: TenantEmailSender) -> dict:
    return {
        "id": str(s.id),
        "email": s.email,
        "email_set": s.email_set,
        "created_at": s.created_at.isoformat(),
    }


@router.get("/settings/mailbox")
def get_mailbox(
    context: TenantContext = Depends(get_tenant_context),
):
    """Return the single platform-wide app mailbox (same for every tenant)."""
    return {
        "mailbox": _mailbox_address(),
        "domain": get_settings().EMAIL_APP_DOMAIN,
    }


@router.get("/settings/email-senders")
def list_email_senders(
    email_set: Optional[EmailSet] = Query(default=None),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """List authorized emails; optionally filter by inbound|outbound set."""
    stmt = select(TenantEmailSender).where(TenantEmailSender.tenant_id == context.tenant_id)
    if email_set:
        stmt = stmt.where(TenantEmailSender.email_set == email_set)
    senders = db_session.exec(stmt).all()
    return [_serialize_sender(s) for s in senders]


@router.post("/settings/email-senders", status_code=status.HTTP_201_CREATED)
def add_email_sender(
    payload: EmailSenderCreate,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Add an authorized email to the inbound or outbound set."""
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage authorized email sets.",
        )

    email_clean = str(payload.email).strip().lower()
    email_set = payload.email_set

    # Globally unique: one sender address → one tenant (shared mailbox model).
    stmt = select(TenantEmailSender).where(TenantEmailSender.email == email_clean)
    existing = db_session.exec(stmt).first()
    if existing:
        if existing.tenant_id == context.tenant_id:
            detail = f"Email address is already registered in the {existing.email_set} set."
        else:
            detail = "Email address is already registered to another workspace."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    sender = TenantEmailSender(
        id=uuid4(),
        tenant_id=context.tenant_id,
        email=email_clean,
        email_set=email_set,
    )
    db_session.add(sender)
    db_session.commit()
    db_session.refresh(sender)
    return _serialize_sender(sender)


@router.delete("/settings/email-senders/{sender_id}")
def delete_email_sender(
    sender_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Remove an email from an authorized set."""
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage authorized email sets.",
        )

    sender = db_session.get(TenantEmailSender, sender_id)
    if not sender or sender.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sender email record not found or access denied.",
        )
    db_session.delete(sender)
    db_session.commit()
    return {"status": "success", "message": "Email address removed from allowlist."}


async def _ingest_outbound_email_pdf(
    *,
    file_bytes: bytes,
    filename: str,
    tenant: Tenant,
    context: TenantContext,
    db_session: Session,
    batch_id: UUID,
    submitted_by_email: str | None = None,
) -> str:
    """Mirror outbound upload path for email-submitted AR PDFs."""
    if not tenant.send_invoices_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Send Invoices is not enabled for this tenant. Enable it in Settings first.",
        )

    invoice_id = uuid4()
    file_path = await run_in_threadpool(
        upload_pdf_to_blob_storage, file_bytes, str(context.tenant_id), str(invoice_id)
    )

    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        file_path=file_path,
        flow_direction="OUTBOUND",
        status="UPLOADED",
        tags=["email"],
        submitted_by_email=(submitted_by_email or "").strip().lower() or None,
    )
    db_session.add(db_invoice)
    await run_in_threadpool(db_session.commit)
    db_session.refresh(db_invoice)

    settings = get_settings()
    if settings.AZURE_STORAGE_CONNECTION_STRING:
        try:
            queue_client = QueueClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
            )
            queue_client.send_message(json.dumps({
                "task": "process_outbound_invoice",
                "kwargs": {
                    "batch_id": str(batch_id),
                    "file_path": file_path,
                    "tenant_id": str(context.tenant_id),
                },
            }))
            db_invoice.last_enqueued_at = datetime.utcnow()
            db_invoice.processing_attempts = 1
            db_session.add(db_invoice)
            await run_in_threadpool(db_session.commit)
        except Exception as e:
            logger.error(
                "Failed to queue outbound email invoice %s: %s", invoice_id, e
            )
    else:
        logger.error(
            "AZURE_STORAGE_CONNECTION_STRING missing — outbound email invoice %s stored but not queued.",
            invoice_id,
        )

    return str(invoice_id)


@router.post("/mailintegration")
async def email_mailintegration_webhook(
    to: str = Form(..., description="The To recipient header of the email"),
    from_header: str = Form(..., alias="from", description="The From sender header of the email"),
    files: list[UploadFile] = File(default=[]),
    db_session: Session = Depends(get_db_session),
):
    """
    Shared SendGrid mail webhook (inbound + outbound).

    Path: POST /api/v1/email/mailintegration
    One URL for both directions — email_set on From picks the pipeline.
    """
    logger.info(
        "Received mailintegration webhook. To: %s, From: %s, Attachments: %d",
        to, from_header, len(files),
    )

    mailbox = _mailbox_address()
    to_normalized = _normalize_email_header(to)
    # Soft check: prefer our global address, but still resolve by From if To is wrapped oddly.
    if mailbox not in to.lower() and to_normalized != mailbox:
        logger.warning(
            "Email To '%s' does not contain global mailbox '%s' — still resolving by sender.",
            to, mailbox,
        )

    sender_email = _normalize_email_header(from_header)

    allowed_sender = db_session.exec(
        select(TenantEmailSender).where(TenantEmailSender.email == sender_email)
    ).first()
    if not allowed_sender:
        logger.warning("Dropping email from unauthorized sender '%s'", sender_email)
        return {
            "success": True,
            "status": "dropped",
            "message": "Sender is not registered to any workspace.",
        }

    tenant_id = allowed_sender.tenant_id
    tenant = db_session.get(Tenant, tenant_id)
    if not tenant:
        logger.warning("Sender '%s' points at missing tenant '%s'", sender_email, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    email_set = (allowed_sender.email_set or "inbound").lower()
    batch_id = uuid4()
    job_ids = []

    pdf_files = [f for f in files if f.filename and f.filename.lower().endswith(".pdf")]
    if not pdf_files:
        return {
            "success": True,
            "status": "skipped",
            "message": "No PDF attachments found.",
            "email_set": email_set,
        }

    context = TenantContext(
        tenant_id=tenant_id,
        user_id="system_email_ingestion",
        db_user_id=None,
        role="System",
        billing_plan=tenant.billing_plan,
    )

    for file in pdf_files:
        try:
            file_bytes = await file.read()
            if email_set == "outbound":
                job_id = await _ingest_outbound_email_pdf(
                    file_bytes=file_bytes,
                    filename=file.filename or "invoice.pdf",
                    tenant=tenant,
                    context=context,
                    db_session=db_session,
                    batch_id=batch_id,
                    submitted_by_email=sender_email,
                )
                job_ids.append(job_id)
            else:
                if tenant.billing_plan == "free":
                    if tenant.free_invoices_remaining <= 0:
                        logger.warning(
                            "Tenant %s free quota exhausted. Dropping email attachment %s.",
                            tenant_id, file.filename,
                        )
                        continue
                    tenant.free_invoices_remaining -= 1
                    db_session.add(tenant)
                    db_session.commit()

                job_id = await _ingest_single_file(
                    file_bytes=file_bytes,
                    filename=file.filename,
                    tags=["email"],
                    batch_id=batch_id,
                    tenant=tenant,
                    context=context,
                    db_session=db_session,
                    submitted_by_email=sender_email,
                )
                job_ids.append(job_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Failed to ingest email attachment %s: %s", file.filename, e)

    return {
        "success": True,
        "status": "processed",
        "email_set": email_set,
        "flow_direction": "OUTBOUND" if email_set == "outbound" else "INBOUND",
        "tenant_id": str(tenant_id),
        "batch_id": str(batch_id),
        "job_ids": job_ids,
    }
