"""Feature 28 — the five ingestion doors, end to end, on real Postgres.

`tests/test_file_intake.py` proves the conversion is correct in isolation. This
file proves each door actually *uses* it and that nothing downstream of the door
learned that images exist: the blob written is a PDF, `Invoice.file_path` ends
`.pdf`, `Invoice.file_hash` is the hash of the converted bytes, dedup still
fires on a re-uploaded photo, and quota is charged exactly once.

Postgres, not SQLite (CONVENTIONS hard rule 2). The dedup and quota paths under
test here are the ones that go through `SELECT … FOR UPDATE` in
`services/billing_quota.charge_free_quota()`, which SQLite does not implement —
a SQLite run would exercise a different code path and prove nothing about the
one that ships.

The doors covered:
  1. `POST /invoices/upload`            (routers/invoices.py::upload_invoices)
  2. `POST /invoices/watcher/start`     (routers/invoices.py::start_directory_watcher)
  3. `POST /outbound-invoices/upload`   (routers/outbound_invoices.py)
  4. `POST /trainer/upload`             (routers/trainer.py::upload_transient_file)
  5. `POST /email/mailintegration`      (routers/email_ingestion.py)
plus the Google Drive pair (`utils/connector_files.py` listing +
`services/autopilot_sync.py` loop), which has no HTTP door of its own.
"""
import hashlib
import io
import os
import pathlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import services.inbound_mail_security as inbound_security
from config import get_settings
from dependencies import (
    TenantContext,
    get_db_session,
    require_can_load,
    require_can_load_or_api_key,
    require_can_send_invoices,
)
from main import app
from models import (
    DroppedInboundEmail,
    Invoice,
    Tenant,
    TenantAutopilotConfig,
    TenantAutopilotLog,
    TenantConnection,
    TenantEmailSender,
)
from services.file_intake import ACCEPTED_FORMATS_DETAIL, normalize_upload
from utils.encryption import encrypt_token

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "image_uploads"

#: A tenant of this file's own, never `dependencies.MOCK_TENANT_ID`.
#:
#: The mock-auth fallback resolves its tenant by looking up the
#: `user_test_default` User row, and on a shared local Postgres that row is
#: already attached to whichever tenant a previous seeding script created. Tests
#: written against `MOCK_TENANT_ID` therefore read an empty tenant while the
#: router writes into someone else's — every assertion here would have been
#: vacuously wrong, and re-running the file would hit that tenant's existing
#: file hashes and silently take the DUPLICATE branch. The auth dependencies are
#: overridden below instead, which pins the tenant regardless of DB state.
TEST_TENANT_ID = uuid4()

TEST_INBOUND_SECRET = "test-inbound-shared-secret"
SECRET_HEADER = {"X-Inbound-Secret": TEST_INBOUND_SECRET}
GLOBAL_MAILBOX = "invoices@invoiceeq.app"

client = TestClient(app)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _upload_part(name: str, field: str = "files"):
    """Build the multipart part for a fixture, deliberately declaring a
    content_type that does NOT match the bytes where it can — the door must
    decide on bytes, never on the client's claim."""
    return {field: (name, io.BytesIO(_fixture(name)), "application/octet-stream")}


# ── Postgres session ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pg_engine():
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL — see .claude/skills/verify-postgres")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(pg_engine):
    """A real Postgres session holding this file's own freshly created tenant.

    Created per test and deleted afterwards, so the file leaves the shared local
    Postgres exactly as it found it and two runs never collide on a file hash.
    """
    with Session(pg_engine) as session:
        # Idempotent setup. The suite runs under pytest-randomly, so a test
        # whose teardown was cut short must not take the whole file down with a
        # duplicate-key error on the next test's INSERT.
        _purge(session)
        stale = session.get(Tenant, TEST_TENANT_ID)
        if stale:
            session.delete(stale)
            session.commit()
        session.add(
            Tenant(
                id=TEST_TENANT_ID,
                name="F28 Upload Formats",
                domain=f"f28-{TEST_TENANT_ID.hex[:12]}.example.com",
                billing_plan="free",
                free_invoices_remaining=50,
                send_invoices_enabled=True,
            )
        )
        session.commit()
        try:
            yield session
        finally:
            session.rollback()
            _purge(session)
            tenant = session.get(Tenant, TEST_TENANT_ID)
            if tenant:
                session.delete(tenant)
            session.commit()


