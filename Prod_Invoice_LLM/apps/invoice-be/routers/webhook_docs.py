"""
Gap 184 (part 3): the outbound webhook payload schemas, declared so Swagger UI
renders them.

These are documentation-only route declarations. FastAPI's `app.webhooks` router
contributes to the generated OpenAPI document (the "webhooks" section, OpenAPI
3.1) without mounting anything the server can be called on -- the operations
below describe requests *this platform sends to the integrator*, which is
exactly what the Security → API Docs tab needs to show alongside the inbound
REST routes. The handler bodies are never executed.

Payload shape is taken from services/webhooks.build_delivery_body(), which is
the single place the wire format is built, and the event list from
routers/webhooks.ALLOWED_EVENT_TYPES. Both are copied here by hand, so both can
drift -- and both had, by the time BE Gap 737 checked: the envelope had gained
two fields, the payloads three, a whole event type had been added and the
signature advice had been superseded, none of it reflected here. A subscriber
cannot tell "this platform does not send that" from "we forgot to write it
down", so tests/test_webhook_docs_match_reality.py now fails when this file and
that allowlist disagree.

(The Gap 184 tracker entry guessed at `invoice.failed` and `invoice.overdue`,
which do not exist as events in this codebase; `invoice.rejected` and
`outbound_invoice.overdue` are their nearest real counterparts.)
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class InboundInvoiceEventData(BaseModel):
    invoice_id: str = Field(description="UUID of the invoice this event is about.")
    status: str = Field(description="The invoice status at the moment the event fired.")
    vendor_name: str | None = Field(default=None, description="Extracted vendor name, when known.")
    grand_total: float | None = Field(default=None, description="Extracted invoice total, when known.")
    # Gap 215/557: really sent, on every event that knows an amount.
    currency: str | None = Field(
        default=None,
        description=(
            "ISO currency code for `grand_total`. Null when extraction did not "
            "establish one -- deliberately never defaulted to USD, so do not "
            "read a null as dollars. On a blended multi-currency tenant that "
            "assumption is the difference between 40000 rupees and 40000 dollars."
        ),
    )
    # Gap 558. Only on invoice.rejected.
    reject_reason: str | None = Field(
        default=None,
        description="Why the auditor rejected it. Present only on `invoice.rejected`.",
    )


class OutboundInvoiceEventData(BaseModel):
    invoice_id: str = Field(description="UUID of the outbound invoice this event is about.")
    status: str = Field(description="The invoice status at the moment the event fired.")
    customer_name: str | None = Field(default=None, description="Customer the invoice was addressed to.")
    grand_total: float | None = Field(default=None, description="Invoice total, when known.")
    currency: str | None = Field(
        default=None,
        description=(
            "ISO currency code for `grand_total`. Null when unknown; never "
            "defaulted to USD."
        ),
    )
    # Feature 15 Task 15.6: the overdue sweep carries two fields the
    # transition-driven events have no use for.
    due_date: str | None = Field(
        default=None,
        description="Due date (ISO). Present only on `outbound_invoice.overdue`.",
    )
    days_overdue: int | None = Field(
        default=None,
        description="Days past due. Present only on `outbound_invoice.overdue`.",
    )


class InboundInvoiceEvent(BaseModel):
    """Envelope delivered for an inbound (accounts-payable) invoice event."""
    # Gap 555 put both on the wire and nobody wrote them down here, so an
    # integrator reading this page had no way to know a retried delivery is
    # identifiable -- and would post the same invoice into their ledger twice.
    event_id: str = Field(
        description="UUIDv4, stable across retries of the same event. De-duplicate on this."
    )
    occurred_at: str = Field(
        description="ISO-8601 UTC timestamp of when the event occurred."
    )
    event: str = Field(description="Event type, e.g. 'invoice.completed'.")
    data: InboundInvoiceEventData


class OutboundInvoiceEvent(BaseModel):
    """Envelope delivered for an outbound (accounts-receivable) invoice event."""
    event_id: str = Field(
        description="UUIDv4, stable across retries of the same event. De-duplicate on this."
    )
    occurred_at: str = Field(
        description="ISO-8601 UTC timestamp of when the event occurred."
    )
    event: str = Field(description="Event type, e.g. 'outbound_invoice.sent'.")
    data: OutboundInvoiceEventData


# Gap 564 added a replay-resistant second signature and this note went on
# telling integrators to verify the first one. Anyone who followed the page
# built a verifier that accepts an intercepted body replayed back at them
# later -- exactly the attack V2 exists to stop. The note now leads with V2 and
# names V1 as the compatibility header it has become.
_SIGNATURE_NOTE = (
    "Delivered as an HTTP POST to every enabled subscription registered for this "
    "event type (see POST /api/v1/webhooks).\n\n"
    "**Verify `X-Webhook-Signature-V2`.** It is HMAC-SHA256, keyed with the "
    "subscription secret, over `X-Webhook-Timestamp` + `\".\"` + the raw body. "
    "Reject the delivery if that timestamp is older than your tolerance (5 "
    "minutes is typical): binding the signature to a timestamp is what stops a "
    "captured request being replayed at you later. `X-Webhook-Signature` covers "
    "the body alone, has no such binding, and is kept only for backwards "
    "compatibility -- prefer V2.\n\n"
    "`X-InvoiceEQ-Event-Id` repeats the envelope\'s `event_id` and is stable "
    "across retries. Key your de-duplication on it: delivery is at-least-once, "
    "so you WILL see the same event twice.\n\n"
    "Respond 2xx to acknowledge. A non-2xx or a timeout is retried 3 times with "
    "exponential backoff, and 10 consecutive failures auto-disable the "
    "subscription (visible under Settings -> Webhooks)."
)


def _description(summary: str) -> str:
    """
    Build an operation description.

    Passed as a `description=` kwarg rather than written as a docstring because
    a docstring must be a single string literal: a triple-quoted literal
    concatenated with `_SIGNATURE_NOTE` via `+` is an ordinary expression
    statement and leaves `__doc__` as None, so the delivery/signature contract
    would silently fail to render in /docs.
    """
    return f"{summary}\n\n{_SIGNATURE_NOTE}"


# BE Gap 727: these two were being DELIVERED but not documented, so a
# subscriber reading this page would build a handler that silently ignored
# them. Both are inbound-lifecycle events like the four below.
@router.post("invoice.processing", description=_description(
    "The file was accepted and queued; extraction has started. Sent once per "
    "upload, before any result is known."))
def invoice_processing(body: InboundInvoiceEvent):
    ...


@router.post("invoice.duplicate", description=_description(
    "The file matched one already ingested for this workspace, so no new "
    "invoice was created. `duplicate_of_invoice_id` points at the original "
    "(null when the match was a non-invoice document, in which case "
    "`duplicate_of_document_id` carries it instead)."))
def invoice_duplicate(body: InboundInvoiceEvent):
    ...


@router.post("invoice.completed", description=_description(
    "Extraction finished and the invoice needs no human review."))
def invoice_completed(body: InboundInvoiceEvent):
    ...


@router.post("invoice.audit_required", description=_description(
    "Extraction finished but confidence/validation rules flagged the invoice for audit."))
def invoice_audit_required(body: InboundInvoiceEvent):
    ...


@router.post("invoice.approved", description=_description(
    "An auditor marked the inbound invoice as approved/paid."))
def invoice_approved(body: InboundInvoiceEvent):
    ...


@router.post("invoice.rejected", description=_description(
    "An auditor rejected the inbound invoice. `data.reject_reason` carries why."))
def invoice_rejected(body: InboundInvoiceEvent):
    ...


# Gap 558 added this event and never documented it, which left the one event
# that UNDOES another one invisible. A subscriber that already posted an
# approval into its own ledger needs this to reverse it; with the page silent,
# their handler drops it and their books keep an approval we no longer hold.
@router.post("invoice.reopened", description=_description(
    "An Admin reopened an invoice that had been approved or rejected, returning "
    "it to AUDIT_REQUIRED. The earlier `invoice.approved` or `invoice.rejected` "
    "you received for this `invoice_id` no longer reflects our state -- reverse "
    "whatever you recorded for it."))
def invoice_reopened(body: InboundInvoiceEvent):
    ...


@router.post("outbound_invoice.sent", description=_description(
    "An outbound invoice was confirmed and sent to the customer."))
def outbound_invoice_sent(body: OutboundInvoiceEvent):
    ...


@router.post("outbound_invoice.overdue", description=_description(
    "An outbound invoice passed its due date without payment."))
def outbound_invoice_overdue(body: OutboundInvoiceEvent):
    ...


@router.post("outbound_invoice.approved", description=_description(
    "An outbound invoice was marked approved/paid."))
def outbound_invoice_approved(body: OutboundInvoiceEvent):
    ...
