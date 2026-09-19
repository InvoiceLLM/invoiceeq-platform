"""Tests for BE Gap 681 (EX-24): PDF uploads have no page-count ceiling.

Verifies:
1. Default settings: MAX_PDF_PAGES = 50, SHADOW_MODE_MAX_PDF_PAGES = False.
2. Direct PDF upload at ceiling passes; ceiling + 1 is refused with HTTP 400 / PdfTooManyPagesError.
3. Error message explicitly names both the document's actual page count and the limit.
4. Error inherits from UnsupportedUploadError for seamless backwards compatibility.
5. Multi-frame TIFFs are checked AFTER conversion and rejected if frame count exceeds ceiling.
6. Shadow mode logs a structured warning and allows the upload through without raising.
7. Unparseable mock stubs pass through without crashing fitz.
8. Inbound, outbound, and trainer routers return HTTP 400 with detail.
9. Zero false rejections: all 68 real PDFs across the repository pass normalize_upload().
"""

import io
import logging
import os
import pathlib
from unittest.mock import patch, MagicMock
from uuid import uuid4

import fitz
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from config import settings
from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant
from services.file_intake import (
    ImageTooLargeError,
    NormalizedUpload,
    PdfTooManyPagesError,
    UnsupportedUploadError,
    normalize_upload,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed mock tenant so auth & quotas resolve against in-memory SQLite
        tenant = Tenant(
            id=MOCK_TENANT_ID,
            name="Test Tenant",
            domain="test.example.com",
            billing_plan="pro",
            billing_status="active",
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


def _make_synthetic_pdf(pages: int) -> bytes:
    """Create a minimal valid PDF with exact number of pages."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=100, height=100)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _make_synthetic_tiff(frames: int) -> bytes:
    """Create a multi-frame TIFF image."""
    imgs = [Image.new("RGB", (20, 20), color=(i * 2, i * 2, i * 2)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="TIFF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


# ── Configuration Defaults ───────────────────────────────────────────────────

def test_settings_have_gap681_defaults():
    assert hasattr(settings, "MAX_PDF_PAGES")
    assert settings.MAX_PDF_PAGES == 50
    assert hasattr(settings, "SHADOW_MODE_MAX_PDF_PAGES")
    assert settings.SHADOW_MODE_MAX_PDF_PAGES is False


# ── Direct PDF Page Ceiling ──────────────────────────────────────────────────

def test_pdf_at_ceiling_passes_under_custom_limit():
    pdf_bytes = _make_synthetic_pdf(10)
    result = normalize_upload("ten_page.pdf", pdf_bytes, max_pages=10)
    assert isinstance(result, NormalizedUpload)
    assert result.pdf_bytes == pdf_bytes
    assert result.was_converted is False
    assert result.pdf_filename == "ten_page.pdf"


def test_pdf_above_ceiling_raises_with_both_numbers():
    pdf_bytes = _make_synthetic_pdf(11)
    with pytest.raises(PdfTooManyPagesError) as exc_info:
        normalize_upload("eleven_page.pdf", pdf_bytes, max_pages=10)

    err = exc_info.value
    assert err.page_count == 11
    assert err.max_pages == 10
    assert err.filename == "eleven_page.pdf"
    assert "11 pages" in err.detail
    assert "limit of 10 pages" in err.detail


def test_pdf_at_default_ceiling_passes():
    pdf_bytes = _make_synthetic_pdf(50)
    result = normalize_upload("fifty_page.pdf", pdf_bytes)
    assert result.pdf_bytes == pdf_bytes
    assert result.was_converted is False


def test_pdf_at_default_ceiling_plus_one_raises():
    pdf_bytes = _make_synthetic_pdf(51)
    with pytest.raises(PdfTooManyPagesError) as exc_info:
        normalize_upload("fifty_one_page.pdf", pdf_bytes)

    err = exc_info.value
    assert err.page_count == 51
    assert err.max_pages == 50
    assert "51 pages" in err.detail
    assert "limit of 50 pages" in err.detail


def test_pdf_error_is_unsupported_upload_subclass():
    assert issubclass(PdfTooManyPagesError, UnsupportedUploadError)
    err = PdfTooManyPagesError(page_count=60, max_pages=50, filename="test.pdf")
    assert isinstance(err, UnsupportedUploadError)
    assert isinstance(err, Exception)
    assert err.detail == "Document 'test.pdf' has 60 pages, exceeding the maximum allowed limit of 50 pages."


# ── Multi-frame TIFF Post-Conversion Ceiling ─────────────────────────────────

def test_multiframe_tiff_at_ceiling_converts_and_passes():
    tiff_bytes = _make_synthetic_tiff(5)
    result = normalize_upload("five_frame.tiff", tiff_bytes, max_pages=5)
    assert isinstance(result, NormalizedUpload)
    assert result.was_converted is True
    assert result.pdf_filename == "five_frame.pdf"

    # Verify resulting PDF has 5 pages
    doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    assert doc.page_count == 5
    doc.close()


def test_multiframe_tiff_above_ceiling_rejected_after_conversion():
    tiff_bytes = _make_synthetic_tiff(6)
    with pytest.raises(PdfTooManyPagesError) as exc_info:
        normalize_upload("six_frame.tiff", tiff_bytes, max_pages=5)

    err = exc_info.value
    assert err.page_count == 6
    assert err.max_pages == 5
    assert "six_frame.tiff" in err.detail
    assert "6 pages" in err.detail
    assert "limit of 5 pages" in err.detail


# ── Shadow Mode ──────────────────────────────────────────────────────────────

def test_shadow_mode_logs_warning_and_permits_document(caplog):
    pdf_bytes = _make_synthetic_pdf(15)
    with caplog.at_level(logging.WARNING):
        result = normalize_upload("monster.pdf", pdf_bytes, max_pages=10, shadow_mode=True)

    assert result.pdf_bytes == pdf_bytes
    assert result.pdf_filename == "monster.pdf"
    assert any("PDF page ceiling exceeded in shadow mode" in r.message for r in caplog.records)
    assert any("has 15 pages (limit: 10)" in r.message for r in caplog.records)


# ── Graceful Mock Stub Handling ──────────────────────────────────────────────

def test_unparseable_pdf_bytes_handled_gracefully():
    # Unit tests often pass mock strings like b"%PDF-1.4 test invoice content"
    result = normalize_upload("mock.pdf", b"%PDF-1.4 test stub")
    assert result.pdf_bytes == b"%PDF-1.4 test stub"
    assert result.pdf_filename == "mock.pdf"
    assert result.was_converted is False


# ── Corpus Verification: Zero False Rejections ───────────────────────────────

def test_zero_false_rejections_across_all_repo_pdf_fixtures():
    """Verify that all 68 PDFs in the repository pass normalize_upload without being rejected."""
    be_dir = pathlib.Path(__file__).parent.parent
    valid_pdfs = []
    for pdf_path in be_dir.rglob("*.pdf"):
        if ".venv" in pdf_path.parts:
            continue
        try:
            doc = fitz.open(str(pdf_path))
            count = doc.page_count
            doc.close()
            valid_pdfs.append((pdf_path, count))
        except Exception:
            continue

    assert len(valid_pdfs) >= 68, f"Expected at least 68 PDFs in repo, found {len(valid_pdfs)}"

    for path, count in valid_pdfs:
        content = path.read_bytes()
        res = normalize_upload(path.name, content)
        assert isinstance(res, NormalizedUpload)
        assert res.pdf_bytes.startswith(b"%PDF"), f"Fixture {path.name} failed to produce PDF bytes!"


# ── Router Integration Tests ─────────────────────────────────────────────────

def test_inbound_upload_rejects_oversized_pdf():
    pdf_bytes = _make_synthetic_pdf(51)
    client = TestClient(app)

    # Patch dependencies/helpers to isolate endpoint behavior
    with patch("routers.invoices.upload_pdf_to_blob_storage"), \
         patch("routers.invoices.QueueClient"):
        response = client.post(
            "/api/v1/invoices/upload",
            files={"files": ("large_invoice.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert "detail" in data
    assert "51 pages" in data["detail"]
    assert "limit of 50 pages" in data["detail"]


def test_outbound_upload_rejects_oversized_pdf():
    pdf_bytes = _make_synthetic_pdf(51)
    client = TestClient(app)

    with patch("routers.outbound_invoices.upload_pdf_to_blob_storage"), \
         patch("routers.outbound_invoices.QueueClient"):
        response = client.post(
            "/api/v1/outbound-invoices/upload",
            files={"file": ("large_outbound.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert "detail" in data
    assert "51 pages" in data["detail"]
    assert "limit of 50 pages" in data["detail"]


def test_trainer_upload_rejects_oversized_pdf():
    pdf_bytes = _make_synthetic_pdf(51)
    client = TestClient(app)

    with patch("routers.trainer._run_ocr", return_value="Mock OCR"), \
         patch("routers.trainer.QueueClient"):
        response = client.post(
            "/api/v1/trainer/upload",
            files={"file": ("large_sample.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert "detail" in data
    assert "51 pages" in data["detail"]
    assert "limit of 50 pages" in data["detail"]
