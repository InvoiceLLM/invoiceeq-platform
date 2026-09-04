"""Feature 26 Phase 3.3 (Gap 452) — attachment extraction, in one place.

WHY THIS MODULE EXISTS
----------------------
Extraction used to live inside `routers/chat_attachments.py::upload_chat_attachment`,
which meant the HTTP request that uploaded a document also ran OCR, the extraction
graph, the chunk indexer and the invoice matcher before it could reply. The F26
benchmark measured that at 24-53 seconds per upload, held on one connection, with
nothing to report to the user but a spinner — there was no channel to report on.

Moving it onto the queue worker gives it a channel: the worker already publishes
progress to `chat_job_channel:{job_id}`, which the browser already subscribes to
through `GET /chat/jobs/{job_id}/stream`. So the stages the pipeline was already
going through — reading, extracting, indexing, matching — become visible instead
of being invisible work behind one spinner.

The functions live HERE rather than in the router or the worker because BOTH now
run them: the worker in the normal case, and the router inline when Redis is
unreachable. Two copies of an extraction pipeline is exactly how the two paths
drift, and the drift would be silent — a document extracted slightly differently
depending on whether a queue happened to be up.

WHAT IS DELIBERATELY UNCHANGED
------------------------------
The order of operations, and every failure rule, is carried over verbatim from the
router:

  * extraction is committed BEFORE indexing is attempted, so a crash in the embed
    step cannot cost an extraction that already succeeded;
  * indexing failure does not fail the upload — the comparison path reads the
    denormalised columns and needs no chunks at all, so failing the upload would
    take away a feature that works to protect one that degrades;
  * matching failure does not fail the upload either, and matching NEVER writes
    `confirmed_invoice_ids`. D4's confirmation gate is untouched: a proposal
    still cannot satisfy it, and no figure is computed until the user agrees.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sqlmodel import Session

from models import ChatAttachment

logger = logging.getLogger(__name__)

#: The stages an upload goes through, in order. Named here rather than as string
#: literals at each call site so the front end has one list to render against and
#: a renamed stage cannot silently stop matching.
STAGE_READING = "reading_document"
STAGE_EXTRACTING = "extracting_fields"
STAGE_INDEXING = "indexing_text"
STAGE_MATCHING = "matching_invoices"
STAGE_READY = "attachment_ready"
STAGE_FAILED = "attachment_failed"

ATTACHMENT_STAGES = (
    STAGE_READING,
    STAGE_EXTRACTING,
    STAGE_INDEXING,
    STAGE_MATCHING,
    STAGE_READY,
)

ProgressFn = Callable[[str], None]


def _noop(_stage: str) -> None:
    """The inline path reports to nobody, and that is correct rather than lazy:
    a synchronous HTTP request has no channel to publish on, so pretending to
    emit progress would write events no one can ever read."""


def extract_attachment(
    row: ChatAttachment,
    db_session: Session,
    progress: Optional[ProgressFn] = None,
) -> ChatAttachment:
    """Run the REFERENCE profile over the stored file and denormalise the result.

    Failure is recorded, not raised: the row exists and the file is stored, so
    the user should be told "I couldn't read that document" on their next turn
    rather than being handed a 500 for an upload that did in fact succeed.
    """
    progress = progress or _noop

    try:
        from agents.extraction_agent import run_extraction_agent
        from config import get_settings
        from queue_worker.handlers import _run_ocr

        progress(STAGE_READING)
        ocr_result = _run_ocr(row.blob_path, get_settings())
        ocr_text = ocr_result["content"] if isinstance(ocr_result, dict) else ocr_result

        progress(STAGE_EXTRACTING)
        result = run_extraction_agent(
            row.blob_path,
            ocr_text,
            str(row.tenant_id),
            ocr_result=ocr_result,
            flow_direction="REFERENCE",
        )
        data = result.get("extracted_data") or {}
        row.extracted_json = data
        # Gap 430: the Feature 27 classifier's verdict is at the TOP level of the
        # result; the REFERENCE schema's own field only knows PO / QUOTATION /
        # OTHER, so reading it first collapsed every statement, remittance,
        # credit note and contract to OTHER.
        classified = str(result.get("doc_type") or "").strip().upper()
        schema_type = str(data.get("doc_type") or "").strip().upper()
        row.doc_type = classified or schema_type or "OTHER"
        row.doc_number = data.get("doc_number") or None
        row.party_name = data.get("party_name") or None
        row.currency = data.get("currency") or None
        row.grand_total = data.get("grand_total")
        raw_date = data.get("doc_date")
        if raw_date:
            from datetime import date as _date

            try:
                row.doc_date = _date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                row.doc_date = None
        row.extraction_status = "EXTRACTED" if data else "EXTRACT_FAILED"
    except Exception as e:
        logger.error("Chat attachment extraction failed for %s: %s", row.id, e)
        row.extraction_status = "EXTRACT_FAILED"

    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    if row.extraction_status == "EXTRACTED":
        progress(STAGE_INDEXING)
        index_attachment(row, db_session)
        progress(STAGE_MATCHING)
        match_attachment(row, db_session)

    return row


def index_attachment(row: ChatAttachment, db_session: Session) -> None:
    """Embed the document's own text so a content question has something to read.

    Best-effort, and the asymmetry is deliberate (task H4): the chunks serve the
    content branch only. Part 1's whole comparison path reads the denormalised
    columns and needs no chunks whatsoever, so failing an upload over a Chroma
    write would remove a working feature to protect a degrading one. Logged at
    ERROR rather than swallowed silently.
    """
    try:
        from services.chat_document_search import index_attachment_chunks

        chunk_count = index_attachment_chunks(row, row.tenant_id)
        row.chunk_count = chunk_count
        from datetime import datetime

        row.indexed_at = datetime.utcnow()
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
    except Exception as e:
        logger.error("Chat attachment indexing failed for %s: %s", row.id, e)
        try:
            db_session.rollback()
        except Exception:
            pass


def match_attachment(row: ChatAttachment, db_session: Session) -> None:
    """Gap 444: propose the matching invoice(s) at upload, not on the first turn.

    A PROPOSAL and nothing more. `confirmed_invoice_ids` is untouched, so D4's
    confirmation gate behaves exactly as it did: no comparison runs and no figure
    is computed until the user agrees to the match.
    """
    if row.extraction_status != "EXTRACTED":
        return
    try:
        from services.document_comparison import find_candidate_invoices

        data = row.extracted_json or {}
        found = find_candidate_invoices(
            tenant_id=row.tenant_id,
            po_number=data.get("po_number") or row.doc_number,
            party_name=row.party_name,
            doc_date=row.doc_date,
            db_session=db_session,
        )
        invoices = found.get("invoices") or []
        row.candidate_invoice_ids = [str(inv.id) for inv in invoices]
        row.match_tier = found.get("tier")
        numbers = [inv.invoice_number for inv in invoices if inv.invoice_number]
        if row.match_tier == 1 and numbers:
            row.match_summary = f"matches {numbers[0]} by document number"
        elif row.match_tier == 2 and numbers:
            row.match_summary = f"probable match: {numbers[0]} (same party and date window)"
        elif row.match_tier == 3 and numbers:
            row.match_summary = f"{len(numbers)} possible match(es) found by content similarity"
        else:
            row.match_summary = "no matching invoice found yet"
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
    except Exception as e:
        logger.error("Match-at-upload failed for attachment %s: %s", row.id, e)
        try:
            db_session.rollback()
        except Exception:
            pass


def stage_label(stage: str) -> str:
    """Human wording for a stage, for any surface that has no copy of its own."""
    return {
        STAGE_READING: "Reading the document",
        STAGE_EXTRACTING: "Extracting the fields",
        STAGE_INDEXING: "Indexing the text",
        STAGE_MATCHING: "Looking for matching invoices",
        STAGE_READY: "Ready",
        STAGE_FAILED: "Could not read this document",
    }.get(stage, stage)
