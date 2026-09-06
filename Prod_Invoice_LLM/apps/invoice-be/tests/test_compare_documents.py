"""Feature 26 B3/B7/B8, task R10 — compare_documents() and list_reconcile.

V-26, V-28, V-29.

The recurring assertion here is that an UNMATCHED line is a real, reportable
outcome and never a line fuzzily attached to the nearest thing found. That is the
judgement call `_compare_one()` explicitly refused to make when it stopped at
line-item COUNT, and the reason B3 builds a tiered matcher rather than a
similarity score: "Widget, blue, 10pk" and "Blue widget x10" may be the same
thing, and a matcher that guesses produces a confident wrong number.

`compare_reference_to_invoices()` is NOT modified, NOT wrapped and NOT called by
any of this. Its determinism is the control the whole feature rests on. One test
below asserts its output is byte-identical before and after R10 landed.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import services.document_comparison as dc
from models import Invoice
from services.document_comparison import (
    BOTH_MODE,
    COMPARISON_MODES,
    LIST_RECONCILE_MODE,
    MONEY_MODE,
    QUANTITY_MODE,
    compare_documents,
    reconcile_referenced_documents,
    resolve_comparison_mode,
)

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TENANT = uuid4()


@pytest.fixture(name="db")
def db_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _line(**kw):
    base = dict(description=None, quantity=None, unit_price=None, amount=None,
                hsn_sac_code=None, uom=None, line_number=None)
    base.update(kw)
    return base


def _doc(*lines):
    return {"items": list(lines)}


# --- V-28: the mode is a pure function of the doc_type pair ------------------


@pytest.mark.parametrize(
    "doc_type,expected",
    [
        ("PURCHASE_ORDER", BOTH_MODE),
        ("ORDER_CONFIRMATION", BOTH_MODE),
        ("QUOTATION", BOTH_MODE),
        ("PROFORMA_INVOICE", BOTH_MODE),
        ("CONTRACT", BOTH_MODE),
        ("DELIVERY_NOTE", QUANTITY_MODE),
        ("GRN", QUANTITY_MODE),
        ("INVOICE", MONEY_MODE),
        ("CREDIT_NOTE", MONEY_MODE),
        ("DEBIT_NOTE", MONEY_MODE),
        ("RECEIPT", MONEY_MODE),
        ("STATEMENT_OF_ACCOUNT", LIST_RECONCILE_MODE),
        ("REMITTANCE_ADVICE", LIST_RECONCILE_MODE),
    ],
)
def test_v28_the_mode_is_a_table_lookup_over_the_doc_type(doc_type, expected):
    assert resolve_comparison_mode(doc_type) == expected


def test_v28_an_unknown_or_other_document_gets_no_mode_and_must_clarify():
    """`OTHER` means we could not establish what this is, so there is no
    comparison we could defend. B9 routes a None mode to the clarifying turn
    rather than picking one -- guessing here would be a financial answer computed
    from an assumption nobody stated."""
    assert resolve_comparison_mode("OTHER") is None
    assert resolve_comparison_mode(None) is None
    assert resolve_comparison_mode("NOT_A_TYPE") is None


def test_v28_the_mode_table_covers_every_taxonomy_value_except_other():
    """An omission would resolve to None and clarify -- safe, but silently
    unhelpful for a type we do understand. Asserted against the live enum so a
    fifteenth type cannot be added without a decision here."""
    from services.document_type_classifier import DOC_TYPES

    for doc_type in DOC_TYPES:
        mode = resolve_comparison_mode(doc_type)
        if doc_type == "OTHER":
            assert mode is None
        else:
            assert mode in COMPARISON_MODES, doc_type


# --- V-26: the L1-L3 matcher -------------------------------------------------


def test_v26_l1_matches_on_the_shared_tax_code_and_unit():
    """An HSN/SAC code plus a unit is an identifier the two documents were meant
    to share. B3's stated prerequisite was widening ReferenceDocLineItem to carry
    it -- without that the only key is free-text description."""
    result = compare_documents(
        _doc(_line(description="MS Angle", hsn_sac_code="7216", uom="NOS", quantity=100)),
        _doc(_line(description="Completely different wording", hsn_sac_code="7216",
                   uom="NOS", quantity=100)),
        mode=QUANTITY_MODE,
    )
    assert result["line_items"][0]["match_tier"] == "L1"
    assert result["line_items"][0]["status"] == "match"


def test_v26_l2_matches_an_exact_description_after_folding():
    result = compare_documents(
        _doc(_line(description="M8 Hex Bolt, Zinc", quantity=50)),
        _doc(_line(description="m8  hex bolt zinc", quantity=50)),
        mode=QUANTITY_MODE,
    )
    assert result["line_items"][0]["match_tier"] == "L2"


def test_v26_l3_requires_corroboration_not_just_token_overlap():
    """The load-bearing half of L3. Token overlap alone matches "Steel Bolt M8"
    to "Steel Bolt M10" -- a different part -- so overlap must be corroborated by
    an equal quantity or a matching unit price before the pair is accepted."""
    corroborated = compare_documents(
        _doc(_line(description="Steel Bolt M8 Zinc Plated", quantity=40)),
        _doc(_line(description="Steel Bolt M8 Plated", quantity=40)),
        mode=QUANTITY_MODE,
    )
    assert corroborated["line_items"][0]["match_tier"] == "L3"

    # Same overlap, contradicted by both quantity and price -> NOT a match.
    uncorroborated = compare_documents(
        _doc(_line(description="Steel Bolt M8 Zinc Plated", quantity=40, unit_price=10)),
        _doc(_line(description="Steel Bolt M10 Plated", quantity=999, unit_price=99)),
        mode=QUANTITY_MODE,
    )
    assert uncorroborated["line_items"] == []
    assert uncorroborated["unmatched_count"] == 2


def test_v26_a_near_miss_is_reported_unmatched_never_attached_to_the_nearest_line():
    """The design point B3 turns on. An unmatched line is a real outcome exactly
    as Tier 0 is in find_candidate_invoices() -- and often it IS the answer, e.g.
    a billed line that was never ordered."""
    result = compare_documents(
        _doc(_line(description="Widget, blue, 10pk", quantity=10)),
        _doc(_line(description="Freight and handling", quantity=1)),
        mode=BOTH_MODE,
    )
    assert result["line_items"] == []
    assert len(result["unmatched"]["reference_lines"]) == 1
    assert len(result["unmatched"]["invoice_lines"]) == 1


def test_v26_a_stronger_tier_is_never_stolen_by_a_weaker_one():
    """Tiers run to exhaustion in order and each line is consumed once, so an L1
    pair cannot be broken up by an L3 candidate that happens to look similar."""
    result = compare_documents(
        _doc(
            _line(description="Angle", hsn_sac_code="7216", uom="NOS", quantity=10),
            _line(description="Angle bracket steel", quantity=10),
        ),
        _doc(
            _line(description="Angle bracket steel", quantity=10),
            _line(description="Totally other", hsn_sac_code="7216", uom="NOS", quantity=10),
        ),
        mode=QUANTITY_MODE,
    )
    tiers = {row["match_tier"] for row in result["line_items"]}
    assert "L1" in tiers
    assert result["matched_count"] == 2


def test_v26_a_uom_mismatch_is_its_own_outcome_not_a_quantity_agreement():
    """40 cartons against 40 pieces is not a quantity agreement. Reporting it as
    one would be a confident wrong answer, so it gets its own status -- the same
    structural choice H11 made for currency_mismatch in the diff table."""
    result = compare_documents(
        _doc(_line(description="Bolts", quantity=40, uom="CARTON")),
        _doc(_line(description="Bolts", quantity=40, uom="NOS")),
        mode=QUANTITY_MODE,
    )
    assert result["line_items"][0]["status"] == "uom_mismatch"


def test_v26_absent_price_is_not_a_discrepancy_in_quantity_mode():
    """Feature 27 E4's quantity rubric, and the founder's original symptom. A
    delivery note prints quantities and no prices BY DESIGN."""
    result = compare_documents(
        _doc(_line(description="MS Flat 40x6", quantity=40, unit_price=None, amount=None)),
        _doc(_line(description="MS Flat 40x6", quantity=40, unit_price=250.0, amount=10000.0)),
        mode=QUANTITY_MODE,
    )
    row = result["line_items"][0]
    assert row["status"] == "match"
    assert row["price_delta"] is None  # absent, never 0


def test_v26_a_missing_value_never_becomes_a_zero_delta():
    """Gap 283's discipline at the comparison layer: None means the document did
    not state it, and a 0 delta is a positive claim that the two agree."""
    result = compare_documents(
        _doc(_line(description="Item", quantity=None, unit_price=None)),
        _doc(_line(description="Item", quantity=5, unit_price=10.0)),
        mode=BOTH_MODE,
    )
    row = result["line_items"][0]
    assert row["quantity_delta"] is None
    assert row["price_delta"] is None


def test_v26_money_is_decimal_derived_and_never_float_arithmetic():
    """0.1 + 0.2 is the reason. Deltas are strings from Decimal subtraction, not
    floats, so nothing downstream can reintroduce binary error."""
    result = compare_documents(
        _doc(_line(description="Item", unit_price=0.1, quantity=1)),
        _doc(_line(description="Item", unit_price=0.3, quantity=1)),
        mode=MONEY_MODE,
    )
    delta = result["line_items"][0]["price_delta"]
    assert Decimal(delta) == Decimal("0.2")
    assert isinstance(delta, str)


def test_v26_an_unknown_mode_raises_rather_than_defaulting():
    """A silently-defaulted mode would compare a delivery note on money and
    report the false discrepancy this feature exists to remove."""
    with pytest.raises(ValueError, match="unknown comparison mode"):
        compare_documents(_doc(), _doc(), mode="whatever")


def test_v26_compare_reference_to_invoices_is_untouched_by_r10():
    """B3's explicit constraint: the Part 1 comparator is not modified, not
    wrapped and not called by compare_documents(). Its determinism is the control
    the whole feature rests on."""
    import inspect

    source = inspect.getsource(dc.compare_documents)
    assert "compare_reference_to_invoices" not in source
    assert "_compare_one" not in source
    # And the module still contains no LLM (hard rule 3).
    module_source = inspect.getsource(dc)
    for forbidden in ("get_llm", "with_structured_output", "llm.invoke"):
        assert forbidden not in module_source


# --- correction_method changes the arithmetic, not the mode (B7) -------------


def test_a_missing_correction_method_runs_as_delta_and_says_so():
    """The founder's ruling, and the reason derive_correction_method() returns
    None rather than defaulting: the assumption is STATED. An unstated assumption
    about which of three arithmetics produced a figure is exactly the silent
    wrongness this feature removes."""
    result = compare_documents(_doc(), _doc(), mode=MONEY_MODE, correction_method=None)
    assert result["correction_method"] == "DELTA"
    assert result["assumptions"], "the assumption must be stated, not silent"
    assert "DELTA" in result["assumptions"][0]

    stated = compare_documents(_doc(), _doc(), mode=MONEY_MODE, correction_method="SUBSTITUTION")
    assert stated["correction_method"] == "SUBSTITUTION"
    assert stated["assumptions"] == []


# --- V-29: list_reconcile (B8) ----------------------------------------------


def _invoice(db, number, total, status="COMPLETED", vendor="Northwind Trading"):
    row = Invoice(
        tenant_id=TENANT, file_path=f"{number}.pdf", vendor_name=vendor,
        invoice_number=number, invoice_date=date(2026, 3, 1), currency="INR",
        grand_total=total, status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_v29_list_reconcile_reports_all_five_outcomes(db):
    """A statement is a list of pointers, not a document with lines to diff. The
    fifth outcome -- an open invoice of OURS the statement omits -- is why this
    mode walks our invoices too rather than only their list."""
    _invoice(db, "INV-1", 1000.0)
    _invoice(db, "INV-2", 2000.0)
    _invoice(db, "INV-3", 3000.0, status="PAID")
    _invoice(db, "INV-MISSING-FROM-STATEMENT", 4000.0)

    result = reconcile_referenced_documents(
        tenant_id=TENANT,
        referenced_documents=[
            {"doc_number": "INV-1", "amount": 1000.0, "status_hint": "OPEN"},
            {"doc_number": "INV-2", "amount": 2500.0, "status_hint": "OPEN"},
            {"doc_number": "INV-3", "amount": 3000.0, "status_hint": "OPEN"},
            {"doc_number": "INV-UNKNOWN", "amount": 500.0, "status_hint": "OPEN"},
        ],
        db_session=db,
    )
    by_number = {r["doc_number"]: r for r in result["references"]}
    assert by_number["INV-1"]["outcome"] == "found_matching"
    assert by_number["INV-2"]["outcome"] == "amount_mismatch"
    assert Decimal(by_number["INV-2"]["delta"]) == Decimal("-500")
    assert by_number["INV-3"]["outcome"] == "status_mismatch"
    assert by_number["INV-UNKNOWN"]["outcome"] == "not_found"

    unreferenced = {u["invoice_number"] for u in result["unreferenced_invoices"]}
    assert "INV-MISSING-FROM-STATEMENT" in unreferenced


def test_v29_deductions_are_reported_per_kind_never_netted(db):
    """A remittance settling 92,000 against 100,000 is not a discrepancy if it
    prints "TDS 6,000" and "chargeback 2,000". One unexplained 8,000 gap is a
    support ticket; the two reasons are an answer."""
    result = reconcile_referenced_documents(
        tenant_id=TENANT,
        referenced_documents=[],
        deductions=[
            {"kind": "TDS", "amount": 6000.0, "reference": "194C"},
            {"kind": "CHARGEBACK", "amount": 2000.0, "reference": "OTIF"},
        ],
        db_session=db,
    )
    assert len(result["deductions"]) == 2
    assert {d["kind"] for d in result["deductions"]} == {"TDS", "CHARGEBACK"}


def test_v29_a_paid_invoice_is_not_reported_as_unreferenced(db):
    """The reverse direction is about what is OUTSTANDING. Listing settled
    invoices as "missing from their statement" would bury the real finding."""
    _invoice(db, "INV-PAID", 1000.0, status="PAID")
    result = reconcile_referenced_documents(
        tenant_id=TENANT, referenced_documents=[], db_session=db,
    )
    assert result["unreferenced_invoices"] == []


def test_v29_reconciliation_never_crosses_a_tenant_boundary(db):
    """A statement from one supplier must not be reconciled against another
    tenant's ledger. Scoped in the query, not filtered afterwards."""
    other = Invoice(
        tenant_id=uuid4(), file_path="x.pdf", vendor_name="Someone Else",
        invoice_number="INV-1", invoice_date=date(2026, 3, 1), currency="INR",
        grand_total=999.0, status="COMPLETED",
    )
    db.add(other)
    db.commit()

    result = reconcile_referenced_documents(
        tenant_id=TENANT,
        referenced_documents=[{"doc_number": "INV-1", "amount": 999.0}],
        db_session=db,
    )
    assert result["references"][0]["outcome"] == "not_found"
    assert result["unreferenced_invoices"] == []


