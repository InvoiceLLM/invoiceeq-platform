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
    T08 - GET /autopilot/history -> 200 groups log rows into runs, paginated

  Gap 427 — sync history is a list of RUNS, not files:
    T20a - runs are grouped by batch_id, newest first, with per-run totals
    T20b - run status derivation: SUCCESS / PARTIAL / FAILED / all-skipped
    T20c - a NO_NEW_FILES marker run reports files_seen 0 and that status
    T20d - legacy (batch_id IS NULL) rows collapse into ONE bucket, ordered last
    T20e - /history/{batch_id}/files returns that run's files, 404 cross-tenant
    T20f - /history/legacy/files returns only the caller's legacy rows
    T20g - run_sync stamps batch_id/trigger/source_file_name on every row and
           writes a NO_NEW_FILES row when the source has nothing new
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
from fastapi import HTTPException
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


def _make_connection(db_session: Session, tenant_id: UUID = MOCK_TENANT_ID, provider: str = "google_drive") -> TenantConnection:
    """Insert an active TenantConnection row and return it.

    BE Gap 288: default is 'google_drive', matching what routers/connectors.py
    actually persists for a Drive connection -- not Autopilot's own 'gdrive'
    source_type spelling. The two vocabularies must never be compared
    directly (see SOURCE_TYPE_TO_PROVIDER in services/autopilot_sync.py); a
    fixture built with provider='gdrive' would agree with that bug instead of
    catching it, which is exactly what happened here for nine days.
    """
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
    batch_id: UUID | None = None,
    trigger: str | None = None,
    source_file_name: str | None = None,
    ingested_at: datetime | None = None,
) -> TenantAutopilotLog:
    """Insert a TenantAutopilotLog row and return it.

    Gap 427: `batch_id` defaults to None so that a bare _make_log() call still
    produces a *legacy* row -- which is what the pre-Gap-427 rows in a real
    database actually are, and keeps the legacy-bucket tests honest. Tests that
    want a real run pass an explicit batch_id.

    `ingested_at` is settable because run ordering is by min(ingested_at), and
    rows inserted in the same test land in the same clock tick often enough on
    Windows that relying on insertion order would make the ordering assertions
    flaky rather than wrong.
    """
    log = TenantAutopilotLog(
        tenant_id=tenant_id,
        source_type="gdrive",
        source_file_id=source_file_id,
        source_file_name=source_file_name,
        content_hash=content_hash,
        batch_id=batch_id,
        trigger=trigger,
        status=status,
    )
    if ingested_at is not None:
        log.ingested_at = ingested_at
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
    """T08: pagination counts RUNS, not files (Gap 427).

    Three runs of two files each: the old per-file endpoint would have reported
    total=6 here. Pagination that counted files was precisely what made the
    screen unreadable, so the count is the assertion that matters.
    """
    base = datetime(2026, 9, 1, 12, 0, 0)
    for i in range(3):
        batch = uuid4()
        for j in range(2):
            _make_log(
                db_session,
                source_file_id=f"file-{i}-{j}",
                content_hash=f"hash{i}{j}",
                status="SUCCESS",
                batch_id=batch,
                trigger="scheduled",
                ingested_at=base + timedelta(hours=i, minutes=j),
            )

    response = client.get("/api/v1/autopilot/history?page=1&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3          # 3 runs, not 6 files
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) == 2
    assert all(item["files_seen"] == 2 for item in data["items"])

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
    with pytest.raises(ValueError, match="No active google_drive connection"):
        run_sync(MOCK_TENANT_ID, db_session)


def test_T12b_run_sync_finds_a_real_google_drive_connection(db_session):
    """T12b (BE Gap 288): the regression this bug needs. A config saying
    source_type='gdrive' must find a connection saved as provider='google_drive'
    -- the two vocabularies are different spellings of the same thing, and
    run_sync() has to translate between them rather than compare directly.
    Before the fix this raised 'No active gdrive connection' even though the
    account genuinely was connected."""
    _make_config(db_session)
    _make_connection(db_session, provider="google_drive")

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=[]):
        summary = run_sync(MOCK_TENANT_ID, db_session)

    # Gap 343 added `quota_exhausted` to the summary; kept as an exact-dict
    # comparison rather than loosened to per-key checks, so a future key added
    # to this contract still has to be acknowledged here.
    assert summary == {
        "processed": 0, "skipped": 0, "failed": 0, "quota_exhausted": False,
    }


