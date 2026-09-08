"""Hard delete for invoices and documents (Gap 460, reopened 2026-09-08).

Founder rule, stated repeatedly and made a hard rule on 2026-09-08: **delete
means the record is gone from every store**. Gap 192 (2026-08-11) had turned
`DELETE /invoices/{id}` into a soft delete (`Invoice.deleted_at`) to keep an
audit trail that no screen displays; every read path since then had to remember
`deleted_at IS NULL`, and three leaks followed — Gap 460's RAG chunks, and on
2026-09-08 the model-generated SQL route, whose only guard is tenant isolation
(`agents/query_agent.py` safety checks) and whose prompt rule 6 explicitly says
soft-deleted rows "are not excluded anywhere today". Gap 460 closed the RAG half
and asserted the SQL half was safe; it was not. This module is the proper fix:
the row is removed, so no read path — SQL, RAG, views, cache, future feature —
can leak it by forgetting a filter.

What one invoice delete removes, in one transaction:
  * every `audit_logs` row for the invoice (they describe data that no longer
    exists), replaced by ONE `DELETE_INVOICE` summary row (number, vendor, status,
    who, when) — the only trace allowed to remain;
  * `document_comparisons` rows keyed on the invoice;
  * back-references: `invoice.duplicate_of_invoice_id`, `invoice.source_invoice_id`
    (both real FKs — the delete would otherwise fail) and
    `bank_statement_line.matched_invoice_id` are set to NULL;
  * the `invoice` row itself.
After the commit, and each swallowing its own errors so a completed delete is
never turned into a 500 the caller would retry against a row that is already
gone: the PDF blob, the Chroma chunks, and every cached chat answer for the
tenant (`chat_answer_cache:<tenant>:*`) — the worker log on 2026-09-08 showed a
cached SQL answer still listing 58 invoices after deletes.

`Invoice.deleted_at` / `Document.deleted_at` stay as columns (add-only rule) and
`invoice_not_deleted()` stays as a predicate; nothing sets them any more, so
every existing filter is inert rather than wrong.
"""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete as sa_delete, update as sa_update
from sqlmodel import Session

from models import AuditLog, BankStatementLine, Document, DocumentComparison, Invoice

logger = logging.getLogger(__name__)

CHAT_CACHE_PATTERN = "chat_answer_cache:{tenant_id}:*"


def delete_invoice_rows(
    db_session: Session,
    invoice: Invoice,
    *,
    actor_user_id: UUID,
    actor_role: str,
    extra_details: dict | None = None,
) -> None:
    """Remove the invoice and everything that points at it. Does NOT commit —
    the caller commits once for the whole request (single or batch)."""
    now = datetime.utcnow()
    invoice_id = invoice.id
    tenant_id = invoice.tenant_id

    db_session.execute(
        sa_update(Invoice)
        .where(Invoice.tenant_id == tenant_id, Invoice.duplicate_of_invoice_id == invoice_id)
        .values(duplicate_of_invoice_id=None)
    )
    db_session.execute(
        sa_update(Invoice)
        .where(Invoice.tenant_id == tenant_id, Invoice.source_invoice_id == invoice_id)
        .values(source_invoice_id=None)
    )
    db_session.execute(
        sa_update(BankStatementLine)
        .where(BankStatementLine.tenant_id == tenant_id, BankStatementLine.matched_invoice_id == invoice_id)
        .values(matched_invoice_id=None)
    )
    db_session.execute(
        sa_delete(DocumentComparison).where(
            DocumentComparison.tenant_id == tenant_id, DocumentComparison.invoice_id == invoice_id
        )
    )
    db_session.execute(
        sa_delete(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.invoice_id == invoice_id)
    )

    details = {
        "hard_delete": True,
        "vendor_name": invoice.vendor_name,
        "invoice_number": invoice.invoice_number,
        "status": invoice.status,
    }
    if extra_details:
        details.update(extra_details)
    db_session.add(
        AuditLog(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="DELETE_INVOICE",
            details=details,
            timestamp=now,
        )
    )
    db_session.delete(invoice)


def delete_document_rows(db_session: Session, document: Document) -> None:
    """Remove the document row. No AuditLog row: `AuditLog.invoice_id` is
    non-nullable and a document id in it would be a lie by column name (Gap 398)."""
    db_session.delete(document)


def purge_invoice_stores(invoice_id: UUID, tenant_id: UUID, file_path: str | None) -> None:
    """After the commit: blob, Chroma chunks, chat cache. Every step is
    best-effort and logged; an orphaned blob or chunk is reachable by the
    existing sweeps, a 500 here would not be."""
    _delete_blob(file_path, what=f"invoice {invoice_id}")
    try:
        from chroma_client import delete_invoice_chunks

        delete_invoice_chunks(str(invoice_id), str(tenant_id))
    except Exception as e:  # pragma: no cover - chroma_client already swallows
        logger.warning("Chroma chunk delete failed for invoice %s: %s", invoice_id, e)
    invalidate_tenant_chat_cache(tenant_id)


def purge_document_stores(document_id: UUID, tenant_id: UUID, file_path: str | None) -> None:
    _delete_blob(file_path, what=f"document {document_id}")
    try:
        from chroma_client import delete_document_chunks

        delete_document_chunks(str(document_id), str(tenant_id))
    except Exception as e:  # pragma: no cover
        logger.warning("Chroma chunk delete failed for document %s: %s", document_id, e)
    invalidate_tenant_chat_cache(tenant_id)


def invalidate_tenant_chat_cache(tenant_id: UUID) -> int:
    """Drop every cached chat answer for the tenant. A cached SQL answer built
    before the delete would otherwise keep returning the deleted invoice for
    the cache TTL. Returns the number of keys removed (0 on any failure)."""
    try:
        from agents.query_agent import _get_redis_client

        client = _get_redis_client()
        keys = list(client.scan_iter(match=CHAT_CACHE_PATTERN.format(tenant_id=tenant_id), count=500))
        if keys:
            client.delete(*keys)
        return len(keys)
    except Exception as e:
        logger.warning("Chat cache invalidation failed for tenant %s: %s", tenant_id, e)
        return 0


def _delete_blob(file_path: str | None, *, what: str) -> None:
    if not file_path:
        return
    try:
        from services.storage import delete_pdf_from_storage

        delete_pdf_from_storage(file_path)
    except Exception as e:
        logger.warning("Blob delete failed for %s (%s): %s", what, file_path, e)
