"""
Feature Website 5 / Feature 19: Support Ticket & Inquiry Email Dispatch.

Formats and sends support alert emails via the existing SendGrid helper
(services/outbound_email.py). Two email types are produced per ticket:

  1. Staff Alert  → Application@infinevocloud.com (or SUPPORT_NOTIFY_EMAIL env)
     Rich HTML with priority badge, submitter metadata, full description,
     and optional chat transcript.

  2. User Receipt → submitter's own email address
     A clean acknowledgement confirming we received their ticket and stating
     the SLA they can expect.

Both calls are non-fatal — if SendGrid is not configured (dev/test with no
SENDGRID_API_KEY) the function logs a warning and returns a "skipped" result
rather than raising. The ticket is already persisted before email is attempted,
so a mail failure never rolls back the record.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime

from config import get_settings
from services.outbound_email import send_email, sendgrid_configured

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority badge colours (inline CSS — no external CSS in email HTML)
# ---------------------------------------------------------------------------
_PRIORITY_STYLES: dict[str, tuple[str, str]] = {
    "URGENT": ("#EF4444", "#FEF2F2"),   # red bg, light red text bg
    "NORMAL": ("#3B82F6", "#EFF6FF"),   # blue
    "LOW":    ("#10B981", "#ECFDF5"),   # green
}

_CATEGORY_LABELS: dict[str, str] = {
    "SALES":               "Sales & Enterprise Demo",
    "TECHNICAL_SUPPORT":   "Technical Support",
    "BILLING":             "Billing & Pricing",
    "PARTNERSHIP":         "Partnership",
    "GENERAL":             "General Inquiry",
}

_SOURCE_LABELS: dict[str, str] = {
    "WEBSITE_CONTACT": "Website Contact Form",
    "HELP_CHATBOT":    "Help Center AI Chatbot",
    "DIRECT_TICKET":   "Help Center Direct Ticket",
}


# ---------------------------------------------------------------------------
# HTML template helpers
# ---------------------------------------------------------------------------

def _priority_badge(priority: str) -> str:
    colour, bg = _PRIORITY_STYLES.get(priority.upper(), ("#6B7280", "#F9FAFB"))
    return (
        f'<span style="background:{bg};color:{colour};border:1px solid {colour}40;'
        f'padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;'
        f'letter-spacing:0.05em">{priority.upper()}</span>'
    )


def _ticket_html(ticket) -> str:
    """Build the rich HTML body for the staff alert email with escaped user inputs."""
    settings = get_settings()
    notify_to = settings.SUPPORT_NOTIFY_EMAIL

    category_label = _CATEGORY_LABELS.get(ticket.category, ticket.category)
    source_label   = _SOURCE_LABELS.get(ticket.source, ticket.source)
    created_fmt    = ticket.created_at.strftime("%Y-%m-%d %H:%M UTC") if ticket.created_at else "—"

    # HTML-escape all user-controlled fields
    user_name_esc   = html.escape(ticket.user_name or "—", quote=True)
    user_email_esc  = html.escape(ticket.user_email or "", quote=True)
    company_esc     = html.escape(ticket.company_name or "", quote=True)
    subject_esc     = html.escape(ticket.subject or "", quote=True)
    description_esc = html.escape(ticket.description or "", quote=True)

    # Transcript section (only for chatbot-escalated tickets)
    transcript_html = ""
    if ticket.chat_transcript:
        rows = ""
        for msg in ticket.chat_transcript:
            role = html.escape(msg.get("role", "unknown").capitalize(), quote=True)
            content = html.escape(msg.get("content", ""), quote=True)
            colour = "#1e40af" if role == "User" else "#065f46"
            rows += (
                f'<tr><td style="padding:6px 10px;color:{colour};font-weight:600;'
                f'width:80px;vertical-align:top">{role}</td>'
                f'<td style="padding:6px 10px;color:#374151">{content}</td></tr>'
            )
        transcript_html = f"""
        <h3 style="margin:24px 0 8px;color:#111827;font-size:14px">Conversation Transcript</h3>
        <table style="width:100%;border-collapse:collapse;background:#F9FAFB;border-radius:6px;
                      border:1px solid #E5E7EB;font-size:13px">{rows}</table>"""

    company_row = (
        f'<tr><td style="padding:6px 0;color:#6B7280;width:140px">Company</td>'
        f'<td style="padding:6px 0;color:#111827">{company_esc}</td></tr>'
        if ticket.company_name else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Support Inquiry - {ticket.ticket_number}</title></head>
<body style="margin:0;padding:0;background:#F3F4F6;font-family:'Segoe UI',Arial,sans-serif">
  <div style="max-width:640px;margin:32px auto;background:#fff;border-radius:10px;
              box-shadow:0 2px 12px rgba(0,0,0,0.08);overflow:hidden">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1e3a5f 0%,#0f172a 100%);padding:28px 32px">
      <p style="margin:0 0 4px;color:#93C5FD;font-size:11px;letter-spacing:0.12em;
                text-transform:uppercase">Invoice AI Platform</p>
      <h1 style="margin:0 0 8px;color:#fff;font-size:22px">New Support {source_label}</h1>
      <div style="display:flex;align-items:center;gap:12px">
        <code style="color:#22D3EE;font-size:16px;font-weight:700">{ticket.ticket_number}</code>
        &nbsp;&nbsp;{_priority_badge(ticket.priority)}
      </div>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px">

      <!-- Metadata table -->
      <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px">
        <tr><td style="padding:6px 0;color:#6B7280;width:140px">Submitted</td>
            <td style="padding:6px 0;color:#111827">{created_fmt}</td></tr>
        <tr><td style="padding:6px 0;color:#6B7280">Name</td>
            <td style="padding:6px 0;color:#111827">{user_name_esc}</td></tr>
        <tr><td style="padding:6px 0;color:#6B7280">Email</td>
            <td style="padding:6px 0;color:#111827">
              <a href="mailto:{user_email_esc}" style="color:#2563EB">{user_email_esc}</a>
            </td></tr>
        {company_row}
        <tr><td style="padding:6px 0;color:#6B7280">Category</td>
            <td style="padding:6px 0;color:#111827">{category_label}</td></tr>
        <tr><td style="padding:6px 0;color:#6B7280">Source</td>
            <td style="padding:6px 0;color:#111827">{source_label}</td></tr>
      </table>

      <!-- Description -->
      <h3 style="margin:0 0 8px;color:#111827;font-size:14px">Subject</h3>
      <p style="margin:0 0 20px;color:#374151;font-size:14px">{subject_esc}</p>

      <h3 style="margin:0 0 8px;color:#111827;font-size:14px">Message / Description</h3>
      <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:6px;
                  padding:14px 16px;color:#374151;font-size:14px;white-space:pre-wrap;
                  line-height:1.6">{description_esc}</div>

      {transcript_html}

    </div>

    <!-- Footer -->
    <div style="background:#F9FAFB;padding:16px 32px;border-top:1px solid #E5E7EB">
      <p style="margin:0;color:#9CA3AF;font-size:12px">
        This alert was sent to <strong>{notify_to}</strong> by Invoice AI Platform's
        automated support engine. Reply directly to this email to respond to the submitter.
      </p>
    </div>
  </div>
</body>
</html>"""


def _receipt_html(ticket) -> str:
    """Build the user auto-acknowledgement HTML with escaped user inputs."""
    created_fmt = ticket.created_at.strftime("%Y-%m-%d %H:%M UTC") if ticket.created_at else "—"
    sla = "within 2 hours" if ticket.priority.upper() == "URGENT" else "within 24 hours"
    user_name_esc = html.escape(ticket.user_name or "there", quote=True)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>We received your inquiry — {ticket.ticket_number}</title></head>
<body style="margin:0;padding:0;background:#F3F4F6;font-family:'Segoe UI',Arial,sans-serif">
  <div style="max-width:560px;margin:32px auto;background:#fff;border-radius:10px;
              box-shadow:0 2px 12px rgba(0,0,0,0.08);overflow:hidden">

    <div style="background:linear-gradient(135deg,#1e3a5f 0%,#0f172a 100%);padding:28px 32px">
      <p style="margin:0 0 4px;color:#93C5FD;font-size:11px;letter-spacing:0.12em;
                text-transform:uppercase">Invoice AI — Support Team</p>
      <h1 style="margin:0;color:#fff;font-size:20px">We've received your inquiry</h1>
    </div>

    <div style="padding:28px 32px">
      <p style="margin:0 0 16px;color:#374151;font-size:15px">
        Hi {user_name_esc},
      </p>
      <p style="margin:0 0 20px;color:#374151;font-size:14px;line-height:1.6">
        Thank you for reaching out to the Invoice AI team. Your inquiry has been logged and
        our engineering or sales team will get back to you <strong>{sla}</strong>.
      </p>

      <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;
                  padding:16px 20px;margin-bottom:20px">
        <p style="margin:0 0 4px;color:#1D4ED8;font-size:12px;font-weight:700;
                  letter-spacing:0.08em">YOUR REFERENCE NUMBER</p>
        <code style="color:#1e3a5f;font-size:20px;font-weight:700">{ticket.ticket_number}</code>
        <p style="margin:6px 0 0;color:#6B7280;font-size:12px">Submitted {created_fmt}</p>
      </div>

      <p style="margin:0;color:#6B7280;font-size:13px;line-height:1.6">
        If you need to follow up, please reply to this email and quote your reference number.
      </p>
    </div>

    <div style="background:#F9FAFB;padding:16px 32px;border-top:1px solid #E5E7EB">
      <p style="margin:0;color:#9CA3AF;font-size:12px">
        Invoice AI Platform &nbsp;·&nbsp; Enterprise multi-tenant AI invoice processing on Azure.
      </p>
    </div>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dispatch_support_ticket_email(ticket) -> dict:
    """
    Send both the staff alert and the user acknowledgement for a SupportTicket.

    Returns a summary dict: {"staff_alert": {...}, "user_receipt": {...}}.
    Both sub-dicts are {"status": "sent"|"skipped", ...}.  A "skipped" status
    means SendGrid is not configured — the ticket is already persisted so this
    is non-fatal and the caller should log a warning, not raise.
    """
    settings = get_settings()
    notify_to = settings.SUPPORT_NOTIFY_EMAIL

    priority = ticket.priority.upper()
    category_label = _CATEGORY_LABELS.get(ticket.category, ticket.category)
    safe_subject = (ticket.subject or "").replace("\r", " ").replace("\n", " ").strip()
    staff_subject = (
        f"[Invoice AI Support] [{ticket.ticket_number}] [{priority}] "
        f"{category_label} — {safe_subject}"
    )
    receipt_subject = f"We received your inquiry [{ticket.ticket_number}] — Invoice AI"

    result: dict = {"staff_alert": {}, "user_receipt": {}}

    if not sendgrid_configured():
        logger.warning(
            "support_email: SENDGRID_API_KEY not configured — skipping dispatch for %s",
            ticket.ticket_number,
        )
        result["staff_alert"]  = {"status": "skipped", "reason": "sendgrid_not_configured"}
        result["user_receipt"] = {"status": "skipped", "reason": "sendgrid_not_configured"}
        return result

    # --- Staff alert ---
    try:
        plain_staff = (
            f"Support Inquiry — {ticket.ticket_number}\n"
            f"Priority : {priority}\n"
            f"Category : {category_label}\n"
            f"From     : {ticket.user_name or 'Anonymous'} <{ticket.user_email}>\n"
            f"Company  : {ticket.company_name or '—'}\n"
            f"Subject  : {ticket.subject}\n\n"
            f"{ticket.description}"
        )
        r = send_email(
            to_addresses=[notify_to],
            subject=staff_subject,
            plain_body=plain_staff,
            html_body=_ticket_html(ticket),
            reply_to=ticket.user_email,
        )
        result["staff_alert"] = {"status": "sent", **r}
        logger.info("support_email: staff alert sent for %s to %s", ticket.ticket_number, notify_to)
    except Exception as exc:
        logger.error("support_email: staff alert failed for %s: %s", ticket.ticket_number, exc)
        result["staff_alert"] = {"status": "error", "error": str(exc)}

    # --- User receipt ---
    try:
        plain_receipt = (
            f"Hi {ticket.user_name or 'there'},\n\n"
            f"We received your inquiry and your reference number is {ticket.ticket_number}.\n"
            f"Our team will respond within "
            f"{'2 hours' if priority == 'URGENT' else '24 hours'}.\n\n"
            f"— Invoice AI Support Team"
        )
        r = send_email(
            to_addresses=[ticket.user_email],
            subject=receipt_subject,
            plain_body=plain_receipt,
            html_body=_receipt_html(ticket),
        )
        result["user_receipt"] = {"status": "sent", **r}
    except Exception as exc:
        logger.error("support_email: user receipt failed for %s: %s", ticket.ticket_number, exc)
        result["user_receipt"] = {"status": "error", "error": str(exc)}

    return result
