"""BE Gap 687: shape and consistency tests for the non-invoice benchmark specs.

`tests/test_extraction_benchmark.py` does this for `CLEAN_DOCUMENTS` -- asserts
every ground-truth figure is printed, and that the arithmetic reconciles -- but
its assertions are invoice-specific (`spec.subtotal`, `line.quantity *
line.unit_price`), so a delivery note that prints no prices would fail them by
design. Hence a sibling file rather than a widened parametrisation.

The point of these: a ground-truth figure the document never prints would make
the source-text faithfulness checks fire on a *clean* case, which would make the
false-positive rate a property of the fixture rather than of the product.
"""

import pytest

from benchmarks.extraction.documents import CLEAN_DOCUMENTS
from benchmarks.extraction.generic_documents import (
    ALL_CLEAN_DOCUMENTS,
    CLEAN_GENERIC_BY_ID,
    CLEAN_GENERIC_DOCUMENTS,
)
from benchmarks.extraction.harness import MODE_VERIFY, ExtractionSpec, run_clean_case
from services.document_type_classifier import DOC_TYPES

_IDS = lambda s: s.doc_id  # noqa: E731


# ───────────────────────────── the corpus itself ─────────────────────────────

def test_generic_corpus_is_not_empty():
    assert len(CLEAN_GENERIC_DOCUMENTS) >= 5


def test_doc_ids_are_unique_and_do_not_collide_with_the_invoice_corpus():
    """`CLEAN_BY_ID` and `CLEAN_GENERIC_BY_ID` are separate dicts, and case ids
    are built as `f"{doc_id}__clean"`, so a collision would silently overwrite
    one document's results with another's."""
    generic_ids = [s.doc_id for s in CLEAN_GENERIC_DOCUMENTS]
    invoice_ids = [s.doc_id for s in CLEAN_DOCUMENTS]
    assert len(set(generic_ids)) == len(generic_ids)
    assert set(generic_ids).isdisjoint(set(invoice_ids))
    assert set(CLEAN_GENERIC_BY_ID) == set(generic_ids)


def test_all_clean_documents_is_the_union():
    assert len(ALL_CLEAN_DOCUMENTS) == len(CLEAN_DOCUMENTS) + len(CLEAN_GENERIC_DOCUMENTS)


@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_every_spec_satisfies_the_harness_protocol(spec):
    """If this fails the harness cannot run the spec at all."""
    assert isinstance(spec, ExtractionSpec)
    # NOT "GENERIC": that value raises `UnknownFlowDirectionError` by design.
    # The generic schema is selected downstream from `doc_type`.
    assert spec.flow_direction == "INBOUND"
    assert spec.doc_type in DOC_TYPES
    assert spec.doc_type != "INVOICE", "an invoice belongs in CLEAN_DOCUMENTS"


@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_rationale_is_present(spec):
    """Copied into the review manifest so a reviewer sees the intent, not just
    the numbers. An unexplained fixture is one nobody can maintain."""
    assert len(spec.rationale) > 80


# ───────────────────────────── printed-figure faithfulness ───────────────────

@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_every_ground_truth_figure_is_printed_in_the_document(spec):
    text = spec.render_ocr_text()
    figures = [
        spec.subtotal, spec.grand_total,
        spec.freight_amount, spec.discount_amount,
    ]
    figures += [line.unit_price for line in spec.lines]
    figures += [line.amount for line in spec.lines]
    if len(spec.taxes) > 1:
        # A split-tax document never prints the summed figure -- a CGST/SGST
        # invoice prints 5,490 twice and never 10,980 -- so its components are
        # what must appear (the Gap 69 component fallback). Asserting the sum
        # were printed would force the fixture to print a figure real documents
        # of this shape do not.
        figures += [t.amount for t in spec.taxes]
    else:
        figures.append(spec.tax_amount)
    for value in figures:
        if value is None:
            continue
        assert f"{value:,.2f}" in text, (
            f"{value:,.2f} is in the ground truth but not printed in the document"
        )


@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_identifiers_and_dates_are_printed(spec):
    text = spec.render_ocr_text()
    assert spec.doc_number in text
    assert spec.doc_date in text
    assert spec.party_name in text
    assert spec.counterparty_name in text
    if spec.po_number:
        assert spec.po_number in text
    if spec.valid_until:
        assert spec.valid_until in text
    for ref in spec.reference_numbers:
        assert ref in text


# ───────────────────────────── arithmetic, where there is any ────────────────

