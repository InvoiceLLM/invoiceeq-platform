"""Feature 26 Phase 5 — tolerances, kept comparisons, date arithmetic.

Gaps 447 (MatchPolicy), 448 (DocumentComparison), 449 (date_math).

The through-line: a comparison is a financial control, so it needs a band the
tenant chose, a record that outlives the conversation, and arithmetic that was
actually performed rather than recalled.
"""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import DocumentComparison, MatchPolicy

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)

TENANT = uuid4()


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _doc(*lines):
    return {"items": list(lines)}


def _line(**kw):
    base = {"description": "Catalysts", "quantity": 100, "unit_price": 10, "amount": 1000}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Gap 447 — the tenant's tolerance band
# ---------------------------------------------------------------------------
def test_gap_447_a_tenant_with_no_policy_gets_the_zero_band(db_session):
    """The zero band is the product's behaviour before this table existed, and
    it is the right default: a tolerance is permission to ignore a real
    difference, and nobody should be granted that by omission."""
    from services.document_comparison import get_match_policy

    policy = get_match_policy(TENANT, db_session)
    assert policy == {
        "quantity_tolerance_percent": 0.0,
        "price_tolerance_percent": 0.0,
        "date_tolerance_days": 0,
    }


def test_gap_447_a_delta_inside_the_band_is_not_a_discrepancy(db_session):
    from services.document_comparison import compare_documents

    policy = {"quantity_tolerance_percent": 2.0, "price_tolerance_percent": 0.0}
    # 100 ordered, 101 delivered: 1%, inside a 2% band.
    result = compare_documents(
        _doc(_line(quantity=100)), _doc(_line(quantity=101)), mode="quantity", policy=policy
    )
    row = result["line_items"][0]

    assert row["status"] == "match"
    assert row["quantity_within_tolerance"] is True
    assert row["quantity_delta"] == "1", "the figure is still reported, not swallowed"


def test_gap_447_a_delta_outside_the_band_is_still_a_discrepancy(db_session):
    from services.document_comparison import compare_documents

    policy = {"quantity_tolerance_percent": 2.0}
    result = compare_documents(
        _doc(_line(quantity=100)), _doc(_line(quantity=110)), mode="quantity", policy=policy
    )
    row = result["line_items"][0]

    assert row["status"] == "quantity_delta"
    assert "quantity_within_tolerance" not in row


def test_gap_447_the_band_that_was_applied_is_stated_in_the_output(db_session):
    """An unstated assumption about which arithmetic produced a figure is the
    silent wrongness this feature exists to remove (Feature 27 A6's rule)."""
    from services.document_comparison import compare_documents

    result = compare_documents(
        _doc(_line()), _doc(_line()), policy={"quantity_tolerance_percent": 2.0}
    )
    assert any("Tolerances applied" in a for a in result["assumptions"])
    assert result["policy"]["quantity_tolerance_percent"] == 2.0


def test_gap_447_an_unanswerable_tolerance_question_reports_the_variance(db_session):
    """Fail-closed. A zero reference, a missing side or no band must never be
    read as "within tolerance"."""
    from services.document_comparison import _within_tolerance

    assert _within_tolerance(0, 5, 10) is False, "any delta from zero is infinite in percent"
    assert _within_tolerance(100, None, 10) is False
    assert _within_tolerance(100, 101, None) is False
    assert _within_tolerance(100, 101, 0) is False
    assert _within_tolerance(100, 101, 2) is True


def test_gap_447_the_policy_row_round_trips(db_session):
    from services.document_comparison import get_match_policy

    db_session.add(
        MatchPolicy(
            tenant_id=TENANT,
            quantity_tolerance_percent=2.5,
            price_tolerance_percent=1.0,
            date_tolerance_days=7,
        )
    )
    db_session.commit()

    assert get_match_policy(TENANT, db_session) == {
        "quantity_tolerance_percent": 2.5,
        "price_tolerance_percent": 1.0,
        "date_tolerance_days": 7,
    }


# ---------------------------------------------------------------------------
# Gap 448 — the comparison is kept
# ---------------------------------------------------------------------------
def test_gap_448_a_comparison_is_written_as_a_record(db_session):
    """A finding that exists only in chat scrollback is not a control."""
    from services.document_comparison import record_comparison

    invoice_id, attachment_id = uuid4(), uuid4()
    record_comparison(
        db_session=db_session,
        tenant_id=TENANT,
        kind="attachment_vs_invoice",
        invoice_id=invoice_id,
        attachment_id=attachment_id,
        doc_type="PURCHASE_ORDER",
        mode="both",
        outcome="variance",
        payload={"header": {"outcome": "variance"}, "lines": {"line_items": []}},
    )

    row = db_session.exec(select(DocumentComparison)).first()
    assert row.tenant_id == TENANT
    assert row.invoice_id == invoice_id
    assert row.outcome == "variance"
    assert row.payload["header"]["outcome"] == "variance"


def test_gap_448_a_failed_write_does_not_raise(db_session):
    """The user already has a correct answer by the time this runs. Failing the
    turn to protect an audit row trades the thing they asked for against the
    thing we wanted."""
    from unittest.mock import MagicMock

    from services.document_comparison import record_comparison

    broken = MagicMock()
    broken.commit.side_effect = RuntimeError("db down")
    assert record_comparison(
        db_session=broken, tenant_id=TENANT, kind="attachment_vs_invoice", payload={}
    ) is None


# ---------------------------------------------------------------------------
# Gap 449 — date arithmetic performed, not recalled
# ---------------------------------------------------------------------------
def test_gap_449_days_between_is_signed_and_states_its_inputs():
    from agents.query_tools import date_math

    result = date_math("days_between", start="2026-03-01", end="2026-06-14")
    assert result["status"] == "ok"
    assert result["days"] == 105
    assert result["start"] == "2026-03-01" and result["end"] == "2026-06-14"

    backwards = date_math("days_between", start="2026-06-14", end="2026-03-01")
    assert backwards["days"] == -105, "a negative interval is information, not an error"


def test_gap_449_a_ninety_day_validity_window_answers_s22():
    """The benchmark scenario this tool exists for: a contract dated 1 March with
    90-day price validity, against an invoice dated 14 June."""
    from agents.query_tools import date_math

    result = date_math("within_window", start="2026-03-01", end="2026-06-14", days=90)
    assert result["within"] is False
    assert result["window_end"] == "2026-05-30", "the window it used is stated, not implied"
    assert result["days_outside"] == 15


def test_gap_449_a_date_inside_the_window_is_reported_as_inside():
    from agents.query_tools import date_math

    result = date_math("within_window", start="2026-03-01", end="2026-04-10", days=90)
    assert result["within"] is True
    assert result["days_outside"] == 0


def test_gap_449_add_days_accepts_the_shapes_the_product_actually_stores():
    from agents.query_tools import date_math

    assert date_math("add_days", start=date(2026, 3, 1), days=45)["result"] == "2026-04-15"
    assert date_math("add_days", start="2026-03-01T00:00:00", days=45)["result"] == "2026-04-15"


@pytest.mark.parametrize(
    "call",
    [
        {"operation": "days_between", "start": "not a date", "end": "2026-06-14"},
        {"operation": "days_between", "start": "2026-03-01"},
        {"operation": "add_days", "start": "2026-03-01"},
        {"operation": "within_window", "start": "2026-03-01", "end": "2026-06-14"},
        {"operation": "nonsense", "start": "2026-03-01"},
    ],
)
def test_gap_449_an_unanswerable_date_question_errors_rather_than_guesses(call):
    """The whole reason this is a function: a model asked the same question
    produces a confident date. This returns "I could not"."""
    from agents.query_tools import date_math

    assert date_math(**call)["status"] == "error"


def test_gap_449_the_content_branch_computes_dates_only_when_asked_to():
    """A date block on a question that is not about dates would put a computed
    figure in front of the model for no reason."""
    from types import SimpleNamespace

    from agents.query_agent import _attachment_date_block

    attachment = SimpleNamespace(
        extracted_json={"doc_date": "2026-03-01", "valid_until": "2026-05-30"},
        doc_date=date(2026, 3, 1),
    )
    assert _attachment_date_block("who signed this?", attachment) == ""

    block = _attachment_date_block("is this still valid?", attachment)
    assert "2026-05-30" in block and "90 days" in block


def test_gap_449_a_validity_duration_beats_a_payment_term_of_the_same_shape():
    """"Net 45 days" and "valid for 90 days" both read as "N days". Taking
    whichever appears first answered a price-validity question with the payment
    term -- seen on the benchmark's contract before this rule."""
    from types import SimpleNamespace

    from agents.query_agent import _attachment_date_block

    attachment = SimpleNamespace(extracted_json={"doc_date": "2026-03-01"}, doc_date=None)
    spans = [
        {"document": "Payment terms: Net 45 days from invoice date."},
        {"document": "Pricing: unit prices are valid for 90 days from the agreement date."},
    ]

    block = _attachment_date_block(
        "Is the invoice dated 2026-06-14 within the price validity window?", attachment, spans
    )
    assert "90-day window" in block and "2026-05-30" in block
    assert "45-day" not in block
    assert "OUTSIDE" in block and "15 days" in block


def test_gap_449_no_dates_on_the_document_means_no_computed_block():
    from types import SimpleNamespace

    from agents.query_agent import _attachment_date_block

    attachment = SimpleNamespace(extracted_json={}, doc_date=None)
    assert _attachment_date_block("is this still valid?", attachment) == ""
