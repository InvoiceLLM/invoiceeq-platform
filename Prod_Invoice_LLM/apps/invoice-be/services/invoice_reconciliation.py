"""
FE Gaps 81 + 84: making a stalled or failed invoice converge to a real terminal
state instead of sitting on its upload status forever.

Two distinct failures produced the same visible symptom ("stuck on PROCESSING /
UPLOADED"), and they need different halves of a fix:

* **Gap 84 -- the worker processed it and hit a real error.** Both queue
  handlers' `except` blocks published `{"status": "FAILED"}` to the ephemeral
  Redis SSE channel and re-raised, but never wrote anything to the `Invoice`
  row. The DB status had only ever been set once, at upload. So a permanent,
  already-logged failure was visible *only* to a browser that happened to have
  the SSE stream open at that exact instant; a reload, a second tab, or simply
  not being on the page showed "Processing" forever. Fixed at the source, in
  the handlers themselves (`mark_invoice_failed` below).
* **Gap 81 -- the worker never touched the message at all.** Nothing supervises
  the worker and nothing notices an invoice aging past a reasonable SLA, so a
  crash between upload and the next restart leaves the row silently frozen.
  Fixed here, by a sweep that re-enqueues stalled work and eventually gives up
  on it.

Why a sweep and not just "restart the worker": re-enqueueing is the part that
makes recovery *automatic*. The 2026-07-29 invoice that motivated Gap 81 was
still stuck four days later specifically because its queue message was gone --
several worker restarts in between drained everything else and never touched
it. No amount of process supervision recovers a row whose message no longer
exists; only something that reads the database and re-enqueues can.

FAILED is a real terminal status, not a display-only string: `routers/invoices.py`'s
SSE generator already treats it as terminal, and the FE's `StatusTable`,
`FilterBar` and `RecentInvoicesTable` already render it. What was missing was
anything that ever *persisted* it.
"""
import json
import logging
from datetime import datetime, timedelta
from uuid import UUID

from azure.storage.queue import QueueClient
from sqlmodel import Session, select

from config import get_settings
from models import Invoice
from services.invoice_visibility import invoice_not_deleted

logger = logging.getLogger(__name__)

QUEUE_NAME = "extraction-tasks-queue"

# Statuses that mean "the pipeline still owes this invoice an answer". Inbound
# persists PROCESSING at upload and outbound persists UPLOADED; the rest are
# published over SSE only today, but are included so this stays correct if any
# of them is ever persisted.
STUCK_STATUSES = ("PROCESSING", "PROCESSING_OCR", "EXTRACTING_DATA", "UPLOADED")

FAILED_STATUS = "FAILED"


def mark_invoice_failed(
    session: Session,
    invoice: Invoice,
    reason: str,
    alert_type: str = "processing_failed",
) -> None:
    """
    Durably record that this invoice's processing failed. Commits.

    Called from both queue handlers' except blocks (Gap 84) and from the sweep
    when an invoice has exhausted its retries (Gap 81). Deliberately preserves
    any alerts already on the row and appends rather than replacing -- an
    invoice can fail *after* verification alerts were raised, and losing those
    would discard the only diagnostic the auditor has.
    """
    alerts = list(invoice.sa_alerts or [])
    alerts.append({"type": alert_type, "message": reason})

    invoice.status = FAILED_STATUS
    invoice.sa_alerts = alerts
    invoice.completed_at = datetime.utcnow()
    session.add(invoice)
    session.commit()


def _enqueue(invoice: Invoice) -> bool:
    """Put a fresh processing message on the queue for this invoice.

    Mirrors the payloads built by routers/invoices.py::_ingest_single_file and
    routers/outbound_invoices.py::upload_outbound_invoice -- same queue, same
    task names, same kwargs -- so a re-enqueued invoice takes the identical code
    path as a first-time upload rather than a parallel one that could drift.
    """
    settings = get_settings()
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        logger.error(
            "Cannot re-enqueue invoice %s: AZURE_STORAGE_CONNECTION_STRING is not set.",
            invoice.id,
        )
        return False

    task = (
        "process_outbound_invoice"
        if (invoice.flow_direction or "INBOUND").upper() == "OUTBOUND"
        else "process_invoice"
    )
    payload = {
        "task": task,
        "kwargs": {
            "batch_id": str(invoice.batch_id) if invoice.batch_id else str(invoice.id),
            "file_path": invoice.file_path,
            "tenant_id": str(invoice.tenant_id),
        },
    }

    try:
        queue_client = QueueClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING, QUEUE_NAME
        )
        queue_client.send_message(json.dumps(payload))
        return True
    except Exception as e:
        # Gap 81's third fix implication: a real enqueue failure must be loud.
        # This is logged at ERROR (not the warning the upload path used to use)
        # precisely because nobody was watching the quiet version.
        logger.error("Failed to re-enqueue invoice %s (task=%s): %s", invoice.id, task, e)
        return False


