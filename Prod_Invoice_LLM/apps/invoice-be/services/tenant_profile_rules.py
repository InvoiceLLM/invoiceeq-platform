"""Feature 33 Tasks 33.28, 33.29, 33.31 — Tenant Routine Questionnaire & Contradiction Detection.

WHAT THIS MODULE DOES
---------------------
1. Six Routine Questions (Task 33.28):
   - Defined once as `ROUTINE_QUESTIONS`.
   - Captured once during onboarding (Setup path or after first Discover).
   - Stored in `tenant_profile_rule` table with `source="atlas_onboarding"`.
   - Skips stored as `"skipped"`, never re-asked on a schedule.

2. Questionnaire Delivery (Task 33.29):
   - `next_routine_question(tenant_id, path, db_session)`
   - `save_routine_answer(tenant_id, key, value, source, db_session)`
   - `routine_answers(tenant_id, db_session)`

3. Contradiction Detection (Task 33.31):
   - `detect_routine_contradiction(tenant_id, db_session)` -> list of contradicted question keys.
   - Only data contradictions trigger re-asking (weekly cron never re-asks).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import UUID

from sqlmodel import Session, select
import sqlalchemy as sa

from models import TenantProfileRule, Fact, Invoice
from config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutineQuestion:
    """A single routine question asked to the business owner."""
    key: str
    prompt: str
    chips: tuple[str, ...] = field(default_factory=tuple)
    free_text: bool = True
    skippable: bool = True
    answer_kind: str = "text"  # "text" | "number" | "user" | "currency_amount"
    default_value: Optional[str] = None


ROUTINE_QUESTIONS: tuple[RoutineQuestion, ...] = (
    RoutineQuestion(
        key="payment_run",
        prompt="When do you normally pay your suppliers?",
        chips=("weekly_run", "on_due_date", "month_end", "when_cash_allows"),
        free_text=True,
        skippable=True,
        answer_kind="text",
    ),
    RoutineQuestion(
        key="po_before_invoice",
        prompt="Do you raise a purchase order before an invoice arrives?",
        chips=("always", "materials_only", "rarely"),
        free_text=True,
        skippable=True,
        answer_kind="text",
    ),
    RoutineQuestion(
        key="invoice_approval",
        prompt="Who approves an invoice for payment?",
        chips=("owner_only", "accounts_then_owner_above_threshold", "accounts_alone"),
        free_text=True,
        skippable=True,
        answer_kind="text",
    ),
    RoutineQuestion(
        key="month_close_day",
        prompt="Which day do you close the month on?",
        chips=("25", "28", "30", "31", "last_day"),
        free_text=True,
        skippable=True,
        answer_kind="number",
        default_value="30",
    ),
    RoutineQuestion(
        key="collections_owner",
        prompt="Who chases overdue customer payments?",
        chips=("accounts_team", "owner", "sales_rep"),
        free_text=True,
        skippable=True,
        answer_kind="user",
    ),
    RoutineQuestion(
        key="approval_threshold",
        prompt="Above what amount does an invoice need your sign-off?",
        chips=("50000", "100000", "250000", "500000"),
        free_text=True,
        skippable=True,
        answer_kind="currency_amount",
        default_value="100000",
    ),
)

QUESTIONS_BY_KEY: dict[str, RoutineQuestion] = {q.key: q for q in ROUTINE_QUESTIONS}


def save_routine_answer(
    tenant_id: Union[str, UUID],
    key: str,
    value: Any,
    source: str = "atlas_onboarding",
    db_session: Optional[Session] = None,
) -> Optional[TenantProfileRule]:
    """Save or update an answer to a routine question for a tenant."""
    if key not in QUESTIONS_BY_KEY:
        raise ValueError(f"Unknown routine question key: {key}")

    if db_session is None:
        return None

    t_uuid = UUID(str(tenant_id))
    val_str = str(value).strip()

    stmt = select(TenantProfileRule).where(
        TenantProfileRule.tenant_id == t_uuid,
        TenantProfileRule.key == key,
    )
    existing = db_session.exec(stmt).first()

    now = datetime.utcnow()
    if existing:
        existing.value = val_str
        existing.source = source
        existing.updated_at = now
        db_session.add(existing)
        rule = existing
    else:
        rule = TenantProfileRule(
            tenant_id=t_uuid,
            key=key,
            value=val_str,
            source=source,
            created_at=now,
            updated_at=now,
        )
        db_session.add(rule)

    db_session.commit()
    db_session.refresh(rule)
    return rule


def routine_answers(
    tenant_id: Union[str, UUID],
    db_session: Optional[Session] = None,
) -> dict[str, str]:
    """Return all answered routine questions for this tenant."""
    if db_session is None:
        return {}

    t_uuid = UUID(str(tenant_id))
    stmt = select(TenantProfileRule).where(TenantProfileRule.tenant_id == t_uuid)
    rows = db_session.exec(stmt).all()
    return {r.key: r.value for r in rows}


def next_routine_question(
    tenant_id: Union[str, UUID],
    path: str = "setup",
    db_session: Optional[Session] = None,
) -> Optional[RoutineQuestion]:
    """Return the next unanswered RoutineQuestion, or None if all are answered."""
    answered = routine_answers(tenant_id, db_session)
    for q in ROUTINE_QUESTIONS:
        if q.key not in answered:
            return q
    return None


def detect_routine_contradiction(
    tenant_id: Union[str, UUID],
    db_session: Optional[Session] = None,
) -> list[str]:
    """Detect discrepancies between answered questionnaire rules and observed data.

    Returns list of contradicted keys to be re-asked.
    """
    if db_session is None:
        return []

    t_uuid = UUID(str(tenant_id))
    answers = routine_answers(t_uuid, db_session)
    if not answers:
        return []

    contradictions: list[str] = []

    # 1. PO rule check: if answered "always" but >50% of invoices have no PO fact
    po_ans = answers.get("po_before_invoice")
    if po_ans == "always":
        invoices = db_session.exec(
            select(Invoice).where(
                Invoice.tenant_id == t_uuid,
                Invoice.deleted_at == None,  # noqa: E711
            ).limit(50)
        ).all()
        if len(invoices) >= 5:
            # Check facts for POs
            po_facts = db_session.exec(
                select(Fact).where(
                    Fact.tenant_id == t_uuid,
                    Fact.kind == "commitment",
                )
            ).all()
            if len(po_facts) < (len(invoices) * 0.4):
                contradictions.append("po_before_invoice")

    # 2. Payment run check: if answered "month_end" but payment dates in facts are scattered mid-month
    pay_ans = answers.get("payment_run")
    if pay_ans == "month_end":
        pay_facts = db_session.exec(
            select(Fact).where(
                Fact.tenant_id == t_uuid,
                Fact.kind == "payment_event",
            ).limit(30)
        ).all()
        if len(pay_facts) >= 5:
            mid_month_count = 0
            for f in pay_facts:
                if f.as_of and 5 <= f.as_of.day <= 24:
                    mid_month_count += 1
            if mid_month_count / len(pay_facts) > 0.6:
                contradictions.append("payment_run")

    return contradictions
