"""Feature 27 A6 / task R8 — the classification attributes.

T-A-1 and the surrounding coverage. Every function under test is pure Python
with no model call, which is not incidental: these attributes select the
verification rubric and (in Feature 26) the comparison mode, both of which decide
how a FIGURE is judged. A model deciding them would be deciding a financial
outcome one step removed, which hard rule 3 exists to prevent. Several tests below
assert that absence directly rather than trusting the module docstring.

The recurring shape here is that a WRONG answer must be harder to produce than
NO answer. `None` means "not determined" throughout, and a test that only checked
happy paths would pass against a function that guessed.
"""
import pytest

from services.doc_attributes import (
    BUYER_ISSUED,
    CORRECTION_METHODS,
    DELTA,
    DIRECTIONS,
    INVOICE_SUBTYPES,
    REVERSAL,
    SELF_ISSUED,
    SUBSTITUTION,
    SUPPLIER_ISSUED,
    derive_correction_method,
    derive_direction,
    derive_doc_attributes,
    derive_invoice_subtype,
    extract_fiscal_markers,
    extract_regional_ids,
    looks_cumulative,
)

GSTIN_A = "29ABCDE1234F1Z5"
GSTIN_B = "27ZYXWV9876K2Z1"  # real GSTINs carry a literal Z at position 14
IRN = "a" * 64


# --- T-A-1: direction is derived from tax IDs, never from the title ----------


def test_t_a_1_direction_comes_from_the_tax_ids_not_the_printed_title():
    """Research §5 trap 2, and the single most valuable thing this module does.

    Same registration on both sides means the issuer and the recipient are the
    same legal person -- an RCM self-invoice, a statutory German *Gutschrift*, an
    ERS settlement. The TITLE actively misleads on all three, which is why the
    title is not consulted.

    Asserted both ways round: changing the title must NOT move `direction`, and
    changing the IDs MUST. A test that only did the first would pass against a
    function that always returned SELF.
    """
    body = f"Supplier GSTIN: {GSTIN_A}\nRecipient GSTIN: {GSTIN_A}\nTotal: 1,000.00\n"

    for title in ("TAX INVOICE", "GUTSCHRIFT", "CREDIT NOTE", "SELF INVOICE", ""):
        direction, evidence = derive_direction(f"{title}\n{body}")
        assert direction == SELF_ISSUED, title
        assert GSTIN_A in evidence

    # Swap one ID: the relationship is no longer determinable from the text alone,
    # and the honest answer is None rather than a guess at who issued it.
    two_party = f"TAX INVOICE\nSupplier GSTIN: {GSTIN_A}\nRecipient GSTIN: {GSTIN_B}\n"
    assert derive_direction(two_party)[0] is None


def test_direction_uses_the_tenants_own_registration_when_it_is_known():
    """With the tenant's own IDs supplied, first-position resolves the
    relationship: ours first means we issued it, ours second means they did."""
    text = f"TAX INVOICE\nSupplier GSTIN: {GSTIN_A}\nRecipient GSTIN: {GSTIN_B}\n"

    assert derive_direction(text, tenant_tax_ids=[GSTIN_A])[0] == SELF_ISSUED
    assert derive_direction(text, tenant_tax_ids=[GSTIN_B])[0] == SUPPLIER_ISSUED
    # A tenant ID that does not appear at all leaves it undetermined.
    assert derive_direction(text, tenant_tax_ids=["29ZZZZZ0000Z1Z9"])[0] is None


def test_direction_is_none_when_the_document_carries_no_registration():
    """Most delivery notes and packing slips print no tax ID at all. That is not
    a failure and must not resolve to a default."""
    assert derive_direction("DELIVERY CHALLAN\nQty: 40 cartons\n")[0] is None
    assert derive_direction("")[0] is None
    assert derive_direction(None)[0] is None


def test_every_direction_value_is_in_the_closed_set():
    assert set(DIRECTIONS) == {SUPPLIER_ISSUED, BUYER_ISSUED, SELF_ISSUED}


# --- regional identifiers ----------------------------------------------------


def test_regional_ids_are_found_and_deduplicated_in_first_appearance_order():
    text = (
        f"Supplier GSTIN: {GSTIN_A}\n"
        f"PAN: ABCDE1234F\n"
        f"Recipient GSTIN: {GSTIN_B}\n"
        f"Supplier GSTIN (repeated in footer): {GSTIN_A}\n"
    )
    ids = extract_regional_ids(text)
    # Order matters: `derive_direction` reads position, so a set would break it.
    assert ids["gstin"] == [GSTIN_A, GSTIN_B]


def test_regional_id_patterns_do_not_fire_on_ordinary_text():
    """A wrong tax ID is worse than a missing one -- `direction` is derived from
    these, so a spurious recipient-side match would flip a supplier invoice into a
    self-billed one. The unlabelled formats that are too common to match safely
    (a bare 9-digit SIREN, a bare 10-digit NIP) REQUIRE their keyword."""
    noise = (
        "Order 1234567890 shipped on 01/09/2026 via lorry MH12AB1234.\n"
        "Reference 123456789 and quantity 4471902 units.\n"
    )
    ids = extract_regional_ids(noise)
    assert ids.get("nip") is None
    assert ids.get("siren") is None
    assert ids.get("gstin") is None

    # ...but they are found when the document labels them, which real ones do.
    assert extract_regional_ids("NIP: 1234567890")["nip"] == ["1234567890"]
    assert extract_regional_ids("SIREN: 123 456 789")["siren"] == ["123456789"]


