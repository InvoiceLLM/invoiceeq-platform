"""Feature 23 / Gap 304 half (2) — scoring real production turns.

What these tests are actually pinning, in the order the risk sits:

1. **No customer text lands in `agent_eval_run`.** That was the founder's
   decision and it is the one property a future refactor could quietly undo (the
   easiest "improvement" here is to store the question for debuggability). Three
   tests cover it: the row's own columns, the `notes` string (the judge's native
   notes quote claims lifted out of the answer, so they are dropped), and the DB
   CHECK that makes the golden invariant survive the columns becoming nullable.
2. **A judge outage does not look like a quality collapse.** `decide_pass()`
   returns False for "nothing could be graded", which is right for the nightly
   harness and wrong for live traffic, so no row is written at all in that case.
3. **The turn is never affected.** Judging happens after the response, on a
   background thread, behind a default-off flag, and swallows everything.
4. **The evidence really reaches the judge**, for both routes, without being
   persisted or cached — driven through the real `run_query_agent()` rather than
   asserted against a stub, because the whole point of the plumbing is that
   `db_result` and the RAG chunk text never leave that function today.
"""

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import telemetry
from dependencies import MOCK_TENANT_ID
from models import AgentEvalRun
from services.agent_eval import ClaimVerdict, CombinedSoftVerdict, PersonaVerdict
from services.online_quality_judge import judge_turn, submit_turn_judgement

TENANT_ID = str(MOCK_TENANT_ID)

_ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(_ENGINE)
    with Session(_ENGINE) as session:
        yield session
    SQLModel.metadata.drop_all(_ENGINE)


@pytest.fixture(name="factory")
def factory_fixture(db_session):  # noqa: ARG001 - creates the schema
    """A `session_factory` for `judge_turn()` on the same in-memory database."""
    return lambda: Session(_ENGINE)


class _ScriptedJudgeLLM:
    """Returns a canned verdict per schema, with no network anywhere.

    Shaped like the real thing rather than a bare MagicMock: `_invoke_structured`
    calls `with_structured_output(schema).invoke(prompt)` inside
    `tracked_llm_call()`, and the score arithmetic downstream reads real pydantic
    attributes.
    """

    def __init__(self, combined=None, persona=None, raises=False):
        self.combined = combined
        self.persona = persona
        self.raises = raises
        self.model_name = "gpt-5-mini-fake"
        self.prompts = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                if outer.raises:
                    raise RuntimeError("judge unreachable")
                if schema is PersonaVerdict:
                    return outer.persona
                return outer.combined

        return _Structured()

    def invoke(self, prompt):  # pragma: no cover - the judge never calls this
        raise AssertionError("the judge only uses structured output")


def _combined(**overrides):
    payload = dict(
        claim_verdicts=[
            ClaimVerdict(claim="Total spend was USD 1,200.", claim_type="positive_fact", supported=True)
        ],
        answer_kind="direct_answer",
        relevance_score=0.9,
        helpfulness_score=0.8,
        tone_score=0.95,
        completeness_score=0.7,
        reason="Reads fine.",
    )
    payload.update(overrides)
    return CombinedSoftVerdict(**payload)


def _judge(factory, **overrides):
    """One `judge_turn()` call with everything a real turn would carry."""
    kwargs = dict(
        question="What did we spend with Acme last month?",
        answer="Total spend was USD 1,200.\n\n### Query Results\n\nid | total\n--- | ---\n1 | 1200",
        evidence={
            "route": "SQL",
            "context": "DATABASE RESULTS:\nid | total\n--- | ---\n1 | 1200",
            "executed_queries": "SELECT id, grand_total FROM invoice",
        },
        generated_sql="SELECT id, grand_total FROM invoice",
        tenant_id=TENANT_ID,
        message_id=str(uuid4()),
        latency_ms=1234.5,
        llm=_ScriptedJudgeLLM(combined=_combined(), persona=PersonaVerdict(applicable=True, score=0.9)),
        session_factory=factory,
    )
    kwargs.update(overrides)
    judge_turn(**kwargs)
    return kwargs


def _rows(session):
    return session.exec(select(AgentEvalRun)).all()


# ---------------------------------------------------------------------------
# 1. What is stored — and what is deliberately not
# ---------------------------------------------------------------------------


def test_a_production_row_stores_scores_and_a_message_id_but_no_customer_text(db_session, factory):
    kwargs = _judge(factory)

    row = _rows(db_session)[0]
    assert row.run_source == telemetry.RUN_SOURCE_PRODUCTION
    assert row.message_id == UUID(kwargs["message_id"])
    # The founder's decision, pinned: the question the customer typed and the
    # answer they were given live in `chatmessage`, and this table points at
    # them rather than holding a second copy.
    assert row.question is None
    assert row.actual_answer is None
    assert row.expected_answer is None
    # ...but the measurement itself is really there.
    assert row.faithfulness_score == 1.0
    assert row.relevance_score == 0.9
    assert row.persona_score == 0.9
    assert row.latency_ms == pytest.approx(1234.5)
    assert row.agent_name == "chat.default_path"


