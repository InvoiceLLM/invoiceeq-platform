"""
BE Gap 464 — the durable ingestion History screen's API.

WHAT PROBLEM THIS SOLVES. Feature 27 decision E10 routes a classified
non-invoice to the `documents` table and DELETES the placeholder `invoice` row
in the same transaction. A user uploads a delivery note and watches the row
vanish from the Ingest status table with no message at all. The surface built
for that (`app/documents/page.tsx`, task R5(c)) was a separate sidebar page
listing only `documents`, and the Ingest status table is client state that
clears on navigation — so there was no durable place to see what was ingested.
Email-in and connector imports had no home at ALL, and a rejected inbound mail
was visible only in the Admin console, which is the wrong audience.

THIS IS A LOG, NOT A DATA TABLE (founder, 2026-09-05). The list endpoint returns
one lightweight row per RUN: when, how it arrived, how many files, and what
happened to them. Nothing heavy is fetched to render it. The full record —
extracted fields, alerts, line items, doc attributes — is fetched only when a
row is expanded, from `GET /ingestion-history/{run_id}/files`. Same shape of
contract as Gap 427's `GET /autopilot/history/{batch_id}/files`, which this
module is modelled on throughout.

BOTH OUTCOMES ARE ROWS. A non-invoice is a normal, explained line — never a
disappearance. `outcome_label` reads "Loaded — VERIFIED", "Not loaded —
Delivery note", "Rejected — no invoice content", and it is computed HERE, in
deterministic code, not assembled by the client from parts.

Endpoints:
  GET  /api/v1/ingestion-history                     — paginated run log
  GET  /api/v1/ingestion-history/{run_id}/files      — one run's files, in full
  POST /api/v1/ingestion-history/archive-all         — archive every visible run
  POST /api/v1/ingestion-history/{run_id}/archive    — archive one run
  POST /api/v1/ingestion-history/{run_id}/unarchive  — restore one run

ARCHIVE, NOT DELETE, AND ONLY ONE WORD FOR IT. A history line is DERIVED from
the `Invoice`/`Document` records that carry its batch_id, so a true hard delete
would either regenerate on the next read or destroy the provenance of a live
invoice. `archived_at` is stamped, the read paths filter it, and nothing about
the invoice changes. The founder was explicit that only ONE label is offered:
two words for one behaviour ("hide" and "delete") is what makes a user believe
one of them removes the invoice. Real invoice deletion stays on the Audit Queue,
where the consequence is visible. POST verbs rather than DELETE for the same
reason — the HTTP method is part of the vocabulary a reader of this file sees.

THREE SOURCES, MERGED READ-ONLY:
  1. `ingestion_batches` — manual / email / connector runs (Gap 464's own table).
  2. `tenant_autopilot_logs` — Autopilot runs, grouped by batch_id exactly as
     `routers/autopilot.py` does. NOT copied, NOT migrated, and the Autopilot
     screen is untouched. Accepted, founder-flagged consequence: archiving an
     Autopilot run from here writes the same `hidden_at` column, so it
     disappears from both views. That is consistent, not a bug.
     The pre-Gap-427 "legacy" bucket (rows with no batch_id) is deliberately
     NOT merged: it is a synthetic aggregate of unrelated files that only makes
     sense inside the Autopilot screen's own vocabulary.
  3. `dropped_inbound_emails` — inbound mail that never became anything, shown
     as REJECTED runs. Only rows with a resolved `tenant_id`: a mail rejected
     before the sender was matched belongs to no tenant, and guessing one from
     `sender_domain` (which `routers/admin.py` does, for an operator audience)
     would put another company's mail in this tenant's history.

PAGINATION ACROSS THE UNION. Each source is queried, tenant-scoped and ordered,
for at most `offset + page_size` rows; the three lists are merged in Python,
sorted by `started_at` descending, and sliced. `X-Total-Count` is the sum of the
three counts. A cross-source SQL UNION was rejected: the three sources need
different aggregations (a GROUP BY for autopilot, a per-row read for dropped
mail) and expressing that as one statement makes the tenant predicate — the only
thing standing between two tenants' file names — much harder to see.
"""
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import case
from sqlmodel import Session, func, select

from dependencies import get_db_session, get_tenant_context, TenantContext
from models import Document, DroppedInboundEmail, IngestionBatch, Invoice, TenantAutopilotLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingestion-history", tags=["Ingestion History"])


# ---------------------------------------------------------------------------
# Outcome vocabulary — deterministic, computed here, never in the client
# ---------------------------------------------------------------------------
#
# CONVENTIONS hard rule 3 in miniature: "did this file load?" is a correctness
# statement about a user's document, so it is decided by these frozen sets and
# not by prose in a component. An unrecognised status falls through to LOADED
# rather than to a fourth silent state, and that fall-through is checked by a
# test rather than assumed.

