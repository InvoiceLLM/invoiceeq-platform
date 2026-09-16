import pytest
from uuid import uuid4
from unittest.mock import patch
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID, MOCK_USER_ID, MOCK_ROLE
from models import Invoice, AuditLog, ExtractionTemplate, ExtractionTemplateVersion, Tenant

import os
import sys

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
    engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

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
        "success": True, "already_resolved": False, "corrections_applied": {},
        "remaining_alerts": ["Invalid vendor"], "unmatched_dismissals": [], "raised_alerts": [],
        "suggested_rule": None, "standing_rule_result": None,
        "email_notify": None,
        # Gap 339: null because this tenant has no TenantWorkflowConfig row and
        # therefore never selected the `email_summary` output destination.
        "email_summary": None,
        # Gap 338: null for the same reason -- no row, so no `drive_archive`.
        "drive_archive": None,
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


def test_resolve_refuses_outbound_invoice(db_session):
    """BE Gap 536: the inbound resolve must not change an OUTBOUND invoice in any way."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/outbound.pdf",
        status="NEEDS_REVIEW",
        flow_direction="OUTBOUND",
        sa_alerts=["Math mismatch"],
    )
    db_session.add(db_invoice)
    db_session.commit()

    payloads = [
        {"status": "PAID"},
        {"status": "REJECTED", "reject_reason": "test"},
        {"status": "REVIEW_LATER"},
        {"corrections": {"vendor_name": "Changed"}},
        {"dismissed_alerts": ["Math mismatch"]},
    ]
    for payload in payloads:
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
        assert response.status_code == 404, payload

    db_session.refresh(db_invoice)
    assert db_invoice.status == "NEEDS_REVIEW"
    assert db_invoice.vendor_name is None
    assert db_invoice.sa_alerts == ["Math mismatch"]
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("source_status", [
    "UPLOADED", "PROCESSING", "PROCESSING_OCR", "EXTRACTING_DATA", "FAILED", "EXTRACT_FAILED", "DUPLICATE",
])
@pytest.mark.parametrize("target_status", ["PAID", "REJECTED"])
def test_resolve_refuses_to_finalize_unfinished_invoice(db_session, source_status, target_status):
    """BE Gap 539: an invoice that never finished extraction cannot be approved or rejected."""
    invoice_id = uuid4()
    db_invoice = Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", status=source_status, sa_alerts=[])
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"status": target_status, "reject_reason": "test"})
    assert response.status_code == 400
    assert source_status in response.json()["detail"]

    db_session.refresh(db_invoice)
    assert db_invoice.status == source_status
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("source_status", ["COMPLETED", "AUDIT_REQUIRED", "REVIEW_LATER", "NEEDS_RESUBMISSION"])
def test_resolve_still_finalizes_reviewable_invoice(db_session, source_status):
    """BE Gap 539: the allow-list keeps the four reviewable statuses approvable."""
    invoice_id = uuid4()
    db_invoice = Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", status=source_status, sa_alerts=[])
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"status": "PAID"})
    assert response.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"


# ---------------------------------------------------------------------------
# Gap 193: reopen (AUDIT_REQUIRED) a resolved invoice — Admin-only, terminal-only
# ---------------------------------------------------------------------------

VIEWER = {"Authorization": "Bearer test_viewer"}


def _viewer_row_with_audit_permission(db_session):
    """Provisions the mock permission-less identity, then grants it
    can_audit=True so it passes the router's require_can_audit gate while its
    role stays the non-Admin zero-permission fallback (`RoleMapper.NO_ROLE`;
    'Viewer' before Gap 337 retired that name) — isolates the Admin-only check in
    resolve_audit_invoke from the unrelated can_audit gate this identity would
    otherwise fail on first."""
    from models import User
    client.get("/auth/me", headers=VIEWER)
    user = db_session.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).first()
    assert user is not None
    user.can_audit = True
    db_session.add(user)
    db_session.commit()


def test_reopen_requires_admin(db_session):
    """A non-Admin with can_audit=True can still resolve invoices, but cannot reopen one."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="PAID", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    _viewer_row_with_audit_permission(db_session)

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "AUDIT_REQUIRED", "dismissed_alerts": []},
        headers=VIEWER,
    )
    assert response.status_code == 403
    assert "Admin" in response.json()["detail"]

    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"  # unchanged


def test_reopen_rejects_non_terminal_invoice(db_session):
    """Reopening only makes sense from PAID/REJECTED — reject it on anything else."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "AUDIT_REQUIRED", "dismissed_alerts": []},
    )
    assert response.status_code == 400
    assert "Cannot reopen" in response.json()["detail"]


def test_reopen_success_as_admin(db_session):
    """Admin can reopen a PAID invoice; logs REOPEN_INVOICE, not RESOLVE_INVOICE;
    does not dispatch invoice.paid/invoice.rejected or send a staff notification —
    a reopen undoes a finalization, it isn't one."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="PAID", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("services.webhooks.dispatch_webhook_event") as m_webhook, \
         patch("services.staff_notify.notify_auditor_action") as m_notify:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": "AUDIT_REQUIRED", "dismissed_alerts": []},
        )
        assert response.status_code == 200
        # Gap 558: Admin reopen dispatches invoice.reopened event
        m_webhook.assert_called_once()
        assert m_webhook.call_args[0][2] == "invoice.reopened"
        m_notify.assert_not_called()

    db_session.refresh(db_invoice)
    assert db_invoice.status == "AUDIT_REQUIRED"

    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "REOPEN_INVOICE"
    assert audit_logs[0].details["target_status"] == "AUDIT_REQUIRED"


@pytest.mark.parametrize("current_status,target_status", [("PAID", "REJECTED"), ("REJECTED", "PAID")])
@pytest.mark.parametrize("as_admin", [True, False])
def test_final_decision_cannot_be_flipped_directly(db_session, current_status, target_status, as_admin):
    """BE Gap 529: nobody switches PAID <-> REJECTED directly; an Admin reopens first."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", grand_total=100.0, status=current_status, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    headers = {}
    if not as_admin:
        _viewer_row_with_audit_permission(db_session)
        headers = VIEWER

    with patch("services.webhooks.dispatch_webhook_event") as m_webhook, \
         patch("services.staff_notify.notify_auditor_action") as m_notify:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": target_status, "reject_reason": "flip test"},
            headers=headers,
        )
        assert response.status_code == 400
        assert "reopen it first" in response.json()["detail"]
        m_webhook.assert_not_called()
        m_notify.assert_not_called()

    db_session.refresh(db_invoice)
    assert db_invoice.status == current_status
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


def test_final_decision_changes_through_admin_reopen(db_session):
    """BE Gap 529: the supported path — an Admin reopens, then the invoice can be decided again."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="PAID", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    reopen = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"status": "AUDIT_REQUIRED"})
    assert reopen.status_code == 200
    reject = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"status": "REJECTED", "reject_reason": "wrong vendor"})
    assert reject.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.status == "REJECTED"
    actions = [log.action for log in db_session.exec(
        select(AuditLog).where(AuditLog.invoice_id == invoice_id).order_by(AuditLog.timestamp)
    ).all()]
    assert actions == ["REOPEN_INVOICE", "RESOLVE_INVOICE"]