def test_notes_carry_no_text_lifted_out_of_the_answer(db_session, factory):
    """`EvalScores.note_text()` embeds unsupported claims verbatim — which are
    sentences from the customer's answer. It is dropped for exactly that reason,
    and this test fails if someone reinstates it for debuggability."""
    combined = _combined(
        claim_verdicts=[
            ClaimVerdict(
                claim="Acme invoiced a secret settlement of USD 90,000.",
                claim_type="positive_fact",
                supported=False,
            )
        ]
    )
    _judge(
        factory,
        llm=_ScriptedJudgeLLM(combined=combined, persona=PersonaVerdict(applicable=False)),
    )

    notes = _rows(db_session)[0].notes
    assert "secret settlement" not in notes
    assert "unsupported" not in notes
    # What a human reading one row does get instead.
    assert "run_source=production" in notes
    assert "route=SQL" in notes
    assert "pass_basis=faithfulness+relevance" in notes


def test_accuracy_and_context_are_null_because_live_traffic_has_no_reference(db_session, factory):
    """Not a gap. Both need something the golden bank has and production cannot:
    an expected answer, and a known-correct invoice set."""
    _judge(factory)

    row = _rows(db_session)[0]
    assert row.accuracy_score is None
    assert row.context_score is None
    # The two that *are* computable without a reference stay populated, so the
    # component-level decomposition is not lost wholesale.
    assert row.orchestration_score is not None
    assert row.persona_score is not None


