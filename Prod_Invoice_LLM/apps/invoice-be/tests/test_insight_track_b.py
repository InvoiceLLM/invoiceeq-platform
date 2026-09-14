"""Feature 30 Track B — Gaps 510, 517.1, 517.2. Pure-function tests, no database.

Property assertions only: a delivered line that pairs with nothing is an UNKNOWN, figures for
two invoices never overwrite each other, and the page text actually reaches region detection.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import services.attachment_insights as ai


def _row(items, doc_type="DELIVERY_NOTE"):
    return SimpleNamespace(
        id="att-1", tenant_id="t-1", doc_type=doc_type, currency="INR",
        extracted_json={"items": items}, party_name="Any Vendor", doc_number="DC-1",
        candidate_invoice_ids=None, confirmed_invoice_ids=None, match_tier="probable",
    )


def _inv(number, items):
    return SimpleNamespace(invoice_number=number, items=items, invoice_date=None, due_date=None,
                           vendor_name="Any Vendor", grand_total=0, currency="INR")


# --- Gap 517.1 --------------------------------------------------------------


def test_a_delivered_line_that_pairs_with_no_billed_line_is_not_checked_not_clean(monkeypatch):
    monkeypatch.setattr(ai, "_confidence_for_link", lambda invs, row: ("med", "stub"))
    row = _row([{"description": "M.S. Round Bar 25mm", "quantity": 10},
                {"description": "Hex Bolt M10", "quantity": 200}])
    ctx = {"invoices": [_inv("INV-1", [{"description": "M.S. Round Bar 25mm", "quantity": 10}])]}

    card = ai.card_delivery_vs_order(row, None, ctx)

    assert card.status == ai.STATUS_OK
    assert "1 delivered lines checked, 1 not checked" in card.title
    unchecked = card.evidence["not_checked"]
    assert unchecked[0]["subjects"] == ["Hex Bolt M10"]
    assert "pairs with this description" in unchecked[0]["reason"]
    assert card.findings == []  # the paired line matched; the unpaired one is NOT a finding


def test_a_fully_paired_delivery_reads_as_checked_with_no_unchecked_clause(monkeypatch):
    monkeypatch.setattr(ai, "_confidence_for_link", lambda invs, row: ("med", "stub"))
    row = _row([{"description": "Widget", "quantity": 5}])
    ctx = {"invoices": [_inv("INV-1", [{"description": "Widget", "quantity": 5}])]}
    card = ai.card_delivery_vs_order(row, None, ctx)
    assert card.title.startswith("1 delivered lines checked")
    assert "not checked" not in card.title


# --- Gap 517.2 --------------------------------------------------------------


def test_two_invoices_billing_the_same_item_do_not_overwrite_each_others_figures(monkeypatch):
    monkeypatch.setattr(ai, "_confidence_for_link", lambda invs, row: ("med", "stub"))
    row = _row([{"description": "Widget", "quantity": 5}])
    ctx = {"invoices": [
        _inv("INV-A", [{"description": "Widget", "quantity": 5}]),
        _inv("INV-B", [{"description": "Widget", "quantity": 7}]),
    ]}
    card = ai.card_delivery_vs_order(row, None, ctx)

    billed_keys = [k for k in card.figures if k.startswith("billed_qty_")]
    assert len(billed_keys) == 2 and all(("INV-A" in k) or ("INV-B" in k) for k in billed_keys)
    assert card.figures["billed_qty_INV-A_widget"] == 5.0
    assert card.figures["billed_qty_INV-B_widget"] == 7.0
    # One passes, one fails, and the finding names the right invoice with formatted quantities.
    assert len(card.findings) == 1
    f = card.findings[0]
    assert f["claim"]["entity"] == "INV-B"
    assert "INV-B bills 7 of 'Widget' but 5 was delivered" == f["title"]


def test_the_delivery_claim_survives_a_renamed_item_and_decimal_quantities():
    claim = ai.Claim(kind="delivery_quantity_mismatch", entity="X-9",
                     figures={"billed": Decimal("2.50"), "delivered": Decimal("2")},
                     subjects=["Cable 3-core (per metre)"])
    assert ai.render_claim(claim) == "X-9 bills 2.50 of 'Cable 3-core (per metre)' but 2 was delivered"


# --- Gap 510 ----------------------------------------------------------------


def test_run_sync_insights_hands_the_page_text_to_region_detection(monkeypatch):
    """The escape hatch existed in `detect_region(ocr_text=...)` and was never fed. This pins
    the plumbing: text given to the sync stage is the text region detection receives."""
    import services.region as region

    seen = {}

    def fake_set_region(row, db, ocr_text=None):
        seen["ocr_text"] = ocr_text
        return "IN"

    monkeypatch.setattr(region, "set_attachment_region", fake_set_region)
    monkeypatch.setattr(ai, "insights_enabled", lambda: True)
    monkeypatch.setattr(ai, "build_insight_block", lambda *a, **k: {"findings": [], "cards": []})
    monkeypatch.setattr(ai, "post_insight_turn", lambda *a, **k: SimpleNamespace(id="m-1"))
    monkeypatch.setattr(ai, "open_insights_from_block", lambda *a, **k: [])

    class Session:
        def add(self, *_): pass
        def commit(self): pass

    row = _row([], doc_type="PURCHASE_ORDER")
    page = "Tax Invoice ... GSTIN 27AAFCV1234M1Z5 ..."
    block = ai.run_sync_insights(row, Session(), ocr_text=page)

    assert block is not None
    assert seen["ocr_text"] == page


def test_a_gstin_only_on_the_page_still_resolves_the_region():
    """End-to-end on the detector itself: nothing in the extraction, the id on the page."""
    import services.region as region
    assert region.detect_region({"po_number": "PO-1"}, ocr_text="... 27AAFCV1234M1Z5 ...") == "IN"
    assert region.detect_region({"po_number": "PO-1"}, ocr_text=None) is None


# --- Gap 518: payment application ------------------------------------------


def _remittance(refs, total, currency="INR"):
    return SimpleNamespace(
        id="att-r", tenant_id="t-1", doc_type="REMITTANCE_ADVICE", currency=currency,
        grand_total=total, extracted_json={"referenced_documents": refs, "utr_ref": "UTR-X"},
        party_name="Om Stationery", doc_number="PA-1",
    )


def _paid_inv(number, total, currency="INR"):
    from datetime import date
    return SimpleNamespace(invoice_number=number, grand_total=total, currency=currency,
                           invoice_date=date(2026, 8, 1), vendor_name="Om Stationery", items=[])


def test_a_remittance_names_the_invoice_it_settles_not_a_vendor_level_net(monkeypatch):
    import agents.entity_resolver as er
    invs = [_paid_inv("OM-2000", 25000), _paid_inv("OM-2001", 30000), _paid_inv("OM-2002", 15446)]
    monkeypatch.setattr(ai, "_tenant_invoices", lambda row, db: invs)
    monkeypatch.setattr(er, "_exact_invoice_lookup",
                        lambda mentions, tenant, db: {"om-2000": ("id-1", "OM-2000")})

    card = ai.card_payment_application(
        _remittance([{"doc_number": "OM-2000", "amount": 25000}], 25000), None, {"invoices": invs})

    assert card.status == ai.STATUS_OK
    assert len(card.findings) == 1
    f = card.findings[0]
    assert f["claim"]["entity"] == "OM-2000"
    assert f["claim"]["asserts"] == {"settled_in_full": True}
    assert f["title"] == "this payment settles OM-2000 in full (₹25,000.00)"
    assert "70,446" not in str(card.figures)  # the vendor-level net is not this card's answer


def test_a_short_payment_says_what_is_still_owed_and_an_unknown_reference_is_not_checked(monkeypatch):
    import agents.entity_resolver as er
    invs = [_paid_inv("OM-2000", 25000)]
    monkeypatch.setattr(ai, "_tenant_invoices", lambda row, db: invs)
    monkeypatch.setattr(er, "_exact_invoice_lookup",
                        lambda mentions, tenant, db: {"om-2000": ("id-1", "OM-2000")})

    card = ai.card_payment_application(
        _remittance([{"doc_number": "OM-2000", "amount": 20000},
                     {"doc_number": "NOT-ON-FILE", "amount": 5}], 20005), None, {"invoices": invs})

    assert "1 referenced invoices checked, 1 not checked" in card.title
    assert card.findings[0]["title"] == (
        "this payment of ₹20,000.00 against OM-2000 (₹25,000.00) leaves ₹5,000.00 still owed")
    assert card.evidence["not_checked"][0]["subjects"] == ["NOT-ON-FILE"]


def test_a_remittance_without_references_skips_rather_than_guessing():
    card = ai.card_payment_application(_remittance([], 100), None, {"invoices": []})
    assert card.status == ai.STATUS_SKIPPED


# --- Gap 517.3: linked duplicates --------------------------------------------


def test_two_linked_invoices_with_same_vendor_date_total_and_different_numbers_are_flagged():
    a, b = _paid_inv("RAJ-2008", 483850), _paid_inv("RAJ-2009", 483850)
    c = _paid_inv("RAJ-2010", 1000)
    card = ai.card_linked_duplicates(_row([]), None, {"invoices": [a, b, c]})
    assert len(card.findings) == 1
    f = card.findings[0]
    assert f["claim"]["severity"] == ai.SEVERITY_BREACH
    assert f["title"] == "RAJ-2008 and RAJ-2009 look like one bill entered twice: ₹483,850.00 on 2026-08-01"
    assert "2 linked invoices checked" in card.title  # the pair is one failed check, RAJ-2010 one passed


def test_a_linked_invoice_missing_a_date_is_not_checked_not_silently_dropped():
    a = _paid_inv("X-1", 100)
    b = _paid_inv("X-2", 100); b.invoice_date = None
    card = ai.card_linked_duplicates(_row([]), None, {"invoices": [a, b]})
    assert card.findings == []
    assert card.evidence["not_checked"][0]["subjects"] == ["X-2"]


def test_fewer_than_two_linked_invoices_skips():
    assert ai.card_linked_duplicates(_row([]), None, {"invoices": [_paid_inv("X", 1)]}).status == ai.STATUS_SKIPPED


# --- FE Gap 472 (BE half): findings carry their insight row id ---------------


def test_every_finding_carries_the_id_of_the_insight_row_opened_from_it(monkeypatch):
    import services.insights as ins
    from uuid import uuid4

    ids = {}

    def fake_open(**kw):
        ids[kw["finding_key"]] = uuid4()
        return SimpleNamespace(id=ids[kw["finding_key"]])

    monkeypatch.setattr(ins, "open_insight", fake_open)
    row = SimpleNamespace(id="a", tenant_id="t", session_id="s", doc_type="PURCHASE_ORDER", currency="INR")
    block = {"doc_type": "PURCHASE_ORDER", "findings": [
        ai.finding("k1", "t1", card="c"), ai.finding("k2", "t2", card="c")]}

    ai.open_insights_from_block(row, block, None)

    for f in block["findings"]:
        assert f["insight_id"] == str(ids[f["finding_key"]])


# --- Task 30.9 x 30.19: unverified rule cards surface as NOT_CHECKED ---------


def test_a_region_whose_rule_cards_are_all_unverified_reports_them_as_not_checked(monkeypatch):
    """Before this, `card_compliance` said "no IN rule card applies" when three exist but none
    is sourced. A missing check must read as missing, never as absent or as passed."""
    import services.rule_cards as rc
    import services.region as region

    monkeypatch.setattr(ai, "insights_enabled", lambda: True, raising=False)
    monkeypatch.setattr(rc, "run_compliance_checks", lambda row, region: [])
    monkeypatch.setattr(rc, "load_rule_cards", lambda **kw: [
        SimpleNamespace(id="in-x", title="A GST document must carry the supplier's GSTIN",
                        source_title="CGST Rules 2017, rule 46", source_url="https://cbic-gst.gov.in/",
                        is_showable=False, applies_to_doc_types=["CREDIT_NOTE", "DEBIT_NOTE"]),
        SimpleNamespace(id="in-y", title="Applies elsewhere", source_title="x", source_url="y",
                        is_showable=False, applies_to_doc_types=["PURCHASE_ORDER"]),
    ])
    row = _row([], doc_type="CREDIT_NOTE"); row.region = "IN"; row.doc_number = "CN-1"
    monkeypatch.setattr(region, "detect_region", lambda *a, **k: "IN", raising=False)

    card = ai.card_compliance(row, None, {"invoices": []})

    assert card.status == ai.STATUS_OK
    assert card.title.startswith("0 IN rules checked, 1 not checked")
    nc = card.evidence["not_checked"][0]
    assert nc["subjects"] == ["A GST document must carry the supplier's GSTIN"]
    assert "CGST Rules 2017, rule 46" in nc["reason"]
    assert card.findings == []


# --- Gap 513: vendor rules select by RESOLUTION, not substring ---------------


def test_a_vendor_rule_applies_only_when_the_mention_binds_to_that_vendor(monkeypatch):
    import agents.query_agent as qa
    import agents.entity_resolver as er
    from agents.entity_resolver import Candidate, ResolvedEntity

    templates = [
        SimpleNamespace(vendor_name="Shree", rules={"constraints": ["RULE-SHREE"]}),
        SimpleNamespace(vendor_name="Shree Packaging Pvt Ltd", rules={"constraints": ["RULE-SPPL"]}),
    ]

    class FakeSession:
        def exec(self, stmt):
            return SimpleNamespace(all=lambda: templates)

    monkeypatch.setattr(qa, "normalize_constraints", lambda c: list(c), raising=False)
    monkeypatch.setattr(er, "_resolve_vendors", lambda q, t, db: [
        ResolvedEntity("vendor", "shree packaging",
                       (Candidate("Shree Packaging Pvt Ltd", "Shree Packaging Pvt Ltd", 1.0),), "bound")])

    rules = qa._get_vendor_business_rules("00000000-0000-0000-0000-000000000001", "what did we buy from shree packaging?", FakeSession())

    # Before Gap 513 the substring test matched BOTH templates ("shree" is inside the question).
    assert rules == ["RULE-SPPL"]


def test_an_ambiguous_vendor_mention_applies_no_rule_at_all(monkeypatch):
    import agents.query_agent as qa
    import agents.entity_resolver as er
    from agents.entity_resolver import Candidate, ResolvedEntity

    templates = [SimpleNamespace(vendor_name="Shree", rules={"constraints": ["RULE-SHREE"]})]

    class FakeSession:
        def exec(self, stmt):
            return SimpleNamespace(all=lambda: templates)

    monkeypatch.setattr(qa, "normalize_constraints", lambda c: list(c), raising=False)
    monkeypatch.setattr(er, "_resolve_vendors", lambda q, t, db: [
        ResolvedEntity("vendor", "shree", (Candidate("Shree", "Shree", .9), Candidate("Shree Packaging Pvt Ltd", "Shree Packaging Pvt Ltd", .8)), "ambiguous")])

    # The question names "shree packaging"; the resolver could not decide between two vendors.
    # Word-boundary matching finds the template "Shree", but that name is CONTAINED in a
    # resolver candidate ("Shree Packaging Pvt Ltd") -- so the user meant the longer vendor
    # and the short template must not fire. Before Gap 513 it fired on every such question.
    assert qa._get_vendor_business_rules(
        "00000000-0000-0000-0000-000000000001", "what did we buy from shree packaging?", FakeSession()) == []


def test_a_whole_vendor_name_in_a_lowercase_question_still_selects_its_rule(monkeypatch):
    """The legacy shape `tests/test_rule_schema.py` protects: no lead word, no capitals, no
    resolver hit -- the whole name on word boundaries is enough."""
    import agents.query_agent as qa
    import agents.entity_resolver as er

    templates = [SimpleNamespace(vendor_name="ACME Corporation", rules={"constraints": ["RULE-ACME"]}),
                 SimpleNamespace(vendor_name="ACME", rules={"constraints": ["RULE-SHORT"]})]

    class FakeSession:
        def exec(self, stmt):
            return SimpleNamespace(all=lambda: templates)

    monkeypatch.setattr(qa, "normalize_constraints", lambda c: list(c), raising=False)
    monkeypatch.setattr(er, "_resolve_vendors", lambda q, t, db: [])

    # Longest whole-name match wins; the shorter "ACME" template is covered by the longer.
    assert qa._get_vendor_business_rules(
        "00000000-0000-0000-0000-000000000001", "what did we pay acme corporation", FakeSession()) == ["RULE-ACME"]
    # And a substring inside another word is NOT a match.
    assert qa._get_vendor_business_rules(
        "00000000-0000-0000-0000-000000000001", "anything from acmeshop today?", FakeSession()) == []
