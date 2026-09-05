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
    being received. Gap 283 (2026-08-21): this now runs the SAME graph inbound
    does (classify -> dynamic_qa -> extract -> verify, with the bounded retry
    edge), via `run_outbound_extraction_agent`'s `flow_direction="OUTBOUND"` --
    the Feature 2.1 "v1 scope cut" that skipped classify/dynamic_qa is gone.
    Rule resolution is still single-stage Global-only (no two-stage vendor
    resolution), which is a rules concern, not a graph-shape one."""
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

                # Feature 17 (task 17.6): a builder-created invoice checks what
                # was actually printed against what the builder intended to
                # print. `builder_intent` is NULL for every uploaded invoice, so
                # this is inert on the upload path.
                #
                # Deterministic arithmetic, not an LLM judgement (CONVENTIONS
                # hard rule 3): the model's only job here was to read the PDF,
                # exactly as for an upload. A disagreement means the render is
                # wrong -- a value painted into the wrong span, a figure that
                # did not fit -- and the invoice lands NEEDS_REVIEW on the
                # existing outbound review screen naming the field, rather than
                # being sent to a customer on a number nobody checked.
                if invoice.builder_intent:
                    from utils.verification_tools import verify_builder_readback

                    mismatches = verify_builder_readback(invoice.builder_intent, extracted_data)
                    if mismatches:
                        named = ", ".join(m["field"] for m in mismatches)
                        alerts = list(alerts)
                        alerts.append({
                            "type": "builder_render_mismatch",
                            "message": (
                                "The generated PDF did not read back as built. "
                                f"Fields that disagree: {named}."
                            ),
                            "fields": mismatches,
                            "severity": "error",
                        })
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
                # Gap 293: same shared Invoice.discount_percent/discount_amount
                # columns inbound already writes (handlers.py) — round_off has
                # no DB column even for inbound, it's verify_totals_math-only.
                invoice.discount_percent = extracted_data.get("discount_percent")
                invoice.discount_amount = extracted_data.get("discount_amount")
                invoice.coordinates = coordinates
                invoice.field_confidence = field_confidence
                invoice.source_document_json = source_document_json
                invoice.status = status
                invoice.sa_alerts = alerts
                invoice.items = extracted_data.get("items", [])
                # Post-Gap-283 correction: `OutboundInvoiceExtractionSchema` now
                # carries `taxes[]` (needed so Gap 69's component-aware
                # tax-faithfulness fallback can engage on a CGST+SGST split).
                # `Invoice.taxes` is the same shared JSON column inbound already
                # writes, so persist the components rather than verifying against
                # them and then dropping them on the floor.
                invoice.taxes = extracted_data.get("taxes") or []
                # BE Gap 467: the rest of what `OutboundInvoiceExtractionSchema`
                # now reads. Every one of these is a column this table already
                # had and only the INBOUND handler ever wrote — the outbound
                # schema was narrower than the row it persists to, so an
                # outbound invoice's own vendor name, PO number, addresses,
                # references, payment instructions, tax IDs and compliance
                # identifiers were dropped even when they were printed on the
                # page. Written here with the same shape and the same
                # `get(..., default)` behaviour as the inbound block in
                # `queue_worker/handlers.py` (`invoice.tax_ids = ...` and the
                # lines around it), so one field cannot mean two things
                # depending on which door the document came through.
                invoice.vendor_name = extracted_data.get("vendor_name")
                invoice.po_number = extracted_data.get("po_number")
                # `or invoice.notes`, unlike every other line here: the BUILDER
                # already stamped the notes block it printed (routers/
                # outbound_invoices.py::_store_and_enqueue_outbound), and a
                # model that simply did not return the free-text block is not
                # evidence the invoice has none. On an upload the column is NULL
                # at this point, so this is a plain write there.
                invoice.notes = extracted_data.get("notes") or invoice.notes
                invoice.tax_ids = extracted_data.get("tax_ids", [])
                invoice.payment_instructions = extracted_data.get("payment_instructions", [])
                invoice.references = extracted_data.get("references", [])
                invoice.addresses = extracted_data.get("addresses", [])
                invoice.compliance_metadata = extracted_data.get("compliance_metadata", [])

                session.add(invoice)
                session.commit()

                # Feature 6.1 (Task 6.1.3): index outbound documents so they're
                # searchable through the same RAG path Chat already uses.
                # Gap 243: this used to be gated on `status == "VERIFIED"`, the
                # outbound twin of Gap 240's inbound `COMPLETED` gate -- a
                # NEEDS_REVIEW outbound invoice was never indexed, permanently,
                # since routers/outbound_audit.py's resolve path doesn't change
                # `status` at all. Now shares inbound's `should_index_status()`.
                from chroma_client import index_invoice_document, should_index_status
                if should_index_status(status):
                    try:
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
