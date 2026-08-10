"""
Tests for Feature 16: Settings — vendor-flow endpoints.
"""
import pytest
from uuid import uuid4
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant, TenantEmailSender

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


def _seed_tenant(db_session: Session, billing_plan: str = "free") -> Tenant:
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


def _add_outbound_email(db_session: Session, email: str = "ar@company.com") -> None:
    db_session.add(
        TenantEmailSender(
            id=uuid4(),
            tenant_id=MOCK_TENANT_ID,
            email=email,
            email_set="outbound",
        )
    )
    db_session.commit()


def test_get_returns_defaults(db_session):
    _seed_tenant(db_session)
    response = client.get("/api/v1/settings/vendor-flow")
    assert response.status_code == 200
    data = response.json()
    assert data["receive_invoices_enabled"] is True
    assert data["send_invoices_enabled"] is False
    assert data["outbound_authorized_count"] == 0


def test_put_admin_pro_combined_succeeds(db_session):
    _seed_tenant(db_session, billing_plan="pro_combined")
    _add_outbound_email(db_session)
    payload = {"send_invoices_enabled": True}
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["send_invoices_enabled"] is True
    assert data["outbound_authorized_count"] == 1


def test_put_non_admin_returns_403(db_session):
    _seed_tenant(db_session, billing_plan="pro_combined")
    _add_outbound_email(db_session)
    headers = {"Authorization": "Bearer test_viewer"}
    payload = {"send_invoices_enabled": True}
    response = client.put("/api/v1/settings/vendor-flow", json=payload, headers=headers)
    assert response.status_code == 403


def test_put_enable_send_without_outbound_set_returns_400(db_session):
    _seed_tenant(db_session, billing_plan="pro_combined")
    payload = {"send_invoices_enabled": True}
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 400
    assert "outbound authorized email" in response.json()["detail"].lower()


def test_put_enable_send_without_pro_combined_returns_402(db_session):
    _seed_tenant(db_session, billing_plan="pro")
    _add_outbound_email(db_session)
    payload = {"send_invoices_enabled": True}
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 402


def test_put_invalid_email_format_returns_400(db_session):
    _seed_tenant(db_session, billing_plan="pro_combined")
    _add_outbound_email(db_session)
    payload = {"outbound_sender_email": "not-an-email"}
    response = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert response.status_code == 400
    assert "valid email" in response.json()["detail"].lower()


def test_get_reflects_updated_values(db_session):
    _seed_tenant(db_session, billing_plan="pro_combined")
    _add_outbound_email(db_session)
    payload = {"send_invoices_enabled": True}
    put_resp = client.put("/api/v1/settings/vendor-flow", json=payload)
    assert put_resp.status_code == 200

    get_resp = client.get("/api/v1/settings/vendor-flow")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["send_invoices_enabled"] is True
    assert data["outbound_authorized_count"] == 1
