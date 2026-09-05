import json
import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4, UUID
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Response, status
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from typing import Optional

from pydantic import BaseModel, Field

from dependencies import (
    get_db_session,
    require_can_load,
    # Gap 405: per-user Send Invoices visibility, layered on top of can_load
    # below -- both must pass to upload an outbound invoice.
    require_can_send_invoices,
    # Feature 25 (Gap 335): gates confirm-send / mark-paid, which had NO
    # permission gate at all before this -- see the note on each handler.
    require_actions_scope,
    TenantContext,
)
from models import Invoice, Tenant, User
from services.invoice_builder import (
    BuildRequest,
    builder_intent,
    default_build_from_source,
    totals_for,
)
from services.pdf_render import (
    harvest_branding,
    number_renderings,
    render_invoice,
)
from services.storage import download_pdf_from_storage
from services.billing_quota import charge_free_quota, count_billable_uploads
from services.ingestion_batches import record_ingestion_batch
from services.file_intake import (
    ImageTooLargeError,
    UnsupportedUploadError,
    normalize_upload,
)
from services.storage import upload_pdf_to_blob_storage
from services.staff_notify import notify_auditor_action
from services.invoice_visibility import invoice_not_deleted
from azure.storage.queue import QueueClient
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outbound-invoices", tags=["Outbound Invoices"])


class OutboundNotifyPayload(BaseModel):
    notify_emails: Optional[list[str]] = Field(
        default=None,
        description="Subset of the tenant outbound authorized set to notify (Gap 125). Never customers.",
    )


def _submitter_email_from_context(db_session: Session, context: TenantContext) -> str | None:
    if not context.db_user_id:
        return None
    user = db_session.get(User, context.db_user_id)
    if not user or not user.email:
        return None
    return str(user.email).strip().lower() or None


def _dispatch_outbound_webhook(db_session: Session, invoice: Invoice, event_type: str) -> None:
    """Feature 15 (Task 15.4): fires right after the commit that actually
    changed the status. `outbound_invoice.overdue` still has no call site here,
    and correctly so -- overdue is a virtual, read-time-only computation
    (Feature 7.1/8.1), not a status transition, so there is no commit in this
    router to hang it off. Gap 126 gave it the scheduled trigger it needed
    instead: services/outbound_overdue.py, run daily by
    scripts/sweep_outbound_overdue.py. Overdue is still never written to
    `Invoice.status`."""
    try:
        from services.webhooks import dispatch_webhook_event
        dispatch_webhook_event(db_session, invoice.tenant_id, event_type, {
            "invoice_id": str(invoice.id),
            "status": invoice.status,
            "customer_name": invoice.customer_name,
            "grand_total": invoice.grand_total,
            # Gap 215: same fix as the inbound dispatch sites -- a bare
            # grand_total is ambiguous on a blended multi-currency tenant.
            "currency": invoice.currency or "USD",
        })
    except Exception as we:
        logger.error("Webhook dispatch failed for outbound invoice %s: %s", invoice.id, we)


