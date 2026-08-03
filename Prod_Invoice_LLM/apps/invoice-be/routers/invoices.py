import logging
import json
import os
import hashlib
import asyncio
from uuid import uuid4, UUID
from datetime import date
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from config import settings

from dependencies import get_tenant_context, get_db_session, require_can_load, TenantContext
from models import Invoice, Tenant, AuditLog
from services.storage import upload_pdf_to_blob_storage, download_pdf_from_storage, delete_pdf_from_storage
from chroma_client import delete_invoice_chunks
from azure.storage.queue import QueueClient
from config import get_settings
from azure.core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


async def _ingest_single_file(
    file_bytes: bytes,
    filename: str,
    tags: list[str],
    batch_id: UUID,
    tenant: Tenant,
    context: TenantContext,
    db_session: Session,
) -> str:
    """
    Shared per-file ingestion logic (dedup check, blob upload, DB row, queue
    dispatch) used by both the direct upload endpoint and the directory
    watcher (Gap 12) — one path, not two copies to keep in sync. Returns the
    new invoice_id as a string.
    """
    invoice_id = uuid4()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    existing_invoice = db_session.exec(
        select(Invoice).where(
            Invoice.tenant_id == context.tenant_id,
            Invoice.file_hash == file_hash
        )
    ).first()

    if existing_invoice:
        db_invoice = Invoice(
            id=invoice_id,
            tenant_id=context.tenant_id,
            batch_id=batch_id,
            file_path=existing_invoice.file_path,
            file_hash=file_hash,
            vendor_name=existing_invoice.vendor_name,
            grand_total=existing_invoice.grand_total,
            invoice_number=existing_invoice.invoice_number,
            invoice_date=existing_invoice.invoice_date,
            due_date=existing_invoice.due_date,
            tax_amount=existing_invoice.tax_amount,
            po_number=existing_invoice.po_number,
            status="DUPLICATE",
            sa_alerts=[{
                "type": "duplicate",
                "message": f"This file is a duplicate of a previously uploaded invoice (ID: {existing_invoice.id})."
            }],
            tags=tags,
            items=existing_invoice.items
        )
        db_session.add(db_invoice)
        await run_in_threadpool(db_session.commit)
        db_session.refresh(db_invoice)

        try:
            import redis
            r = redis.Redis.from_url(settings.REDIS_URL)
            event_data = {
                "status": "DUPLICATE",
                "message": "Duplicate invoice signature detected. Copied data from previous upload.",
                "invoice_id": str(invoice_id),
                "data": {
                    "vendor_name": existing_invoice.vendor_name,
                    "invoice_number": existing_invoice.invoice_number,
                    "invoice_date": str(existing_invoice.invoice_date) if existing_invoice.invoice_date else None,
                    "due_date": str(existing_invoice.due_date) if existing_invoice.due_date else None,
                    "grand_total": existing_invoice.grand_total,
                    "tax_amount": existing_invoice.tax_amount,
                    "po_number": existing_invoice.po_number,
                    "items": existing_invoice.items,
                    "tags": tags
                },
                "alerts": [{
                    "type": "duplicate",
                    "message": f"Duplicate of invoice {existing_invoice.invoice_number or existing_invoice.id}."
                }]
            }
            r.publish(f"invoice.update.{batch_id}", json.dumps(event_data))
        except Exception as re:
            logger.warning("Failed to publish SSE duplicate event: %s", re)
        return str(invoice_id)

    try:
        file_path = await run_in_threadpool(
            upload_pdf_to_blob_storage, file_bytes, str(context.tenant_id), str(invoice_id)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store file {filename}: {str(e)}"
        )

    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        file_path=file_path,
        file_hash=file_hash,
        status="PROCESSING",
        tags=tags
    )
    db_session.add(db_invoice)
    await run_in_threadpool(db_session.commit)
    db_session.refresh(db_invoice)

    try:
        watcher_settings = get_settings()
        if watcher_settings.AZURE_STORAGE_CONNECTION_STRING:
            queue_client = QueueClient.from_connection_string(
                watcher_settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
            )
            payload = {
                "task": "process_invoice",
                "kwargs": {
                    "batch_id": str(batch_id),
                    "file_path": file_path,
                    "tenant_id": str(context.tenant_id)
                }
            }
            queue_client.send_message(json.dumps(payload))
            print(f"SUCCESS: Dispatched Azure Storage Queue task for invoice {invoice_id}", flush=True)
        else:
            print("WARNING: AZURE_STORAGE_CONNECTION_STRING missing, skipped queueing.", flush=True)
            logger.warning("AZURE_STORAGE_CONNECTION_STRING missing, skipped queueing.")
    except Exception as e:
        print(f"ERROR: Failed to dispatch Azure Storage Queue task: {str(e)}", flush=True)
        logger.warning("Failed to dispatch Azure Storage Queue task: %s", e)

    return str(invoice_id)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_invoices(
    files: list[UploadFile] = File(...),
    tags: list[str] = Form([]),
    # Feature 1.1 (Task 1.1.2): ingestion is a granted permission, default off.
    # Only the two write/ingest endpoints are gated -- the GET list/detail/pdf
    # routes below stay open so the Dashboard remains reachable for a user with
    # no permissions at all, per the feature's access model.
    context: TenantContext = Depends(require_can_load),
    db_session: Session = Depends(get_db_session)
):
    """
    Accepts invoice PDF file uploads, saves them to tenant-isolated storage,
    provisions DB entries, and dispatches background processing tasks.
    Enforces subscription limits for free-tier tenants.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded."
        )

    # 1. Validate that all files are PDFs
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file format: {file.filename}. Only PDF is allowed."
            )

    # 2. Fetch Tenant context (provisioned by get_tenant_context)
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found."
        )

    # 3. Enforce Free Plan Limits
    if tenant.billing_plan == "free":
        if tenant.free_invoices_remaining < len(files):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Limit reached"
            )
        tenant.free_invoices_remaining -= len(files)
        db_session.add(tenant)
        await run_in_threadpool(db_session.commit)

    batch_id = uuid4()
    job_ids = []

    for file in files:
        try:
            file_bytes = await file.read()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read file {file.filename}: {str(e)}"
            )
        job_id = await _ingest_single_file(file_bytes, file.filename, tags, batch_id, tenant, context, db_session)
        job_ids.append(job_id)

    return {
        "batch_id": batch_id,
        "job_ids": job_ids
    }


class DirectoryWatchRequest(BaseModel):
    directory_path: str


@router.post("/watcher/start", status_code=status.HTTP_200_OK)
async def start_directory_watcher(
    payload: DirectoryWatchRequest,
    # Feature 1.1 (Task 1.1.2): bulk directory ingest is the same action as
    # /upload by another door, so it carries the same `can_load` gate.
    context: TenantContext = Depends(require_can_load),
    db_session: Session = Depends(get_db_session)
):
    """
    Gap 12: bulk-ingests every PDF found in a server-accessible directory in
    one pass, through the same dedup/upload/queue path as a normal upload.

    Deliberately a one-time scan, not a persistent background watch — there's
    no stop endpoint to manage a long-running watcher's lifecycle, and most
    cloud tenants have no persistent filesystem for the backend to watch
    anyway. This targets local/on-prem bulk-ingestion (e.g. a shared network
    drop folder), not continuous cloud monitoring.

    Path-traversal guard: directory_path must resolve inside
    settings.WATCHER_ALLOWED_BASE_DIR. Unconfigured (empty) disables the
    feature entirely, since allowing arbitrary server filesystem reads from
    tenant-supplied input is a real risk otherwise.
    """
    watcher_settings = get_settings()
    allowed_base = watcher_settings.WATCHER_ALLOWED_BASE_DIR
    if not allowed_base:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Directory watcher is not configured for this environment."
        )

    allowed_base_abs = os.path.realpath(allowed_base)
    requested_abs = os.path.realpath(payload.directory_path)
    if os.path.commonpath([allowed_base_abs, requested_abs]) != allowed_base_abs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="directory_path must be inside the configured watcher base directory."
        )
    if not os.path.isdir(requested_abs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Directory not found: {payload.directory_path}"
        )

    pdf_filenames = sorted(f for f in os.listdir(requested_abs) if f.lower().endswith(".pdf"))
    watcher_id = uuid4()
    if not pdf_filenames:
        return {"watcher_id": watcher_id, "status": "completed", "files_found": 0, "files_queued": 0}

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    if tenant.billing_plan == "free" and tenant.free_invoices_remaining < len(pdf_filenames):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Limit reached")
    if tenant.billing_plan == "free":
        tenant.free_invoices_remaining -= len(pdf_filenames)
        db_session.add(tenant)
        await run_in_threadpool(db_session.commit)

    batch_id = uuid4()
    job_ids = []
    for filename in pdf_filenames:
        with open(os.path.join(requested_abs, filename), "rb") as f:
            file_bytes = f.read()
        job_id = await _ingest_single_file(file_bytes, filename, [], batch_id, tenant, context, db_session)
        job_ids.append(job_id)

    return {
        "watcher_id": watcher_id,
        "status": "completed",
        "batch_id": batch_id,
        "files_found": len(pdf_filenames),
        "files_queued": len(job_ids),
        "job_ids": job_ids,
    }


async def sse_event_generator(batch_id: str):
    """Async generator to yield Redis pub/sub messages as Server-Sent Events."""
    redis_client = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    channel = f"invoice.update.{batch_id}"
    await pubsub.subscribe(channel)
    
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                data = message["data"]
                yield f"data: {data}\n\n"
                
                # Terminate stream on final state
                try:
                    payload = json.loads(data)
                    if payload.get("status") in ["COMPLETED", "AUDIT_REQUIRED", "FAILED"]:
                        break
                except Exception:
                    pass
            else:
                # Heartbeat keep-alive to keep connection open
                yield ": keep-alive\n\n"
                
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info("SSE subscription disconnected for batch %s", batch_id)
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.close()


@router.get("/stream/{batch_id}")
async def stream_invoice_status(batch_id: UUID, context: TenantContext = Depends(get_tenant_context)):
    """Streaming response endpoint yielding real-time processing updates for a batch."""
    return StreamingResponse(sse_event_generator(str(batch_id)), media_type="text/event-stream")


@router.get("/status/{job_id}")
async def get_invoice_status(
    job_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """Polling status endpoint returning DB record details for a single invoice."""
    statement = select(Invoice).where(Invoice.id == job_id, Invoice.tenant_id == context.tenant_id)
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found or access denied.")
    return {
        "id": invoice.id,
        "status": invoice.status,
        "vendor_name": invoice.vendor_name,
        "grand_total": invoice.grand_total,
        "alerts": invoice.sa_alerts
    }


@router.get("", response_model=list[Invoice])
async def list_invoices(
    response: Response,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    status_in: str | None = None,
    tag: str | None = None,
    vendor_name: str | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Fetches a page of matching records for the requesting tenant, most recent
    first. Supports pagination, date ranges, status/vendor filters, and search
    tags.

    FE Gap 29: the total matching count (ignoring limit/offset) is returned in
    the X-Total-Count header so a caller can page through the tenant's full
    result set via repeated limit/offset calls, instead of fetching one fixed
    batch and re-slicing it client-side. `status_in` (comma-separated) exists
    alongside the single-value `status` filter so the FE's "Pending" tab --
    which spans several raw statuses (Processing/Completed/Audit Required/
    Duplicate) rather than one -- can still be a real server-side filter
    compatible with this pagination, instead of a client-side re-filter of an
    already-paginated page.
    """
    conditions = [
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "INBOUND"
    ]
    if start_date:
        conditions.append(Invoice.invoice_date >= start_date)
    if end_date:
        conditions.append(Invoice.invoice_date <= end_date)
    if status:
        conditions.append(Invoice.status == status)
    if status_in:
        conditions.append(Invoice.status.in_([s.strip() for s in status_in.split(",") if s.strip()]))
    if vendor_name:
        conditions.append(Invoice.vendor_name == vendor_name)

    query = select(Invoice).where(*conditions)
    if tag:
        # Check DB dialect to use correct JSON query syntax
        if db_session.bind.dialect.name == "postgresql":
            query = query.where(Invoice.tags.contains([tag]))
        else:
            query = query.where(Invoice.tags.like(f'%"{tag}"%'))

    total = db_session.exec(
        select(func.count()).select_from(query.with_only_columns(Invoice.id).subquery())
    ).one()
    response.headers["X-Total-Count"] = str(total)

    query = query.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    return db_session.exec(query).all()


