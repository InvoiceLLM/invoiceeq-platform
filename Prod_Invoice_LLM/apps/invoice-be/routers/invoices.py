import logging
import json
import os
import hashlib
import asyncio
from typing import Literal
from uuid import uuid4, UUID
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from config import settings

from dependencies import (
    get_tenant_context,
    get_db_session,
    require_can_load,
    # Feature 25 (Gap 335): the ingestion + read surface an integration reaches
    # with an `inv_live_` key. `require_can_load_or_api_key` keeps the human
    # can_load gate on /upload intact while admitting a key of any scope --
    # upload is ingestion, not one of the actions `actions` scope governs.
    get_tenant_or_api_key_context,
    require_can_load_or_api_key,
    # BE Gap 736: the replace route's gate. Stricter than the upload gate
    # above on the key side -- see the dependency's docstring.
    require_can_load_and_actions_scope,
    TenantContext,
)
from chroma_client import delete_document_chunks, delete_invoice_chunks
from models import Document, Invoice, Tenant, AuditLog, User
from services.storage import upload_pdf_to_blob_storage, download_pdf_from_storage, StorageUploadError
from services.invoice_visibility import invoice_not_deleted
from utils.alert_ids import with_alert_ids
from services.invoice_deletion import (
    delete_document_rows,
    delete_invoice_rows,
    purge_document_stores,
    purge_invoice_stores,
)
from services.billing_quota import charge_free_quota, count_billable_uploads
from services.ingestion_batches import record_ingestion_batch
from services.file_intake import (
    ACCEPTED_UPLOAD_SUFFIXES,
    ImageTooLargeError,
    PdfTooManyPagesError,
    UnsupportedUploadError,
    normalize_upload,
)
from azure.storage.queue import QueueClient
from config import get_settings
from azure.core.exceptions import ResourceNotFoundError
from database import engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


def _submitter_email_from_context(db_session: Session, context: TenantContext) -> str | None:
    """Best-effort UI uploader email for Gap 125 process-complete notify."""
    if not context.db_user_id:
        return None
    user = db_session.get(User, context.db_user_id)
    if not user or not user.email:
        return None
    return str(user.email).strip().lower() or None


async def _enqueue_extraction(
    db_invoice: Invoice,
    batch_id: UUID,
    file_path: str,
    context: TenantContext,
    db_session: Session,
) -> bool:
    """Put one extraction task on the queue. Returns whether it went.

    BE Gap 732 lifted this out of `_ingest_single_file` so the replace-file
    route dispatches through the same code rather than a second copy of it --
    two copies of a queue send is how one of them quietly loses the
    `last_enqueued_at` stamp the reconciliation sweep keys on.

    Failure is deliberately NOT raised. The invoice is already stored and
    committed; leaving it at PROCESSING is what lets
    `services/invoice_reconciliation.py` find and re-enqueue it, and
    `GET /status/{id}` reports `queued: false` until it does (BE Gap 731).
    Raising here would hand the caller a 5xx for a file we successfully kept.
    """
    invoice_id = db_invoice.id
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
            # Gap 81: stamp when the message actually went on the queue. The
            # reconciliation sweep measures staleness from this, not from
            # created_at, so it can tell "uploaded 20 minutes ago and never
            # picked up" from "re-enqueued 20 seconds ago".
            db_invoice.last_enqueued_at = datetime.utcnow()
            db_invoice.processing_attempts = (db_invoice.processing_attempts or 0) + 1
            db_session.add(db_invoice)
            await run_in_threadpool(db_session.commit)
            print(f"SUCCESS: Dispatched Azure Storage Queue task for invoice {invoice_id}", flush=True)
            return True

        print("WARNING: AZURE_STORAGE_CONNECTION_STRING missing, skipped queueing.", flush=True)
        logger.error(
            "AZURE_STORAGE_CONNECTION_STRING missing -- invoice %s was stored but never queued "
            "and will sit at PROCESSING until the reconciliation sweep re-enqueues it.",
            invoice_id,
        )
        return False
    except Exception as e:
        print(f"ERROR: Failed to dispatch Azure Storage Queue task: {str(e)}", flush=True)
        # Gap 81 (third fix implication): this used to be logger.warning, which
        # is exactly the "swallowed signal nobody watches" the gap called out --
        # a failed enqueue leaves a real invoice permanently stuck, so it is an
        # error, and the message names that consequence explicitly.
        logger.error(
            "Failed to dispatch extraction queue task for invoice %s -- it will remain at "
            "PROCESSING until the reconciliation sweep re-enqueues it: %s",
            invoice_id, e,
        )
        return False


