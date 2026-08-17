"""Feature 18: historical impact replay behind the preview-before-commit gate.

What this is for
----------------
Before a rule is committed, the user is shown what it would actually have done
to their existing invoices. That number has to be either **real** or **absent** —
a plausible-looking estimate is worse than no estimate, because the whole point
of the preview gate is to stop people committing rules whose effect they haven't
seen.

So there are exactly two answers:

* **exact** — the rule is a pure function over columns already stored on
  `Invoice`, so it can be replayed by re-running the same verification function
  the pipeline uses, against every historical row. No re-extraction, no OCR, no
  LLM call: a query plus a loop.
* **not_computable** — the rule is a free-text extraction instruction. Its effect
  depends on how an LLM reads a PDF, which cannot be known without actually
  re-running OCR + extraction on every historical invoice. We say so, and show no
  number.

A real constraint found during implementation
---------------------------------------------
`Invoice` has **no `subtotal` column** (verified against `models.py` — it stores
`grand_total`, `tax_amount`, `items`, `discount_amount`, `discount_percent`, but
subtotal is extracted and never persisted). Two of the three tolerance-overridable
checks need it:

* `line_item_calculation_mismatch` — replayable **exactly** without it: the
  per-line check only compares `quantity * unit_price` against `amount`, all of
  which live in the stored `items` JSON. (`verify_line_items_math` takes a
  subtotal purely as an early-return guard, and its per-line loop runs first.)
* `line_items_mismatch` and `tax_mismatch` — genuinely need a subtotal. It is
  recovered from `Invoice.source_document_json["SubTotal"]` (Gap 178 persists
  Doc Intelligence's own reading of the document) when present. When it is not
  present, those two types are reported **not computable for that invoice** —
  never estimated, and never silently counted as "no change", which would have
  understated the impact of exactly the rules most likely to be committed.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from models import Invoice
from services.invoice_visibility import invoice_not_deleted
from utils.rule_schema import (
    KIND_ALERT_OVERRIDE,
    KIND_CONFIDENCE,
    KIND_EXTRACTION,
    KIND_TOLERANCE,
    SCOPE_OUTBOUND_GLOBAL,
    alert_overrides,
    confidence_threshold_override,
    render_constraint,
    rule_kind,
    tolerance_overrides,
)
from utils.verification_tools import (
    verify_field_confidence,
    verify_line_items_math,
    verify_totals_math,
)

logger = logging.getLogger(__name__)

#: Cap on how many historical invoices a single preview replays. A preview is an
#: interactive request; a tenant with 100k invoices must not turn it into a
#: multi-second table scan. The response reports how many were actually examined
#: so the number is never presented as "all of them" when it isn't.
MAX_REPLAY_INVOICES = 500

IMPACT_EXACT = "exact"
IMPACT_NOT_COMPUTABLE = "not_computable"
IMPACT_PARTIAL = "partial"

_TEXT_RULE_REASON = (
    "This is a free-text extraction instruction. Its effect depends on how the "
    "model reads each PDF, which cannot be known without re-running OCR and "
    "extraction on every historical invoice — so no impact count is shown rather "
    "than an estimated one."
)

_NO_SUBTOTAL_REASON = (
    "Subtotal is not stored as a column on the invoice, and Doc Intelligence's "
    "reading of it is not available for some of these invoices, so the "
    "subtotal-sum and totals checks could not be replayed for them."
)


def _recover_subtotal(invoice: Invoice) -> float | None:
    """Best-effort subtotal for a stored invoice — Doc Intelligence's own reading.

    Returns None rather than guessing. A caller that gets None must treat the
    subtotal-dependent checks as not computable for that invoice.
    """
    source = getattr(invoice, "source_document_json", None)
    if not isinstance(source, dict):
        return None
    field = source.get("SubTotal") or source.get("Subtotal")
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    if isinstance(value, dict):  # currency field: {"amount": .., "currency_code": ..}
        value = value.get("amount")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _sum_line_amounts(items: list) -> float:
    total = 0.0
    for item in items or []:
        if isinstance(item, dict):
            try:
                total += float(item.get("amount") or 0.0)
            except (TypeError, ValueError):
                continue
    return total


def _replay_invoice(
    invoice: Invoice,
    tolerances: dict,
    threshold: float | None,
) -> tuple[set[str], set[str]]:
    """Re-run the replayable checks for one invoice.

    Returns `(fired_types, not_computable_types)`. Uses the *same* verification
    functions the pipeline uses — this module never re-implements the maths, so
    the preview cannot drift away from what the pipeline will actually do.
    """
    fired: set[str] = set()
    not_computable: set[str] = set()

    items = invoice.items if isinstance(invoice.items, list) else []
    real_subtotal = _recover_subtotal(invoice)
    tax_amount = invoice.tax_amount
    grand_total = invoice.grand_total

    if items:
        # When the true subtotal is unknown, feed the sum of line amounts: it
        # makes the subtotal-sum comparison trivially pass (so we must NOT report
        # on `line_items_mismatch`), while leaving the per-line arithmetic check
        # — which uses only stored `items` fields — exactly as the pipeline runs it.
        subtotal_for_lines = real_subtotal if real_subtotal is not None else _sum_line_amounts(items)
        try:
            alert = verify_line_items_math(
                items, subtotal_for_lines, invoice_tax_amount=tax_amount, tolerances=tolerances
            )
        except Exception as e:  # a malformed stored items blob must not break the preview
            logger.warning("Impact replay: line-item check failed for invoice %s: %s", invoice.id, e)
            alert = None
            not_computable.update({"line_item_calculation_mismatch", "line_items_mismatch"})
        if alert:
            fired.add(alert.get("type"))
        if real_subtotal is None:
            not_computable.add("line_items_mismatch")

    if real_subtotal is not None:
        try:
            totals_alert = verify_totals_math(
                real_subtotal,
                tax_amount,
                grand_total,
                discount_amount=invoice.discount_amount,
                discount_percent=invoice.discount_percent,
                tolerances=tolerances,
            )
        except Exception as e:
            logger.warning("Impact replay: totals check failed for invoice %s: %s", invoice.id, e)
            totals_alert = None
            not_computable.add("tax_mismatch")
        if totals_alert:
            fired.add(totals_alert.get("type"))
    else:
        not_computable.add("tax_mismatch")

    # field_confidence IS a stored column, so this one is always exact.
    field_confidence = invoice.field_confidence if isinstance(invoice.field_confidence, dict) else {}
    if field_confidence:
        try:
            confidence_alerts = (
                verify_field_confidence(field_confidence, threshold=threshold)
                if threshold is not None
                else verify_field_confidence(field_confidence)
            )
        except Exception as e:
            logger.warning("Impact replay: confidence check failed for invoice %s: %s", invoice.id, e)
            confidence_alerts = []
            not_computable.add("low_confidence_field")
        if confidence_alerts:
            fired.add("low_confidence_field")

    return fired, not_computable


def _fetch_invoices(
    db_session: Session,
    tenant_id: UUID,
    scope: str,
    vendor_name: str | None,
) -> list[Invoice]:
    stmt = select(Invoice).where(Invoice.tenant_id == tenant_id, invoice_not_deleted())
    if scope == SCOPE_OUTBOUND_GLOBAL:
        stmt = stmt.where(Invoice.flow_direction == "OUTBOUND")
    elif vendor_name:
        stmt = stmt.where(Invoice.vendor_name == vendor_name, Invoice.flow_direction == "INBOUND")
    stmt = stmt.order_by(Invoice.created_at.desc()).limit(MAX_REPLAY_INVOICES)
    return list(db_session.exec(stmt).all())


def _rule_identity(rule: Any) -> str:
    """Stable-enough identity for diffing candidate rules against committed ones."""
    text = render_constraint(rule) or ""
    if isinstance(rule, dict):
        return f"{rule.get('kind')}|{rule.get('source_alert_type')}|{rule.get('field')}|{text}"
    return f"{KIND_EXTRACTION}|||{text}"


def new_rules(baseline: list, candidate: list) -> list:
    """The rules present in `candidate` that aren't already committed in `baseline`."""
    known = {_rule_identity(r) for r in (baseline or [])}
    return [r for r in (candidate or []) if _rule_identity(r) not in known]


