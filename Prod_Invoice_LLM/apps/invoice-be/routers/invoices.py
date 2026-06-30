import logging
from uuid import uuid4
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlmodel import Session

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, Tenant
from services.storage import upload_pdf_to_blob_storage
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

    # 2. Fetch or Auto-Provision Tenant Context
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        tenant = Tenant(
            id=context.tenant_id,
            name="Tenant Account",
            domain=f"domain-{context.tenant_id}.com",
            billing_plan=context.billing_plan,
        )
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)

    # 3. Enforce Free Plan Limits
    if tenant.billing_plan == "free":
        if tenant.free_invoices_remaining < len(files):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Limit reached"
            )
        tenant.free_invoices_remaining -= len(files)
        db_session.add(tenant)
        db_session.commit()

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

        # Upload file to storage
        try:
            file_path = upload_pdf_to_blob_storage(file_bytes, str(context.tenant_id), str(invoice_id))
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
            status="PROCESSING",
            tags=tags
        )
        db_session.add(db_invoice)
        db_session.commit()
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
