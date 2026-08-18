import os
import logging
import fitz
import chromadb
import threading
from typing import Callable, Optional
from sentence_transformers import SentenceTransformer
from config import get_settings
from services.storage import download_pdf_from_storage

logger = logging.getLogger(__name__)

_chroma_client = None
_embedding_model = None
_embedding_lock = threading.Lock()

# Gap 244: relevance cutoff for `query_invoice_chunks()`, expressed in **cosine
# distance** (0 = identical, 1 = orthogonal, 2 = opposite). Replaces the old 0.4,
# which was never reachable because collections were created in Chroma's default
# raw-L2 space (see `_collection_metadata()` below).
#
# Derived empirically 2026-08-17, not chosen by intuition. Method: the 8-turn
# category-browsing test's real questions were run against real BAAI/bge-m3
# embeddings of the real invoice PDFs, twice -- once over tenant-us's 10
# invoices, once over all 30 invoices of the three InvoiceEQ test tenants so the
# false-positive floor was estimated off ~3x the negatives. Both runs produced
# the same separation band:
#   * hardest genuine match that is separable at all: 0.4749
#     ("Any janitorial or cleaning services?" -> Redwood Facilities Group)
#   * best (lowest) distance any chunk reaches on a deliberately-absent category:
#     0.5062 ("Do we have any legal or attorney fees?" -> Fieldstone Analytics)
# 0.49 is the midpoint of [0.4749, 0.5062], i.e. the maximally drift-tolerant
# point between "still catches real matches" and "still answers 'no match'
# honestly for a category the tenant genuinely doesn't have". At 0.49 the
# labelled set scores 6/7 recall with **zero** chunks passing on either
# absent-category question.
#
# The one genuine match 0.49 does not catch is CMC-330217 at 0.5331 (a single
# $200 freight line item on an otherwise-manufacturing invoice) -- it sits
# *above* the false-positive floor, so no threshold can admit it without also
# admitting fabricated matches. That case is left to the keyword pass below,
# which is now a genuine second channel rather than the only working one.
RELEVANCE_DISTANCE_THRESHOLD = 0.49

# Statuses whose documents must never be indexed: PROCESSING/UPLOADED haven't
# been extracted yet, FAILED has no usable content, and DUPLICATE is a pointer
# row whose content is already indexed under the original invoice. Everything
# else is indexable -- notably AUDIT_REQUIRED (Gap 240) and NEEDS_REVIEW
# (Gap 243), whose text is exactly as searchable as a clean invoice's.
NON_INDEXABLE_STATUSES = frozenset({
    "UPLOADED", "PROCESSING", "PROCESSING_OCR", "EXTRACTING_DATA",
    "INDEXING", "FAILED", "DUPLICATE", "SKIPPED_DUPLICATE",
})


def should_index_status(status: str | None) -> bool:
    """
    Gaps 240/243: single shared answer to "should this invoice's document be in
    the RAG index?", used by both ingestion handlers, both audit-resolve
    backstops, and the re-embed migration script, so the four can't drift apart
    the way the old `status == "COMPLETED"` / `status == "VERIFIED"` literals did.

    RAG content is independent of arithmetic-verification outcome -- a flagged
    invoice's text is exactly as searchable as a clean one's, and is arguably
    the more likely one to be asked about.
    """
    return bool(status) and status.upper() not in NON_INDEXABLE_STATUSES


def _collection_metadata() -> dict:
    """
    Gap 244: Chroma defaults a collection's HNSW index to raw (squared) L2
    distance, which is unbounded and scales with vector magnitude -- there is no
    single threshold value that means "relevant" in that space. Every collection
    this module creates is pinned to cosine instead.

    Migration hazard, verified live against chromadb 1.5.9: passing this metadata
    to `get_or_create_collection()` for a collection that **already exists**
    silently returns the existing collection with its original `space` -- no
    error, no warning. Chroma fixes the HNSW space at creation time. Existing
    collections therefore have to be dropped and re-embedded; see
    `scripts/reembed_chroma_collections.py`. `query_invoice_chunks()` below
    tolerates a not-yet-migrated collection so the threshold still means the
    same thing either way, but that is a compatibility shim, not a substitute
    for running the migration.
    """
    return {"hnsw:space": "cosine"}