async def _store_and_enqueue_outbound(
    db_session: Session,
    context: TenantContext,
    tenant: Tenant,
    pdf_bytes: bytes,
    filename: str,
    *,
    source_invoice_id: UUID | None = None,
    builder_intent: dict | None = None,
    notes: str | None = None,
) -> dict:
    """The tail every outbound ingestion door shares: quota, blob, row, queue.

    Feature 17 (task 17.4) factored this out of `upload_outbound_invoice()` so
    that `POST /outbound-invoices/build` creates an invoice through *exactly*
    the same path an upload does — same Gap 343 quota charge in the same order,
    same blob location, same `UPLOADED` status, same `process_outbound_invoice`
    message, same Gap 81 `last_enqueued_at` stamp. A builder-created invoice is
    an ordinary outbound invoice from here on, which is why nothing downstream
    (the worker, RAG indexing, webhooks, Drive archive, the ops workbooks) needs
    to know this feature exists.

    `pdf_bytes` is always a PDF: the upload door normalises images to PDF
    before calling (Feature 28), and the builder renders one. `tenant` is the
    already-loaded row the caller checked `send_invoices_enabled` on — it is not
    re-read here, but `charge_free_quota()` deliberately re-reads it with
    `populate_existing=True` (Gap 343) so the allowance is never evaluated
    against a stale copy.

    The three keyword arguments are NULL for uploads and set only by the
    builder. BE Gap 467 added `notes`: the builder knows the notes block it is
    about to print, so the column is stamped at creation rather than waiting for
    the worker to read it back off the PDF — an upload has no such knowledge and
    passes None, leaving the extraction pass (which now reads `notes`) as the
    only writer on that door.
    """
    invoice_id = uuid4()
    batch_id = uuid4()

    # Gap 343: the AR upload door charged nothing, so a Free Tier tenant at
    # free_invoices_remaining=0 could keep creating invoices through it. Same
    # helpers, same order and same 402 "Limit reached" as
    # routers/invoices.py::upload_invoices() -- classify the hash first so a
    # re-upload of a file already on this tenant never burns quota, then take the
    # `SELECT tenant … FOR UPDATE` and decrement. Placed before the blob upload
    # so a refused upload stores nothing.
    #
    # Note the Tenant row was already loaded by the caller for the
    # send_invoices_enabled check; charge_free_quota() re-reads it with
    # populate_existing=True (Gap 343, see services/billing_quota.py) precisely
    # so this call site cannot evaluate the allowance against that earlier, now
    # stale copy.
    billable = count_billable_uploads(db_session, context.tenant_id, [pdf_bytes])
    charge_free_quota(db_session, context.tenant_id, billable)

    try:
        file_path = await run_in_threadpool(
            upload_pdf_to_blob_storage, pdf_bytes, str(context.tenant_id), str(invoice_id)
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to store file {filename}: {str(e)}")

    db_invoice = Invoice(
        id=invoice_id,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        file_path=file_path,
        flow_direction="OUTBOUND",
        status="UPLOADED",
        submitted_by_email=_submitter_email_from_context(db_session, context),
        source_invoice_id=source_invoice_id,
        builder_intent=builder_intent,
        notes=notes,
    )
    db_session.add(db_invoice)
    await run_in_threadpool(db_session.commit)
    db_session.refresh(db_invoice)

    # Gap 464: one AR upload is one run. Recorded after the Invoice row commits
    # rather than at the mint above, because everything between them (quota
    # refusal, blob failure) raises -- a run row written first would be a
    # History line for an upload that never happened.
    record_ingestion_batch(
        db_session,
        tenant_id=context.tenant_id,
        batch_id=batch_id,
        trigger="manual",
        file_count=1,
        flow_direction="OUTBOUND",
    )

    try:
        settings = get_settings()
        if settings.AZURE_STORAGE_CONNECTION_STRING:
            queue_client = QueueClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
            )
            queue_client.send_message(json.dumps({
                "task": "process_outbound_invoice",
                "kwargs": {"batch_id": str(batch_id), "file_path": file_path, "tenant_id": str(context.tenant_id)},
            }))
            # Gap 81: see routers/invoices.py -- the reconciliation sweep
            # measures staleness from this stamp, not from created_at.
            db_invoice.last_enqueued_at = datetime.utcnow()
            db_invoice.processing_attempts = 1
            db_session.add(db_invoice)
            await run_in_threadpool(db_session.commit)
        else:
            logger.error(
                "AZURE_STORAGE_CONNECTION_STRING missing -- outbound invoice %s was stored but never "
                "queued and will sit at UPLOADED until the reconciliation sweep re-enqueues it.",
                invoice_id,
            )
    except Exception as e:
        # Gap 81: promoted from warning. Azurite/Azure accepting an upload while
        # the queue send fails is precisely the silent-forever case this gap was
        # about -- the request still returns 201, so the log line is the only
        # signal that exists.
        logger.error(
            "Failed to dispatch outbound extraction queue task for invoice %s -- it will remain at "
            "UPLOADED until the reconciliation sweep re-enqueues it: %s",
            invoice_id, e,
        )

    return {"batch_id": str(batch_id), "invoice_id": str(invoice_id)}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_outbound_invoice(
    file: UploadFile = File(...),
    # Feature 1.1 (Task 1.1.2): AR-side mirror of the inbound upload gate.
    #
    # This comment used to end "confirm-send / mark-paid below are deliberately
    # left ungated in this pass". That is no longer true and the sentence is
    # removed rather than left to mislead: Feature 25 (Gap 335) gated both of
    # them on `actions` scope / can_audit. Leaving those two routes open to any
    # authenticated user turned out to be a real hole, not a scoping decision
    # worth preserving.
    #
    # This upload route itself is deliberately NOT dual-credential in Phase 0:
    # widening the AR ingestion surface to API keys was not requested, and the
    # inbound /invoices/upload is the ingestion path integrations actually
    # asked for. Revisit with Gap 336 if an AR integration needs it.
    context: TenantContext = Depends(require_can_load),
    # Gap 405: per-user Send Invoices visibility, on top of can_load above --
    # both are required. can_load alone would let anyone who can upload
    # inbound invoices also upload outbound ones regardless of an Admin's
    # per-user grant, which is exactly the granular control this gap exists
    # to add. A second Depends param (not a combined check) matches this
    # codebase's existing one-permission-per-dependency convention.
    _send_check: TenantContext = Depends(require_can_send_invoices),
    db_session: Session = Depends(get_db_session),
):
    """Feature 2.1, Task 2.1.5: upload the tenant's own invoice to be sent to
    a customer. Gated on the Send Invoices toggle -- upload-only, no in-app
    invoice creation/generation (see feature_17_invoice_builder.md)."""
    fname = (file.filename or "").strip() or "invoice.pdf"

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    if not tenant.send_invoices_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Send Invoices is not enabled for this tenant. Enable it in Settings first.",
        )

    try:
        file_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to read file {fname}: {str(e)}")

    # Feature 28: one normalisation call replaces the old filename-suffix +
    # %PDF-header pair. A PDF passes through byte-identical; an accepted image
    # becomes a PDF here, so the blob write, the hash and everything downstream
    # still only ever see a PDF. Placed before the quota charge below so a
    # refused file never burns quota (Gap 343's ordering rule).
    try:
        normalized = normalize_upload(fname, file_bytes)
    except (UnsupportedUploadError, ImageTooLargeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail)
    fname = normalized.pdf_filename
    file_bytes = normalized.pdf_bytes

    # Feature 17 (task 17.4): quota, blob, row and queue now live in
    # `_store_and_enqueue_outbound()` above, shared verbatim with
    # `POST /outbound-invoices/build`. Everything before this line -- the
    # tenant/send-invoices gate and Feature 28's normalisation -- is upload-only
    # validation and stays here. Behaviour is unchanged.
    return await _store_and_enqueue_outbound(
        db_session, context, tenant, file_bytes, fname,
    )


