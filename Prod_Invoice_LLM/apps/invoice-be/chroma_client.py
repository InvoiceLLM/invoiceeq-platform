import os
import time
import logging
import contextlib
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
_chroma_lock = threading.Lock()

# Gap 278: bounds on the Chroma HTTP session. `connect` is the one that matters
# for the reported bug -- an unreachable Chroma container used to burn the OS's
# whole TCP connect-retry budget (~140s, ending in `[Errno 110] Connection timed
# out`) before `get_chroma_client()`'s PersistentClient fallback could run, and
# that entire wait happened inline inside a live chat request. `read` is kept
# generous because a legitimate query/upsert against a warm server is a real
# workload, not a handshake -- shortening it would trade one failure mode for
# another.
CHROMA_CONNECT_TIMEOUT_SECONDS = 3.0
CHROMA_READ_TIMEOUT_SECONDS = 30.0

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

class _TimeoutBoundHttpx:
    """
    Gap 278: stand-in for the `httpx` module *as seen by
    `chromadb.api.fastapi`*, whose only job is to force a timeout onto the
    session chromadb builds for itself.

    chromadb 1.5.9 constructs that session as `httpx.Client(timeout=None, ...)`
    (`chromadb/api/fastapi.py`, both branches) and exposes no way to change it:
    `chromadb.HttpClient()` takes `(host, port, ssl, headers, settings, tenant,
    database)` and nothing else, and the only `*_timeout_seconds` fields in
    `chromadb.config.Settings` (`chroma_logservice_/sysdb_/query_request_...`)
    belong to the server's own internal components, not to this HTTP session.
    Because chromadb passes `timeout=None` explicitly, a `functools.partial`
    default would collide -- the keyword has to be overwritten, hence this
    wrapper rather than a bound default.

    Everything other than `Client` is delegated to the real module, so
    `httpx.ConnectError`/`httpx.HTTPStatusError` and friends stay identical
    objects and `except` clauses inside chromadb keep matching.
    """

    def __init__(self, module, timeout):
        self._module = module
        self._timeout = timeout

    def Client(self, *args, **kwargs):
        kwargs["timeout"] = self._timeout
        return self._module.Client(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._module, name)


def _chroma_http_timeout():
    """The `httpx.Timeout` applied to chromadb's HTTP session (Gap 278)."""
    import httpx

    return httpx.Timeout(
        connect=CHROMA_CONNECT_TIMEOUT_SECONDS,
        read=CHROMA_READ_TIMEOUT_SECONDS,
        write=CHROMA_READ_TIMEOUT_SECONDS,
        pool=CHROMA_CONNECT_TIMEOUT_SECONDS,
    )


@contextlib.contextmanager
def _bounded_chroma_http_timeout():
    """
    Gap 278: makes the timeout above apply to the `chromadb.HttpClient(...)`
    call itself, not just to later requests.

    The swap has to be in place *during construction*: `chromadb.api.client.
    Client.__init__` already issues live HTTP (`get_user_identity()`, then
    `_validate_tenant_database()`) before the caller ever gets the object back,
    so setting a timeout on the finished client would be too late -- the ~140s
    hang this gap is about happened inside the constructor. The session object
    built in that window keeps the timeout afterwards, so every subsequent
    request through the cached singleton is bounded too.

    Scoped to `chromadb.api.fastapi`'s module global rather than to
    `httpx.Client` itself, so nothing else in the process (Clerk JWKS fetches,
    outbound webhooks, connector calls) can pick up Chroma's timeout during the
    window.
    """
    try:
        from chromadb.api import fastapi as chroma_fastapi
    except Exception:  # pragma: no cover - chromadb layout changed; don't block the client
        yield
        return

    original = chroma_fastapi.httpx
    chroma_fastapi.httpx = _TimeoutBoundHttpx(original, _chroma_http_timeout())
    try:
        yield
    finally:
        chroma_fastapi.httpx = original


def _build_chroma_client():
    """Constructs the Chroma client, falling back to a persistent local db."""
    settings = get_settings()
    try:
        logger.info("Initializing Chroma HttpClient at %s:%s (ssl=%s)", settings.CHROMA_HOST, settings.CHROMA_PORT, settings.CHROMA_USE_SSL)
        with _bounded_chroma_http_timeout():
            client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT,
                ssl=settings.CHROMA_USE_SSL
            )
            # Verify connection
            client.heartbeat()
        return client
    except Exception as e:
        logger.warning("Chroma HttpClient failed: %s. Falling back to PersistentClient.", e)
        return chromadb.PersistentClient(path=os.path.join(os.path.dirname(__file__), "temp_chroma_db"))


