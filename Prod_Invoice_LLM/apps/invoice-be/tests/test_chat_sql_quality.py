"""Group 2 (chat SQL quality) — BE Gaps 241, 242 and 237 step 2 + the step-3
hedge's own trigger-condition bug. All of it lands in `agents/query_agent.py`'s
SQL route.

Scope note, deliberately stated up front: these are mocked unit tests, so they
can only assert the *mechanics* — that the rules reach the prompt, that the
prior turn's SQL is handed over, that the null-SQL retry happens once, that the
hedge fires on the shape the live repro actually produced. They cannot validate
prompt *behaviour* against a real model. BE Gap 226 is this repo's precedent for
why that distinction matters (a prompt fix passed the mocked suite and caused a
worse live regression). The behavioural evidence for this pass is statistical,
across repeated live runs of `tests/gap237_sql_repro.py` — recorded in
`docs/test_evidence/gap237_step2_fix_2026-08-17/` and in the tracker, not here.
"""
import json
import os
import re
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timedelta

import pytest
from sqlmodel import SQLModel, create_engine, Session, text
from sqlalchemy.pool import StaticPool

os.environ["MOCK_EMBEDDINGS"] = "true"

from dependencies import MOCK_TENANT_ID
from models import ChatMessage, Invoice
from agents import query_agent, sage_prompts
from agents.query_agent import (
    _NO_FRESH_QUERY_NOTE,
    _NULL_SQL_FOLLOWUP_RETRY_DIRECTIVE,
    get_prior_turn_sql,
)
from agents.query_tools import parse_results_table

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed_invoice(db_session, **kwargs):
    defaults = dict(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/inv.pdf",
        flow_direction="INBOUND",
        status="COMPLETED",
        currency="USD",
    )
    defaults.update(kwargs)
    inv = Invoice(**defaults)
    db_session.add(inv)
    db_session.commit()
    return inv


def _seed_turn(db_session, session_id, *, content, sql=None, ids=None, minutes_ago=5):
    """One prior assistant turn in a chat session."""
    msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="assistant",
        content=content,
        generated_sql=sql,
        result_invoice_ids=ids or [],
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db_session.add(msg)
    db_session.commit()
    return msg


class _RecordingLLM:
    """Captures every prompt the SQL route sends, and replays a scripted list of
    SQLGenerationSchema-ish results (one per structured call)."""

    def __init__(self, sql_results, summary="Formatted summary."):
        self._sql_results = list(sql_results)
        self._summary = summary
        self.prompts = []
        # Kept separate from `prompts` on purpose: several tests below assert on
        # len(llm.prompts) to count SQL-generation round-trips, so the summary
        # call must not land in the same list.
        self.summary_prompts = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                if not outer._sql_results:
                    raise AssertionError("SQL generation called more times than scripted")
                return outer._sql_results.pop(0)

        return _Structured()

    def invoke(self, prompt):
        self.summary_prompts.append(prompt)
        return MagicMock(content=self._summary)


def _run(
    db_session,
    llm,
    message,
    session_id,
    surfaced_rows=None,
    classified_route="SQL",
    surfaced_ids=None,
    results_markdown=None,
    execute_side_effect=None,
):
    """Run the SQL route with the LLM mocked out.

    `surfaced_rows`: when given, `execute_generated_sql` is stubbed to report
    that many invoice ids for this turn. The hedge tests need to control that
    number exactly, and doing it through real rows isn't possible here —
    SQLite stores UUID columns as dashless hex, so the dashed tenant literal
    every generated query carries (and the tenant-isolation safety check
    requires) matches zero rows under this fixture's engine.

    `surfaced_ids` (Gap 310): the same stub, but reporting the ids you pass
    instead of freshly invented ones. The full-record block is keyed on the
    invoice ids a turn identified, so a test about it has to be able to name a
    REAL seeded row (or, for the isolation test, a real row belonging to someone
    else) rather than a random UUID that resolves to nothing.

    `results_markdown` (Gap 315): the exact results table the stub hands back,
    for tests about what the answering step does with the ROWS. The default stub
    returns an `id | currency` table, which carries no arithmetic at all -- a
    test about the computed-totals block has to be able to name the line-item
    columns rule 6d actually produces.

    `execute_side_effect` (Gap 294): replaces the stub outright, for the tests
    that need execution to FAIL -- the failure branch is one of the three places
    the generated statement used to reach the user.
    """
    if execute_side_effect is not None:
        surfaced_rows = None
    if surfaced_ids is not None and surfaced_rows is None:
        surfaced_rows = len(surfaced_ids)
    if results_markdown is not None and surfaced_rows is None:
        surfaced_rows = 0
    patches = [
        patch("agents.query_agent.classify_query", return_value=classified_route),
        patch("agents.query_agent.query_invoice_chunks", return_value=[]),
        patch("agents.query_agent.get_llm", return_value=llm),
        patch("agents.query_agent.get_cached_answer", return_value=None),
        patch("agents.query_agent.set_cached_answer"),
        patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
    ]
    if surfaced_rows is not None:
        ids = (
            [str(i) for i in surfaced_ids]
            if surfaced_ids is not None
            else [str(uuid4()) for _ in range(surfaced_rows)]
        )

        def _fake_execute(sql, tenant_id, db_sess, snapshot=None):
            if snapshot is not None:
                snapshot.extend(ids)
            if results_markdown is not None:
                return results_markdown
            return "\n\nid | currency\n--- | ---\n" + "\n".join(f"{i} | USD" for i in ids)

        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=_fake_execute))
    if execute_side_effect is not None:
        patches.append(
            patch("agents.query_agent.execute_generated_sql", side_effect=execute_side_effect)
        )

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return query_agent.run_query_agent(
            str(session_id), message, str(MOCK_TENANT_ID), db_session
        )


# ── Gap 241/242 follow-on (2026-08-18): the JSONB columns must be cast ───────

_JSON_COLUMNS = ("tags", "items", "sa_alerts")


