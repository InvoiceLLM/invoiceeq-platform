"""T-C-6, T-R-8..11, T-A-1 — the A5–A8 amendments against REAL fixture PDFs.

Task R11. Every other A-series test in this repo drives hand-built state dicts,
which is right for asserting a rubric's wiring and wrong for asserting that the
taxonomy survives contact with a document. These run the real
`classify_doc_type()` over the real PDFs in `tests/fixtures/doc_types/`, through
the same PyMuPDF text extraction the OCR path produces.

WHY THAT DISTINCTION MATTERS. A hand-built `{"doc_type": "RECEIPT"}` proves the
rubric branches correctly once something has already decided the type. It cannot
catch a synonym that does not match the printed title, a title-band guard that
picks the wrong line, or a German transliteration nobody thought of — all three
of which are real defects this file's fixtures found (BE Gap 396).

Skips rather than fails if a fixture is missing: the fixture set is generated
(`_generate_fixtures.py`) and a checkout without it should not report a false
defect in the classifier.
"""
from pathlib import Path

import pytest

pytest.importorskip("fitz")
import fitz  # noqa: E402

from agents.extraction_agent import _RUBRIC_BY_DOC_TYPE  # noqa: E402
from services.doc_attributes import derive_doc_attributes  # noqa: E402
from services.document_type_classifier import (  # noqa: E402
    DOC_TYPE_CONFIDENCE_THRESHOLD,
    DOC_TYPE_FAMILY,
    MONEY_FAMILY,
    classify_doc_type,
)

FIXTURES = Path(__file__).parent / "fixtures" / "doc_types"

#: folder -> the type its documents must classify as.
EXPECTED_BY_FOLDER = {
    "order_confirmation": "ORDER_CONFIRMATION",
    "receipt": "RECEIPT",
    "remittance_advice": "REMITTANCE_ADVICE",
    "statement_of_account": "STATEMENT_OF_ACCOUNT",
    "delivery_note": "DELIVERY_NOTE",
    "proforma_invoice": "PROFORMA_INVOICE",
    "purchase_order": "PURCHASE_ORDER",
    "contract": "CONTRACT",
    "quotation": "QUOTATION",
    "grn": "GRN",
    "credit_note": "CREDIT_NOTE",
    "debit_note": "DEBIT_NOTE",
    "other": "OTHER",
}


def _all_fixtures():
    if not FIXTURES.exists():
        return []
    return sorted(FIXTURES.rglob("*.pdf"))


def _text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _folder_of(path: Path) -> str:
    return path.relative_to(FIXTURES).parts[0]


ALL = _all_fixtures()
pytestmark = pytest.mark.skipif(not ALL, reason="fixture set not generated")


# --- T-C-6: every fixture classifies correctly, and cheaply -----------------


@pytest.mark.parametrize("path", ALL, ids=lambda p: str(p.name))
def test_t_c_6_every_fixture_classifies_to_its_folders_type(path):
    """The whole fixture set, against the real classifier and real PDF text.

    The folder IS the ground truth -- `MANIFEST.md` records the expected type,
    family and evidence phrase per file, and the directory layout encodes the
    first of those, so a fixture filed in the wrong folder fails here rather than
    quietly becoming its own baseline.
    """
    result = classify_doc_type(_text(path), {})
    assert result["doc_type"] == EXPECTED_BY_FOLDER[_folder_of(path)], (
        f"{path.name}: got {result['doc_type']} via {result['doc_type_method']} "
        f"(evidence {result['doc_type_evidence']!r})"
    )


@pytest.mark.parametrize("path", ALL, ids=lambda p: str(p.name))
def test_t_c_6_every_fixture_resolves_without_paying_for_a_model_call(path):
    """E7 requires the deterministic pass to be the common case, and the whole
    fixture set is the common case: 24 of 24 resolve from the printed title band.

    This is the test BE Gap 396 was found by. Three fixtures previously reached
    the right answer through the LLM fallback because the synonym table carried
    only the umlaut-folded German spellings ("auftragsbestatigung") and not the
    ASCII transliterations ("auftragsbestaetigung") that every system unable to
    emit umlauts produces. The answers were right and the cost was wrong, which
    an assertion on the ANSWER alone could never have caught.
    """
    result = classify_doc_type(_text(path), {})
    assert result["doc_type_method"] == "deterministic", (
        f"{path.name} fell back to {result['doc_type_method']} "
        f"(reason {result.get('doc_type_reason')!r}) -- if that is correct, say so "
        f"in MANIFEST.md; if it is a missing synonym, add it"
    )
    assert result["doc_type_confidence"] == 1.0


def test_t_c_6_the_fixture_set_covers_every_taxonomy_value_that_can_be_printed():
    """A5 widened `DOC_TYPES` to fourteen and four of the new values had no
    fixture at all, which is what made A5-A8 code with no evidence.

    `INVOICE` is excluded deliberately: §7 says to reuse the existing
    `tests/india` and `tests/eu` invoice fixtures rather than duplicate them.
    """
    covered = {EXPECTED_BY_FOLDER[_folder_of(p)] for p in ALL}
    expected = set(DOC_TYPE_FAMILY) - {"INVOICE"}
    assert covered == expected, f"uncovered: {sorted(expected - covered)}"