# The pipeline has not finished with it yet. It is neither loaded nor rejected.
IN_PROGRESS_INVOICE_STATUSES = frozenset({"PROCESSING", "UPLOADED"})
# Terminal failures. The file arrived and produced nothing usable.
REJECTED_INVOICE_STATUSES = frozenset({"FAILED", "EXTRACT_FAILED", "REJECTED"})
# A duplicate is NOT a rejection and NOT a load: the row exists, but no new data
# entered the system. Reported as its own explained not-loaded reason rather
# than being quietly folded into either neighbour.
DUPLICATE_INVOICE_STATUSES = frozenset({"DUPLICATE"})

OUTCOME_LOADED = "LOADED"
OUTCOME_NOT_LOADED = "NOT_LOADED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_IN_PROGRESS = "IN_PROGRESS"

# `dropped_inbound_emails.reason` → the sentence the tenant reads. The stored
# reason is an operator-facing constant ("no_pdf_attachment"); this is the only
# place it is turned into something a person who emailed an invoice in would
# understand. An unmapped reason degrades to its own humanised form rather than
# to a generic "rejected", so a new DROP_REASONS value is never silently blank.
DROP_REASON_PHRASES = {
    "secret_unconfigured": "inbound mail is not configured",
    "unverified_secret": "the sender could not be verified",
    "oversized": "the message was too large",
    "malformed": "the message could not be read",
    "unknown_sender": "the sender is not registered for this workspace",
    "missing_tenant": "the workspace could not be resolved",
    "no_pdf_attachment": "no invoice content",
    "quota_exhausted": "the workspace has no free invoices left",
    "ingest_rejected": "the attachment was refused",
    "ingest_failed": "the attachment failed to ingest",
}


def _humanise(value: str | None) -> str:
    """`DELIVERY_NOTE` → `Delivery note`. Empty in, empty out."""
    if not value:
        return ""
    return value.replace("_", " ").capitalize()


def _invoice_outcome(status_value: str | None) -> tuple[str, str]:
    """(outcome, label) for one `Invoice` row. Deterministic, total."""
    value = (status_value or "").upper()
    if value in IN_PROGRESS_INVOICE_STATUSES:
        return OUTCOME_IN_PROGRESS, f"In progress — {_humanise(value)}"
    if value in REJECTED_INVOICE_STATUSES:
        return OUTCOME_REJECTED, f"Rejected — {_humanise(value)}"
    if value in DUPLICATE_INVOICE_STATUSES:
        return OUTCOME_NOT_LOADED, "Not loaded — duplicate of an earlier upload"
    return OUTCOME_LOADED, f"Loaded — {value or 'UNKNOWN'}"


def _document_outcome(row: Document) -> tuple[str, str]:
    """(outcome, label) for one `Document` row.

    ALWAYS NOT_LOADED, never REJECTED, and the distinction is the whole point of
    the feature: a delivery note that extracted perfectly did not fail at
    anything. It is simply not a payable, and the label says which kind of
    document it turned out to be instead.
    """
    if (row.status or "").upper() == "EXTRACT_FAILED":
        return OUTCOME_NOT_LOADED, "Not loaded — could not be read"
    label = _humanise(row.doc_type) or "Not an invoice"
    return OUTCOME_NOT_LOADED, f"Not loaded — {label}"


def _dropped_email_outcome(reason: str | None) -> tuple[str, str]:
    key = (reason or "").lower()
    phrase = DROP_REASON_PHRASES.get(key) or _humanise(key).lower() or "refused"
    return OUTCOME_REJECTED, f"Rejected — {phrase}"


def _derive_run_status(
    loaded: int, not_loaded: int, rejected: int, in_progress: int, file_count: int
) -> str:
    """Collapse a run's file outcomes into one run-level status.

    Checked in this order, and the order is the reasoning:
      - anything still moving          -> IN_PROGRESS (the run is not over yet)
      - a mix of loaded and rejected   -> PARTIAL
      - rejected and nothing else      -> REJECTED
      - nothing loaded, but files seen -> NOT_LOADED (the delivery-note case)
      - no files at all                -> EMPTY
      - anything else                  -> LOADED
    """
    if in_progress:
        return "IN_PROGRESS"
    if rejected and (loaded or not_loaded):
        return "PARTIAL"
    if rejected:
        return "REJECTED"
    if not (loaded or not_loaded or rejected):
        return "EMPTY" if file_count == 0 else "IN_PROGRESS"
    if not loaded:
        return "NOT_LOADED"
    return "LOADED"


