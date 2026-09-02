"""Feature 27 (G9/G10/G14) — decision E10's proof: non-invoice documents leave `invoice`.

§9's T-E10 block. Five things are asserted here and each one is the test for a
specific way this feature could silently corrupt existing behaviour:

  T-E10-1  a `DELIVERY_NOTE` ingested end-to-end leaves ZERO rows in `invoice`
           for that file and exactly one in `documents`, `status="EXTRACTED"`.
  T-E10-2  `/dashboard/metrics`' four aggregates (totals by currency, status
           breakdown, top vendors, spend-over-time) are byte-identical before and
           after a `DELIVERY_NOTE` and a `PURCHASE_ORDER` are ingested for the
           same tenant. **This is the Gap-329-shaped test** — that gap was
           `flow_direction` added to `Invoice` with the dashboard never filtered
           on it, found only because the founder noticed it on screen. This
           feature adds nine new row-kinds; the assertion is applied
           pre-emptively rather than after the fact.
  T-E10-3  the same non-invoice file re-uploaded is not billed twice, its first
           upload IS billed once, and — §2A/A4/F2 — a *second tenant's* first
           upload of a byte-identical file DOES consume that second tenant's
           quota. That last one is the tenant-scoping half of the union, and it
           is the one that turns the quota counter into a cross-tenant oracle if
           it is got wrong.
  T-E10-4  `docs_{tenant_id}` is created with `hnsw:space == "cosine"` (§8 trap
           3), and `query_invoice_chunks()` on the same tenant cannot see a
           chunk in it.
  T-E10-5  §2A/A4/F1 — tenant B requesting tenant A's `document_id` gets 404
           (never 403), and `GET /documents` for B returns zero of A's rows.

**Evidence standard.** T-E10-1/2/3/5 are persistence and aggregate tests, and per
CONVENTIONS hard rule 2 they run against **real PostgreSQL** — the local dev
instance at `DATABASE_URL`, which `pg_available()` below verifies and skips on if
it is not reachable. They are not SQLite tests dressed up: the SQLite/Postgres
fidelity gap is the root cause of 4+ incidents in this repo, and an aggregate
byte-identity claim on SQLite would prove nothing about the database the product
runs on. T-E10-4 is pure Chroma against the session-scoped EphemeralClient
(`conftest.py`) and touches no database at all.

Every Postgres test tags its rows with a per-run `uuid4()` and deletes what it
created in a `finally`, because it runs against the developer's real dev
database rather than a throwaway one.
"""
import hashlib
from datetime import date, datetime
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import Document, Invoice, Tenant


