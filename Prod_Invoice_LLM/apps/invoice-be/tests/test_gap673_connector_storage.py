"""Tests for BE Gap 673: Eliminate ephemeral local disk fallback on blob upload failure.

Verifies:
1. is_storage_configured correctly detects configured vs unconfigured/placeholder storage.
2. In production with unconfigured storage, upload_pdf_to_blob_storage raises StorageUploadError (fail-closed).
3. In non-production with unconfigured storage, offline dev local fallback is allowed.
4. When Azure storage is configured and upload fails after retries, StorageUploadError is raised
   and NO file is written to local disk (never strands files in ephemeral container disk).
5. Connector import handler (handle_import_connector_file) fails fast on StorageUploadError,
   saving NO orphan Invoice row and enqueuing NO extraction message.
6. Routers (/invoices/upload, /outbound/invoices/upload, /chat/sessions/.../attachments) return HTTP 503
   with "File storage is temporarily unavailable. Nothing was saved. Try again." and save NO rows (Decision D3).
"""
import os
import shutil
import tempfile
import pytest
from uuid import uuid4, UUID
from unittest.mock import patch, MagicMock
from sqlmodel import Session, select
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, ChatAttachment, ChatSession, Tenant
from services.storage import (
    upload_pdf_to_blob_storage,
    is_storage_configured,
    StorageUploadError,
    LOCAL_STORAGE_DIR,
)
from config import settings
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: F401  (pytest fixture)

client = TestClient(app)


# The "no row was saved" checks are persistence claims, so they run on Postgres only
# (CONVENTIONS hard rule 2); the pure storage-helper tests below need no database.
@pytest.fixture(name="db_session")
def db_session_fixture(pg_engine):
    with Session(pg_engine) as session:
        def get_db_session_override():
            yield session
        app.dependency_overrides[get_db_session] = get_db_session_override
        with patch("queue_worker.handlers.engine", pg_engine), patch("routers.invoices.engine", pg_engine):
            yield session
        app.dependency_overrides.clear()


# ===========================================================================
# 1. Storage Configuration Tests
# ===========================================================================

def test_is_storage_configured():
    with patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", ""):
        assert is_storage_configured() is False

    with patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "   "):
        assert is_storage_configured() is False

    with patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=your_azure_storage_account;AccountKey=xxx"):
        assert is_storage_configured() is False

    with patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "<your-connection-string>"):
        assert is_storage_configured() is False

    with patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=stinvoicellm;AccountKey=validkey;EndpointSuffix=core.windows.net"):
        assert is_storage_configured() is True

    with patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true"):
        assert is_storage_configured() is True


# ===========================================================================
# 2. Pure Unit Tests for upload_pdf_to_blob_storage
# ===========================================================================

def test_unconfigured_storage_in_production_fails_closed(monkeypatch):
    """In production, unconfigured storage must fail loudly (never fall back to container disk)."""
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with pytest.raises(StorageUploadError) as exc_info:
        upload_pdf_to_blob_storage(b"%PDF dummy", str(uuid4()), str(uuid4()))

    assert "not configured in production environment" in str(exc_info.value)


def test_unconfigured_storage_in_non_production_allows_local_fallback(monkeypatch, tmp_path):
    """In non-production (dev/test), unconfigured storage writes locally for offline development."""
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")

    test_storage_dir = str(tmp_path / "temp_storage")
    monkeypatch.setattr("services.storage.LOCAL_STORAGE_DIR", test_storage_dir)

    tenant_id = str(uuid4())
    invoice_id = str(uuid4())
    pdf_bytes = b"%PDF dummy content for offline dev"

    result_path = upload_pdf_to_blob_storage(pdf_bytes, tenant_id, invoice_id)

    assert result_path.startswith(test_storage_dir)
    assert os.path.exists(result_path)
    with open(result_path, "rb") as f:
        assert f.read() == pdf_bytes