def _run_summary(
    loaded: int, not_loaded: int, rejected: int, in_progress: int, file_count: int
) -> str:
    """"3 files: 1 loaded, 1 not loaded, 1 rejected" — zero clauses dropped."""
    parts: list[str] = []
    if loaded:
        parts.append(f"{loaded} loaded")
    if not_loaded:
        parts.append(f"{not_loaded} not loaded")
    if rejected:
        parts.append(f"{rejected} rejected")
    if in_progress:
        parts.append(f"{in_progress} in progress")
    noun = "file" if file_count == 1 else "files"
    if not parts:
        return f"{file_count} {noun}"
    return f"{file_count} {noun}: {', '.join(parts)}"


# ---------------------------------------------------------------------------
# Run id vocabulary
# ---------------------------------------------------------------------------
#
# A bare UUID is an `ingestion_batches` run. The other two sources are prefixed,
# because their ids live in different tables and a bare UUID collision between
# them would silently drill into the wrong run.

AUTOPILOT_PREFIX = "autopilot:"
EMAIL_PREFIX = "email:"

SOURCE_AUTOPILOT = "autopilot"
SOURCE_EMAIL = "email"
VALID_TRIGGERS = ("manual", "email", "connector", "autopilot")


def _parse_run_id(run_id: str) -> tuple[str, UUID]:
    """(kind, uuid) for a run id, or 404.

    A malformed id is a 404, never a 422 — indistinguishable to the caller from
    a run that does not exist, which is the same non-probing rule
    `routers/autopilot.py::get_run_files` follows.
    """
    raw = run_id
    kind = "batch"
    if run_id.startswith(AUTOPILOT_PREFIX):
        kind, raw = SOURCE_AUTOPILOT, run_id[len(AUTOPILOT_PREFIX):]
    elif run_id.startswith(EMAIL_PREFIX):
        kind, raw = SOURCE_EMAIL, run_id[len(EMAIL_PREFIX):]
    try:
        return kind, UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------

class IngestionRunEntry(BaseModel):
    """One line of the log. Everything here is cheap to compute from counts."""
    run_id: str
    # 'manual' | 'email' | 'connector' | 'autopilot'
    source: str
    # 'INBOUND' (receiving) | 'OUTBOUND' (sending). NULL only where the run
    # never got far enough to have one — a mail rejected before its set was read.
    flow_direction: Optional[str] = None
    started_at: datetime
    file_count: int
    loaded: int = 0
    not_loaded: int = 0
    rejected: int = 0
    in_progress: int = 0
    status: str
    summary: str
    archived_at: Optional[datetime] = None


class IngestionHistoryResponse(BaseModel):
    items: list[IngestionRunEntry]
    total: int
    page: int
    page_size: int


class IngestionFileEntry(BaseModel):
    """One file inside a run, WITH its full record.

    `record` is the expensive half and is why this endpoint exists separately
    from the list: extracted fields, alerts, line items and doc attributes are
    fetched only when a row is expanded.
    """
    id: str
    # 'invoice' | 'document' | 'autopilot_file' | 'rejected_email'
    kind: str
    file_name: str
    outcome: str
    outcome_label: str
    status: Optional[str] = None
    doc_type: Optional[str] = None
    created_at: Optional[datetime] = None
    record: dict[str, Any] = {}


class IngestionRunFilesResponse(BaseModel):
    items: list[IngestionFileEntry]


class IngestionArchiveResponse(BaseModel):
    archived: int


# ---------------------------------------------------------------------------
# GET /ingestion-history
# ---------------------------------------------------------------------------

def _count_expr(column, values: frozenset[str]):
    """COUNT of rows whose `column` is in `values`, per GROUP BY group."""
    return func.coalesce(
        func.sum(case((column.in_(tuple(values)), 1), else_=0)), 0
    )