def test_an_eu_vat_id_needs_its_country_prefix():
    assert extract_regional_ids("VAT: DE123456789")["vat_id"] == ["DE123456789"]
    # No prefix -> not a VAT ID, just a number.
    assert "vat_id" not in extract_regional_ids("Reference: 123456789012")


# --- fiscal markers ----------------------------------------------------------


def test_fiscal_markers_are_evidence_of_the_invoice_family_not_a_verdict():
    """Research §5 trap 1(d). An IRN comes from India's IRP and a proforma cannot
    have one -- but a CREDIT NOTE also carries an IRN, and an e-way bill quotes
    the invoice's. So this returns evidence, and A8 consumes it as a pre-check
    that biases; nothing here decides a type."""
    assert extract_fiscal_markers(f"Tax Invoice\nIRN: {IRN}\n") == ["IRN_QR"]
    assert "KSEF_NO" in extract_fiscal_markers("Faktura\nKSeF: 1234567890-ABC")
    assert "SDI_ID" in extract_fiscal_markers("Fattura\nCodice Destinatario: ABC1234")
    assert extract_fiscal_markers("DELIVERY CHALLAN\nQty 40\n") == []
    assert extract_fiscal_markers(None) == []


def test_a_peppol_type_code_is_captured_with_its_number():
    markers = extract_fiscal_markers("Peppol BIS Billing 3.0 type code 381")
    assert "PEPPOL_TYPE_CODE:381" in markers
    # An unknown code is not recorded -- inventing a mapping would be a guess.
    assert not any(m.startswith("PEPPOL_TYPE_CODE") for m in
                   extract_fiscal_markers("Peppol type code 999"))


# --- correction_method -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Factura rectificativa por sustitución", SUBSTITUTION),
        ("Factura rectificativa por diferencias", DELTA),
        ("Faktura korygująca do faktury 12/2026", DELTA),
        ("Nota di variazione TD04", DELTA),
        ("Avoir sur facture 4471", DELTA),
        ("Stornorechnung zu Rechnung 4471", REVERSAL),
        ("Cancellation invoice", REVERSAL),
    ],
)
def test_correction_method_reads_the_regional_marker_not_the_language(text, expected):
    """Research §5 trap 8: the local label is not the model. "Factura
    rectificativa" (ES) is a corrective invoice, "Faktura korygująca" (PL) is
    always a delta, and both are "credit note" in English. The canonical value
    plus `correction_method` carries the difference; the label never does."""
    method, evidence = derive_correction_method(text)
    assert method == expected, text
    assert evidence


def test_correction_method_is_none_when_the_document_does_not_say():
    """The FOUNDER RULING depends on this returning None rather than defaulting:
    Feature 26 then runs the comparison as DELTA **and states that assumption in
    the answer**. A silent default here would make the assumption unstatable,
    because nothing downstream could tell a derived DELTA from an assumed one."""
    assert derive_correction_method("CREDIT NOTE\nAgainst invoice INV-1\n")[0] is None
    assert derive_correction_method("")[0] is None


def test_a_correcting_to_zero_note_reads_as_reversal_not_delta():
    """Specificity beats generality: a Polish note is a delta by default, but one
    explicitly correcting to zero is a reversal, and the more specific reading
    must win."""
    assert derive_correction_method("Faktura korygująca do zera")[0] == REVERSAL


def test_every_correction_method_is_in_the_closed_set():
    assert set(CORRECTION_METHODS) == {DELTA, SUBSTITUTION, REVERSAL}


# --- invoice_subtype ---------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Schlussrechnung Nr. 4471", "FINAL"),
        ("Anzahlungsrechnung", "ADVANCE"),
        ("Receipt Voucher under Rule 50", "ADVANCE"),
        ("RA Bill No. 7", "PARTIAL_PROGRESS"),
        ("Application for Payment AIA G702", "PARTIAL_PROGRESS"),
        ("Self Invoice under Rule 47A", "RCM_SELF_INVOICE"),
        ("Gutschrift", "SELF_BILLED"),
        ("ISD Invoice", "ISD"),
        ("Bill of Supply", "BILL_OF_SUPPLY"),
        ("Kleinbetragsrechnung", "SIMPLIFIED"),
        ("Export Invoice under LUT", "EXPORT"),
    ],
)
def test_invoice_subtype_reads_the_printed_marker(text, expected):
    subtype, evidence = derive_invoice_subtype(text, "INVOICE")
    assert subtype == expected, text
    assert evidence


