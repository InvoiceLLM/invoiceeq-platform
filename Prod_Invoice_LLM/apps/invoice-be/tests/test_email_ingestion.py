import pytest
from uuid import uuid4
from unittest.mock import patch, MagicMock
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant, TenantEmailSender, Invoice

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

GLOBAL_MAILBOX = "invoices@invoiceeq.app"


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(
            id=MOCK_TENANT_ID,
            name="Test Tenant",
            domain="test-tenant.com",
            billing_plan="free",
            free_invoices_remaining=10,
            send_invoices_enabled=True,
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


def test_mailbox_endpoint(db_session):
    res = client.get("/api/v1/email/settings/mailbox")
    assert res.status_code == 200
    data = res.json()
    assert data["mailbox"] == GLOBAL_MAILBOX
    assert data["domain"] == "invoiceeq.app"


def test_crud_authorized_sets(db_session):
    res = client.get("/api/v1/email/settings/email-senders")
    assert res.status_code == 200
    assert res.json() == []

    res = client.post(
        "/api/v1/email/settings/email-senders",
        json={"email": "ap@company.com", "email_set": "inbound"},
    )
    assert res.status_code == 201
    assert res.json()["email_set"] == "inbound"
    inbound_id = res.json()["id"]

    res = client.post(
        "/api/v1/email/settings/email-senders",
        json={"email": "ar@company.com", "email_set": "outbound"},
    )
    assert res.status_code == 201
    assert res.json()["email_set"] == "outbound"

    res = client.get("/api/v1/email/settings/email-senders?email_set=inbound")
    assert len(res.json()) == 1
    assert res.json()[0]["email"] == "ap@company.com"

    res = client.post(
        "/api/v1/email/settings/email-senders",
        json={"email": "ap@company.com", "email_set": "outbound"},
    )
    assert res.status_code == 400

    res = client.delete(f"/api/v1/email/settings/email-senders/{inbound_id}")
    assert res.status_code == 200


def test_webhook_unauthorized_sender(db_session):
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "vendor@partners.com"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "dropped"


@patch("routers.invoices.upload_pdf_to_blob_storage")
@patch("routers.invoices.QueueClient")
def test_webhook_inbound_ingestion(mock_qc, mock_storage, db_session):
    mock_storage.return_value = "mock/path/invoice.pdf"
    mock_qc.from_connection_string.return_value.send_message = MagicMock()

    sender = TenantEmailSender(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, email="allowed@partners.com", email_set="inbound"
    )
    db_session.add(sender)
    db_session.commit()

    res = client.post(
        "/api/v1/email/mailintegration",
        data={
            "to": f"InvoiceEQ <{GLOBAL_MAILBOX}>",
            "from": "allowed@partners.com",
        },
        files={"files": ("invoice.pdf", b"%PDF-1.4 stub content", "application/pdf")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "processed"
    assert data["flow_direction"] == "INBOUND"
    assert data["tenant_id"] == str(MOCK_TENANT_ID)
    assert len(data["job_ids"]) == 1

    invoices = db_session.exec(select(Invoice)).all()
    assert len(invoices) == 1
    assert invoices[0].status == "PROCESSING"
    assert "email" in invoices[0].tags


@patch("routers.email_ingestion.upload_pdf_to_blob_storage")
@patch("routers.email_ingestion.QueueClient")
def test_webhook_outbound_ingestion(mock_qc, mock_storage, db_session):
    mock_storage.return_value = "mock/path/out.pdf"
    mock_qc.from_connection_string.return_value.send_message = MagicMock()

    with patch("routers.email_ingestion.get_settings") as mock_settings:
        s = MagicMock()
        s.AZURE_STORAGE_CONNECTION_STRING = "UseDevelopmentStorage=true"
        s.EMAIL_APP_DOMAIN = "invoiceeq.app"
        s.EMAIL_APP_ADDRESS = GLOBAL_MAILBOX
        mock_settings.return_value = s

        sender = TenantEmailSender(
            id=uuid4(), tenant_id=MOCK_TENANT_ID, email="ar@company.com", email_set="outbound"
        )
        db_session.add(sender)
        db_session.commit()

        res = client.post(
            "/api/v1/email/mailintegration",
            data={
                "to": GLOBAL_MAILBOX,
                "from": "AR Desk <ar@company.com>",
            },
            files={"files": ("out.pdf", b"%PDF-1.4 stub", "application/pdf")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "processed"
        assert data["flow_direction"] == "OUTBOUND"

        invoices = db_session.exec(select(Invoice)).all()
        assert len(invoices) == 1
        assert invoices[0].flow_direction == "OUTBOUND"
        assert invoices[0].status == "UPLOADED"
