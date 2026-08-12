import pytest
from base64 import b64encode
from uuid import uuid4
from unittest.mock import patch, MagicMock
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant, TenantEmailSender, Invoice, DroppedInboundEmail
import services.inbound_mail_security as inbound_security

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

GLOBAL_MAILBOX = "invoices@invoiceeq.app"

# Gap 124 item 5: the mailintegration webhook now requires this shared secret on
# every POST. Tests drive it through the same three transports real traffic can
# use (header / query param / Basic-auth password) rather than reaching into the
# verification function, so the accept path being tested is the wire path.
TEST_INBOUND_SECRET = "test-inbound-shared-secret"
SECRET_HEADER = {"X-Inbound-Secret": TEST_INBOUND_SECRET}
# Big enough that the ordinary ingestion tests never trip the cap, small enough
# that the oversize tests don't have to push 25 MiB through TestClient.
TEST_MAX_BYTES = 4096


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


@pytest.fixture(autouse=True)
def inbound_secret_configured(monkeypatch):
    """Configure the Gap 124 shared secret + a small size cap for the suite.

    `services/inbound_mail_security.py` reads both values through
    `get_settings()`, which is `lru_cache`d at import time, so patching that one
    reference is what a test can actually control. Tests that need the
    *unconfigured* fail-closed path override it again locally.
    """
    settings_stub = MagicMock()
    settings_stub.INBOUND_PARSE_SHARED_SECRET = TEST_INBOUND_SECRET
    settings_stub.INBOUND_EMAIL_MAX_BYTES = TEST_MAX_BYTES
    monkeypatch.setattr(inbound_security, "get_settings", lambda: settings_stub)
    yield settings_stub


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
        headers=SECRET_HEADER,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "dropped"

    # Gap 124 item 6: the drop is recorded, not just logged.
    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert len(dropped) == 1
    assert dropped[0].reason == inbound_security.REASON_UNKNOWN_SENDER
    assert dropped[0].from_email == "vendor@partners.com"
    assert dropped[0].sender_domain == "partners.com"
    assert dropped[0].tenant_id is None


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
        # `attachment1` is the field name real SendGrid Inbound Parse uses; the
        # handler now collects file parts by type rather than by field name.
        files={"attachment1": ("invoice.pdf", b"%PDF-1.4 stub content", "application/pdf")},
        headers=SECRET_HEADER,
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
            headers=SECRET_HEADER,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "processed"
        assert data["flow_direction"] == "OUTBOUND"

        invoices = db_session.exec(select(Invoice)).all()
        assert len(invoices) == 1
        assert invoices[0].flow_direction == "OUTBOUND"
        assert invoices[0].status == "UPLOADED"


# ---------------------------------------------------------------------------
# Gap 124 items 5-7: authenticity, size cap, dropped-mail visibility
# ---------------------------------------------------------------------------


def _register_sender(db_session, email="allowed@partners.com", email_set="inbound"):
    sender = TenantEmailSender(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, email=email, email_set=email_set
    )
    db_session.add(sender)
    db_session.commit()
    return sender


def _multipart_body(boundary: str, fields: dict[str, str], attachment: tuple[str, bytes] | None):
    """Hand-rolled multipart body, so a request can be sent without a
    Content-Length header (see test_size_cap_rejects_body_with_no_content_length).
    """
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    if attachment:
        filename, payload = attachment
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="attachment1"; '
            f'filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
            + payload
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def test_webhook_rejects_request_with_no_secret(db_session):
    """No secret at all -> 401, and the attempt is recorded."""
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
    )
    assert res.status_code == 401

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert len(dropped) == 1
    assert dropped[0].reason == inbound_security.REASON_UNVERIFIED_SECRET


def test_webhook_rejects_wrong_secret(db_session):
    _register_sender(db_session)
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("invoice.pdf", b"%PDF-1.4 stub", "application/pdf")},
        headers={"X-Inbound-Secret": "not-the-right-secret"},
    )
    assert res.status_code == 401
    # A registered sender does NOT buy a pass — the secret is checked first and
    # the body is never parsed, so nothing was ingested.
    assert db_session.exec(select(Invoice)).all() == []

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_UNVERIFIED_SECRET]


def test_webhook_rejects_when_secret_is_unconfigured(db_session, monkeypatch):
    """Fail-closed: a deployment with no secret seeded accepts nothing.

    The reason is distinct from a wrong secret precisely because the operator
    action is different — seed the Key Vault value, not chase an intruder.
    """
    settings_stub = MagicMock()
    settings_stub.INBOUND_PARSE_SHARED_SECRET = ""
    settings_stub.INBOUND_EMAIL_MAX_BYTES = TEST_MAX_BYTES
    monkeypatch.setattr(inbound_security, "get_settings", lambda: settings_stub)

    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 401

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_SECRET_UNCONFIGURED]


@pytest.mark.parametrize(
    "request_kwargs",
    [
        pytest.param({"headers": SECRET_HEADER}, id="x-inbound-secret-header"),
        pytest.param(
            {"headers": {"X-Sendgrid-Inbound-Secret": TEST_INBOUND_SECRET}},
            id="x-sendgrid-inbound-secret-header",
        ),
        pytest.param({"params": {"key": TEST_INBOUND_SECRET}}, id="key-query-param"),
        pytest.param({"params": {"secret": TEST_INBOUND_SECRET}}, id="secret-query-param"),
        pytest.param(
            {
                "headers": {
                    "Authorization": "Basic "
                    + b64encode(f"sendgrid:{TEST_INBOUND_SECRET}".encode()).decode()
                }
            },
            id="basic-auth-password",
        ),
    ],
)
@patch("routers.invoices.upload_pdf_to_blob_storage")
@patch("routers.invoices.QueueClient")
def test_webhook_accepts_every_supported_secret_transport(
    mock_qc, mock_storage, db_session, request_kwargs
):
    """A correctly-presented secret is accepted through each transport.

    SendGrid Inbound Parse only lets you set a Destination URL, so the secret
    has to arrive as a query parameter or Basic credentials in that URL; the
    headers are what the invoice-website relay and our own tooling use.
    """
    mock_storage.return_value = "mock/path/invoice.pdf"
    mock_qc.from_connection_string.return_value.send_message = MagicMock()
    _register_sender(db_session)

    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("invoice.pdf", b"%PDF-1.4 stub", "application/pdf")},
        **request_kwargs,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "processed"
    assert db_session.exec(select(DroppedInboundEmail)).all() == []


