"""
Gap 184 (part 3): the outbound webhook payload schemas, declared so Swagger UI
renders them.

These are documentation-only route declarations. FastAPI's `app.webhooks` router
contributes to the generated OpenAPI document (the "webhooks" section, OpenAPI
3.1) without mounting anything the server can be called on -- the operations
below describe requests *this platform sends to the integrator*, which is
exactly what the Security → API Docs tab needs to show alongside the inbound
REST routes. The handler bodies are never executed.

Payload shape is taken verbatim from services/webhooks.dispatch_webhook_event(),
which sends `{"event": <type>, "data": {...}}` and signs the raw body with
HMAC-SHA256 into the `X-Webhook-Signature` header. The event list is
routers/webhooks.ALLOWED_EVENT_TYPES -- deliberately the real seven, not the
three names the Gap 184 tracker entry guessed at (`invoice.failed` and
`invoice.overdue` do not exist as events in this codebase; `invoice.rejected`
and `outbound_invoice.overdue` are their nearest real counterparts).
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class InboundInvoiceEventData(BaseModel):
    invoice_id: str = Field(description="UUID of the invoice this event is about.")
    status: str = Field(description="The invoice status at the moment the event fired.")
    vendor_name: str | None = Field(default=None, description="Extracted vendor name, when known.")
    grand_total: float | None = Field(default=None, description="Extracted invoice total, when known.")


class OutboundInvoiceEventData(BaseModel):
    invoice_id: str = Field(description="UUID of the outbound invoice this event is about.")
    status: str = Field(description="The invoice status at the moment the event fired.")
    customer_name: str | None = Field(default=None, description="Customer the invoice was addressed to.")
    grand_total: float | None = Field(default=None, description="Invoice total, when known.")


class InboundInvoiceEvent(BaseModel):
    """Envelope delivered for an inbound (accounts-payable) invoice event."""
    event: str = Field(description="Event type, e.g. 'invoice.completed'.")
    data: InboundInvoiceEventData


class OutboundInvoiceEvent(BaseModel):
    """Envelope delivered for an outbound (accounts-receivable) invoice event."""
    event: str = Field(description="Event type, e.g. 'outbound_invoice.sent'.")
    data: OutboundInvoiceEventData


_SIGNATURE_NOTE = (
    "Delivered as an HTTP POST to every enabled subscription registered for this "
    "event type (see POST /api/v1/webhooks). The raw request body is signed with "
    "HMAC-SHA256 using the subscription secret and sent as `X-Webhook-Signature`; "
    "verify it before trusting the payload. Respond 2xx to acknowledge -- a "
    "non-2xx or timeout is retried 3 times with exponential backoff, and 10 "
    "consecutive failures auto-disable the subscription."
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
    "An auditor rejected the inbound invoice."))
def invoice_rejected(body: InboundInvoiceEvent):
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