def test_prompt_casts_json_columns_before_lower(db_session):
    """Live runs against Postgres aborted with
    `psycopg2.errors.UndefinedFunction: function lower(jsonb) does not exist`
    on tag/keyword questions, because the prompt's own canonical example was
    `LOWER(tags) LIKE LOWER('%"hardware"%')` and claimed it worked on both
    engines. `tags`/`items`/`sa_alerts` are JSONB on Postgres (models.py's
    JSON_VARIANT) and untyped TEXT on SQLite -- so the bare form only ever
    "worked" on the engine the unit suite runs against, which is exactly how it
    shipped. Every JSONB example in the prompt now carries the cast."""
    llm = _RecordingLLM([MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")])
    _run(db_session, llm, "How much did we spend on cloud?", uuid4())
    prompt = llm.prompts[0]

    for column in _JSON_COLUMNS:
        # No uncast form is offered as a usable predicate. `LOWER(tags)` does
        # still appear in the rule's prose, as the named counter-example -- the
        # thing being ruled out is a `LOWER(json_col) LIKE ...` pattern the
        # model could copy.
        assert f"LOWER({column}) LIKE" not in prompt, f"uncast LOWER({column}) predicate still shown to the model"
        assert f"LOWER(CAST({column} AS TEXT))" in prompt
    # The failure itself is named, so the model has the reason and not just the rule.
    assert "function lower(jsonb) does not exist" in prompt
    # VARCHAR columns stay uncast -- a blanket "cast everything" reading would
    # be a different kind of wrong.
    assert "LOWER(vendor_name) LIKE" in prompt


def test_prompt_does_not_teach_the_postgres_only_cast_operator(db_session):
    """`tags::text` fixes Postgres and breaks SQLite ("unrecognized token: :"),
    which the test suite and any SQLite-backed deployment run on. CAST(... AS
    TEXT) is the one form both parse, so it is the only one the prompt shows."""
    llm = _RecordingLLM([MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")])
    _run(db_session, llm, "How much did we spend on cloud?", uuid4())

    for column in _JSON_COLUMNS:
        assert f"{column}::" not in llm.prompts[0]


def test_recommended_cast_form_runs_on_sqlite(db_session):
    """The prompt's claim that this form is portable, executed rather than
    asserted: the same predicate the model is now told to write, run against
    this fixture's real SQLite engine."""
    _seed_invoice(
        db_session,
        vendor_name="Acme Manufacturing",
        tags=["cloud", "infra"],
        items=[{"description": "Server rack maintenance"}],
    )
    rows = db_session.exec(
        text(
            "SELECT COUNT(*) FROM invoice WHERE LOWER(CAST(tags AS TEXT)) LIKE LOWER('%cloud%') "
            "OR LOWER(CAST(items AS TEXT)) LIKE LOWER('%cloud%')"
        )
    ).one()
    assert rows[0] == 1


@pytest.mark.parametrize("predicate,should_run", [
    ("LOWER(CAST(tags AS TEXT)) LIKE LOWER('%cloud%')", True),
    ("LOWER(CAST(items AS TEXT)) LIKE LOWER('%cloud%')", True),
    ("LOWER(CAST(sa_alerts AS TEXT)) LIKE LOWER('%duplicate%')", True),
    ("LOWER(tags) LIKE LOWER('%cloud%')", False),  # the shipped bug
])
def test_recommended_cast_form_runs_on_postgres(predicate, should_run):
    """The engine the bug actually fired on. Skipped when no local Postgres is
    configured/reachable -- the rest of the suite is SQLite-only, and a SQLite
    run is precisely what failed to catch this."""
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    try:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM invoice WHERE {predicate}")
            ran = True
        except psycopg2.errors.UndefinedFunction:
            ran = False
        finally:
            conn.rollback()
    finally:
        conn.close()

    assert ran is should_run


# ── Gaps 241 + 242: one category-matching rule, one shared test ──────────────

def test_category_question_prompt_forbids_word_splitting_and_fixes_the_column_set(db_session):
    """Gap 241 (bare `%office%` OR `%supplies%` branches pulled an unrelated
    janitorial invoice into an office-supplies total) and Gap 242 (a
    freight/logistics question checked only item descriptions, missing a vendor
    literally named "Logistics") are the same prompt rule from two directions:
    which text a category phrase is matched against, and how the phrase is
    allowed to be broken up."""
    _seed_invoice(db_session, vendor_name="Summit Office Supplies", grand_total=450.0)
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])

    _run(db_session, llm, "How much did we spend on office supplies?", uuid4())

    prompt = llm.prompts[0]
    # Gap 242: one standard column set for every category question. The two
    # JSONB columns carry the cast rule 6(a) requires, the two VARCHAR ones
    # must not (see the jsonb-cast tests below).
    assert "CATEGORY / SUBJECT-MATTER QUESTIONS" in prompt
    for expr in (
        "LOWER(CAST(tags AS TEXT)) LIKE LOWER('%<phrase>%')",
        "LOWER(CAST(items AS TEXT)) LIKE LOWER('%<phrase>%')",
        "LOWER(vendor_name) LIKE LOWER('%<phrase>%')",
        "LOWER(customer_name) LIKE LOWER('%<phrase>%')",
    ):
        assert expr in prompt
    # Gap 241: the phrase stays whole.
    assert "NEVER decompose a multi-word category phrase" in prompt
    assert "NOT ('%office%' OR '%supplies%')" in prompt
    # "logistics or freight" -> two whole phrases, not four words.
    assert "'%logistics%', '%freight%'" in prompt


# ── Gap 237 step 2: the prior turn's WHERE clause is handed over verbatim ────

def test_prior_turn_sql_is_injected_into_the_followup_prompt(db_session):
    """The live repro (7 runs) showed the follow-up re-deriving the whole
    predicate from conversation prose, dropping the `vendor_name` branch in both
    reproductions. The prose never contained the WHERE clause — so the fix is to
    put the real one in front of the model."""
    session_id = uuid4()
    prior_sql = (
        f"SELECT currency, COUNT(*) FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}' AND ("
        "LOWER(vendor_name) LIKE LOWER('%cloud%') OR LOWER(CAST(tags AS TEXT)) LIKE LOWER('%cloud%') "
        "OR LOWER(CAST(items AS TEXT)) LIKE LOWER('%cloud%'))"
    )
    _seed_turn(db_session, session_id, content="There are 4 cloud invoices.", sql=prior_sql, ids=[str(uuid4())] * 1)

    llm = _RecordingLLM([MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")])
    _run(db_session, llm, "Can you explain the 3 USD ones in detail?", session_id)

    prompt = llm.prompts[0]
    assert "PREVIOUS TURN'S SQL" in prompt
    assert prior_sql in prompt
    assert "Start from ITS WHERE clause VERBATIM" in prompt
    assert "do NOT drop, merge or simplify away any branch of an existing OR group" in prompt


def test_first_turn_has_no_previous_sql_block(db_session):
    """No prior SQL-answered turn -> the block is absent entirely, rather than
    an empty header the model could try to 'reuse'."""
    llm = _RecordingLLM([MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")])
    _run(db_session, llm, "What are the total invoices related to cloud?", uuid4())

    # Rule 9 itself names the block, so assert on the block's own header line.
    assert "PREVIOUS TURN'S SQL (the query that produced" not in llm.prompts[0]


def test_get_prior_turn_sql_skips_turns_that_ran_no_query(db_session):
    """A RAG/CHAT-answered turn (generated_sql NULL) must not shadow the most
    recent turn that actually ran a query."""
    session_id = uuid4()
    _seed_turn(db_session, session_id, content="Older SQL turn.", sql="SELECT 1", minutes_ago=10)
    _seed_turn(db_session, session_id, content="A RAG answer with no SQL.", sql=None, minutes_ago=2)

    assert get_prior_turn_sql(str(session_id), db_session) == "SELECT 1"


def test_get_prior_turn_sql_is_none_for_an_unknown_or_invalid_session(db_session):
    assert get_prior_turn_sql(str(uuid4()), db_session) is None
    assert get_prior_turn_sql("not-a-uuid", db_session) is None


# ── Gap 237: the "no SQL at all" follow-up (4 of 7 live runs) ────────────────

@pytest.mark.parametrize("message", [
    "Can you explain the 3 USD ones in detail?",
    "explain those 2 invoices",
    "Show me those overdue ones",
    "break down these invoices for me",
    "list them",
])
def test_back_reference_phrasings_are_recognised(message):
    assert query_agent._is_narrowing_followup(message) is True


@pytest.mark.parametrize("message", [
    "What are the total invoices related to cloud?",
    "Which vendors have freight or logistics related charges?",
    "What does the vendor say about payment terms?",
    "Show me the largest invoice",
])
def test_ordinary_questions_are_not_treated_as_back_references(message):
    assert query_agent._is_narrowing_followup(message) is False


def test_narrowing_followup_is_forced_onto_the_sql_route(db_session):
    """The measured mechanism behind the live "no SQL at all" runs: with no
    session context, `classify_query()` sent "Can you explain the 3 USD ones in
    detail?" to RAG on ~40% of real calls, and RAG — which has no notion of the
    previous turn's result set — answered from chat history alone. A back-
    reference to a prior SQL-answered turn belongs on the route that can filter
    those rows."""
    session_id = uuid4()
    _seed_turn(db_session, session_id, content="There are 4 cloud invoices.", sql="SELECT 1")

    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    result = _run(
        db_session, llm, "Can you explain the 3 USD ones in detail?", session_id,
        surfaced_rows=2, classified_route="RAG",
    )

    assert llm.prompts, "SQL route never ran — the override did not fire"
    assert result["generated_sql"] is not None


def test_routing_override_needs_a_prior_sql_answered_turn(db_session):
    """First turn of a session: "the 3 ..." can't be a back-reference to
    anything, so the classifier's own decision stands."""
    llm = _RecordingLLM([])
    result = _run(
        db_session, llm, "Can you explain the 3 USD ones in detail?", uuid4(),
        classified_route="RAG",
    )

    assert llm.prompts == [], "SQL route ran with no prior query to narrow"
    assert result["generated_sql"] is None


def test_routing_override_leaves_a_fresh_question_alone(db_session):
    """A genuine document-content question in a session that happens to have a
    prior SQL turn must still reach RAG — the override is for back-references
    only, not "any question after a query"."""
    session_id = uuid4()
    _seed_turn(db_session, session_id, content="There are 4 cloud invoices.", sql="SELECT 1")

    llm = _RecordingLLM([])
    _run(
        db_session, llm, "What does the vendor say about payment terms?", session_id,
        classified_route="RAG",
    )

    assert llm.prompts == []



def test_null_sql_on_a_followup_is_retried_once_with_an_explicit_directive(db_session):
    """Most frequent live failure mode: the follow-up produced `sql: null` and
    the reply was composed from the prior turn's aggregate text. Deliberate
    behaviour is to push back once, not to accept a history-restated answer."""
    session_id = uuid4()
    _seed_turn(db_session, session_id, content="There are 4 cloud invoices.", sql="SELECT 1")

    llm = _RecordingLLM([
        MagicMock(sql=None, explanation_or_error="Already answered above."),
        MagicMock(sql=f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'"),
    ])
    result = _run(db_session, llm, "Can you explain the 3 USD ones in detail?", session_id)

    assert len(llm.prompts) == 2, "expected exactly one regeneration attempt"
    assert _NULL_SQL_FOLLOWUP_RETRY_DIRECTIVE in llm.prompts[1]
    assert result["generated_sql"] is not None
    assert _NO_FRESH_QUERY_NOTE not in result["content"]


def test_null_sql_twice_answers_but_says_no_query_was_run(db_session):
    """If the model still declines, the answer ships — but not dressed up as
    query-backed. A confident answer with no backing query is the thing this
    branch exists to stop."""
    session_id = uuid4()
    _seed_turn(db_session, session_id, content="There are 4 cloud invoices.", sql="SELECT 1")

    llm = _RecordingLLM([
        MagicMock(sql=None, explanation_or_error="Already answered above."),
        MagicMock(sql=None, explanation_or_error="3 USD invoices totaling $73,612.43."),
    ])
    result = _run(db_session, llm, "Can you explain the 3 USD ones in detail?", session_id)

    assert len(llm.prompts) == 2
    assert result["generated_sql"] is None
    assert _NO_FRESH_QUERY_NOTE in result["content"]
    assert "3 USD invoices totaling $73,612.43." in result["content"]


def test_null_sql_on_a_first_turn_is_neither_retried_nor_annotated(db_session):
    """No prior query to narrow from means a null answer is just a normal
    "can't answer that with these columns" — retrying or annotating it would be
    noise on every genuinely unsupported question."""
    llm = _RecordingLLM([MagicMock(sql=None, explanation_or_error="No such column.")])
    result = _run(db_session, llm, "Which invoices did Bob approve?", uuid4())

    assert len(llm.prompts) == 1
    assert result["content"] == "No such column."
    assert _NO_FRESH_QUERY_NOTE not in result["content"]


def test_sql_prompt_states_history_is_not_a_data_source(db_session):
    llm = _RecordingLLM([MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")])
    _run(db_session, llm, "How many invoices are there?", uuid4())

    assert "The history is a record of what was said, not a data source" in llm.prompts[0]


# ── Gap 237 step 3: the hedge's own trigger-condition bug ────────────────────

def test_hedge_fires_when_the_user_references_a_subcount_of_the_prior_answer(db_session):
    """The bug: the hedge compared the referenced number against the prior
    turn's TOTAL row count. In the reported (and reproduced) shape the user
    references a SUB-count — "the 3 USD ones" out of a 4-row answer (3 USD +
    1 EUR) — so 4 was checked against {3} and it never fired, in either live
    reproduction of the defect it exists to catch."""
    session_id = uuid4()
    _seed_turn(
        db_session, session_id,
        content="There are 4 cloud-related invoices: 3 in USD totaling $73,612.43 and 1 in EUR for 800.00.",
        sql="SELECT 1",
        ids=[str(uuid4()) for _ in range(4)],
    )

    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    # 2 surfaced against the 3 the user referenced — the exact live shape of
    # run0/run6 in the repro (CNH-1001, the vendor-name-only match, dropped).
    result = _run(db_session, llm, "Can you explain the 3 USD ones in detail?", session_id, surfaced_rows=2)

    assert len(result["result_invoice_ids"]) == 2  # one silently missing
    assert "Heads up: you referenced 3 from the previous answer" in result["content"]
    assert "only found 2" in result["content"]


def test_hedge_is_silent_when_the_followup_reconciles(db_session):
    """A follow-up that finds exactly what the user referenced must not be
    hedged — noise on correct answers is the Gap 226 failure mode."""
    session_id = uuid4()
    _seed_turn(
        db_session, session_id,
        content="There are 4 cloud-related invoices: 3 in USD and 1 in EUR.",
        sql="SELECT 1",
        ids=[str(uuid4()) for _ in range(4)],
    )

    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    result = _run(db_session, llm, "Can you explain the 3 USD ones in detail?", session_id, surfaced_rows=3)

    assert len(result["result_invoice_ids"]) == 3
    assert "Heads up" not in result["content"]


def test_hedge_is_silent_when_the_number_is_not_a_back_reference(db_session):
    """"Show me the 3 largest invoices" contains "the 3" but references nothing
    the prior turn said — requiring the number to appear in the prior reply's
    text keeps a fresh top-N question from being hedged."""
    session_id = uuid4()
    _seed_turn(
        db_session, session_id,
        content="Total spend is $120,000.00 across all vendors.",
        sql="SELECT 1",
        ids=[str(uuid4()) for _ in range(9)],
    )

    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    result = _run(db_session, llm, "Show me the 3 largest invoices", session_id, surfaced_rows=1)

    assert "Heads up" not in result["content"]


def test_hedge_is_silent_when_no_invoice_ids_could_be_harvested(db_session):
    """An aggregate whose id-harvest comes back empty is indistinguishable from
    a real miss here; hedging it would fire on every unharvestable aggregate."""
    session_id = uuid4()
    _seed_turn(
        db_session, session_id,
        content="There are 4 cloud-related invoices: 3 in USD and 1 in EUR.",
        sql="SELECT 1",
        ids=[str(uuid4()) for _ in range(4)],
    )

    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT COUNT(*) FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}' AND 1=0")
    ])
    result = _run(db_session, llm, "Can you explain the 3 USD ones in detail?", session_id)

    assert result["result_invoice_ids"] == []
    assert "Heads up" not in result["content"]


# ── Gap 253: line-item extraction (rule 6d), dialect-conditioned ─────────────
#
# The mechanism here is the same one rule 6(a) already settled: teach one correct
# form per engine at prompt-build time. The first implementation of this gap
# instead emitted Postgres JSONB syntax unconditionally and regex-translated it
# to SQLite inside execute_generated_sql(); that rewriter is gone. These tests
# therefore assert (a) that the prompt carries the live engine's form and NOT the
# other engine's, and (b) -- the part that actually matters -- that the taught
# SQL, extracted verbatim from the prompt constant, executes correctly against
# a real engine. Same shape as test_recommended_cast_form_runs_on_{sqlite,postgres}.

_LINE_ITEM_SEED = [
    {"description": "Cloud Storage", "quantity": 1, "unit_price": 765.36, "amount": 765.36},
    {"description": "Training & Onboarding", "quantity": 40, "unit_price": 732.5735, "amount": 29302.94},
]


def _taught_sql(rule_text: str, marker: str) -> str:
    """The SQL example that immediately follows `marker` in a rule 6d constant.

    Pulled out of the constant rather than re-typed, so these tests execute
    literally the text the model is shown -- a divergence between what is taught
    and what is tested is exactly the failure mode this gap already had once.
    """
    lines = rule_text.splitlines()
    idx = next(i for i, line in enumerate(lines) if marker in line)
    return lines[idx + 1]


def test_line_item_rule_teaches_only_the_live_engines_dialect(db_session):
    """The prompt must not offer the model syntax the bound engine cannot parse.

    This fixture's session is SQLite, so rule 6d must be the json_each form --
    and must NOT mention jsonb_array_elements / LATERAL / ::numeric, all of
    which SQLite rejects outright ("near LATERAL: syntax error",
    "unrecognized token: :").
    """
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "show me the price for training line items", uuid4())
    prompt = llm.prompts[0]

    assert "6d. LINE-ITEM LEVEL EXTRACTION" in prompt
    assert "json_each(" in prompt
    assert "item.value ->> 'description'" in prompt
    for postgres_only in ("jsonb_array_elements", "LATERAL", "::numeric", "::jsonb"):
        assert postgres_only not in prompt, f"SQLite prompt still shows Postgres-only {postgres_only!r}"


def test_postgres_variant_of_rule_6d_is_the_one_built_for_a_postgres_bind():
    """The mirror of the above, without needing a live Postgres: the Postgres
    branch is selected by dialect name and carries the Postgres spelling."""
    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    rule = query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session)

    assert "jsonb_array_elements" in rule
    assert "LEFT JOIN LATERAL" in rule
    assert "json_each" not in rule
    # An unreadable bind must fall back to the production engine, not the test one.
    broken = MagicMock()
    broken.get_bind.side_effect = RuntimeError("no bind")
    assert "jsonb_array_elements" in query_agent._line_item_rule(str(MOCK_TENANT_ID), broken)


def test_rule_6d_guards_against_null_or_non_array_items(db_session):
    """`items` is nullable and machine-populated. Un-nesting it unguarded aborts
    the whole tenant's query on a single bad row (confirmed by hand: SQLite
    raises `malformed JSON`, Postgres raises on a non-array), and burns an
    attempt of the 3-try repair loop each time."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the training amount", uuid4())
    assert "json_valid(items) AND json_type(items) = 'array'" in llm.prompts[0]

    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    assert "jsonb_typeof(items) = 'array'" in query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session)


_RULE_6D_MARKER = "The one and only shape for rule 6d"


def test_rule_6d_selects_currency_per_rule_7(db_session):
    """Rule 7 requires `currency` alongside any monetary column; rule 6d's own
    example has to obey it, or every line-item answer is an unlabelled number
    (FE Gap 183 is on file for exactly that)."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the training amount", uuid4())
    shape = _taught_sql(llm.prompts[0], _RULE_6D_MARKER)
    assert "invoice.currency" in shape


def test_taught_line_item_sql_runs_on_sqlite_and_returns_only_the_matching_line(db_session):
    """The gap's own reported case, executed rather than asserted: an invoice
    whose Training & Onboarding line is 29,302.94 inside a 35,480.59 grand total.
    The taught query must return 29,302.94 and must not surface the unrelated
    Cloud Storage line -- returning the grand total was the reported defect.

    The two junk rows are the Fix-2 guard under test: before the CASE guard,
    either of them aborted the entire query with `malformed JSON`.

    Tenant literal is `.hex` because SQLite stores UUID columns dashless; the
    dashed form the generated SQL carries in production is Postgres' shape and
    is covered by the isolation tests, not this one.
    """
    _seed_invoice(db_session, invoice_number="US-1", grand_total=35480.59, items=_LINE_ITEM_SEED)
    _seed_invoice(db_session, invoice_number="US-2", grand_total=500.0, items=None)
    _seed_invoice(db_session, invoice_number="US-3", grand_total=700.0, items=[])
    # A value that isn't JSON at all -- the ORM can't produce one, but OCR/LLM
    # extraction writing into a JSON-typed column on an untyped engine can.
    db_session.exec(
        text("UPDATE invoice SET items = 'not json at all' WHERE invoice_number = 'US-3'")
    )
    db_session.commit()

    rule = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    rows = db_session.exec(text(_taught_sql(rule, _RULE_6D_MARKER))).all()

    assert len(rows) == 1
    invoice_number, vendor_name, currency, description, qty, unit_price, amount = rows[0]
    assert (invoice_number, currency, description) == ("US-1", "USD", "Training & Onboarding")
    assert (qty, unit_price, amount) == (40, 732.5735, 29302.94)
    assert amount != 35480.59


def test_taught_line_item_sql_returns_raw_rows_across_invoices_and_currencies_ungrouped(db_session):
    """Found live, 2026-08-19 (US tenant test, twice): letting SQL both find AND
    aggregate line items was the repeated source of wrong answers (summing the
    wrong column, grouping by the wrong thing). Rule 6d no longer aggregates at
    all -- this confirms the taught query returns every matching line as its
    own raw row, across invoices and currencies, with no SUM/GROUP BY collapsing
    them. Adding them up correctly is the summary step's job now, not SQL's."""
    _seed_invoice(db_session, invoice_number="US-1", items=_LINE_ITEM_SEED)
    _seed_invoice(
        db_session, invoice_number="US-2",
        items=[{"description": "Training refresher", "quantity": 2, "unit_price": 100.0, "amount": 200.0}],
    )
    _seed_invoice(
        db_session, invoice_number="IN-1", currency="INR",
        items=[{"description": "Onboarding training pack", "quantity": 1, "unit_price": 50.0, "amount": 50.0}],
    )

    rule = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    rows = db_session.exec(text(_taught_sql(rule, _RULE_6D_MARKER))).all()

    amounts_by_currency = {}
    for invoice_number, vendor_name, currency, description, qty, unit_price, amount in rows:
        amounts_by_currency.setdefault(currency, []).append(amount)

    assert len(rows) == 3  # one row per matching line, not one row per currency/total
    assert sorted(amounts_by_currency["USD"]) == [200.0, 29302.94]
    assert amounts_by_currency["INR"] == [50.0]


def test_taught_line_item_sql_runs_on_postgres():
    """The engine that actually runs this in production. Same skip-when-absent
    shape as test_recommended_cast_form_runs_on_postgres -- SQLite cannot catch
    a `jsonb_array_elements`/`::numeric`/`LATERAL` defect, which is precisely how
    rule 6's original `LOWER(tags)` bug shipped."""
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    sql = _taught_sql(query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session), _RULE_6D_MARKER)
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            cur.fetchall()
        finally:
            conn.rollback()
    finally:
        conn.close()


def test_line_item_query_still_yields_a_result_set_snapshot(db_session):
    """Gap 231's invoice-id snapshot drives the FE's "which invoice was wrong?"
    triage picker, and the Gap 237 step-3 hedge only fires when it is non-empty.
    Rule 6d's queries always carry a join, and the companion-query harvester used
    to bail on the word `join` outright -- so every line-item answer silently
    came back with an empty snapshot."""
    invoice = _seed_invoice(db_session, invoice_number="US-1", items=_LINE_ITEM_SEED)
    _seed_invoice(db_session, invoice_number="US-2", items=[{"description": "Cloud Storage", "amount": 1.0}])

    rule = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    harvested = query_agent._harvest_invoice_ids_via_companion_query(
        _taught_sql(rule, _RULE_6D_MARKER), MOCK_TENANT_ID.hex, db_session
    )
    assert harvested == [str(invoice.id)]


def test_harvester_still_refuses_a_join_to_a_real_table(db_session):
    """The un-nest join is whitelisted by shape, not by "contains a join" -- a
    join to anything else is still unreconstructible and must bail."""
    sql = (
        f"SELECT SUM(grand_total) FROM invoice JOIN chat_message ON chat_message.id = invoice.id "
        f"WHERE tenant_id = '{MOCK_TENANT_ID.hex}'"
    )
    assert query_agent._harvest_invoice_ids_via_companion_query(sql, MOCK_TENANT_ID.hex, db_session) == []


def test_summary_prompt_formats_line_items_with_the_rows_own_currency(db_session):
    """FE Gap 183 is on file because a hardcoded `$` was once rendered over
    mixed-currency data. The line-item format string must take the currency from
    the row, and must not carry a literal `$` for the model to copy."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT invoice_number, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the training amount", uuid4(), surfaced_rows=1)

    summary_prompt = llm.summary_prompts[0]
    assert "<line_qty> units × <currency> <line_unit_price> = <currency> <line_amount>" in summary_prompt
    assert "Never hardcode '$'" in summary_prompt
    # Gap 313 moved the section boundary: this prompt's own "CRITICAL CURRENCY
    # RULE" paragraph is gone (the rule is stated once, in the shared persona
    # block at the top of the prompt), so the line-item formatting section now
    # runs from its heading to the results table.
    format_section = summary_prompt.split("FORMATTING FOR LINE-ITEM EXTRACTION:")[1].split("Results:")[0]
    assert "$<" not in format_section and "× $" not in format_section


def test_rule_9_authorises_the_line_item_from_change_on_a_narrowing_followup(db_session):
    """Gap 253's own reported phrasing ("the amount only for training and
    onboarding from the total invoice") is a narrowing follow-up, so rules 6d and
    9 fire together. Rule 9 said only the WHERE clause was fixed and said nothing
    about FROM, which reads as "keep the previous invoice-level FROM" -- i.e.
    return the grand total again, the exact reported defect."""
    session_id = uuid4()
    _seed_turn(
        db_session, session_id,
        content="Invoice US-1 totals USD 35,480.59.",
        sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'",
    )
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(
        db_session, llm,
        "I want the amount only for training and onboarding from the total invoice",
        session_id,
    )
    prompt = llm.prompts[0]
    assert "EXCEPTION -- the FROM clause" in prompt
    assert "rule 6d's line-item join" in prompt


# ── Live regressions found 2026-08-19 (CGST question, "list all invoices") ──


def test_rule_6d_excludes_tax_component_terms(db_session):
    """Live bug: "what's the CGST we paid on the Rajesh Steel invoices" matched
    rule 6d's trigger (a phrase + a money word) and searched item descriptions
    for '%cgst%' -- guaranteed zero rows, since CGST/SGST/IGST are never stored
    as line-item descriptions (only a single combined tax_amount exists). The
    reply then reported "no Rajesh Steel invoices matching your query", which is
    false -- the invoice existed; only that one wrong-shaped filter matched
    nothing. Both dialect variants must steer the model to tax_amount instead.

    Second live bug, found immediately after the first fix shipped: the first
    version of this guardrail enumerated CGST/SGST/IGST/VAT by name and missed
    plain "GST" -- arguably the more commonly used standalone term of the four.
    That's the exact case-by-case-list failure mode this whole session kept
    finding elsewhere in this file, reproduced in its own bugfix. The guardrail
    must teach the CONCEPT (any tax-component term, not a fixed enumeration),
    so this test checks for the generalizing language itself, not just that a
    slightly longer list of literals was pasted in -- a plain re-list would
    pass a test that only checks "GST" is present without fixing the actual
    defect class."""
    # Feature 6.1 C4.2 (2026-09-03): the CONCEPT no longer lives as prose inside
    # rule 6d. It lives in code -- `detect_tax_component_term()` recognises the
    # term, and the SCHEMA LINK block states the column as a fact before the
    # model runs. Rule 6d itself now defers to that block. Same defect class
    # guarded, one level earlier: a re-list of literals in the prompt cannot pass
    # this, only a detector that generalises can.
    for term in ("GST", "CGST", "SGST", "IGST", "VAT", "sales tax"):
        assert query_agent.detect_tax_component_term(f"what {term} did we pay Rajesh Steel") == term, term
    block = query_agent._schema_linking_block_for("whats the CGST we paid to Rajesh Steel")
    assert "tax_amount" in block
    assert "never search line items for a tax term" in block
    rule_sqlite = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    assert "When the SCHEMA LINK names a column, select that column" in rule_sqlite
    assert "do NOT search line items" in rule_sqlite
    # The generalizing instruction itself, not just a longer list of named terms --
    # this is what should catch the NEXT unlisted tax term too (TDS, cess, duty, ...).
    # (C4.2: the "principle, not a fixed list" language moved with the concept into
    # `detect_tax_component_term`, whose parametrised check above IS the test of it.)

    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    rule_pg = query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session)
    # Both dialect rules defer to the same dialect-independent SCHEMA LINK fact,
    # so the SQLite test path and the Postgres live path cannot diverge on it.
    assert "When the SCHEMA LINK names a column, select that column" in rule_pg
    assert "do NOT search line items" in rule_pg


@pytest.mark.parametrize("message,expected", [
    ("what is the GST on this invoice", "GST"),
    ("whats the CGST we paid to Rajesh Steel", "CGST"),
    ("any SGST charged", "SGST"),
    ("what about IGST", "IGST"),
    ("any VAT charged on this", "VAT"),
    ("was there withholding tax applied", "withholding tax"),
    ("what's the HST on this Canadian invoice", "HST"),
    ("what is the training amount", None),
    ("gstreet vendor invoice", None),  # word-boundary: must not match mid-word
])
def test_detect_tax_component_term_is_deterministic_not_llm_judged(message, expected):
    """Gap 263's second follow-up (2026-08-19): the prose guardrail in rule 6d
    was widened from a fixed list (CGST/SGST/IGST/VAT) to "any tax-related
    term" after plain "GST" was found missing -- but that still asks the LLM
    to correctly recognize an open-ended category from a sentence, every call,
    for every jurisdiction. This is the actual fix requested: a real,
    deterministic, testable tool (data-driven term list, not prompt prose).
    Extending coverage to a new jurisdiction's tax name is "add a string to
    _TAX_COMPONENT_TERMS", not "reword a paragraph and hope the model reads it
    the way intended"."""
    assert query_agent.detect_tax_component_term(message) == expected


def test_tax_term_block_is_injected_into_the_sql_prompt_when_detected(db_session):
    """The detector is only useful if its output actually reaches the prompt --
    this confirms the SQL route grounds the model with the SPECIFIC term found
    in the user's own question, not just the general rule 6d guardrail text."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT tax_amount, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the GST on the Rajesh Steel invoice", uuid4())
    assert 'contains the tax-related term "GST"' in llm.prompts[0]

    # Gap 310: the note still fires on the same detection, but it no longer
    # asserts the (now false) claim that drove a decline. `Invoice.taxes` holds
    # the itemized components and has since extraction started populating it.
    assert "This schema has no breakdown by tax type" not in llm.prompts[0]
    assert "`taxes` field" in llm.prompts[0]

    llm2 = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm2, "what is the training amount", uuid4())
    # Check for the dynamic injection's own distinctive phrasing, not "tax-related
    # term" alone -- rule 6d's static guardrail text always contains that phrase
    # regardless of this question, so that substring is present either way.
    assert "NOTE: this question contains the tax-related term" not in llm2.prompts[0]


# ── Gap 310: the identified invoice's whole row reaches the answering step ────


def _seed_rajesh_steel(db_session):
    """The Gaps 263/264 invoice, now carrying the `taxes` it always really had."""
    return _seed_invoice(
        db_session,
        vendor_name="Rajesh Steel",
        invoice_number="INDIA-20260722-003",
        currency="INR",
        subtotal=100000.0,
        grand_total=118000.0,
        tax_amount=18000.0,
        taxes=[
            {"tax_type": "CGST", "rate_percent": 9.0, "amount": 9000.0},
            {"tax_type": "SGST", "rate_percent": 9.0, "amount": 9000.0},
        ],
        tax_ids=[{"type": "GSTIN", "value": "29ABCDE1234F1Z5"}],
    )


def test_full_record_block_gives_the_answer_step_the_real_cgst_sgst_breakdown(db_session):
    """Gap 310, the case the gap was opened over.

    "whats the CGST we paid to Rajesh Steel" was answerable from the data the
    whole time -- `Invoice.taxes` carries one entry per component -- and was
    declined anyway, because the SQL route's hand-typed schema block never
    listed the column and its tax-term note said outright that no breakdown
    existed. The answering step now receives the identified invoice's entire ORM
    row, so the real INR 9,000.00 / INR 9,000.00 split is in front of the model
    instead of being invisible to it.
    """
    invoice = _seed_rajesh_steel(db_session)
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT tax_amount, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    result = _run(
        db_session,
        llm,
        "whats the CGST we paid to Rajesh Steel",
        uuid4(),
        surfaced_ids=[invoice.id],
    )

    summary_prompt = llm.summary_prompts[0]
    assert "FULL INVOICE RECORD(S)" in summary_prompt
    # The actual component figures, read off the row -- not derivable from the
    # `tax_amount, currency` SELECT list the query used.
    assert '"tax_type": "CGST"' in summary_prompt
    assert '"tax_type": "SGST"' in summary_prompt
    assert summary_prompt.count('"amount": 9000.0') == 2
    # And the other columns the schema block never exposed either.
    assert '"subtotal": 100000.0' in summary_prompt
    assert "29ABCDE1234F1Z5" in summary_prompt
    # Never a licence to invent: the block says so in as many words, because the
    # original live failure (Gap 263) was a FABRICATED CGST/SGST split.
    assert "never derive, split or estimate one" in summary_prompt
    # Gap 304 half (2): the online quality judge has to be shown the same
    # evidence the model was, or a correct CGST answer scores as unfaithful.
    assert '"tax_type": "CGST"' in result["judge_evidence"]["context"]


def test_full_record_block_is_generic_not_gated_on_a_tax_term(db_session):
    """The correction that shaped this fix (2026-08-24): the mechanism is "the
    model can see the whole record", not "the model gets extra data for tax
    questions". A keyword gate is the exact failure mode this file already has
    two named instances of (rule 6d's tax-component miss, Gap 264's fixed term
    list) -- it works for the phrasing it was written against and silently does
    nothing for the next one. So a question with no tax word anywhere in it gets
    the same record."""
    invoice = _seed_rajesh_steel(db_session)
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT invoice_number, grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(
        db_session,
        llm,
        "pull up the Rajesh Steel invoice",
        uuid4(),
        surfaced_ids=[invoice.id],
    )

    assert query_agent.detect_tax_component_term("pull up the Rajesh Steel invoice") is None
    summary_prompt = llm.summary_prompts[0]
    assert "FULL INVOICE RECORD(S)" in summary_prompt
    assert '"tax_type": "CGST"' in summary_prompt
    assert '"subtotal": 100000.0' in summary_prompt


def test_full_record_block_cannot_fetch_another_tenants_invoice(db_session):
    """Tenant isolation, checked at the block itself rather than only through the
    route. The ids fed in normally come from a query `execute_generated_sql`'s
    Safety Check 3 already forced to be tenant-scoped -- this is the second,
    independent check, and it is `get_full_record`'s own: a row belonging to
    another tenant comes back `not_found`, never as a distinguishable error, so
    a caller cannot even learn that the id exists."""
    other_tenant = uuid4()
    mine = _seed_rajesh_steel(db_session)
    theirs = _seed_invoice(
        db_session,
        tenant_id=other_tenant,
        vendor_name="Someone Else Ltd",
        invoice_number="OTHER-1",
        grand_total=999999.0,
        taxes=[{"tax_type": "CGST", "rate_percent": 9.0, "amount": 123456.0}],
    )

    # Directly: the other tenant's id yields nothing at all, not a partial record.
    assert query_agent._full_record_block_for(
        [str(theirs.id)], str(MOCK_TENANT_ID), db_session
    ) == ""
    # Mixed in with a legitimate one, only the caller's own row survives.
    block = query_agent._full_record_block_for(
        [str(mine.id), str(theirs.id)], str(MOCK_TENANT_ID), db_session
    )
    assert "29ABCDE1234F1Z5" in block
    assert "Someone Else Ltd" not in block
    assert "123456.0" not in block

    # And through the whole route, with the turn's id snapshot poisoned with the
    # other tenant's row: nothing of theirs reaches the prompt.
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the CGST", uuid4(), surfaced_ids=[theirs.id])
    assert "FULL INVOICE RECORD(S)" not in llm.summary_prompts[0]
    assert "Someone Else Ltd" not in llm.summary_prompts[0]


def test_full_record_block_fails_soft_when_the_fetch_raises(db_session):
    """Same fail-soft posture as everything else on this route: a broken
    enrichment must cost the turn its extra context, never the answer. The turn
    still summarizes the results table it already had, exactly as it did before
    this block existed."""
    invoice = _seed_rajesh_steel(db_session)
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT tax_amount, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    with patch(
        "agents.query_tools.get_full_record", side_effect=RuntimeError("boom")
    ):
        result = _run(
            db_session,
            llm,
            "whats the CGST we paid to Rajesh Steel",
            uuid4(),
            surfaced_ids=[invoice.id],
        )

    assert "FULL INVOICE RECORD(S)" not in llm.summary_prompts[0]
    assert "### Query Results" in result["content"]
    assert result["content"].startswith("Formatted summary.")


def test_full_record_block_is_bounded_to_a_few_identified_invoices(db_session):
    """A turn that identified 40 rows is an aggregate or a listing, not a detail
    question, and 40 complete records would be both useless and the single
    largest thing in the prompt. `MAX_FULL_RECORD_INVOICES` is that bound, and
    it is a policy recorded in code -- the same posture as
    `query_tools.MAX_FULL_RECORD_CHUNK_CHARS`."""
    invoices = [
        _seed_rajesh_steel(db_session)
        for _ in range(query_agent.MAX_FULL_RECORD_INVOICES + 1)
    ]
    assert query_agent._full_record_block_for(
        [str(i.id) for i in invoices], str(MOCK_TENANT_ID), db_session
    ) == ""
    # One under the bound still gets the full treatment.
    kept = query_agent._full_record_block_for(
        [str(i.id) for i in invoices[: query_agent.MAX_FULL_RECORD_INVOICES]],
        str(MOCK_TENANT_ID),
        db_session,
    )
    assert kept.count("FULL INVOICE RECORD(S)") == 1
    assert kept.count('"tax_type": "CGST"') == query_agent.MAX_FULL_RECORD_INVOICES


def _bulky_items(marker: str, lines: int) -> list[dict]:
    """Line items long enough to make one rendered record measurably large.

    `items` is the one field on this record with no natural ceiling -- a
    consolidated invoice can carry hundreds of lines -- which is exactly why the
    block has a character budget on top of its invoice-count bound.
    """
    return [
        {
            "description": f"{marker} line {n} -- " + "x" * 90,
            "quantity": 1,
            "unit_price": 100.0,
            "amount": 100.0,
        }
        for n in range(lines)
    ]


def _rendered_size(db_session, invoice) -> int:
    """How many characters this invoice contributes, measured the way the block
    itself measures it -- `json.dumps(record, indent=2)` on what
    `get_full_record` returns, not on the ORM object."""
    from agents.query_tools import get_full_record

    result = get_full_record(
        str(invoice.id), str(MOCK_TENANT_ID), db_session, include_document_pages=False
    )
    return len(json.dumps(result.record, indent=2, default=str))


def test_full_record_block_is_bounded_by_its_character_budget(db_session):
    """The second bound, on the axis `MAX_FULL_RECORD_INVOICES` cannot cover.

    Three invoices is within the count bound, but three *large* invoices are not
    within the prompt budget: `items` is unbounded in principle, so a
    count-only bound would let a single turn put an arbitrary number of
    characters in front of the summary model. What does not fit is held back,
    and -- the part that matters -- it is DISCLOSED in the block rather than
    silently dropped, the same honesty rule `get_full_record`'s
    `columns_omitted` / `pages_omitted` follow. An answer that describes a
    partial set as the whole set is the failure this note exists to stop.
    """
    invoices = [
        _seed_invoice(
            db_session,
            vendor_name=f"Bulk Vendor {marker}",
            invoice_number=f"BULK-{marker}",
            grand_total=1000.0,
            items=_bulky_items(marker, 22),
        )
        for marker in ("A", "B", "C")
    ]
    sizes = {inv.invoice_number: _rendered_size(db_session, inv) for inv in invoices}
    # Precondition, asserted rather than assumed: the fixture really does
    # overrun the budget, so a passing test below means the cap fired.
    assert sum(sizes.values()) > query_agent.MAX_FULL_RECORD_BLOCK_CHARS
    assert len(invoices) <= query_agent.MAX_FULL_RECORD_INVOICES

    block = query_agent._full_record_block_for(
        [str(i.id) for i in invoices], str(MOCK_TENANT_ID), db_session
    )
    shown = [
        number for number in sizes if f'"invoice_number": "{number}"' in block
    ]
    assert 0 < len(shown) < len(invoices)
    assert sum(sizes[number] for number in shown) <= query_agent.MAX_FULL_RECORD_BLOCK_CHARS
    # Held back, and said so -- with the real count, not a vague hedge.
    assert (
        f"({len(invoices) - len(shown)} further identified invoice record(s) were "
        "held back for size" in block
    )
    assert "do not describe this as every matching invoice's detail" in block


def test_full_record_block_still_shows_one_record_larger_than_the_whole_budget(db_session):
    """The deliberate exception to the budget: the FIRST record is always
    rendered, however large. A single 400-line invoice would otherwise produce an
    empty block plus a note saying everything was held back -- which is strictly
    worse than a long block, because the turn then has neither the detail nor any
    reason to think it is missing."""
    huge = _seed_invoice(
        db_session,
        vendor_name="Bulk Vendor HUGE",
        invoice_number="BULK-HUGE",
        grand_total=1000.0,
        items=_bulky_items("HUGE", 200),
    )
    assert _rendered_size(db_session, huge) > query_agent.MAX_FULL_RECORD_BLOCK_CHARS

    block = query_agent._full_record_block_for(
        [str(huge.id)], str(MOCK_TENANT_ID), db_session
    )
    assert '"invoice_number": "BULK-HUGE"' in block
    assert "held back for size" not in block


def test_full_record_block_is_absent_when_no_invoice_was_identified(db_session):
    """An aggregate ("total spend across every invoice") identifies no single
    row worth dumping, and a turn that identified nothing must be byte-identical
    to what it was before Gap 310 -- this is what keeps the enrichment off the
    turns that would only pay for it."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT SUM(grand_total), currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}' GROUP BY currency")
    ])
    _run(db_session, llm, "what did we spend in total", uuid4(), surfaced_rows=0)
    assert "FULL INVOICE RECORD(S)" not in llm.summary_prompts[0]
    assert query_agent._full_record_block_for([], str(MOCK_TENANT_ID), db_session) == ""
    assert query_agent._full_record_block_for(None, str(MOCK_TENANT_ID), db_session) == ""


