"""Gap 189: free-tier upload quota — charge billable files only, under row lock.

Every product door that can create an Invoice row must share this logic so they
cannot drift: classify hashes before charging, then `SELECT … FOR UPDATE` the
Tenant row and decrement only the billable count.

Gap 343 (2026-08-30): for two years that meant exactly the two doors in
`routers/invoices.py` (`upload_invoices` and `start_directory_watcher`), while
three others created invoices and charged nothing — the Google Drive connector
import, the scheduled Autopilot sync, and the outbound (AR) upload. The call
sites are now five:

  routers/invoices.py          -> upload_invoices(), start_directory_watcher()
  routers/connectors.py        -> trigger_file_import()          (flat 1/import)
  services/autopilot_sync.py   -> run_sync()                     (1 per new file)
  routers/outbound_invoices.py -> upload_outbound_invoice()

`charge_free_quota()` is the single definition of "what happens when the
allowance runs out" (402 "Limit reached", nothing ingested); a caller that
cannot return an HTTP status handles that exception rather than redefining the
rule — see services/autopilot_sync.py.
"""
from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session, select

from models import Document, Invoice, Tenant


def count_billable_uploads(
    db_session: Session,
    tenant_id: UUID,
    file_payloads: list[bytes],
) -> int:
    """How many files in this batch would create a new (non-DUPLICATE) row.

    A file is billable when its SHA-256 is not already on any invoice **or any
    document** for the tenant (including soft-deleted rows — same dedup rule as
    Gap 192) and is not a repeat of an earlier file in this same batch.

    Feature 27 (G14 / E10): the `Document` half is the one filter this feature
    **widens** rather than narrows, and it is easy to get backwards. Once a
    non-invoice document leaves `invoice` for `documents`, an `Invoice`-only
    dedup set stops recognising a re-uploaded delivery note as something the
    tenant has already paid for, and every re-upload is charged again. A
    non-invoice upload *is* billable on its first arrival — it consumed a real
    Document Intelligence page and a real extraction call — but exactly once.
    Gap 343 established that every door which creates a row shares this logic;
    the same rule applies to the new one.

    **The tenant predicate is inside each side of the union, never applied to a
    combined set** (§2A/A4/F2, from the security review of E10). An unscoped
    union does two bad things at once, and the second is worse than the first:
      1. A file two tenants happen to share — a common vendor's standard PO
         template — makes tenant B's genuine first upload look like a duplicate,
         so real DI + extraction spend goes unbilled.
      2. It turns the quota counter into a cross-tenant oracle. B can learn
         whether *anyone else* has uploaded a given file's bytes purely by
         watching whether its own `free_invoices_remaining` moves.
    Both `.where()` clauses below therefore carry `tenant_id == tenant_id`
    themselves, and the union happens only after each side is already scoped.
    """
    existing = {
        h
        for h in db_session.exec(
            select(Invoice.file_hash).where(
                Invoice.tenant_id == tenant_id,
                Invoice.file_hash.is_not(None),  # type: ignore[arg-type]
            )
        ).all()
        if h
    }
    existing |= {
        h
        for h in db_session.exec(
            select(Document.file_hash).where(
                Document.tenant_id == tenant_id,
                Document.file_hash.is_not(None),  # type: ignore[arg-type]
            )
        ).all()
        if h
    }
    seen_in_batch: set[str] = set()
    billable = 0
    for data in file_payloads:
        file_hash = hashlib.sha256(data).hexdigest()
        if file_hash in existing or file_hash in seen_in_batch:
            seen_in_batch.add(file_hash)
            continue
        seen_in_batch.add(file_hash)
        existing.add(file_hash)
        billable += 1
    return billable


def locked_tenant_select(tenant_id: UUID):
    """Statement used by charge_free_quota — exposed so tests can assert FOR UPDATE."""
    return select(Tenant).where(Tenant.id == tenant_id).with_for_update()


def charge_free_quota(
    db_session: Session,
    tenant_id: UUID,
    billable_count: int,
) -> Tenant:
    """Lock the tenant row; on free plan enforce + decrement by billable_count.

    Non-free plans: lock, return tenant, no decrement.
    billable_count <= 0: no decrement (all duplicates).
    """
    # Gap 343: `populate_existing=True` is load-bearing, not tidiness. Without it
    # SQLAlchemy returns an already-loaded Tenant straight from the identity map
    # and leaves its attributes as they were — so a caller that read the tenant
    # earlier in the same transaction would take the row lock and then evaluate
    # the check below against a stale `free_invoices_remaining`. The lock would
    # hold; the value it exists to protect would not. `routers/invoices.py` never
    # hit this (it loads no tenant before charging), but
    # `routers/outbound_invoices.py` loads the row up front for its
    # `send_invoices_enabled` check, which is exactly that shape. Fixed here
    # rather than at the call site so a sixth door cannot reintroduce it.
    # `locked_tenant_select()` itself is unchanged — the FOR UPDATE assertion in
    # tests/test_ingestion.py still guards it.
    tenant = db_session.exec(
        locked_tenant_select(tenant_id).execution_options(populate_existing=True)
    ).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )
    if tenant.billing_plan != "free" or billable_count <= 0:
        return tenant
    if tenant.free_invoices_remaining < billable_count:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Limit reached",
        )
    tenant.free_invoices_remaining -= billable_count
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant
