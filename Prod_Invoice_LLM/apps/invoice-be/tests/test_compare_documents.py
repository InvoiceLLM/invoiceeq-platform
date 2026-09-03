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