# ---------------------------------------------------------------------------
# Postgres harness (hard rule 2)
# ---------------------------------------------------------------------------
def pg_engine_or_skip():
    """Real Postgres or skip — never a silent SQLite substitution.

    Same shape as `tests/test_chat_queue.py`'s Postgres-only isolation test.
    Skipping is the honest outcome when the dev database is not running; falling
    back to SQLite would let a green run be cited as evidence for a claim it
    cannot support.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")
    engine = create_engine(url)
    # Idempotent: every table already exists on a migrated database. Present so
    # the file also runs against a freshly created one.
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="pg")
def pg_fixture():
    engine = pg_engine_or_skip()
    with Session(engine) as session:
        yield session


def _tenant(session, tag, name="A"):
    row = Tenant(
        id=uuid4(),
        name=f"F27-{name}-{tag}",
        domain=f"f27-{name.lower()}-{tag}.invalid",
        billing_plan="free",
        free_invoices_remaining=50,
    )
    session.add(row)
    session.commit()
    return row


def _cleanup(session, tenant_ids):
    """Remove everything a test created. Runs in a `finally`, and swallows
    nothing — a failed cleanup on a shared dev database should be loud."""
    session.rollback()
    for tid in tenant_ids:
        for row in session.exec(select(Document).where(Document.tenant_id == tid)).all():
            session.delete(row)
        for row in session.exec(select(Invoice).where(Invoice.tenant_id == tid)).all():
            session.delete(row)
        tenant = session.get(Tenant, tid)
        if tenant:
            session.delete(tenant)
    session.commit()


# ---------------------------------------------------------------------------
# End-to-end ingestion harness
# ---------------------------------------------------------------------------
_DELIVERY_NOTE_EXTRACT = {
    "doc_type": "DELIVERY_NOTE",
    "party_name": "Bharat Steels Pvt Ltd",
    "counterparty_name": "Novatech Industries",
    "doc_number": "DC-2026-0912",
    "po_number": "PO-2026-4471",
    "reference_numbers": ["PO-2026-4471"],
    "doc_date": "2026-08-14",
    "valid_until": None,
    # No prices anywhere. This is the founder's original symptom document: a
    # delivery challan prints quantities and no money by design.
    "currency": None,
    "subtotal": None,
    "tax_amount": None,
    "discount_amount": None,
    "grand_total": None,
    "items": [
        {"description": "MS Angle 50x50x6", "quantity": 120.0, "uom": "NOS",
         "unit_price": None, "amount": None},
        {"description": "MS Flat 40x6", "quantity": 40.0, "uom": "NOS",
         "unit_price": None, "amount": None},
    ],
    "taxes": [],
    "payment_terms": None,
    "delivery_terms": "Ex-works, buyer's transport",
    "incoterms": None,
    "notes": "Goods despatched against PO-2026-4471.",
}

_PURCHASE_ORDER_EXTRACT = {
    **_DELIVERY_NOTE_EXTRACT,
    "doc_type": "PURCHASE_ORDER",
    "doc_number": "PO-2026-4471",
    "currency": "INR",
    "subtotal": 84000.0,
    "grand_total": 99120.0,
}


def _ingest_non_invoice(
    session,
    tenant,
    tag,
    doc_type="DELIVERY_NOTE",
    extracted=None,
    status="EXTRACTED",
    file_hash=None,
):
    """Drive `handle_process_invoice` end to end for one non-invoice document.

    The door creates the placeholder `Invoice` row exactly as `routers/invoices.py`
    does today (that is the whole reason a placeholder exists to delete), then the
    worker runs with OCR and the extraction graph mocked — the two things that
    would otherwise require Azure Document Intelligence and a real LLM. Everything
    between them, including the routing decision and the transaction, is the real
    code path.

    Returns the placeholder's id so the caller can assert it is gone.
    """
    from queue_worker import handlers

    file_path = f"{tenant.id}/f27-{tag}-{doc_type.lower()}.pdf"
    batch_id = uuid4()
    placeholder = Invoice(
        id=uuid4(),
        tenant_id=tenant.id,
        batch_id=batch_id,
        file_path=file_path,
        file_hash=file_hash or hashlib.sha256(file_path.encode()).hexdigest(),
        status="PROCESSING",
        submitted_by_email="uploader@example.com",
    )
    session.add(placeholder)
    session.commit()
    placeholder_id = placeholder.id

    agent_result = {
        "status": status,
        "alerts": [],
        "extracted_data": dict(extracted or _DELIVERY_NOTE_EXTRACT),
        "doc_type": doc_type,
        "doc_type_evidence": "DELIVERY CHALLAN",
        "doc_type_confidence": 1.0,
    }
    ocr_result = {
        "content": "DELIVERY CHALLAN\nBharat Steels Pvt Ltd\n",
        "coordinates": [{"field": "InvoiceTotal", "page": 1}],
        "field_confidence": {"InvoiceTotal": 0.21},
        "tax_details_sum": None,
        "source_document_json": {"docs": []},
    }

    with patch.object(handlers, "_run_ocr", return_value=ocr_result), \
         patch.object(handlers, "run_extraction_agent", return_value=agent_result), \
         patch.object(handlers, "_publish_sse_events"), \
         patch("chroma_client.index_document_chunks", return_value=0):
        handlers.handle_process_invoice(str(batch_id), file_path, str(tenant.id))

    session.expire_all()
    return placeholder_id, file_path, batch_id


# ---------------------------------------------------------------------------
# T-E10-1 — the exclusion proof
# ---------------------------------------------------------------------------
def test_t_e10_1_delivery_note_leaves_no_invoice_row_and_one_document_row(pg):
    """The whole isolation guarantee, asserted on rows rather than on intent."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        placeholder_id, file_path, batch_id = _ingest_non_invoice(pg, tenant, tag)

        invoices = pg.exec(
            select(Invoice).where(Invoice.tenant_id == tenant.id)
        ).all()
        assert invoices == [], (
            "a classified DELIVERY_NOTE left an Invoice row behind; every spend "
            "aggregate, the AUDIT_REQUIRED count, billing quota and the RAG index "
            "read `invoice` as money owed"
        )
        # Asserted by id as well as by count: the placeholder specifically is the
        # row that had to go, and a delete that removed some *other* row while
        # leaving this one would satisfy a count-only check on a fresh tenant.
        assert pg.get(Invoice, placeholder_id) is None

        documents = pg.exec(
            select(Document).where(Document.tenant_id == tenant.id)
        ).all()
        assert len(documents) == 1
        doc = documents[0]
        assert doc.status == "EXTRACTED"
        assert doc.doc_type == "DELIVERY_NOTE"
        assert doc.doc_type_evidence == "DELIVERY CHALLAN"
        assert doc.doc_type_confidence == 1.0
        assert doc.file_path == file_path
        assert doc.batch_id == batch_id
        # A4/F4(a): tenant_id came from the loaded Invoice row.
        assert doc.tenant_id == tenant.id
        # Operational columns carried across from the placeholder.
        assert doc.submitted_by_email == "uploader@example.com"

        # The spine landed, and — the part that matters for this document type —
        # absence stayed absence. `is None`, never truthiness: `not None` and
        # `not 0.0` are both True and that equivalence is how Gap 283 happened.
        assert doc.party_name == "Bharat Steels Pvt Ltd"
        assert doc.counterparty_name == "Novatech Industries"
        assert doc.doc_number == "DC-2026-0912"
        assert doc.po_number == "PO-2026-4471"
        assert doc.doc_date == date(2026, 8, 14)
        assert doc.grand_total is None
        assert doc.subtotal is None
        assert doc.tax_amount is None
        assert doc.currency is None
        assert len(doc.items) == 2
        assert doc.items[0]["unit_price"] is None
    finally:
        _cleanup(pg, [tenant.id])


def test_t_e10_1b_extract_failed_still_lands_in_documents_not_invoice(pg):
    """The failure half of the status pair.

    A failed extraction of a non-invoice document must still not be an `Invoice`
    row — otherwise the one case where the pipeline is least sure what it read is
    the case that lands in the payables table.
    """
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        _ingest_non_invoice(pg, tenant, tag, status="EXTRACT_FAILED")
        assert pg.exec(select(Invoice).where(Invoice.tenant_id == tenant.id)).all() == []
        docs = pg.exec(select(Document).where(Document.tenant_id == tenant.id)).all()
        assert len(docs) == 1
        assert docs[0].status == "EXTRACT_FAILED"
    finally:
        _cleanup(pg, [tenant.id])