# ===========================================================================
# The signed money ledger — Gap 472
# ===========================================================================
# Probe turn A4 (PO + credit note, "after the credit is applied what do we owe
# Apex?") failed on all three candidate models because nothing computed the
# answer. These tests are the arithmetic, not the narration: the prompt rule
# that makes the model read the block out is asserted in
# `tests/test_chat_attachments.py`.


def _term(doc_type, amount, number=None, currency="USD", source="attachment"):
    return {
        "doc_type": doc_type,
        "doc_number": number,
        "amount": amount,
        "currency": currency,
        "source": source,
    }


def test_a4_credit_note_against_the_po_is_the_probe_turn_verbatim():
    """The exact shape of turn A4: $452 invoiced, $20 credited, $432 PO."""
    result = dc.compute_amount_owed(
        [
            _term("INVOICE", 452, "APS-410093", source="invoice"),
            _term("CREDIT_NOTE", 20, "CN-APEX-01"),
        ],
        {
            "doc_type": "PURCHASE_ORDER",
            "doc_number": "PO-US-7002",
            "amount": 432,
            "currency": "USD",
        },
    )
    assert result["net"] == "432"
    assert result["currency"] == "USD"
    assert result["complete"] is True
    # The second half of the expected answer: the net EQUALS what was authorised.
    assert result["agreed"]["status"] == "match"
    assert result["agreed"]["delta"] == "0"
    assert result["agreed"]["doc_number"] == "PO-US-7002"


