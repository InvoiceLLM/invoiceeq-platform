"""Feature 27 (G2) — `services/document_type_classifier.py`.

Covers §9's classifier block:
  * **T-C-1** — every synonym in E4's table classifies to its canonical value via
    the **deterministic** pass, proven by patching `get_llm` and asserting it was
    never called (the assertion shape Gap 366/367 used). A right answer reached
    by paying for a model call is a different behaviour from the one E7
    specifies, and only the mock can tell them apart.
  * **T-C-2** — an ambiguous title falls back to the LLM path, and an invented
    `doc_type` is a pydantic validation error rather than a stored string.
  * **T-C-3** — confidence below threshold → `OTHER`, with the reason recorded.
  * **T-C-4** — a bill of lading and an e-way bill both classify `OTHER` (E5's
    scope exclusion). Minimal representative text, not fixture files: §7 task F
    has not produced real samples yet, and this asserts the *routing*, not
    extraction quality on a real scan.

Pure Python, no DB, no network — §9 explicitly allows the classifier tests to run
anywhere. Hard rule 2 still binds anything that claims the *pipeline* works: that
is the Postgres run in task V, not this file.
"""
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

import services.document_type_classifier as dtc
from services.document_type_classifier import (
    DOC_TYPE_CONFIDENCE_THRESHOLD,
    DOC_TYPE_FAMILY,
    DOC_TYPES,
    MONEY_FAMILY,
    QUANTITY_FAMILY,
    DocTypeClassification,
    classify_doc_type,
    classify_doc_type_deterministic,
)
from utils.llm import MockInvoiceLLM

_SYNONYMS = dtc._DOC_TYPE_SYNONYMS


def _document(title: str) -> str:
    """A title band with realistic noise above and below it.

    The letterhead lines matter: if the classifier matched anywhere in the text
    rather than on a title line, several of these tests would pass for the wrong
    reason.
    """
    return (
        "Sample Supplier Pvt Ltd\n"
        "17 Industrial Estate, Pune 411019\n"
        "GSTIN 27AABCS1429B1ZQ\n"
        f"{title}\n"
        "Ref No: 4471          Dated: 01/09/2026\n"
        "Consignee: Northbridge Manufacturing Ltd\n"
    )


# --- The taxonomy itself (E4) ------------------------------------------------


def test_doc_types_is_the_closed_fourteen_value_tuple_in_lifecycle_order():
    """The order is load-bearing (E4): quote -> proforma -> order -> confirmation
    -> contract -> delivery -> goods receipt -> invoice -> payment receipt ->
    adjustments -> settlement -> reconciliation. It is the order a future matching
    feature walks, so an alphabetical "tidy-up" would be a regression.

    Widened 10 -> 14 by A5/R7. The four additions each earn a value rather than an
    attribute because each needs a DIFFERENT rubric or a different comparison
    mode: ORDER_CONFIRMATION is commitment (and is separated from PURCHASE_ORDER
    by direction, not layout), RECEIPT is money with legally-absent fields,
    and REMITTANCE_ADVICE / STATEMENT_OF_ACCOUNT are advisory list documents that
    must never be booked as payables (research §5 trap 10).
    """
    assert DOC_TYPES == (
        "QUOTATION",
        "PROFORMA_INVOICE",
        "PURCHASE_ORDER",
        "ORDER_CONFIRMATION",
        "CONTRACT",
        "DELIVERY_NOTE",
        "GRN",
        "INVOICE",
        "RECEIPT",
        "CREDIT_NOTE",
        "DEBIT_NOTE",
        "REMITTANCE_ADVICE",
        "STATEMENT_OF_ACCOUNT",
        "OTHER",
    )


