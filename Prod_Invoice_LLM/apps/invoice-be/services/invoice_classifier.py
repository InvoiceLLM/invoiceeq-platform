import logging
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

STANDARD = "STANDARD"
COMPLEX = "COMPLEX"

# ── BE Gap 682 ────────────────────────────────────────────────────────────────
# The pre-Gap-682 classifier returned COMPLEX on the *presence* of a Doc
# Intelligence field -- `{"Taxes", "Discounts", "CustomerTaxId", "VendorTaxId",
# "Items"}` -- or on any of twelve content keywords including `gst`, `vat` and
# `discount`. `Items` is present on every itemised invoice DI parses and a tax id
# is on every B2B invoice in India or the EU, so the signal fired on essentially
# the whole population. COMPLEX gates `dynamic_qa_node`, a second full LLM
# round-trip measured at 24-53 s across two reasoning calls
# (`agents/extraction_agent.py`), so every user paid for a pre-analysis pass on
# documents that needed none of it -- and a signal that always fires carries no
# information.
#
# The replacement scores the things `dynamic_qa_node` actually asks about, and
# scores them deterministically (CONVENTIONS hard rule 3 -- a check that decides
# behaviour is code, not a prompt keyword sweep):
#
#   1. a line-item table large enough that its structure is worth pre-reading,
#   2. a genuine multi-row tax split (DI's own `TaxDetails` breakdown), not the
#      mere fact that tax exists,
#   3. a layout Doc Intelligence itself had trouble with (low field confidence),
#   4. a deduction/retention structure, by keyword -- the one question in the
#      node that has no structured DI anchor to read instead.
#
# Bare `gst`/`vat`/`discount`/`hsn`/`sac`/`cgst`/`sgst`/`igst` are deliberately
# NOT triggers: they describe ordinary tax jurisdictions, not layout difficulty.
#
# Thresholds are settings, not literals, because the right values come from the
# live corpus and nobody has measured it yet -- see `_log_verdict` below, which
# records the legacy verdict alongside the new one on every call so the COMPLEX
# rate change is measurable from logs without a separate exercise.

#: Structural signals with no structured DI equivalent. Each names a mechanism
#: `dynamic_qa_node` asks about, not a tax regime.
_STRUCTURAL_KEYWORDS: Tuple[str, ...] = (
    "retention",
    "retainage",
    "holdback",
    "withholding",
    "tds",
    "reverse charge",
    "advance adjustment",
)

#: The pre-Gap-682 trigger set, kept only to compute the comparison verdict that
#: `_log_verdict` emits. Never returned.
_LEGACY_FIELDS = frozenset(
    {"Taxes", "Discounts", "CustomerTaxId", "VendorTaxId", "Items"}
)
_LEGACY_KEYWORDS: Tuple[str, ...] = (
    "gst", "vat", "discount", "deduction", "hsn", "sac",
    "cgst", "sgst", "igst", "tds", "withholding", "reverse charge",
)


def _thresholds() -> Tuple[int, int, float, bool]:
    """Read the tunables, tolerating a settings object that predates them."""
    try:
        from config import get_settings

        s = get_settings()
        return (
            int(getattr(s, "COMPLEX_MIN_LINE_ITEMS", 15)),
            int(getattr(s, "COMPLEX_MIN_TAX_ENTRIES", 2)),
            float(getattr(s, "COMPLEX_DI_CONFIDENCE_FLOOR", 0.70)),
            bool(getattr(s, "USE_LEGACY_COMPLEXITY_CLASSIFIER", False)),
        )
    except Exception:  # pragma: no cover - settings unavailable in some unit contexts
        return (15, 2, 0.70, False)


def _keyword_hit(text: str, keywords: Iterable[str]) -> Optional[str]:
    lowered = text.lower()
    for kw in keywords:
        if kw in lowered:
            return kw
    return None


def _di_array_len(source_document_json: Any, key: str) -> int:
    """Length of a Doc Intelligence array field, or 0 when absent/!list.

    `source_document_json` is `_serialize_di_document_fields`' output, so an
    array field arrives as `{"value": [ {...}, {...} ]}`.
    """
    if not isinstance(source_document_json, dict):
        return 0
    entry = source_document_json.get(key)
    if not isinstance(entry, dict):
        return 0
    value = entry.get("value")
    return len(value) if isinstance(value, list) else 0


def _lowest_confidence(field_confidence: Any) -> Optional[float]:
    if not isinstance(field_confidence, dict) or not field_confidence:
        return None
    scores = [float(v) for v in field_confidence.values() if isinstance(v, (int, float))]
    return min(scores) if scores else None


