import pytest
from uuid import uuid4
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID, MOCK_USER_ID, MOCK_ROLE
from models import Invoice, AuditLog

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

client = TestClient(app)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields clean isolated test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides dependencies database session."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

def test_resolve_invoice_paid(db_session):
    """Verify standard status update to PAID and dismissal of string alerts."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=["Math mismatch", "Invalid vendor"]
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {
        "status": "PAID",
        "dismissed_alerts": ["Math mismatch"]
    }
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Verify updates in database
    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"
    assert db_invoice.sa_alerts == ["Invalid vendor"]

    # Verify audit log was created
    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    log = audit_logs[0]
    assert log.tenant_id == MOCK_TENANT_ID
    assert log.actor_user_id == MOCK_USER_ID
    assert log.actor_role == MOCK_ROLE
    assert log.action == "RESOLVE_INVOICE"
    assert log.details["target_status"] == "PAID"
    assert log.details["dismissed_alerts_input"] == ["Math mismatch"]

def test_resolve_invoice_rejected_dict_alerts(db_session):
    """Verify rejection status and dismissal of structured dictionary alerts."""
    invoice_id = uuid4()
    alerts = [
        {"id": "alert_1", "type": "line_items_mismatch", "message": "Sum mismatch"},
        {"id": "alert_2", "type": "tax_mismatch", "message": "Tax mismatch"}
    ]
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=alerts
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {
        "status": "REJECTED",
        "dismissed_alerts": ["tax_mismatch"] # dismiss by type
    }
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.status == "REJECTED"
    assert len(db_invoice.sa_alerts) == 1
    assert db_invoice.sa_alerts[0]["id"] == "alert_1"

def test_resolve_invalid_status(db_session):
    """Verify that resolving to an invalid status returns HTTP 400."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=[]
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {
        "status": "COMPLETED",
        "dismissed_alerts": []
    }
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 400
    assert "Invalid target status" in response.json()["detail"]

def test_resolve_tenant_isolation(db_session):
    """Verify that tenant isolation prevents updating other tenant's invoice."""
    other_tenant_id = uuid4()
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=other_tenant_id,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=[]
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {
        "status": "PAID",
        "dismissed_alerts": []
    }
    
    # Context headers will default to MOCK_TENANT_ID (which doesn't match other_tenant_id)
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 404