def get_chroma_client():
    """
    Returns the process-wide Chroma client singleton, falling back to a
    persistent local db when the server is unreachable.

    Gap 278: the construction is now under `_chroma_lock` as well as bounded by
    `_bounded_chroma_http_timeout()`. Without the lock, every request that
    arrived while the first one was still connecting would start its own
    connect attempt and pay the same wait -- which is what turned a single cold
    start into a window of apparently-hung chat rather than one slow turn.
    """
    global _chroma_client
    if _chroma_client is None:
        with _chroma_lock:
            if _chroma_client is None:
                _chroma_client = _build_chroma_client()
    return _chroma_client


def warm_rag_dependencies() -> dict:
    """
    Gap 278: primes both lazy singletons in this module -- the Chroma client and
    the `BAAI/bge-m3` SentenceTransformer -- so no live chat request pays their
    cold-start cost inline.

    Called from `main.py`'s lifespan hook at process startup (in a background
    thread; see the comment there for why it must not block startup). Both
    halves are best-effort and swallow their own failures: an unreachable
    Chroma is already handled by `get_chroma_client()`'s PersistentClient
    fallback, and a failed model load must degrade to the pre-existing lazy
    behaviour on the next call rather than take the process down.

    Returns a per-dependency status dict, which is what the startup log line
    below reports; nothing branches on it.
    """
    results: dict[str, str] = {}

    started = time.monotonic()
    try:
        client = get_chroma_client()
        client.heartbeat()
        results["chroma"] = "ok"
    except Exception as e:
        results["chroma"] = f"degraded: {e}"
        logger.warning("RAG warm-up: Chroma unavailable (%s)", e)
    chroma_seconds = time.monotonic() - started

    started = time.monotonic()
    try:
        results["embedding_model"] = "mocked" if get_embedding_model() is None else "ok"
    except Exception as e:
        results["embedding_model"] = f"failed: {e}"
        logger.warning("RAG warm-up: embedding model failed to load (%s)", e)
    model_seconds = time.monotonic() - started

    logger.info(
        "RAG warm-up complete: chroma=%s (%.1fs), embedding_model=%s (%.1fs)",
        results["chroma"], chroma_seconds, results["embedding_model"], model_seconds,
    )
    return results

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

def get_all_invoice_chunks(invoice_id: str, tenant_id: str) -> list[dict]:
    """Every indexed page of ONE invoice, by direct metadata filter.

    Feature 21's `get_full_record` companion, and deliberately not a search:
    `query_invoice_chunks()` below ranks a candidate pool against a query
    embedding and drops whatever falls under the relevance threshold, which is
    the right behaviour for discovery ("which invoices relate to X") and the
    wrong behaviour once the invoice is already identified -- there, "the page
    carrying the tax table didn't score high enough" is a silent data loss, not
    a relevance decision. So this ranks nothing, thresholds nothing and returns
    every chunk, ordered by page.

    Same structural isolation as every other function here (Gap 55: one
    collection per tenant); the `invoice_id` metadata filter is what narrows it
    to a single invoice. Returns `[]` on any Chroma error -- an unreachable
    index must degrade the answer to "structured record only", never take the
    turn down.
    """
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(
            name=_tenant_collection_name(tenant_id),
            metadata=_collection_metadata(),
        )
        found = collection.get(where={"invoice_id": str(invoice_id)})
    except Exception as e:
        logger.warning("Chroma chunk fetch failed for invoice %s: %s", invoice_id, e)
        return []

    if not found or not found.get("ids"):
        return []

    documents = found.get("documents") or []
    metadatas = found.get("metadatas") or []
    chunks = []
    for idx, chunk_id in enumerate(found["ids"]):
        metadata = metadatas[idx] if idx < len(metadatas) else {}
        chunks.append(
            {
                "id": chunk_id,
                "document": documents[idx] if idx < len(documents) else "",
                "metadata": metadata or {},
                # Named for the caller's benefit: a chunk that arrived here was
                # fetched by id, not ranked, and nothing downstream should treat
                # its presence as evidence of relevance.
                "matched_by": "invoice_id",
            }
        )
    chunks.sort(key=lambda c: (c.get("metadata") or {}).get("page") or 0)
    return chunks


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
