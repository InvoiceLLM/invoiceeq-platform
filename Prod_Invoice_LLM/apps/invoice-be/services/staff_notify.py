"""Gap 125: staff-only email notifications (never end customers).

Notify #1 — after processing finishes (COMPLETED / AUDIT_REQUIRED or
VERIFIED / NEEDS_REVIEW).
Notify #2 — auditor Mark Paid / Reject / Confirm Send / Mark Paid with an
explicit multi-select of registered set addresses.
"""
from __future__ import annotations

import logging
from typing import Sequence

from sqlmodel import Session, select

from models import Invoice, TenantEmailSender
from services.outbound_email import send_email, sendgrid_configured

logger = logging.getLogger(__name__)


def email_set_for_invoice(invoice: Invoice) -> str:
    return "outbound" if (invoice.flow_direction or "INBOUND").upper() == "OUTBOUND" else "inbound"


def list_registered_emails(session: Session, tenant_id, email_set: str) -> list[str]:
    rows = session.exec(
        select(TenantEmailSender).where(
            TenantEmailSender.tenant_id == tenant_id,
            TenantEmailSender.email_set == email_set,
        )
    ).all()
    return sorted({(r.email or "").strip().lower() for r in rows if r.email})


def validate_notify_emails(
    session: Session,
    *,
    tenant_id,
    email_set: str,
    notify_emails: Sequence[str] | None,
) -> list[str]:
    """Return cleaned emails; raise ValueError if any address is outside the set."""
    if not notify_emails:
        return []
    cleaned = sorted({(e or "").strip().lower() for e in notify_emails if e and str(e).strip()})
    if not cleaned:
        return []
    allowed = set(list_registered_emails(session, tenant_id, email_set))
    bad = [e for e in cleaned if e not in allowed]
    if bad:
        raise ValueError(
            f"notify_emails must be registered in the {email_set} authorized set. "
            f"Not allowed: {', '.join(bad)}"
        )
    return cleaned


def _recipients_for_processing(session: Session, invoice: Invoice) -> list[str]:
    submitter = (invoice.submitted_by_email or "").strip().lower()
    if submitter:
        return [submitter]
    return list_registered_emails(session, invoice.tenant_id, email_set_for_invoice(invoice))


def _alert_summary(invoice: Invoice, limit: int = 5) -> str:
    alerts = invoice.sa_alerts or []
    if not alerts:
        return ""
    lines: list[str] = []
    for a in alerts[:limit]:
        if isinstance(a, dict):
            lines.append(f"- {a.get('message') or a.get('type') or 'alert'}")
        else:
            lines.append(f"- {a}")
    extra = len(alerts) - limit
    if extra > 0:
        lines.append(f"- …and {extra} more")
    return "\n".join(lines)


def notify_processing_complete(session: Session, invoice: Invoice) -> dict | None:
    """Notify #1 after extraction settles. Soft-fails if SendGrid missing."""
    if not sendgrid_configured():
        logger.info("Skip process-complete notify for %s — SENDGRID_API_KEY not set", invoice.id)
        return None

    recipients = _recipients_for_processing(session, invoice)
    if not recipients:
        logger.info("Skip process-complete notify for %s — no recipients", invoice.id)
        return None

    status = (invoice.status or "").upper()
    inv_ref = invoice.invoice_number or str(invoice.id)
    party = invoice.customer_name if email_set_for_invoice(invoice) == "outbound" else invoice.vendor_name
    party_label = party or "unknown"

    if status in ("AUDIT_REQUIRED", "NEEDS_REVIEW"):
        subject = f"[InvoiceEQ] Audit pending — {inv_ref}"
        outcome = "needs auditor review"
    else:
        subject = f"[InvoiceEQ] Processing complete — {inv_ref}"
        outcome = "completed successfully"

    alert_block = _alert_summary(invoice)
    plain = (
        f"Invoice {inv_ref} ({party_label}) {outcome}.\n"
        f"Status: {status}\n"
    )
    if alert_block:
        plain += f"\nAlerts:\n{alert_block}\n"
    plain += "\nThis message was sent only to registered workspace emails — not to customers.\n"

    try:
        result = send_email(to_addresses=recipients, subject=subject, plain_body=plain)
        return {"sent": True, **result}
    except Exception as e:
        logger.error("Process-complete notify failed for invoice %s: %s", invoice.id, e)
        return {"sent": False, "error": str(e)}


