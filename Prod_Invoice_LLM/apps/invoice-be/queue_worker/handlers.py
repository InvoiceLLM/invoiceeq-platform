import json
import logging
import time
from datetime import datetime
from typing import Optional
import redis
from config import get_settings, Settings
from sqlmodel import Session, select
from database import engine
from uuid import UUID, uuid4
from azure.storage.queue import QueueClient
from models import Invoice, ExtractionTemplate, TenantConnection
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

import io
from services.storage import download_pdf_from_storage


def _serialize_di_field(field) -> dict | None:
    """Gap 178: turn one Azure DocumentField into plain JSON (no polygons)."""
    if field is None:
        return None

    out: dict = {}
    field_type = getattr(field, "type", None) or getattr(field, "value_type", None)
    if field_type:
        out["type"] = field_type
    confidence = getattr(field, "confidence", None)
    if confidence is not None:
        out["confidence"] = confidence

    if getattr(field, "value_string", None) is not None:
        out["value"] = field.value_string
    elif getattr(field, "value_number", None) is not None:
        out["value"] = field.value_number
    elif getattr(field, "value_integer", None) is not None:
        out["value"] = field.value_integer
    elif getattr(field, "value_date", None) is not None:
        d = field.value_date
        out["value"] = d.isoformat() if hasattr(d, "isoformat") else str(d)
    elif getattr(field, "value_time", None) is not None:
        t = field.value_time
        out["value"] = t.isoformat() if hasattr(t, "isoformat") else str(t)
    elif getattr(field, "value_phone_number", None) is not None:
        out["value"] = field.value_phone_number
    elif getattr(field, "value_country_region", None) is not None:
        out["value"] = field.value_country_region
    elif getattr(field, "value_currency", None) is not None:
        cv = field.value_currency
        if isinstance(cv, dict):
            out["value"] = cv
        else:
            out["value"] = {
                "amount": getattr(cv, "amount", None),
                "currency_code": getattr(cv, "currency_code", None)
                or getattr(cv, "currencyCode", None),
            }
    elif getattr(field, "value_address", None) is not None:
        addr = field.value_address
        if isinstance(addr, dict):
            out["value"] = addr
        else:
            out["value"] = {
                k: getattr(addr, k, None)
                for k in (
                    "house_number",
                    "po_box",
                    "road",
                    "city",
                    "state",
                    "postal_code",
                    "country_region",
                    "street_address",
                )
                if getattr(addr, k, None) is not None
            }
    elif getattr(field, "value_array", None) is not None:
        out["value"] = [_serialize_di_field(item) for item in field.value_array]
    elif getattr(field, "value_object", None) is not None:
        obj = field.value_object or {}
        out["value"] = {
            key: _serialize_di_field(sub)
            for key, sub in obj.items()
        }
    elif getattr(field, "content", None) is not None:
        out["value"] = field.content

    return out


def _serialize_di_document_fields(fields) -> dict:
    """Gap 178: DI prebuilt-invoice fields → JSON-safe dict for source_document_json."""
    if not fields:
        return {}
    serialized = {}
    for name, field in fields.items():
        try:
            serialized[name] = _serialize_di_field(field)
        except Exception as e:
            logger.warning("Failed to serialize Doc Intelligence field %s: %s", name, e)
            content = getattr(field, "content", None)
            if content is not None:
                serialized[name] = {"value": content}
    return serialized


