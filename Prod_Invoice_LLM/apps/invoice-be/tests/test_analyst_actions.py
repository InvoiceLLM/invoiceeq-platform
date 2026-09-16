"""Tests for Feature 33 Tasks 33.25, 33.26, 33.27 — Action Registry, Execution & Role Gating."""
from uuid import uuid4
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from models import ActionLog
from agents.capabilities import ACTIONS, role_allows
from services.action_log import execute_action, log_action, ActionPermissionError


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


def test_action_registry_defined():
    assert "setup_inbound_email" in ACTIONS
    assert "enable_auto_load_inbox" in ACTIONS
    assert "set_outbound_email_sender" in ACTIONS
    assert "hold_invoice" in ACTIONS
    assert "dismiss_finding" in ACTIONS
    assert "write_rule" in ACTIONS


def test_role_gating_permissions():
    # Admin allowed setup actions
    assert role_allows("setup_inbound_email", "Admin") is True
    # Auditor denied setup actions
    assert role_allows("setup_inbound_email", "Auditor") is False
    # Auditor allowed hold_invoice
    assert role_allows("hold_invoice", "Auditor") is True
    # Trainer allowed write_rule
    assert role_allows("write_rule", "Trainer") is True
    assert role_allows("write_rule", "Auditor") is False


def test_auditor_denied_setup_action_raises(test_db):
    tenant_id = uuid4()
    with pytest.raises(ActionPermissionError):
        execute_action(
            tenant_id=tenant_id,
            user_id="auditor_user",
            capability_name="setup_inbound_email",
            role="Auditor",
            db_session=test_db,
        )


def test_action_disabled_by_flag_raises(test_db):
    tenant_id = uuid4()
    # By default ENABLE_ANALYST_ACTIONS is False
    with pytest.raises(ActionPermissionError, match="disabled"):
        execute_action(
            tenant_id=tenant_id,
            user_id="admin_user",
            capability_name="setup_inbound_email",
            args={},
            role="Admin",
            db_session=test_db,
        )


def test_admin_executes_action_and_logs(test_db, monkeypatch):
    from config import Settings
    monkeypatch.setattr(
        "services.action_log.get_settings",
        lambda: Settings(ENABLE_ANALYST_ACTIONS=True),
    )
    tenant_id = uuid4()
    res = execute_action(
        tenant_id=tenant_id,
        user_id="admin_user",
        capability_name="setup_inbound_email",
        args={},
        role="Admin",
        db_session=test_db,
    )
    assert res.get("ok") is True

    # Verify action_log row written in same transaction
    logs = test_db.exec(
        select(ActionLog).where(
            ActionLog.tenant_id == tenant_id,
            ActionLog.capability == "setup_inbound_email",
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].outcome == "success"
    assert logs[0].user_id == "admin_user"
