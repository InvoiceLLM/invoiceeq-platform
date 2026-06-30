import json
import logging
from datetime import datetime
import redis
from .celery_app import celery_app
from config import get_settings, Settings
from sqlmodel import Session, select
from database import engine
from models import Invoice
from agents.extraction_agent import run_extraction_agent


logger = logging.getLogger(__name__)

def _get_redis_sync() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

def _publish_sse_events(batch_id: str, payload: dict) -> None:
    if not batch_id:
        logger.warning("batch_id is None, skipping event publish")
        return

    event = f"invoice.update.{batch_id}"
    try:
        # publishes the event to the redis pubsub channel
        redis_client = _get_redis_sync()
        logger.info("publishing event %s with data %s", event, payload)
        redis_client.publish(event, json.dumps(payload))
    except Exception as e:
        logger.error("failed to publish event %s with data %s: %s", event, payload, e)
        return

def _run_ocr(file_path: str, settings: Settings) -> str:
    """
    Runs the OCR / PDF layout extraction process for a given file path.
    - In local dev (LLM_PROVIDER=ollama): extracts text using local pypdf.
    - In production (LLM_PROVIDER=azure): calls Azure Document Intelligence.
    """
    if settings.LLM_PROVIDER == "ollama":
        logger.info("Running local PDF text extraction (Ollama mode) using pypdf for file: %s", file_path)
        try:
            import pypdf
        except ImportError:
            raise ImportError(
                "The 'pypdf' package is required for local extraction. "
                "Please run: uv add pypdf"
            )

        try:
            reader = pypdf.PdfReader(file_path)
            extracted_text = ""
            for page in reader.pages:
                text_content = page.extract_text()
                if text_content:
                    extracted_text += text_content + "\n"
            return extracted_text.strip()
        except Exception as e:
            logger.error("Failed to extract local PDF text from %s: %s", file_path, e)
            raise e

    # Production: Azure Document Intelligence
    logger.info("Running Azure Document Intelligence OCR for file: %s", file_path)
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        raise ImportError(
            "Azure Document Intelligence SDK is required for Azure extraction. "
            "Please run: uv add azure-ai-documentintelligence azure-core"
        )

    if not settings.AZURE_DOC_INTEL_ENDPOINT or not settings.AZURE_DOC_INTEL_KEY:
        raise ValueError("Azure Document Intelligence credentials (endpoint or key) are missing in settings.")

    try:
        client = DocumentIntelligenceClient(
            endpoint=settings.AZURE_DOC_INTEL_ENDPOINT,
            credential=AzureKeyCredential(settings.AZURE_DOC_INTEL_KEY)
        )
        
        with open(file_path, "rb") as f:
            poller = client.begin_analyze_document(
                model_id="prebuilt-layout",
                analyze_request=f,
                content_type="application/octet-stream"
            )
        result = poller.result()
        return result.content or ""
    except Exception as e:
        logger.error("Azure Document Intelligence call failed for %s: %s", file_path, e)
        raise e

@celery_app.task(name="workers.tasks.process_invoice_task")
def process_invoice_task(batch_id: str, file_path: str, tenant_id: str) -> dict:
    """
    Asynchronous Celery task to process an uploaded invoice PDF:
    1. Runs OCR/Text extraction via _run_ocr.
    2. Sends progress updates to client via SSE.
    3. Triggers multi-modal extraction/verification (agent block placeholder).
    """
    settings = get_settings()
    
    # 1. Update status: processing OCR
    _publish_sse_events(batch_id, {"status": "PROCESSING_OCR", "message": "Extracting text from PDF invoice..."})
    
    try:
        # 2. Extract raw layout text
        _extracted_text = _run_ocr(file_path, settings)
        
        # 3. Update status: extracting structures (agent processing)
        _publish_sse_events(batch_id, {"status": "EXTRACTING_DATA", "message": "Extracting structured fields using LLM..."})
        
        # Test environment overrides triggered by keywords in file_path
        if "fail" in file_path.lower():
            raise Exception("Mock processing failure triggered by file name keyword.")
        
        # Run extraction agent
        agent_result = run_extraction_agent(file_path, _extracted_text, tenant_id)
        
        status = agent_result["status"]
        alerts = agent_result["alerts"]
        extracted_data = agent_result["extracted_data"] or {}
        
        # Update invoice record in the database
        with Session(engine) as session:
            statement = select(Invoice).where(Invoice.file_path == file_path)
            invoice = session.exec(statement).first()
            if invoice:
                invoice.vendor_name = extracted_data.get("vendor_name")
                invoice.grand_total = extracted_data.get("grand_total")
                invoice.invoice_number = extracted_data.get("invoice_number")
                
                # Parse date strings if present
                for date_field in ["invoice_date", "due_date"]:
                    date_val = extracted_data.get(date_field)
                    if date_val:
                        try:
                            # Truncate time if any or split by space/T
                            date_str = str(date_val).split("T")[0].split(" ")[0].strip()
                            setattr(invoice, date_field, datetime.strptime(date_str, "%Y-%m-%d").date())
                        except Exception as de:
                            logger.warning("Could not parse date %s for %s: %s", date_val, date_field, de)
                            
                invoice.tax_amount = extracted_data.get("tax_amount")
                invoice.po_number = extracted_data.get("po_number")
                invoice.status = status
                invoice.sa_alerts = alerts
                invoice.tags = extracted_data.get("tags", [])
                invoice.items = extracted_data.get("items", [])
                
                session.add(invoice)
                session.commit()
            
            # If successfully completed, run page-level RAG indexing
            if status == "COMPLETED":
                try:
                    _publish_sse_events(batch_id, {
                        "status": "INDEXING",
                        "message": "Generating page embeddings and indexing document chunks..."
                    })
                    from chroma_client import index_invoice_document
                    index_invoice_document(
                        invoice_id=str(invoice.id),
                        tenant_id=str(invoice.tenant_id),
                        vendor_name=invoice.vendor_name,
                        file_path=file_path
                    )
                except Exception as ie:
                    logger.error("RAG indexing failed for invoice %s: %s", invoice.id, ie)
            
            # Update SSE status to COMPLETED/AUDIT_REQUIRED
            _publish_sse_events(batch_id, {
                "status": status,
                "message": f"Processing finished with status: {status}",
                "invoice_id": str(invoice.id),
                "data": extracted_data,
                "alerts": alerts
            })
        
        return {
            "vendor_name": extracted_data.get("vendor_name"),
            "grand_total": extracted_data.get("grand_total"),
            "status": status,
            "alerts": alerts
        }

    except Exception as e:
        logger.error("Error processing invoice batch %s: %s", batch_id, e)
        # Update status: failed
        _publish_sse_events(batch_id, {"status": "FAILED", "message": str(e)})
        raise e


