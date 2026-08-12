import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

import httpx
from azure.storage.queue import QueueClient
from sqlmodel import Session, select

from config import get_settings
from models import WebhookDeliveryLog, WebhookSubscription

logger = logging.getLogger(__name__)

# Task 15.5: disable a subscription after this many consecutive delivery
# failures, rather than retrying it forever against a dead/misconfigured
# endpoint. Surfaced in the settings UI (FE) so the tenant notices and can
# re-enable once fixed, instead of silently losing events forever.
MAX_CONSECUTIVE_FAILURES = 10
DELIVERY_TIMEOUT_SECONDS = 5.0
MAX_DELIVERY_ATTEMPTS = 3

# Gap 194: webhook deliveries ride the same Azure Storage Queue every other
# background job in this repo uses (see queue_worker/main_worker.poll_queue).
QUEUE_NAME = "extraction-tasks-queue"
DELIVERY_TASK_NAME = "deliver_webhook"


class InvalidWebhookUrlError(ValueError):
    """Raised when a target_url is malformed or resolves to a disallowed (SSRF-risk) address."""


@dataclass
class DeliveryResult:
    """Outcome of one delivery *attempt series* (up to MAX_DELIVERY_ATTEMPTS
    HTTP calls against the same subscriber). Recorded as a single
    WebhookDeliveryLog row."""
    success: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    attempts: int = 0
    duration_ms: int = 0


def validate_webhook_target_url(target_url: str) -> None:
    """Task 15.2: reject a target_url that resolves to a private/link-local/
    loopback/reserved IP range at creation/update time -- a tenant could
    otherwise point a webhook at internal infrastructure (e.g. the cloud
    metadata endpoint, an internal admin panel) and use our own outbound
    delivery calls to reach it. Resolves the hostname now, at validation
    time; delivery itself also uses a short timeout and does not follow
    redirects, so a later DNS rebind can't silently redirect a validated
    hostname to an internal address post-validation.
    """
    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidWebhookUrlError(f"Invalid target_url: {target_url!r} must be an http(s) URL with a hostname.")

    try:
        resolved_ips = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as e:
        raise InvalidWebhookUrlError(f"Could not resolve hostname {parsed.hostname!r}: {e}") from e

    for ip_str in resolved_ips:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise InvalidWebhookUrlError(
                f"target_url {target_url!r} resolves to a disallowed address ({ip_str}) -- "
                "private/loopback/link-local/reserved IP ranges are not permitted."
            )


