"""Feature 27 task R6 — the `Document` soft-delete path and its chunk lifecycle.

WHAT R6 ACTUALLY ASKED FOR AND WHAT WAS MISSING. §10B R6 reads "soft-delete of a
`Document` removes its chunks". G14 (Gap 381) had shipped `deleted_at` on the
model and a `deleted_at IS NULL` predicate on both read endpoints — but nothing
in the codebase ever *set* it. The column was unreachable, so the requirement had
no path to attach to and a tenant who uploaded the wrong contract could not
withdraw it. `DELETE /documents/{id}` is that path, and Gap 397 is the second one:
`DELETE /invoices/batches/{id}` had been rolling back only half of a batch since
E10 made batches heterogeneous.

WHY THESE RUN AGAINST REAL POSTGRES (hard rule 2). Two of the assertions here are
about what a *committed* transaction contains at a specific instant — the row is
durable before Chroma is touched — and one is about a cross-tenant delete leaving
another tenant's row intact. Both are claims about a database, and a mock of a
session would only restate the code back to itself. Same `pg_engine_or_skip()`
harness as `tests/test_documents_table.py`; skips rather than substitutes SQLite,
because a green run on the wrong engine cannot be cited as evidence.
"""
from datetime import date, datetime
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import AuditLog, Document, Invoice, Tenant, User

DOCS = "/api/v1/documents"


# ---------------------------------------------------------------------------
# Harness — deliberately the same shape as tests/test_documents_table.py
# ---------------------------------------------------------------------------
def pg_engine_or_skip():
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        # `connect_timeout` for the reason test_documents_table.py gives: a
        # paused-but-listening container completes the handshake and never
        # answers, hanging the whole suite instead of skipping this file.
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="pg")
def pg_fixture():
    engine = pg_engine_or_skip()
    with Session(engine) as session:
        yield session


@pytest.fixture(name="engine")
def engine_fixture():
    return pg_engine_or_skip()


def _tenant(session, tag, name="A"):
    row = Tenant(
        id=uuid4(),
        name=f"F27R6-{name}-{tag}",
        domain=f"f27r6-{name.lower()}-{tag}.invalid",
        billing_plan="free",
        free_invoices_remaining=50,
    )
    session.add(row)
    session.commit()
    return row


def _user(session, tenant, tag):
    """A real `users` row: `AuditLog.actor_user_id` is a foreign key to it, so
    the batch-rollback path cannot be exercised with an invented UUID."""
    row = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"r6-{tag}@f27r6.invalid",
        role="Admin",
        clerk_user_id=f"user_r6_{tag}",
    )
    session.add(row)
    session.commit()
    return row


