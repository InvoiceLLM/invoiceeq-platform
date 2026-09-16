"""Tests for GAP-01: Chat Session Clearance Filtering and Multi-Tenant Clearance Isolation."""
from datetime import datetime
from uuid import UUID, uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from routers.chat import router as chat_router
from dependencies import get_db_session, get_tenant_or_api_key_context, TenantContext
from models import ChatSession, ChatMessage


@pytest.fixture
def test_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def build_client(test_session, role="Admin", clearance="exec", tenant_id=None):
    app = FastAPI()
    app.include_router(chat_router)

    t_id = tenant_id or uuid4()
    context = TenantContext(
        tenant_id=t_id,
        user_id=f"test_{role.lower()}_user",
        role=role,
        clearance=clearance,
        billing_plan="active",
        can_train=(role in ("Admin", "Trainer")),
        can_audit=(role in ("Admin", "Auditor")),
        can_load=(role == "Admin"),
    )

    app.dependency_overrides[get_db_session] = lambda: test_session
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: context

    return TestClient(app), t_id, context


def test_session_create_clearance(test_session):
    admin_client, t_id, _ = build_client(test_session, role="Admin", clearance="exec")
    auditor_client, _, _ = build_client(test_session, role="Auditor", clearance="ops", tenant_id=t_id)

    # 1. Admin can create ops session
    res = admin_client.post("/chat/sessions", json={"title": "General Invoices", "clearance": "ops"})
    assert res.status_code == 201
    data = res.json()
    assert data["clearance"] == "ops"
    assert data["title"] == "General Invoices"

    # 2. Admin can create exec session
    res = admin_client.post("/chat/sessions", json={"title": "Executive Payroll & Cash", "clearance": "exec"})
    assert res.status_code == 201
    data = res.json()
    assert data["clearance"] == "exec"
    assert data["title"] == "Executive Payroll & Cash"

    # 3. Auditor cannot create exec session
    res = auditor_client.post("/chat/sessions", json={"title": "Unauthorized Exec", "clearance": "exec"})
    assert res.status_code == 403
    assert "Cannot create executive session" in res.json()["detail"]

    # 4. Auditor can create ops session
    res = auditor_client.post("/chat/sessions", json={"title": "Auditor Review", "clearance": "ops"})
    assert res.status_code == 201
    assert res.json()["clearance"] == "ops"


def test_session_list_clearance_filtering(test_session):
    admin_client, t_id, _ = build_client(test_session, role="Admin", clearance="exec")
    auditor_client, _, _ = build_client(test_session, role="Auditor", clearance="ops", tenant_id=t_id)

    # Seed 1 ops session and 1 exec session
    s_ops = ChatSession(id=uuid4(), tenant_id=t_id, title="Ops Session", clearance="ops")
    s_exec = ChatSession(id=uuid4(), tenant_id=t_id, title="Exec Private Session", clearance="exec")
    test_session.add(s_ops)
    test_session.add(s_exec)
    test_session.commit()

    # Admin should see BOTH sessions
    res_admin = admin_client.get("/chat/sessions")
    assert res_admin.status_code == 200
    admin_titles = [s["title"] for s in res_admin.json()]
    assert "Ops Session" in admin_titles
    assert "Exec Private Session" in admin_titles
    # Clearance field present
    for s in res_admin.json():
        assert "clearance" in s

    # Auditor should ONLY see ops session
    res_auditor = auditor_client.get("/chat/sessions")
    assert res_auditor.status_code == 200
    auditor_titles = [s["title"] for s in res_auditor.json()]
    assert "Ops Session" in auditor_titles
    assert "Exec Private Session" not in auditor_titles


def test_session_access_forbidden_for_ops_on_exec_session(test_session):
    admin_client, t_id, _ = build_client(test_session, role="Admin", clearance="exec")
    auditor_client, _, _ = build_client(test_session, role="Auditor", clearance="ops", tenant_id=t_id)

    # Create exec session
    s_exec = ChatSession(id=uuid4(), tenant_id=t_id, title="Private Executive Board", clearance="exec")
    test_session.add(s_exec)
    test_session.commit()

    # Auditor attempting to get messages -> 403
    res = auditor_client.get(f"/chat/sessions/{s_exec.id}")
    assert res.status_code == 403
    assert "executive clearance required" in res.json()["detail"].lower()

    # Auditor attempting to rename -> 403
    res = auditor_client.put(f"/chat/sessions/{s_exec.id}", json={"title": "Hacked Title"})
    assert res.status_code == 403
    assert "executive clearance required" in res.json()["detail"].lower()

    # Auditor attempting to delete -> 403
    res = auditor_client.delete(f"/chat/sessions/{s_exec.id}")
    assert res.status_code == 403
    assert "executive clearance required" in res.json()["detail"].lower()