def _purge(session: Session) -> None:
    # `invoice.duplicate_of_invoice_id` is a self-referencing FK: a DUPLICATE row
    # points at the original, so deleting the batch in arbitrary order trips
    # `fk_invoice_duplicate_of_invoice_id_invoice`. Break the pointers first —
    # the rows are on their way out anyway.
    for row in session.exec(
        select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)
    ).all():
        if row.duplicate_of_invoice_id is not None:
            row.duplicate_of_invoice_id = None
            session.add(row)
    session.commit()

    for model in (
        TenantAutopilotLog,
        TenantAutopilotConfig,
        TenantConnection,
        TenantEmailSender,
        Invoice,
    ):
        for row in session.exec(select(model).where(model.tenant_id == TEST_TENANT_ID)).all():
            session.delete(row)
    for row in session.exec(
        select(DroppedInboundEmail).where(DroppedInboundEmail.tenant_id == TEST_TENANT_ID)
    ).all():
        session.delete(row)
    session.commit()


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Pin both the session and the caller identity.

    The permission dependencies are overridden rather than satisfied with a real
    User row: this file is testing what the upload doors do with a file's
    *bytes*, and every one of them sits behind a different gate
    (`can_load`, `can_send_invoices`, a paid plan). Granting those through the
    dependency layer keeps each test to the one thing it is about, and pins the
    tenant so the assertions read the same rows the router wrote.
    """
    import routers.trainer as trainer_module

    context = TenantContext(
        tenant_id=TEST_TENANT_ID,
        user_id="f28-test-user",
        role="Admin",
        billing_plan="free",
    )

    def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    for dependency in (
        require_can_load,
        require_can_load_or_api_key,
        require_can_send_invoices,
        trainer_module.require_paid_plan,
    ):
        app.dependency_overrides[dependency] = lambda: context
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def captured_blobs():
    """Patch the blob write on every module that calls it and record the bytes.

    Recording the bytes (not just asserting the call happened) is the point:
    the whole feature is a claim about *what* gets stored.
    """
    store: dict[str, bytes] = {}

    def _fake_upload(file_data: bytes, tenant_id: str, invoice_id: str) -> str:
        store[invoice_id] = file_data
        return f"tenants/{tenant_id}/invoices/{invoice_id}.pdf"

    with patch("routers.invoices.upload_pdf_to_blob_storage", side_effect=_fake_upload), \
         patch("routers.outbound_invoices.upload_pdf_to_blob_storage", side_effect=_fake_upload), \
         patch("services.autopilot_sync.upload_pdf_to_blob_storage", side_effect=_fake_upload), \
         patch("routers.invoices.QueueClient") as inv_queue, \
         patch("routers.outbound_invoices.QueueClient", MagicMock()):
        inv_queue.from_connection_string.return_value.send_message = MagicMock()
        yield store


# ── Door 1: POST /invoices/upload ────────────────────────────────────────────

def test_png_upload_is_stored_as_a_pdf(db_session, captured_blobs):
    res = client.post("/api/v1/invoices/upload", files=_upload_part("invoice_photo.png"))
    assert res.status_code == 201, res.text

    invoices = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    assert len(invoices) == 1
    invoice = invoices[0]

    assert invoice.file_path.endswith(".pdf")
    stored = captured_blobs[str(invoice.id)]
    assert stored.startswith(b"%PDF")

    # The hash on the row is the hash of the CONVERTED bytes — this is what
    # dedup and `count_billable_uploads` compare against later.
    expected = normalize_upload("invoice_photo.png", _fixture("invoice_photo.png")).pdf_bytes
    assert stored == expected
    assert invoice.file_hash == hashlib.sha256(expected).hexdigest()


def test_the_same_photo_uploaded_twice_is_a_duplicate_and_is_charged_once(
    db_session, captured_blobs
):
    """The billing consequence of deterministic conversion. If conversion ever
    became non-deterministic this is the test that fails, and it fails here
    rather than in a customer's invoice."""
    tenant = db_session.get(Tenant, TEST_TENANT_ID)
    tenant.free_invoices_remaining = 10
    db_session.add(tenant)
    db_session.commit()

    for _ in range(2):
        res = client.post("/api/v1/invoices/upload", files=_upload_part("invoice_photo.jpg"))
        assert res.status_code == 201, res.text

    invoices = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    assert len(invoices) == 2
    assert sorted(i.status for i in invoices) == ["DUPLICATE", "PROCESSING"]
    assert len({i.file_hash for i in invoices if i.file_hash}) == 1

    db_session.refresh(tenant)
    assert tenant.free_invoices_remaining == 9, "the duplicate must not burn quota"


