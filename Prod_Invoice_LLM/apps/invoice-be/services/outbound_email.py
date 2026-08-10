"""Gap 125: SendGrid Mail Send helper for staff notifications (never customers)."""
from __future__ import annotations

import base64
import logging
from typing import Sequence

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

SENDGRID_MAIL_URL = "https://api.sendgrid.com/v3/mail/send"


def from_address() -> str:
    """Technical From for outbound mail (Single Sender or authenticated domain)."""
    settings = get_settings()
    addr = (settings.EMAIL_APP_ADDRESS or "").strip()
    if addr:
        return addr
    domain = (settings.SENDGRID_SENDING_DOMAIN or settings.EMAIL_APP_DOMAIN or "invoiceeq.app").strip()
    return f"invoices@{domain}"


def sendgrid_configured() -> bool:
    return bool((get_settings().SENDGRID_API_KEY or "").strip())


def send_email(
    *,
    to_addresses: Sequence[str],
    subject: str,
    plain_body: str,
    html_body: str | None = None,
    reply_to: str | None = None,
    attachment_filename: str | None = None,
    attachment_bytes: bytes | None = None,
) -> dict:
    """
    Send via SendGrid v3 API using httpx.

    Without SENDGRID_API_KEY raises RuntimeError — callers should check
    sendgrid_configured() or catch and decide whether to fail the request.
    Domain authentication is optional for testing (Single Sender Verification
    is enough); missing DNS mainly hurts inbox placement, not the API call.
    """
    settings = get_settings()
    api_key = (settings.SENDGRID_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY is not configured.")

    recipients = [a.strip().lower() for a in to_addresses if a and a.strip()]
    if not recipients:
        raise ValueError("At least one recipient email is required.")

    personalizations: list[dict] = [{"to": [{"email": r} for r in recipients]}]
    content = [{"type": "text/plain", "value": plain_body}]
    if html_body:
        content.append({"type": "text/html", "value": html_body})

    payload: dict = {
        "personalizations": personalizations,
        "from": {"email": from_address()},
        "subject": subject,
        "content": content,
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to.strip().lower()}

    if attachment_bytes is not None and attachment_filename:
        payload["attachments"] = [
            {
                "content": base64.b64encode(attachment_bytes).decode("ascii"),
                "type": "application/pdf",
                "filename": attachment_filename,
                "disposition": "attachment",
            }
        ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(SENDGRID_MAIL_URL, headers=headers, json=payload)

    if resp.status_code >= 400:
        logger.error("SendGrid mail send failed status=%s body=%s", resp.status_code, resp.text[:500])
        raise RuntimeError(f"SendGrid mail send failed ({resp.status_code}): {resp.text[:300]}")

    logger.info(
        "SendGrid mail accepted status=%s to=%s subject=%s",
        resp.status_code, recipients, subject[:80],
    )
    return {"status_code": resp.status_code, "to": recipients}
