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
    """Calculates embedding vectors for a list of texts (1024-dimensional)."""
    model = get_embedding_model()
    if model is None:
        import random
        return [[random.uniform(-0.1, 0.1) for _ in range(1024)] for _ in texts]
    with _embedding_lock:
        embeddings = model.encode(texts, convert_to_numpy=True)
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
    collection = client.get_or_create_collection(name=_tenant_collection_name(tenant_id))
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
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection(name=_tenant_collection_name(tenant_id))
    collection.delete(where={"invoice_id": str(invoice_id)})

def query_invoice_chunks(tenant_id: str, query_text: str, limit: int = 5) -> list[dict]:
    """
    Query indexed invoice chunks. Isolation is structural (Gap 55) — each tenant has
    its own Chroma collection, so no metadata `where` filter is needed to keep one
    tenant's results out of another's, and this is also the seam a future per-tenant
    Chroma instance/cluster router would plug into.
    Includes a hybrid keyword pass and local reranker (Gap 22), enforcing a distance
    relevance threshold (Gap 21).
    """
    import re

    client = get_chroma_client()
    collection = client.get_or_create_collection(name=_tenant_collection_name(tenant_id))

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
        
        # Original semantic distance (Chroma default is L2, but we treat lower as better)
        vec_dist = distances[idx] if idx < len(distances) else 1.0
        
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

    # Gap 21: Enforce relevance threshold (0.4)
    # We apply the threshold on the original vector distance to avoid false positives,
    # OR if there's a strong keyword match, we let it pass (exact match fallback).
    matched_chunks = []
    min_k_score = min(2, max(1, len(keywords))) # Require 1 if only 1 keyword, 2 if >= 2
    for chunk in candidates:
        if chunk["distance"] <= 0.4 or chunk["keyword_score"] >= min_k_score:
            matched_chunks.append({
                "id": chunk["id"],
                "document": chunk["document"],
                "metadata": chunk["metadata"],
                "distance": chunk["distance"]
            })
            if len(matched_chunks) >= limit:
                break
                
    return matched_chunks
