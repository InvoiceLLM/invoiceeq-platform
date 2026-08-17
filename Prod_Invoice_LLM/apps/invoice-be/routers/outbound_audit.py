import json
import logging
from uuid import UUID, uuid4
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from datetime import datetime

from dependencies import get_tenant_context, get_db_session, require_can_audit, TenantContext
from models import Invoice, AuditLog, ExtractionTemplate, ExtractionTemplateVersion, User
from services.invoice_visibility import invoice_not_deleted
from utils.rule_schema import (
    build_audit_correction_rule,
    merge_constraints,
    normalize_constraints,
    ORIGIN_AUDIT_CORRECTION_OUTBOUND,
    SCOPE_OUTBOUND_GLOBAL,
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Feature 1.1 (Task 1.1.2): AR-side mirror of routers/audit.py -- same
# `can_audit` permission gates the outbound review console.
router = APIRouter(
    prefix="/outbound-audit",
    tags=["Outbound Audit"],
    dependencies=[Depends(require_can_audit)],
)

# Feature 7.1: outbound corrections only ever touch these fields -- the
# same set OutboundInvoiceExtractionSchema extracts (feature_2.1_vendor_flow_ingestion.md),
# not inbound's field list (no po_number on an outbound invoice, for instance).
_CORRECTABLE_FIELDS = {
    "customer_name": "str",
    "invoice_number": "str",
    "invoice_date": "date",
    "due_date": "date",
    "subtotal": "float",
    "grand_total": "float",
    "tax_amount": "float",
    "items": "list",
}


class OutboundAuditResolutionPayload(BaseModel):
    corrections: Optional[Dict[str, Any]] = Field(
        default=None,
        description=f"Field name -> corrected value. Allowed fields: {sorted(_CORRECTABLE_FIELDS)}.",
    )
    dismissed_alerts: Optional[list] = Field(default=None, description="Alert messages, types, or IDs to dismiss")
    apply_as_standing_rule: bool = Field(
        default=False,
        description="Feature 7.1 Task 7.1.3: write this correction directly as the tenant's "
                     "OUTBOUND Global rule -- no safety gate, unlike inbound's Gap 62/Task 7.5, "
                     "since every outbound invoice is the same single, self-authored format.",
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
    if field_type == "list":
        if isinstance(raw_value, list):
            return raw_value
        try:
            val = json.loads(str(raw_value))
            if isinstance(val, list):
                return val
        except Exception:
            pass
        return [raw_value]
    return str(raw_value)


def _apply_corrections(invoice: Invoice, corrections: Dict[str, Any]) -> Dict[str, dict]:
    diff: Dict[str, dict] = {}
    for field, raw_value in corrections.items():
        if field not in _CORRECTABLE_FIELDS:
            logger.warning("Ignoring outbound correction for non-correctable field '%s'", field)
            continue
        try:
            new_value = _coerce_correction_value(field, raw_value)
        except (ValueError, TypeError) as e:
            logger.warning("Ignoring malformed outbound correction for '%s'=%r: %s", field, raw_value, e)
            continue

        old_value = getattr(invoice, field)
        old_comparable = old_value.isoformat() if hasattr(old_value, "isoformat") else old_value
        new_comparable = new_value.isoformat() if hasattr(new_value, "isoformat") else new_value
        if old_comparable == new_comparable:
            continue

        setattr(invoice, field, new_value)
        diff[field] = {"old": old_comparable, "new": new_comparable}
    return diff


def _resolve_changed_by(db_session: Session, context: TenantContext) -> str:
    if context.db_user_id:
        user = db_session.get(User, context.db_user_id)
        if user and user.email:
            return user.email
    return context.user_id


def _apply_standing_rule_direct(db_session: Session, tenant_context: TenantContext, correction_diff: Dict[str, dict]) -> dict:
    """Task 7.1.3: no safety gate, unlike inbound's Gap 62 mechanism -- every
    outbound invoice is the tenant's own single, consistent format, so
    there's no vendor-layout variability to de-risk against before
    committing. Global-only (vendor_name=NULL), flow_direction='OUTBOUND'."""
    # Feature 18: structured rules, same as inbound's `_apply_standing_rule`.
    # Scope is `outbound_global` rather than `vendor`: an outbound invoice has no
    # `vendor_name` at all (the counterparty is `customer_name`, a different
    # party), so the Global OUTBOUND template row is the only row an outbound
    # rule can structurally live on. That row and every read of it are unchanged.
    candidate_rules = [
        build_audit_correction_rule(
            field=field,
            new_value=diff["new"],
            old_value=diff["old"],
            scope=SCOPE_OUTBOUND_GLOBAL,
            origin=ORIGIN_AUDIT_CORRECTION_OUTBOUND,
        )
        for field, diff in correction_diff.items()
    ]

    stmt = select(ExtractionTemplate).where(
        ExtractionTemplate.tenant_id == tenant_context.tenant_id,
        ExtractionTemplate.vendor_name.is_(None),
        ExtractionTemplate.flow_direction == "OUTBOUND",
    )
    template = db_session.exec(stmt).first()
    existing_constraints = (
        list(template.rules.get("constraints", []) or [])
        if template and isinstance(template.rules, dict)
        else []
    )
    merged_constraints = merge_constraints(existing_constraints, candidate_rules)

    changed_by = _resolve_changed_by(db_session, tenant_context)
    if template:
        template.rules = {"constraints": merged_constraints}
        template.version = (template.version or 1) + 1
        template.updated_at = datetime.utcnow()
        db_session.add(template)
    else:
        template = ExtractionTemplate(
            id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            vendor_name=None,
            flow_direction="OUTBOUND",
            rules={"constraints": merged_constraints},
            version=1,
        )
        db_session.add(template)

    db_session.flush()
    db_session.add(ExtractionTemplateVersion(
        template_id=template.id,
        tenant_id=tenant_context.tenant_id,
        vendor_name=None,
        version=template.version,
        rules={"constraints": merged_constraints},
        changed_by=changed_by,
    ))

    return {
        "applied": True,
        "rules_added": normalize_constraints(candidate_rules, for_prompt=False),
        "rules_added_structured": candidate_rules,
    }


@router.put("/resolve/{invoice_id}")
async def resolve_outbound_alert(
    invoice_id: UUID,
    payload: OutboundAuditResolutionPayload,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 7.1, Task 7.1.2/7.1.3: corrections + AuditLog diff for a
    NEEDS_REVIEW outbound invoice. Deliberately not importing from
    routers/audit.py -- that file's resolve logic isn't factored into
    reusable pieces, and no pattern-detection/suggestion logic here (that's
    an inbound-only concept, see the doc for why)."""
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

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
    invoice.sa_alerts = new_alerts

    correction_diff = _apply_corrections(invoice, payload.corrections or {})
    db_session.add(invoice)

    standing_rule_result = None
    if payload.apply_as_standing_rule and correction_diff:
        standing_rule_result = _apply_standing_rule_direct(db_session, context, correction_diff)

    audit_log = AuditLog(
        tenant_id=context.tenant_id,
        invoice_id=invoice_id,
        actor_user_id=context.db_user_id,
        actor_role=context.role,
        action="RESOLVE_OUTBOUND_INVOICE",
        details={
            "dismissed_alerts_input": dismissed_list,
            "previous_alerts": previous_alerts,
            "remaining_alerts": new_alerts,
            "corrections": correction_diff,
            "standing_rule_result": standing_rule_result,
        },
        timestamp=datetime.utcnow(),
    )
    db_session.add(audit_log)
    db_session.commit()

    return {"success": True, "corrections_applied": correction_diff, "standing_rule_result": standing_rule_result}