def test_every_doc_type_has_exactly_one_family_and_no_family_has_a_stray_key():
    """`DOC_TYPE_FAMILY` is what G5's rubric map is derived from; a missing key
    there is a `KeyError` mid-extraction, and a stray one is a rubric nothing can
    reach."""
    assert set(DOC_TYPE_FAMILY) == set(DOC_TYPES)
    # A5/R7 widened the enum and A7/R9 adds ADVISORY; the closed set is asserted
    # from the module's own exported constants rather than restated as literals,
    # so adding a family is one edit there and not a second one here.
    assert set(DOC_TYPE_FAMILY.values()) <= {
        MONEY_FAMILY,
        QUANTITY_FAMILY,
        dtc.COMMITMENT_FAMILY,
        dtc.OTHER_FAMILY,
    } | {getattr(dtc, "ADVISORY_FAMILY", "ADVISORY")}
    assert DOC_TYPE_FAMILY["INVOICE"] == "MONEY"
    assert DOC_TYPE_FAMILY["PROFORMA_INVOICE"] == "MONEY"
    assert DOC_TYPE_FAMILY["CREDIT_NOTE"] == "MONEY"
    assert DOC_TYPE_FAMILY["DEBIT_NOTE"] == "MONEY"
    assert DOC_TYPE_FAMILY["DELIVERY_NOTE"] == "QUANTITY"
    assert DOC_TYPE_FAMILY["GRN"] == "QUANTITY"
    assert DOC_TYPE_FAMILY["PURCHASE_ORDER"] == "COMMITMENT"
    assert DOC_TYPE_FAMILY["CONTRACT"] == "COMMITMENT"
    assert DOC_TYPE_FAMILY["OTHER"] == "OTHER"


def test_no_synonym_is_claimed_by_two_document_types():
    """A phrase in two lists is an unresolvable ambiguity that would present as a
    classification flip depending on dict order."""
    seen = {}
    for doc_type, phrases in _SYNONYMS.items():
        assert doc_type in DOC_TYPES
        for phrase in phrases:
            assert phrase not in seen, f"{phrase!r} claimed by {seen.get(phrase)} and {doc_type}"
            seen[phrase] = doc_type
    # A5/R7 CHANGED THIS INVARIANT, deliberately. It previously read
    # `assert _SYNONYMS["OTHER"] == ()`, on the reasoning that OTHER is where the
    # classifier lands when it DECLINES to decide and is not something a document
    # prints.
    #
    # That is still true of a genuine miss, but it was never true of E5's deferred
    # documents. A bill of lading, an e-way bill, a bill of entry and a dunning
    # letter are not undecided: we know exactly what they are and have decided
    # they are out of v1. Recognising them by title costs nothing and buys two
    # things -- the v1 exclusion becomes free (no LLM call) and unambiguous (a
    # model that mistakes an e-way bill quoting a tax-invoice number for an
    # invoice can no longer do so).
    #
    # The distinction OTHER now carries is not lost, it MOVED: `doc_type_method`
    # is `deterministic` for a recognised-and-deferred document and `fallback` for
    # a genuine miss, which is what that field exists to record.
    assert _SYNONYMS["OTHER"], "E5's deferred documents must be recognised, not guessed at"
    for phrase in ("bill of lading", "e way bill", "bill of entry", "mahnung"):
        assert phrase in _SYNONYMS["OTHER"]


# --- T-C-1: the deterministic pass, and no model call ------------------------


@pytest.mark.parametrize(
    "doc_type,synonym",
    [(t, s) for t, phrases in _SYNONYMS.items() for s in phrases],
    ids=[f"{t}-{s.replace(' ', '_')}" for t, phrases in _SYNONYMS.items() for s in phrases],
)
def test_every_synonym_classifies_deterministically_without_an_llm_call(doc_type, synonym):
    """T-C-1. Every entry in `_DOC_TYPE_SYNONYMS`, printed as the title, in the
    upper-case form documents actually use."""
    title = synonym.upper()

    with patch.object(dtc, "get_llm") as get_llm:
        result = classify_doc_type(_document(title), {})

    get_llm.assert_not_called()
    assert result["doc_type"] == doc_type
    assert result["doc_type_method"] == "deterministic"
    assert result["doc_type_confidence"] == 1.0
    assert result["doc_type_evidence"] == title
    assert result["doc_type_reason"] is None


