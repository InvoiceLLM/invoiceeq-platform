"""Feature 18: the canonical registry of every alert `type` this system produces.

Why this module exists
----------------------
Until now the alert vocabulary was implicit — a `{"type": "..."}` string literal
scattered across seven producers, with no single place that answered "what alerts
can exist?" or "is this one correctable, and by what knob?". The Trainer redesign
needs both answers as *data*: the "flag as missed" flow asks a user to pick the
alert type they expected from a list, and the "unnecessary alert" flow has to
route each type to the right correction form (or refuse it, because it has no
numeric knob at all).

Every entry below was verified against the live producer at the cited line, not
copied from a design doc.

Correctability, deliberately narrow
-----------------------------------
Exactly three types are tolerance-overridable via `abs_tol`/`rel_tol`, because
exactly three come out of the two functions that take a tolerance at all
(`verify_line_items_math`, `verify_totals_math` in `utils/verification_tools.py`).

`low_confidence_field` is *threshold*-overridable, which is a different parameter
(`threshold`, default `CONFIDENCE_THRESHOLD = 0.4`) on a different function
(`verify_field_confidence`) — it gets its own form, not the tolerance one.
Conflating the two would have shipped a form whose numbers silently did nothing.

The five `*_not_verified_in_source` types have **no numeric knob whatsoever**:
they ask a yes/no question ("does this figure appear verbatim in the OCR text?")
that has no tolerance to widen. They are excluded from the tolerance-override
path in this pass by construction, not by omission — see
`TOLERANCE_EXCLUDED_SOURCE_TEXT_TYPES` below and the documented follow-up in
`docs/feature_18_trainer_alert_anchored_training.md`.

duplicate/failed/timeout types aren't correctable by any numeric knob either —
they're facts about the world (this file was seen before / the LLM never
answered), not thresholded judgements.

Severity and message overrides apply to *any* type, since they only relabel an
alert that already fired rather than changing whether it fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Literal


# Correction shapes a type supports. Kept as plain strings so the API can return
# them verbatim and the FE can switch on them without a second mapping table.
CorrectionForm = Literal["tolerance", "confidence_threshold", "severity_message", "none"]


@dataclass(frozen=True)
class AlertTypeSpec:
    """One alert `type` value, with everything the Trainer UI needs to render it."""

    type: str
    label: str
    #: Human-readable "which function emits this", for the registry endpoint and docs.
    producer: str
    #: The field name this alert is normally attached to (`alert["field"]`), or
    #: None when the producer doesn't set one (e.g. duplicate detection).
    default_field: str | None = None
    #: True only for the three types produced by a tolerance-taking check.
    tolerance_overridable: bool = False
    #: True only for `low_confidence_field` (a `threshold`, not a tolerance).
    threshold_overridable: bool = False
    #: Severity/message relabelling works on every type — it never changes
    #: whether the alert fires, only how it reads.
    severity_overridable: bool = True
    #: Why a type is not numerically correctable, surfaced to the user instead of
    #: an unexplained missing button. Empty when it is correctable.
    not_correctable_reason: str = ""
    #: Whether this type is offered in the "flag as missed" picker. Types the user
    #: cannot meaningfully "expect" (a duplicate, a crash, a timeout) are excluded.
    flaggable_as_missed: bool = True
    #: Alternate spellings/aliases seen in stored `sa_alerts` from older rows.
    aliases: tuple[str, ...] = dc_field(default_factory=tuple)

    @property
    def correction_form(self) -> CorrectionForm:
        if self.tolerance_overridable:
            return "tolerance"
        if self.threshold_overridable:
            return "confidence_threshold"
        if self.severity_overridable:
            return "severity_message"
        return "none"


# ---------------------------------------------------------------------------
# The vocabulary. Producer line numbers are the ones verified on 2026-08-13.
# ---------------------------------------------------------------------------

_SOURCE_TEXT_NOT_CORRECTABLE = (
    "This check asks whether the figure appears verbatim in the document's OCR "
    "text — a yes/no question with no numeric tolerance to widen. Correcting it "
    "means fixing the extraction itself, not loosening a threshold."
)

_FACTUAL_NOT_CORRECTABLE = (
    "This alert reports a fact (a matching invoice already exists, or processing "
    "never completed), not a thresholded judgement, so there is no numeric knob "
    "to adjust."
)

ALERT_TYPES: dict[str, AlertTypeSpec] = {
    # ── utils/verification_tools.py ────────────────────────────────────────
    "line_item_calculation_mismatch": AlertTypeSpec(
        type="line_item_calculation_mismatch",
        label="Line item does not match qty x unit price",
        producer="utils/verification_tools.py::verify_line_items_math (:71)",
        default_field="items",
        tolerance_overridable=True,
    ),
    "line_items_mismatch": AlertTypeSpec(
        type="line_items_mismatch",
        label="Line items do not sum to subtotal",
        producer="utils/verification_tools.py::verify_line_items_math (:87)",
        default_field="subtotal",
        tolerance_overridable=True,
    ),
    "tax_mismatch": AlertTypeSpec(
        type="tax_mismatch",
        label="Subtotal + tax does not match grand total",
        producer="utils/verification_tools.py::verify_totals_math (:142)",
        default_field="tax_amount",
        tolerance_overridable=True,
    ),
    "total_not_verified_in_source": AlertTypeSpec(
        type="total_not_verified_in_source",
        label="Grand total not found verbatim in the document",
        producer="utils/verification_tools.py::verify_grand_total_in_source_text (:225)",
        default_field="grand_total",
        not_correctable_reason=_SOURCE_TEXT_NOT_CORRECTABLE,
    ),
    "line_item_not_verified_in_source": AlertTypeSpec(
        type="line_item_not_verified_in_source",
        label="Line item amount not found verbatim in the document",
        producer="utils/verification_tools.py::verify_line_item_amounts_in_source_text (:275)",
        default_field="items",
        not_correctable_reason=_SOURCE_TEXT_NOT_CORRECTABLE,
    ),
    "subtotal_not_verified_in_source": AlertTypeSpec(
        type="subtotal_not_verified_in_source",
        label="Subtotal not found verbatim in the document",
        producer="utils/verification_tools.py::verify_subtotal_in_source_text (:305)",
        default_field="subtotal",
        not_correctable_reason=_SOURCE_TEXT_NOT_CORRECTABLE,
    ),
    "unit_price_not_verified_in_source": AlertTypeSpec(
        type="unit_price_not_verified_in_source",
        label="Unit price not found verbatim in the document",
        producer="utils/verification_tools.py::verify_unit_prices_in_source_text (:344)",
        default_field="items",
        not_correctable_reason=_SOURCE_TEXT_NOT_CORRECTABLE,
    ),
    "tax_amount_not_verified_in_source": AlertTypeSpec(
        type="tax_amount_not_verified_in_source",
        label="Tax amount not found verbatim in the document",
        producer="utils/verification_tools.py::verify_tax_amount_in_source_text (:412)",
        default_field="tax_amount",
        not_correctable_reason=_SOURCE_TEXT_NOT_CORRECTABLE,
    ),
    "low_confidence_field": AlertTypeSpec(
        type="low_confidence_field",
        label="OCR confidence below threshold",
        producer="utils/verification_tools.py::verify_field_confidence (:500)",
        default_field=None,
        threshold_overridable=True,
    ),
    # ── agents/extraction_agent.py (one shared graph, both directions) ─────
    # Gap 283: outbound no longer has its own extract/verify nodes -- it runs
    # the same graph with flow_direction="OUTBOUND", so these producers are
    # single-sited now.
    "extraction_failed": AlertTypeSpec(
        type="extraction_failed",
        label="Structured extraction failed",
        producer="agents/extraction_agent.py::extract_node",
        default_field=None,
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
    "token_limit_exceeded": AlertTypeSpec(
        type="token_limit_exceeded",
        label="Document too large for the model context window",
        producer="agents/extraction_agent.py::run_extraction_agent",
        default_field="file_path",
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
    "missing_required_field": AlertTypeSpec(
        type="missing_required_field",
        label="Required outbound field could not be extracted",
        producer="agents/extraction_agent.py::verify_node (OUTBOUND profile only)",
        default_field=None,
    ),
    # ── queue_worker/ + routers/invoices.py ────────────────────────────────
    "duplicate_invoice": AlertTypeSpec(
        type="duplicate_invoice",
        label="Duplicate invoice (same number + vendor)",
        producer="queue_worker/handlers.py::handle_process_invoice (:663)",
        default_field=None,
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
    "duplicate_invoice_number": AlertTypeSpec(
        type="duplicate_invoice_number",
        label="Duplicate outbound invoice (same number + customer)",
        producer="queue_worker/outbound_handlers.py::handle_process_outbound_invoice (:87)",
        default_field=None,
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
    "duplicate": AlertTypeSpec(
        type="duplicate",
        label="Duplicate upload (same file bytes)",
        producer="routers/invoices.py::_ingest_single_file (:93,:137)",
        default_field=None,
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
    # ── services/invoice_reconciliation.py ─────────────────────────────────
    "processing_failed": AlertTypeSpec(
        type="processing_failed",
        label="Processing failed",
        producer="services/invoice_reconciliation.py (default, :63)",
        default_field=None,
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
    "processing_timeout": AlertTypeSpec(
        type="processing_timeout",
        label="Processing timed out",
        producer="services/invoice_reconciliation.py (:180)",
        default_field=None,
        not_correctable_reason=_FACTUAL_NOT_CORRECTABLE,
        flaggable_as_missed=False,
    ),
}


#: The three types a tolerance override can legitimately act on. Anything else
#: sent to the tolerance endpoint is a 400, not a silently-ignored write.
TOLERANCE_OVERRIDABLE_TYPES: frozenset[str] = frozenset(
    t for t, spec in ALERT_TYPES.items() if spec.tolerance_overridable
)

#: `low_confidence_field` only. Separate constant so a future second
#: threshold-driven check is added here rather than smuggled into the tolerance set.
THRESHOLD_OVERRIDABLE_TYPES: frozenset[str] = frozenset(
    t for t, spec in ALERT_TYPES.items() if spec.threshold_overridable
)

#: Deliberately excluded from the "unnecessary alert" tolerance path in this
#: pass. Documented as a follow-up in feature_18, NOT a silent omission.
TOLERANCE_EXCLUDED_SOURCE_TEXT_TYPES: frozenset[str] = frozenset({
    "total_not_verified_in_source",
    "line_item_not_verified_in_source",
    "subtotal_not_verified_in_source",
    "unit_price_not_verified_in_source",
    "tax_amount_not_verified_in_source",
})

#: Severity values an override may set. Matches what the producers already emit
#: ("error"/"warning"); "info" is added so a tenant can demote an alert to a
#: note without suppressing it entirely.
VALID_SEVERITIES: frozenset[str] = frozenset({"error", "warning", "info"})


def get_alert_type(alert_type: str | None) -> AlertTypeSpec | None:
    """Look up a spec, tolerating None and unknown types (returns None)."""
    if not alert_type:
        return None
    return ALERT_TYPES.get(alert_type)


def is_known_alert_type(alert_type: str | None) -> bool:
    return bool(alert_type) and alert_type in ALERT_TYPES


def list_alert_types(flaggable_only: bool = False) -> list[dict]:
    """Registry as plain JSON-able dicts, for `GET /trainer/alert-types`.

    `flaggable_only=True` returns just the types a user can meaningfully say
    "I expected this and didn't get it" about — duplicates, crashes and timeouts
    are not things a rule can teach the system to notice.
    """
    specs = ALERT_TYPES.values()
    if flaggable_only:
        specs = [s for s in specs if s.flaggable_as_missed]
    return [
        {
            "type": s.type,
            "label": s.label,
            "producer": s.producer,
            "defaultField": s.default_field,
            "toleranceOverridable": s.tolerance_overridable,
            "thresholdOverridable": s.threshold_overridable,
            "severityOverridable": s.severity_overridable,
            "correctionForm": s.correction_form,
            "notCorrectableReason": s.not_correctable_reason,
            "flaggableAsMissed": s.flaggable_as_missed,
        }
        for s in sorted(specs, key=lambda s: s.label.lower())
    ]
