"""Feature 29 tasks 29.2 (judge calibration) and 29.3 (failure taxonomy).

Both are pure functions over recorded turns and recorded verdicts: no model is
called, nothing touches the database. That is the point of testing them here
rather than through a run — a gate that costs a paid eval run to check is a gate
nobody checks.

The kappa figures below are hand-computed from the 2x2 tables in the docstrings,
so a refactor that changes the arithmetic fails here rather than silently
reporting a friendlier number.
"""
import json

import pytest

from scripts.run_agent_eval import (
    FAILURE_BUCKETS,
    KAPPA_GATE,
    calibration_report,
    classify_failure,
    cohens_kappa,
    taxonomy_report,
)


# ---------------------------------------------------------------------------
# 29.2 — Cohen's kappa
# ---------------------------------------------------------------------------


def test_perfect_agreement_on_a_mixed_set_is_kappa_one():
    pairs = [(True, True)] * 10 + [(False, False)] * 10
    result = cohens_kappa(pairs)
    assert result["kappa"] == 1.0
    assert result["n"] == 20
    assert result["agreement"] == 1.0


def test_kappa_is_undefined_not_zero_when_both_raters_labelled_everything_the_same():
    """The trap this metric exists to avoid, in its purest form. Two raters who
    both passed all 20 turns agree completely, but expected agreement is also
    1.0, so kappa is 0/0. Reporting 0.0 there would read as 'no agreement' —
    the opposite of the truth — so it reports None and says so."""
    result = cohens_kappa([(True, True)] * 20)
    assert result["kappa"] is None
    assert result["agreement"] == 1.0


def test_raw_agreement_flatters_an_unbalanced_set_and_kappa_does_not():
    """A judge that fails almost everything on a set that is almost all failures
    scores high raw agreement and near-zero kappa. This is exactly the shape the
    golden set has (22–28% pass), which is why the gate is on kappa."""
    #        judge  human
    pairs = [(False, False)] * 17 + [(False, True)] * 2 + [(True, True)] * 1
    result = cohens_kappa(pairs)
    assert result["agreement"] == 0.9
    assert result["kappa"] is not None and result["kappa"] < 0.5


def test_the_two_by_two_table_names_the_direction_of_each_disagreement():
    """A kappa without its marginals cannot be argued with, and the two kinds of
    disagreement need different fixes: a judge that passes what a human fails is
    a lenient grader, the reverse is a strict one."""
    result = cohens_kappa([(True, False)] * 3 + [(False, True)] * 5 + [(True, True)] * 2)
    assert result["table"]["judge_pass_human_fail"] == 3
    assert result["table"]["human_pass_judge_fail"] == 5
    assert result["table"]["both_pass"] == 2
    assert result["n"] == 10


def test_an_empty_set_reports_no_kappa_rather_than_a_number():
    result = cohens_kappa([])
    assert result["kappa"] is None and result["n"] == 0


def test_calibration_report_scores_only_entries_with_both_verdicts(tmp_path):
    calibration = {
        "source_run": "runs/f29-golden-20260906/agent_eval_output.json",
        "judge_model": "gpt-5-mini",
        "provisional": True,
        "entries": [
            {"case_id": "a", "judge_verdict": True, "human_verdict": True, "grader": "expected-text (founder to confirm)"},
            {"case_id": "b", "judge_verdict": False, "human_verdict": False, "grader": "expected-text (founder to confirm)"},
            {"case_id": "c", "judge_verdict": False, "human_verdict": True, "grader": "expected-text (founder to confirm)", "human_note": "answer is right; judge marked one sub-claim unsupported"},
            # Not yet graded — must be excluded, not counted as a disagreement.
            {"case_id": "d", "judge_verdict": True, "human_verdict": None},
        ],
    }
    report = calibration_report(calibration)

    assert report["entries"] == 4
    assert report["scored"] == 3
    assert report["rater_count"] == 1
    assert report["provisional"] is True
    assert report["gate"] == KAPPA_GATE
    assert [d["case_id"] for d in report["disagreements"]] == ["c"]
    assert report["disagreements"][0]["human_note"]


def test_the_gate_is_zero_point_six_and_a_low_kappa_fails_it():
    low = calibration_report(
        {
            "entries": [
                {"case_id": f"c{i}", "judge_verdict": False, "human_verdict": i < 2, "grader": "x"}
                for i in range(20)
            ]
        }
    )
    assert low["passes_gate"] is False

    high = calibration_report(
        {
            "entries": (
                [{"case_id": f"p{i}", "judge_verdict": True, "human_verdict": True, "grader": "x"} for i in range(10)]
                + [{"case_id": f"f{i}", "judge_verdict": False, "human_verdict": False, "grader": "x"} for i in range(10)]
            )
        }
    )
    assert high["kappa"] == 1.0 and high["passes_gate"] is True