@pytest.mark.parametrize(
    "printed_title",
    [
        # India
        "Delivery Challan",
        "CHALLAN",
        "Goods Delivery Note",
        # US
        "Packing Slip",
        "PACKING LIST",
        "Delivery Note",
        "Shipping List",
        # Germany / DACH
        "Lieferschein",
        # Italy — both the acronym as printed with stops, and the full form
        "D.D.T.",
        "Documento di Trasporto",
        # France
        "Bon de livraison",
        # Netherlands
        "Pakbon",
        # Spain — accented as printed, and the unaccented spelling
        "Albarán",
        "ALBARAN",
    ],
)
def test_e4_regional_delivery_note_table_normalises_to_one_canonical_value(printed_title):
    """T-C-1, the synonym-recognition proof E4 calls out by name: a Lieferschein
    and a delivery challan are the same document type and must land on the same
    value. Accents and acronym stops are folded before matching, so "Albarán" and
    "D.D.T." are handled as printed rather than requiring a tidied OCR string."""
    with patch.object(dtc, "get_llm") as get_llm:
        result = classify_doc_type(_document(printed_title), {})

    get_llm.assert_not_called()
    assert result["doc_type"] == "DELIVERY_NOTE"
    assert result["doc_type_method"] == "deterministic"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("TAX INVOICE", "INVOICE"),
        ("E-Invoice", "INVOICE"),
        ("Bill of Supply", "INVOICE"),
        ("VAT INVOICE", "INVOICE"),
        ("PROFORMA INVOICE", "PROFORMA_INVOICE"),
        ("Pro-Forma Invoice", "PROFORMA_INVOICE"),
    ],
)
def test_invoice_sub_cases_and_proforma_resolve_by_specificity_not_by_scan_order(title, expected):
    """"PROFORMA INVOICE" contains "invoice"; "TAX INVOICE" contains "invoice".
    The contained match is the specific one's tail, not independent evidence of a
    second type — without that rule every invoice sub-case would read as
    ambiguous and pay for a model call it does not need."""
    with patch.object(dtc, "get_llm") as get_llm:
        result = classify_doc_type(_document(title), {})

    get_llm.assert_not_called()
    assert result["doc_type"] == expected


def test_a_purchase_order_number_quoted_on_an_invoice_is_not_a_purchase_order():
    """The title-band coverage guard. An invoice that references its PO must
    classify INVOICE — "decide from what the document IS, not what it mentions".
    This is the same guard that keeps an e-way bill quoting an invoice number out
    of the money family."""
    text = (
        "Northbridge Manufacturing Ltd\n"
        "TAX INVOICE\n"
        "Invoice No: INV-2026-0447    Dated: 01/09/2026\n"
        "Purchase Order No: PO-2024-1188\n"
        "Delivery Note reference: DN-88213\n"
    )

    with patch.object(dtc, "get_llm") as get_llm:
        result = classify_doc_type(text, {})

    get_llm.assert_not_called()
    assert result["doc_type"] == "INVOICE"
    assert result["doc_type_evidence"] == "TAX INVOICE"


# --- T-C-2: ambiguity, the LLM fallback, and the closed vocabulary -----------


def test_a_title_naming_two_types_is_ambiguous_and_does_not_guess():
    """"TAX INVOICE CUM DELIVERY NOTE" is a real Indian document. The
    deterministic pass must decline it rather than pick whichever synonym is
    longer, and must say why — a `None` type with a non-empty evidence string is
    how the caller tells ambiguity from nothing-found."""
    doc_type, evidence = classify_doc_type_deterministic(
        _document("TAX INVOICE CUM DELIVERY NOTE")
    )

    assert doc_type is None
    assert "ambiguous" in evidence
    assert "INVOICE" in evidence and "DELIVERY_NOTE" in evidence


def test_an_invented_doc_type_cannot_be_constructed_at_all():
    """T-C-2, the direct proof. `Literal` over `DOC_TYPES` means a value outside
    the enum is a validation error, not a silently-stored string — including the
    transport types E5 deliberately excluded."""
    with pytest.raises(ValidationError):
        DocTypeClassification(doc_type="BILL_OF_LADING", confidence=0.98, evidence="Bill of Lading")

    with pytest.raises(ValidationError):
        DocTypeClassification(doc_type="E_WAY_BILL", confidence=0.9, evidence="e-Way Bill")


