import pytest
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, AuditLog

# Setup SQLite in-memory database
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

def test_list_batches_and_rollback(db_session):
    client = TestClient(app)
    
    tenant_id = MOCK_TENANT_ID
    batch_1 = uuid4()
    batch_2 = uuid4()

    # Pre-populate invoices for batch 1
    inv1 = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        batch_id=batch_1,
        file_path="mock/path/1.pdf",
        vendor_name="Vendor A",
        grand_total=100.0,
        status="COMPLETED",
        flow_direction="INBOUND",
        created_at=datetime(2026, 6, 1, 10, 0, 0)
    )
    inv2 = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        batch_id=batch_1,
        file_path="mock/path/2.pdf",
        vendor_name="Vendor B",
        grand_total=200.0,
        status="PROCESSING",
        flow_direction="INBOUND",
        created_at=datetime(2026, 6, 1, 10, 5, 0)
    )
    
    # Pre-populate invoices for batch 2
    inv3 = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        batch_id=batch_2,
        file_path="mock/path/3.pdf",
        vendor_name="Vendor C",
        grand_total=300.0,
        status="VERIFIED",
        flow_direction="OUTBOUND",
        created_at=datetime(2026, 6, 2, 11, 0, 0)
    )

    db_session.add(inv1)
    db_session.add(inv2)
    db_session.add(inv3)
    db_session.commit()

    # 1. Test GET /api/v1/invoices/batches
    response = client.get("/api/v1/invoices/batches")
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    data = response.json()
    assert len(data) == 2
    
    # Order should be most recent batch first (batch_2 created at June 2)
    assert data[0]["batch_id"] == str(batch_2)
    assert data[0]["invoice_count"] == 1
    assert data[0]["flow_direction"] == "OUTBOUND"
    assert data[0]["status_summary"] == {"VERIFIED": 1}

    assert data[1]["batch_id"] == str(batch_1)
    assert data[1]["invoice_count"] == 2
    assert data[1]["flow_direction"] == "INBOUND"
    assert data[1]["status_summary"] == {"COMPLETED": 1, "PROCESSING": 1}

    # 2. Test filtering /api/v1/invoices by batch_id
    response = client.get(f"/api/v1/invoices?batch_id={batch_1}")
    assert response.status_code == 200
    assert len(response.json()) == 2

    # 3. Test DELETE /api/v1/invoices/batches/{batch_id} (Rollback)
    response = client.delete(f"/api/v1/invoices/batches/{batch_1}")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["count"] == 2

    # Verify soft delete in DB
    db_session.expire_all()
    invoices = db_session.exec(select(Invoice).where(Invoice.batch_id == batch_1)).all()
    assert len(invoices) == 2
    assert all(inv.deleted_at is not None for inv in invoices)

    # Verify AuditLogs created
    audit_logs = db_session.exec(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action == "DELETE_INVOICE"
        )
    ).all()
    assert len(audit_logs) == 2
    assert all(log.details.get("batch_rollback") is True for log in audit_logs)

    # GET /batches should now return x-total-count = 1 (only batch 2 is active)
    response = client.get("/api/v1/invoices/batches")
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert len(response.json()) == 1
    assert response.json()[0]["batch_id"] == str(batch_2)
