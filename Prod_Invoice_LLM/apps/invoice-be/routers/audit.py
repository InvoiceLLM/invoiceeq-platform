import json
import logging
from uuid import UUID, uuid4
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from datetime import datetime, timedelta

from config import get_settings
from dependencies import (
    get_db_session,
    # Feature 25 (Gap 335): replaces this router's former
    # `require_can_audit` / `get_tenant_context` pair. The human rule is
    # unchanged (still can_audit, same 403 text); an `actions`-scoped API key
    # now also passes.
    get_tenant_or_api_key_context,
    require_actions_scope,
    TenantContext,
)
from models import Invoice, AuditLog, ExtractionTemplate, ExtractionTemplateVersion, User
from services.invoice_visibility import invoice_not_deleted
from queue_worker.handlers import _run_ocr
from agents.extraction_agent import run_extraction_agent
from utils.rule_schema import (
    build_audit_correction_rule,
    merge_constraints,
    normalize_constraints,
    ORIGIN_AUDIT_CORRECTION,
    SCOPE_VENDOR,
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Feature 1.1 (Task 1.1.2): the Audit Queue's actions (Mark Paid, Reject,
# corrections) are real financial actions, so the whole router requires
# `can_audit`. Admins pass implicitly.
#
# Feature 25 (Gap 335): this is a ROUTER-LEVEL dependency, so it gates every
# route on the router, not just the resolve handler below -- checked, and it
# matters: raising the gate here raises it for everything mounted at /audit.
# As of this change the router has exactly ONE route
# (PUT /resolve/{invoice_id}) and no read-only views at all, so requiring
# `actions` scope here removes no read access from anyone. If a read-only audit
# view is ever added to this router it must NOT inherit this gate -- give it its
# own Depends(get_tenant_or_api_key_context) and move this dependency down onto
# the resolve route, or a readonly key loses a read it should have.
#
# require_actions_scope keeps the human rule byte-identical to require_can_audit
# (same permission, same 403 message) and adds the key rule alongside it.
router = APIRouter(
    prefix="/audit",
    tags=["Audit"],
    dependencies=[Depends(require_actions_scope)],
)

# Feature 4: standard inbound fields that are permitted to receive corrections,
# matching exactly what fe_features/feature_4_auditor.md's ReadOnlyField list shows.
# "date" fields are parsed as ISO YYYY-MM-DD (or a leading date segment of a
# datetime string), same convention as queue_worker/handlers.py's own date parsing.
_CORRECTABLE_FIELDS = {
    "vendor_name": "str",
    "invoice_number": "str",
    "po_number": "str",
    "invoice_date": "date",
    "due_date": "date",
    "subtotal": "float",
    "grand_total": "float",
    "tax_amount": "float",
    "items": "list",
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
        description="Target status: PAID, REJECTED, AUDIT_REQUIRED (Gap 193: "
                     "Admin-only reopen of an already-resolved invoice), "
                     "REVIEW_LATER, or NEEDS_RESUBMISSION (Gap 407: non-terminal "
                     "deferrals, not usable directly on a PAID/REJECTED invoice). "
                     "Omit to just dismiss alerts and/or save corrections without "
                     "finalizing the invoice.",
    )
    resubmission_reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Gap 421: why the invoice is being sent back, persisted on "
                    "the invoice when status=NEEDS_RESUBMISSION. Without it the "
                    "vendor is told to resend with no statement of what to fix.",
    )
    dismissed_alerts: Optional[List[str]] = Field(default=None, description="Alert messages, types, or IDs to dismiss")
    corrections: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Field name -> corrected value, for fields the auditor edited "
                     f"in the metadata inspector. Allowed fields: {sorted(_CORRECTABLE_FIELDS)}.",
    )
    apply_as_standing_rule: bool = Field(
        default=False,
        description="Gap 62/Task 7.5: if true and corrections are present, teach the "
                     "correction back as a vendor-scoped ExtractionTemplate rule, gated "
                     "on a safety re-extraction check (see _apply_standing_rule below).",
    )
    reject_reason: Optional[str] = Field(
        default=None,
        description="Auditor rejection reason"
    )
    notify_emails: Optional[List[str]] = Field(
        default=None,
        description="Gap 125: subset of inbound authorized set to notify on PAID/REJECTED. Never customers.",
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


# ─────────────────────────────────────────────────────────────────────────────
# Gap 62 / Task 7.5: let Audit teach a standing rule directly, gated on a
# safety re-extraction check. Deliberately duplicated from routers/trainer.py's
# equivalent small helpers (_run_ocr_split, template fetch, changed_by
# resolution) rather than imported -- this codebase's established convention
# for parallel audit/trainer mechanisms is to accept a small amount of
# duplication in exchange for never editing the other's shipped code.
# ─────────────────────────────────────────────────────────────────────────────

def _run_ocr_split(file_path: str) -> str:
    """Run OCR and return just the raw text -- `_run_ocr` returns a dict on
    Azure (content + coordinates + field_confidence) and a plain string in
    local/Ollama mode."""
    settings = get_settings()
    ocr_result = _run_ocr(file_path, settings)
    if isinstance(ocr_result, dict):
        return ocr_result.get("content", "")
    return ocr_result


def _get_vendor_template(db_session: Session, tenant_id: UUID, vendor_name: str) -> ExtractionTemplate | None:
    """Fetch this vendor's template row. Vendor-scoped only -- this gap is
    deliberately not Global-scope, since a single invoice correction is a
    weak signal for a tenant-wide rule (see feature_7_audit.md Task 7.5)."""
    stmt = select(ExtractionTemplate).where(
        ExtractionTemplate.tenant_id == tenant_id,
        ExtractionTemplate.vendor_name == vendor_name,
    )
    return db_session.exec(stmt).first()


def _resolve_changed_by(db_session: Session, context: TenantContext) -> str:
    if context.db_user_id:
        user = db_session.get(User, context.db_user_id)
        if user and user.email:
            return user.email
    return context.user_id


def _apply_standing_rule(
    db_session: Session,
    invoice: Invoice,
    correction_diff: Dict[str, dict],
    tenant_context: TenantContext,
) -> dict:
    """Auto-re-run extraction with the candidate rule applied; only commit the
    rule if the re-extraction actually reflects the correction for every
    corrected field. This is the safety gate inbound needs that outbound
    doesn't -- every vendor can have a different layout, so a rule taught
    from one correction risks being a one-off anomaly if applied blind."""
    vendor_name = invoice.vendor_name
    if not vendor_name:
        return {"applied": False, "reason": "No vendor name on this invoice -- standing rules are vendor-scoped."}

    # Feature 18: this was the second free-text rule producer in the codebase --
    # it synthesised a sentence and dropped it into the same undifferentiated
    # `constraints` bag the Trainer wrote to, so nothing downstream could tell an
    # auditor-derived rule from a chat-derived one, or recover which field it was
    # about. It now emits structured rule objects. The rendered `text` is
    # byte-identical to the sentence this function has always produced, so the
    # extraction prompt is unchanged; the field/old/new are simply also available
    # structurally now.
    candidate_rules = [
        build_audit_correction_rule(
            field=field,
            new_value=diff["new"],
            old_value=diff["old"],
            scope=SCOPE_VENDOR,
            origin=ORIGIN_AUDIT_CORRECTION,
        )
        for field, diff in correction_diff.items()
    ]

    existing_template = _get_vendor_template(db_session, tenant_context.tenant_id, vendor_name)
    existing_constraints = (
        list(existing_template.rules.get("constraints", []) or [])
        if existing_template and isinstance(existing_template.rules, dict)
        else []
    )
    merged_constraints = merge_constraints(existing_constraints, candidate_rules)

    try:
        ocr_text = _run_ocr_split(invoice.file_path)
        result = run_extraction_agent(
            invoice.file_path, ocr_text, str(tenant_context.tenant_id),
            rules={"constraints": merged_constraints},
        )
    except Exception as e:
        logger.warning("Standing-rule safety re-extraction failed for invoice %s: %s", invoice.id, e)
        return {"applied": False, "reason": "Safety re-extraction failed -- rule not applied."}

    re_extracted = result.get("extracted_data") or {}
    for field, diff in correction_diff.items():
        old_comparable = diff["new"]
        new_comparable = re_extracted.get(field)
        if hasattr(new_comparable, "isoformat"):
            new_comparable = new_comparable.isoformat()
        if str(new_comparable) != str(old_comparable):
            return {
                "applied": False,
                "reason": (
                    f"Safety check failed: re-extraction with the candidate rule still didn't "
                    f"produce '{field}' = {diff['new']!r} (got {new_comparable!r}). Rule not applied."
                ),
            }

    changed_by = _resolve_changed_by(db_session, tenant_context)
    if existing_template:
        existing_template.rules = {"constraints": merged_constraints}
        existing_template.version = (existing_template.version or 1) + 1
        existing_template.updated_at = datetime.utcnow()
        db_session.add(existing_template)
        template = existing_template
    else:
        template = ExtractionTemplate(
            id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            vendor_name=vendor_name,
            rules={"constraints": merged_constraints},
            version=1,
        )
        db_session.add(template)

    db_session.flush()  # need template.id for the version row below
    db_session.add(ExtractionTemplateVersion(
        template_id=template.id,
        tenant_id=tenant_context.tenant_id,
        vendor_name=vendor_name,
        version=template.version,
        rules={"constraints": merged_constraints},
        changed_by=changed_by,
    ))

    # Feature 18: `rules_added` stays a list of plain sentences so the existing FE
    # contract is unchanged; the structured objects that were actually persisted
    # are exposed alongside it under a new key rather than replacing it.
    return {
        "applied": True,
        "rules_added": normalize_constraints(candidate_rules, for_prompt=False),
        "rules_added_structured": candidate_rules,
    }


@router.put("/resolve/{invoice_id}")
async def resolve_audit_invoice(
    invoice_id: UUID,
    payload: AuditResolutionPayload,
    # Feature 25 (Gap 335): must be the dual-credential resolver, not
    # get_tenant_context -- the router-level gate above already admitted an
    # `actions`-scoped key, and a Clerk-only resolver here would then 401 the
    # very request it just let through (an `inv_live_` Bearer token is not a
    # verifiable JWT). `context.db_user_id` is the tenant's synthetic API-key
    # service user on that path, which is what keeps the AuditLog write below
    # inside its non-null FK.
    context: TenantContext = Depends(get_tenant_or_api_key_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Enables manual auditor override actions: dismiss alerts, correct extracted
    field values, and/or finalize the invoice as PAID or REJECTED. `status` is
    optional — omit it to just dismiss alerts or save corrections without
    finalizing (e.g. a single alert's "Dismiss" button on a still-AUDIT_REQUIRED
    invoice, which previously always failed because it forced a PAID/REJECTED
    transition even when the auditor wasn't ready to close the invoice out).

    Gap 193: `status=AUDIT_REQUIRED` reopens an already-resolved (PAID/REJECTED)
    invoice — Admin-only, since it undoes another auditor's finalized decision,
    and only valid from a terminal state (reopening a non-terminal invoice is a
    no-op the FE should never send, rejected here rather than silently accepted).

    Gap 407: `status=REVIEW_LATER` / `status=NEEDS_RESUBMISSION` are two more
    non-terminal states — an auditor deferring a decision, or flagging a
    disputed invoice as queued back for vendor correction. Unlike
    AUDIT_REQUIRED's reopen, setting either is **not** Admin-gated (neither
    undoes a prior finalization, so the same restriction doesn't apply), but
    both are blocked from an already-terminal invoice (see the check below) —
    un-finalizing a PAID/REJECTED invoice must still go through the Admin
    reopen path first. Inbound only in this pass: outbound invoices
    (`routers/outbound_invoices.py`) have their own separate status machine
    (`NEEDS_REVIEW`/`VERIFIED`/`SENT`/`PAID`) and are not touched here.
    """
    # 1. Validate status, if one was actually provided
    target_status = None
    if payload.status is not None:
        target_status = payload.status.upper()
        if target_status not in ["PAID", "REJECTED", "AUDIT_REQUIRED", "REVIEW_LATER", "NEEDS_RESUBMISSION"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target status '{payload.status}'. Must be PAID, REJECTED, AUDIT_REQUIRED, REVIEW_LATER, or NEEDS_RESUBMISSION."
            )
        # Gap 420: the Admin gate on AUDIT_REQUIRED moved below, to after the
        # invoice is loaded. It cannot be decided here any more because it now
        # depends on the invoice's CURRENT status: undoing a finalization is
        # Admin-only (Gap 193), but returning a *parked* invoice to the queue
        # is not. See the transition block after the fetch.

    # Gap 125: validate notify list before mutating (only meaningful on finalize).
    if target_status in ("PAID", "REJECTED") and payload.notify_emails:
        try:
            from services.staff_notify import validate_notify_emails
            validate_notify_emails(
                db_session,
                tenant_id=context.tenant_id,
                email_set="inbound",
                notify_emails=payload.notify_emails,
            )
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve

    # 2. Retrieve the target invoice with tenant isolation scope
    statement = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == context.tenant_id,
        invoice_not_deleted(),
    )
    invoice = db_session.exec(statement).first()
    # Gap 421: a superseded invoice is frozen history -- it has been replaced by
    # a corrected upload, and its row survives only so the old data and alerts
    # stay reviewable. Acting on it (approve/reject/park/correct) would write
    # decisions onto a version nobody is using, and those writes would be
    # invisible in every list because `invoice_is_live()` filters it out.
    # Fetched with `invoice_not_deleted()` above rather than `invoice_is_live()`
    # deliberately, so this returns an explicit 409 instead of a misleading 404.
    if invoice is not None and invoice.superseded_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This invoice has been replaced by a resubmitted version and is now "
                "read-only. Act on the replacement instead."
            ),
        )
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or access denied."
        )

    # Two different transitions both land on AUDIT_REQUIRED, and they carry
    # deliberately different permission rules.
    if target_status == "AUDIT_REQUIRED":
        if invoice.status in ("PAID", "REJECTED"):
            # Gap 193 reopen: this undoes another auditor's *finalized*
            # decision, so it stays Admin-only exactly as before.
            if context.role != "Admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only an Admin can reopen a resolved invoice."
                )
        elif invoice.status in ("REVIEW_LATER", "NEEDS_RESUBMISSION"):
            # Gap 420 un-park: parking was never a finalization, so Gap 193's
            # Admin gate does not apply -- whoever could park an invoice can
            # put it back in the queue. Before this, BOTH guards rejected it
            # (the Admin check above, and the PAID/REJECTED-only check below),
            # so a parked invoice could not be returned to the queue by ANY
            # role, including Admin. Parking was a one-way door.
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot reopen an invoice with status '{invoice.status}' — only PAID, "
                    "REJECTED, REVIEW_LATER or NEEDS_RESUBMISSION invoices can be returned "
                    "to the audit queue."
                )
            )

    # Gap 407: REVIEW_LATER / NEEDS_RESUBMISSION are non-terminal deferrals, not
    # finalizations — they must not be reachable directly from an already
    # terminal invoice, or this would silently un-finalize a PAID/REJECTED
    # invoice with no Admin involved. Reopen it via AUDIT_REQUIRED first.
    if target_status in ("REVIEW_LATER", "NEEDS_RESUBMISSION") and invoice.status in ("PAID", "REJECTED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot set '{target_status}' on a {invoice.status} invoice — reopen it first (Admin-only)."
        )

    # Gap 420: capture the status we are transitioning FROM, before it is
    # overwritten below. The audit trail records `target_status` but never
    # recorded where the invoice came from, so a log entry could not tell an
    # Admin undoing a finalization apart from an auditor returning a parked
    # invoice to the queue -- both write action=REOPEN_INVOICE. Recorded in
    # `details` rather than as a new action string on purpose:
    # services/extraction_quality_rollup.py consumes exactly
    # ("RESOLVE_INVOICE", "REOPEN_INVOICE"), so a third action would silently
    # vanish from that rollup.
    previous_status = invoice.status

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

    # Gap 421: persist why it is being sent back. Only meaningful on
    # NEEDS_RESUBMISSION -- this is the text a human will act on when they open
    # the replaced version to see what was wrong. Cleared when the invoice
    # leaves that state (including on un-park), so a stale reason from a
    # previous round can never be shown against a later decision.
    if target_status == "NEEDS_RESUBMISSION":
        invoice.resubmission_reason = (payload.resubmission_reason or "").strip() or None
    elif target_status is not None:
        invoice.resubmission_reason = None

    # 3b. Apply field corrections (Task 7.3), capturing a before/after diff.
    vendor_name_for_pattern = invoice.vendor_name  # capture before a vendor_name correction itself changes it
    correction_diff = _apply_corrections(invoice, payload.corrections or {})

    db_session.add(invoice)

    # 3c. Gap 62/Task 7.5: teach the correction back as a standing rule, gated
    # on the safety re-extraction check. Runs before commit so a passing rule
    # writes land in the same transaction as the invoice correction itself;
    # a failing/skipped rule never touches the session, so the invoice
    # correction always succeeds regardless of this check's outcome.
    standing_rule_result = None
    if payload.apply_as_standing_rule and correction_diff:
        standing_rule_result = _apply_standing_rule(db_session, invoice, correction_diff, context)

    # 4. Save audit log record — corrections included so Task 7.4 can detect
    # recurring patterns across resolves, and so there's a durable record of
    # exactly what a human changed and why.
    log_details = {
        "target_status": target_status,
        # Gap 420: where the invoice came from. Distinguishes an Admin undoing
        # a finalization (PAID/REJECTED -> AUDIT_REQUIRED) from an auditor
        # returning a parked invoice to the queue (REVIEW_LATER /
        # NEEDS_RESUBMISSION -> AUDIT_REQUIRED), which are otherwise identical
        # in the trail because both write action=REOPEN_INVOICE.
        "previous_status": previous_status,
        "reject_reason": payload.reject_reason,
        "dismissed_alerts_input": dismissed_list,
        "previous_alerts": previous_alerts,
        "remaining_alerts": new_alerts,
        "corrections": correction_diff,
        "standing_rule_result": standing_rule_result,
    }


    audit_log = AuditLog(
        tenant_id=context.tenant_id,
        invoice_id=invoice_id,
        actor_user_id=context.db_user_id,
        actor_role=context.role,
        action="REOPEN_INVOICE" if target_status == "AUDIT_REQUIRED" else "RESOLVE_INVOICE",
        details=log_details,
        timestamp=datetime.utcnow()
    )
    db_session.add(audit_log)

    # 5. Commit transaction
    db_session.commit()

    # Gap 317: a finalize action (Mark Paid/Reject/Reopen) moves
    # audit_rate_percent, the aggregate Actionable Insights grounds its
    # "audit rate" recommendation in. Gated on target_status actually being
    # set, same condition the status assignment itself used above -- a plain
    # alert-dismiss/correction with no target_status doesn't move it.
    if target_status is not None:
        try:
            from routers.dashboard import invalidate_insights_cache
            invalidate_insights_cache(invoice.tenant_id)
        except Exception as ie:
            logger.error("Insights cache invalidation failed for %s: %s", invoice.id, ie)

    # Gap 240 backstop: make sure a resolved invoice is in the RAG index, for
    # any row that predates the ingestion-side fix (or whose ingestion-time
    # indexing failed). Deliberately keyed on **the resolution happening at
    # all**, not on the target status: `target_status` is validated above
    # against exactly PAID/REJECTED/AUDIT_REQUIRED and can never be COMPLETED
    # (repo-wide, COMPLETED is only ever set by the queue worker), so a backstop
    # keyed on "reached COMPLETED" would never fire. `target_status` is also
    # None for a plain alert-dismiss/correction, which is still a resolution
    # action worth backstopping.
    try:
        from chroma_client import has_invoice_chunks, index_invoice_document, should_index_status
        if should_index_status(invoice.status) and not await run_in_threadpool(
            has_invoice_chunks, str(invoice.id), str(invoice.tenant_id)
        ):
            logger.info("Backfilling RAG index for resolved invoice %s (no chunks found)", invoice.id)
            await run_in_threadpool(
                index_invoice_document,
                str(invoice.id),
                str(invoice.tenant_id),
                invoice.vendor_name,
                invoice.file_path,
            )
    except Exception as ie:
        # Never fail a human's resolve action because the search index is unhappy.
        logger.error("RAG index backfill failed for resolved invoice %s: %s", invoice.id, ie)

    # Feature 15 (Task 15.4): only fires on an actual PAID/REJECTED
    # finalization -- a plain alert-dismiss/correction (target_status=None)
    # doesn't change the invoice's terminal outcome and isn't one of this
    # feature's subscribable event types. Gap 193's AUDIT_REQUIRED reopen is
    # deliberately excluded too -- it undoes a finalization, it isn't one.
    if target_status in ("PAID", "REJECTED"):
        try:
            from services.webhooks import dispatch_webhook_event
            event_type = "invoice.approved" if target_status == "PAID" else "invoice.rejected"
            dispatch_webhook_event(db_session, invoice.tenant_id, event_type, {
                "invoice_id": str(invoice.id),
                "status": target_status,
                "vendor_name": invoice.vendor_name,
                "grand_total": invoice.grand_total,
                # Gap 215: without this, a subscriber can't tell 40000 apart
                # from ₹40000 vs $40000 on a blended multi-currency tenant.
                "currency": invoice.currency or "USD",
            })
        except Exception as we:
            logger.error("Webhook dispatch failed for invoice %s: %s", invoice.id, we)

    # Feature 25 (Gap 339): the `email_summary` output destination.
    #
    # THIS IS THE SINGLE TRIGGER POINT, and it is placed here on purpose. Both
    # ways of approving an invoice -- a human clicking Approve in the Auditor
    # Review Console, and an `actions`-scoped API key (Gap 335) calling this
    # same PUT -- converge on this one handler; the router-level
    # `require_actions_scope` admits both credential types and
    # `get_tenant_or_api_key_context` normalises them into one TenantContext
    # before the body runs. So there is nothing to duplicate for the second
    # path, and duplicating it would be the bug: two call sites would drift.
    #
    # Fires only on PAID -- "approved". REJECTED is deliberately excluded (a
    # rejected invoice has no result worth exporting), as is Gap 193's
    # AUDIT_REQUIRED reopen, which undoes a finalization rather than being one.
    # This differs from the webhook block above, which fires on both, because
    # that block dispatches two *different* event types.
    #
    # Runs after db_session.commit() above: the summary must describe an
    # invoice that is actually PAID in the database, not one that is about to
    # be. deliver_email_summary() never raises (see its docstring); the
    # try/except is the same belt-and-braces the webhook and RAG blocks use.
    #
    # Gap 338 added the second destination (`drive_archive`) to this same
    # block rather than to a second one, for the same reason: one trigger, one
    # condition, both credential paths.
    email_summary = None
    drive_archive = None
    if target_status == "PAID":
        try:
            from services.workflow_outputs import deliver_email_summary
            email_summary = deliver_email_summary(db_session, invoice)
        except Exception as ee:
            logger.error("Email summary delivery failed for invoice %s: %s", invoice.id, ee)
        try:
            from services.workflow_outputs import deliver_drive_archive
            drive_archive = deliver_drive_archive(db_session, invoice)
        except Exception as de:
            # deliver_drive_archive() never raises either (see its docstring);
            # separate try/except so a fault in one destination cannot suppress
            # the other -- they are independent choices by the tenant.
            logger.error("Drive archive delivery failed for invoice %s: %s", invoice.id, de)

    email_notify = None
    if target_status in ("PAID", "REJECTED"):
        try:
            from services.staff_notify import notify_auditor_action
            email_notify = notify_auditor_action(
                db_session,
                invoice,
                action_label="Mark Paid" if target_status == "PAID" else "Rejected",
                notify_emails=payload.notify_emails,
            )
        except ValueError as ve:
            # Already validated above; defensive only.
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve

    # 6. Task 7.4: suggest a Trainer rule if a correction just made recurred often
    # enough to be worth automating instead of fixing by hand every time.
    suggested_rule = None
    if correction_diff:
        suggested_rule = _detect_correction_pattern(
            db_session, context.tenant_id, vendor_name_for_pattern, list(correction_diff.keys())
        )

    return {
        "success": True,
        "corrections_applied": correction_diff,
        "suggested_rule": suggested_rule,
        "standing_rule_result": standing_rule_result,
        "email_notify": email_notify,
        # Gap 339: null unless the tenant selected the `email_summary` output
        # destination AND this resolve was an approval. Surfaced rather than
        # kept internal so an integration can tell "no summary was configured"
        # apart from "a summary was configured and the send failed" -- the
        # second is actionable, the first is not.
        "email_summary": email_summary,
        # Gap 338: same contract for the Drive destination. Its `code` is the
        # one field worth reading -- `reconnect_required` is how an integration
        # learns the tenant's Drive grant is read-only, without having to parse
        # a message or read the backend's logs.
        "drive_archive": drive_archive,
    }
