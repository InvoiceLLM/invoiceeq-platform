import logging
from uuid import UUID, uuid4
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from datetime import datetime

from dependencies import (
    get_db_session,
    # Feature 25 (Gap 335): replaces this router's former
    # `require_can_audit` / `get_tenant_context` pair, exactly as on the
    # inbound router. Human rule unchanged; `actions`-scoped keys now pass.
    get_tenant_or_api_key_context,
    require_actions_scope,
    TenantContext,
)
from agents.extraction_agent import OutboundInvoiceExtractionSchema
from models import Invoice, AuditLog, ExtractionTemplate, ExtractionTemplateVersion, User
from services.invoice_visibility import invoice_not_deleted
from utils.correction_values import (
    is_blank,
    list_entry_model,
    parse_currency,
    parse_date,
    parse_entries,
    parse_money,
    parse_percent,
)
from utils.alert_dismissal import dismiss_alerts
from utils.correction_recheck import MONEY_FIELDS, alerts_raised_by_correction, snapshot_money_fields
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
#
# Feature 25 (Gap 335): router-level, so it gates everything mounted at
# /outbound-audit -- which today is exactly one route,
# PUT /resolve/{invoice_id}, with no read-only views. Same note as the inbound
# router: a read-only view added here later must not silently inherit an
# `actions`-scope requirement.
router = APIRouter(
    prefix="/outbound-audit",
    tags=["Outbound Audit"],
    dependencies=[Depends(require_actions_scope)],
)

# Feature 7.1: outbound corrections only ever touch these fields -- the
# same set OutboundInvoiceExtractionSchema extracts (feature_2.1_vendor_flow_ingestion.md),
# not inbound's field list (no customer_name inbound; no discount lines, deductions or tags outbound).
_CORRECTABLE_FIELDS = {
    "customer_name": "str",
    "invoice_number": "str",
    "invoice_date": "date",
    "due_date": "date",
    "subtotal": "float",
    "grand_total": "float",
    "tax_amount": "float",
    "items": "list",
    # BE Gap 531 (founder ruling 2026-09-15: all of them): the rest of what
    # OutboundInvoiceExtractionSchema extracts into an Invoice column since BE Gap 467
    # (so an outbound invoice does carry vendor_name and po_number now). `round_off` has no column.
    "vendor_name": "str",
    "po_number": "str",
    "notes": "str",
    "currency": "currency",
    "discount_amount": "float",
    "discount_percent": "percent",
    "taxes": "list",
    "tax_ids": "list",
    "payment_instructions": "list",
    "references": "list",
    "addresses": "list",
    "compliance_metadata": "list",
}

# BE Gap 531: each list field's entries are checked against the model OutboundInvoiceExtractionSchema
# itself uses for that field (read from the schema, not imported by name — see list_entry_model).
_LIST_ENTRY_NAMES = {
    "items": "line item",
    "taxes": "tax line",
    "tax_ids": "tax ID",
    "payment_instructions": "payment instruction",
    "references": "reference",
    "addresses": "address",
    "compliance_metadata": "compliance entry",
}
_LIST_ENTRY_MODELS = {
    field: (list_entry_model(OutboundInvoiceExtractionSchema, field), entry_name)
    for field, entry_name in _LIST_ENTRY_NAMES.items()
}

# BE Gap 532 (founder ruling 2026-09-15): fields a correction may change but never empty.
_REQUIRED_FIELDS = frozenset({"customer_name", "invoice_number", "invoice_date", "grand_total"})


