"""Feature 25 / Gap 339: the `email_summary` output destination.

The properties these tests exist to hold:

  * the summary fires from **one** place, so a human clicking Approve in the web
    UI and an `actions`-scoped API key (Gap 335) calling the same PUT produce
    identical behaviour -- asserted by driving both credentials through the same
    endpoint against the same tenant and comparing the resulting send;
  * recipients come from the pre-registered `TenantEmailSender` allowlist and
    from nowhere else -- there is no way to make this email an arbitrary
    address;
  * an approval never fails because mail did: no sender rows, no SendGrid key,
    or a raising send all leave the invoice PAID and the request 200;
  * it fires on PAID only -- not on REJECTED, not on a plain alert dismissal;
  * the attachments carry their real content types, not the `application/pdf`
    `send_email()` used to hardcode.

Fake SendGrid, real Postgres. `services.workflow_outputs.send_email` is patched
throughout (there is no SendGrid account in CI, and asserting on the HTTP call
we would have made is the point). The trigger logic and the recipient-resolution
query are additionally exercised against **real Postgres** at the bottom of this
file, per CONVENTIONS.md hard rule 2 -- SQLite cannot stand in for the JSONB
`output_destinations` read that decides whether anything sends at all.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from main import app
from dependencies import (
    KEY_SCOPE_ACTIONS,
    MOCK_TENANT_ID,
    api_key_service_clerk_id,
    get_db_session,
)
from models import AuditLog, Invoice, Tenant, TenantEmailSender, TenantWorkflowConfig, User
from services.api_keys import generate_api_key, generate_salt, hash_api_key, key_prefix
from services.invoice_export import (
    CSV_COLUMNS,
    build_invoice_csv,
    build_invoice_json,
    build_invoice_summary,
    export_filenames,
)
from services.outbound_email import DEFAULT_ATTACHMENT_MIME_TYPE, EmailAttachment, send_email
from services.workflow_outputs import (
    CSV_MIME_TYPE,
    JSON_MIME_TYPE,
    deliver_email_summary,
    email_summary_recipients,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

RESOLVE_URL = "/api/v1/audit/resolve/{invoice_id}"


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


# --- seeding ---------------------------------------------------------------


LINE_ITEMS = [
    {"description": "Rack unit", "quantity": 2, "unit_price": 150.0, "amount": 300.0},
    {"description": "Install labour", "quantity": 5, "unit_price": 40.0, "amount": 200.0},
]


def _seed_tenant(session: Session, tenant_id=None) -> Tenant:
    tenant = Tenant(
        id=tenant_id or MOCK_TENANT_ID,
        name="Test Workspace",
        domain=f"test-{uuid4().hex[:8]}.example.com",
        billing_plan="pro",
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def _seed_sender(session: Session, email: str, tenant_id=None, email_set: str = "inbound"):
    session.add(TenantEmailSender(
        tenant_id=tenant_id or MOCK_TENANT_ID, email=email, email_set=email_set,
    ))
    session.commit()


def _seed_workflow(session: Session, destinations: list[str], tenant_id=None):
    session.add(TenantWorkflowConfig(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        input_channels=["email"],
        output_destinations=destinations,
        chat_access="dashboard",
    ))
    session.commit()


def _seed_invoice(session: Session, tenant_id=None, **overrides) -> Invoice:
    invoice = Invoice(
        id=overrides.pop("id", uuid4()),
        tenant_id=tenant_id or MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status=overrides.pop("status", "AUDIT_REQUIRED"),
        vendor_name=overrides.pop("vendor_name", "Northwind Supply"),
        invoice_number=overrides.pop("invoice_number", "INV-4471"),
        grand_total=overrides.pop("grand_total", 530.0),
        subtotal=overrides.pop("subtotal", 500.0),
        tax_amount=overrides.pop("tax_amount", 30.0),
        currency=overrides.pop("currency", "USD"),
        items=overrides.pop("items", list(LINE_ITEMS)),
        **overrides,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice


def _issue_actions_key(session: Session, tenant: Tenant) -> str:
    """Give the tenant an `actions`-scoped key, the credential Gap 335 built."""
    raw = generate_api_key()
    salt = generate_salt()
    tenant.api_key_hash = hash_api_key(raw, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw)
    tenant.api_key_scope = KEY_SCOPE_ACTIONS
    session.add(tenant)
    session.commit()
    return raw


# ===========================================================================
# 1. The CSV / JSON builders (services/invoice_export.py)
# ===========================================================================


def test_csv_has_a_header_and_one_row_per_line_item(db_session):
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session)

    rows = build_invoice_csv(invoice).strip().split("\n")
    assert rows[0] == ",".join(CSV_COLUMNS)
    assert len(rows) == 1 + len(LINE_ITEMS)
    assert "Rack unit" in rows[1]
    assert "Install labour" in rows[2]
    # The invoice-level fields repeat on every line -- that is what makes this a
    # single rectangular table rather than a two-section file.
    for row in rows[1:]:
        assert "INV-4471" in row
        assert "Northwind Supply" in row


def test_csv_with_no_line_items_still_has_one_data_row(db_session):
    """"No itemisation" and "the export broke" must not look the same."""
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session, items=[])

    rows = build_invoice_csv(invoice).strip().split("\n")
    assert len(rows) == 2
    assert "INV-4471" in rows[1]


def test_csv_uses_lf_line_endings_only(db_session):
    """csv's default terminator is \\r\\n; combined with text-mode writing that
    yields \\r\\r\\n, which mangles the attachment."""
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session)
    assert "\r" not in build_invoice_csv(invoice)


def test_json_carries_the_fields_and_the_nested_line_items(db_session):
    _seed_tenant(db_session)
    invoice = _seed_invoice(
        db_session,
        taxes=[{"tax_type": "Sales Tax", "rate_percent": 6.0, "amount": 30.0}],
    )

    data = json.loads(build_invoice_json(invoice))
    assert data["invoice_number"] == "INV-4471"
    assert data["vendor_name"] == "Northwind Supply"
    assert data["grand_total"] == 530.0
    assert data["tax_amount"] == 30.0
    assert data["status"] == "AUDIT_REQUIRED"
    # Nested, not flattened -- the machine form has no reason to repeat the
    # header on every line the way the CSV must.
    assert [i["description"] for i in data["line_items"]] == ["Rack unit", "Install labour"]
    assert data["taxes"] == [{"tax_type": "Sales Tax", "rate_percent": 6.0, "amount": 30.0}]


def test_summary_omits_internal_extraction_state(db_session):
    """file_path is an internal blob path and coordinates/field_confidence are
    extraction internals -- none belong in a file a recipient opens."""
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session)
    summary = build_invoice_summary(invoice)
    for leaked in ("file_path", "coordinates", "field_confidence", "source_document_json", "sa_alerts"):
        assert leaked not in summary


def test_builders_tolerate_a_non_dict_line_item(db_session):
    """`items` is a free-form JSON column, so it is not guaranteed to hold the
    extractor's shape. A weird row is kept, not dropped -- an attachment that
    silently omits a line is worse than one that shows an odd-looking line."""
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session, items=["just a string"])

    assert "just a string" in build_invoice_csv(invoice)
    assert json.loads(build_invoice_json(invoice))["line_items"][0]["description"] == "just a string"


def test_export_filenames_sanitize_a_vendor_controlled_invoice_number(db_session):
    """An invoice number is vendor text that reached us through OCR, and it is
    about to become a filename in someone's mail client."""
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session, invoice_number="../../etc/pa ss wd")

    csv_name, json_name = export_filenames(invoice)
    assert csv_name.endswith(".csv") and json_name.endswith(".json")
    for name in (csv_name, json_name):
        assert "/" not in name
        assert "." not in name.rsplit(".", 1)[0]
        assert " " not in name


