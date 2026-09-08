"""Feature 30 task 30.15 — the insight golden bank and its harness.

The harness is graded here the way any other measurement tool in this repo is:
the BANK is checked for the composition the spec asked for, and the SCORER is
checked against hand-built blocks where the right answer is obvious. The live
narration path (`--narrate`) is deliberately not exercised — no live model call
is made from any test (hard rule 6).

The end-to-end run itself is real and is recorded in the tasklist: 20/20 cases,
21/21 figures exact, 0 fabricated figures, against Postgres with no LLM.
"""
import json
import os

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from scripts.run_insight_eval import (  # noqa: E402
    FABRICATION_TARGET,
    FIGURE_TARGET_PCT,
    grade_case,
    load_golden,
)

GOLDEN = load_golden()
CASES = GOLDEN["cases"]


# --- the bank ---------------------------------------------------------------


def test_the_bank_has_the_twenty_attachments_the_spec_asked_for():
    assert len(CASES) == 20


def test_the_document_type_mix_matches_the_spec():
    """§5 30.15: 4 PO, 3 quotation, 3 contract, 3 credit note, 2 debit note,
    2 statement, 2 remittance, 1 delivery note."""
    counts: dict = {}
    for case in CASES:
        counts[case["doc_type"]] = counts.get(case["doc_type"], 0) + 1
    assert counts == {
        "PURCHASE_ORDER": 4,
        "QUOTATION": 3,
        "CONTRACT": 3,
        "CREDIT_NOTE": 3,
        "DEBIT_NOTE": 2,
        "STATEMENT_OF_ACCOUNT": 2,
        "REMITTANCE_ADVICE": 2,
        "DELIVERY_NOTE": 1,
    }


def test_the_bank_covers_all_three_regions():
    assert {c.get("region") for c in CASES} == {"IN", "EU", "US"}


def test_every_case_is_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case id"
    for case in CASES:
        assert case["attachment"]["party_name"], case["id"]
        assert isinstance(case.get("invoices", []), list), case["id"]
        assert case.get("expected_cards"), case["id"]
        for figure, value in (case.get("expected_figures") or {}).items():
            assert isinstance(value, (int, float)), f"{case['id']}:{figure} is not a number"


def test_the_bank_contains_controls_not_only_problems():
    """A bank of nothing but findings cannot catch a card that flags everything."""
    clean = [c for c in CASES if not c.get("expected_findings")]
    assert len(clean) >= 4


def test_the_two_regression_figures_are_pinned():
    """The credit-note sign bug (Gap 475) has two known wrong answers; both are
    in `must_not_contain` so a regression fails the bank rather than passing it."""
    forbidden = {v for c in CASES for v in (c.get("must_not_contain") or [])}
    assert 144800.0 in forbidden  # 123200 + 21600 instead of minus
    assert 475.2 in forbidden  # the probe-A4 case verbatim


# --- the scorer -------------------------------------------------------------


def _case(**kw):
    base = {"id": "t", "doc_type": "PURCHASE_ORDER", "expected_cards": {}, "expected_figures": {}}
    base.update(kw)
    return base


def test_an_exact_figure_passes_and_a_near_miss_fails():
    block = {"figures": {"overbilled": 23200.0}, "cards": [], "findings": []}
    assert grade_case(_case(expected_figures={"overbilled": 23200.0}), block)["passed"]
    near = grade_case(_case(expected_figures={"overbilled": 23200.01}), block)
    assert not near["passed"]
    assert near["figures"][0]["actual"] == 23200.0


def test_a_missing_figure_fails_rather_than_being_skipped():
    result = grade_case(_case(expected_figures={"absent": 1.0}), {"figures": {}, "cards": [], "findings": []})
    assert not result["passed"]
    assert result["figures"][0]["actual"] is None


def test_a_card_status_mismatch_fails():
    block = {"figures": {}, "cards": [{"card": "agreed_vs_billed", "status": "skipped"}], "findings": []}
    assert not grade_case(_case(expected_cards={"agreed_vs_billed": "ok"}), block)["passed"]
    assert grade_case(_case(expected_cards={"agreed_vs_billed": "skipped"}), block)["passed"]


def test_a_forbidden_figure_anywhere_in_the_block_is_a_fabrication():
    """Not just in `figures` — a fabricated number in a finding title or in
    evidence is exactly as wrong."""
    block = {
        "figures": {},
        "cards": [],
        "findings": [{"title": "you were overbilled 144800.0", "finding_key": "x"}],
    }
    result = grade_case(_case(must_not_contain=[144800.0]), block)
    assert result["fabrications"] == [144800.0]
    assert not result["passed"]


def test_a_wildcard_finding_key_matches_by_prefix():
    block = {
        "figures": {},
        "cards": [],
        "findings": [{"finding_key": "bank_reconcile:duplicate:abc-123"}],
    }
    assert grade_case(_case(expected_findings=["bank_reconcile:duplicate:*"]), block)["passed"]
    assert not grade_case(_case(expected_findings=["bank_reconcile:ambiguous:*"]), block)["passed"]


def test_a_skip_reason_is_graded_on_its_wording():
    block = {
        "figures": {},
        "cards": [{"card": "quote_drift", "status": "skipped", "reason": "drift needs 2"}],
        "findings": [],
    }
    passing = _case(
        expected_cards={"quote_drift": "skipped"}, expected_skip_reasons={"quote_drift": "needs 2"}
    )
    assert grade_case(passing, block)["passed"]
    failing = _case(
        expected_cards={"quote_drift": "skipped"}, expected_skip_reasons={"quote_drift": "needs 3"}
    )
    assert not grade_case(failing, block)["passed"]


def test_the_targets_are_the_spec_numbers():
    assert FIGURE_TARGET_PCT == 90.0
    assert FABRICATION_TARGET == 0


def test_the_harness_does_not_call_a_model_unless_asked():
    """Hard rule 6, asserted on the source: `run()` narrates only under the
    explicit `--narrate` flag."""
    import inspect

    import scripts.run_insight_eval as harness

    source = inspect.getsource(harness.run)
    assert "if narrate:" in source
    assert inspect.signature(harness.run).parameters["narrate"].default is False
