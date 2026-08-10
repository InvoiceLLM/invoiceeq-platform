"""Gap 125: staff notify helpers + confirm-send notify_emails validation."""
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, Tenant, TenantEmailSender
from services.staff_notify import (
    validate_notify_emails,
    notify_auditor_action,
    notify_processing_complete,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def _seed(db_session, *, emails: list[tuple[str, str]] | None = None):
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Workspace",
        domain="test.example.com",
        billing_plan="pro_combined",
        send_invoices_enabled=True,
    )
    db_session.add(tenant)
    for addr, email_set in (emails or [("ar@co.com", "outbound"), ("ap@co.com", "inbound")]):
        db_session.add(TenantEmailSender(
            id=uuid4(), tenant_id=MOCK_TENANT_ID, email=addr, email_set=email_set,
        ))
    db_session.commit()


def test_validate_notify_emails_rejects_unregistered(db_session):
    _seed(db_session)
    with pytest.raises(ValueError, match="Not allowed"):
        validate_notify_emails(
            db_session, tenant_id=MOCK_TENANT_ID, email_set="outbound",
            notify_emails=["ar@co.com", "customer@elsewhere.com"],
        )


def test_validate_notify_emails_accepts_subset(db_session):
    _seed(db_session)
    got = validate_notify_emails(
        db_session, tenant_id=MOCK_TENANT_ID, email_set="outbound",
        notify_emails=["AR@co.com"],
    )
    assert got == ["ar@co.com"]


def test_confirm_send_rejects_bad_notify_emails(db_session):
    _seed(db_session)
    inv = Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="x.pdf",
        flow_direction="OUTBOUND", status="VERIFIED",
    )
    db_session.add(inv)
    db_session.commit()

    res = client.put(
        f"/api/v1/outbound-invoices/{inv.id}/confirm-send",
        json={"notify_emails": ["not-on-set@co.com"]},
    )
    assert res.status_code == 400
    db_session.refresh(inv)
    assert inv.status == "VERIFIED"


def test_confirm_send_calls_staff_notify(db_session):
    _seed(db_session)
    inv = Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="x.pdf",
        flow_direction="OUTBOUND", status="VERIFIED", invoice_number="OUT-1",
    )
    db_session.add(inv)
    db_session.commit()

    with patch("routers.outbound_invoices.notify_auditor_action") as mock_notify:
        mock_notify.return_value = {"sent": True, "to": ["ar@co.com"]}
        res = client.put(
            f"/api/v1/outbound-invoices/{inv.id}/confirm-send",
            json={"notify_emails": ["ar@co.com"]},
        )
    assert res.status_code == 200
    assert res.json()["status"] == "SENT"
    assert res.json()["email_notify"]["sent"] is True
    mock_notify.assert_called_once()


def test_process_complete_uses_submitted_by(db_session):
    _seed(db_session)
    inv = Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="x.pdf",
        status="COMPLETED", invoice_number="IN-9",
        submitted_by_email="ap@co.com",
    )
    db_session.add(inv)
    db_session.commit()

    with patch("services.staff_notify.sendgrid_configured", return_value=True), \
         patch("services.staff_notify.send_email") as mock_send:
        mock_send.return_value = {"status_code": 202, "to": ["ap@co.com"]}
        result = notify_processing_complete(db_session, inv)
    assert result and result["sent"] is True
    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["to_addresses"] == ["ap@co.com"]


def test_auditor_notify_soft_skips_without_api_key(db_session):
    _seed(db_session)
    inv = Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="x.pdf",
        status="PAID", invoice_number="IN-1",
    )
    db_session.add(inv)
    db_session.commit()

    with patch("services.staff_notify.sendgrid_configured", return_value=False):
        result = notify_auditor_action(
            db_session, inv, action_label="Mark Paid", notify_emails=["ap@co.com"],
        )
    assert result == {"sent": False, "error": "SENDGRID_API_KEY is not configured.", "to": ["ap@co.com"]}