def test_gif_upload_is_refused_with_the_shared_accept_list(db_session, captured_blobs):
    res = client.post("/api/v1/invoices/upload", files=_upload_part("tiny.gif"))
    assert res.status_code == 400
    assert ACCEPTED_FORMATS_DETAIL in res.json()["detail"]
    assert db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all() == []


def test_a_gif_renamed_to_pdf_is_still_refused(db_session, captured_blobs):
    files = {"files": ("invoice.pdf", io.BytesIO(_fixture("tiny.gif")), "application/pdf")}
    res = client.post("/api/v1/invoices/upload", files=files)
    assert res.status_code == 400
    assert ACCEPTED_FORMATS_DETAIL in res.json()["detail"]


def test_a_real_pdf_is_stored_byte_identical_to_what_was_sent(db_session, captured_blobs):
    """The no-regression assertion: a PDF's journey through the door must be
    exactly what it was before Feature 28 existed."""
    raw = _fixture("real_invoice.pdf")
    res = client.post("/api/v1/invoices/upload", files=_upload_part("real_invoice.pdf"))
    assert res.status_code == 201, res.text

    invoice = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).one()
    assert captured_blobs[str(invoice.id)] == raw
    assert invoice.file_hash == hashlib.sha256(raw).hexdigest()


def test_a_pdf_named_as_a_jpg_is_accepted_and_not_converted(db_session, captured_blobs):
    raw = _fixture("pdf_named_as.jpg")
    res = client.post("/api/v1/invoices/upload", files=_upload_part("pdf_named_as.jpg"))
    assert res.status_code == 201, res.text

    invoice = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).one()
    assert captured_blobs[str(invoice.id)] == raw


def test_a_multi_page_tiff_upload_produces_a_multi_page_pdf(db_session, captured_blobs):
    import fitz

    res = client.post("/api/v1/invoices/upload", files=_upload_part("invoice_two_page.tiff"))
    assert res.status_code == 201, res.text

    invoice = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).one()
    doc = fitz.open(stream=captured_blobs[str(invoice.id)], filetype="pdf")
    try:
        assert doc.page_count == 2
    finally:
        doc.close()


# ── Door 2: POST /invoices/watch-directory ───────────────────────────────────

def test_directory_watcher_picks_up_images_alongside_pdfs(
    db_session, captured_blobs, tmp_path, monkeypatch
):
    watch_dir = tmp_path / "drop"
    watch_dir.mkdir()
    (watch_dir / "a_photo.png").write_bytes(_fixture("invoice_photo.png"))
    (watch_dir / "b_scan.pdf").write_bytes(_fixture("real_invoice.pdf"))
    (watch_dir / "c_notes.gif").write_bytes(_fixture("tiny.gif"))

    import routers.invoices as invoices_module

    watcher_settings = get_settings()
    monkeypatch.setattr(
        watcher_settings, "WATCHER_ALLOWED_BASE_DIR", str(tmp_path), raising=False
    )
    monkeypatch.setattr(invoices_module, "get_settings", lambda: watcher_settings)

    res = client.post(
        "/api/v1/invoices/watcher/start", json={"directory_path": str(watch_dir)}
    )
    assert res.status_code == 200, res.text
    body = res.json()

    # The .gif is not in ACCEPTED_UPLOAD_SUFFIXES, so it is not even listed —
    # it must not turn the whole batch into a 400.
    assert body["files_found"] == 2
    assert body["files_queued"] == 2

    invoices = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    assert len(invoices) == 2
    for invoice in invoices:
        assert invoice.file_path.endswith(".pdf")
        assert captured_blobs[str(invoice.id)].startswith(b"%PDF")


# ── Door 3: POST /outbound-invoices/upload ───────────────────────────────────

def test_outbound_png_upload_is_stored_as_a_pdf(db_session, captured_blobs):
    res = client.post(
        "/api/v1/outbound-invoices/upload", files=_upload_part("invoice_photo.png", field="file")
    )
    assert res.status_code == 201, res.text

    invoice = db_session.get(Invoice, UUID(res.json()["invoice_id"]))
    assert invoice.flow_direction == "OUTBOUND"
    assert invoice.file_path.endswith(".pdf")
    assert captured_blobs[str(invoice.id)].startswith(b"%PDF")


