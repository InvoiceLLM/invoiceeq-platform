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
from contextlib import ExitStack
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


def _run(db_session, llm, message, session_id, surfaced_rows=None, classified_route="SQL"):
    """Run the SQL route with the LLM mocked out.

    `surfaced_rows`: when given, `execute_generated_sql` is stubbed to report
    that many invoice ids for this turn. The hedge tests need to control that
    number exactly, and doing it through real rows isn't possible here —
    SQLite stores UUID columns as dashless hex, so the dashed tenant literal
    every generated query carries (and the tenant-isolation safety check
    requires) matches zero rows under this fixture's engine.
    """
    patches = [
        patch("agents.query_agent.classify_query", return_value=classified_route),
        patch("agents.query_agent.query_invoice_chunks", return_value=[]),
        patch("agents.query_agent.get_llm", return_value=llm),
        patch("agents.query_agent.get_cached_answer", return_value=None),
        patch("agents.query_agent.set_cached_answer"),
        patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
    ]
    if surfaced_rows is not None:
        ids = [str(uuid4()) for _ in range(surfaced_rows)]

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


def test_rule_6d_selects_currency_per_rule_7(db_session):
    """Rule 7 requires `currency` alongside any monetary column; rule 6d's own
    examples have to obey it, or every line-item answer is an unlabelled number
    (FE Gap 183 is on file for exactly that)."""
    llm = _RecordingLLM([
        MagicMock(sql=f"SELECT grand_total, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    ])
    _run(db_session, llm, "what is the training amount", uuid4())
    detail = _taught_sql(llm.prompts[0], "To list matching lines:")
    aggregate = _taught_sql(llm.prompts[0], "To total matching lines")
    assert "invoice.currency" in detail
    assert "invoice.currency" in aggregate
    assert "GROUP BY invoice.currency" in aggregate


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
    rows = db_session.exec(text(_taught_sql(rule, "To list matching lines:"))).all()

    assert len(rows) == 1
    invoice_number, currency, description, qty, unit_price, amount = rows[0]
    assert (invoice_number, currency, description) == ("US-1", "USD", "Training & Onboarding")
    assert (qty, unit_price, amount) == (40, 732.5735, 29302.94)
    assert amount != 35480.59

    total_rows = db_session.exec(text(_taught_sql(rule, "To total matching lines"))).all()
    assert total_rows == [(29302.94, "USD")]


def test_taught_line_item_sql_aggregates_across_invoices_and_currencies(db_session):
    """The aggregate shape must group by currency, not sum across them (no
    exchange rate exists -- same reason `_get_tenant_stats_summary` breaks spend
    out per currency)."""
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
    totals = dict(
        (currency, total)
        for total, currency in db_session.exec(text(_taught_sql(rule, "To total matching lines"))).all()
    )
    assert totals == {"USD": 29502.94, "INR": 50.0}


@pytest.mark.parametrize("marker", ["To list matching lines:", "To total matching lines"])
def test_taught_line_item_sql_runs_on_postgres(marker):
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
    sql = _taught_sql(query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session), marker)
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
        _taught_sql(rule, "To total matching lines"), MOCK_TENANT_ID.hex, db_session
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
    nothing. Both dialect variants must steer the model to tax_amount instead."""
    rule_sqlite = query_agent._line_item_rule(MOCK_TENANT_ID.hex, db_session)
    assert "CGST" in rule_sqlite and "SGST" in rule_sqlite and "IGST" in rule_sqlite
    assert "tax_amount" in rule_sqlite
    assert "no invoice found" in rule_sqlite.lower() or "doesn't exist" in rule_sqlite.lower()

    pg_session = MagicMock()
    pg_session.get_bind.return_value.dialect.name = "postgresql"
    rule_pg = query_agent._line_item_rule(str(MOCK_TENANT_ID), pg_session)
    assert "CGST" in rule_pg and "SGST" in rule_pg and "IGST" in rule_pg
    assert "tax_amount" in rule_pg


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

