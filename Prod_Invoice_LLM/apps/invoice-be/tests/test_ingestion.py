import io
import pytest
from unittest.mock import patch
from uuid import UUID, uuid4
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Document, Invoice, Tenant

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

def test_upload_single_pdf(db_session):
    """Verify successful upload of a single PDF invoice."""
    pdf_content = b"%PDF-1.4 test invoice content"
    files = {"files": ("invoice1.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient") as mock_queue_client_cls:

        mock_storage.return_value = "mock/path/invoice1.pdf"
        mock_queue_client = mock_queue_client_cls.from_connection_string.return_value

        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)

        assert response.status_code == 201
        data = response.json()
        assert "batch_id" in data
        assert "job_ids" in data
        assert len(data["job_ids"]) == 1

        # Verify db entry
        invoice_id = UUID(data["job_ids"][0])
        invoice = db_session.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.status == "PROCESSING"
        assert invoice.file_path == "mock/path/invoice1.pdf"
        assert invoice.tenant_id == MOCK_TENANT_ID

        # Verify background task was queued via Azure Storage Queue
        mock_queue_client.send_message.assert_called_once()

def test_upload_multiple_pdfs(db_session):
    """Verify uploading multiple PDFs in a single request."""
    pdf_content1 = b"%PDF-1.4 test 1"
    pdf_content2 = b"%PDF-1.4 test 2"
    files = [
        ("files", ("invoice1.pdf", io.BytesIO(pdf_content1), "application/pdf")),
        ("files", ("invoice2.pdf", io.BytesIO(pdf_content2), "application/pdf"))
    ]
    
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient") as mock_queue_client_cls:

        mock_storage.side_effect = ["mock/path/1.pdf", "mock/path/2.pdf"]
        mock_queue_client = mock_queue_client_cls.from_connection_string.return_value

        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)

        assert response.status_code == 201
        data = response.json()
        assert len(data["job_ids"]) == 2
        assert len(db_session.exec(select(Invoice)).all()) == 2
        assert mock_queue_client.send_message.call_count == 2

def test_free_plan_quota_exhausted(db_session):
    """Verify that uploads are rejected once the free plan invoice quota is exhausted."""
    # Pre-provision the test tenant with 0 remaining invoices
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Tenant",
        domain="test.com",
        billing_plan="free",
        free_invoices_remaining=0
    )
    db_session.add(tenant)
    db_session.commit()
    
    files = {"files": ("invoice1.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    
    client = TestClient(app)
    response = client.post("/api/v1/invoices/upload", files=files)
    
    assert response.status_code == 402
    assert response.json()["detail"] == "Limit reached"

def test_free_plan_quota_decrement(db_session):
    """Verify that uploading a PDF successfully decrements the remaining quota."""
    # Pre-provision the test tenant with 1 remaining invoice
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Tenant",
        domain="test.com",
        billing_plan="free",
        free_invoices_remaining=1
    )
    db_session.add(tenant)
    db_session.commit()
    
    files = {"files": ("invoice1.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient"):

        mock_storage.return_value = "mock/path/1.pdf"
        
        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)
        
        assert response.status_code == 201
        
        # Verify count decremented to 0 in database
        db_session.refresh(tenant)
        assert tenant.free_invoices_remaining == 0


def test_free_plan_duplicate_does_not_burn_quota(db_session):
    """Gap 189: re-uploading the same PDF is DUPLICATE and leaves quota unchanged."""
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Tenant",
        domain="test.com",
        billing_plan="free",
        free_invoices_remaining=5,
    )
    db_session.add(tenant)
    db_session.commit()

    pdf = b"%PDF-1.4 duplicate-quota-test"
    files = {"files": ("invoice1.pdf", io.BytesIO(pdf), "application/pdf")}

    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient"):
        mock_storage.return_value = "mock/path/first.pdf"
        client = TestClient(app)
        first = client.post("/api/v1/invoices/upload", files=files)
        assert first.status_code == 201
        db_session.refresh(tenant)
        assert tenant.free_invoices_remaining == 4

        files2 = {"files": ("invoice1-again.pdf", io.BytesIO(pdf), "application/pdf")}
        second = client.post("/api/v1/invoices/upload", files=files2)
        assert second.status_code == 201
        job_id = UUID(second.json()["job_ids"][0])
        dup = db_session.get(Invoice, job_id)
        assert dup is not None
        assert dup.status == "DUPLICATE"
        db_session.refresh(tenant)
        assert tenant.free_invoices_remaining == 4