def test_an_invoice_family_document_still_updates_the_invoice_row(pg):
    """The control for T-E10-1, and the reason it cannot pass vacuously.

    Without this, an implementation that deleted the `Invoice` row for *every*
    document — invoices included — would pass T-E10-1 with flying colours.
    """
    from queue_worker import handlers

    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        file_path = f"{tenant.id}/f27-{tag}-invoice.pdf"
        batch_id = uuid4()
        row = Invoice(
            id=uuid4(), tenant_id=tenant.id, batch_id=batch_id, file_path=file_path,
            file_hash=hashlib.sha256(file_path.encode()).hexdigest(), status="PROCESSING",
        )
        pg.add(row)
        pg.commit()
        invoice_id = row.id

        agent_result = {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {
                "vendor_name": "Bharat Steels Pvt Ltd",
                "invoice_number": f"INV-{tag}",
                "grand_total": 99120.0,
                "currency": "INR",
            },
            "doc_type": "INVOICE",
            "doc_type_evidence": "TAX INVOICE",
            "doc_type_confidence": 1.0,
        }
        with patch.object(handlers, "_run_ocr", return_value={
            "content": "TAX INVOICE", "coordinates": [], "field_confidence": {},
            "tax_details_sum": None, "source_document_json": None,
        }), patch.object(handlers, "run_extraction_agent", return_value=agent_result), \
                patch.object(handlers, "_publish_sse_events"), \
                patch("chroma_client.index_invoice_document"), \
                patch("services.webhooks.dispatch_webhook_event"), \
                patch("services.staff_notify.notify_processing_complete"), \
                patch("routers.dashboard.invalidate_insights_cache"):
            handlers.handle_process_invoice(str(batch_id), file_path, str(tenant.id))

        pg.expire_all()
        kept = pg.get(Invoice, invoice_id)
        assert kept is not None, "an INVOICE must stay in `invoice`"
        assert kept.status == "COMPLETED"
        assert kept.grand_total == 99120.0
        assert pg.exec(select(Document).where(Document.tenant_id == tenant.id)).all() == []
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# T-E10-2 — the Gap 329-shaped regression test
# ---------------------------------------------------------------------------
def test_t_e10_2_dashboard_aggregates_are_byte_identical_after_non_invoice_ingestion(pg):
    """`/dashboard/metrics` must not move when a non-invoice document is ingested.

    §9 names this endpoint `/dashboard/insights`, but the four aggregates it
    lists — totals by currency, status breakdown, top vendors, spend-over-time —
    are `/dashboard/metrics`' payload; `/insights` is the LLM recommendation
    surface built on top of them and cannot be asserted byte-identical because it
    makes a model call. The subject here is the endpoint that actually carries
    the four aggregates, which is also the exact endpoint Gap 329 regressed.

    The comparison is **byte-level on the serialised response**, not a per-key
    spot check, for the same reason T-R-6 uses equality: a non-invoice leaking
    into the aggregates still produces a plausible-looking dashboard, and
    anything weaker than "the bytes did not change" passes while a phantom
    "Unknown Vendor" bucket is being created.
    """
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        # A real invoice, so the aggregates are non-trivial. A dashboard that is
        # empty before and empty after would be byte-identical for the wrong
        # reason.
        pg.add(Invoice(
            id=uuid4(), tenant_id=tenant.id, file_path=f"{tenant.id}/inv-{tag}.pdf",
            vendor_name="Bharat Steels Pvt Ltd", grand_total=99120.0, currency="INR",
            invoice_date=date(2026, 8, 1), created_at=datetime(2026, 8, 1),
            status="COMPLETED", flow_direction="INBOUND",
        ))
        pg.commit()

        def _get_db_session_override():
            yield pg

        def _tenant_override():
            return TenantContext(
                tenant_id=tenant.id, user_id="test-user", role="Admin",
                billing_plan="free",
            )

        app.dependency_overrides[get_db_session] = _get_db_session_override
        app.dependency_overrides[get_tenant_context] = _tenant_override
        try:
            client = TestClient(app)
            before = client.get("/api/v1/dashboard/metrics")
            assert before.status_code == 200
            before_bytes = before.content

            _ingest_non_invoice(pg, tenant, tag + "dn", doc_type="DELIVERY_NOTE")
            _ingest_non_invoice(
                pg, tenant, tag + "po", doc_type="PURCHASE_ORDER",
                extracted=_PURCHASE_ORDER_EXTRACT,
            )
            # Both really landed — otherwise this test passes by ingesting nothing.
            assert len(pg.exec(select(Document).where(Document.tenant_id == tenant.id)).all()) == 2

            after = client.get("/api/v1/dashboard/metrics")
            assert after.status_code == 200
            assert after.content == before_bytes, (
                "a non-invoice document moved /dashboard/metrics. This is Gap 329's "
                "failure mode on a new row-kind: totals inflated and an 'Unknown "
                "Vendor' bucket created by rows that are not payables."
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# T-E10-3 — billing quota, including A4/F2's tenant scoping
# ---------------------------------------------------------------------------
def test_t_e10_3_non_invoice_reupload_is_not_billed_twice(pg):
    """First upload billable; the same bytes again, once they live in `documents`,
    are not. Without the union this is charged on every re-upload."""
    from services.billing_quota import count_billable_uploads

    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        payload = f"delivery-challan-{tag}".encode()
        file_hash = hashlib.sha256(payload).hexdigest()

        assert count_billable_uploads(pg, tenant.id, [payload]) == 1, (
            "a non-invoice document's FIRST upload is billable — it consumed a "
            "real Document Intelligence page and a real extraction call"
        )

        _ingest_non_invoice(pg, tenant, tag, file_hash=file_hash)
        # The row is in `documents`, and there is no `invoice` row left to dedup
        # against — which is exactly the condition the union exists for.
        assert pg.exec(select(Invoice).where(Invoice.tenant_id == tenant.id)).all() == []
        assert pg.exec(
            select(Document).where(Document.tenant_id == tenant.id,
                                   Document.file_hash == file_hash)
        ).first() is not None

        assert count_billable_uploads(pg, tenant.id, [payload]) == 0, (
            "the same delivery note re-uploaded was billed again: the dedup set "
            "is still Invoice-only"
        )
    finally:
        _cleanup(pg, [tenant.id])


def test_t_e10_3b_second_tenants_first_upload_of_the_same_file_is_still_billed(pg):
    """§2A/A4/F2 — the tenant predicate must be inside **each side** of the union.

    Two tenants can legitimately hold byte-identical files (a common vendor's
    standard PO template). If the union is computed globally:
      * tenant B's genuine first upload looks like a duplicate and goes unbilled
        on real DI + extraction spend, and
      * worse, the quota counter becomes a cross-tenant oracle — B can learn
        whether *any other tenant* has uploaded a given file's bytes purely by
        watching whether its own `free_invoices_remaining` moves.
    """
    from services.billing_quota import count_billable_uploads

    tag = uuid4().hex[:10]
    tenant_a = _tenant(pg, tag, name="A")
    tenant_b = _tenant(pg, tag, name="B")
    try:
        payload = f"shared-vendor-po-template-{tag}".encode()
        file_hash = hashlib.sha256(payload).hexdigest()

        _ingest_non_invoice(pg, tenant_a, tag + "a", file_hash=file_hash)
        assert pg.exec(
            select(Document).where(Document.tenant_id == tenant_a.id,
                                   Document.file_hash == file_hash)
        ).first() is not None

        assert count_billable_uploads(pg, tenant_a.id, [payload]) == 0, (
            "tenant A's own re-upload should still dedup"
        )
        assert count_billable_uploads(pg, tenant_b.id, [payload]) == 1, (
            "tenant B's FIRST upload of a file tenant A happens to have was not "
            "billed — the dedup union is missing its per-side tenant predicate "
            "(A4/F2), which also makes the quota counter a cross-tenant oracle"
        )

        # The same guarantee on the Invoice side of the union, so a future edit
        # cannot scope one half and forget the other.
        inv_payload = f"shared-invoice-{tag}".encode()
        pg.add(Invoice(
            id=uuid4(), tenant_id=tenant_a.id, file_path=f"{tenant_a.id}/x-{tag}.pdf",
            file_hash=hashlib.sha256(inv_payload).hexdigest(), status="COMPLETED",
        ))
        pg.commit()
        assert count_billable_uploads(pg, tenant_a.id, [inv_payload]) == 0
        assert count_billable_uploads(pg, tenant_b.id, [inv_payload]) == 1
    finally:
        _cleanup(pg, [tenant_a.id, tenant_b.id])


def test_soft_deleted_documents_still_dedup(pg):
    """Gap 192's rule, carried onto the new table: a soft-deleted row still
    counts for dedup. Otherwise deleting a document becomes a way to get its
    re-upload for free."""
    from services.billing_quota import count_billable_uploads

    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        payload = f"deleted-doc-{tag}".encode()
        pg.add(Document(
            id=uuid4(), tenant_id=tenant.id, file_path=f"{tenant.id}/d-{tag}.pdf",
            file_hash=hashlib.sha256(payload).hexdigest(), doc_type="PURCHASE_ORDER",
            status="EXTRACTED", deleted_at=datetime.utcnow(),
        ))
        pg.commit()
        assert count_billable_uploads(pg, tenant.id, [payload]) == 0
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# T-E10-4 — the sibling collection (no database; §8 trap 3)
# ---------------------------------------------------------------------------
def test_t_e10_4_document_collection_is_created_in_cosine_space():
    """§8 trap 3. Chroma pins `hnsw:space` at creation and silently ignores the
    metadata on a collection that already exists, so a collection created without
    `_collection_metadata()` is permanently on `l2` — where
    `RELEVANCE_DISTANCE_THRESHOLD = 0.49`, derived empirically in cosine space,
    means nothing — and the only recovery is a drop + re-embed."""
    from chroma_client import (
        _collection_space,
        _document_collection_name,
        _tenant_collection_name,
        get_chroma_client,
        get_document_collection,
    )

    tenant_id = str(uuid4())
    assert _document_collection_name(tenant_id) == f"docs_{tenant_id}"
    # A sibling, not the invoice collection, and per-tenant on both sides.
    assert _document_collection_name(tenant_id) != _tenant_collection_name(tenant_id)
    assert _document_collection_name(tenant_id) != _document_collection_name(str(uuid4()))

    get_document_collection(tenant_id)
    collection = get_chroma_client().get_collection(_document_collection_name(tenant_id))
    assert _collection_space(collection) == "cosine"


def test_t_e10_4b_query_invoice_chunks_cannot_reach_the_document_collection():
    """Unreachability by construction — the thing E10 actually buys.

    `query_invoice_chunks()` names `invoice_chunks_{tenant}` and has no parameter
    that could make it name `docs_{tenant}`. This asserts the consequence rather
    than the intent: a chunk written into the document collection is not
    returned by an invoice query on the same tenant, even for its own text.
    """
    from chroma_client import get_document_collection, get_embeddings, query_invoice_chunks

    tenant_id = str(uuid4())
    text = "Delivery challan DC-2026-0912 for 120 NOS MS Angle 50x50x6"
    get_document_collection(tenant_id).upsert(
        ids=[f"{uuid4()}_page_1"],
        embeddings=get_embeddings([text]),
        documents=[text],
        metadatas=[{"tenant_id": tenant_id, "document_id": str(uuid4()),
                    "doc_type": "DELIVERY_NOTE", "party_name": "Bharat Steels",
                    "page": 1}],
    )
    assert query_invoice_chunks(tenant_id, text, limit=5) == []


def test_index_document_chunks_writes_to_the_sibling_collection_with_a_typed_header():
    """The write path: chunks land in `docs_{tenant}`, carry the document type in
    their header (§5 step 9), and carry **no `invoice_id` metadata key** — a
    document is not an invoice, so anything filtering on `invoice_id` must find
    nothing here."""
    import fitz

    from chroma_client import _document_collection_name, get_chroma_client, index_document_chunks

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "DELIVERY CHALLAN DC-2026-0912 MS Angle 120 NOS")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    tenant_id = str(uuid4())
    document_id = str(uuid4())
    with patch("chroma_client.download_pdf_from_storage", return_value=pdf_bytes):
        written = index_document_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            doc_type="DELIVERY_NOTE",
            party_name="Bharat Steels Pvt Ltd",
            file_path=f"{tenant_id}/dc.pdf",
        )

    assert written == 1
    collection = get_chroma_client().get_collection(_document_collection_name(tenant_id))
    got = collection.get(include=["documents", "metadatas"])
    assert collection.count() == 1
    assert got["documents"][0].startswith("[DELIVERY_NOTE | Party: Bharat Steels Pvt Ltd")
    meta = got["metadatas"][0]
    assert meta["document_id"] == document_id
    assert meta["doc_type"] == "DELIVERY_NOTE"
    assert "invoice_id" not in meta


