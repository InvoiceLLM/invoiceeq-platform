"""BE Gap 682: the complexity classifier's trigger set.

`classify_invoice_complexity` decides whether a document takes `dynamic_qa_node`,
a second full LLM reasoning call measured at 24-53 s across two calls. Before this
gap it returned COMPLEX on the *presence* of a Doc Intelligence field -- and
`Items` is present on every itemised invoice DI parses -- or on any of twelve
content keywords including bare `gst`, `vat` and `discount`. So it fired on
essentially the whole population, which both doubled the cost of an ordinary
invoice and destroyed the signal's information content.

The module had **no test file at all** before this one, which is how a heuristic
that always returns the same answer survived.

These are pure-function tests: no database, no network, no LLM. The first test is
the regression this gap is about -- an ordinary Indian GST invoice with line
items and a tax id, which the old classifier called COMPLEX and this one must
not.
"""

import pytest

from services.invoice_classifier import (
    COMPLEX,
    STANDARD,
    _legacy_verdict,
    classify_invoice_complexity,
)


def _di_array(n: int) -> dict:
    """A serialised Doc Intelligence array field with `n` entries."""
    return {"value": [{"value": "row %d" % i} for i in range(n)]}


def _ocr(
    *,
    line_items: int = 3,
    tax_rows: int = 1,
    content: str = "Tax Invoice\nSubtotal 1000\nGST 18% 180\nTotal 1180",
    confidence: dict | None = None,
) -> dict:
    """An `ocr_result` shaped like `_run_ocr`'s Azure return value."""
    return {
        "content": content,
        "coordinates": [],
        "field_confidence": {"VendorName": 0.97, "InvoiceTotal": 0.95}
        if confidence is None
        else confidence,
        "tax_details_sum": None,
        "source_document_json": {
            "Items": _di_array(line_items),
            "TaxDetails": _di_array(tax_rows),
            "VendorName": {"value": "Acme Supplies Pvt Ltd"},
            "CustomerTaxId": {"value": "29ABCDE1234F1Z5"},
        },
    }


# ───────────────────────────── the regression this gap is about ──────────────

def test_ordinary_gst_invoice_is_standard():
    """The case BE Gap 682 exists for.

    Three line items, one tax row, a customer tax id, and the word "GST" in the
    body -- an entirely ordinary Indian B2B invoice. The old classifier returned
    COMPLEX on three independent triggers here (`Items` present, `CustomerTaxId`
    present, `gst` in content). It must now be STANDARD.
    """
    ocr = _ocr()
    assert classify_invoice_complexity(ocr) == STANDARD
    # Pin that this genuinely is a behaviour change and not a fixture that never
    # tripped the old triggers -- otherwise this test proves nothing.
    assert _legacy_verdict(ocr) == COMPLEX


@pytest.mark.parametrize("word", ["gst", "vat", "discount", "hsn", "sac", "cgst", "igst"])
def test_bare_tax_vocabulary_alone_is_not_complex(word):
    """These describe a tax jurisdiction, not a difficult layout."""
    ocr = _ocr(content="Invoice\n%s applied\nTotal 500" % word)
    assert classify_invoice_complexity(ocr) == STANDARD


# ───────────────────────────── signal 1: table size ──────────────────────────

def test_large_line_item_table_is_complex():
    assert classify_invoice_complexity(_ocr(line_items=15)) == COMPLEX


def test_line_item_table_just_below_threshold_is_standard():
    """Boundary: the threshold is `>=`, so 14 rows against a floor of 15 passes."""
    assert classify_invoice_complexity(_ocr(line_items=14)) == STANDARD


# ───────────────────────────── signal 2: multi-row tax split ─────────────────

def test_multi_row_tax_split_is_complex():
    """Two TaxDetails rows is a real CGST/SGST-style split, which the QA node asks about."""
    assert classify_invoice_complexity(_ocr(tax_rows=2)) == COMPLEX


def test_single_tax_row_is_standard():
    assert classify_invoice_complexity(_ocr(tax_rows=1)) == STANDARD


# ───────────────────────────── signal 3: DI confidence ───────────────────────

def test_low_di_confidence_is_complex():
    """Doc Intelligence's own confidence is a structural difficulty signal."""
    ocr = _ocr(confidence={"VendorName": 0.31, "InvoiceTotal": 0.88})
    assert classify_invoice_complexity(ocr) == COMPLEX


def test_high_di_confidence_is_standard():
    ocr = _ocr(confidence={"VendorName": 0.99, "InvoiceTotal": 0.97})
    assert classify_invoice_complexity(ocr) == STANDARD


# ───────────────────────────── signal 4: structural keywords ─────────────────

@pytest.mark.parametrize(
    "phrase",
    ["Retention 5% held back", "holdback applied", "TDS deducted",
     "Reverse charge applies", "advance adjustment"],
)
def test_deduction_structures_are_complex(phrase):
    """The one QA-node question with no structured DI anchor to read instead."""
    ocr = _ocr(content="Invoice\n%s\nTotal 1000" % phrase)
    assert classify_invoice_complexity(ocr) == COMPLEX


# ───────────────────────────── text input (Ollama / local mode) ──────────────

def test_string_input_uses_narrowed_keywords():
    """`_run_ocr` returns a bare string in Ollama mode -- no structured DI output.

    The old classifier applied its *full* legacy keyword list on this path, so a
    local run routed differently from production on the same document. Both paths
    now use the narrowed set.
    """
    assert classify_invoice_complexity("Invoice with GST 18% and a discount") == STANDARD
    assert classify_invoice_complexity("Invoice with 5% retention held back") == COMPLEX


# ───────────────────────────── robustness ────────────────────────────────────

@pytest.mark.parametrize(
    "source_json",
    [None, {}, {"Items": None}, {"Items": {"value": "not-a-list"}}, {"Items": "scalar"}],
)
def test_malformed_source_document_json_does_not_raise(source_json):
    """`source_document_json` is `None` on every non-Azure path and any DI field
    can come back a different shape by SDK version, so the readers must tolerate
    it rather than assume an array."""
    ocr = _ocr()
    ocr["source_document_json"] = source_json
    assert classify_invoice_complexity(ocr) in (STANDARD, COMPLEX)


def test_empty_field_confidence_does_not_trigger_the_floor():
    """No confidence data must not read as zero confidence."""
    ocr = _ocr(confidence={})
    assert classify_invoice_complexity(ocr) == STANDARD


def test_non_numeric_confidence_values_are_ignored():
    ocr = _ocr(confidence={"VendorName": None, "InvoiceTotal": "0.9"})
    assert classify_invoice_complexity(ocr) == STANDARD


# ───────────────────────────── rollback switch ───────────────────────────────

def test_legacy_switch_restores_previous_behaviour(monkeypatch):
    """The BE Gap 682 rollback path: restore the old triggers without a deploy."""
    import services.invoice_classifier as mod

    monkeypatch.setattr(mod, "_thresholds", lambda: (15, 2, 0.70, True))
    # The ordinary invoice the new classifier calls STANDARD goes back to COMPLEX.
    assert classify_invoice_complexity(_ocr()) == COMPLEX