def _finalization_side_effect_patches():
    return (
        patch("services.webhooks.dispatch_webhook_event"),
        patch("services.staff_notify.notify_auditor_action"),
        patch("services.workflow_outputs.deliver_email_summary"),
        patch("services.workflow_outputs.deliver_drive_archive"),
        patch("routers.dashboard.invalidate_insights_cache"),
    )


@pytest.mark.parametrize("final_status", ["PAID", "REJECTED"])
def test_repeated_decision_is_a_no_op(db_session, final_status):
    """BE Gap 554: repeating the decision already in place re-sends nothing and writes no second trail row."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", grand_total=100.0, status="AUDIT_REQUIRED", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()
    payload = {"status": final_status, "reject_reason": "duplicate billing"}

    first = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert first.status_code == 200
    assert first.json()["already_resolved"] is False

    webhook, notify, summary, drive, cache = _finalization_side_effect_patches()
    with webhook as m_webhook, notify as m_notify, summary as m_summary, drive as m_drive, cache as m_cache:
        retry = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
        assert retry.status_code == 200
        assert retry.json()["already_resolved"] is True
        for mock in (m_webhook, m_notify, m_summary, m_drive, m_cache):
            mock.assert_not_called()

    db_session.refresh(db_invoice)
    assert db_invoice.status == final_status
    assert len(db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()) == 1


def test_repeated_decision_with_a_correction_saves_it_without_resending(db_session):
    """BE Gap 554: a real correction sent with the same final status is saved and logged, but the approval is not re-sent."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", grand_total=100.0, status="PAID", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    webhook, notify, summary, drive, cache = _finalization_side_effect_patches()
    with webhook as m_webhook, notify as m_notify, summary as m_summary, drive as m_drive, cache as m_cache:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": "PAID", "corrections": {"vendor_name": "ACME Corporation"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["already_resolved"] is False
        assert body["corrections_applied"]["vendor_name"]["new"] == "ACME Corporation"
        for mock in (m_webhook, m_notify, m_summary, m_drive, m_cache):
            mock.assert_not_called()

    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"
    assert db_invoice.vendor_name == "ACME Corporation"
    logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert [log.action for log in logs] == ["RESOLVE_INVOICE"]


@pytest.mark.parametrize("flow_direction,url,payload", [
    ("INBOUND", "/api/v1/audit/resolve/{id}", {"status": "PAID"}),
    ("OUTBOUND", "/api/v1/outbound-audit/resolve/{id}", {"corrections": {"grand_total": 90.0}}),
])
def test_resolve_locks_the_invoice_row(db_session, flow_direction, url, payload):
    """BE Gap 541: both resolve endpoints load the invoice with a row lock, so concurrent decisions queue.

    SQLite ignores FOR UPDATE, so this checks the statement as Postgres would run it."""
    from sqlalchemy.dialects import postgresql

    invoice_id = uuid4()
    status_value = "AUDIT_REQUIRED" if flow_direction == "INBOUND" else "NEEDS_REVIEW"
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        grand_total=100.0, status=status_value, flow_direction=flow_direction, sa_alerts=[],
    ))
    db_session.commit()

    captured = []
    real_exec = db_session.exec

    def spy(statement, *args, **kwargs):
        captured.append(statement)
        return real_exec(statement, *args, **kwargs)

    with patch.object(db_session, "exec", side_effect=spy):
        response = client.put(url.format(id=invoice_id), json=payload)
    assert response.status_code == 200

    compiled = [str(s.compile(dialect=postgresql.dialect())) for s in captured if hasattr(s, "compile")]
    assert any("FROM invoice" in sql and "FOR UPDATE" in sql for sql in compiled)


