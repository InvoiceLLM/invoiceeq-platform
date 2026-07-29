import pytest
from uuid import uuid4
from unittest.mock import patch
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID, MOCK_USER_ID, MOCK_ROLE
from models import Invoice, AuditLog, ExtractionTemplate, ExtractionTemplateVersion

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
    assert response.json() == {
        "success": True, "corrections_applied": {}, "suggested_rule": None, "standing_rule_result": None,
    }

    # Verify updates in database
    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"
    assert db_invoice.sa_alerts == ["Invalid vendor"]

    # Verify audit log was created
    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    log = audit_logs[0]
    assert log.tenant_id == MOCK_TENANT_ID
    from models import User
    db_user = db_session.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).first()
    assert log.actor_user_id == db_user.id
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


def test_resolve_correction_only_on_completed_invoice(db_session):
    """Gap 53: a wrong-but-confident COMPLETED invoice (zero alerts, never flagged)
    needs a correction path too, not just AUDIT_REQUIRED ones. PUT /audit/resolve
    already supports this generically -- status and dismissed_alerts are both
    optional -- so this confirms it end-to-end rather than adding a new endpoint:
    a correction-only payload (no status, no dismissed_alerts) must persist the
    field, log it, and leave the invoice's status untouched."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        vendor_name="ACME Corp",
        status="COMPLETED",
        grand_total=100.0,
        sa_alerts=[]
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {"corrections": {"grand_total": 150.0}}
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["corrections_applied"] == {"grand_total": {"old": 100.0, "new": 150.0}}

    db_session.refresh(db_invoice)
    assert db_invoice.status == "COMPLETED"  # untouched -- no status was requested
    assert db_invoice.grand_total == 150.0

    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    assert audit_logs[0].details["target_status"] is None
    assert audit_logs[0].details["corrections"] == {"grand_total": {"old": 100.0, "new": 150.0}}


# ── Gap 62 / Task 7.5: standing-rule checkbox with safety re-extraction ──────

def test_standing_rule_applied_when_safety_check_passes(db_session):
    """Re-extraction with the candidate rule reflects the correction -> rule is written."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("routers.audit._run_ocr", return_value="Mock OCR Text"), \
         patch("routers.audit.run_extraction_agent", return_value={
             "extracted_data": {"grand_total": 150.0}, "status": "COMPLETED", "alerts": [],
         }):
        payload = {"corrections": {"grand_total": 150.0}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is True

    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.vendor_name == "ACME Corp")
    ).all()
    assert len(templates) == 1
    assert "grand total" in templates[0].rules["constraints"][0]

    versions = db_session.exec(select(ExtractionTemplateVersion)).all()
    assert len(versions) == 1 and versions[0].version == 1


def test_standing_rule_rejected_when_safety_check_fails(db_session):
    """Re-extraction with the candidate rule still doesn't match the correction ->
    rule is rejected, but the invoice correction itself still succeeds."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("routers.audit._run_ocr", return_value="Mock OCR Text"), \
         patch("routers.audit.run_extraction_agent", return_value={
             "extracted_data": {"grand_total": 999.0}, "status": "COMPLETED", "alerts": [],
         }):
        payload = {"corrections": {"grand_total": 150.0}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is False
    assert "Safety check failed" in data["standing_rule_result"]["reason"]
    assert data["corrections_applied"] == {"grand_total": {"old": 100.0, "new": 150.0}}  # correction still applied

    db_session.refresh(db_invoice)
    assert db_invoice.grand_total == 150.0  # correction persisted despite rejected rule

    templates = db_session.exec(select(ExtractionTemplate)).all()
    assert templates == []  # no rule was written


def test_standing_rule_skipped_without_vendor_name(db_session):
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name=None, status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {"corrections": {"grand_total": 150.0}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    assert response.json()["standing_rule_result"]["applied"] is False


def test_standing_rule_not_attempted_when_checkbox_unset(db_session):
    """Default behavior -- apply_as_standing_rule omitted -- must not call the LLM at all."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("routers.audit.run_extraction_agent") as m_extract:
        payload = {"corrections": {"grand_total": 150.0}}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
        m_extract.assert_not_called()

    assert response.status_code == 200
    assert response.json()["standing_rule_result"] is None
