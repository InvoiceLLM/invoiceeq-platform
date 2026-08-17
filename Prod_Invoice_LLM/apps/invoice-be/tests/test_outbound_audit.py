"""Tests for Feature 7.1 (Outbound Auditor): the resolve endpoint
(routers/outbound_audit.py) and the list/overdue endpoint
(routers/outbound_dashboard.py). Mirrors test_audit.py's conventions."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, ExtractionTemplate, ExtractionTemplateVersion

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


# ── Resolve endpoint (Task 7.1.2) ─────────────────────────────────────────────

def test_resolve_correction_only_no_rule(db_session):
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND",
        status="NEEDS_REVIEW", customer_name="Wrong Co", subtotal=80.0, grand_total=100.0,
        sa_alerts=[{"type": "missing_required_field", "field": "customer_name", "message": "..."}],
    ))
    db_session.commit()

    payload = {
        "corrections": {"customer_name": "Vertex Industries", "subtotal": 90.0},
        "dismissed_alerts": ["missing_required_field"]
    }
    response = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["corrections_applied"] == {
        "customer_name": {"old": "Wrong Co", "new": "Vertex Industries"},
        "subtotal": {"old": 80.0, "new": 90.0}
    }
    assert data["standing_rule_result"] is None

    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.customer_name == "Vertex Industries"
    assert invoice.subtotal == 90.0
    assert invoice.sa_alerts == []

    templates = db_session.exec(select(ExtractionTemplate)).all()
    assert templates == []  # no rule written when checkbox unset


def test_resolve_tenant_isolation(db_session):
    other_tenant = uuid4()
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=other_tenant, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="NEEDS_REVIEW"))
    db_session.commit()

    response = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json={"corrections": {"grand_total": 1.0}})
    assert response.status_code == 404


# ── Standing-rule direct write (Task 7.1.3, no safety gate) ──────────────────

def test_standing_rule_written_directly_no_safety_gate(db_session):
    """Unlike inbound's Gap 62 mechanism, this always writes the rule when
    checked -- no re-extraction check, since outbound has no vendor-layout
    variability to de-risk against."""
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND",
        status="NEEDS_REVIEW", customer_name="Wrong Co", grand_total=100.0,
    ))
    db_session.commit()

    payload = {"corrections": {"customer_name": "Vertex Industries"}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    assert response.json()["standing_rule_result"]["applied"] is True

    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.flow_direction == "OUTBOUND")
    ).all()
    assert len(templates) == 1
    assert templates[0].vendor_name is None  # Global-only
    # Feature 18: structured rule object, scoped `outbound_global` -- an outbound
    # invoice has no vendor_name, so the Global OUTBOUND row is the only row this
    # rule can live on. Rendered text is unchanged from the pre-Feature-18 string.
    from utils.rule_schema import normalize_constraints

    stored_rule = templates[0].rules["constraints"][0]
    assert isinstance(stored_rule, dict)
    assert stored_rule["field"] == "customer_name"
    assert stored_rule["scope"] == "outbound_global"
    assert stored_rule["origin"] == "audit_correction_outbound"
    assert "customer name" in normalize_constraints(templates[0].rules["constraints"])[0]

    versions = db_session.exec(select(ExtractionTemplateVersion)).all()
    assert len(versions) == 1 and versions[0].version == 1


def test_standing_rule_versions_on_second_correction(db_session):
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out1.pdf", flow_direction="OUTBOUND", status="NEEDS_REVIEW", grand_total=100.0))
    db_session.commit()
    client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json={"corrections": {"grand_total": 150.0}, "apply_as_standing_rule": True})

    invoice_id2 = uuid4()
    db_session.add(Invoice(id=invoice_id2, tenant_id=MOCK_TENANT_ID, file_path="mock/out2.pdf", flow_direction="OUTBOUND", status="NEEDS_REVIEW", tax_amount=5.0))
    db_session.commit()
    response = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id2}", json={"corrections": {"tax_amount": 9.0}, "apply_as_standing_rule": True})
    assert response.status_code == 200

    templates = db_session.exec(select(ExtractionTemplate).where(ExtractionTemplate.flow_direction == "OUTBOUND")).all()
    assert len(templates) == 1  # same Global row, versioned not duplicated
    assert templates[0].version == 2
    assert len(templates[0].rules["constraints"]) == 2

    versions = db_session.exec(select(ExtractionTemplateVersion)).all()
    assert len(versions) == 2


def test_inbound_extraction_template_unaffected(db_session):
    """Confirms zero cross-contamination with inbound's Trainer-managed rows."""
    db_session.add(ExtractionTemplate(id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND", rules={"constraints": ["inbound rule"]}, version=1))
    db_session.commit()

    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="NEEDS_REVIEW", grand_total=100.0))
    db_session.commit()
    client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json={"corrections": {"grand_total": 150.0}, "apply_as_standing_rule": True})

    inbound_tpl = db_session.exec(select(ExtractionTemplate).where(ExtractionTemplate.flow_direction == "INBOUND")).first()
    assert inbound_tpl.version == 1
    assert inbound_tpl.rules["constraints"] == ["inbound rule"]  # untouched