def describe_rule(rule: Any) -> dict:
    """Plain-terms interpretation of one rule, for the preview response.

    This is what makes the gate meaningful: the user sees field / condition /
    scope spelled out, not the sentence an LLM happened to generate.
    """
    if isinstance(rule, dict):
        return {
            "kind": rule_kind(rule),
            "field": rule.get("field") or "*",
            "condition": rule.get("condition") or "",
            "scope": rule.get("scope"),
            "sourceAlertType": rule.get("source_alert_type"),
            "origin": rule.get("origin"),
            "text": render_constraint(rule),
            "params": rule.get("params") or {},
        }
    return {
        "kind": KIND_EXTRACTION,
        "field": "*",
        "condition": "prompt_instruction",
        "scope": None,
        "sourceAlertType": None,
        "origin": "legacy_text",
        "text": render_constraint(rule),
        "params": {},
    }


def compute_rule_impact(
    db_session: Session,
    tenant_id: UUID,
    *,
    scope: str,
    vendor_name: str | None,
    baseline_constraints: list,
    candidate_constraints: list,
) -> dict:
    """Replay the candidate rules against stored invoices. Never fabricates a count.

    `baseline_constraints` are what is committed today; `candidate_constraints`
    are what the session would commit. Only the difference is described and
    replayed — re-reporting the effect of already-live rules would inflate the
    number the user is being asked to approve.
    """
    delta = new_rules(baseline_constraints, candidate_constraints)
    descriptions = [describe_rule(r) for r in delta]

    kinds = {rule_kind(r) for r in delta}
    has_text_rule = KIND_EXTRACTION in kinds
    numeric_kinds = kinds & {KIND_TOLERANCE, KIND_CONFIDENCE, KIND_ALERT_OVERRIDE}

    result: dict[str, Any] = {
        "rules": descriptions,
        "invoicesExamined": 0,
        "alertsRemoved": None,
        "alertsAdded": None,
        "invoicesAffected": None,
        "alertsRelabelled": None,
        "sample": [],
        "notComputable": [],
    }

    if not delta:
        result["kind"] = IMPACT_EXACT
        result["summary"] = "No new rules — nothing would change."
        return result

    if has_text_rule:
        result["notComputable"].append({"reason": _TEXT_RULE_REASON, "appliesTo": "extraction rules"})

    if not numeric_kinds:
        # Purely text rules: be explicit rather than showing a zero.
        result["kind"] = IMPACT_NOT_COMPUTABLE
        result["summary"] = (
            "This rule changes how the model reads invoices. Its historical effect "
            "can't be computed without re-processing every past invoice, so no "
            "count is shown."
        )
        return result

    invoices = _fetch_invoices(db_session, tenant_id, scope, vendor_name)
    result["invoicesExamined"] = len(invoices)

    baseline_tol = tolerance_overrides(baseline_constraints)
    candidate_tol = tolerance_overrides(candidate_constraints)
    baseline_threshold = confidence_threshold_override(baseline_constraints)
    candidate_threshold = confidence_threshold_override(candidate_constraints)

    #: Only report on the alert types the delta actually targets.
    targeted_types = {
        r.get("source_alert_type")
        for r in delta
        if isinstance(r, dict) and r.get("source_alert_type")
    }

    removed = 0
    added = 0
    affected_invoices = 0
    uncomputable_types: set[str] = set()
    sample: list[dict] = []

    for invoice in invoices:
        before, before_unknown = _replay_invoice(invoice, baseline_tol, baseline_threshold)
        after, after_unknown = _replay_invoice(invoice, candidate_tol, candidate_threshold)
        unknown = (before_unknown | after_unknown) & targeted_types
        uncomputable_types |= unknown

        gone = (before - after) & targeted_types - unknown
        appeared = (after - before) & targeted_types - unknown
        if gone or appeared:
            affected_invoices += 1
            removed += len(gone)
            added += len(appeared)
            if len(sample) < 10:
                sample.append({
                    "invoiceId": str(invoice.id),
                    "invoiceNumber": invoice.invoice_number,
                    "vendorName": invoice.vendor_name or invoice.customer_name,
                    "alertsRemoved": sorted(gone),
                    "alertsAdded": sorted(appeared),
                })

    result["alertsRemoved"] = removed
    result["alertsAdded"] = added
    result["invoicesAffected"] = affected_invoices
    result["sample"] = sample

    # Severity/message overrides don't change whether an alert fires, so their
    # impact is "how many stored alerts would now read differently".
    override_specs = alert_overrides(delta)
    if override_specs:
        relabelled = 0
        override_types = {o["type"] for o in override_specs if o.get("type")}
        for invoice in invoices:
            for alert in (invoice.sa_alerts or []):
                if isinstance(alert, dict) and alert.get("type") in override_types:
                    relabelled += 1
        result["alertsRelabelled"] = relabelled

    if uncomputable_types:
        result["notComputable"].append({
            "reason": _NO_SUBTOTAL_REASON,
            "appliesTo": sorted(uncomputable_types),
        })

    result["kind"] = IMPACT_PARTIAL if result["notComputable"] else IMPACT_EXACT
    result["summary"] = _summarize(result)
    return result


def _summarize(result: dict) -> str:
    bits = []
    removed = result.get("alertsRemoved")
    added = result.get("alertsAdded")
    relabelled = result.get("alertsRelabelled")
    examined = result.get("invoicesExamined") or 0
    affected = result.get("invoicesAffected") or 0

    if removed:
        bits.append(f"{removed} alert(s) would no longer fire")
    if added:
        bits.append(f"{added} new alert(s) would fire")
    if relabelled:
        bits.append(f"{relabelled} existing alert(s) would be relabelled")
    if not bits:
        bits.append("no change to any existing alert")
    return (
        f"Replayed against {examined} stored invoice(s): "
        + ", ".join(bits)
        + f" (across {affected} invoice(s))."
    )