@router.get("/{invoice_id}", response_model=Invoice)
async def get_invoice(
    invoice_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Fetches a single invoice details. Enforces tenant isolation.
    """
    query = select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id)
    invoice = db_session.exec(query).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )
    return invoice


@router.get("/{invoice_id}/pdf")
async def get_invoice_pdf(
    invoice_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Streams the secure PDF file retrieved from storage (Azure or Local fallback).
    Enforces tenant isolation.
    """
    query = select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id)
    invoice = db_session.exec(query).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )
    
    try:
        pdf_bytes = download_pdf_from_storage(invoice.file_path)
    except (FileNotFoundError, ResourceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice PDF file not found in storage."
        )
    except Exception as e:
        logger.error("Error retrieving PDF for invoice %s: %s", invoice_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve invoice PDF."
        )
        
    import io
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={invoice_id}.pdf"}
    )


@router.delete("/{invoice_id}")
async def delete_invoice(
    invoice_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Permanently deletes an invoice: the Postgres row, the PDF in Blob Storage,
    its indexed vector chunks in ChromaDB, and any related audit log entries.
    Enforces tenant isolation. Blob/vector cleanup is best-effort — a failure there
    logs a warning but does not block removing the Postgres row, so a flaky
    downstream store can't make an invoice permanently undeletable.
    """
    query = select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id)
    invoice = db_session.exec(query).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )

    try:
        await run_in_threadpool(delete_pdf_from_storage, invoice.file_path)
    except Exception as e:
        logger.warning("Failed to delete PDF for invoice %s: %s", invoice_id, e)

    try:
        await run_in_threadpool(delete_invoice_chunks, str(invoice_id), str(context.tenant_id))
    except Exception as e:
        logger.warning("Failed to delete vector chunks for invoice %s: %s", invoice_id, e)

    audit_stmt = select(AuditLog).where(AuditLog.invoice_id == invoice_id, AuditLog.tenant_id == context.tenant_id)
    for log in db_session.exec(audit_stmt).all():
        db_session.delete(log)

    db_session.delete(invoice)
    await run_in_threadpool(db_session.commit)

    return {"success": True}