# ── List/overdue endpoint (Task 7.1.4 / Task 8.1.4) ──────────────────────────

def test_list_outbound_invoices_pagination_and_customer_filter(db_session):
    for i in range(3):
        db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=f"mock/{i}.pdf", flow_direction="OUTBOUND", status="SENT", customer_name="Vertex"))
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/other.pdf", flow_direction="OUTBOUND", status="SENT", customer_name="Acme"))
    db_session.commit()

    resp = client.get("/api/v1/outbound-dashboard/invoices", params={"customer_name": "Vertex", "limit": 2})
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 2


def test_list_outbound_invoices_excludes_inbound_rows(db_session):
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/inbound.pdf", flow_direction="INBOUND", status="COMPLETED", vendor_name="ACME"))
    db_session.commit()

    resp = client.get("/api/v1/outbound-dashboard/invoices")
    assert resp.status_code == 200
    assert resp.json() == []


def test_status_in_filter_bundles_multiple_statuses(db_session):
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/a.pdf", flow_direction="OUTBOUND", status="VERIFIED"))
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/b.pdf", flow_direction="OUTBOUND", status="NEEDS_REVIEW"))
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/c.pdf", flow_direction="OUTBOUND", status="PAID"))
    db_session.commit()

    resp = client.get("/api/v1/outbound-dashboard/invoices", params={"status_in": "VERIFIED,NEEDS_REVIEW,SENT"})
    assert resp.status_code == 200
    statuses = [row["status"] for row in resp.json()]
    assert set(statuses) == {"VERIFIED", "NEEDS_REVIEW"}


def test_overdue_virtual_filter(db_session):
    past_due_id = uuid4()
    db_session.add(Invoice(
        id=past_due_id, tenant_id=MOCK_TENANT_ID, file_path="mock/overdue.pdf", flow_direction="OUTBOUND",
        status="SENT", due_date=date.today() - timedelta(days=5), customer_name="Vertex",
    ))
    not_due_id = uuid4()
    db_session.add(Invoice(
        id=not_due_id, tenant_id=MOCK_TENANT_ID, file_path="mock/future.pdf", flow_direction="OUTBOUND",
        status="SENT", due_date=date.today() + timedelta(days=5), customer_name="Vertex",
    ))
    db_session.commit()

    resp = client.get("/api/v1/outbound-dashboard/invoices", params={"status": "overdue"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert str(past_due_id) in ids
    assert str(not_due_id) not in ids

    # Confirm is_overdue flag is correct on the unfiltered list too
    resp_all = client.get("/api/v1/outbound-dashboard/invoices")
    by_id = {row["id"]: row for row in resp_all.json()}
    assert by_id[str(past_due_id)]["is_overdue"] is True
    assert by_id[str(not_due_id)]["is_overdue"] is False
