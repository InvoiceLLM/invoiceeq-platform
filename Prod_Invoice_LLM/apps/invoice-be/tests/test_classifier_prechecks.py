"""T-C-5 — Feature 27 amendment A8, task R10: the classifier's pre-checks.

Four additions to E7's two-stage mechanism, all deterministic and all consulted
BEFORE a model ever is:

  1. a printed disclaimer that vetoes `INVOICE`,
  2. a title word whose meaning is decided by direction rather than by the word,
  3. the constrained answer that resolves (2),
  4. a `rule_era` derived from the document's date.

Separate file from `test_document_type_classifier.py` because these test the
guards AROUND the classifier rather than the classifier's own synonym matching,
and they fail for different reasons.
"""
from unittest.mock import patch

import pytest

import services.document_type_classifier as dtc
from services.document_type_classifier import classify_doc_type
from utils.llm import MockInvoiceLLM


def test_t_c_5_a_printed_disclaimer_vetoes_invoice_but_confirms_a_proforma():
    """Research §5 trap 1(c). A proforma, an order confirmation and a dunning
    letter routinely reuse an invoice template, and the document prints
    "ne vaut pas facture" / "kein Vorsteuerabzug" precisely BECAUSE the layout
    misleads.

    The veto is scoped to `INVOICE` ALONE, and that scoping is the substance of
    this test. A proforma carrying the same disclaimer is not contradicting
    itself -- a proforma IS by definition not a tax document, so the phrase
    CONFIRMS what the title band read. Vetoing the whole money family would have
    thrown away a correct answer and then paid for a model call to re-derive it.
    """
    with patch.object(dtc, "get_llm", return_value=MockInvoiceLLM()), patch.object(
        dtc, "tracked_llm_call"
    ):
        vetoed = classify_doc_type("TAX INVOICE\nne vaut pas facture\nTotal 100\n", {})

    assert vetoed["doc_type_method"] != "deterministic"
    assert vetoed["doc_type"] != "INVOICE"

    # The three that must NOT be vetoed still resolve deterministically, with no
    # model call at all.
    with patch.object(dtc, "get_llm") as get_llm, patch.object(dtc, "tracked_llm_call"):
        assert (
            classify_doc_type("PROFORMA INVOICE\nne vaut pas facture\n", {})["doc_type"]
            == "PROFORMA_INVOICE"
        )
        assert (
            classify_doc_type("CREDIT NOTE\nno input tax credit\n", {})["doc_type"]
            == "CREDIT_NOTE"
        )
        assert classify_doc_type("TAX INVOICE\nTotal 100\n", {})["doc_type"] == "INVOICE"
        get_llm.assert_not_called()


@pytest.mark.parametrize(
    "phrase",
    [
        "kein Vorsteuerabzug",
        "ne vaut pas facture",
        "non valido ai fini fiscali",
        "This is not a tax invoice",
        "no input tax credit",
    ],
)
def test_t_c_5_the_disclaimer_pass_recognises_each_regional_phrasing(phrase):
    hit, marker = dtc.has_not_a_tax_document_disclaimer(f"SOMETHING\n{phrase}\n")
    assert hit is True, phrase
    assert marker


def test_t_c_5_the_disclaimer_pass_does_not_fire_on_ordinary_text():
    """A false veto costs a model call and discards a correct deterministic
    answer, so the phrases are specific rather than keyword-ish."""
    assert dtc.has_not_a_tax_document_disclaimer("TAX INVOICE\nTotal 1000\n")[0] is False
    assert dtc.has_not_a_tax_document_disclaimer("")[0] is False
    assert dtc.has_not_a_tax_document_disclaimer(None)[0] is False