def test_free_plan_mixed_batch_charges_only_billable(db_session):
    """Gap 189: one new + one duplicate in the same request decrements by 1."""
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="Test Tenant",
        domain="test.com",
        billing_plan="free",
        free_invoices_remaining=3,
    )
    db_session.add(tenant)
    db_session.commit()

    known = b"%PDF-1.4 already-known"
    fresh = b"%PDF-1.4 brand-new-file"
    client = TestClient(app)

    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient"):
        mock_storage.return_value = "mock/path/seed.pdf"
        seed = client.post(
            "/api/v1/invoices/upload",
            files={"files": ("seed.pdf", io.BytesIO(known), "application/pdf")},
        )
        assert seed.status_code == 201
        db_session.refresh(tenant)
        assert tenant.free_invoices_remaining == 2

        mock_storage.return_value = "mock/path/fresh.pdf"
        mixed = client.post(
            "/api/v1/invoices/upload",
            files=[
                ("files", ("dup.pdf", io.BytesIO(known), "application/pdf")),
                ("files", ("new.pdf", io.BytesIO(fresh), "application/pdf")),
            ],
        )
        assert mixed.status_code == 201
        assert len(mixed.json()["job_ids"]) == 2
        statuses = {
            db_session.get(Invoice, UUID(jid)).status for jid in mixed.json()["job_ids"]
        }
        assert statuses == {"DUPLICATE", "PROCESSING"}
        db_session.refresh(tenant)
        assert tenant.free_invoices_remaining == 1


def test_charge_free_quota_uses_for_update():
    """Gap 189: charge path locks the Tenant row (SELECT FOR UPDATE)."""
    from services.billing_quota import locked_tenant_select

    stmt = locked_tenant_select(MOCK_TENANT_ID)
    # SQLAlchemy 2 / SQLModel: for_update flag lives on the select
    assert getattr(stmt, "_for_update_arg", None) is not None or "FOR UPDATE" in str(
        stmt.compile(compile_kwargs={"literal_binds": True})
    )


def test_directory_watcher_disabled_by_default(db_session, monkeypatch):
    """Gap 12: watcher endpoint returns 501 when WATCHER_ALLOWED_BASE_DIR is unset.

    Explicitly forced empty here (same pattern as the two tests below) rather
    than relying on the ambient setting being unset -- FE Gap 181's fix set
    WATCHER_ALLOWED_BASE_DIR=./watched_invoices in .env.example/.env for local
    dev usability, which silently broke this test's original unstated
    assumption that no one's .env would ever set it.
    """
    from config import get_settings
    monkeypatch.setattr(get_settings(), "WATCHER_ALLOWED_BASE_DIR", "")
    client = TestClient(app)
    response = client.post("/api/v1/invoices/watcher/start", json={"directory_path": "/tmp/anything"})
    assert response.status_code == 501


def test_directory_watcher_rejects_path_traversal(db_session, tmp_path, monkeypatch):
    """Gap 12: a directory_path outside the configured base dir is rejected, not read."""
    from config import get_settings
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    monkeypatch.setattr(get_settings(), "WATCHER_ALLOWED_BASE_DIR", str(allowed_dir))
    client = TestClient(app)
    response = client.post("/api/v1/invoices/watcher/start", json={"directory_path": str(outside_dir)})
    assert response.status_code == 400


def test_directory_watcher_ingests_pdfs(db_session, tmp_path, monkeypatch):
    """Gap 12: a valid directory scan finds and ingests every PDF via the shared upload path."""
    from config import get_settings
    allowed_dir = tmp_path / "watched"
    allowed_dir.mkdir()
    (allowed_dir / "a.pdf").write_bytes(b"%PDF-1.4 watcher test a")
    (allowed_dir / "b.pdf").write_bytes(b"%PDF-1.4 watcher test b")
    (allowed_dir / "ignore.txt").write_text("not a pdf")

    monkeypatch.setattr(get_settings(), "WATCHER_ALLOWED_BASE_DIR", str(allowed_dir))

    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient") as mock_queue_client_cls:
        mock_storage.side_effect = ["mock/path/a.pdf", "mock/path/b.pdf"]
        mock_queue_client = mock_queue_client_cls.from_connection_string.return_value

        client = TestClient(app)
        response = client.post("/api/v1/invoices/watcher/start", json={"directory_path": str(allowed_dir)})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["files_found"] == 2
        assert data["files_queued"] == 2
        assert len(db_session.exec(select(Invoice)).all()) == 2
        assert mock_queue_client.send_message.call_count == 2


def test_duplicate_upload_copies_currency_from_original(db_session):
    """FE Gap 183: the duplicate-detection path in
    routers/invoices.py::_ingest_single_file() copies vendor_name, grand_total,
    tax_amount, po_number, dates and items onto the new DUPLICATE row -- but
    silently dropped `currency`. A duplicate of an INR invoice therefore landed
    with currency=NULL and every reader downstream treated it as USD. This is
    real data loss, not just a display bug: the duplicate row never goes back
    through extraction, so the value can't be recovered later.
    """
    import hashlib

    pdf_content = b"%PDF-1.4 duplicate currency test"
    file_hash = hashlib.sha256(pdf_content).hexdigest()

    original = Invoice(
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/original-inr.pdf",
        file_hash=file_hash,
        vendor_name="Mumbai Supplies Pvt Ltd",
        grand_total=40000.0,
        tax_amount=7200.0,
        currency="INR",
        status="COMPLETED",
        sa_alerts=[],
    )
    db_session.add(original)
    db_session.commit()

    files = {"files": ("invoice-again.pdf", io.BytesIO(pdf_content), "application/pdf")}

    with patch("routers.invoices.upload_pdf_to_blob_storage"), \
         patch("routers.invoices.QueueClient"):
        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)

    assert response.status_code == 201
    duplicate_id = UUID(response.json()["job_ids"][0])
    duplicate = db_session.get(Invoice, duplicate_id)

    assert duplicate is not None
    assert duplicate.status == "DUPLICATE"
    # The fields that were already being copied, still copied...
    assert duplicate.vendor_name == "Mumbai Supplies Pvt Ltd"
    assert duplicate.grand_total == 40000.0
    assert duplicate.tax_amount == 7200.0
    # ...and the one that wasn't.
    assert duplicate.currency == "INR"


# ---------------------------------------------------------------------------
# BE Gap 385 — ingestion dedup widened to the Invoice ∪ Document union
# ---------------------------------------------------------------------------
# Feature 27 §2A/A4/F5's ruling, which had never been made in code or prose.
# E10 moved non-invoice documents into `documents`, and
# `_ingest_single_file`'s dedup probe stayed `Invoice`-only -- so a re-uploaded
# delivery note was processed from scratch every time, while
# `services/billing_quota.py::count_billable_uploads` (already widened at G14)
# was simultaneously declaring it non-billable. Two halves of one rule
# disagreeing: work done, not charged, row count drifting from invoice count.
#
# SQLite, like the rest of this file. The union and the tenant predicates are
# plain SQL that behaves the same on both engines, but the FK-shaped concerns
# around `duplicate_of_invoice_id` are NOT proven here (CONVENTIONS hard rule 2).

_DOC_PDF = b"%PDF-1.4 delivery note DN-88213"


def _seed_document(db_session, tenant_id=MOCK_TENANT_ID, content=_DOC_PDF, **overrides):
    """One `documents` row carrying `content`'s hash, the way E10's routing writes it."""
    import hashlib

    fields = dict(
        tenant_id=tenant_id,
        file_path="mock/original-delivery-note.pdf",
        file_hash=hashlib.sha256(content).hexdigest(),
        doc_type="DELIVERY_NOTE",
        doc_number="DN-88213",
        party_name="Bharat Steels",
        status="EXTRACTED",
        sa_alerts=[],
    )
    fields.update(overrides)
    document = Document(**fields)
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