def test_the_check_constraint_still_forbids_a_row_with_neither_text_nor_pointer(db_session):
    """`question`/`actual_answer` became nullable for the production shape. The
    CHECK is what stops that from also permitting a corrupt golden row."""
    db_session.add(
        AgentEvalRun(agent_name="chat.default_path", tenant_id=uuid4(), run_source="golden")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ---------------------------------------------------------------------------
# 2. Pass semantics, and the judge-outage case
# ---------------------------------------------------------------------------


def test_pass_is_decided_on_faithfulness_and_relevance_only(db_session, factory):
    """A golden row's pass includes accuracy; a production row's cannot. Same
    `decide_pass()`, fewer inputs — so the two rates are not comparable, which is
    why every consumer filters `run_source`."""
    _judge(
        factory,
        llm=_ScriptedJudgeLLM(
            # Faithfulness 0/1 -> below the floor. Nothing else can rescue it.
            combined=_combined(
                claim_verdicts=[
                    ClaimVerdict(claim="x", claim_type="positive_fact", supported=False)
                ],
                relevance_score=1.0,
            ),
            persona=PersonaVerdict(applicable=True, score=1.0),
        ),
    )
    assert _rows(db_session)[0].passed is False

    _judge(factory)
    assert _rows(db_session)[1].passed is True


def test_an_unreachable_judge_writes_no_row_at_all(db_session, factory, caplog):
    """The alternative — a row with every score NULL and `pass` False — would
    render a judge outage as a live quality collapse in the same chart the
    golden bank is plotted in."""
    with caplog.at_level(logging.DEBUG):
        _judge(factory, llm=_ScriptedJudgeLLM(raises=True))

    assert _rows(db_session) == []


def test_an_empty_answer_is_not_judged(db_session, factory):
    _judge(factory, answer="   ")
    assert _rows(db_session) == []


def test_a_turn_with_no_evidence_payload_is_not_judged(db_session, factory):
    """A cache hit, the SAGE path and the router's error fallback all return a
    dict with no `judge_evidence`. Judging them would grade real claims against
    an empty context, which the judge correctly treats as 0.00 faithfulness —
    a harness defect, not a model result."""
    _judge(factory, evidence=None)
    assert _rows(db_session) == []


# ---------------------------------------------------------------------------
# 3. The turn is never affected
# ---------------------------------------------------------------------------


def test_a_persistence_failure_is_swallowed(db_session, factory):  # noqa: ARG001
    """The turn was committed and returned before this ran. Nothing here is
    allowed to surface."""

    def _exploding_factory():
        raise RuntimeError("database gone")

    # No exception, and no crash on the telemetry mirror either.
    _judge(factory, session_factory=_exploding_factory)


def test_a_judge_that_returns_garbage_is_swallowed(factory):
    llm = MagicMock()
    llm.with_structured_output.side_effect = RuntimeError("no such method")
    _judge(factory, llm=llm)


def test_the_telemetry_mirror_is_tagged_as_production(db_session, factory, caplog):  # noqa: ARG001
    with caplog.at_level(logging.INFO):
        kwargs = _judge(factory)

    events = [
        r
        for r in caplog.records
        if getattr(r, "microsoft.custom_event.name", None) == telemetry.EVAL_RESULT_EVENT_NAME
    ]
    assert len(events) == 1
    event = events[0]
    assert event.run_source == telemetry.RUN_SOURCE_PRODUCTION
    # `case_id` is the message id: a stable per-turn identifier that is not
    # customer text.
    assert event.case_id == kwargs["message_id"]
    assert event.tenant_id == TENANT_ID
    assert event.judge_mode == "combined"
    # The three soft metrics with no column ride the event, same as golden runs.
    assert event.helpfulness_score == 0.8
    assert event.tone_score == 0.95
    assert event.completeness_score == 0.7
    # Absent-stays-absent: accuracy has no value here, so it has no field.
    assert not hasattr(event, "accuracy_score")


def test_the_flag_is_off_by_default_and_nothing_is_submitted():
    """Default off, and off costs the turn literally nothing — the pool is never
    touched, so no thread and no import happen on the request path."""
    from config import get_settings

    assert get_settings().ENABLE_PRODUCTION_QUALITY_JUDGE is False

    with patch("routers.chat._chat_background_pool") as pool:
        submit_turn_judgement(question="q", answer="a", evidence={}, tenant_id=TENANT_ID,
                              message_id=str(uuid4()))
    assert pool.submit.called is False


def test_the_flag_on_submits_to_the_existing_chat_background_pool(monkeypatch):
    import config

    monkeypatch.setattr(config.settings, "ENABLE_PRODUCTION_QUALITY_JUDGE", True)

    with patch("routers.chat._chat_background_pool") as pool:
        submit_turn_judgement(question="q", answer="a", evidence={}, tenant_id=TENANT_ID,
                              message_id=str(uuid4()))

    assert pool.submit.called
    assert pool.submit.call_args.args[0] is judge_turn


def test_submitting_never_raises_even_if_the_pool_is_broken(monkeypatch):
    import config

    monkeypatch.setattr(config.settings, "ENABLE_PRODUCTION_QUALITY_JUDGE", True)

    with patch("routers.chat._chat_background_pool") as pool:
        pool.submit.side_effect = RuntimeError("cannot schedule new futures after shutdown")
        submit_turn_judgement(question="q", answer="a", evidence={}, tenant_id=TENANT_ID,
                              message_id=str(uuid4()))


def test_the_appended_results_table_and_citations_are_not_graded(factory):
    """`run_query_agent()` staples the results table and citation links onto the
    model's prose. Grading the model on text it did not write measures the
    formatter — the golden harness strips the same two markers."""
    llm = _ScriptedJudgeLLM(combined=_combined(), persona=PersonaVerdict(applicable=False))
    _judge(
        factory,
        answer="Prose only.\n\n### Query Results\n\nid | total\n--- | ---\n1 | 2\n\n**Citations:**\n[a](b)",
        llm=llm,
    )
    combined_prompt = llm.prompts[0]
    assert "Prose only." in combined_prompt
    assert "### Query Results" not in combined_prompt
    assert "**Citations:**" not in combined_prompt


# ---------------------------------------------------------------------------
# 4. Evidence plumbing — driven through the real agent, both routes
# ---------------------------------------------------------------------------


class _ScriptedSqlLLM:
    """One scripted SQL-generation result, then a fixed summary answer.

    Same shape as `tests/test_telemetry.py`'s Gap 305 harness, kept local so this
    file runs on its own.
    """

    def __init__(self, sql):
        self._sql = sql
        self.model_name = "gpt-5-mini-fake"

    def with_structured_output(self, schema):  # noqa: ARG002 - shape only
        outer = self

        class _Structured:
            def invoke(self, prompt):  # noqa: ARG002 - shape only
                return MagicMock(sql=outer._sql, explanation_or_error=None)

        return _Structured()

    def invoke(self, prompt):  # noqa: ARG002 - shape only
        return MagicMock(content="Formatted summary.")


def _run_route(db_session, llm, message, route, *, execute=None, chunks=None, cached=None):
    from contextlib import ExitStack

    from agents import query_agent

    patches = [
        patch("agents.query_agent.classify_query", return_value=route),
        patch("agents.query_agent.query_invoice_chunks", return_value=chunks or []),
        patch("agents.query_agent.get_llm", return_value=llm),
        patch("agents.query_agent.get_cached_answer", return_value=cached),
        patch("agents.query_agent.set_cached_answer"),
        patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
    ]
    if execute is not None:
        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=execute))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return query_agent.run_query_agent(str(uuid4()), message, TENANT_ID, db_session)