def test_index_document_chunks_returns_zero_when_the_blob_is_missing():
    """Failure policy mirrors `index_invoice_document()`: a missing blob is
    logged and returns 0, never raises. The `Document` row is fully usable
    without an index."""
    from chroma_client import index_document_chunks

    with patch("chroma_client.download_pdf_from_storage", side_effect=Exception("404")):
        assert index_document_chunks(
            document_id=str(uuid4()), tenant_id=str(uuid4()),
            doc_type="PURCHASE_ORDER", party_name=None, file_path="missing.pdf",
        ) == 0


# ---------------------------------------------------------------------------
# T-E10-5 — §2A/A4/F1, the IDOR shape the security review flagged
# ---------------------------------------------------------------------------
def test_t_e10_5_cross_tenant_document_id_is_404_and_list_is_scoped(pg):
    """Tenant B must not be able to read, or learn the existence of, tenant A's
    document. 404 rather than 403: confirming that someone else's row exists is
    itself a disclosure."""
    tag = uuid4().hex[:10]
    tenant_a = _tenant(pg, tag, name="A")
    tenant_b = _tenant(pg, tag, name="B")
    try:
        _ingest_non_invoice(pg, tenant_a, tag + "a", doc_type="PURCHASE_ORDER",
                            extracted=_PURCHASE_ORDER_EXTRACT)
        _ingest_non_invoice(pg, tenant_b, tag + "b", doc_type="DELIVERY_NOTE")

        doc_a = pg.exec(select(Document).where(Document.tenant_id == tenant_a.id)).one()
        doc_b = pg.exec(select(Document).where(Document.tenant_id == tenant_b.id)).one()

        def _get_db_session_override():
            yield pg

        current = {"tenant": tenant_b}

        def _tenant_override():
            return TenantContext(
                tenant_id=current["tenant"].id, user_id="test-user", role="Admin",
                billing_plan="free",
            )

        app.dependency_overrides[get_db_session] = _get_db_session_override
        app.dependency_overrides[get_tenant_context] = _tenant_override
        try:
            client = TestClient(app)

            # B asking for A's document id.
            resp = client.get(f"/api/v1/documents/{doc_a.id}")
            assert resp.status_code == 404, (
                "cross-tenant document detail must be 404 — a 403 confirms the row "
                "exists, and a 200 is the pre-Gap-341 IDOR outright"
            )
            assert "not found" in resp.json()["detail"].lower()

            # B's list contains B's row and none of A's.
            listed = client.get("/api/v1/documents")
            assert listed.status_code == 200
            ids = {row["id"] for row in listed.json()}
            assert str(doc_b.id) in ids
            assert str(doc_a.id) not in ids
            assert all(row["tenant_id"] == str(tenant_b.id) for row in listed.json())

            # The control: B can read B's own row, so the 404 above is a
            # tenant boundary and not a broken endpoint.
            own = client.get(f"/api/v1/documents/{doc_b.id}")
            assert own.status_code == 200
            assert own.json()["doc_type"] == "DELIVERY_NOTE"
            # `source_document_json` is deliberately not on the wire.
            assert "source_document_json" not in own.json()

            # And A can read A's own row — the same id that was 404 for B.
            current["tenant"] = tenant_a
            as_a = client.get(f"/api/v1/documents/{doc_a.id}")
            assert as_a.status_code == 200
            assert as_a.json()["doc_type"] == "PURCHASE_ORDER"
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant_a.id, tenant_b.id])


