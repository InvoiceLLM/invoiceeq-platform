import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlmodel import Session, select

from models import WebhookSubscription

logger = logging.getLogger(__name__)

# Task 15.5: disable a subscription after this many consecutive delivery
# failures, rather than retrying it forever against a dead/misconfigured
# endpoint. Surfaced in the settings UI (FE) so the tenant notices and can
# re-enable once fixed, instead of silently losing events forever.
MAX_CONSECUTIVE_FAILURES = 10
DELIVERY_TIMEOUT_SECONDS = 5.0
MAX_DELIVERY_ATTEMPTS = 3


class InvalidWebhookUrlError(ValueError):
    """Raised when a target_url is malformed or resolves to a disallowed (SSRF-risk) address."""


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


def _deliver_with_retry(target_url: str, headers: dict, raw_body: bytes) -> bool:
    """Task 15.3: 3 attempts, exponential backoff (1s, 2s) on non-2xx/timeout.
    No redirect-follow -- a validated target_url must not be able to
    silently hop to an unvalidated host at delivery time."""
    for attempt in range(MAX_DELIVERY_ATTEMPTS):
        try:
            with httpx.Client(timeout=DELIVERY_TIMEOUT_SECONDS, follow_redirects=False) as client:
                response = client.post(target_url, headers=headers, content=raw_body)
            if 200 <= response.status_code < 300:
                return True
            logger.warning(
                "Webhook delivery to %s got HTTP %d (attempt %d/%d)",
                target_url, response.status_code, attempt + 1, MAX_DELIVERY_ATTEMPTS,
            )
        except httpx.HTTPError as e:
            logger.warning(
                "Webhook delivery to %s failed (attempt %d/%d): %s",
                target_url, attempt + 1, MAX_DELIVERY_ATTEMPTS, e,
            )
        if attempt < MAX_DELIVERY_ATTEMPTS - 1:
            time.sleep(2 ** attempt)
    return False


def dispatch_webhook_event(db_session: Session, tenant_id: UUID, event_type: str, payload: dict) -> None:
    """Task 15.3/15.4: fan out one event to every enabled subscription for
    this tenant that's actually subscribed to it. Called right after the
    triggering DB commit at each hook point (queue_worker/handlers.py,
    routers/audit.py, routers/outbound_invoices.py) -- deliberately swallows
    all delivery errors internally (never raises), since a webhook delivery
    failure must never fail the invoice operation that triggered it.
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

    body = {"event": event_type, "data": payload}
    raw_body = json.dumps(body, default=str).encode("utf-8")

    for sub in subscriptions:
        if event_type not in (sub.subscribed_events or []):
            continue

        signature = _sign_payload(sub.secret, raw_body)
        headers = {"Content-Type": "application/json", "X-Webhook-Signature": signature}

        try:
            success = _deliver_with_retry(sub.target_url, headers, raw_body)
        except Exception as e:
            logger.error("Unexpected error delivering webhook %s to %s: %s", sub.id, sub.target_url, e)
            success = False

        if success:
            if sub.consecutive_failures != 0:
                sub.consecutive_failures = 0
                db_session.add(sub)
                db_session.commit()
        else:
            sub.consecutive_failures += 1
            if sub.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                sub.enabled = False
                logger.warning(
                    "Webhook subscription %s auto-disabled after %d consecutive failures (target: %s)",
                    sub.id, sub.consecutive_failures, sub.target_url,
                )
            db_session.add(sub)
            db_session.commit()