# ── Gap 315: the summary step's arithmetic is done in Python, not by the model ─


def _line_item_table(rows: list[str]) -> str:
    """A rule 6d line-item results table, in `execute_generated_sql()`'s format."""
    header = "line_description | line_qty | line_unit_price | line_amount | currency | vendor_name"
    return header + "\n" + " | ".join(["---"] * 6) + "\n" + "\n".join(rows)


# The exact live failure Gap 269 was opened over (US tenant test, 2026-08-19,
# Q4/Q10): the model printed "5000.00 units x USD 0.08 = USD 420.00" -- an
# equation that is false, since 5000 x 0.08 is 400.00, not 420.00. The row is
# genuinely reconcilable two ways (the stored amount, or quantity x unit price)
# and the model picked one figure for one side and the other for the other.
_GAP_269_TABLE = _line_item_table([
    "Bulk fastener supply | 5000.00 | 0.08 | 420.00 | USD | Titan Steel Distributors",
    "Freight surcharge | 2.00 | 150.00 | 300.00 | USD | Titan Steel Distributors",
])


def test_line_item_totals_are_computed_in_python_not_by_the_model(db_session):
    """Gap 315, and the specific class of bug Gap 269 found.

    Gap 273 stopped SQL from aggregating rule 6d's line items and replaced it
    with "YOU compute this total, not the database" -- which moved the summation
    to the LLM rather than making it deterministic, so Gap 269's root cause (an
    LLM doing arithmetic) survived its own fix. Here both figures a model could
    confuse are computed and labelled before the model is invoked at all: the
    stored amount, the amount quantity x unit price actually computes to, and the
    difference between them.
    """
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT line_description FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    result = _run(
        db_session,
        llm,
        "does the fastener line on the Titan Steel invoice add up",
        uuid4(),
        results_markdown=_GAP_269_TABLE,
    )
    prompt = llm.summary_prompts[0]

    assert "COMPUTED FIGURES" in prompt
    # The reconciliation, per line, with both figures present and named -- the
    # model cannot restate the false equation, because the block never contains
    # one and says the difference out loud.
    assert (
        "Bulk fastener supply: USD 420.00 stated, 5000 x USD 0.08 computes to "
        "USD 400.00 -- USD 20.00 mismatch" in prompt
    )
    assert "5000 x USD 0.08 = USD 420.00" not in prompt
    # The line that does reconcile still gets the plain equation form.
    assert "Freight surcharge: 2 x USD 150.00 = USD 300.00" in prompt
    # And the total is the deterministic one (420.00 + 300.00), not something the
    # model was asked to work out.
    assert "- total of the line amounts, per currency:" in prompt
    assert "USD 720.00" in prompt
    # The instruction actually swapped: the model is told the arithmetic is done,
    # and the pre-Gap-315 "you do it" wording is gone from this turn.
    assert query_agent._DETERMINISTIC_TOTALS_INSTRUCTION in prompt
    assert query_agent._LLM_TOTALS_INSTRUCTION not in prompt
    assert "YOU compute this total, not the database" not in prompt
    # The mismatch instruction lives in the header, never among the figures --
    # an instruction sitting where data sits gets reproduced as data.
    assert "Never write such a line as an 'x = y' equation" in prompt
    assert prompt.index("Never write such a line as an 'x = y' equation") < prompt.index(
        "- each line, checked against its own quantity x unit price:"
    )
    # Gap 304 half (2): the judge is shown the same figures the model was.
    assert "USD 20.00 mismatch" in result["judge_evidence"]["context"]


