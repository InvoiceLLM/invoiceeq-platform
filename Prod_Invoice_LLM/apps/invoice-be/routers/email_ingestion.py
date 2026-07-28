import re
import json
import logging
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from dependencies import get_db_session, get_tenant_context, TenantContext
from models import Tenant, TenantEmailSender, Invoice
from routers.invoices import _ingest_single_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email Ingestion"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class EmailSenderCreate(BaseModel):
    email: EmailStr


# ─────────────────────────────────────────────────────────────────────────────
# Settings Allowed-Senders CRUD (Task 14.3)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/settings/email-senders")
def list_email_senders(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """Retrieve the allow-list of email addresses permitted to submit invoices."""
    stmt = select(TenantEmailSender).where(TenantEmailSender.tenant_id == context.tenant_id)
    senders = db_session.exec(stmt).all()
    return [{
        "id": str(s.id),
        "email": s.email,
        "created_at": s.created_at.isoformat()
    } for s in senders]


@router.post("/settings/email-senders", status_code=status.HTTP_201_CREATED)
def add_email_sender(
    payload: EmailSenderCreate,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """Add a sender email address to the allow-list."""
    email_clean = payload.email.strip().lower()
    
    # Check if duplicate
    stmt = select(TenantEmailSender).where(
        TenantEmailSender.tenant_id == context.tenant_id,
        TenantEmailSender.email == email_clean
    )
    existing = db_session.exec(stmt).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already in the allowlist."
        )
        
    sender = TenantEmailSender(
        id=uuid4(),
        tenant_id=context.tenant_id,
        email=email_clean
    )
    db_session.add(sender)
    db_session.commit()
    db_session.refresh(sender)
    
    return {
        "id": str(sender.id),
        "email": sender.email,
        "created_at": sender.created_at.isoformat()
    }


@router.delete("/settings/email-senders/{sender_id}")
def delete_email_sender(
    sender_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """Delete an email sender from the allow-list."""
    sender = db_session.get(TenantEmailSender, sender_id)
    if not sender or sender.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sender email record not found or access denied."
        )
    db_session.delete(sender)
    db_session.commit()
    return {"status": "success", "message": "Email address removed from allowlist."}


# ─────────────────────────────────────────────────────────────────────────────
# Inbound Webhook Parsing (Task 14.4)
# ─────────────────────────────────────────────────────────────────────────────

# UUID extraction pattern from To header alias (e.g. 1a2b3c4d-5e6f-...@invoices.domain.com)
UUID_EMAIL_PATTERN = re.compile(r"([a-f0-9-]{36})@invoices\.", re.IGNORECASE)

# Standard sender email parser from From header (e.g. "Vendor Name" <sender@domain.com> -> sender@domain.com)
EMAIL_CLEAN_PATTERN = re.compile(r"<([^>]+)>")

@router.post("/inbound")
async def inbound_email_webhook(
    to: str = Form(..., description="The To recipient header of the email"),
    from_header: str = Form(..., alias="from", description="The From sender header of the email"),
    files: list[UploadFile] = File(default=[]),
    db_session: Session = Depends(get_db_session)
):
    """
    SendGrid Inbound Parse Webhook endpoint.
    1. Resolves tenant_id from the recipient alias in the 'To' header.
    2. Verifies the sender email 'From' against the tenant's allow-list.
    3. Ingests all uploaded PDF attachments under a system-scopable context.
    """
    logger.info("Received inbound email webhook. To: %s, From: %s, Attachments: %d", to, from_header, len(files))

    # 1. Resolve tenant_id from recipient alias
    to_match = UUID_EMAIL_PATTERN.search(to)
    if not to_match:
        logger.warning("Inbound email recipient '%s' does not match tenant alias format.", to)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant alias not recognized."
        )
    
    try:
        tenant_id = UUID(to_match.group(1))
    except ValueError:
        logger.warning("Recipient alias contains invalid UUID string: %s", to_match.group(1))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid tenant alias ID."
        )

    # Verify tenant exists
    tenant = db_session.get(Tenant, tenant_id)
    if not tenant:
        logger.warning("Inbound email target tenant '%s' not found.", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found."
        )

    # 2. Extract and verify sender email from From header
    sender_email = from_header.strip().lower()
    from_match = EMAIL_CLEAN_PATTERN.search(sender_email)
    if from_match:
        sender_email = from_match.group(1).strip().lower()

    # Check if sender is allowed
    stmt = select(TenantEmailSender).where(
        TenantEmailSender.tenant_id == tenant_id,
        TenantEmailSender.email == sender_email
    )
    allowed_sender = db_session.exec(stmt).first()
    if not allowed_sender:
        logger.warning("Silently dropping email from unauthorized sender '%s' to tenant '%s'", sender_email, tenant_id)
        # Return 200 OK so SendGrid doesn't retry / bounce, but perform no processing
        return {
            "success": True,
            "status": "dropped",
            "message": "Sender is not allowed to submit invoices to this tenant."
        }

    # 3. Process PDF attachments
    batch_id = uuid4()
    job_ids = []
    
    pdf_files = [f for f in files if f.filename and f.filename.lower().endswith(".pdf")]
    
    if not pdf_files:
        logger.info("No PDF attachments found in email from %s.", sender_email)
        return {
            "success": True,
            "status": "skipped",
            "message": "No PDF attachments found."
        }

    # Create dummy TenantContext for shared _ingest_single_file logic
    context = TenantContext(
        tenant_id=tenant_id,
        user_id="system_email_ingestion",
        db_user_id=None,
        role="System",
        billing_plan=tenant.billing_plan
    )

    for file in pdf_files:
        try:
            file_bytes = await file.read()
            # Enforce limits if on free plan
            if tenant.billing_plan == "free":
                if tenant.free_invoices_remaining <= 0:
                    logger.warning("Tenant %s free quota exhausted. Dropping email attachment %s.", tenant_id, file.filename)
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
                db_session=db_session
            )
            job_ids.append(job_id)
        except Exception as e:
            logger.error("Failed to ingest email attachment %s: %s", file.filename, e)

    return {
        "success": True,
        "status": "processed",
        "batch_id": str(batch_id),
        "job_ids": job_ids
    }