@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf", "1e400", "not-a-number"])
@pytest.mark.parametrize("flow_direction,url,extra", [
    ("INBOUND", "/api/v1/audit/resolve/{id}", {"status": "PAID"}),
    ("OUTBOUND", "/api/v1/outbound-audit/resolve/{id}", {}),
])
def test_unreadable_money_correction_is_refused_and_nothing_saved(db_session, bad_value, flow_direction, url, extra):
    """BE Gap 533: a money correction that is not a finite number gets 422 naming the field; nothing is saved."""
    invoice_id = uuid4()
    status_value = "AUDIT_REQUIRED" if flow_direction == "INBOUND" else "NEEDS_REVIEW"
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, invoice_number="INV-1", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        url.format(id=invoice_id),
        json={**extra, "corrections": {"grand_total": bad_value, "invoice_number": "INV-2"}},
    )
    assert response.status_code == 422
    assert [c["field"] for c in response.json()["detail"]["invalid_corrections"]] == ["grand_total"]

    db_session.refresh(db_invoice)
    assert db_invoice.grand_total == 100.0
    assert db_invoice.invoice_number == "INV-1"
    assert db_invoice.status == status_value
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("flow_direction,url", [
    ("INBOUND", "/api/v1/audit/resolve/{id}"),
    ("OUTBOUND", "/api/v1/outbound-audit/resolve/{id}"),
])
def test_negative_money_correction_is_still_accepted(db_session, flow_direction, url):
    """BE Gap 533: credit and debit notes are negative on purpose, so a negative amount stays valid."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status="AUDIT_REQUIRED" if flow_direction == "INBOUND" else "NEEDS_REVIEW", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {"grand_total": "-500"}})
    assert response.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.grand_total == -500.0


RESOLVE_ENDPOINTS = [
    ("INBOUND", "/api/v1/audit/resolve/{id}", "AUDIT_REQUIRED"),
    ("OUTBOUND", "/api/v1/outbound-audit/resolve/{id}", "NEEDS_REVIEW"),
]
ORIGINAL_ITEMS = [{"description": "Widget", "quantity": 2.0, "unit_price": 50.0, "amount": 100.0}]


@pytest.mark.parametrize("bad_items", [
    "Widget A, 100",
    [{"arbitrary": "object", "no_amount": True}],
    [{"description": "Widget"}],
    [{"description": "Widget", "amount": "nan"}],
    {"description": "Widget", "amount": 100.0},
])
@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_malformed_line_items_are_refused_and_nothing_saved(db_session, bad_items, flow_direction, url, status_value):
    """BE Gap 534: line items that are not valid line items get 422; the stored items stay as they were."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, items=ORIGINAL_ITEMS, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {"items": bad_items}})
    assert response.status_code == 422
    assert [c["field"] for c in response.json()["detail"]["invalid_corrections"]] == ["items"]

    db_session.refresh(db_invoice)
    assert db_invoice.items == ORIGINAL_ITEMS
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_valid_line_items_including_a_credit_line_are_saved(db_session, flow_direction, url, status_value):
    """BE Gap 534: well-formed items (a negative credit line included) are saved exactly as sent."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, items=ORIGINAL_ITEMS, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    new_items = [
        {"description": "Widget", "quantity": 3, "unit_price": 50, "amount": 150},
        {"description": "Loyalty discount", "amount": -20},
    ]
    response = client.put(url.format(id=invoice_id), json={"corrections": {"items": new_items}})
    assert response.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.items == [
        {"description": "Widget", "quantity": 3.0, "unit_price": 50.0, "amount": 150.0},
        {"description": "Loyalty discount", "amount": -20.0},
    ]


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_common_money_and_date_formats_are_saved(db_session, flow_direction, url, status_value):
    """BE Gap 530: "$1,250.60" and "15/01/2026" are read and saved instead of silently dropped."""
    from datetime import date

    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        url.format(id=invoice_id),
        json={"corrections": {"grand_total": "$1,250.60", "invoice_date": "15/01/2026"}},
    )
    assert response.status_code == 200
    applied = response.json()["corrections_applied"]
    assert applied["grand_total"]["new"] == 1250.6
    assert applied["invoice_date"]["new"] == "2026-01-15"

    db_session.refresh(db_invoice)
    assert db_invoice.grand_total == 1250.6
    assert db_invoice.invoice_date == date(2026, 1, 15)


@pytest.mark.parametrize("flow_direction,url,status_value,corrections,bad_field", [
    ("INBOUND", "/api/v1/audit/resolve/{id}", "AUDIT_REQUIRED", {"invoice_date": "01/02/2026"}, "invoice_date"),
    ("OUTBOUND", "/api/v1/outbound-audit/resolve/{id}", "NEEDS_REVIEW", {"invoice_date": "01/02/2026"}, "invoice_date"),
    # round_off is extracted but has no Invoice column (BE Gap 531 made everything else correctable).
    ("INBOUND", "/api/v1/audit/resolve/{id}", "AUDIT_REQUIRED", {"round_off": "0.50"}, "round_off"),
    ("OUTBOUND", "/api/v1/outbound-audit/resolve/{id}", "NEEDS_REVIEW", {"round_off": "0.50"}, "round_off"),
])
def test_ambiguous_date_or_uncorrectable_field_is_refused(db_session, flow_direction, url, status_value, corrections, bad_field):
    """BE Gap 530: a date that reads two ways, or a field that cannot be corrected, gets 422 naming it; nothing is saved."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, invoice_number="INV-1", currency="USD", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {**corrections, "invoice_number": "INV-2"}})
    assert response.status_code == 422
    invalid = response.json()["detail"]["invalid_corrections"]
    assert [c["field"] for c in invalid] == [bad_field]
    if bad_field == "invoice_date":
        assert "YYYY-MM-DD" in invalid[0]["reason"]

    db_session.refresh(db_invoice)
    assert db_invoice.invoice_number == "INV-1"
    assert db_invoice.currency == "USD"
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_trail_row_records_a_browser_session_without_a_key_prefix(db_session, flow_direction, url, status_value):
    """BE Gap 552: a signed-in (non-key) resolve records auth_method 'clerk' and no API-key prefix."""
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, invoice_number="INV-1", sa_alerts=[],
    ))
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {"invoice_number": "INV-2"}})
    assert response.status_code == 200

    log = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).one()
    assert log.details["auth_method"] == "clerk"
    assert "api_key_prefix" not in log.details


def _seed_correction_history(db_session, *, rows):
    """Seed RESOLVE_INVOICE trail rows; `rows` is a list of (vendor_name, field, new_value, minutes_ago)."""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    for vendor_name, field, new_value, minutes_ago in rows:
        invoice_id = uuid4()
        db_session.add(Invoice(
            id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/history.pdf", vendor_name=vendor_name,
            status="AUDIT_REQUIRED", sa_alerts=[],
        ))
        db_session.add(AuditLog(
            tenant_id=MOCK_TENANT_ID, invoice_id=invoice_id, actor_user_id=uuid4(), actor_role="Admin",
            action="RESOLVE_INVOICE", details={"corrections": {field: {"old": None, "new": new_value}}},
            timestamp=now - timedelta(minutes=minutes_ago),
        ))
    db_session.commit()


def test_pattern_detection_reads_only_the_newest_corrections(db_session, monkeypatch):
    """BE Gap 560: pattern detection scans a bounded window of the newest corrections, not the whole 90 days."""
    import routers.audit as audit_router

    monkeypatch.setattr(audit_router, "_RULE_SUGGESTION_SCAN_LIMIT", 5)

    # Three older currency corrections (an invariant field -- Gap 547 excludes transaction scalars such as po_number) for ACME, buried under five newer unrelated corrections.
    _seed_correction_history(db_session, rows=[
        *[("ACME Corp", "currency", f"CUR-{i}", 100 + i) for i in range(3)],
        *[("Other Vendor", "invoice_number", f"INV-{i}", 10 + i) for i in range(5)],
    ])
    assert audit_router._detect_correction_pattern(db_session, MOCK_TENANT_ID, "ACME Corp", ["currency"]) is None


def test_pattern_detection_still_suggests_from_recent_repeats_and_quotes_the_newest(db_session, monkeypatch):
    """BE Gap 560: repeats inside the window still produce a suggestion, quoting the most recent correction."""
    import routers.audit as audit_router

    monkeypatch.setattr(audit_router, "_RULE_SUGGESTION_SCAN_LIMIT", 5)

    _seed_correction_history(db_session, rows=[
        ("ACME Corp", "currency", "EUR", 1),
        ("ACME Corp", "currency", "GBP", 2),
        ("ACME Corp", "currency", "USD", 3),
        *[("Other Vendor", "invoice_number", f"INV-{i}", 50 + i) for i in range(5)],
    ])
    suggestion = audit_router._detect_correction_pattern(db_session, MOCK_TENANT_ID, "ACME Corp", ["currency"])
    assert suggestion is not None
    assert suggestion["scope"] == "existing_vendor"
    assert "EUR" in suggestion["sample_correction"]


