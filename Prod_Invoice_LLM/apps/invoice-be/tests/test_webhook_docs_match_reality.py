"""BE Gap 737: the Docs Hub must describe the webhooks we actually send.

`routers/webhook_docs.py` is a hand-written copy of two things it does not
import: the event allowlist in `routers/webhooks.py` and the envelope built in
`services/webhooks.py`. Copies drift, and this one had -- by the time anyone
looked, `invoice.reopened` had been delivered for weeks without appearing on the
page, and the envelope had grown `event_id` and `occurred_at` that no integrator
was told about.

The failure mode is quiet and lands on the customer, not on us: a subscriber
cannot distinguish "InvoiceEQ does not send that" from "InvoiceEQ forgot to
document it", so they write a handler that drops a real event, and nothing
anywhere reports an error. These tests turn that into a red build.

They deliberately compare against the REAL objects rather than a second list of
expected names -- a third copy would just be one more thing to forget.
"""
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from routers import webhook_docs
from routers.webhooks import ALLOWED_EVENT_TYPES
from services.webhooks import build_delivery_body


def _documented_event_types() -> set[str]:
    """Event types the Docs Hub renders.

    Each documentation-only operation is declared as `@router.post("<event>")`,
    so the route path IS the event name. FastAPI normalises it with a leading
    slash, which is stripped here.
    """
    return {route.path.lstrip("/") for route in webhook_docs.router.routes}


def test_every_delivered_event_is_documented():
    """An event a tenant can subscribe to but cannot read about is an event
    their integration will silently ignore."""
    undocumented = ALLOWED_EVENT_TYPES - _documented_event_types()
    assert not undocumented, (
        f"These event types can be subscribed to but are not documented in "
        f"routers/webhook_docs.py: {sorted(undocumented)}. A subscriber reading "
        f"Settings -> Security -> API Docs would never know to handle them."
    )


def test_nothing_is_documented_that_is_never_sent():
    """The opposite drift, and the more embarrassing one: an integrator builds
    and tests a handler for an event that will never arrive."""
    phantom = _documented_event_types() - ALLOWED_EVENT_TYPES
    assert not phantom, (
        f"These event types are documented but are not in ALLOWED_EVENT_TYPES, "
        f"so nothing can ever subscribe to them or receive them: {sorted(phantom)}."
    )


def test_the_documented_envelope_matches_the_bytes_we_actually_post():
    """`build_delivery_body()` is the only place the wire format exists. The
    documented envelope must name every key it produces -- an undocumented
    `event_id` is how a subscriber ends up with no de-duplication key and books
    the same invoice twice on a retry."""
    real_keys = set(
        json.loads(
            build_delivery_body("invoice.completed", {"invoice_id": "x", "status": "COMPLETED"})
        )
    )
    documented_keys = set(webhook_docs.InboundInvoiceEvent.model_fields)

    assert real_keys <= documented_keys, (
        f"Delivered but undocumented envelope keys: {sorted(real_keys - documented_keys)}"
    )
    assert documented_keys <= real_keys, (
        f"Documented but never delivered envelope keys: {sorted(documented_keys - real_keys)}"
    )


def test_the_outbound_envelope_matches_too():
    real_keys = set(
        json.loads(
            build_delivery_body("outbound_invoice.sent", {"invoice_id": "x", "status": "SENT"})
        )
    )
    assert set(webhook_docs.OutboundInvoiceEvent.model_fields) == real_keys


def test_the_event_id_is_a_uuid_and_the_timestamp_parses():
    """Both are documented as things a subscriber should key behaviour on --
    de-duplication on one, staleness checks on the other -- so the documented
    format has to be the real one."""
    envelope = json.loads(build_delivery_body("invoice.completed", {"invoice_id": "x"}))

    UUID(envelope["event_id"])  # raises if it is not a UUID
    parsed = datetime.fromisoformat(envelope["occurred_at"])
    assert parsed.tzinfo is not None, "occurred_at is documented as UTC; it must carry an offset"
    assert parsed.tzinfo.utcoffset(parsed) == timezone.utc.utcoffset(None)


def test_retries_of_one_event_can_be_recognised():
    """The de-duplication advice on the page only works if the id is genuinely
    stable when it is passed through -- which is what the delivery worker does
    on each retry."""
    fixed = "11111111-2222-3333-4444-555555555555"
    first = json.loads(build_delivery_body("invoice.completed", {"invoice_id": "x"}, event_id=fixed))
    again = json.loads(build_delivery_body("invoice.completed", {"invoice_id": "x"}, event_id=fixed))
    assert first["event_id"] == again["event_id"] == fixed


def test_two_distinct_events_do_not_share_an_id():
    a = json.loads(build_delivery_body("invoice.completed", {"invoice_id": "x"}))
    b = json.loads(build_delivery_body("invoice.completed", {"invoice_id": "x"}))
    assert a["event_id"] != b["event_id"]


@pytest.mark.parametrize(
    "field", ["currency", "reject_reason", "vendor_name", "grand_total", "status", "invoice_id"]
)
def test_documented_inbound_payload_fields(field):
    """Pinned individually so that removing one from the docs names itself in
    the failure rather than showing up as a set difference."""
    assert field in webhook_docs.InboundInvoiceEventData.model_fields


@pytest.mark.parametrize("field", ["currency", "due_date", "days_overdue", "customer_name"])
def test_documented_outbound_payload_fields(field):
    assert field in webhook_docs.OutboundInvoiceEventData.model_fields


def test_the_page_tells_integrators_to_verify_the_replay_safe_signature():
    """Gap 564 introduced V2 and this page kept recommending V1. Advice that is
    merely out of date here is a security instruction the customer follows."""
    note = webhook_docs._SIGNATURE_NOTE
    assert "X-Webhook-Signature-V2" in note
    assert "X-Webhook-Timestamp" in note
    assert "X-InvoiceEQ-Event-Id" in note
    # V1 must still be mentioned -- existing subscribers verify it -- but the
    # page has to say it is the weaker one.
    assert "backwards compatibility" in note
