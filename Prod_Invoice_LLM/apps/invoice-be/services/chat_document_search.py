"""Feature 26 Part 2 (task H3, decision E-2) — vector index/search over the text
of a document a user ATTACHED to a chat turn.

Deliberately its own module rather than three more functions in
`chroma_client.py`. That file is the *invoice* collection's module: every one of
its five `get_or_create_collection()` call sites names
`_tenant_collection_name()`, and keeping the sibling collection's access out of
it means an accidental cross-collection call shows up as a cross-file import in
a diff instead of hiding as a one-word change to a collection name.

**The single rule this module exists to enforce**: attachment chunks live in
`chat_docs_{tenant_id}` and never in `invoice_chunks_{tenant_id}`. The reason is
specific, not stylistic — `agents/query_agent.py`'s RAG route builds the model's
context from *every* retrieved chunk and only filters *citations* against real
`Invoice` rows afterwards. An attachment chunk sitting in the invoice collection
would therefore feed a quoted (not billed) price into an unrelated chat answer
and then have its source silently dropped: a wrong number with no visible
provenance. So this module never calls `_tenant_collection_name()` and never
calls `get_or_create_collection()` itself — it goes through
`chroma_client.get_chat_doc_collection()`, which is the one place that
collection may be created or opened and the one call passing
`_collection_metadata()` (task H2's contract; Chroma pins a collection's HNSW
space at creation, and a first creation that forgets the metadata leaves the
collection on `l2` permanently, where `RELEVANCE_DISTANCE_THRESHOLD = 0.49` —
derived empirically in cosine space — means nothing).

Scope of task H3, stated so the boundary is not guessed at: this module is
**not called by anything yet**. The embed step in
`routers/chat_attachments.py::_extract_attachment` is task H4 and the
content-branch call from `_run_attached_document_turn()` is task H5.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import fitz

# `_collection_space` and `_to_cosine_distance` are underscore-prefixed but are
# module-internal-to-the-app, not private-to-a-class: `query_invoice_chunks()`
# and `tests/test_rag.py` already use them the same way. They are imported here
# rather than reimplemented so a chat-doc distance and an invoice distance keep
# meaning the same thing (Gap 244).
from chroma_client import (
    _collection_space,
    _to_cosine_distance,
    embed_query,
    get_chat_doc_collection,
    get_embeddings,
)
from services.storage import download_pdf_from_storage

logger = logging.getLogger(__name__)

#: Default breadth of a content-branch search. Deliberately wider than the RAG
#: route's 5 (`query_invoice_chunks`'s default): amendment B5 dropped the
#: bounded tool-calling loop, so the content branch gets exactly **one** search
#: with the user's raw question and no chance to refine it. A slightly larger
#: window is the stated mitigation for that, and it is cheap here because the
#: search is already scoped to a single document's handful of pages.
DEFAULT_SEARCH_LIMIT = 6

#: Metadata key every chunk carries and every read filters on. Named once so the
#: writer and the reader cannot drift — a filter typo would silently return
#: another attachment's pages inside the same tenant, which is exactly what V-3
#: exists to catch.
ATTACHMENT_ID_METADATA_KEY = "attachment_id"


def _header(doc_type: str, party_name: str, doc_number: str, page: int) -> str:
    """E-2's chunk header.

    Deliberately *not* `index_invoice_document`'s
    `[Vendor: X | Document ID: Y | Page N]`. A retrieved chunk has to carry its
    own document type, because the single worst thing this feature can do is let
    a model read a *quoted* price off a quotation and narrate it as a *billed*
    price. "Vendor" is also wrong for a document the tenant itself issued (a PO
    they sent), which is why the field is "Party".
    """
    return (
        f"[Document type: {doc_type} | Party: {party_name} | "
        f"Document number: {doc_number} | Page {page}]\n"
    )


def index_attachment_chunks(attachment, tenant_id) -> int:
    """Chunk an attached document one chunk per page and index it into
    `chat_docs_{tenant_id}`. Returns the number of chunks written.

    `attachment` is a `models.ChatAttachment` row (duck-typed: `id`, `blob_path`,
    `doc_type`, `party_name`, `doc_number`). **The text comes from the stored
    PDF, not from `extracted_json`** — that column holds ~15 denormalised fields
    (doc number, party, totals, line items), which is precisely the shape that
    cannot answer "what are the payment terms?". The page text is re-read from
    the blob with `fitz`, the same way `index_invoice_document()` does it, so the
    chunk shape stays identical to the one the RAG route was tuned against.

    Idempotent: ids are `{attachment_id}_page_{n}` and the write is an `upsert`,
    so re-indexing the same attachment replaces its chunks rather than
    duplicating them.

    Failure policy mirrors `index_invoice_document()`: a missing blob or an
    unreadable PDF is logged and returns 0 rather than raising — the attachment
    row itself is still valid and the comparison branch (Part 1) does not need
    the index. A genuine Chroma write failure *does* propagate, so task H4 can
    decide whether it fails the upload; silently reporting "0 chunks" for a
    broken vector store would make an unsearchable document look like an empty
    one.
    """
    attachment_id = str(attachment.id)
    try:
        pdf_bytes = download_pdf_from_storage(attachment.blob_path)
    except Exception as e:
        logger.warning(
            "Chat attachment %s: PDF not available for indexing (%s): %s",
            attachment_id, attachment.blob_path, e,
        )
        return 0

    try:
        # Gap 446: an attachment may now be a PNG/JPEG on the Azure path. PyMuPDF
        # opens both; the filetype hint has to follow the file, or it raises on an
        # image and the document is stored with no searchable text at all.
        suffix = (attachment.blob_path or "").lower().rsplit(".", 1)[-1]
        filetype = suffix if suffix in ("png", "jpg", "jpeg") else "pdf"
        doc = fitz.open(stream=pdf_bytes, filetype=filetype)
    except Exception as e:
        logger.error("Chat attachment %s: failed to open PDF for indexing: %s", attachment_id, e)
        return 0

    doc_type = (getattr(attachment, "doc_type", None) or "OTHER").upper()
    party_name = getattr(attachment, "party_name", None) or "Unknown"
    doc_number = getattr(attachment, "doc_number", None) or "Unknown"

    chunks: List[str] = []
    metadata_list: List[Dict[str, Any]] = []
    ids: List[str] = []
    try:
        for idx, page in enumerate(doc):
            text = page.get_text()
            if not text.strip():
                continue
            chunks.append(_header(doc_type, party_name, doc_number, idx + 1) + text)
            metadata_list.append(
                {
                    "tenant_id": str(tenant_id),
                    # The scoping key. Note there is deliberately **no**
                    # `invoice_id` key on a chat-doc chunk: an attachment is not
                    # an invoice (D2), and anything filtering on `invoice_id`
                    # must find nothing here.
                    ATTACHMENT_ID_METADATA_KEY: attachment_id,
                    "doc_type": doc_type,
                    "party_name": party_name,
                    "doc_number": doc_number,
                    "page": idx + 1,
                }
            )
            ids.append(f"{attachment_id}_page_{idx + 1}")
    finally:
        doc.close()

    if not chunks:
        logger.info("Chat attachment %s: no extractable text to index.", attachment_id)
        return 0

    embeddings = get_embeddings(chunks)
    collection = get_chat_doc_collection(str(tenant_id))
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadata_list,
    )
    logger.info(
        "Indexed %d page chunks for chat attachment %s into chat_docs_%s",
        len(chunks), attachment_id, tenant_id,
    )
    return len(chunks)


def search_attachment_chunks(
    attachment_id,
    tenant_id,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> List[Dict[str, Any]]:
    """Vector search inside ONE attached document.

    `attachment_id` is the **first positional parameter and has no default**,
    per E-2: *"a chat-doc search with no attachment scope is not a valid call"*.
    Omitting it is a `TypeError` at the call site rather than a search that
    quietly ranges over every document in the tenant — a defaulted-to-`None`
    scope would mean one session's five attachments answer each other's
    questions.

    Scoping is a Chroma `where` clause, evaluated **before** `n_results`, not a
    Python filter over the results. A post-hoc filter would silently shrink the
    result set below `limit` whenever another attachment's pages outranked this
    one's, so a user with two documents open would get a thinner answer about
    the second. (A cheap equality re-check on the returned metadata is kept
    below purely as a backstop that *logs*; it is not the mechanism.)

    Returns a list of `{id, document, metadata, page, distance}`, best first.
    `distance` is normalised into cosine space via `_to_cosine_distance()` so it
    means the same thing as an invoice chunk's distance (Gap 244).

    **No relevance threshold is applied, and that is deliberate.**
    `query_invoice_chunks()` thresholds because it searches the whole tenant's
    corpus, where "nothing is relevant" is a real and important answer. Here the
    corpus *is* the document the user attached and explicitly asked about, so
    the only question is which of its pages is most relevant. Dropping the best
    page for scoring 0.51 would produce an "I couldn't find that" about a
    document sitting in front of the user. Callers that want a cutoff have the
    cosine distance to apply one.

    Returns `[]` on any Chroma error: an unreachable index must degrade the
    turn's evidence, never take the turn down (`get_all_invoice_chunks()`'s
    policy).
    """
    if attachment_id is None:
        # Belt and braces around the signature above: the parameter cannot be
        # omitted, and passing an explicit None is rejected here rather than
        # becoming `where={"attachment_id": "None"}` and matching nothing.
        raise ValueError("search_attachment_chunks requires an attachment_id.")

    try:
        collection = get_chat_doc_collection(str(tenant_id))
        collection_space = _collection_space(collection)
        results = collection.query(
            query_embeddings=[embed_query(query)],
            n_results=max(1, int(limit)),
            where={ATTACHMENT_ID_METADATA_KEY: str(attachment_id)},
        )
    except Exception as e:
        logger.warning(
            "Chat-doc search failed for attachment %s (tenant %s): %s",
            attachment_id, tenant_id, e,
        )
        return []

    if not results or not results.get("documents"):
        return []

    documents = results["documents"][0] or []
    metadatas = (results.get("metadatas") or [[]])[0] or []
    distances = (results.get("distances") or [[]])[0] or []
    ids = (results.get("ids") or [[]])[0] or []

    matches: List[Dict[str, Any]] = []
    for idx, document in enumerate(documents):
        metadata = metadatas[idx] if idx < len(metadatas) else {}
        metadata = metadata or {}
        found_id = str(metadata.get(ATTACHMENT_ID_METADATA_KEY) or "")
        if found_id != str(attachment_id):
            # Unreachable unless the `where` clause stopped working. Loud,
            # because the failure it guards is one attachment's content being
            # narrated as another's.
            logger.error(
                "Chat-doc search returned a chunk scoped to %s while searching %s; dropped.",
                found_id or "<none>", attachment_id,
            )
            continue
        raw_distance = distances[idx] if idx < len(distances) else 1.0
        matches.append(
            {
                "id": ids[idx] if idx < len(ids) else "",
                "document": document,
                "metadata": metadata,
                "page": metadata.get("page"),
                "distance": _to_cosine_distance(raw_distance, collection_space),
            }
        )
    return matches


def delete_attachment_chunks(attachment_id, tenant_id) -> None:
    """Remove every chunk belonging to one attachment from `chat_docs_{tenant}`.

    Written now, called later: task H8's TTL sweeper
    (`scripts/sweep_chat_attachments.py`, E-7) is its intended caller, along with
    any attachment-delete path H4 adds. Nothing calls it as of task H3.

    This is the one place in the feature where a delete is *correct*, unlike
    `delete_invoice_chunks()`, which is deliberately unwired from invoice
    soft-delete so a restored invoice keeps its chunks (Gap 239). An attachment
    has a genuine finite lifetime — it is a transient artifact of one
    conversation, and without this `chat_docs_{tenant_id}` grows without bound.

    Errors are logged and swallowed: a sweeper that dies on one unreachable
    tenant collection leaves every later tenant unswept.
    """
    if attachment_id is None:
        raise ValueError("delete_attachment_chunks requires an attachment_id.")
    try:
        collection = get_chat_doc_collection(str(tenant_id))
        collection.delete(where={ATTACHMENT_ID_METADATA_KEY: str(attachment_id)})
    except Exception as e:
        logger.warning(
            "Failed to delete chat-doc chunks for attachment %s (tenant %s): %s",
            attachment_id, tenant_id, e,
        )


__all__ = [
    "ATTACHMENT_ID_METADATA_KEY",
    "DEFAULT_SEARCH_LIMIT",
    "delete_attachment_chunks",
    "index_attachment_chunks",
    "search_attachment_chunks",
]
