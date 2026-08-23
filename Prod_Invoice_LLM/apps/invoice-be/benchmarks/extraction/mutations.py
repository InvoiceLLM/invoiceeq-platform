"""The seeded set: named, single-issue mutations with a recorded expectation.

Every mutator here answers four questions in one place, and the review manifest
is generated straight out of those four answers rather than described separately:

  1. **What was changed** — the field or the OCR line, by name.
  2. **What the correct value was** — copied off the clean spec, not retyped.
  3. **What was planted instead** — the value after mutation.
  4. **Which alert must fire** — an exact `type` string from
     `utils/verification_tools.py` / `agents/extraction_agent.py::verify_node`.

Two mutation surfaces, and the difference is not cosmetic
----------------------------------------------------------
The extraction pipeline has two genuinely different failure modes, and they can
only be seeded on different sides of it:

  * ``surface="document"`` — the **OCR text** is mutated. The document itself is
    now internally inconsistent (the vendor's own arithmetic is wrong, or a
    required field is not printed). A correct extraction transcribes it
    faithfully, and an arithmetic check is what catches it. These cases are
    fully gradeable in **both** run modes, because a live model reading the
    mutated text should reproduce the planted inconsistency.

  * ``surface="extraction"`` — the **extracted record** is mutated while the OCR
    text is left clean. This simulates the model itself going wrong: a
    fabricated total, a silently "corrected" tax figure, a dropped required
    field. The source-text faithfulness checks (Gaps 33/36/43/44/46) exist for
    exactly this and nothing else can catch it. These cases are gradeable in
    **verify-only** mode only — in live mode a correctly-behaving model will not
    reproduce the planted error, so there is nothing to detect, and the harness
    reports them as `not_applicable` rather than as a miss. That distinction is
    load-bearing: counting them as misses would make live-mode recall look
    catastrophic for the wrong reason.

Tolerance sizing
----------------
`verify_line_items_math` / `verify_totals_math` accept `max(0.01, 0.5%
relative)` (Gap 31). Every arithmetic mutation below shifts a figure by a
percentage of the affected amount with a fixed floor, so it clears that band on
a EUR 18,170 invoice and on an INR 102,070 one alike, rather than by a flat few
units that a large invoice would swallow. `_shift()` is the single place that
policy lives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from benchmarks.extraction.documents import CLEAN_BY_ID, InvoiceSpec

#: Relative and absolute components of every arithmetic mutation. Chosen against
#: `REL_TOLERANCE` in `utils/verification_tools.py` (0.005) with roughly an
#: order of magnitude of headroom, so a mutation is never "just barely" outside
#: tolerance and a recall miss is never explainable as a near-miss.
MUTATION_REL = 0.05
MUTATION_ABS_FLOOR = 25.0


def _shift(value: float) -> float:
    """A deliberately-out-of-tolerance delta for `value`, rounded to the cent."""
    return round(max(abs(value) * MUTATION_REL, MUTATION_ABS_FLOOR), 2)


@dataclass
class SeededCase:
    """One clean document plus exactly one planted issue.

    One issue per case on purpose. Two planted issues in one document would make
    "did the right check fire" ambiguous — a single alert could be attributed to
    either — and alert recall is the whole reason this set exists.
    """

    case_id: str
    doc_id: str
    mutation: str
    surface: str  # "document" | "extraction"
    #: The alert `type` that MUST appear for this case to count as a recall hit.
    expected_alert_type: str
    #: Alert types that are an acceptable, non-penalised side effect of the same
    #: planted issue. A mis-printed line amount, for instance, legitimately
    #: breaks both the per-line check and the subtotal sum. Anything fired that
    #: is neither the expected type nor in here is reported as collateral.
    tolerated_alert_types: tuple[str, ...]
    field_path: str
    correct_value: Any
    planted_value: Any
    #: Why this specific issue is worth planting — the real-world shape it
    #: stands for. Rendered verbatim into the review manifest.
    rationale: str
    ocr_text: str
    extracted_data: dict[str, Any]
    flow_direction: str
    #: The ground truth of the *underlying clean* document. Field accuracy on a
    #: seeded case is still graded against the clean truth for every field the
    #: mutation did not touch.
    clean_ground_truth: dict[str, Any] = field(default_factory=dict)

    @property
    def gradeable_live(self) -> bool:
        """Can live mode (real LLM over the OCR text) reproduce this issue?"""
        return self.surface == "document"


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------
# Each returns (ocr_text, extracted_data, field_path, correct, planted). The
# harness supplies a pristine copy of both, so a mutator may edit in place.

Mutator = Callable[[InvoiceSpec, str, dict], tuple[str, dict, str, Any, Any]]


def _replace_money_in_text(text: str, old: float, new: float, *, on_line_with: str) -> str:
    """Rewrite one printed money figure on one identified line.

    Deliberately narrow on both axes. It matches only the thousands-separated
    2dp form the renderer emits (so a mutation cannot accidentally rewrite a
    quantity, a rate or a date that shares digits), and only on lines containing
    `on_line_with` — because the same figure legitimately appears twice on a
    real invoice. On the zero-VAT document the subtotal and the grand total are
    the same number, and a whole-text replace would silently mutate both, which
    would make the manifest's "what was changed" entry a lie.

    Raises unless exactly one line changes. A mutation that silently no-ops, or
    that hits more than it claimed, is the one failure this module exists to
    prevent.
    """
    old_s = f"{old:,.2f}"
    new_s = f"{new:,.2f}"
    pattern = re.compile(rf"(?<!\d){re.escape(old_s)}(?!\d)")
    lines = text.splitlines()
    hits = 0
    for i, line in enumerate(lines):
        if on_line_with not in line:
            continue
        rewritten, count = pattern.subn(new_s, line)
        if count:
            lines[i] = rewritten
            hits += count
    if hits != 1:
        raise ValueError(
            f"mutation target {old_s!r} on a line containing {on_line_with!r} "
            f"matched {hits} times, expected exactly 1"
        )
    return "\n".join(lines)


# --- document-surface mutations (the vendor's own document is wrong) --------


def mutate_printed_total_does_not_reconcile(spec, ocr, data):
    """The printed TOTAL DUE does not equal subtotal - discount + tax.

    Real shape: a vendor's totals block that simply does not add up. Faithful
    extraction transcribes the wrong total, and `verify_totals_math` is the only
    thing that notices.
    """
    planted = round(spec.grand_total + _shift(spec.grand_total), 2)
    ocr = _replace_money_in_text(ocr, spec.grand_total, planted, on_line_with="TOTAL DUE:")
    data["grand_total"] = planted
    return ocr, data, "grand_total", spec.grand_total, planted


def mutate_printed_subtotal_not_sum_of_lines(spec, ocr, data):
    """The printed Subtotal does not equal the sum of the printed line amounts."""
    planted = round(spec.subtotal - _shift(spec.subtotal), 2)
    ocr = _replace_money_in_text(ocr, spec.subtotal, planted, on_line_with="Subtotal:")
    data["subtotal"] = planted
    return ocr, data, "subtotal", spec.subtotal, planted


def mutate_printed_line_amount_off(spec, ocr, data):
    """One printed line amount is not quantity x unit price.

    Gap 269's shape ("5,000 units at USD 0.08 printed as USD 420.00"), planted
    on purpose. The largest line is chosen so the delta is unambiguous.
    """
    idx = max(range(len(spec.lines)), key=lambda i: abs(spec.lines[i].amount))
    line = spec.lines[idx]
    planted = round(line.amount + _shift(line.amount), 2)
    ocr = _replace_money_in_text(ocr, line.amount, planted, on_line_with=line.description)
    data["items"][idx]["amount"] = planted
    return ocr, data, f"items[{idx}].amount", line.amount, planted


def mutate_required_field_not_printed(spec, ocr, data):
    """The customer name is absent from the document entirely (OUTBOUND only).

    `_DIRECTION_PROFILES["OUTBOUND"].required_fields` is
    `("customer_name", "invoice_number", "grand_total")`; INBOUND deliberately
    has none, so this mutation is only meaningful on the outbound document.
    """
    ocr = ocr.replace(f"Bill To: {spec.party_name}\n", "Bill To:\n")
    ocr = ocr.replace(spec.party_name, "")
    data["customer_name"] = None
    return ocr, data, "customer_name", spec.party_name, None


# --- extraction-surface mutations (the model went wrong) -------------------


def mutate_fabricated_total(spec, ocr, data):
    """The extracted grand_total appears nowhere in the OCR text.

    The pure hallucination case. Note the delta is chosen so the fabricated
    figure still reconciles arithmetically is NOT possible here -- it will also
    trip `verify_totals_math`, which is listed as tolerated. The check under
    test is `verify_grand_total_in_source_text` (Gap 33).
    """
    planted = round(spec.grand_total + _shift(spec.grand_total) + 0.37, 2)
    data["grand_total"] = planted
    return ocr, data, "grand_total", spec.grand_total, planted


def mutate_tax_silently_corrected(spec, ocr, data):
    """The extracted tax_amount is a figure the document never prints.

    Gap 46's exact shape: the model "helpfully" recalculates a tax figure so the
    totals block balances, instead of transcribing what is printed. Only
    `verify_tax_amount_in_source_text` can see it, because a self-corrected tax
    figure by construction passes the arithmetic check.
    """
    planted = round(spec.tax_amount + _shift(spec.tax_amount) + 0.13, 2)
    data["tax_amount"] = planted
    return ocr, data, "tax_amount", spec.tax_amount, planted


def mutate_subtotal_not_in_source(spec, ocr, data):
    """The extracted subtotal appears nowhere in the OCR text (Gap 43)."""
    planted = round(spec.subtotal + _shift(spec.subtotal) + 0.11, 2)
    data["subtotal"] = planted
    return ocr, data, "subtotal", spec.subtotal, planted


def mutate_unit_price_not_in_source(spec, ocr, data):
    """An extracted unit price appears nowhere in the OCR text (Gap 44)."""
    idx = max(range(len(spec.lines)), key=lambda i: abs(spec.lines[i].unit_price))
    line = spec.lines[idx]
    planted = round(line.unit_price + _shift(line.unit_price) + 0.07, 2)
    data["items"][idx]["unit_price"] = planted
    return ocr, data, f"items[{idx}].unit_price", line.unit_price, planted


def mutate_line_amount_not_in_source(spec, ocr, data):
    """An extracted line amount appears nowhere in the OCR text (Gap 36)."""
    idx = 0
    line = spec.lines[idx]
    planted = round(line.amount + _shift(line.amount) + 0.03, 2)
    data["items"][idx]["amount"] = planted
    return ocr, data, f"items[{idx}].amount", line.amount, planted


def mutate_required_field_dropped(spec, ocr, data):
    """The model returns no customer_name even though the document prints one.

    Distinct from `mutate_required_field_not_printed`: there the document is at
    fault, here the extraction is. Same alert, two different causes — which is
    itself worth having both of, because a check that only fires on one of them
    is half-built.
    """
    data["customer_name"] = None
    return ocr, data, "customer_name", spec.party_name, None


def mutate_low_field_confidence(spec, ocr, data):
    """Document Intelligence reports low confidence on grand_total (Gap 3).

    Seeded on the OCR *result* rather than the text or the record — it is the
    only one of the ten alert types whose input is neither. Handled by
    `ocr_result_for()` below rather than by editing `data`.

    The key is Document Intelligence's own field name (`InvoiceTotal`), not the
    schema's — `verify_field_confidence` reads `CRITICAL_CONFIDENCE_FIELDS` and
    maps to schema names on the way out, so a stub keyed on `grand_total` would
    be silently ignored and this case would look like a recall miss.
    """
    return ocr, data, "ocr_result.field_confidence.InvoiceTotal", 0.97, 0.31


# ---------------------------------------------------------------------------
# The frozen seeded set
# ---------------------------------------------------------------------------
# (case suffix, doc_id, mutator, surface, expected alert, tolerated alerts,
#  rationale)
_PLAN: tuple[tuple[str, str, Mutator, str, str, tuple[str, ...], str], ...] = (
    # -- document surface --------------------------------------------------
    (
        "printed_total_broken",
        "us_flat_sales_tax",
        mutate_printed_total_does_not_reconcile,
        "document",
        "tax_mismatch",
        ("total_not_verified_in_source",),
        "A vendor totals block that does not add up. The commonest real audit "
        "finding, and the reason `verify_totals_math` is the first check.",
    ),
    (
        "printed_total_broken_gst",
        "india_cgst_sgst_round_off",
        mutate_printed_total_does_not_reconcile,
        "document",
        "tax_mismatch",
        ("total_not_verified_in_source",),
        "The same break on a split-tax invoice, where the tax figure being "
        "summed from two components gives the check one more way to go wrong.",
    ),
    (
        "printed_subtotal_mismatch",
        "eu_reverse_charge_zero_vat",
        mutate_printed_subtotal_not_sum_of_lines,
        "document",
        "line_items_mismatch",
        ("tax_mismatch", "subtotal_not_verified_in_source"),
        "A subtotal that does not equal the lines above it. Planted on the "
        "zero-VAT invoice specifically: with tax at 0.00 the totals check and "
        "the line-sum check cannot cover for each other.",
    ),
    (
        "printed_line_amount_off",
        "us_flat_sales_tax",
        mutate_printed_line_amount_off,
        "document",
        "line_item_calculation_mismatch",
        ("line_items_mismatch", "tax_mismatch", "line_item_not_verified_in_source"),
        "Gap 269's shape: a printed line amount that is not quantity x unit "
        "price. The out-of-tolerance line-item mismatch the feature doc names.",
    ),
    (
        "required_field_not_printed",
        "outbound_trade_discount",
        mutate_required_field_not_printed,
        "document",
        "missing_required_field",
        ("tax_mismatch",),
        "An outbound invoice with no customer name printed on it at all. The "
        "missing-required-field case from the feature doc's table.",
    ),
    # -- extraction surface ------------------------------------------------
    (
        "fabricated_total",
        "india_cgst_sgst_round_off",
        mutate_fabricated_total,
        "extraction",
        "total_not_verified_in_source",
        ("tax_mismatch",),
        "The fabricated total from the feature doc's table. Nothing but the "
        "Gap 33 source-text check can see a number the document never printed.",
    ),
    (
        "tax_silently_corrected",
        "us_flat_sales_tax",
        mutate_tax_silently_corrected,
        "extraction",
        "tax_amount_not_verified_in_source",
        ("tax_mismatch",),
        "'A tax figure that doesn't match the OCR text', verbatim from the "
        "feature doc. Gap 46: the model recalculating rather than transcribing.",
    ),
    (
        "tax_silently_corrected_split",
        "india_cgst_sgst_round_off",
        mutate_tax_silently_corrected,
        "extraction",
        "tax_amount_not_verified_in_source",
        ("tax_mismatch",),
        "The same fabrication on the CGST+SGST invoice, where the correct "
        "summed figure is itself never printed. This is the case that tells a "
        "working Gap 69 component fallback apart from one that just never "
        "fires -- the clean version of this document must stay silent and this "
        "one must not.",
    ),
    (
        "subtotal_not_in_source",
        "eu_reverse_charge_zero_vat",
        mutate_subtotal_not_in_source,
        "extraction",
        "subtotal_not_verified_in_source",
        ("tax_mismatch", "line_items_mismatch"),
        "Gap 43's check, on the invoice where subtotal and grand total are "
        "equal -- so a check that accidentally matched the grand total instead "
        "would pass here for the wrong reason and be caught by nothing else.",
    ),
    (
        "unit_price_not_in_source",
        "india_cgst_sgst_round_off",
        mutate_unit_price_not_in_source,
        "extraction",
        "unit_price_not_verified_in_source",
        ("line_item_calculation_mismatch",),
        "Gap 44's check. A wrong unit price with a correct line amount is the "
        "quiet version of a transcription error: every total still balances.",
    ),
    (
        "line_amount_not_in_source",
        "us_flat_sales_tax",
        mutate_line_amount_not_in_source,
        "extraction",
        "line_item_not_verified_in_source",
        ("line_item_calculation_mismatch", "line_items_mismatch", "tax_mismatch"),
        "Gap 36's check: a line amount the document never printed.",
    ),
    (
        "required_field_dropped",
        "outbound_trade_discount",
        mutate_required_field_dropped,
        "extraction",
        "missing_required_field",
        ("tax_mismatch",),
        "The extraction-side twin of `required_field_not_printed`: the name IS "
        "on the document and the model returned nothing.",
    ),
    (
        "low_field_confidence",
        "us_flat_sales_tax",
        mutate_low_field_confidence,
        "extraction",
        "low_confidence_field",
        (),
        "Gap 3's confidence router. The only alert whose input is neither the "
        "OCR text nor the extracted record but Document Intelligence's own "
        "per-field confidence, so it is the only one that would go untested by "
        "a benchmark built purely on documents and extractions.",
    ),
)


def build_seeded_cases() -> list[SeededCase]:
    """Materialise the seeded set. Deterministic — no RNG anywhere in this module."""
    import copy

    cases: list[SeededCase] = []
    for suffix, doc_id, mutator, surface, expected, tolerated, rationale in _PLAN:
        spec = CLEAN_BY_ID[doc_id]
        ocr = spec.render_ocr_text()
        data = copy.deepcopy(spec.initial_extraction())
        ocr, data, field_path, correct, planted = mutator(spec, ocr, data)
        cases.append(
            SeededCase(
                case_id=f"{doc_id}__{suffix}",
                doc_id=doc_id,
                mutation=mutator.__name__,
                surface=surface,
                expected_alert_type=expected,
                tolerated_alert_types=tolerated,
                field_path=field_path,
                correct_value=correct,
                planted_value=planted,
                rationale=rationale,
                ocr_text=ocr,
                extracted_data=data,
                flow_direction=spec.flow_direction,
                clean_ground_truth=spec.ground_truth(),
            )
        )
    return cases


def ocr_result_for(case: SeededCase) -> Optional[dict[str, Any]]:
    """The Document Intelligence result stub a case needs, if any.

    Only `low_field_confidence` needs one; every other case passes None, which
    is what `verify_field_confidence` receives when Doc Intelligence returned no
    per-field confidence at all.
    """
    if case.mutation == "mutate_low_field_confidence":
        return {"field_confidence": {"InvoiceTotal": 0.31, "VendorName": 0.94}}
    return None


#: Every alert `type` this benchmark knows how to seed. Used by the metrics
#: layer to report which checks are covered and, more usefully, which are not.
SEEDED_ALERT_TYPES: tuple[str, ...] = tuple(
    dict.fromkeys(expected for _s, _d, _m, _su, expected, _t, _r in _PLAN)
)


__all__ = [
    "MUTATION_ABS_FLOOR",
    "MUTATION_REL",
    "SEEDED_ALERT_TYPES",
    "SeededCase",
    "build_seeded_cases",
    "ocr_result_for",
]
