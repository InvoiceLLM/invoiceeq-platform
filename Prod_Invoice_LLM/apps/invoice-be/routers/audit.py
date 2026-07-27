import logging
from uuid import UUID
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from datetime import datetime, timedelta

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, AuditLog
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Audit"])

# Fields an auditor is allowed to correct from the metadata inspector (Task 7.3),
# matching exactly what fe_features/feature_4_auditor.md's ReadOnlyField list shows.
# "date" fields are parsed as ISO YYYY-MM-DD (or a leading date segment of a
# datetime string), same convention as queue_worker/handlers.py's own date parsing.
_CORRECTABLE_FIELDS = {
    "vendor_name": "str",
    "invoice_number": "str",
    "po_number": "str",
    "invoice_date": "date",
    "due_date": "date",
    "grand_total": "float",
    "tax_amount": "float",
}

# Task 7.4: after N corrections on the same field, suggest saving it as a Trainer
# rule instead of correcting it by hand every time. Same field corrected for one
# vendor repeatedly -> vendor-scope suggestion; across multiple distinct vendors ->
# global-scope suggestion (a Global rule, since it's not vendor-specific behavior).
_RULE_SUGGESTION_THRESHOLD = 3
_RULE_SUGGESTION_LOOKBACK_DAYS = 90


class AuditResolutionPayload(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="Target status: PAID or REJECTED. Omit to just dismiss alerts "
                     "and/or save corrections without finalizing the invoice.",
    )
    dismissed_alerts: Optional[List[str]] = Field(default=None, description="Alert messages, types, or IDs to dismiss")
    corrections: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Field name -> corrected value, for fields the auditor edited "
                     f"in the metadata inspector. Allowed fields: {sorted(_CORRECTABLE_FIELDS)}.",
    )


def _coerce_correction_value(field: str, raw_value: Any):
    field_type = _CORRECTABLE_FIELDS[field]
    if raw_value is None or raw_value == "":
        return None
    if field_type == "date":
        date_str = str(raw_value).split("T")[0].split(" ")[0].strip()
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    if field_type == "float":
        return float(raw_value)
    return str(raw_value)


def _apply_corrections(invoice: Invoice, corrections: Dict[str, Any]) -> Dict[str, dict]:
    """Persist corrected values onto the Invoice row. Returns a before/after diff
    (only for fields that actually changed) for the AuditLog and for pattern
    detection — silently ignores unknown/uncorrectable field names rather than
    erroring, so a stale FE build sending an extra field can't break a resolve."""
    diff: Dict[str, dict] = {}
    for field, raw_value in corrections.items():
        if field not in _CORRECTABLE_FIELDS:
            logger.warning("Ignoring correction for non-correctable field '%s'", field)
            continue
        try:
            new_value = _coerce_correction_value(field, raw_value)
        except (ValueError, TypeError) as e:
            logger.warning("Ignoring malformed correction for '%s'=%r: %s", field, raw_value, e)
            continue

        old_value = getattr(invoice, field)
        old_comparable = old_value.isoformat() if hasattr(old_value, "isoformat") else old_value
        new_comparable = new_value.isoformat() if hasattr(new_value, "isoformat") else new_value
        if old_comparable == new_comparable:
            continue  # no actual change - not a correction, don't log or count it

        setattr(invoice, field, new_value)
        diff[field] = {"old": old_comparable, "new": new_comparable}
    return diff


