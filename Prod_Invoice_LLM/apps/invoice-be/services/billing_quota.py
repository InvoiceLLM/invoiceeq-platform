"""Gap 189: free-tier upload quota — charge billable files only, under row lock.

Product doors (`POST /invoices/upload` and the directory watcher) must share this
logic so they cannot drift: classify hashes before charging, then
`SELECT … FOR UPDATE` the Tenant row and decrement only the billable count.
"""
from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session, select

from models import Invoice, Tenant


def count_billable_uploads(
    db_session: Session,
    tenant_id: UUID,
    file_payloads: list[bytes],
) -> int:
    """How many files in this batch would create a new (non-DUPLICATE) invoice.

    A file is billable when its SHA-256 is not already on any invoice for the
    tenant (including soft-deleted rows — same dedup rule as Gap 192) and is
    not a repeat of an earlier file in this same batch.
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
    tenant = db_session.exec(locked_tenant_select(tenant_id)).first()
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
