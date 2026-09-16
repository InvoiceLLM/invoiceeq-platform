"""Feature 33 Task 33.8 / FE Task 22.7 — The Facts Router.

WHAT THIS ROUTER PROVIDES
-------------------------
1. GET /facts (or /api/v1/facts):
   - Retrieve facts for an entity (e.g. invoice, vendor, counterparty) via `services.facts.facts_for()`.
   - Clearance-aware: clerks ('ops') see operational facts; executives ('exec') see both 'ops' and 'exec' facts.
   - Filterable by `subject_kind`, `subject_id`, `source_id`, `kind`, with limit/offset paging.

2. GET /facts/{fact_id}:
   - Retrieve a single Fact row by its UUID with clearance authorization.

3. GET /facts/documents/summary:
   - Aggregated ledger of attachments that left facts behind (for DocumentsTable in Task 22.7).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select, func

from dependencies import TenantContext, get_db_session, get_tenant_context
from models import Fact
from services.facts import facts_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/facts", tags=["facts"])


class FactResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    clearance: str
    kind: str
    subject_kind: str
    subject_id: str
    counterparty_id: Optional[str] = None
    as_of: Optional[date] = None
    figures: Optional[dict] = None
    source_kind: Optional[str] = None
    source_id: Optional[UUID] = None
    evidence: Optional[dict] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FactListResponse(BaseModel):
    ok: bool = True
    facts: List[FactResponse]
    count: int


@router.get("", response_model=FactListResponse, summary="Retrieve facts with clearance filtering")
def list_facts(
    subject_kind: Optional[str] = Query(None, description="Entity type: invoice, vendor, counterparty, etc."),
    subject_id: Optional[str] = Query(None, description="Entity identifier or UUID"),
    source_id: Optional[str] = Query(None, description="Source document/attachment UUID"),
    kind: Optional[str] = Query(None, description="Fact kind: commitment, delivery, payment, etc."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    t_uuid = UUID(str(context.tenant_id))
    clearance = context.clearance or "ops"

    # If subject_kind and subject_id are provided without source_id/kind filters, use facts_for()
    if subject_kind and subject_id and not source_id and not kind:
        raw_facts = facts_for(
            subject_kind=subject_kind,
            subject_id=subject_id,
            clearance=clearance,
            db_session=db,
            tenant_id=t_uuid,
        )
        paged = raw_facts[offset : offset + limit]
        return {
            "ok": True,
            "facts": [FactResponse.model_validate(f) for f in paged],
            "count": len(raw_facts),
        }

    # Otherwise build query
    stmt = select(Fact).where(Fact.tenant_id == t_uuid)
    if subject_kind:
        stmt = stmt.where(Fact.subject_kind == subject_kind)
    if subject_id:
        stmt = stmt.where(Fact.subject_id == subject_id)
    if source_id:
        try:
            s_uuid = UUID(source_id)
            stmt = stmt.where(Fact.source_id == s_uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid source_id UUID")
    if kind:
        stmt = stmt.where(Fact.kind == kind)

    # Clearance gate: ops sees ops; exec sees ops and exec
    if clearance != "exec":
        stmt = stmt.where(Fact.clearance == "ops")

    stmt = stmt.order_by(Fact.created_at.desc())
    all_rows = db.exec(stmt).all()
    paged_rows = all_rows[offset : offset + limit]

    return {
        "ok": True,
        "facts": [FactResponse.model_validate(f) for f in paged_rows],
        "count": len(all_rows),
    }


@router.get("/documents/summary", summary="Summary of documents that left facts")
def get_documents_with_facts(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    t_uuid = UUID(str(context.tenant_id))
    clearance = context.clearance or "ops"

    stmt = select(
        Fact.source_id,
        Fact.source_kind,
        func.count(Fact.id).label("facts_count"),
    ).where(Fact.tenant_id == t_uuid, Fact.source_id != None)

    if clearance != "exec":
        stmt = stmt.where(Fact.clearance == "ops")

    stmt = stmt.group_by(Fact.source_id, Fact.source_kind)
    rows = db.exec(stmt).all()
    return {
        "ok": True,
        "documents": [
            {
                "source_id": str(r[0]),
                "source_kind": r[1],
                "facts_count": r[2],
            }
            for r in rows
        ],
    }


@router.get("/{fact_id}", response_model=FactResponse, summary="Get single fact by ID")
def get_fact(
    fact_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> Fact:
    t_uuid = UUID(str(context.tenant_id))
    clearance = context.clearance or "ops"

    fact = db.exec(
        select(Fact).where(Fact.id == fact_id, Fact.tenant_id == t_uuid)
    ).first()
    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")

    if clearance != "exec" and fact.clearance != "ops":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Fact requires executive clearance",
        )

    return fact