def _run_ocr(file_path: str, settings: Settings):
    """
    Runs the OCR / PDF layout extraction process for a given file path.
    - In local dev (LLM_PROVIDER=ollama): extracts text using local pypdf.
    - In production (LLM_PROVIDER=azure): calls Azure Document Intelligence.
    Azure path returns a dict with content, coordinates, field_confidence,
    tax_details_sum, and source_document_json (Gap 178).
    """
    # Download file bytes from storage (Azure Blob or Local Filesystem)
    try:
        pdf_bytes = download_pdf_from_storage(file_path)
    except Exception as e:
        logger.error("Failed to load PDF bytes from storage for %s: %s", file_path, e)
        raise e

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
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
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
        from azure.core.exceptions import ServiceRequestError, ServiceResponseError, HttpResponseError
    except ImportError:
        raise ImportError(
            "Azure Document Intelligence SDK is required for Azure extraction. "
            "Please run: uv add azure-ai-documentintelligence azure-core"
        )

    from utils.doc_intel_client import get_doc_intel_pool
    pool = get_doc_intel_pool(settings)

    # ---------------------------------------------------------------------------
    # Azure Document Intelligence OCR Retry & Failover Loop
    # ---------------------------------------------------------------------------
    # Retries transient connection drops, timeouts, and rate-limits (HTTP 429/503/504)
    # with exponential backoff (1s, 2s). On every attempt (including retries),
    # next_endpoint_key() automatically rotates to the NEXT Azure resource in our
    # 3-resource pool, ensuring failover to a healthy endpoint if one is busy.
    # ---------------------------------------------------------------------------
    MAX_OCR_ATTEMPTS = 3
    last_exc = None
    result = None

    for attempt in range(MAX_OCR_ATTEMPTS):
        endpoint, key = pool.next_endpoint_key()  # rotates resource on every attempt
        try:
            client = DocumentIntelligenceClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(key)
            )
            
            poller = client.begin_analyze_document(
                model_id="prebuilt-invoice",
                body=pdf_bytes,
                content_type="application/octet-stream"
            )
            result = poller.result()
            break
        except (ServiceRequestError, ServiceResponseError) as e:
            last_exc = e
            logger.warning(
                "Doc Intelligence connection error (attempt %d/%d) on %s: %s",
                attempt + 1, MAX_OCR_ATTEMPTS, endpoint, e
            )
        except HttpResponseError as e:
            if e.status_code not in (429, 503, 504):
                raise  # Permanent error (e.g. 400 Bad Request), don't retry
            last_exc = e
            logger.warning(
                "Doc Intelligence transient HTTP %s (attempt %d/%d) on %s",
                e.status_code, attempt + 1, MAX_OCR_ATTEMPTS, endpoint
            )
        except Exception as e:
            last_exc = e
            logger.warning(
                "Doc Intelligence error (attempt %d/%d) on %s: %s",
                attempt + 1, MAX_OCR_ATTEMPTS, endpoint, e
            )
            
        if attempt < MAX_OCR_ATTEMPTS - 1:
            time.sleep(2 ** attempt)
    else:
        logger.error("Azure Document Intelligence call failed after %d attempts for %s: %s", MAX_OCR_ATTEMPTS, file_path, last_exc)
        raise last_exc

    coordinates_list = []
    confidence_dict = {}
    tax_details_sum = None
    source_document_json = None

    if hasattr(result, "documents") and result.documents:
        doc = result.documents[0]
        if hasattr(doc, "fields") and doc.fields:
            source_document_json = _serialize_di_document_fields(doc.fields)
            for field_name, field in doc.fields.items():
                if hasattr(field, "confidence") and field.confidence is not None:
                    confidence_dict[field_name] = field.confidence

                if hasattr(field, "bounding_regions") and field.bounding_regions:
                    for region in field.bounding_regions:
                        if hasattr(region, "polygon") and region.polygon:
                            poly = region.polygon
                            if len(poly) >= 8:
                                xs = [poly[i] for i in range(0, len(poly), 2)]
                                ys = [poly[i] for i in range(1, len(poly), 2)]
                                x_min, x_max = min(xs), max(xs)
                                y_min, y_max = min(ys), max(ys)
                                coordinates_list.append({
                                    "field": field_name,
                                    "x": x_min,
                                    "y": y_min,
                                    "width": x_max - x_min,
                                    "height": y_max - y_min,
                                    "page": region.page_number or 1
                                })

            # Doc Intelligence anchor: TaxDetails is a per-tax-line breakdown (e.g.
            # separate CGST/SGST entries) that Doc Intelligence itself isolates
            # deterministically, independent of the LLM extraction step. Sum it here
            # so extract_node can backfill a missing tax_amount without asking the
            # LLM to remember to add up a multi-row tax split. This is a *fallback*
            # only (used solely when the LLM's own tax_amount comes back null) —
            # extract_node never lets this override a value the LLM did transcribe,
            # and every existing faithfulness/arithmetic check still runs against
            # the final value either way, so this doesn't bypass Gap 31/33/36/40/46.
            tax_details_field = doc.fields.get("TaxDetails")
            if tax_details_field is not None and getattr(tax_details_field, "value_array", None):
                try:
                    amounts = []
                    for entry in tax_details_field.value_array:
                        entry_obj = getattr(entry, "value_object", None) or {}
                        amount_field = entry_obj.get("Amount")
                        if amount_field is None:
                            continue
                        currency_val = getattr(amount_field, "value_currency", None)
                        # CurrencyValue may come back as a dict or an object depending
                        # on SDK version — handle both rather than assuming one shape.
                        amount_num = None
                        if isinstance(currency_val, dict):
                            amount_num = currency_val.get("amount")
                        elif currency_val is not None:
                            amount_num = getattr(currency_val, "amount", None)
                        if amount_num is not None:
                            amounts.append(float(amount_num))
                    if amounts:
                        tax_details_sum = sum(amounts)
                except Exception as e:
                    logger.warning("Failed to sum Doc Intelligence TaxDetails for %s: %s", file_path, e)

    return {
        "content": result.content or "",
        "coordinates": coordinates_list,
        "field_confidence": confidence_dict,
        "tax_details_sum": tax_details_sum,
        "source_document_json": source_document_json,
    }



