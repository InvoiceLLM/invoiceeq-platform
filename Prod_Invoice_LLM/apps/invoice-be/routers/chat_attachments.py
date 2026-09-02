"""Feature 26 (Gap 366) — chat reference-document attachments.

A deliberately SEPARATE module from `routers/chat.py`. Two reasons, both
concrete: that file is already ~3k lines carrying the Feature 18 triage
machinery and the queue endpoints, and this feature landed alongside two other
tracks that were editing it — keeping the new surface out of it is what made the
three changes conflict-free.

Three endpoints:
  POST /chat/sessions/{session_id}/attachments   — upload + synchronous extract
  POST /chat/attachments/{attachment_id}/confirm-matches
  GET  /chat/attachments/{attachment_id}

Ownership is checked on every one of them the way `_require_owned_chat_job()`
does it (routers/chat.py, Gap 341's pattern): resolve through the database, not
through anything the caller supplied. Gap 341 was exactly the defect of taking a
`tenant_context` dependency and then never using it, and an attached purchase
order contains another company's negotiated pricing — a worse leak than an
invoice total.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlmodel import Session, select

from dependencies import get_db_session, get_tenant_context, TenantContext
from models import ChatAttachment, ChatSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat-attachments"])

# --- Decision D3's caps ------------------------------------------------------
# Enforced here, in the request path, rather than as DB constraints. Two of the
# three are inherently request-shaped (a content type and a byte count), and a
# CHECK constraint covering only the third would read as though all three were
# enforced at the database. `file_size_bytes` is persisted so the size cap is
# auditable after the fact rather than being a check that leaves no trace.
#
# These caps ARE the abuse control for this feature. A reference document does
# NOT consume ingestion quota (D3): `billing_quota` meters invoice ingestion,
# and a PO never becomes a payable, so charging it against that meter would
# misprice the plan. The chat turn itself is already metered where chat is
# metered — that is untouched here.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_SESSION = 5
# PDF only. Image/scan upload is `docs/phase_2_enhancements.md` section 2 — a
# separate item, deliberately not folded in here.
ALLOWED_CONTENT_TYPES = {"application/pdf"}


class AttachmentOut(BaseModel):
    id: str
    session_id: str
    filename: str
    doc_type: str
    extraction_status: str
    doc_number: Optional[str] = None
    party_name: Optional[str] = None
    doc_date: Optional[str] = None
    currency: Optional[str] = None
    grand_total: Optional[float] = None
    file_size_bytes: int = 0
    candidate_invoice_ids: List[str] = []
    confirmed_invoice_ids: List[str] = []


class ConfirmMatchesIn(BaseModel):
    invoice_ids: List[UUID]


def _to_out(row: ChatAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=str(row.id),
        session_id=str(row.session_id),
        filename=row.filename,
        doc_type=row.doc_type,
        extraction_status=row.extraction_status,
        doc_number=row.doc_number,
        party_name=row.party_name,
        doc_date=row.doc_date.isoformat() if row.doc_date else None,
        currency=row.currency,
        grand_total=row.grand_total,
        file_size_bytes=row.file_size_bytes,
        candidate_invoice_ids=[str(i) for i in (row.candidate_invoice_ids or [])],
        confirmed_invoice_ids=[str(i) for i in (row.confirmed_invoice_ids or [])],
    )


def _require_owned_session(
    session_id: UUID, db_session: Session, tenant_context: TenantContext
) -> ChatSession:
    chat_session = db_session.exec(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if chat_session is None:
        # 404 rather than 403 on a cross-tenant id: confirming that someone
        # else's session exists is itself a disclosure.
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return chat_session


def _require_owned_attachment(
    attachment_id: UUID, db_session: Session, tenant_context: TenantContext
) -> ChatAttachment:
    row = db_session.exec(
        select(ChatAttachment).where(
            ChatAttachment.id == attachment_id,
            ChatAttachment.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return row


@router.post("/sessions/{session_id}/attachments", response_model=AttachmentOut)
async def upload_chat_attachment(
    session_id: UUID,
    file: UploadFile = File(...),
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Attach a PO/quotation PDF to a chat session and extract it synchronously.

    Synchronous on purpose: the user is sitting in the composer waiting to ask a
    question about the document they just picked, and a queued extraction would
    mean the very next turn finds `extraction_status == "PENDING"` and can do
    nothing useful with it. One PDF's extraction is a single graph run, not a
    batch.

    **No `Invoice` row is written and no billing counter moves** (D2/D3). If that
    ever changes, spend aggregates, /dashboard/insights, the AUDIT_REQUIRED
    count, billing quota and the RAG index all silently change with it.
    """
    _require_owned_session(session_id, db_session, tenant_context)

    # --- Cap: 5 per session -------------------------------------------------
    existing = db_session.exec(
        select(ChatAttachment).where(ChatAttachment.session_id == session_id)
    ).all()
    if len(existing) >= MAX_ATTACHMENTS_PER_SESSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This conversation already has {MAX_ATTACHMENTS_PER_SESSION} attachments, "
                "which is the limit. Start a new conversation to attach more."
            ),
        )

    # --- Cap: PDF only ------------------------------------------------------
    filename = file.filename or "attachment.pdf"
    if (file.content_type or "").lower() not in ALLOWED_CONTENT_TYPES or not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files can be attached to a conversation.",
        )

    # --- Cap: 10 MB ---------------------------------------------------------
    # Measured on the bytes actually read, NOT on the Content-Length header,
    # which the client controls and can understate.
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Attachments are limited to {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.",
        )
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    attachment_id = uuid4()
    from services.storage import upload_pdf_to_blob_storage

    # Same helper the invoice path uses; the path segment differs so a reference
    # document is never mistaken for an invoice blob by anything walking storage.
    blob_path = upload_pdf_to_blob_storage(
        data, str(tenant_context.tenant_id), f"chat-attachments/{attachment_id}"
    )

    # E-7's TTL is stamped onto the row at creation, not computed at read time
    # from `created_at`. Two reasons: the sweeper (H8) can then find expired rows
    # with a plain indexed predicate instead of arithmetic over every row, and a
    # later change to CHAT_ATTACHMENT_TTL_DAYS cannot retroactively expire a
    # document a user attached under the old policy. `created_at` is passed
    # explicitly rather than left to its default_factory so the two values are
    # computed from the same instant and cannot disagree by a few microseconds.
    from config import get_settings as _get_settings

    created_at = datetime.utcnow()
    row = ChatAttachment(
        id=attachment_id,
        tenant_id=tenant_context.tenant_id,
        session_id=session_id,
        filename=filename[:512],
        blob_path=blob_path,
        file_size_bytes=len(data),
        extraction_status="PENDING",
        created_at=created_at,
        expires_at=created_at
        + timedelta(days=_get_settings().CHAT_ATTACHMENT_TTL_DAYS),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    _extract_attachment(row, db_session)
    return _to_out(row)


def _extract_attachment(row: ChatAttachment, db_session: Session) -> None:
    """Run the REFERENCE direction profile over the stored PDF and denormalise,
    then (Feature 26 Part 2, task H4) embed the document's own text.

    Failure is recorded, not raised: the row exists and the user should be told
    "I couldn't read that document" on their next turn rather than getting a 500
    on an upload that did in fact store the file.
    """
    try:
        from queue_worker.handlers import _run_ocr
        from agents.extraction_agent import run_extraction_agent
        from config import get_settings

        ocr_result = _run_ocr(row.blob_path, get_settings())
        ocr_text = ocr_result["content"] if isinstance(ocr_result, dict) else ocr_result

        result = run_extraction_agent(
            row.blob_path,
            ocr_text,
            str(row.tenant_id),
            ocr_result=ocr_result,
            flow_direction="REFERENCE",
        )
        data = result.get("extracted_data") or {}
        row.extracted_json = data
        row.doc_type = (data.get("doc_type") or "OTHER").upper()
        row.doc_number = (data.get("doc_number") or None)
        row.party_name = (data.get("party_name") or None)
        row.currency = (data.get("currency") or None)
        row.grand_total = data.get("grand_total")
        raw_date = data.get("doc_date")
        if raw_date:
            from datetime import date as _date

            try:
                row.doc_date = _date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                row.doc_date = None
        # "EXTRACTED"/"EXTRACT_FAILED" come from the REFERENCE direction
        # profile's own status vocabulary — a reference document has no audit
        # lifecycle, so it never carries an invoice status string.
        row.extraction_status = "EXTRACTED" if data else "EXTRACT_FAILED"
    except Exception as e:
        logger.error("Chat attachment extraction failed for %s: %s", row.id, e)
        row.extraction_status = "EXTRACT_FAILED"

    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    # The extraction result is committed above BEFORE indexing is attempted, so a
    # crash inside the embed step cannot cost the extraction that already
    # succeeded. The two are independent facts about the row and are persisted
    # independently.
    if row.extraction_status == "EXTRACTED":
        _index_attachment(row, db_session)


def _index_attachment(row: ChatAttachment, db_session: Session) -> None:
    """Embed the attached document's text into `chat_docs_{tenant_id}` (E-2/E-6).

    Only ever called for an EXTRACTED row. An EXTRACT_FAILED document is one we
    could not read at all, so there is nothing to chunk and calling the indexer
    would spend an embedding round trip to write zero chunks.

    **Indexing failure does not fail the upload, and that is a deliberate
    asymmetry.** The chunks serve Part 2's content branch ("what are the payment
    terms?"); Part 1's whole comparison path -- the matcher, the confirmation
    gate, `compare_reference_to_invoices()` -- reads the denormalised columns and
    `extracted_json` and needs no chunks whatsoever. Failing an upload because a
    Chroma write failed would take away a feature that works to protect one that
    degrades.

    It is not silently swallowed either: the failure is logged at ERROR, and the
    row is left at `chunk_count=0` / `indexed_at=None`, which is the same state
    an un-indexed row has. That pair on an EXTRACTED row is the inspectable
    signal -- one SQL predicate finds every attachment whose embed step did not
    take, without reading logs.
    """
    try:
        from services.chat_document_search import index_attachment_chunks

        written = index_attachment_chunks(row, row.tenant_id)
    except Exception as e:
        logger.error(
            "Chat attachment indexing failed for %s (document remains usable for "
            "comparison; content search is unavailable for it): %s",
            row.id,
            e,
        )
        return

    if not written:
        # A real outcome, not an error: a scanned PDF with no extractable text
        # layer chunks to nothing. `index_attachment_chunks()` has already logged
        # which of the two it was, and the row's `indexed_at` stays null so this
        # is indistinguishable from "never attempted" only in the sense that both
        # mean "no chunks exist" -- which is the fact any caller actually needs.
        return

    row.chunk_count = written
    row.indexed_at = datetime.utcnow()
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)


