"""
Gap 126: the missing half of Feature 15's event set -- `outbound_invoice.overdue`.

Every other webhook event in this codebase fires from a real status transition,
right after the commit that made it (`queue_worker/handlers.py`,
`routers/audit.py`, `routers/outbound_invoices.py`). Overdue has no such moment:
it is a *virtual*, read-time computation (Feature 7.1/8.1 -- an OUTBOUND invoice
still in SENT whose `due_date` is in the past), derived on every list/metrics
query and never written to `Invoice.status`. Nothing in the system "happens"
when an invoice crosses its due date, so nothing could ever dispatch the event,
and a tenant could subscribe to `outbound_invoice.overdue` and simply never
receive anything.

This module is the something-that-happens: a sweep that runs on a schedule
(`scripts/sweep_outbound_overdue.py`, driven by the Container Apps job in
`infra/modules/compute/scheduled-job.bicep`), finds invoices that have crossed
their due date, and fires the event once per invoice.

Two deliberate design choices:

* **The read-time rule is not duplicated, it is reused.** `is_overdue` in
  routers/outbound_dashboard.py is `status == "SENT" and due_date is not None
  and due_date < today`. `OVERDUE_STATUS` plus the predicate in
  `find_overdue_invoices()` below is the same rule expressed as SQL, and must
  stay that way -- if the two ever disagree, a tenant gets a webhook for an
  invoice their dashboard does not show as overdue (or vice versa).
* **Overdue is still never persisted as a status.** The sweep writes only
  `Invoice.overdue_notified_at`, the "already fired" marker. Turning overdue
  into a stored status would fork the definition in two places and change what
  every existing status filter returns; that stays out of scope here exactly as
  it has been everywhere else in this codebase.

Idempotency is the whole point of `overdue_notified_at`: an invoice that stays
unpaid is overdue on every subsequent day, so without a marker a daily sweep
would re-deliver the same event to the same endpoint every day until it was
paid.
"""
import logging
from datetime import date, datetime
from uuid import UUID

from sqlmodel import Session, select

from models import Invoice
from services.webhooks import dispatch_webhook_event

logger = logging.getLogger(__name__)

OVERDUE_EVENT_TYPE = "outbound_invoice.overdue"

# The only status an invoice can be overdue *from*. Mirrors the read-time rule
# in routers/outbound_dashboard.py -- an invoice that has been PAID, or is still
# UPLOADED/awaiting review, is not overdue no matter what its due_date says.
OVERDUE_STATUS = "SENT"


def find_overdue_invoices(
    session: Session,
    today: date | None = None,
    tenant_id: UUID | None = None,
) -> list[Invoice]:
    """Every OUTBOUND invoice that has newly crossed its due date and has not
    already had its overdue event fired.

    Strictly `due_date < today`, matching the dashboard: an invoice due *today*
    is not overdue yet.
    """
    today = today or date.today()

    conditions = [
        Invoice.flow_direction == "OUTBOUND",
        Invoice.status == OVERDUE_STATUS,
        Invoice.due_date.is_not(None),          # type: ignore[union-attr]
        Invoice.due_date < today,               # type: ignore[operator]
        Invoice.overdue_notified_at.is_(None),  # type: ignore[union-attr]
    ]
    if tenant_id:
        conditions.append(Invoice.tenant_id == tenant_id)

    return list(session.exec(select(Invoice).where(*conditions)).all())


def sweep_overdue_invoices(
    session: Session,
    today: date | None = None,
    now: datetime | None = None,
    tenant_id: UUID | None = None,
) -> list[Invoice]:
    """Fire `outbound_invoice.overdue` once for each newly-overdue invoice and
    return the invoices that were notified. Commits per invoice.

    `overdue_notified_at` is stamped and committed *before* the dispatch, not
    after, which makes this at-most-once rather than at-least-once. That is the
    right trade here: `dispatch_webhook_event()` already swallows its own
    delivery failures (with its own 3-attempt retry inside), so a "dispatch
    first, mark only on success" ordering could not distinguish a failed
    delivery from a successful one anyway -- it would only add a crash window in
    which a *delivered* event gets re-delivered on the next run. Re-notifying an
    endpoint about the same invoice is the failure mode this marker exists to
    prevent.

    The marker is stamped even when the tenant has no webhook subscriptions at
    all (dispatch is then a no-op): it records "this invoice's overdue moment
    has been processed", which keeps the candidate set from growing without
    bound and gives a future scheduled consumer (e.g. an AR follow-up job) a
    real timestamp for when the invoice first went overdue.
    """
    today = today or date.today()
    now = now or datetime.utcnow()

    notified: list[Invoice] = []
    candidates = find_overdue_invoices(session, today=today, tenant_id=tenant_id)

    for invoice in candidates:
        invoice.overdue_notified_at = now
        session.add(invoice)
        session.commit()

        try:
            dispatch_webhook_event(
                session,
                invoice.tenant_id,
                OVERDUE_EVENT_TYPE,
                {
                    "invoice_id": str(invoice.id),
                    "status": invoice.status,
                    "customer_name": invoice.customer_name,
                    "grand_total": invoice.grand_total,
                    # Two fields the transition-driven events have no use for
                    # but an overdue consumer always wants: which date was
                    # missed, and by how much.
                    "due_date": str(invoice.due_date) if invoice.due_date else None,
                    "days_overdue": (today - invoice.due_date).days if invoice.due_date else None,
                    "currency": invoice.currency,
                },
            )
        except Exception as e:
            # Same contract as every other hook point: a webhook problem must
            # never abort the sweep and starve the invoices after this one.
            logger.error("Overdue webhook dispatch failed for invoice %s: %s", invoice.id, e)

        notified.append(invoice)
        logger.info(
            "Overdue sweep: fired %s for invoice %s (tenant=%s, due %s).",
            OVERDUE_EVENT_TYPE, invoice.id, invoice.tenant_id, invoice.due_date,
        )

    logger.info("Overdue sweep complete: %s invoice(s) notified.", len(notified))
    return notified