# ---------------------------------------------------------------------------
# Feature 17 — Invoice Builder (clone & edit)
# ---------------------------------------------------------------------------
#
# Three endpoints, one shared preparation path. Everything that decides
# correctness here is deterministic code and none of it is a prompt rule
# (CONVENTIONS hard rule 3): the totals arithmetic
# (`services/invoice_builder.compute_totals`), the number formatting
# (`format_like`), the invoice-number suggestion and the duplicate-number
# refusal below. The LLM sees the generated PDF only after it has been created,
# through the ordinary outbound extraction pipeline, exactly as it sees an
# upload.
#
# BE Gap 462 (2026-09-05): there is no longer a renderer to choose. The
# substitution path and its `plan_render_mode()` are deleted — every clone goes
# through `render_invoice()` with the source's harvested branding.

#: Founder decision D4. `OVERDUE` is a virtual, read-time condition (SENT past
#: due_date, Feature 7.1/8.1) and is never written to `Invoice.status`, so
#: accepting `SENT` is what makes an overdue invoice cloneable; the literal is
#: accepted too in case a future status write ever appears.
CLONE_ELIGIBLE_STATUSES = ("VERIFIED", "SENT", "PAID", "OVERDUE")


def _load_clone_source(db_session: Session, context: TenantContext, invoice_id: UUID) -> Invoice:
    """The source-eligibility rules, in one place for all three endpoints.

    404 for anything that is not this tenant's live OUTBOUND invoice — the same
    answer for "does not exist" and "belongs to someone else", so the endpoint
    cannot be used to probe another tenant's ids. 409, with a reason, for a real
    invoice that simply may not be cloned: a `NEEDS_REVIEW` source is refused
    because its own extracted values have not been trusted yet and cloning them
    would propagate an unreviewed reading (D4).
    """
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")
    if (invoice.status or "").upper() not in CLONE_ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot build from an invoice with status '{invoice.status}'. "
                "Only VERIFIED, SENT, PAID or overdue invoices can be cloned."
            ),
        )
    if not invoice.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source invoice has no stored PDF to build from.",
        )
    return invoice