def test_computed_totals_are_split_per_vendor_and_never_across_currencies(db_session):
    """The two breakdowns the summary prompt asks for by name, both deterministic.

    The prompt tells the model to give one subtotal per vendor when the question
    asks for that, and never to add across currencies. Both were arithmetic the
    model performed itself; both are now figures it is handed. If the per-vendor
    split were not computed here, telling the model not to do arithmetic would
    push it straight back into doing arithmetic for that one case.
    """
    table = _line_item_table([
        "Rack rental | 4.00 | 100.00 | 400.00 | USD | DataPipe Solutions",
        "Onboarding pack | 2.00 | 50.00 | 100.00 | INR | StratEdge Partners",
        "Support hours | 10.00 | 25.00 | 250.00 | USD | StratEdge Partners",
    ])
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT line_description FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(
        db_session,
        llm,
        "which vendors billed us for support, how much per vendor",
        uuid4(),
        results_markdown=table,
    )
    prompt = llm.summary_prompts[0]

    assert "- subtotal for DataPipe Solutions, per currency:\n    USD 400.00" in prompt
    assert "- subtotal for StratEdge Partners, per currency:\n    INR 100.00\n    USD 250.00" in prompt
    # Per currency at every level, and never one blended figure: 400 + 100 + 250
    # is not a number that means anything without an exchange rate.
    assert "- total of the line amounts, per currency:\n    INR 100.00\n    USD 650.00" in prompt
    assert "750.00" not in prompt


def test_non_line_item_tables_get_a_per_currency_total_of_their_money_columns(db_session):
    """The other shape: an ordinary multi-row listing. Money columns are summed
    per currency; a quantity, a unit price or an average is not, because a total
    of those is a figure with no referent (`is_summable_money_column`)."""
    table = (
        "invoice_number | grand_total | avg_grand_total | line_qty | currency\n"
        "--- | --- | --- | --- | ---\n"
        "INV-1 | 1000.00 | 500.00 | 3.00 | USD\n"
        "INV-2 | 250.50 | 500.00 | 4.00 | USD"
    )
    block = query_agent._computed_figures_block_for(table)

    assert "- total of `grand_total` across the 2 rows above:\n    USD 1,250.50" in block
    assert "avg_grand_total" not in block
    assert "line_qty" not in block


def test_a_single_already_aggregated_row_is_never_re_totalled(db_session):
    """A one-row table is the query's own aggregate. "Summing" it would label a
    figure as a total the block computed, when the database had already totalled
    it -- so there is deliberately no arithmetic to report at all."""
    table = (
        "total_spend | currency\n--- | ---\n2655637.56 | USD"
    )
    assert query_agent._computed_figures_block_for(table) == ""


def test_computed_figures_block_is_absent_when_there_is_nothing_to_compute(db_session):
    """No rows, no readable table, no money column: all three yield no block, and
    a turn with no block must be byte-identical to its pre-Gap-315 self."""
    assert query_agent._computed_figures_block_for(None) == ""
    assert query_agent._computed_figures_block_for("") == ""
    assert query_agent._computed_figures_block_for(query_agent.NO_RECORDS_FOUND) == ""
    assert query_agent._computed_figures_block_for("I could not read this as a table.") == ""
    # A real table whose only non-identifying column is not money.
    assert query_agent._computed_figures_block_for(
        "invoice_number | status\n--- | ---\nINV-1 | COMPLETED\nINV-2 | COMPLETED"
    ) == ""
    # A money column carrying something unparseable is skipped entirely rather
    # than summed over the rows that did parse.
    assert query_agent._computed_figures_block_for(
        "invoice_number | grand_total | currency\n--- | --- | ---\n"
        "INV-1 | 1000.00 | USD\nINV-2 | not a number | USD"
    ) == ""