@router.post("/attachments/{attachment_id}/confirm-matches", response_model=AttachmentOut)
def confirm_attachment_matches(
    attachment_id: UUID,
    payload: ConfirmMatchesIn,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """The user's explicit confirmation of which invoices to compare against (D4).

    This is the gate that stops the assistant producing a financial answer
    against a set it guessed at. It is a separate, explicit call rather than an
    inference from the next message precisely so that "the user agreed" is a
    recorded fact and not an interpretation of prose.

    Confirmation is restricted to the candidates the matcher actually proposed.
    Letting a caller confirm an arbitrary invoice id would turn this endpoint
    into an oracle for "does invoice X exist in my tenant" — and, worse, would
    let a client compare against a row the deterministic matcher had rejected.
    """
    row = _require_owned_attachment(attachment_id, db_session, tenant_context)

    proposed = {str(i) for i in (row.candidate_invoice_ids or [])}
    requested = [str(i) for i in payload.invoice_ids]
    if not requested:
        raise HTTPException(status_code=400, detail="Confirm at least one invoice.")
    unknown = [i for i in requested if i not in proposed]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Only invoices offered as candidates for this attachment can be confirmed.",
        )

    row.confirmed_invoice_ids = requested
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return _to_out(row)


@router.get("/attachments/{attachment_id}", response_model=AttachmentOut)
def get_chat_attachment(
    attachment_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Read one attachment back. Supports the FE reload/reattach path — the
    reason this is a persisted row rather than session scratch (D2)."""
    return _to_out(_require_owned_attachment(attachment_id, db_session, tenant_context))
