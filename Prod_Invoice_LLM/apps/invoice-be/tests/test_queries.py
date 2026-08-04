import pytest
from unittest.mock import patch
from uuid import uuid4
from datetime import date
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
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
    
    # 1. Test pagination limit. FE Gap 29: X-Total-Count reports the full
    # matching count (3) regardless of the page-sized limit, so a caller can
    # page through the whole result set rather than treating this batch as
    # everything there is.
    response = client.get("/api/v1/invoices?limit=2")
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    data = response.json()
    assert len(data) == 2
    
    # 2. Test pagination offset. FE Gap 29: list_invoices now orders by
    # created_at desc (most recent first) rather than relying on incidental
    # DB return order, so offset=2 lands on the first-created invoice.
    response = client.get("/api/v1/invoices?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vendor_name"] == "Vendor A"
    
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


def _seed_pdf_invoice(db_session):
    invoice = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="azure://invoices/tenants/0000-0000/invoices/gone.pdf",
        vendor_name="Test Vendor",
        status="COMPLETED",
    )
    db_session.add(invoice)
    db_session.commit()
    return invoice


def test_stream_pdf_missing_blob_is_404_not_500(db_session):
    """
    FE Gap 90 regression guard.

    A blob that no longer exists (e.g. Azurite storage lost across a container
    restart while Postgres survived on its named volume) raises the Azure SDK's
    ResourceNotFoundError, which is NOT a Python FileNotFoundError. Before this
    was fixed, only FileNotFoundError was caught, so a missing blob fell through
    to the generic handler and returned a raw 500 -- and the Trainer's PDF pane
    rendered that error JSON verbatim in place of the document.
    """
    from azure.core.exceptions import ResourceNotFoundError

    invoice = _seed_pdf_invoice(db_session)

    with patch("routers.invoices.download_pdf_from_storage") as mock_download:
        mock_download.side_effect = ResourceNotFoundError("The specified blob does not exist.")

        response = TestClient(app).get(f"/api/v1/invoices/{invoice.id}/pdf")

    assert response.status_code == 404
    assert "not found in storage" in response.json()["detail"].lower()


def test_stream_pdf_is_get_only_and_405s_a_direct_head(db_session):
    """
    Pins a real asymmetry found while closing FE Gap 90, so it can't be
    misremembered later.

    The FE's PdfViewerPanel probes this endpoint with HEAD before rendering the
    iframe (to choose between the document and a friendly "Document Unavailable"
    card). That probe works only because it goes through invoice-fe's own route
    handler, and Next 14 auto-implements HEAD by invoking the exported GET
    (`next/dist/server/future/route-modules/app-route/helpers/auto-implement-methods.js`),
    which then calls this backend with an explicit `method: "GET"`. This backend
    route is registered with `@router.get` and -- unlike a bare Starlette Route,
    which does add HEAD alongside GET -- FastAPI's APIRouter does not, so a
    *direct* HEAD here is a 405.

    That matters because if anyone ever changes `app/api/invoices/[id]/pdf/route.ts`
    to forward the caller's real method instead of hardcoding GET, every probe
    starts returning 405 and the panel shows "Document Unavailable" for every
    perfectly good PDF -- a worse bug than the one Gap 90 fixed. The FE now
    treats a non-404 failure as inconclusive and renders the document anyway, so
    this asymmetry is defused on that side rather than by widening the API here.
    """
    invoice = _seed_pdf_invoice(db_session)

    response = TestClient(app).head(f"/api/v1/invoices/{invoice.id}/pdf")

    assert response.status_code == 405