def test_T12c_run_sync_rejects_an_unsupported_source_type(db_session):
    """T12c (BE Gap 288): SOURCE_TYPE_TO_PROVIDER.get() returning None (an
    unrecognised source_type slipping past config validation) must read as a
    config error, not silently match zero connections the way the direct
    comparison used to."""
    _make_config(db_session, source_type="dropbox")

    with pytest.raises(ValueError, match="Unsupported Autopilot source_type"):
        run_sync(MOCK_TENANT_ID, db_session)


def test_T12d_run_sync_passes_since_dt_as_modified_after(db_session):
    """T12d (Gap 360): since_dt was computed from the last SUCCESS log and
    logged, but never actually reached list_google_drive_files -- every sync
    re-listed the entire folder from scratch and re-wrote a
    SKIPPED_DUPLICATE row for every already-ingested file, every run,
    forever. This asserts the wiring itself, not just the summary counts,
    because every other test in this file mocks list_google_drive_files
    with return_value= and would stay green even if the argument were
    silently dropped again."""
    _make_config(db_session)
    _make_connection(db_session)
    last_sync = _make_log(
        db_session, source_file_id="gdrive-file-000", content_hash="h0", status="SUCCESS"
    )

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=[]) as mock_list:
        run_sync(MOCK_TENANT_ID, db_session)

    assert mock_list.call_args.kwargs["modified_after"] == last_sync.ingested_at


def test_T12e_run_sync_passes_none_when_no_prior_sync(db_session):
    """T12e (Gap 360): a tenant's first-ever sync has no last-SUCCESS row to
    poll since -- modified_after must be None, not an error and not a
    made-up timestamp that would silently exclude every file."""
    _make_config(db_session)
    _make_connection(db_session)

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=[]) as mock_list:
        run_sync(MOCK_TENANT_ID, db_session)

    assert mock_list.call_args.kwargs["modified_after"] is None


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

    def _fake_run_sync(tenant_id, session, trigger="scheduled"):
        # Gap 427: the scheduled path must label its rows 'scheduled'; asserting
        # it here is what stops the ACA job silently writing 'manual' runs.
        assert trigger == "scheduled"
        call_log.append(tenant_id)
        return {"processed": 0, "skipped": 0, "failed": 0}

    with patch("services.autopilot_sync.run_sync", side_effect=_fake_run_sync):
        run_sync_for_all_due_tenants(db_session)

    assert len(call_log) == 2
    assert set(call_log) == {tenant_a, tenant_b}


def test_T19_autopilot_sends_notify_email_after_import(db_session):
    """BE Gap 220: notify_emails + send_approval_links trigger staff email after sync."""
    from models import TenantEmailSender

    db_session.add(
        TenantEmailSender(
            tenant_id=MOCK_TENANT_ID,
            email_set="inbound",
            email="ops@example.com",
        )
    )
    db_session.commit()

    _make_config(
        db_session,
        notify_emails=["ops@example.com"],
        send_approval_links=True,
    )
    _make_connection(db_session)

    remote_files = [{"id": "file-1", "name": "invoice.pdf", "type": "file", "size_bytes": 100}]
    good_bytes = b"%PDF-1.4 mock"

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=remote_files), \
         patch("services.autopilot_sync.download_google_drive_file", return_value=good_bytes), \
         patch("services.autopilot_sync.upload_pdf_to_blob_storage", return_value="blobs/t/x.pdf"), \
         patch("services.autopilot_sync._dispatch_queue"), \
         patch("services.staff_notify.sendgrid_configured", return_value=True), \
         patch("services.staff_notify.send_email", return_value={"status": "queued"}) as m_send:
        summary = run_sync(MOCK_TENANT_ID, db_session)

    assert summary["processed"] == 1
    m_send.assert_called_once()
    _, kwargs = m_send.call_args
    assert kwargs["to_addresses"] == ["ops@example.com"]
    assert "/invoices/review/" in kwargs["plain_body"]