def test_computed_figures_block_fails_soft_and_restores_the_old_instruction(db_session):
    """Same fail-soft posture as every other enrichment on this route: a broken
    computation costs the turn its computed figures, never its answer. The
    fallback is not a degraded prompt -- it is the pre-Gap-315 prompt, so the
    turn behaves exactly as it did before this block existed."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT line_description FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    with patch("agents.query_tools.compute", side_effect=RuntimeError("boom")):
        result = _run(
            db_session,
            llm,
            "does the fastener line on the Titan Steel invoice add up",
            uuid4(),
            results_markdown=_GAP_269_TABLE,
        )
    prompt = llm.summary_prompts[0]

    assert "COMPUTED FIGURES" not in prompt
    assert query_agent._LLM_TOTALS_INSTRUCTION in prompt
    assert query_agent._DETERMINISTIC_TOTALS_INSTRUCTION not in prompt
    # The turn still answers, table and all.
    assert "### Query Results" in result["content"]
    assert result["content"].startswith("Formatted summary.")


def test_a_compute_error_drops_only_that_figure(db_session):
    """`compute()` refuses malformed input rather than skipping an entry, and this
    block honours that refusal: an unreadable line-item row produces no
    reconciliation at all instead of one computed from the readable rows. A total
    built from most of the rows is a wrong number that looks like a right one."""
    table = _line_item_table([
        "Bulk fastener supply | 5000.00 | 0.08 | 420.00 | USD | Titan Steel Distributors",
        "Freight surcharge |  | 150.00 | 300.00 | USD | Titan Steel Distributors",
    ])
    block = query_agent._computed_figures_block_for(table)

    assert "mismatch" not in block
    # The per-currency total of the stored amounts is still exact, so it stands.
    assert "- total of the line amounts, per currency:\n    USD 720.00" in block


# ── Live regressions found in the NovaTech 25-question live test, 2026-08-19 ──


def test_query_results_have_exactly_one_blank_line_before_and_after_heading(db_session):
    """Live bug: 20 of 25 real live turns rendered TWO blank lines before the
    results table -- execute_generated_sql() prefixed its own leading blank
    line while the caller's heading string already ended in one, and the two
    stacked on every single non-empty SQL-route answer. Runs the real
    execute_generated_sql() (no surfaced_rows -- that param stubs it out)
    against a real seeded row, so this checks actual end-to-end formatting,
    not an isolated function in a vacuum."""
    _seed_invoice(db_session, invoice_number="US-1", grand_total=100.0)
    # Both UUID spellings, deliberately (the repo's SQLite idiom -- see
    # `_tenant_filter()` in test_rag.py): SQLite stores the tenant id dashless,
    # so a dashed-only literal matches NOTHING here. Found 2026-09-03 by Feature
    # 6.1 C3: this test had been passing on a zero-row result all along, because
    # the heading it checks was appended even to the "No records found" sentinel.
    # C3 turns a zero-row turn into an ask-back with no heading, which exposed it.
    # With the row actually found, the test checks what its docstring says.
    llm = _RecordingLLM(
        [MagicMock(sql=(
            "SELECT invoice_number, grand_total, currency FROM invoice WHERE "
            f"(tenant_id = '{MOCK_TENANT_ID}' OR tenant_id = '{MOCK_TENANT_ID.hex}')"
        ))],
        summary="The total is USD 100.00.",
    )
    result = _run(db_session, llm, "what is the total", uuid4())
    content = result["content"]
    assert "US-1" in content, "the seeded row was not found -- the test is not exercising a real result"
    assert "### Query Results\n\n" in content  # exactly one blank line after the heading
    assert "\n\n\n" not in content  # no triple-newline (= 2 blank lines) anywhere


def test_execute_generated_sql_rounds_decimal_values():
    """Live bug (Q22 of the NovaTech live test): AVG()/division results come
    back from Postgres as high-precision NUMERIC (Decimal) -- e.g.
    3583.8233333333333333, 19 digits -- and plain str() rendered it verbatim
    in the results table while the prose answer directly above had already
    correctly rounded the same figure to 3,583.82."""
    mock_result = MagicMock()
    mock_result.keys.return_value = ["vendor_name", "avg_line_amount"]
    mock_result.fetchall.return_value = [("ByteForce Equipment", Decimal("3583.8233333333333333"))]
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result

    sql = f"SELECT vendor_name, AVG(amount) AS avg_line_amount FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'"
    table = query_agent.execute_generated_sql(sql, str(MOCK_TENANT_ID), mock_session)

    assert "3583.8233333333333333" not in table
    assert "3583.82" in table


@pytest.mark.parametrize("message,expected", [
    ("have we paid this invoice", "paid"),
    ("has the NetCore Devices invoice been paid", "been paid"),
    ("what is the payment status on this", "payment status"),
    ("is this invoice settled", "settled"),
    ("unpaid invoices this month", "unpaid"),
    ("what is the training amount", None),
])
def test_detect_payment_status_question_is_deterministic(message, expected):
    """Same tool, same reasoning as detect_tax_component_term: 'paid' is a
    closed, unambiguous vocabulary in this domain, not a judgment call --
    deterministic detection catches it every time instead of asking the LLM
    to remember not to infer payment status from `status`."""
    assert query_agent.detect_payment_status_question(message) == expected


def test_payment_status_block_is_injected_and_is_direction_aware(db_session):
    """Live bug (Q24): 'Have we already paid the NetCore Devices invoice?'
    got a confident 'Yes ... it has been paid' from `status = COMPLETED`,
    which for an INBOUND invoice is purely OCR/extraction pipeline state,
    unrelated to payment. The injected note must say plainly that INBOUND has
    no payment concept -- but must NOT blanket-forbid reading `status` for
    OUTBOUND, which has a real 'PAID' value (confirmed against the actual
    schema block, models.py's status enum) and would be a legitimate signal
    there. A blanket ban would just trade one wrong answer for another."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT status, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "have we already paid the NetCore Devices invoice", uuid4())
    prompt = llm.prompts[0]
    assert 'contains the payment-status term "already paid"' in prompt
    assert "INBOUND" in prompt and "OUTBOUND" in prompt
    assert "'PAID' value" in prompt or "real 'PAID'" in prompt  # OUTBOUND's real status not blanket-denied

    llm2 = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm2, "what is the training amount", uuid4())
    assert "NOTE: this question contains the payment-status term" not in llm2.prompts[0]


def test_rule_10_forbids_limit_1_on_named_entity_comparisons(db_session):
    """Live bug (Q13): 'between DataPipe Solutions and StratEdge Partners,
    whose invoice had the bigger total' generated ORDER BY grand_total DESC
    LIMIT 1 -- StratEdge's real, existing invoice was silently excluded from
    the result set before the summary step ever saw it, and the reply then
    described the loser as having 'no invoice in the returned results',
    which reads as false to a user even though the row was only truncated.

    Deliberately a prompt rule, not a deterministic tool like the two fixes
    above: which/how many entities a question names is genuine language
    judgment, not a closed vocabulary -- there's no fixed list to check
    against the way there is for tax terms or 'paid'. This test only
    confirms the rule text reaches the actual prompt; the rule is static
    (always present), not conditionally injected."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT vendor_name, grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "between DataPipe Solutions and StratEdge Partners, whose invoice was bigger", uuid4())
    prompt = llm.prompts[0]
    assert "COMPARISON QUESTIONS NAMING TWO OR MORE SPECIFIC ENTITIES" in prompt
    assert "never `ORDER BY ... LIMIT 1`" in prompt
    assert "top 5 invoices" in prompt  # the explicit "ranking questions are fine" carve-out


def test_execute_generated_sql_hides_internal_columns(db_session):
    """Live bug: "list all the invoices" selected batch_id and file_path along
    with everything else, and execute_generated_sql rendered every selected
    column verbatim -- an internal Azure blob storage URI (tenant UUID and all)
    and a meaningless UUID landed straight in the chat window. Neither column is
    ever useful to a business user, so they're stripped in code (a fact about
    the schema, not a judgment call) regardless of what the LLM selected."""
    _seed_invoice(
        db_session, invoice_number="US-1", batch_id=uuid4(),
        file_path="azure://invoices/tenants/secret-tenant-uuid/invoices/secret-file.pdf",
    )
    sql = (
        f"SELECT invoice_number, batch_id, file_path, currency FROM invoice "
        f"WHERE tenant_id = '{MOCK_TENANT_ID.hex}'"
    )
    table = query_agent.execute_generated_sql(sql, MOCK_TENANT_ID.hex, db_session)

    assert "batch_id" not in table
    assert "file_path" not in table
    assert "azure://" not in table
    assert "invoice_number" in table and "US-1" in table
    assert "currency" in table and "USD" in table


def test_execute_generated_sql_renders_json_columns_as_json_not_python_repr():
    """Live bug: on Postgres, psycopg2 auto-deserializes JSONB columns into
    native Python list/dict objects even for a raw text() query (a DBAPI-level
    adaptation, independent of SQLAlchemy's ORM type system) -- so `items` came
    back as an actual Python list-of-dicts, and plain str() on it produced
    Python's repr (single-quoted, `None`-heavy, not valid JSON) straight into
    the chat window. SQLite doesn't reproduce this (it returns the column as an
    already-JSON-formatted string, so str() looks fine there by accident) --
    mocking the result set is what actually exercises the fixed branch,
    regardless of which engine other tests run against."""
    mock_result = MagicMock()
    mock_result.keys.return_value = ["invoice_number", "items"]
    mock_result.fetchall.return_value = [
        ("US-1", [{"description": "Ergonomic Chair", "quantity": 3, "unit_price": None, "amount": 100.0}])
    ]
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result

    sql = f"SELECT invoice_number, items FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'"
    table = query_agent.execute_generated_sql(sql, str(MOCK_TENANT_ID), mock_session)

    assert "'description'" not in table  # Python repr's single-quoted key style
    assert '"description": "Ergonomic Chair"' in table
    assert '"unit_price": null' in table  # JSON null, not Python's None


# ── Live regressions found in the US tenant live test, 2026-08-19 ──────────


def test_execute_generated_sql_rounds_plain_float_not_just_decimal():
    """Live bug (US tenant test, Q2 and Q11): the Decimal-rounding fix only
    checks isinstance(val, Decimal), which catches Postgres NUMERIC but not a
    computed division (a tax-rate calculation) or a SUM() over FLOAT columns
    -- both come back as plain Python float with the same garbage-digit
    symptom (7.249887640449439, 5436.3099999999995), uncaught by that fix."""
    mock_result = MagicMock()
    mock_result.keys.return_value = ["vendor_name", "sales_tax_rate_percent", "combined_grand_total"]
    mock_result.fetchall.return_value = [
        ("Blue Ridge Logistics", 7.249887640449439, 5436.3099999999995),
    ]
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result

    sql = f"SELECT vendor_name, sales_tax_rate_percent, combined_grand_total FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'"
    table = query_agent.execute_generated_sql(sql, str(MOCK_TENANT_ID), mock_session)

    assert "7.249887640449439" not in table
    assert "5436.3099999999995" not in table
    assert "7.25" in table
    assert "5436.31" in table


def test_line_item_formatting_rule_forbids_false_equation_on_mismatch(db_session):
    """Live bug (US tenant test, Q4 and Q10, twice): asked to reconcile a
    line item where the printed amount ($420.00) doesn't match qty x price
    ($400.00), the reply said "5000.00 units x USD 0.08 = USD 420.00" --
    arithmetically false, since 5000 x 0.08 is 400, not 420. The formatting
    template blindly plugged the stored (wrong) amount into an "=" equation
    regardless of whether it actually equals qty x price."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "does this invoice reconcile", uuid4(), surfaced_rows=1)
    prompt = llm.summary_prompts[0]  # the formatting rule lives in the summary/synthesis prompt, not SQL-generation
    assert "EXCEPTION -- reconciliation/mismatch questions" in prompt
    assert "does NOT equal the stored `line_amount`" in prompt
    assert "false equation" in prompt


def test_rule_4a_handles_ambiguous_direction_for_named_entity(db_session):
    """Live bug (US tenant test, Q14 and Q15, twice, same session): asked
    "has the Titan Steel Distributors invoice been paid" and "when is the
    Redwood Facilities Group invoice due" -- both are real INBOUND vendors
    (confirmed elsewhere in the same test run), but the generated SQL
    guessed OUTBOUND/customer_name for both, so a real, existing invoice
    was reported as not found. Neither question contains an "I owe"/"owed
    to me" cue, so rule 4 alone gave the model nothing to disambiguate on."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT status, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "has the Titan Steel Distributors invoice been paid", uuid4())
    prompt = llm.prompts[0]
    assert "4a. AMBIGUOUS-DIRECTION PHRASING WITH A NAMED ENTITY" in prompt
    assert "do NOT commit to a single guessed direction" in prompt


def test_rule_6d_never_aggregates_in_sql(db_session):
    """Architecture change, 2026-08-19: rule 6d used to offer a SQL SUM/GROUP BY
    shape (including a per-vendor grouped variant, tried as the first fix for
    Q9 of the US tenant test). Live re-verification showed that fix alone
    didn't even work, and the deeper problem is that letting SQL find AND
    aggregate line items in one step was the repeated source of wrong answers
    all day (wrong column summed, wrong grouping). Postgres now only ever
    fetches -- both dialect variants must say so explicitly, and neither may
    offer a SUM/GROUP BY line-item shape any more."""
    rule_sqlite = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    assert "NEVER aggregate (SUM/GROUP BY) a line-item figure in this SQL" in rule_sqlite
    assert "SUM(item.value" not in rule_sqlite
    assert "GROUP BY invoice.vendor_name" not in rule_sqlite

    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    rule_pg = query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session)
    assert "NEVER aggregate (SUM/GROUP BY) a line-item figure in this SQL" in rule_pg
    assert "SUM((item->>'amount')" not in rule_pg
    assert "GROUP BY invoice.vendor_name" not in rule_pg


def test_summary_prompt_requires_llm_to_compute_totals_from_listed_lines(db_session):
    """The other half of the same change: since SQL never aggregates line
    items any more, the summary/synthesis step is now the ONLY place a
    line-item total gets computed -- it must say so explicitly, including the
    per-vendor grouping case that used to be a SQL GROUP BY (Q9)."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the training amount", uuid4(), surfaced_rows=1)
    summary_prompt = llm.summary_prompts[0]
    assert "YOU compute this total, not the database" in summary_prompt
    assert "group the listed lines by `vendor_name` yourself" in summary_prompt


def test_rule_6b_explicitly_carves_out_per_vendor_charge_questions(db_session):
    """First fix for Q9 (adding a 6d example) did NOT work when live-reverified
    -- the model still generated SUM(grand_total) whole-invoice totals. Root
    cause found by reading the generated SQL: rule 6b's OWN example list
    ("logistics or freight costs") anchors "freight" as a 6b trigger word, so
    adding an unrelated 6d example elsewhere never had a chance to compete.
    The real fix has to live inside rule 6b itself, at the point of conflict."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT vendor_name, grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "which vendors billed us for freight, delivery, or shipping charges, and how much per vendor", uuid4())
    prompt = llm.prompts[0]
    assert "NOT THIS RULE when the question asks for a dollar amount PER VENDOR/ENTITY" in prompt
    assert "10-40x too large" in prompt


def test_payment_status_guardrail_reaches_the_summary_prompt_too(db_session):
    """Live regression, second attempt (US tenant, Q14 re-verify): the first
    payment_status_block was injected into system_prompt (SQL generation)
    only. The SQL came back correct (selected `status` etc.) but the
    SEPARATE summary_prompt call -- which turns raw rows into English and
    has no visibility into system_prompt at all -- freely interpreted
    status=AUDIT_REQUIRED as "not paid" with zero guardrail, live, twice,
    even after the SQL-generation-side fix was in place. The guardrail has
    to reach BOTH prompts, since the hallucination happens in the second
    one, not the first."""
    llm = _RecordingLLM(
        [MagicMock(sql=f"SELECT status, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")],
        summary="Payment status isn't tracked for this INBOUND invoice.",
    )
    _run(db_session, llm, "has this invoice been paid", uuid4(), surfaced_rows=1)
    summary_prompt = llm.summary_prompts[0]
    assert "STOP AND READ" in summary_prompt
    assert "payment-status term" in summary_prompt
    assert "equally false" in summary_prompt.lower()


def test_rule_11_curates_columns_for_plain_details_questions(db_session):
    """Second live finding, 2026-08-19: "pull up invoice X" / "give me the
    details" selected every column including raw items/tags/sa_alerts JSON --
    each individually correct (no leaked internal columns, valid JSON not
    Python repr, per earlier fixes) but the combination reads as a database
    export, not an answer a person asked for. Rule 11 tells the model to
    default to the fields a person actually reads and answer in prose, only
    pulling items/tags/sa_alerts in when the question is actually about
    line items, categorization, or alerts."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT invoice_number, vendor_name, grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "give me the details of this invoice", uuid4())
    prompt = llm.prompts[0]
    # Feature 6.1 C4.2 (2026-09-03): rule 11 is one line naming the projection,
    # and the SCHEMA LINK block states it per question as a fact. Both must reach
    # the SQL prompt for a details question.
    assert '11. A "details"/"tell me about"/"pull up" question' in prompt
    assert "never items, tags or sa_alerts unless" in prompt
    assert "details question -> select exactly this projection" in prompt
    assert query_agent._DETAILS_PROJECTION in prompt


