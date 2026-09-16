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

import os

# Gap 525: Allow running against Postgres with strict localhost guard to prevent purging non-local data
postgres_test_url = os.getenv("TEST_DATABASE_URL")
if postgres_test_url:
    # Gap 525: this fixture runs create_all/drop_all around every test, so the URL must name a
    # throwaway database (its name contains "test") on the local host -- the dev database
    # `invoice_db` on localhost:5433 is deliberately refused.
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(postgres_test_url)
    assert _parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525 security guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1 to avoid accidental data loss."
    )
    assert "test" in (_parsed.path or "").lower(), (
        "Gap 525 security guard: TEST_DATABASE_URL must name a throwaway database whose name contains 'test' "
        "(this fixture drops every table after each test)."
    )
    engine = create_engine(postgres_test_url)
else:
    sqlite_url = "sqlite:///:memory:"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_resolve_rate_limiter():
    """Gap 561: the limiter is process-wide (and Redis-backed when Redis is up), so every test
    starts from an empty window instead of inheriting the previous test's -- or run's -- hits."""
    from routers import audit as _audit, outbound_audit as _outbound_audit
    _audit._resolve_rate_limiter.reset()
    _outbound_audit._resolve_rate_limiter.reset()
    yield
    _audit._resolve_rate_limiter.reset()
    _outbound_audit._resolve_rate_limiter.reset()


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
        status="NEEDS_REVIEW", customer_name="Wrong Co", subtotal=80.0, tax_amount=10.0, grand_total=100.0,
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


# ── Standing-rule direct write (Task 7.1.3 / Gap 542) ──────────────────────────

def test_outbound_standing_rule_disallowed_gap542(db_session):
    """Gap 542: Outbound invoices are tenant-wide Global templates.
    Single-invoice corrections must NOT create global standing rules that corrupt
    future outbound invoices across all customers."""
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND",
        status="NEEDS_REVIEW", customer_name="Wrong Co", grand_total=100.0,
    ))
    db_session.commit()

    payload = {"corrections": {"customer_name": "Vertex Industries", "grand_total": 150.0}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is False
    assert "outbound templates are tenant-wide" in data["standing_rule_result"]["reason"]

    # The invoice itself was correctly updated
    db_invoice = db_session.get(Invoice, invoice_id)
    assert db_invoice.customer_name == "Vertex Industries"
    assert db_invoice.grand_total == 150.0

    # No global outbound template rules were written
    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.flow_direction == "OUTBOUND")
    ).all()
    assert len(templates) == 0


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


VIEWER = {"Authorization": "Bearer test_viewer"}


def test_outbound_resolve_with_standing_rule_requires_can_train_gap544(db_session):
    """Gap 544 (AF-9): Outbound audit resolve with apply_as_standing_rule=True requires
    can_train=True. A caller with only can_audit gets HTTP 403."""
    from models import User
    from dependencies import MOCK_USER_ID
    client.get("/auth/me", headers=VIEWER)
    user = db_session.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).first()
    assert user is not None
    user.can_audit = True
    user.can_train = False
    db_session.add(user)
    db_session.commit()

    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND",
        status="NEEDS_REVIEW", customer_name="Wrong Co", grand_total=100.0,
    ))
    db_session.commit()

    payload = {"corrections": {"customer_name": "Vertex Industries"}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json=payload, headers=VIEWER)
    assert response.status_code == 403
    assert "AI Trainer permission required" in response.json()["detail"]

    # Regular resolve without standing rule succeeds
    payload_normal = {"corrections": {"customer_name": "Vertex Industries"}, "apply_as_standing_rule": False}
    response_normal = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json=payload_normal, headers=VIEWER)
    assert response_normal.status_code == 200


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

    resp_all = client.get("/api/v1/outbound-dashboard/invoices")
    by_id = {row["id"]: row for row in resp_all.json()}
    assert by_id[str(past_due_id)]["is_overdue"] is True
    assert by_id[str(not_due_id)]["is_overdue"] is False


def test_outbound_webhook_sends_none_currency_when_unknown_gap557(db_session):
    """Gap 557 (AF-22): Outbound webhook sends null/None for unknown currency instead of defaulting to USD."""
    from unittest.mock import patch
    from routers.outbound_invoices import _dispatch_outbound_webhook
    invoice = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/out.pdf",
        flow_direction="OUTBOUND",
        status="SENT",
        customer_name="Test Customer",
        grand_total=300.0,
        currency=None,
    )
    with patch("services.webhooks.dispatch_webhook_event") as m_webhook:
        _dispatch_outbound_webhook(db_session, invoice, "outbound_invoice.sent")
        m_webhook.assert_called_once()
        payload = m_webhook.call_args[0][3]
        assert payload["currency"] is None


def test_confirm_send_and_mark_paid_write_audit_log_gap551(db_session):
    """Gap 551 (AF-16): Outbound Confirm Send and Mark Paid must write AuditLog rows."""
    from models import AuditLog
    from unittest.mock import patch

    inv_id = uuid4()
    db_session.add(Invoice(
        id=inv_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/out.pdf",
        flow_direction="OUTBOUND",
        status="VERIFIED",
        customer_name="Vertex Corp",
    ))
    db_session.commit()

    with patch("routers.outbound_invoices._dispatch_outbound_webhook"), \
         patch("routers.outbound_invoices.notify_auditor_action"):
        # 1. Confirm Send
        resp1 = client.put(f"/api/v1/outbound-invoices/{inv_id}/confirm-send")
        assert resp1.status_code == 200

        logs1 = db_session.exec(
            select(AuditLog).where(AuditLog.invoice_id == inv_id, AuditLog.action == "CONFIRM_SEND_OUTBOUND_INVOICE")
        ).all()
        assert len(logs1) == 1
        assert logs1[0].details["previous_status"] == "VERIFIED"
        assert logs1[0].details["target_status"] == "SENT"

        # 2. Mark Paid
        resp2 = client.put(f"/api/v1/outbound-invoices/{inv_id}/mark-paid")
        assert resp2.status_code == 200

        logs2 = db_session.exec(
            select(AuditLog).where(AuditLog.invoice_id == inv_id, AuditLog.action == "MARK_PAID_OUTBOUND_INVOICE")
        ).all()
        assert len(logs2) == 1
        assert logs2[0].details["previous_status"] == "SENT"
        assert logs2[0].details["target_status"] == "PAID"


def test_resolve_correction_arithmetic_recheck_gap535(db_session):
    """Gap 535 (AF: provisional 521): correcting totals to impossible arithmetic generates a math alert."""
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/out.pdf",
        flow_direction="OUTBOUND",
        status="NEEDS_REVIEW",
        customer_name="Test Customer",
        subtotal=100.0,
        tax_amount=10.0,
        grand_total=110.0,
        sa_alerts=[]
    ))
    db_session.commit()

    # Correct grand_total to 150.0 without changing subtotal or tax (100 + 10 != 150)
    payload = {
        "corrections": {"grand_total": 150.0}
    }
    resp = client.put(f"/api/v1/outbound-audit/resolve/{invoice_id}", json=payload)
    assert resp.status_code == 200

    inv = db_session.get(Invoice, invoice_id)
    assert inv.grand_total == 150.0
    assert any(a.get("type") == "tax_mismatch" for a in inv.sa_alerts)



