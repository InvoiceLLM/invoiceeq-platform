import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import TenantConnection, Invoice
from utils.encryption import encrypt_token, decrypt_token

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

client = TestClient(app)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields clean isolated test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides dependencies database session."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

def test_encryption_decryption():
    """Verify that credentials can be successfully encrypted and decrypted."""
    plain_token = "my-super-secret-oauth-refresh-token-12345"
    encrypted = encrypt_token(plain_token)
    assert encrypted != plain_token
    
    decrypted = decrypt_token(encrypted)
    assert decrypted == plain_token

def test_connectors_status_not_configured(db_session):
    """Verify status is 'Not Configured' when no connection database records exist."""
    response = client.get("/api/v1/connectors/status")
    assert response.status_code == 200
    data = response.json()
    assert data["google_drive"] == "Not Configured"
    assert data["salesforce"] == "Not Configured"

def test_connectors_status_active(db_session):
    """Verify status updates to 'Active' when active credentials exist."""
    expiry_time = datetime.utcnow() + timedelta(hours=2)
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("active_token"),
        encrypted_refresh_token=encrypt_token("refresh_token"),
        token_expiry=expiry_time,
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    response = client.get("/api/v1/connectors/status")
    assert response.status_code == 200
    data = response.json()
    assert data["google_drive"] == "Active"
    assert data["salesforce"] == "Not Configured"

def test_get_auth_url():
    """Verify auth redirect URL generation endpoint is working."""
    response = client.get("/api/v1/connectors/auth-url/google_drive")
    assert response.status_code == 200
    assert "auth_url" in response.json()
    assert "google" in response.json()["auth_url"]

def test_salesforce_pkce_flow(db_session):
    """Some Salesforce Connected Apps require PKCE on the authorization flow
    (real-world error hit: 'invalid_request: missing required code challenge').
    get_auth_url() must attach a code_challenge/state and stash the matching
    code_verifier server-side; oauth_callback() must retrieve it by state and
    include it in the token exchange payload.
    """
    response = client.get("/api/v1/connectors/auth-url/salesforce")
    assert response.status_code == 200
    auth_url = response.json()["auth_url"]
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert "state=" in auth_url

    query = parse_qs(urlparse(auth_url).query)
    state = query["state"][0]

    captured_payload = {}

    class FakeTokenResponse:
        status_code = 200
        def json(self):
            return {
                "access_token": "sf_real_token",
                "refresh_token": "sf_real_refresh",
                "instance_url": "https://example.my.salesforce.com",
            }

    async def fake_post(self, url, data=None, **kwargs):
        captured_payload.update(data or {})
        return FakeTokenResponse()

    with patch("httpx.AsyncClient.post", new=fake_post):
        response = client.get(
            f"/api/v1/connectors/callback/salesforce?code=real_code_123&state={state}",
            follow_redirects=False,
        )

    assert response.status_code in (302, 307)
    assert "code_verifier" in captured_payload
    assert len(captured_payload["code_verifier"]) >= 43  # RFC 7636 minimum length

def test_oauth_callback(db_session):
    """Verify code redirect callback performs token encryption, updates table,
    and redirects the browser back into the FE (Google/Salesforce land the
    browser here as a full-page navigation, not a fetch call -- see
    routers/connectors.py::oauth_callback).

    Forces the mock path via patching rather than relying on salesforce
    lacking real credentials -- both providers may have real creds configured
    in this environment's .env now, so ambient state can't be assumed.
    """
    with patch("routers.connectors._has_real_credentials", return_value=False):
        response = client.get(
            "/api/v1/connectors/callback/salesforce?code=auth_code_9928",
            follow_redirects=False,
        )
    assert response.status_code in (302, 307)
    assert "connected=salesforce" in response.headers["location"]

    # Verify db entry
    statement = select(TenantConnection).where(
        TenantConnection.tenant_id == MOCK_TENANT_ID,
        TenantConnection.provider == "salesforce"
    )
    conn = db_session.exec(statement).first()
    assert conn is not None
    assert conn.status == "active"
    # Verify tokens are encrypted
    assert conn.encrypted_access_token != "mock_access_token_salesforce"
    assert decrypt_token(conn.encrypted_access_token).startswith("mock_access_token_salesforce")