def test_export_filenames_fall_back_to_the_invoice_id(db_session):
    _seed_tenant(db_session)
    invoice = _seed_invoice(db_session, invoice_number=None)
    csv_name, _ = export_filenames(invoice)
    assert str(invoice.id) in csv_name


# ===========================================================================
# 2. The MIME-type fix (services/outbound_email.py)
# ===========================================================================


def _fake_sendgrid_settings():
    return SimpleNamespace(
        SENDGRID_API_KEY="SG.fake",
        SENDGRID_FROM_EMAIL="invoices@example.com",
        SENDGRID_FROM_NAME="InvoiceEQ",
        EMAIL_APP_ADDRESS="",
        SENDGRID_SENDING_DOMAIN="example.com",
        EMAIL_APP_DOMAIN="example.com",
    )


def _capture_sendgrid_payload(**send_kwargs) -> dict:
    """Run the real send_email() with httpx stubbed, and return the JSON body it
    would have POSTed to SendGrid."""
    with patch("services.outbound_email.get_settings", _fake_sendgrid_settings), \
         patch("services.outbound_email.httpx.Client") as mock_client:
        post = mock_client.return_value.__enter__.return_value.post
        post.return_value = SimpleNamespace(status_code=202, text="")
        send_email(**send_kwargs)
    return post.call_args.kwargs["json"]


