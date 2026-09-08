"""Feature 30 tasks 30.9-30.11 — rule cards and the deterministic compliance card.

Verification plan 30.9-30.10: "Every card file has all fields and a reachable
`source_url`; founder spot-checks each card against its source."
Verification plan 30.11: "Fixtures per check (credit note without original
invoice reference; EU PO without VAT id; RCM contract without flag) -> `verify`
fails with the citing rule id; compliant fixtures pass."

**Reachability is asserted OFFLINE**: the URLs are checked for shape and host,
not fetched. A test that hits the internet fails when a government site is down,
which would make an unrelated build red; the fetch happened once, on
2026-09-08, and is recorded in each card's `fetched_at`. What this file DOES
assert is the thing that protects the user: an `unverified` card, with no text
because nobody read the source, can never reach a bubble.

No LLM: every check in `CHECKS` is deterministic Python over the extracted JSON.
"""
import os
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from services import rule_cards as rc  # noqa: E402

ALL_CARDS = rc.load_rule_cards(include_unverified=True)


def _row(doc_type="CREDIT_NOTE", region="EU", **data):
    return SimpleNamespace(
        id=uuid4(), doc_type=doc_type, region=region, extracted_json=data, doc_number=data.get("doc_number")
    )


# --- the card files ---------------------------------------------------------


def test_there_are_cards_for_all_three_regions():
    regions = {c.region for c in ALL_CARDS}
    assert regions == {"IN", "EU", "US"}


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.id)
def test_every_card_declares_every_required_field(card):
    for field in rc.REQUIRED_FIELDS:
        assert getattr(card, field), f"{card.id} is missing {field}"
    assert card.applies_to_doc_types
    assert card.review_at, f"{card.id} has no review date"


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.id)
def test_every_source_url_is_a_primary_source(card):
    """Shape and host, checked offline — see the module docstring."""
    assert re.match(r"^https://", card.source_url), card.id
    host = card.source_url.split("/")[2]
    assert host.endswith((".gov", ".gov.in", ".europa.eu")), f"{card.id} cites {host}"


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.id)
def test_a_cards_verify_names_a_real_check_or_nothing(card):
    if card.verify:
        assert card.verify in rc.CHECKS, f"{card.id} names an unknown check {card.verify}"


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.id)
def test_status_and_body_agree(card):
    """Hard rule 8, as a property of every file on disk.

    A `verified` card must have text (somebody read the source and wrote it);
    an `unverified` card must have NONE (nobody did, so there is nothing
    honest to say).
    """
    if card.status == rc.STATUS_VERIFIED:
        assert card.body.strip(), f"{card.id} claims verified but has no text"
        assert card.fetched_at, f"{card.id} claims verified but records no fetch date"
    else:
        assert not card.body.strip(), f"{card.id} is unverified but carries rule text"


def test_unverified_cards_are_never_loaded_for_display():
    shown = {c.id for c in rc.load_rule_cards()}
    unverified = {c.id for c in ALL_CARDS if c.status != rc.STATUS_VERIFIED}
    assert unverified, "this test is meaningless with no unverified cards"
    assert not (shown & unverified)


def test_the_india_cards_are_unverified_and_say_which_source_they_need():
    """Recorded as a test, not only in prose: the founder asked for CBIC/GSTN
    cards, the sources could not be fetched from this environment, and the
    skeletons must not drift into looking authoritative."""
    india = [c for c in ALL_CARDS if c.region == "IN"]
    assert len(india) == 3
    assert all(c.status == rc.STATUS_UNVERIFIED for c in india)
    assert all(not c.body.strip() for c in india)
    assert all("cbic-gst.gov.in" in c.source_url for c in india)
    assert all(c.source_title for c in india)


def test_a_malformed_card_is_skipped_not_half_loaded():
    assert rc.parse_rule_card("no front matter here") is None
    assert rc.parse_rule_card("---\nid: x\n---\nbody") is None  # missing required fields


# --- the checks (30.11) -----------------------------------------------------


def test_credit_note_reference_check():
    fails, detail = rc.credit_note_references_invoice({}, _row())
    assert fails == "fail"
    assert "does not name" in detail

    passes, detail = rc.credit_note_references_invoice(
        {"referenced_documents": [{"doc_number": "INV-2026-014"}]}, _row()
    )
    assert passes == "pass"
    assert "INV-2026-014" in detail


def test_vat_id_check():
    assert rc.vat_id_present({"tax_ids": ["DE123456789"]}, _row())[0] == "pass"
    assert rc.vat_id_present({"party_name": "Nobody Ltd"}, _row())[0] == "fail"


def test_gstin_check():
    assert rc.gstin_present({"tax_ids": ["27AAPFU0939F1ZV"]}, _row(region="IN"))[0] == "pass"
    assert rc.gstin_present({"tax_ids": ["DE123456789"]}, _row(region="IN"))[0] == "fail"


def test_hsn_check_distinguishes_absent_from_partial():
    assert rc.hsn_code_present({}, _row())[0] == "not_applicable"
    assert rc.hsn_code_present({"items": [{"description": "x"}]}, _row())[0] == "fail"
    partial = rc.hsn_code_present(
        {"items": [{"hsn_sac_code": "4819"}, {"description": "no code"}]}, _row()
    )
    assert partial[0] == "fail" and "1 of 2" in partial[1]
    assert rc.hsn_code_present({"items": [{"hsn_sac_code": "4819"}]}, _row())[0] == "pass"