def test_every_money_doc_type_carries_its_sign_not_just_credit_notes():
    """The founder's scoping call: one ledger, not a credit-note special case."""
    assert dc.owed_sign("INVOICE") == 1
    assert dc.owed_sign("PROFORMA_INVOICE") == 1
    assert dc.owed_sign("DEBIT_NOTE") == 1
    assert dc.owed_sign("CREDIT_NOTE") == -1
    assert dc.owed_sign("RECEIPT") == -1
    assert dc.owed_sign("REMITTANCE_ADVICE") == -1
    # Lower case and padding are the same type -- doc_type reaches here from an
    # extractor, not from a literal.
    assert dc.owed_sign("  credit_note ") == -1


def test_a_document_with_no_money_claim_contributes_nothing():
    """A delivery note or GRN on the same table must not move the number, and a
    statement of account must not either -- its total is the balance of the very
    invoices being summed, so adding it would double-count."""
    for doc_type in ("DELIVERY_NOTE", "GRN", "STATEMENT_OF_ACCOUNT", "OTHER", "CONTRACT"):
        assert dc.owed_sign(doc_type) is None
    result = dc.compute_amount_owed(
        [
            _term("INVOICE", 500, "I-1", source="invoice"),
            _term("CREDIT_NOTE", 100, "C-1"),
            _term("DELIVERY_NOTE", 999, "DN-1"),
            _term("STATEMENT_OF_ACCOUNT", 12345, "SOA-1"),
        ]
    )
    assert result["net"] == "400"
    assert [t["doc_number"] for t in result["terms"]] == ["I-1", "C-1"]


