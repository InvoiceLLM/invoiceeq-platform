"""Feature 30 task 30.0d — `detect_region()`.

Verification plan 30.0d: "GSTIN fixture -> IN; VAT-ID fixture -> EU; neither ->
None."

Pure string work, so no database and no LLM. The one persistence path
(`set_attachment_region`) is exercised in `tests/test_attachment_insights.py`,
which already holds a real Postgres attachment row.
"""
import os

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from services.region import detect_region  # noqa: E402


def test_gstin_is_india():
    doc = {"party_name": "Shree Packaging Pvt Ltd", "tax_ids": ["27AAPFU0939F1ZV"]}
    assert detect_region(doc) == "IN"


def test_gstin_wins_over_a_vat_looking_string():
    """A GSTIN is unambiguous; nothing may override it."""
    doc = {"tax_ids": ["27AAPFU0939F1ZV", "DE123456789"]}
    assert detect_region(doc) == "IN"


@pytest.mark.parametrize("vat", ["DE123456789", "FR12345678901", "EL123456789", "XI123456789"])
def test_eu_vat_ids(vat):
    assert detect_region({"tax_ids": [vat]}) == "EU"


def test_a_non_eu_country_prefix_is_not_eu():
    """"IN123456789" is an Indian party writing a non-GST id, not a EU VAT id."""
    assert detect_region({"tax_ids": ["IN123456789"]}) is None


def test_us_ein():
    assert detect_region({"party_tax_id": "12-3456789"}) == "US"


def test_us_state_and_zip_in_an_address():
    doc = {"addresses": [{"line1": "500 Market St", "line2": "San Francisco CA 94105"}]}
    assert detect_region(doc) == "US"


def test_neither_is_none_never_us():
    """None means "we do not know". A rule card that fires by default fires on
    the wrong documents."""
    doc = {"party_name": "Anonymous Trading", "grand_total": 1000.0}
    assert detect_region(doc) is None


def test_empty_and_malformed_inputs_are_none():
    assert detect_region(None) is None
    assert detect_region({}) is None
    assert detect_region({"items": [None, {"description": None}]}) is None


def test_a_tax_id_only_in_the_raw_text_is_still_found():
    assert detect_region({}, ocr_text="GSTIN: 27AAPFU0939F1ZV") == "IN"


def test_it_reads_nested_structures():
    doc = {"compliance_metadata": [{"scheme": "gst", "value": {"id": "27aapfu0939f1zv"}}]}
    assert detect_region(doc) == "IN"