def test_soft_deleted_documents_are_invisible_on_both_endpoints(pg):
    """Gap 192's soft delete honoured on the detail endpoint too, not only the
    list — the same asymmetry A4/F1 caught for tenant scoping."""
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        _ingest_non_invoice(pg, tenant, tag)
        doc = pg.exec(select(Document).where(Document.tenant_id == tenant.id)).one()
        doc.deleted_at = datetime.utcnow()
        pg.add(doc)
        pg.commit()

        def _get_db_session_override():
            yield pg

        def _tenant_override():
            return TenantContext(
                tenant_id=tenant.id, user_id="u", role="Admin", billing_plan="free",
            )

        app.dependency_overrides[get_db_session] = _get_db_session_override
        app.dependency_overrides[get_tenant_context] = _tenant_override
        try:
            client = TestClient(app)
            assert client.get("/api/v1/documents").json() == []
            assert client.get(f"/api/v1/documents/{doc.id}").status_code == 404
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# The routing decision itself (no database)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("doc_type", ["INVOICE", "PROFORMA_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"])
def test_money_family_never_routes_to_documents(doc_type):
    """The three non-`INVOICE` money types are the ones a bare
    `doc_type != "INVOICE"` comparison would misroute — Gap 369's naming
    collision, and the reason the code compares against `MONEY_FAMILY`."""
    from queue_worker.handlers import _routes_to_documents_table

    assert _routes_to_documents_table(doc_type) is False


