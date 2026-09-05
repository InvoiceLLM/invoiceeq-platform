import json
import re
import logging
from uuid import UUID, uuid4
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from pydantic import BaseModel, EmailStr, field_validator
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
# `fastapi.UploadFile` is a *subclass* of Starlette's, and `request.form()`
# yields the Starlette one — so the isinstance check in _collect_attachments
# must be against the base class or it matches nothing.
from starlette.datastructures import UploadFile as StarletteUploadFile

from config import get_settings
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import Tenant, TenantEmailSender, Invoice
from routers.invoices import _ingest_single_file
from services.storage import upload_pdf_to_blob_storage
from services.ingestion_batches import record_ingestion_batch
from services.file_intake import (
    ImageTooLargeError,
    UnsupportedUploadError,
    normalize_upload,
    sniff_format,
)
from services.inbound_mail_security import (
    REASON_INGEST_FAILED,
    REASON_INGEST_REJECTED,
    REASON_MALFORMED,
    REASON_MISSING_TENANT,
    REASON_NO_PDF_ATTACHMENT,
    REASON_OVERSIZED,
    REASON_QUOTA_EXHAUSTED,
    REASON_SECRET_UNCONFIGURED,
    REASON_UNKNOWN_SENDER,
    describe_client,
    declared_content_length,
    max_inbound_bytes,
    oversize_from_content_length,
    record_dropped_email,
    verify_inbound_secret,
)
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


def _collect_attachments(form) -> list[StarletteUploadFile]:
    """Every file part of the multipart body, whatever its field name.

    Gap 124: the handler used to declare `files: list[UploadFile]`, which only
    ever matched parts literally named `files`. Real SendGrid Inbound Parse
    names them `attachment1`, `attachment2`, … — so the one field name the old
    signature accepted was the one name SendGrid never sends. Collecting by
    type instead of by name accepts both, which is why this webhook could not
    have worked against live Parse traffic as written.
    """
    return [
        value for _key, value in form.multi_items()
        if isinstance(value, StarletteUploadFile)
    ]


def _attachment_size(file: StarletteUploadFile) -> int | None:
    """Byte size of an uploaded part without reading it, when Starlette knows it."""
    size = getattr(file, "size", None)
    return int(size) if isinstance(size, int) else None