def _collection_space(collection) -> str:
    """
    Reads the HNSW distance space a collection was actually created with.
    Defaults to Chroma's own default ("l2") when the client/collection object
    doesn't expose a configuration (older clients, fakes in unit tests).
    """
    try:
        config = getattr(collection, "configuration_json", None) or {}
        space = (config.get("hnsw") or {}).get("space")
        if space:
            return str(space).lower()
    except Exception:  # pragma: no cover - defensive, never worth failing a query for
        pass
    try:
        meta = getattr(collection, "metadata", None) or {}
        space = meta.get("hnsw:space")
        if space:
            return str(space).lower()
    except Exception:  # pragma: no cover
        pass
    return "l2"


def _to_cosine_distance(distance: float, space: str) -> float:
    """
    Gap 244: normalize a Chroma distance into cosine distance so
    `RELEVANCE_DISTANCE_THRESHOLD` means one thing everywhere.

    Because `get_embeddings()` guarantees unit-norm vectors:
      * `cosine` -> already 1 - cos(a, b). Passed through.
      * `l2`     -> Chroma returns the *squared* L2 distance, and for unit
                    vectors ||a-b||^2 = 2 - 2*cos(a, b) = 2 * cosine_distance,
                    so halving it is exact, not an approximation. This is what
                    keeps a pre-migration (`space=l2`) collection scoring on the
                    same scale as a migrated one. Verified against the real
                    stack: the same 8 queries measured 0.9709/0.7646/0.8263/...
                    in l2 and exactly half those values (0.4854/0.3823/0.4131/...)
                    in cosine.
      * `ip`     -> 1 - dot(a, b), which equals cosine distance for unit vectors.

    The unit-norm premise holds for anything indexed by this module today. It
    does not hold for chunks written by the *old* mock-embedding path (norm
    ~1.85), whose distances stay far above the threshold and fall through to the
    keyword pass -- which is the pre-existing behaviour, and is resolved for real
    by re-embedding rather than by more arithmetic here.
    """
    try:
        d = float(distance)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 1.0
    if space == "l2":
        return d / 2.0
    return d

def get_chroma_client():
    """Returns the Chroma client instance, falling back to a persistent local db."""
    global _chroma_client
    if _chroma_client is None:
        settings = get_settings()
        try:
            logger.info("Initializing Chroma HttpClient at %s:%s (ssl=%s)", settings.CHROMA_HOST, settings.CHROMA_PORT, settings.CHROMA_USE_SSL)
            _chroma_client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT,
                ssl=settings.CHROMA_USE_SSL
            )
            # Verify connection
            _chroma_client.heartbeat()
        except Exception as e:
            logger.warning("Chroma HttpClient failed: %s. Falling back to PersistentClient.", e)
            _chroma_client = chromadb.PersistentClient(path=os.path.join(os.path.dirname(__file__), "temp_chroma_db"))
    return _chroma_client

def get_embedding_model():
    """Returns the SentenceTransformer model (mocked if MOCK_EMBEDDINGS=true)."""
    global _embedding_model
    settings = get_settings()
    if settings.MOCK_EMBEDDINGS:
        return None

    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                logger.info("Loading sentence-transformers BAAI/bge-m3 model...")
                _embedding_model = SentenceTransformer("BAAI/bge-m3")
    return _embedding_model

def _tenant_collection_name(tenant_id: str) -> str:
    """
    Gap 55: one Chroma collection per tenant instead of a single shared
    "invoice_chunks" collection filtered by a tenant_id metadata field.
    Structural isolation instead of filter-based, and the seam a future
    per-tenant Chroma instance/cluster router would plug into.
    """
    return f"invoice_chunks_{tenant_id}"