@pytest.mark.parametrize(
    "doc_type",
    ["QUOTATION", "PURCHASE_ORDER", "CONTRACT", "DELIVERY_NOTE", "GRN", "OTHER"],
)
def test_every_non_money_type_routes_to_documents(doc_type):
    from queue_worker.handlers import _routes_to_documents_table

    assert _routes_to_documents_table(doc_type) is True


def test_routing_is_complete_against_the_closed_enum():
    """Keyed on `DOC_TYPES`, so an eleventh type added later is covered by this
    test the moment it has a family — rather than being silently unrouted."""
    from services.document_type_classifier import DOC_TYPES, DOC_TYPE_FAMILY, MONEY_FAMILY
    from queue_worker.handlers import _routes_to_documents_table

    for t in DOC_TYPES:
        assert _routes_to_documents_table(t) is (DOC_TYPE_FAMILY[t] != MONEY_FAMILY)


def test_unknown_and_none_doc_types_fail_closed_to_the_invoice_row():
    """`None` is every flag-OFF run and every caller that patches
    `run_extraction_agent` with a dict predating the key; an out-of-vocabulary
    value is a caller defect. Neither may delete an `Invoice` row."""
    from queue_worker.handlers import _routes_to_documents_table

    assert _routes_to_documents_table(None) is False
    assert _routes_to_documents_table("LIEFERSCHEIN") is False
    assert _routes_to_documents_table("") is False


def test_doc_type_is_normalised_before_the_family_lookup():
    """The classifier's output is `Literal`-constrained, but
    `run_extraction_agent`'s caller-supplied override is free text. Without
    normalisation `" delivery_note "` would take the unknown-type branch — safe,
    but for the wrong reason — and `" invoice "` would too."""
    from queue_worker.handlers import _routes_to_documents_table

    assert _routes_to_documents_table("  delivery_note  ") is True
    assert _routes_to_documents_table(" invoice ") is False


def test_document_model_carries_e10s_full_column_list():
    """E10's shape, asserted against the model so a column dropped in a later
    edit fails here rather than in production."""
    expected = {
        "id", "tenant_id", "batch_id", "file_path", "file_hash", "doc_type",
        "doc_type_evidence", "doc_type_confidence", "party_name",
        "counterparty_name", "doc_number", "po_number", "reference_numbers",
        "doc_date", "valid_until", "currency", "subtotal", "tax_amount",
        "discount_amount", "grand_total", "items", "taxes", "payment_terms",
        "delivery_terms", "incoterms", "notes", "status", "sa_alerts",
        "source_document_json", "created_at", "completed_at", "deleted_at",
        "last_enqueued_at", "processing_attempts", "submitted_by_email",
    }
    assert {c.name for c in Document.__table__.columns} == expected
    assert Document.__tablename__ == "documents"
    # Nothing invoice-specific leaked onto this table.
    for absent in ("coordinates", "compliance_metadata", "tax_ids", "round_off",
                   "flow_direction", "vendor_name", "field_confidence"):
        assert absent not in {c.name for c in Document.__table__.columns}


def test_document_status_vocabulary_matches_the_generic_profile():
    """The table and the extraction profile must agree by construction rather
    than through a mapping table someone has to maintain."""
    from agents.extraction_agent import _DIRECTION_PROFILES

    generic = _DIRECTION_PROFILES["GENERIC"]
    assert {generic.passed_status, generic.review_status} == {"EXTRACTED", "EXTRACT_FAILED"}
    assert Document.model_fields["status"].default == "EXTRACTED"


def test_invoice_doc_type_columns_are_nullable_with_a_none_default():
    """Every existing row stays valid with no backfill, and a flag-OFF run writes
    NULL exactly as it writes nothing today."""
    assert Invoice.__table__.c.doc_type.nullable is True
    assert Invoice.__table__.c.doc_type_evidence.nullable is True
    assert Invoice.model_fields["doc_type"].default is None
    assert Invoice.model_fields["doc_type_evidence"].default is None