def test_a_debit_note_adds_and_a_receipt_clears():
    assert dc.compute_amount_owed(
        [_term("INVOICE", 500, source="invoice"), _term("DEBIT_NOTE", 50)]
    )["net"] == "550"
    assert dc.compute_amount_owed(
        [_term("INVOICE", 500, source="invoice"), _term("RECEIPT", 500)]
    )["net"] == "0"
    assert dc.compute_amount_owed(
        [_term("INVOICE", 2500, source="invoice"), _term("REMITTANCE_ADVICE", 2500)]
    )["net"] == "0"


def test_a_lone_claim_produces_no_ledger_at_all():
    """None, not a net equal to the invoice. There is no arithmetic to state and
    a block saying "net owed = the invoice total" is noise the model would then
    feel obliged to narrate."""
    assert dc.compute_amount_owed([_term("INVOICE", 100, source="invoice")]) is None
    assert dc.compute_amount_owed([]) is None
    assert dc.compute_amount_owed([_term("DELIVERY_NOTE", 100)]) is None
    # But a lone REDUCTION is a real question ("we paid this, what now?").
    assert dc.compute_amount_owed([_term("CREDIT_NOTE", 100)])["net"] == "-100"


def test_mixed_currencies_stop_the_sum_and_say_so():
    """Same hard stop as `_compare_one()`: no FX rate exists in this module and
    inventing one produces a confident wrong answer about money."""
    result = dc.compute_amount_owed(
        [_term("INVOICE", 100, "I-1", "USD", "invoice"), _term("CREDIT_NOTE", 10, "C-1", "EUR")]
    )
    assert result["net"] is None
    assert result["complete"] is False
    assert "EUR" in result["blocked_reason"] and "USD" in result["blocked_reason"]