@router.post("/mailintegration")
async def email_mailintegration_webhook(
    request: Request,
    db_session: Session = Depends(get_db_session),
):
    """
    Shared SendGrid mail webhook (inbound + outbound).

    Path: POST /api/v1/email/mailintegration
    One URL for both directions — email_set on From picks the pipeline.

    Gap 124 items 5–7 — this endpoint has no authenticated caller (SendGrid
    holds no Clerk session), so three guards stand in for one:

      * **Shared secret** (`services/inbound_mail_security.verify_inbound_secret`).
        Rejected requests get 401 and never reach the body. Fail-closed when
        `INBOUND_PARSE_SHARED_SECRET` is unset — see that setting's comment.
      * **25 MiB cap**, checked against the declared Content-Length *before*
        the multipart is parsed (so an oversized body is refused without being
        spooled to disk), then re-checked against the bytes actually read for
        clients that send no Content-Length.
      * **Every rejection is recorded** in `dropped_inbound_emails` and shown
        by `GET /api/v1/admin/dropped-emails`. Previously each of these paths
        was a `logger.warning` and a 200, i.e. the mail was gone with no trace
        an Admin could ever see.

    The body is parsed by hand (`await request.form()`) rather than declared as
    `Form(...)`/`File(...)` parameters on purpose: FastAPI reads and parses the
    body *before* it solves dependencies, so a declared-parameter signature
    gives no point at which the size cap or the secret can be enforced ahead of
    the parse. Parsing here is the only way those two guards run first.
    """
    client = describe_client(request)

    # --- Guard 1: size, from the declared Content-Length (body untouched) ---
    oversized = oversize_from_content_length(request)
    if oversized is not None:
        record_dropped_email(
            db_session,
            reason=REASON_OVERSIZED,
            detail=(
                f"Declared Content-Length {oversized} bytes exceeds the "
                f"{max_inbound_bytes()} byte limit. Sender: {client}."
            ),
            content_length=oversized,
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Inbound email exceeds the {max_inbound_bytes()} byte limit.",
        )

    # --- Guard 2: shared secret ---------------------------------------------
    verified, failure_reason = verify_inbound_secret(request)
    if not verified:
        if failure_reason == REASON_SECRET_UNCONFIGURED:
            detail = (
                "INBOUND_PARSE_SHARED_SECRET is not configured on this deployment, "
                "so no inbound mail can be authenticated. Seed the Key Vault secret "
                f"SENDGRID-INBOUND-SECRET. Sender: {client}."
            )
            message = "Inbound mail authentication is not configured on this deployment."
        else:
            detail = f"Missing or incorrect inbound shared secret. Sender: {client}."
            message = "Inbound mail could not be authenticated."
        record_dropped_email(
            db_session,
            reason=failure_reason,
            detail=detail,
            content_length=declared_content_length(request),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)

    # --- Body ---------------------------------------------------------------
    try:
        form = await request.form()
    except Exception as exc:
        record_dropped_email(
            db_session,
            reason=REASON_MALFORMED,
            detail=f"Could not parse the request body: {exc}. Sender: {client}.",
            content_length=declared_content_length(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inbound email body could not be parsed.",
        )

    to = str(form.get("to") or "").strip()
    from_header = str(form.get("from") or "").strip()
    files = _collect_attachments(form)

    if not to or not from_header:
        record_dropped_email(
            db_session,
            reason=REASON_MALFORMED,
            detail=(
                "Inbound mail POST is missing the 'to' and/or 'from' field. "
                f"Sender: {client}."
            ),
            from_email=from_header or None,
            to_email=to or None,
            content_length=declared_content_length(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inbound email is missing the 'to' or 'from' field.",
        )

    logger.info(
        "Received mailintegration webhook. To: %s, From: %s, Attachments: %d",
        to, from_header, len(files),
    )

    # --- Guard 3: size again, measured ---------------------------------------
    # Covers a caller that sent no Content-Length at all (guard 1 saw nothing to
    # check). Uses Starlette's recorded part sizes so nothing is re-read.
    known_sizes = [s for s in (_attachment_size(f) for f in files) if s is not None]
    measured_total = sum(known_sizes)
    if measured_total > max_inbound_bytes():
        record_dropped_email(
            db_session,
            reason=REASON_OVERSIZED,
            detail=(
                f"Attachments total {measured_total} bytes, over the "
                f"{max_inbound_bytes()} byte limit. Sender: {client}."
            ),
            from_email=_normalize_email_header(from_header),
            to_email=to,
            content_length=measured_total,
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Inbound email exceeds the {max_inbound_bytes()} byte limit.",
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
        # Still a 200: SendGrid retries non-2xx responses, and an unregistered
        # sender is a settled business outcome, not a transient failure. The
        # record below is what makes the drop visible instead of silent.
        record_dropped_email(
            db_session,
            reason=REASON_UNKNOWN_SENDER,
            detail=(
                "Sender is not in any workspace's authorized email set. Add it under "
                "Settings → Email Setup to accept mail from this address."
            ),
            from_email=sender_email,
            to_email=to,
            content_length=measured_total or declared_content_length(request),
        )
        return {
            "success": True,
            "status": "dropped",
            "message": "Sender is not registered to any workspace.",
        }

    tenant_id = allowed_sender.tenant_id
    tenant = db_session.get(Tenant, tenant_id)
    if not tenant:
        record_dropped_email(
            db_session,
            reason=REASON_MISSING_TENANT,
            detail=f"Registered sender points at workspace {tenant_id}, which no longer exists.",
            tenant_id=tenant_id,
            from_email=sender_email,
            to_email=to,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    email_set = (allowed_sender.email_set or "inbound").lower()
    batch_id = uuid4()
    job_ids = []

    # Feature 28: an attachment is ingestable if its *bytes* sniff to an
    # accepted format -- a phone photo named IMG_0421.JPG is in, a GIF named
    # invoice.pdf is out. The bytes have to be read here for the sniff to be
    # possible at all; the per-attachment loop below reuses them instead of
    # re-reading a consumed stream. REASON_NO_PDF_ATTACHMENT keeps its constant
    # name (it is persisted and reported on); only the detail text moves.
    attachments: list[tuple[str, bytes]] = []
    for f in files:
        try:
            raw_bytes = await f.read()
        except Exception as read_exc:
            logger.error("Failed to read email attachment %s: %s", f.filename, read_exc)
            record_dropped_email(
                db_session,
                reason=REASON_INGEST_FAILED,
                detail=f"Attachment could not be read: {read_exc}",
                tenant_id=tenant_id,
                from_email=sender_email,
                to_email=to,
                filename=f.filename,
            )
            continue
        if sniff_format(raw_bytes) is not None:
            attachments.append((f.filename or "invoice.pdf", raw_bytes))

    if not attachments:
        record_dropped_email(
            db_session,
            reason=REASON_NO_PDF_ATTACHMENT,
            detail=(
                f"Mail carried {len(files)} attachment(s), none of them a PDF or "
                "supported image. Only PDF, PNG, JPG, TIFF, WEBP or BMP "
                "attachments are ingested."
            ),
            tenant_id=tenant_id,
            from_email=sender_email,
            to_email=to,
        )
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
        # Gap 133: TenantContext.tenant_name exists for the FE's identity
        # display; this machine-to-machine context never reaches a browser, but
        # populate it anyway so the model has one meaning everywhere.
        tenant_name=tenant.name,
    )

    # Gap 464: an inbound mail had no tenant-facing home at all before this --
    # its only trace was a `logger.warning` plus, on a rejection, a
    # `dropped_inbound_emails` row visible ONLY in the Admin console, which is
    # the wrong audience for "where did the invoice I emailed in go?". The run
    # is recorded here, once the attachment set is known, so `file_count` is the
    # number of files this mail actually offered the pipeline.
    record_ingestion_batch(
        db_session,
        tenant_id=tenant_id,
        batch_id=batch_id,
        trigger="email",
        file_count=len(attachments),
        flow_direction="OUTBOUND" if email_set == "outbound" else "INBOUND",
    )

    for source_filename, raw_bytes in attachments:
        try:
            # Feature 28: convert here, once, so both the outbound and inbound
            # branches below hand a PDF to storage/hashing exactly as before.
            try:
                normalized = normalize_upload(source_filename, raw_bytes)
            except (UnsupportedUploadError, ImageTooLargeError) as norm_exc:
                record_dropped_email(
                    db_session,
                    reason=REASON_INGEST_REJECTED,
                    detail=f"Attachment refused: {norm_exc.detail}",
                    tenant_id=tenant_id,
                    from_email=sender_email,
                    to_email=to,
                    filename=source_filename,
                )
                continue
            file_bytes = normalized.pdf_bytes
            filename = normalized.pdf_filename
            if email_set == "outbound":
                job_id = await _ingest_outbound_email_pdf(
                    file_bytes=file_bytes,
                    filename=filename,
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
                        record_dropped_email(
                            db_session,
                            reason=REASON_QUOTA_EXHAUSTED,
                            detail=(
                                "Workspace has no free invoices left this cycle, so this "
                                "attachment was not ingested. Upgrade the plan or wait for "
                                "the quota to refill."
                            ),
                            tenant_id=tenant_id,
                            from_email=sender_email,
                            to_email=to,
                            filename=source_filename,
                        )
                        continue
                    tenant.free_invoices_remaining -= 1
                    db_session.add(tenant)
                    db_session.commit()

                job_id = await _ingest_single_file(
                    file_bytes=file_bytes,
                    filename=filename,
                    tags=["email"],
                    batch_id=batch_id,
                    tenant=tenant,
                    context=context,
                    db_session=db_session,
                    submitted_by_email=sender_email,
                )
                job_ids.append(job_id)
        except HTTPException as http_exc:
            # e.g. _ingest_outbound_email_pdf's 403 when Send Invoices is off
            # for the tenant. Recorded before re-raising so the Admin sees why
            # the mail was refused, not just a 403 in the SendGrid logs.
            record_dropped_email(
                db_session,
                reason=REASON_INGEST_REJECTED,
                detail=f"Attachment refused ({http_exc.status_code}): {http_exc.detail}",
                tenant_id=tenant_id,
                from_email=sender_email,
                to_email=to,
                filename=source_filename,
            )
            raise
        except Exception as e:
            logger.error("Failed to ingest email attachment %s: %s", source_filename, e)
            record_dropped_email(
                db_session,
                reason=REASON_INGEST_FAILED,
                detail=f"Attachment failed to ingest: {e}",
                tenant_id=tenant_id,
                from_email=sender_email,
                to_email=to,
                filename=source_filename,
            )

    return {
        "success": True,
        "status": "processed",
        "email_set": email_set,
        "flow_direction": "OUTBOUND" if email_set == "outbound" else "INBOUND",
        "tenant_id": str(tenant_id),
        "batch_id": str(batch_id),
        "job_ids": job_ids,
    }