def _assert_invoice_number_unused(
    db_session: Session,
    tenant_id: UUID,
    customer_name: str | None,
    invoice_number: str | None,
    exclude_invoice_id: UUID | None = None,
) -> None:
    """Founder decision D5: refuse a number already used for this customer.

    The same predicate `queue_worker/outbound_handlers.py` uses for its
    `duplicate_invoice_number` alert — case-insensitive, whitespace-normalised,
    scoped to this tenant's OUTBOUND rows — but applied *before* the invoice is
    created rather than after it has been rendered, stored, charged for and
    extracted. Auto-increment stays a suggestion; this is the only hard rule
    about invoice numbers.
    """
    number = (invoice_number or "").strip()
    customer = (customer_name or "").strip()
    if not number or not customer:
        return
    conditions = [
        Invoice.tenant_id == tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        func.lower(func.trim(Invoice.invoice_number)) == number.lower(),
        func.lower(func.trim(Invoice.customer_name)) == customer.lower(),
        invoice_not_deleted(),
    ]
    if exclude_invoice_id is not None:
        conditions.append(Invoice.id != exclude_invoice_id)
    if db_session.exec(select(Invoice).where(*conditions)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice number already used for this customer",
        )


def _number_style_from_source(source_pdf: bytes, grand_total: float | None) -> str:
    """A sample of how the source printed money, for `format_like()`.

    Found by looking for the source's own grand total on page 1 in each
    plausible rendering and returning whichever one is actually printed; falls
    back to plain `1234.56` when the total is unknown or not found, which is
    the safe default rather than a guessed locale.
    """
    if grand_total is None:
        return "1234.56"
    try:
        import fitz

        with fitz.open(stream=source_pdf, filetype="pdf") as doc:
            if doc.page_count:
                page = doc[0]
                for rendering in number_renderings(Decimal(str(grand_total))):
                    if page.search_for(rendering):
                        return rendering
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not sample the source number style: %s", exc)
    return f"{Decimal(str(grand_total)):.2f}"


async def _render_build(db_session: Session, context: TenantContext, req: BuildRequest) -> tuple[bytes, Invoice, dict]:
    """Shared by preview and create: validate, recompute, render.

    Returns the PDF bytes, the source row and the `builder_intent` payload.

    BE Gap 462 (2026-09-05): this used to pick between an in-place substitution
    on the source PDF and a structured re-render, on row count alone, and raise
    `UnlocatedFieldsError` → 422 when substitution could not find a changed
    value in the source page. That fired on the *normal* clone (same rows, new
    dates, new totals) and told the user to add or remove a row to force the
    other renderer. Both the planner and the 422 are gone; `render_invoice()`
    handles any row count and any edit, so there is no refusal path left here.
    """
    source = _load_clone_source(db_session, context, req.source_invoice_id)
    _assert_invoice_number_unused(
        db_session, context.tenant_id, req.customer_name, req.invoice_number,
    )

    # The server always recomputes; a client-supplied total is never trusted and
    # is not even part of `BuildRequest`. BE Gap 463: `totals_for()` rather than
    # `compute_totals(items, tax)` directly, so the widened discount/tax/
    # deduction inputs cannot be forgotten at one of the two call sites.
    totals = totals_for(req)

    try:
        source_pdf = await run_in_threadpool(download_pdf_from_storage, source.file_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read the source invoice PDF: {e}",
        )

    branding = await run_in_threadpool(
        harvest_branding, source_pdf, [source.invoice_number, source.customer_name],
    )
    # The source's own grand total is the sample that tells the renderer
    # whether this tenant prints `1,250.00` or `1.250,00`.
    number_style = _number_style_from_source(source_pdf, source.grand_total)
    pdf_bytes = await run_in_threadpool(
        render_invoice, req, totals, branding, number_style,
    )

    return pdf_bytes, source, builder_intent(req, totals)


@router.get("/{invoice_id}/build-defaults")
async def get_build_defaults(
    invoice_id: UUID,
    context: TenantContext = Depends(require_can_load),
    _send_check: TenantContext = Depends(require_can_send_invoices),
    db_session: Session = Depends(get_db_session),
):
    """Feature 17: the prefill for a clone — everything copied, the invoice
    number incremented and the dates rolled forward by the source's own payment
    term. Same permission pair as the upload door (Gap 405)."""
    source = _load_clone_source(db_session, context, invoice_id)
    return default_build_from_source(source, date.today())


@router.post("/build/preview")
async def preview_built_invoice(
    req: BuildRequest,
    context: TenantContext = Depends(require_can_load),
    _send_check: TenantContext = Depends(require_can_send_invoices),
    db_session: Session = Depends(get_db_session),
):
    """Feature 17: render exactly what `/build` would create, and persist
    nothing — no `Invoice` row, no blob, no quota charge. The user sees the real
    output before committing to it."""
    pdf_bytes, _source, _intent = await _render_build(db_session, context, req)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/build", status_code=status.HTTP_201_CREATED)