def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Calculates embedding vectors for a list of texts (1024-dimensional, unit norm).

    Gap 244: `normalize_embeddings=True` is passed explicitly. Measured against
    the real model, `BAAI/bge-m3`'s own `modules.json` already ends in a
    `sentence_transformers.models.Normalize` module, so this is currently a
    no-op that returns the same L2-norm-1.0 vectors -- it is here as an explicit
    contract, so that swapping in any model whose ST config lacks that module
    can't silently reintroduce unnormalized vectors and break the cosine
    threshold above.

    The mock branch is normalized for the same reason. Unnormalized mock vectors
    (`random.uniform(-0.1, 0.1)` over 1024 dims) have an L2 norm of ~1.85 and sit
    ~6.5 apart in squared-L2 space, which is what made Gap 244's original
    investigation read a mock-mode collection as evidence about the real model.
    """
    model = get_embedding_model()
    if model is None:
        import math
        import random
        mock = []
        for _ in texts:
            vec = [random.uniform(-0.1, 0.1) for _ in range(1024)]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            mock.append([v / norm for v in vec])
        return mock
    with _embedding_lock:
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.tolist()

def index_invoice_document(
    invoice_id: str,
    tenant_id: str,
    vendor_name: str | None,
    file_path: str,
    on_log: Optional[Callable[[str], None]] = None,
):
    """
    Load a PDF page-by-page, prepend structured context metadata headers,
    generate embedding vectors, and index chunks into the Chroma collection.
    """
    logger.info("Indexing invoice document %s for tenant %s", invoice_id, tenant_id)
    try:
        pdf_bytes = download_pdf_from_storage(file_path)
    except Exception as e:
        logger.warning("PDF file not found for RAG indexing: %s (%s)", file_path, e)
        return

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error("Failed to open PDF for RAG indexing: %s", e)
        return
        
    chunks = []
    metadata_list = []
    ids = []

    if on_log:
        on_log("Chunking document pages...")

    try:
        for idx, page in enumerate(doc):
            text = page.get_text()
            if not text.strip():
                continue
            
            # Prepend structured context metadata header to keep page constraints clear
            vendor = vendor_name or "Unknown"
            header = f"[Vendor: {vendor} | Document ID: {invoice_id} | Page {idx + 1}]\n"
            chunk_content = header + text
            
            chunks.append(chunk_content)
            metadata_list.append({
                "tenant_id": str(tenant_id),
                "invoice_id": str(invoice_id),
                "vendor_name": vendor,
                "page": idx + 1
            })
            ids.append(f"{invoice_id}_page_{idx + 1}")
    finally:
        doc.close()
        
    if not chunks:
        logger.info("No extractable text found in PDF for indexing.")
        return

    if on_log:
        on_log("Generating page embeddings...")
    embeddings = get_embeddings(chunks)

    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=_tenant_collection_name(tenant_id),
        metadata=_collection_metadata(),
    )
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadata_list
    )
    logger.info("Successfully indexed %d page chunks for invoice %s", len(chunks), invoice_id)

def delete_invoice_chunks(invoice_id: str, tenant_id: str) -> None:
    """
    Deletes all indexed vector chunks for a given invoice from that tenant's collection.

    Gap 239: deliberately **not** wired into `routers/invoices.py::delete_invoice`
    or `::rollback_batch` -- both are soft deletes (Gap 192), which keep the
    Chroma chunks on purpose so a restore stays possible. Its callers are the
    orphan-pruning path of `scripts/reembed_chroma_collections.py` and any future
    hard-delete/purge path. If a hard delete is ever added, it must call this.
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=_tenant_collection_name(tenant_id),
        metadata=_collection_metadata(),
    )
    collection.delete(where={"invoice_id": str(invoice_id)})


def has_invoice_chunks(invoice_id: str, tenant_id: str) -> bool:
    """
    Gaps 240/243: cheap "is this invoice already in the index?" probe, so the
    audit-resolve backstops can skip the expensive PDF-download + embed round
    trip for the normal case where ingestion already indexed the invoice.
    Returns False on any Chroma error -- callers treat that as "index it", and
    `index_invoice_document()` upserts by a deterministic id, so a redundant
    call is idempotent rather than duplicating chunks.
    """
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(
            name=_tenant_collection_name(tenant_id),
            metadata=_collection_metadata(),
        )
        existing = collection.get(where={"invoice_id": str(invoice_id)}, limit=1)
        return bool(existing and existing.get("ids"))
    except Exception as e:
        logger.warning("Chroma chunk-presence probe failed for invoice %s: %s", invoice_id, e)
        return False