def test_the_shipped_calibration_file_is_well_formed_and_declares_itself_provisional():
    """The file the founder is asked to confirm. Its honesty markers are part of
    the deliverable: a kappa presented as hand-graded when it was not would be
    worse than no kappa at all."""
    from pathlib import Path

    path = Path(__file__).with_name("golden_calibration.json")
    if not path.exists():
        pytest.skip("golden_calibration.json has not been generated yet")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["provisional"] is True
    assert data["source_run"]
    assert data["judge_model"]
    assert len(data["entries"]) >= 30, "decision 4 requires at least 30 turns now"
    for entry in data["entries"]:
        assert entry["grader"] == "expected-text (founder to confirm)"
        assert entry["human_verdict"] in (True, False)
        assert entry["judge_verdict"] in (True, False)
        assert entry["case_id"] and entry["question"]
        # The reference the verdict was taken against has to be in the file, or
        # the founder cannot check the verdict without opening two other files.
        assert entry["expected_answer"] is not None
        assert entry["human_note"]


# ---------------------------------------------------------------------------
# 29.3 — failure taxonomy
# ---------------------------------------------------------------------------


class _Case:
    def __init__(self, expected_invoice_numbers=None):
        self.expected_invoice_numbers = expected_invoice_numbers


def _turn(**kwargs):
    base = {
        "case_id": "c",
        "passed": False,
        "error": None,
        "context": "DATABASE RESULTS:\nid | total\n--- | ---\n1 | 10",
        "executed_queries": ["SELECT 1"],
        "citations": [],
        "generated_sql": "SELECT 1",
        "fetched_invoice_numbers": [],
        "accuracy_score": 0.4,
        "faithfulness_score": 0.9,
        "context_score": None,
    }
    base.update(kwargs)
    return base


def test_a_turn_that_errored_is_no_route():
    assert classify_failure(_turn(error="Timeout"), _Case()) == "no_route"


def test_a_turn_that_ran_no_query_and_cited_nothing_is_no_route():
    """Spec section 2.3's worst shape: nine of 36 turns answered 'the invoice is
    not in the provided context' having never run a query or fetched a chunk."""
    assert (
        classify_failure(
            _turn(executed_queries=[], citations=[], generated_sql=None, context=""), _Case()
        )
        == "no_route"
    )


def test_a_route_that_ran_and_produced_nothing_to_read_is_no_evidence():
    assert classify_failure(_turn(context="   "), _Case()) == "no_evidence"


def test_fetching_the_wrong_invoice_is_wrong_evidence_even_when_the_prose_is_faithful():
    turn = _turn(fetched_invoice_numbers=["INV-2"], faithfulness_score=1.0, accuracy_score=0.2)
    assert classify_failure(turn, _Case(expected_invoice_numbers=("INV-1",))) == "wrong_evidence"


def test_an_empty_expected_set_is_a_real_expectation_and_is_respected():
    """`()` means the correct retrieval is *nothing* — a vendor that does not
    exist. Fetching something is then wrong evidence; fetching nothing is not."""
    empty = _Case(expected_invoice_numbers=())
    assert classify_failure(_turn(fetched_invoice_numbers=["INV-9"]), empty) == "wrong_evidence"
    assert classify_failure(_turn(fetched_invoice_numbers=[]), empty) != "wrong_evidence"


def test_a_high_accuracy_failure_is_attributed_to_the_judge_not_to_the_pipeline():
    """Section 2.5 measured pass flips of 5.6–27.8% between judges. When the
    accuracy judge is nearly satisfied and the turn still failed, blaming the
    pipeline is a guess."""
    turn = _turn(accuracy_score=0.9, faithfulness_score=0.5)
    assert classify_failure(turn, _Case()) == "judge"


def test_prose_beyond_the_evidence_is_narration():
    turn = _turn(accuracy_score=0.3, faithfulness_score=0.4)
    assert classify_failure(turn, _Case()) == "narration"


def test_right_evidence_faithful_prose_wrong_figure_is_no_computation():
    """The residual bucket, and the one task 29.6 exists to empty: the line-sum
    checks and per-line GST questions the model is forbidden to compute."""
    turn = _turn(
        accuracy_score=0.3,
        faithfulness_score=1.0,
        fetched_invoice_numbers=["INV-1"],
    )
    assert classify_failure(turn, _Case(expected_invoice_numbers=("INV-1",))) == "no_computation"


def test_every_bucket_is_reachable_and_counts_sum_to_the_failure_count():
    """The property that makes a taxonomy a decomposition rather than a set of
    labels: every failed turn gets exactly one bucket, and nothing else does."""
    turns = [
        _turn(case_id="passed_one", passed=True),
        _turn(case_id="err", error="boom"),
        _turn(case_id="noev", context=""),
        _turn(case_id="wrong", fetched_invoice_numbers=["X"]),
        _turn(case_id="judge", accuracy_score=0.95),
        _turn(case_id="narr", accuracy_score=0.2, faithfulness_score=0.1),
        _turn(case_id="comp", accuracy_score=0.2, faithfulness_score=1.0),
    ]
    cases = {
        "wrong": _Case(expected_invoice_numbers=("INV-1",)),
    }
    report = taxonomy_report(turns, cases)

    assert report["failures"] == 6
    assert sum(report["counts"].values()) == 6
    assert set(report["counts"]) == set(FAILURE_BUCKETS)
    assert [line["case_id"] for line in report["lines"]] == [
        "err", "noev", "wrong", "judge", "narr", "comp",
    ]
    assert "passed_one" not in [line["case_id"] for line in report["lines"]]