@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_priced_specs_are_arithmetically_consistent(spec):
    priced = [l for l in spec.lines if l.unit_price is not None and l.amount is not None]
    if not priced:
        pytest.skip("unpriced document type")
    for line in priced:
        assert line.quantity * line.unit_price == pytest.approx(line.amount, abs=0.01)
    assert sum(l.amount for l in priced) == pytest.approx(spec.subtotal, abs=0.01)
    expected = spec.subtotal + (spec.tax_amount or 0.0) - (spec.discount_amount or 0.0)
    expected += spec.freight_amount or 0.0
    assert expected == pytest.approx(spec.grand_total, abs=0.01)
    if spec.taxes:
        assert sum(t.amount for t in spec.taxes) == pytest.approx(spec.tax_amount, abs=0.01)


@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_unpriced_specs_state_no_monetary_value_anywhere(spec):
    """The hallucination that matters most on a non-invoice document.

    `prebuilt-invoice` force-fits an invoice shape onto a delivery note and
    invents a `VendorName`/`InvoiceTotal`. A spec that claims to be unpriced but
    leaks a currency or a total into its ground truth would mark that
    hallucination correct.
    """
    if any(l.unit_price is not None for l in spec.lines):
        pytest.skip("priced document type")
    assert spec.currency is None
    assert spec.subtotal is None
    assert spec.tax_amount is None
    assert spec.grand_total is None
    assert spec.taxes == ()
    truth = spec.ground_truth()
    assert truth["currency"] is None and truth["grand_total"] is None
    for item in truth["items"]:
        assert item["unit_price"] is None
        assert item["amount"] is None


# ───────────────────────────── the structural shapes ─────────────────────────

def test_credit_note_figures_are_all_negative():
    """The extraction prompt requires signs transcribed as printed and forbids
    flipping them 'to make the document read like an invoice'. A positive
    grand_total here reverses the direction of money on the ledger and reads as
    perfectly correct, so it is pinned rather than left to the prompt."""
    spec = CLEAN_GENERIC_BY_ID["eu_credit_note_negative"]
    assert spec.grand_total < 0
    assert spec.subtotal < 0
    assert spec.tax_amount < 0
    assert all(t.amount < 0 for t in spec.taxes)
    for line in spec.lines:
        assert line.unit_price < 0 and line.amount < 0
    # And the minus signs survive rendering -- not just the dataclass.
    text = spec.render_ocr_text()
    assert "-612.85" in text
    assert spec.reference_numbers, "a credit note must cite what it adjusts"


def test_grn_prints_three_distinct_quantity_columns():
    """Collapsing ordered/delivered/received into one `quantity` loses the
    discrepancy that is the entire purpose of a goods receipt note."""
    spec = CLEAN_GENERIC_BY_ID["in_grn_three_quantity_columns"]
    for line in spec.lines:
        assert line.quantity_ordered is not None
        assert line.quantity_delivered is not None
        assert line.quantity_received is not None
    # At least one row must actually disagree, or the columns prove nothing.
    assert any(l.quantity_ordered != l.quantity_delivered for l in spec.lines)
    assert any(l.quantity_delivered != l.quantity_received for l in spec.lines)
    extraction = spec.initial_extraction()
    assert all("quantity_received" in item for item in extraction["items"])


def test_quotation_validity_is_printed_and_not_derivable_from_the_date():
    """The schema forbids deriving `valid_until` from `doc_date`. A fixture whose
    validity happened to be doc_date + 30 days would mark that derivation
    correct."""
    spec = CLEAN_GENERIC_BY_ID["in_quotation_with_validity"]
    assert spec.valid_until and spec.valid_until != spec.doc_date
    assert spec.valid_until in spec.render_ocr_text()


def test_purchase_order_po_number_equals_its_own_document_number():
    """The schema says so explicitly, and a null `po_number` here is a common
    miss -- the model looks for a *referenced* order instead of this one."""
    spec = CLEAN_GENERIC_BY_ID["us_purchase_order_priced"]
    assert spec.po_number == spec.doc_number
    assert spec.ground_truth()["po_number"] == spec.doc_number


# ───────────────────────────── ground truth / extraction shapes ──────────────

@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_initial_extraction_is_a_superset_of_ground_truth(spec):
    """Verify-only mode feeds `initial_extraction()` to the real `verify_node`,
    so it must carry everything graded plus the fields the checks read."""
    truth, extraction = spec.ground_truth(), spec.initial_extraction()
    assert set(truth).issubset(set(extraction))
    for key, value in truth.items():
        if key == "items":
            continue
        assert extraction[key] == value
    assert len(extraction["items"]) == len(truth["items"]) == len(spec.lines)


# ───────────────────────────── through the real verify_node ──────────────────

@pytest.mark.parametrize("spec", CLEAN_GENERIC_DOCUMENTS, ids=_IDS)
def test_clean_generic_documents_run_through_the_real_verify_node(spec):
    """The false-positive measurement, as a floor. A clean document that raises
    any alert at all is a false positive -- and these run through the actual
    production `verify_node`, not a reimplementation of it."""
    run = run_clean_case(spec, MODE_VERIFY)
    assert run.error is None, run.error
    assert run.flow_direction == "INBOUND"