def query_invoice_chunks(tenant_id: str, query_text: str, limit: int = 5) -> list[dict]:
    """
    Query indexed invoice chunks. Isolation is structural (Gap 55) — each tenant has
    its own Chroma collection, so no metadata `where` filter is needed to keep one
    tenant's results out of another's, and this is also the seam a future per-tenant
    Chroma instance/cluster router would plug into.
    Includes a hybrid keyword pass and local reranker (Gap 22), enforcing a distance
    relevance threshold (Gap 21, re-derived empirically in Gap 244).
    """
    import re

    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=_tenant_collection_name(tenant_id),
        metadata=_collection_metadata(),
    )
    # Gap 244: a collection created before this fix keeps its original `l2`
    # space forever (Chroma pins the HNSW space at creation and ignores the
    # metadata above on an existing collection). Read what the collection
    # actually uses so the threshold can be applied in one consistent space
    # whether or not the re-embed migration has been run for this tenant yet.
    collection_space = _collection_space(collection)

    query_embeddings = get_embeddings([query_text])

    # Gap 22: Fetch a larger candidate pool for reranking
    candidate_limit = limit * 3
    results = collection.query(
        query_embeddings=query_embeddings,
        n_results=candidate_limit
    )
    
    if not results or not results.get("documents") or len(results["documents"]) == 0:
        return []

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results.get("distances", [[]])[0]
    ids = results["ids"][0]
    
    # Extract query keywords for hybrid pass (ignore common stopwords)
    stopwords = {"THE", "AND", "FOR", "WITH", "THAT", "THIS", "ARE", "WAS", "WHAT", "WHO", "WHERE", "HOW", "MANY", "MUCH", "DOES", "DID", "HAS", "HAVE", "HAD"}
    keywords = set(re.findall(r'\b[A-Z0-9-]{3,}\b|\b\d+(?:\.\d+)?\b', query_text.upper()))
    keywords = {kw for kw in keywords if kw not in stopwords}

    candidates = []
    for idx in range(len(documents)):
        doc_text = documents[idx]
        doc_upper = doc_text.upper()
        
        # Semantic distance, expressed in cosine space regardless of how this
        # particular collection was created (Gap 244).
        raw_dist = distances[idx] if idx < len(distances) else 1.0
        vec_dist = _to_cosine_distance(raw_dist, collection_space)
        
        # Keyword Pass Score (TF-like)
        k_score = sum(1 for kw in keywords if kw in doc_upper)
        
        # Combine: each matching keyword boosts the semantic distance (lowers it)
        # We cap the boost so a huge keyword match doesn't pull in totally irrelevant semantic stuff
        # but 0.1 per keyword is enough to rerank strong exact matches to the top.
        combined_score = vec_dist - (k_score * 0.1)
        
        candidates.append({
            "id": ids[idx],
            "document": doc_text,
            "metadata": metadatas[idx],
            "distance": vec_dist,
            "combined_score": combined_score,
            "keyword_score": k_score
        })

    # Rerank by combined score
    candidates.sort(key=lambda x: x["combined_score"])

    # Gap 21 / Gap 244: enforce the relevance threshold, in cosine distance.
    # We apply the threshold on the original vector distance to avoid false positives,
    # OR if there's a strong keyword match, we let it pass (exact match fallback).
    matched_chunks = []
    min_k_score = min(2, max(1, len(keywords))) # Require 1 if only 1 keyword, 2 if >= 2
    for chunk in candidates:
        passed_vector = chunk["distance"] <= RELEVANCE_DISTANCE_THRESHOLD
        passed_keyword = chunk["keyword_score"] >= min_k_score
        if passed_vector or passed_keyword:
            matched_chunks.append({
                "id": chunk["id"],
                "document": chunk["document"],
                "metadata": chunk["metadata"],
                "distance": chunk["distance"],
                # Gap 244: which channel actually admitted this chunk. Reported
                # so a caller/test can tell a genuine semantic match from one
                # carried only by the literal-keyword fallback -- before this
                # gap was fixed, *every* match was the latter, and nothing in
                # the return value made that visible. Purely additive:
                # agents/query_agent.py reads only `document` and `metadata`.
                "keyword_score": chunk["keyword_score"],
                "matched_by": (
                    "vector+keyword" if passed_vector and passed_keyword
                    else "vector" if passed_vector
                    else "keyword"
                ),
            })
            if len(matched_chunks) >= limit:
                break

    return matched_chunks