def test_outbound_gif_upload_is_refused_and_stores_nothing(db_session, captured_blobs):
    res = client.post(
        "/api/v1/outbound-invoices/upload", files=_upload_part("tiny.gif", field="file")
    )
    assert res.status_code == 400
    assert ACCEPTED_FORMATS_DETAIL in res.json()["detail"]
    assert captured_blobs == {}


def test_outbound_refusal_does_not_burn_quota(db_session, captured_blobs):
    tenant = db_session.get(Tenant, TEST_TENANT_ID)
    tenant.free_invoices_remaining = 3
    db_session.add(tenant)
    db_session.commit()

    client.post("/api/v1/outbound-invoices/upload", files=_upload_part("tiny.gif", field="file"))

    db_session.refresh(tenant)
    assert tenant.free_invoices_remaining == 3


# ── Door 4: POST /trainer/upload ─────────────────────────────────────────────

@pytest.fixture
def paid_tenant(db_session):
    tenant = db_session.get(Tenant, TEST_TENANT_ID)
    tenant.billing_plan = "pro_combined"
    db_session.add(tenant)
    db_session.commit()
    return tenant


def test_trainer_upload_accepts_a_photo_and_writes_a_pdf(paid_tenant, db_session):
    written: dict[str, bytes] = {}

    def _fake_ocr(path):
        written["bytes"] = pathlib.Path(path).read_bytes()
        written["path"] = path
        return ("ocr text", {}, {})

    with patch("routers.trainer._run_ocr_split", side_effect=_fake_ocr), \
         patch("routers.trainer.run_extraction_agent", return_value={"extracted_data": {}, "alerts": []}):
        res = client.post(
            "/api/v1/trainer/upload", files=_upload_part("invoice_photo.png", field="file")
        )

    assert res.status_code == 201, res.text
    assert written["path"].endswith(".pdf")
    assert written["bytes"].startswith(b"%PDF")
    if os.path.exists(written["path"]):
        os.remove(written["path"])


def test_trainer_upload_refuses_a_gif(paid_tenant, db_session):
    res = client.post("/api/v1/trainer/upload", files=_upload_part("tiny.gif", field="file"))
    assert res.status_code == 400
    assert ACCEPTED_FORMATS_DETAIL in res.json()["detail"]


# ── Door 5: POST /email/mailintegration ──────────────────────────────────────

@pytest.fixture
def inbound_secret_configured(monkeypatch):
    stub = MagicMock()
    stub.INBOUND_PARSE_SHARED_SECRET = TEST_INBOUND_SECRET
    # Large enough for the 30 KB JPEG fixture; the size cap is not what this
    # file is testing.
    stub.INBOUND_EMAIL_MAX_BYTES = 5_000_000
    monkeypatch.setattr(inbound_security, "get_settings", lambda: stub)
    return stub


def _register_sender(db_session, email="allowed@partners.com", email_set="inbound"):
    db_session.add(
        TenantEmailSender(
            id=uuid4(), tenant_id=TEST_TENANT_ID, email=email, email_set=email_set
        )
    )
    db_session.commit()


def test_email_attachment_that_is_a_photo_is_ingested(
    db_session, captured_blobs, inbound_secret_configured
):
    _register_sender(db_session)
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("IMG_0421.JPG", _fixture("invoice_photo.jpg"), "image/jpeg")},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "processed"

    invoice = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).one()
    assert invoice.file_path.endswith(".pdf")
    assert captured_blobs[str(invoice.id)].startswith(b"%PDF")


def test_email_with_only_a_gif_is_dropped_with_the_new_detail_text(
    db_session, captured_blobs, inbound_secret_configured
):
    """`REASON_NO_PDF_ATTACHMENT` keeps its constant name — it is persisted and
    reported on — but the human-readable detail must now name the image
    formats, or an Admin reading `GET /admin/dropped-emails` is told a supported
    photo was rejected for not being a PDF."""
    _register_sender(db_session)
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files={"attachment1": ("animation.gif", _fixture("tiny.gif"), "image/gif")},
        headers=SECRET_HEADER,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "skipped"

    dropped = db_session.exec(
        select(DroppedInboundEmail).where(DroppedInboundEmail.tenant_id == TEST_TENANT_ID)
    ).all()
    assert [d.reason for d in dropped] == [inbound_security.REASON_NO_PDF_ATTACHMENT]
    assert "PDF or supported image" in dropped[0].detail
    assert "PNG" in dropped[0].detail and "TIFF" in dropped[0].detail