def test_send_email_no_longer_lies_about_the_attachment_type():
    """The bug: the content type was hardcoded to application/pdf, so a CSV or a
    JSON could not be attached honestly."""
    payload = _capture_sendgrid_payload(
        to_addresses=["ap@example.com"],
        subject="s",
        plain_body="b",
        attachments=[
            EmailAttachment("invoice_X.csv", b"a,b\n1,2\n", CSV_MIME_TYPE),
            EmailAttachment("invoice_X.json", b"{}", JSON_MIME_TYPE),
        ],
    )
    types = [a["type"] for a in payload["attachments"]]
    assert types == ["text/csv", "application/json"]
    assert [a["filename"] for a in payload["attachments"]] == [
        "invoice_X.csv", "invoice_X.json",
    ]
    assert "application/pdf" not in types


def test_send_email_single_attachment_still_defaults_to_pdf():
    """Backwards compatibility: the old two-argument form keeps the exact type
    the hardcoded value produced, so no existing caller changes behaviour."""
    payload = _capture_sendgrid_payload(
        to_addresses=["ap@example.com"],
        subject="s",
        plain_body="b",
        attachment_filename="doc.pdf",
        attachment_bytes=b"%PDF-1.4",
    )
    assert payload["attachments"][0]["type"] == DEFAULT_ATTACHMENT_MIME_TYPE == "application/pdf"


# ===========================================================================
# 3. Recipient resolution -- pre-registered addresses only
# ===========================================================================


def test_recipients_come_from_the_registered_sender_allowlist(db_session):
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_sender(db_session, "finance@acme.com")
    # A different set, and a different tenant, must not leak in.
    _seed_sender(db_session, "ar@acme.com", email_set="outbound")
    other = _seed_tenant(db_session, tenant_id=uuid4())
    _seed_sender(db_session, "someone@other.com", tenant_id=other.id)

    invoice = _seed_invoice(db_session)
    assert email_summary_recipients(db_session, invoice) == ["ap@acme.com", "finance@acme.com"]


