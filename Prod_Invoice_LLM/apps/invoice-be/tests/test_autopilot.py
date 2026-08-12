"""
Feature 13: Tenant Autopilot — Test Suite (tests/test_autopilot.py)

Covers:
  Unit / API tests (mock DB, mock externals):
    T01 - GET /autopilot/config  -> 200 null when no config saved
    T02 - PUT /autopilot/config  -> 200 creates new config
    T03 - PUT /autopilot/config  -> 200 upserts (updates) existing config
    T04 - PUT /autopilot/config  -> 422 rejects invalid source_type
    T05 - PUT /autopilot/config  -> 422 rejects invalid flow_direction
    T06 - PUT /autopilot/config  -> 422 rejects invalid trigger_mode
    T07 - GET /autopilot/history -> 200 empty list when no logs
    T08 - GET /autopilot/history -> 200 returns paginated log entries
    T09 - POST /autopilot/sync   -> 400 when no config saved
    T10 - POST /autopilot/sync   -> 400 when no active connection

  Sync engine service tests (unit, fully mocked externals):
    T11 - run_sync raises ValueError when tenant has no config
    T12 - run_sync raises ValueError when tenant has no active connection
    T13 - run_sync skips file on Layer-1 dedup (source_file_id already seen)
    T14 - run_sync skips file on Layer-2 dedup (content hash already seen)
    T15 - run_sync processes new file end-to-end (happy path)
    T16 - run_sync handles download failure -> FAILED log row, continues

  ACA Job script tests:
    T17 - run_sync_for_all_due_tenants logs "nothing to do" with no configs
    T18 - run_sync_for_all_due_tenants calls run_sync once per configured tenant

Run:
    uv run pytest tests/test_autopilot.py -v
"""

import hashlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from database import get_session
from dependencies import MOCK_TENANT_ID, get_db_session
from main import app
from models import (
    Tenant,
    TenantAutopilotConfig,
    TenantAutopilotLog,
    TenantConnection,
)
from services.autopilot_sync import run_sync, run_sync_for_all_due_tenants
from utils.encryption import encrypt_token

