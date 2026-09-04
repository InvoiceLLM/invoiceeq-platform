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
from services.attachment_extraction import extract_attachment

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

#: Gap 446 (Phase 4.4). A photo of a delivery note is the most common way a
#: warehouse actually sends one, and Azure Document Intelligence reads images as
#: readily as PDFs. Accepted ONLY on the Azure path: local dev extracts text with
#: pypdf, which cannot open a PNG at all, so accepting one there would store a
#: file that can never be read and report EXTRACT_FAILED every time.
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}
ALLOWED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def _accepted_content_types() -> set:
    """Which types this deployment can actually read, not which it would like to."""
    from config import get_settings

    if get_settings().LLM_PROVIDER == "ollama":
        return set(ALLOWED_CONTENT_TYPES)
    return set(ALLOWED_CONTENT_TYPES) | ALLOWED_IMAGE_CONTENT_TYPES


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
    # Feature 26 Phase 4 (Gap 444). Everything below is what the chip has to show
    # WITHOUT a turn having happened yet: how many lines were read, which tier
    # matched and against what, and how much of the per-session cap is used.
    # Before this the FE could only render a filename and a spinner, and
    # `candidate_invoice_ids` was empty until the user's first question -- so
    # "found 1 matching invoice" was unsayable at the only moment it is useful.
    line_count: int = 0
    match_tier: Optional[int] = None
    match_summary: Optional[str] = None
    attachment_count: int = 0
    attachment_limit: int = MAX_ATTACHMENTS_PER_SESSION
    # Gap 445: the extracted document itself, so the user can check what was read
    # BEFORE a comparison is computed from it. Bounded to the fields the chip and
    # the "here is what I read" panel render.
    extraction_preview: Optional[dict] = None
    low_confidence_fields: List[str] = []
    # Feature 26 Phase 3.3 (Gap 452). Present when extraction was queued: the
    # browser opens `GET /chat/jobs/{extraction_job_id}/stream` and watches the
    # document being read instead of holding one request open for 25-50 seconds.
    # Absent when extraction already ran inline, which is the Redis-down case --
    # its absence is the signal that there is nothing to wait for.
    extraction_job_id: Optional[str] = None


class ConfirmMatchesIn(BaseModel):
    invoice_ids: List[UUID]


#: Gap 445. Below this, a field the extractor was unsure of is worth confirming
#: with the user before a Tier 1 match is attempted on it -- a misread document
#: number is the difference between "no invoice matches" and the right invoice.
LOW_CONFIDENCE_THRESHOLD = 0.6

#: Gap 445. Which fields are worth querying. A misread `notes` costs nothing; a
#: misread `doc_number` or `grand_total` costs the whole answer.
CONFIDENCE_GATED_FIELDS = ("doc_number", "grand_total", "party_name", "doc_date")


def _extraction_preview(row: ChatAttachment) -> dict:
    """Gap 445: what we read, in the shape the panel renders.

    Straight out of the persisted extraction -- no re-reading, no model, and
    truncated to the first 20 lines so a 300-line statement cannot make an
    upload response enormous.
    """
    data = row.extracted_json or {}
    items = (data.get("items") or [])[:20]
    return {
        "doc_type": row.doc_type,
        "doc_number": row.doc_number,
        "party_name": row.party_name,
        "doc_date": row.doc_date.isoformat() if row.doc_date else None,
        "currency": row.currency,
        "subtotal": data.get("subtotal"),
        "tax_amount": data.get("tax_amount"),
        "grand_total": row.grand_total,
        "payment_terms": data.get("payment_terms"),
        "delivery_terms": data.get("delivery_terms"),
        "line_count": len(data.get("items") or []),
        "lines": [
            {
                "description": i.get("description"),
                "quantity": i.get("quantity"),
                "unit_price": i.get("unit_price"),
                "amount": i.get("amount"),
            }
            for i in items
        ],
        "referenced_document_count": len(data.get("referenced_documents") or []),
    }