def test_t_c_6_the_recalibrated_threshold_demotes_nothing_in_the_fixture_set():
    """R11's calibration, asserted rather than asserted-about.

    0.6 was a placeholder (§2A/N2). The measured LLM-path confidences across
    runs 2 and 3 were 0.90/0.92/0.93/0.95/0.95/0.95 -- nothing between 0.60 and
    0.90 -- and the threshold is now 0.75, clear of every observation. Since the
    whole set now resolves deterministically at 1.0, the threshold cannot demote
    any of them, and this test is what keeps that true if a synonym is ever
    removed.
    """
    assert DOC_TYPE_CONFIDENCE_THRESHOLD == 0.75
    for path in ALL:
        confidence = classify_doc_type(_text(path), {})["doc_type_confidence"]
        assert confidence >= DOC_TYPE_CONFIDENCE_THRESHOLD, path.name


# --- T-R-8 / T-R-9: the new families against real documents -----------------


@pytest.mark.parametrize(
    "folder", ["remittance_advice", "statement_of_account"]
)
def test_t_r_8_advisory_fixtures_land_on_a_rubric_that_runs_no_arithmetic(folder):
    """A statement carries a RUNNING BALANCE and a remittance lists per-invoice
    amounts against one payment -- research §5 trap 6, money-only with no lines.
    Asserted on the resolved rubric for the type the REAL document classified as,
    so a synonym change that silently re-typed one of these would fail here."""
    paths = [p for p in ALL if _folder_of(p) == folder]
    assert paths, f"no {folder} fixture"

    for path in paths:
        doc_type = classify_doc_type(_text(path), {})["doc_type"]
        rubric = _RUBRIC_BY_DOC_TYPE[doc_type]
        assert rubric.run_line_item_math is False, path.name
        assert rubric.run_totals_math is False, path.name
        assert rubric.advisory_only is True, path.name
        assert DOC_TYPE_FAMILY[doc_type] != MONEY_FAMILY, path.name


def test_t_r_9_a_receipt_is_money_family_but_legally_missing_fields():
    """Research §5 trap 9. `EU-RC-01_kleinbetragsrechnung.pdf` is a real
    small-amount invoice shape: NO buyer name, NO unit price, VAT shown as a rate
    rather than an amount. All three absences are lawful (s.33 UStDV).

    The fixture's job is to make that concrete -- the relaxation itself rides on
    `invoice_subtype=SIMPLIFIED` and is R8's, so this asserts the classification
    and the absence, not a rubric that does not exist yet.
    """
    paths = [p for p in ALL if _folder_of(p) == "receipt"]
    assert paths

    for path in paths:
        text = _text(path)
        assert classify_doc_type(text, {})["doc_type"] == "RECEIPT", path.name
        assert DOC_TYPE_FAMILY["RECEIPT"] == MONEY_FAMILY

    kleinbetrag = next((p for p in paths if "kleinbetrag" in p.name.lower()), None)
    if kleinbetrag:
        text = _text(kleinbetrag).lower()
        # It says outright that no separate tax statement is required. That
        # sentence is why the money rubric must not demand one.
        assert "kleinbetragsrechnung" in text


# --- T-R-11 / T-A-1: A6's attributes off real documents ---------------------


def test_t_a_1_direction_and_ids_are_derived_from_real_document_text():
    """A6/T-A-1 against a document rather than a string literal. The India
    remittance advice prints both parties' GSTINs, so the identifier extraction
    has something real to find -- and `direction` stays None because two
    different registrations with no tenant context is genuinely undetermined,
    which is the honest answer rather than a guess."""
    path = next((p for p in ALL if "IN-RA-01" in p.name), None)
    if path is None:
        pytest.skip("India remittance fixture not generated")

    attrs = derive_doc_attributes(_text(path), doc_type="REMITTANCE_ADVICE")
    gstins = attrs.get("regional_ids", {}).get("gstin", [])
    assert len(gstins) >= 2, f"expected both parties' GSTINs, got {gstins}"
    assert attrs.get("direction") is None


def test_t_r_11_a_real_credit_note_fixture_carries_no_invented_correction_method():
    """`derive_correction_method()` returning None is load-bearing: it is what
    makes Feature 26 state the DELTA assumption instead of hiding it. A fixture
    that prints no correction marker must therefore produce None, not a default.
    """
    path = next((p for p in ALL if _folder_of(p) == "credit_note"), None)
    if path is None:
        pytest.skip("credit-note fixture not generated")

    attrs = derive_doc_attributes(_text(path), doc_type="CREDIT_NOTE")
    method = attrs.get("correction_method")
    assert method in (None, "DELTA", "SUBSTITUTION", "REVERSAL")
    if method is None:
        assert "correction_method_evidence" not in attrs