def _batch_runs(
    db_session: Session,
    tenant_id: UUID,
    archived: bool,
    trigger: Optional[str],
    flow_direction: Optional[str],
    limit: int,
) -> tuple[int, list[IngestionRunEntry]]:
    """`ingestion_batches` runs, with their outcomes derived from the rows."""
    conditions = [IngestionBatch.tenant_id == tenant_id]
    conditions.append(
        IngestionBatch.archived_at.is_not(None)  # type: ignore[union-attr]
        if archived
        else IngestionBatch.archived_at.is_(None)  # type: ignore[union-attr]
    )
    if trigger:
        conditions.append(IngestionBatch.trigger == trigger)
    if flow_direction:
        conditions.append(IngestionBatch.flow_direction == flow_direction)

    total = int(
        db_session.exec(
            select(func.count()).select_from(
                select(IngestionBatch.batch_id).where(*conditions).subquery()
            )
        ).one()
    )
    rows = db_session.exec(
        select(IngestionBatch)
        .where(*conditions)
        .order_by(IngestionBatch.started_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    if not rows:
        return total, []

    batch_ids = [r.batch_id for r in rows]

    # ONE grouped query per table for the whole page, not one per run: an N+1
    # here would be N+1 on every page of a log the user opens constantly.
    invoice_counts = {
        row.batch_id: row
        for row in db_session.exec(
            select(
                Invoice.batch_id,
                func.count().label("total"),
                _count_expr(Invoice.status, IN_PROGRESS_INVOICE_STATUSES).label("in_progress"),
                _count_expr(Invoice.status, REJECTED_INVOICE_STATUSES).label("rejected"),
                _count_expr(Invoice.status, DUPLICATE_INVOICE_STATUSES).label("duplicate"),
            )
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.batch_id.in_(batch_ids),  # type: ignore[union-attr]
                Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
            )
            .group_by(Invoice.batch_id)
        ).all()
    }
    document_counts = {
        row.batch_id: int(row.total or 0)
        for row in db_session.exec(
            select(Document.batch_id, func.count().label("total"))
            .where(
                Document.tenant_id == tenant_id,
                Document.batch_id.in_(batch_ids),  # type: ignore[union-attr]
                Document.deleted_at.is_(None),  # type: ignore[union-attr]
            )
            .group_by(Document.batch_id)
        ).all()
    }

    items: list[IngestionRunEntry] = []
    for run in rows:
        inv = invoice_counts.get(run.batch_id)
        inv_total = int(inv.total or 0) if inv else 0
        in_progress = int(inv.in_progress or 0) if inv else 0
        rejected = int(inv.rejected or 0) if inv else 0
        duplicate = int(inv.duplicate or 0) if inv else 0
        loaded = max(0, inv_total - in_progress - rejected - duplicate)
        # `documents` rows plus duplicate invoices are both "arrived, explained,
        # not a new payable" — the two ways a file legitimately does not load.
        not_loaded = document_counts.get(run.batch_id, 0) + duplicate
        # `file_count` is what the door accepted; the derived counts can exceed
        # it only if something was re-ingested into the same batch, so the
        # displayed file total is the larger of the two rather than a number the
        # expansion visibly contradicts.
        file_count = max(run.file_count, loaded + not_loaded + rejected + in_progress)
        items.append(
            IngestionRunEntry(
                run_id=str(run.batch_id),
                source=run.trigger,
                flow_direction=run.flow_direction,
                started_at=run.started_at,
                file_count=file_count,
                loaded=loaded,
                not_loaded=not_loaded,
                rejected=rejected,
                in_progress=in_progress,
                status=_derive_run_status(loaded, not_loaded, rejected, in_progress, file_count),
                summary=_run_summary(loaded, not_loaded, rejected, in_progress, file_count),
                archived_at=run.archived_at,
            )
        )
    return total, items


def _autopilot_runs(
    db_session: Session,
    tenant_id: UUID,
    archived: bool,
    flow_direction: Optional[str],
    limit: int,
) -> tuple[int, list[IngestionRunEntry]]:
    """Autopilot runs, read through from `tenant_autopilot_logs` unchanged.

    `flow_direction` filters this source OUT entirely when it is set to
    OUTBOUND: an Autopilot config carries a flow_direction but its log rows do
    not, and inventing one per run by joining back to the config would attribute
    every historical run to the config's CURRENT setting. Autopilot is reported
    as INBOUND, which is what every existing run is, and a Sending filter
    therefore shows none rather than showing them mislabelled.
    """
    if flow_direction and flow_direction != "INBOUND":
        return 0, []
    visibility = (
        TenantAutopilotLog.hidden_at.is_not(None)  # type: ignore[union-attr]
        if archived
        else TenantAutopilotLog.hidden_at.is_(None)  # type: ignore[union-attr]
    )
    conditions = [
        TenantAutopilotLog.tenant_id == tenant_id,
        TenantAutopilotLog.batch_id.is_not(None),  # type: ignore[union-attr]
        visibility,
    ]
    total = int(
        db_session.exec(
            select(func.count(func.distinct(TenantAutopilotLog.batch_id))).where(*conditions)
        ).one()
    )
    rows = db_session.exec(
        select(
            TenantAutopilotLog.batch_id,
            func.min(TenantAutopilotLog.ingested_at).label("started_at"),
            func.max(TenantAutopilotLog.hidden_at).label("archived_at"),
            _count_expr(TenantAutopilotLog.status, frozenset({"SUCCESS"})).label("loaded"),
            _count_expr(
                TenantAutopilotLog.status, frozenset({"SKIPPED_DUPLICATE"})
            ).label("skipped"),
            _count_expr(TenantAutopilotLog.status, frozenset({"FAILED"})).label("failed"),
        )
        .where(*conditions)
        .group_by(TenantAutopilotLog.batch_id)
        .order_by(func.min(TenantAutopilotLog.ingested_at).desc())
        .limit(limit)
    ).all()

    items: list[IngestionRunEntry] = []
    for row in rows:
        loaded = int(row.loaded or 0)
        # A skipped duplicate is the same fact as a DUPLICATE invoice: it
        # arrived, it is explained, and no new payable came of it.
        not_loaded = int(row.skipped or 0)
        rejected = int(row.failed or 0)
        file_count = loaded + not_loaded + rejected
        items.append(
            IngestionRunEntry(
                run_id=f"{AUTOPILOT_PREFIX}{row.batch_id}",
                source=SOURCE_AUTOPILOT,
                flow_direction="INBOUND",
                started_at=row.started_at,
                file_count=file_count,
                loaded=loaded,
                not_loaded=not_loaded,
                rejected=rejected,
                in_progress=0,
                status=_derive_run_status(loaded, not_loaded, rejected, 0, file_count),
                summary=_run_summary(loaded, not_loaded, rejected, 0, file_count),
                archived_at=row.archived_at,
            )
        )
    return total, items


def _dropped_email_runs(
    db_session: Session,
    tenant_id: UUID,
    archived: bool,
    flow_direction: Optional[str],
    limit: int,
) -> tuple[int, list[IngestionRunEntry]]:
    """Rejected inbound mail, one run per dropped message.

    Excluded from a `flow_direction` filter for the reason the module docstring
    gives: a mail rejected before its set was resolved has no direction, and
    guessing one would be a fabricated fact on a screen whose only job is to
    report what happened.
    """
    if flow_direction:
        return 0, []
    conditions = [
        # Tenant-attributed rows only. `routers/admin.py::list_dropped_emails`
        # additionally surfaces unattributed rows by `sender_domain` for an
        # OPERATOR audience; doing that here would show one tenant a mail that
        # merely looks like theirs.
        DroppedInboundEmail.tenant_id == tenant_id,
    ]
    conditions.append(
        DroppedInboundEmail.archived_at.is_not(None)  # type: ignore[union-attr]
        if archived
        else DroppedInboundEmail.archived_at.is_(None)  # type: ignore[union-attr]
    )
    total = int(
        db_session.exec(
            select(func.count()).select_from(
                select(DroppedInboundEmail.id).where(*conditions).subquery()
            )
        ).one()
    )
    rows = db_session.exec(
        select(DroppedInboundEmail)
        .where(*conditions)
        .order_by(DroppedInboundEmail.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    items = []
    for row in rows:
        _, label = _dropped_email_outcome(row.reason)
        items.append(
            IngestionRunEntry(
                run_id=f"{EMAIL_PREFIX}{row.id}",
                source=SOURCE_EMAIL,
                flow_direction=None,
                started_at=row.created_at,
                file_count=1 if row.filename else 0,
                loaded=0,
                not_loaded=0,
                rejected=1,
                in_progress=0,
                status="REJECTED",
                summary=label,
                archived_at=row.archived_at,
            )
        )
    return total, items


@router.get("", response_model=IngestionHistoryResponse)
def list_ingestion_history(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    trigger: Optional[str] = Query(default=None),
    flow_direction: Optional[str] = Query(default=None),
    archived: bool = Query(default=False),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """This tenant's ingestion log, newest first, one row per run.

    `trigger` is one of manual/email/connector/autopilot; `flow_direction` is
    INBOUND or OUTBOUND; `archived=true` shows the archived view instead of the
    live one (never both — an archived row is hidden, and a list that showed it
    alongside live rows would make "archive" look like it did nothing).

    `X-Total-Count` carries the total, matching `GET /documents` and
    `GET /invoices`; the body repeats it as `total` so a client can page from
    either, matching `GET /autopilot/history`.
    """
    if trigger is not None:
        trigger = trigger.strip().lower()
        if trigger not in VALID_TRIGGERS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"trigger must be one of {', '.join(VALID_TRIGGERS)}.",
            )
    if flow_direction is not None:
        flow_direction = flow_direction.strip().upper()
        if flow_direction not in ("INBOUND", "OUTBOUND"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="flow_direction must be INBOUND or OUTBOUND.",
            )

    offset = (page - 1) * page_size
    # Each source only ever needs enough rows to fill the requested window in
    # the worst case where every row on the page came from it alone.
    window = offset + page_size

    # `ingestion_batches` answers manual / email / connector; `autopilot` is the
    # one trigger it can never produce, so that filter skips this source
    # entirely rather than querying for a value the column never holds.
    batch_total, batch_items = (0, [])
    if trigger != SOURCE_AUTOPILOT:
        batch_total, batch_items = _batch_runs(
            db_session, context.tenant_id, archived, trigger, flow_direction, window,
        )

    autopilot_total, autopilot_items = (0, [])
    if trigger in (None, SOURCE_AUTOPILOT):
        autopilot_total, autopilot_items = _autopilot_runs(
            db_session, context.tenant_id, archived, flow_direction, window
        )

    dropped_total, dropped_items = (0, [])
    if trigger in (None, SOURCE_EMAIL):
        dropped_total, dropped_items = _dropped_email_runs(
            db_session, context.tenant_id, archived, flow_direction, window
        )

    merged = batch_items + autopilot_items + dropped_items
    merged.sort(key=lambda item: item.started_at, reverse=True)
    total = batch_total + autopilot_total + dropped_total

    response.headers["X-Total-Count"] = str(total)
    return IngestionHistoryResponse(
        items=merged[offset: offset + page_size],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /ingestion-history/{run_id}/files  — the expensive half, on demand only
# ---------------------------------------------------------------------------

def _invoice_record(row: Invoice) -> dict[str, Any]:
    """The full `Invoice` record for an expanded row.

    Fields are listed explicitly rather than dumping the ORM row, the same
    decision and for the same reason as `routers/documents.py::DocumentOut`:
    `source_document_json` is Gap 178's raw Document Intelligence diagnostic
    blob and has no business on a product API, and an explicit list means a
    column added later is opted IN deliberately.
    """
    return {
        "vendor_name": row.vendor_name,
        "invoice_number": row.invoice_number,
        "invoice_date": row.invoice_date.isoformat() if row.invoice_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "po_number": row.po_number,
        "currency": row.currency,
        "subtotal": row.subtotal,
        "tax_amount": row.tax_amount,
        "discount_amount": row.discount_amount,
        "grand_total": row.grand_total,
        "items": list(row.items or []),
        "taxes": list(row.taxes or []),
        "sa_alerts": list(row.sa_alerts or []),
        "tags": list(row.tags or []),
        "flow_direction": row.flow_direction,
        "submitted_by_email": row.submitted_by_email,
    }


def _document_record(row: Document) -> dict[str, Any]:
    """The full `Document` record — including `doc_attributes`, which is the
    evidence for WHY this file is not an invoice and is the single most useful
    thing on an expanded not-loaded row."""
    return {
        "doc_type": row.doc_type,
        "doc_type_evidence": row.doc_type_evidence,
        "doc_type_confidence": row.doc_type_confidence,
        "doc_attributes": row.doc_attributes or {},
        "party_name": row.party_name,
        "counterparty_name": row.counterparty_name,
        "doc_number": row.doc_number,
        "po_number": row.po_number,
        "reference_numbers": list(row.reference_numbers or []),
        "doc_date": row.doc_date.isoformat() if row.doc_date else None,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "currency": row.currency,
        "subtotal": row.subtotal,
        "tax_amount": row.tax_amount,
        "discount_amount": row.discount_amount,
        "grand_total": row.grand_total,
        "items": list(row.items or []),
        "taxes": list(row.taxes or []),
        "sa_alerts": list(row.sa_alerts or []),
        "payment_terms": row.payment_terms,
        "delivery_terms": row.delivery_terms,
        "incoterms": row.incoterms,
        "notes": row.notes,
        "submitted_by_email": row.submitted_by_email,
    }


def _file_name(file_path: str | None) -> str:
    """Last path segment of a blob/local path. The stored value is a location
    (`azure://invoices/tenants/…/x.pdf`); a person recognises the file name."""
    if not file_path:
        return "(unnamed file)"
    return file_path.replace("\\", "/").rstrip("/").split("/")[-1] or file_path


@router.get("/{run_id}/files", response_model=IngestionRunFilesResponse)
def get_ingestion_run_files(
    run_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Every file in one run, WITH its full record — the expand payload.

    Tenant-scoped in the WHERE clause of every branch, not merely looked up by
    id. A run id is a bare identifier in a URL and this predicate is the only
    thing standing between one tenant and another tenant's file names and
    negotiated prices. An unknown run and another tenant's run both 404,
    deliberately indistinguishable.

    Archived runs are still drillable. That differs from
    `routers/autopilot.py`'s hide, which 404s a hidden run — deliberately:
    archiving here is an inbox-style tidy with a visible Archived filter that
    can be browsed, so a row the user can see but not open would be a dead end.
    """
    kind, parsed = _parse_run_id(run_id)

    if kind == SOURCE_EMAIL:
        row = db_session.exec(
            select(DroppedInboundEmail).where(
                DroppedInboundEmail.id == parsed,
                DroppedInboundEmail.tenant_id == context.tenant_id,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Ingestion run not found.")
        _, label = _dropped_email_outcome(row.reason)
        return IngestionRunFilesResponse(items=[
            IngestionFileEntry(
                id=str(row.id),
                kind="rejected_email",
                file_name=row.filename or "(no attachment)",
                outcome=OUTCOME_REJECTED,
                outcome_label=label,
                status=row.reason,
                created_at=row.created_at,
                record={
                    "from_email": row.from_email,
                    "to_email": row.to_email,
                    "reason": row.reason,
                    "detail": row.detail,
                    "content_length": row.content_length,
                },
            )
        ])

    if kind == SOURCE_AUTOPILOT:
        logs = db_session.exec(
            select(TenantAutopilotLog)
            .where(
                TenantAutopilotLog.tenant_id == context.tenant_id,
                TenantAutopilotLog.batch_id == parsed,
            )
            .order_by(TenantAutopilotLog.ingested_at.desc())  # type: ignore[union-attr]
        ).all()
        if not logs:
            raise HTTPException(status_code=404, detail="Ingestion run not found.")
        items = []
        for log in logs:
            log_status = (log.status or "").upper()
            if log_status == "SUCCESS":
                outcome, label = OUTCOME_LOADED, "Loaded — SUCCESS"
            elif log_status == "SKIPPED_DUPLICATE":
                outcome, label = OUTCOME_NOT_LOADED, "Not loaded — duplicate of an earlier import"
            elif log_status == "NO_NEW_FILES":
                outcome, label = OUTCOME_NOT_LOADED, "Not loaded — nothing new to import"
            else:
                outcome, label = OUTCOME_REJECTED, "Rejected — import failed"
            items.append(
                IngestionFileEntry(
                    id=str(log.id),
                    kind="autopilot_file",
                    file_name=log.source_file_name or log.source_file_id or "(unnamed file)",
                    outcome=outcome,
                    outcome_label=label,
                    status=log.status,
                    created_at=log.ingested_at,
                    record={
                        "source_type": log.source_type,
                        "source_file_id": log.source_file_id,
                        "content_hash": log.content_hash,
                        "error_detail": log.error_detail,
                    },
                )
            )
        return IngestionRunFilesResponse(items=items)

    run = db_session.exec(
        select(IngestionBatch).where(
            IngestionBatch.batch_id == parsed,
            IngestionBatch.tenant_id == context.tenant_id,
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")

    items: list[IngestionFileEntry] = []
    invoices = db_session.exec(
        select(Invoice)
        .where(
            Invoice.tenant_id == context.tenant_id,
            Invoice.batch_id == parsed,
            Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
        )
        .order_by(Invoice.created_at.desc())  # type: ignore[union-attr]
    ).all()
    for inv in invoices:
        outcome, label = _invoice_outcome(inv.status)
        items.append(
            IngestionFileEntry(
                id=str(inv.id),
                kind="invoice",
                file_name=_file_name(inv.file_path),
                outcome=outcome,
                outcome_label=label,
                status=inv.status,
                created_at=inv.created_at,
                record=_invoice_record(inv),
            )
        )

    documents = db_session.exec(
        select(Document)
        .where(
            Document.tenant_id == context.tenant_id,
            Document.batch_id == parsed,
            Document.deleted_at.is_(None),  # type: ignore[union-attr]
        )
        .order_by(Document.created_at.desc())  # type: ignore[union-attr]
    ).all()
    for doc in documents:
        outcome, label = _document_outcome(doc)
        items.append(
            IngestionFileEntry(
                id=str(doc.id),
                kind="document",
                file_name=_file_name(doc.file_path),
                outcome=outcome,
                outcome_label=label,
                status=doc.status,
                doc_type=doc.doc_type,
                created_at=doc.created_at,
                record=_document_record(doc),
            )
        )

    items.sort(key=lambda i: i.created_at or datetime.min, reverse=True)
    return IngestionRunFilesResponse(items=items)


# ---------------------------------------------------------------------------
# Archive / unarchive
# ---------------------------------------------------------------------------
#
# `/archive-all` is declared BEFORE `/{run_id}/archive`. FastAPI matches in
# declaration order and the two do not actually collide (different segment
# counts), but the ordering is kept as the same defensive habit
# routers/autopilot.py documents for its `legacy` route.

def _set_archived(
    db_session: Session, tenant_id: UUID, run_id: str, when: datetime | None
) -> int:
    """Stamp (or clear) the archive marker for one run. Returns rows changed."""
    kind, parsed = _parse_run_id(run_id)
    changed = 0

    if kind == SOURCE_EMAIL:
        row = db_session.exec(
            select(DroppedInboundEmail).where(
                DroppedInboundEmail.id == parsed,
                DroppedInboundEmail.tenant_id == tenant_id,
            )
        ).first()
        if row is not None and (row.archived_at is None) == (when is not None):
            row.archived_at = when
            db_session.add(row)
            changed = 1
    elif kind == SOURCE_AUTOPILOT:
        # Founder-accepted consequence: this is the SAME `hidden_at` column the
        # Autopilot screen filters on, so archiving a run here removes it from
        # both views. Consistent, not a bug — there is one run and one
        # visibility fact about it, not two.
        rows = db_session.exec(
            select(TenantAutopilotLog).where(
                TenantAutopilotLog.tenant_id == tenant_id,
                TenantAutopilotLog.batch_id == parsed,
            )
        ).all()
        for row in rows:
            if (row.hidden_at is None) == (when is not None):
                row.hidden_at = when
                db_session.add(row)
                changed += 1
    else:
        row = db_session.exec(
            select(IngestionBatch).where(
                IngestionBatch.batch_id == parsed,
                IngestionBatch.tenant_id == tenant_id,
            )
        ).first()
        if row is not None and (row.archived_at is None) == (when is not None):
            row.archived_at = when
            db_session.add(row)
            changed = 1

    db_session.commit()
    return changed


@router.post("/archive-all", response_model=IngestionArchiveResponse)
def archive_all_ingestion_history(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Archives every currently-visible run in this tenant's history.

    Covers all three sources, including the rejected inbound mails — an
    "archive all" that quietly skipped a source would leave the list non-empty
    the instant after the user emptied it.

    Not a 404 on an empty history: archiving nothing is a no-op the user asked
    for, not an error. Same ruling as
    `routers/autopilot.py::hide_all_autopilot_history`.
    """
    now = datetime.utcnow()
    archived = 0

    for row in db_session.exec(
        select(IngestionBatch).where(
            IngestionBatch.tenant_id == context.tenant_id,
            IngestionBatch.archived_at.is_(None),  # type: ignore[union-attr]
        )
    ).all():
        row.archived_at = now
        db_session.add(row)
        archived += 1

    for row in db_session.exec(
        select(TenantAutopilotLog).where(
            TenantAutopilotLog.tenant_id == context.tenant_id,
            TenantAutopilotLog.hidden_at.is_(None),  # type: ignore[union-attr]
        )
    ).all():
        row.hidden_at = now
        db_session.add(row)
        archived += 1

    for row in db_session.exec(
        select(DroppedInboundEmail).where(
            DroppedInboundEmail.tenant_id == context.tenant_id,
            DroppedInboundEmail.archived_at.is_(None),  # type: ignore[union-attr]
        )
    ).all():
        row.archived_at = now
        db_session.add(row)
        archived += 1

    db_session.commit()
    logger.info(
        "Gap 464: archived %d ingestion history row(s) for tenant %s (archive all)",
        archived, context.tenant_id,
    )
    return IngestionArchiveResponse(archived=archived)


@router.post("/{run_id}/archive", response_model=IngestionArchiveResponse)
def archive_ingestion_run(
    run_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Archives one run. Nothing about the invoice or document changes.

    An unknown run, another tenant's run and an already-archived run all return
    404 — the same non-probing rule as the drill-down.
    """
    archived = _set_archived(db_session, context.tenant_id, run_id, datetime.utcnow())
    if archived == 0:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    logger.info(
        "Gap 464: archived run %s (%d row(s)) for tenant %s",
        run_id, archived, context.tenant_id,
    )
    return IngestionArchiveResponse(archived=archived)


@router.post("/{run_id}/unarchive", response_model=IngestionArchiveResponse)
def unarchive_ingestion_run(
    run_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Restores one archived run to the live list. The exact inverse of archive."""
    restored = _set_archived(db_session, context.tenant_id, run_id, None)
    if restored == 0:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    logger.info(
        "Gap 464: unarchived run %s (%d row(s)) for tenant %s",
        run_id, restored, context.tenant_id,
    )
    return IngestionArchiveResponse(archived=restored)