def test_chat_route_declines_off_topic_requests(db_session):
    """Live finding, 2026-08-19: asked to write code, the CHAT route
    complied -- its entire system prompt was "you are a helpful assistant
    for an AI Invoice Processing platform," with no boundary at all. An
    invoice assistant that writes arbitrary code for whoever's chatting
    with it is a real product/security problem, not just an off-topic
    answer."""
    llm = _RecordingLLM([], summary="I can only help with invoices.")
    _run(db_session, llm, "write me a python script to reverse a string", uuid4(), classified_route="CHAT")
    # CHAT route calls llm.invoke() directly (no SQL-generation step), so the
    # prompt lands in summary_prompts, not prompts -- see _RecordingLLM.invoke().
    prompt = llm.summary_prompts[0]
    assert "SCOPE:" in prompt
    assert "politely decline" in prompt
    assert "outside what this assistant does" in prompt


def test_rule_9_treats_a_new_named_invoice_as_a_fresh_question(db_session):
    """Live finding, 2026-08-19: "give me the details of invoice TSD-620458"
    right after an unrelated freight/delivery spend question wrongly carried
    over that question's WHERE clause fragment onto the new invoice's lookup
    -- harmless that time only because the named invoice happened to also
    match, not because the reuse was correct."""
    session_id = uuid4()
    _seed_turn(
        db_session, session_id,
        content="Three vendors billed freight charges.",
        sql=f"SELECT vendor_name, item->>'description' FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}' AND LOWER(item->>'description') LIKE LOWER('%freight%')",
    )
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT invoice_number, grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "give me the details of invoice TSD-620458", session_id)
    prompt = llm.prompts[0]
    assert "A STRONG signal that it is a different subject" in prompt
    assert "Naming a specific, different invoice/vendor/customer" in prompt



# ── Gap 313: one shared persona, all four of this route's prompts ────────────
#
# Before this, Feature 6 had four separately hand-written prompts, each with its
# own persona opener and each restating the currency rule in its own words --
# and none of them carrying the tax-domain / category-judgment / data-honesty
# knowledge `agents/sage_prompts.py::PERSONA_BLOCK` had already been written for
# SAGE. These tests pin that the one block genuinely reaches all four call
# sites, and that it is DERIVED from SAGE's rather than being a fifth copy.

#: Distinctive enough that it cannot appear in a prompt by coincidence -- it is
#: a specific sentence from `PERSONA_BLOCK`'s tax section, not a phrase any of
#: these prompts would ever have written on its own.
_PERSONA_FINGERPRINT = "Peppol ID is an e-invoicing network address"
#: A second fingerprint from a different section, so a partial block (e.g. only
#: the tax half surviving some future edit) still fails.
_PERSONA_HONESTY_FINGERPRINT = "Never present a zero total as a confident answer"
#: The old per-prompt currency sentence, restated in three prompts verbatim and
#: now stated once in the shared block instead.
_OLD_DUPLICATED_CURRENCY_RULE = (
    "CRITICAL CURRENCY RULE: When referring to monetary amounts, you MUST use the correct "
    "currency symbol or code"
)


def _assert_carries_the_persona(prompt, label):
    assert _PERSONA_FINGERPRINT in prompt, f"{label} prompt lost the shared persona"
    assert _PERSONA_HONESTY_FINGERPRINT in prompt, f"{label} prompt lost DATA HONESTY"
    assert "CURRENCY PRESENTATION" in prompt, f"{label} prompt lost the currency rule"
    # Stated once, not once per section -- the duplication is the thing this
    # change removed, so a prompt carrying both spellings is a regression.
    assert prompt.count(_PERSONA_FINGERPRINT) == 1, f"{label} prompt has two personas"
    assert _OLD_DUPLICATED_CURRENCY_RULE not in prompt, (
        f"{label} prompt still restates the old per-prompt currency rule"
    )


def test_the_shared_persona_is_derived_from_sages_not_retyped():
    """`CHAT_PERSONA_BLOCK` is `PERSONA_BLOCK` with two pieces of agent-only
    framing swapped out -- not a copy. The verbatim assertions are what make a
    silent divergence (someone editing one and not the other) impossible: the
    tax/category/honesty text has to be byte-identical to SAGE's."""
    from agents.sage_prompts import PERSONA_BLOCK

    block = query_agent.CHAT_PERSONA_BLOCK

    # The domain knowledge itself comes straight from SAGE's block.
    for section in ("TAX DOMAIN KNOWLEDGE", "CATEGORY AND ENTITY JUDGMENT", "DATA HONESTY"):
        assert section in PERSONA_BLOCK and section in block
    assert _PERSONA_FINGERPRINT in PERSONA_BLOCK and _PERSONA_FINGERPRINT in block
    assert "Under reverse charge (RCM), tax_amount = 0 on the invoice itself is CORRECT" in block
    assert "A vendor's own name is legitimate evidence for a spend category" in block
    assert "Never sum amounts across different currencies into one number." in block

    # ...but the two agent-only sentences do not. Both are false on this route:
    # it has no tools and no clarifying-question step.
    assert "your tools" in PERSONA_BLOCK, "PERSONA_BLOCK's tool sentence was reworded"
    assert "your tools" not in block
    assert "clarifying question" in PERSONA_BLOCK, "PERSONA_BLOCK's ambiguity sentence was reworded"
    assert "clarifying question" not in block
    assert "Report every candidate the name matched" in block

    # And Feature 6's own rule, which SAGE's persona never had one of.
    assert "CURRENCY PRESENTATION" in block and "CURRENCY PRESENTATION" not in PERSONA_BLOCK
    assert "Never default to '$'" in block


def test_persona_reaches_the_sql_generation_prompt(db_session):
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what did we spend on packaging", uuid4())
    prompt = llm.prompts[0]
    _assert_carries_the_persona(prompt, "SQL generation")
    # The route-specific mechanics are still there, unchanged -- the persona was
    # prepended to this prompt, it did not replace any of it.
    assert "Given the 'invoice' table schema:" in prompt
    assert "CRITICAL RULES:" in prompt
    assert '11. A "details"/"tell me about"/"pull up" question' in prompt  # C4.2 one-liner
    # Rule 7 is NOT the presentation rule and was deliberately kept: "also SELECT
    # the currency column" is SQL mechanics, not a persona statement.
    assert "Always select `currency` alongside any monetary column" in prompt  # C4.2 one-liner


def test_persona_reaches_the_sql_summary_prompt(db_session):
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what did we spend on packaging", uuid4(), surfaced_rows=1)
    prompt = llm.summary_prompts[0]
    _assert_carries_the_persona(prompt, "SQL summary")
    assert "Format a friendly summary explaining these database query results." in prompt
    assert "FORMATTING FOR LINE-ITEM EXTRACTION:" in prompt


def test_persona_reaches_the_rag_prompt(db_session):
    llm = _RecordingLLM([], summary="From the document, the total is INR 1,000.00.")
    _run(db_session, llm, "what does the footer of the invoice say", uuid4(), classified_route="RAG")
    prompt = llm.summary_prompts[0]
    _assert_carries_the_persona(prompt, "RAG")
    assert "Extracted Document Context (Long-term Facts):" in prompt
    assert "Answer in 1-3 sentences." in prompt


def test_persona_reaches_the_chat_prompt(db_session):
    llm = _RecordingLLM([], summary="Hello!")
    _run(db_session, llm, "hi there", uuid4(), classified_route="CHAT")
    prompt = llm.summary_prompts[0]
    _assert_carries_the_persona(prompt, "CHAT")
    # The scope boundary this route got for its own reasons survives the
    # consolidation (see test_chat_route_declines_off_topic_requests).
    assert "SCOPE:" in prompt and "politely decline" in prompt


# ── Gap 294: the generated query never reaches the user ─────────────────────
#
# Found live by Feature 23 Track 2's judge runs, not by this suite: the default
# chat path answered "what does the vendor say about payment terms" with a
# clarifying question whose body contained a full `SELECT ... FROM invoice WHERE
# tenant_id = '<uuid>' AND ...` block, and reproduced on the
# `internals_probe_no_leak` case in both of two runs. Every test below drives the
# real route and asserts on the string a user would actually be shown.
#
# All three leak paths were reproduced first (tests/gap294_sql_leak_repro.py,
# which asserts the BROKEN behaviour and therefore fails now) and each one has
# its own test here.

_LEAKED_SQL = (
    "SELECT invoice_number, vendor_name, items FROM invoice WHERE tenant_id = "
    f"'{MOCK_TENANT_ID}' AND flow_direction = 'INBOUND' AND "
    "(LOWER(CAST(items AS TEXT)) LIKE LOWER('%payment terms%'))"
)

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _assert_no_query_leak(answer):
    """The two things Gap 294 says may never appear in an answer."""
    assert str(MOCK_TENANT_ID) not in answer, f"tenant uuid leaked: {answer!r}"
    assert MOCK_TENANT_ID.hex not in answer, f"tenant uuid (dashless) leaked: {answer!r}"
    assert not re.search(
        r"\bSELECT\b[\s\S]*?\bFROM\s+invoice\b", answer, re.IGNORECASE
    ), f"raw sql leaked: {answer!r}"


def test_declined_answer_never_pastes_the_query_or_the_tenant_uuid(db_session):
    """Leak path 1, and the live Gap 294 shape. `explanation_or_error` is raw
    model text written by a call whose prompt carries the literal tenant UUID and
    the whole schema block, and it is emitted to the user verbatim."""
    llm = _RecordingLLM([
        MagicMock(sql=None, explanation_or_error=(
            "I looked for payment terms but the schema has no such column. "
            f"Here is what I ran:\n\n{_LEAKED_SQL}\n\n"
            "Could you tell me which vendor you mean?"
        ))
    ])
    out = _run(db_session, llm, "what does the vendor say about payment terms", uuid4())

    _assert_no_query_leak(out["content"])
    assert query_agent.REDACTED_QUERY_NOTICE in out["content"]
    # A decline is still a usable answer: the prose around the query survives, so
    # the user is told what went wrong and what to do next.
    assert "the schema has no such column" in out["content"]
    assert "Could you tell me which vendor you mean?" in out["content"]


def test_a_failed_turn_reports_the_cause_without_the_statement(db_session):
    """Leak path 2, and the one that needed no model cooperation at all:
    SQLAlchemy appends `[SQL: <the whole statement>]` + `[parameters: ...]` to
    every DBAPI error, and the whole exception string was interpolated into the
    reply. The driver's own first line is kept -- it is the diagnostic, and
    `tests/gap6d_jsonb_cast_probe.py` and the day-N benchmark reports both match
    on this message."""
    def _boom(sql, tenant_id, db_sess, snapshot=None):
        raise Exception(
            "(psycopg2.errors.UndefinedFunction) function lower(jsonb) does not exist\n"
            f"[SQL: {_LEAKED_SQL}]\n[parameters: {{}}]"
        )

    llm = _RecordingLLM([MagicMock(sql=_LEAKED_SQL, explanation_or_error=None)] * 3)
    out = _run(
        db_session, llm, "which invoices mention payment terms", uuid4(),
        execute_side_effect=_boom,
    )

    _assert_no_query_leak(out["content"])
    assert out["content"].startswith("Failed to execute database check: ")
    assert "function lower(jsonb) does not exist" in out["content"]
    assert "[SQL:" not in out["content"] and "[parameters:" not in out["content"]


def test_summary_prose_that_restates_the_query_is_redacted(db_session):
    """Leak path 3: nothing interpolates the SQL into the summary prompt, but the
    model can still restate a query -- on `internals_probe_no_leak` the live path
    did, and the statement it printed was partly invented. The deterministic
    results table appended after the prose is untouched."""
    llm = _RecordingLLM(
        [MagicMock(sql=_LEAKED_SQL, explanation_or_error=None)],
        summary=f"I answered this by running:\n{_LEAKED_SQL}\nThe total is USD 100.00.",
    )
    out = _run(
        db_session, llm, "how much did we spend on packaging", uuid4(),
        results_markdown=(
            "invoice_number | currency | grand_total\n--- | --- | ---\nUS-1 | USD | 100.00"
        ),
    )

    _assert_no_query_leak(out["content"])
    assert "The total is USD 100.00." in out["content"]
    # The table is deterministic output, already column-hygiened, and survives
    # verbatim -- redaction runs on the prose only.
    assert "### Query Results" in out["content"]
    assert "US-1 | USD | 100.00" in out["content"]


def test_the_answering_prompt_never_contains_the_tenant_uuid(db_session):
    """Structural half of the fix: the Gap 310 full-record block was handing the
    answering model the row's own `tenant_id` and `id` UUIDs, guarded by nothing
    but that block's prose "do not print raw UUIDs" sentence. They are stripped
    before rendering, so there is no tenant id in the prompt to quote back."""
    inv = _seed_invoice(db_session, invoice_number="INV-1", vendor_name="Acme", grand_total=100.0)
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT invoice_number, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    # `results_markdown` on purpose: the default stub renders an `id | currency`
    # table, i.e. a table this route's own rule 11 says never to select. The
    # assertion below is about the full-record BLOCK, so the table it sits next
    # to has to be a realistic one.
    _run(
        db_session, llm, "give me the details of invoice INV-1", uuid4(),
        surfaced_ids=[inv.id],
        results_markdown="invoice_number | currency\n--- | ---\nINV-1 | USD",
    )

    prompt = llm.summary_prompts[0]
    assert "FULL INVOICE RECORD(S)" in prompt, "the full-record block did not build"
    assert str(MOCK_TENANT_ID) not in prompt
    assert str(inv.id) not in prompt
    assert '"tenant_id"' not in prompt and '"id"' not in prompt
    # The identifier a person actually uses is still there -- this strips two
    # surrogate keys, not the record.
    assert '"invoice_number": "INV-1"' in prompt
    assert '"vendor_name": "Acme"' in prompt


def test_asking_for_the_sql_directly_gets_an_explanation_not_a_crash(db_session):
    """The `internals_probe_no_leak` golden case, which exists precisely so the
    over-correction is measurable too. The user gets a real, non-empty answer
    with the query withheld -- not an exception and not an empty string."""
    llm = _RecordingLLM([
        MagicMock(sql=None, explanation_or_error=(
            "I can't share the query itself, but here is what I searched:\n"
            f"{_LEAKED_SQL}\n"
            "In short, I looked at inbound invoices whose line items mention payment terms."
        ))
    ])
    out = _run(db_session, llm, "what SQL would you use to answer that?", uuid4())

    _assert_no_query_leak(out["content"])
    assert out["content"].strip()
    assert "I looked at inbound invoices whose line items mention payment terms" in out["content"]