def find_stuck_invoices(
    session: Session,
    now: datetime | None = None,
    tenant_id: UUID | None = None,
) -> list[Invoice]:
    """Every invoice still in a non-terminal status past the stall threshold.

    Age is measured from `last_enqueued_at` when set, falling back to
    `created_at` -- so an invoice re-enqueued 30 seconds ago is not immediately
    re-enqueued again, while rows predating this feature (which have no
    `last_enqueued_at`) are still evaluated correctly from their upload time.
    """
    settings = get_settings()
    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=settings.INVOICE_STUCK_AFTER_MINUTES)

    conditions = [Invoice.status.in_(STUCK_STATUSES), invoice_not_deleted()]  # type: ignore[attr-defined]
    if tenant_id:
        conditions.append(Invoice.tenant_id == tenant_id)

    candidates = session.exec(select(Invoice).where(*conditions)).all()
    return [inv for inv in candidates if (inv.last_enqueued_at or inv.created_at) < cutoff]


def reconcile_stuck_invoices(
    session: Session,
    now: datetime | None = None,
    tenant_id: UUID | None = None,
) -> dict[str, list[UUID]]:
    """
    Re-enqueue stalled invoices, and fail the ones that have used up their
    retries. Returns {"requeued": [...], "failed": [...]}.

    Idempotent by construction: a requeued invoice gets a fresh
    `last_enqueued_at`, so it is out of scope again until the threshold passes;
    a failed one leaves STUCK_STATUSES entirely.
    """
    settings = get_settings()
    now = now or datetime.utcnow()
    requeued: list[UUID] = []
    failed: list[UUID] = []

    for invoice in find_stuck_invoices(session, now=now, tenant_id=tenant_id):
        if invoice.processing_attempts >= settings.INVOICE_MAX_REPROCESS_ATTEMPTS:
            mark_invoice_failed(
                session,
                invoice,
                reason=(
                    f"Processing never completed after {invoice.processing_attempts} "
                    f"re-queue attempt(s). Last status was {invoice.status}. "
                    "Re-upload the file, or check the queue worker."
                ),
                alert_type="processing_timeout",
            )
            failed.append(invoice.id)
            logger.warning(
                "Reconciliation gave up on invoice %s after %s attempt(s) -- marked FAILED.",
                invoice.id, invoice.processing_attempts,
            )
            continue

        if not _enqueue(invoice):
            # Leave the row alone rather than burning an attempt on a failure
            # that was ours (no connection string / queue unreachable), not the
            # invoice's -- the next sweep should try again.
            continue

        invoice.processing_attempts += 1
        invoice.last_enqueued_at = now
        session.add(invoice)
        session.commit()
        requeued.append(invoice.id)
        logger.info(
            "Reconciliation re-enqueued invoice %s (status=%s, attempt %s).",
            invoice.id, invoice.status, invoice.processing_attempts,
        )

    return {"requeued": requeued, "failed": failed}


def force_requeue(session: Session, invoice_id: UUID, now: datetime | None = None) -> bool:
    """
    Re-enqueue one specific invoice regardless of age or attempt count.

    Exists for operator recovery of an already-stuck record -- notably the
    2026-07-29 outbound invoice from Gap 81, whose queue message is genuinely
    gone and which no age-based sweep can help if it has already exhausted its
    attempts. Resets `processing_attempts` to 0 so the normal sweep will still
    look after it afterwards.
    """
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        logger.error("force_requeue: invoice %s not found.", invoice_id)
        return False

    if not _enqueue(invoice):
        return False

    invoice.processing_attempts = 0
    invoice.last_enqueued_at = now or datetime.utcnow()
    if invoice.status == FAILED_STATUS:
        # Put it back in flight so the poll/SSE paths track it again. Inbound
        # and outbound have different in-flight statuses (see the upload
        # routers) -- use each one's own, not a shared invented value.
        invoice.status = (
            "UPLOADED" if (invoice.flow_direction or "INBOUND").upper() == "OUTBOUND" else "PROCESSING"
        )
    session.add(invoice)
    session.commit()
    logger.info("force_requeue: invoice %s re-enqueued, status=%s.", invoice_id, invoice.status)
    return True