def test_ambiguous_document_falls_back_to_the_llm_and_an_invented_value_is_not_stored():
    """T-C-2 end to end: the ambiguous title reaches the model, the model returns
    a type outside the enum, and what gets recorded is `OTHER` plus the reason —
    never the invented value."""
    def _invent(prompt, **kwargs):
        # What the real `with_structured_output` does on an out-of-vocabulary
        # answer: raise while building the model, not return a loose string.
        return DocTypeClassification(
            doc_type="BILL_OF_LADING", confidence=0.97, evidence="Bill of Lading"
        )

    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = _invent

    with patch.object(dtc, "get_llm", return_value=llm) as get_llm, patch.object(
        dtc, "tracked_llm_call"
    ):
        result = classify_doc_type(_document("TAX INVOICE CUM DELIVERY NOTE"), {})

    get_llm.assert_called_once()
    assert result["doc_type"] == "OTHER"
    assert result["doc_type_method"] == "fallback"
    assert "validation_error" in result["doc_type_reason"]
    assert "ambiguous_title_band" in result["doc_type_reason"]
    assert "BILL_OF_LADING" not in str(result["doc_type"])


def test_a_confident_in_vocabulary_answer_from_the_fallback_is_kept():
    """The other half of the fallback contract: when the model answers inside the
    enum and above the threshold, that answer is what is recorded, tagged `llm`
    so telemetry can tell the two stages apart."""
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = DocTypeClassification(
        doc_type="DELIVERY_NOTE", confidence=0.91, evidence="Warenbegleitschein"
    )

    with patch.object(dtc, "get_llm", return_value=llm), patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(_document("Warenbegleitschein"), {})

    assert result["doc_type"] == "DELIVERY_NOTE"
    assert result["doc_type_method"] == "llm"
    assert result["doc_type_confidence"] == 0.91
    assert result["doc_type_evidence"] == "Warenbegleitschein"
    assert result["doc_type_reason"] is None


def test_the_fallback_call_is_telemetered_once_under_its_own_agent_name():
    """E7: `tracked_llm_call` wraps the fallback path only, so the event count is
    a direct measure of how often the title band was not enough. A deterministic
    hit must cost nothing and show as nothing.

    The unrecognised title was "Rahmenvertrag" until 2026-09-03, chosen because
    it was NOT in the synonym table. BE Gap 396 then added it (a real German
    framework agreement is exactly what CONTRACT is for), so it now resolves
    deterministically and never reaches the fallback this test is about. Swapped
    for a genuinely unrecognised German accounting term -- and the swap is the
    point: this test needs a title the table does not know, not a specific word.
    """
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = DocTypeClassification(
        doc_type="CONTRACT", confidence=0.88, evidence="Betriebsabrechnungsbogen"
    )

    with patch.object(dtc, "get_llm", return_value=llm), patch.object(
        dtc, "tracked_llm_call"
    ) as tracked:
        classify_doc_type(_document("Betriebsabrechnungsbogen"), {}, tenant_id="tenant-1")
    assert tracked.call_args.args[0] == "extraction.classify_doc_type"
    assert tracked.call_args.kwargs["tenant_id"] == "tenant-1"

    with patch.object(dtc, "get_llm"), patch.object(dtc, "tracked_llm_call") as tracked:
        classify_doc_type(_document("DELIVERY CHALLAN"), {}, tenant_id="tenant-1")
    tracked.assert_not_called()


# --- T-C-3: low confidence -> OTHER, with the reason recorded ----------------


def test_low_confidence_is_never_promoted_to_a_type():
    """T-C-3. Below `DOC_TYPE_CONFIDENCE_THRESHOLD` the model's proposal is
    discarded and the reason records both the score and what it proposed, so a
    miss is reviewable rather than merely wrong.

    N2: `0.6` is a placeholder chosen before any real fixture existed. This test
    asserts the *behaviour at the threshold*, reading the constant rather than
    hardcoding it, so recalibrating against task F's fixtures does not require
    rewriting the test.
    """
    below = DOC_TYPE_CONFIDENCE_THRESHOLD - 0.2
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = DocTypeClassification(
        doc_type="DELIVERY_NOTE", confidence=below, evidence="Warenausgang"
    )

    with patch.object(dtc, "get_llm", return_value=llm), patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(_document("Warenausgang"), {})

    assert result["doc_type"] == "OTHER"
    assert result["doc_type_method"] == "fallback"
    assert result["doc_type_confidence"] == below
    assert "low_confidence" in result["doc_type_reason"]
    assert "DELIVERY_NOTE" in result["doc_type_reason"]