_LIST_CORRECTIONS = {
    "taxes": [{"tax_type": "CGST", "rate_percent": 9, "amount": 45}],
    "tax_ids": [{"id_type": "GSTIN", "value": "27AAPFU0939F1ZV", "party": "vendor"}],
    "payment_instructions": [{"method_type": "UPI ID + IFSC", "details": "acme@upi"}],
    "references": [{"ref_type": "Sales Order", "value": "SO-9"}],
    "addresses": [{"address_type": "billing", "text": "12 Main St, Pune", "country": "IN"}],
    "compliance_metadata": [{"key": "IRN", "value": "abc123"}],
}
_SCALAR_CORRECTIONS = {"currency": "eur", "discount_amount": "₹1,250.50", "discount_percent": "12.5%"}
_SCALAR_SAVED = {"currency": "EUR", "discount_amount": 1250.5, "discount_percent": 12.5}
# (corrections sent, values saved) per direction.
NEW_FIELD_CORRECTIONS = {
    "INBOUND": (
        {**_SCALAR_CORRECTIONS, **_LIST_CORRECTIONS, "tags": "it, hardware, it",
         "discounts": [{"discount_type": "trade discount", "amount": 50}],
         "deductions": [{"deduction_type": "retention", "amount": 25}]},
        {**_SCALAR_SAVED, **_LIST_CORRECTIONS, "tags": ["it", "hardware"],
         "discounts": [{"discount_type": "trade discount", "amount": 50.0}],
         "deductions": [{"deduction_type": "retention", "amount": 25.0}]},
    ),
    "OUTBOUND": (
        {**_SCALAR_CORRECTIONS, **_LIST_CORRECTIONS,
         "vendor_name": "Our Company Pvt Ltd", "po_number": "PO-77", "notes": "Payment due within 30 days"},
        {**_SCALAR_SAVED, **_LIST_CORRECTIONS,
         "vendor_name": "Our Company Pvt Ltd", "po_number": "PO-77", "notes": "Payment due within 30 days"},
    ),
}


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_every_previously_uncorrectable_field_is_saved(db_session, flow_direction, url, status_value):
    """BE Gap 531: the twelve fields that used to be refused are read, saved and reported in one correction."""
    corrections, saved = NEW_FIELD_CORRECTIONS[flow_direction]
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, currency="USD", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": corrections})
    assert response.status_code == 200, response.text
    assert {field: change["new"] for field, change in response.json()["corrections_applied"].items()} == saved

    db_session.refresh(db_invoice)
    for field, value in saved.items():
        assert getattr(db_invoice, field) == value, field


@pytest.mark.parametrize("router_module,schema_name", [
    ("routers.audit", "InvoiceExtractionSchema"),
    ("routers.outbound_audit", "OutboundInvoiceExtractionSchema"),
])
def test_every_extracted_field_with_a_column_is_correctable(router_module, schema_name):
    """BE Gap 531: a field extraction stores on the invoice can also be corrected, so a new field cannot silently miss the list."""
    import importlib

    import agents.extraction_agent as extraction_agent

    router_code = importlib.import_module(router_module)
    stored_fields = set(getattr(extraction_agent, schema_name).model_fields) & set(Invoice.model_fields)
    assert stored_fields - set(router_code._CORRECTABLE_FIELDS) == set()
    list_fields = {field for field, kind in router_code._CORRECTABLE_FIELDS.items() if kind == "list"}
    assert set(router_code._LIST_ENTRY_MODELS) == list_fields


ORIGINAL_TAXES = [{"tax_type": "VAT", "amount": 10.0}]


@pytest.mark.parametrize("corrections,bad_field", [
    ({"currency": "EURO"}, "currency"),
    ({"currency": 978}, "currency"),
    ({"discount_percent": "150"}, "discount_percent"),
    ({"discount_percent": "nan"}, "discount_percent"),
    ({"taxes": [{"rate_percent": 9}]}, "taxes"),
    ({"tax_ids": "GSTIN 27AAPFU0939F1ZV"}, "tax_ids"),
    ({"addresses": [{"address_type": "billing", "text": "12 Main St", "zip": "411001"}]}, "addresses"),
])
@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_unreadable_new_field_correction_is_refused(db_session, corrections, bad_field, flow_direction, url, status_value):
    """BE Gap 531: a bad currency code, percentage or list entry gets 422 naming the field; nothing is saved."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, currency="USD", invoice_number="INV-1", taxes=ORIGINAL_TAXES, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {**corrections, "invoice_number": "INV-2"}})
    assert response.status_code == 422
    assert [c["field"] for c in response.json()["detail"]["invalid_corrections"]] == [bad_field]

    db_session.refresh(db_invoice)
    assert (db_invoice.currency, db_invoice.invoice_number, db_invoice.taxes) == ("USD", "INV-1", ORIGINAL_TAXES)
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("cleared", ["", [], None])
@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_clearing_a_list_field_stores_an_empty_list(db_session, cleared, flow_direction, url, status_value):
    """BE Gap 531: an empty correction on a list field clears it to [], never NULL."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, taxes=ORIGINAL_TAXES, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {"taxes": cleared}})
    assert response.status_code == 200, response.text

    db_session.refresh(db_invoice)
    assert db_invoice.taxes == []


# Two "not verified in source" alerts carry the same formatted number as their message (BE Gap 537's trigger).
SAME_MESSAGE_ALERTS = [
    {"type": "subtotal_not_verified_in_source", "field": "subtotal", "message": "1,250.00"},
    {"type": "grand_total_not_verified_in_source", "field": "grand_total", "message": "1,250.00"},
    {"type": "tax_mismatch", "field": "tax_amount", "message": "Subtotal (1250.00) + Tax (0.00) does not match Grand Total (1300.00)"},
]


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_dismissing_one_alert_keeps_alerts_that_share_its_message(db_session, flow_direction, url, status_value):
    """BE Gap 537: dismissing the subtotal alert leaves the grand-total alert with the same message open."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=SAME_MESSAGE_ALERTS,
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"dismissed_alerts": [SAME_MESSAGE_ALERTS[0]]})
    assert response.status_code == 200, response.text
    assert response.json()["remaining_alerts"] == SAME_MESSAGE_ALERTS[1:]
    assert response.json()["unmatched_dismissals"] == []

    db_session.refresh(db_invoice)
    assert db_invoice.sa_alerts == SAME_MESSAGE_ALERTS[1:]
    log = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).one()
    assert log.details["dismissed_alerts"] == [SAME_MESSAGE_ALERTS[0]]


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_a_message_string_dismissal_removes_one_alert_per_entry(db_session, flow_direction, url, status_value):
    """BE Gap 537: an older integration's message string removes one alert per entry, not every alert with that text."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=SAME_MESSAGE_ALERTS,
    )
    db_session.add(db_invoice)
    db_session.commit()

    assert client.put(url.format(id=invoice_id), json={"dismissed_alerts": ["1,250.00"]}).status_code == 200
    db_session.refresh(db_invoice)
    assert db_invoice.sa_alerts == SAME_MESSAGE_ALERTS[1:]

    assert client.put(url.format(id=invoice_id), json={"dismissed_alerts": ["1,250.00"]}).status_code == 200
    db_session.refresh(db_invoice)
    assert db_invoice.sa_alerts == SAME_MESSAGE_ALERTS[2:]


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_dismissals_that_match_nothing_are_reported_and_the_rest_is_saved(db_session, flow_direction, url, status_value):
    """BE Gap 538 (founder ruling: save and warn): unmatched dismissals come back; the real dismissal and correction save."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, invoice_number="INV-1", sa_alerts=SAME_MESSAGE_ALERTS[:1],
    )
    db_session.add(db_invoice)
    db_session.commit()

    unmatched = ["Totally nonexistent alert text", {"type": "another_fake_type"}]
    response = client.put(
        url.format(id=invoice_id),
        json={"dismissed_alerts": [SAME_MESSAGE_ALERTS[0], *unmatched], "corrections": {"invoice_number": "INV-2"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["unmatched_dismissals"] == unmatched

    db_session.refresh(db_invoice)
    assert (db_invoice.sa_alerts, db_invoice.invoice_number) == ([], "INV-2")
    log = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).one()
    assert log.details["unmatched_dismissals"] == unmatched


BALANCED_INVOICE = {"subtotal": 500.0, "tax_amount": 20.0, "grand_total": 520.0, "items": [{"description": "Widget", "amount": 500.0}]}


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_a_correction_that_breaks_the_totals_raises_an_alert_without_blocking(db_session, flow_direction, url, status_value):
    """BE Gap 535 (founder ruling: alert, not block): the tracker's own case — old alert dismissed, total corrected to 100."""
    invoice_id = uuid4()
    old_alert = {"type": "tax_mismatch", "field": "tax_amount", "message": "Math mismatch"}
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=[old_alert], **BALANCED_INVOICE,
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {"dismissed_alerts": [old_alert], "corrections": {"grand_total": 100}}
    if flow_direction == "INBOUND":
        payload["status"] = "PAID"
    response = client.put(url.format(id=invoice_id), json=payload)
    assert response.status_code == 200, response.text

    raised = response.json()["remaining_alerts"]
    assert [(a["type"], a["field"], a["raised_by"]) for a in raised] == [("tax_mismatch", "tax_amount", "correction")]
    assert response.json()["raised_alerts"] == raised
    assert "Grand Total (100.00)" in raised[0]["message"]

    db_session.refresh(db_invoice)
    assert db_invoice.sa_alerts == raised
    assert db_invoice.grand_total == 100.0
    if flow_direction == "INBOUND":
        assert db_invoice.status == "PAID"
    log = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).one()
    assert log.details["raised_alerts"] == raised