def _get_template_rules(session: Session, tenant_id: str, vendor_name: str | None) -> list:
    """Return the constraints list for a template scope, or [] if none exists.

    vendor_name=None resolves the tenant's single Global template (Task 10.8).
    """
    stmt = select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == UUID(tenant_id))
    if vendor_name is None:
        stmt = stmt.where(ExtractionTemplate.vendor_name.is_(None))
    else:
        stmt = stmt.where(ExtractionTemplate.vendor_name == vendor_name)
    tpl = session.exec(stmt).first()
    if tpl and isinstance(tpl.rules, dict):
        return tpl.rules.get("constraints", []) or []
    return []


def _merge_constraints(global_constraints: list, vendor_constraints: list) -> list:
    """Merge Global + vendor constraints. Vendor rules are appended last (they win on
    conflict); exact duplicates are dropped."""
    merged = list(global_constraints)
    for c in vendor_constraints:
        if c not in merged:
            merged.append(c)
    return merged


def _enqueue_process_invoice(batch_id: str, file_path: str, tenant_id: str) -> bool:
    """Put a single invoice back on the extraction queue (used to fan out re-audits)."""
    settings = get_settings()
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        logger.warning("AZURE_STORAGE_CONNECTION_STRING missing; cannot enqueue re-audit item.")
        return False
    try:
        queue_client = QueueClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
        )
        queue_client.send_message(json.dumps({
            "task": "process_invoice",
            "kwargs": {"batch_id": batch_id, "file_path": file_path, "tenant_id": tenant_id},
        }))
        return True
    except Exception as e:
        logger.error("Failed to enqueue re-audit process_invoice message: %s", e)
        return False