# ===========================================================================
# BE Gap 334 Postgres checkpoint (functional-tester)
#
# T01-T19 above all run against the in-memory SQLite fixture (autouse
# `override_db_session`). Per CONVENTIONS.md hard rule 2 that alone is not
# sufficient evidence. Mirrors the repo's existing `*_on_postgres` pattern
# (test_auth.py, test_chat_sql_quality.py): skip cleanly if Postgres isn't
# reachable, else bind a session to the real Docker Postgres engine (this
# also genuinely exercises the TenantConnection -> Tenant foreign key, which
# SQLite does not enforce by default and the fixture above never triggers).
# ===========================================================================

def test_run_sync_google_drive_translation_and_unsupported_source_type_on_postgres():
    """BE Gap 334 / Gap 288 Postgres checkpoint: SOURCE_TYPE_TO_PROVIDER still
    correctly translates config source_type='gdrive' to a provider='google_drive'
    connection row (T12b's real-engine counterpart), and an unsupported
    source_type still fails loudly with 'Unsupported Autopilot source_type'
    rather than silently matching (T12c's real-engine counterpart) -- both
    against the real Postgres engine, not the SQLite fixture."""
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

    tenant_id = uuid4()
    with Session(pg_engine) as pg_session:
        pg_session.add(
            Tenant(id=tenant_id, name="PG Checkpoint Tenant", domain=f"pgcheck-{tenant_id.hex[:8]}.com")
        )
        pg_session.commit()

        try:
            _make_config(pg_session, tenant_id=tenant_id)
            _make_connection(pg_session, tenant_id=tenant_id, provider="google_drive")

            with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
                 patch("services.autopilot_sync.list_google_drive_files", return_value=[]):
                summary = run_sync(tenant_id, pg_session)
            # Gap 343 added `quota_exhausted` to the summary contract.
            assert summary == {
                "processed": 0, "skipped": 0, "failed": 0, "quota_exhausted": False,
            }

            # Flip the config to an unsupported source_type and re-verify the
            # loud-failure path on the real engine too.
            config = pg_session.exec(
                select(TenantAutopilotConfig).where(TenantAutopilotConfig.tenant_id == tenant_id)
            ).first()
            config.source_type = "dropbox"
            pg_session.add(config)
            pg_session.commit()

            with pytest.raises(ValueError, match="Unsupported Autopilot source_type"):
                run_sync(tenant_id, pg_session)
        finally:
            # Clean up everything this test wrote, leave the rest of the dev DB alone.
            for log in pg_session.exec(
                select(TenantAutopilotLog).where(TenantAutopilotLog.tenant_id == tenant_id)
            ).all():
                pg_session.delete(log)
            for conn in pg_session.exec(
                select(TenantConnection).where(TenantConnection.tenant_id == tenant_id)
            ).all():
                pg_session.delete(conn)
            for cfg in pg_session.exec(
                select(TenantAutopilotConfig).where(TenantAutopilotConfig.tenant_id == tenant_id)
            ).all():
                pg_session.delete(cfg)
            pg_session.commit()
            tenant_row = pg_session.get(Tenant, tenant_id)
            if tenant_row:
                pg_session.delete(tenant_row)
                pg_session.commit()


# ===========================================================================
# Gap 427 — sync history is a list of RUNS, not a list of files
# ===========================================================================

def _seed_run(db_session, statuses, *, tenant_id=MOCK_TENANT_ID, trigger="scheduled",
              started=None, batch_id=None):
    """Insert one run's worth of log rows and return its batch_id."""
    batch_id = batch_id or uuid4()
    started = started or datetime(2026, 9, 1, 9, 0, 0)
    for idx, st in enumerate(statuses):
        _make_log(
            db_session,
            tenant_id=tenant_id,
            source_file_id=f"{batch_id.hex[:6]}-file-{idx}",
            content_hash=f"{batch_id.hex[:6]}{idx}",
            status=st,
            batch_id=batch_id,
            trigger=trigger,
            source_file_name=f"invoice-{idx}.pdf",
            ingested_at=started + timedelta(seconds=idx),
        )
    return batch_id