def _low_confidence_fields(row: ChatAttachment) -> List[str]:
    """Gap 445: which of the fields that matter the extractor was unsure of."""
    confidences = (row.extracted_json or {}).get("field_confidence") or {}
    out = []
    for field in CONFIDENCE_GATED_FIELDS:
        score = confidences.get(field)
        if isinstance(score, (int, float)) and score < LOW_CONFIDENCE_THRESHOLD:
            out.append(field)
    return out


def _session_attachment_count(session_id, db_session: Session) -> int:
    """Gap 444: how many documents this conversation already holds.

    On every response, not only the upload: the composer shows "3 of 5" and has
    to be right after a reload too, which is the same reason the row is
    persisted rather than remembered in the browser (D2).
    """
    try:
        return len(
            db_session.exec(
                select(ChatAttachment).where(ChatAttachment.session_id == session_id)
            ).all()
        )
    except Exception:
        return 0


def _to_out(
    row: ChatAttachment, *, attachment_count: int = 0, extraction_job_id: Optional[str] = None
) -> AttachmentOut:
    data = row.extracted_json or {}
    candidates = [str(i) for i in (row.candidate_invoice_ids or [])]
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
        candidate_invoice_ids=candidates,
        confirmed_invoice_ids=[str(i) for i in (row.confirmed_invoice_ids or [])],
        line_count=len(data.get("items") or []),
        match_tier=row.match_tier,
        match_summary=row.match_summary,
        attachment_count=attachment_count,
        extraction_preview=_extraction_preview(row) if row.extraction_status == "EXTRACTED" else None,
        low_confidence_fields=_low_confidence_fields(row),
        extraction_job_id=extraction_job_id,
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
    accepted = _accepted_content_types()
    lowered = filename.lower()
    suffix_ok = lowered.endswith(".pdf") or (
        ALLOWED_IMAGE_CONTENT_TYPES & accepted and lowered.endswith(ALLOWED_IMAGE_SUFFIXES)
    )
    if (file.content_type or "").lower() not in accepted or not suffix_ok:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Only PDF files can be attached to a conversation."
                if len(accepted) == 1
                else "Only PDF, PNG or JPEG files can be attached to a conversation."
            ),
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

    # Feature 26 Phase 3.3 (Gap 452). The upload's job ends once the file is
    # stored and the row exists; reading the document is the worker's job, and
    # doing it here is what made an upload take 25-50 seconds with nothing to
    # show for the wait.
    #
    # The fallback is not a nicety. `enqueue_attachment_extraction()` returns
    # None when Redis is unreachable, and in that case the document is extracted
    # inline exactly as it was before -- slower, but a working upload. An upload
    # that 500s because a queue is down would be a worse product than a slow one.
    from services.chat_queue import ChatQueueService

    queued = ChatQueueService.enqueue_attachment_extraction(
        attachment_id=str(row.id), tenant_id=str(row.tenant_id)
    )
    if queued is None:
        logger.warning(
            "Attachment %s: extraction queue unavailable, extracting inline", row.id
        )
        extract_attachment(row, db_session)
        return _to_out(row, attachment_count=len(existing) + 1)

    return _to_out(
        row,
        attachment_count=len(existing) + 1,
        extraction_job_id=queued["job_id"],
    )


# Feature 26 Phase 3.3 (Gap 452): `_match_at_upload()`, `_extract_attachment()` and
# `_index_attachment()` used to live here -- around 200 lines of extraction pipeline
# inside an HTTP router. They now live in `services/attachment_extraction.py`,
# because the QUEUE WORKER runs the same pipeline and two copies of it would drift
# silently: a document extracted one way when the queue is up and another way when
# it is down. That module keeps every failure rule these had, and its docstring
# records which rules and why.


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
    return _to_out(row, attachment_count=_session_attachment_count(row.session_id, db_session))


@router.get("/attachments/{attachment_id}", response_model=AttachmentOut)
def get_chat_attachment(
    attachment_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Read one attachment back. Supports the FE reload/reattach path — the
    reason this is a persisted row rather than session scratch (D2)."""
    row = _require_owned_attachment(attachment_id, db_session, tenant_context)
    return _to_out(row, attachment_count=_session_attachment_count(row.session_id, db_session))
