"""Tests for Feature 33 Task 33.11 — Clearance Enforcement on All Read Paths."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from dependencies import TenantContext
from models import ChatAttachment, ChatSession, Fact, Insight
from services.clearance import clearance_filter, clearance_for_role
from services.facts import facts_for
from services.insights import list_insights
from routers.chat_attachments import _require_owned_session, _require_owned_attachment


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_clearance_for_role_mapping():
    assert clearance_for_role("Admin") == "exec"
    assert clearance_for_role("admin") == "exec"
    assert clearance_for_role("Auditor") == "ops"
    assert clearance_for_role("Trainer") == "ops"
    assert clearance_for_role("Viewer") == "ops"
    assert clearance_for_role("") == "ops"


def test_session_read_path_clearance_gate(session: Session):
    tenant_id = uuid4()
    exec_session = ChatSession(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Exec Confidential Session",
        clearance="exec",
    )
    ops_session = ChatSession(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Ops Normal Session",
        clearance="ops",
    )
    session.add(exec_session)
    session.add(ops_session)
    session.commit()

    ops_context = TenantContext(
        tenant_id=tenant_id,
        user_id="user_ops",
        role="Auditor",
        billing_plan="pro",
        clearance="ops",
    )
    exec_context = TenantContext(
        tenant_id=tenant_id,
        user_id="user_admin",
        role="Admin",
        billing_plan="pro",
        clearance="exec",
    )

    # Ops context reading ops session -> OK
    res = _require_owned_session(ops_session.id, session, ops_context)
    assert res.id == ops_session.id

    # Ops context reading exec session -> 404
    with pytest.raises(HTTPException) as exc:
        _require_owned_session(exec_session.id, session, ops_context)
    assert exc.value.status_code == 404

    # Exec context reading exec session -> OK
    res_exec = _require_owned_session(exec_session.id, session, exec_context)
    assert res_exec.id == exec_session.id

    # Exec context reading ops session -> OK (Exec can read all)
    res_ops = _require_owned_session(ops_session.id, session, exec_context)
    assert res_ops.id == ops_session.id


def test_attachment_read_path_clearance_gate(session: Session):
    tenant_id = uuid4()
    session_id = uuid4()

    exec_att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=session_id,
        filename="bank_statement_aug.pdf",
        blob_path="/blobs/stmt.pdf",
        clearance="exec",
    )
    ops_att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=session_id,
        filename="po_101.pdf",
        blob_path="/blobs/po.pdf",
        clearance="ops",
    )
    session.add(exec_att)
    session.add(ops_att)
    session.commit()

    ops_context = TenantContext(
        tenant_id=tenant_id,
        user_id="user_ops",
        role="Auditor",
        billing_plan="pro",
        clearance="ops",
    )
    exec_context = TenantContext(
        tenant_id=tenant_id,
        user_id="user_admin",
        role="Admin",
        billing_plan="pro",
        clearance="exec",
    )

    # Ops reading ops attachment -> OK
    assert _require_owned_attachment(ops_att.id, session, ops_context).id == ops_att.id

    # Ops reading exec attachment -> 404
    with pytest.raises(HTTPException) as exc:
        _require_owned_attachment(exec_att.id, session, ops_context)
    assert exc.value.status_code == 404

    # Exec reading exec attachment -> OK
    assert _require_owned_attachment(exec_att.id, session, exec_context).id == exec_att.id


def test_insights_clearance_gate(session: Session):
    tenant_id = uuid4()
    att_id = uuid4()

    ops_insight = Insight(
        id=uuid4(),
        tenant_id=tenant_id,
        attachment_id=att_id,
        card="agreed_vs_billed",
        finding_key="f1",
        title="PO overbilled",
        clearance="ops",
    )
    exec_insight = Insight(
        id=uuid4(),
        tenant_id=tenant_id,
        attachment_id=att_id,
        card="cash_forecast",
        finding_key="f2",
        title="Cash Runway Deficit",
        clearance="exec",
    )
    session.add(ops_insight)
    session.add(exec_insight)
    session.commit()

    # Ops query only gets ops insights
    ops_results = list_insights(tenant_id, session, status=None, clearance="ops")
    assert len(ops_results) == 1
    assert ops_results[0].finding_key == "f1"

    # Exec query gets both
    exec_results = list_insights(tenant_id, session, status=None, clearance="exec")
    assert len(exec_results) == 2
