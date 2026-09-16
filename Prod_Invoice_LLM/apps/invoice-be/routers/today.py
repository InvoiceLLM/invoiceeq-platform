"""Feature 33 Tasks 33.17, 33.26, 33.29, 33.32, 33.37 — Today Router.

WHAT THIS ROUTER PROVIDES
-------------------------
1. `GET /today` (Tasks 33.17, 33.37):
   - Pre-onboarding state when docs < ANALYST_ONBOARD_MIN_DOCS (default 10).
   - Ranked list for Today screen (cash position, findings, summary, input requests, proposals).
   - Clearance-aware: clerks see operational items, Admins see exec lines.

2. Interaction Routes (Tasks 33.17, 33.26):
   - `POST /today/{item_id}/open`: Creates/resumes Ask chat session with seeded question.
   - `POST /today/{item_id}/dismiss`: Dismisses line and feeds learn().
   - `POST /today/{item_id}/scenario`: Arithmetic scenario recomputation.
   - `POST /today/{item_id}/confirm`: Role-gated action execution with audit log.

3. Convention Decision Routes (Task 33.23):
   - `POST /today/{proposal_id}/accept`
   - `POST /today/{proposal_id}/reject`
   - `POST /today/{proposal_id}/edit`

4. Questionnaire Delivery Routes (Tasks 33.28, 33.29):
   - `GET /today/questionnaire`: Next unanswered routine question.
   - `POST /today/questionnaire/answer`: Submit answer or skip.
   - `GET /today/routine-answers`: List all routine answers.
   - `PATCH /today/routine-answers/{key}`: Edit a routine answer (Trainer surface).

5. Admin Run-Now (Task 33.32):
   - `POST /today/run`: Admin-only trigger with Redis-backed cooldown (429 rate limit).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from config import get_settings
from dependencies import TenantContext, get_db_session, get_tenant_context
from models import ChatSession, InputRequest, TodayItem, Invoice, ChatAttachment
from services.clearance import clearance_filter
from services.forecast import forecast, scenario
from services.tenant_profile_rules import (
    ROUTINE_QUESTIONS,
    QUESTIONS_BY_KEY,
    detect_routine_contradiction,
    next_routine_question,
    routine_answers,
    save_routine_answer,
)
from services.conventions import (
    ConventionProposal,
    accept_convention,
    propose_conventions,
    reject_convention,
)
from services.business_profile import profile_tenant
from services.action_log import execute_action, ActionPermissionError, ActionExecutionError
from services.chat_queue import get_redis_client
from queue_worker.analyst_handlers import enqueue_analyst_job
from agents.analyst_agent import learn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/today", tags=["today"])


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class ScenarioRequest(BaseModel):
    change: dict = Field(default_factory=dict)
    horizon_days: int = 90


class QuestionnaireAnswerRequest(BaseModel):
    key: str
    value: str
    path: str = "setup"


class RoutineAnswerUpdateRequest(BaseModel):
    value: str


class AcceptConventionRequest(BaseModel):
    rule_text: Optional[str] = None
    title: Optional[str] = None
    target: Optional[str] = "tenant_chat_rule"


class EditConventionRequest(BaseModel):
    rule_text: str
    target: str = "tenant_chat_rule"


# ---------------------------------------------------------------------------
# 1. GET /today (Tasks 33.17, 33.37)
# ---------------------------------------------------------------------------

@router.get("", summary="Get today items and status for the tenant")
def get_today(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    settings = get_settings()
    tenant_id = context.tenant_id
    t_uuid = UUID(str(tenant_id))
    clearance = context.clearance or "ops"
    role = context.role or "Auditor"

    # Pre-onboarding check: count completed docs
    inv_count = len(db.exec(
        select(Invoice.id).where(Invoice.tenant_id == t_uuid, Invoice.deleted_at == None)
    ).all())
    att_count = len(db.exec(
        select(ChatAttachment.id).where(ChatAttachment.tenant_id == t_uuid)
    ).all())
    total_docs = inv_count + att_count

    min_docs = getattr(settings, "ANALYST_ONBOARD_MIN_DOCS", 10)
    if total_docs < min_docs:
        return {
            "state": "pre_onboarding",
            "docs_seen": total_docs,
            "docs_required": min_docs,
        }

    # Fetch TodayItem rows
    stmt = select(TodayItem).where(
        TodayItem.tenant_id == t_uuid,
        TodayItem.cleared_at == None,  # noqa: E711
    )
    stmt = clearance_filter(stmt, TodayItem, clearance)
    stmt = stmt.order_by(TodayItem.severity.asc(), TodayItem.created_at.desc())
    items = db.exec(stmt).all()

    findings = [i for i in items if i.section == "findings"]
    summary = [i for i in items if i.section == "summary"]

    # Input Requests
    req_stmt = select(InputRequest).where(
        InputRequest.tenant_id == t_uuid,
        InputRequest.fulfilled_at == None,  # noqa: E711
    )
    req_stmt = clearance_filter(req_stmt, InputRequest, clearance)
    input_requests = db.exec(req_stmt).all()

    # Cash position line (forecast certain tier)
    fc = forecast(tenant_id, clearance=clearance, horizon_days=30, db_session=db)
    position_lines = [
        {"currency": curr, "text": fc.certain_summary.get(curr, ""), "position": fc.cash_position_by_currency.get(curr, 0.0)}
        for curr in fc.currencies
    ]

    # Proposals (Convention proposals)
    b_profile = profile_tenant(tenant_id, clearance=clearance, db_session=db)
    proposals = propose_conventions(b_profile, facts=[], db_session=db)

    # Next questionnaire question if any
    next_q = next_routine_question(tenant_id, db_session=db)

    return {
        "state": "active",
        "docs_seen": total_docs,
        "docs_required": min_docs,
        "position_lines": position_lines,
        "findings": [
            {
                "id": str(f.id),
                "section": f.section,
                "text": f.text,
                "seeded_question": f.seeded_question,
                "severity": f.severity,
                "meta": f.meta,
                "clearance": f.clearance,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in findings
        ],
        "summary": [
            {
                "id": str(s.id),
                "section": s.section,
                "text": s.text,
                "severity": s.severity,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in summary
        ],
        "input_requests": [
            {
                "id": str(r.id),
                "kind": r.kind,
                "phrase": r.phrase,
                "unlock_amount": r.unlock_amount,
                "unlock_currency": r.unlock_currency,
                "unlock_count": r.unlock_count,
            }
            for r in input_requests
        ],
        "proposals": [
            {
                "id": p.id,
                "kind": p.kind,
                "title": p.title,
                "description": p.description,
                "suggested_rule": p.suggested_rule,
                "evidence": p.evidence,
            }
            for p in proposals
        ],
        "next_question": (
            {
                "key": next_q.key,
                "prompt": next_q.prompt,
                "chips": list(next_q.chips),
                "free_text": next_q.free_text,
                "skippable": next_q.skippable,
                "answer_kind": next_q.answer_kind,
                "default_value": next_q.default_value,
            }
            if next_q
            else None
        ),
    }


# ---------------------------------------------------------------------------
# 2. Today Item Interactions (Tasks 33.17, 33.26)
# ---------------------------------------------------------------------------

@router.post("/{item_id}/open", summary="Open item in Ask / Chat session")
def open_in_ask(
    item_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    t_uuid = UUID(str(context.tenant_id))
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item_id UUID")

    item = db.exec(
        select(TodayItem).where(TodayItem.id == item_uuid, TodayItem.tenant_id == t_uuid)
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Today item not found")

    seeded_q = item.seeded_question or item.text or "Tell me more about this finding"
    now = datetime.utcnow()

    # Create a new chat session for this conversation
    session = ChatSession(
        tenant_id=t_uuid,
        user_id=context.user_id or "user",
        title=item.text[:60],
        clearance=context.clearance or "ops",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "session_id": str(session.id),
        "seeded_question": seeded_q,
        "item_id": item_id,
    }


@router.post("/{item_id}/dismiss", summary="Dismiss a Today line")
def dismiss_item(
    item_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    t_uuid = UUID(str(context.tenant_id))
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item_id UUID")

    item = db.exec(
        select(TodayItem).where(TodayItem.id == item_uuid, TodayItem.tenant_id == t_uuid)
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Today item not found")

    item.cleared_at = datetime.utcnow()
    db.add(item)
    db.commit()

    # Feed learn()
    try:
        learn(
            result=None,
            feedback={"action": "dismiss", "item_id": item_id, "tenant_id": str(t_uuid)},
            db_session=db,
        )
    except Exception as exc:
        logger.warning("dismiss_item: learn() call failed: %s", exc)

    return {"ok": True, "item_id": item_id, "dismissed": True}


@router.post("/{item_id}/scenario", summary="Run what-if scenario on forecast")
def run_scenario_route(
    item_id: str,
    req: ScenarioRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    fc = forecast(context.tenant_id, clearance=context.clearance, horizon_days=req.horizon_days, db_session=db)
    sc = scenario(fc, req.change)
    return {
        "ok": True,
        "currencies": sc.currencies,
        "cash_position_by_currency": sc.cash_position_by_currency,
        "runway_days_by_currency": sc.runway_days_by_currency,
        "certain_summary": sc.certain_summary,
        "tiers_summary": sc.tiers_summary,
    }


@router.post("/{item_id}/confirm", summary="Confirm and execute an action")
def confirm_action_route(
    item_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    settings = get_settings()
    if not getattr(settings, "ENABLE_ANALYST_ACTIONS", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst actions are currently disabled tenant-wide.",
        )

    t_uuid = UUID(str(context.tenant_id))
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item_id UUID")

    item = db.exec(
        select(TodayItem).where(TodayItem.id == item_uuid, TodayItem.tenant_id == t_uuid)
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Today item not found")

    meta = item.meta or {}
    cap_name = meta.get("action") or meta.get("capability") or "dismiss_finding"
    args = meta.get("args") or {}

    try:
        res = execute_action(
            tenant_id=t_uuid,
            user_id=context.user_id or "user",
            capability_name=cap_name,
            args=args,
            role=context.role or "Admin",
            db_session=db,
        )
        item.cleared_at = datetime.utcnow()
        db.add(item)
        db.commit()
        return {"ok": True, "result": res}
    except ActionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ActionExecutionError as ee:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(ee))


# ---------------------------------------------------------------------------
# 3. Convention Decisions (Task 33.23)
# ---------------------------------------------------------------------------

@router.post("/{proposal_id}/accept", summary="Accept a convention proposal")
def accept_convention_route(
    proposal_id: str,
    req: Optional[AcceptConventionRequest] = Body(None),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    rule_text = req.rule_text if req and req.rule_text else None
    title = req.title if req and req.title else None
    rule_target = req.target if req and req.target else "tenant_chat_rule"

    # If rule_text was not explicitly supplied, look up the proposal from ATLAS conventions
    if not rule_text:
        try:
            b_profile = profile_tenant(context.tenant_id, clearance=context.clearance, db_session=db)
            proposals = propose_conventions(b_profile, facts=[], db_session=db)
            matching_prop = next(
                (p for p in proposals if p.id == proposal_id or p.kind == proposal_id),
                None,
            )
            if matching_prop:
                rule_text = matching_prop.suggested_rule
                title = title or matching_prop.title
                rule_target = matching_prop.rule_target
        except Exception as exc:
            logger.warning("accept_convention_route: failed to query proposals: %s", exc)

    # Standard fallback definitions if proposal wasn't in the immediate profile snapshot
    if not rule_text:
        CONVENTION_DEFAULTS = {
            "auto_apply_credit_notes": (
                "Auto-apply Credit Notes to open invoices?",
                "When a credit note is received, apply it to reduce the balance of open matching invoices for that vendor.",
            ),
            "proforma_as_commitment": (
                "Treat Proforma Invoices as commitments?",
                "Treat proforma invoices from verified vendors as committed cashflow liabilities.",
            ),
            "default_terms": (
                "Default payment terms NET 30",
                "Default payment terms are NET 30 days unless explicitly stated otherwise on the invoice.",
            ),
        }
        for k, (def_title, def_rule) in CONVENTION_DEFAULTS.items():
            if k in proposal_id:
                title = title or def_title
                rule_text = def_rule
                break

    if not rule_text:
        title = title or f"Convention {proposal_id}"
        rule_text = f"Convention rule for {proposal_id}"

    res = accept_convention(
        tenant_id=context.tenant_id,
        proposal={
            "id": proposal_id,
            "kind": proposal_id,
            "title": title,
            "suggested_rule": rule_text,
            "rule_target": rule_target,
        },
        user_id=context.user_id or "user",
        db_session=db,
    )
    return res


@router.post("/{proposal_id}/reject", summary="Reject a convention proposal")
def reject_convention_route(
    proposal_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    res = reject_convention(
        tenant_id=context.tenant_id,
        proposal={"kind": proposal_id},
        db_session=db,
    )
    return res


@router.post("/{proposal_id}/edit", summary="Edit and accept a convention proposal")
def edit_convention_route(
    proposal_id: str,
    req: EditConventionRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    res = accept_convention(
        tenant_id=context.tenant_id,
        proposal={
            "kind": proposal_id,
            "suggested_rule": req.rule_text,
            "rule_target": req.target,
        },
        user_id=context.user_id or "user",
        db_session=db,
    )
    return res


# ---------------------------------------------------------------------------
# 4. Questionnaire Routes (Tasks 33.28, 33.29)
# ---------------------------------------------------------------------------

@router.get("/questionnaire", summary="Get next questionnaire question")
def get_questionnaire_question(
    path: str = Query("setup", description="setup or ingest"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    q = next_routine_question(context.tenant_id, path=path, db_session=db)
    if not q:
        return {"question": None, "completed": True}
    return {
        "completed": False,
        "question": {
            "key": q.key,
            "prompt": q.prompt,
            "chips": list(q.chips),
            "free_text": q.free_text,
            "skippable": q.skippable,
            "answer_kind": q.answer_kind,
            "default_value": q.default_value,
        },
    }


@router.post("/questionnaire/answer", summary="Submit answer to routine question")
def answer_questionnaire_question(
    req: QuestionnaireAnswerRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    rule = save_routine_answer(
        tenant_id=context.tenant_id,
        key=req.key,
        value=req.value,
        source=f"atlas_{req.path}",
        db_session=db,
    )
    next_q = next_routine_question(context.tenant_id, path=req.path, db_session=db)
    return {
        "ok": True,
        "saved_key": req.key,
        "has_next": next_q is not None,
        "next_question": (
            {
                "key": next_q.key,
                "prompt": next_q.prompt,
                "chips": list(next_q.chips),
                "free_text": next_q.free_text,
                "skippable": next_q.skippable,
                "answer_kind": next_q.answer_kind,
                "default_value": next_q.default_value,
            }
            if next_q
            else None
        ),
    }


@router.get("/routine-answers", summary="List all routine questionnaire answers")
def list_routine_answers(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    answers = routine_answers(context.tenant_id, db_session=db)
    contradictions = detect_routine_contradiction(context.tenant_id, db_session=db)
    return {
        "answers": answers,
        "contradictions": contradictions,
    }


@router.patch("/routine-answers/{key}", summary="Update a routine questionnaire answer (Trainer)")
def edit_routine_answer(
    key: str,
    req: RoutineAnswerUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    rule = save_routine_answer(
        tenant_id=context.tenant_id,
        key=key,
        value=req.value,
        source="trainer",
        db_session=db,
    )
    return {"ok": True, "key": key, "value": req.value}


# ---------------------------------------------------------------------------
# 5. Admin Run-Now (Task 33.32)
# ---------------------------------------------------------------------------

@router.post("/run", summary="Admin trigger to run analyst loop immediately")
def run_now(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> dict:
    # 1. Admin role gate
    if context.role != "Admin" and context.clearance != "exec":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admins can trigger an immediate ATLAS run",
        )

    settings = get_settings()
    cooldown_seconds = getattr(settings, "ANALYST_RUN_NOW_COOLDOWN_SECONDS", 600)
    tenant_id_str = str(context.tenant_id)
    cache_key = f"atlas_run_now_cooldown:{tenant_id_str}"

    r = get_redis_client()
    if r is not None:
        try:
            ttl = r.ttl(cache_key)
            if ttl and ttl > 0:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded. ATLAS run is cooling down.",
                        "retry_after_seconds": ttl,
                    },
                )
            r.set(cache_key, "1", ex=cooldown_seconds)
        except Exception as exc:
            logger.warning("run_now: Redis cooldown check failed: %s", exc)

    job_id = enqueue_analyst_job(
        tenant_id=tenant_id_str,
        clearance=context.clearance or "ops",
    )
    return {
        "ok": True,
        "job_id": job_id,
        "status": "enqueued",
        "cooldown_seconds": cooldown_seconds,
    }
