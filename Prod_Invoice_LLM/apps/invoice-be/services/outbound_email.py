"""Gap 125: SendGrid Mail Send helper for staff notifications (never customers)."""
from __future__ import annotations

import base64
import logging
from typing import NamedTuple, Sequence

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

SENDGRID_MAIL_URL = "https://api.sendgrid.com/v3/mail/send"

DEFAULT_ATTACHMENT_MIME_TYPE = "application/pdf"


class EmailAttachment(NamedTuple):
    """One file to attach, with its own content type.

    Feature 25 (Gap 339): the MIME type used to be hardcoded to
    `application/pdf` inside send_email(), so the only attachment this module
    could send honestly was a PDF. Gap 339 attaches a CSV and a JSON summary,
    and telling a mail client that a `.csv` is a PDF makes it undisplayable
    (and, on some clients, unopenable) for no reason. The type travels with
    the bytes now instead of being assumed by the sender.
    """
    filename: str
    content: bytes
    mime_type: str = DEFAULT_ATTACHMENT_MIME_TYPE


def from_address() -> str:
    """Technical From for outbound mail.

    Priority order:
    1. SENDGRID_FROM_EMAIL  — dedicated outbound address (e.g. invoice@notify.invoicellm...)
    2. EMAIL_APP_ADDRESS    — platform mailbox fallback (inbound address, avoid if possible)
    3. invoices@<SENDGRID_SENDING_DOMAIN or EMAIL_APP_DOMAIN or invoiceeq.app>

    SENDGRID_FROM_EMAIL is declared separately from EMAIL_APP_ADDRESS so the
    inbound AI-receive mailbox and the outbound sender are cleanly decoupled.
    """
    settings = get_settings()
    # 1. Dedicated outbound sender
    from_email = (settings.SENDGRID_FROM_EMAIL or "").strip()
    if from_email:
        return from_email
    # 2. Mailbox address fallback
    addr = (settings.EMAIL_APP_ADDRESS or "").strip()
    if addr:
        return addr
    # 3. Construct from domain
    domain = (settings.SENDGRID_SENDING_DOMAIN or settings.EMAIL_APP_DOMAIN or "invoiceeq.app").strip()
    return f"invoices@{domain}"


def from_display_name() -> str:
    """Display name shown to email recipients (e.g. 'InvoiceLLM')."""
    return (get_settings().SENDGRID_FROM_NAME or "InvoiceLLM").strip()


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
    attachment_mime_type: str = DEFAULT_ATTACHMENT_MIME_TYPE,
    attachments: Sequence[EmailAttachment] | None = None,
) -> dict:
    """
    Send via SendGrid v3 API using httpx.

    Without SENDGRID_API_KEY raises RuntimeError — callers should check
    sendgrid_configured() or catch and decide whether to fail the request.
    Domain authentication is optional for testing (Single Sender Verification
    is enough); missing DNS mainly hurts inbox placement, not the API call.

    Attachments (Gap 339). Two ways in, and they compose:
      * `attachment_filename` + `attachment_bytes` — the single-file form this
        function has always had. `attachment_mime_type` defaults to
        `application/pdf`, which is exactly what the hardcoded value used to
        be, so every existing caller is unaffected;
      * `attachments` — a list of `EmailAttachment(filename, content, mime_type)`
        for the multi-file case (Gap 339 sends a CSV *and* a JSON).
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
        "from": {"email": from_address(), "name": from_display_name()},
        "subject": subject,
        "content": content,
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to.strip().lower()}

    all_attachments: list[EmailAttachment] = []
    if attachment_bytes is not None and attachment_filename:
        all_attachments.append(
            EmailAttachment(attachment_filename, attachment_bytes, attachment_mime_type)
        )
    all_attachments.extend(attachments or [])
    if all_attachments:
        payload["attachments"] = [
            {
                "content": base64.b64encode(att.content).decode("ascii"),
                "type": att.mime_type or DEFAULT_ATTACHMENT_MIME_TYPE,
                "filename": att.filename,
                "disposition": "attachment",
            }
            for att in all_attachments
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