@patch("azure.storage.blob.BlobServiceClient")
def test_configured_storage_upload_success(mock_bsc, monkeypatch):
    """When Azure storage is configured and succeeds, returns azure:// URI."""
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    mock_client_instance = MagicMock()
    mock_bsc.from_connection_string.return_value = mock_client_instance
    mock_container = MagicMock()
    mock_client_instance.get_container_client.return_value = mock_container
    mock_blob = MagicMock()
    mock_client_instance.get_blob_client.return_value = mock_blob

    tenant_id = str(uuid4())
    invoice_id = str(uuid4())
    pdf_bytes = b"%PDF dummy uploaded"

    result = upload_pdf_to_blob_storage(pdf_bytes, tenant_id, invoice_id)

    assert result == f"azure://invoices/tenants/{tenant_id}/invoices/{invoice_id}.pdf"
    mock_blob.upload_blob.assert_called_once_with(pdf_bytes, overwrite=True)


@patch("azure.storage.blob.BlobServiceClient")
def test_configured_storage_failure_raises_storage_upload_error_no_local_write(mock_bsc, monkeypatch, tmp_path):
    """Gap 673 core requirement: When Azure storage is configured but fails,
    it must raise StorageUploadError and NEVER write to local container disk."""
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    test_storage_dir = str(tmp_path / "temp_storage")
    monkeypatch.setattr("services.storage.LOCAL_STORAGE_DIR", test_storage_dir)

    mock_bsc.from_connection_string.side_effect = RuntimeError("Azure Storage connection timeout / network down")

    tenant_id = str(uuid4())
    invoice_id = str(uuid4())
    pdf_bytes = b"%PDF dummy content"

    with pytest.raises(StorageUploadError) as exc_info:
        upload_pdf_to_blob_storage(pdf_bytes, tenant_id, invoice_id)

    assert "Azure Blob Storage upload failed" in str(exc_info.value)
    assert not os.path.exists(test_storage_dir) or os.listdir(test_storage_dir) == []


# ===========================================================================
# 3. Connector Import Handler (handle_import_connector_file)
# ===========================================================================

@pg_only
@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers._enqueue_process_invoice")
def test_connector_import_storage_failure_raises_and_creates_no_invoice(mock_enqueue, mock_bsc, monkeypatch, db_session):
    """Gap 673: Inbound connector import fails fast when storage fails:
    1. Raises StorageUploadError
    2. Does NOT persist an orphan Invoice row in the database
    3. Does NOT enqueue a message for extraction
    """
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    mock_bsc.from_connection_string.side_effect = Exception("Storage unreachable")

    from queue_worker.handlers import handle_import_connector_file

    tenant_id = str(MOCK_TENANT_ID)
    file_id = "test_doc_gap673"

    with pytest.raises(StorageUploadError):
        handle_import_connector_file(
            provider="google_drive",
            file_id=file_id,
            tenant_id=tenant_id,
            direction="inbound",
            db_session=db_session,
        )

    # Invariant: No Invoice row was persisted
    invoices = db_session.exec(select(Invoice)).all()
    assert len(invoices) == 0

    # Invariant: No message was enqueued
    mock_enqueue.assert_not_called()


@pg_only
@patch("azure.storage.blob.BlobServiceClient")
@patch("queue_worker.handlers._enqueue_process_invoice", return_value=True)
def test_connector_import_storage_success_persists_invoice_and_enqueues(mock_enqueue, mock_bsc, monkeypatch, db_session):
    """When storage succeeds, connector import persists invoice with azure:// path and enqueues."""
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    mock_client_instance = MagicMock()
    mock_bsc.from_connection_string.return_value = mock_client_instance
    mock_container = MagicMock()
    mock_client_instance.get_container_client.return_value = mock_container
    mock_blob = MagicMock()
    mock_client_instance.get_blob_client.return_value = mock_blob

    from queue_worker.handlers import handle_import_connector_file

    tenant_id = str(MOCK_TENANT_ID)
    file_id = "test_doc_success"

    result = handle_import_connector_file(
        provider="google_drive",
        file_id=file_id,
        tenant_id=tenant_id,
        direction="inbound",
        db_session=db_session,
    )

    assert result["success"] is True
    assert result["blob_path"].startswith("azure://invoices/tenants/")

    # Invariant: Invoice row was persisted with azure path
    invoice = db_session.get(Invoice, UUID(result["invoice_id"]))
    assert invoice is not None
    assert invoice.file_path == result["blob_path"]
    assert invoice.status == "PROCESSING"

    # Invariant: Extraction was enqueued
    mock_enqueue.assert_called_once()