def test_t_c_5_gutschrift_never_resolves_deterministically():
    """A8 item 4, and the reason the check runs BEFORE the synonym pass rather
    than after: "Gutschrift" IS a synonym -- of CREDIT_NOTE in commercial use and
    of a self-billed INVOICE under UStG §14(2). Letting the deterministic pass
    see it first would hand a confident 1.0 answer to the one word that cannot be
    answered from the word (BMF 25.10.2013; research §5 trap 2).
    """
    assert dtc.title_band_is_mandatorily_ambiguous("Gutschrift Nr. 4471")[0] is True

    with patch.object(
        dtc, "get_llm", return_value=MockInvoiceLLM()
    ) as get_llm, patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type("Gutschrift Nr. 4471\nBetrag 1.000,00 EUR\n", {})

    assert result["doc_type_method"] != "deterministic"
    assert "direction_decided_title" in (result["doc_type_reason"] or "")
    get_llm.assert_called()


def test_t_c_5_an_ordinary_credit_note_is_not_dragged_into_the_ambiguous_path():
    """Only the named words are ambiguous. An English "Credit Note" is not, and
    sending it to the fallback would pay for a call to re-derive an answer the
    title already gave."""
    assert dtc.title_band_is_mandatorily_ambiguous("CREDIT NOTE\nAgainst INV-1\n")[0] is False


@pytest.mark.parametrize(
    "direction,references_original,expected",
    [
        # Issued by the customer or by us, referencing nothing -> a self-billed
        # invoice, which is an INVOICE carrying invoice_subtype=SELF_BILLED.
        ("SELF", False, "INVOICE"),
        ("BUYER_ISSUED", False, "INVOICE"),
        # Issued by the supplier AND referencing a prior invoice -> a commercial
        # credit note.
        ("SUPPLIER_ISSUED", True, "CREDIT_NOTE"),
        # Everything else stays unresolved. Guessing between the two would put a
        # payable and a credit on the same footing.
        ("SUPPLIER_ISSUED", False, None),
        ("SELF", True, None),
        (None, False, None),
        (None, True, None),
    ],
)
def test_t_c_5_the_gutschrift_rule_keys_on_direction_and_reference_never_the_word(
    direction, references_original, expected
):
    """Research §3.3 verbatim: classification must key on issuer direction, a
    reference to a prior invoice, and the sign of VAT -- never on the label."""
    assert dtc.resolve_ambiguous_direction_type(direction, references_original) == expected


@pytest.mark.parametrize(
    "doc_date,expected",
    [
        ("2024-01-01", None),                          # before every boundary
        ("2025-09-22", "IN_GST_SLABS_RATIONALISED"),   # on the boundary
        ("2025-12-31", "IN_GST_SLABS_RATIONALISED"),
        ("2026-04-01", "IN_TDS_RENUMBERED"),
        ("2026-09-30", "FR_EINVOICE_RECEIVE_ALL"),     # most recent boundary wins
        ("not-a-date", None),
        (None, None),
    ],
)
def test_t_c_5_rule_era_is_derived_from_the_document_date(doc_date, expected):
    """A8 item 5. NOT a classifier input -- a document's type does not depend on
    when it was issued. It is a VERIFICATION input: a credit note dated before
    2025-09-22 legitimately carries a GST rate that no longer exists, and a
    rubric checking it against today's slabs would flag a correct document.
    Research §3.1 is explicit that HSN->rate must never be hard-coded.
    """
    assert dtc.derive_rule_era(doc_date) == expected


def test_t_c_5_rule_era_none_means_no_era_established_not_current_rules():
    """An unparseable date and a date before every boundary both give None, and
    neither may be read as "today's rules apply" -- that reading is exactly what
    would flag a legitimately old document."""
    assert dtc.derive_rule_era("") is None
    assert dtc.derive_rule_era("01/09/2026") is None  # unparsed, never assumed


def test_t_c_5_the_pre_checks_consult_no_model():
    """All four decide whether a money-family answer stands, which feeds rubric
    selection and therefore how a figure is judged. Hard rule 3, asserted
    structurally rather than trusted."""
    import inspect

    for fn in (
        dtc.has_not_a_tax_document_disclaimer,
        dtc.title_band_is_mandatorily_ambiguous,
        dtc.resolve_ambiguous_direction_type,
        dtc.derive_rule_era,
    ):
        source = inspect.getsource(fn)
        for forbidden in ("get_llm", "invoke", "with_structured_output"):
            assert forbidden not in source, f"{fn.__name__} / {forbidden}"
