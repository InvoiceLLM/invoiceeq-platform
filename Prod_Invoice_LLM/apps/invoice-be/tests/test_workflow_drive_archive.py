"""Feature 25 / Gap 338: the `drive_archive` output destination.

The properties these tests exist to hold:

  * **the re-consent case is detected, not discovered at write time.** Every
    Google Drive connection made before 2026-08-30 consented to
    `drive.readonly`, and Google never widens an existing grant when the app
    starts asking for more. A read-only token must produce a named,
    actionable `reconnect_required` state -- at selection time (422) and at
    write time (a reported skip) -- never an opaque 403 buried in an approval;
  * an indeterminate scope probe is **not** treated as "no permission": if
    Google's tokeninfo endpoint cannot be reached the write is attempted
    anyway, and a real 403/401 from Drive is translated back into the same
    `reconnect_required` code;
  * the trigger is the same single point Gap 339 used, so a human approving in
    the web UI and an `actions`-scoped API key (Gap 335) calling the same PUT
    archive identically -- asserted by driving both and comparing the uploads;
  * an approval never fails because Drive did: no connection, a read-only
    grant, a missing source PDF or a raising upload all leave the invoice PAID
    and the request 200;
  * the CSV and JSON are the *same* builders the email summary uses -- there is
    no second serialiser.

Fake Drive, real Postgres. `utils/connector_files.py`'s upload/folder calls are
patched throughout (there is no Google account in this environment, and
asserting on the exact call that would have been made is the point). The
trigger and the JSONB destination read are additionally exercised against
**real Postgres** at the bottom of this file, per CONVENTIONS.md hard rule 2.
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
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
from models import AuditLog, Invoice, Tenant, TenantConnection, TenantWorkflowConfig, User
from services.api_keys import generate_api_key, generate_salt, hash_api_key, key_prefix
from services.invoice_export import export_filenames, export_pdf_filename
from services.workflow_outputs import (
    CSV_MIME_TYPE,
    DRIVE_ARCHIVE_FOLDER_NAME,
    DRIVE_NOT_CONNECTED,
    DRIVE_OAUTH_NOT_CONFIGURED,
    DRIVE_OK,
    DRIVE_RECONNECT_REQUIRED,
    DRIVE_SCOPE_UNKNOWN,
    DRIVE_TOKEN_UNUSABLE,
    JSON_MIME_TYPE,
    PDF_MIME_TYPE,
    deliver_drive_archive,
    drive_archive_readiness,
)
from utils.connector_oauth import (
    GOOGLE_DRIVE_FILE_SCOPE,
    GOOGLE_DRIVE_FULL_SCOPE,
    GOOGLE_DRIVE_OAUTH_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    google_granted_scopes,
    token_has_drive_write_scope,
)
from utils.encryption import encrypt_token

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

RESOLVE_URL = "/api/v1/audit/resolve/{invoice_id}"

FAKE_PDF = b"%PDF-1.4 fake source document"


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


def _seed_drive_connection(
    session: Session,
    tenant_id=None,
    status: str = "active",
    expired: bool = False,
    refresh: bool = True,
) -> TenantConnection:
    connection = TenantConnection(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("drive-access-token"),
        encrypted_refresh_token=encrypt_token("drive-refresh-token") if refresh else None,
        token_expiry=datetime.utcnow() + (timedelta(hours=-1) if expired else timedelta(hours=1)),
        status=status,
    )
    session.add(connection)
    session.commit()
    session.refresh(connection)
    return connection


def _seed_workflow(session: Session, destinations: list[str], tenant_id=None):
    session.add(TenantWorkflowConfig(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        input_channels=["drive"],
        output_destinations=destinations,
        chat_access="dashboard",
    ))
    session.commit()


def _seed_invoice(session: Session, tenant_id=None, **overrides) -> Invoice:
    invoice = Invoice(
        id=overrides.pop("id", uuid4()),
        tenant_id=tenant_id or MOCK_TENANT_ID,
        file_path=overrides.pop("file_path", "mock/invoice.pdf"),
        status=overrides.pop("status", "AUDIT_REQUIRED"),
        vendor_name=overrides.pop("vendor_name", "Northwind Supply"),
        invoice_number=overrides.pop("invoice_number", "INV-4471"),
        grand_total=overrides.pop("grand_total", 530.0),
        currency=overrides.pop("currency", "USD"),
        items=overrides.pop("items", list(LINE_ITEMS)),
        **overrides,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice


def _issue_actions_key(session: Session, tenant: Tenant) -> str:
    raw = generate_api_key()
    salt = generate_salt()
    tenant.api_key_hash = hash_api_key(raw, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw)
    tenant.api_key_scope = KEY_SCOPE_ACTIONS
    session.add(tenant)
    session.commit()
    return raw


def _drive_patches(write_scope=True, folder_id="folder-abc"):
    """The four seams between this feature and Google.

    `has_real_credentials` is patched True because a deployment without a
    Google OAuth app short-circuits before any of this runs (and the local .env
    happens to carry a real client id, so leaving it unpatched would make the
    tests depend on that file).
    """
    return (
        patch("services.workflow_outputs.has_real_credentials", return_value=True),
        patch("services.workflow_outputs.token_has_drive_write_scope", return_value=write_scope),
        patch("services.workflow_outputs.find_or_create_google_drive_folder", return_value=folder_id),
        patch("services.workflow_outputs.upload_google_drive_file"),
        patch("services.workflow_outputs.download_pdf_from_storage", return_value=FAKE_PDF),
    )


# ===========================================================================
# 1. The scope probe -- utils/connector_oauth.py
# ===========================================================================


def _tokeninfo_response(status_code=200, scope=None, json_error=False):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = "body"

        def json(self):
            if json_error:
                raise ValueError("not json")
            return {"scope": scope} if scope is not None else {}

    return _Resp()


def test_granted_scopes_are_parsed_from_googles_space_separated_list():
    with patch(
        "utils.connector_oauth.httpx.get",
        return_value=_tokeninfo_response(scope=GOOGLE_DRIVE_OAUTH_SCOPE),
    ):
        assert google_granted_scopes("tok") == {
            GOOGLE_DRIVE_READONLY_SCOPE, GOOGLE_DRIVE_FILE_SCOPE,
        }


@pytest.mark.parametrize(
    "scope,expected",
    [
        (GOOGLE_DRIVE_READONLY_SCOPE, False),
        (GOOGLE_DRIVE_OAUTH_SCOPE, True),
        (GOOGLE_DRIVE_FILE_SCOPE, True),
        # The bare `drive` scope is a superset -- this app never asks for it,
        # but a token that already carries it can write.
        (GOOGLE_DRIVE_FULL_SCOPE, True),
    ],
)
def test_write_scope_detection(scope, expected):
    """The whole migration turns on this: a readonly grant cannot write."""
    with patch("utils.connector_oauth.httpx.get", return_value=_tokeninfo_response(scope=scope)):
        assert token_has_drive_write_scope("tok") is expected


def test_an_invalid_token_reports_no_scopes_rather_than_unknown():
    """Google answers 400 for an expired/revoked token. That token definitely
    cannot write, so it is a definite False, not an indeterminate None."""
    with patch("utils.connector_oauth.httpx.get", return_value=_tokeninfo_response(status_code=400)):
        assert google_granted_scopes("tok") == set()
        assert token_has_drive_write_scope("tok") is False


def test_an_unreachable_tokeninfo_endpoint_is_unknown_not_denied():
    """`None` must never collapse into `False` -- see drive_archive_readiness."""
    with patch("utils.connector_oauth.httpx.get", side_effect=httpx.ConnectError("down")):
        assert google_granted_scopes("tok") is None
        assert token_has_drive_write_scope("tok") is None


def test_a_non_json_or_unexpected_tokeninfo_answer_is_unknown():
    with patch("utils.connector_oauth.httpx.get", return_value=_tokeninfo_response(json_error=True)):
        assert google_granted_scopes("tok") is None
    with patch("utils.connector_oauth.httpx.get", return_value=_tokeninfo_response(status_code=500)):
        assert google_granted_scopes("tok") is None


def test_the_authorize_url_asks_for_read_and_write():
    """drive.file alone cannot read the tenant's existing PDFs (Features 9/13),
    and drive.readonly alone cannot write. The connection needs both -- and it
    must not be the bare `drive` scope, which grants the whole Drive."""
    assert GOOGLE_DRIVE_READONLY_SCOPE in GOOGLE_DRIVE_OAUTH_SCOPE
    assert GOOGLE_DRIVE_FILE_SCOPE in GOOGLE_DRIVE_OAUTH_SCOPE
    assert f"{GOOGLE_DRIVE_FULL_SCOPE} " not in f"{GOOGLE_DRIVE_OAUTH_SCOPE} "

    with patch("routers.connectors._has_real_credentials", return_value=True), \
         patch("routers.connectors.get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(
            GOOGLE_CLIENT_ID="real-client-id",
            GOOGLE_CLIENT_SECRET="secret",
            GOOGLE_REDIRECT_URI="https://example.com/cb",
            FRONTEND_URL="https://example.com",
        )
        response = client.get("/api/v1/connectors/auth-url/google_drive")

    assert response.status_code == 200, response.text
    url = response.json()["auth_url"]
    assert "drive.readonly" in url
    assert "drive.file" in url


# ===========================================================================
# 2. Readiness -- the re-consent detector
# ===========================================================================


def test_no_connection_is_not_connected(db_session):
    _seed_tenant(db_session)
    readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["ready"] is False
    assert readiness["code"] == DRIVE_NOT_CONNECTED


def test_a_disconnected_row_does_not_count_as_connected(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session, status="revoked")
    readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["code"] == DRIVE_NOT_CONNECTED


def test_a_deployment_without_a_google_app_says_so(db_session):
    """The mock OAuth exchange stores a `mock_access_token_...` string; probing
    or uploading with it would produce a confusing 401 from Google."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    with patch("services.workflow_outputs.has_real_credentials", return_value=False):
        readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["ready"] is False
    assert readiness["code"] == DRIVE_OAUTH_NOT_CONFIGURED