def test_the_sql_route_returns_its_db_result_as_judge_evidence(db_session):
    """`db_result` is a local variable that never left `run_query_agent()`. It is
    the only faithfulness evidence a SQL turn has, and it is not persisted
    anywhere — `ChatMessage` keeps the SQL and the invoice ids, not the rows."""
    table = "\n\nid | grand_total\n--- | ---\nINV-1 | 1200"

    def _execute(sql, tenant_id, db_sess, snapshot=None):  # noqa: ARG001 - shape only
        return table

    result = _run_route(
        db_session,
        _ScriptedSqlLLM("SELECT id, grand_total FROM invoice"),
        "what did we spend with acme?",
        "SQL",
        execute=_execute,
    )

    evidence = result["judge_evidence"]
    assert evidence["route"] == "SQL"
    assert "DATABASE RESULTS:" in evidence["context"]
    assert "INV-1" in evidence["context"]
    # The other half: what was *asked for*. Without it a correct "no records for
    # X" answer is unscoreable (agent_eval.py's failure mode 3).
    assert evidence["executed_queries"] == "SELECT id, grand_total FROM invoice"


def test_the_rag_route_returns_chunk_text_as_judge_evidence(db_session):
    """The reason this had to be an in-process hook rather than a batch scorer
    reading Postgres back: only citations are persisted, never the chunk text."""
    chunks = [
        {
            "document": "Invoice INV-9 from Globex covers freight of USD 40.",
            "metadata": {"invoice_id": str(uuid4()), "vendor_name": "Globex", "page": 2},
        }
    ]
    llm = MagicMock()
    llm.model_name = "gpt-5-mini-fake"
    llm.invoke.return_value = MagicMock(content="Globex billed USD 40 of freight.")

    result = _run_route(db_session, llm, "what did globex bill for freight?", "RAG", chunks=chunks)

    evidence = result["judge_evidence"]
    assert evidence["route"] == "RAG"
    assert "DOCUMENT CHUNK:" in evidence["context"]
    assert "covers freight of USD 40" in evidence["context"]
    assert evidence["executed_queries"] == ""


def test_judge_evidence_is_attached_after_the_cache_write_not_before(db_session):
    """Two things at once: the Redis payload keeps the size it had before this
    change, and a cache hit is therefore not re-judged from an empty context."""
    import json

    def _execute(sql, tenant_id, db_sess, snapshot=None):  # noqa: ARG001 - shape only
        return "\n\nid | grand_total\n--- | ---\nINV-1 | 1200"

    # Serialized at call time, exactly as `set_cached_answer()` itself does it.
    # Asserting against `call_args` would prove nothing: the mock holds the same
    # dict object the function mutates afterwards, so it would show the evidence
    # that the real Redis write (a `json.dumps` on the spot) never saw.
    captured = {}

    # `rules_version` is Gap 438's fourth parameter (the tenant's enabled-rule
    # hash, which the cache key now carries). Accepted with a default so this
    # stub matches the real signature without asserting on a value this test is
    # not about.
    def _capture(tenant_id, user_message, result, rules_version=None):  # noqa: ARG001 - shape only
        captured["payload"] = json.dumps(result)

    with patch("agents.query_agent.set_cached_answer", side_effect=_capture) as cache_write:
        with patch("agents.query_agent.classify_query", return_value="SQL"), \
             patch("agents.query_agent.query_invoice_chunks", return_value=[]), \
             patch("agents.query_agent.get_llm", return_value=_ScriptedSqlLLM("SELECT 1")), \
             patch("agents.query_agent.get_cached_answer", return_value=None), \
             patch("agents.query_agent._get_tenant_stats_summary", return_value=""), \
             patch("agents.query_agent.execute_generated_sql", side_effect=_execute):
            from agents import query_agent

            query_agent.run_query_agent(str(uuid4()), "spend?", TENANT_ID, db_session)

    assert cache_write.called
    assert "judge_evidence" not in captured["payload"]
    assert "INV-1" in captured["payload"]  # the payload itself is otherwise unchanged


def test_a_cached_turn_carries_no_evidence_and_is_therefore_skipped(db_session):
    cached = {
        "content": "Total spend was USD 1,200.",
        "generated_sql": "SELECT 1",
        "citations": [],
        "result_invoice_ids": [],
    }
    result = _run_route(db_session, MagicMock(), "spend?", "SQL", cached=cached)

    assert result is cached
    assert "judge_evidence" not in result


def test_judge_evidence_is_not_written_to_the_chat_message(db_session):
    """It is transient by construction: `ChatMessage` has no column for it and
    the router builds the row from named fields, so this is a regression guard
    against someone widening that later."""
    from models import ChatMessage

    assert not hasattr(ChatMessage, "judge_evidence")
    _ = db_session