class OutboundAuditResolutionPayload(BaseModel):
    corrections: Optional[Dict[str, Any]] = Field(
        default=None,
        description=f"Field name -> corrected value. Allowed fields: {sorted(_CORRECTABLE_FIELDS)}.",
    )
    dismissed_alerts: Optional[list] = Field(
        default=None,
        description="Alerts to dismiss, one entry per alert (BE Gap 537): an alert object "
                    '({"id"} or {"type", "field", "message"}) or, from older integrations, an alert id, '
                    "message or type string. Each entry removes at most one alert; entries that match "
                    "nothing are returned in `unmatched_dismissals` (BE Gap 538).",
    )
    apply_as_standing_rule: bool = Field(
        default=False,
        description="Feature 7.1 Task 7.1.3: write this correction directly as the tenant's "
                     "OUTBOUND Global rule -- no safety gate, unlike inbound's Gap 62/Task 7.5, "
                     "since every outbound invoice is the same single, self-authored format.",
    )


def _coerce_correction_value(field: str, raw_value: Any):
    field_type = _CORRECTABLE_FIELDS[field]
    if raw_value is None or raw_value == "":
        # BE Gap 531: a list column is cleared to an empty list, never NULL.
        return [] if field_type == "list" else None
    if field_type == "date":
        return parse_date(raw_value)
    if field_type == "float":
        return parse_money(raw_value)
    if field_type == "percent":
        return parse_percent(raw_value)
    if field_type == "currency":
        return parse_currency(raw_value)
    if field_type == "list":
        entry_model, entry_name = _LIST_ENTRY_MODELS[field]
        return parse_entries(raw_value, entry_model, entry_name)
    return str(raw_value)


def _apply_corrections(invoice: Invoice, corrections: Dict[str, Any]) -> Dict[str, dict]:
    diff: Dict[str, dict] = {}
    invalid: list[Dict[str, str]] = []
    for field, raw_value in corrections.items():
        if field not in _CORRECTABLE_FIELDS:
            # BE Gap 530: reported, not skipped.
            logger.warning("Rejected outbound correction for non-correctable field '%s'", field)
            invalid.append({"field": field, "reason": "this field cannot be corrected"})
            continue
        if field in _REQUIRED_FIELDS and is_blank(raw_value):
            # BE Gap 532: a required field is never emptied by a correction. Blank on a field that is
            # already empty changes nothing, so it is not refused.
            if getattr(invoice, field) is not None:
                invalid.append({"field": field, "reason": "this field is required and cannot be left empty"})
            continue
        try:
            new_value = _coerce_correction_value(field, raw_value)
        except (ValueError, TypeError) as e:
            # BE Gap 533: report it instead of skipping; the raw value is not logged.
            logger.warning("Rejected unreadable outbound correction for '%s': %s", field, type(e).__name__)
            invalid.append({"field": field, "reason": str(e)})
            continue

        old_value = getattr(invoice, field)
        old_comparable = old_value.isoformat() if hasattr(old_value, "isoformat") else old_value
        new_comparable = new_value.isoformat() if hasattr(new_value, "isoformat") else new_value
        if old_comparable == new_comparable:
            continue

        setattr(invoice, field, new_value)
        diff[field] = {"old": old_comparable, "new": new_comparable}
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Some corrections could not be read; nothing was saved.", "invalid_corrections": invalid},
        )
    return diff


def _resolve_changed_by(db_session: Session, context: TenantContext) -> str:
    if context.db_user_id:
        user = db_session.get(User, context.db_user_id)
        if user and user.email:
            return user.email
    return context.user_id


