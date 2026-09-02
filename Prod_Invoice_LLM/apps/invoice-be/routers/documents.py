"""Feature 27 (G14) — read access to non-invoice documents (decision E10).

E10 sends a classified non-INVOICE-family upload to the `documents` table and
deletes the upload-time placeholder `invoice` row. That is correct — a delivery
note is not a payable and must not be counted as one — but it also means the
uploader has no way to see their own file again unless something reads that
table back. This module is that minimum surface: a tenant-scoped list and a
single-row detail.

Two endpoints:
  GET /documents          — list, tenant-scoped, soft-delete aware
  GET /documents/{id}     — one row

**Ownership is resolved through the database on every one of them**, via
`_require_owned_document()`, mirroring `routers/chat_attachments.py`'s
`_require_owned_attachment()`. This is not boilerplate: a security review of E10
(§2A/A4/F1) flagged the detail endpoint specifically, because the original spec
said "tenant-scoped" about the list and said nothing at all about the detail —
the asymmetry a single-tenant test never catches, and the exact shape of the
pre-Gap-341 IDOR. A purchase order or a contract holds another company's
negotiated pricing, delivery commitments and penalty terms; it is a worse leak
than an invoice total.

A cross-tenant id returns **404, never 403**, for the reason
`routers/chat_attachments.py` states: confirming that another tenant's row
exists is itself a disclosure.

The auth dependency is `get_tenant_context` (Clerk session), deliberately not the
API-key variant `get_tenant_or_api_key_context` that `routers/invoices.py`'s list
uses. Feature 25's API-key scopes were written against the invoice lifecycle and
no integration has ever been told this table exists; widening machine access to a
new document population is a product decision with its own scope question, not a
side effect of adding a read endpoint. Narrower is the reversible direction.
"""
import logging
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from dependencies import get_db_session, get_tenant_context, TenantContext
from models import Document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentOut(BaseModel):
    """The wire shape of a `Document`.

    An explicit response model rather than returning the ORM row (which is what
    `routers/invoices.py` does for `Invoice`), for one specific reason:
    `source_document_json` is Gap 178's raw Document Intelligence snapshot and
    has no business on a product API. It is a diagnostic blob, it is large, and
    on a non-invoice document it is DI's invoice-shaped misread of a document
    that is not an invoice — the single most misleading thing this row carries.
    Listing the fields explicitly means a column added later is opted *in*
    deliberately rather than published by default.
    """
    id: str
    tenant_id: str
    batch_id: Optional[str] = None
    file_path: str
    doc_type: Optional[str] = None
    doc_type_evidence: Optional[str] = None
    doc_type_confidence: Optional[float] = None
    party_name: Optional[str] = None
    counterparty_name: Optional[str] = None
    doc_number: Optional[str] = None
    po_number: Optional[str] = None
    reference_numbers: List[Any] = []
    doc_date: Optional[str] = None
    valid_until: Optional[str] = None
    currency: Optional[str] = None
    # Every money field is Optional and is passed through as-is. A delivery note
    # with no prices returns `null`, not `0` — "the document did not state it"
    # and "the document stated zero" are different facts, and collapsing them is
    # the Gap 283 class of bug.
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    grand_total: Optional[float] = None
    items: List[Any] = []
    taxes: List[Any] = []
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    incoterms: Optional[str] = None
    notes: Optional[str] = None
    status: str
    sa_alerts: List[Any] = []
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    submitted_by_email: Optional[str] = None


def _to_out(row: Document) -> DocumentOut:
    return DocumentOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        batch_id=str(row.batch_id) if row.batch_id else None,
        file_path=row.file_path,
        doc_type=row.doc_type,
        doc_type_evidence=row.doc_type_evidence,
        doc_type_confidence=row.doc_type_confidence,
        party_name=row.party_name,
        counterparty_name=row.counterparty_name,
        doc_number=row.doc_number,
        po_number=row.po_number,
        reference_numbers=list(row.reference_numbers or []),
        doc_date=row.doc_date.isoformat() if row.doc_date else None,
        valid_until=row.valid_until.isoformat() if row.valid_until else None,
        currency=row.currency,
        subtotal=row.subtotal,
        tax_amount=row.tax_amount,
        discount_amount=row.discount_amount,
        grand_total=row.grand_total,
        items=list(row.items or []),
        taxes=list(row.taxes or []),
        payment_terms=row.payment_terms,
        delivery_terms=row.delivery_terms,
        incoterms=row.incoterms,
        notes=row.notes,
        status=row.status,
        sa_alerts=list(row.sa_alerts or []),
        created_at=row.created_at.isoformat() if row.created_at else None,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        submitted_by_email=row.submitted_by_email,
    )


def _require_owned_document(
    document_id: UUID, db_session: Session, tenant_context: TenantContext
) -> Document:
    """Resolve one document, or 404. §2A/A4/F1.

    A **single** query carrying both predicates — `id` and `tenant_id` — rather
    than a fetch followed by a comparison. The two are equivalent when written
    correctly and are not equivalent when someone later edits one of them: a
    fetch-then-check can have its check deleted and still return rows, whereas
    deleting a predicate here changes a query that visibly has two of them.
    Same construction as `routers/chat_attachments.py::_require_owned_attachment`.

    Soft-deleted rows (Gap 192) are excluded here too, so a deleted document
    behaves identically to one that never existed on both endpoints rather than
    only on the list.
    """
    row = db_session.exec(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_context.tenant_id,
            Document.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    if row is None:
        # 404 rather than 403 on a cross-tenant id: confirming that someone
        # else's document exists is itself a disclosure.
        raise HTTPException(status_code=404, detail="Document not found.")
    return row


@router.get("", response_model=List[DocumentOut])
def list_documents(
    response: Response,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    doc_type: Optional[str] = None,
    batch_id: Optional[UUID] = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Non-invoice documents for the requesting tenant, most recent first.

    `tenant_id` comes from the resolved auth context and is never a parameter —
    there is no query string on this endpoint that can widen its scope.
    Soft-deleted rows are excluded (Gap 192). `X-Total-Count` matches the
    invoice list's pagination contract so an FE surface can reuse it.
    """
    conditions = [
        Document.tenant_id == tenant_context.tenant_id,
        Document.deleted_at.is_(None),  # type: ignore[union-attr]
    ]
    if doc_type:
        conditions.append(Document.doc_type == doc_type.strip().upper())
    if batch_id:
        conditions.append(Document.batch_id == batch_id)

    total = db_session.exec(
        select(func.count()).select_from(
            select(Document.id).where(*conditions).subquery()
        )
    ).one()
    response.headers["X-Total-Count"] = str(total)

    rows = db_session.exec(
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    ).all()
    return [_to_out(r) for r in rows]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """One document, resolved through `_require_owned_document()`."""
    return _to_out(_require_owned_document(document_id, db_session, tenant_context))