def test_a_final_invoice_is_not_read_as_an_advance_even_though_it_mentions_advances():
    """DE §14(5): a Schlussrechnung MUST list and deduct the prior
    Anzahlungsrechnungen, so both words appear on the same document. Ordering in
    `_SUBTYPE_MARKERS` is what resolves it, and this test is what pins that
    ordering down."""
    text = "Schlussrechnung\nAbzüglich Anzahlungsrechnung vom 01.08.2026: 5.000,00\n"
    assert derive_invoice_subtype(text, "INVOICE")[0] == "FINAL"


def test_subtype_is_none_rather_than_standard_when_nothing_is_printed():
    """`STANDARD` is a positive claim; `None` means not determined. The money
    rubric's expected-absent set must not relax itself on a value nobody
    established -- which it would if an unmarked invoice defaulted to a subtype."""
    assert derive_invoice_subtype("TAX INVOICE\nTotal 1000\n", "INVOICE")[0] is None


def test_subtype_is_not_derived_for_a_non_invoice_family_document():
    """The question only arises once the type is known to be invoice-family. A
    delivery note that happens to mention an advance is not an ADVANCE invoice."""
    assert derive_invoice_subtype("Anzahlungsrechnung reference", "DELIVERY_NOTE")[0] is None


def test_gutschrift_maps_to_self_billed_here_without_contradicting_a8():
    """A8 rules that "Gutschrift" must NEVER resolve a DOC TYPE deterministically,
    because in UStG §14 it is a self-billing invoice and commercially it is a
    credit note. This function answers a different, narrower question that only
    arises once the type is already known to be INVOICE -- and given that, the
    word has exactly one meaning. Asserted explicitly so the two rules are not
    later mistaken for a conflict."""
    assert derive_invoice_subtype("Gutschrift", "INVOICE")[0] == "SELF_BILLED"
    # ...and it still says nothing about a credit note's type.
    assert derive_invoice_subtype("Gutschrift", "DELIVERY_NOTE")[0] is None


def test_every_subtype_is_in_the_closed_set():
    assert len(set(INVOICE_SUBTYPES)) == len(INVOICE_SUBTYPES)
    assert "STANDARD" in INVOICE_SUBTYPES


# --- cumulative --------------------------------------------------------------


def test_cumulative_is_detected_on_the_documents_that_actually_carry_it():
    """Research §5 trap 5: on these, "this bill" and "cumulative to date" are
    different numbers, and conflating them reports a discrepancy on a correct
    document -- the same false-failure class the feature exists to remove."""
    assert looks_cumulative("Less Previous Certificates: 40,000.00")
    assert looks_cumulative("RA Bill No 7\nRetention @ 5%")
    assert looks_cumulative("Abschlagszahlungen bisher berechnet")
    assert not looks_cumulative("TAX INVOICE\nSubtotal 1000\nTax 180\nTotal 1180\n")


# --- the entry point ---------------------------------------------------------


def test_derive_doc_attributes_omits_undetermined_keys_rather_than_writing_null():
    """`{}` and a dict of nulls are different statements. The column records what
    was ESTABLISHED, and a key present with a null value would be a third state
    (looked, found nothing, wrote it down) that nothing wants to distinguish."""
    attrs = derive_doc_attributes("DELIVERY CHALLAN\nQty: 40 cartons\n",
                                  doc_type="DELIVERY_NOTE")
    assert attrs == {} or "direction" not in attrs
    assert "invoice_subtype" not in attrs
    assert "correction_method" not in attrs


def test_derive_doc_attributes_collects_everything_a_rich_document_carries():
    text = (
        f"Schlussrechnung\n"
        f"Supplier GSTIN: {GSTIN_A}\nRecipient GSTIN: {GSTIN_A}\n"
        f"IRN: {IRN}\n"
        f"Less Previous Certificates: 40,000.00\n"
    )
    attrs = derive_doc_attributes(text, doc_type="INVOICE")
    assert attrs["direction"] == SELF_ISSUED
    assert attrs["invoice_subtype"] == "FINAL"
    assert attrs["fiscal_markers"] == ["IRN_QR"]
    assert attrs["cumulative"] is True
    assert attrs["regional_ids"]["gstin"] == [GSTIN_A]
    # Every derived value carries the phrase it was decided from, so a wrong
    # answer is reviewable after the fact rather than merely wrong.
    assert attrs["direction_evidence"]
    assert attrs["invoice_subtype_evidence"]


def test_derive_doc_attributes_never_raises():
    """It runs inside the extraction graph. A classification ENRICHMENT must not
    be able to fail the extraction it decorates -- the same policy
    `classify_doc_type_node` applies to the classifier itself."""
    for bad in (None, "", "\x00\x00", "x" * 100_000):
        assert isinstance(derive_doc_attributes(bad), dict)


def test_no_model_is_consulted_anywhere_in_this_module():
    """Hard rule 3, asserted structurally rather than trusted. These attributes
    select the verification rubric and Feature 26's comparison mode, so a model
    deciding them would be deciding a financial outcome one step removed."""
    import inspect

    import services.doc_attributes as mod

    source = inspect.getsource(mod)
    for forbidden in ("get_llm", "invoke(", "with_structured_output", "tracked_llm_call"):
        assert forbidden not in source, f"{forbidden} must not appear in doc_attributes"