def test_confidence_exactly_at_the_threshold_is_accepted():
    """The boundary, stated rather than left to whoever next edits the
    comparison: `< threshold` is rejected, `== threshold` is kept."""
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = DocTypeClassification(
        doc_type="GRN", confidence=DOC_TYPE_CONFIDENCE_THRESHOLD, evidence="Wareneingang"
    )

    with patch.object(dtc, "get_llm", return_value=llm), patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(_document("Wareneingang"), {})

    assert result["doc_type"] == "GRN"
    assert result["doc_type_method"] == "llm"


def test_a_failed_model_call_fails_closed_to_other():
    """Any exception out of the fallback is `OTHER` with the reason, not a
    propagated 500 in the middle of an extraction run."""
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = RuntimeError("upstream 429")

    with patch.object(dtc, "get_llm", return_value=llm), patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(_document("Warenbegleitschein"), {})

    assert result["doc_type"] == "OTHER"
    assert "llm_error" in result["doc_type_reason"]


# --- T-C-4: E5's scope exclusion --------------------------------------------


_BILL_OF_LADING = (
    "BILL OF LADING\n"
    "B/L No: MAEU-4471902\n"
    "Shipper: Sample Exports Pvt Ltd, Nhava Sheva\n"
    "Consignee: To Order\n"
    "Vessel: MV Northern Star      Voyage: 118W\n"
    "Port of Loading: Nhava Sheva  Port of Discharge: Rotterdam\n"
    "Containers: 2 x 40HC          Freight: PREPAID\n"
)

_E_WAY_BILL = (
    "e-Way Bill\n"
    "EWB No: 1810 0012 3456\n"
    "Generated Date: 01/09/2026 14:22\n"
    "Valid Until: 03/09/2026\n"
    "Mode: Road     Approx Distance: 412 km\n"
    "Vehicle No: MH12AB1234\n"
    "From: Pune, Maharashtra   To: Indore, Madhya Pradesh\n"
)


@pytest.mark.parametrize(
    "text,label",
    [(_BILL_OF_LADING, "bill of lading"), (_E_WAY_BILL, "e-way bill")],
)
def test_transport_documents_are_other_not_a_mistyped_commercial_document(text, label):
    """T-C-4 / E5. Transport and custody documents are deliberately out of v1 and
    must route to `OTHER` cleanly rather than being force-fitted onto a
    commercial type.

    INVERTED BY A5/R7. This previously asserted
    `classify_doc_type_deterministic(text) == (None, "")` -- that the deterministic
    pass must NOT decide -- and then that the LLM fallback landed on `OTHER`.
    A8 rules the opposite: E5's deferred documents are recognised by title
    DETERMINISTICALLY "so they never fall to the LLM". These are not undecided
    documents; they are known documents we have decided are out of v1, and paying
    for a model call to reach a conclusion we already hold was the waste.

    What is asserted now is stronger on the point that matters: the answer is
    still `OTHER`, it costs NO model call, and `doc_type_method` says
    `deterministic` -- so a genuine miss (`fallback`) stays distinguishable from a
    recognised deferral in the telemetry, which is the distinction that made this
    change safe to make.

    Minimal representative text, not a fixture file: §7 task F has not produced
    real samples for these cells yet.
    """
    doc_type, evidence = classify_doc_type_deterministic(text)
    assert doc_type == "OTHER", label
    assert evidence, "a deterministic OTHER must still cite the printed line it decided from"

    with patch.object(dtc, "get_llm") as get_llm, patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(text, {})

    assert result["doc_type"] == "OTHER"
    assert result["doc_type_method"] == "deterministic"
    # The load-bearing half: a recognised deferral must not pay for a model call.
    get_llm.assert_not_called()