def _document(session, tenant, tag, batch_id=None, doc_type="PURCHASE_ORDER"):
    row = Document(
        id=uuid4(),
        tenant_id=tenant.id,
        batch_id=batch_id,
        file_path=f"{tenant.id}/doc-{tag}.pdf",
        doc_type=doc_type,
        doc_number=f"PO-{tag}",
        status="EXTRACTED",
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return row


def _invoice(session, tenant, tag, batch_id=None):
    row = Invoice(
        id=uuid4(),
        tenant_id=tenant.id,
        batch_id=batch_id,
        file_path=f"{tenant.id}/inv-{tag}.pdf",
        vendor_name="Bharat Steels Pvt Ltd",
        grand_total=99120.0,
        currency="INR",
        invoice_date=date(2026, 8, 1),
        created_at=datetime.utcnow(),
        status="COMPLETED",
        flow_direction="INBOUND",
    )
    session.add(row)
    session.commit()
    return row


def _cleanup(session, tenant_ids):
    session.rollback()
    for tid in tenant_ids:
        for row in session.exec(select(AuditLog).where(AuditLog.tenant_id == tid)).all():
            session.delete(row)
        for row in session.exec(select(Document).where(Document.tenant_id == tid)).all():
            session.delete(row)
        for row in session.exec(select(Invoice).where(Invoice.tenant_id == tid)).all():
            session.delete(row)
        for row in session.exec(select(User).where(User.tenant_id == tid)).all():
            session.delete(row)
        tenant = session.get(Tenant, tid)
        if tenant:
            session.delete(tenant)
    session.commit()


class _Client:
    """`TestClient` with the session and the tenant context overridden.

    A context manager because `app.dependency_overrides` is process-global: a
    test that raised mid-body and left an override installed would silently
    re-tenant every later test in the run.
    """

    def __init__(self, session, tenant, db_user_id=None):
        self._session, self._tenant, self._db_user_id = session, tenant, db_user_id

    def __enter__(self):
        def _db():
            yield self._session

        def _ctx():
            return TenantContext(
                tenant_id=self._tenant.id,
                user_id="test-user",
                db_user_id=self._db_user_id,
                role="Admin",
                billing_plan="free",
            )

        app.dependency_overrides[get_db_session] = _db
        app.dependency_overrides[get_tenant_context] = _ctx
        return TestClient(app)

    def __exit__(self, *exc):
        app.dependency_overrides.clear()
        return False


# ---------------------------------------------------------------------------
# DELETE /documents/{id}
# ---------------------------------------------------------------------------
def test_delete_soft_deletes_the_row_and_both_read_endpoints_stop_seeing_it(pg):
    """Soft, not hard: the row survives so the file, its classification and its
    extraction evidence remain reviewable, exactly as Gap 192 chose for invoices.
    Asserted on the DATABASE as well as the endpoints — a 404 alone would also be
    produced by a hard delete, which is the outcome this must not be."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        doc = _document(pg, tenant, tag)
        with _Client(pg, tenant) as client:
            with patch("routers.documents.delete_document_chunks"):
                assert client.get(f"{DOCS}/{doc.id}").status_code == 200
                assert len(client.get(DOCS).json()) == 1

                res = client.delete(f"{DOCS}/{doc.id}")
                assert res.status_code == 200, res.text
                assert res.json() == {"success": True}

                assert client.get(f"{DOCS}/{doc.id}").status_code == 404
                assert client.get(DOCS).json() == []

        pg.expire_all()
        row = pg.get(Document, doc.id)
        assert row is not None, "soft delete must keep the row"
        assert row.deleted_at is not None
    finally:
        _cleanup(pg, [tenant.id])


def test_delete_drops_the_documents_chunks_from_the_sibling_collection(pg):
    """R6's actual sentence. Both arguments are asserted, not just the call:
    `delete_document_chunks(document_id, tenant_id)` takes two ids of the same
    type in the same shape, and swapping them would delete nothing and raise
    nothing — the function swallows its own errors by design."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        doc = _document(pg, tenant, tag)
        with _Client(pg, tenant) as client:
            with patch("routers.documents.delete_document_chunks") as drop:
                assert client.delete(f"{DOCS}/{doc.id}").status_code == 200
        drop.assert_called_once_with(str(doc.id), str(tenant.id))
    finally:
        _cleanup(pg, [tenant.id])


def test_the_row_is_committed_before_the_chunks_are_touched(pg, engine):
    """Ordering, asserted from OUTSIDE the request's own session.

    The endpoint commits first and drops chunks second, and the docstring gives
    the reason: `delete_document_chunks` swallows its failures, so a Chroma error
    after the commit leaves orphaned chunks the reembed sweep can still reach,
    whereas chunks-first plus a failed commit would leave a LIVE document that had
    silently stopped being retrievable — invisible, and unrecoverable without
    knowing to look.

    A second connection is what makes this a real check: reading `deleted_at`
    through the request's own session would see the pending change whether or not
    anything had been committed.
    """
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    seen = {}
    try:
        doc = _document(pg, tenant, tag)

        def _observe(document_id, tenant_id):
            with Session(engine) as other:
                seen["deleted_at"] = other.get(Document, doc.id).deleted_at

        with _Client(pg, tenant) as client:
            with patch("routers.documents.delete_document_chunks", side_effect=_observe):
                assert client.delete(f"{DOCS}/{doc.id}").status_code == 200

        assert seen["deleted_at"] is not None, (
            "chunks were dropped before the row was committed -- a failed commit "
            "would then leave a live document with no chunks"
        )
    finally:
        _cleanup(pg, [tenant.id])


def test_an_unreachable_chroma_does_not_fail_the_request(pg):
    """The real `delete_document_chunks` runs here, with its Chroma call broken.

    Not patched at the router seam, deliberately: the claim under test is that
    the function's own swallow (chroma_client.py:639) reaches the endpoint, and a
    mock at the router boundary would prove that only about the mock. A 500 here
    would tell the user their delete failed when the row is already gone, and they
    would retry it into a 404.
    """
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        doc = _document(pg, tenant, tag)
        with _Client(pg, tenant) as client:
            with patch(
                "chroma_client.get_document_collection",
                side_effect=RuntimeError("chroma is down"),
            ):
                assert client.delete(f"{DOCS}/{doc.id}").status_code == 200
        pg.expire_all()
        assert pg.get(Document, doc.id).deleted_at is not None
    finally:
        _cleanup(pg, [tenant.id])


def test_a_second_delete_is_a_404_and_does_not_touch_chroma_again(pg):
    """Already-deleted behaves as never-existed, matching `delete_invoice`. The
    chunk assertion is the load-bearing half: a repeated delete that still fired
    a Chroma call would make an idempotent-looking endpoint do unbounded work."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        doc = _document(pg, tenant, tag)
        with _Client(pg, tenant) as client:
            with patch("routers.documents.delete_document_chunks") as drop:
                assert client.delete(f"{DOCS}/{doc.id}").status_code == 200
                assert client.delete(f"{DOCS}/{doc.id}").status_code == 404
                assert drop.call_count == 1
    finally:
        _cleanup(pg, [tenant.id])


def test_a_cross_tenant_delete_is_404_and_destroys_nothing(pg):
    """§2A/A4/F1, on the verb that can actually destroy something.

    The read endpoints got their cross-tenant test at G14; this is the same
    boundary with consequences. The chunk assertion is why it is a separate test
    rather than a line in the one above: a handler that 404s *after* dropping the
    chunks would pass every status-code assertion in this file while deleting
    another tenant's embeddings on request.
    """
    tag = uuid4().hex[:10]
    tenant_a = _tenant(pg, tag, name="A")
    tenant_b = _tenant(pg, tag, name="B")
    try:
        doc_b = _document(pg, tenant_b, tag)
        with _Client(pg, tenant_a) as client:
            with patch("routers.documents.delete_document_chunks") as drop:
                res = client.delete(f"{DOCS}/{doc_b.id}")
                assert res.status_code == 404
                assert "not found" in res.json()["detail"].lower()
                drop.assert_not_called()

        pg.expire_all()
        assert pg.get(Document, doc_b.id).deleted_at is None
    finally:
        _cleanup(pg, [tenant_a.id, tenant_b.id])


# ---------------------------------------------------------------------------
# Gap 397 — DELETE /invoices/batches/{id} was rolling back half a batch
# ---------------------------------------------------------------------------
def test_batch_rollback_soft_deletes_the_batchs_documents_too(pg):
    """The Gap 397 regression. E10 made a batch heterogeneous — three of ten files
    classify as delivery notes and leave `invoice` entirely — and the rollback
    endpoint still queried only `Invoice`. The user was told the batch was undone
    while those three stayed live, visible and indexed."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        user = _user(pg, tenant, tag)
        batch_id = uuid4()
        inv = _invoice(pg, tenant, tag, batch_id=batch_id)
        doc = _document(pg, tenant, tag, batch_id=batch_id)
        # A document in a DIFFERENT batch, which the rollback must not touch.
        other = _document(pg, tenant, tag + "x", batch_id=uuid4())

        with _Client(pg, tenant, db_user_id=user.id) as client:
            with patch("routers.invoices.delete_document_chunks") as drop:
                res = client.delete(f"/api/v1/invoices/batches/{batch_id}")
                assert res.status_code == 200, res.text
                body = res.json()
                # `count` keeps meaning "invoices" for existing callers.
                assert body["count"] == 1
                assert body["document_count"] == 1
                drop.assert_called_once_with(str(doc.id), str(tenant.id))

        pg.expire_all()
        assert pg.get(Invoice, inv.id).deleted_at is not None
        assert pg.get(Document, doc.id).deleted_at is not None
        assert pg.get(Document, other.id).deleted_at is None, "wrong batch was rolled back"
    finally:
        _cleanup(pg, [tenant.id])


def test_a_batch_that_is_all_documents_is_no_longer_a_404(pg):
    """The worse half of Gap 397. A batch whose every file classified as a
    non-invoice matched zero `Invoice` rows, so the endpoint answered 404 — "no
    such batch" — about a batch that plainly existed and was still fully live."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        user = _user(pg, tenant, tag)
        batch_id = uuid4()
        d1 = _document(pg, tenant, tag + "1", batch_id=batch_id)
        d2 = _document(pg, tenant, tag + "2", batch_id=batch_id, doc_type="DELIVERY_NOTE")

        with _Client(pg, tenant, db_user_id=user.id) as client:
            with patch("routers.invoices.delete_document_chunks"):
                res = client.delete(f"/api/v1/invoices/batches/{batch_id}")
                assert res.status_code == 200, res.text
                assert res.json() == {"success": True, "count": 0, "document_count": 2}

        pg.expire_all()
        assert pg.get(Document, d1.id).deleted_at is not None
        assert pg.get(Document, d2.id).deleted_at is not None
    finally:
        _cleanup(pg, [tenant.id])


def test_an_unknown_batch_is_still_a_404(pg):
    """The 404 was widened, not removed. A batch_id with nothing behind it in
    either table must still be "not found" rather than a cheerful zero-count
    success that hides a typo."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        user = _user(pg, tenant, tag)
        with _Client(pg, tenant, db_user_id=user.id) as client:
            assert client.delete(f"/api/v1/invoices/batches/{uuid4()}").status_code == 404
    finally:
        _cleanup(pg, [tenant.id])


def test_batch_rollback_cannot_reach_another_tenants_documents(pg):
    """`batch_id` is caller-supplied and a UUID collision is not the threat — a
    copied id from a screen or a log is. The document half of the query carries
    the same `tenant_id` predicate as the invoice half, and this is what fails if
    someone later writes the new branch without it."""
    tag = uuid4().hex[:10]
    tenant_a = _tenant(pg, tag, name="A")
    tenant_b = _tenant(pg, tag, name="B")
    try:
        user_a = _user(pg, tenant_a, tag)
        batch_id = uuid4()
        _invoice(pg, tenant_a, tag, batch_id=batch_id)
        doc_b = _document(pg, tenant_b, tag, batch_id=batch_id)

        with _Client(pg, tenant_a, db_user_id=user_a.id) as client:
            with patch("routers.invoices.delete_document_chunks") as drop:
                res = client.delete(f"/api/v1/invoices/batches/{batch_id}")
                assert res.status_code == 200
                assert res.json()["document_count"] == 0
                drop.assert_not_called()

        pg.expire_all()
        assert pg.get(Document, doc_b.id).deleted_at is None
    finally:
        _cleanup(pg, [tenant_a.id, tenant_b.id])


# ---------------------------------------------------------------------------
# Gap 381 open item 3 — the deferral, held in place by a test
# ---------------------------------------------------------------------------
def test_a_document_row_is_only_ever_created_in_a_terminal_status(pg):
    """THE EVIDENCE FOR DEFERRING GAP 381 ITEM 3 (Gap 399), not a restatement of it.

    Item 3 asked for a re-enqueue path for stuck `Document` rows, by analogy with
    `services/invoice_reconciliation.py`. It is deferred because a stuck
    `Document` row cannot presently exist: there is exactly one construction site
    (`queue_worker/handlers.py:494`), it runs *after* the extraction graph
    returns, and it sets `status` to EXTRACTED or EXTRACT_FAILED with
    `completed_at` already stamped. A stall before that point is a stall of the
    placeholder `Invoice` row, which the existing sweep already covers — building
    a second sweep would be building it for a state no code can produce.

    That is a claim about the code as it stands, so it needs something that fails
    when the code changes. If a `Document` is ever created at upload time — the
    obvious future move, and the one that would make the deferral wrong — this is
    the test that goes red, rather than the deferral quietly becoming a defect.
    """
    from services.invoice_reconciliation import STUCK_STATUSES

    assert Document.model_fields["status"].default == "EXTRACTED"
    assert Document.model_fields["status"].default not in STUCK_STATUSES

    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        doc = _document(pg, tenant, tag)
        assert doc.status not in STUCK_STATUSES
        live = pg.exec(
            select(Document).where(
                Document.tenant_id == tenant.id,
                Document.status.in_(STUCK_STATUSES),  # type: ignore[attr-defined]
            )
        ).all()
        assert live == [], (
            "a Document now exists in a non-terminal status -- Gap 399's deferral "
            "of the re-enqueue sweep no longer holds; build it"
        )
    finally:
        _cleanup(pg, [tenant.id])