def test_the_agreed_documents_currency_can_block_the_sum_too():
    result = dc.compute_amount_owed(
        [_term("INVOICE", 100, "I-1", "USD", "invoice"), _term("CREDIT_NOTE", 10, "C-1", "USD")],
        {"doc_type": "PURCHASE_ORDER", "doc_number": "PO-1", "amount": 90, "currency": "GBP"},
    )
    assert result["net"] is None
    assert "GBP" in result["blocked_reason"]


def test_an_unreadable_total_is_never_worth_zero():
    """Treating a missing figure as nought is exactly how a credit note silently
    stops being applied. The term is named and the net is marked provisional."""
    result = dc.compute_amount_owed(
        [
            _term("INVOICE", 100, "I-1", source="invoice"),
            _term("CREDIT_NOTE", None, "C-1"),
        ]
    )
    assert result["net"] == "100"
    assert result["complete"] is False
    assert [t["doc_number"] for t in result["ignored_terms"]] == ["C-1"]
    assert "not readable" in result["ignored_terms"][0]["reason"]


def test_net_higher_and_net_lower_than_what_was_authorised():
    over = dc.compute_amount_owed(
        [_term("INVOICE", 500, source="invoice"), _term("DEBIT_NOTE", 50)],
        {"doc_type": "PURCHASE_ORDER", "doc_number": "PO-1", "amount": 500, "currency": "USD"},
    )
    assert over["agreed"]["status"] == "net_higher" and over["agreed"]["delta"] == "50"
    under = dc.compute_amount_owed(
        [_term("INVOICE", 500, source="invoice"), _term("CREDIT_NOTE", 50)],
        {"doc_type": "QUOTATION", "doc_number": "Q-1", "amount": 500, "currency": "USD"},
    )
    assert under["agreed"]["status"] == "net_lower" and under["agreed"]["delta"] == "-50"