def test_default_size_cap_is_25_mib():
    """Pin the real default — the suite runs against a lowered cap."""
    from config import Settings

    assert Settings.model_fields["INBOUND_EMAIL_MAX_BYTES"].default == 25 * 1024 * 1024


def test_size_cap_rejects_oversized_declared_body(db_session):
    """Rejected on the declared Content-Length, before the body is parsed."""
    _register_sender(db_session)
    oversized_pdf = b"%PDF-1.4 " + (b"x" * (TEST_MAX_BYTES + 512))

    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("big.pdf", oversized_pdf, "application/pdf")},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 413
    assert str(TEST_MAX_BYTES) in res.json()["detail"]
    assert db_session.exec(select(Invoice)).all() == []

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert len(dropped) == 1
    assert dropped[0].reason == inbound_security.REASON_OVERSIZED
    assert dropped[0].content_length > TEST_MAX_BYTES


def test_size_cap_rejects_body_with_no_content_length(db_session):
    """The second cap check: a chunked client declares no length at all.

    Streaming the body as an iterator makes httpx send
    `Transfer-Encoding: chunked` with no Content-Length, so guard 1 has nothing
    to inspect and the measured-attachment-bytes check is the one that fires.
    """
    _register_sender(db_session)
    boundary = "----gap124boundary"
    body = _multipart_body(
        boundary,
        {"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        ("big.pdf", b"%PDF-1.4 " + b"y" * (TEST_MAX_BYTES + 512)),
    )

    def chunks():
        yield body

    res = client.post(
        "/api/v1/email/mailintegration",
        content=chunks(),
        headers={
            **SECRET_HEADER,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    assert res.status_code == 413
    assert db_session.exec(select(Invoice)).all() == []

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_OVERSIZED]
    assert dropped[0].from_email == "allowed@partners.com"


def test_malformed_body_missing_from_is_recorded(db_session):
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 400

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_MALFORMED]
    assert dropped[0].to_email == GLOBAL_MAILBOX


def test_non_pdf_attachment_is_recorded_against_the_tenant(db_session):
    _register_sender(db_session)
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("notes.txt", b"just a note", "text/plain")},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "skipped"

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_NO_PDF_ATTACHMENT]
    # Sender was registered, so this drop is attributable to their workspace.
    assert dropped[0].tenant_id == MOCK_TENANT_ID


def test_free_quota_exhaustion_is_recorded(db_session):
    tenant = db_session.get(Tenant, MOCK_TENANT_ID)
    tenant.free_invoices_remaining = 0
    db_session.add(tenant)
    db_session.commit()
    _register_sender(db_session)

    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("invoice.pdf", b"%PDF-1.4 stub", "application/pdf")},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 200
    assert res.json()["job_ids"] == []

    dropped = db_session.exec(select(DroppedInboundEmail)).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_QUOTA_EXHAUSTED]
    assert dropped[0].filename == "invoice.pdf"
    assert dropped[0].tenant_id == MOCK_TENANT_ID


# --- Admin visibility -------------------------------------------------------


def test_admin_lists_attributed_and_domain_matched_drops(db_session):
    """The Admin console's read side of the dropped-mail record.

    Three rows, three outcomes: this tenant's own attributed drop is shown; an
    unattributed drop from a domain this workspace owns is shown but flagged as
    unattributed; an unattributed drop from an unrelated domain is not shown to
    this tenant at all.
    """
    _register_sender(db_session, email="ap@customer.example", email_set="inbound")

    inbound_security.record_dropped_email(
        db_session,
        reason=inbound_security.REASON_NO_PDF_ATTACHMENT,
        detail="no pdf",
        tenant_id=MOCK_TENANT_ID,
        from_email="ap@customer.example",
        to_email=GLOBAL_MAILBOX,
    )
    inbound_security.record_dropped_email(
        db_session,
        reason=inbound_security.REASON_UNKNOWN_SENDER,
        detail="unregistered colleague at the same company",
        from_email="finance@customer.example",
        to_email=GLOBAL_MAILBOX,
    )
    inbound_security.record_dropped_email(
        db_session,
        reason=inbound_security.REASON_UNKNOWN_SENDER,
        detail="nothing to do with this workspace",
        from_email="spam@somewhere-else.test",
        to_email=GLOBAL_MAILBOX,
    )

    res = client.get("/api/v1/admin/dropped-emails")
    assert res.status_code == 200
    rows = res.json()

    by_sender = {r["from_email"]: r for r in rows}
    assert set(by_sender) == {"ap@customer.example", "finance@customer.example"}
    assert by_sender["ap@customer.example"]["attributed"] is True
    assert by_sender["finance@customer.example"]["attributed"] is False


def test_admin_dropped_emails_requires_admin(db_session):
    """Same Admin-only boundary as the rest of routers/admin.py."""
    res = client.get(
        "/api/v1/admin/dropped-emails",
        headers={"Authorization": "Bearer test_viewer_token"},
    )
    assert res.status_code in (401, 403)
