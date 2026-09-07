"""Feature 29 task 29.9 — the answer contract gate and the abstain payload.

One sentence is under test: **every number in the narration must appear in the
evidence the turn was given.** A number that does not is either invented or
derived, and this product forbids both (CONVENTIONS hard rule 3).

The tests are split in two, deliberately:

  * the gate must CATCH the failure shapes that have actually happened here
    (Gap 269's false equation, spec section 2.3's "one sub-claim unsupported");
  * the gate must NOT fire on dates, ids, percentages, counts or figures that
    are in the evidence in a different rendering. A gate with false positives is
    worse than no gate, because it replaces correct answers with abstentions.

The second half is the larger half on purpose.
"""
from decimal import Decimal

import pytest

from agents import query_agent as qa


EVIDENCE = """
DATABASE RESULTS:
invoice_number | vendor_name | grand_total | currency | invoice_date | due_date
--- | --- | --- | --- | --- | ---
TSD-620458 | Titan Steel Distributors | 18450.00 | USD | 2026-07-02 | 2026-08-01
RSL-2026-0042 | Rajesh Steel | 1180.0 | INR | 2026-06-11 | 2026-07-11

COMPUTED FIGURES
- total of `grand_total` across the 2 rows above:
    USD 18,450.00
    INR 1,180.00
- line arithmetic for RSL-2026-0042: 1 line(s) checked, 1 agree, 0 do not.
"""


def _numbers():
    return qa._gate_evidence_numbers(EVIDENCE)


# ---------------------------------------------------------------------------
# It catches what has actually gone wrong
# ---------------------------------------------------------------------------


def test_a_figure_that_appears_nowhere_in_the_evidence_is_caught():
    verdict = qa._answer_contract_gate(
        "Titan Steel Distributors' invoice totals USD 18,650.00.", _numbers()
    )
    assert verdict["status"] == "unsupported"
    assert verdict["unsupported"] == [Decimal("18650.00")]


def test_gap_269s_false_equation_is_caught_as_an_unsupported_figure():
    """"5000.00 units x USD 0.08 = USD 420.00" -- the printed 420 was in the row,
    the computed 400 was not, and the model stated both."""
    evidence = qa._gate_evidence_numbers("line_qty | line_unit_price | line_amount\n5000 | 0.08 | 420.00")
    verdict = qa._answer_contract_gate(
        "Bolts: 5000.00 units x USD 0.08 = USD 420.00, so the line total is USD 400.00.",
        evidence,
    )
    assert verdict["status"] == "unsupported"
    assert Decimal("400.00") in verdict["unsupported"]


def test_a_derived_sum_across_two_currencies_is_caught():
    """The one arithmetic this product refuses outright: there is no exchange
    rate, so a combined total cannot be in any payload and must never be said."""
    verdict = qa._answer_contract_gate(
        "Across both invoices you spent 19,630.00.", _numbers()
    )
    assert verdict["status"] == "unsupported"


def test_every_offending_figure_is_named_not_just_the_first():
    verdict = qa._answer_contract_gate("Totals were 111.11 and 222.22.", _numbers())
    assert verdict["unsupported"] == [Decimal("111.11"), Decimal("222.22")]
    directive = qa._gate_regeneration_directive(verdict["unsupported"])
    assert "111.11" in directive and "222.22" in directive
    # The retry names the figures. "Be more faithful" is the instruction that has
    # already failed everywhere else in this codebase.
    assert "may not compute" in directive


# ---------------------------------------------------------------------------
# It does not fire on things that are not claims
# ---------------------------------------------------------------------------


def test_a_figure_rendered_differently_from_the_row_still_passes():
    """`18450.00` in the row, `USD 18,450.00` in the prose. Textual matching
    would abstain on a correct answer; the comparison is numeric."""
    verdict = qa._answer_contract_gate(
        "The Titan Steel invoice is USD 18,450.00 and the Rajesh Steel one is INR 1,180.",
        _numbers(),
    )
    assert verdict["status"] == "ok"


def test_dates_do_not_contribute_numbers():
    """`2026-08-01` must not become 2026, 8 and 1 -- three unsupported figures
    on an answer that only quoted a due date."""
    verdict = qa._answer_contract_gate(
        "It was dated 2026-07-02 and is due on 2026-08-01; the 11/07/2026 one is Rajesh Steel's.",
        _numbers(),
    )
    assert verdict["status"] == "ok"


def test_a_bare_year_is_not_a_figure():
    verdict = qa._answer_contract_gate("Both invoices are from 2026.", _numbers())
    assert verdict["status"] == "ok"


def test_small_counts_and_ordinals_are_not_figures():
    """"the 2 invoices", "the first 3 lines" -- a count is derived from the rows
    themselves, which the model is allowed to do. Requiring every count to be
    pre-computed would make ordinary sentences ungrammatical."""
    verdict = qa._answer_contract_gate(
        "There are 2 invoices; the 3 line items on the second one all reconcile.", _numbers()
    )
    assert verdict["status"] == "ok"