def test_email_mixing_a_gif_and_a_photo_ingests_only_the_photo(
    db_session, captured_blobs, inbound_secret_configured
):
    _register_sender(db_session)
    res = client.post(
        "/api/v1/email/mailintegration",
        data={"to": GLOBAL_MAILBOX, "from": "allowed@partners.com"},
        files=[
            ("attachment1", ("animation.gif", _fixture("tiny.gif"), "image/gif")),
            ("attachment2", ("photo.png", _fixture("invoice_photo.png"), "image/png")),
        ],
        headers=SECRET_HEADER,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "processed"
    assert len(res.json()["job_ids"]) == 1

    invoices = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    assert len(invoices) == 1


# ── Door 6: Google Drive (listing + Autopilot loop) ──────────────────────────

def test_the_drive_listing_query_asks_for_every_convertible_mime_type():
    """Unit, no DB. An `image/` prefix match would be shorter and wrong: Drive
    would return HEIC and SVG, which the door then refuses — the tenant would
    watch files appear in the browser and fail on import."""
    from utils.connector_files import list_google_drive_files

    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"files": []}

        def raise_for_status(self):
            pass

    def _fake_get(url, headers=None, params=None, timeout=None):
        captured["q"] = params["q"]
        return _Resp()

    with patch("utils.connector_files.httpx.get", side_effect=_fake_get):
        list_google_drive_files("token", folder_id="folder-1")

    for mime in (
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/webp",
        "image/bmp",
        "application/vnd.google-apps.folder",
    ):
        assert f"mimeType = '{mime}'" in captured["q"], mime


def test_the_drive_listing_reports_the_mime_type_of_each_entry():
    from utils.connector_files import list_google_drive_files

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "files": [
                    {"id": "1", "name": "photo.png", "mimeType": "image/png", "size": "10"},
                    {
                        "id": "2",
                        "name": "sub",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ]
            }

        def raise_for_status(self):
            pass

    with patch("utils.connector_files.httpx.get", return_value=_Resp()):
        entries = list_google_drive_files("token")

    assert entries[0]["mime_type"] == "image/png"
    assert entries[0]["type"] == "file"
    assert entries[1]["type"] == "folder"


def test_autopilot_converts_a_drive_photo_before_storing_it(db_session, captured_blobs):
    from services.autopilot_sync import run_sync

    db_session.add(
        TenantAutopilotConfig(
            tenant_id=TEST_TENANT_ID,
            source_type="gdrive",
            source_ref="folder-abc-123",
            flow_direction="INBOUND",
            trigger_mode="interval",
            trigger_value="60",
            notify_emails=[],
            send_approval_links=False,
        )
    )
    db_session.add(
        TenantConnection(
            id=uuid4(),
            tenant_id=TEST_TENANT_ID,
            provider="google_drive",
            encrypted_access_token=encrypt_token("test-access-token"),
            encrypted_refresh_token=encrypt_token("test-refresh-token"),
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            status="active",
        )
    )
    db_session.commit()

    listing = [{"id": "drive-file-1", "name": "IMG_5512.JPG", "type": "file", "size_bytes": 1}]

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=listing), \
         patch(
             "services.autopilot_sync.download_google_drive_file",
             return_value=_fixture("invoice_photo.jpg"),
         ):
        summary = run_sync(TEST_TENANT_ID, db_session)

    assert summary["processed"] == 1, summary
    assert summary["failed"] == 0

    invoice = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).one()
    assert invoice.file_path.endswith(".pdf")
    assert captured_blobs[str(invoice.id)].startswith(b"%PDF")

    # Dedup Layer 2 hashes the converted bytes, so the log row must too.
    log = db_session.exec(
        select(TenantAutopilotLog).where(TenantAutopilotLog.tenant_id == TEST_TENANT_ID)
    ).one()
    expected = normalize_upload("IMG_5512.JPG", _fixture("invoice_photo.jpg")).pdf_bytes
    assert log.content_hash == hashlib.sha256(expected).hexdigest()