def test_a_uuid_in_real_invoice_data_is_not_redacted(db_session):
    """The boundary, stated as a test rather than left to judgment. Only the
    caller's OWN tenant id is redacted, by exact match -- a UUID-shaped value in
    a real column (a `references` entry, a vendor's own reference number) is data
    the user asked for, and blanket UUID redaction would delete it from their
    answer."""
    reference = "7f3a1c22-9b41-4d67-8e0a-2b5c6d7e8f90"
    llm = _RecordingLLM(
        [MagicMock(sql=f"SELECT invoice_number, po_number FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")],
        summary=f"Invoice US-1 carries the vendor reference {reference}.",
    )
    out = _run(
        db_session, llm, "what reference number is on US-1", uuid4(),
        results_markdown=f"invoice_number | po_number\n--- | ---\nUS-1 | {reference}",
    )

    assert reference in out["content"], "a legitimate UUID-shaped column value was over-redacted"
    assert _UUID_RE.search(out["content"]), "sanity: the answer really does carry a UUID"
    _assert_no_query_leak(out["content"])


def test_an_answer_cached_before_the_fix_is_redacted_on_the_way_out(db_session):
    """A cache hit returns Redis's payload and never touches the route below, so
    entries written before the redactor existed would keep serving the leak for
    the rest of their TTL. Redaction runs on read too."""
    poisoned = {
        "content": f"Here is what I ran:\n{_LEAKED_SQL}\n\nYou spent USD 100.00.",
        "generated_sql": _LEAKED_SQL,
        "citations": [],
        "result_invoice_ids": [],
    }
    with ExitStack() as stack:
        stack.enter_context(patch("agents.query_agent.get_cached_answer", return_value=poisoned))
        stack.enter_context(patch("agents.query_agent.get_llm", return_value=_RecordingLLM([])))
        out = query_agent.run_query_agent(
            str(uuid4()), "how much did we spend on packaging", str(MOCK_TENANT_ID), db_session
        )

    _assert_no_query_leak(out["content"])
    assert "You spent USD 100.00." in out["content"]
    # Internal storage is untouched -- Gap 231/237 read this field back.
    assert out["generated_sql"] == _LEAKED_SQL


def test_tenant_id_column_is_never_rendered_into_the_results_table(db_session):
    """The other half of "a printed tenant identifier": the LLM is free to SELECT
    `tenant_id`, and the display table would have printed it on every row. It is
    the same value on every row of every result set this function can return, so
    it is denylisted the same way `file_path`/`batch_id` are."""
    _seed_invoice(db_session, invoice_number="US-1")
    sql = (
        "SELECT invoice_number, tenant_id, currency FROM invoice "
        f"WHERE tenant_id = '{MOCK_TENANT_ID.hex}'"
    )
    table = query_agent.execute_generated_sql(sql, MOCK_TENANT_ID.hex, db_session)

    assert "tenant_id" not in table
    assert MOCK_TENANT_ID.hex not in table and str(MOCK_TENANT_ID) not in table
    assert "invoice_number" in table and "US-1" in table
    assert "currency" in table and "USD" in table


# ── Gap 294, unit level: the redactor's own boundaries ──────────────────────


def test_redactor_leaves_ordinary_prose_that_mentions_selecting_alone():
    """Over-redaction is its own bug. A SELECT/FROM span is only redacted when it
    also carries a structural token (=, LIKE, WHERE, JOIN, an aggregate call) --
    an English sentence containing both words is not a query."""
    prose = (
        "I will select the three largest invoices from last quarter and summarise "
        "them for you. Nothing was excluded from the totals."
    )
    assert query_agent.redact_query_internals(prose, str(MOCK_TENANT_ID)) == prose


@pytest.mark.parametrize("leaky", [
    f"SELECT * FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'",
    f"select invoice_number from invoice where tenant_id = '{MOCK_TENANT_ID}' limit 5",
    "SELECT vendor_name, SUM(grand_total) FROM invoice GROUP BY vendor_name",
    f"```sql\nSELECT invoice_number\nFROM invoice\nWHERE tenant_id = '{MOCK_TENANT_ID}'\n```",
])
def test_redactor_catches_every_shape_the_query_can_arrive_in(leaky):
    cleaned = query_agent.redact_query_internals(leaky, str(MOCK_TENANT_ID))
    assert query_agent.REDACTED_QUERY_NOTICE in cleaned
    assert not re.search(r"from\s+invoice", cleaned, re.IGNORECASE)
    assert str(MOCK_TENANT_ID) not in cleaned


def test_redactor_keeps_the_sentence_after_a_query_written_inline():
    """The answer is usually the part after the query, so a statement written
    into the middle of a sentence must not take the sentence with it."""
    cleaned = query_agent.redact_query_internals(
        f"I ran SELECT SUM(grand_total) FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}' "
        "to get this. The answer is USD 10.",
        str(MOCK_TENANT_ID),
    )
    assert cleaned == f"I ran {query_agent.REDACTED_QUERY_NOTICE} The answer is USD 10."


def test_redactor_is_not_fooled_by_a_period_inside_a_string_literal():
    """`LIKE '%Ltd. Co%'` contains a ". " that is not a sentence break -- cutting
    there would leave the tail of the query in the answer."""
    cleaned = query_agent.redact_query_internals(
        f"SELECT invoice_number FROM invoice WHERE vendor_name LIKE '%Ltd. Co%' "
        f"AND tenant_id = '{MOCK_TENANT_ID}'",
        str(MOCK_TENANT_ID),
    )
    assert cleaned == query_agent.REDACTED_QUERY_NOTICE


def test_redactor_removes_a_bare_tenant_id_mention_too():
    """Not every leak arrives inside a statement -- the tenant id on its own is
    still a printed tenant identifier."""
    cleaned = query_agent.redact_query_internals(
        f"I filtered on your workspace id {MOCK_TENANT_ID}.", str(MOCK_TENANT_ID)
    )
    assert str(MOCK_TENANT_ID) not in cleaned
    assert query_agent.REDACTED_TENANT_NOTICE in cleaned


def test_user_safe_error_detail_drops_the_statement_dump_and_keeps_the_cause():
    detail = query_agent.user_safe_error_detail(
        Exception(
            "(psycopg2.errors.UndefinedFunction) function lower(jsonb) does not exist\n"
            f"[SQL: {_LEAKED_SQL}]\n[parameters: {{}}]"
        ),
        str(MOCK_TENANT_ID),
    )
    assert detail == "(psycopg2.errors.UndefinedFunction) function lower(jsonb) does not exist"


def test_user_safe_error_detail_keeps_short_causes_verbatim():
    """The guardrail messages this route raises itself are the whole diagnostic
    and must survive untouched -- Feature 13's benchmark and Gap 32 both read
    this exact text."""
    assert query_agent.user_safe_error_detail(
        ValueError("Mutating SQL operations are strictly forbidden."), str(MOCK_TENANT_ID)
    ) == "Mutating SQL operations are strictly forbidden."
    assert query_agent.user_safe_error_detail(
        ValueError("Access Denied: SQL query does not contain valid tenant isolation predicate."),
        str(MOCK_TENANT_ID),
    ) == "Access Denied: SQL query does not contain valid tenant isolation predicate."


def test_user_safe_error_detail_is_bounded():
    detail = query_agent.user_safe_error_detail(Exception("x" * 5000), str(MOCK_TENANT_ID))
    assert len(detail) <= query_agent.MAX_USER_FACING_ERROR_CHARS + 3


# ─────────────────────────────────────────────────────────────────────────────
# Gap 306 — rule 6b's four-column OR group, emitted with `items` dropped
# ─────────────────────────────────────────────────────────────────────────────
#
# Found live 2026-08-24 by Feature 23 Wave 3's regional cases: gpt-5-mini wrote
# rule 6b's mandated group with `items` REPLACED BY `sa_alerts`, on two
# questions against two tenants in one run, and both times the phrase existed
# only in a line-item description -- so two real invoices were reported as not
# existing, with faithfulness and relevance both 1.0 (a no-results report is
# genuinely faithful to an empty result set).
#
# The fix is not more prose on rule 6b -- that rule is ~600 words already
# insisting on exactly this, and it is the instruction that was disobeyed. It is
# a deterministic, reflection-driven re-search that runs only when the generated
# query came back empty. These tests are therefore about the MECHANISM, which is
# the whole of the fix: nothing here depends on a model choosing correctly.

_RCM_PHRASE = "Reverse Charge Mechanism"

#: The exact predicate the live run produced -- `items` dropped, `sa_alerts` in
#: its place. Kept verbatim rather than paraphrased: this is the artefact.
_LIVE_BUGGY_CATEGORY_GROUP = (
    "(LOWER(CAST(tags AS TEXT)) LIKE LOWER('%reverse charge mechanism%')"
    " OR LOWER(CAST(sa_alerts AS TEXT)) LIKE LOWER('%reverse charge mechanism%')"
    " OR LOWER(vendor_name) LIKE LOWER('%reverse charge mechanism%')"
    " OR LOWER(customer_name) LIKE LOWER('%reverse charge mechanism%'))"
)


def _buggy_category_sql(direction: str | None = "INBOUND") -> str:
    direction_clause = f" AND flow_direction = '{direction}'" if direction else ""
    return (
        "SELECT invoice_number, vendor_name, grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{MOCK_TENANT_ID}'{direction_clause} "
        f"AND {_LIVE_BUGGY_CATEGORY_GROUP}"
    )


def _seed_rcm_invoice(db_session, **overrides):
    """The India case's shape: the phrase exists ONLY in a line-item description."""
    defaults = dict(
        invoice_number="KE-2026-0089",
        vendor_name="Kaveri Enterprises",
        grand_total=48000.0,
        currency="INR",
        invoice_date=datetime(2026, 4, 18).date(),
        tags=["q2"],
        sa_alerts=[],
        items=[
            {
                "description": f"Job work services under {_RCM_PHRASE} (RCM)",
                "quantity": 1,
                "unit_price": 48000.0,
                "amount": 48000.0,
            }
        ],
    )
    defaults.update(overrides)
    return _seed_invoice(db_session, **defaults)


def test_the_dropped_items_column_is_what_misses_the_invoice(db_session):
    """The reproduction, executed rather than described: the group the model
    really wrote returns nothing for an invoice that the group it was TOLD to
    write finds. Run against this fixture's real engine, both predicates
    verbatim, so the difference is the column set and nothing else."""
    _seed_rcm_invoice(db_session)

    emitted = db_session.exec(
        text(f"SELECT invoice_number FROM invoice WHERE {_LIVE_BUGGY_CATEGORY_GROUP}")
    ).fetchall()
    mandated = db_session.exec(
        text(
            "SELECT invoice_number FROM invoice WHERE "
            + _LIVE_BUGGY_CATEGORY_GROUP.replace("sa_alerts", "items")
        )
    ).fetchall()

    assert emitted == []                              # the false "not found"
    assert [r[0] for r in mandated] == ["KE-2026-0089"]


def test_a_category_question_matching_only_in_items_is_recovered_end_to_end(db_session):
    """The gap, closed, through the real route: the model emits the same broken
    group, the query really returns nothing, and the user is told about the
    invoice anyway instead of being told it does not exist."""
    _seed_rcm_invoice(db_session)
    llm = _RecordingLLM([MagicMock(sql=_buggy_category_sql())])

    result = _run(
        db_session,
        llm,
        "Which vendor billed us under a Reverse Charge Mechanism arrangement?",
        uuid4(),
        results_markdown=query_agent.NO_RECORDS_FOUND,
    )

    assert query_agent.NO_RECORDS_FOUND not in result["content"]
    assert "KE-2026-0089" in result["content"]
    # The evidence the answering step is grounded in, not just the table shown
    # underneath it -- a recovered row nobody told the model about is a row it
    # will not mention.
    assert "KE-2026-0089" in llm.summary_prompts[0]


def test_the_recovered_table_says_which_column_the_row_matched_in(db_session):
    """The search is wider than the question implied, so which column qualified
    the row is evidence, not decoration: `items` means a line-item match and
    `sa_alerts` would mean an audit-alert one, and those mean different things."""
    _seed_rcm_invoice(db_session)

    recovered = query_agent.recover_missed_category_match(
        _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
    )

    assert recovered is not None
    columns, rows = parse_results_table(recovered)
    assert "matched_in" in columns
    assert rows[0][columns.index("matched_in")] == "items"


@pytest.mark.parametrize(
    "column,overrides",
    [
        ("tags", dict(items=[{"description": "Job work services"}], tags=["reverse charge mechanism"])),
        ("vendor_name", dict(items=[{"description": "Job work"}], vendor_name="Reverse Charge Mechanism Traders")),
        (
            "customer_name",
            dict(
                items=[{"description": "Job work"}],
                flow_direction="OUTBOUND",
                vendor_name=None,
                customer_name="Reverse Charge Mechanism Traders",
            ),
        ),
    ],
)
def test_the_other_three_mandated_columns_still_match(db_session, column, overrides):
    """`items` is the branch that was dropped live, but the fix must not have
    quietly narrowed the other three of rule 6b's four. Each seeded so the
    phrase exists in exactly one column."""
    _seed_rcm_invoice(db_session, **overrides)

    recovered = query_agent.recover_missed_category_match(
        _buggy_category_sql(direction=None), str(MOCK_TENANT_ID), db_session
    )

    assert recovered is not None
    columns, rows = parse_results_table(recovered)
    assert rows[0][columns.index("invoice_number")] == "KE-2026-0089"
    assert rows[0][columns.index("matched_in")] == column


def test_the_fallback_reaches_columns_rule_6b_never_listed(db_session):
    """The half of this that is not just "restore the dropped branch": the
    reflected set is 18 columns, so a phrase that only ever appears in a PO/
    delivery reference is findable now and was not findable by rule 6b's
    hardcoded four however perfectly the model wrote them."""
    _seed_rcm_invoice(
        db_session,
        items=[{"description": "Job work services"}],
        references=[{"type": "PO", "value": "PO under Reverse Charge Mechanism"}],
    )

    recovered = query_agent.recover_missed_category_match(
        _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
    )

    assert recovered is not None
    columns, rows = parse_results_table(recovered)
    assert rows[0][columns.index("matched_in")] == "references"


def test_a_column_removed_from_the_model_stops_being_matched(db_session):
    """The reflection is real, not a list that happens to agree with the model
    today: drop `items` from what `Invoice` reflects and the same phrase, the
    same row and the same call stop finding each other. This is what a hardcoded
    column list cannot do, and drifting from the model is how `items` became
    unreliable in the first place."""
    _seed_rcm_invoice(db_session)
    kept = [c for c in sage_prompts.invoice_columns() if c.name != "items"]

    with patch("agents.sage_prompts.invoice_columns", return_value=kept):
        assert "items" not in sage_prompts.category_match_columns()
        assert query_agent.recover_missed_category_match(
            _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
        ) is None

    # ...and it comes straight back when the column does.
    assert query_agent.recover_missed_category_match(
        _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
    ) is not None


