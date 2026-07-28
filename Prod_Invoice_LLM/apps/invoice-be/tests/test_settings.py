"""
Tests for Feature 16: Settings — vendor-flow endpoints.

Coverage
--------
1. GET returns correct defaults for a fresh tenant.
2. PUT (Admin, pro_combined, valid email) → 200 and state persists.
3. PUT by non-Admin role → 403.
4. PUT enabling send without outbound_sender_email set → 400.
5. PUT enabling send without pro_combined plan → 402.
6. PUT with an invalid email format → 400.
7. GET after a successful PUT reflects updated values.
"""
import pytest
from uuid import uuid4
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant

# ---------------------------------------------------------------------------
# In-memory SQLite engine shared across the test module
# ---------------------------------------------------------------------------
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)


@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yield a clean isolated in-memory session per test."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Wire the test session into FastAPI's dependency injection."""
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_tenant(db_session: Session, billing_plan: str = "free") -> Tenant:
    """Insert the mock tenant with the given billing plan."""
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Workspace",
        domain="test.example.com",
        billing_plan=billing_plan,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_returns_defaults(db_session):
    """GET /settings/vendor-flow returns safe defaults for a fresh tenant."""
    _seed_tenant(db_session)
    response = client.get("/api/v1/settings/vendor-flow")
    assert response.status_code == 200
    data = response.json()
    assert data["receive_invoices_enabled"] is True
    assert data["send_invoices_enabled"] is False
    assert data["outbound_sender_email"] is None


def test_put_admin_pro_combined_succeeds(db_session):
    """Admin with pro_combined plan and valid sender email can enable outbound."""
    _seed_tenant(db_session, billing_plan="pro_combined")
    payload = {
        "send_invoices_enabled": True,
        "outbound_sender_email": "invoices@mycompany.com",
    }
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["send_invoices_enabled"] is True
    assert data["outbound_sender_email"] == "invoices@mycompany.com"


def test_put_non_admin_returns_403(db_session):
    """Viewer/Auditor role gets 403 Forbidden on PUT."""
    _seed_tenant(db_session, billing_plan="pro_combined")
    # The test-token protocol in dependencies.py: 'test_viewer' → role='Viewer'
    headers = {"Authorization": "Bearer test_viewer"}
    payload = {"send_invoices_enabled": True, "outbound_sender_email": "a@b.com"}
    response = client.put("/api/v1/settings/vendor-flow", json=payload, headers=headers)
    assert response.status_code == 403


def test_put_enable_send_without_email_returns_400(db_session):
    """Enabling send_invoices without an outbound_sender_email returns 400."""
    _seed_tenant(db_session, billing_plan="pro_combined")
    payload = {"send_invoices_enabled": True}
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 400
    assert "outbound_sender_email" in response.json()["detail"]


def test_put_enable_send_without_pro_combined_returns_402(db_session):
    """Enabling send_invoices without the pro_combined plan returns 402."""
    _seed_tenant(db_session, billing_plan="pro")
    payload = {
        "send_invoices_enabled": True,
        "outbound_sender_email": "invoices@mycompany.com",
    }
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 402
    assert "pro_combined" in response.json()["detail"].lower() or "Pro Combined" in response.json()["detail"]


def test_put_invalid_email_format_returns_400(db_session):
    """A malformed outbound_sender_email returns 400."""
    _seed_tenant(db_session, billing_plan="pro_combined")
    payload = {
        "send_invoices_enabled": True,
        "outbound_sender_email": "not-an-email",
    }
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 400
    assert "valid email" in response.json()["detail"].lower()


def test_get_reflects_updated_values(db_session):
    """After a successful PUT, GET returns the persisted values."""
    _seed_tenant(db_session, billing_plan="pro_combined")
    payload = {
        "send_invoices_enabled": True,
        "outbound_sender_email": "send@acme.io",
    }
    put_resp = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert put_resp.status_code == 200

    get_resp = client.get("/api/v1/settings/vendor-flow")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["send_invoices_enabled"] is True
    assert data["outbound_sender_email"] == "send@acme.io"