def test_autopilot_records_a_failed_row_for_an_unconvertible_drive_file(
    db_session, captured_blobs
):
    from services.autopilot_sync import run_sync

    db_session.add(
        TenantAutopilotConfig(
            tenant_id=TEST_TENANT_ID,
            source_type="gdrive",
            source_ref="folder-abc-123",
            flow_direction="INBOUND",
            trigger_mode="interval",
            trigger_value="60",
            notify_emails=[],
            send_approval_links=False,
        )
    )
    db_session.add(
        TenantConnection(
            id=uuid4(),
            tenant_id=TEST_TENANT_ID,
            provider="google_drive",
            encrypted_access_token=encrypt_token("test-access-token"),
            encrypted_refresh_token=encrypt_token("test-refresh-token"),
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            status="active",
        )
    )
    db_session.commit()

    listing = [{"id": "drive-file-2", "name": "banner.gif", "type": "file", "size_bytes": 1}]

    with patch("services.autopilot_sync.get_valid_access_token", return_value="tok"), \
         patch("services.autopilot_sync.list_google_drive_files", return_value=listing), \
         patch(
             "services.autopilot_sync.download_google_drive_file",
             return_value=_fixture("tiny.gif"),
         ):
        summary = run_sync(TEST_TENANT_ID, db_session)

    assert summary["processed"] == 0
    assert summary["failed"] == 1
    assert db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all() == []

    log = db_session.exec(
        select(TenantAutopilotLog).where(TenantAutopilotLog.tenant_id == TEST_TENANT_ID)
    ).one()
    assert log.status == "FAILED"
    assert ACCEPTED_FORMATS_DETAIL in log.error_detail


# ── Door 7: the connector import queue handler ───────────────────────────────

@pytest.fixture
def connector_import_env(db_session, tmp_path, monkeypatch):
    """Drive the manual-import handler down its local-storage fallback.

    `handle_import_connector_file` imports its helpers *inside* the function, so
    they have to be patched on the source modules, not on `queue_worker.handlers`.
    Blanking the Azure connection string is what selects the local write, which
    is the only branch a test can read the stored bytes back out of.
    """
    import services.storage as storage_module
    import utils.connector_files as connector_files_module
    import utils.connector_oauth as connector_oauth_module

    settings = get_settings()
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "", raising=False)
    monkeypatch.setattr(storage_module, "LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(connector_oauth_module, "has_real_credentials", lambda *a, **k: True)
    monkeypatch.setattr(connector_oauth_module, "get_valid_access_token", lambda *a, **k: "tok")

    db_session.add(
        TenantConnection(
            id=uuid4(),
            tenant_id=TEST_TENANT_ID,
            provider="google_drive",
            encrypted_access_token=encrypt_token("test-access-token"),
            encrypted_refresh_token=encrypt_token("test-refresh-token"),
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            status="active",
        )
    )
    db_session.commit()
    return connector_files_module, tmp_path


def test_connector_import_handler_stores_a_drive_photo_as_a_pdf(
    db_session, connector_import_env
):
    """`handle_import_connector_file` writes straight to storage with no router
    in front of it, so it needs its own door check — this is the path a manual
    "import this file" click takes, as opposed to the scheduled Autopilot loop."""
    from queue_worker.handlers import handle_import_connector_file

    connector_files_module, tmp_path = connector_import_env

    with patch.object(
        connector_files_module,
        "download_google_drive_file",
        return_value=_fixture("invoice_photo.png"),
    ), patch("queue_worker.handlers._enqueue_process_invoice", return_value=True):
        result = handle_import_connector_file(
            provider="google_drive",
            file_id="drive-file-9",
            tenant_id=str(TEST_TENANT_ID),
            direction="inbound",
            db_session=db_session,
        )

    assert result["success"] is True
    stored = pathlib.Path(result["blob_path"])
    assert stored.name.endswith(".pdf")
    assert stored.read_bytes().startswith(b"%PDF")

    invoice = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).one()
    assert invoice.file_path.endswith(".pdf")


def test_connector_import_handler_refuses_an_unconvertible_file(
    db_session, connector_import_env
):
    from queue_worker.handlers import handle_import_connector_file

    connector_files_module, _ = connector_import_env

    with patch.object(
        connector_files_module,
        "download_google_drive_file",
        return_value=_fixture("tiny.gif"),
    ):
        with pytest.raises(RuntimeError, match="refused"):
            handle_import_connector_file(
                provider="google_drive",
                file_id="drive-file-10",
                tenant_id=str(TEST_TENANT_ID),
                direction="inbound",
                db_session=db_session,
            )

    assert db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all() == []
