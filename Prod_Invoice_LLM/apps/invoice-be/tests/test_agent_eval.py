"""Feature 23 Phase 3 — unit tests for the evaluation infrastructure.

Scope note, stated up front in the same spirit as `test_telemetry.py`'s: these
prove the *mechanics* — that faithfulness really is supported-claims over total
claims, that an unreachable judge leaves a score absent rather than zero, that
the pass floors are per-dimension and not averaged, that the `agent_eval_run`
row (and its `pass` column) round-trips, that the migration's DDL executes, and
that the per-turn LLM-call counter counts the product's calls and not the
judge's. They deliberately do not assert anything about how a real model scores
a real answer: that is what `scripts/run_agent_eval.py` is for, and its output
is data, not a test assertion.
"""
import importlib.util
import logging
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import telemetry
from models import AgentEvalRun
from services import agent_eval
from services.agent_eval import (
    ACCURACY_FLOOR,
    CLAIM_TYPE_ABSENCE,
    CLAIM_TYPE_NON_FACTUAL,
    CLAIM_TYPE_POSITIVE,
    CLAIM_TYPE_QUERY_SCOPE,
    KIND_CAPABILITY_OR_GREETING,
    KIND_CLARIFYING_QUESTION,
    KIND_DIRECT_ANSWER,
    KIND_NO_RESULTS_REPORT,
    KIND_OFF_TOPIC,
    KIND_OUT_OF_SCOPE_REFUSAL,
    EvalScores,
    ClaimList,
    ClaimVerdict,
    CombinedSoftVerdict,
    FaithfulnessVerdicts,
    PersonaVerdict,
    RelevanceVerdict,
    ScoreWithReason,
    collect_invoice_identifiers,
    decide_pass,
    identifiers_from_markdown,
    score_answer,
    score_context,
    score_faithfulness,
    score_orchestration,
    score_persona,
    score_relevance,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


class _ScriptedJudge:
    """Returns a canned object per schema class, same shape as this repo's other
    LLM doubles (`_RecordingLLM` in `test_chat_sql_quality.py`)."""

    def __init__(self, by_schema: dict, raise_for: tuple = ()):
        self._by_schema = by_schema
        self._raise_for = raise_for
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                if schema in outer._raise_for:
                    raise RuntimeError("judge unavailable")
                return outer._by_schema[schema]

        return _Structured()


def _judge(
    claims,
    verdicts,
    relevance=1.0,
    accuracy=1.0,
    raise_for=(),
    relevance_kind=KIND_DIRECT_ANSWER,
    persona=None,
):
    """`verdicts` items are `(claim, supported)` or `(claim, supported, claim_type)`."""
    return _ScriptedJudge(
        {
            ClaimList: ClaimList(claims=claims),
            FaithfulnessVerdicts: FaithfulnessVerdicts(
                verdicts=[
                    ClaimVerdict(
                        claim=item[0],
                        supported=item[1],
                        claim_type=item[2] if len(item) > 2 else CLAIM_TYPE_POSITIVE,
                    )
                    for item in verdicts
                ]
            ),
            RelevanceVerdict: RelevanceVerdict(
                answer_kind=relevance_kind, score=relevance, reason="scripted"
            ),
            ScoreWithReason: ScoreWithReason(score=accuracy, reason="scripted"),
            PersonaVerdict: persona or PersonaVerdict(applicable=False, reason="scripted"),
        },
        raise_for=raise_for,
    )


# ---------------------------------------------------------------------------
# Faithfulness — the RAGAS definition, implemented
# ---------------------------------------------------------------------------


def test_faithfulness_is_supported_claims_over_total_claims():
    llm = _judge(
        claims=["Total is USD 42,300.00", "The vendor is DataPipe Solutions", "It was paid in July"],
        verdicts=[
            ("Total is USD 42,300.00", True),
            ("The vendor is DataPipe Solutions", True),
            ("It was paid in July", False),
        ],
    )

    score, claims, notes, calls = score_faithfulness(
        "DataPipe Solutions billed USD 42,300.00 and it was paid in July.",
        "vendor_name | grand_total\nDataPipe Solutions | 42300.00",
        llm,
    )

    assert score == pytest.approx(2 / 3)
    assert len(claims) == 3
    assert calls == 2  # one decomposition + one verdict pass
    assert any("It was paid in July" in n for n in notes)


def test_claims_asserted_with_no_context_at_all_score_zero_not_absent():
    """The unfaithful case by definition: facts stated with no evidence behind
    them. That is a real 0.0, and must not be confused with 'not scored'."""
    llm = _judge(claims=["Total spend was USD 96,420.00"], verdicts=[])

    score, _claims, notes, _calls = score_faithfulness("Total spend was USD 96,420.00", "", llm)

    assert score == 0.0
    assert any("no tool context" in n for n in notes)


def test_an_answer_with_no_factual_claims_is_not_scored_rather_than_zero():
    """A greeting asserts nothing, so there is nothing to be faithful to. Scoring
    it 0.0 would drag every trend line down on the cheapest turn in the set."""
    llm = _judge(claims=[], verdicts=[])

    score, claims, notes, _calls = score_faithfulness("Hello! How can I help?", "some context", llm)

    assert score is None
    assert claims == []
    assert any("no factual claims" in n for n in notes)


def test_an_unreachable_judge_leaves_the_score_absent(caplog):
    llm = _judge(
        claims=["Total is USD 1.00"],
        verdicts=[("Total is USD 1.00", True)],
        raise_for=(FaithfulnessVerdicts,),
    )

    with caplog.at_level(logging.WARNING):
        score, _claims, notes, _calls = score_faithfulness("Total is USD 1.00", "context", llm)

    assert score is None
    assert any("judge unavailable" in n for n in notes)


# ---------------------------------------------------------------------------
# Judge failure mode 3 — a correct "no records found" scored 0.00 faithfulness
# ---------------------------------------------------------------------------
# Every string below is copied verbatim out of `tests/agent_eval_output.json`,
# the persisted output of the 2026-08-21 run that exhibited the bug (case
# `zero_result_vendor`, path `default`, faithfulness 0.0). They are not invented
# examples of the shape -- they ARE the shape.

_ZERO_RESULT_QUESTION = "what did we spend with Nonexistent Holdings last quarter"
_ZERO_RESULT_ANSWER = (
    "No records were found for Nonexistent Holdings last quarter, so there were "
    "no recorded spends with that vendor during the period."
)
_ZERO_RESULT_CONTEXT = "DATABASE RESULTS:\nNo records found matching the query criteria."
_ZERO_RESULT_CLAIMS = [
    "No records were found for Nonexistent Holdings last quarter.",
    "There were no recorded spends with Nonexistent Holdings during the period.",
]
_ZERO_RESULT_SQL = (
    "SQL EXECUTED:\nSELECT SUM(grand_total) FROM invoice WHERE tenant_id = '000...' "
    "AND LOWER(vendor_name) LIKE LOWER('%Nonexistent Holdings%') "
    "AND invoice_date >= '2026-04-01' AND invoice_date < '2026-07-01';"
)


def test_the_zero_result_evidence_now_names_the_vendor_that_was_searched_for():
    """The actual defect, isolated.

    The judge's verdict on the live run was defensible on the evidence it was
    given: 'No records found matching the query criteria.' does not mention
    Nonexistent Holdings or any period, so neither claim could be checked. The
    fix is that the executed query is now part of the evidence -- assert the
    vendor name really reaches the prompt, because that is the thing that was
    missing.
    """
    llm = _judge(
        claims=_ZERO_RESULT_CLAIMS,
        verdicts=[(c, True, CLAIM_TYPE_ABSENCE) for c in _ZERO_RESULT_CLAIMS],
    )

    score_faithfulness(_ZERO_RESULT_ANSWER, _ZERO_RESULT_CONTEXT, llm, _ZERO_RESULT_SQL)

    verdict_prompt = llm.prompts[-1]
    assert "Nonexistent Holdings" in verdict_prompt
    assert "2026-04-01" in verdict_prompt
    # And the rubric it is judged under names the four claim types explicitly,
    # rather than appending an empty-result carve-out after three absolute rules.
    for claim_type in (
        CLAIM_TYPE_POSITIVE,
        CLAIM_TYPE_ABSENCE,
        CLAIM_TYPE_QUERY_SCOPE,
        CLAIM_TYPE_NON_FACTUAL,
    ):
        assert claim_type in verdict_prompt


def test_a_correct_no_records_answer_scores_full_faithfulness():
    """The end-to-end assertion for failure mode 3: this exact turn scored 0.00
    on 2026-08-21 and must now score 1.00."""
    llm = _judge(
        claims=_ZERO_RESULT_CLAIMS,
        verdicts=[(c, True, CLAIM_TYPE_ABSENCE) for c in _ZERO_RESULT_CLAIMS],
    )

    score, claims, notes, _calls = score_faithfulness(
        _ZERO_RESULT_ANSWER, _ZERO_RESULT_CONTEXT, llm, _ZERO_RESULT_SQL
    )

    assert score == 1.0
    assert len(claims) == 2
    assert any("2/2 claims supported" in note for note in notes)


def test_an_empty_results_block_no_longer_short_circuits_when_a_query_ran():
    """`context` empty used to mean a hard-coded 0.00 before the judge was even
    called. With a recorded query, "the tool ran and matched nothing" is evidence
    and gets judged like any other evidence."""
    llm = _judge(
        claims=["No invoices exist for Nonexistent Holdings."],
        verdicts=[("No invoices exist for Nonexistent Holdings.", True, CLAIM_TYPE_ABSENCE)],
    )

    score, _claims, notes, calls = score_faithfulness(
        "No invoices exist for Nonexistent Holdings.", "", llm, _ZERO_RESULT_SQL
    )

    assert score == 1.0
    assert calls == 2  # the verdict judge really was reached, not short-circuited
    assert not any("no tool context" in note for note in notes)


def test_with_no_query_and_no_results_an_asserted_fact_is_still_a_real_zero():
    """The guard that keeps the fix above from becoming a free pass: nothing ran,
    nothing came back, and the answer stated a figure anyway."""
    llm = _judge(claims=["Total spend was USD 96,420.00"], verdicts=[])

    score, _claims, notes, _calls = score_faithfulness(
        "Total spend was USD 96,420.00", "", llm, None
    )

    assert score == 0.0
    assert any("no tool context" in note for note in notes)


def test_a_positive_claim_against_an_empty_result_is_still_unsupported():
    """Failure mode 3's fix must not make every claim supported. An amount cannot
    come out of an empty result set, whatever the query was."""
    llm = _judge(
        claims=[
            "No records were found for Nonexistent Holdings.",
            "Spend with Nonexistent Holdings was USD 4,000.00.",
        ],
        verdicts=[
            ("No records were found for Nonexistent Holdings.", True, CLAIM_TYPE_ABSENCE),
            ("Spend with Nonexistent Holdings was USD 4,000.00.", False, CLAIM_TYPE_POSITIVE),
        ],
    )

    score, _claims, _notes, _calls = score_faithfulness(
        "…", _ZERO_RESULT_CONTEXT, llm, _ZERO_RESULT_SQL
    )

    assert score == 0.5


def test_non_factual_claims_leave_the_denominator_rather_than_costing_score():
    """The third instance of the same family as failure mode 2: a pleasantry the
    decomposition step failed to filter must cost nothing, not cost score."""
    llm = _judge(
        claims=["The total is USD 42,300.00", "Let me know if you'd like a breakdown."],
        verdicts=[
            ("The total is USD 42,300.00", True, CLAIM_TYPE_POSITIVE),
            ("Let me know if you'd like a breakdown.", True, CLAIM_TYPE_NON_FACTUAL),
        ],
    )

    score, _claims, notes, _calls = score_faithfulness("…", "USD 42,300.00", llm)

    assert score == 1.0  # 1/1, not 1/2
    assert any("1 non-factual claim(s) excluded" in note for note in notes)


def test_an_answer_that_is_entirely_pleasantry_is_not_scored_rather_than_zero():
    llm = _judge(
        claims=["Happy to help!"],
        verdicts=[("Happy to help!", True, CLAIM_TYPE_NON_FACTUAL)],
    )

    score, _claims, notes, _calls = score_faithfulness("Happy to help!", "some context", llm)

    assert score is None
    assert any("all 1 claims were non-factual" in note for note in notes)


# ---------------------------------------------------------------------------
# Judge failure mode 4 — the same refusal scored 1.0 on one path, 0.0 on the other
# ---------------------------------------------------------------------------
# Both answer texts below are verbatim from `tests/agent_eval_output.json`, case
# `out_of_scope_code_request`: the default path's answer scored relevance 0.0 and
# SAGE's scored 1.0 in the same run, for the same correct refusal of the same
# question.

_REFUSAL_QUESTION = "write me a python script to reverse a string"
_REFUSAL_DEFAULT_PATH = (
    "Sorry - I can't write general-purpose code. I help with invoices and this "
    "platform's features; if you need a script that operates on invoice data (for "
    "example, reversing a text field in invoice descriptions), tell me the "
    "runtime/environment and I can help design an invoice-focused solution or "
    "outline high-level steps."
)
_REFUSAL_SAGE_PATH = (
    "Sorry - I can't help with general programming requests like writing Python "
    "scripts; I assist with accounts-payable and audit queries. If you need this "
    "for an AP workflow (e.g., filename normalization or data parsing), tell me "
    "the context and I can suggest how to handle it within our platform."
)


def _relevance_only_judge(kind, score):
    return _ScriptedJudge(
        {RelevanceVerdict: RelevanceVerdict(answer_kind=kind, score=score, reason="scripted")}
    )


def test_the_same_refusal_scores_identically_however_the_judge_numbers_it():
    """The consistency assertion for failure mode 4.

    Both judge calls are given the divergence that actually happened -- 0.0 on
    one path, 1.0 on the other -- and both must now come out at 1.0, because for
    an out-of-scope refusal the relevance is fixed by policy rather than by the
    judge's number. Two paraphrases of the same correct refusal can no longer
    land on different scores.
    """
    default_score, default_notes, _ = score_relevance(
        _REFUSAL_QUESTION,
        _REFUSAL_DEFAULT_PATH,
        _relevance_only_judge(KIND_OUT_OF_SCOPE_REFUSAL, 0.0),
    )
    sage_score, _sage_notes, _ = score_relevance(
        _REFUSAL_QUESTION,
        _REFUSAL_SAGE_PATH,
        _relevance_only_judge(KIND_OUT_OF_SCOPE_REFUSAL, 1.0),
    )

    assert default_score == sage_score == 1.0
    assert any("fixed by kind" in note for note in default_notes)


def test_the_greeting_shape_is_stable_across_paths_too():
    """Same run, lower amplitude: `greeting_no_tool` scored 0.7 on one path and
    1.0 on the other."""
    a, _notes, _ = score_relevance(
        "hello there", "Hi! I can help with your invoices.",
        _relevance_only_judge(KIND_CAPABILITY_OR_GREETING, 0.7),
    )
    b, _notes, _ = score_relevance(
        "hello there", "Hello! Ask me anything about your invoices.",
        _relevance_only_judge(KIND_CAPABILITY_OR_GREETING, 1.0),
    )

    assert a == b == 1.0


def test_a_no_results_report_is_definitionally_relevant():
    score, _notes, _ = score_relevance(
        _ZERO_RESULT_QUESTION,
        _ZERO_RESULT_ANSWER,
        _relevance_only_judge(KIND_NO_RESULTS_REPORT, 0.0),
    )
    assert score == 1.0


def test_off_topic_is_a_fixed_zero_whatever_the_judge_says():
    score, _notes, _ = score_relevance(
        "what did we spend on freight",
        "The weather in Bangalore is pleasant this week.",
        _relevance_only_judge(KIND_OFF_TOPIC, 0.9),
    )
    assert score == 0.0


@pytest.mark.parametrize("kind", [KIND_DIRECT_ANSWER, KIND_CLARIFYING_QUESTION])
def test_the_kinds_where_relevance_is_a_matter_of_degree_still_use_the_judge(kind):
    """The fix must not flatten the metric: for a real answer, relevance is still
    a judged number, not a category."""
    score, notes, _ = score_relevance("q", "a", _relevance_only_judge(kind, 0.4))

    assert score == 0.4
    assert any("judged" in note for note in notes)


def test_an_unrecognised_answer_kind_falls_back_to_the_raw_score():
    """A judge double that predates this schema, or a model that invents its own
    label, must still produce a usable number rather than losing the score."""
    score, notes, _ = score_relevance("q", "a", _relevance_only_judge("something_else", 0.6))

    assert score == 0.6
    assert any("not recognised" in note for note in notes)


def test_the_relevance_prompt_makes_the_judge_classify_before_it_scores():
    llm = _relevance_only_judge(KIND_DIRECT_ANSWER, 1.0)
    score_relevance(_REFUSAL_QUESTION, _REFUSAL_DEFAULT_PATH, llm)

    prompt = llm.prompts[-1]
    assert prompt.index("STEP 1") < prompt.index("STEP 2")
    for kind in (
        KIND_DIRECT_ANSWER,
        KIND_CLARIFYING_QUESTION,
        KIND_NO_RESULTS_REPORT,
        KIND_OUT_OF_SCOPE_REFUSAL,
        KIND_CAPABILITY_OR_GREETING,
        KIND_OFF_TOPIC,
    ):
        assert kind in prompt


# ---------------------------------------------------------------------------
# Component-level scoring — context (deterministic)
# ---------------------------------------------------------------------------


def test_context_score_is_f1_over_the_expected_invoice_set():
    score, notes = score_context(
        fetched=["DPS-9981", "SEP-4410"], expected=["DPS-9981", "SEP-4410"]
    )
    assert score == 1.0
    assert any("precision 1.00" in note for note in notes)

    # Gap 268's shape: ORDER BY ... LIMIT 1 truncated the loser.
    half, notes = score_context(fetched=["DPS-9981"], expected=["DPS-9981", "SEP-4410"])
    assert half == pytest.approx(2 / 3)
    assert any("SEP-4410" in note for note in notes)


def test_context_score_penalises_fetching_the_wrong_invoice_and_the_right_one():
    """Precision matters on its own: an over-broad filter that happens to include
    the answer is still a context-builder defect."""
    score, _notes = score_context(
        fetched=["DPS-9981", "SEP-4410", "BRL-7702"], expected=["DPS-9981"]
    )
    assert score == pytest.approx(0.5)


def test_fetching_nothing_when_nothing_should_be_fetched_is_a_full_score():
    """Gap 224's shape is the most diagnostic case in the set, so an empty
    expected set is scored, not skipped."""
    assert score_context(fetched=[], expected=())[0] == 1.0
    assert score_context(fetched=["BRL-7702"], expected=())[0] == 0.0


def test_a_case_with_no_declared_expected_set_is_not_scored_rather_than_zero():
    score, notes = score_context(fetched=["BRL-7702"], expected=None)
    assert score is None
    assert any("no expected invoice set" in note for note in notes)


def test_identifiers_are_collected_from_structures_and_from_markdown_tables():
    """The two real evidence shapes: the agentic path returns structures, the
    default path returns a rendered table."""
    structured = {
        "status": "ok",
        "candidates": [{"invoice_number": "dps-9981"}, {"invoice_number": "SEP-4410"}],
        "record": {"invoice_id": "abc-123", "line_items": [{"description": "Bolts"}]},
    }
    assert collect_invoice_identifiers(structured) == {"DPS-9981", "SEP-4410", "ABC-123"}

    markdown = (
        "invoice_number | vendor_name | grand_total\n"
        "--- | --- | ---\n"
        "TSD-620458 | Titan Steel Distributors | 18450.00\n"
        "BRL-7702 | Blue Ridge Logistics | 6120.00"
    )
    assert identifiers_from_markdown(markdown) == {"TSD-620458", "BRL-7702"}
    # A query that did not select the column yields nothing rather than a guess.
    assert identifiers_from_markdown("vendor_name | total\n--- | ---\nAcme | 10") == set()


# ---------------------------------------------------------------------------
# Component-level scoring — orchestration (mechanical, no judge)
# ---------------------------------------------------------------------------


def test_orchestration_score_is_traceable_figures_over_total_figures():
    context = (
        "invoice_number | grand_total | due_date\n"
        "DPS-9981 | 42300.00 | 2026-08-01"
    )
    score, notes = score_orchestration(
        "DataPipe Solutions billed USD 42,300.00, due 2026-08-01.", context
    )
    assert score == 1.0
    assert any("2/2 figures" in note for note in notes)


def test_orchestration_score_catches_a_figure_that_is_in_no_tool_result():
    """The failure this component exists for: a number that appears nowhere in
    the evidence. Gaps 263/264's fabricated CGST split is exactly this shape."""
    score, notes = score_orchestration(
        "The CGST recorded for Rajesh Steel is INR 9,000.00.",
        "vendor_name | tax_amount | grand_total\nRajesh Steel | 18000.00 | 118000.00",
    )
    assert score == 0.0
    assert any("9,000.00" in note for note in notes)


def test_a_computed_figure_traces_to_the_fetched_fields_it_was_computed_from():
    """'or a compute() output' is in the design instruction, and without it a
    correct arithmetic answer would score as a fabrication."""
    score, _notes = score_orchestration(
        "DataPipe is bigger by USD 14,350.00.",
        "DPS-9981 | 42300.00\nSEP-4410 | 27950.00",
    )
    assert score == 1.0


def test_a_second_arithmetic_hop_is_allowed_only_over_already_grounded_figures():
    """Found by running this check against the 2026-08-21 round's real output.

    `bolts_reconciliation`'s correct answer had `USD 20.00` marked untraceable,
    because 20 = 420 - 400 and 400 is itself derived (5,000 x 0.08). A correct
    answer under-scored is the exact bug class this module has a documented
    history of. The text below is that turn's real answer prose.
    """
    answer = (
        "No -- the Bolts line does not reconcile. It shows 5,000 units at USD 0.08, "
        "which computes to USD 400.00, but the printed line amount is USD 420.00, "
        "a USD 20.00 discrepancy."
    )
    context = "description | quantity | unit_price | amount\nBolts | 5000.00 | 0.08 | 420.00"

    score, notes = score_orchestration(answer, context)

    assert score == 1.0, notes
    # ...and the second hop must not become "any number is derivable": an
    # invented figure with no path from the evidence is still caught.
    bad, notes = score_orchestration(answer + " The vendor also billed USD 7,431.19.", context)
    assert bad < 1.0
    assert any("7,431.19" in note for note in notes)


def test_no_judge_call_is_made_by_the_orchestration_check():
    """It is arithmetic, so it costs nothing and cannot vary between runs."""
    first = score_orchestration("USD 42,300.00", "42300.00")
    second = score_orchestration("USD 42,300.00", "42300.00")
    assert first == second == (1.0, ["orchestration: 1/1 figures trace to the evidence"])


def test_an_answer_with_no_gradeable_figure_is_not_scored_rather_than_zero():
    score, notes = score_orchestration(_REFUSAL_DEFAULT_PATH, "")
    assert score is None
    assert any("no gradeable figures" in note for note in notes)


def test_small_bare_integers_are_skipped_and_reported_not_silently_dropped():
    """Grading '3 invoices' or a list marker would re-create the exact
    under-scoring-correct-answers bug this module has a history of."""
    score, notes = score_orchestration("We found 3 invoices totalling USD 1,120.00.", "1120.00")
    assert score == 1.0
    assert any("skipped" in note for note in notes)


def test_the_executed_query_counts_as_evidence_for_orchestration_too():
    """A date filter the answer restates lives in the SQL, not in the results."""
    score, _notes = score_orchestration(
        "Nothing was billed between 2026-04-01 and 2026-06-30.",
        "No records found matching the query criteria.",
        "SQL EXECUTED: ... invoice_date BETWEEN '2026-04-01' AND '2026-06-30'",
    )
    assert score == 1.0


# ---------------------------------------------------------------------------
# Component-level scoring — persona (LLM-judged)
# ---------------------------------------------------------------------------


def test_persona_is_not_scored_on_a_turn_that_needed_no_domain_judgement():
    """Most turns need none, and a 0.0 or a 1.0 for them would both be noise.
    The denominator has to stay honest for the trend to mean anything."""
    llm = _ScriptedJudge({PersonaVerdict: PersonaVerdict(applicable=False, score=1.0)})

    score, notes, calls = score_persona("hello there", "Hi!", None, llm)

    assert score is None
    assert calls == 1
    assert any("no domain judgement required" in note for note in notes)


def test_persona_scores_a_domain_error_and_names_the_area():
    llm = _ScriptedJudge(
        {
            PersonaVerdict: PersonaVerdict(
                applicable=True,
                score=0.0,
                domain_areas=["tax components"],
                reason="relabelled a combined tax_amount as CGST",
            )
        }
    )

    score, notes, _calls = score_persona(
        "whats the CGST we paid to Rajesh Steel",
        "The CGST recorded for Rajesh Steel is INR 18,000.00",
        "There is no CGST figure stored; only a combined tax_amount of INR 18,000.00.",
        llm,
    )

    assert score == 0.0
    assert any("tax components" in note for note in notes)


def test_the_persona_rubric_names_this_repos_own_domain_failures():
    """Not generic accounting: the rubric is this repo's closed gaps."""
    llm = _ScriptedJudge({PersonaVerdict: PersonaVerdict(applicable=False)})
    score_persona("q", "a", None, llm)

    prompt = llm.prompts[-1]
    for term in ("CGST", "IGST", "Reverse charge", "payment status", "LINE ITEM", "exchange rate"):
        assert term in prompt


# ---------------------------------------------------------------------------
# The component scores are additive, not a redefinition of pass/fail
# ---------------------------------------------------------------------------


def test_component_scores_do_not_change_the_pass_decision():
    """Folding them into `passed` would silently redefine what a pass means
    halfway through a trend series, which is the one thing a trend must not do."""
    passing = EvalScores(faithfulness_score=1.0, relevance_score=1.0, accuracy_score=1.0)
    assert decide_pass(passing) is True

    passing.context_score = 0.0
    passing.orchestration_score = 0.0
    passing.persona_score = 0.0
    assert decide_pass(passing) is True


def test_score_answer_populates_all_six_scores():
    llm = _judge(
        claims=["The total is USD 42,300.00"],
        verdicts=[("The total is USD 42,300.00", True, CLAIM_TYPE_POSITIVE)],
        relevance=1.0,
        accuracy=1.0,
        persona=PersonaVerdict(applicable=True, score=0.5, reason="scripted"),
    )

    scores = score_answer(
        question="whose invoice was bigger",
        answer="The total is USD 42,300.00.",
        context="invoice_number | grand_total\nDPS-9981 | 42300.00",
        expected_answer="DPS-9981 at USD 42,300.00",
        llm=llm,
        expected_invoice_ids=("DPS-9981",),
        fetched_invoice_ids=("DPS-9981",),
    )

    assert scores.faithfulness_score == 1.0
    assert scores.relevance_score == 1.0
    assert scores.accuracy_score == 1.0
    assert scores.context_score == 1.0
    assert scores.orchestration_score == 1.0
    assert scores.persona_score == 0.5
    assert scores.passed is True


# ---------------------------------------------------------------------------
# The pass decision
# ---------------------------------------------------------------------------


def test_a_fabricated_figure_is_not_redeemed_by_being_on_topic():
    """Three floors, not one average: 0.5 faithfulness + 1.0 relevance +
    1.0 accuracy averages to 0.83, which would pass. It must not."""
    assert decide_pass(EvalScores(faithfulness_score=0.5, relevance_score=1.0, accuracy_score=1.0)) is False


def test_a_case_with_no_reference_answer_passes_on_the_dimensions_it_has():
    assert decide_pass(EvalScores(faithfulness_score=1.0, relevance_score=0.9, accuracy_score=None)) is True


def test_nothing_scored_at_all_is_a_fail_not_a_pass():
    """A harness that defaulted to pass would go green on the day the judge broke."""
    assert decide_pass(EvalScores()) is False


def test_accuracy_exactly_at_the_floor_passes():
    assert decide_pass(EvalScores(accuracy_score=ACCURACY_FLOOR)) is True


def test_score_answer_skips_accuracy_when_there_is_no_reference_answer():
    llm = _judge(claims=["A"], verdicts=[("A", True)], relevance=0.9)

    scores = score_answer(question="q", answer="A", context="A", expected_answer=None, llm=llm)

    assert scores.faithfulness_score == 1.0
    assert scores.relevance_score == 0.9
    assert scores.accuracy_score is None
    assert scores.passed is True
    # decomposition + verdicts + relevance + persona. No accuracy call was made
    # at all, because there is no reference answer to compare against.
    assert scores.judge_llm_calls == 4
    # ...and the two deterministic components cost no judge call by construction.
    assert score_answer(
        question="q", answer="A", context="A", expected_answer=None,
        llm=_judge(claims=["A"], verdicts=[("A", True)], relevance=0.9),
        score_persona_component=False,
    ).judge_llm_calls == 3


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_agent_eval_run_round_trips_including_the_pass_column(db_session):
    tenant_id = uuid4()
    db_session.add(
        AgentEvalRun(
            agent_name="chat.default_path",
            question="how much did we spend on freight",
            expected_answer="USD 1,120.00 from Blue Ridge Logistics",
            actual_answer="Blue Ridge Logistics billed USD 1,120.00 for freight.",
            passed=True,
            faithfulness_score=1.0,
            relevance_score=0.95,
            accuracy_score=1.0,
            latency_ms=18422.5,
            llm_call_count=3,
            tenant_id=tenant_id,
            notes="case=freight_per_vendor",
        )
    )
    db_session.commit()

    row = db_session.exec(select(AgentEvalRun)).one()
    assert row.passed is True
    assert row.llm_call_count == 3
    assert row.accuracy_score == 1.0
    # The column really is named `pass` in SQL, whatever the attribute is called.
    raw = db_session.connection().exec_driver_sql(
        "SELECT \"pass\", llm_call_count FROM agent_eval_run"
    ).fetchall()
    assert raw == [(1, 3)]


def test_absent_scores_persist_as_null_not_zero(db_session):
    db_session.add(
        AgentEvalRun(
            agent_name="sage.agentic_path",
            question="hello there",
            actual_answer="Hi! I can help with your invoices.",
            passed=True,
            relevance_score=1.0,
            latency_ms=5016.4,
            llm_call_count=2,
            tenant_id=uuid4(),
        )
    )
    db_session.commit()

    row = db_session.exec(select(AgentEvalRun)).one()
    assert row.faithfulness_score is None
    assert row.accuracy_score is None


def test_quality_trend_is_queryable_by_day_and_agent(db_session):
    """The reason this table exists at all: 'is it getting worse' has to be a
    query, not a memory."""
    tenant_id = uuid4()
    today = datetime.utcnow()
    for day_offset, passed in ((2, True), (1, True), (0, False)):
        db_session.add(
            AgentEvalRun(
                agent_name="chat.default_path",
                run_at=today - timedelta(days=day_offset),
                question="q",
                actual_answer="a",
                passed=passed,
                faithfulness_score=1.0 if passed else 0.4,
                tenant_id=tenant_id,
            )
        )
    db_session.commit()

    rows = db_session.exec(
        select(AgentEvalRun)
        .where(AgentEvalRun.agent_name == "chat.default_path")
        .order_by(AgentEvalRun.run_at)
    ).all()
    assert [r.passed for r in rows] == [True, True, False]


def test_the_migration_creates_the_table_it_says_it_does():
    """Runs revision b5d2c8a41f30's own `upgrade()`/`downgrade()` DDL, rather
    than trusting that the model metadata and the migration agree."""
    spec = importlib.util.spec_from_file_location(
        "_mig_b5d2c8a41f30",
        str(__import__("pathlib").Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "b5d2c8a41f30_add_agent_eval_run.py"),
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "f3e8b2a1d6c9"

    temp_engine = sa_create_engine("sqlite:///:memory:")
    with temp_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(agent_eval_run)").fetchall()
            }
            assert {
                "id", "agent_name", "run_at", "question", "expected_answer", "actual_answer",
                "pass", "faithfulness_score", "relevance_score", "accuracy_score",
                "latency_ms", "llm_call_count", "tenant_id", "notes",
            } == columns

            migration.downgrade()
            remaining = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_eval_run'"
            ).fetchall()
            assert remaining == []
    temp_engine.dispose()


