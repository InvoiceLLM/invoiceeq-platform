"""Tests for Feature 33 Task 33.3, 33.4, 33.5, 33.6 — ATLAS Analyst Agent Loop."""
from datetime import datetime, date
from uuid import uuid4
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from models import ChatAttachment, Fact, Invoice
from agents.analyst_agent import (
    AnalystScope,
    Budget,
    Observation,
    Plan,
    AnalystResult,
    run_analyst,
    observe,
    plan_by_rule,
    act,
    say,
    ask,
    learn,
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


def test_analyst_agent_attachment_scope_empty(test_db):
    tenant_id = uuid4()
    scope = AnalystScope(
        kind="attachment",
        tenant_id=str(tenant_id),
        clearance="ops",
    )
    result = run_analyst(scope, test_db)
    assert result is not None
    assert result.error is None
    assert result.empty_graph is True or len(result.cards) == 0


def test_analyst_agent_attachment_scope_with_doc(test_db):
    tenant_id = uuid4()
    att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="po_1041.pdf",
        blob_path="dummy.pdf",
        doc_type="PURCHASE_ORDER",
        doc_number="PO-1041",
        party_name="Rajesh Steel",
        grand_total=50000.0,
        currency="INR",
        extracted_json={
            "doc_type": "PURCHASE_ORDER",
            "doc_number": "PO-1041",
            "party_name": "Rajesh Steel",
            "grand_total": 50000.0,
            "currency": "INR",
        },
    )
    test_db.add(att)
    test_db.commit()

    scope = AnalystScope(
        kind="attachment",
        tenant_id=str(tenant_id),
        attachment_id=str(att.id),
        clearance="ops",
    )
    result = run_analyst(scope, test_db)
    assert result is not None
    assert result.error is None
    assert result.scope.kind == "attachment"


def test_analyst_agent_never_raises_on_corrupt_data(test_db):
    # Pass completely broken scope / types — run_analyst must catch and return result with error
    scope = AnalystScope(
        kind="tenant",
        tenant_id="not-a-valid-uuid-12345",
        clearance="ops",
    )
    result = run_analyst(scope, test_db)
    assert result is not None
    # Never raises to caller


def test_plan_by_rule():
    obs = Observation(
        scope=AnalystScope(kind="attachment", tenant_id="t1"),
        doc_type="PURCHASE_ORDER",
    )
    plan = plan_by_rule(obs, obs.scope)
    assert plan.source == "rule"
    assert len(plan.steps) > 0


def test_say_answer_contract_fallback():
    # say() returns gated narration
    scope = AnalystScope(kind="attachment", tenant_id="t1")
    narration = say([], scope)
    assert isinstance(narration, list)