def handle_import_connector_file(
    provider: str,
    file_id: str,
    tenant_id: str,
    direction: str = "inbound",
    db_session: Optional[Session] = None,
) -> dict:
    """Task 9.4 / Gap 98 — Queue-worker job for connector file imports.

    Flow (inbound / AP):
      1. Download file bytes from provider (real Drive API call once a real
         TenantConnection + company OAuth app exist for this provider;
         stub bytes otherwise -- see Gap 98 in be_features_tracker.md).
      2. Upload to Azure Blob Storage or Local Storage under the tenant's prefix.
      3. Enqueue a ``process_invoice`` task to feed the extraction pipeline.

    Flow (outbound / AR):
      1. Same download step.
      2. Upload to Azure Blob Storage or Local Storage under the tenant's prefix.
      3. No extraction queued — file is stored for AR record-keeping only.

    ``db_session`` is injectable for tests; production (queue-worker) calls
    leave it as None and get a real, short-lived ``Session(engine)``.
    """
    import os
    from services.storage import LOCAL_STORAGE_DIR
    from utils.connector_oauth import has_real_credentials, get_valid_access_token
    from utils.connector_files import download_google_drive_file, download_salesforce_file

    settings = get_settings()
    batch_id = str(uuid4())

    owns_session = db_session is None
    if owns_session:
        db_session = Session(engine)

    file_bytes = None
    try:
        connection = db_session.exec(
            select(TenantConnection).where(
                TenantConnection.tenant_id == UUID(tenant_id),
                TenantConnection.provider == provider,
            )
        ).first()

        # Gap 180: an *active* tenant connection must never fall through to the
        # stub PDF. That stub is only for local/dev tests with no connection;
        # in Azure it produced Doc Intelligence InvalidContent while the FE
        # still said "Import request queued!".
        if connection and connection.status == "active":
            if not has_real_credentials(provider, settings):
                raise RuntimeError(
                    f"Connector '{provider}' is active but platform OAuth credentials "
                    "are not configured on this worker (GOOGLE_CLIENT_ID / "
                    "SALESFORCE_CLIENT_ID). Cannot download the real file."
                )
            access_token = get_valid_access_token(connection, settings, db_session)
            if provider == "google_drive":
                file_bytes = download_google_drive_file(access_token, file_id)
            elif provider == "salesforce" and connection.instance_url:
                file_bytes = download_salesforce_file(access_token, connection.instance_url, file_id)
            if not file_bytes:
                raise RuntimeError(
                    f"Download from '{provider}' returned empty content for file_id={file_id}."
                )
            logger.info(
                "Downloaded real file from %s: file_id=%s size=%d bytes",
                provider, file_id, len(file_bytes),
            )
    finally:
        if owns_session:
            db_session.close()

    if file_bytes is None:
        # No active connection for this tenant/provider — simulated content so
        # local/dev tests without a registered connection still work.
        file_bytes = (
            b"%PDF-1.4 stub content for connector import "
            + f"provider={provider} file_id={file_id}".encode()
        )
    file_name = f"connector_{provider}_{file_id}.pdf"
    direction_prefix = "outbound" if direction == "outbound" else "inbound"
    blob_path = f"tenants/{tenant_id}/{direction_prefix}/{batch_id}/{file_name}"

    uploaded_path = None
    container_name = "invoices"

    if settings.AZURE_STORAGE_CONNECTION_STRING and "your_azure_storage" not in settings.AZURE_STORAGE_CONNECTION_STRING:
        try:
            from azure.storage.blob import BlobServiceClient
            blob_service = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
            container_client = blob_service.get_container_client(container_name)
            try:
                container_client.create_container()
            except Exception:
                pass
                
            blob_client = blob_service.get_blob_client(container=container_name, blob=blob_path)
            blob_client.upload_blob(file_bytes, overwrite=True)
            uploaded_path = f"azure://{container_name}/{blob_path}"
            logger.info(
                "Connector import uploaded to Azure: provider=%s file_id=%s direction=%s path=%s",
                provider, file_id, direction, uploaded_path,
            )
        except Exception as e:
            logger.warning("Connector import blob upload to Azure failed, falling back to local: %s", e)

    if not uploaded_path:
        local_path = os.path.join(LOCAL_STORAGE_DIR, tenant_id, direction_prefix, batch_id, file_name)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        logger.info("Writing connector PDF file locally for offline fallback: %s", local_path)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        uploaded_path = local_path

    # Gap 179: inbound connector import used to enqueue process_invoice without
    # creating an Invoice row. handle_process_invoice only updates when
    # Invoice.file_path matches — so extraction ran (or was queued) with nothing
    # visible in Ingestion/Audit. Mirror the normal upload path: persist first.
    if direction == "inbound":
        invoice_id = uuid4()
        batch_uuid = UUID(batch_id)
        tenant_uuid = UUID(tenant_id)

        def _persist_and_enqueue(session: Session) -> bool:
            invoice = Invoice(
                id=invoice_id,
                tenant_id=tenant_uuid,
                batch_id=batch_uuid,
                file_path=uploaded_path,
                status="PROCESSING",
                tags=["connector", provider],
                flow_direction="INBOUND",
            )
            session.add(invoice)
            session.commit()

            enqueued = _enqueue_process_invoice(batch_id, uploaded_path, tenant_id)
            if enqueued:
                invoice.last_enqueued_at = datetime.utcnow()
                invoice.processing_attempts = 1
                session.add(invoice)
                session.commit()
            else:
                logger.error(
                    "Connector inbound import stored invoice %s but failed to enqueue extraction "
                    "(queue unavailable). Row left at PROCESSING for reconciliation.",
                    invoice_id,
                )
            return enqueued

        if owns_session or db_session is None:
            with Session(engine) as session:
                _persist_and_enqueue(session)
        else:
            # Tests inject an in-memory session — write the Invoice there so
            # assertions can see it (Session(engine) would hit a different DB).
            _persist_and_enqueue(db_session)

        logger.info(
            "Connector inbound import queued for extraction: batch_id=%s invoice_id=%s",
            batch_id, invoice_id,
        )
        return {
            "success": True,
            "batch_id": batch_id,
            "invoice_id": str(invoice_id),
            "blob_path": uploaded_path,
            "direction": direction,
        }

    logger.info(
        "Connector outbound import stored (no extraction): path=%s", uploaded_path
    )

    return {
        "success": True,
        "batch_id": batch_id,
        "blob_path": uploaded_path,
        "direction": direction,
    }




