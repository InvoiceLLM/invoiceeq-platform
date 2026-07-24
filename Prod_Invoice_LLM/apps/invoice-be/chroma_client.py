import os
import logging
import fitz
import chromadb
import threading
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
            logger.info("Initializing Chroma HttpClient at %s:%s", settings.CHROMA_HOST, settings.CHROMA_PORT)
            _chroma_client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT
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

def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Calculates embedding vectors for a list of texts (1024-dimensional)."""
    model = get_embedding_model()
    if model is None:
        import random
        return [[random.uniform(-0.1, 0.1) for _ in range(1024)] for _ in texts]
    with _embedding_lock:
        embeddings = model.encode(texts, convert_to_numpy=True)
    return embeddings.tolist()

def index_invoice_document(invoice_id: str, tenant_id: str, vendor_name: str | None, file_path: str):
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
        
    embeddings = get_embeddings(chunks)
    
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="invoice_chunks")
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadata_list
    )
    logger.info("Successfully indexed %d page chunks for invoice %s", len(chunks), invoice_id)

def delete_invoice_chunks(invoice_id: str) -> None:
    """
    Deletes all indexed vector chunks for a given invoice from the invoice_chunks collection.
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="invoice_chunks")
    collection.delete(where={"invoice_id": str(invoice_id)})

def query_invoice_chunks(tenant_id: str, query_text: str, limit: int = 5) -> list[dict]:
    """
    Query indexed invoice chunks, isolating results strictly by requesting tenant_id.
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="invoice_chunks")
    
    query_embeddings = get_embeddings([query_text])
    
    results = collection.query(
        query_embeddings=query_embeddings,
        where={"tenant_id": str(tenant_id)},
        n_results=limit
    )
    
    matched_chunks = []
    if results and results.get("documents") and len(results["documents"]) > 0:
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results.get("distances", [[]])[0]
        ids = results["ids"][0]
        
        for idx in range(len(documents)):
            matched_chunks.append({
                "id": ids[idx],
                "document": documents[idx],
                "metadata": metadatas[idx],
                "distance": distances[idx] if idx < len(distances) else None
            })
            
    return matched_chunks