def test_no_summary_when_the_destination_is_not_selected(db_session):
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["webhook"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.send_email") as mock_send:
        assert deliver_email_summary(db_session, invoice) is None
    mock_send.assert_not_called()


def test_no_summary_when_the_tenant_never_ran_the_wizard(db_session):
    """No TenantWorkflowConfig row is the normal state for most tenants."""
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.send_email") as mock_send:
        assert deliver_email_summary(db_session, invoice) is None
    mock_send.assert_not_called()


def test_selected_but_no_registered_sender_logs_and_skips(db_session):
    """Should be unreachable via the endpoint (PUT /settings/workflow refuses to
    store it), but the allowlist can be emptied *after* the destination was
    saved -- that must not start 500-ing every approval."""
    _seed_tenant(db_session)
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.send_email") as mock_send:
        result = deliver_email_summary(db_session, invoice)
    mock_send.assert_not_called()
    assert result == {"sent": False, "error": "No registered email sender for this workspace."}


def test_missing_sendgrid_key_soft_skips(db_session):
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.sendgrid_configured", return_value=False), \
         patch("services.workflow_outputs.send_email") as mock_send:
        result = deliver_email_summary(db_session, invoice)
    mock_send.assert_not_called()
    assert result["sent"] is False
    assert result["to"] == ["ap@acme.com"]


def test_a_raising_send_is_reported_never_propagated(db_session):
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email", side_effect=RuntimeError("SendGrid 503")):
        result = deliver_email_summary(db_session, invoice)
    assert result["sent"] is False
    assert "SendGrid 503" in result["error"]


def test_the_summary_email_carries_both_attachments_and_a_readable_body(db_session):
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary", "webhook"])
    invoice = _seed_invoice(db_session, status="PAID")

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email") as mock_send:
        mock_send.return_value = {"status_code": 202, "to": ["ap@acme.com"]}
        result = deliver_email_summary(db_session, invoice)

    assert result["sent"] is True
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to_addresses"] == ["ap@acme.com"]
    assert "INV-4471" in kwargs["subject"]

    body = kwargs["plain_body"]
    for expected in ("Northwind Supply", "INV-4471", "USD 530.0", "PAID"):
        assert expected in body

    csv_att, json_att = kwargs["attachments"]
    assert (csv_att.mime_type, json_att.mime_type) == (CSV_MIME_TYPE, JSON_MIME_TYPE)
    assert csv_att.filename.endswith(".csv") and json_att.filename.endswith(".json")
    assert b"Rack unit" in csv_att.content
    assert json.loads(json_att.content)["invoice_number"] == "INV-4471"


# ===========================================================================
# 4. The trigger -- one point, both credentials
# ===========================================================================


def _resolve(invoice_id, status_value="PAID", headers=None):
    return client.put(
        RESOLVE_URL.format(invoice_id=invoice_id),
        json={"status": status_value},
        headers=headers or {},
    )


def test_human_approve_sends_the_summary(db_session):
    """The web-UI path: mock auth resolves an Admin Clerk context."""
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email") as mock_send:
        mock_send.return_value = {"status_code": 202, "to": ["ap@acme.com"]}
        response = _resolve(invoice.id)

    assert response.status_code == 200, response.text
    assert response.json()["email_summary"]["sent"] is True
    mock_send.assert_called_once()
    db_session.refresh(invoice)
    assert invoice.status == "PAID"


def test_api_key_approve_sends_the_identical_summary(db_session):
    """The Gap 335 path: an `actions`-scoped key calling the same endpoint.

    Both credentials converge on resolve_audit_invoice(), so this asserts the
    *same* send -- same recipients, same subject, same two attachments -- rather
    than merely asserting that something was sent.
    """
    tenant = _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    raw_key = _issue_actions_key(db_session, tenant)

    human_invoice = _seed_invoice(db_session, invoice_number="INV-SAME")
    key_invoice = _seed_invoice(db_session, invoice_number="INV-SAME")

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email") as mock_send:
        mock_send.return_value = {"status_code": 202, "to": ["ap@acme.com"]}
        human = _resolve(human_invoice.id)
        via_key = _resolve(key_invoice.id, headers={"X-API-Key": raw_key})

    assert human.status_code == 200, human.text
    assert via_key.status_code == 200, via_key.text
    assert via_key.json()["email_summary"]["sent"] is True

    human_call, key_call = mock_send.call_args_list
    assert human_call.kwargs["to_addresses"] == key_call.kwargs["to_addresses"] == ["ap@acme.com"]
    assert human_call.kwargs["subject"] == key_call.kwargs["subject"]
    assert (
        [(a.filename, a.mime_type) for a in human_call.kwargs["attachments"]]
        == [(a.filename, a.mime_type) for a in key_call.kwargs["attachments"]]
    )

    db_session.refresh(key_invoice)
    assert key_invoice.status == "PAID"


def test_reject_does_not_send_a_summary(db_session):
    """A rejected invoice has no result worth exporting."""
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email") as mock_send:
        response = _resolve(invoice.id, status_value="REJECTED")

    assert response.status_code == 200
    assert response.json()["email_summary"] is None
    mock_send.assert_not_called()


def test_alert_dismissal_without_a_status_does_not_send_a_summary(db_session):
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session, sa_alerts=["Math mismatch"])

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email") as mock_send:
        response = client.put(
            RESOLVE_URL.format(invoice_id=invoice.id),
            json={"dismissed_alerts": ["Math mismatch"]},
        )

    assert response.status_code == 200
    assert response.json()["email_summary"] is None
    mock_send.assert_not_called()