def test_T20a_history_groups_rows_into_runs_newest_first(db_session):
    """T20a: rows collapse into one item per batch_id, newest run first, with
    per-run totals derived from the file rows."""
    older = _seed_run(
        db_session, ["SUCCESS", "SKIPPED_DUPLICATE"],
        trigger="scheduled", started=datetime(2026, 9, 1, 8, 0, 0),
    )
    newer = _seed_run(
        db_session, ["SUCCESS", "SUCCESS", "FAILED"],
        trigger="manual", started=datetime(2026, 9, 1, 10, 0, 0),
    )

    data = client.get("/api/v1/autopilot/history").json()
    assert data["total"] == 2
    assert [item["batch_id"] for item in data["items"]] == [str(newer), str(older)]

    first, second = data["items"]
    assert first["trigger"] == "manual"
    assert (first["files_seen"], first["imported"], first["skipped"], first["failed"]) == (3, 2, 0, 1)
    assert first["source_type"] == "gdrive"
    # started_at/finished_at bracket the run rather than both being one row's time
    assert first["started_at"] < first["finished_at"]

    assert second["trigger"] == "scheduled"
    assert (second["files_seen"], second["imported"], second["skipped"], second["failed"]) == (2, 1, 1, 0)


def test_T20b_run_status_derivation(db_session):
    """T20b: every run-status rule, each on its own run."""
    cases = {
        "all_success": (["SUCCESS", "SUCCESS"], "SUCCESS"),
        "mixed": (["SUCCESS", "FAILED"], "PARTIAL"),
        "skip_plus_fail": (["SKIPPED_DUPLICATE", "FAILED"], "PARTIAL"),
        "all_failed": (["FAILED", "FAILED"], "FAILED"),
        # Dedup working correctly is not a failure and not an empty run.
        "all_skipped": (["SKIPPED_DUPLICATE", "SKIPPED_DUPLICATE"], "SUCCESS"),
    }
    expected = {}
    for offset, (name, (statuses, want)) in enumerate(cases.items()):
        batch = _seed_run(
            db_session, statuses,
            started=datetime(2026, 9, 1, 8, 0, 0) + timedelta(hours=offset),
        )
        expected[str(batch)] = want

    data = client.get("/api/v1/autopilot/history").json()
    assert data["total"] == len(cases)
    got = {item["batch_id"]: item["status"] for item in data["items"]}
    assert got == expected

    # An all-skipped run is SUCCESS but must still report imported 0 -- the
    # status alone would otherwise read as "2 invoices imported".
    all_skipped = [i for i in data["items"] if i["skipped"] == 2][0]
    assert all_skipped["imported"] == 0 and all_skipped["files_seen"] == 2


def test_T20c_no_new_files_run_is_visible_with_zero_files(db_session):
    """T20c: an empty run still appears, as NO_NEW_FILES with files_seen 0.

    The marker row is not a file, so counting it as one would make the UI claim
    a run processed a file it never saw.
    """
    batch = uuid4()
    _make_log(
        db_session, source_file_id="", content_hash="", status="NO_NEW_FILES",
        batch_id=batch, trigger="manual",
    )

    data = client.get("/api/v1/autopilot/history").json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["status"] == "NO_NEW_FILES"
    assert item["files_seen"] == 0
    assert (item["imported"], item["skipped"], item["failed"]) == (0, 0, 0)
    assert item["trigger"] == "manual"


def test_T20d_legacy_rows_collapse_into_one_bucket_ordered_last(db_session):
    """T20d: pre-Gap-427 rows (batch_id IS NULL) become ONE synthetic item,
    always last, no matter how many of them there are."""
    # Three legacy rows, timestamped NEWER than the real run, to prove the
    # bucket is pinned last by rule and not merely by its timestamps.
    for i in range(3):
        _make_log(
            db_session, source_file_id=f"legacy-{i}", content_hash=f"lh{i}",
            status="SUCCESS" if i < 2 else "FAILED",
            ingested_at=datetime(2026, 9, 2, 12, 0, i),
        )
    real = _seed_run(db_session, ["SUCCESS"], started=datetime(2026, 9, 1, 8, 0, 0))

    data = client.get("/api/v1/autopilot/history").json()
    assert data["total"] == 2          # 1 real run + 1 legacy bucket, not 4
    assert [i["batch_id"] for i in data["items"]] == [str(real), None]

    legacy = data["items"][-1]
    assert legacy["trigger"] is None
    assert (legacy["files_seen"], legacy["imported"], legacy["failed"]) == (3, 2, 1)
    assert legacy["status"] == "PARTIAL"


