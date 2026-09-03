"""Feature 26 Part 2, task H3 (E-2) — `services/chat_document_search.py`.

The file §P2.5 reserves for this module's isolation and scoping tests.

What is asserted here, and why each one is on the *retrieval* side rather than
the write side:

  * **V-1** — an attachment's chunks land in `chat_docs_{tenant}` and are
    **absent** from `invoice_chunks_{tenant}`, asserted by reading the invoice
    collection back and searching it for the attachment's distinctive text.
    Trusting the write path is exactly what this test refuses to do: the failure
    it guards is a quoted (not billed) price reaching an unrelated RAG answer
    with its citation silently dropped.
  * **V-3** — a search scoped to attachment A never returns a chunk from
    attachment B in the same tenant, *and* still returns a full `limit` worth of
    A's pages, which is what distinguishes a real `where` clause from a Python
    filter applied after `n_results`.
  * `attachment_id` cannot be omitted (E-2: "a chat-doc search with no
    attachment scope is not a valid call").

**Real chromadb is exercised** (1.5.9, through `get_chroma_client()`'s
`PersistentClient` fallback — no Chroma server is reachable from this
environment), because the point of V-1/V-3 is that the isolation is real and a
fake collection would prove nothing about it. **Embeddings are mocked**
(`MOCK_EMBEDDINGS=true`, as in `tests/test_rag.py`), so nothing here asserts on
*ranking* — every assertion is about which collection a chunk is in and which
attachment it belongs to, both of which are exact. Not a hard-rule-2
verification: no Postgres is involved and none is claimed.
"""
import inspect
import os

import pytest
from uuid import uuid4

# Must precede the chroma_client import, exactly as tests/test_rag.py does it.
os.environ["MOCK_EMBEDDINGS"] = "true"

import fitz

from chroma_client import (
    _tenant_collection_name,
    get_chat_doc_collection,
    get_chroma_client,
    index_invoice_document,
    query_invoice_chunks,
)
from models import ChatAttachment
from services.chat_document_search import (
    ATTACHMENT_ID_METADATA_KEY,
    DEFAULT_SEARCH_LIMIT,
    delete_attachment_chunks,
    index_attachment_chunks,
    search_attachment_chunks,
)

# Distinctive enough that a stray hit anywhere is unambiguous rather than a
# coincidence of shared invoice vocabulary.
PO_TEXT_PAGE_1 = "Meridian Ironworks purchase order net ninety day payment terms"
PO_TEXT_PAGE_2 = "Delivery to the Basingstoke depot before the equinox"
PO_TEXT_PAGE_3 = "Warranty covers the flange assembly for eighteen months"
QUOTE_TEXT_PAGE_1 = "Thornbury Glassworks quotation valid for forty five days"
INVOICE_TEXT = "Freight and logistics charges for delivery"


def _write_pdf(path: str, pages: list[str]) -> str:
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((50, 50), text)
    doc.save(path)
    doc.close()
    return path


def _attachment(path: str, **kw) -> ChatAttachment:
    """A real `ChatAttachment` row object (not persisted — this module never
    touches the database, and using the real class keeps the duck-typing honest
    about the attribute names H4 will actually be handing it)."""
    defaults = dict(
        tenant_id=uuid4(),
        session_id=uuid4(),
        filename="po.pdf",
        blob_path=path,
        doc_type="PURCHASE_ORDER",
        doc_number="PO-9911",
        party_name="Meridian Ironworks",
        extraction_status="EXTRACTED",
    )
    defaults.update(kw)
    return ChatAttachment(**defaults)


@pytest.fixture
def po_pdf(tmp_path):
    return _write_pdf(
        str(tmp_path / "po.pdf"), [PO_TEXT_PAGE_1, PO_TEXT_PAGE_2, PO_TEXT_PAGE_3]
    )


@pytest.fixture
def quote_pdf(tmp_path):
    return _write_pdf(str(tmp_path / "quote.pdf"), [QUOTE_TEXT_PAGE_1])


# ---------------------------------------------------------------------------
# index_attachment_chunks
# ---------------------------------------------------------------------------
def test_indexing_writes_one_chunk_per_page_with_the_e2_header(po_pdf):
    """E-2's chunk shape: one chunk per page, header-prefixed, and the header
    carries the document *type* — not `index_invoice_document`'s
    `[Vendor: ... | Document ID: ...]`. The type is what stops a model reading a
    quoted price off a quotation and narrating it as a billed one."""
    tenant_id = uuid4()
    attachment = _attachment(po_pdf, tenant_id=tenant_id)

    written = index_attachment_chunks(attachment, tenant_id)

    assert written == 3
    collection = get_chat_doc_collection(str(tenant_id))
    stored = collection.get()
    assert collection.count() == 3
    assert sorted(stored["ids"]) == sorted(
        f"{attachment.id}_page_{n}" for n in (1, 2, 3)
    )

    by_page = {m["page"]: (d, m) for d, m in zip(stored["documents"], stored["metadatas"])}
    document, metadata = by_page[1]
    assert document.startswith(
        "[Document type: PURCHASE_ORDER | Party: Meridian Ironworks "
        "| Document number: PO-9911 | Page 1]\n"
    )
    assert "Meridian Ironworks purchase order" in document
    assert metadata[ATTACHMENT_ID_METADATA_KEY] == str(attachment.id)
    assert metadata["tenant_id"] == str(tenant_id)
    # An attachment is not an invoice (D2). Nothing filtering on `invoice_id`
    # may ever find one of these.
    assert "invoice_id" not in metadata


