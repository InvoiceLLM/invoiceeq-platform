import pytest
from uuid import uuid4, UUID
from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant, TenantEmailSender, Invoice

# Isolated in-memory database for testing
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

client = TestClient(app)

@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed default tenant
        tenant = Tenant(
            id=MOCK_TENANT_ID,
            name="Test Tenant",
            domain="test-tenant.com",
            billing_plan="free",
            free_invoices_remaining=10
        )
        session.add(tenant)
        session.commit()
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Allowed Senders Management (Task 14.3)
# ─────────────────────────────────────────────────────────────────────────────

def test_crud_allowed_senders(db_session):
    # 1. List senders (initially empty)
    res = client.get("/api/v1/email/settings/email-senders")
    assert res.status_code == 200
    assert len(res.json()) == 0

    # 2. Add sender email
    payload = {"email": "vendor@partners.com"}
    res = client.post("/api/v1/email/settings/email-senders", json=payload)
    assert res.status_code == 201
    added = res.json()
    assert added["email"] == "vendor@partners.com"
    sender_id = added["id"]

    # List senders again
    res = client.get("/api/v1/email/settings/email-senders")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["email"] == "vendor@partners.com"

    # Add duplicate email (expected to fail)
    res = client.post("/api/v1/email/settings/email-senders", json=payload)
    assert res.status_code == 400

    # 3. Delete sender email
    res = client.delete(f"/api/v1/email/settings/email-senders/{sender_id}")
    assert res.status_code == 200

    # List senders (should be empty again)
    res = client.get("/api/v1/email/settings/email-senders")
    assert res.status_code == 200
    assert len(res.json()) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Inbound Webhook Ingestion (Task 14.4)
# ─────────────────────────────────────────────────────────────────────────────

def test_webhook_invalid_alias(db_session):
    # Missing UUID alias
    res = client.post(
        "/api/v1/email/inbound",
        data={"to": "inbound-invoices@invoices.example.com", "from": "vendor@partners.com"}
    )
    assert res.status_code == 404

    # Invalid UUID alias
    res = client.post(
        "/api/v1/email/inbound",
        data={"to": "not-a-uuid@invoices.example.com", "from": "vendor@partners.com"}
    )
    assert res.status_code == 404


def test_webhook_unknown_tenant(db_session):
    random_uuid = str(uuid4())
    res = client.post(
        "/api/v1/email/inbound",
        data={"to": f"{random_uuid}@invoices.example.com", "from": "vendor@partners.com"}
    )
    assert res.status_code == 404


def test_webhook_unauthorized_sender(db_session):
    res = client.post(
        "/api/v1/email/inbound",
        data={"to": f"{MOCK_TENANT_ID}@invoices.example.com", "from": "vendor@partners.com"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "dropped"


@patch("routers.invoices.QueueClient")
def test_webhook_success_ingestion(mock_qc, db_session):
    mock_qc.from_connection_string.return_value.send_message = MagicMock()

    # 1. Add sender to allow-list
    sender = TenantEmailSender(id=uuid4(), tenant_id=MOCK_TENANT_ID, email="allowed@partners.com")
    db_session.add(sender)
    db_session.commit()

    # 2. Trigger webhook with PDF attachment
    res = client.post(
        "/api/v1/email/inbound",
        data={
            "to": f"Inbound Alias <{MOCK_TENANT_ID}@invoices.example.com>",
            "from": "allowed@partners.com"
        },
        files={"files": ("invoice.pdf", b"%PDF-1.4 stub content", "application/pdf")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "processed"
    assert len(data["job_ids"]) == 1

    # 3. Verify Database Entry
    invoices = db_session.exec(select(Invoice)).all()
    assert len(invoices) == 1
    assert invoices[0].status == "PROCESSING"
    assert "email" in invoices[0].tags