def test_an_e_way_bill_quoting_its_tax_invoice_number_is_still_not_an_invoice():
    """The case the minimal fixture above deliberately leaves out, and the one
    that would actually happen: a real e-way bill carries the tax-invoice number
    it was generated against. Only the title-band coverage guard keeps that
    reference from typing the document as an INVOICE and sending a transport
    document into the money rubric.

    Negative control run while writing this (2026-09-02): with
    `_TITLE_LINE_COVERAGE` temporarily set to 0.0, this exact text classifies
    `INVOICE` with evidence "Document Details: Tax Invoice No INV-2026-0447
    dated 01/09/2026". The guard is load-bearing, not decorative.
    """
    text = (
        "e-Way Bill\n"
        "EWB No: 1810 0012 3456\n"
        "Document Details: Tax Invoice No INV-2026-0447 dated 01/09/2026\n"
        "Valid Until: 03/09/2026     Approx Distance: 412 km\n"
    )

    # A5/R7: this now resolves DETERMINISTICALLY to OTHER on the "e-Way Bill"
    # title line, where it previously reached OTHER only via the LLM fallback.
    # The test is STRONGER for it, not weaker: the danger was never that a model
    # would decline to answer, it was that a model shown "Tax Invoice No
    # INV-2026-0447" might answer INVOICE. Recognising the title removes the
    # opportunity entirely rather than relying on the model's restraint.
    #
    # The title-band coverage guard is still what makes this work and is still
    # load-bearing -- the quoted tax-invoice reference sits on a body line whose
    # synonym coverage is far below the threshold, so it never competes with the
    # title. The negative control below still applies.
    doc_type, evidence = classify_doc_type_deterministic(text)
    assert doc_type == "OTHER"
    assert "way bill" in evidence.lower(), (
        f"must have decided from the TITLE, not the quoted invoice reference; got {evidence!r}"
    )

    with patch.object(dtc, "get_llm") as get_llm, patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(text, {})

    assert result["doc_type"] == "OTHER"
    assert result["doc_type_method"] == "deterministic"
    get_llm.assert_not_called()



# --- T-C-6 (A5/R7): the widened taxonomy, end to end -------------------------


@pytest.mark.parametrize(
    "printed_title,expected",
    [
        # The four new types, in their own words.
        ("Auftragsbestätigung", "ORDER_CONFIRMATION"),
        ("ORDER ACKNOWLEDGEMENT", "ORDER_CONFIRMATION"),
        ("Conferma d'ordine", "ORDER_CONFIRMATION"),
        ("Sales Order", "ORDER_CONFIRMATION"),
        ("RECEIPT", "RECEIPT"),
        ("Cash Memo", "RECEIPT"),
        ("Kleinbetragsrechnung", "RECEIPT"),
        ("Scontrino", "RECEIPT"),
        ("Remittance Advice", "REMITTANCE_ADVICE"),
        ("Zahlungsavis", "REMITTANCE_ADVICE"),
        ("Avis de paiement", "REMITTANCE_ADVICE"),
        ("STATEMENT OF ACCOUNT", "STATEMENT_OF_ACCOUNT"),
        ("Kontoauszug", "STATEMENT_OF_ACCOUNT"),
        ("Estratto conto", "STATEMENT_OF_ACCOUNT"),
        ("Balance Confirmation", "STATEMENT_OF_ACCOUNT"),
        # The PACKING_LIST fold -- these are DELIVERY_NOTE, not a 15th value.
        ("Packing List", "DELIVERY_NOTE"),
        ("Pick Ticket", "DELIVERY_NOTE"),
        ("Packliste", "DELIVERY_NOTE"),
        ("Liste de colisage", "DELIVERY_NOTE"),
        ("Paklijst", "DELIVERY_NOTE"),
        ("Dispatch Note", "DELIVERY_NOTE"),
        # E5's deferred set -- recognised, and recognised as OUT of v1.
        ("BILL OF LADING", "OTHER"),
        ("Air Waybill", "OTHER"),
        ("Lorry Receipt", "OTHER"),
        ("e-Way Bill", "OTHER"),
        ("Bill of Entry", "OTHER"),
        ("Shipping Bill", "OTHER"),
        ("Mahnung", "OTHER"),
        ("Zahlungserinnerung", "OTHER"),
        ("Timesheet", "OTHER"),
    ],
)
def test_t_c_6_every_new_synonym_classifies_deterministically_with_no_model_call(
    printed_title, expected
):
    """T-C-6. The widened vocabulary resolves from the printed title alone.

    `get_llm` is patched and asserted NOT called, which is T-C-1's shape and is
    the load-bearing half: a right answer reached by paying for a model call is a
    DIFFERENT BEHAVIOUR from the one E7 specifies, and only the mock can tell the
    two apart. A synonym that silently starts costing a call would otherwise pass.
    """
    with patch.object(dtc, "get_llm") as get_llm, patch.object(dtc, "tracked_llm_call"):
        result = classify_doc_type(f"{printed_title}\nRef: ABC-123\n", {})

    assert result["doc_type"] == expected, printed_title
    assert result["doc_type_method"] == "deterministic"
    get_llm.assert_not_called()