def _load_migration(name):
    spec = importlib.util.spec_from_file_location(
        "_mig_" + name.split("_")[0],
        str(__import__("pathlib").Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / name),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_component_score_migration_adds_exactly_three_nullable_columns():
    """Runs `c4a91e77b208`'s own DDL on top of `b5d2c8a41f30`'s, rather than
    trusting that the model metadata and the migration agree. Also asserts the
    chain, because this history has four merge points in it and a wrong
    `down_revision` is how the last two-head incident started."""
    base = _load_migration("b5d2c8a41f30_add_agent_eval_run.py")
    component = _load_migration("c4a91e77b208_add_agent_eval_component_scores.py")

    assert component.down_revision == base.revision == "b5d2c8a41f30"

    temp_engine = sa_create_engine("sqlite:///:memory:")
    with temp_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            base.upgrade()
            before = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(agent_eval_run)").fetchall()
            }
            component.upgrade()
            rows = connection.exec_driver_sql("PRAGMA table_info(agent_eval_run)").fetchall()
            after = {row[1] for row in rows}

            assert after - before == {"context_score", "orchestration_score", "persona_score"}
            # Nullable with no default: an existing row must read as "not
            # scored", never as "scored, and zero".
            for row in rows:
                if row[1] in after - before:
                    assert row[3] == 0 and row[4] is None  # notnull=0, dflt_value=None

            component.downgrade()
            reverted = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(agent_eval_run)").fetchall()
            }
            assert reverted == before
    temp_engine.dispose()