def test_reverse_charge_check_is_three_valued():
    assert rc.reverse_charge_flagged({"notes": "Reverse charge applies"}, _row())[0] == "pass"
    # No tax and no wording -> the finding.
    assert rc.reverse_charge_flagged({"grand_total": 1000.0, "tax_amount": 0}, _row())[0] == "fail"
    # Tax charged -> no wording expected, and that is not a pass either.
    assert (
        rc.reverse_charge_flagged({"grand_total": 1180.0, "tax_amount": 180.0}, _row())[0]
        == "not_applicable"
    )


def test_payment_terms_and_document_number_checks():
    assert rc.payment_terms_stated({"payment_terms": "Net 30"}, _row())[0] == "pass"
    assert rc.payment_terms_stated({}, _row())[0] == "fail"
    assert rc.document_number_present({}, _row(doc_number="CN-1"))[0] == "pass"
    assert rc.document_number_present({}, _row())[0] == "fail"


def test_a_card_with_no_verify_is_informational_never_a_pass():
    card = next(c for c in ALL_CARDS if c.verify is None)
    result = rc.verify_checks_for(card, {}, _row())
    assert result["outcome"] == "informational"
    assert result["source_url"] == card.source_url


def test_a_card_naming_a_missing_check_never_passes():
    """A typo in a card must not read as compliance."""
    card = rc.RuleCard(
        id="typo", region="EU", title="t", source_url="https://x.europa.eu/",
        applies_to_doc_types=("CREDIT_NOTE",), status=rc.STATUS_VERIFIED, body="text",
        verify="no_such_check",
    )
    result = rc.verify_checks_for(card, {}, _row())
    assert result["outcome"] == "not_applicable"
    assert "does not exist" in result["detail"]


def test_a_check_that_raises_is_contained():
    def _boom(data, row):
        raise RuntimeError("nope")

    rc.CHECKS["_boom"] = _boom
    try:
        card = rc.RuleCard(
            id="boom", region="EU", title="t", source_url="https://x.europa.eu/",
            applies_to_doc_types=("CREDIT_NOTE",), status=rc.STATUS_VERIFIED, body="text",
            verify="_boom",
        )
        assert rc.verify_checks_for(card, {}, _row())["outcome"] == "not_applicable"
    finally:
        rc.CHECKS.pop("_boom", None)


# --- running them against a document ---------------------------------------


def test_eu_credit_note_without_a_reference_fails_with_the_citing_rule():
    row = _row("CREDIT_NOTE", "EU", grand_total=1000.0, tax_amount=180.0)
    results = rc.run_compliance_checks(row)
    failed = {r["card_id"] for r in results if r["outcome"] == "fail"}
    assert "eu-credit-note-reference" in failed
    assert "eu-supplier-vat-id" in failed
    for result in results:
        assert result["source_url"].startswith("https://")


def test_a_compliant_eu_credit_note_passes():
    row = _row(
        "CREDIT_NOTE",
        "EU",
        referenced_documents=[{"doc_number": "INV-2026-014"}],
        tax_ids=["DE123456789"],
        grand_total=1000.0,
        tax_amount=190.0,
    )
    results = rc.run_compliance_checks(row)
    assert results and not [r for r in results if r["outcome"] == "fail"]


def test_no_region_means_no_checks_rather_than_default_checks():
    assert rc.run_compliance_checks(_row("CREDIT_NOTE", None)) == []


def test_india_cards_never_run_even_on_an_indian_document():
    """They are unverified, so `load_rule_cards()` does not return them."""
    row = _row("CREDIT_NOTE", "IN", grand_total=1000.0)
    assert rc.run_compliance_checks(row) == []


# --- the bubble's compliance card -------------------------------------------


def test_the_compliance_card_reports_failures_with_their_source(monkeypatch):
    from config import get_settings
    from services import attachment_insights as ai

    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", True, raising=False)
    row = _row("CREDIT_NOTE", "EU", grand_total=1000.0, tax_amount=180.0)
    row.tenant_id = uuid4()
    row.party_name = "Berlin Verpackung GmbH"
    row.currency = "EUR"

    card = ai.card_compliance(row, None, {"stage": "sync"})
    assert card.status == "ok"
    assert card.evidence["region"] == "EU"
    keys = {f["finding_key"] for f in card.findings}
    assert "compliance:eu-credit-note-reference" in keys
    # A compliance finding carries no invented impact amount.
    assert all(f["impact_amount"] is None for f in card.findings)
    assert all(f["evidence"]["source_url"].startswith("https://") for f in card.findings)


def test_the_compliance_card_says_when_it_cannot_tell_the_region(monkeypatch):
    from config import get_settings
    from services import attachment_insights as ai

    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", True, raising=False)
    row = _row("CREDIT_NOTE", None)
    row.tenant_id = uuid4()
    card = ai.card_compliance(row, None, {"stage": "sync"})
    assert card.status == "skipped"
    assert "which country's rules" in card.reason