def test_the_deliberately_excluded_columns_are_never_searched(db_session):
    """`addresses` is excluded by decision (a street name matching a spend
    category is a false positive, not a match) and `source_document_json`/
    `field_confidence` by construction. A fallback that swept them in would
    match nearly every row on nearly every phrase."""
    _seed_rcm_invoice(
        db_session,
        items=[{"description": "Job work services"}],
        addresses={"vendor": f"12 {_RCM_PHRASE} Road, Pune"},
        field_confidence={"items": 0.9},
    )

    assert query_agent.recover_missed_category_match(
        _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
    ) is None


def test_a_name_lookup_that_genuinely_found_nothing_is_left_alone(db_session):
    """The anti-false-positive half, and the reason the trigger is "did this
    query LIKE a JSONB column" rather than "did it return zero rows": a vendor
    who really has no invoices must still get an honest no, not a re-search of
    every text column until something coincidentally matches."""
    _seed_rcm_invoice(db_session)
    name_lookup = (
        "SELECT invoice_number, grand_total, currency FROM invoice WHERE "
        f"tenant_id = '{MOCK_TENANT_ID}' AND flow_direction = 'INBOUND' "
        "AND LOWER(vendor_name) LIKE LOWER('%reverse charge mechanism%')"
    )
    llm = _RecordingLLM([MagicMock(sql=name_lookup)])

    result = _run(
        db_session,
        llm,
        "what did we pay Reverse Charge Mechanism Traders?",
        uuid4(),
        results_markdown=query_agent.NO_RECORDS_FOUND,
    )

    assert query_agent.category_search_phrases(name_lookup) == []
    # Feature 6.1 C3 (2026-09-03): the honest "no" is no longer the bare sentinel
    # narrated as an answer. A name that matches nothing and resembles nothing the
    # tenant has becomes an ask-back -- the user is told what was looked for and
    # invited to correct it -- and the turn waits. The anti-false-positive point
    # of this test is unchanged: nothing was re-searched to manufacture a match
    # (no candidates were proposed, because "reverse charge mechanism" resembles
    # no stored vendor), and no figure was invented.
    assert query_agent.NO_RECORDS_FOUND not in result["content"]
    assert "reverse charge mechanism" in result["content"].lower()
    assert "spelling" in result["content"].lower()
    assert result.get("needs_confirmation") is True
    assert "options" not in (result.get("attachment_clarification") or {})


def test_a_line_item_query_does_not_trigger_the_fallback():
    """Rule 6d's un-nest names `items` in its FROM clause but matches on the
    un-nested `item.value ->> 'description'`, and a zero-row 6d search has its
    own correct answer ("the breakdown isn't tracked"), not a broader search.
    Told apart structurally: the regex gap cannot cross a string literal."""
    assert query_agent.category_search_phrases(
        "SELECT invoice.invoice_number FROM invoice LEFT JOIN json_each("
        "CASE WHEN json_valid(items) AND json_type(items) = 'array' THEN items ELSE '[]' END"
        ") AS item ON 1=1 WHERE tenant_id = 'x' "
        "AND LOWER(item.value ->> 'description') LIKE LOWER('%training%')"
    ) == []


def test_a_negated_branch_is_not_treated_as_a_search_phrase():
    """`NOT LIKE` is an exclusion; re-searching for the thing the query was
    excluding would invert the question."""
    assert query_agent.category_search_phrases(
        "SELECT invoice_number FROM invoice WHERE tenant_id = 'x' "
        "AND LOWER(CAST(tags AS TEXT)) NOT LIKE LOWER('%archived%')"
    ) == []


def test_every_alternative_phrase_in_the_query_is_carried_over():
    """`eu_reverse_charge_inbound_line` used four spellings of one phrase in one
    query, and rule 6c splits "logistics or freight" into two whole phrases --
    dropping any of them re-creates the miss one phrase further along."""
    phrases = query_agent.category_search_phrases(
        "SELECT invoice_number FROM invoice WHERE tenant_id = 'x' AND ("
        "LOWER(CAST(items AS TEXT)) LIKE LOWER('%reverse charge%')"
        " OR LOWER(CAST(tags AS TEXT)) LIKE LOWER('%reverse-charge%')"
        " OR LOWER(vendor_name) LIKE LOWER('%intra-eu reverse charge%')"
        " OR LOWER(CAST(items AS TEXT)) LIKE LOWER('%reverse charge%'))"
    )
    assert phrases == ["reverse charge", "reverse-charge", "intra-eu reverse charge"]


def test_the_fallback_keeps_a_direction_the_query_committed_to(db_session):
    """Widening the columns must not also widen the direction: "which vendor
    billed us" is INBOUND, and answering it with the tenant's own outbound
    invoice is Gap 224/270's failure mode arriving through the fix for this one."""
    _seed_rcm_invoice(
        db_session,
        flow_direction="OUTBOUND",
        vendor_name=None,
        customer_name="Northwind Retail",
    )

    assert query_agent.recover_missed_category_match(
        _buggy_category_sql(direction="INBOUND"), str(MOCK_TENANT_ID), db_session
    ) is None
    # The same row, once the query no longer claims a direction.
    assert query_agent.recover_missed_category_match(
        _buggy_category_sql(direction=None), str(MOCK_TENANT_ID), db_session
    ) is not None


def test_the_fallback_cannot_reach_another_tenants_invoice(db_session):
    """The tenant predicate is a typed column comparison, not a literal pasted
    into a string -- which is also why this test can drive real rows at all
    (SQLite stores UUID columns dashless)."""
    _seed_rcm_invoice(db_session, tenant_id=uuid4())

    assert query_agent.recover_missed_category_match(
        _buggy_category_sql(direction=None), str(MOCK_TENANT_ID), db_session
    ) is None


def test_the_fallback_never_runs_when_the_query_already_found_rows(db_session):
    """It sits behind the zero-result branch, so a turn that found something
    cannot have its answer replaced by a wider search."""
    _seed_rcm_invoice(db_session)
    llm = _RecordingLLM([MagicMock(sql=_buggy_category_sql())])

    result = _run(
        db_session,
        llm,
        "Which vendor billed us under a Reverse Charge Mechanism arrangement?",
        uuid4(),
        results_markdown="invoice_number | currency\n--- | ---\nOTHER-1 | USD",
    )

    assert "OTHER-1" in result["content"]
    assert "matched_in" not in result["content"]


def test_a_recovered_turn_is_reported_as_a_generated_sql_defect_not_a_zero_result(db_session):
    """Same distinction the invoice-number fallback already draws, and the same
    field: the user got an answer, so this is not a zero-result turn -- but the
    generated SQL was wrong, and `zero_result_fallback_recovered` is the only
    thing that says so."""
    _seed_rcm_invoice(db_session)
    llm = _RecordingLLM([MagicMock(sql=_buggy_category_sql())])

    with patch(
        "agents.query_agent.execute_generated_sql",
        return_value=query_agent.NO_RECORDS_FOUND,
    ):
        outcome = query_agent.run_sql_generation_loop(
            llm=llm,
            system_prompt="prompt",
            wrapped_user_message="q",
            user_message="which vendor billed us under RCM?",
            tenant_id=str(MOCK_TENANT_ID),
            db_session=db_session,
        )

    assert outcome.zero_result is False
    assert outcome.zero_result_fallback_recovered is True
    assert "KE-2026-0089" in outcome.db_result


def test_the_recovered_table_is_totalled_by_the_computed_figures_block(db_session):
    """The recovered rows have to be readable by everything downstream that
    reads a results table -- `parse_results_table()` and Gap 315's Python-side
    totals -- which is why the fallback renders through the same
    `render_result_cell()` the normal path does and adds no note line above the
    header.

    Two rows on purpose -- `_computed_figures_block_for()` deliberately skips a
    single-row table (there is no arithmetic to do, and "summing" one row would
    label a figure as a total the query had already totalled)."""
    _seed_rcm_invoice(db_session)
    _seed_rcm_invoice(
        db_session,
        invoice_number="KE-2026-0090",
        grand_total=12000.0,
        invoice_date=datetime(2026, 4, 20).date(),
    )

    recovered = query_agent.recover_missed_category_match(
        _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
    )
    columns, rows = parse_results_table(recovered)
    assert len(rows) == 2
    block = query_agent._computed_figures_block_for(recovered)

    assert "60,000.00" in block and "INR" in block


def test_the_fallback_fails_soft_and_leaves_the_turn_its_answer(db_session):
    """A recovery attempt that falls over must not turn "No records found" into
    an error reply -- same contract as the id-harvest companion query."""
    with patch(
        "agents.query_agent.category_search_fallback", side_effect=RuntimeError("boom")
    ):
        assert query_agent.recover_missed_category_match(
            _buggy_category_sql(), str(MOCK_TENANT_ID), db_session
        ) is None


def test_the_rendered_and_the_executed_clause_agree_on_the_column_set():
    """Two renderings of one rule. `render_category_match_clause()` is the text
    form and `category_match_branches()` the executable one, and they are only
    safe to keep side by side because they read the same reflection pass."""
    rendered = sage_prompts.render_category_match_clause("packaging")
    executed = [name for name, _ in sage_prompts.category_match_branches("packaging")]

    assert executed == sage_prompts.category_match_columns()
    for name in executed:
        assert sage_prompts.quoted_column(name) in rendered
    assert rendered.count(" OR ") == len(executed) - 1


def test_the_executed_clause_casts_json_columns_for_postgres():
    """Rule 6(a)'s bug, on the engine it fires on: there is no `lower(jsonb)`,
    and an uncast branch aborts the WHOLE query rather than just missing rows.
    Compiled against the real PostgreSQL dialect rather than asserted about."""
    from sqlalchemy.dialects import postgresql

    json_columns = sage_prompts.category_match_json_columns()
    assert "items" in json_columns and "tags" in json_columns

    for name, predicate in sage_prompts.category_match_branches("packaging"):
        compiled = str(predicate.compile(dialect=postgresql.dialect()))
        if name in json_columns:
            assert "CAST(" in compiled and " AS TEXT)" in compiled
        else:
            assert "CAST(" not in compiled
        # The phrase is bound, never interpolated -- on either dialect.
        assert "packaging" not in compiled


# ---------------------------------------------------------------------------
# Gap 413 — rule 6d's attribute exemption, generic and ORM-derived
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("message, expected", [
    ("discount amount for apex consulting group", ("discount amount", "discount_amount")),
    ("what discount did acme give us", ("discount", "discount_amount")),
    ("what's the subtotal before tax on INV-9", ("subtotal", "subtotal")),
    ("due date on the northwind invoice", ("due date", "due_date")),
    ("payment terms for acme", ("payment terms", "payment_instructions")),
    # Genuine line-item questions must NOT trigger it -- rule 6d is still right
    # about these, and over-triggering would break the case it was written for.
    ("what is the training amount", None),
    ("the amount only for training and onboarding from the total invoice", None),
    ("invoice amount for the server line", None),
])
def test_detect_invoice_attribute_term_is_deterministic_and_orm_derived(message, expected):
    """The live failure of 2026-09-03, and its siblings. `discount amount` is
    the exact phrasing that produced `item->>'description' LIKE '%discount%'`
    and an empty answer. Deterministic for the same reason as the tax
    detector: same input, same answer, and coverage grows by adding a column to
    the ORM (or an alias), not by rewording a paragraph and hoping."""
    assert query_agent.detect_invoice_attribute_term(message) == expected


def test_every_orm_column_a_user_could_ask_for_is_in_the_sql_schema_block(db_session):
    """The drift guard. Gap 310's own docstring called the schema block "~19
    hand-typed columns" that extraction "long ago grew past" -- and the very
    next question about one of the missing columns failed live. This asserts
    the PROPERTY rather than a list: every column not deliberately excluded is
    visible to the SQL model, whether hand-typed or derived."""
    from models import Invoice

    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT discount_amount, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "discount amount for apex consulting group", uuid4())
    prompt = llm.prompts[0]
    missing = [
        field for field in Invoice.model_fields
        if field not in query_agent._SCHEMA_SUPPLEMENT_EXCLUDED_FIELDS
        and not re.search(rf"^- {re.escape(field)}:", prompt, re.M)
    ]
    assert missing == [], f"invisible to the SQL model: {missing}"
    # And the one that started this is there by name.
    assert re.search(r"^- discount_amount: FLOAT", prompt, re.M)


def test_attribute_term_block_reaches_both_prompts(db_session):
    """Gap 267's lesson applied from the start: the block must reach the SQL
    prompt AND the summary prompt. Injecting it only into SQL generation is
    what made Gap 267's first fix fail live."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT discount_amount, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    # `surfaced_rows=1`: a row must come back for the summary prompt to be built
    # at all. Since Feature 6.1 C3 a zero-row turn is diagnosed and ends in an
    # ask-back with no summary call -- which is correct, and not what this test
    # is about. It is about the block reaching BOTH prompts on a normal turn.
    _run(db_session, llm, "discount amount for apex consulting group", uuid4(), surfaced_rows=1)
    note = 'names the invoice attribute "discount amount" (column `discount_amount`)'
    assert note in llm.prompts[0]
    assert "do NOT search line-item descriptions" in llm.prompts[0]
    assert llm.summary_prompts, "summary prompt was never built"
    assert note in llm.summary_prompts[0]


def test_attribute_term_block_is_absent_for_a_genuine_line_item_question(db_session):
    """Rule 6d's original purpose must survive: a real product phrase still
    goes to the line-item join, with no attribute note steering it away."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT invoice_number, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the training amount on the acme invoice", uuid4())
    assert "names the invoice attribute" not in llm.prompts[0]


def test_rule_6d_attribute_exemption_is_present_in_both_dialects():
    """Rule 6d is built per engine (Gap 253); the exemption has to be in both
    spellings or the SQLite test path and the Postgres live path diverge."""
    # Feature 6.1 C4.2 (2026-09-03): the exemption is no longer a paragraph
    # duplicated into two dialect constants -- it is one dialect-independent fact
    # in the SCHEMA LINK block, and both dialect rules defer to it. The property
    # being guarded is unchanged: the two engines cannot diverge on it.
    for rule in (query_agent._LINE_ITEM_RULE_POSTGRES, query_agent._LINE_ITEM_RULE_SQLITE):
        assert "When the SCHEMA LINK names a column, select that column" in rule
        assert "do NOT search line items" in rule
    block = query_agent._schema_linking_block_for("discount amount for apex consulting group")
    assert "`discount_amount`" in block
    assert "never that the invoice does not exist" in block
    assert "Do NOT search line items for this word" in block