def test_component_scores_round_trip_and_absent_ones_stay_null(db_session):
    db_session.add(
        AgentEvalRun(
            agent_name="sage.agentic_path",
            question="whats the CGST we paid to Rajesh Steel",
            actual_answer="There is no separate CGST figure recorded.",
            passed=True,
            faithfulness_score=1.0,
            context_score=1.0,
            orchestration_score=0.5,
            # Not scored: this turn needed no domain judgement.
            persona_score=None,
            tenant_id=uuid4(),
        )
    )
    db_session.commit()

    row = db_session.exec(select(AgentEvalRun)).one()
    assert (row.context_score, row.orchestration_score) == (1.0, 0.5)
    assert row.persona_score is None


def test_track_eval_result_mirrors_the_component_scores_and_omits_absent_ones(caplog):
    with caplog.at_level(logging.INFO):
        telemetry.track_eval_result(
            "sage.agentic_path",
            "rajesh_steel_cgst",
            False,
            context_score=1.0,
            orchestration_score=0.0,
            persona_score=None,
        )

    record = [r for r in caplog.records if r.getMessage() == telemetry.EVAL_RESULT_EVENT_NAME][-1]
    assert record.context_score == 1.0
    assert record.orchestration_score == 0.0
    # persona is NULL on most turns by design; a 0.0 here would read as "the
    # persona failed on every greeting" in the workbook's trend.
    assert not hasattr(record, "persona_score")