# ---------------------------------------------------------------------------
# Gap 385 — the sibling collection's LIFECYCLE (no database; §2A/A4 item 3)
# ---------------------------------------------------------------------------
# G10 shipped creation and writes only. §2A/A4 item 3 asked for a decision, not
# silence, on the other half: the invoice collection has `delete_invoice_chunks`,
# `has_invoice_chunks` and `get_all_invoice_chunks` around it plus two operational
# scripts, and none of that existed for `docs_{tenant_id}`. The decision taken is
# "commit to the siblings", and these are its tests.
#
# Chroma-only, against the session-scoped EphemeralClient in `conftest.py` — no
# database, so these run whether or not the dev Postgres is up.


def _seed_document_chunks(tenant_id: str, document_id: str, pages: int = 2) -> None:
    """Two page chunks for one document, written the way `index_document_chunks()`
    writes them (same id shape, same metadata keys)."""
    from chroma_client import get_document_collection, get_embeddings

    texts = [f"Page {n} of purchase order PO-{document_id[:8]}" for n in range(1, pages + 1)]
    get_document_collection(tenant_id).upsert(
        ids=[f"{document_id}_page_{n}" for n in range(1, pages + 1)],
        embeddings=get_embeddings(texts),
        documents=texts,
        metadatas=[
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "doc_type": "PURCHASE_ORDER",
                "party_name": "Bharat Steels",
                "page": n,
            }
            for n in range(1, pages + 1)
        ],
    )


def test_has_and_get_all_document_chunks_are_scoped_to_one_document():
    """The read siblings. `get_all_document_chunks` ranks nothing and thresholds
    nothing — for the same reason `get_all_invoice_chunks` does not: once the
    document is already identified, "the page carrying the delivery quantities
    didn't score high enough" is silent data loss, not a relevance decision."""
    from chroma_client import get_all_document_chunks, has_document_chunks

    tenant_id = str(uuid4())
    wanted, other = str(uuid4()), str(uuid4())
    _seed_document_chunks(tenant_id, wanted, pages=3)
    _seed_document_chunks(tenant_id, other, pages=2)

    assert has_document_chunks(wanted, tenant_id) is True
    assert has_document_chunks(str(uuid4()), tenant_id) is False

    chunks = get_all_document_chunks(wanted, tenant_id)
    assert len(chunks) == 3
    assert [c["metadata"]["page"] for c in chunks] == [1, 2, 3]
    assert {c["metadata"]["document_id"] for c in chunks} == {wanted}
    # Named for the caller's benefit, and NOT "invoice_id": a Document is not an
    # Invoice (E10), and `index_document_chunks()` writes no `invoice_id` key at
    # all, so anything filtering on one must find nothing here.
    assert {c["matched_by"] for c in chunks} == {"document_id"}
    assert all("invoice_id" not in c["metadata"] for c in chunks)


def test_delete_document_chunks_removes_only_that_documents_pages():
    """The write-side sibling of `delete_invoice_chunks`, with a different policy
    about *when* to call it: that one is deliberately unwired from soft delete
    (Gap 239, so a restored invoice keeps its chunks), this one has a caller from
    the day it was written."""
    from chroma_client import delete_document_chunks, get_all_document_chunks, has_document_chunks

    tenant_id = str(uuid4())
    doomed, kept = str(uuid4()), str(uuid4())
    _seed_document_chunks(tenant_id, doomed, pages=2)
    _seed_document_chunks(tenant_id, kept, pages=2)

    delete_document_chunks(doomed, tenant_id)

    assert has_document_chunks(doomed, tenant_id) is False
    assert get_all_document_chunks(doomed, tenant_id) == []
    assert len(get_all_document_chunks(kept, tenant_id)) == 2


def test_document_chunk_lifecycle_functions_are_tenant_isolated():
    """Gap 55's guarantee, re-asserted on the new functions rather than assumed
    from the collection name: deleting tenant A's document cannot reach tenant B's
    chunks, and B's probe cannot see A's document even given its id."""
    from chroma_client import delete_document_chunks, get_all_document_chunks, has_document_chunks

    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    document_id = str(uuid4())  # the same id in both tenants — the hostile case
    _seed_document_chunks(tenant_a, document_id)
    _seed_document_chunks(tenant_b, document_id)

    delete_document_chunks(document_id, tenant_a)

    assert has_document_chunks(document_id, tenant_a) is False
    assert has_document_chunks(document_id, tenant_b) is True
    assert len(get_all_document_chunks(document_id, tenant_b)) == 2


def test_the_lifecycle_functions_never_open_a_collection_without_the_metadata():
    """§8 trap 3 / Gap 244, asserted structurally rather than by hoping. Chroma
    pins `hnsw:space` at creation and silently returns an existing collection on
    its original space, so ONE call site that forgets `_collection_metadata()`
    leaves `docs_{tenant}` permanently on `l2` — where
    `RELEVANCE_DISTANCE_THRESHOLD = 0.49` means nothing — recoverable only by a
    drop + re-embed. The invoice-side functions each pass the metadata themselves,
    four times; the document-side ones go through the single
    `get_document_collection()` call site instead."""
    import inspect

    import chroma_client

    for name in ("delete_document_chunks", "has_document_chunks", "get_all_document_chunks"):
        source = inspect.getsource(getattr(chroma_client, name))
        assert "get_document_collection(" in source, name
        assert "get_or_create_collection(" not in source, name


