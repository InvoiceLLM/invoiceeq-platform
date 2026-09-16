"""Tests for Feature 33 Task 33.39 — Per-User Preference Store (/me/preferences)."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from fastapi import FastAPI
from dependencies import get_db_session, get_tenant_context_allow_unpaid, TenantContext
from routers import auth
from models import User, Tenant

app = FastAPI()
app.include_router(auth.router)


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


@pytest.fixture(name="client")
def client_fixture(session: Session):
    tenant = Tenant(
        id=uuid4(),
        name="Test Org",
        domain="testorg.com",
    )
    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="owner@testorg.com",
        role="Admin",
        clerk_user_id="user_clerk_123",
        ui_prefs=None,
    )
    session.add(tenant)
    session.add(user)
    session.commit()
    session.refresh(user)

    def override_get_db():
        yield session

    def override_get_context():
        return TenantContext(
            tenant_id=tenant.id,
            user_id="user_clerk_123",
            db_user_id=user.id,
            role="Admin",
            billing_plan="pro",
        )

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_tenant_context_allow_unpaid] = override_get_context

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_get_preferences_defaults(client: TestClient):
    response = client.get("/auth/me/preferences")
    assert response.status_code == 200
    data = response.json()
    assert data["layout"] == "surfaces"
    assert data["first_run_seen"] is False
    assert data["tour_seen"] is False
    assert data["questionnaire_progress"] is None


def test_patch_preferences_success(client: TestClient):
    patch_data = {
        "layout": "classic",
        "first_run_seen": True,
        "tour_seen": True,
        "questionnaire_progress": {"step": 2},
    }
    response = client.patch("/auth/me/preferences", json=patch_data)
    assert response.status_code == 200
    data = response.json()
    assert data["layout"] == "classic"
    assert data["first_run_seen"] is True
    assert data["tour_seen"] is True
    assert data["questionnaire_progress"] == {"step": 2}

    # Verify subsequent GET returns persisted values
    get_res = client.get("/auth/me/preferences")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["layout"] == "classic"
    assert get_data["first_run_seen"] is True


def test_patch_preferences_unknown_key_rejected(client: TestClient):
    patch_data = {
        "layout": "classic",
        "invalid_key_xyz": "value",
    }
    response = client.patch("/auth/me/preferences", json=patch_data)
    assert response.status_code == 400
    assert "Unknown preference keys" in response.json()["detail"]


def test_patch_preferences_invalid_payload(client: TestClient):
    response = client.patch("/auth/me/preferences", content="not a json object", headers={"Content-Type": "application/json"})
    assert response.status_code in (400, 422)