# ---------------------------------------------------------------------------
# The quality telemetry mirror
# ---------------------------------------------------------------------------


def test_track_eval_result_emits_pass_as_a_number_and_omits_absent_scores(caplog):
    with caplog.at_level(logging.INFO):
        telemetry.track_eval_result(
            "chat.default_path",
            "freight_per_vendor",
            True,
            faithfulness_score=1.0,
            relevance_score=0.95,
            accuracy_score=None,
            latency_ms=18422.5,
            llm_call_count=3,
            tenant_id="tenant-1",
        )

    records = [r for r in caplog.records if r.getMessage() == telemetry.EVAL_RESULT_EVENT_NAME]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "microsoft.custom_event.name") == telemetry.EVAL_RESULT_EVENT_NAME
    # A pass-rate is avg(pass) in KQL, so it must be a number, not "True".
    assert getattr(record, "pass") == 1
    assert record.faithfulness_score == 1.0
    assert record.llm_call_count == 3
    # Absent stays absent -- a 0.0 would be a real score in every trend chart.
    assert not hasattr(record, "accuracy_score")


def test_a_broken_emitter_never_breaks_an_eval_run(monkeypatch):
    def _explode(*_args, **_kwargs):
        raise RuntimeError("Application Insights is down")

    monkeypatch.setattr(telemetry, "_emit_event", _explode)
    telemetry.track_eval_result("chat.default_path", "case", True)  # must not raise


