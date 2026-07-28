import pytest
from uuid import uuid4
from datetime import datetime, timedelta
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

def test_oauth_callback(db_session):
    """Verify code redirect callback performs token encryption and updates table."""
    response = client.get("/api/v1/connectors/callback/salesforce?code=auth_code_9928")
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Successfully connected to salesforce"}

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
    """Verify explorer routes list files and handle decryption verification."""
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

    response = client.get("/api/v1/connectors/files/google_drive")
    assert response.status_code == 200
    files = response.json()["files"]
    assert len(files) > 0
    assert files[0]["name"] == "invoice_acme_hardware.pdf"

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
def test_handle_import_connector_file_inbound_no_azure(mock_qc, mock_bsc):
    """handle_import_connector_file succeeds (simulated) when no Azure creds set."""
    mock_bsc.from_connection_string.side_effect = Exception("Mock storage offline")
    mock_qc.from_connection_string.side_effect = Exception("Mock queue offline")
    from queue_worker.handlers import handle_import_connector_file
    result = handle_import_connector_file(
        provider="google_drive",
        file_id="test_file_001",
        tenant_id=str(MOCK_TENANT_ID),
        direction="inbound",
    )
    assert result["success"] is True
    assert result["direction"] == "inbound"
    assert "inbound" in result["blob_path"]


@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers.QueueClient")
def test_handle_import_connector_file_outbound_no_azure(mock_qc, mock_bsc):
    """handle_import_connector_file stores to outbound prefix, no extraction queued."""
    mock_bsc.from_connection_string.side_effect = Exception("Mock storage offline")
    mock_qc.from_connection_string.side_effect = Exception("Mock queue offline")
    from queue_worker.handlers import handle_import_connector_file
    result = handle_import_connector_file(
        provider="salesforce",
        file_id="sf_doc_888",
        tenant_id=str(MOCK_TENANT_ID),
        direction="outbound",
    )
    assert result["success"] is True
    assert result["direction"] == "outbound"
    assert "outbound" in result["blob_path"]