def handle_process_invoice(batch_id: str, file_path: str, tenant_id: str) -> dict:
    """
    Queue-worker job to process an uploaded invoice PDF:
    1. Runs OCR/Text extraction via _run_ocr.
    2. Sends progress updates to client via SSE.
    3. Triggers multi-modal extraction/verification (agent block placeholder).
    """
    settings = get_settings()

    # Gap 2: real per-stage log lines for the FE terminal feed, replacing the
    # 4 coarse SSE stages as the only visibility into what's happening.
    with Session(engine) as _lookup_session:
        _invoice_id_for_log = _lookup_session.exec(
            select(Invoice.id).where(Invoice.file_path == file_path)
        ).first()

    def on_log(message: str) -> None:
        _publish_sse_events(batch_id, {
            "type": "log_line",
            "invoice_id": str(_invoice_id_for_log) if _invoice_id_for_log else None,
            "message": message,
            "level": "info",
        })

    # 1. Update status: processing OCR
    _publish_sse_events(batch_id, {"status": "PROCESSING_OCR", "message": "Extracting text from PDF invoice..."})
    on_log("Starting OCR (Azure Document Intelligence)...")

    try:
        # 2. Extract raw layout text and metadata
        ocr_result = _run_ocr(file_path, settings)
        on_log("OCR complete.")
        if isinstance(ocr_result, dict):
            _extracted_text = ocr_result["content"]
            coordinates = ocr_result.get("coordinates", [])
            field_confidence = ocr_result.get("field_confidence", {})
            source_document_json = ocr_result.get("source_document_json")
        else:
            _extracted_text = ocr_result
            coordinates = []
            field_confidence = {}
            source_document_json = None
        
        # 3. Update status: extracting structures (agent processing)
        _publish_sse_events(batch_id, {"status": "EXTRACTING_DATA", "message": "Extracting structured fields using LLM..."})
        
        # Test environment overrides triggered by keywords in file_path

        if "fail" in file_path.lower():
            raise Exception("Mock processing failure triggered by file name keyword.")
        
        # ── Two-stage rule resolution (Task 10.8) ──────────────────────────────
        # Stage 1: apply the tenant's Global template (vendor-agnostic rules) on the
        # first pass, before we know the vendor.
        with Session(engine) as session:
            global_constraints = _get_template_rules(session, tenant_id, None)

        first_pass_rules = {"constraints": global_constraints} if global_constraints else None
        agent_result = run_extraction_agent(
            file_path, _extracted_text, tenant_id, rules=first_pass_rules, ocr_result=ocr_result, on_log=on_log
        )
        status = agent_result["status"]
        alerts = agent_result["alerts"]
        extracted_data = agent_result["extracted_data"] or {}

        # Stage 2: now that the vendor is known, merge Global + vendor-specific
        # constraints (vendor wins on conflict) and re-run if a vendor template exists.
        vendor_name = extracted_data.get("vendor_name")
        if vendor_name:
            with Session(engine) as session:
                vendor_constraints = _get_template_rules(session, tenant_id, vendor_name)
            if vendor_constraints:
                merged = _merge_constraints(global_constraints, vendor_constraints)
                logger.info(
                    "Applying merged Global+vendor rules for vendor %s (%d constraints). Re-running extraction.",
                    vendor_name, len(merged)
                )
                on_log(f"Re-running extraction with {vendor_name}'s trained rules...")
                agent_result = run_extraction_agent(
                    file_path, _extracted_text, tenant_id, rules={"constraints": merged}, ocr_result=ocr_result, on_log=on_log
                )
                status = agent_result["status"]
                alerts = agent_result["alerts"]
                extracted_data = agent_result["extracted_data"] or {}

        
        # Update invoice record in the database
        with Session(engine) as session:
            statement = select(Invoice).where(Invoice.file_path == file_path)
            invoice = session.exec(statement).first()
            if invoice:
                vendor_name = extracted_data.get("vendor_name")
                invoice_number = extracted_data.get("invoice_number")
                
                # Layer 2 Duplicate Detection
                if vendor_name and invoice_number:
                    from sqlalchemy import func
                    dup_stmt = select(Invoice).where(
                        Invoice.tenant_id == invoice.tenant_id,
                        Invoice.id != invoice.id,
                        func.lower(Invoice.invoice_number) == invoice_number.lower(),
                        func.lower(Invoice.vendor_name) == vendor_name.lower()
                    )
                    dup_invoice = session.exec(dup_stmt).first()
                    if dup_invoice and dup_invoice.id:
                        dup_alert = {
                            "type": "duplicate_invoice",
                            "message": f"An invoice with the same number ({invoice_number}) and vendor ({vendor_name}) already exists (ID: {dup_invoice.id})."
                        }
                        if dup_alert not in alerts:
                            alerts = list(alerts)
                            alerts.append(dup_alert)
                        status = "AUDIT_REQUIRED"

                invoice.vendor_name = vendor_name
                invoice.grand_total = extracted_data.get("grand_total")
                invoice.invoice_number = invoice_number

                
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
                invoice.coordinates = coordinates
                invoice.field_confidence = field_confidence
                invoice.source_document_json = source_document_json
                invoice.currency = extracted_data.get("currency")
                invoice.discount_percent = extracted_data.get("discount_percent")
                invoice.discount_amount = extracted_data.get("discount_amount")
                invoice.taxes = extracted_data.get("taxes", [])
                invoice.discounts = extracted_data.get("discounts", [])
                invoice.deductions = extracted_data.get("deductions", [])
                invoice.tax_ids = extracted_data.get("tax_ids", [])
                invoice.payment_instructions = extracted_data.get("payment_instructions", [])
                invoice.references = extracted_data.get("references", [])
                invoice.addresses = extracted_data.get("addresses", [])
                invoice.compliance_metadata = extracted_data.get("compliance_metadata", [])
                invoice.status = status
                invoice.completed_at = datetime.utcnow()
                invoice.sa_alerts = alerts
                invoice.tags = extracted_data.get("tags", [])
                invoice.items = extracted_data.get("items", [])
                
                session.add(invoice)
                session.commit()

                # Feature 15 (Task 15.4): fire right after the commit that
                # actually changed the status -- never before, so a webhook
                # is never sent for a status the DB doesn't durably reflect yet.
                if status in ("COMPLETED", "AUDIT_REQUIRED"):
                    try:
                        from services.webhooks import dispatch_webhook_event
                        event_type = "invoice.completed" if status == "COMPLETED" else "invoice.audit_required"
                        dispatch_webhook_event(session, invoice.tenant_id, event_type, {
                            "invoice_id": str(invoice.id),
                            "status": status,
                            "vendor_name": invoice.vendor_name,
                            "grand_total": invoice.grand_total,
                        })
                    except Exception as we:
                        logger.error("Webhook dispatch failed for invoice %s: %s", invoice.id, we)

                    try:
                        from services.staff_notify import notify_processing_complete
                        notify_processing_complete(session, invoice)
                    except Exception as ne:
                        logger.error("Staff process-complete notify failed for %s: %s", invoice.id, ne)



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
                        file_path=file_path,
                        on_log=on_log,
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
        # Gap 84: persist FAILED before re-raising. This block used to publish
        # to the ephemeral SSE channel only, so a permanent failure was visible
        # solely to a browser that happened to have the stream open at that
        # instant -- every REST poll of GET /invoices/status/{id} kept returning
        # the upload-time PROCESSING forever, on a row nothing would ever touch
        # again.
        _persist_processing_failure(file_path, e)
        _publish_sse_events(batch_id, {"status": "FAILED", "message": str(e)})
        raise e


