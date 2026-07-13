import logging
import json
import asyncio
from uuid import uuid4, UUID
from datetime import date
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis as AsyncRedis
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from config import settings

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, Tenant
from services.storage import upload_pdf_to_blob_storage, download_pdf_from_storage
from workers.tasks import process_invoice_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices", tags=["Invoices"])

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_invoices(
    files: list[UploadFile] = File(...),
    tags: list[str] = Form([]),
    context: TenantContext = Depends(get_tenant_context),
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
        invoice_id = uuid4()
        
        try:
            file_bytes = await file.read()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read file {file.filename}: {str(e)}"
            )

        # Compute SHA-256 hash of file content
        import hashlib
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Check for duplicates
        existing_invoice = db_session.exec(
            select(Invoice).where(
                Invoice.tenant_id == context.tenant_id,
                Invoice.file_hash == file_hash
            )
        ).first()

        if existing_invoice:
            # Create duplicate database entry copying metadata
            db_invoice = Invoice(
                id=invoice_id,
                tenant_id=context.tenant_id,
                batch_id=batch_id,
                file_path=existing_invoice.file_path,  # Reuse existing file path
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
            job_ids.append(str(invoice_id))

            # Publish completed event instantly to SSE
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
            continue

        # Upload file to storage
        try:
            file_path = await run_in_threadpool(
                upload_pdf_to_blob_storage, file_bytes, str(context.tenant_id), str(invoice_id)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to store file {file.filename}: {str(e)}"
            )

        # Create database entry
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
        
        job_ids.append(str(invoice_id))

        # Enqueue background tasks via Celery
        try:
            process_invoice_task.delay(str(batch_id), file_path, str(context.tenant_id))
        except Exception as e:
            logger.warning("Failed to dispatch Celery task: %s (Ignored for local offline dev)", e)

    return {
        "batch_id": batch_id,
        "job_ids": job_ids
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
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    tag: str | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Fetches a list of matching records for the requesting tenant.
    Supports pagination, date ranges, status filters, and search tags.
    """
    query = select(Invoice).where(Invoice.tenant_id == context.tenant_id)
    
    if start_date:
        query = query.where(Invoice.invoice_date >= start_date)
    if end_date:
        query = query.where(Invoice.invoice_date <= end_date)
    if status:
        query = query.where(Invoice.status == status)
    if tag:
        # Check DB dialect to use correct JSON query syntax
        if db_session.bind.dialect.name == "postgresql":
            query = query.where(Invoice.tags.contains([tag]))
        else:
            query = query.where(Invoice.tags.like(f'%"{tag}"%'))
            
    query = query.offset(offset).limit(limit)
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
    except FileNotFoundError:
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