async def _ingest_single_file(
    file_bytes: bytes,
    filename: str,
    tags: list[str],
    batch_id: UUID,
    tenant: Tenant,
    context: TenantContext,
    db_session: Session,
    submitted_by_email: str | None = None,
    original_filename: str | None = None,
) -> str:
    """
    Shared per-file ingestion logic (dedup check, blob upload, DB row, queue
    dispatch) used by both the direct upload endpoint and the directory
    watcher (Gap 12) — one path, not two copies to keep in sync. Returns the
    new invoice_id as a string.
    """
    invoice_id = uuid4()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    submitter = (submitted_by_email or _submitter_email_from_context(db_session, context) or "").strip().lower() or None

    existing_invoice = db_session.exec(
        select(Invoice).where(
            Invoice.tenant_id == context.tenant_id,
            Invoice.file_hash == file_hash
        )
    ).first()

    # Feature 27 (BE Gap 385, closing §2A/A4/F5's never-made ingestion-dedup
    # ruling). E10 moved non-invoice documents out of `invoice` into `documents`,
    # and this check never followed them: re-uploading the same delivery note
    # twice produced a second full DI + extraction run and a second row, because
    # its first arrival had left no `Invoice.file_hash` to match. Meanwhile
    # `services/billing_quota.py::count_billable_uploads` had *already* been
    # widened to the union at G14 -- so the two halves of one rule disagreed:
    # billing said "already paid for, not billable", ingestion said "never seen
    # it, process it". The tenant got the work done for free and the row count
    # stopped matching the invoice count. Same union, same shape, same file-order
    # as `count_billable_uploads`, deliberately.
    #
    # **The tenant predicate is inside each side, never applied to a combined
    # set** (§2A/A4/F2). An unscoped union would let one tenant's upload be
    # marked DUPLICATE of another tenant's file -- a cross-tenant information
    # leak through the duplicate alert, strictly worse here than in billing
    # because the alert text is rendered to the user.
    #
    # Invoice is probed FIRST and short-circuits, so the pre-existing
    # Invoice-vs-Invoice path is byte-identical to what it was; the Document
    # probe only runs when there is no invoice match.
    existing_document = None
    if not existing_invoice:
        existing_document = db_session.exec(
            select(Document).where(
                Document.tenant_id == context.tenant_id,
                Document.file_hash == file_hash
            )
        ).first()

    if existing_invoice or existing_document:
        # WHAT GETS COPIED WHEN THE MATCH IS A `Document` (BE Gap 385's ruling).
        #
        # Only the storage pointer. `file_path` is the one column that means the
        # same thing on both tables -- a blob location -- and copying it is what
        # avoids re-uploading bytes already in storage, which is the whole reason
        # the invoice-vs-invoice path copies it.
        #
        # Every extracted field is deliberately left NULL, and this is a decision
        # against the obvious-looking mapping, not an omission:
        #   - `Document.party_name` is NOT `Invoice.vendor_name`. `party_name` is
        #     whoever ISSUED the document, so on a purchase order it is the
        #     *buyer* -- our own tenant. Copying it into `vendor_name` would file
        #     the tenant as its own vendor.
        #   - `Document.doc_number` is NOT an `invoice_number`, and
        #     `Document.doc_date` is not an `invoice_date`.
        #   - Money is optional on `documents` by design (a delivery note prints
        #     quantities and no prices). Copying `grand_total`/`tax_amount` would
        #     either fabricate an invoice-shaped total from a non-invoice or, on
        #     the common NULL, be a no-op that only looks like data.
        # A DUPLICATE row is never re-extracted, so anything wrong copied in here
        # is permanent -- exactly how FE Gap 183 (dropped currency) became real
        # data loss. NULL is honest; a mislabelled value is not, which is the same
        # call A1 made about not drawing invoice-field overlays on a PO.
        #
        # `duplicate_of_invoice_id` stays NULL for a document match: it is a
        # pointer into `invoice.id` and putting a `documents.id` in it would make
        # every reader that dereferences it (FE alert UI, Gap 195 consumers)
        # look up an invoice that does not exist. The document origin goes in the
        # `sa_alerts` payload instead, structured, so it is traceable without a
        # new column and therefore without a migration.
        if existing_invoice:
            source_file_path = existing_invoice.file_path
            copied = dict(
                vendor_name=existing_invoice.vendor_name,
                grand_total=existing_invoice.grand_total,
                invoice_number=existing_invoice.invoice_number,
                invoice_date=existing_invoice.invoice_date,
                due_date=existing_invoice.due_date,
                tax_amount=existing_invoice.tax_amount,
                po_number=existing_invoice.po_number,
                # FE Gap 183: currency was the one extracted field this copy
                # dropped. A duplicate of an INR invoice landed with currency=NULL,
                # so it was silently treated as USD by every reader downstream --
                # real data loss, not just a display bug, because the duplicate row
                # never goes through extraction again to recover it.
                currency=existing_invoice.currency,
                items=existing_invoice.items,
            )
            # Gap 195: structured pointer to the original, alongside the
            # existing prose message below (kept for the alert UI).
            duplicate_of_invoice_id = existing_invoice.id
            duplicate_alert = {
                "type": "duplicate",
                "message": f"This file is a duplicate of a previously uploaded invoice (ID: {existing_invoice.id})."
            }
            sse_message = "Duplicate invoice signature detected. Copied data from previous upload."
            sse_alert_message = (
                f"Duplicate of invoice {existing_invoice.invoice_number or existing_invoice.id}."
            )
        else:
            source_file_path = existing_document.file_path
            copied = dict(
                vendor_name=None,
                grand_total=None,
                invoice_number=None,
                invoice_date=None,
                due_date=None,
                tax_amount=None,
                po_number=None,
                currency=None,
                items=[],
            )
            duplicate_of_invoice_id = None
            duplicate_alert = {
                "type": "duplicate",
                "message": (
                    f"This file is a duplicate of a previously uploaded "
                    f"{(existing_document.doc_type or 'document').replace('_', ' ').lower()} "
                    f"(document ID: {existing_document.id})."
                ),
                # Structured origin pointer, the `documents` counterpart of
                # Gap 195's `duplicate_of_invoice_id` column. Kept in the alert
                # payload rather than promoted to a column so this ruling needs
                # no migration; promote it if a reader ever needs to join on it.
                "duplicate_of_document_id": str(existing_document.id),
                "duplicate_of_doc_type": existing_document.doc_type,
            }
            sse_message = (
                "Duplicate file signature detected -- this file was already ingested as a "
                "non-invoice document, so no data was copied."
            )
            sse_alert_message = (
                f"Duplicate of document {existing_document.doc_number or existing_document.id}."
            )

        db_invoice = Invoice(
            id=invoice_id,
            tenant_id=context.tenant_id,
            batch_id=batch_id,
            file_path=source_file_path,
            file_hash=file_hash,
            status="DUPLICATE",
            duplicate_of_invoice_id=duplicate_of_invoice_id,
            sa_alerts=with_alert_ids([duplicate_alert]),  # BE Gap 566
            tags=tags,
            submitted_by_email=submitter,
            # BE Gap 464: persist the user-facing name even on duplicates so
            # the History screen shows what the user uploaded, not a UUID.
            original_filename=original_filename or filename,
            **copied,
        )
        db_session.add(db_invoice)
        await run_in_threadpool(db_session.commit)
        db_session.refresh(db_invoice)

        try:
            from services.webhooks import dispatch_webhook_event
            # BE Gap 385: still `invoice.duplicate` -- the row created IS an
            # Invoice row whichever table matched, and a new event type would
            # break every existing subscriber's filter for no gain. But
            # `duplicate_of_invoice_id` is NULL on a document match rather than
            # carrying a `documents.id`, for the same dereferencing reason as the
            # column; the origin is exposed under its own key so a subscriber
            # keying on `duplicate_of_invoice_id` never receives a document id in
            # an invoice-id field.
            dispatch_webhook_event(db_session, context.tenant_id, "invoice.duplicate", {
                "invoice_id": str(invoice_id),
                "duplicate_of_invoice_id": (
                    str(existing_invoice.id) if existing_invoice else None
                ),
                "duplicate_of_document_id": (
                    None if existing_invoice else str(existing_document.id)
                ),
                "status": "DUPLICATE",
                "vendor_name": copied["vendor_name"],
                "grand_total": copied["grand_total"],
                "currency": copied["currency"],
            })
        except Exception as we:
            logger.error("Webhook dispatch failed for invoice %s: %s", invoice_id, we)

        try:
            import redis
            r = redis.Redis.from_url(settings.REDIS_URL)
            # The SSE payload is built from `copied`, not from the matched row, so
            # it reports exactly what was persisted. On a document match that is
            # all-NULL and the message says so -- the FE must not render an empty
            # card as though extraction had produced nothing.
            event_data = {
                "status": "DUPLICATE",
                "message": sse_message,
                "invoice_id": str(invoice_id),
                "data": {
                    "vendor_name": copied["vendor_name"],
                    "invoice_number": copied["invoice_number"],
                    "invoice_date": str(copied["invoice_date"]) if copied["invoice_date"] else None,
                    "due_date": str(copied["due_date"]) if copied["due_date"] else None,
                    "grand_total": copied["grand_total"],
                    "currency": copied["currency"],
                    "tax_amount": copied["tax_amount"],
                    "po_number": copied["po_number"],
                    "items": copied["items"],
                    "tags": tags
                },
                "alerts": [{
                    "type": "duplicate",
                    "message": sse_alert_message,
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
    except StorageUploadError as e:
        logger.error("Storage upload failed for invoice %s (%s): %s", invoice_id, filename, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is temporarily unavailable. Nothing was saved. Try again.",
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
        tags=tags,
        submitted_by_email=submitter,
        # BE Gap 464: persist the user-facing name before UUID blob renaming.
        original_filename=original_filename or filename,
    )
    db_session.add(db_invoice)
    await run_in_threadpool(db_session.commit)
    db_session.refresh(db_invoice)

    await _enqueue_extraction(db_invoice, batch_id, file_path, context, db_session)

    return str(invoice_id)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_invoices(
    files: list[UploadFile] = File(...),
    tags: list[str] = Form([]),
    # Feature 1.1 (Task 1.1.2): ingestion is a granted permission, default off.
    # Only the two write/ingest endpoints are gated -- the GET list/detail/pdf
    # routes below stay open so the Dashboard remains reachable for a user with
    # no permissions at all, per the feature's access model.
    # Feature 25 (Gap 335): now also reachable with an `inv_live_` API key at
    # EITHER scope -- the founder's Strict Review policy is "read/upload-only",
    # so feeding the system is exactly what a readonly key is for. The human
    # can_load requirement above is unchanged; see
    # require_permission_or_api_key().
    context: TenantContext = Depends(require_can_load_or_api_key),
    db_session: Session = Depends(get_db_session)
):
    """
    Accepts invoice PDF file uploads, saves them to tenant-isolated storage,
    provisions DB entries, and dispatches background processing tasks.
    Enforces subscription limits for free-tier tenants (Gap 189: charge only
    billable/non-duplicate files under a Tenant row lock).
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded."
        )

    # 1. Read all bytes up front, then normalise each file at the door
    #    (Feature 28): a PDF passes through byte-identical, an accepted image is
    #    converted to PDF here and nothing downstream sees anything but a PDF.
    #    This replaces Gap 355's two-step (filename suffix, then %PDF header)
    #    check — sniffing the bytes subsumes both and cannot disagree with
    #    itself. Reading up front is still what lets duplicates be classified
    #    before quota is charged (Gap 189).
    payloads: list[tuple[str, bytes]] = []
    for file in files:
        fname = file.filename or "invoice.pdf"
        try:
            file_bytes = await file.read()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read file {fname}: {str(e)}"
            )
        try:
            normalized = normalize_upload(fname, file_bytes)
        except (UnsupportedUploadError, ImageTooLargeError, PdfTooManyPagesError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.detail,
            )
        # BE Gap 464: keep original user-facing name alongside the normalized
        # pdf_filename; `fname` is what the browser sent before normalization.
        payloads.append((normalized.pdf_filename, normalized.pdf_bytes, fname))

    # 2. Gap 189: count billable hashes, then lock Tenant and charge that count only.
    billable = count_billable_uploads(
        db_session, context.tenant_id, [data for _, data, _orig in payloads]
    )
    tenant = charge_free_quota(db_session, context.tenant_id, billable)

    batch_id = uuid4()
    # Gap 464: record the RUN before the files are processed, not after. A run
    # whose every file is rejected downstream still happened and still belongs
    # in the History screen -- deriving history from the rows a run produced is
    # exactly what loses it (models.IngestionBatch).
    record_ingestion_batch(
        db_session,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        trigger="manual",
        file_count=len(payloads),
        flow_direction="INBOUND",
    )
    # BE Gap 734: a multi-file upload is validated all-or-nothing ABOVE (the
    # loop that reads and normalises raises before a single byte is charged or
    # stored), but the ingest loop below is not atomic: file 3 hitting a storage
    # outage after files 1 and 2 are stored and queued used to raise 503 out of
    # this handler, and the caller was told the whole request failed while two
    # invoices were quietly live -- and the quota had been charged for all
    # three. The customer's next move is to retry, which dedups files 1 and 2
    # but makes the response a lie either way.
    #
    # Now the failure is reported WITH what actually landed. 207 is deliberate:
    # a 2xx says "some of this worked, read the body", which is exactly the
    # truth, and a caller that only checks `response.ok` still gets the ids it
    # needs rather than throwing away a successful half.
    job_ids = []
    failures: list[dict] = []
    for filename, file_bytes, orig_name in payloads:
        try:
            job_id = await _ingest_single_file(
                file_bytes, filename, tags, batch_id, tenant, context, db_session,
                original_filename=orig_name,
            )
            job_ids.append(job_id)
        except HTTPException as exc:
            # BE Gap 721/722 landed `orig_name` while this was in flight, and it
            # is the right name to report: `filename` is the normalised one this
            # pipeline invented, and telling a customer that "a3f9c1.pdf" failed
            # when they uploaded "ACME-Invoice-0042.pdf" is not a report they can
            # act on.
            reported = orig_name or filename
            logger.error(
                "Upload batch %s: %s failed to ingest (%s) -- %d of %d already stored.",
                batch_id, reported, exc.detail, len(job_ids), len(payloads),
            )
            failures.append({"filename": reported, "detail": exc.detail, "status": exc.status_code})

    if failures and not job_ids:
        # Nothing landed: the caller's mental model ("this request failed") is
        # accurate, so keep the original error rather than inventing a 207 that
        # reports an empty success.
        first = failures[0]
        raise HTTPException(status_code=first["status"], detail=first["detail"])

    # BE Gap 577 (CH-10): Invalidate cached chat answers on ingestion write
    try:
        from services.chat_cache import bump_tenant_data_version
        bump_tenant_data_version(context.tenant_id)
    except Exception as e:
        logger.debug("Failed to bump chat data version on invoice upload: %s", e)

    if failures:
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content={
                "batch_id": str(batch_id),
                "job_ids": [str(j) for j in job_ids],
                "failed": failures,
                "detail": (
                    f"{len(job_ids)} of {len(payloads)} files were accepted. "
                    "The rest are listed in `failed` and were NOT stored; retry those only."
                ),
            },
        )

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

    allowed_base_abs = os.path.normcase(os.path.realpath(allowed_base))
    requested_abs = os.path.normcase(os.path.realpath(payload.directory_path))
    try:
        common = os.path.commonpath([allowed_base_abs, requested_abs])
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid path comparison: {str(ve)}"
        )
    if common != allowed_base_abs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="directory_path must be inside the configured watcher base directory."
        )
    if not os.path.isdir(requested_abs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Directory not found: {payload.directory_path}"
        )

    # Feature 28: the watched directory may hold images as well as PDFs. The
    # listing filter is the shared accept list, and each file is normalised to
    # PDF bytes before anything hashes, charges or stores it.
    source_filenames = sorted(
        f for f in os.listdir(requested_abs)
        if os.path.splitext(f)[1].lower() in ACCEPTED_UPLOAD_SUFFIXES
    )
    watcher_id = uuid4()
    if not source_filenames:
        return {"watcher_id": watcher_id, "status": "completed", "files_found": 0, "files_queued": 0}

    payloads: list[tuple[str, bytes]] = []
    for filename in source_filenames:
        with open(os.path.join(requested_abs, filename), "rb") as f:
            raw_bytes = f.read()
        try:
            normalized = normalize_upload(filename, raw_bytes)
        except (UnsupportedUploadError, ImageTooLargeError, PdfTooManyPagesError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.detail,
            )
        payloads.append((normalized.pdf_filename, normalized.pdf_bytes, filename))

    # Gap 189: same classify → lock → charge path as /upload (shared helpers).
    billable = count_billable_uploads(
        db_session, context.tenant_id, [data for _, data, _orig in payloads]
    )
    tenant = charge_free_quota(db_session, context.tenant_id, billable)

    batch_id = uuid4()
    # Gap 464: the directory watcher is the same manual door with a different
    # file picker, so its runs carry the same trigger.
    record_ingestion_batch(
        db_session,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        trigger="manual",
        file_count=len(payloads),
        flow_direction="INBOUND",
    )
    job_ids = []
    for filename, file_bytes, orig_name in payloads:
        job_id = await _ingest_single_file(
            file_bytes, filename, [], batch_id, tenant, context, db_session,
            original_filename=orig_name,
        )
        job_ids.append(job_id)

    return {
        "watcher_id": watcher_id,
        "status": "completed",
        "batch_id": batch_id,
        "files_found": len(source_filenames),
        "files_queued": len(job_ids),
        "job_ids": job_ids,
    }


async def _sse_aclose(resource, label: str) -> None:
    """Best-effort aclose/close for Redis client or pubsub — never raises (Gap 187)."""
    if resource is None:
        return
    closer = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if asyncio.iscoroutine(result):
            await result
    except Exception as e:
        logger.warning("SSE %s cleanup failed for resource: %s", label, e)


async def sse_event_generator(batch_id: str):
    """Async generator to yield Redis pub/sub messages as Server-Sent Events.

    Gap 233: Keep stream open for multi-file batches until all invoices finish.
    """
    # Query all active invoices in the batch at the start of the stream
    tracking_invoices = {}
    try:
        with Session(engine) as session:
            db_invoices = session.exec(
                select(Invoice.id, Invoice.status).where(
                    Invoice.batch_id == UUID(batch_id),
                    invoice_not_deleted()
                )
            ).all()
            tracking_invoices = {str(inv.id): inv.status for inv in db_invoices}
    except Exception as e:
        logger.warning("Failed to initialize invoice status tracking for batch %s: %s", batch_id, e)

    channel = f"invoice.update.{batch_id}"
    redis_client = None
    pubsub = None
    try:
        redis_client = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    data = message["data"]
                    yield f"data: {data}\n\n"

                    # Terminate stream when all invoices in the batch have reached a terminal status
                    try:
                        payload = json.loads(data)
                        status = payload.get("status")
                        inv_id = payload.get("invoice_id")
                        
                        if status in ["COMPLETED", "AUDIT_REQUIRED", "FAILED", "DUPLICATE"]:
                            if inv_id and inv_id in tracking_invoices:
                                tracking_invoices[inv_id] = status
                            elif len(tracking_invoices) == 1:
                                # Single invoice batch: update its status directly even if invoice_id is missing/None
                                only_id = list(tracking_invoices.keys())[0]
                                tracking_invoices[only_id] = status
                            else:
                                # Fallback: query the DB to refresh all statuses if invoice_id is missing/unmatched
                                with Session(engine) as session:
                                    db_invoices = session.exec(
                                        select(Invoice.id, Invoice.status).where(
                                            Invoice.batch_id == UUID(batch_id),
                                            invoice_not_deleted()
                                        )
                                    ).all()
                                    for inv in db_invoices:
                                        tracking_invoices[str(inv.id)] = inv.status
                        
                        # Break loop only when ALL tracked invoices are terminal
                        if tracking_invoices and all(st in ["COMPLETED", "AUDIT_REQUIRED", "FAILED", "DUPLICATE"] for st in tracking_invoices.values()):
                            break
                    except Exception as e:
                        logger.warning("Error processing SSE message status check: %s", e)
                else:
                    # Heartbeat keep-alive to keep connection open
                    yield ": keep-alive\n\n"

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("SSE subscription disconnected for batch %s", batch_id)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception as e:
                    logger.warning("SSE pubsub unsubscribe failed for batch %s: %s", batch_id, e)
                await _sse_aclose(pubsub, "pubsub")
                pubsub = None
    finally:
        await _sse_aclose(redis_client, "client")


@router.get("/stream/{batch_id}")
async def stream_invoice_status(
    batch_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Streaming response endpoint yielding real-time processing updates for a batch.

    Gap 186: refuse the Redis subscription unless this tenant owns at least one
    invoice in the batch — same 404 shape as get_invoice_status so a foreign
    batch_id is indistinguishable from a missing one.
    """
    owned = db_session.exec(
        select(Invoice.id).where(
            Invoice.batch_id == batch_id,
            Invoice.tenant_id == context.tenant_id,
            invoice_not_deleted(),
        )
    ).first()
    if not owned:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied.",
        )
    return StreamingResponse(sse_event_generator(str(batch_id)), media_type="text/event-stream")


@router.get("/status/{job_id}")
async def get_invoice_status(
    job_id: UUID,
    # Feature 25 (Gap 335): readonly-scope API key or Clerk session. Polling the
    # status of a job you submitted is the other half of upload.
    context: TenantContext = Depends(get_tenant_or_api_key_context),
    db_session: Session = Depends(get_db_session)
):
    """Polling status endpoint returning DB record details for a single invoice."""
    statement = select(Invoice).where(
        Invoice.id == job_id,
        Invoice.tenant_id == context.tenant_id,
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found or access denied.")
    # BE Gap 731: a file whose enqueue failed sits at PROCESSING and is
    # recovered by services/invoice_reconciliation.py, which retries it and only
    # gives up after MAX attempts. That design is right and is NOT changed here:
    # marking the invoice FAILED at the first failed send would abandon a file
    # that is safely stored and would otherwise have been picked up.
    #
    # What was wrong is that the caller could not tell the difference. An
    # integration polling this endpoint saw PROCESSING either way and waited
    # forever. `queued` is that missing fact, read from the same column the
    # sweep keys on -- no new state, no new writer.
    return {
        "id": invoice.id,
        "status": invoice.status,
        "vendor_name": invoice.vendor_name,
        "grand_total": invoice.grand_total,
        # FE Gap 183: this endpoint hand-builds its dict, so the ingestion
        # status ledger had no currency to render and hardcoded "$".
        "currency": invoice.currency,
        "alerts": invoice.sa_alerts,
        "queued": invoice.last_enqueued_at is not None,
        "queued_at": invoice.last_enqueued_at,
        "processing_attempts": invoice.processing_attempts,
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
    batch_id: UUID | None = None,
    # BE Gap 723: which side of the ledger. Default INBOUND -- every caller that
    # exists today (this app's Invoices screen, and any integration written
    # against the old behaviour) gets exactly what it got before. OUTBOUND and
    # ALL are opt-in. Typed as a Literal so an unknown value is a 422 from
    # FastAPI rather than a string reaching the query.
    flow_direction: Literal["INBOUND", "OUTBOUND", "ALL"] = "INBOUND",
    # BE Gap 724: "what finished since I last looked". Reads the EXISTING
    # `completed_at` column -- no new column, no trigger, no migration for the
    # data itself. Deliberately NOT a general "updated_since": completed_at is
    # written once, when processing finishes, and a later human decision
    # (approve/reject) is announced by webhook instead. Documented as such, so
    # nobody builds a sync on a promise this filter does not make.
    #
    # BE Gap 730: timestamps are UTC. A value carrying an offset is converted to
    # UTC before it is compared; a value without one is taken as UTC already.
    # Stored timestamps are naive `datetime.utcnow()` values, so an offset-aware
    # bound would otherwise raise inside the comparison on Postgres and silently
    # shift the window by the offset on SQLite -- the same query giving two
    # different answers per backend is the worst of the available failures.
    completed_since: datetime | None = None,
    # Feature 25 (Gap 335): readonly-scope API key or Clerk session.
    context: TenantContext = Depends(get_tenant_or_api_key_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Fetches a page of matching records for the requesting tenant, most recent
    first. Supports pagination, date ranges, status/vendor filters, search
    tags, and batch_id.
    """
    # BE Gap 728: `status` and `vendor_name` do not mean the same thing on the
    # two sides of the ledger, so combining either with ALL returns a mixture
    # that reads as one set and is not.
    #   status   PAID inbound = we paid a supplier.
    #            PAID outbound = a customer paid us.
    #   vendor_name  inbound = the supplier. Outbound it carries the ISSUER,
    #            which on the tenant's own invoice is the tenant (BE Gap 467).
    # A caller asking for ALL+PAID gets money facing both ways in one list and
    # no field in the row that says which. Refused rather than documented: a
    # silent wrong number in someone's ledger is worse than a 400 they read
    # once. Both filters stay fully available per direction.
    if flow_direction == "ALL" and (status or status_in or vendor_name):
        raise HTTPException(
            # The literal, not `status.HTTP_400_BAD_REQUEST`: inside THIS handler
            # `status` is the query parameter declared above, which shadows
            # fastapi's `status` module. Written the usual way this line raised
            # AttributeError on None and the caller got a 500 for what is a
            # plainly explainable 400. The parameter name is part of the
            # published API and cannot be renamed to free the word.
            status_code=400,
            detail=(
                "status, status_in and vendor_name mean different things for INBOUND and "
                "OUTBOUND invoices, so they cannot be combined with flow_direction=ALL. "
                "Ask for one direction at a time, or drop the filter."
            ),
        )

    conditions = [
        Invoice.tenant_id == context.tenant_id,
    ]
    # BE Gap 723. ALL omits the predicate entirely rather than listing both
    # values: the tenant+flow+created_at index is still usable on a tenant-only
    # prefix, and an IN over the full domain would only mislead a reader into
    # thinking it filters something.
    if flow_direction != "ALL":
        conditions.append(Invoice.flow_direction == flow_direction)
    # BE Gap 724: `>=`, not `>`. A caller re-sending its last watermark gets the
    # boundary row again, which is safe (ids are stable, the row is identical);
    # `>` would silently drop anything that completed inside the same
    # microsecond as the watermark.
    if completed_since:
        # BE Gap 730, see the parameter. `utcoffset()` is None for a naive value.
        if completed_since.utcoffset() is not None:
            completed_since = completed_since.astimezone(timezone.utc).replace(tzinfo=None)
        conditions.append(Invoice.completed_at >= completed_since)
    if batch_id:
        conditions.append(Invoice.batch_id == batch_id)
    if start_date:
        conditions.append(func.date(Invoice.created_at) >= start_date)
    if end_date:
        conditions.append(func.date(Invoice.created_at) <= end_date)
    if status:
        conditions.append(Invoice.status == status)
    if status_in:
        conditions.append(Invoice.status.in_([s.strip() for s in status_in.split(",") if s.strip()]))
    if vendor_name:
        conditions.append(Invoice.vendor_name == vendor_name)

    # BE Gap 729 WITHDRAWN 2026-09-23. An `include_deleted` parameter was added
    # here to let an integration read deleted invoices back. It could never
    # return a row: Gap 460 (2026-09-08) made deletion a HARD delete on the
    # founder's rule that a deleted record is gone from every store, and
    # `services/invoice_deletion.py` states that nothing writes `deleted_at` any
    # more. The filter below is therefore inert rather than wrong, and stays
    # unconditional exactly as it was.
    #
    # "Which invoices were removed?" is answered by the `DELETE_INVOICE` audit
    # row that `delete_invoice_rows()` writes and BE Gap 550 deliberately keeps
    # -- build that read if an integration asks, rather than reviving this.
    conditions.append(invoice_not_deleted())

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


@router.get("/batches")
async def list_batches(
    response: Response,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Lists upload batches for the current tenant, grouped by batch_id.
    Returns: batch_id, created_at (min invoice created_at), invoice_count,
    flow_direction, status_summary.
    """
    # count distinct batch_ids for pagination X-Total-Count
    total_statement = (
        select(func.count(func.distinct(Invoice.batch_id)))
        .where(
            Invoice.tenant_id == context.tenant_id,
            Invoice.batch_id != None,
            invoice_not_deleted()
        )
    )
    total = db_session.exec(total_statement).one()
    response.headers["X-Total-Count"] = str(total)

    # get page of batches
    batches_statement = (
        select(
            Invoice.batch_id,
            func.min(Invoice.created_at).label("created_at"),
            func.count(Invoice.id).label("invoice_count"),
            Invoice.flow_direction
        )
        .where(
            Invoice.tenant_id == context.tenant_id,
            Invoice.batch_id != None,
            invoice_not_deleted()
        )
        .group_by(Invoice.batch_id, Invoice.flow_direction)
        .order_by(func.min(Invoice.created_at).desc())
        .offset(offset)
        .limit(limit)
    )
    batch_rows = db_session.exec(batches_statement).all()

    batch_ids = [row[0] for row in batch_rows if row[0]]
    if not batch_ids:
        return []

    # Get status breakdown for the batch_ids
    invoices_statement = (
        select(Invoice.batch_id, Invoice.status, func.count(Invoice.id))
        .where(Invoice.batch_id.in_(batch_ids), invoice_not_deleted())
        .group_by(Invoice.batch_id, Invoice.status)
    )
    invoice_rows = db_session.exec(invoices_statement).all()

    status_counts = {}
    for b_id, status_val, count in invoice_rows:
        if b_id not in status_counts:
            status_counts[b_id] = {}
        status_counts[b_id][status_val] = count

    result = []
    for b_id, created_at, invoice_count, flow_direction in batch_rows:
        result.append({
            "batch_id": b_id,
            "created_at": created_at,
            "invoice_count": invoice_count,
            "flow_direction": flow_direction,
            "status_summary": status_counts.get(b_id, {})
        })
    return result


@router.delete("/batches/{batch_id}")
async def rollback_batch(
    batch_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Hard-deletes all invoices in the specified batch, acting as a rollback
    (Gap 460 reopened 2026-09-08: was a soft delete since Gap 192).

    Gap 397 (Feature 27 task R6): **and every `Document` row from the same
    batch**, dropping their Chroma chunks as it goes. E10 (Gap 381) made a batch
    upload heterogeneous -- a classified delivery note leaves `invoice` entirely
    and becomes a `documents` row carrying the same `batch_id` -- and this
    endpoint kept querying only `Invoice`. So "rollback the batch" silently rolled
    back part of it, and a mixed upload of ten files where three classified as
    non-invoices left those three live and indexed after the user had been told
    the batch was undone. A batch of *only* non-invoice documents was worse
    still: zero rows matched, so the endpoint returned 404 -- "no such batch" --
    about a batch that plainly existed.

    Gap 460: chunks are dropped for both halves now. The earlier asymmetry (Gap
    239 retained invoice chunks for a restore path) ended because no restore
    path was ever built while deleted invoices kept surfacing in RAG chat.
    """
    if context.db_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user required to rollback a batch.",
        )

    query = select(Invoice).where(
        Invoice.batch_id == batch_id,
        Invoice.tenant_id == context.tenant_id,
        invoice_not_deleted()
    )
    invoices = db_session.exec(query).all()

    # Gap 397: the other half of the batch. Tenant-scoped and soft-delete aware
    # on the same three predicates, so a cross-tenant batch_id finds nothing here
    # for the same reason it finds nothing above.
    documents = db_session.exec(
        select(Document).where(
            Document.batch_id == batch_id,
            Document.tenant_id == context.tenant_id,
            Document.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).all()

    # The 404 now asks about the BATCH, not about one of its two tables -- a
    # batch that classified entirely to non-invoice documents is a real batch.
    if not invoices and not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active invoices or documents found for the specified batch_id."
        )

    # Gap 460 (reopened 2026-09-08): hard delete, both halves. Captured before
    # the rows go, because the purge below needs ids and blob paths.
    invoice_refs = [(inv.id, inv.file_path) for inv in invoices]
    document_refs = [(doc.id, doc.file_path) for doc in documents]
    for invoice in invoices:
        delete_invoice_rows(
            db_session,
            invoice,
            actor_user_id=context.db_user_id,
            actor_role=context.role,
            extra_details={"batch_rollback": True, "batch_id": str(batch_id)},
        )
    for document in documents:
        # No AuditLog row: `AuditLog.invoice_id` is non-nullable and a document id
        # in it would be a lie by column name (Gap 398 tracks giving documents
        # their own audit trail). Logged instead, so the action is not invisible.
        delete_document_rows(db_session, document)

    await run_in_threadpool(db_session.commit)

    # After the commit, each step swallowing its own errors: an unreachable
    # Chroma or blob store must not turn a completed rollback into a 500 the
    # caller would retry against rows that are already gone.
    for inv_id, path in invoice_refs:
        purge_invoice_stores(inv_id, context.tenant_id, path)
    for doc_id, path in document_refs:
        purge_document_stores(doc_id, context.tenant_id, path)
    if documents:
        logger.info(
            "Batch rollback %s also deleted %d document(s), their blobs and chunks.",
            batch_id, len(document_refs),
        )

    return {
        "success": True,
        "count": len(invoices),
        # Reported separately rather than folded into `count`: an existing caller
        # reads `count` as "invoices rolled back" and must keep meaning that.
        "document_count": len(documents),
    }


@router.get("/{invoice_id}", response_model=Invoice)
async def get_invoice(
    invoice_id: UUID,
    # Feature 25 (Gap 335): readonly-scope API key or Clerk session.
    context: TenantContext = Depends(get_tenant_or_api_key_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Fetches a single invoice details. Enforces tenant isolation.
    """
    query = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        invoice_not_deleted(),
    )
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
    # Feature 25 (Gap 335): readonly-scope API key or Clerk session.
    context: TenantContext = Depends(get_tenant_or_api_key_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Streams the secure PDF file retrieved from storage (Azure or Local fallback).
    Enforces tenant isolation.
    """
    query = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        invoice_not_deleted(),
    )
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


# BE Gap 732: the statuses at which a file may no longer be swapped. The test is
# "has anyone acted on it", not "has extraction finished" -- COMPLETED and
# AUDIT_REQUIRED are both still replaceable, because nobody has decided anything
# yet and the whole point is to fix the mistake before they do. PROCESSING is
# allowed too: a wrong file noticed while it is still extracting is the most
# common case of all, and re-enqueueing simply supersedes the running job.
# BE Gap 739: "CANCELLED" was in this set and is not a status this system has
# -- nothing anywhere assigns it, so the entry matched nothing and only told the
# next reader that such a status exists. Every name below was checked against
# what the code actually writes: PAID/REJECTED/SENT are assigned as literals;
# REVIEW_LATER and NEEDS_RESUBMISSION arrive through `routers/audit.py`'s
# `invoice.status = target_status`, validated against `_FINALIZABLE_FROM_STATUSES`.
REPLACEABLE_BLOCKED_STATUSES = frozenset(
    {"PAID", "REJECTED", "SENT", "REVIEW_LATER", "NEEDS_RESUBMISSION"}
)


@router.post("/{invoice_id}/file", status_code=status.HTTP_200_OK)
async def replace_invoice_file(
    invoice_id: UUID,
    file: UploadFile = File(...),
    # BE Gap 736: NOT the upload gate. That one admits a readonly key by
    # design, and replacing a file is not uploading one -- it destroys the
    # extracted state of an invoice a reviewer may be mid-way through.
    context: TenantContext = Depends(require_can_load_and_actions_scope),
    db_session: Session = Depends(get_db_session),
):
    """Attach a corrected PDF to an existing invoice and extract it again.

    WHY THE INVOICE ID IS KEPT. Uploading the right file as a NEW invoice is
    what a caller has to do today, and it leaves two rows: the wrong one sitting
    in the queue forever (a key cannot delete it) and a new one whose id the
    customer's ERP has never seen. Replacing in place keeps the id the customer
    already stored, so nothing on their side has to be re-linked, and leaves one
    row where there is one invoice.

    WHAT IT DOES NOT DO. It does not touch a decided invoice. Once somebody has
    approved, rejected or sent it, the record is evidence of a decision and the
    document underneath it must not change silently -- that needs an Admin
    reopen, in the app, where the consequence is visible.

    WHAT IT CLEARS. Every extracted field, the alerts and the line items, all of
    which describe the OLD document. Leaving them would mean a row whose numbers
    came from one file and whose PDF is another -- the exact confusion this gap
    exists to remove. `created_at`, tags, batch and the audit trail survive: the
    invoice's history is real, only its contents were wrong.
    """
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied.",
        )

    if invoice.status in REPLACEABLE_BLOCKED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This invoice is {invoice.status} and its file can no longer be replaced. "
                "An Admin can reopen it in the app first."
            ),
        )

    fname = (file.filename or "invoice.pdf").strip() or "invoice.pdf"
    try:
        raw = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file {fname}: {exc}",
        )

    # Same door as the upload route: sniffed, page-capped, image-converted.
    try:
        normalized = normalize_upload(fname, raw)
    except (UnsupportedUploadError, ImageTooLargeError, PdfTooManyPagesError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail)

    new_bytes = normalized.pdf_bytes
    new_hash = hashlib.sha256(new_bytes).hexdigest()

    # Re-sending the file that is already attached is a no-op, not an error: a
    # retried request must not cost a second extraction.
    if new_hash == invoice.file_hash:
        return {
            "id": invoice.id,
            "status": invoice.status,
            "replaced": False,
            "detail": "The uploaded file is identical to the one already attached.",
        }

    # BE Gap 738: the file must not already be in this tenant's system.
    #
    # Every other door checks the incoming hash against invoices AND documents
    # and turns a match into a DUPLICATE row. This one did not, so a customer
    # correcting invoice A could attach a PDF they had already uploaded as
    # invoice B and end up holding two live invoices, different ids, same
    # document, no alert on either -- which is how one bill gets paid twice.
    #
    # Refused rather than marked. Upload is CREATING a record, so a DUPLICATE
    # row is a truthful account of what arrived; replace is MUTATING a record
    # that already exists, and there is no coherent way to stamp an existing
    # invoice as a duplicate of another without destroying whatever it
    # legitimately was. Nothing is changed and nothing is charged.
    #
    # Same union, same order, tenant predicate inside each side, as
    # `_ingest_single_file` and `services/billing_quota.py`. Three copies of one
    # rule already disagreed once (BE Gap 385); keeping the shape identical is
    # what makes the next divergence visible.
    clashing_invoice = db_session.exec(
        select(Invoice).where(
            Invoice.tenant_id == context.tenant_id,
            Invoice.file_hash == new_hash,
            Invoice.id != invoice_id,
        )
    ).first()
    clashing_document = None
    if not clashing_invoice:
        clashing_document = db_session.exec(
            select(Document).where(
                Document.tenant_id == context.tenant_id,
                Document.file_hash == new_hash,
            )
        ).first()

    if clashing_invoice or clashing_document:
        if clashing_invoice:
            where = (
                f"invoice {clashing_invoice.invoice_number or clashing_invoice.id} "
                f"(ID: {clashing_invoice.id})"
            )
        else:
            doc_type = (clashing_document.doc_type or "document").replace("_", " ").lower()
            where = f"a {doc_type} already on file (document ID: {clashing_document.id})"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"That file is already in this workspace as {where}. Nothing was changed. "
                "Attaching it here as well would leave two records for one document."
            ),
        )

    # BE Gap 735: a replacement is a billable event, on the same rule and
    # through the same function as an upload.
    #
    # This endpoint re-runs Document Intelligence and a full LLM extraction on
    # the new file. Left uncharged it was not merely lost revenue, it was a way
    # around the 402 entirely: `charge_free_quota()` is the only thing stopping
    # a free-plan tenant at zero remaining, and it is called from the upload
    # doors alone. A tenant could spend their last credit on one invoice and
    # then process unlimited unrelated documents through it by replacing the
    # file over and over.
    #
    # `count_billable_uploads()` carries the rule rather than a second copy of
    # it: new bytes the tenant has never had processed are billable once, and
    # re-attaching a file they already paid for is free -- the same answer the
    # upload path gives for the same file. The identical-hash case returned
    # above, so a retried request still costs nothing.
    #
    # Charged BEFORE the blob write, matching `_ingest_files`. The alternative
    # ordering trades a possible stale charge for a possible orphaned blob;
    # keeping both doors in one order matters more than the choice between them,
    # because a billing rule that depends on which endpoint you came through is
    # the kind of thing nobody can reason about later.
    billable = count_billable_uploads(db_session, context.tenant_id, [new_bytes])
    charge_free_quota(db_session, context.tenant_id, billable)

    # The blob is written BEFORE the row changes, exactly as the upload path
    # does it: a storage failure must leave the invoice as it was, still
    # pointing at a file that exists.
    try:
        new_path = await run_in_threadpool(
            upload_pdf_to_blob_storage, new_bytes, str(context.tenant_id), str(invoice_id)
        )
    except StorageUploadError as exc:
        logger.error("Storage upload failed replacing invoice %s: %s", invoice_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is temporarily unavailable. Nothing was changed. Try again.",
        )

    previous_status = invoice.status
    previous_hash = invoice.file_hash

    invoice.file_path = new_path
    invoice.file_hash = new_hash
    invoice.status = "PROCESSING"
    invoice.completed_at = None
    invoice.sa_alerts = []
    invoice.items = []
    invoice.vendor_name = None
    invoice.invoice_number = None
    invoice.invoice_date = None
    invoice.due_date = None
    invoice.grand_total = None
    invoice.tax_amount = None
    invoice.currency = None
    invoice.po_number = None
    # BE Gap 740: this pointer describes the OLD document, exactly like every
    # extracted field above it, and was the one that got left behind. A
    # DUPLICATE row whose file is replaced keeps a genuinely different document
    # now, so "I am a copy of invoice X" stops being true the moment the bytes
    # change -- and Gap 195 added this column precisely so subscribers and the
    # alert UI could dereference it, which means a stale value is followed, not
    # ignored. The matching `duplicate` alert is already dropped by the
    # `sa_alerts = []` above; this is its structured half.
    invoice.duplicate_of_invoice_id = None
    invoice.processing_attempts = 0
    invoice.last_enqueued_at = None

    db_session.add(invoice)
    db_session.add(
        AuditLog(
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            actor_user_id=context.db_user_id,
            actor_role=context.role,
            action="REPLACE_INVOICE_FILE",
            details={
                "previous_status": previous_status,
                "previous_file_hash": previous_hash,
                "new_file_hash": new_hash,
                "filename": normalized.pdf_filename,
                **context.trail_identity(),
            },
            timestamp=datetime.utcnow(),
        )
    )
    await run_in_threadpool(db_session.commit)
    db_session.refresh(invoice)

    # Re-extract. Deliberately the same dispatch the upload path uses, including
    # its failure behaviour: if the queue send fails the row stays PROCESSING
    # and the reconciliation sweep picks it up, and `GET /status/{id}` reports
    # `queued: false` in the meantime (BE Gap 731).
    await _enqueue_extraction(invoice, invoice.batch_id, invoice.file_path, context, db_session)

    return {
        "id": invoice.id,
        "status": invoice.status,
        "replaced": True,
        "previous_status": previous_status,
    }


@router.delete("/{invoice_id}")
async def delete_invoice(
    invoice_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Hard-deletes an invoice (Gap 460, reopened and fixed properly 2026-09-08;
    reverses Gap 192's soft delete -- see services/invoice_deletion.py for the
    record of why). The row, its audit history, comparison rows and every
    back-reference go in one transaction, replaced by a single DELETE_INVOICE
    summary audit row; after the commit the PDF blob, the Chroma chunks and the
    tenant's cached chat answers are purged, each best-effort. Enforces tenant
    isolation; an unknown or already-deleted id is a 404.
    """
    if context.db_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user required to delete an invoice.",
        )

    query = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
    )
    invoice = db_session.exec(query).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )

    file_path = invoice.file_path
    delete_invoice_rows(
        db_session, invoice, actor_user_id=context.db_user_id, actor_role=context.role
    )
    await run_in_threadpool(db_session.commit)

    purge_invoice_stores(invoice_id, context.tenant_id, file_path)

    return {"success": True}