def _detect_correction_pattern(
    db_session: Session, tenant_id: UUID, vendor_name: str | None, corrected_fields: List[str]
) -> dict | None:
    """Task 7.4: check whether any just-corrected field has recurred often enough
    (across this invoice's own resolve plus past ones) to be worth promoting to a
    Trainer rule instead of correcting by hand every time. Returns the first
    qualifying field's suggestion, or None."""
    if not corrected_fields:
        return None

    cutoff = datetime.utcnow() - timedelta(days=_RULE_SUGGESTION_LOOKBACK_DAYS)
    stmt = (
        select(AuditLog, Invoice.vendor_name)
        .join(Invoice, AuditLog.invoice_id == Invoice.id)
        .where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action == "RESOLVE_INVOICE",
            AuditLog.timestamp >= cutoff,
        )
    )
    try:
        rows = db_session.exec(stmt).all()
    except Exception as e:
        logger.warning("Failed to load correction history for pattern detection: %s", e)
        return None

    for field in corrected_fields:
        vendor_hit_count = 0
        distinct_vendors: set[str] = set()
        sample_value = None
        for log_row, log_vendor_name in rows:
            corr = (log_row.details or {}).get("corrections") or {}
            if field not in corr:
                continue
            entry = corr[field]
            sample_value = entry.get("new") if isinstance(entry, dict) else entry
            if log_vendor_name:
                distinct_vendors.add(log_vendor_name)
                if log_vendor_name == vendor_name:
                    vendor_hit_count += 1

        sample_correction = f"Field '{field}' should be read as {sample_value!r}."
        if vendor_name and vendor_hit_count >= _RULE_SUGGESTION_THRESHOLD:
            return {
                "scope": "existing_vendor",
                "field": field,
                "vendor_name": vendor_name,
                "sample_correction": sample_correction,
            }
        if len(distinct_vendors) >= _RULE_SUGGESTION_THRESHOLD:
            return {
                "scope": "global",
                "field": field,
                "vendor_name": None,
                "sample_correction": sample_correction,
            }
    return None


@router.put("/resolve/{invoice_id}")
async def resolve_audit_invoice(
    invoice_id: UUID,
    payload: AuditResolutionPayload,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Enables manual auditor override actions: dismiss alerts, correct extracted
    field values, and/or finalize the invoice as PAID or REJECTED. `status` is
    optional — omit it to just dismiss alerts or save corrections without
    finalizing (e.g. a single alert's "Dismiss" button on a still-AUDIT_REQUIRED
    invoice, which previously always failed because it forced a PAID/REJECTED
    transition even when the auditor wasn't ready to close the invoice out).
    """
    # 1. Validate status, if one was actually provided
    target_status = None
    if payload.status is not None:
        target_status = payload.status.upper()
        if target_status not in ["PAID", "REJECTED"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target status '{payload.status}'. Must be PAID or REJECTED."
            )

    # 2. Retrieve the target invoice with tenant isolation scope
    statement = select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == context.tenant_id)
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )

    # 3. Dismiss specified warnings
    previous_alerts = list(invoice.sa_alerts or [])
    dismissed_list = payload.dismissed_alerts or []

    new_alerts = []
    for alert in previous_alerts:
        if isinstance(alert, str):
            if alert not in dismissed_list:
                new_alerts.append(alert)
        elif isinstance(alert, dict):
            alert_id = alert.get("id")
            alert_type = alert.get("type")
            alert_msg = alert.get("message")
            if (alert_id not in dismissed_list) and (alert_type not in dismissed_list) and (alert_msg not in dismissed_list):
                new_alerts.append(alert)
        else:
            new_alerts.append(alert)

    # Assign the new list (needs to be a new list object so SQLModel/SQLAlchemy registers the update)
    invoice.sa_alerts = new_alerts
    if target_status is not None:
        invoice.status = target_status

    # 3b. Apply field corrections (Task 7.3), capturing a before/after diff.
    vendor_name_for_pattern = invoice.vendor_name  # capture before a vendor_name correction itself changes it
    correction_diff = _apply_corrections(invoice, payload.corrections or {})

    db_session.add(invoice)

    # 4. Save audit log record — corrections included so Task 7.4 can detect
    # recurring patterns across resolves, and so there's a durable record of
    # exactly what a human changed and why.
    log_details = {
        "target_status": target_status,
        "dismissed_alerts_input": dismissed_list,
        "previous_alerts": previous_alerts,
        "remaining_alerts": new_alerts,
        "corrections": correction_diff,
    }

    audit_log = AuditLog(
        tenant_id=context.tenant_id,
        invoice_id=invoice_id,
        actor_user_id=context.db_user_id,
        actor_role=context.role,
        action="RESOLVE_INVOICE",
        details=log_details,
        timestamp=datetime.utcnow()
    )
    db_session.add(audit_log)

    # 5. Commit transaction
    db_session.commit()

    # 6. Task 7.4: suggest a Trainer rule if a correction just made recurred often
    # enough to be worth automating instead of fixing by hand every time.
    suggested_rule = None
    if correction_diff:
        suggested_rule = _detect_correction_pattern(
            db_session, context.tenant_id, vendor_name_for_pattern, list(correction_diff.keys())
        )

    return {"success": True, "corrections_applied": correction_diff, "suggested_rule": suggested_rule}