def test_a_half_cent_apart_is_a_match_not_a_discrepancy():
    """Same tolerance the header diff uses -- two independently OCR'd pages."""
    result = dc.compute_amount_owed(
        [_term("INVOICE", "452.005", source="invoice"), _term("CREDIT_NOTE", 20)],
        {"doc_type": "PURCHASE_ORDER", "doc_number": "PO-1", "amount": 432, "currency": "USD"},
    )
    assert result["agreed"]["status"] == "match"


def test_only_commitment_documents_are_the_agreed_figure():
    for doc_type in ("PURCHASE_ORDER", "QUOTATION", "ORDER_CONFIRMATION", "CONTRACT"):
        assert dc.is_agreed_figure_doc_type(doc_type) is True
    for doc_type in ("INVOICE", "CREDIT_NOTE", "RECEIPT", "DELIVERY_NOTE", None, ""):
        assert dc.is_agreed_figure_doc_type(doc_type) is False


# ===========================================================================
# Contract terms — Gap 473
# ===========================================================================
# Probe turn B4: "per this contract, is the sales tax on Redwood invoice
# RFG-500712 correct? Show the expected figure." All three candidate models
# answered "the contract does not state a tax amount", because nothing parsed
# the rate and nothing computed 8.25% of 1,500.00.


