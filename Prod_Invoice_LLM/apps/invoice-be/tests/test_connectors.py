import pytest
import json
import io
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
    """Verify that file imports dispatch back-end Celery queue tasks."""
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

    with patch("workers.tasks.import_connector_file_task.delay") as mock_celery:
        payload = {"file_id": "gdrive_file_101"}
        response = client.post("/api/v1/connectors/import/google_drive", json=payload)
        assert response.status_code == 200
        assert "Queued" in response.json()["message"]
        mock_celery.assert_called_once_with(
            provider="google_drive",
            file_id="gdrive_file_101",
            tenant_id=str(MOCK_TENANT_ID)
        )

def test_mcp_server_initialize(db_session):
    """Verify MCP stdio JSON-RPC server handles initialize protocol handshakes."""
    from mcp_servers.ingestion_mcp import main as mcp_main
    
    init_request = json.dumps({
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        "id": 1
    }) + "\n"

    # Patch stdin/stdout
    mock_stdin = io.StringIO(init_request)
    mock_stdout = io.StringIO()

    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout), patch("mcp_servers.ingestion_mcp.engine", engine):
        mcp_main()
        
    response = json.loads(mock_stdout.getvalue().strip())
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["serverInfo"]["name"] == "ingestion-mcp"

def test_mcp_server_list_tools(db_session):
    """Verify MCP stdio server lists connector capability tools."""
    from mcp_servers.ingestion_mcp import main as mcp_main

    list_request = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 2
    }) + "\n"

    mock_stdin = io.StringIO(list_request)
    mock_stdout = io.StringIO()

    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout), patch("mcp_servers.ingestion_mcp.engine", engine):
        mcp_main()

    response = json.loads(mock_stdout.getvalue().strip())
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    tools = response["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "list_drive_files" in tool_names
    assert "import_drive_file" in tool_names

def test_mcp_server_call_list_files(db_session):
    """Verify MCP stdio server handles list_drive_files tool calls with DB decrypt access."""
    # Register connection in database
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("active_token"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active"
    )
    db_session.add(conn)
    db_session.commit()

    from mcp_servers.ingestion_mcp import main as mcp_main

    call_request = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "list_drive_files",
            "arguments": {
                "provider": "google_drive",
                "tenant_id": str(MOCK_TENANT_ID)
            }
        },
        "id": 3
    }) + "\n"

    mock_stdin = io.StringIO(call_request)
    mock_stdout = io.StringIO()

    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout), patch("mcp_servers.ingestion_mcp.engine", engine):
        mcp_main()

    response = json.loads(mock_stdout.getvalue().strip())
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 3
    
    text_content = response["result"]["content"][0]["text"]
    files_data = json.loads(text_content)
    assert len(files_data["files"]) > 0
    assert files_data["files"][0]["name"] == "invoice_acme_hardware.pdf"