def test_reindexing_the_same_attachment_replaces_rather_than_duplicates(po_pdf):
    """Ids are deterministic and the write is an upsert, so H4 re-running the
    embed step (a retry, a re-extraction) cannot double a document's chunks."""
    tenant_id = uuid4()
    attachment = _attachment(po_pdf, tenant_id=tenant_id)

    assert index_attachment_chunks(attachment, tenant_id) == 3
    assert index_attachment_chunks(attachment, tenant_id) == 3
    assert get_chat_doc_collection(str(tenant_id)).count() == 3


def test_indexing_an_unreadable_blob_returns_zero_rather_than_raising(tmp_path):
    """H4 sets `chunk_count` from this return value, so "we could not read it"
    has to be a number, not an exception that would fail an upload whose file is
    stored and whose extraction succeeded."""
    tenant_id = uuid4()
    missing = _attachment(str(tmp_path / "does-not-exist.pdf"), tenant_id=tenant_id)

    assert index_attachment_chunks(missing, tenant_id) == 0
    assert get_chat_doc_collection(str(tenant_id)).count() == 0


# ---------------------------------------------------------------------------
# V-1 — collection isolation, asserted from the invoice collection's side
# ---------------------------------------------------------------------------
def test_attachment_chunks_are_absent_from_the_invoice_collection(po_pdf, tmp_path):
    """**V-1**, the half task H2 deliberately left open because it needs this
    module's write path.

    The invoice collection is deliberately *non-empty* here — an assertion that
    a query returns nothing is worth much less against a collection that has
    nothing in it. So a real invoice is indexed first, then the attachment, then
    the invoice collection is interrogated for the attachment's distinctive
    text three ways: by RAG query, by raw read, and by the `attachment_id`
    metadata key."""
    tenant_id = uuid4()
    invoice_pdf = _write_pdf(str(tmp_path / "invoice.pdf"), [INVOICE_TEXT])
    index_invoice_document(
        invoice_id="inv-h3-1",
        tenant_id=tenant_id,
        vendor_name="Blue Ridge Logistics",
        file_path=invoice_pdf,
    )
    attachment = _attachment(po_pdf, tenant_id=tenant_id)
    assert index_attachment_chunks(attachment, tenant_id) == 3

    # The attachment's chunks exist -- so a zero-hit result on the invoice side
    # below is isolation, not an indexing no-op.
    assert get_chat_doc_collection(str(tenant_id)).count() == 3

    # 1. Through the product's own RAG retrieval path.
    hits = query_invoice_chunks(
        tenant_id=tenant_id, query_text="Meridian Ironworks payment terms", limit=10
    )
    assert all("Meridian Ironworks" not in h["document"] for h in hits)
    assert all(str(attachment.id) not in h["id"] for h in hits)

    # 2. Reading the invoice collection directly -- no ranking involved at all.
    invoice_collection = get_chroma_client().get_collection(
        _tenant_collection_name(tenant_id)
    )
    stored = invoice_collection.get()
    assert invoice_collection.count() == 1  # the invoice's single page, nothing else
    assert all("Meridian Ironworks" not in d for d in stored["documents"])
    assert all(
        ATTACHMENT_ID_METADATA_KEY not in (m or {}) for m in stored["metadatas"]
    )

    # 3. And by the scoping key itself.
    scoped = invoice_collection.get(
        where={ATTACHMENT_ID_METADATA_KEY: str(attachment.id)}
    )
    assert scoped["ids"] == []


def test_a_tenants_chat_doc_chunks_are_invisible_to_another_tenant(po_pdf):
    """**V-4**'s shape. Isolation is structural (Gap 55) -- a different tenant is
    a different collection, not a metadata filter someone has to remember."""
    tenant_a, tenant_b = uuid4(), uuid4()
    attachment = _attachment(po_pdf, tenant_id=tenant_a)
    index_attachment_chunks(attachment, tenant_a)

    assert get_chat_doc_collection(str(tenant_b)).count() == 0
    # Same attachment id, wrong tenant: nothing, because the id is looked up in
    # tenant B's own collection.
    assert search_attachment_chunks(attachment.id, tenant_b, "payment terms") == []