async def build_outbound_invoice(
    req: BuildRequest,
    context: TenantContext = Depends(require_can_load),
    _send_check: TenantContext = Depends(require_can_send_invoices),
    db_session: Session = Depends(get_db_session),
):
    """Feature 17: create the cloned invoice.

    Renders the same PDF `/build/preview` just showed, then hands it to the
    shared `_store_and_enqueue_outbound()` — so it is charged, stored, queued
    and processed exactly like an upload (D2: a built invoice is billable), and
    lands on the Sending ledger as an ordinary outbound invoice carrying its
    lineage (`source_invoice_id`) and its intent (`builder_intent`).
    """
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    if not tenant.send_invoices_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Send Invoices is not enabled for this tenant. Enable it in Settings first.",
        )

    pdf_bytes, source, intent = await _render_build(db_session, context, req)

    return await _store_and_enqueue_outbound(
        db_session, context, tenant, pdf_bytes,
        f"{(req.invoice_number or 'invoice').strip()}.pdf",
        source_invoice_id=source.id,
        builder_intent=intent,
        # BE Gap 467: onto the row's own column, not only into `builder_intent`
        # — that is what lets a clone of this clone inherit the notes block.
        notes=req.notes,
    )


@router.put("/{invoice_id}/confirm-send", status_code=status.HTTP_200_OK)
async def confirm_send_outbound_invoice(
    invoice_id: UUID,
    payload: OutboundNotifyPayload | None = None,
    # Feature 25 (Gap 335). This route previously depended on bare
    # `get_tenant_context` with NO permission gate whatsoever: any authenticated
    # user -- including one with zero granted permissions -- could mark a
    # tenant's outbound invoice SENT, fire the outbound webhook and trigger the
    # staff notification email. Every other financial-finalization route in the
    # product requires can_audit; this one and mark-paid below were the two that
    # did not. Found during Gap 335's route audit, fixed here because this exact
    # line was being rewritten anyway. Now: humans need can_audit (same rule and
    # same 403 text as the audit routers), and an API key needs `actions` scope.
    context: TenantContext = Depends(require_actions_scope),
    db_session: Session = Depends(get_db_session),
):
    """Feature 2.1 + Gap 125: VERIFIED/NEEDS_REVIEW → SENT. Staff notify only
    (registered outbound set); never emails the end customer."""
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

    if invoice.status not in ("VERIFIED", "NEEDS_REVIEW"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm-send an invoice with status '{invoice.status}'. Must be VERIFIED or NEEDS_REVIEW.",
        )

    notify_emails = (payload.notify_emails if payload else None)
    try:
        # Validate before mutating so a bad list doesn't leave a half-sent state.
        from services.staff_notify import validate_notify_emails
        validate_notify_emails(
            db_session, tenant_id=invoice.tenant_id, email_set="outbound", notify_emails=notify_emails,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve

    invoice.status = "SENT"
    invoice.sent_at = datetime.utcnow()
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    _dispatch_outbound_webhook(db_session, invoice, "outbound_invoice.sent")
    email_notify = notify_auditor_action(
        db_session, invoice, action_label="Confirm Send (SENT)", notify_emails=notify_emails,
    )

    return {
        "success": True,
        "status": invoice.status,
        "sent_at": invoice.sent_at.isoformat(),
        "email_notify": email_notify,
    }


@router.put("/{invoice_id}/mark-paid", status_code=status.HTTP_200_OK)
async def mark_outbound_invoice_paid(
    invoice_id: UUID,
    payload: OutboundNotifyPayload | None = None,
    # Feature 25 (Gap 335): same previously-ungated route as confirm-send above
    # -- see that handler's note. Marking an invoice PAID is a financial
    # finalization and now requires can_audit (humans) or `actions` scope (keys).
    context: TenantContext = Depends(require_actions_scope),
    db_session: Session = Depends(get_db_session),
):
    """SENT → PAID + optional staff notify (Gap 125)."""
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

    if invoice.status != "SENT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot mark an invoice with status '{invoice.status}' as paid. Must be SENT.",
        )

    notify_emails = (payload.notify_emails if payload else None)
    try:
        from services.staff_notify import validate_notify_emails
        validate_notify_emails(
            db_session, tenant_id=invoice.tenant_id, email_set="outbound", notify_emails=notify_emails,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve

    invoice.status = "PAID"
    invoice.paid_at = datetime.utcnow()
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    _dispatch_outbound_webhook(db_session, invoice, "outbound_invoice.approved")
    email_notify = notify_auditor_action(
        db_session, invoice, action_label="Mark Paid", notify_emails=notify_emails,
    )

    return {
        "success": True,
        "status": invoice.status,
        "paid_at": invoice.paid_at.isoformat(),
        "email_notify": email_notify,
    }