def _upload(content=_DOC_PDF, filename="reupload.pdf"):
    """Posts `content` to /upload with storage + queue mocked, returning
    (response, storage_mock, queue_mock)."""
    files = {"files": (filename, io.BytesIO(content), "application/pdf")}
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient") as mock_queue_cls:
        mock_storage.return_value = "mock/path/reupload.pdf"
        client = TestClient(app)
        response = client.post("/api/v1/invoices/upload", files=files)
    return response, mock_storage, mock_queue_cls


def test_reuploading_a_non_invoice_document_is_now_a_duplicate(db_session):
    """The bug itself. Before this, the `documents` row was invisible to the
    dedup probe, so the file was stored again and re-queued for a second full
    Doc Intelligence + extraction run."""
    _seed_document(db_session)

    response, mock_storage, mock_queue_cls = _upload()

    assert response.status_code == 201
    duplicate = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))
    assert duplicate is not None
    assert duplicate.status == "DUPLICATE"
    # The two things that make this a real fix rather than a label: the bytes
    # were not re-uploaded to storage, and no extraction was queued.
    mock_storage.assert_not_called()
    mock_queue_cls.from_connection_string.return_value.send_message.assert_not_called()


def test_a_document_match_copies_the_storage_pointer_and_nothing_else(db_session):
    """BE Gap 385's copy ruling, asserted field by field.

    `file_path` is the one column that means the same thing on both tables. Every
    extracted field stays NULL on purpose: `Document.party_name` is the *issuer*
    (on a PO, our own tenant -- copying it into `vendor_name` would file the
    tenant as its own vendor), `doc_number` is not an `invoice_number`, and money
    is optional on `documents` by design. A DUPLICATE row is never re-extracted,
    so a wrong value copied here is permanent -- that is how FE Gap 183 became
    real data loss, from the other direction."""
    document = _seed_document(db_session)

    response, _storage, _queue = _upload()
    duplicate = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))

    assert duplicate.file_path == document.file_path
    assert duplicate.vendor_name is None
    assert duplicate.invoice_number is None
    assert duplicate.invoice_date is None
    assert duplicate.due_date is None
    assert duplicate.grand_total is None
    assert duplicate.tax_amount is None
    assert duplicate.po_number is None
    assert duplicate.currency is None
    assert duplicate.items == []
    # NULL, not the `documents.id`: this column is a pointer into `invoice.id`
    # and every reader that dereferences it (Gap 195 consumers, the FE alert UI)
    # would look up an invoice that does not exist.
    assert duplicate.duplicate_of_invoice_id is None


def test_a_document_match_records_its_origin_in_sa_alerts(db_session):
    """The origin still has to be traceable. It goes in the alert payload rather
    than a new column, so this ruling needs no migration."""
    document = _seed_document(db_session)

    response, _storage, _queue = _upload()
    duplicate = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))

    alert = duplicate.sa_alerts[0]
    assert alert["type"] == "duplicate"
    assert alert["duplicate_of_document_id"] == str(document.id)
    assert alert["duplicate_of_doc_type"] == "DELIVERY_NOTE"
    # The prose names the document, not "a previously uploaded invoice" -- the
    # user is told what it actually matched.
    assert "delivery note" in alert["message"]
    assert str(document.id) in alert["message"]


def test_an_invoice_match_still_wins_and_is_byte_identical(db_session):
    """The pre-existing path is unchanged. `Invoice` is probed first and
    short-circuits, so when a file matches BOTH tables the invoice copy runs
    exactly as it did before -- including FE Gap 183's currency."""
    import hashlib

    content = b"%PDF-1.4 matches both tables"
    file_hash = hashlib.sha256(content).hexdigest()
    _seed_document(db_session, content=content, file_path="mock/doc-copy.pdf")
    db_session.add(Invoice(
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/original-inr.pdf",
        file_hash=file_hash,
        vendor_name="Mumbai Supplies Pvt Ltd",
        grand_total=40000.0,
        currency="INR",
        status="COMPLETED",
        sa_alerts=[],
    ))
    db_session.commit()

    response, _storage, _queue = _upload(content=content)
    duplicate = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))

    assert duplicate.status == "DUPLICATE"
    assert duplicate.file_path == "mock/original-inr.pdf"
    assert duplicate.vendor_name == "Mumbai Supplies Pvt Ltd"
    assert duplicate.grand_total == 40000.0
    assert duplicate.currency == "INR"
    assert duplicate.duplicate_of_invoice_id is not None
    assert "previously uploaded invoice" in duplicate.sa_alerts[0]["message"]


