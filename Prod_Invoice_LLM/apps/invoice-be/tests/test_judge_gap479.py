"""Gap 479 (2026-09-07): the judge grades a checklist, accuracy is the verdict,
and the harness grades against the app's own evidence (Gap 478).

Background, so the assertions read as decisions and not as taste: on the
2026-09-06 calibration set the judge failed 20 of the 28 answers a reader marks
correct and passed none it would fail (kappa 0.151). Fourteen died on a 0.5
accuracy for a missing bonus fact; fourteen on a faithfulness judged against
evidence that lacked the figures the app had computed.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import services.agent_eval as ae
from services.agent_eval import (
    ACCURACY_FLOOR,
    EvalScores,
    FactChecklistVerdict,
    FactVerdict,
    decide_pass,
    score_accuracy,
)


# ---------------------------------------------------------------------------
# The checklist accuracy judge
# ---------------------------------------------------------------------------


def _judge_returning(verdict):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = verdict
    return llm


def test_every_required_fact_met_and_nothing_forbidden_scores_one():
    llm = _judge_returning(
        FactChecklistVerdict(
            required=[FactVerdict(fact="a", met=True), FactVerdict(fact="b", met=True)],
            forbidden=[FactVerdict(fact="x", met=False)],
        )
    )
    score, notes, calls = score_accuracy(
        "q", "prose reference", "ans", llm, required_facts=("a", "b"), forbidden=("x",)
    )
    assert score == 1.0 and calls == 1
    assert notes[0].startswith("accuracy: 1.00 (2/2 required facts met)")


def test_a_missing_bonus_fact_is_not_in_the_checklist_so_cannot_cost_half_a_point():
    """The defect this gap exists for: the exact vendor and invoice, scored 0.5
    under the old prompt for lacking the reference's "Bonus, not required" note.
    With a two-item checklist and both met, it is 1.0 -- the bonus lives in
    `notes`, which the judge never sees."""
    llm = _judge_returning(
        FactChecklistVerdict(
            required=[
                FactVerdict(fact="Names Konkan Exports Pvt Ltd.", met=True),
                FactVerdict(fact="Names invoice KE-2026-0089.", met=True),
            ],
            forbidden=[
                FactVerdict(fact="Names any other vendor.", met=False),
                FactVerdict(fact="Reports that no invoice mentions reverse charge.", met=False),
            ],
        )
    )
    score, _, _ = score_accuracy(
        "Which vendor billed us under RCM?",
        "long prose with a bonus",
        "Konkan Exports Pvt Ltd, KE-2026-0089.",
        llm,
        required_facts=("Names Konkan Exports Pvt Ltd.", "Names invoice KE-2026-0089."),
        forbidden=("Names any other vendor.", "Reports that no invoice mentions reverse charge."),
    )
    assert score == 1.0
    # And the prose reference was NOT shown to the judge on this path.
    prompt = llm.with_structured_output.return_value.invoke.call_args.args[0]
    assert "long prose with a bonus" not in prompt
    assert "REQUIRED FACTS" in prompt and "FORBIDDEN ASSERTIONS" in prompt


def test_score_is_the_fraction_of_facts_met():
    llm = _judge_returning(
        FactChecklistVerdict(
            required=[
                FactVerdict(fact="a", met=True),
                FactVerdict(fact="b", met=False),
                FactVerdict(fact="c", met=True),
            ]
        )
    )
    score, notes, _ = score_accuracy("q", None, "ans", llm, required_facts=("a", "b", "c"))
    assert score == pytest.approx(2 / 3)
    assert any(n.startswith("missing: b") for n in notes)


def test_a_forbidden_assertion_zeroes_the_score_whatever_else_was_right():
    llm = _judge_returning(
        FactChecklistVerdict(
            required=[FactVerdict(fact="States the CGST as INR 9,000.00.", met=True)],
            forbidden=[FactVerdict(fact="Claims no per-component breakdown is stored.", met=True)],
        )
    )
    score, notes, _ = score_accuracy(
        "q",
        None,
        "ans",
        llm,
        required_facts=("States the CGST as INR 9,000.00.",),
        forbidden=("Claims no per-component breakdown is stored.",),
    )
    assert score == 0.0
    assert any(n.startswith("forbidden:") for n in notes)


def test_a_short_verdict_list_counts_the_missing_lines_as_not_met():
    """A judge that returns fewer verdicts than facts must not go green."""
    llm = _judge_returning(FactChecklistVerdict(required=[FactVerdict(fact="a", met=True)]))
    score, _, _ = score_accuracy("q", None, "ans", llm, required_facts=("a", "b"))
    assert score == 0.5


def test_no_checklist_falls_back_to_the_prose_reference_path():
    """A case the facts file does not know is still graded, on the old prompt."""
    llm = _judge_returning(ae.ScoreWithReason(score=1.0, reason="matches"))
    score, _, _ = score_accuracy("q", "prose reference", "ans", llm)
    assert score == 1.0
    prompt = llm.with_structured_output.return_value.invoke.call_args.args[0]
    assert "REFERENCE ANSWER" in prompt


def test_a_judge_failure_is_not_scored_rather_than_zero():
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = RuntimeError("judge down")
    score, notes, calls = score_accuracy("q", None, "ans", llm, required_facts=("a",))
    assert score is None and calls == 1
    assert "not scored" in notes[0]


# ---------------------------------------------------------------------------
# The pass rule
# ---------------------------------------------------------------------------


def test_accuracy_is_the_verdict_when_scored():
    assert decide_pass(
        EvalScores(accuracy_score=ACCURACY_FLOOR, faithfulness_score=0.5, relevance_score=0.2)
    ) is True
    assert decide_pass(EvalScores(accuracy_score=0.5, faithfulness_score=1.0, relevance_score=1.0)) is False


def test_zero_faithfulness_still_fails_a_right_by_accident_answer():
    """Every claim absent from ALL evidence is fabrication, and an answer that
    happens to match the reference must not pass on it."""
    assert decide_pass(EvalScores(accuracy_score=1.0, faithfulness_score=0.0)) is False


def test_without_a_reference_the_old_floors_still_apply():
    assert decide_pass(EvalScores(faithfulness_score=0.9, relevance_score=0.8)) is True
    assert decide_pass(EvalScores(faithfulness_score=0.5, relevance_score=0.8)) is False
    assert decide_pass(EvalScores()) is False


# ---------------------------------------------------------------------------
# The golden facts file
# ---------------------------------------------------------------------------


def test_every_golden_case_with_a_reference_has_a_checklist():
    from benchmarks.agent_eval_golden_sample import CASES

    for case in CASES:
        if case.expected_answer:
            assert case.required_facts, f"{case.case_id} has a prose reference but no required_facts"
        assert all(isinstance(f, str) and f.strip() for f in case.required_facts), case.case_id
        assert all(isinstance(f, str) and f.strip() for f in case.forbidden), case.case_id


def test_facts_file_names_only_real_cases():
    # Gap 483 (2026-09-07): the universe widened from CASES to CASES +
    # ATTACHMENT_CASES when the 16 attachment-probe turns were added as golden
    # cases. They are deliberately kept off the default path (twelve of them need
    # a document the harness cannot yet seed), so checking only CASES reported all
    # sixteen as orphans. The assertion itself is unchanged and just as strict:
    # a facts key naming no case at all is still a failure.
    from benchmarks.agent_eval_golden_sample import ATTACHMENT_CASES, CASES

    path = Path(__file__).resolve().parents[1] / "benchmarks" / "agent_eval_golden_facts.json"
    facts = json.loads(path.read_text(encoding="utf-8"))
    ids = {c.case_id for c in CASES} | {c.case_id for c in ATTACHMENT_CASES}
    unknown = [k for k in facts if not k.startswith("_") and k not in ids]
    assert unknown == [], unknown


# ---------------------------------------------------------------------------
# Gap 478 -- the harness grades the app's own evidence
# ---------------------------------------------------------------------------


def test_harness_prefers_the_apps_judge_evidence_over_the_recorder():
    from scripts.run_agent_eval import _judge_context

    recorder = SimpleNamespace(context=lambda: "DATABASE RESULTS:\n| a | 1 |")
    result = {
        "judge_evidence": {
            "context": "FULL RECORD:\n{...}\n\nCOMPUTED FIGURES:\n5,000 x 0.08 = 400.00"
        }
    }
    ctx = _judge_context(result, recorder)
    assert ctx.startswith("FULL RECORD:")
    # Unioned, not replaced: the recorder's evidence is still there.
    assert "DATABASE RESULTS" in ctx


def test_harness_falls_back_to_the_recorder_when_the_app_attached_nothing():
    from scripts.run_agent_eval import _judge_context

    recorder = SimpleNamespace(context=lambda: "DOCUMENT CHUNK:\nnet 30")
    assert _judge_context({}, recorder) == "DOCUMENT CHUNK:\nnet 30"
    assert _judge_context({"judge_evidence": {"context": ""}}, recorder) == "DOCUMENT CHUNK:\nnet 30"


def test_a_verdict_filed_in_the_wrong_list_is_matched_by_its_id():
    """Found live on the first re-score: the judge put required line R1 inside
    `forbidden` with met=true. Trusting list membership scored a correct answer
    0.0 for a forbidden assertion it never made. Ids win over lists."""
    llm = _judge_returning(
        FactChecklistVerdict(
            required=[],
            forbidden=[
                FactVerdict(id="R1", fact="States that payment status is not tracked.", met=True),
                FactVerdict(id="F1", fact="Asserts that the invoice HAS been paid.", met=False),
            ],
        )
    )
    score, notes, _ = score_accuracy(
        "q", None, "ans", llm,
        required_facts=("States that payment status is not tracked.",),
        forbidden=("Asserts that the invoice HAS been paid.",),
    )
    assert score == 1.0, notes
    assert not any(n.startswith("forbidden:") for n in notes)


def test_a_required_line_with_no_verdict_at_all_is_not_met():
    llm = _judge_returning(
        FactChecklistVerdict(required=[FactVerdict(id="R2", fact="b", met=True)], forbidden=[])
    )
    score, notes, _ = score_accuracy("q", None, "ans", llm, required_facts=("a", "b"))
    assert score == 0.5
    assert any(n.startswith("missing: a") for n in notes)