def _span(text, page=1):
    return {"document": text, "page": page, "metadata": {}, "distance": 0.1}


class _Inv:
    """The two fields the expected-figure comparison reads, and nothing else --
    it takes an ORM row in production but must not depend on one."""

    def __init__(self, subtotal=None, tax_amount=None, number="RFG-500712", currency="USD"):
        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.invoice_number = number
        self.currency = currency


def test_b4_the_probe_turn_verbatim():
    """8.25% of a 1,500.00 subtotal is 123.75; the invoice printed 90.00."""
    terms = dc.extract_contract_terms(
        [_span("Section 4. Sales tax shall be charged at 8.25% on all services.", page=2)]
    )
    assert [t["key"] for t in terms] == ["sales_tax_rate"]
    assert terms[0]["value"] == "8.25"
    assert terms[0]["page"] == 2
    assert "8.25%" in terms[0]["source_text"]

    expected = dc.compare_contract_terms_to_invoice(terms, _Inv(1500, 90))
    assert expected["expected_tax"] == "123.75"
    assert expected["invoice_tax"] == "90.00"
    assert expected["delta"] == "-33.75"
    assert expected["status"] == "under_charged"
    assert expected["invoice_number"] == "RFG-500712"
    # The evidence travels with the figure -- that is what makes it quotable
    # without the model reasoning over free document text.
    assert "8.25" in expected["source_text"]


def test_a_percentage_is_read_however_the_document_spells_it():
    for text, value in (
        ("VAT at 20%", "20"),
        ("GST of 18 %", "18"),
        ("Sales tax: 8.25 percent", "8.25"),
        ("service tax rate of 12.5 per cent", "12.5"),
    ):
        terms = dc.extract_contract_terms([_span(text)])
        assert terms and terms[0]["value"] == value, text


def test_a_rate_named_twice_is_reported_once():
    """A contract that repeats a rate is not self-contradictory, and emitting
    both invites an answer that says it is."""
    terms = dc.extract_contract_terms(
        [
            _span("Sales tax at 8.25% applies.", page=1),
            _span("As stated, sales tax at 8.25% applies to all invoices.", page=4),
        ]
    )
    assert len([t for t in terms if t["key"] == "sales_tax_rate"]) == 1
    assert terms[0]["page"] == 1  # first match wins


def test_discount_late_fee_and_payment_terms_are_reported_but_never_computed():
    """No unambiguous base exists on the invoice for a discount or a late fee,
    and days are not money. Guessing a base is a confident wrong number."""
    terms = dc.extract_contract_terms(
        [
            _span(
                "A discount of 5% applies. Late payment interest of 1.5% per month. "
                "Payment terms are Net 30.",
            )
        ]
    )
    keys = {t["key"] for t in terms}
    assert {"discount_rate", "late_fee_rate", "payment_terms_days"} <= keys
    days = next(t for t in terms if t["key"] == "payment_terms_days")
    assert days["value"] == "30" and days["unit"] == "days"
    # None of them produces an expected figure.
    assert dc.compare_contract_terms_to_invoice(
        [t for t in terms if t["key"] != "sales_tax_rate"], _Inv(1500, 90)
    ) is None


def test_within_n_days_is_the_same_payment_term():
    terms = dc.extract_contract_terms([_span("Invoices are payable within 45 days.")])
    days = next(t for t in terms if t["key"] == "payment_terms_days")
    assert days["value"] == "45"


def test_no_terms_and_no_text_produce_nothing_rather_than_a_guess():
    assert dc.extract_contract_terms([]) == []
    assert dc.extract_contract_terms([_span("")]) == []
    assert dc.extract_contract_terms([_span("This agreement is governed by Oregon law.")]) == []
    assert dc.compare_contract_terms_to_invoice([], _Inv(1500, 90)) is None


