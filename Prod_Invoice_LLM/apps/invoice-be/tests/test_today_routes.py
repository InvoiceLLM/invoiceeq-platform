"""Tests for Feature 33 Tasks 33.17, 33.26, 33.29, 33.32, 33.37 — Today Routes."""
from datetime import datetime, date, timedelta
from uuid import UUID, uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from unittest.mock import patch, MagicMock

from routers.today import router as today_router
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import TodayItem, Invoice, ChatSession, TenantProfileRule, Fact


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


@pytest.fixture
def client(test_session):
    app = FastAPI()
    app.include_router(today_router)

    def override_get_db():
        return test_session

    tenant_id = uuid4()
    def override_tenant_context():
        return TenantContext(
            tenant_id=tenant_id,
            user_id="test_admin_user",
            role="Admin",
            clearance="exec",
            billing_plan="free",
            is_authenticated=True,
            can_edit=True,
            can_train=True,
        )

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    test_client = TestClient(app)
    yield test_client, test_session, tenant_id
    app.dependency_overrides.clear()


def test_get_today_pre_onboarding_state(client):
    c, session, tenant_id = client
    # Less than 10 documents -> returns pre_onboarding state
    resp = c.get("/today")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("state") == "pre_onboarding"
    assert data.get("docs_seen") == 0
    assert data.get("docs_required") == 10


def test_get_today_active_state(client):
    c, session, tenant_id = client
    # Seed 10 invoices so state flips to active
    today = date.today()
    for i in range(10):
        inv = Invoice(
            tenant_id=tenant_id,
            invoice_number=f"INV-PRE-{i}",
            vendor_name=f"Vendor-{i}",
            flow_direction="INBOUND",
            grand_total=1000.0,
            currency="INR",
            invoice_date=today,
            file_path="dummy.pdf",
        )
        session.add(inv)

    item = TodayItem(
        tenant_id=tenant_id,
        section="findings",
        clearance="exec",
        text="Price drift detected on Vendor-0",
        seeded_question="Why did Vendor-0 price increase?",
        severity=2,
    )
    session.add(item)
    session.commit()

    resp = c.get("/today")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("state") == "active"
    assert len(data.get("findings", [])) >= 1
    assert data["findings"][0]["text"] == "Price drift detected on Vendor-0"


def test_open_in_ask(client):
    c, session, tenant_id = client
    item = TodayItem(
        tenant_id=tenant_id,
        section="findings",
        text="Price drift detected",
        seeded_question="Why did price increase?",
        severity=2,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    resp = c.post(f"/today/{item.id}/open")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["seeded_question"] == "Why did price increase?"


def test_dismiss_item(client):
    c, session, tenant_id = client
    item = TodayItem(
        tenant_id=tenant_id,
        section="findings",
        text="Price drift detected",
        severity=2,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    resp = c.post(f"/today/{item.id}/dismiss")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # Item cleared_at is now set
    session.refresh(item)
    assert item.cleared_at is not None


def test_run_now_cooldown_rate_limit(client):
    c, session, tenant_id = client

    fake_redis = MagicMock()
    # First call: ttl is 0 (not in cooldown)
    fake_redis.ttl.return_value = 0

    with patch("routers.today.get_redis_client", return_value=fake_redis):
        resp1 = c.post("/today/run")
        assert resp1.status_code == 200
        assert resp1.json()["ok"] is True

        # Second call: inside cooldown window -> 429
        fake_redis.ttl.return_value = 450
        resp2 = c.post("/today/run")
        assert resp2.status_code == 429
        assert resp2.json()["retry_after_seconds"] == 450
