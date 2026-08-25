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
from agents import query_agent
from agents.query_agent import (
    _NO_FRESH_QUERY_NOTE,
    _NULL_SQL_FOLLOWUP_RETRY_DIRECTIVE,
    get_prior_turn_sql,
)

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
    """
    if surfaced_ids is not None and surfaced_rows is None:
        surfaced_rows = len(surfaced_ids)
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
            return "\n\nid | currency\n--- | ---\n" + "\n".join(f"{i} | USD" for i in ids)

        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=_fake_execute))

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
    format_section = summary_prompt.split("FORMATTING FOR LINE-ITEM EXTRACTION:")[1].split("CRITICAL CURRENCY RULE")[0]
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
    rule_sqlite = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    assert re.search(r"\bGST\b", rule_sqlite)  # plain "GST", not just as a substring of CGST/SGST/IGST
    assert "CGST" in rule_sqlite and "SGST" in rule_sqlite and "IGST" in rule_sqlite
    assert "tax_amount" in rule_sqlite
    assert "no invoice found" in rule_sqlite.lower() or "doesn't exist" in rule_sqlite.lower()
    # The generalizing instruction itself, not just a longer list of named terms --
    # this is what should catch the NEXT unlisted tax term too (TDS, cess, duty, ...).
    assert "not just the specific ones" in rule_sqlite or "not a fixed list" in rule_sqlite

    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    rule_pg = query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session)
    assert re.search(r"\bGST\b", rule_pg)
    assert "CGST" in rule_pg and "SGST" in rule_pg and "IGST" in rule_pg
    assert "tax_amount" in rule_pg
    assert "not just the specific ones" in rule_pg or "not a fixed list" in rule_pg


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
    llm = _RecordingLLM(
        [MagicMock(sql=f"SELECT invoice_number, grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")],
        summary="The total is USD 100.00.",
    )
    result = _run(db_session, llm, "what is the total", uuid4())
    content = result["content"]
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
    assert '11. "DETAILS" QUESTIONS ABOUT ONE SPECIFIC INVOICE' in prompt
    assert "Do NOT select `items`, `tags`, or `sa_alerts` by default" in prompt
    assert "short prose summary" in prompt


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