# ---------------------------------------------------------------------------
# Per-turn LLM-call counting — the number Feature 21's decision rests on
# ---------------------------------------------------------------------------


def test_the_turn_counter_counts_product_calls_and_excludes_the_judge():
    from scripts.run_agent_eval import _counting_llm_calls

    with _counting_llm_calls() as counter:
        telemetry.track_agent_call("chat.classify", "gpt-5-mini", 10, 2, 100.0, "success", "t")
        telemetry.track_agent_call("chat.sql_generation", "gpt-5-mini", 900, 60, 2500.0, "success", "t")
        telemetry.track_agent_call("chat.sql_summary", "gpt-5-mini", 700, 300, 4000.0, "success", "t")
        # The grader's own spend is real and billable, and is deliberately
        # visible in the cost rollup -- but it is not part of the turn.
        telemetry.track_agent_call("eval.faithfulness", "gpt-5-mini", 1200, 90, 3000.0, "success", "t")

    assert counter.call_count == 3
    assert counter.tokens_in == 1610
    assert [e["agent_name"] for e in counter.events] == [
        "chat.classify",
        "chat.sql_generation",
        "chat.sql_summary",
    ]


def test_a_retry_inside_one_tracked_block_counts_as_two_round_trips():
    """`llm_calls` on the event is what LangChain's callback actually observed:
    a repair retry is a second billable round-trip inside one tracked block."""
    from scripts.run_agent_eval import _counting_llm_calls

    with _counting_llm_calls() as counter:
        telemetry.track_agent_call(
            "chat.sql_generation", "gpt-5-mini", 1800, 120, 5000.0, "success", "t", llm_calls=2
        )

    assert counter.call_count == 2


def test_the_scoring_module_never_lets_a_judge_failure_lose_a_measured_turn():
    """A turn's latency and call count are real measurements. A grader having a
    bad minute must not throw them away."""
    llm = _ScriptedJudge({}, raise_for=(ClaimList, FaithfulnessVerdicts, ScoreWithReason))

    scores = score_answer(question="q", answer="a", context="c", expected_answer="e", llm=llm)

    assert (scores.faithfulness_score, scores.relevance_score, scores.accuracy_score) == (None, None, None)
    assert scores.passed is False
    assert isinstance(scores.note_text(), str)


def test_scores_are_clamped_into_range():
    """A judge that returns 1.4 has misread its own instructions; the stored
    number still has to be a score."""
    assert agent_eval._clamp(1.4) == 1.0
    assert agent_eval._clamp(-0.2) == 0.0
    assert agent_eval._clamp("not a number") is None


# ---------------------------------------------------------------------------
# Feature 23 Track 2 — the combined five-metric judge (2026-08-23)
# ---------------------------------------------------------------------------
# `feature_23_ai_control_tower.md`: "Soft -- one combined judge call, not five
# separate ones". Same scope note as the top of this file: these prove the
# mechanics (one call, the classify-before-score policies survive the merge, the
# new metrics stay out of `passed`, absent still means absent), not how a real
# model scores a real answer.


def _combined(
    *,
    verdicts=(),
    kind=KIND_DIRECT_ANSWER,
    relevance=1.0,
    helpfulness=1.0,
    tone=1.0,
    completeness=1.0,
    accuracy=1.0,
):
    return _ScriptedJudge(
        {
            CombinedSoftVerdict: CombinedSoftVerdict(
                claim_verdicts=[
                    ClaimVerdict(claim=c, supported=s, claim_type=t) for c, s, t in verdicts
                ],
                answer_kind=kind,
                relevance_score=relevance,
                helpfulness_score=helpfulness,
                tone_score=tone,
                completeness_score=completeness,
                reason="scripted",
            ),
            ScoreWithReason: ScoreWithReason(score=accuracy, reason="scripted"),
        }
    )


def test_the_combined_judge_scores_all_five_soft_metrics_in_one_call():
    """The headline requirement: five metrics, one round-trip."""
    llm = _combined(
        verdicts=[("The total is USD 42,300.00", True, CLAIM_TYPE_POSITIVE)],
        relevance=1.0,
        helpfulness=0.7,
        tone=0.4,
        completeness=0.5,
    )

    scores, claims, notes, calls = agent_eval.score_soft_metrics_combined(
        "whose invoice was bigger",
        "The total is USD 42,300.00.",
        "invoice_number | grand_total\nDPS-9981 | 42300.00",
        llm,
    )

    assert calls == 1
    assert len(llm.prompts) == 1
    assert scores == {
        "faithfulness": 1.0,
        "relevance": 1.0,
        "helpfulness": 0.7,
        "tone": 0.4,
        "completeness": 0.5,
    }
    assert claims == ["The total is USD 42,300.00"]
    assert any("helpfulness" in n for n in notes)
    assert any("completeness" in n for n in notes)
    assert any("tone" in n for n in notes)


