"""BE Gap 480 (2026-09-14): an abstention has nothing to be faithful to.

Gap 479 left one AND-clause standing in `decide_pass()` -- a faithfulness of
exactly 0.0 fails whatever accuracy says -- as a fabrication guard. That guard
is right for an answer that asserts things about the data, and structurally
wrong for a Feature 29 decision-3 refusal, whose claims are about the SCHEMA
("there is no finance-approval column") while `judge_evidence.context` carries
only rows and document text. The 2026-09-07 live golden run
(`runs/f29-golden-20260907/`) shows it: `unsupported_field_asks_for_alternative`
scored accuracy 1.00, relevance 1.0, persona 1.0, faithfulness 0.00 -> FAIL,
against a reference verdict of PASS.

These tests assert the RULE, not that run's numbers: at every accuracy above the
floor and every faithfulness value, an abstention is graded on accuracy alone
and an ordinary answer still dies at faithfulness 0.0. The abstain signal is the
turn's own enumerated outcome, so the prose fixtures below are mutated -- vendor,
currency, column name, language -- to prove no assertion here depends on the
words in the answer.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import telemetry
from services.agent_eval import (
    ACCURACY_FLOOR,
    KIND_OUT_OF_SCOPE_REFUSAL,
    ClaimList,
    ClaimVerdict,
    EvalScores,
    FactChecklistVerdict,
    FactVerdict,
    FaithfulnessVerdicts,
    RelevanceVerdict,
    ScoreWithReason,
    PersonaVerdict,
    decide_pass,
    is_abstain_turn,
    score_answer,
)


# ---------------------------------------------------------------------------
# The signal is the turn's declared outcome, never the answer text
# ---------------------------------------------------------------------------


def test_the_contract_gates_abstention_is_an_abstain_turn():
    """Task 29.9's gate replaced the model's answer with `_abstain_payload()`."""
    assert is_abstain_turn({"answer_gate": "abstained"}) is True


def test_a_declined_turn_is_an_abstain_turn_even_with_no_answer_gate():
    """The case this gap was actually filed for. `unsupported_field_asks_for_
    alternative` generated no SQL at all, so the summary branch -- the only
    place `answer_gate` is set -- never ran; the refusal came out of the
    null-SQL path, which sets `status=declined`/`stop_reason=sql_declined`.
    Reading `answer_gate` alone, as the gap entry's option (c) proposed, would
    not have exempted the one turn it was written about."""
    assert is_abstain_turn(
        {"answer_gate": "", "turn_status": telemetry.TURN_STATUS_DECLINED,
         "stop_reason": "sql_declined"}
    ) is True


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        {"answer_gate": "", "turn_status": ""},
        {"answer_gate": "skipped", "turn_status": telemetry.TURN_STATUS_SUCCESS},
        {"answer_gate": "ok", "turn_status": telemetry.TURN_STATUS_SUCCESS},
        {"answer_gate": "regenerated_ok", "turn_status": telemetry.TURN_STATUS_SUCCESS},
        {"answer_gate": "regenerated_unsupported", "turn_status": telemetry.TURN_STATUS_SUCCESS},
        {"answer_gate": "regeneration_failed", "turn_status": telemetry.TURN_STATUS_ERROR},
        {"turn_status": telemetry.TURN_STATUS_ERROR},
        {"turn_status": telemetry.TURN_STATUS_CACHE_HIT},
    ],
)
def test_every_other_outcome_is_an_ordinary_answer(evidence):
    """Including the two that must NOT be exempted: a turn that errored, and a
    gate verdict of `regenerated_unsupported` -- the model was told which figure
    was unsupported and said it again. A missing payload (a cache hit carries no
    `judge_evidence`) reads as ordinary, which is the pre-Gap-480 behaviour."""
    assert is_abstain_turn(evidence) is False


@pytest.mark.parametrize(
    "prose",
    [
        "The invoice schema has no finance-approval field.",
        "Le schéma ne comporte aucun champ d'approbation.",
        "No hay ningún campo de aprobación en Konkan Exports' invoices.",
        "I can confirm every Blue Ridge Logistics invoice was approved by finance.",
        "",
    ],
)
def test_the_verdict_does_not_move_with_the_answer_text(prose):
    """`is_abstain_turn()` is not shown the answer at all. The last fixture is a
    confident fabrication and the first is a correct refusal: same signal, same
    verdict, because the signal is the agent's record and not its prose."""
    declined = {"turn_status": telemetry.TURN_STATUS_DECLINED, "answer_prose": prose}
    answered = {"turn_status": telemetry.TURN_STATUS_SUCCESS, "answer_prose": prose}
    assert is_abstain_turn(declined) is True
    assert is_abstain_turn(answered) is False