@pytest.mark.parametrize("corrections", [
    {"tax_amount": 30, "grand_total": 530},  # still reconciles
    {"invoice_number": "INV-2"},  # not a money field
])
@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_a_correction_that_keeps_the_totals_consistent_raises_nothing(db_session, corrections, flow_direction, url, status_value):
    """BE Gap 535: no alert when the corrected figures still add up, or when no money field changed."""
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=[], **BALANCED_INVOICE,
    ))
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": corrections})
    assert response.status_code == 200, response.text
    assert response.json()["remaining_alerts"] == []


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_totals_that_never_reconciled_are_not_flagged_again_by_a_correction(db_session, flow_direction, url, status_value):
    """BE Gap 535: the row has no round_off column, so totals that were already off before the correction are not re-flagged."""
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=[], **{**BALANCED_INVOICE, "grand_total": 540.0},
    ))
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {"tax_amount": 25}})
    assert response.status_code == 200, response.text
    assert response.json()["remaining_alerts"] == []


def _required_field_values(flow_direction):
    from datetime import date

    name_field = "vendor_name" if flow_direction == "INBOUND" else "customer_name"
    return {name_field: "ACME Corp", "invoice_number": "INV-1", "invoice_date": date(2026, 1, 15), "grand_total": 520.0}


@pytest.mark.parametrize("blank", ["", "   ", None])
@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_a_required_field_cannot_be_emptied_by_a_correction(db_session, blank, flow_direction, url, status_value):
    """BE Gap 532 (founder ruling): clearing a required field gets 422 naming it; nothing is saved or logged."""
    values = _required_field_values(flow_direction)
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=[], **values,
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {field: blank for field in values}})
    assert response.status_code == 422, response.text
    invalid = response.json()["detail"]["invalid_corrections"]
    assert sorted(c["field"] for c in invalid) == sorted(values)
    assert all("required" in c["reason"] for c in invalid)

    db_session.refresh(db_invoice)
    assert {field: getattr(db_invoice, field) for field in values} == values
    assert db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all() == []


@pytest.mark.parametrize("flow_direction,url,status_value", RESOLVE_ENDPOINTS)
def test_an_optional_field_can_still_be_cleared(db_session, flow_direction, url, status_value):
    """BE Gap 532: only required fields are protected — due_date clears; a blank on an already-empty required field is ignored."""
    from datetime import date

    name_field = "vendor_name" if flow_direction == "INBOUND" else "customer_name"
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", flow_direction=flow_direction,
        status=status_value, sa_alerts=[], due_date=date(2026, 2, 15),
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(url.format(id=invoice_id), json={"corrections": {"due_date": "", name_field: ""}})
    assert response.status_code == 200, response.text
    assert list(response.json()["corrections_applied"]) == ["due_date"]

    db_session.refresh(db_invoice)
    assert db_invoice.due_date is None


def test_admin_sees_who_changed_what_newest_first(db_session):
    """Change history (founder request with BE Gap 532): an Admin reads an invoice's saved changes —
    who, role, when, old → new, dismissed alerts — newest first."""
    from datetime import timedelta

    from models import User

    invoice_id = uuid4()
    alert = {"type": "tax_mismatch", "field": "tax_amount", "message": "Math mismatch"}
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", status="AUDIT_REQUIRED",
        vendor_name="ACME Corp", sa_alerts=[alert], **BALANCED_INVOICE,
    ))
    db_session.commit()

    url = f"/api/v1/audit/resolve/{invoice_id}"
    assert client.put(url, json={"corrections": {"vendor_name": "ACME Corporation"}, "dismissed_alerts": [alert]}).status_code == 200
    first = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).one()
    first.timestamp = first.timestamp - timedelta(minutes=5)
    db_session.add(first)
    db_session.commit()
    assert client.put(url, json={"status": "PAID"}).status_code == 200

    response = client.get(f"/api/v1/audit-history/{invoice_id}")
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert [(e["action"], e["target_status"]) for e in entries] == [("RESOLVE_INVOICE", "PAID"), ("RESOLVE_INVOICE", None)]
    assert entries[1]["corrections"] == {"vendor_name": {"old": "ACME Corp", "new": "ACME Corporation"}}
    assert entries[1]["dismissed_alerts"] == [alert]

    user = db_session.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).one()
    assert {(e["actor_email"], e["actor_role"], e["auth_method"]) for e in entries} == {(user.email, MOCK_ROLE, "clerk")}
    assert entries[0]["timestamp"].endswith("+00:00")