def test_an_invoice_number_is_not_read_as_a_figure():
    """`TSD-620458` and `RSL-2026-0042` are identifiers. They are in the
    evidence anyway, but the point is that the tokeniser does not split them into
    620458 / 2026 / 42 and demand each be justified."""
    verdict = qa._answer_contract_gate(
        "Invoice TSD-620458 from Titan Steel and RSL-2026-0042 from Rajesh Steel.", _numbers()
    )
    assert verdict["status"] == "ok"


def test_a_percentage_that_is_in_the_evidence_passes():
    evidence = qa._gate_evidence_numbers("tax_rate | 18.00\ncontract rate 8.25%")
    verdict = qa._answer_contract_gate(
        "The contract rate is 8.25% and the invoice charged 18.00%.", evidence
    )
    assert verdict["status"] == "ok"


def test_an_answer_with_no_numbers_at_all_passes_trivially():
    verdict = qa._answer_contract_gate(
        "Payment status is not tracked in this system, so I cannot say whether it was paid.",
        _numbers(),
    )
    assert verdict["status"] == "ok" and verdict["checked"] == 0


def test_the_gate_never_raises_on_junk():
    for junk in (None, "", "   ", "— – %%%"):
        assert qa._answer_contract_gate(junk, set())["status"] == "ok"


# ---------------------------------------------------------------------------
# The abstention — decision 3 (founder, 2026-09-06)
# ---------------------------------------------------------------------------


def test_the_abstention_names_the_gap_what_is_on_file_and_a_next_step():
    """All three clauses are required. An abstention that only says "I don't
    know" hides that the system holds most of what was asked for."""
    payload = qa._abstain_payload(
        missing=["whether TSD-620458 has been paid"],
        on_file=["TSD-620458, USD 18,450.00, due 2026-08-01, processing status COMPLETED"],
        next_step="show you its due date and processing status instead",
    )
    assert payload["status"] == "insufficient_evidence"
    assert payload["missing"] == ["whether TSD-620458 has been paid"]
    assert payload["on_file"]
    assert payload["next_step"]
    message = payload["message"]
    assert message.startswith("I can't confirm whether TSD-620458 has been paid")
    assert "USD 18,450.00" in message
    assert message.rstrip().endswith("?")


def test_an_abstention_with_nothing_on_file_says_so_rather_than_going_quiet():
    payload = qa._abstain_payload(missing=["any invoice from Nonexistent Holdings"])
    assert "no record on file" in payload["message"]
    # There is still a next step, always.
    assert payload["next_step"]
    assert payload["message"].rstrip().endswith("?")


def test_on_file_is_built_from_the_records_the_turn_actually_had():
    from services import full_records

    record_set = full_records.FullRecordSet(
        records=[
            full_records.FullRecord(
                invoice_id="1", record={"invoice_number": "TSD-620458", "vendor_name": "Titan Steel"}
            )
        ]
    )
    on_file = qa._abstain_on_file_from(["1"], record_set)
    assert on_file == ["TSD-620458 (Titan Steel)"]
    # No records: it still says something true rather than nothing.
    assert qa._abstain_on_file_from(["1", "2"], None) == [
        "2 matching invoice row(s) from this question's query"
    ]
    assert qa._abstain_on_file_from([], None) == []


def test_no_uuid_ever_reaches_an_abstention(monkeypatch):
    """Gap 294's rule holds on this path too: the identifier a user recognises is
    the invoice number, never the surrogate key."""
    from services import full_records

    record_set = full_records.FullRecordSet(
        records=[
            full_records.FullRecord(
                invoice_id="11111111-1111-1111-1111-111111111111",
                record={"invoice_number": "TSD-620458"},
            )
        ]
    )
    payload = qa._abstain_payload(
        missing=["the figure 18,650.00"], on_file=qa._abstain_on_file_from([], record_set)
    )
    assert "11111111" not in payload["message"]


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


def test_the_gate_can_be_turned_off_without_a_deploy(monkeypatch):
    """A gate with false positives suppresses correct answers. If that is ever
    observed live this is the switch -- and the observation gets a Gap entry."""
    from config import get_settings

    assert get_settings().ENABLE_ANSWER_CONTRACT_GATE is True
    assert qa._answer_gate_enabled() is True

    monkeypatch.setattr(get_settings(), "ENABLE_ANSWER_CONTRACT_GATE", False)
    assert qa._answer_gate_enabled() is False


def test_the_turn_trace_carries_the_gate_outcome():
    """"How often does the gate fire?" has to be answerable from telemetry, or
    the control is unmeasurable."""
    import telemetry

    trace = telemetry.ChatTurn(session_id="s", tenant_id="t")
    assert trace.answer_gate == ""
    trace.answer_gate = "abstained"
    assert trace.event_fields()["answer_gate"] == "abstained"
