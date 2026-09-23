"""BE Gaps 728-734: the seven fixes that make the integration surface honest.

The theme running through all of them is the same: the API was not WRONG, it was
silent. It returned a mixture without saying so, reported success for a half-done
batch, showed PROCESSING for a file that was never queued, and hid a deletion
rather than reporting it. Each test below pins the thing that is now said out
loud.
"""
import io
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from dependencies import (
    API_KEY_USER_ID,
    MOCK_TENANT_ID,
    get_db_session,
    get_tenant_or_api_key_context,
)
from main import app
from models import AuditLog, Invoice, Tenant

client = TestClient(app)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


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


def _invoice(**kw) -> Invoice:
    defaults = dict(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path=f"mock/{uuid4()}.pdf",
        file_hash=uuid4().hex,
        invoice_number="INV-1",
        vendor_name="Vendor A",
        grand_total=100.0,
        status="COMPLETED",
        flow_direction="INBOUND",
        invoice_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 12, 0, 0),
    )
    defaults.update(kw)
    return Invoice(**defaults)


def _pdf_bytes() -> bytes:
    """A minimal but structurally real PDF -- `normalize_upload` sniffs the
    header, so a bare string would be refused before the handler is reached."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 728 — ALL refuses the filters whose meaning flips with direction
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "params",
    [
        {"flow_direction": "ALL", "status": "PAID"},
        {"flow_direction": "ALL", "status_in": "PAID,REJECTED"},
        {"flow_direction": "ALL", "vendor_name": "Vendor A"},
    ],
)
def test_all_refuses_direction_dependent_filters(db_session, params):
    """PAID means "we paid a supplier" inbound and "a customer paid us"
    outbound. Returning both under one filter puts money facing two ways in one
    list with nothing in the row to say which -- so it is refused, loudly,
    rather than documented and silently believed."""
    response = client.get("/api/v1/invoices", params=params)
    assert response.status_code == 400
    assert "flow_direction=ALL" in response.json()["detail"]


def test_all_is_fine_without_those_filters(db_session):
    db_session.add(_invoice(flow_direction="INBOUND", invoice_number="IN-1"))
    db_session.add(_invoice(flow_direction="OUTBOUND", invoice_number="OUT-1"))
    db_session.commit()

    response = client.get("/api/v1/invoices", params={"flow_direction": "ALL"})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_the_same_filters_still_work_per_direction(db_session):
    """The refusal is about the MIXTURE, not about the filters. Asking one
    direction at a time keeps everything it always had."""
    db_session.add(_invoice(flow_direction="INBOUND", status="PAID", invoice_number="IN-PAID"))
    db_session.add(_invoice(flow_direction="OUTBOUND", status="PAID", invoice_number="OUT-PAID"))
    db_session.commit()

    inbound = client.get(
        "/api/v1/invoices", params={"flow_direction": "INBOUND", "status": "PAID"}
    )
    assert inbound.status_code == 200
    assert [i["invoice_number"] for i in inbound.json()] == ["IN-PAID"]


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 729 WITHDRAWN — deletion is HARD, so there is nothing to report
# ═══════════════════════════════════════════════════════════════════════════

def test_deleted_invoices_are_not_listed(db_session):
    """The unconditional rule, unchanged from master. An `include_deleted`
    parameter briefly lived here and was withdrawn: it filtered on a column that
    no code writes, so it could never return a row."""
    db_session.add(_invoice(invoice_number="LIVE"))
    db_session.add(_invoice(invoice_number="GONE", deleted_at=datetime(2026, 9, 2, 9, 0, 0)))
    db_session.commit()

    numbers = [i["invoice_number"] for i in client.get("/api/v1/invoices").json()]
    assert numbers == ["LIVE"]


def test_the_list_takes_no_parameter_for_reading_deleted_rows(db_session):
    """Pins the withdrawal. If someone re-adds `include_deleted` without first
    re-introducing a writer for `deleted_at`, this fails and says why."""
    import inspect

    from routers.invoices import list_invoices

    params = inspect.signature(list_invoices).parameters
    assert "include_deleted" not in params, (
        "`include_deleted` is back. Before re-adding it, check that something "
        "actually WRITES Invoice.deleted_at -- as of Gap 460 (2026-09-08) "
        "deletion is a hard delete and services/invoice_deletion.py states that "
        "nothing sets that column any more, so the parameter can only ever "
        "return an empty list."
    )


def test_nothing_in_the_codebase_writes_invoice_deleted_at(db_session):
    """The premise itself, asserted rather than assumed -- this is the check
    that was missing when Gap 729 was built.

    A column that every read filters on and no write populates is inert. Reading
    it is not evidence that it is used; only a writer is."""
    import pathlib
    import re

    writer = re.compile(r"(?<!Document)\.deleted_at\s*=\s*(?!=)")
    offenders = []
    for folder in ("routers", "services", "queue_worker", "agents", "utils"):
        for path in pathlib.Path(folder).rglob("*.py"):
            for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if writer.search(line) and "deleted_at = None" not in line:
                    offenders.append(f"{path.as_posix()}:{num}")

    assert not offenders, (
        "Something now writes a `deleted_at`, so soft delete may be back: "
        f"{offenders}. If invoices are soft-deleted again, BE Gap 729 "
        "(include_deleted) becomes buildable -- and every read path has to be "
        "re-checked for the leaks that made Gap 460 remove it."
    )


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 730 — the timezone rule is stated and enforced
# ═══════════════════════════════════════════════════════════════════════════

def test_offset_aware_bound_is_converted_not_rejected(db_session):
    """Stored timestamps are naive UTC. An offset-bearing bound used to raise on
    Postgres and shift the window by the offset on SQLite -- one query, two
    answers, depending on the backend. It is now converted to UTC first."""
    db_session.add(_invoice(invoice_number="DONE", completed_at=datetime(2026, 9, 5, 10, 0, 0)))
    db_session.commit()

    # 14:30 at +05:30 IS 09:00 UTC, so the 10:00 UTC row is after it.
    ist = timezone(timedelta(hours=5, minutes=30))
    response = client.get(
        "/api/v1/invoices",
        params={"completed_since": datetime(2026, 9, 5, 14, 30, tzinfo=ist).isoformat()},
    )
    assert response.status_code == 200
    assert [i["invoice_number"] for i in response.json()] == ["DONE"]


def test_naive_bound_is_read_as_utc(db_session):
    db_session.add(_invoice(invoice_number="DONE", completed_at=datetime(2026, 9, 5, 10, 0, 0)))
    db_session.commit()

    response = client.get(
        "/api/v1/invoices", params={"completed_since": "2026-09-05T09:00:00"}
    )
    assert [i["invoice_number"] for i in response.json()] == ["DONE"]


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 731 — "queued" is reported, and recovery is NOT abandoned
# ═══════════════════════════════════════════════════════════════════════════

def test_status_reports_a_file_that_never_reached_the_queue(db_session):
    """The failure this surfaces: a queue send that failed leaves the invoice at
    PROCESSING, and the caller polling this endpoint could not distinguish that
    from an invoice being worked on right now. It waited forever."""
    stuck = _invoice(status="PROCESSING", last_enqueued_at=None)
    db_session.add(stuck)
    db_session.commit()

    body = client.get(f"/api/v1/invoices/status/{stuck.id}").json()
    assert body["status"] == "PROCESSING"
    assert body["queued"] is False


def test_status_reports_a_file_that_is_genuinely_being_worked_on(db_session):
    working = _invoice(
        status="PROCESSING", last_enqueued_at=datetime(2026, 9, 5, 10, 0, 0), processing_attempts=1
    )
    db_session.add(working)
    db_session.commit()

    body = client.get(f"/api/v1/invoices/status/{working.id}").json()
    assert body["queued"] is True
    assert body["processing_attempts"] == 1


def test_an_unqueued_invoice_is_left_recoverable(db_session):
    """Deliberately NOT marked FAILED. `services/invoice_reconciliation.py`
    sweeps exactly the statuses below and re-enqueues them, giving up only after
    repeated attempts -- failing the row here would throw away a file that is
    safely stored and would otherwise have been picked up."""
    from services.invoice_reconciliation import STUCK_STATUSES

    stuck = _invoice(status="PROCESSING", last_enqueued_at=None)
    db_session.add(stuck)
    db_session.commit()

    db_session.refresh(stuck)
    assert stuck.status in STUCK_STATUSES


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 732 — replace the file on an invoice nobody has decided on
# ═══════════════════════════════════════════════════════════════════════════

def _replace(invoice_id, data: bytes = None, name: str = "corrected.pdf"):
    return client.post(
        f"/api/v1/invoices/{invoice_id}/file",
        files={"file": (name, io.BytesIO(data or _pdf_bytes()), "application/pdf")},
    )


@pytest.mark.parametrize("decided", ["PAID", "REJECTED", "SENT"])
def test_a_decided_invoice_refuses_a_new_file(db_session, decided):
    """Once somebody has acted on it the row is evidence of a decision, and the
    document underneath it must not change quietly. 409, naming the remedy."""
    invoice = _invoice(status=decided)
    db_session.add(invoice)
    db_session.commit()

    response = _replace(invoice.id)
    assert response.status_code == 409
    assert "reopen" in response.json()["detail"].lower()


def test_replacing_the_same_file_again_is_a_no_op(db_session):
    """A retried request must not cost a second extraction."""
    same = _pdf_bytes()
    import hashlib

    invoice = _invoice(file_hash=hashlib.sha256(same).hexdigest(), status="AUDIT_REQUIRED")
    db_session.add(invoice)
    db_session.commit()

    response = _replace(invoice.id, same)
    assert response.status_code == 200
    assert response.json()["replaced"] is False
    db_session.refresh(invoice)
    assert invoice.status == "AUDIT_REQUIRED"


def test_another_tenants_invoice_is_not_replaceable(db_session):
    invoice = _invoice(tenant_id=uuid4())
    db_session.add(invoice)
    db_session.commit()

    assert _replace(invoice.id).status_code == 404


def test_a_rubbish_file_is_refused_before_anything_changes(db_session):
    """Same door as the upload route -- sniffed and page-capped. The invoice
    must be untouched when the new file is rejected."""
    invoice = _invoice(status="AUDIT_REQUIRED", file_hash="original-hash")
    db_session.add(invoice)
    db_session.commit()

    response = _replace(invoice.id, b"this is not a pdf", "notes.txt")
    assert response.status_code == 400
    db_session.refresh(invoice)
    assert invoice.file_hash == "original-hash"
    assert invoice.status == "AUDIT_REQUIRED"


def test_a_corrected_file_is_attached_and_re_extracted(db_session):
    """The whole point of the endpoint: the id survives, the old document's
    extracted values do not, and the invoice goes back through extraction.

    Keeping the id is what makes this different from re-uploading. The customer's
    ERP already stored it; a second upload would hand them a stranger."""
    invoice = _invoice(
        status="AUDIT_REQUIRED",
        vendor_name="WRONG VENDOR",
        invoice_number="WRONG-1",
        grand_total=999.0,
        completed_at=datetime(2026, 9, 2, 9, 0, 0),
    )
    original_id = invoice.id
    db_session.add(invoice)
    db_session.commit()

    corrected = _pdf_bytes().replace(b"MediaBox", b"MediaB0x")  # different bytes, same shape
    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/corrected.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)) as enqueue:
        response = _replace(original_id, corrected)

    assert response.status_code == 200
    body = response.json()
    assert body["replaced"] is True
    assert body["id"] == str(original_id)
    assert body["previous_status"] == "AUDIT_REQUIRED"
    assert enqueue.await_count == 1

    db_session.refresh(invoice)
    assert invoice.id == original_id          # the customer's reference is intact
    assert invoice.file_path == "mock/corrected.pdf"
    assert invoice.status == "PROCESSING"
    # Everything that described the OLD document is gone. A row whose numbers
    # came from one file and whose PDF is another is the confusion this exists
    # to remove.
    assert invoice.vendor_name is None
    assert invoice.invoice_number is None
    assert invoice.grand_total is None
    assert invoice.completed_at is None


def test_a_replacement_is_written_into_the_audit_trail(db_session):
    """Swapping the document under an invoice is exactly the kind of act an
    auditor must be able to see afterwards, including what it used to be."""
    invoice = _invoice(status="COMPLETED", file_hash="the-old-hash")
    db_session.add(invoice)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/corrected.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)):
        assert _replace(invoice.id, _pdf_bytes()).status_code == 200

    entry = db_session.exec(
        select(AuditLog).where(AuditLog.action == "REPLACE_INVOICE_FILE")
    ).first()
    assert entry is not None
    assert entry.invoice_id == invoice.id
    assert entry.details["previous_status"] == "COMPLETED"
    assert entry.details["previous_file_hash"] == "the-old-hash"


def test_storage_failure_leaves_the_invoice_exactly_as_it_was(db_session):
    """The blob is written before the row is touched, so an outage must not
    strand an invoice pointing at a file that was never stored."""
    from services.storage import StorageUploadError

    invoice = _invoice(status="COMPLETED", vendor_name="Vendor A", file_hash="the-old-hash")
    db_session.add(invoice)
    db_session.commit()

    with patch(
        "routers.invoices.upload_pdf_to_blob_storage",
        side_effect=StorageUploadError("blob storage unreachable"),
    ):
        response = _replace(invoice.id, _pdf_bytes())

    assert response.status_code == 503
    assert "nothing was changed" in response.json()["detail"].lower()

    db_session.refresh(invoice)
    assert invoice.status == "COMPLETED"
    assert invoice.file_hash == "the-old-hash"
    assert invoice.vendor_name == "Vendor A"


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 735 — a replacement is billable, because it costs what an upload costs
# ═══════════════════════════════════════════════════════════════════════════

def _free_tenant(db_session, remaining: int) -> Tenant:
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Acme",
        domain="acme.test",
        billing_plan="free",
        free_invoices_remaining=remaining,
    )
    db_session.add(tenant)
    db_session.commit()
    return tenant


def test_replacing_a_file_consumes_quota(db_session):
    """It re-runs Document Intelligence and a full extraction on the new file.
    Charging nothing for that is not a discount, it is an unmetered cost."""
    tenant = _free_tenant(db_session, remaining=5)
    invoice = _invoice(status="AUDIT_REQUIRED")
    db_session.add(invoice)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/corrected.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)):
        assert _replace(invoice.id, _pdf_bytes()).status_code == 200

    db_session.refresh(tenant)
    assert tenant.free_invoices_remaining == 4


def test_a_tenant_out_of_quota_cannot_extract_by_replacing(db_session):
    """The hole this closes. `charge_free_quota` is the ONLY thing enforcing the
    free limit, and it was called from the upload doors alone -- so a tenant at
    zero could spend their last credit on one invoice and then process unlimited
    unrelated documents through it, forever, by replacing the file."""
    tenant = _free_tenant(db_session, remaining=0)
    invoice = _invoice(status="AUDIT_REQUIRED", file_hash="the-old-hash")
    db_session.add(invoice)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage") as storage, \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock()) as enqueue:
        response = _replace(invoice.id, _pdf_bytes())

    assert response.status_code == 402
    # And it is refused BEFORE the expensive part, not after.
    storage.assert_not_called()
    enqueue.assert_not_awaited()

    db_session.refresh(invoice)
    assert invoice.file_hash == "the-old-hash"
    assert invoice.status == "AUDIT_REQUIRED"


def test_re_sending_the_identical_file_is_still_free(db_session):
    """A retry must not be charged -- it returns before the meter, because
    nothing is re-extracted."""
    import hashlib

    tenant = _free_tenant(db_session, remaining=3)
    same = _pdf_bytes()
    invoice = _invoice(file_hash=hashlib.sha256(same).hexdigest(), status="AUDIT_REQUIRED")
    db_session.add(invoice)
    db_session.commit()

    assert _replace(invoice.id, same).json()["replaced"] is False

    db_session.refresh(tenant)
    assert tenant.free_invoices_remaining == 3


def test_a_paid_plan_is_not_decremented(db_session):
    """Same rule as the upload path: the free counter is a free-plan concept."""
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Acme",
        domain="acme.test",
        billing_plan="pro",
        free_invoices_remaining=2,
    )
    db_session.add(tenant)
    invoice = _invoice(status="AUDIT_REQUIRED")
    db_session.add(invoice)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/c.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)):
        assert _replace(invoice.id, _pdf_bytes()).status_code == 200

    db_session.refresh(tenant)
    assert tenant.free_invoices_remaining == 2


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 736 — replacing needs `actions` scope; uploading still does not
# ═══════════════════════════════════════════════════════════════════════════

def _as_key(scope: str):
    """Swap both auth dependencies for an API-key context at `scope`.

    The Clerk one is overridden too, and made to raise: a test that leaves it
    mounted gets the mock ADMIN session instead of the key, passes for the
    wrong reason, and tells you a scope gate works when it was never consulted.
    """
    from dependencies import (
        TenantContext,
        get_tenant_context,
        get_tenant_or_api_key_context,
        permissions_for_key_scope,
    )

    # Permissions come from the real derivation, not from hand-picked booleans:
    # a test that hardcodes can_load=True for a readonly key is asserting
    # against a key that cannot exist.
    can_train, can_audit, can_load = permissions_for_key_scope(scope)
    context = TenantContext(
        tenant_id=MOCK_TENANT_ID,
        user_id=API_KEY_USER_ID,
        role="Restricted",
        billing_plan="free",
        auth_method="api_key",
        key_scope=scope,
        can_train=can_train,
        can_audit=can_audit,
        can_load=can_load,
    )

    def _refuse_clerk():
        raise HTTPException(status_code=401, detail="No Clerk session in this test.")

    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: context
    app.dependency_overrides[get_tenant_context] = _refuse_clerk


def test_a_readonly_key_cannot_replace_a_file(db_session):
    """Strict Review means a human finalises every invoice in the web UI. If a
    readonly key could replace, it could wipe the extracted values out from
    under an auditor reading them, seconds before they approve -- exactly what
    that policy is bought to prevent."""
    invoice = _invoice(status="AUDIT_REQUIRED", file_hash="the-old-hash")
    db_session.add(invoice)
    db_session.commit()
    _as_key("readonly")

    with patch("routers.invoices.upload_pdf_to_blob_storage") as storage:
        response = _replace(invoice.id, _pdf_bytes())

    assert response.status_code == 403
    assert "read-only" in response.json()["detail"]
    # Names the setting, because the reader is an integrator looking at JSON.
    assert "Full Automation" in response.json()["detail"]
    storage.assert_not_called()

    db_session.refresh(invoice)
    assert invoice.file_hash == "the-old-hash"


def test_an_actions_key_can_replace_a_file(db_session):
    """The other half: tightening the gate must not close it."""
    _free_tenant(db_session, remaining=5)
    invoice = _invoice(status="AUDIT_REQUIRED")
    db_session.add(invoice)
    db_session.commit()
    _as_key("actions")

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/c.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)):
        response = _replace(invoice.id, _pdf_bytes())

    assert response.status_code == 200
    assert response.json()["replaced"] is True


def test_a_readonly_key_can_still_upload(db_session):
    """The upload gate is deliberately looser and must stay that way -- Strict
    Review is defined as read/UPLOAD-only. Pinned so that tightening the replace
    gate cannot spread to the upload one by copy-paste."""
    from dependencies import (
        require_can_load_and_actions_scope,
        require_can_load_or_api_key,
    )

    _as_key("readonly")
    key_ctx = app.dependency_overrides[get_tenant_or_api_key_context]()

    # Upload admits a key of any scope...
    assert require_can_load_or_api_key(key_ctx) is key_ctx

    # ...while replace refuses this one.
    with pytest.raises(HTTPException) as refused:
        require_can_load_and_actions_scope(key_ctx)
    assert refused.value.status_code == 403


def test_a_human_without_can_load_cannot_replace(db_session):
    """The human half of the gate is unchanged from the upload route's: this
    tightened the MACHINE side only, and loosening the human side to do it
    would have been a trade rather than a fix."""
    from dependencies import TenantContext, require_can_load_and_actions_scope

    human = TenantContext(
        tenant_id=MOCK_TENANT_ID,
        user_id="user_abc",
        role="Auditor",
        billing_plan="free",
        auth_method="clerk",
        can_audit=True,
        can_load=False,
    )
    with pytest.raises(HTTPException) as refused:
        require_can_load_and_actions_scope(human)
    assert refused.value.status_code == 403
    assert "Ask an Admin" in refused.value.detail


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 738 — replacing must not smuggle a duplicate past the dedup check
# ═══════════════════════════════════════════════════════════════════════════

def test_cannot_replace_with_a_file_already_on_another_invoice(db_session):
    """The double-payment shape. A customer corrects invoice A and picks a PDF
    they already uploaded as invoice B: two live invoices, different ids, one
    document, no alert on either. Every other door checks this hash; this one
    did not."""
    import hashlib

    _free_tenant(db_session, remaining=5)
    already = _pdf_bytes()
    other = _invoice(invoice_number="INV-B", file_hash=hashlib.sha256(already).hexdigest())
    target = _invoice(invoice_number="INV-A", status="AUDIT_REQUIRED", file_hash="a-different-hash")
    db_session.add(other)
    db_session.add(target)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage") as storage:
        response = _replace(target.id, already)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "INV-B" in detail                    # names what it collided with
    assert "Nothing was changed" in detail
    storage.assert_not_called()

    db_session.refresh(target)
    assert target.file_hash == "a-different-hash"
    assert target.status == "AUDIT_REQUIRED"


def test_cannot_replace_with_a_file_already_stored_as_a_document(db_session):
    """Feature 27 moved non-invoice files into their own table, and BE Gap 385
    is the record of what happens when one half of the dedup rule forgets the
    other half exists."""
    import hashlib

    from models import Document

    _free_tenant(db_session, remaining=5)
    already = _pdf_bytes()
    db_session.add(
        Document(
            id=uuid4(),
            tenant_id=MOCK_TENANT_ID,
            file_path="mock/note.pdf",
            file_hash=hashlib.sha256(already).hexdigest(),
            doc_type="DELIVERY_NOTE",
        )
    )
    target = _invoice(status="AUDIT_REQUIRED", file_hash="a-different-hash")
    db_session.add(target)
    db_session.commit()

    response = _replace(target.id, already)

    assert response.status_code == 409
    assert "delivery note" in response.json()["detail"].lower()


def test_another_tenants_copy_of_the_file_does_not_block_a_replacement(db_session):
    """The tenant predicate sits inside the lookup, not outside it. Two
    customers sharing a common vendor's standard template must not be able to
    block each other -- and must not learn of each other's existence through a
    409 either."""
    import hashlib

    _free_tenant(db_session, remaining=5)
    same = _pdf_bytes()
    db_session.add(_invoice(tenant_id=uuid4(), file_hash=hashlib.sha256(same).hexdigest()))
    target = _invoice(status="AUDIT_REQUIRED", file_hash="a-different-hash")
    db_session.add(target)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/c.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)):
        response = _replace(target.id, same)

    assert response.status_code == 200
    assert response.json()["replaced"] is True


def test_the_invoices_own_current_file_is_not_treated_as_a_clash(db_session):
    """`Invoice.id != invoice_id` in the lookup. Without it the no-op path would
    be unreachable -- the row always matches its own hash -- and a retried
    request would 409 instead of returning quietly."""
    import hashlib

    same = _pdf_bytes()
    target = _invoice(status="AUDIT_REQUIRED", file_hash=hashlib.sha256(same).hexdigest())
    db_session.add(target)
    db_session.commit()

    response = _replace(target.id, same)
    assert response.status_code == 200
    assert response.json()["replaced"] is False


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 739 — the blocked-status list names only statuses that exist
# ═══════════════════════════════════════════════════════════════════════════

def test_every_blocked_status_is_one_this_system_actually_sets():
    """`CANCELLED` sat in this set and does not exist anywhere in the codebase.
    An entry that matches nothing is not harmless: it tells the next reader that
    such a status exists, and the next person to write a status check copies it.

    Both sources are real -- literals assigned to `status`, and the target
    statuses `routers/audit.py` assigns through `invoice.status = target_status`."""
    import re

    from routers.invoices import REPLACEABLE_BLOCKED_STATUSES

    audit_src = io.open("routers/audit.py", encoding="utf-8").read()
    finalizable = set(
        re.findall(r'"([A-Z_]+)"', re.search(
            r"_FINALIZABLE_FROM_STATUSES\s*=\s*\(([^)]*)\)", audit_src
        ).group(1))
    )

    assigned = set()
    import pathlib

    for folder in ("routers", "services", "queue_worker", "agents"):
        for path in pathlib.Path(folder).rglob("*.py"):
            assigned |= set(
                re.findall(r'status\s*=\s*"([A-Z_]+)"', path.read_text(encoding="utf-8"))
            )

    real = assigned | finalizable
    phantom = REPLACEABLE_BLOCKED_STATUSES - real
    assert not phantom, (
        f"These statuses are blocked from replacement but nothing ever sets them: "
        f"{sorted(phantom)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 740 — the duplicate pointer describes the OLD document
# ═══════════════════════════════════════════════════════════════════════════

def test_replacing_a_duplicates_file_clears_its_pointer_to_the_original(db_session):
    """A DUPLICATE row says "I am a copy of invoice X". Replace its file and it
    now holds a genuinely different document, so that sentence stops being true.

    Gap 195 added this column so subscribers and the alert UI could dereference
    it -- a stale value here is followed, not ignored, and would point a reader
    at an unrelated invoice."""
    _free_tenant(db_session, remaining=5)
    original = _invoice(invoice_number="ORIGINAL")
    db_session.add(original)
    db_session.commit()

    dupe = _invoice(
        invoice_number="COPY",
        status="AUDIT_REQUIRED",
        duplicate_of_invoice_id=original.id,
        sa_alerts=[{"type": "duplicate", "message": "This file is a duplicate."}],
    )
    db_session.add(dupe)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/c.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)):
        assert _replace(dupe.id, _pdf_bytes()).status_code == 200

    db_session.refresh(dupe)
    assert dupe.duplicate_of_invoice_id is None      # the structured half
    assert dupe.sa_alerts == []                      # and the alert half
    # The invoice it used to point at is untouched.
    db_session.refresh(original)
    assert original.invoice_number == "ORIGINAL"