def test_a_failing_send_never_fails_the_approval(db_session):
    """The status transition has already committed by the time mail is attempted.
    A mail outage must not turn a successful approval into a 500."""
    _seed_tenant(db_session)
    _seed_sender(db_session, "ap@acme.com")
    _seed_workflow(db_session, ["email_summary"])
    invoice = _seed_invoice(db_session)

    with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
         patch("services.workflow_outputs.send_email", side_effect=RuntimeError("boom")):
        response = _resolve(invoice.id)

    assert response.status_code == 200
    assert response.json()["email_summary"]["sent"] is False
    db_session.refresh(invoice)
    assert invoice.status == "PAID"


# ===========================================================================
# 5. Real Postgres checkpoint
#
# Everything above runs on the in-memory SQLite fixture. Per CONVENTIONS.md hard
# rule 2 that is not sufficient evidence on its own, and here it is specifically
# insufficient: `output_destinations` is JSONB on Postgres and plain JSON on
# SQLite, and it is the column that decides whether a summary sends at all. This
# mirrors the repo's existing `*_on_postgres` pattern (test_connectors.py,
# test_auth.py) -- skip cleanly if Postgres is unreachable, otherwise point the
# app's real dependency at a session bound to the real engine and drive the
# actual HTTP endpoint.
# ===========================================================================