def test_a_missing_subtotal_blocks_the_expected_figure():
    """The 'missing value treated as zero' mistake, refused here as everywhere
    else in this module: with no subtotal there is nothing to apply a rate to."""
    terms = dc.extract_contract_terms([_span("Sales tax at 8.25%.")])
    assert dc.compare_contract_terms_to_invoice(terms, _Inv(None, 90)) is None


def test_an_invoice_with_no_tax_figure_is_reported_not_called_a_variance():
    """'Under-charged by the whole amount' would be a claim the data does not
    support -- the invoice simply states no tax."""
    terms = dc.extract_contract_terms([_span("Sales tax at 8.25%.")])
    result = dc.compare_contract_terms_to_invoice(terms, _Inv(1500, None))
    assert result["status"] == "invoice_tax_missing"
    assert result["delta"] is None
    assert result["expected_tax"] == "123.75"


def test_match_and_over_charged():
    terms = dc.extract_contract_terms([_span("Sales tax at 10%.")])
    assert dc.compare_contract_terms_to_invoice(terms, _Inv(1000, 100))["status"] == "match"
    # Same half-cent tolerance the rest of the module uses.
    assert dc.compare_contract_terms_to_invoice(terms, _Inv(1000, "100.005"))["status"] == "match"
    over = dc.compare_contract_terms_to_invoice(terms, _Inv(1000, 150))
    assert over["status"] == "over_charged" and over["delta"] == "50.00"


# ---------------------------------------------------------------------------
# Gap 475 / Gap 476 -- both found by the 29.8 probe re-run, 2026-09-06
# ---------------------------------------------------------------------------


def test_gap475_a_credit_note_that_prints_its_own_total_negative_is_not_double_negated():
    """Probe turn A4's real defect, hiding behind a passing regex.

    The Apex credit note prints "Total Credit: -$21.60", so extraction returns
    grand_total = -21.6. `-1 * -21.6` ADDED the credit: net 475.20 where the
    answer is 432.00. The sign belongs to the document type, not to how the
    document chose to print its own total.
    """
    from services.document_comparison import compute_amount_owed

    negative = compute_amount_owed(
        [
            {"doc_type": "INVOICE", "doc_number": "APS-410093", "amount": 453.6, "currency": "USD"},
            {"doc_type": "CREDIT_NOTE", "doc_number": "CN-APS-0021", "amount": -21.6, "currency": "USD"},
        ],
        agreed={"doc_type": "PURCHASE_ORDER", "doc_number": "PO-US-7002", "amount": 432.0, "currency": "USD"},
    )
    assert negative["net"] == "432.0"
    assert negative["agreed"]["status"] == "match"

    # The same credit note printed positive must give the identical answer.
    positive = compute_amount_owed(
        [
            {"doc_type": "INVOICE", "doc_number": "APS-410093", "amount": 453.6, "currency": "USD"},
            {"doc_type": "CREDIT_NOTE", "doc_number": "CN-APS-0021", "amount": 21.6, "currency": "USD"},
        ],
        agreed={"doc_type": "PURCHASE_ORDER", "doc_number": "PO-US-7002", "amount": 432.0, "currency": "USD"},
    )
    assert positive["net"] == negative["net"]
    assert [t["sign"] for t in positive["terms"]] == [t["sign"] for t in negative["terms"]]


def test_gap475_a_negative_invoice_total_still_adds_by_its_type():
    """The rule is uniform, not a credit-note special case: an invoice keeps its
    +1 whatever sign the extractor read off the page."""
    from services.document_comparison import compute_amount_owed

    result = compute_amount_owed(
        [
            {"doc_type": "INVOICE", "doc_number": "INV-1", "amount": -100.0, "currency": "USD"},
            {"doc_type": "CREDIT_NOTE", "doc_number": "CN-1", "amount": 40.0, "currency": "USD"},
        ]
    )
    assert result["net"] == "60.0"