def test_change_history_reads_older_rows_and_outbound_lifecycle_rows(db_session):
    """Change history: a row written before BE Gap 537 shows its raw dismissal input; Confirm Send (BE Gap 551)
    shows its status change, notified staff and the API key used (BE Gap 552)."""
    from datetime import datetime, timedelta

    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="SENT", sa_alerts=[],
    ))
    now = datetime.utcnow()
    db_session.add(AuditLog(
        tenant_id=MOCK_TENANT_ID, invoice_id=invoice_id, actor_user_id=uuid4(), actor_role="Admin",
        action="RESOLVE_OUTBOUND_INVOICE", timestamp=now - timedelta(hours=1),
        details={"dismissed_alerts_input": ["missing_required_field"], "corrections": {}},
    ))
    db_session.add(AuditLog(
        tenant_id=MOCK_TENANT_ID, invoice_id=invoice_id, actor_user_id=uuid4(), actor_role="Admin",
        action="CONFIRM_SEND_OUTBOUND_INVOICE", timestamp=now,
        details={"previous_status": "NEEDS_REVIEW", "target_status": "SENT", "notify_emails": ["ops@acme.test"],
                 "auth_method": "api_key", "api_key_prefix": "inv_live_abcd"},
    ))
    db_session.commit()

    entries = client.get(f"/api/v1/audit-history/{invoice_id}").json()["entries"]
    assert [e["action"] for e in entries] == ["CONFIRM_SEND_OUTBOUND_INVOICE", "RESOLVE_OUTBOUND_INVOICE"]
    sent = entries[0]
    assert (sent["previous_status"], sent["target_status"], sent["notify_emails"]) == ("NEEDS_REVIEW", "SENT", ["ops@acme.test"])
    assert (sent["auth_method"], sent["api_key_prefix"], sent["actor_email"]) == ("api_key", "inv_live_abcd", None)
    assert entries[1]["dismissed_alerts"] == ["missing_required_field"]


def test_change_history_is_admin_only(db_session):
    """Change history: a non-Admin — even one allowed to audit — gets 403."""
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf", status="AUDIT_REQUIRED", sa_alerts=[]))
    db_session.commit()
    _viewer_row_with_audit_permission(db_session)

    response = client.get(f"/api/v1/audit-history/{invoice_id}", headers=VIEWER)
    assert response.status_code == 403
    assert "Admin" in response.json()["detail"]


def test_change_history_of_another_tenants_invoice_is_not_found(db_session):
    """Change history: tenant-scoped like every other invoice read."""
    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=uuid4(), file_path="mock/invoice.pdf", status="PAID", sa_alerts=[]))
    db_session.commit()

    assert client.get(f"/api/v1/audit-history/{invoice_id}").status_code == 404


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
        subtotal=80.0,
        grand_total=100.0,
        items=[{"description": "Item 1", "amount": 80.0}],
        sa_alerts=[]
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {
        "corrections": {
            "grand_total": 150.0,
            "subtotal": 120.0,
            "items": [{"description": "Item 1", "amount": 80.0}, {"description": "Item 2", "amount": 40.0}]
        }
    }
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["corrections_applied"] == {
        "grand_total": {"old": 100.0, "new": 150.0},
        "subtotal": {"old": 80.0, "new": 120.0},
        "items": {
            "old": [{"description": "Item 1", "amount": 80.0}],
            "new": [{"description": "Item 1", "amount": 80.0}, {"description": "Item 2", "amount": 40.0}]
        }
    }

    db_session.refresh(db_invoice)
    assert db_invoice.status == "COMPLETED"  # untouched -- no status was requested
    assert db_invoice.grand_total == 150.0
    assert db_invoice.subtotal == 120.0
    assert db_invoice.items == [{"description": "Item 1", "amount": 80.0}, {"description": "Item 2", "amount": 40.0}]

    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    assert audit_logs[0].details["target_status"] is None
    assert audit_logs[0].details["corrections"] == {
        "grand_total": {"old": 100.0, "new": 150.0},
        "subtotal": {"old": 80.0, "new": 120.0},
        "items": {
            "old": [{"description": "Item 1", "amount": 80.0}],
            "new": [{"description": "Item 1", "amount": 80.0}, {"description": "Item 2", "amount": 40.0}]
        }
    }


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
             "extracted_data": {"vendor_name": "ACME Corporation"}, "status": "COMPLETED", "alerts": [],
         }):
        payload = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is True

    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.vendor_name == "ACME Corporation")
    ).all()
    assert len(templates) == 1
    # Feature 18: the auditor's standing rule is now a structured rule object
    # rather than a bare sentence. Its rendered `text` is byte-identical to the
    # sentence this path always produced (so the extraction prompt is unchanged),
    # and the field it came from is now recoverable structurally.
    from utils.rule_schema import normalize_constraints

    stored_rule = templates[0].rules["constraints"][0]
    assert isinstance(stored_rule, dict)
    assert stored_rule["field"] == "vendor_name"
    assert stored_rule["origin"] == "audit_correction"
    assert stored_rule["kind"] == "extraction"
    assert "vendor name" in normalize_constraints(templates[0].rules["constraints"])[0]

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
             "extracted_data": {"vendor_name": "Wrong Extraction Corp"}, "status": "COMPLETED", "alerts": [],
         }):
        payload = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is False
    assert "Safety check failed" in data["standing_rule_result"]["reason"]
    assert data["corrections_applied"] == {"vendor_name": {"old": "ACME Corp", "new": "ACME Corporation"}}  # correction still applied

    db_session.refresh(db_invoice)
    assert db_invoice.vendor_name == "ACME Corporation"  # correction persisted despite rejected rule

    templates = db_session.exec(select(ExtractionTemplate)).all()
    assert templates == []  # no rule was written


def test_standing_rule_safety_check_passes_with_canonical_whitespace_or_formatting_gap543(db_session):
    """Gap 543: Re-extraction producing equivalent text with surrounding whitespace or
    canonical formatting must pass the safety check (previously failed with strict str != str)."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("routers.audit._run_ocr", return_value="Mock OCR Text"), \
         patch("routers.audit.run_extraction_agent", return_value={
             "extracted_data": {"vendor_name": "  ACME Corporation  "}, "status": "COMPLETED", "alerts": [],
         }):
        payload = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is True


def test_standing_rule_safety_check_uses_holdout_invoice_gap543(db_session, tmp_path):
    """Gap 543: When an eligible holdout invoice from the same vendor exists, safety check
    validates the candidate rule on the holdout document to avoid tautological self-validation."""
    # Create holdout file on disk
    holdout_file = tmp_path / "holdout_invoice.pdf"
    holdout_file.write_text("Mock PDF Content")

    invoice_id = uuid4()
    holdout_id = uuid4()

    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    holdout_invoice = Invoice(
        id=holdout_id, tenant_id=MOCK_TENANT_ID, file_path=str(holdout_file),
        vendor_name="ACME Corp", status="COMPLETED", grand_total=120.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.add(holdout_invoice)
    db_session.commit()

    with patch("routers.audit._run_ocr", return_value="Mock OCR Holdout Text") as m_ocr, \
         patch("routers.audit.run_extraction_agent", return_value={
             "extracted_data": {"vendor_name": "ACME Corporation"}, "status": "COMPLETED", "alerts": [],
         }) as m_agent:
        payload = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    assert response.json()["standing_rule_result"]["applied"] is True
    # Verify extraction agent was called with the holdout invoice file path!
    m_agent.assert_called_once()
    assert m_agent.call_args[0][0] == str(holdout_file)


def test_standing_rule_skipped_without_vendor_name(db_session):
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name=None, status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {"corrections": {"vendor_name": "ACME Corp"}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 200
    assert response.json()["standing_rule_result"]["applied"] is False


def test_resolve_with_standing_rule_requires_can_train_gap544(db_session):
    """Gap 544 (AF-9): Audit resolve with apply_as_standing_rule=True requires the
    Trainer (can_train) permission. A user with only can_audit gets HTTP 403."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    _viewer_row_with_audit_permission(db_session)

    # With apply_as_standing_rule=True, caller without can_train is denied with 403
    payload = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload, headers=VIEWER)
    assert response.status_code == 403
    assert "AI Trainer permission required" in response.json()["detail"]

    # Without apply_as_standing_rule, regular resolve succeeds for the same auditor
    payload_normal = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": False}
    response_normal = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload_normal, headers=VIEWER)
    assert response_normal.status_code == 200


