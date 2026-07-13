import json
import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice
from workers.tasks import process_invoice_task

# Setup an in-memory SQLite database for testing isolation
sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields a clean, isolated in-memory test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides the FastAPI db session dependency to inject the test database session."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

def test_get_invoice_status(db_session):
    """Verify single polling endpoint returns correct database metadata."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/path.pdf",
        status="COMPLETED",
        vendor_name="Test Vendor",
        grand_total=120.00,
        sa_alerts=["Warning message"]
    )
    db_session.add(db_invoice)
    db_session.commit()
    
    client = TestClient(app)
    response = client.get(f"/api/v1/invoices/status/{invoice_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(invoice_id)
    assert data["status"] == "COMPLETED"
    assert data["vendor_name"] == "Test Vendor"
    assert data["grand_total"] == 120.00
    assert data["alerts"] == ["Warning message"]

def test_get_invoice_status_foreign_tenant(db_session):
    """Verify tenant isolation blocks access to invoices of foreign tenants."""
    foreign_tenant_id = uuid4()
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=foreign_tenant_id,
        file_path="mock/path.pdf",
        status="COMPLETED"
    )
    db_session.add(db_invoice)
    db_session.commit()
    
    client = TestClient(app)
    # The default mock context maps to MOCK_TENANT_ID, which is different from foreign_tenant_id
    response = client.get(f"/api/v1/invoices/status/{invoice_id}")
    assert response.status_code == 404

def test_celery_task_updates_database(db_session):
    """Verify Celery task synchronously updates PostgreSQL with completion details."""
    batch_id = uuid4()
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice_standard.pdf",
        status="PROCESSING"
    )
    db_session.add(db_invoice)
    db_session.commit()
    
    with patch("workers.tasks._run_ocr") as mock_ocr, \
         patch("workers.tasks._publish_sse_events"):
        mock_ocr.return_value = "ocr layout content text"
        
        # Patch engine inside workers.tasks to point to our test engine
        with patch("workers.tasks.engine", engine):
            process_invoice_task(str(batch_id), "mock/invoice_standard.pdf", str(MOCK_TENANT_ID))
            
            # Verify record updated
            db_session.refresh(db_invoice)
            assert db_invoice.status == "COMPLETED"
            assert db_invoice.vendor_name == "ACME Corporation"
            assert db_invoice.grand_total == 165.00
            assert db_invoice.sa_alerts == []

def test_celery_task_audit_anomalies(db_session):
    """Verify Celery task sets status to AUDIT_REQUIRED and adds alerts if warnings are hit."""
    batch_id = uuid4()
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice_audit.pdf",  # contains trigger keyword "audit"
        status="PROCESSING"
    )
    db_session.add(db_invoice)
    db_session.commit()
    
    with patch("workers.tasks._run_ocr") as mock_ocr, \
         patch("workers.tasks._publish_sse_events"):
        mock_ocr.return_value = "ocr layout content text"
        
        with patch("workers.tasks.engine", engine):
            process_invoice_task(str(batch_id), "mock/invoice_audit.pdf", str(MOCK_TENANT_ID))
            
            # Verify status is AUDIT_REQUIRED and alerts are populated
            db_session.refresh(db_invoice)
            assert db_invoice.status == "AUDIT_REQUIRED"
            assert db_invoice.sa_alerts == ["Math mismatch"]

def test_sse_stream_endpoint():
    """Verify streaming endpoint correctly formats and yields Redis Pub/Sub payloads."""
    batch_id = uuid4()
    
    from unittest.mock import MagicMock
    mock_redis = MagicMock()
    mock_redis.close = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_redis.pubsub.return_value = mock_pubsub
    
    # Mock progress update packet then terminal status completed packet
    mock_pubsub.get_message.side_effect = [
        {"data": json.dumps({"status": "PROCESSING_OCR", "message": "OCR Processing"})},
        {"data": json.dumps({"status": "COMPLETED", "message": "Finished", "data": {}})},
    ]
    
    with patch("routers.invoices.AsyncRedis.from_url") as mock_from_url:
        mock_from_url.return_value = mock_redis
        
        client = TestClient(app)
        with client.stream("GET", f"/api/v1/invoices/stream/{batch_id}") as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())
            assert any("PROCESSING_OCR" in line for line in lines)
            assert any("COMPLETED" in line for line in lines)