def _sign_payload(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def build_delivery_body(event_type: str, payload: dict) -> bytes:
    """The exact bytes POSTed to the subscriber, and the exact bytes the
    X-Webhook-Signature HMAC is computed over. Built in one place so the
    dispatcher (which enqueues) and the worker (which delivers) can never
    disagree about the wire format."""
    return json.dumps({"event": event_type, "data": payload}, default=str).encode("utf-8")


def _deliver_with_retry(target_url: str, headers: dict, raw_body: bytes) -> DeliveryResult:
    """Task 15.3: 3 attempts, exponential backoff (1s, 2s) on non-2xx/timeout.
    No redirect-follow -- a validated target_url must not be able to
    silently hop to an unvalidated host at delivery time.

    Gap 194: returns a DeliveryResult rather than a bare bool, because the
    delivery log needs the HTTP status / transport error / attempt count that
    this loop was previously throwing away into logger.warning only. Worst
    case here is ~19s (3 x 5s timeout + 1s + 2s backoff) -- which is exactly
    why this now runs on the queue worker and not on the thread that just
    committed the invoice.
    """
    started = time.monotonic()
    status_code: Optional[int] = None
    error: Optional[str] = None

    for attempt in range(MAX_DELIVERY_ATTEMPTS):
        try:
            with httpx.Client(timeout=DELIVERY_TIMEOUT_SECONDS, follow_redirects=False) as client:
                response = client.post(target_url, headers=headers, content=raw_body)
            status_code = response.status_code
            if 200 <= response.status_code < 300:
                return DeliveryResult(
                    success=True,
                    status_code=response.status_code,
                    attempts=attempt + 1,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            error = f"HTTP {response.status_code}"
            logger.warning(
                "Webhook delivery to %s got HTTP %d (attempt %d/%d)",
                target_url, response.status_code, attempt + 1, MAX_DELIVERY_ATTEMPTS,
            )
        except httpx.HTTPError as e:
            status_code = None
            error = f"{type(e).__name__}: {e}"[:1000]
            logger.warning(
                "Webhook delivery to %s failed (attempt %d/%d): %s",
                target_url, attempt + 1, MAX_DELIVERY_ATTEMPTS, e,
            )
        if attempt < MAX_DELIVERY_ATTEMPTS - 1:
            time.sleep(2 ** attempt)

    return DeliveryResult(
        success=False,
        status_code=status_code,
        error=error,
        attempts=MAX_DELIVERY_ATTEMPTS,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _log_delivery(
    db_session: Session,
    sub: WebhookSubscription,
    event_type: str,
    result: DeliveryResult,
) -> None:
    """Gap 194: persist one delivery-attempt row. Never raises -- an
    observability write must not be the thing that breaks delivery."""
    try:
        db_session.add(
            WebhookDeliveryLog(
                tenant_id=sub.tenant_id,
                subscription_id=sub.id,
                event_type=event_type,
                success=result.success,
                status_code=result.status_code,
                attempts=result.attempts,
                duration_ms=result.duration_ms,
                error=(result.error or None) if not result.success else None,
            )
        )
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error("Failed to record webhook delivery log for subscription %s: %s", sub.id, e)


def record_delivery_result(
    db_session: Session,
    sub: WebhookSubscription,
    event_type: str,
    result: DeliveryResult,
) -> None:
    """Gap 194 -- failure accounting, scoped per event type.

    Why per event type, but auto-disable still per subscription: a
    WebhookSubscription row is *one target URL and one signing secret*, so
    "disabled" can only ever mean "stop calling this URL" -- there is nothing
    finer to switch off, and adding a per-event enable flag would be a
    different (bigger) feature than this gap. What was actually wrong before
    is the *counting*: one flat `consecutive_failures` meant a subscriber that
    500s on, say, `outbound_invoice.overdue` while happily 200-ing
    `invoice.completed` would take the whole endpoint -- including the event
    types it was accepting -- offline after 10 overdue sweeps.

    So the counter is now per event type (`event_failure_counts`), and the
    auto-disable trip requires both:
      * the event type that just failed has hit MAX_CONSECUTIVE_FAILURES, and
      * no *other* event type on this subscription is currently healthy
        (i.e. none has a count of 0, meaning its last delivery succeeded).

    A genuinely dead endpoint fails every event type it is sent, so it still
    auto-disables exactly as before. An endpoint that is only broken for one
    event type stays enabled; the failures are visible instead in
    `webhook_delivery_logs` and in the per-event breakdown on the settings
    page, which is what the tenant needs to fix it.

    `consecutive_failures` is kept in sync as max(counts.values()) so the
    existing public API shape and the settings-page health warning keep
    working unchanged.
    """
    counts = dict(sub.event_failure_counts or {})

    # Lazy backfill for rows created before this column existed: attribute the
    # old flat counter to the first event type that fails after the upgrade,
    # rather than silently forgiving a subscription that was already 9 failures
    # deep at deploy time.
    if not counts and sub.consecutive_failures and not result.success:
        counts[event_type] = sub.consecutive_failures

    if result.success:
        counts[event_type] = 0
    else:
        counts[event_type] = counts.get(event_type, 0) + 1

    sub.event_failure_counts = counts
    sub.consecutive_failures = max(counts.values()) if counts else 0

    if not result.success and counts[event_type] >= MAX_CONSECUTIVE_FAILURES:
        healthy_elsewhere = any(count == 0 for evt, count in counts.items() if evt != event_type)
        if healthy_elsewhere:
            logger.warning(
                "Webhook subscription %s has %d consecutive failures for event %s, but other event "
                "types are still delivering successfully -- not auto-disabling (target: %s)",
                sub.id, counts[event_type], event_type, sub.target_url,
            )
        else:
            sub.enabled = False
            logger.warning(
                "Webhook subscription %s auto-disabled after %d consecutive failures for event %s "
                "with no other event type delivering successfully (target: %s)",
                sub.id, counts[event_type], event_type, sub.target_url,
            )

    try:
        db_session.add(sub)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error("Failed to persist webhook failure state for subscription %s: %s", sub.id, e)

    _log_delivery(db_session, sub, event_type, result)


def deliver_webhook_now(
    db_session: Session,
    subscription_id: UUID,
    event_type: str,
    payload: dict,
) -> Optional[DeliveryResult]:
    """Gap 194: the actual HTTP delivery, run by the queue worker
    (queue_worker/handlers.handle_deliver_webhook) rather than by the request
    or ingestion thread that produced the event.

    Re-reads the subscription at delivery time on purpose: it may have been
    disabled, deleted, or had its event list edited between enqueue and
    delivery, and the queue message must not be able to resurrect a
    subscription the tenant has since turned off. Returns None when there is
    nothing to deliver.
    """
    sub = db_session.exec(
        select(WebhookSubscription).where(WebhookSubscription.id == subscription_id)
    ).first()
    if not sub:
        logger.info("Webhook subscription %s no longer exists; dropping queued delivery.", subscription_id)
        return None
    if not sub.enabled:
        logger.info("Webhook subscription %s is disabled; dropping queued delivery.", subscription_id)
        return None
    if event_type not in (sub.subscribed_events or []):
        logger.info(
            "Webhook subscription %s is no longer subscribed to %s; dropping queued delivery.",
            subscription_id, event_type,
        )
        return None

    raw_body = build_delivery_body(event_type, payload)
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": _sign_payload(sub.secret, raw_body),
    }

    try:
        result = _deliver_with_retry(sub.target_url, headers, raw_body)
    except Exception as e:
        logger.error("Unexpected error delivering webhook %s to %s: %s", sub.id, sub.target_url, e)
        result = DeliveryResult(success=False, error=f"{type(e).__name__}: {e}"[:1000], attempts=0)

    record_delivery_result(db_session, sub, event_type, result)
    return result


def _enqueue_delivery(sub: WebhookSubscription, event_type: str, payload: dict) -> Optional[str]:
    """Put one delivery on the shared task queue. Returns None on success, or a
    short error string describing why it could not be queued."""
    settings = get_settings()
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        return "AZURE_STORAGE_CONNECTION_STRING is not set; webhook delivery could not be queued."

    message = {
        "task": DELIVERY_TASK_NAME,
        "kwargs": {
            "tenant_id": str(sub.tenant_id),
            "subscription_id": str(sub.id),
            "event_type": event_type,
            "payload": payload,
        },
    }
    try:
        queue_client = QueueClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING, QUEUE_NAME
        )
        queue_client.send_message(json.dumps(message, default=str))
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"[:1000]


def dispatch_webhook_event(db_session: Session, tenant_id: UUID, event_type: str, payload: dict) -> None:
    """Task 15.3/15.4: fan out one event to every enabled subscription for
    this tenant that's actually subscribed to it. Called right after the
    triggering DB commit at each hook point (queue_worker/handlers.py,
    routers/audit.py, routers/outbound_invoices.py, services/outbound_overdue.py)
    -- deliberately swallows all errors internally (never raises), since a
    webhook failure must never fail the invoice operation that triggered it.

    Gap 194: this no longer performs the HTTP call. It only resolves which
    subscriptions match and enqueues one `deliver_webhook` task each; the
    queue worker does the delivery. Previously the caller's thread paid the
    full retry cost inline -- up to ~19s per subscriber (3 attempts x 5s
    timeout plus 1s/2s backoff) -- so one slow subscriber back-pressured
    invoice ingestion and every request path that fires an event.

    An enqueue failure is recorded as a failed WebhookDeliveryLog row so the
    tenant can see the event never went out, but it deliberately does *not*
    count toward auto-disable: failing to reach our own queue says nothing
    about the health of the subscriber's endpoint.
    """
    try:
        subscriptions = db_session.exec(
            select(WebhookSubscription).where(
                WebhookSubscription.tenant_id == tenant_id,
                WebhookSubscription.enabled == True,  # noqa: E712
            )
        ).all()
    except Exception as e:
        logger.error("Failed to load webhook subscriptions for tenant %s: %s", tenant_id, e)
        return

    for sub in subscriptions:
        if event_type not in (sub.subscribed_events or []):
            continue

        try:
            error = _enqueue_delivery(sub, event_type, payload)
        except Exception as e:  # defensive: settings/queue construction paths
            error = f"{type(e).__name__}: {e}"[:1000]

        if error:
            logger.error(
                "Could not queue webhook %s (%s) for subscription %s: %s",
                event_type, sub.target_url, sub.id, error,
            )
            _log_delivery(
                db_session,
                sub,
                event_type,
                DeliveryResult(success=False, error=f"Not queued: {error}"[:1000], attempts=0),
            )
