"""Invoice visibility helpers (Gap 192 soft delete).

Product-facing reads must hide soft-deleted invoices. Dedup-by-hash intentionally
does *not* use this filter so deleting then re-uploading the same PDF still
lands as DUPLICATE.
"""
from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from models import Invoice


def invoice_not_deleted() -> ColumnElement[bool]:
    """SQLAlchemy predicate: Invoice.deleted_at IS NULL."""
    return Invoice.deleted_at.is_(None)


def invoice_is_live() -> ColumnElement[bool]:
    """Gap 421: not deleted AND not superseded.

    Use this for anything that produces a **result** -- lists, dashboard
    aggregates, batch counts, trainer sample selection, rule-impact replay,
    and the chat agent's SQL. A superseded invoice carries data a human has
    already declared wrong and replaced, so letting it into a total, a vendor
    ranking or a chat answer is exactly the pollution the replace workflow
    exists to prevent.

    Use plain `invoice_not_deleted()` instead for **fetch-by-id** paths that
    must still be able to load a superseded invoice: `get_invoice`,
    `get_invoice_pdf`, and the revision-history view. That is how a user opens
    the previous, wrong version to see what was flagged on it -- widening this
    predicate to cover those call sites would make the history unreachable and
    silently defeat the feature.

    Deliberately a second function rather than widening `invoice_not_deleted()`
    in place: the one-line version would have been free but would have taken
    the fetch-by-id paths with it.
    """
    return and_(Invoice.deleted_at.is_(None), Invoice.superseded_at.is_(None))
