import pytest
from datetime import datetime
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
        m_webhook.assert_not_called()
        m_notify.assert_not_called()

    db_session.refresh(db_invoice)
    assert db_invoice.status == "AUDIT_REQUIRED"

    audit_logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "REOPEN_INVOICE"
    assert audit_logs[0].details["target_status"] == "AUDIT_REQUIRED"

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
    # Feature 18: the auditor's standing rule is now a structured rule object
    # rather than a bare sentence. Its rendered `text` is byte-identical to the
    # sentence this path always produced (so the extraction prompt is unchanged),
    # and the field it came from is now recoverable structurally.
    from utils.rule_schema import normalize_constraints

    stored_rule = templates[0].rules["constraints"][0]
    assert isinstance(stored_rule, dict)
    assert stored_rule["field"] == "grand_total"
    assert stored_rule["origin"] == "audit_correction"
    assert stored_rule["kind"] == "extraction"
    assert "grand total" in normalize_constraints(templates[0].rules["constraints"])[0]

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


# ---------------------------------------------------------------------------
# Gap 419: parking an invoice must NOT dismiss its alerts
#
# The FE's handleResolve() sent `dismissed_alerts` on every action, so parking
# an invoice permanently deleted every alert on it -- you parked it to review
# later and came back to nothing to review, and you sent an invoice back for
# resubmission having erased the record of what was wrong. The FE fix stops
# sending them; these tests pin the backend contract the FE now relies on.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target_status", ["REVIEW_LATER", "NEEDS_RESUBMISSION"])
def test_parking_without_dismissed_alerts_preserves_them(db_session, target_status):
    """The contract the fixed FE depends on: omit `dismissed_alerts` and every
    alert survives the status change."""
    invoice_id = uuid4()
    alerts = [
        {"id": "a1", "type": "line_items_mismatch", "message": "Sum mismatch"},
        {"id": "a2", "type": "tax_mismatch", "message": "Tax mismatch"},
    ]
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=alerts,
    )
    db_session.add(db_invoice)
    db_session.commit()

    # No dismissed_alerts key at all -- exactly what the FE now sends.
    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": target_status},
    )
    assert response.status_code == 200, response.text

    db_session.refresh(db_invoice)
    assert db_invoice.status == target_status
    assert len(db_invoice.sa_alerts) == 2, "parking must not dismiss alerts"
    assert {a["id"] for a in db_invoice.sa_alerts} == {"a1", "a2"}


def test_terminal_resolve_still_dismisses_alerts(db_session):
    """Regression guard on the other side: Gap 419 must not stop a genuine
    finalization from clearing the alerts it resolved."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=["Math mismatch", "Invalid vendor"],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "PAID", "dismissed_alerts": ["Math mismatch"]},
    )
    assert response.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"
    assert db_invoice.sa_alerts == ["Invalid vendor"]


# ---------------------------------------------------------------------------
# Gap 420: a parked invoice can be returned to the audit queue
#
# Before this, BOTH guards rejected the transition -- the Admin check AND the
# "only PAID/REJECTED can be reopened" check -- so a parked invoice could not
# be un-parked by ANY role, including Admin. Parking was a one-way door.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("parked_status", ["REVIEW_LATER", "NEEDS_RESUBMISSION"])
def test_non_admin_can_unpark_to_audit_queue(db_session, parked_status):
    """Parking was never a finalization, so Gap 193's Admin-only rule must not
    apply to undoing it -- whoever could park it can put it back."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status=parked_status, sa_alerts=["Sum mismatch"],
    )
    db_session.add(db_invoice)
    db_session.commit()

    _viewer_row_with_audit_permission(db_session)

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "AUDIT_REQUIRED"},
        headers=VIEWER,
    )
    assert response.status_code == 200, response.text

    db_session.refresh(db_invoice)
    assert db_invoice.status == "AUDIT_REQUIRED"
    # The alerts that justified parking it must still be there to review.
    assert db_invoice.sa_alerts == ["Sum mismatch"]