# ---------------------------------------------------------------------------
# V-3 — attachment_id scoping
# ---------------------------------------------------------------------------
def test_search_scoped_to_one_attachment_never_returns_anothers_chunks(
    po_pdf, quote_pdf
):
    """**V-3**. Two attachments, one tenant, one session.

    `limit` is set to exactly the number of pages the scoped document has, so
    the test also distinguishes a real `where` clause from a Python filter over
    the results: under a post-hoc filter the quotation's page could occupy one
    of the three slots and the assertion on the returned count would fail."""
    tenant_id = uuid4()
    session_id = uuid4()
    po = _attachment(po_pdf, tenant_id=tenant_id, session_id=session_id)
    quote = _attachment(
        quote_pdf,
        tenant_id=tenant_id,
        session_id=session_id,
        doc_type="QUOTATION",
        doc_number="QT-4",
        party_name="Thornbury Glassworks",
        filename="quote.pdf",
    )
    index_attachment_chunks(po, tenant_id)
    index_attachment_chunks(quote, tenant_id)
    assert get_chat_doc_collection(str(tenant_id)).count() == 4

    results = search_attachment_chunks(po.id, tenant_id, "how long is the warranty", limit=3)

    assert len(results) == 3
    assert all(
        r["metadata"][ATTACHMENT_ID_METADATA_KEY] == str(po.id) for r in results
    )
    assert all("Thornbury Glassworks" not in r["document"] for r in results)
    assert sorted(r["page"] for r in results) == [1, 2, 3]

    # And the mirror: searching the quotation cannot reach the PO.
    quote_results = search_attachment_chunks(quote.id, tenant_id, "warranty", limit=6)
    assert len(quote_results) == 1
    assert "Thornbury Glassworks" in quote_results[0]["document"]
    assert all("Meridian Ironworks" not in r["document"] for r in quote_results)


def test_search_returns_cosine_distances_and_page_numbers(po_pdf):
    """The content branch (H5) renders `evidence[]` with page numbers, and any
    future caller that wants a cutoff needs the distance to mean what it means
    everywhere else (Gap 244: cosine, whatever space the collection is in)."""
    tenant_id = uuid4()
    attachment = _attachment(po_pdf, tenant_id=tenant_id)
    index_attachment_chunks(attachment, tenant_id)

    results = search_attachment_chunks(attachment.id, tenant_id, "payment terms")

    assert results
    for r in results:
        assert r["page"] in (1, 2, 3)
        assert 0.0 <= r["distance"] <= 2.0
        assert r["document"].startswith("[Document type: PURCHASE_ORDER")


def test_search_on_a_tenant_with_no_attachments_returns_empty(po_pdf):
    """An empty sibling collection is a normal state (no attachment has been
    indexed yet), not an error, and must not take a turn down."""
    assert search_attachment_chunks(uuid4(), uuid4(), "anything at all") == []


# ---------------------------------------------------------------------------
# attachment_id is required -- E-2, stated as a signature property
# ---------------------------------------------------------------------------
def test_attachment_id_is_a_required_parameter_not_a_defaulted_one():
    """E-2: *"a chat-doc search with no attachment scope is not a valid call"*.

    Asserted three ways, because the defect this guards is a *silently* wider
    search rather than a crash: the signature has no default, omitting the
    argument is a `TypeError`, and passing an explicit `None` is rejected
    instead of becoming `where={"attachment_id": "None"}`."""
    signature = inspect.signature(search_attachment_chunks)
    first = list(signature.parameters.values())[0]
    assert first.name == "attachment_id"
    assert first.default is inspect.Parameter.empty

    with pytest.raises(TypeError):
        search_attachment_chunks(tenant_id=uuid4(), query="what are the terms")

    with pytest.raises(ValueError):
        search_attachment_chunks(None, uuid4(), "what are the terms")

    # Same rule on the delete path -- an unscoped delete would empty a tenant's
    # whole chat-doc collection.
    delete_signature = inspect.signature(delete_attachment_chunks)
    delete_first = list(delete_signature.parameters.values())[0]
    assert delete_first.name == "attachment_id"
    assert delete_first.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        delete_attachment_chunks(tenant_id=uuid4())


def test_default_search_limit_is_wider_than_the_rag_routes_five():
    """Amendment B5 dropped the tool loop, so the content branch gets exactly one
    search with the raw question and no chance to refine it; the stated
    mitigation is a wider window than `query_invoice_chunks`'s default of 5."""
    assert DEFAULT_SEARCH_LIMIT >= 6
    assert inspect.signature(search_attachment_chunks).parameters["limit"].default == (
        DEFAULT_SEARCH_LIMIT
    )


# ---------------------------------------------------------------------------
# delete_attachment_chunks
# ---------------------------------------------------------------------------
def test_delete_removes_only_that_attachments_chunks(po_pdf, quote_pdf):
    """H8's TTL sweeper is the intended caller. A delete that took the tenant's
    other attachments with it would silently un-ground every other open
    conversation in that tenant."""
    tenant_id = uuid4()
    po = _attachment(po_pdf, tenant_id=tenant_id)
    quote = _attachment(
        quote_pdf, tenant_id=tenant_id, doc_type="QUOTATION", party_name="Thornbury Glassworks"
    )
    index_attachment_chunks(po, tenant_id)
    index_attachment_chunks(quote, tenant_id)

    delete_attachment_chunks(po.id, tenant_id)

    assert get_chat_doc_collection(str(tenant_id)).count() == 1
    assert search_attachment_chunks(po.id, tenant_id, "payment terms") == []
    assert len(search_attachment_chunks(quote.id, tenant_id, "validity")) == 1