# ---------------------------------------------------------------------------
# The pass rule
# ---------------------------------------------------------------------------


def test_an_abstention_with_full_accuracy_and_zero_faithfulness_passes():
    """The Gap 480 case, in the shape the run recorded it."""
    assert decide_pass(
        EvalScores(accuracy_score=1.0, faithfulness_score=0.0, relevance_score=1.0, abstained=True)
    ) is True


def test_an_ordinary_answer_with_zero_faithfulness_still_fails():
    """Gap 479's fabrication guard, untouched."""
    assert decide_pass(
        EvalScores(accuracy_score=1.0, faithfulness_score=0.0, relevance_score=1.0)
    ) is False


@pytest.mark.parametrize("faithfulness", [0.0, 0.25, 0.5, 0.75, 1.0, None])
@pytest.mark.parametrize("accuracy", [ACCURACY_FLOOR, 0.8, 1.0])
def test_an_abstention_is_graded_on_accuracy_alone(faithfulness, accuracy):
    """The property, not one fixture: above the accuracy floor, no faithfulness
    value can sink an abstention."""
    assert decide_pass(
        EvalScores(accuracy_score=accuracy, faithfulness_score=faithfulness, abstained=True)
    ) is True


@pytest.mark.parametrize("accuracy", [0.0, 0.5, ACCURACY_FLOOR - 0.01])
def test_an_abstention_that_is_itself_wrong_still_fails_on_accuracy(accuracy):
    """The stated boundary. Refusing on a field that does exist is a wrong
    answer; nothing here rescues it, and accuracy is the only thing that catches
    it -- this fix does not make abstaining safe, it makes it gradeable."""
    assert decide_pass(
        EvalScores(accuracy_score=accuracy, faithfulness_score=1.0, abstained=True)
    ) is False


@pytest.mark.parametrize("faithfulness", [0.0, 0.4])
def test_with_no_reference_an_abstention_is_graded_on_relevance(faithfulness):
    """The online judge's branch: live turns have no reference, so accuracy is
    None and the old floors apply. Faithfulness is dropped there too -- a
    production refusal would otherwise fail for having no rows to cite."""
    assert decide_pass(
        EvalScores(faithfulness_score=faithfulness, relevance_score=0.9, abstained=True)
    ) is True
    assert decide_pass(
        EvalScores(faithfulness_score=faithfulness, relevance_score=0.9)
    ) is False


def test_an_abstention_with_nothing_scored_at_all_is_still_a_fail():
    """Dropping faithfulness must not turn a broken judge into a green run."""
    assert decide_pass(EvalScores(abstained=True)) is False
    assert decide_pass(EvalScores(faithfulness_score=0.0, abstained=True)) is False


# ---------------------------------------------------------------------------
# End to end through `score_answer()`, on mutated fixtures
# ---------------------------------------------------------------------------


class _ScriptedJudge:
    """Returns one canned verdict per structured-output schema."""

    def __init__(self, by_schema):
        self._by_schema = by_schema

    def with_structured_output(self, schema):
        verdict = self._by_schema[schema]
        handle = MagicMock()
        handle.invoke.return_value = verdict
        return handle


