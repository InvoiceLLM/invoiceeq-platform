import io
import pytest
from unittest.mock import patch
from uuid import UUID
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, Tenant

# Setup an in-memory SQLite database for testing isolation
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

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

def test_upload_single_pdf(db_session):
    """Verify successful upload of a single PDF invoice."""
    pdf_content = b"%PDF-1.4 test invoice content"
    files = {"files": ("invoice1.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.process_invoice_task.delay") as mock_celery:
        
        mock_storage.return_value = "mock/path/invoice1.pdf"
        
        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)
        
        assert response.status_code == 201
        data = response.json()
        assert "batch_id" in data
        assert "job_ids" in data
        assert len(data["job_ids"]) == 1
        
        # Verify db entry
        invoice_id = UUID(data["job_ids"][0])
        invoice = db_session.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.status == "PROCESSING"
        assert invoice.file_path == "mock/path/invoice1.pdf"
        assert invoice.tenant_id == MOCK_TENANT_ID
        
        # Verify background Celery task dispatch
        mock_celery.assert_called_once_with(data["batch_id"], "mock/path/invoice1.pdf", str(MOCK_TENANT_ID))

def test_upload_multiple_pdfs(db_session):
    """Verify uploading multiple PDFs in a single request."""
    pdf_content1 = b"%PDF-1.4 test 1"
    pdf_content2 = b"%PDF-1.4 test 2"
    files = [
        ("files", ("invoice1.pdf", io.BytesIO(pdf_content1), "application/pdf")),
        ("files", ("invoice2.pdf", io.BytesIO(pdf_content2), "application/pdf"))
    ]
    
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.process_invoice_task.delay") as mock_celery:
         
        mock_storage.side_effect = ["mock/path/1.pdf", "mock/path/2.pdf"]
        
        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)
        
        assert response.status_code == 201
        data = response.json()
        assert len(data["job_ids"]) == 2
        assert len(db_session.exec(select(Invoice)).all()) == 2
        assert mock_celery.call_count == 2

def test_free_plan_quota_exhausted(db_session):
    """Verify that uploads are rejected once the free plan invoice quota is exhausted."""
    # Pre-provision the test tenant with 0 remaining invoices
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Tenant",
        domain="test.com",
        billing_plan="free",
        free_invoices_remaining=0
    )
    db_session.add(tenant)
    db_session.commit()
    
    files = {"files": ("invoice1.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    
    client = TestClient(app)
    response = client.post("/api/v1/invoices/upload", files=files)
    
    assert response.status_code == 402
    assert response.json()["detail"] == "Limit reached"

def test_free_plan_quota_decrement(db_session):
    """Verify that uploading a PDF successfully decrements the remaining quota."""
    # Pre-provision the test tenant with 1 remaining invoice
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Tenant",
        domain="test.com",
        billing_plan="free",
        free_invoices_remaining=1
    )
    db_session.add(tenant)
    db_session.commit()
    
    files = {"files": ("invoice1.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.process_invoice_task.delay"):
         
        mock_storage.return_value = "mock/path/1.pdf"
        
        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)
        
        assert response.status_code == 201
        
        # Verify count decremented to 0 in database
        db_session.refresh(tenant)
        assert tenant.free_invoices_remaining == 0
