import logging
from datetime import datetime
from uuid import UUID
from sqlmodel import Session, select
from sqlalchemy import func

from database import engine
from models import Invoice, ExtractionTemplate
from queue_worker.handlers import _run_ocr, _publish_sse_events, _persist_processing_failure
from agents.outbound_extraction_agent import run_outbound_extraction_agent
from config import get_settings

logger = logging.getLogger(__name__)


def _get_outbound_global_rules(session: Session, tenant_id: str) -> list:
    """Feature 7.1: outbound rules are Global-only, no vendor/customer scoping
    -- every outbound invoice is the tenant's own single, consistent format,
    so there's no per-customer variability to justify per-customer rules."""
    stmt = select(ExtractionTemplate).where(
        ExtractionTemplate.tenant_id == UUID(tenant_id),
        ExtractionTemplate.vendor_name.is_(None),
        ExtractionTemplate.flow_direction == "OUTBOUND",
    )
    tpl = session.exec(stmt).first()
    if tpl and isinstance(tpl.rules, dict):
        # Feature 18: raw entries, same reasoning as handlers._get_template_rules
        # -- verify_node needs the structured objects, extract_node renders only
        # the prompt-relevant ones via the shared normalizer.
        return list(tpl.rules.get("constraints", []) or [])
    return []


def handle_process_outbound_invoice(batch_id: str, file_path: str, tenant_id: str) -> dict:
    """Queue-worker job for an outbound invoice (Feature 2.1, Task 2.1.3):
    tenant's own invoice being sent to a customer, not a vendor's invoice
    being received. Single extract->verify pass (no classify/dynamic_qa
    split, no two-stage vendor rule resolution -- see
    feature_2.1_vendor_flow_ingestion.md's v1 scope cut)."""
    settings = get_settings()

    _publish_sse_events(batch_id, {"status": "PROCESSING_OCR", "message": "Extracting text from outbound invoice PDF..."})

    try:
        ocr_result = _run_ocr(file_path, settings)
        if isinstance(ocr_result, dict):
            ocr_text = ocr_result["content"]
            coordinates = ocr_result.get("coordinates", [])
            field_confidence = ocr_result.get("field_confidence", {})
            source_document_json = ocr_result.get("source_document_json")
        else:
            ocr_text = ocr_result
            coordinates = []
            field_confidence = {}
            source_document_json = None

        _publish_sse_events(batch_id, {"status": "EXTRACTING_DATA", "message": "Extracting structured fields using LLM..."})

        with Session(engine) as session:
            global_constraints = _get_outbound_global_rules(session, tenant_id)
        rules = {"constraints": global_constraints} if global_constraints else None

        agent_result = run_outbound_extraction_agent(
            file_path, ocr_text, tenant_id, rules=rules, ocr_result=ocr_result,
        )
        status = agent_result["status"]
        alerts = agent_result["alerts"]
        extracted_data = agent_result["extracted_data"] or {}

        with Session(engine) as session:
            statement = select(Invoice).where(Invoice.file_path == file_path)
            invoice = session.exec(statement).first()
            if invoice:
                customer_name = extracted_data.get("customer_name")
                invoice_number = extracted_data.get("invoice_number")

                # duplicate_invoice_number (Feature 7.1): scoped per customer_name,
                # the AR mirror of inbound's per-vendor_name duplicate check.
                if customer_name and invoice_number:
                    dup_stmt = select(Invoice).where(
                        Invoice.tenant_id == invoice.tenant_id,
                        Invoice.id != invoice.id,
                        Invoice.flow_direction == "OUTBOUND",
                        func.lower(Invoice.invoice_number) == invoice_number.lower(),
                        func.lower(Invoice.customer_name) == customer_name.lower(),
                    )
                    dup_invoice = session.exec(dup_stmt).first()
                    if dup_invoice and dup_invoice.id:
                        dup_alert = {
                            "type": "duplicate_invoice_number",
                            "message": f"An outbound invoice with the same number ({invoice_number}) and customer ({customer_name}) already exists (ID: {dup_invoice.id}).",
                        }
                        if dup_alert not in alerts:
                            alerts = list(alerts)
                            alerts.append(dup_alert)
                        status = "NEEDS_REVIEW"

                invoice.customer_name = customer_name
                invoice.invoice_number = invoice_number

                for date_field in ["invoice_date", "due_date"]:
                    date_val = extracted_data.get(date_field)
                    if date_val:
                        try:
                            date_str = str(date_val).split("T")[0].split(" ")[0].strip()
                            setattr(invoice, date_field, datetime.strptime(date_str, "%Y-%m-%d").date())
                        except Exception as de:
                            logger.warning("Could not parse date %s for %s: %s", date_val, date_field, de)

                invoice.grand_total = extracted_data.get("grand_total")
                invoice.tax_amount = extracted_data.get("tax_amount")
                invoice.currency = extracted_data.get("currency")
                invoice.coordinates = coordinates
                invoice.field_confidence = field_confidence
                invoice.source_document_json = source_document_json
                invoice.status = status
                invoice.sa_alerts = alerts
                invoice.items = extracted_data.get("items", [])

                session.add(invoice)
                session.commit()

                # Feature 6.1 (Task 6.1.3): index on VERIFIED, mirroring inbound's
                # COMPLETED trigger, so outbound documents are searchable through
                # the same RAG path Chat already uses -- imported call, zero
                # changes to chroma_client.py itself.
                if status == "VERIFIED":
                    try:
                        from chroma_client import index_invoice_document
                        index_invoice_document(
                            invoice_id=str(invoice.id),
                            tenant_id=str(invoice.tenant_id),
                            vendor_name=invoice.customer_name,
                            file_path=file_path,
                        )
                    except Exception as ie:
                        logger.error("RAG indexing failed for outbound invoice %s: %s", invoice.id, ie)

                if status in ("VERIFIED", "NEEDS_REVIEW"):
                    try:
                        from services.staff_notify import notify_processing_complete
                        notify_processing_complete(session, invoice)
                    except Exception as ne:
                        logger.error("Staff process-complete notify failed for outbound %s: %s", invoice.id, ne)

            _publish_sse_events(batch_id, {
                "status": status,
                "message": f"Outbound processing finished with status: {status}",
                "invoice_id": str(invoice.id) if invoice else None,
                "data": extracted_data,
                "alerts": alerts,
            })

        return {
            "customer_name": extracted_data.get("customer_name"),
            "grand_total": extracted_data.get("grand_total"),
            "status": status,
            "alerts": alerts,
        }

    except Exception as e:
        logger.error("Error processing outbound invoice batch %s: %s", batch_id, e)
        # Gap 84: persist FAILED before re-raising -- see the inbound handler's
        # note. Outbound is the worse of the two cases: it never persists any
        # intermediate status at all, so without this the row stays on its
        # upload-time UPLOADED, which is also exactly what a Gap 81 worker-down
        # invoice looks like. Writing FAILED is what makes the two
        # distinguishable from the database alone instead of only from the
        # worker log.
        _persist_processing_failure(file_path, e)
        _publish_sse_events(batch_id, {"status": "FAILED", "message": str(e)})
        raise e