def _persist_processing_failure(file_path: str, error: Exception) -> None:
    """Write FAILED onto the invoice row for a processing exception (Gap 84).

    Wrapped in its own try/except on purpose: if recording the failure itself
    fails (DB down, row missing), that must not replace the original exception
    the caller is about to re-raise -- losing the real cause to a bookkeeping
    error would make this strictly harder to debug than the bug it fixes.
    """
    try:
        from services.invoice_reconciliation import mark_invoice_failed

        with Session(engine) as session:
            invoice = session.exec(select(Invoice).where(Invoice.file_path == file_path)).first()
            if invoice is None:
                logger.error("Could not persist FAILED status: no invoice row for %s", file_path)
                return
            mark_invoice_failed(session, invoice, reason=str(error))
    except Exception as persist_error:
        logger.error(
            "Could not persist FAILED status for %s: %s (original error preserved)",
            file_path, persist_error,
        )


def handle_reaudit_templates(tenant_id: str, vendor_name: str = None) -> dict:
    """Re-audit a tenant's invoices after trainer rules were committed/rolled back (Task 10.7).

    Scope of the re-audit:
      - vendor_name=None  -> Global change: re-audit invoices across all vendors.
      - vendor_name set   -> re-audit only that vendor's invoices.

    Only invoices that a human hasn't finalized are touched (statuses COMPLETED and
    AUDIT_REQUIRED). PAID / REJECTED / PROCESSING / DUPLICATE are left alone so we never
    overturn an auditor's decision or fight an in-flight job.

    Rather than reprocessing every invoice inline (which could exceed the queue message's
    visibility timeout), each target is re-enqueued as its own ``process_invoice`` message.
    Those re-runs pick up the freshly committed rules via the two-stage resolution above.
    """
    REAUDIT_STATUSES = ("COMPLETED", "AUDIT_REQUIRED")
    REAUDIT_LIMIT = 500  # safety cap so a Global re-audit can't flood the queue unbounded

    with Session(engine) as session:
        stmt = select(Invoice).where(
            Invoice.tenant_id == UUID(tenant_id),
            Invoice.status.in_(REAUDIT_STATUSES),
        )
        if vendor_name:
            stmt = stmt.where(Invoice.vendor_name == vendor_name)
        stmt = stmt.order_by(Invoice.created_at.desc()).limit(REAUDIT_LIMIT)
        targets = [
            (str(inv.id), inv.file_path, str(inv.batch_id) if inv.batch_id else None)
            for inv in session.exec(stmt).all()
        ]

    logger.info(
        "Re-audit requested for tenant %s (vendor=%s): %d invoice(s) to reprocess.",
        tenant_id, vendor_name, len(targets)
    )

    enqueued = 0
    for _invoice_id, file_path, batch_id in targets:
        if _enqueue_process_invoice(batch_id or str(uuid4()), file_path, tenant_id):
            enqueued += 1

    return {
        "tenant_id": tenant_id,
        "vendor_name": vendor_name,
        "enqueued": enqueued,
        "total": len(targets),
    }