def test_T20d2_legacy_bucket_lands_on_the_last_page_only(db_session):
    """T20d2: the bucket occupies exactly one slot in the paged ordering -- it
    is not repeated on every page and not dropped off the end."""
    for i in range(2):
        _make_log(db_session, source_file_id=f"legacy-{i}", content_hash=f"lh{i}")
    for offset in range(2):
        _seed_run(db_session, ["SUCCESS"],
                  started=datetime(2026, 9, 1, 8, 0, 0) + timedelta(hours=offset))

    page1 = client.get("/api/v1/autopilot/history?page=1&page_size=2").json()
    page2 = client.get("/api/v1/autopilot/history?page=2&page_size=2").json()

    assert page1["total"] == 3 and page2["total"] == 3
    assert len(page1["items"]) == 2
    assert all(i["batch_id"] is not None for i in page1["items"])
    assert [i["batch_id"] for i in page2["items"]] == [None]


def test_T20e_run_files_endpoint_and_tenant_isolation(db_session):
    """T20e: the drill-down returns that run's files with readable names, and
    another tenant's batch_id is a 404 -- not a leak, and not an empty 200."""
    batch = _seed_run(db_session, ["SUCCESS", "FAILED"])

    resp = client.get(f"/api/v1/autopilot/history/{batch}/files")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert {i["source_file_name"] for i in items} == {"invoice-0.pdf", "invoice-1.pdf"}
    assert all("source_file_id" in i and "content_hash" in i for i in items)

    # A run belonging to a different tenant must not be readable by this caller.
    other_tenant = uuid4()
    db_session.add(Tenant(id=other_tenant, name="Other", domain=f"other-{other_tenant.hex[:8]}.com"))
    db_session.commit()
    other_batch = _seed_run(db_session, ["SUCCESS"], tenant_id=other_tenant)

    cross = client.get(f"/api/v1/autopilot/history/{other_batch}/files")
    assert cross.status_code == 404

    # ...and an id that exists nowhere behaves identically, so the 404 cannot be
    # used to probe which run ids are real.
    assert client.get(f"/api/v1/autopilot/history/{uuid4()}/files").status_code == 404

    # The other tenant's run must not appear in this caller's run list either.
    listed = client.get("/api/v1/autopilot/history").json()
    assert [i["batch_id"] for i in listed["items"]] == [str(batch)]


def test_T20f_legacy_files_endpoint_is_tenant_scoped(db_session):
    """T20f: /history/legacy/files returns only the caller's own legacy rows."""
    _make_log(db_session, source_file_id="mine-1", content_hash="m1")

    other_tenant = uuid4()
    db_session.add(Tenant(id=other_tenant, name="Other2", domain=f"o2-{other_tenant.hex[:8]}.com"))
    db_session.commit()
    _make_log(db_session, tenant_id=other_tenant, source_file_id="theirs-1", content_hash="t1")

    resp = client.get("/api/v1/autopilot/history/legacy/files")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["source_file_id"] for i in items] == ["mine-1"]


def test_T20g_run_sync_stamps_run_identity_and_logs_empty_runs(db_session):
    """T20g: the write side. Every row a run writes carries that run's batch_id,
    its trigger and the human-readable file name; a run that finds nothing
    writes exactly one NO_NEW_FILES row so it is still visible in history."""
    _make_config(db_session)
    _make_connection(db_session)

    remote = [{"id": "drive-file-1", "name": "ACME March.pdf", "type": "file", "size_bytes": 10}]
    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=remote), \
         patch("services.autopilot_sync.download_google_drive_file", return_value=b"pdf-bytes"), \
         patch("services.autopilot_sync.upload_pdf_to_blob_storage", return_value="path/x.pdf"), \
         patch("services.autopilot_sync.charge_free_quota"), \
         patch("services.autopilot_sync._dispatch_queue"):
        summary = run_sync(MOCK_TENANT_ID, db_session, trigger="manual")

    assert summary["processed"] == 1
    logs = db_session.exec(
        select(TenantAutopilotLog).where(TenantAutopilotLog.tenant_id == MOCK_TENANT_ID)
    ).all()
    assert len(logs) == 1
    assert logs[0].batch_id is not None
    assert logs[0].trigger == "manual"
    assert logs[0].source_file_name == "ACME March.pdf"
    first_batch = logs[0].batch_id

    # Second run: nothing new upstream -> one NO_NEW_FILES marker, its own batch.
    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=[]):
        run_sync(MOCK_TENANT_ID, db_session, trigger="scheduled")

    markers = db_session.exec(
        select(TenantAutopilotLog).where(
            TenantAutopilotLog.tenant_id == MOCK_TENANT_ID,
            TenantAutopilotLog.status == "NO_NEW_FILES",
        )
    ).all()
    assert len(markers) == 1
    assert markers[0].source_file_id == ""
    assert markers[0].trigger == "scheduled"
    assert markers[0].batch_id is not None and markers[0].batch_id != first_batch

    # Both runs are visible, and the marker run did not become a fake file.
    data = client.get("/api/v1/autopilot/history").json()
    assert data["total"] == 2
    by_status = {i["status"]: i for i in data["items"]}
    assert by_status["NO_NEW_FILES"]["files_seen"] == 0
    assert by_status["SUCCESS"]["imported"] == 1