def test_combined_mode_costs_two_calls_where_separate_mode_costs_four():
    """The cost claim, measured rather than asserted in a comment.

    Compared with `score_persona_component=False` on both sides, so the figure
    isolates the soft-metric merge: the persona component is an orthogonal extra
    judge call that both modes pay identically. With it on, the two are 3 and 5.
    """
    combined_llm = _combined(verdicts=[("x", True, CLAIM_TYPE_POSITIVE)])
    combined = score_answer(
        question="q",
        answer="The total is USD 42,300.00.",
        context="42300.00",
        expected_answer="ref",
        llm=combined_llm,
        combined_judge=True,
        score_persona_component=False,
    )

    separate_llm = _judge(
        claims=["x"],
        verdicts=[("x", True, CLAIM_TYPE_POSITIVE)],
        relevance=1.0,
        accuracy=1.0,
        persona=PersonaVerdict(applicable=False),
    )
    separate = score_answer(
        question="q",
        answer="The total is USD 42,300.00.",
        context="42300.00",
        expected_answer="ref",
        llm=separate_llm,
        score_persona_component=False,
    )

    assert combined.judge_llm_calls == 2  # combined soft + accuracy
    assert separate.judge_llm_calls == 4  # decompose + faithfulness + relevance + accuracy
    assert combined.judge_mode == "combined"
    assert separate.judge_mode == "separate"


def test_score_answer_defaults_to_the_separate_judge():
    """The existing metric series must not be redefined by an import."""
    llm = _judge(
        claims=["x"],
        verdicts=[("x", True, CLAIM_TYPE_POSITIVE)],
        relevance=1.0,
        accuracy=1.0,
        persona=PersonaVerdict(applicable=False),
    )
    scores = score_answer(question="q", answer="a 500.00", context="500.00", llm=llm)
    assert scores.judge_mode == "separate"
    assert (scores.helpfulness_score, scores.completeness_score, scores.tone_score) == (
        None,
        None,
        None,
    )


def test_the_new_soft_metrics_do_not_change_the_pass_decision():
    """Same rule as the component scores: adding a dimension to `passed`
    halfway through a series silently redefines what a pass means."""
    passing = EvalScores(faithfulness_score=1.0, relevance_score=1.0, accuracy_score=1.0)
    assert decide_pass(passing) is True
    passing.helpfulness_score = 0.0
    passing.completeness_score = 0.0
    passing.tone_score = 0.0
    assert decide_pass(passing) is True


def test_combined_faithfulness_excludes_non_factual_claims_from_the_denominator():
    """Failure mode 2's family, carried into the merged judge: a pleasantry the
    decomposition failed to filter must cost nothing, not cost score."""
    llm = _combined(
        verdicts=[
            ("The total is USD 500.00", True, CLAIM_TYPE_POSITIVE),
            ("I can also show you spend summaries", False, CLAIM_TYPE_NON_FACTUAL),
        ]
    )
    scores, _claims, notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "answer", "500.00", llm
    )
    assert scores["faithfulness"] == 1.0
    assert any("non-factual claim(s) excluded" in n for n in notes)


def test_combined_absence_claim_against_an_empty_result_is_supported():
    """Failure mode 3's fix survives the merge: an empty result set is a real
    negative finding, and the executed query is what makes it attributable."""
    llm = _combined(
        verdicts=[("No records were found for Nonexistent Holdings", True, CLAIM_TYPE_ABSENCE)],
        kind=KIND_NO_RESULTS_REPORT,
        relevance=0.0,  # ignored: the kind fixes it
    )
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "what did we spend with Nonexistent Holdings",
        "No records were found for Nonexistent Holdings.",
        "No records found matching the query criteria.",
        llm,
        executed_queries="SELECT ... WHERE vendor_name ILIKE '%Nonexistent Holdings%'",
    )
    assert scores["faithfulness"] == 1.0
    assert scores["relevance"] == 1.0


@pytest.mark.parametrize(
    "kind,expected",
    [
        (KIND_NO_RESULTS_REPORT, 1.0),
        (KIND_OUT_OF_SCOPE_REFUSAL, 1.0),
        (KIND_CAPABILITY_OR_GREETING, 1.0),
        (KIND_OFF_TOPIC, 0.0),
    ],
)
def test_combined_relevance_is_still_fixed_by_kind_not_by_the_judges_number(kind, expected):
    """Failure mode 4's fix survives the merge. The judge returns 0.33 every
    time; only the classification is allowed to decide."""
    llm = _combined(kind=kind, relevance=0.33)
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "an answer", "ctx", llm
    )
    assert scores["relevance"] == expected


@pytest.mark.parametrize("kind", [KIND_DIRECT_ANSWER, KIND_CLARIFYING_QUESTION])
def test_combined_relevance_still_uses_the_judges_number_where_it_is_a_matter_of_degree(kind):
    llm = _combined(kind=kind, relevance=0.4)
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "an answer", "ctx", llm
    )
    assert scores["relevance"] == 0.4


def test_combined_judge_failure_leaves_every_metric_absent_not_zero():
    llm = _ScriptedJudge({}, raise_for=(CombinedSoftVerdict,))
    scores, claims, notes, calls = agent_eval.score_soft_metrics_combined("q", "a", "c", llm)
    assert set(scores.values()) == {None}
    assert claims == []
    assert calls == 1
    assert any("judge unavailable" in n for n in notes)


def test_combined_judge_on_an_empty_answer_makes_no_call_at_all():
    llm = _combined()
    scores, _claims, _notes, calls = agent_eval.score_soft_metrics_combined("q", "   ", "c", llm)
    assert calls == 0
    assert llm.prompts == []
    assert set(scores.values()) == {None}


def test_combined_claims_with_no_evidence_at_all_is_a_real_zero():
    """The one deliberate 0.0, inherited unchanged from `score_faithfulness`:
    nothing ran, nothing was retrieved, and the answer still asserted facts."""
    llm = _combined(verdicts=[("We spent USD 9,000.00", True, CLAIM_TYPE_POSITIVE)])
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "We spent USD 9,000.00.", "", llm, executed_queries=""
    )
    assert scores["faithfulness"] == 0.0


def test_an_answer_that_is_all_greeting_is_not_scored_for_faithfulness():
    llm = _combined(verdicts=[], kind=KIND_CAPABILITY_OR_GREETING)
    scores, claims, notes, _calls = agent_eval.score_soft_metrics_combined(
        "hello", "Hi! I can help with your invoices.", "", llm
    )
    assert scores["faithfulness"] is None
    assert claims == []
    assert any("no factual claims" in n for n in notes)
    # The other four still produce numbers -- a greeting is fully gradeable on
    # relevance, helpfulness, tone and completeness.
    assert scores["relevance"] == 1.0
    assert scores["tone"] == 1.0


def test_the_combined_prompt_asks_for_all_five_dimensions_by_name():
    """The prompt is the contract with the judge. If a dimension is dropped from
    it the schema field still exists and would silently return its default."""
    prompt = agent_eval._build_combined_prompt("q", "a", "ctx", "SELECT 1")
    for heading in ("FAITHFULNESS", "RELEVANCE", "HELPFULNESS", "PERSONA / TONE FIT", "COMPLETENESS"):
        assert heading in prompt
    # Classify-before-score, both times.
    assert prompt.index("assign a `claim_type`") < prompt.index("decide `supported`")
    assert prompt.index("Choose exactly one `answer_kind` FIRST") < prompt.index("Then score:")
    # The evidence, and the instruction that makes an empty result count as some.
    assert "SELECT 1" in prompt
    assert "NOT an absence of evidence" in prompt
    # Each new dimension must be told what it is NOT, or it collapses into the
    # others -- the failure that made relevance unstable in the first place.
    assert "Not 'is it right'" in prompt  # helpfulness is not faithfulness
    assert "Correctness is not tone" in prompt  # tone is not faithfulness
    assert "not against an ideal answer" in prompt  # completeness is bounded by the evidence