# ===========================================================================
# 4. Router Endpoints Fail Fast with HTTP 503 (Decision D3)
# ===========================================================================

@pg_only
def test_invoice_upload_storage_failure_returns_503_and_saves_no_row(monkeypatch, db_session):
    """Decision D3: When file upload to storage fails, return HTTP 503 and save NO Invoice row."""
    with patch("routers.invoices.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Storage down")):
        files = [("files", ("test_invoice.pdf", b"%PDF-1.4 sample content", "application/pdf"))]
        response = client.post("/api/v1/invoices/upload", files=files)

        assert response.status_code == 503
        assert "File storage is temporarily unavailable. Nothing was saved. Try again." in response.json()["detail"]

    # Verify no Invoice row was saved in the database
    invoices = db_session.exec(select(Invoice)).all()
    assert len(invoices) == 0


@pg_only
def test_outbound_invoice_upload_storage_failure_returns_503_and_saves_no_row(monkeypatch, db_session):
    """Outbound upload returns HTTP 503 and saves NO Invoice row when storage fails."""
    tenant = db_session.get(Tenant, MOCK_TENANT_ID)
    if not tenant:
        tenant = Tenant(
            id=MOCK_TENANT_ID,
            name="Test Tenant",
            domain="testtenant.com",
            billing_plan="pro",
            send_invoices_enabled=True,
        )
        db_session.add(tenant)
        db_session.commit()
    else:
        tenant.send_invoices_enabled = True
        db_session.add(tenant)
        db_session.commit()

    with patch("routers.outbound_invoices.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Storage down")):
        files = {"file": ("outbound_inv.pdf", b"%PDF-1.4 sample content", "application/pdf")}
        response = client.post("/api/v1/outbound-invoices/upload", files=files)

        assert response.status_code == 503
        assert "File storage is temporarily unavailable. Nothing was saved. Try again." in response.json()["detail"]

    invoices = db_session.exec(select(Invoice).where(Invoice.flow_direction == "OUTBOUND")).all()
    assert len(invoices) == 0


@pg_only
def test_chat_attachment_storage_failure_returns_503_and_saves_no_row(monkeypatch, db_session):
    """Chat attachment upload returns HTTP 503 and creates NO ChatAttachment row when storage fails."""
    session_id = uuid4()
    chat_sess = ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="Test Chat")
    db_session.add(chat_sess)
    db_session.commit()

    with patch("services.storage.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Storage down")):
        files = {"file": ("reference_doc.pdf", b"%PDF-1.4 sample content", "application/pdf")}
        response = client.post(f"/api/v1/chat/sessions/{session_id}/attachments", files=files)

        assert response.status_code == 503
        assert "File storage is temporarily unavailable. Nothing was saved. Try again." in response.json()["detail"]

    attachments = db_session.exec(select(ChatAttachment)).all()
    assert len(attachments) == 0


@pg_only
def test_outbound_email_pdf_storage_failure_returns_503_and_saves_no_row(db_session):
    """The email door: an outbound email attachment whose storage upload fails raises 503
    (so the caller records the dropped email and the mail provider can retry) and saves
    NO Invoice row."""
    import asyncio

    from fastapi import HTTPException

    from dependencies import TenantContext
    from routers.email_ingestion import _ingest_outbound_email_pdf

    tenant = Tenant(id=MOCK_TENANT_ID, name="Email Tenant", domain="email-tenant.test",
                    billing_plan="pro", send_invoices_enabled=True)
    db_session.add(tenant)
    db_session.commit()
    context = TenantContext(tenant_id=MOCK_TENANT_ID, user_id="email", role="Admin", billing_plan="pro")

    with patch("routers.email_ingestion.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Storage down")):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_ingest_outbound_email_pdf(
                file_bytes=b"%PDF-1.4 sample", filename="emailed.pdf", tenant=tenant,
                context=context, db_session=db_session, batch_id=uuid4(),
            ))

    assert exc_info.value.status_code == 503
    assert "Nothing was saved" in exc_info.value.detail
    assert db_session.exec(select(Invoice)).all() == []