def test_gap_427_run_grouping_on_postgres():
    """Gap 427 Postgres checkpoint (CONVENTIONS hard rule 2).

    The rest of this file drives the API over the SQLite fixture, which is fine
    for the derivation rules but proves nothing about the SQL that produces
    them: the runs endpoint is the first place in this router to use GROUP BY
    with SUM(CASE ...) and COUNT(DISTINCT ...), and SQLite is far more forgiving
    than Postgres about aggregate/grouping shape. This exercises the real query
    against the real engine.

    The handlers are called directly rather than through TestClient because the
    TestClient's session dependency is pinned to the SQLite fixture for the
    whole module; the query under test is inside the handler either way.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings
    from dependencies import TenantContext
    from routers.autopilot import get_autopilot_history, get_run_files, get_legacy_run_files

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)

    tenant_id = uuid4()
    other_id = uuid4()
    with Session(pg_engine) as pg:
        pg.add(Tenant(id=tenant_id, name="PG 427", domain=f"pg427-{tenant_id.hex[:8]}.com"))
        pg.add(Tenant(id=other_id, name="PG 427 Other", domain=f"pg427o-{other_id.hex[:8]}.com"))
        pg.commit()

        ctx = TenantContext(
            tenant_id=tenant_id, user_id="pg-427-user", role="Admin", billing_plan="free",
        )

        try:
            partial = _seed_run(pg, ["SUCCESS", "FAILED"], tenant_id=tenant_id,
                                trigger="manual", started=datetime(2026, 9, 1, 10, 0, 0))
            skipped_only = _seed_run(pg, ["SKIPPED_DUPLICATE"], tenant_id=tenant_id,
                                     started=datetime(2026, 9, 1, 9, 0, 0))
            # Legacy rows for this tenant, plus another tenant's run that must
            # never appear in either result.
            _make_log(pg, tenant_id=tenant_id, source_file_id="pg-legacy",
                      content_hash="pgl", ingested_at=datetime(2026, 9, 1, 8, 0, 0))
            foreign = _seed_run(pg, ["SUCCESS"], tenant_id=other_id)

            result = get_autopilot_history(page=1, page_size=50, context=ctx, db_session=pg)
            assert result.total == 3   # 2 runs + 1 legacy bucket
            assert [i.batch_id for i in result.items] == [str(partial), str(skipped_only), None]
            assert [i.status for i in result.items] == ["PARTIAL", "SUCCESS", "SUCCESS"]
            assert result.items[0].files_seen == 2
            assert (result.items[0].imported, result.items[0].failed) == (1, 1)
            assert result.items[0].trigger == "manual"
            assert result.items[1].imported == 0 and result.items[1].skipped == 1

            files = get_run_files(batch_id=partial, context=ctx, db_session=pg)
            assert len(files.items) == 2
            assert all(f.source_file_name for f in files.items)

            legacy_files = get_legacy_run_files(context=ctx, db_session=pg)
            assert [f.source_file_id for f in legacy_files.items] == ["pg-legacy"]

            # Cross-tenant read is a 404 on the real engine too.
            with pytest.raises(HTTPException) as exc_info:
                get_run_files(batch_id=foreign, context=ctx, db_session=pg)
            assert exc_info.value.status_code == 404
        finally:
            for t in (tenant_id, other_id):
                for log in pg.exec(
                    select(TenantAutopilotLog).where(TenantAutopilotLog.tenant_id == t)
                ).all():
                    pg.delete(log)
                pg.commit()
                row = pg.get(Tenant, t)
                if row:
                    pg.delete(row)
                    pg.commit()
