"""Tests for Feature 33 Tasks 33.28, 33.29, 33.31 — Tenant Routine Questionnaire."""
from uuid import uuid4
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from services.tenant_profile_rules import (
    ROUTINE_QUESTIONS,
    detect_routine_contradiction,
    next_routine_question,
    routine_answers,
    save_routine_answer,
)


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_six_routine_questions_defined():
    assert len(ROUTINE_QUESTIONS) == 6
    keys = [q.key for q in ROUTINE_QUESTIONS]
    assert keys == [
        "payment_run",
        "po_before_invoice",
        "invoice_approval",
        "month_close_day",
        "collections_owner",
        "approval_threshold",
    ]


def test_questionnaire_answering_and_progression(test_db):
    tenant_id = uuid4()

    # First question is payment_run
    q1 = next_routine_question(tenant_id, db_session=test_db)
    assert q1 is not None
    assert q1.key == "payment_run"

    # Answer q1
    save_routine_answer(tenant_id, "payment_run", "weekly_run", db_session=test_db)

    # Next question is po_before_invoice
    q2 = next_routine_question(tenant_id, db_session=test_db)
    assert q2 is not None
    assert q2.key == "po_before_invoice"

    # Answer remaining questions
    for q_key in ["po_before_invoice", "invoice_approval", "month_close_day", "collections_owner", "approval_threshold"]:
        save_routine_answer(tenant_id, q_key, "sample_val", db_session=test_db)

    # All answered -> None
    q_done = next_routine_question(tenant_id, db_session=test_db)
    assert q_done is None

    ans = routine_answers(tenant_id, db_session=test_db)
    assert len(ans) == 6
    assert ans["payment_run"] == "weekly_run"