def test_the_combined_prompt_is_never_shown_the_reference_answer():
    """Accuracy is judged separately precisely so faithfulness cannot be
    contaminated by the reference. If the reference leaked into this prompt, a
    model could mark a claim supported because the reference says so rather than
    because the evidence does."""
    prompt = agent_eval._build_combined_prompt("q", "a", "the tool returned nothing", None)
    assert "REFERENCE" not in prompt


def test_combined_scores_are_clamped():
    llm = _combined(helpfulness=1.9, tone=-0.5, completeness=0.5, relevance=1.4)
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined("q", "a", "c", llm)
    assert scores["helpfulness"] == 1.0
    assert scores["tone"] == 0.0
    assert scores["relevance"] == 1.0


def test_combined_mode_still_produces_the_deterministic_component_scores():
    """The two free, no-judge components must not be lost by switching modes."""
    llm = _combined(verdicts=[("The total is USD 42,300.00", True, CLAIM_TYPE_POSITIVE)])
    scores = score_answer(
        question="q",
        answer="The total is USD 42,300.00.",
        context="invoice_number | grand_total\nDPS-9981 | 42300.00",
        llm=llm,
        expected_invoice_ids=("DPS-9981",),
        fetched_invoice_ids=("DPS-9981",),
        score_persona_component=False,
    )
    assert scores.context_score == 1.0
    assert scores.orchestration_score == 1.0
    assert scores.persona_score is None


def test_track_eval_result_carries_the_new_soft_metrics_as_event_extras(caplog):
    """No migration was added for these three; they ride the event's
    `**extra_attributes` so the workbook can chart them."""
    caplog.set_level(logging.INFO, logger="invoice_be_telemetry")
    telemetry.track_eval_result(
        "chat.default",
        "case-x",
        True,
        helpfulness_score=0.7,
        tone_score=1.0,
        completeness_score=0.5,
        judge_mode="combined",
    )
    record = next(r for r in caplog.records if getattr(r, "case_id", None) == "case-x")
    assert record.helpfulness_score == 0.7
    assert record.tone_score == 1.0
    assert record.completeness_score == 0.5
    assert record.judge_mode == "combined"


# ---------------------------------------------------------------------------
# The extended golden case set (Feature 23 Track 2)
# ---------------------------------------------------------------------------


def _golden_cases():
    # Moved out of tests/ to benchmarks/ on 2026-08-23 -- see benchmarks/__init__.py.
    from benchmarks.agent_eval_golden_sample import ALL_ROWS, CASES

    return CASES, ALL_ROWS


def test_the_case_set_was_extended_not_rewritten():
    """The scope was 'more cases, not a full rewrite'. Every original case id
    must still be present."""
    cases, _rows = _golden_cases()
    ids = {c.case_id for c in cases}
    original = {
        "titan_steel_payment_status",
        "rajesh_steel_cgst",
        "datapipe_vs_stratedge",
        "freight_per_vendor",
        "bolts_reconciliation",
        "zero_result_vendor",
        "payment_terms_document",
        "out_of_scope_code_request",
        "greeting_no_tool",
        "large_invoice_full_detail",
        "small_invoice_full_detail",
    }
    assert original <= ids
    assert len(cases) > len(original)


def test_every_case_id_is_unique_and_every_case_states_why_it_is_on_file():
    cases, _rows = _golden_cases()
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case.why_on_file.strip()
        assert case.source.strip()
        assert case.question.strip()


def test_every_expected_invoice_number_exists_in_the_seeded_fixture():
    """A reference answer naming an invoice the fixture does not contain would
    make `context_score` unachievable and the case permanently red.

    Tenant-aware since Wave 3 (2026-08-24), and it has to be: `TSD-620458` is a
    real invoice number in BOTH the base tenant and the US tenant, with
    different totals, so a flat union of every seeded number would pass this
    test for a case that names the right number against the wrong tenant --
    exactly the confusion the separate tenant ids exist to prevent.
    """
    from benchmarks.region_seed_fixtures import REGION_TENANTS

    cases, rows = _golden_cases()
    seeded_by_tenant = {
        tenant_id: {row["invoice_number"] for row in region["rows"]}
        for tenant_id, region in REGION_TENANTS.items()
    }
    base = {row["invoice_number"] for row in rows}
    for case in cases:
        seeded = seeded_by_tenant.get(case.tenant_id, base)
        for number in case.expected_invoice_numbers or ():
            assert number in seeded, (
                f"{case.case_id} expects invoice {number}, which is not seeded in "
                f"tenant {case.tenant_id}"
            )


# ---------------------------------------------------------------------------
# The regional banks (Feature 23 Wave 3, 2026-08-24)
# ---------------------------------------------------------------------------


def test_the_regional_cases_were_added_without_moving_any_existing_case():
    """Wave 3's rule: extend, do not disturb. Every pre-Wave-3 case must still
    be bound to the base tenant, because all twenty reference answers are
    computed or stated against those nine rows and nothing else."""
    from benchmarks.agent_eval_golden_sample import TENANT_ID
    from benchmarks.region_seed_fixtures import REGION_TENANTS

    cases, _rows = _golden_cases()
    regional = [c for c in cases if c.tenant_id != TENANT_ID]
    base = [c for c in cases if c.tenant_id == TENANT_ID]
    assert len(base) == 20, "an existing case changed tenant"
    assert len(regional) == 15
    # Breadth over volume was the explicit goal -- five per region, not fifteen
    # drained out of India.
    per_tenant = {tenant_id: 0 for tenant_id in REGION_TENANTS}
    for case in regional:
        assert case.tenant_id in REGION_TENANTS, case.case_id
        per_tenant[case.tenant_id] += 1
    assert set(per_tenant.values()) == {5}


def test_regional_rows_reconcile_against_their_own_line_items():
    """Every figure in a regional reference answer is stated to the cent off
    these rows, so the rows themselves have to add up: line amounts sum to the
    subtotal, and subtotal + tax is the grand total. The deliberate qty x rate
    mismatches are NOT repaired -- they are the ground-truth defects three of
    the ported questions are about."""
    import json as _json

    from benchmarks.region_seed_fixtures import REGION_TENANTS

    for region in REGION_TENANTS.values():
        for row in region["rows"]:
            items = _json.loads(row["items"])
            line_sum = round(sum(item["amount"] for item in items), 2)
            assert line_sum == pytest.approx(row["subtotal"]), row["invoice_number"]
            assert round(row["subtotal"] + row["tax_amount"], 2) == pytest.approx(
                row["grand_total"]
            ), row["invoice_number"]


def test_the_regional_tenants_are_isolated_from_the_base_fixture():
    """The reason there are four tenants and not one. Vendor names and even an
    invoice number are shared across them with different figures, which is only
    safe because a case is asked against exactly one tenant id."""
    from benchmarks.agent_eval_golden_sample import ALL_ROWS, TENANT_ID
    from benchmarks.region_seed_fixtures import REGION_TENANTS, US_ROWS

    assert TENANT_ID not in REGION_TENANTS
    assert len(set(REGION_TENANTS)) == 3
    base_numbers = {row["invoice_number"] for row in ALL_ROWS}
    us_numbers = {row["invoice_number"] for row in US_ROWS}
    # Stated as an assertion rather than a comment: the collision is real.
    assert "TSD-620458" in base_numbers & us_numbers
    base_titan = next(r for r in ALL_ROWS if r["invoice_number"] == "TSD-620458")
    us_titan = next(r for r in US_ROWS if r["invoice_number"] == "TSD-620458")
    assert base_titan["grand_total"] != us_titan["grand_total"]


def test_each_tenant_gets_its_own_snapshot_and_its_own_document_chunks():
    """Handing a turn another tenant's grounding facts is the failure
    `tenant_stats_summary()`'s own docstring records. With four tenants there
    are three more ways to make it, so the selection is a function, not a
    call-site choice."""
    from benchmarks.agent_eval_golden_sample import (
        TENANT_ID,
        chunks_for_tenant,
        stats_for_tenant,
        tenant_stats_summary,
    )
    from benchmarks.region_seed_fixtures import REGION_TENANTS

    assert stats_for_tenant(TENANT_ID) == tenant_stats_summary()
    base_chunk_ids = {chunk["id"] for chunk in chunks_for_tenant(TENANT_ID)}
    for tenant_id, region in REGION_TENANTS.items():
        stats = stats_for_tenant(tenant_id)
        assert stats != tenant_stats_summary()
        assert "9 total invoices" in stats
        assert "No invoice in this tenant has a due date recorded." in stats
        chunk_ids = {chunk["id"] for chunk in chunks_for_tenant(tenant_id)}
        assert chunk_ids == {chunk["id"] for chunk in region["chunks"]}
        assert not chunk_ids & base_chunk_ids