def test_t_c_6_packing_list_is_folded_not_a_fifteenth_type():
    """A5 folds PACKING_LIST into DELIVERY_NOTE rather than adding a value: same
    quantity rubric, same absent-price expectation, so a separate type would split
    one document class in two for no downstream difference. Asserted as an
    absence, because that is the shape of the decision."""
    assert "PACKING_LIST" not in DOC_TYPES
    assert "packing list" in _SYNONYMS["DELIVERY_NOTE"]
    assert DOC_TYPE_FAMILY["DELIVERY_NOTE"] == QUANTITY_FAMILY


def test_t_c_6_the_two_advisory_types_never_reach_the_money_rubric():
    """REMITTANCE_ADVICE and STATEMENT_OF_ACCOUNT must never be graded as
    payables (research §5 trap 10). R9 gives them their own ADVISORY family; until
    then they sit on OTHER_FAMILY, whose rubric is already `advisory_only`.

    This test is written against the GUARANTEE, not the family name, so it keeps
    passing when R9 moves them -- and fails if either is ever mapped to MONEY.
    """
    from agents.extraction_agent import _RUBRIC_BY_DOC_TYPE

    for doc_type in ("REMITTANCE_ADVICE", "STATEMENT_OF_ACCOUNT"):
        assert DOC_TYPE_FAMILY[doc_type] != MONEY_FAMILY, doc_type
        rubric = _RUBRIC_BY_DOC_TYPE[doc_type]
        assert rubric.advisory_only is True, doc_type
        assert rubric.run_field_confidence is False, doc_type
        assert rubric.run_di_tax_backfill is False, doc_type

# --- §8 trap 2: the model must be constructible with no arguments ------------


def test_the_classification_model_constructs_with_no_arguments():
    """§8 trap 2. `MockInvoiceLLM._generate_structured()`'s fallback is
    `try: return schema_cls()` inside a bare `except Exception`. A required field
    on this model would make mock mode present a classification *miss* instead of
    an error — the same masking that hid Gap 367's `TypeError`. The defaults are
    also the fail-closed answer: no opinion, no confidence, no evidence."""
    default = DocTypeClassification()
    assert default.doc_type == "OTHER"
    assert default.confidence == 0.0
    assert default.evidence == ""

    produced = MockInvoiceLLM().with_structured_output(DocTypeClassification).invoke("anything")
    assert isinstance(produced, DocTypeClassification)
    assert produced.doc_type == "OTHER"


def test_out_of_range_confidence_is_a_validation_error_not_a_silent_clamp():
    """A model that reports 1.4 confidence is not reporting confidence. `OTHER`
    with a recorded reason is the honest outcome (E7's "validation failure →
    OTHER")."""
    with pytest.raises(ValidationError):
        DocTypeClassification(doc_type="INVOICE", confidence=1.4, evidence="Tax Invoice")


# --- Degenerate input --------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   \n\n  ", None])
def test_empty_ocr_text_is_other_without_paying_for_a_model_call(text):
    """No text is not an ambiguity a model can resolve; spending a call on it
    buys a hallucination."""
    with patch.object(dtc, "get_llm") as get_llm:
        result = classify_doc_type(text, {})

    get_llm.assert_not_called()
    assert result["doc_type"] == "OTHER"
    assert result["doc_type_reason"] == "empty_ocr_text"


def test_ocr_text_falls_back_to_the_ocr_result_content_key():
    """`_run_ocr()` returns `content`; a caller that has the dict but not the
    string should not silently classify an empty document."""
    with patch.object(dtc, "get_llm") as get_llm:
        result = classify_doc_type("", {"content": _document("LIEFERSCHEIN")})

    get_llm.assert_not_called()
    assert result["doc_type"] == "DELIVERY_NOTE"