def test_list_files(db_session):
    """Verify explorer routes list files and handle decryption verification.

    Forces the mock path via patching -- both providers may have real
    credentials configured in this environment's .env now, so this can't
    rely on either one being the "safe" mocked provider by default.
    """
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="salesforce",
        encrypted_access_token=encrypt_token("sf_secret"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    with patch("routers.connectors._has_real_credentials", return_value=False):
        response = client.get("/api/v1/connectors/files/salesforce")
    assert response.status_code == 200
    files = response.json()["files"]
    assert len(files) > 0
    assert files[0]["name"] == "Attachment_ACME_PO_99.pdf"

def test_list_files_real_google_drive(db_session):
    """Gap 98: once a provider has a real Client ID configured (google_drive,
    via the dev's personal GCP app standing in as the company's), the files
    endpoint must call the real Drive API instead of returning the mock list.
    """
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("real_access_token"),
        encrypted_refresh_token=encrypt_token("real_refresh_token"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    with patch("routers.connectors.list_google_drive_files") as mock_list:
        mock_list.return_value = [
            {"id": "real_drive_1", "name": "real_supplier_invoice.pdf", "type": "file", "size_bytes": 5000},
        ]
        response = client.get("/api/v1/connectors/files/google_drive")

    assert response.status_code == 200
    files = response.json()["files"]
    assert files == [{"id": "real_drive_1", "name": "real_supplier_invoice.pdf", "type": "file", "size_bytes": 5000}]
    mock_list.assert_called_once()
    called_access_token = mock_list.call_args[0][0]
    assert called_access_token == "real_access_token"

def test_trigger_import(db_session):
    """Verify that file imports dispatch back-end Azure Storage Queue tasks (inbound, default)."""
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("drive_secret"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    with patch("routers.connectors.QueueClient") as mock_qc:
        mock_qc.from_connection_string.return_value.send_message = MagicMock()
        payload = {"file_id": "gdrive_file_101"}
        response = client.post("/api/v1/connectors/import/google_drive", json=payload)
    assert response.status_code == 200
    assert "inbound" in response.json()["message"].lower()


def test_trigger_import_outbound(db_session):
    """Verify outbound direction is accepted and reflected in the response message."""
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("drive_secret"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    with patch("routers.connectors.QueueClient") as mock_qc:
        mock_qc.from_connection_string.return_value.send_message = MagicMock()
        payload = {"file_id": "gdrive_file_202"}
        response = client.post(
            "/api/v1/connectors/import/google_drive?direction=outbound", json=payload
        )
    assert response.status_code == 200
    assert "outbound" in response.json()["message"].lower()


def test_list_files_invalid_direction(db_session):
    """Verify an unknown direction returns 400."""
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("drive_secret"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    response = client.get("/api/v1/connectors/files/google_drive?direction=sideways")
    assert response.status_code == 400


@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers.QueueClient")
def test_handle_import_connector_file_inbound_no_azure(mock_qc, mock_bsc, db_session):
    """handle_import_connector_file succeeds (simulated) when no Azure creds set.

    Passes the isolated in-memory db_session explicitly -- with no
    TenantConnection row seeded, the lookup finds nothing and the handler
    falls back to the stub bytes, deterministically, regardless of whatever
    real connections happen to exist in this environment's actual database
    (the handler defaults to a real Session(engine) when none is passed).
    """
    mock_bsc.from_connection_string.side_effect = Exception("Mock storage offline")
    mock_qc.from_connection_string.side_effect = Exception("Mock queue offline")
    from queue_worker.handlers import handle_import_connector_file
    result = handle_import_connector_file(
        provider="google_drive",
        file_id="test_file_001",
        tenant_id=str(MOCK_TENANT_ID),
        direction="inbound",
        db_session=db_session,
    )
    assert result["success"] is True
    assert result["direction"] == "inbound"
    assert "inbound" in result["blob_path"]


@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers.QueueClient")
def test_handle_import_connector_file_outbound_no_azure(mock_qc, mock_bsc, db_session):
    """handle_import_connector_file stores to outbound prefix, no extraction queued."""
    mock_bsc.from_connection_string.side_effect = Exception("Mock storage offline")
    mock_qc.from_connection_string.side_effect = Exception("Mock queue offline")
    from queue_worker.handlers import handle_import_connector_file
    result = handle_import_connector_file(
        provider="salesforce",
        file_id="sf_doc_888",
        tenant_id=str(MOCK_TENANT_ID),
        direction="outbound",
        db_session=db_session,
    )
    assert result["success"] is True
    assert result["direction"] == "outbound"
    assert "outbound" in result["blob_path"]


@patch("utils.connector_files.download_google_drive_file")
@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers.QueueClient")
def test_handle_import_connector_file_google_drive_real_download(mock_qc, mock_bsc, mock_download, db_session):
    """Gap 98: with a real, active google_drive TenantConnection, the handler
    must download the file's real bytes via the Drive API instead of writing
    the stub PDF marker.
    """
    mock_bsc.from_connection_string.side_effect = Exception("Mock storage offline")
    mock_qc.from_connection_string.side_effect = Exception("Mock queue offline")
    mock_download.return_value = b"%PDF-1.4 real bytes downloaded from drive"

    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("real_access_token_xyz"),
        encrypted_refresh_token=encrypt_token("real_refresh_token_xyz"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active",
    )
    db_session.add(conn)
    db_session.commit()

    from queue_worker.handlers import handle_import_connector_file
    result = handle_import_connector_file(
        provider="google_drive",
        file_id="real_drive_file_999",
        tenant_id=str(MOCK_TENANT_ID),
        direction="inbound",
        db_session=db_session,
    )

    assert result["success"] is True
    mock_download.assert_called_once_with("real_access_token_xyz", "real_drive_file_999")
    with open(result["blob_path"], "rb") as f:
        content = f.read()
    assert content == b"%PDF-1.4 real bytes downloaded from drive"
    assert b"stub content" not in content


@patch("utils.connector_oauth.httpx.post")
@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers.QueueClient")
@patch("utils.connector_files.download_google_drive_file")
def test_handle_import_connector_file_refreshes_expired_token(mock_download, mock_qc, mock_bsc, mock_post, db_session):
    """Gap 98 / 'connect once': an expired access token with a stored
    refresh_token must be silently refreshed (real POST to Google's token
    endpoint) rather than requiring the user to reconnect.
    """
    mock_bsc.from_connection_string.side_effect = Exception("Mock storage offline")
    mock_qc.from_connection_string.side_effect = Exception("Mock queue offline")
    mock_download.return_value = b"%PDF-1.4 downloaded after refresh"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "refreshed_access_token", "expires_in": 3600}
    mock_post.return_value = mock_response

    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("stale_access_token"),
        encrypted_refresh_token=encrypt_token("real_refresh_token_abc"),
        token_expiry=datetime.utcnow() - timedelta(minutes=5),  # already expired
        status="active",
    )
    db_session.add(conn)
    db_session.commit()

    from queue_worker.handlers import handle_import_connector_file
    result = handle_import_connector_file(
        provider="google_drive",
        file_id="drive_file_after_refresh",
        tenant_id=str(MOCK_TENANT_ID),
        direction="inbound",
        db_session=db_session,
    )

    assert result["success"] is True
    mock_post.assert_called_once()
    mock_download.assert_called_once_with("refreshed_access_token", "drive_file_after_refresh")

    # The refreshed token must be persisted back onto the connection row.
    db_session.refresh(conn)
    assert decrypt_token(conn.encrypted_access_token) == "refreshed_access_token"
    assert conn.token_expiry > datetime.utcnow()