def test_every_regional_chunk_names_the_invoice_it_belongs_to():
    """`scripts/run_agent_eval.py` binds each chunk to its row's generated id so
    a `get_full_record` fetch returns a page. A chunk with no entry here would
    be silently unreachable on the agentic path."""
    from benchmarks.region_seed_fixtures import CHUNK_INVOICE_NUMBERS, REGION_TENANTS

    for region in REGION_TENANTS.values():
        numbers = {row["invoice_number"] for row in region["rows"]}
        for chunk in region["chunks"]:
            invoice_number = CHUNK_INVOICE_NUMBERS.get(chunk["id"])
            assert invoice_number, f"{chunk['id']} is not bound to an invoice"
            assert invoice_number in numbers


def test_seed_writes_to_the_named_tenant_and_fills_the_regional_columns():
    """`_seed` gained a `tenant_id` and three optional columns for Wave 3. Both
    halves are asserted against a real insert rather than read off the SQL."""
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine, text

    from benchmarks.region_seed_fixtures import US_ROWS, US_TENANT_ID
    from benchmarks.sage_seed_fixtures import _seed

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session, US_ROWS, tenant_id=US_TENANT_ID)
        row = session.execute(
            text(
                "SELECT tenant_id, po_number, subtotal, due_date, sa_alerts, customer_name, "
                "flow_direction FROM invoice WHERE invoice_number = 'IEQ-US-9002'"
            )
        ).one()
        assert row[0] == US_TENANT_ID
        assert row[1] is None
        assert row[2] == 6200.00
        assert row[3] is None  # ground truth: none of these invoices prints a due date
        assert "subtotal_mismatch" in row[4]
        assert row[5] == "Fieldstone Analytics LLC"
        assert row[6] == "OUTBOUND"
        titan = session.execute(
            text("SELECT po_number, sa_alerts FROM invoice WHERE invoice_number = 'TSD-620458'")
        ).one()
        assert titan[0] == "PO-71004"
        assert "line_item_calculation_mismatch" in titan[1]
    engine.dispose()


def test_the_threshold_case_is_computed_over_every_seeded_row_not_a_typed_subset():
    """The concrete drift this guards against happened while the case was being
    written: `ALL_ROWS` is nine rows, not the seven the incident history
    contributes, and a hand-typed 'vendors over USD 20,000' answer omitted the
    USD 271,019.63 fixture invoice."""
    cases, rows = _golden_cases()
    case = next(c for c in cases if c.case_id == "all_vendors_over_twenty_thousand")
    expected = {
        row["invoice_number"]
        for row in rows
        if row["currency"] == "USD" and float(row["grand_total"]) > 20000
    }
    assert set(case.expected_invoice_numbers) == expected
    for number in expected:
        assert number in case.expected_answer


def test_the_cross_currency_case_states_both_currency_totals_exactly():
    cases, rows = _golden_cases()
    case = next(c for c in cases if c.case_id == "cross_currency_total_refused")
    by_currency: dict = {}
    for row in rows:
        by_currency[row["currency"]] = by_currency.get(row["currency"], 0.0) + float(
            row["grand_total"]
        )
    for currency, total in by_currency.items():
        assert f"{currency} {total:,.2f}" in case.expected_answer


def test_each_new_soft_metric_has_cases_that_can_actually_move_it():
    """The reason for extending the set at all. A single-fact lookup cannot be
    incomplete, and a neutrally-phrased question cannot show a tone failure."""
    cases, _rows = _golden_cases()
    by_id = {c.case_id: c for c in cases}
    completeness = [
        "multi_part_totals_and_dates",
        "all_vendors_over_twenty_thousand",
        "two_vendors_two_questions",
        "line_item_breakdown_completeness",
    ]
    helpfulness = ["unsupported_field_asks_for_alternative", "zero_result_with_useful_redirect"]
    tone = ["hostile_user_tone", "internals_probe_no_leak"]
    for case_id in completeness + helpfulness + tone:
        assert case_id in by_id, f"{case_id} missing from the golden sample"
    # A completeness case is one whose reference answer states that a partial
    # but otherwise-correct answer is wrong. That property, not the question's
    # punctuation, is what makes the metric able to move on it.
    for case_id in completeness:
        assert "incomplete" in by_id[case_id].expected_answer.lower(), case_id
    # A helpfulness case is one whose correct answer is a negative, so the whole
    # score is the difference between a dead end and a useful redirect.
    for case_id in helpfulness:
        reference = by_id[case_id].expected_answer.lower()
        assert "not tracked" in reference or "no records" in reference or "nothing matches" in reference
    # A tone case has to name the voice failure it is looking for.
    for case_id in tone:
        reference = by_id[case_id].expected_answer.lower()
        assert "tone" in reference or "sql" in reference


# ---------------------------------------------------------------------------
# Completeness's classify-then-fix policy — found by running, 2026-08-23
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected",
    [
        (KIND_OUT_OF_SCOPE_REFUSAL, 1.0),
        (KIND_CAPABILITY_OR_GREETING, 1.0),
        (KIND_OFF_TOPIC, 0.0),
    ],
)
def test_completeness_is_fixed_by_kind_where_it_is_definitional(kind, expected):
    """The concrete failure this closes, from the first real combined-judge run:
    `internals_probe_no_leak` ("what SQL did you run?") was declined correctly
    and scored completeness 0.00, the judge reasoning that the substantive
    request was unaddressed. Correct on a rubric phrased as "covers what was
    asked" -- and that is failure mode 4's shape, one metric down."""
    llm = _combined(kind=kind, completeness=0.0 if expected else 1.0)
    scores, _claims, notes, _calls = agent_eval.score_soft_metrics_combined(
        "what SQL did you run?", "I can't share that; here is what I can do.", "ctx", llm
    )
    assert scores["completeness"] == expected
    assert any("fixed by kind" in n for n in notes if n.startswith("completeness"))


@pytest.mark.parametrize(
    "kind", [KIND_DIRECT_ANSWER, KIND_CLARIFYING_QUESTION, KIND_NO_RESULTS_REPORT]
)
def test_completeness_still_uses_the_judges_number_where_it_is_a_matter_of_degree(kind):
    """A two-part question CAN be half answered, and a no-results report can
    still omit half of what was asked about. Only the definitional kinds are
    taken out of the judge's hands."""
    llm = _combined(kind=kind, completeness=0.5)
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "an answer", "ctx", llm
    )
    assert scores["completeness"] == 0.5


def test_completeness_and_relevance_cannot_disagree_about_the_response_kind():
    """Both read the same `answer_kind` off the same verdict. If completeness
    re-derived it, a refusal could be relevance-1.0 and completeness-0.0 in the
    same call, which is the incoherence this whole classify-first pattern
    exists to remove."""
    llm = _combined(kind=KIND_OUT_OF_SCOPE_REFUSAL, relevance=0.0, completeness=0.0)
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "I can't help with that.", "ctx", llm
    )
    assert scores["relevance"] == 1.0
    assert scores["completeness"] == 1.0


def test_the_completeness_rubric_tells_the_judge_a_refusal_is_complete():
    prompt = agent_eval._build_combined_prompt("q", "a", "ctx", None)
    assert "a correct refusal is complete" in prompt
    assert "withholding what it was right to withhold" in prompt


def test_an_unrecognised_kind_still_yields_a_completeness_number():
    """Same fallback as relevance: an older double or an invented label must
    lose the classification, not the score."""
    llm = _combined(kind="something_new", completeness=0.6)
    scores, _claims, _notes, _calls = agent_eval.score_soft_metrics_combined(
        "q", "a", "ctx", llm
    )
    assert scores["completeness"] == 0.6
    assert scores["relevance"] == 1.0  # the judged number, kind unrecognised