def _judge_scoring_zero_faithfulness(claim: str):
    """Every claim unsupported -- the 0.00 the schema-claim case produces."""
    return _ScriptedJudge(
        {
            ClaimList: ClaimList(claims=[claim]),
            FaithfulnessVerdicts: FaithfulnessVerdicts(
                verdicts=[ClaimVerdict(claim=claim, supported=False, claim_type="positive_fact")]
            ),
            RelevanceVerdict: RelevanceVerdict(answer_kind=KIND_OUT_OF_SCOPE_REFUSAL, score=1.0, reason="r"),
            FactChecklistVerdict: FactChecklistVerdict(
                required=[FactVerdict(id="R1", fact="Says the field is not tracked.", met=True)],
                forbidden=[],
            ),
            PersonaVerdict: PersonaVerdict(applicable=False),
            ScoreWithReason: ScoreWithReason(score=1.0, reason="r"),
        }
    )


#: Four unrelated refusals: different vendor, currency, column, language. The
#: fix is generic or none of these work.
MUTATED_REFUSALS = [
    ("The invoice schema has no finance-approval field.", "which invoices were approved by finance?"),
    ("There is no purchase-order column on these records.", "show me the PO number for KE-2026-0089"),
    ("We record no FX rate for JPY, so a yen total cannot be given.", "what did we bill in JPY?"),
    ("Konkan Exports' records carry no delivery date.", "when was the Konkan shipment delivered?"),
]


@pytest.mark.parametrize("prose,question", MUTATED_REFUSALS)
def test_a_marked_abstention_passes_and_the_same_turn_unmarked_does_not(prose, question):
    """One input, two flag values, opposite verdicts -- so the difference is the
    rule and not the fixture. Faithfulness is still SCORED at 0.0 in both: the
    number is recorded and trended, it just stops voting."""
    abstained = score_answer(
        question=question,
        answer=prose,
        context="",
        expected_answer="States the field is not tracked.",
        llm=_judge_scoring_zero_faithfulness(prose),
        required_facts=("Says the field is not tracked.",),
        abstained=True,
    )
    assert abstained.faithfulness_score == 0.0
    assert abstained.accuracy_score == 1.0
    assert abstained.passed is True
    assert "BE Gap 480" in abstained.note_text()

    ordinary = score_answer(
        question=question,
        answer=prose,
        context="",
        expected_answer="States the field is not tracked.",
        llm=_judge_scoring_zero_faithfulness(prose),
        required_facts=("Says the field is not tracked.",),
    )
    assert ordinary.faithfulness_score == 0.0
    assert ordinary.accuracy_score == 1.0
    assert ordinary.passed is False
    assert "BE Gap 480" not in ordinary.note_text()


def test_score_answer_defaults_to_not_abstained():
    """Additive by construction: every existing caller keeps Gap 479's rule."""
    scores = score_answer(
        question="q",
        answer="a",
        context="",
        expected_answer=None,
        llm=_judge_scoring_zero_faithfulness("a"),
    )
    assert scores.abstained is False


# ---------------------------------------------------------------------------
# The wiring: the agent declares it, the harness reads it
# ---------------------------------------------------------------------------


def test_the_agent_publishes_the_outcome_keys_on_judge_evidence():
    """`is_abstain_turn()` can only work if `run_query_agent()` actually puts the
    turn's outcome on the payload the harness and the online judge both read."""
    import inspect

    import agents.query_agent as qa

    src = inspect.getsource(qa._run_query_agent)
    block = src[src.index('result["judge_evidence"] = {'):]
    for key in ('"answer_gate"', '"turn_status"', '"stop_reason"'):
        assert key in block[:600], key


def test_the_harness_marks_the_turn_and_grades_it_with_that_mark():
    """Both halves of the harness wiring, so a green pass rule with a payload
    that never carries the flag cannot look like a fix."""
    import inspect

    from scripts import run_agent_eval

    assert '"abstained": is_abstain_turn(result.get("judge_evidence"))' in inspect.getsource(
        run_agent_eval.run_turn
    )
    assert 'abstained=bool(turn.get("abstained"))' in inspect.getsource(run_agent_eval.score_turn)


def test_the_online_judge_uses_the_same_signal():
    """Gap 480 is a pass-rule change, and the production judge shares that rule."""
    import inspect

    from services import online_quality_judge

    assert "abstained=is_abstain_turn(evidence)" in inspect.getsource(online_quality_judge._judge_turn)
