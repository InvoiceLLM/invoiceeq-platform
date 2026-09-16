"""Tests for GAP-02: ENABLE_ANALYST_ACTIONS safety flag enforcement on confirm routes."""
from datetime import datetime
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool
from unittest.mock import patch

from routers.today import router as today_router
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import TodayItem, ActionLog
from config import Settings


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


def build_test_client(db_session, role="Admin", clearance="exec"):
    app = FastAPI()
    app.include_router(today_router)

    tenant_id = uuid4()

    def override_get_db():
        return db_session

    def override_tenant_context():
        return TenantContext(
            tenant_id=tenant_id,
            user_id="test_user_id",
            role=role,
            clearance=clearance,
            billing_plan="free",
            is_authenticated=True,
            can_edit=True,
            can_train=True,
        )

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    client = TestClient(app)
    return client, tenant_id


def test_confirm_action_forbidden_when_flag_disabled(test_db):
    client, tenant_id = build_test_client(test_db, role="Admin", clearance="exec")

    item = TodayItem(
        tenant_id=tenant_id,
        section="proposals",
        text="Setup inbound email address",
        meta={"action": "setup_inbound_email", "args": {}},
    )
    test_db.add(item)
    test_db.commit()
    test_db.refresh(item)

    # By default, ENABLE_ANALYST_ACTIONS is False
    with patch("routers.today.get_settings", return_value=Settings(ENABLE_ANALYST_ACTIONS=False)):
        resp = client.post(f"/today/{item.id}/confirm")

    assert resp.status_code == 403
    assert "Analyst actions are currently disabled" in resp.json()["detail"]

    # TodayItem should not be cleared
    test_db.refresh(item)
    assert item.cleared_at is None


def test_confirm_action_forbidden_for_auditor_when_flag_enabled(test_db):
    client, tenant_id = build_test_client(test_db, role="Auditor", clearance="ops")

    item = TodayItem(
        tenant_id=tenant_id,
        section="proposals",
        text="Setup inbound email address",
        meta={"action": "setup_inbound_email", "args": {}},
    )
    test_db.add(item)
    test_db.commit()
    test_db.refresh(item)

    # When flag is True, but user is Auditor for Admin-only action -> 403
    with patch("routers.today.get_settings", return_value=Settings(ENABLE_ANALYST_ACTIONS=True)):
        resp = client.post(f"/today/{item.id}/confirm")

    assert resp.status_code == 403
    assert "not permitted" in resp.json()["detail"]

    test_db.refresh(item)
    assert item.cleared_at is None


def test_confirm_action_succeeds_for_admin_when_flag_enabled(test_db):
    client, tenant_id = build_test_client(test_db, role="Admin", clearance="exec")

    item = TodayItem(
        tenant_id=tenant_id,
        section="proposals",
        text="Setup inbound email address",
        meta={"action": "setup_inbound_email", "args": {}},
    )
    test_db.add(item)
    test_db.commit()
    test_db.refresh(item)

    # With flag True and Admin role -> executes, clears item, writes ActionLog
    with patch("routers.today.get_settings", return_value=Settings(ENABLE_ANALYST_ACTIONS=True)), \
         patch("services.action_log.get_settings", return_value=Settings(ENABLE_ANALYST_ACTIONS=True)):
        resp = client.post(f"/today/{item.id}/confirm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["action"] == "setup_inbound_email"

    # TodayItem must be marked cleared
    test_db.refresh(item)
    assert item.cleared_at is not None

    # ActionLog must be recorded
    logs = test_db.exec(
        select(ActionLog).where(
            ActionLog.tenant_id == tenant_id,
            ActionLog.capability == "setup_inbound_email",
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].outcome == "success"