def test_resolve_with_standing_rule_allowed_with_can_train_gap544(db_session):
    """Gap 544: A user with can_train=True is permitted to apply standing rules."""
    from models import User
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    _viewer_row_with_audit_permission(db_session)
    user = db_session.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).first()
    user.can_train = True
    db_session.add(user)
    db_session.commit()

    with patch("routers.audit._run_ocr", return_value="Mock OCR Text"), \
         patch("routers.audit.run_extraction_agent", return_value={
             "extracted_data": {"vendor_name": "ACME Corporation"}, "status": "COMPLETED", "alerts": [],
         }):
        payload = {"corrections": {"vendor_name": "ACME Corporation"}, "apply_as_standing_rule": True}
        response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload, headers=VIEWER)

    assert response.status_code == 200
    assert response.json()["standing_rule_result"]["applied"] is True



@pytest.mark.parametrize("var_field, new_val", [
    ("grand_total", 250.0),
    ("subtotal", 200.0),
    ("tax_amount", 50.0),
    ("invoice_number", "INV-9999"),
    ("invoice_date", "2026-05-01"),
    ("due_date", "2026-06-01"),
    ("po_number", "PO-8888"),
])
def test_standing_rule_disallowed_for_variable_transaction_fields_gap542(db_session, var_field, new_val):
    """Gap 542: A one-invoice correction to variable transactional fields must NEVER
    become a standing rule across future vendor invoices. The correction applies to the
    invoice, but the standing rule is skipped with an explanatory notice."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path=f"mock/{var_field}.pdf",
        vendor_name="Acme Supplies", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    payload = {"corrections": {var_field: new_val}, "apply_as_standing_rule": True}
    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["standing_rule_result"]["applied"] is False
    assert "Standing rules cannot be created for variable transactional fields" in data["standing_rule_result"]["reason"]
    assert var_field in data["standing_rule_result"]["reason"]

    # Verify no template rule was written
    templates = db_session.exec(select(ExtractionTemplate)).all()
    assert templates == []


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


# ---------------------------------------------------------------------------
# Gap 407: REVIEW_LATER / NEEDS_RESUBMISSION — non-terminal deferral states
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target_status", ["REVIEW_LATER", "NEEDS_RESUBMISSION"])
def test_resolve_to_deferral_status_succeeds_from_audit_required(db_session, target_status):
    """Either new status is reachable from AUDIT_REQUIRED, the normal case, by
    any user who can already resolve invoices -- no Admin gate, unlike reopen."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=["Math mismatch"],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": target_status, "dismissed_alerts": []},
    )
    assert response.status_code == 200, response.text

    db_session.refresh(db_invoice)
    assert db_invoice.status == target_status
    # Neither is a finalization -- action must log as RESOLVE_INVOICE, not
    # REOPEN_INVOICE (that branch checks specifically for AUDIT_REQUIRED).
    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "RESOLVE_INVOICE"
    assert audit_logs[0].details["target_status"] == target_status


@pytest.mark.parametrize("target_status", ["REVIEW_LATER", "NEEDS_RESUBMISSION"])
@pytest.mark.parametrize("terminal_status", ["PAID", "REJECTED"])
def test_deferral_status_rejected_from_a_terminal_invoice(db_session, target_status, terminal_status):
    """Neither new status may be set directly on an already-finalized invoice --
    that would silently un-finalize it with no Admin involved. Must go through
    the existing AUDIT_REQUIRED reopen (Admin-only) first."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status=terminal_status, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": target_status, "dismissed_alerts": []},
    )
    assert response.status_code == 400
    assert "reopen it first" in response.json()["detail"]

    db_session.refresh(db_invoice)
    assert db_invoice.status == terminal_status  # unchanged


@pytest.mark.parametrize("target_status", ["REVIEW_LATER", "NEEDS_RESUBMISSION"])
def test_deferral_status_does_not_trigger_finalization_side_effects(db_session, target_status):
    """The webhook dispatch, staff-notify, Drive-archive, and email-summary
    blocks in resolve_audit_invoice() all gate on target_status in
    ("PAID", "REJECTED") specifically -- confirms neither new status
    accidentally fires an invoice.approved/invoice.rejected webhook or a
    customer/staff notification meant for an actual finalization."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        vendor_name="ACME Corp", status="AUDIT_REQUIRED", grand_total=100.0, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("services.webhooks.dispatch_webhook_event") as m_webhook, \
         patch("services.staff_notify.notify_auditor_action") as m_notify:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": target_status, "dismissed_alerts": []},
        )
        assert response.status_code == 200, response.text
        m_webhook.assert_not_called()
        m_notify.assert_not_called()


def test_deferral_status_not_reachable_via_invalid_status_message(db_session):
    """The 400 error message for a genuinely invalid status must list all five
    valid values -- a stale error message would be a real regression for
    anyone reading it to debug an integration."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "BOGUS_STATUS", "dismissed_alerts": []},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    for expected in ("PAID", "REJECTED", "AUDIT_REQUIRED", "REVIEW_LATER", "NEEDS_RESUBMISSION"):
        assert expected in detail


# ── Gap 557: Unknown currency sent as null/None in webhooks ───────────────────

def test_resolve_webhook_sends_none_currency_when_unknown_gap557(db_session):
    """Gap 557 (AF-22): Unknown currency must be sent as null/None in webhook payload,
    not coerced to 'USD'."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        vendor_name="Global Tech",
        grand_total=500.0,
        currency=None,  # unknown currency
        sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("services.webhooks.dispatch_webhook_event") as m_webhook:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": "PAID", "dismissed_alerts": []},
        )
        assert response.status_code == 200
        m_webhook.assert_called_once()
        payload = m_webhook.call_args[0][3]
        assert payload["currency"] is None