def _legacy_verdict(ocr_result: Dict[str, Any] | str) -> str:
    """What the pre-Gap-682 classifier would have returned, for comparison only."""
    if isinstance(ocr_result, str):
        return COMPLEX if _keyword_hit(ocr_result, _LEGACY_KEYWORDS) else STANDARD
    if any(k in (ocr_result.get("field_confidence") or {}) for k in _LEGACY_FIELDS):
        return COMPLEX
    if _keyword_hit(ocr_result.get("content") or "", _LEGACY_KEYWORDS):
        return COMPLEX
    return STANDARD


def _log_verdict(verdict: str, reason: str, ocr_result: Dict[str, Any] | str) -> str:
    """Emit both verdicts so the Gap 682 rate change is measurable from logs.

    The COMPLEX rate before this change was never measured. Logging the legacy
    verdict beside the new one on every call means the before/after can be read
    out of App Insights retroactively, rather than needing a separate corpus run.
    """
    try:
        legacy = _legacy_verdict(ocr_result)
    except Exception:  # never let the comparison break classification
        legacy = "UNKNOWN"
    logger.info(
        "Complexity verdict: %s (%s) [legacy would have said: %s]",
        verdict, reason, legacy,
        extra={"extra_fields": {
            "complexity": verdict,
            "complexity_reason": reason,
            "complexity_legacy": legacy,
            "complexity_changed": legacy != verdict,
        }},
    )
    return verdict


def classify_invoice_complexity(ocr_result: Dict[str, Any] | str) -> str:
    """Classify an invoice's extraction difficulty as 'STANDARD' or 'COMPLEX'.

    COMPLEX routes the document through `dynamic_qa_node`, which costs a full
    extra LLM reasoning call, so the bar is "this document's structure is hard
    enough that pre-reading it pays for itself" -- not "this document has tax".

    See the BE Gap 682 note at the top of this module for why the previous
    field-presence and tax-keyword triggers were removed.
    """
    min_lines, min_tax_entries, conf_floor, use_legacy = _thresholds()

    if use_legacy:
        # Rollback switch for BE Gap 682. Flipping this restores the previous
        # behaviour without a deploy if the narrowed classifier misbehaves.
        verdict = _legacy_verdict(ocr_result)
        logger.warning("USE_LEGACY_COMPLEXITY_CLASSIFIER is on; returning %s", verdict)
        return verdict

    # Local/Ollama mode: `_run_ocr` returns a bare string, so there is no
    # structured DI output to read. Only the keyword signal is available -- and
    # it is the narrowed set, so a local run routes closer to production than the
    # old classifier did (it used the full legacy keyword list here).
    if isinstance(ocr_result, str):
        kw = _keyword_hit(ocr_result, _STRUCTURAL_KEYWORDS)
        if kw:
            return _log_verdict(COMPLEX, "structural keyword %r (text input)" % kw, ocr_result)
        return _log_verdict(STANDARD, "no structural signal (text input)", ocr_result)

    source_json = ocr_result.get("source_document_json")

    # 1. A large line-item table. The count comes from Doc Intelligence's own
    #    `Items` array, so this measures the table, not the presence of one.
    line_items = _di_array_len(source_json, "Items")
    if line_items >= min_lines:
        return _log_verdict(
            COMPLEX, "line-item count %d >= %d" % (line_items, min_lines), ocr_result
        )

    # 2. A genuine multi-row tax split -- CGST/SGST, VAT at two rates, a reverse
    #    charge line beside a standard one. One tax row is an ordinary invoice.
    tax_entries = _di_array_len(source_json, "TaxDetails")
    if tax_entries >= min_tax_entries:
        return _log_verdict(
            COMPLEX,
            "tax breakdown rows %d >= %d" % (tax_entries, min_tax_entries),
            ocr_result,
        )

    # 3. A layout Doc Intelligence itself struggled with. Its own confidence is a
    #    better difficulty proxy than any keyword: it is computed from the
    #    document's structure rather than its vocabulary.
    lowest = _lowest_confidence(ocr_result.get("field_confidence"))
    if lowest is not None and lowest < conf_floor:
        return _log_verdict(
            COMPLEX,
            "lowest DI field confidence %.2f < %.2f" % (lowest, conf_floor),
            ocr_result,
        )

    # 4. Deduction/retention structures. This is the one `dynamic_qa_node`
    #    question with no structured DI anchor, so it stays a keyword check.
    kw = _keyword_hit(ocr_result.get("content") or "", _STRUCTURAL_KEYWORDS)
    if kw:
        return _log_verdict(COMPLEX, "structural keyword %r" % kw, ocr_result)

    return _log_verdict(STANDARD, "no structural signal", ocr_result)