def notify_auditor_action(
    session: Session,
    invoice: Invoice,
    *,
    action_label: str,
    notify_emails: Sequence[str] | None,
) -> dict | None:
    """
    Notify #2 for auditor terminal actions.
    Empty notify_emails → no send. Invalid addresses → ValueError.
    Missing SendGrid → soft skip with sent=False.
    """
    email_set = email_set_for_invoice(invoice)
    recipients = validate_notify_emails(
        session,
        tenant_id=invoice.tenant_id,
        email_set=email_set,
        notify_emails=notify_emails,
    )
    if not recipients:
        return None

    if not sendgrid_configured():
        logger.warning(
            "Auditor notify requested for %s but SENDGRID_API_KEY missing", invoice.id
        )
        return {"sent": False, "error": "SENDGRID_API_KEY is not configured.", "to": recipients}

    inv_ref = invoice.invoice_number or str(invoice.id)
    party = invoice.customer_name if email_set == "outbound" else invoice.vendor_name
    subject = f"[InvoiceEQ] {action_label} — {inv_ref}"
    plain = (
        f"Invoice {inv_ref} ({party or 'unknown'}) was marked: {action_label}.\n"
        f"Status: {invoice.status}\n\n"
        "Staff notification only — the app does not email end customers.\n"
    )
    try:
        result = send_email(to_addresses=recipients, subject=subject, plain_body=plain)
        return {"sent": True, **result}
    except Exception as e:
        logger.error("Auditor notify failed for invoice %s: %s", invoice.id, e)
        return {"sent": False, "error": str(e), "to": recipients}


def notify_autopilot_sync_summary(
    session: Session,
    *,
    tenant_id,
    notify_emails: Sequence[str],
    imported: Sequence[dict],
    send_approval_links: bool,
    frontend_base_url: str,
) -> dict | None:
    """
    BE Gap 220: email staff after Autopilot ingests new files.
    `imported` items: {invoice_id, file_name, vendor_name?}
    """
    if not imported or not notify_emails:
        return None

    email_set = "inbound" if all(
        (item.get("flow_direction") or "INBOUND").upper() == "INBOUND" for item in imported
    ) else "inbound"
    try:
        recipients = validate_notify_emails(
            session,
            tenant_id=tenant_id,
            email_set=email_set,
            notify_emails=notify_emails,
        )
    except ValueError as e:
        logger.warning("Autopilot notify skipped — invalid emails: %s", e)
        return {"sent": False, "error": str(e)}

    if not recipients:
        return None

    if not sendgrid_configured():
        logger.warning("Autopilot notify requested but SENDGRID_API_KEY missing")
        return {"sent": False, "error": "SENDGRID_API_KEY is not configured.", "to": recipients}

    base = (frontend_base_url or "").rstrip("/")
    lines = [f"Autopilot imported {len(imported)} new invoice(s):\n"]
    for item in imported:
        name = item.get("file_name") or item.get("invoice_id")
        line = f"- {name}"
        if send_approval_links and base and item.get("invoice_id"):
            line += f"\n  Review: {base}/invoices/review/{item['invoice_id']}"
        lines.append(line)
    lines.append("\nStaff notification only — the app does not email end customers.\n")
    plain = "\n".join(lines)

    try:
        result = send_email(
            to_addresses=recipients,
            subject=f"[InvoiceEQ] Autopilot imported {len(imported)} invoice(s)",
            plain_body=plain,
        )
        return {"sent": True, **result}
    except Exception as e:
        logger.error("Autopilot notify failed for tenant %s: %s", tenant_id, e)
        return {"sent": False, "error": str(e), "to": recipients}
