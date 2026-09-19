"""BE Gap 696 -- the answer contract gate's three fixes.

These are pure-function tests on the gate itself; the route-level behaviour
(widened evidence, flag-instead-of-abstain) is exercised by the eval harness,
which is where a prompt change can actually be measured.
"""

from decimal import Decimal

from agents.query_agent import (
    _answer_contract_gate,
    _gate_evidence_numbers,
    _gate_normalise_expression,
    _gate_supported_derivations,
    _gate_unverified_notice,
)


def _d(*values):
    return {Decimal(str(v)) for v in values}


# --- part 2: shown working ------------------------------------------------


def test_a_shown_sum_of_evidence_figures_is_supported():
    """The case that regressed live: a correct total, binned for being correct."""
    assert _gate_supported_derivations(
        "The two invoices come to 12,000 (5,000 + 7,000).", _d(5000, 7000)
    ) == _d(12000)


def test_a_shown_sum_that_does_not_add_up_is_not_supported():
    """The case the old gate could not catch at all: correct-looking, wrong."""
    assert _gate_supported_derivations(
        "The two invoices come to 13,000 (5,000 + 7,000).", _d(5000, 7000)
    ) == set()


def test_an_input_not_in_the_evidence_is_refused_even_when_the_maths_is_right():
    """Arithmetic is not a laundering channel for a number nobody supplied."""
    assert _gate_supported_derivations(
        "Total 12,000 (5,000 + 7,000).", _d(5000)
    ) == set()


def test_multiplication_of_a_quantity_by_a_unit_price():
    assert _gate_supported_derivations(
        "Training & Onboarding: 29,302.80 (40 x 732.57)", _d(40, 732.57)
    ) == _d("29302.80")


def test_a_percentage_of_a_base():
    assert _gate_supported_derivations(
        "Tax is 1,800 (18% of 10,000).", _d(18, 10000)
    ) == _d(1800)


def test_a_division_for_an_average():
    assert _gate_supported_derivations(
        "That averages 4,000 (12,000 / 3).", _d(12000)
    ) == _d(4000)


def test_rounding_tolerance_allows_a_conversion_carried_to_more_decimals():
    """A converted figure printed to 2dp must not fail on the 3rd."""
    assert _gate_supported_derivations(
        "About 10,830.00 (10,000 x 1.083).", _d(10000, "1.083")
    ) == _d("10830.00")


def test_an_ordinary_parenthetical_is_not_read_as_arithmetic():
    """"Acme Corp (the vendor)" must cost nothing and support nothing."""
    assert _gate_supported_derivations(
        "Invoice 5,000 from Acme Corp (the vendor of record).", _d(5000)
    ) == set()


def test_an_equation_is_read_on_its_left_side_only():
    """A model that writes the whole equation must still be checked, not
    handed its own restatement of the answer to compare against itself."""
    assert _gate_supported_derivations(
        "Total 12,000 (5,000 + 7,000 = 12,000).", _d(5000, 7000)
    ) == _d(12000)
    assert _gate_supported_derivations(
        "Total 12,000 (5,000 + 6,000 = 12,000).", _d(5000, 6000)
    ) == set()


def test_no_function_call_or_name_is_ever_evaluated():
    """The expression parser is a whitelist, not an `eval()`."""
    for hostile in (
        "Total 12,000 (__import__('os').system('echo') + 12000)",
        "Total 12,000 (open + 12000)",
        "Total 12,000 (2 ** 40)",
    ):
        assert _gate_supported_derivations(hostile, _d(12000, 2, 40)) == set()


def test_the_normaliser_rewrites_finance_notation_but_not_arbitrary_words():
    assert _gate_normalise_expression("USD 5,000 + $7,000") == "5000 +  7000"
    assert "*" in _gate_normalise_expression("40 × 732.57")
    assert "/100" in _gate_normalise_expression("18% of 10,000")


# --- the gate as a whole --------------------------------------------------


def test_the_gate_passes_an_answer_whose_working_checks_out():
    verdict = _answer_contract_gate(
        "Two invoices totalling 12,000 (5,000 + 7,000).",
        _gate_evidence_numbers("5,000 and 7,000"),
    )
    assert verdict["status"] == "ok", verdict


def test_the_gate_still_fails_a_figure_with_no_working_and_no_source():
    """The fabrication guard is untouched -- this is the whole point of the gate."""
    verdict = _answer_contract_gate(
        "The total is 99,999.", _gate_evidence_numbers("5,000 and 7,000")
    )
    assert verdict["status"] == "unsupported"
    assert Decimal("99999") in verdict["unsupported"]


def test_a_figure_the_user_supplied_is_supported_once_the_question_is_evidence():
    """BE Gap 696 part 1, at the level this test can reach: the gate is only as
    good as what the caller passes it, so the caller passing the question is
    what fixes "why is invoice X 20,000?" being answered and then binned."""
    evidence = _gate_evidence_numbers("no rows", "why is invoice X 20,000?")
    verdict = _answer_contract_gate("Invoice X is 20,000.", evidence)
    assert verdict["status"] == "ok", verdict


# --- part 3: the flag replaces the refusal --------------------------------


def test_the_unverified_notice_names_the_figure_and_keeps_its_spelling():
    notice = _gate_unverified_notice(["99,999"])
    assert "99,999" in notice
    assert "this value" in notice


def test_the_unverified_notice_is_empty_when_there_is_nothing_to_name():
    assert _gate_unverified_notice([]) == ""
    assert _gate_unverified_notice(["", "  "]) == ""


def test_the_unverified_notice_reads_as_plural_for_several_figures():
    notice = _gate_unverified_notice(["99,999", "2026-03-15"])
    assert "these values" in notice
    assert "2026-03-15" in notice
