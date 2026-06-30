import io
import pytest
from unittest.mock import patch
from uuid import UUID, uuid4
from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID, MOCK_USER_ID, TenantContext, get_tenant_context
from models import Invoice

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

def test_get_invoices_list_and_filters(db_session):
    """Verify that pagination, date ranges, status filters, and search tags work on lists."""
    tenant_a = MOCK_TENANT_ID
    
    # Pre-populate invoices for tenant A
    inv1 = Invoice(
        id=uuid4(),
        tenant_id=tenant_a,
        file_path="mock/path/1.pdf",
        vendor_name="Vendor A",
        grand_total=100.0,
        status="COMPLETED",
        invoice_date=date(2026, 6, 1),
        tags=["urgent", "hardware"]
    )
    inv2 = Invoice(
        id=uuid4(),
        tenant_id=tenant_a,
        file_path="mock/path/2.pdf",
        vendor_name="Vendor B",
        grand_total=200.0,
        status="PROCESSING",
        invoice_date=date(2026, 6, 15),
        tags=["software"]
    )
    inv3 = Invoice(
        id=uuid4(),
        tenant_id=tenant_a,
        file_path="mock/path/3.pdf",
        vendor_name="Vendor C",
        grand_total=300.0,
        status="COMPLETED",
        invoice_date=date(2026, 6, 30),
        tags=["hardware"]
    )
    
    db_session.add(inv1)
    db_session.add(inv2)
    db_session.add(inv3)
    db_session.commit()
    
    client = TestClient(app)
    
    # 1. Test pagination limit
    response = client.get("/api/v1/invoices?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    
    # 2. Test pagination offset
    response = client.get("/api/v1/invoices?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vendor_name"] == "Vendor C"
    
    # 3. Test status filter
    response = client.get("/api/v1/invoices?status=COMPLETED")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(i["status"] == "COMPLETED" for i in data)
    
    # 4. Test date range filter
    response = client.get("/api/v1/invoices?start_date=2026-06-10&end_date=2026-06-20")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vendor_name"] == "Vendor B"
    
    # 5. Test search tags filter
    response = client.get("/api/v1/invoices?tag=hardware")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    vendors = [i["vendor_name"] for i in data]
    assert "Vendor A" in vendors
    assert "Vendor C" in vendors

def test_tenant_boundary_isolation(db_session):
    """Verify that queries do not leak across tenants."""
    tenant_a = MOCK_TENANT_ID
    tenant_b = uuid4()
    
    inv_a = Invoice(
        id=uuid4(),
        tenant_id=tenant_a,
        file_path="mock/path/a.pdf",
        vendor_name="Vendor Tenant A",
        status="COMPLETED"
    )
    inv_b = Invoice(
        id=uuid4(),
        tenant_id=tenant_b,
        file_path="mock/path/b.pdf",
        vendor_name="Vendor Tenant B",
        status="COMPLETED"
    )
    db_session.add(inv_a)
    db_session.add(inv_b)
    db_session.commit()
    
    client = TestClient(app)
    
    # Test list isolation: Tenant A client should only see A's invoices
    response = client.get("/api/v1/invoices")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vendor_name"] == "Vendor Tenant A"
    
    # Test details isolation: Tenant A cannot fetch Tenant B's invoice details
    response = client.get(f"/api/v1/invoices/{inv_b.id}")
    assert response.status_code == 404
    
    # Test PDF download isolation: Tenant A cannot download Tenant B's PDF
    response = client.get(f"/api/v1/invoices/{inv_b.id}/pdf")
    assert response.status_code == 404

def test_get_single_invoice_detail(db_session):
    """Verify fetching single invoice returns full DB columns."""
    invoice_id = uuid4()
    invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/path/invoice.pdf",
        vendor_name="Test Vendor Detail",
        grand_total=150.50,
        invoice_number="INV-123",
        po_number="PO-999",
        status="COMPLETED",
        sa_alerts=["Alert 1"],
        tags=["tag1"],
        items=[{"description": "Item 1", "amount": 150.50}]
    )
    db_session.add(invoice)
    db_session.commit()
    
    client = TestClient(app)
    response = client.get(f"/api/v1/invoices/{invoice_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(invoice_id)
    assert data["vendor_name"] == "Test Vendor Detail"
    assert data["grand_total"] == 150.50
    assert data["invoice_number"] == "INV-123"
    assert data["po_number"] == "PO-999"
    assert data["sa_alerts"] == ["Alert 1"]
    assert data["items"] == [{"description": "Item 1", "amount": 150.50}]

def test_stream_pdf(db_session):
    """Verify that secure PDF delivery route returns correct media types and streams data."""
    invoice_id = uuid4()
    invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="azure://invoices/tenants/0000-0000/invoices/abc.pdf",
        vendor_name="Test Vendor",
        status="COMPLETED"
    )
    db_session.add(invoice)
    db_session.commit()
    
    pdf_content = b"%PDF-1.4 mock binary pdf content"
    
    with patch("routers.invoices.download_pdf_from_storage") as mock_download:
        mock_download.return_value = pdf_content
        
        client = TestClient(app)
        response = client.get(f"/api/v1/invoices/{invoice_id}/pdf")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert f"inline; filename={invoice_id}.pdf" in response.headers["content-disposition"]
        assert response.content == pdf_content
        mock_download.assert_called_once_with(invoice.file_path)