# ---------------------------------------------------------------------------
# Shared in-memory SQLite engine
# ---------------------------------------------------------------------------

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields a clean, isolated in-memory database session for each test."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Ensure default mock tenant exists for foreign key integrity
        tenant = Tenant(id=MOCK_TENANT_ID, name="Mock Tenant", domain="mock.com")
        session.add(tenant)
        session.commit()
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Injects the in-memory test DB into all FastAPI dependency slots."""
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.clear()



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(db_session: Session, tenant_id: UUID = MOCK_TENANT_ID, **overrides) -> TenantAutopilotConfig:
    """Insert a TenantAutopilotConfig row and return it."""
    # Ensure Tenant row exists for foreign key constraint
    existing_tenant = db_session.get(Tenant, tenant_id)
    if not existing_tenant:
        db_session.add(Tenant(id=tenant_id, name=f"Test Tenant {tenant_id.hex[:6]}", domain=f"test-{tenant_id.hex[:8]}.com"))
        db_session.commit()

    defaults = dict(
        tenant_id=tenant_id,
        source_type="gdrive",
        source_ref="folder-abc-123",
        flow_direction="INBOUND",
        trigger_mode="interval",
        trigger_value="60",
        notify_emails=[],
        send_approval_links=False,
    )
    defaults.update(overrides)
    config = TenantAutopilotConfig(**defaults)
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


def _make_connection(db_session: Session, tenant_id: UUID = MOCK_TENANT_ID, provider: str = "gdrive") -> TenantConnection:
    """Insert an active TenantConnection row and return it."""
    conn = TenantConnection(
        id=uuid4(),
        tenant_id=tenant_id,
        provider=provider,
        encrypted_access_token=encrypt_token("test-access-token"),
        encrypted_refresh_token=encrypt_token("test-refresh-token"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active",
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


def _make_log(
    db_session: Session,
    tenant_id: UUID = MOCK_TENANT_ID,
    source_file_id: str = "file-001",
    content_hash: str = "aabbcc",
    status: str = "SUCCESS",
) -> TenantAutopilotLog:
    """Insert a TenantAutopilotLog row and return it."""
    log = TenantAutopilotLog(
        tenant_id=tenant_id,
        source_type="gdrive",
        source_file_id=source_file_id,
        content_hash=content_hash,
        status=status,
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    return log


# ===========================================================================
# T01 - GET /autopilot/config -> null when no config saved
# ===========================================================================

def test_T01_get_config_no_config(db_session):
    """T01: GET /autopilot/config returns null when tenant has no saved config."""
    response = client.get("/api/v1/autopilot/config")
    assert response.status_code == 200
    assert response.json() is None


# ===========================================================================
# T02 - PUT /autopilot/config -> creates new config
# ===========================================================================

def test_T02_put_config_creates(db_session):
    """T02: PUT /autopilot/config creates and persists a new configuration."""
    payload = {
        "source_type": "gdrive",
        "source_ref": "folder-xyz-999",
        "flow_direction": "INBOUND",
        "trigger_mode": "cron",
        "trigger_value": "0 2 * * *",
        "notify_emails": ["ops@example.com"],
        "send_approval_links": True,
    }
    response = client.put("/api/v1/autopilot/config", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["source_type"] == "gdrive"
    assert data["source_ref"] == "folder-xyz-999"
    assert data["trigger_mode"] == "cron"
    assert data["trigger_value"] == "0 2 * * *"
    assert data["notify_emails"] == ["ops@example.com"]
    assert data["send_approval_links"] is True
    assert "id" in data
    assert "tenant_id" in data

    # Verify DB row was written
    saved = db_session.exec(
        select(TenantAutopilotConfig).where(
            TenantAutopilotConfig.tenant_id == MOCK_TENANT_ID
        )
    ).first()
    assert saved is not None
    assert saved.source_ref == "folder-xyz-999"


# ===========================================================================
# T03 - PUT /autopilot/config -> upserts existing config
# ===========================================================================

def test_T03_put_config_upserts(db_session):
    """T03: A second PUT replaces (upserts) the existing config - only one row allowed."""
    _make_config(db_session, source_ref="folder-old")

    # Upsert with new values
    payload = {
        "source_type": "gdrive",
        "source_ref": "folder-new",
        "flow_direction": "OUTBOUND",
        "trigger_mode": "interval",
        "trigger_value": "30",
        "notify_emails": [],
        "send_approval_links": False,
    }
    response = client.put("/api/v1/autopilot/config", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["source_ref"] == "folder-new"
    assert response.json()["flow_direction"] == "OUTBOUND"

    # Still only one row in DB
    all_configs = db_session.exec(
        select(TenantAutopilotConfig).where(
            TenantAutopilotConfig.tenant_id == MOCK_TENANT_ID
        )
    ).all()
    assert len(all_configs) == 1


# ===========================================================================
# T04 - PUT /autopilot/config -> 422 invalid source_type
# ===========================================================================

def test_T04_put_config_invalid_source_type(db_session):
    """T04: PUT /autopilot/config returns 422 for unsupported source_type."""
    payload = {
        "source_type": "dropbox",   # not supported
        "source_ref": "folder-123",
        "flow_direction": "INBOUND",
        "trigger_mode": "interval",
        "trigger_value": "60",
    }
    response = client.put("/api/v1/autopilot/config", json=payload)
    assert response.status_code == 422


# ===========================================================================
# T05 - PUT /autopilot/config -> 422 invalid flow_direction
# ===========================================================================

def test_T05_put_config_invalid_flow_direction(db_session):
    """T05: PUT /autopilot/config returns 422 for invalid flow_direction."""
    payload = {
        "source_type": "gdrive",
        "source_ref": "folder-123",
        "flow_direction": "SIDEWAYS",  # invalid
        "trigger_mode": "interval",
        "trigger_value": "60",
    }
    response = client.put("/api/v1/autopilot/config", json=payload)
    assert response.status_code == 422


# ===========================================================================
# T06 - PUT /autopilot/config -> 422 invalid trigger_mode
# ===========================================================================

def test_T06_put_config_invalid_trigger_mode(db_session):
    """T06: PUT /autopilot/config returns 422 for invalid trigger_mode."""
    payload = {
        "source_type": "gdrive",
        "source_ref": "folder-123",
        "flow_direction": "INBOUND",
        "trigger_mode": "timer",    # invalid
        "trigger_value": "60",
    }
    response = client.put("/api/v1/autopilot/config", json=payload)
    assert response.status_code == 422


# ===========================================================================
# T07 - GET /autopilot/history -> empty list when no logs
# ===========================================================================

def test_T07_get_history_empty(db_session):
    """T07: GET /autopilot/history returns empty list when no sync runs have occurred."""
    response = client.get("/api/v1/autopilot/history")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


# ===========================================================================
# T08 - GET /autopilot/history -> returns paginated log entries
# ===========================================================================

def test_T08_get_history_paginated(db_session):
    """T08: GET /autopilot/history returns correct log entries with pagination metadata."""
    # Insert 3 log rows
    for i in range(3):
        _make_log(
            db_session,
            source_file_id=f"file-{i:03d}",
            content_hash=f"hash{i:03d}",
            status="SUCCESS",
        )

    response = client.get("/api/v1/autopilot/history?page=1&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) == 2  # page_size=2 -> only 2 returned

    # Second page
    response2 = client.get("/api/v1/autopilot/history?page=2&page_size=2")
    assert response2.status_code == 200
    data2 = response2.json()
    assert len(data2["items"]) == 1


# ===========================================================================
# T09 - POST /autopilot/sync -> 400 when no config
# ===========================================================================

def test_T09_sync_no_config(db_session):
    """T09: POST /autopilot/sync returns 400 when no autopilot config has been saved."""
    response = client.post("/api/v1/autopilot/sync")
    assert response.status_code == 400
    assert "No Autopilot config" in response.json()["detail"]


# ===========================================================================
# T10 - POST /autopilot/sync -> 400 when no active connection
# ===========================================================================

def test_T10_sync_no_active_connection(db_session):
    """T10: POST /autopilot/sync returns 400 when no active connector is linked."""
    _make_config(db_session)  # config exists, but no TenantConnection
    response = client.post("/api/v1/autopilot/sync")
    assert response.status_code == 400
    assert "connection" in response.json()["detail"].lower()


# ===========================================================================
# T11 - run_sync raises ValueError with no config (unit)
# ===========================================================================

def test_T11_run_sync_no_config(db_session):
    """T11 (unit): run_sync raises ValueError when tenant has no config."""
    orphan_tenant_id = uuid4()
    with pytest.raises(ValueError, match="No Autopilot config"):
        run_sync(orphan_tenant_id, db_session)


# ===========================================================================
# T12 - run_sync raises ValueError with no active connection (unit)
# ===========================================================================

def test_T12_run_sync_no_connection(db_session):
    """T12 (unit): run_sync raises ValueError when no active OAuth connection exists."""
    _make_config(db_session)
    with pytest.raises(ValueError, match="No active gdrive connection"):
        run_sync(MOCK_TENANT_ID, db_session)


# ===========================================================================
# T13 - run_sync skips on Layer-1 dedup (source_file_id already seen)
# ===========================================================================

def test_T13_run_sync_dedup_layer1(db_session):
    """T13 (unit): run_sync skips a file that is already in the log by source_file_id."""
    _make_config(db_session)
    _make_connection(db_session)
    # Pre-seed a SUCCESS log for gdrive-file-001
    _make_log(db_session, source_file_id="gdrive-file-001", content_hash="oldhash", status="SUCCESS")

    remote_files = [{"id": "gdrive-file-001", "name": "invoice.pdf", "type": "file"}]

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=remote_files):
        summary = run_sync(MOCK_TENANT_ID, db_session)

    assert summary["processed"] == 0
    assert summary["skipped"] == 1
    assert summary["failed"] == 0

    # A SKIPPED_DUPLICATE log row must have been written
    logs = db_session.exec(
        select(TenantAutopilotLog).where(
            TenantAutopilotLog.status == "SKIPPED_DUPLICATE"
        )
    ).all()
    assert len(logs) == 1


# ===========================================================================
# T14 - run_sync skips on Layer-2 dedup (content hash already seen)
# ===========================================================================

def test_T14_run_sync_dedup_layer2(db_session):
    """T14 (unit): run_sync skips a file whose SHA-256 hash already exists (renamed file)."""
    _make_config(db_session)
    _make_connection(db_session)

    # Pre-seed a SUCCESS log with a known hash - different file_id (renamed file scenario)
    file_bytes = b"%PDF-1.4 duplicate content"
    known_hash = hashlib.sha256(file_bytes).hexdigest()
    _make_log(db_session, source_file_id="old-file-id", content_hash=known_hash, status="SUCCESS")

    # New file has a different ID but same bytes
    remote_files = [{"id": "new-file-id", "name": "renamed_invoice.pdf", "type": "file"}]

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=remote_files), \
         patch("services.autopilot_sync.download_google_drive_file", return_value=file_bytes):
        summary = run_sync(MOCK_TENANT_ID, db_session)

    assert summary["processed"] == 0
    assert summary["skipped"] == 1
    assert summary["failed"] == 0


# ===========================================================================
# T15 - run_sync processes new file end-to-end (happy path)
# ===========================================================================

def test_T15_run_sync_happy_path(db_session):
    """T15 (unit): run_sync fully processes a new file - uploads blob, creates Invoice, writes log."""
    from models import Invoice

    _make_config(db_session)
    _make_connection(db_session)

    file_bytes = b"%PDF-1.4 brand new invoice"
    remote_files = [{"id": "new-file-abc", "name": "new_invoice.pdf", "type": "file"}]

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=remote_files), \
         patch("services.autopilot_sync.download_google_drive_file", return_value=file_bytes), \
         patch("services.autopilot_sync.upload_pdf_to_blob_storage", return_value="blobs/tenant/invoice.pdf"), \
         patch("services.autopilot_sync._dispatch_queue"):
        summary = run_sync(MOCK_TENANT_ID, db_session)

    assert summary["processed"] == 1
    assert summary["skipped"] == 0
    assert summary["failed"] == 0

    # Invoice DB row must exist
    invoices = db_session.exec(select(Invoice)).all()
    assert len(invoices) == 1
    assert invoices[0].status == "PROCESSING"
    assert invoices[0].file_path == "blobs/tenant/invoice.pdf"

    # SUCCESS log row must exist
    logs = db_session.exec(
        select(TenantAutopilotLog).where(TenantAutopilotLog.status == "SUCCESS")
    ).all()
    assert len(logs) == 1
    assert logs[0].source_file_id == "new-file-abc"


# ===========================================================================
# T16 - run_sync handles download failure -> FAILED log, continues
# ===========================================================================

def test_T16_run_sync_download_failure(db_session):
    """T16 (unit): A download error is caught - FAILED log written, other files continue."""
    _make_config(db_session)
    _make_connection(db_session)

    good_bytes = b"%PDF-1.4 good invoice"
    remote_files = [
        {"id": "bad-file-id", "name": "corrupt.pdf", "type": "file"},
        {"id": "good-file-id", "name": "good.pdf", "type": "file"},
    ]

    def _download_side_effect(token, file_id):
        if file_id == "bad-file-id":
            raise RuntimeError("Network error: download failed")
        return good_bytes

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=remote_files), \
         patch("services.autopilot_sync.download_google_drive_file", side_effect=_download_side_effect), \
         patch("services.autopilot_sync.upload_pdf_to_blob_storage", return_value="blobs/t/x.pdf"), \
         patch("services.autopilot_sync._dispatch_queue"):
        summary = run_sync(MOCK_TENANT_ID, db_session)

    assert summary["processed"] == 1
    assert summary["failed"] == 1

    failed_logs = db_session.exec(
        select(TenantAutopilotLog).where(TenantAutopilotLog.status == "FAILED")
    ).all()
    assert len(failed_logs) == 1
    assert "Network error" in failed_logs[0].error_detail


# ===========================================================================
# T17 - run_sync_for_all_due_tenants: no configs -> nothing done
# ===========================================================================

def test_T17_job_no_tenants(db_session, caplog):
    """T17 (unit): run_sync_for_all_due_tenants logs 'nothing to do' when no configs exist."""
    import logging
    with caplog.at_level(logging.INFO, logger="services.autopilot_sync"):
        run_sync_for_all_due_tenants(db_session)

    assert any(
        "Nothing to do" in r.message or "No tenants configured" in r.message
        for r in caplog.records
    )


# ===========================================================================
# T18 - run_sync_for_all_due_tenants calls run_sync once per tenant
# ===========================================================================

def test_T18_job_calls_run_sync_per_tenant(db_session):
    """T18 (unit): run_sync_for_all_due_tenants invokes run_sync once for each configured tenant."""
    # Two separate tenants
    tenant_a = uuid4()
    tenant_b = uuid4()
    _make_config(db_session, tenant_id=tenant_a)
    _make_config(db_session, tenant_id=tenant_b)

    call_log = []

    def _fake_run_sync(tenant_id, session):
        call_log.append(tenant_id)
        return {"processed": 0, "skipped": 0, "failed": 0}

    with patch("services.autopilot_sync.run_sync", side_effect=_fake_run_sync):
        run_sync_for_all_due_tenants(db_session)

    assert len(call_log) == 2
    assert set(call_log) == {tenant_a, tenant_b}