def test_approve_sends_email_summary_on_postgres():
    """Both approval paths, against real Postgres, on rows this test creates and
    then deletes: the destination read, the recipient query and the trigger."""
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)

    # The human path is mock auth, which always resolves MOCK_TENANT_ID, so this
    # cannot run on a throwaway tenant id -- it has to borrow that one. Every
    # piece of pre-existing state it touches is captured first and restored in
    # the `finally`, and every row it creates is deleted there.
    tenant_id = MOCK_TENANT_ID
    created_invoice_ids: list = []
    sender = None
    config = None
    config_was_created = False
    previous_destinations = None
    service_user_existed = False
    with Session(pg_engine) as pg_session:
        def get_db_session_override():
            yield pg_session

        app.dependency_overrides[get_db_session] = get_db_session_override
        tenant = pg_session.get(Tenant, tenant_id)
        tenant_was_created = tenant is None
        previous_scope = tenant.api_key_scope if tenant else None
        previous_key = (
            (tenant.api_key_hash, tenant.api_key_salt, tenant.api_key_prefix)
            if tenant else None
        )
        service_user_existed = pg_session.exec(
            select(User).where(User.clerk_user_id == api_key_service_clerk_id(tenant_id))
        ).first() is not None
        try:
            if tenant is None:
                tenant = _seed_tenant(pg_session, tenant_id=tenant_id)

            address = f"gap339-{uuid4().hex[:8]}@example.com"
            sender = TenantEmailSender(
                tenant_id=tenant_id, email=address, email_set="inbound",
            )
            pg_session.add(sender)

            config = pg_session.exec(
                select(TenantWorkflowConfig).where(
                    TenantWorkflowConfig.tenant_id == tenant_id
                )
            ).first()
            config_was_created = config is None
            previous_destinations = list(config.output_destinations or []) if config else None
            if config is None:
                config = TenantWorkflowConfig(tenant_id=tenant_id)
            config.output_destinations = ["email_summary"]
            pg_session.add(config)

            raw_key = _issue_actions_key(pg_session, tenant)
            pg_session.commit()

            # The JSONB round-trip the SQLite fixture cannot prove.
            pg_session.refresh(config)
            assert config.output_destinations == ["email_summary"]

            human_invoice = _seed_invoice(pg_session, invoice_number="PG-HUMAN")
            key_invoice = _seed_invoice(pg_session, invoice_number="PG-KEY")
            created_invoice_ids = [human_invoice.id, key_invoice.id]

            with patch("services.workflow_outputs.sendgrid_configured", return_value=True), \
                 patch("services.workflow_outputs.send_email") as mock_send:
                mock_send.return_value = {"status_code": 202, "to": [address]}
                human = _resolve(human_invoice.id)
                via_key = _resolve(key_invoice.id, headers={"X-API-Key": raw_key})

            assert human.status_code == 200, human.text
            assert via_key.status_code == 200, via_key.text
            assert human.json()["email_summary"]["sent"] is True
            assert via_key.json()["email_summary"]["sent"] is True

            # The recipient really was resolved by querying Postgres, and it is
            # the registered address -- identical for both credential paths.
            human_call, key_call = mock_send.call_args_list
            assert human_call.kwargs["to_addresses"] == [address]
            assert key_call.kwargs["to_addresses"] == [address]
            assert [a.mime_type for a in key_call.kwargs["attachments"]] == [
                CSV_MIME_TYPE, JSON_MIME_TYPE,
            ]
            assert b"Rack unit" in key_call.kwargs["attachments"][0].content

            pg_session.refresh(human_invoice)
            pg_session.refresh(key_invoice)
            assert human_invoice.status == "PAID"
            assert key_invoice.status == "PAID"
        finally:
            app.dependency_overrides.clear()
            pg_session.rollback()
            # AuditLog rows first: resolve writes one per invoice, and they
            # outlive the invoice (invoice_id carries no FK).
            for invoice_id in created_invoice_ids:
                for log in pg_session.exec(
                    select(AuditLog).where(AuditLog.invoice_id == invoice_id)
                ).all():
                    pg_session.delete(log)
                row = pg_session.get(Invoice, invoice_id)
                if row:
                    pg_session.delete(row)
            if sender is not None:
                row = pg_session.get(TenantEmailSender, sender.id)
                if row:
                    pg_session.delete(row)
            if config is not None:
                row = pg_session.get(TenantWorkflowConfig, config.id)
                if row and config_was_created:
                    pg_session.delete(row)
                elif row:
                    row.output_destinations = previous_destinations
                    pg_session.add(row)
            pg_session.commit()
            # The actions-scoped key lazily created a synthetic service user
            # (Gap 335). Remove it only if this test is what brought it into
            # existence -- and only after its AuditLog rows are gone, since
            # actor_user_id is a real FK.
            if not service_user_existed:
                svc = pg_session.exec(
                    select(User).where(
                        User.clerk_user_id == api_key_service_clerk_id(tenant_id)
                    )
                ).first()
                if svc:
                    pg_session.delete(svc)
            if tenant is not None and not tenant_was_created:
                tenant.api_key_scope = previous_scope
                (tenant.api_key_hash, tenant.api_key_salt, tenant.api_key_prefix) = (
                    previous_key or (None, None, None)
                )
                pg_session.add(tenant)
            elif tenant is not None:
                row = pg_session.get(Tenant, tenant.id)
                if row:
                    pg_session.delete(row)
            pg_session.commit()
