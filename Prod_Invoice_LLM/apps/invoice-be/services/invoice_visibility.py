"""Invoice visibility helpers (Gap 192 soft delete).

Product-facing reads must hide soft-deleted invoices. Dedup-by-hash intentionally
does *not* use this filter so deleting then re-uploading the same PDF still
lands as DUPLICATE.
"""
from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from models import Invoice


def invoice_not_deleted() -> ColumnElement[bool]:
    """SQLAlchemy predicate: Invoice.deleted_at IS NULL."""
    return Invoice.deleted_at.is_(None)