def test_reopen_webhook_and_reject_reason_gap558(db_session):
    """Gap 558: Admin reopen dispatches invoice.reopened webhook;
    REJECTED finalization includes reject_reason in webhook payload."""
    db_tenant = db_session.exec(select(Tenant).where(Tenant.id == MOCK_TENANT_ID)).first()
    if not db_tenant:
        db_tenant = Tenant(id=MOCK_TENANT_ID, name="Test Workspace", domain="test.example.com")
        db_session.add(db_tenant)
        db_session.commit()
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        vendor_name="Acme Corp",
        invoice_number="INV-558",
        status="PAID",
        grand_total=500.0,
        currency="USD",
        sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    # 1. Admin reopen (PAID -> AUDIT_REQUIRED) dispatches invoice.reopened
    with patch("services.webhooks.dispatch_webhook_event") as m_webhook:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": "AUDIT_REQUIRED"},
        )
        assert response.status_code == 200
        m_webhook.assert_called_once()
        call_args = m_webhook.call_args[0]
        event_type = call_args[2]
        payload = call_args[3]
        assert event_type == "invoice.reopened"
        assert payload["invoice_id"] == str(invoice_id)
        assert payload["status"] == "AUDIT_REQUIRED"

    # 2. Reject with reason dispatches invoice.rejected with reject_reason in payload
    with patch("services.webhooks.dispatch_webhook_event") as m_webhook:
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": "REJECTED", "reject_reason": "Duplicate invoice number for PO-1234"},
        )
        assert response.status_code == 200
        m_webhook.assert_called_once()
        call_args = m_webhook.call_args[0]
        event_type = call_args[2]
        payload = call_args[3]
        assert event_type == "invoice.rejected"
        assert payload["invoice_id"] == str(invoice_id)
        assert payload["status"] == "REJECTED"
        assert payload["reject_reason"] == "Duplicate invoice number for PO-1234"


def test_inbound_resolve_rejects_outbound_invoice_gap536(db_session):
    """Gap 536: Inbound resolve endpoint must reject OUTBOUND invoices with 404."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/outbound.pdf",
        status="NEEDS_REVIEW",
        flow_direction="OUTBOUND",
        sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "PAID"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.parametrize("start_status,target_status", [
    ("PAID", "REJECTED"),
    ("REJECTED", "PAID"),
])
def test_terminal_flip_requires_admin_reopen_gap529(db_session, start_status, target_status):
    """Gap 529: Direct terminal flip PAID <-> REJECTED must return 400 requiring Admin reopen."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status=start_status,
        flow_direction="INBOUND",
        sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": target_status},
    )
    assert response.status_code == 400
    assert "reopen it first" in response.json()["detail"]


def test_post_commit_notify_failure_does_not_raise_400_gap556(db_session):
    """Gap 556: Staff notification failure post-commit must return 200 with notice, never 400."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    with patch("services.staff_notify.notify_auditor_action", side_effect=Exception("Simulated SMTP timeout")):
        response = client.put(
            f"/api/v1/audit/resolve/{invoice_id}",
            json={"status": "PAID"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["email_notify"] == {"sent": False, "reason": "Simulated SMTP timeout"}

    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"


def test_pattern_detection_ignores_variable_fields_gap547(db_session):
    """Gap 547: Pattern detection excludes variable transaction fields like grand_total."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        grand_total=100.0,
        sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    # Even with corrections on variable field grand_total, no pattern rule is suggested
    res = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"corrections": {"grand_total": 120.0}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["suggested_rule"] is None


def test_resolve_rate_limit_exceeded_returns_429_gap561(db_session, monkeypatch):
    """Gap 561: the (max_requests + 1)th resolve inside the window is refused with HTTP 429 on the real
    route, and the invoice is untouched by the refused call."""
    from routers.audit import _resolve_rate_limiter
    monkeypatch.setattr(_resolve_rate_limiter, "max_requests", 2)
    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=[{"id": "a1", "type": "x", "message": "m1"}, {"id": "a2", "type": "x", "message": "m2"}],
    ))
    db_session.commit()

    first = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"dismissed_alerts": [{"id": "a1"}]})
    second = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"dismissed_alerts": []})
    third = client.put(f"/api/v1/audit/resolve/{invoice_id}", json={"dismissed_alerts": [{"id": "a2"}]})
    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert "Rate limit" in third.json()["detail"]
    db_session.expire_all()
    assert [a["id"] for a in db_session.get(Invoice, invoice_id).sa_alerts] == ["a2"]  # refused call changed nothing


def test_rate_limit_window_is_per_tenant_and_principal_gap561():
    """Gap 561: an API key and a Clerk user of the same tenant do not share one window, and two tenants
    never do -- so one runaway integration key cannot lock the tenant's auditors out."""
    from types import SimpleNamespace
    from utils.rate_limiter import rate_limit_key
    tenant, other = uuid4(), uuid4()
    api_key = SimpleNamespace(tenant_id=tenant, auth_method="api_key", api_key_prefix="ieq_ab12", user_id=None)
    auditor = SimpleNamespace(tenant_id=tenant, auth_method="clerk", api_key_prefix=None, user_id="user_1")
    other_auditor = SimpleNamespace(tenant_id=other, auth_method="clerk", api_key_prefix=None, user_id="user_1")
    keys = {rate_limit_key(api_key), rate_limit_key(auditor), rate_limit_key(other_auditor)}
    assert len(keys) == 3
    assert rate_limit_key(api_key) == f"{tenant}:key:ieq_ab12"
    assert rate_limit_key(auditor) == f"{tenant}:user:user_1"


def test_rate_limiter_retries_redis_after_the_cooldown_gap561(monkeypatch):
    """Gap 561: after a Redis failure the limiter degrades to its in-process window, then tries Redis
    again once the cooldown has passed instead of staying degraded for the life of the process."""
    from utils.rate_limiter import SlidingWindowRateLimiter
    limiter = SlidingWindowRateLimiter(key_prefix="ratelimit:test:", max_requests=5, window_seconds=60)
    limiter.redis_retry_seconds = 0.0
    attempts = []

    def failing_redis(*_a, **_k):
        attempts.append(1)
        raise ConnectionError("down")

    import utils.rate_limiter as rl
    monkeypatch.setattr(rl, "get_settings", lambda: SimpleNamespaceSettings())
    monkeypatch.setitem(sys.modules, "redis", type("R", (), {"Redis": type("C", (), {"from_url": staticmethod(failing_redis)})}))
    assert limiter.check("t") is True   # first call: Redis attempt fails, in-process window used
    assert limiter.check("t") is True   # cooldown of 0s has passed: Redis is attempted again
    assert len(attempts) == 2


class SimpleNamespaceSettings:
    REDIS_URL = "redis://localhost:1/0"


def test_postgres_test_port_localhost_guard_gap525():
    """Gap 525: the fixture drops every table after each test, so TEST_DATABASE_URL is accepted only for a
    local throwaway database whose name says "test". The dev database on localhost is refused too."""
    from urllib.parse import urlparse

    def guard_accepts(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.hostname in ("localhost", "127.0.0.1") and "test" in (parsed.path or "").lower()

    assert not guard_accepts("postgresql://user:pass@production-db.azure.com:5432/invoice_db_test")
    assert not guard_accepts("postgresql://user:pass@localhost.evil.com:5432/invoice_db_test")
    assert not guard_accepts("postgresql://postgres:pass@localhost:5433/invoice_db")  # the dev database
    assert guard_accepts("postgresql://postgres:pass@localhost:5433/invoice_db_test")
    assert guard_accepts("postgresql://postgres:pass@127.0.0.1:5433/invoice_test")