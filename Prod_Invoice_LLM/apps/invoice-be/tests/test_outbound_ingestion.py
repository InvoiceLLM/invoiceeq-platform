"""Tests for Feature 2.1 (Outbound Invoice Ingestion): the upload/confirm-send
endpoints (routers/outbound_invoices.py) and the queue handler
(queue_worker/outbound_handlers.py). Mirrors test_ingestion.py/test_extraction.py's
conventions -- mock storage/queue/OCR/LLM at the module boundary."""
import io
import pytest
from unittest.mock import patch
from uuid import uuid4, UUID

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, Tenant, ExtractionTemplate

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

client = TestClient(app)


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


def _seed_tenant(db_session, send_invoices_enabled: bool = True) -> Tenant:
    tenant = Tenant(
        id=MOCK_TENANT_ID, name="Test Workspace", domain="test.example.com",
        billing_plan="pro_combined", send_invoices_enabled=send_invoices_enabled,
        outbound_sender_email="ar@test.example.com",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# ── Upload endpoint ───────────────────────────────────────────────────────────

def test_upload_rejected_when_send_invoices_disabled(db_session):
    _seed_tenant(db_session, send_invoices_enabled=False)
    files = {"file": ("out1.pdf", io.BytesIO(b"%PDF-1.4 mock"), "application/pdf")}
    response = client.post("/api/v1/outbound-invoices/upload", files=files)
    assert response.status_code == 403


def test_upload_succeeds_when_enabled(db_session):
    _seed_tenant(db_session, send_invoices_enabled=True)
    files = {"file": ("out1.pdf", io.BytesIO(b"%PDF-1.4 mock"), "application/pdf")}

    with patch("routers.outbound_invoices.upload_pdf_to_blob_storage", return_value="mock/path/out1.pdf"), \
         patch("routers.outbound_invoices.QueueClient") as mock_queue_cls:
        mock_queue = mock_queue_cls.from_connection_string.return_value
        response = client.post("/api/v1/outbound-invoices/upload", files=files)

    assert response.status_code == 201
    data = response.json()
    invoice = db_session.get(Invoice, UUID(data["invoice_id"]))
    assert invoice.flow_direction == "OUTBOUND"
    assert invoice.status == "UPLOADED"
    assert invoice.file_path == "mock/path/out1.pdf"
    mock_queue.send_message.assert_called_once()


def test_upload_rejects_non_pdf(db_session):
    _seed_tenant(db_session)
    files = {"file": ("out1.txt", io.BytesIO(b"not a pdf"), "text/plain")}
    response = client.post("/api/v1/outbound-invoices/upload", files=files)
    assert response.status_code == 400


# ── Confirm-send endpoint ─────────────────────────────────────────────────────

def test_confirm_send_from_verified(db_session):
    _seed_tenant(db_session)
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="VERIFIED"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-invoices/{invoice_id}/confirm-send")
    assert response.status_code == 200
    assert response.json()["status"] == "SENT"

    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.status == "SENT"
    assert invoice.sent_at is not None


def test_confirm_send_from_needs_review_allowed(db_session):
    """A corrected NEEDS_REVIEW invoice can still be confirmed -- the outbound
    Auditor's job is correcting it first, not blocking confirm-send forever."""
    _seed_tenant(db_session)
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="NEEDS_REVIEW"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-invoices/{invoice_id}/confirm-send")
    assert response.status_code == 200


def test_confirm_send_rejects_wrong_status(db_session):
    _seed_tenant(db_session)
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="SENT"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-invoices/{invoice_id}/confirm-send")
    assert response.status_code == 400


def test_confirm_send_tenant_isolation(db_session):
    _seed_tenant(db_session)
    other_tenant = uuid4()
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=other_tenant, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="VERIFIED"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-invoices/{invoice_id}/confirm-send")
    assert response.status_code == 404


# ── Mark-paid endpoint ─────────────────────────────────────────────────────────

def test_mark_paid_from_sent(db_session):
    _seed_tenant(db_session)
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="SENT"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-invoices/{invoice_id}/mark-paid")
    assert response.status_code == 200
    assert response.json()["status"] == "PAID"

    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.status == "PAID"
    assert invoice.paid_at is not None


def test_mark_paid_rejects_wrong_status(db_session):
    _seed_tenant(db_session)
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="VERIFIED"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-invoices/{invoice_id}/mark-paid")
    assert response.status_code == 400


# ── Queue handler ──────────────────────────────────────────────────────────────

def test_handle_process_outbound_invoice_clean_reaches_verified(db_session):
    from queue_worker import outbound_handlers

    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="UPLOADED"))
    db_session.commit()

    ocr_text = "INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-1\nTotal: 110.00"

    with patch("queue_worker.outbound_handlers.engine", engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value=ocr_text), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent") as m_extract:
        m_extract.return_value = {
            "status": "VERIFIED", "alerts": [],
            "extracted_data": {"customer_name": "Vertex Industries", "invoice_number": "OUT-1", "grand_total": 110.0},
        }
        outbound_handlers.handle_process_outbound_invoice("batch-1", "mock/out.pdf", str(MOCK_TENANT_ID))

    db_session.refresh(db_session.get(Invoice, invoice_id))
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.status == "VERIFIED"
    assert invoice.customer_name == "Vertex Industries"
    assert invoice.grand_total == 110.0


def test_handle_process_outbound_invoice_duplicate_detection(db_session):
    from queue_worker import outbound_handlers

    existing_id = uuid4()
    db_session.add(Invoice(
        id=existing_id, tenant_id=MOCK_TENANT_ID, file_path="mock/existing.pdf", flow_direction="OUTBOUND",
        status="SENT", customer_name="Vertex Industries", invoice_number="OUT-DUP",
    ))
    new_id = uuid4()
    db_session.add(Invoice(id=new_id, tenant_id=MOCK_TENANT_ID, file_path="mock/new.pdf", flow_direction="OUTBOUND", status="UPLOADED"))
    db_session.commit()

    with patch("queue_worker.outbound_handlers.engine", engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value="ocr text"), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent") as m_extract:
        m_extract.return_value = {
            "status": "VERIFIED", "alerts": [],
            "extracted_data": {"customer_name": "Vertex Industries", "invoice_number": "OUT-DUP", "grand_total": 50.0},
        }
        outbound_handlers.handle_process_outbound_invoice("batch-2", "mock/new.pdf", str(MOCK_TENANT_ID))

    invoice = db_session.get(Invoice, new_id)
    assert invoice.status == "NEEDS_REVIEW"
    assert any(a.get("type") == "duplicate_invoice_number" for a in invoice.sa_alerts)


def test_handle_process_outbound_invoice_uses_outbound_global_template(db_session):
    """Confirms rule injection is scoped correctly: an INBOUND Global template
    with the same tenant must NOT leak into the outbound extraction call."""
    from queue_worker import outbound_handlers

    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND",
        rules={"constraints": ["inbound rule -- must not appear here"]}, version=1,
    ))
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="OUTBOUND",
        rules={"constraints": ["Read customer name from the Bill To block"]}, version=1,
    ))
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="UPLOADED"))
    db_session.commit()

    with patch("queue_worker.outbound_handlers.engine", engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value="ocr text"), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent") as m_extract:
        m_extract.return_value = {"status": "VERIFIED", "alerts": [], "extracted_data": {}}
        outbound_handlers.handle_process_outbound_invoice("batch-3", "mock/out.pdf", str(MOCK_TENANT_ID))

        passed_rules = m_extract.call_args.kwargs.get("rules")
        assert passed_rules == {"constraints": ["Read customer name from the Bill To block"]}