def test_another_tenants_document_is_not_a_duplicate(db_session):
    """§2A/A4/F2's tenant predicate, on the new side of the union.

    Unscoped, a file two tenants happen to share -- a common vendor's standard
    PO template -- would mark tenant B's genuine first upload DUPLICATE of
    tenant A's row, and the alert text is rendered to the user, so it would leak
    the existence of another tenant's document. Strictly worse here than in
    billing, where the same predicate only moved a counter."""
    from uuid import uuid4

    _seed_document(db_session, tenant_id=uuid4())  # someone else's document

    response, mock_storage, mock_queue_cls = _upload()
    invoice = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))

    assert invoice.status == "PROCESSING"
    assert invoice.sa_alerts == []
    # It really was treated as new: stored and queued.
    mock_storage.assert_called_once()
    mock_queue_cls.from_connection_string.return_value.send_message.assert_called_once()


def test_a_soft_deleted_document_still_dedups(db_session):
    """Same rule as Gap 192 / `count_billable_uploads`: the dedup set includes
    soft-deleted rows. The tenant already paid the DI + extraction cost for
    these bytes; deleting the row does not refund it, so a re-upload must not
    buy a second free run."""
    from datetime import datetime

    _seed_document(db_session, deleted_at=datetime.utcnow())

    response, mock_storage, _queue = _upload()
    duplicate = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))

    assert duplicate.status == "DUPLICATE"
    mock_storage.assert_not_called()


def test_ingestion_and_billing_now_agree_on_the_same_file(db_session):
    """The consistency this gap exists to restore.

    `count_billable_uploads` was widened to the union at G14 and this probe was
    not, so for a re-uploaded delivery note billing said "already paid for" while
    ingestion said "never seen it". Both halves are asserted here together, on one
    file, because that disagreement is the defect -- either answer alone looks
    correct in isolation."""
    from services.billing_quota import count_billable_uploads

    _seed_document(db_session)

    assert count_billable_uploads(db_session, MOCK_TENANT_ID, [_DOC_PDF]) == 0

    response, _storage, _queue = _upload()
    duplicate = db_session.get(Invoice, UUID(response.json()["job_ids"][0]))
    assert duplicate.status == "DUPLICATE"


def test_invoice_status_endpoint_returns_currency(db_session):
    """FE Gap 183: GET /invoices/status/{job_id} hand-builds its response dict,
    so the ingestion status ledger had no currency to render and hardcoded "$".
    """
    invoice = Invoice(
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/inr.pdf",
        vendor_name="Mumbai Supplies Pvt Ltd",
        grand_total=40000.0,
        currency="INR",
        status="COMPLETED",
        sa_alerts=[],
    )
    db_session.add(invoice)
    db_session.commit()

    client = TestClient(app)
    data = client.get(f"/api/v1/invoices/status/{invoice.id}").json()
    assert data["grand_total"] == 40000.0
    assert data["currency"] == "INR"