def test_delete_tenant_document_collection_drops_the_whole_collection():
    """Distinct from `delete_document_chunks`, and both are needed. Deleting every
    row's chunks one at a time leaves the collection itself behind, and an
    empty-but-present collection is indistinguishable from a live tenant's to the
    orphan sweep in `scripts/reembed_chroma_collections.py`. The tenant-expiry path
    is deleting a tenant, not a document, so it says that."""
    from chroma_client import (
        _document_collection_name,
        delete_tenant_document_collection,
        get_chroma_client,
    )

    tenant_id = str(uuid4())
    _seed_document_chunks(tenant_id, str(uuid4()))
    client = get_chroma_client()
    assert _document_collection_name(tenant_id) in [
        c if isinstance(c, str) else c.name for c in client.list_collections()
    ]

    delete_tenant_document_collection(tenant_id)

    assert _document_collection_name(tenant_id) not in [
        c if isinstance(c, str) else c.name for c in client.list_collections()
    ]


def test_dropping_a_collection_that_never_existed_is_not_an_error():
    """The common case: a sandbox visitor who never uploaded a non-invoice
    document has no `docs_` collection. Chroma raises for a missing collection
    rather than returning quietly, and a sweeper that dies on that leaves every
    later tenant unswept."""
    from chroma_client import delete_tenant_document_collection

    delete_tenant_document_collection(str(uuid4()))  # must not raise


def test_the_lifecycle_functions_cannot_reach_the_invoice_collection():
    """The isolation E10 buys, restated for the new functions. A chunk in
    `invoice_chunks_{tenant}` survives every document-side delete for the same
    tenant, and `query_invoice_chunks()` still cannot see the document
    collection — the property T-E10-4b asserts, re-checked here because these are
    the first functions written that could plausibly have blurred the boundary."""
    from chroma_client import (
        _collection_metadata,
        _tenant_collection_name,
        delete_document_chunks,
        delete_tenant_document_collection,
        get_chroma_client,
        get_embeddings,
        query_invoice_chunks,
    )

    tenant_id = str(uuid4())
    invoice_id = str(uuid4())
    text = "Invoice INV-2026-0441 grand total 118000 INR"
    get_chroma_client().get_or_create_collection(
        name=_tenant_collection_name(tenant_id), metadata=_collection_metadata(),
    ).upsert(
        ids=[f"{invoice_id}_page_1"],
        embeddings=get_embeddings([text]),
        documents=[text],
        metadatas=[{"tenant_id": tenant_id, "invoice_id": invoice_id, "page": 1}],
    )

    document_id = str(uuid4())
    _seed_document_chunks(tenant_id, document_id)

    delete_document_chunks(document_id, tenant_id)
    delete_tenant_document_collection(tenant_id)

    # The invoice chunk is untouched by both.
    assert query_invoice_chunks(tenant_id, text, limit=5) != []


# ---------------------------------------------------------------------------
# Gap 385 — the orphan sweep knows the sibling prefix exists
# ---------------------------------------------------------------------------
def test_the_reembed_script_sweeps_the_docs_prefix_too():
    """§2A/A4 item 3's other half. Left as it was, `scripts/reembed_chroma_collections.py`
    reported and pruned `invoice_chunks_*` only, so a `docs_{tenant}` belonging to
    a tenant with no Postgres row was invisible to the one tool that exists to find
    exactly that."""
    from scripts.reembed_chroma_collections import (
        COLLECTION_PREFIX,
        DOCUMENT_COLLECTION_PREFIX,
        ORPHAN_SWEEP_PREFIXES,
        _collection_names_for_prefix,
        _existing_collection_names,
    )

    from chroma_client import _document_collection_name

    assert DOCUMENT_COLLECTION_PREFIX == "docs_"
    assert set(ORPHAN_SWEEP_PREFIXES) == {COLLECTION_PREFIX, DOCUMENT_COLLECTION_PREFIX}
    # The prefix and the collection-name function agree, so a rename of one is
    # caught here rather than by a sweep that silently stops matching.
    tenant_id = str(uuid4())
    assert _document_collection_name(tenant_id).startswith(DOCUMENT_COLLECTION_PREFIX)

    class _FakeClient:
        def list_collections(self):
            return [
                "invoice_chunks_t1",
                "docs_t1",
                "docs_t2",
                "chat_docs_t1",  # Feature 26 — its own lifecycle, NOT swept here
            ]

    client = _FakeClient()
    assert set(_collection_names_for_prefix(client, DOCUMENT_COLLECTION_PREFIX)) == {"t1", "t2"}
    # The prefixes do not collide: "chat_docs_t1" must not be read as tenant
    # "t1" under the docs_ prefix, and the invoice-only view is unchanged.
    assert _collection_names_for_prefix(client, DOCUMENT_COLLECTION_PREFIX)["t1"] == "docs_t1"
    assert set(_existing_collection_names(client)) == {"t1"}


def test_the_reembed_rebuild_half_is_still_invoice_only():
    """Scope, asserted so it is not over-read later. Only the whole-collection
    orphan sweep learned the `docs_` prefix. Rebuilding a `docs_` collection would
    mean walking `Document` rows through `index_document_chunks()`, which is a
    feature rather than a prefix addition — and the distance-space migration this
    script was written for (Gap 244) does not apply to `docs_` anyway: every one
    of those collections was created after `_collection_metadata()` shipped, via
    `get_document_collection()`."""
    import inspect

    from scripts import reembed_chroma_collections

    source = inspect.getsource(reembed_chroma_collections.reembed)
    assert "index_invoice_document(" in source
    assert "index_document_chunks(" not in source