def _outbound_verification_rules(db_session: Session, tenant_id: UUID) -> dict | None:
    """BE Gap 535: the tenant's OUTBOUND Global rules (outbound has no vendor scope), so the arithmetic
    re-check after a correction uses the same tolerance overrides extraction did."""
    statement = select(ExtractionTemplate).where(
        ExtractionTemplate.tenant_id == tenant_id,
        ExtractionTemplate.vendor_name.is_(None),
        ExtractionTemplate.flow_direction == "OUTBOUND",
    )
    template = db_session.exec(statement).first()
    if template and isinstance(template.rules, dict) and template.rules.get("constraints"):
        return {"constraints": list(template.rules["constraints"])}
    return None


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
    # Feature 25 (Gap 335): dual-credential, for the same reason as the inbound
    # resolve handler -- the router gate above has already admitted an
    # `actions` key, and a Clerk-only resolver would 401 it here.
    context: TenantContext = Depends(get_tenant_or_api_key_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 7.1, Task 7.1.2/7.1.3: corrections + AuditLog diff for a
    NEEDS_REVIEW outbound invoice. Deliberately not importing from
    routers/audit.py -- that file's resolve logic isn't factored into
    reusable pieces, and no pattern-detection/suggestion logic here (that's
    an inbound-only concept, see the doc for why)."""
    # BE Gap 541: lock the row so two simultaneous resolves on one invoice run one after the other.
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
        invoice_not_deleted(),
    ).with_for_update()
    invoice = db_session.exec(statement).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbound invoice not found or access denied.")

    # BE Gaps 537/538: one alert per dismissal — by id, else type + field + message; unmatched ones reported back.
    previous_alerts = list(invoice.sa_alerts or [])
    dismissed_list = payload.dismissed_alerts or []
    new_alerts, dismissed_alerts, unmatched_dismissals = dismiss_alerts(previous_alerts, dismissed_list)
    invoice.sa_alerts = new_alerts

    values_before = snapshot_money_fields(invoice)
    correction_diff = _apply_corrections(invoice, payload.corrections or {})

    # BE Gap 535: a correction that breaks the arithmetic raises a new alert (founder ruling: an alert, not a block).
    raised_alerts: list[dict] = []
    if set(correction_diff) & set(MONEY_FIELDS):
        raised_alerts = alerts_raised_by_correction(
            values_before,
            snapshot_money_fields(invoice),
            rules=_outbound_verification_rules(db_session, context.tenant_id),
            doc_type=invoice.doc_type,
            open_alerts=new_alerts,
        )
        if raised_alerts:
            new_alerts = new_alerts + raised_alerts
            invoice.sa_alerts = new_alerts
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
            # BE Gaps 537/538/535: see routers/audit.py — read by the alert-accuracy metrics.
            "dismissed_alerts": dismissed_alerts,
            "unmatched_dismissals": unmatched_dismissals,
            "raised_alerts": raised_alerts,
            "previous_alerts": previous_alerts,
            "remaining_alerts": new_alerts,
            "corrections": correction_diff,
            "standing_rule_result": standing_rule_result,
            **context.trail_identity(),
        },
        timestamp=datetime.utcnow(),
    )
    db_session.add(audit_log)
    db_session.commit()

    # Gap 243 backstop, the outbound twin of routers/audit.py's Gap 240 one:
    # this endpoint never changes `invoice.status` (an outbound resolve is
    # corrections + alert dismissal only), so there is no status transition to
    # key on -- the trigger is the resolution itself. Only re-indexes when the
    # invoice genuinely has no chunks, and never fails the resolve on error.
    try:
        from chroma_client import has_invoice_chunks, index_invoice_document, should_index_status
        if should_index_status(invoice.status) and not await run_in_threadpool(
            has_invoice_chunks, str(invoice.id), str(invoice.tenant_id)
        ):
            logger.info("Backfilling RAG index for resolved outbound invoice %s (no chunks found)", invoice.id)
            await run_in_threadpool(
                index_invoice_document,
                str(invoice.id),
                str(invoice.tenant_id),
                invoice.customer_name,
                invoice.file_path,
            )
    except Exception as ie:
        logger.error("RAG index backfill failed for resolved outbound invoice %s: %s", invoice.id, ie)

    return {
        "success": True,
        "corrections_applied": correction_diff,
        "standing_rule_result": standing_rule_result,
        # BE Gaps 535/537/538: the alerts left open (including any the correction raised) and the unmatched dismissals.
        "remaining_alerts": new_alerts,
        "unmatched_dismissals": unmatched_dismissals,
        "raised_alerts": raised_alerts,
    }