def test_rejects_non_pdf_file_extension(db_session):
    """Gap 355 (BE): Non-PDF files (e.g. .docx, .jpg) must be rejected with 400 Bad Request."""
    files = {"files": ("invoice.docx", io.BytesIO(b"PK\x03\x04 fake docx content"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    client = TestClient(app)
    response = client.post("/api/v1/invoices/upload", files=files)
    assert response.status_code == 400
    assert "Only PDF is allowed" in response.json()["detail"]


def test_rejects_invalid_pdf_magic_bytes(db_session):
    """Gap 355 (BE): Files with .pdf extension but invalid/corrupt PDF headers must be rejected with 400."""
    files = {"files": ("fake.pdf", io.BytesIO(b"This is just plain text, not a PDF"), "application/pdf")}
    client = TestClient(app)
    response = client.post("/api/v1/invoices/upload", files=files)
    assert response.status_code == 400
    assert "Invalid PDF content" in response.json()["detail"]



# ---------------------------------------------------------------------------
# Gap 429: replace a NEEDS_RESUBMISSION invoice with a corrected upload
#
# The design in one line: nothing is destroyed except the vector chunks. The
# old row, its alerts and its blob all survive; it is merely stamped
# `superseded_at` so `invoice_is_live()` drops it from results.
# ---------------------------------------------------------------------------

REPLACE_PDF = b"%PDF-1.4 corrected invoice"


def _parked_invoice(db_session, status_value="NEEDS_RESUBMISSION", alerts=None):
    """A tenant + one invoice sitting in the given status."""
    if db_session.get(Tenant, MOCK_TENANT_ID) is None:
        db_session.add(Tenant(id=MOCK_TENANT_ID, name="T", domain="t.example.com", billing_plan="pro"))
    inv = Invoice(
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/original.pdf",
        file_hash="originalhash",
        status=status_value,
        sa_alerts=alerts if alerts is not None else ["Total mismatch"],
        tags=["#q1"],
    )
    db_session.add(inv)
    db_session.commit()
    db_session.refresh(inv)
    return inv


def _do_replace(invoice_id, filename="corrected.pdf", content=REPLACE_PDF):
    files = {"file": (filename, io.BytesIO(content), "application/pdf")}
    with patch("routers.invoices.upload_pdf_to_blob_storage") as mock_storage, \
         patch("routers.invoices.QueueClient") as mock_queue_cls, \
         patch("chroma_client.delete_invoice_chunks") as mock_del:
        mock_storage.return_value = "mock/path/corrected.pdf"
        mock_queue_cls.from_connection_string.return_value
        client = TestClient(app)
        res = client.post(f"/api/v1/invoices/{invoice_id}/replace", files=files)
        return res, mock_del


def test_replace_supersedes_the_old_invoice_and_links_the_new_one(db_session):
    old = _parked_invoice(db_session)
    res, _ = _do_replace(old.id)
    assert res.status_code == 201, res.text

    body = res.json()
    assert body["replaced_invoice_id"] == str(old.id)
    new_id = UUID(body["replacement_invoice_id"])

    db_session.refresh(old)
    assert old.superseded_at is not None, "old row must be stamped superseded"

    new = db_session.get(Invoice, new_id)
    assert new is not None
    assert new.supersedes_invoice_id == old.id
    assert new.status == "PROCESSING", "replacement runs the normal pipeline"


def test_replace_preserves_the_old_invoice_its_alerts_and_its_blob(db_session):
    """The whole point: the old version stays reviewable. Nothing about the
    old row is cleared, and its blob pointer is untouched."""
    old = _parked_invoice(db_session, alerts=["Total mismatch", "Bad GST"])
    original_path = old.file_path
    res, _ = _do_replace(old.id)
    assert res.status_code == 201

    db_session.refresh(old)
    assert old.sa_alerts == ["Total mismatch", "Bad GST"], "alerts are the evidence"
    assert old.file_path == original_path, "original PDF must never be deleted"
    assert old.deleted_at is None, "superseded is not deleted"


def test_replace_removes_the_old_invoice_from_the_vector_index(db_session):
    """The one thing that IS hard-deleted -- otherwise chat keeps answering
    from an invoice a human already declared wrong."""
    old = _parked_invoice(db_session)
    res, mock_del = _do_replace(old.id)
    assert res.status_code == 201
    mock_del.assert_called_once()
    assert mock_del.call_args[0][0] == str(old.id)


@pytest.mark.parametrize("bad_status", ["AUDIT_REQUIRED", "PAID", "REJECTED", "REVIEW_LATER", "COMPLETED"])
def test_replace_rejected_unless_needs_resubmission(db_session, bad_status):
    old = _parked_invoice(db_session, status_value=bad_status)
    res, mock_del = _do_replace(old.id)
    assert res.status_code == 400
    assert "NEEDS_RESUBMISSION" in res.json()["detail"]
    mock_del.assert_not_called()

    db_session.refresh(old)
    assert old.superseded_at is None


def test_replace_twice_is_refused(db_session):
    old = _parked_invoice(db_session)
    first, _ = _do_replace(old.id)
    assert first.status_code == 201

    second, _ = _do_replace(old.id, filename="again.pdf", content=b"%PDF-1.4 again")
    assert second.status_code == 409
    assert "already been replaced" in second.json()["detail"]


def test_replace_rejects_a_non_pdf(db_session):
    """Same magic-byte check as the upload path -- a .pdf name is not a PDF."""
    old = _parked_invoice(db_session)
    res, mock_del = _do_replace(old.id, filename="evil.pdf", content=b"MZ not a pdf")
    assert res.status_code == 400
    assert "Invalid PDF content" in res.json()["detail"]
    mock_del.assert_not_called()

    db_session.refresh(old)
    assert old.superseded_at is None, "a rejected replace must not supersede anything"


def test_replace_writes_an_audit_log_naming_both_invoices(db_session):
    from models import AuditLog
    old = _parked_invoice(db_session)
    res, _ = _do_replace(old.id)
    assert res.status_code == 201
    new_id = res.json()["replacement_invoice_id"]

    logs = db_session.exec(select(AuditLog).where(AuditLog.invoice_id == old.id)).all()
    replace_logs = [l for l in logs if l.action == "REPLACE_INVOICE"]
    assert len(replace_logs) == 1
    assert replace_logs[0].details["replacement_invoice_id"] == new_id
    assert replace_logs[0].details["replaced_invoice_id"] == str(old.id)


# ---------------------------------------------------------------------------
# Gap 432: GET /invoices/{id}/last-action -- the fix plan's "show who/when/why"
# item. AuditLog has always recorded actor + target_status; nothing served it
# to the frontend. These go through the real resolve endpoint rather than
# hand-inserting an AuditLog row, since the risk that matters is a key-name
# mismatch between what routers/audit.py writes into `details` and what this
# endpoint reads back out of it.
# ---------------------------------------------------------------------------

def test_last_action_is_null_before_any_resolution(db_session):
    """A freshly-parked... no, a freshly-AUDIT_REQUIRED invoice has no
    resolve/reopen/replace history yet -- must not 404, must return null."""
    inv = _parked_invoice(db_session, status_value="AUDIT_REQUIRED")
    client = TestClient(app)
    res = client.get(f"/api/v1/invoices/{inv.id}/last-action")
    assert res.status_code == 200
    assert res.json() is None


def test_last_action_reports_who_when_why_for_needs_resubmission(db_session):
    from models import User

    inv = _parked_invoice(db_session, status_value="AUDIT_REQUIRED")
    client = TestClient(app)
    resolve = client.put(
        f"/api/v1/audit/resolve/{inv.id}",
        json={"status": "NEEDS_RESUBMISSION", "resubmission_reason": "Vendor name is wrong."},
    )
    assert resolve.status_code == 200, resolve.text

    res = client.get(f"/api/v1/invoices/{inv.id}/last-action")
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "RESOLVE_INVOICE"
    assert body["target_status"] == "NEEDS_RESUBMISSION"
    assert body["previous_status"] == "AUDIT_REQUIRED"
    assert body["actor_role"] == "Admin"  # MOCK_ROLE
    # Falls back to invoice.resubmission_reason since no reject_reason was sent.
    assert body["reason"] == "Vendor name is wrong."

    db_user = db_session.exec(select(User).where(User.tenant_id == MOCK_TENANT_ID)).first()
    assert db_user is not None
    assert body["actor_name"]  # resolved to a real name/email, not the "Unknown user" fallback


def test_last_action_reflects_the_most_recent_of_several_resolutions(db_session):
    """Park, then un-park -- must report the un-park, not the original park."""
    inv = _parked_invoice(db_session, status_value="AUDIT_REQUIRED")
    client = TestClient(app)
    client.put(f"/api/v1/audit/resolve/{inv.id}", json={"status": "REVIEW_LATER"})
    reopen = client.put(f"/api/v1/audit/resolve/{inv.id}", json={"status": "AUDIT_REQUIRED"})
    assert reopen.status_code == 200, reopen.text

    res = client.get(f"/api/v1/invoices/{inv.id}/last-action")
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "REOPEN_INVOICE"
    assert body["target_status"] == "AUDIT_REQUIRED"
    assert body["previous_status"] == "REVIEW_LATER"


def test_last_action_404s_for_a_missing_invoice(db_session):
    client = TestClient(app)
    res = client.get(f"/api/v1/invoices/{uuid4()}/last-action")
    assert res.status_code == 404