def handle_deliver_webhook(
    tenant_id: str,
    subscription_id: str,
    event_type: str,
    payload: dict,
    db_session: Optional[Session] = None,
) -> dict:
    """Gap 194 — queue-worker job for one outbound webhook delivery.

    ``services.webhooks.dispatch_webhook_event`` used to make the subscriber
    HTTP call inline on whatever thread had just committed the invoice (this
    module's own ``handle_process_invoice``, routers/audit.py,
    routers/outbound_invoices.py, services/outbound_overdue.py). With a 5s
    timeout, 3 attempts and 1s/2s backoff, one slow subscriber added up to
    ~19s to the operation that triggered it — per subscription. That work
    lives here now: the dispatcher only enqueues, and this handler owns the
    retries, the failure accounting and the delivery-log row.

    Errors are logged and swallowed rather than re-raised: a raise would leave
    the queue message undeleted and redeliver the same event to a subscriber
    that may already have received it. The retry policy for a bad subscriber
    is ``_deliver_with_retry``'s 3 attempts, not queue redelivery.

    ``db_session`` is injectable for tests; production (queue-worker) calls
    leave it as None and get a real, short-lived ``Session(engine)``.
    """
    from services.webhooks import deliver_webhook_now

    def _run(session: Session) -> dict:
        result = deliver_webhook_now(
            session,
            UUID(subscription_id),
            event_type,
            payload or {},
        )
        if result is None:
            return {"delivered": False, "skipped": True}
        return {
            "delivered": result.success,
            "skipped": False,
            "status_code": result.status_code,
            "attempts": result.attempts,
        }

    try:
        if db_session is not None:
            return _run(db_session)
        with Session(engine) as session:
            return _run(session)
    except Exception as e:
        logger.error(
            "Webhook delivery job failed (tenant=%s, subscription=%s, event=%s): %s",
            tenant_id, subscription_id, event_type, e,
        )
        return {"delivered": False, "skipped": False, "error": str(e)}