def test_a_readonly_grant_is_reconnect_required(db_session):
    """THE migration case: connected before 2026-08-30, so the token carries
    drive.readonly and nothing else. Google will not widen it silently."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    with patch("services.workflow_outputs.has_real_credentials", return_value=True), \
         patch("services.workflow_outputs.token_has_drive_write_scope", return_value=False):
        readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["ready"] is False
    assert readiness["code"] == DRIVE_RECONNECT_REQUIRED
    assert "Reconnect Google Drive" in readiness["detail"]


def test_an_undetermined_scope_fails_open(db_session):
    """A blip on Google's tokeninfo endpoint must not block a tenant's config;
    the write is attempted and a real 403 is what settles it."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    with patch("services.workflow_outputs.has_real_credentials", return_value=True), \
         patch("services.workflow_outputs.token_has_drive_write_scope", return_value=None):
        readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["ready"] is True
    assert readiness["code"] == DRIVE_SCOPE_UNKNOWN


def test_a_write_scoped_connection_is_ok(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    with patch("services.workflow_outputs.has_real_credentials", return_value=True), \
         patch("services.workflow_outputs.token_has_drive_write_scope", return_value=True):
        readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["ready"] is True
    assert readiness["code"] == DRIVE_OK
    assert readiness["access_token"] == "drive-access-token"


def test_an_expired_token_with_no_refresh_token_is_unusable(db_session):
    """get_valid_access_token() raises for exactly this; it must surface as a
    reconnect state, not as a 500 inside an approval."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session, expired=True, refresh=False)
    with patch("services.workflow_outputs.has_real_credentials", return_value=True):
        readiness = drive_archive_readiness(db_session, MOCK_TENANT_ID)
    assert readiness["ready"] is False
    assert readiness["code"] == DRIVE_TOKEN_UNUSABLE
    assert "reconnect" in readiness["detail"].lower()


# ===========================================================================
# 3. Delivery
# ===========================================================================


def test_no_archive_when_the_destination_is_not_selected(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["webhook"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf:
        assert deliver_drive_archive(db_session, invoice) is None
    mock_upload.assert_not_called()


def test_no_archive_when_the_tenant_never_ran_the_wizard(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf:
        assert deliver_drive_archive(db_session, invoice) is None
    mock_upload.assert_not_called()


def test_selected_but_readonly_grant_logs_and_skips(db_session):
    """Reachable after the fact: the tenant can revoke the grant on Google's
    side at any time after saving the destination. It must not 500 an approval,
    and the reported code has to be the actionable one."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches(write_scope=False)
    with creds, scope, folder, upload as mock_upload, pdf:
        result = deliver_drive_archive(db_session, invoice)
    mock_upload.assert_not_called()
    assert result["uploaded"] is False
    assert result["code"] == DRIVE_RECONNECT_REQUIRED


def test_selected_but_drive_disconnected_logs_and_skips(db_session):
    _seed_tenant(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf:
        result = deliver_drive_archive(db_session, invoice)
    mock_upload.assert_not_called()
    assert result == {
        "uploaded": False,
        "code": DRIVE_NOT_CONNECTED,
        "error": result["error"],
    }
    assert "not connected" in result["error"]


def test_the_archive_writes_csv_json_and_the_source_pdf(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive", "webhook"])
    invoice = _seed_invoice(db_session, status="PAID")

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder as mock_folder, upload as mock_upload, pdf:
        result = deliver_drive_archive(db_session, invoice)

    assert result["uploaded"] is True
    assert result["source_pdf_included"] is True
    mock_folder.assert_called_once()
    assert mock_folder.call_args.args[1] == DRIVE_ARCHIVE_FOLDER_NAME

    csv_name, json_name = export_filenames(invoice)
    calls = [c.args for c in mock_upload.call_args_list]
    assert [c[2] for c in calls] == [csv_name, json_name, export_pdf_filename(invoice)]
    assert [c[4] for c in calls] == [CSV_MIME_TYPE, JSON_MIME_TYPE, PDF_MIME_TYPE]
    # Every file lands in the app-owned folder, not loose in the user's Drive.
    assert {c[1] for c in calls} == {"folder-abc"}

    # The same builders the email summary uses -- not a second serialiser.
    assert b"Rack unit" in calls[0][3]
    assert json.loads(calls[1][3])["invoice_number"] == "INV-4471"
    assert calls[2][3] == FAKE_PDF


def test_a_missing_source_pdf_does_not_cost_the_tenant_the_other_two_files(db_session):
    """An archive with two of three files and a logged reason beats no archive."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, _pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, \
         patch("services.workflow_outputs.download_pdf_from_storage",
               side_effect=FileNotFoundError("blob gone")):
        result = deliver_drive_archive(db_session, invoice)

    assert result["uploaded"] is True
    assert result["source_pdf_included"] is False
    assert len(mock_upload.call_args_list) == 2


def test_an_invoice_with_no_file_path_still_archives_the_data(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session, file_path="")

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf as mock_download:
        result = deliver_drive_archive(db_session, invoice)

    assert result["uploaded"] is True
    assert result["source_pdf_included"] is False
    mock_download.assert_not_called()
    assert len(mock_upload.call_args_list) == 2


def test_a_403_from_drive_is_reported_as_reconnect_required(db_session):
    """The other half of the re-consent story. If the scope probe was
    indeterminate and the grant really was read-only, this is how the tenant
    finds out -- with the same actionable code, not a raw HTTP error."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    refused = httpx.HTTPStatusError(
        "insufficient permissions",
        request=httpx.Request("POST", "https://www.googleapis.com/upload/drive/v3/files"),
        response=httpx.Response(403),
    )
    creds, scope, folder, _upload, pdf = _drive_patches(write_scope=None)
    with creds, scope, folder, pdf, \
         patch("services.workflow_outputs.upload_google_drive_file", side_effect=refused):
        result = deliver_drive_archive(db_session, invoice)

    assert result["uploaded"] is False
    assert result["code"] == DRIVE_RECONNECT_REQUIRED
    assert "403" in result["error"]


def test_a_raising_upload_is_reported_never_propagated(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, _upload, pdf = _drive_patches()
    with creds, scope, folder, pdf, \
         patch("services.workflow_outputs.upload_google_drive_file",
               side_effect=RuntimeError("Drive 503")):
        result = deliver_drive_archive(db_session, invoice)

    assert result["uploaded"] is False
    assert "Drive 503" in result["error"]


# ===========================================================================
# 4. The trigger -- one point, both credentials
# ===========================================================================


def _resolve(invoice_id, status_value="PAID", headers=None):
    return client.put(
        RESOLVE_URL.format(invoice_id=invoice_id),
        json={"status": status_value},
        headers=headers or {},
    )


def test_human_approve_archives_to_drive(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf:
        response = _resolve(invoice.id)

    assert response.status_code == 200, response.text
    assert response.json()["drive_archive"]["uploaded"] is True
    assert len(mock_upload.call_args_list) == 3
    db_session.refresh(invoice)
    assert invoice.status == "PAID"


def test_api_key_approve_archives_identically(db_session):
    """Gap 335's path. Both credentials converge on resolve_audit_invoice(), so
    this asserts the *same* uploads rather than merely asserting that something
    was uploaded."""
    tenant = _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    raw_key = _issue_actions_key(db_session, tenant)

    human_invoice = _seed_invoice(db_session, invoice_number="INV-SAME")
    key_invoice = _seed_invoice(db_session, invoice_number="INV-SAME")

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf:
        human = _resolve(human_invoice.id)
        via_key = _resolve(key_invoice.id, headers={"X-API-Key": raw_key})

    assert human.status_code == 200, human.text
    assert via_key.status_code == 200, via_key.text
    assert via_key.json()["drive_archive"]["uploaded"] is True

    calls = [c.args for c in mock_upload.call_args_list]
    human_calls, key_calls = calls[:3], calls[3:]
    # Same folder, same filenames, same content types.
    assert [(c[1], c[2], c[4]) for c in human_calls] == [(c[1], c[2], c[4]) for c in key_calls]
    # Same content, modulo the one field that legitimately differs -- these are
    # two different invoice rows, so `invoice_id` is not expected to match.
    def _without_id(payload: bytes) -> object:
        data = json.loads(payload)
        data.pop("invoice_id")
        return data

    assert _without_id(human_calls[1][3]) == _without_id(key_calls[1][3])
    assert human_calls[2][3] == key_calls[2][3] == FAKE_PDF
    for csv_bytes in (human_calls[0][3], key_calls[0][3]):
        assert b"INV-SAME" in csv_bytes and b"Rack unit" in csv_bytes

    db_session.refresh(key_invoice)
    assert key_invoice.status == "PAID"


def test_reject_does_not_archive(db_session):
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches()
    with creds, scope, folder, upload as mock_upload, pdf:
        response = _resolve(invoice.id, status_value="REJECTED")

    assert response.status_code == 200
    assert response.json()["drive_archive"] is None
    mock_upload.assert_not_called()


def test_a_failing_upload_never_fails_the_approval(db_session):
    """The status transition has already committed by the time Drive is called."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, _upload, pdf = _drive_patches()
    with creds, scope, folder, pdf, \
         patch("services.workflow_outputs.upload_google_drive_file",
               side_effect=RuntimeError("boom")):
        response = _resolve(invoice.id)

    assert response.status_code == 200
    assert response.json()["drive_archive"]["uploaded"] is False
    db_session.refresh(invoice)
    assert invoice.status == "PAID"


def test_a_reconnect_required_tenant_still_gets_a_200_and_a_paid_invoice(db_session):
    """The end-to-end shape of the migration case: nothing is archived, the
    approval succeeds, and the response says exactly why."""
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)
    _seed_workflow(db_session, ["drive_archive"])
    invoice = _seed_invoice(db_session)

    creds, scope, folder, upload, pdf = _drive_patches(write_scope=False)
    with creds, scope, folder, upload as mock_upload, pdf:
        response = _resolve(invoice.id)

    assert response.status_code == 200
    body = response.json()["drive_archive"]
    assert body["uploaded"] is False
    assert body["code"] == DRIVE_RECONNECT_REQUIRED
    assert "Reconnect Google Drive" in body["error"]
    mock_upload.assert_not_called()
    db_session.refresh(invoice)
    assert invoice.status == "PAID"


# ===========================================================================
# 5. Real Postgres checkpoint
#
# Everything above runs on the in-memory SQLite fixture, which per
# CONVENTIONS.md hard rule 2 is not sufficient evidence on its own -- and here
# it is specifically insufficient: `output_destinations` is JSONB on Postgres
# and plain JSON on SQLite, and it is the column that decides whether anything
# is archived at all. Same shape as Gap 339's checkpoint: borrow MOCK_TENANT_ID
# (mock auth always resolves it), capture every piece of pre-existing state,
# restore or delete all of it in the finally.
# ===========================================================================


def test_approve_archives_to_drive_on_postgres():
    """Both approval paths and the reconnect-required path, against real
    Postgres, on rows this test creates and then deletes."""
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

    tenant_id = MOCK_TENANT_ID
    created_invoice_ids: list = []
    connection = None
    config = None
    config_was_created = False
    previous_destinations = None
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
        # A tenant may legitimately already have a Drive connection on this
        # shared local database; this test must not disturb it.
        pre_existing_connection = pg_session.exec(
            select(TenantConnection).where(
                TenantConnection.tenant_id == tenant_id,
                TenantConnection.provider == "google_drive",
            )
        ).first()
        try:
            if tenant is None:
                tenant = _seed_tenant(pg_session, tenant_id=tenant_id)
            if pre_existing_connection is None:
                connection = _seed_drive_connection(pg_session, tenant_id=tenant_id)

            config = pg_session.exec(
                select(TenantWorkflowConfig).where(
                    TenantWorkflowConfig.tenant_id == tenant_id
                )
            ).first()
            config_was_created = config is None
            previous_destinations = list(config.output_destinations or []) if config else None
            if config is None:
                config = TenantWorkflowConfig(tenant_id=tenant_id)
            config.output_destinations = ["drive_archive"]
            pg_session.add(config)

            raw_key = _issue_actions_key(pg_session, tenant)
            pg_session.commit()

            # The JSONB round-trip the SQLite fixture cannot prove.
            pg_session.refresh(config)
            assert config.output_destinations == ["drive_archive"]

            human_invoice = _seed_invoice(pg_session, invoice_number="PG-DRIVE-HUMAN")
            key_invoice = _seed_invoice(pg_session, invoice_number="PG-DRIVE-KEY")
            created_invoice_ids = [human_invoice.id, key_invoice.id]

            creds, scope, folder, upload, pdf = _drive_patches()
            with creds, scope, folder, upload as mock_upload, pdf:
                human = _resolve(human_invoice.id)
                via_key = _resolve(key_invoice.id, headers={"X-API-Key": raw_key})

            assert human.status_code == 200, human.text
            assert via_key.status_code == 200, via_key.text
            assert human.json()["drive_archive"]["uploaded"] is True
            assert via_key.json()["drive_archive"]["uploaded"] is True

            # Six uploads: three files per approval, identical across the two
            # credential paths -- the destination read really did come from the
            # JSONB column, for both.
            calls = [c.args for c in mock_upload.call_args_list]
            assert len(calls) == 6
            assert [c[4] for c in calls[:3]] == [CSV_MIME_TYPE, JSON_MIME_TYPE, PDF_MIME_TYPE]
            assert [c[4] for c in calls[3:]] == [CSV_MIME_TYPE, JSON_MIME_TYPE, PDF_MIME_TYPE]
            assert b"Rack unit" in calls[0][3]

            pg_session.refresh(human_invoice)
            pg_session.refresh(key_invoice)
            assert human_invoice.status == "PAID"
            assert key_invoice.status == "PAID"

            # And the migration case, against the same real rows: a read-only
            # grant archives nothing, says why, and still leaves a PAID invoice.
            readonly_invoice = _seed_invoice(pg_session, invoice_number="PG-DRIVE-READONLY")
            created_invoice_ids.append(readonly_invoice.id)
            creds, scope, folder, upload, pdf = _drive_patches(write_scope=False)
            with creds, scope, folder, upload as mock_upload, pdf:
                readonly = _resolve(readonly_invoice.id)
            assert readonly.status_code == 200, readonly.text
            assert readonly.json()["drive_archive"]["code"] == DRIVE_RECONNECT_REQUIRED
            mock_upload.assert_not_called()
            pg_session.refresh(readonly_invoice)
            assert readonly_invoice.status == "PAID"
        finally:
            app.dependency_overrides.clear()
            pg_session.rollback()
            for invoice_id in created_invoice_ids:
                for log in pg_session.exec(
                    select(AuditLog).where(AuditLog.invoice_id == invoice_id)
                ).all():
                    pg_session.delete(log)
                row = pg_session.get(Invoice, invoice_id)
                if row:
                    pg_session.delete(row)
            if connection is not None:
                row = pg_session.get(TenantConnection, connection.id)
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