@pytest.mark.parametrize("parked_status", ["REVIEW_LATER", "NEEDS_RESUBMISSION"])
def test_unpark_records_where_it_came_from(db_session, parked_status):
    """The trail writes REOPEN_INVOICE for both un-park and Gap 193 reopen, so
    `previous_status` in details is the only thing telling them apart."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status=parked_status, sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "AUDIT_REQUIRED"},
    )
    assert response.status_code == 200

    logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == invoice_id)).all()
    assert len(logs) == 1
    assert logs[0].details["previous_status"] == parked_status
    assert logs[0].details["target_status"] == "AUDIT_REQUIRED"


def test_unpark_does_not_weaken_the_admin_only_reopen(db_session):
    """The security-relevant half of Gap 420: relaxing the gate for parked
    invoices must not let a non-Admin undo a genuine finalization."""
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
        json={"status": "AUDIT_REQUIRED"},
        headers=VIEWER,
    )
    assert response.status_code == 403
    assert "Admin" in response.json()["detail"]

    db_session.refresh(db_invoice)
    assert db_invoice.status == "PAID"  # unchanged


def test_cannot_unpark_an_invoice_that_was_never_parked(db_session):
    """AUDIT_REQUIRED -> AUDIT_REQUIRED is still a no-op the FE should never
    send, and is still rejected rather than silently accepted."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=[],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "AUDIT_REQUIRED"},
    )
    assert response.status_code == 400
    assert "Cannot reopen" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Gap 421: resubmission reason, and superseded invoices are read-only
# ---------------------------------------------------------------------------

def test_resubmission_reason_is_persisted(db_session):
    """Without this the column is dead and the vendor is told to resend with
    no statement of what to fix."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="AUDIT_REQUIRED", sa_alerts=["Total mismatch"],
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "NEEDS_RESUBMISSION", "resubmission_reason": "Line items do not sum to the total."},
    )
    assert response.status_code == 200, response.text

    db_session.refresh(db_invoice)
    assert db_invoice.status == "NEEDS_RESUBMISSION"
    assert db_invoice.resubmission_reason == "Line items do not sum to the total."


def test_resubmission_reason_is_cleared_when_the_invoice_moves_on(db_session):
    """A stale reason from a previous round must never be shown against a
    later decision."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="NEEDS_RESUBMISSION", sa_alerts=[], resubmission_reason="Old reason",
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(
        f"/api/v1/audit/resolve/{invoice_id}",
        json={"status": "AUDIT_REQUIRED"},
    )
    assert response.status_code == 200

    db_session.refresh(db_invoice)
    assert db_invoice.status == "AUDIT_REQUIRED"
    assert db_invoice.resubmission_reason is None


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "PAID"},
        {"status": "REVIEW_LATER"},
        {"corrections": {"grand_total": 99.0}},
        {"dismissed_alerts": ["Total mismatch"]},
    ],
)
def test_superseded_invoice_is_read_only(db_session, payload):
    """A replaced invoice is frozen history. Acting on it would write decisions
    onto a version nobody uses, and those writes would be invisible in every
    list because invoice_is_live() filters it out."""
    invoice_id = uuid4()
    db_invoice = Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/invoice.pdf",
        status="NEEDS_RESUBMISSION", sa_alerts=["Total mismatch"],
        superseded_at=datetime.utcnow(),
    )
    db_session.add(db_invoice)
    db_session.commit()

    response = client.put(f"/api/v1/audit/resolve/{invoice_id}", json=payload)
    assert response.status_code == 409
    assert "replaced" in response.json()["detail"].lower()

    db_session.refresh(db_invoice)
    assert db_invoice.status == "NEEDS_RESUBMISSION"
    assert db_invoice.sa_alerts == ["Total mismatch"]


def test_should_index_invoice_excludes_superseded():
    """Gap 421: status alone cannot express superseded-ness, so a re-index
    keyed on status would silently restore the vectors replace_invoice()
    deleted."""
    from chroma_client import should_index_invoice, should_index_status

    live = Invoice(tenant_id=MOCK_TENANT_ID, file_path="x.pdf", status="NEEDS_RESUBMISSION")
    superseded = Invoice(
        tenant_id=MOCK_TENANT_ID, file_path="x.pdf", status="NEEDS_RESUBMISSION",
        superseded_at=datetime.utcnow(),
    )

    # The status itself is indexable -- which is exactly why the status-only
    # check was not enough.
    assert should_index_status("NEEDS_RESUBMISSION") is True
    assert should_index_invoice(live) is True
    assert should_index_invoice(superseded) is False
    assert should_index_invoice(None) is False
