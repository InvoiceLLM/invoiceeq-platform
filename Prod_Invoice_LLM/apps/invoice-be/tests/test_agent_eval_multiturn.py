"""Gap 307 — the offline multi-turn context-drift tier.

Three things are pinned here, in this order:

1. **The scorer's mechanics.** `score_context_drift()` is deterministic, so
   unlike the judged dimensions it can be asserted exactly: which surface each
   kind of term is checked against, that an absent expectation is `None` and
   never 1.0, and that the score degrades per-check rather than being a boolean.
2. **The scripts' well-formedness against the real fixture.** A drift case is
   only a test if its pinned entities exist in the seeded tenant and the *wrong*
   answer it names is genuinely reachable. Every one of those facts is asserted
   against `benchmarks/sage_seed_fixtures.py` / `large_invoice_fixture.py` rather
   than restated from the case text — the same rule
   `test_every_expected_invoice_number_exists_in_the_seeded_fixture` holds the
   single-turn bank to.
3. **The wiring that makes the turns a conversation.** The shared session id and
   the `ChatMessage` write-back are the whole tier: without them every drift
   check passes vacuously against twelve independent first turns, which is the
   most plausible way for this to look green while measuring nothing.

Like `test_agent_eval.py`, nothing here asserts how a real model scores a real
answer. A live run's numbers are data, not an assertion.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))
_SCRIPTS = str(_BE_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import telemetry  # noqa: E402
from benchmarks.agent_eval_golden_sample import ALL_ROWS, CASES  # noqa: E402
from benchmarks.agent_eval_multiturn import (  # noqa: E402
    MULTI_TURN_CASES,
    MULTI_TURN_PATH,
    MULTI_TURN_SCRIPTS,
    cases_for,
)
from models import ChatMessage  # noqa: E402
from services.agent_eval import (  # noqa: E402
    DriftExpectation,
    EvalScores,
    decide_pass,
    score_context_drift,
)

_ROW_BY_NUMBER = {row["invoice_number"]: row for row in ALL_ROWS}


def _all_terms(drift) -> tuple[str, ...]:
    """Every entity string a `DriftExpectation` pins, flattened.

    `required_entities` is a tuple of *alias groups*, so it is flattened here
    rather than concatenated — see `DriftExpectation`'s docstring for why one
    entity needs several stable surface forms.
    """
    return (
        drift.forbidden_terms
        + drift.forbidden_sql_terms
        + tuple(alias for group in drift.required_entities for alias in group)
    )


# ---------------------------------------------------------------------------
# The scorer
# ---------------------------------------------------------------------------


def test_a_turn_with_no_expectation_is_unscored_not_perfect():
    """`None` means "this turn has no predecessor to have drifted from". A 1.0
    would put 35 free perfect scores into the mean."""
    score, notes = score_context_drift("anything at all", None)

    assert score is None
    assert notes == []


def test_an_expectation_that_pins_nothing_is_unscored_and_says_so():
    score, notes = score_context_drift("anything", DriftExpectation())

    assert score is None
    assert "pins no check" in notes[0]


def test_every_check_holding_is_a_full_score():
    drift = DriftExpectation(
        forbidden_terms=("BRL-7702",),
        forbidden_sql_terms=("Blue Ridge",),
        required_entities=(("DataPipe", "DPS-9981"),),
        forbidden_invoice_numbers=("BRL-7702",),
    )

    score, notes = score_context_drift(
        "DataPipe Solutions' invoice DPS-9981 totals USD 42,300.00.",
        drift,
        generated_sql="SELECT * FROM invoice WHERE vendor_name ILIKE '%DataPipe%'",
        fetched_invoice_ids=["DPS-9981"],
    )

    assert score == 1.0
    assert notes == ["context drift: 4/4 checks held"]


def test_the_score_degrades_per_check_rather_than_collapsing_to_zero():
    """One leaked entity out of four pinned checks is 0.75, not a fail. The
    difference is what makes a mean over the tier readable."""
    drift = DriftExpectation(
        forbidden_terms=("BRL-7702",),
        forbidden_sql_terms=("Blue Ridge",),
        required_entities=(("DataPipe", "DPS-9981"),),
        forbidden_invoice_numbers=("BRL-7702",),
    )

    score, notes = score_context_drift(
        "DataPipe Solutions' invoice DPS-9981 totals USD 42,300.00, unlike BRL-7702.",
        drift,
        generated_sql="SELECT * FROM invoice WHERE vendor_name ILIKE '%DataPipe%'",
        fetched_invoice_ids=["DPS-9981"],
    )

    assert score == 0.75
    assert any("BRL-7702" in note for note in notes)


def test_a_stale_predicate_is_caught_in_the_sql_even_when_the_prose_is_clean():
    """Gap 276's exact shape: the WHERE clause is where the previous turn's
    subject survives, and it survives there whether or not the stale rows reach
    the answer."""
    drift = DriftExpectation(forbidden_sql_terms=("Blue Ridge",))

    score, notes = score_context_drift(
        "Here are DataPipe Solutions' invoices.",
        drift,
        generated_sql="SELECT * FROM invoice WHERE vendor_name ILIKE '%Blue Ridge%'",
    )

    assert score == 0.0
    assert "predicate survived a topic change" in notes[1]


def test_a_forbidden_sql_term_says_nothing_about_the_prose():
    """The three surfaces are separate on purpose: an answer that *mentions* the
    subject it just moved off is chatty, not drifted, and must not be scored as
    drifted."""
    drift = DriftExpectation(forbidden_sql_terms=("Blue Ridge",))

    score, _notes = score_context_drift(
        "Switching from Blue Ridge Logistics to DataPipe Solutions: DPS-9981 is USD 42,300.00.",
        drift,
        generated_sql="SELECT * FROM invoice WHERE vendor_name ILIKE '%DataPipe%'",
    )

    assert score == 1.0


def test_a_forbidden_term_is_checked_against_the_prose_and_the_sql():
    drift = DriftExpectation(forbidden_terms=("TSD-620458",))

    from_prose, _ = score_context_drift("See TSD-620458.", drift, generated_sql="SELECT 1")
    from_sql, _ = score_context_drift(
        "See the invoice.", drift, generated_sql="... WHERE invoice_number = 'TSD-620458'"
    )

    assert from_prose == 0.0
    assert from_sql == 0.0


def test_a_required_term_is_checked_against_the_prose_only():
    """A WHERE clause tells the user nothing, so a term appearing only there does
    not satisfy "the answer must name this"."""
    drift = DriftExpectation(required_entities=(("StratEdge", "SEP-4410"),))

    score, notes = score_context_drift(
        "The oldest is the 2026-06-27 one.",
        drift,
        generated_sql="SELECT * FROM invoice WHERE vendor_name = 'StratEdge Partners'",
    )

    assert score == 0.0
    assert "went missing" in notes[1]


def test_an_entity_named_by_any_of_its_aliases_satisfies_the_check():
    """Regression, from the first live dry run (2026-08-26). The real answer to
    `drift_ambiguous_previous_invoice` turn 2 was
    "Do you mean the invoice dated 2026-06-27 (SEP-4410) or 2026-06-30
    (DPS-9981)? SEP-4410 tax = USD 2,236.00; DPS-9981 tax = USD 3,384.00" —
    the exact clarifying question that case exists to reward, with SQL that
    filtered on both vendors. It scored 0.60 because the check demanded the
    vendor *names* and the answer used the invoice *numbers*. One entity, several
    stable surface forms; requiring one of them is under-scoring a correct
    answer, which is the trap this module has four documented instances of."""
    drift = DriftExpectation(
        required_entities=(("DataPipe", "DPS-9981"), ("StratEdge", "SEP-4410")),
        forbidden_terms=("Rajesh Steel",),
    )

    score, _notes = score_context_drift(
        "Do you mean the invoice dated 2026-06-27 (SEP-4410) or 2026-06-30 (DPS-9981)? "
        "SEP-4410 tax = USD 2,236.00; DPS-9981 tax = USD 3,384.00.",
        drift,
        generated_sql=(
            "SELECT invoice_number, vendor_name, tax_amount FROM invoice WHERE "
            "LOWER(vendor_name) LIKE LOWER('%DataPipe Solutions%') OR "
            "LOWER(vendor_name) LIKE LOWER('%StratEdge Partners%')"
        ),
    )

    assert score == 1.0


def test_an_alias_group_is_one_check_not_one_per_alias():
    """Otherwise a two-alias entity would weigh twice as much in the mean as a
    one-alias entity, for no reason a reader could infer."""
    two_aliases = DriftExpectation(required_entities=(("DataPipe", "DPS-9981"),))
    one_alias = DriftExpectation(required_entities=(("DataPipe",),))

    assert two_aliases.check_count() == one_alias.check_count() == 1
    assert score_context_drift("nothing relevant", two_aliases)[0] == 0.0


def test_matching_is_case_insensitive():
    drift = DriftExpectation(
        forbidden_terms=("Harbor Tech",), required_entities=(("StratEdge",),)
    )

    score, _ = score_context_drift("stratedge partners, not HARBOR TECH", drift)

    assert score == 0.5


def test_a_stale_row_is_caught_from_what_the_tools_fetched_not_from_prose():
    """The retrieval half. An answer can be worded perfectly while the query
    behind it read the wrong rows, which is exactly the failure `context_score`
    exists for one turn at a time."""
    drift = DriftExpectation(forbidden_invoice_numbers=("US-20260722-001",))

    score, notes = score_context_drift(
        "StratEdge Partners' SEP-4410 is the oldest.",
        drift,
        fetched_invoice_ids=["SEP-4410", "us-20260722-001"],
    )

    assert score == 0.0
    assert "stale rows fetched" in notes[1]


def test_the_case_note_is_attached_only_when_something_actually_drifted():
    drift = DriftExpectation(forbidden_terms=("Meridian",), note="the June scope must hold")

    clean, clean_notes = score_context_drift("DataPipe Solutions.", drift)
    dirty, dirty_notes = score_context_drift("Meridian Industrial Supply.", drift)

    assert clean == 1.0
    assert not any("drift case:" in note for note in clean_notes)
    assert dirty == 0.0
    assert any("the June scope must hold" in note for note in dirty_notes)


def test_the_scorer_makes_no_judge_call_at_all():
    """Deterministic by design. If this ever needs an LLM it has stopped being
    the thing it was built to be."""
    calls = []
    original = telemetry.tracked_llm_call

    class _Boom:
        def __enter__(self_inner):
            calls.append(1)
            raise AssertionError("the drift check must not call a model")

        def __exit__(self_inner, *_args):
            return False

    telemetry.tracked_llm_call = lambda *a, **k: _Boom()
    try:
        score_context_drift(
            "DataPipe", DriftExpectation(required_entities=(("DataPipe",),)), generated_sql="SELECT 1"
        )
    finally:
        telemetry.tracked_llm_call = original

    assert calls == []


def test_drift_does_not_change_the_pass_decision():
    """Same rule the other component scores hold to: folding a new dimension
    into `passed` halfway through a series redefines what a pass means."""
    passing = EvalScores(faithfulness_score=1.0, relevance_score=1.0, accuracy_score=1.0)
    assert decide_pass(passing) is True

    passing.context_drift_score = 0.0
    assert decide_pass(passing) is True


def test_score_answer_leaves_drift_unscored_for_every_single_turn_caller():
    """The default path. 35 golden cases and the production judge all call
    `score_answer()` without a `drift=`, and none of them may acquire a 1.0."""
    from services.agent_eval import score_answer

    class _NullJudge:
        def with_structured_output(self, _schema):
            raise RuntimeError("no judge needed for this assertion")

    scores = score_answer(
        question="q",
        answer="a",
        context="c",
        llm=_NullJudge(),
    )

    assert scores.context_drift_score is None


# ---------------------------------------------------------------------------
# The scripts, against the real seeded fixture
# ---------------------------------------------------------------------------


def test_the_tier_is_additive_the_single_turn_bank_is_untouched():
    """Gap 307 extends the bank; it does not rewrite it. No drift case may leak
    into `CASES`, and no existing case may acquire a drift expectation."""
    single_turn_ids = {case.case_id for case in CASES}
    drift_ids = {case.case_id for case in MULTI_TURN_CASES}

    # 35 at Gap 307; +1 on 2026-09-03 for Feature 6.1 C3's `zero_result_typo_vendor`
    # (a misspelt vendor must become a proposal, never a figure or a flat "none").
    assert len(CASES) == 36
    assert not (single_turn_ids & drift_ids)
    assert all(getattr(case, "drift", None) is None for case in CASES)


def test_every_script_has_two_or_three_turns():
    """`feature_20_23_24_ops_workbook.md`'s own scoping: fixed 2-3 turn scripts
    with pinned expectations, explicitly in preference to a general detector."""
    for script in MULTI_TURN_SCRIPTS:
        assert 2 <= len(script.turns) <= 3, script.script_id


def test_every_case_id_is_unique_and_states_why_it_is_on_file():
    ids = [case.case_id for case in MULTI_TURN_CASES]

    assert len(ids) == len(set(ids))
    for case in MULTI_TURN_CASES:
        assert case.why_on_file.strip()
        assert case.source.strip()
        assert case.question.strip()
        assert case.expected_answer and case.expected_answer.strip()


def test_a_scripts_first_turn_never_carries_a_drift_expectation():
    """A first turn has no predecessor. Pinning drift on one would be scoring a
    single-turn case and calling it a conversation."""
    for script in MULTI_TURN_SCRIPTS:
        assert script.turns[0].drift is None, script.script_id


def test_every_later_turn_does_carry_one():
    for script in MULTI_TURN_SCRIPTS:
        for case in script.turns[1:]:
            assert case.drift is not None, case.case_id
            assert case.drift.check_count() > 0, case.case_id
            assert case.drift.note.strip(), case.case_id


def test_every_pinned_invoice_number_exists_in_the_seeded_fixture():
    """A forbidden invoice number that is not seeded can never be fetched, so
    the check would pass every night while testing nothing — the silent-green
    failure this file exists to prevent."""
    seeded = set(_ROW_BY_NUMBER)
    for case in MULTI_TURN_CASES:
        for number in case.expected_invoice_numbers or ():
            assert number in seeded, f"{case.case_id} expects unseeded {number}"
        for number in (case.drift.forbidden_invoice_numbers if case.drift else ()):
            assert number in seeded, f"{case.case_id} forbids unseeded {number}"


def test_every_pinned_term_is_a_string_the_fixture_can_actually_produce():
    """Terms are entity strings — a vendor name, an invoice number, or an ISO
    date that is stored as text. A term matching nothing in the fixture is a
    check that can never fire."""
    haystack = " ".join(
        f"{row['vendor_name']} {row['invoice_number']} {row.get('invoice_date') or ''} "
        f"{row.get('due_date') or ''}"
        for row in ALL_ROWS
    ).lower()

    for case in MULTI_TURN_CASES:
        if not case.drift:
            continue
        for term in _all_terms(case.drift):
            assert term.lower() in haystack, f"{case.case_id} pins {term!r}, not in the fixture"


def test_no_pinned_term_is_a_money_figure():
    """Stated in `DriftExpectation`'s docstring and asserted here: the same
    amount renders three different ways depending on the route, so a numeric
    term would mostly fail to match — and a missed forbidden match reads as
    "no drift"."""
    for case in MULTI_TURN_CASES:
        if not case.drift:
            continue
        for term in _all_terms(case.drift):
            stripped = term.replace(",", "").replace(".", "")
            assert not stripped.isdigit(), f"{case.case_id} pins the bare figure {term!r}"


def test_no_term_is_both_required_and_forbidden_on_the_same_turn():
    for case in MULTI_TURN_CASES:
        if not case.drift:
            continue
        required = {
            alias.lower() for group in case.drift.required_entities for alias in group
        }
        forbidden = {t.lower() for t in case.drift.forbidden_terms}
        assert not (required & forbidden), case.case_id


def test_every_alias_group_names_exactly_one_seeded_invoice():
    """An alias group is "one entity, any of its names". Two aliases pointing at
    two different rows would let a turn satisfy the check by naming the wrong
    invoice — which is drift passing itself."""
    for case in MULTI_TURN_CASES:
        if not case.drift:
            continue
        for group in case.drift.required_entities:
            assert group, f"{case.case_id} has an empty alias group"
            matched = {
                number
                for number, row in _ROW_BY_NUMBER.items()
                for alias in group
                if alias.lower() in f"{row['vendor_name']} {number}".lower()
            }
            assert len(matched) == 1, (
                f"{case.case_id}'s alias group {group} matches {sorted(matched)}, "
                "not exactly one seeded invoice"
            )


def test_a_required_entity_is_never_absent_from_its_own_reference_answer():
    """The rule `required_entities` is limited to is "naming the entity IS the
    answer". If the case's own reference answer does not name it, it is not."""
    for case in MULTI_TURN_CASES:
        if not case.drift:
            continue
        reference = (case.expected_answer or "").lower()
        for group in case.drift.required_entities:
            assert any(alias.lower() in reference for alias in group), (
                f"{case.case_id} requires one of {group} but its reference answer "
                "names none of them"
            )


def test_the_reference_answer_names_the_wrong_answer_the_drift_check_pins():
    """A drift check and its case text must agree about what the failure is —
    otherwise a future reader "fixes" one against the other."""
    for case in MULTI_TURN_CASES:
        if not case.drift:
            continue
        reference = (case.expected_answer or "").lower()
        for term in case.drift.forbidden_terms + case.drift.forbidden_sql_terms:
            assert term.lower() in reference, (
                f"{case.case_id} forbids {term!r} but its reference answer never "
                "explains why that would be wrong"
            )


# --- The three fixture facts the wrong answers depend on --------------------


def test_the_oldest_invoice_overall_is_outside_the_over_20k_set():
    """`drift_narrowing_followup_keeps_filter` turn 2 is only a test because
    dropping the threshold lands on a *different* invoice."""
    oldest = min(ALL_ROWS, key=lambda row: row["invoice_date"])
    over_20k = [
        row
        for row in ALL_ROWS
        if row["currency"] == "USD" and float(row["grand_total"]) > 20000
    ]
    oldest_over_20k = min(over_20k, key=lambda row: row["invoice_date"])

    assert oldest["invoice_number"] == "US-20260722-001"
    assert oldest_over_20k["invoice_number"] == "SEP-4410"
    assert oldest["invoice_number"] not in {row["invoice_number"] for row in over_20k}


def test_the_largest_invoice_overall_is_outside_june():
    """`drift_scope_stated_once_still_applies` turn 2's wrong answer."""
    largest = max(
        (row for row in ALL_ROWS if row["currency"] == "USD"),
        key=lambda row: float(row["grand_total"]),
    )
    june = [row for row in ALL_ROWS if row["invoice_date"].startswith("2026-06")]
    largest_in_june = max(june, key=lambda row: float(row["grand_total"]))

    assert largest["invoice_number"] == "MIS-2026-0881"
    assert not largest["invoice_date"].startswith("2026-06")
    assert largest_in_june["invoice_number"] == "DPS-9981"


def test_the_only_freight_line_in_the_tenant_is_outside_june():
    """`drift_scope_stated_once_still_applies` turn 3's wrong answer, and the
    reason its correct answer is a negative."""
    with_freight = [
        row
        for row in ALL_ROWS
        if "freight" in str(row.get("items") or "").lower()
    ]

    assert [row["invoice_number"] for row in with_freight] == ["BRL-7702"]
    assert not with_freight[0]["invoice_date"].startswith("2026-06")


def test_the_two_referents_in_the_moving_referent_script_have_different_due_dates():
    """Turn 3 asks "when is that one due" with no noun, so a stale referent has
    to be visible as a wrong date rather than as a matter of opinion."""
    assert _ROW_BY_NUMBER["TSD-620458"]["due_date"] == "2026-08-01"
    assert _ROW_BY_NUMBER["BRL-7702"]["due_date"] == "2026-08-04"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_no_case_filter_selects_every_script():
    assert cases_for(None) == MULTI_TURN_SCRIPTS
    assert cases_for(set()) == MULTI_TURN_SCRIPTS


def test_a_script_id_selects_that_whole_script():
    picked = cases_for({"drift_subject_switch_vendor"})

    assert [s.script_id for s in picked] == ["drift_subject_switch_vendor"]


def test_selecting_one_turn_selects_the_whole_script():
    """Running turn 2 without turn 1 is not running turn 2 — it is running a
    different and much easier question."""
    picked = cases_for({"drift_referent_moves_with_conversation__t3"})

    assert len(picked) == 1
    assert len(picked[0].turns) == 3


def test_a_single_turn_case_id_selects_no_script():
    assert cases_for({"greeting_no_tool"}) == []


# ---------------------------------------------------------------------------
# The wiring that makes twelve turns a conversation
# ---------------------------------------------------------------------------


@pytest.fixture(name="db_session")
def db_session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_the_write_back_produces_the_rows_the_drift_functions_read(db_session):
    """`get_chat_history()` and `get_prior_turn_sql()` are the two functions
    drift happens in, and both read `ChatMessage`. `run_query_agent()` writes
    nothing, so without this write-back a script is twelve first turns."""
    from datetime import datetime

    from agents.query_agent import get_chat_history, get_prior_turn_sql
    from scripts.run_agent_eval import record_turn_messages

    session_id = str(uuid4())
    record_turn_messages(
        db_session,
        session_id,
        "which invoices do we have from Blue Ridge Logistics?",
        {
            "answer": "BRL-7702, USD 6,120.00.",
            "generated_sql": "SELECT * FROM invoice WHERE vendor_name ILIKE '%Blue Ridge%'",
            "citations": [],
        },
        datetime.utcnow(),
    )

    rows = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == UUID(session_id))
    ).all()

    assert sorted(row.role for row in rows) == ["assistant", "user"]
    assert "Blue Ridge Logistics" in get_chat_history(session_id, db_session)
    assert "Blue Ridge" in (get_prior_turn_sql(session_id, db_session) or "")


def test_the_user_row_is_always_older_than_its_own_assistant_row(db_session):
    """Ordering is what `get_chat_history()` reconstructs the conversation from,
    and both functions order by `created_at` — so it is stamped explicitly
    rather than left to two `utcnow()` defaults landing in the same microsecond."""
    from datetime import datetime

    from scripts.run_agent_eval import record_turn_messages

    session_id = str(uuid4())
    for question in ("first question", "second question"):
        record_turn_messages(
            db_session,
            session_id,
            question,
            {"answer": f"answer to {question}", "generated_sql": None, "citations": []},
            datetime.utcnow(),
        )

    rows = db_session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == UUID(session_id))
        .order_by(ChatMessage.created_at)
    ).all()

    assert [row.role for row in rows] == ["user", "assistant", "user", "assistant"]
    assert [row.content for row in rows][0] == "first question"
    assert all(
        rows[i].created_at <= rows[i + 1].created_at for i in range(len(rows) - 1)
    )


def test_a_turn_with_no_sql_does_not_become_the_prior_turns_sql(db_session):
    """`get_prior_turn_sql()` filters on `generated_sql IS NOT NULL`, so a RAG or
    CHAT turn between two SQL turns must not blank the predicate the next turn
    extends."""
    from datetime import datetime

    from agents.query_agent import get_prior_turn_sql
    from scripts.run_agent_eval import record_turn_messages

    session_id = str(uuid4())
    record_turn_messages(
        db_session,
        session_id,
        "sql turn",
        {"answer": "a", "generated_sql": "SELECT 1 FROM invoice", "citations": []},
        datetime.utcnow(),
    )
    record_turn_messages(
        db_session,
        session_id,
        "chat turn",
        {"answer": "hello", "generated_sql": None, "citations": []},
        datetime.utcnow(),
    )

    assert get_prior_turn_sql(session_id, db_session) == "SELECT 1 FROM invoice"


def test_a_script_shares_one_session_across_its_turns(monkeypatch, db_session):
    """The other half of the same point: one session id, 1-based turn indices,
    and the rows of turn N visible to turn N+1."""
    import scripts.run_agent_eval as runner

    seen: list[tuple[str, str]] = []

    def _fake_run_turn(case, path, session, stats, chunks, invoice_chunks=None, **kwargs):
        from agents.query_agent import get_chat_history

        seen.append((kwargs["session_id"], get_chat_history(kwargs["session_id"], session)))
        return {
            "case_id": case.case_id,
            "path": path,
            "session_id": kwargs["session_id"],
            "turn_index": kwargs["turn_index"],
            "answer": f"answer {kwargs['turn_index']}",
            "generated_sql": None,
            "citations": [],
            "llm_call_count": 0,
            "latency_ms": 1.0,
            "error": None,
        }

    monkeypatch.setattr(runner, "run_turn", _fake_run_turn)
    script = MULTI_TURN_SCRIPTS[2]  # the three-turn one

    turns = runner.run_multi_turn_script(script, MULTI_TURN_PATH, db_session, "", [])

    assert [t["turn_index"] for t in turns] == [1, 2, 3]
    assert len({t["session_id"] for t in turns}) == 1
    assert all(t["script_id"] == script.script_id for t in turns)
    # Turn 1 saw an empty history; every later turn saw the turns before it.
    assert seen[0][1] == ""
    assert script.turns[0].question in seen[1][1]
    assert script.turns[1].question in seen[2][1]


def test_the_tier_reports_under_its_own_summary_bucket():
    """Folding these turns into `default` would move the nightly pass rate and
    every quality mean onto a different, deliberately harder population than
    every historical figure in the docs."""
    from scripts.run_agent_eval import summarise

    summary = summarise(
        [
            {"path": "default", "llm_call_count": 1, "latency_ms": 10.0, "faithfulness_score": 1.0},
            {
                "path": MULTI_TURN_PATH,
                "llm_call_count": 1,
                "latency_ms": 10.0,
                "faithfulness_score": 0.0,
                "context_drift_score": 0.5,
            },
        ]
    )

    assert set(summary) == {"default", MULTI_TURN_PATH}
    assert summary["default"]["faithfulness_mean"] == 1.0
    assert summary["default"]["context_drift_mean"] is None
    assert summary["default"]["context_drift_scored_turns"] == 0
    assert summary[MULTI_TURN_PATH]["context_drift_mean"] == 0.5
    assert summary[MULTI_TURN_PATH]["context_drift_scored_turns"] == 1


def test_the_drift_dimension_is_mirrored_and_absent_scores_stay_absent(caplog):
    """Same absent-stays-absent rule the component scores already hold to: a
    single-turn case must emit no drift field at all, not a 0.0 that would read
    as total drift on every greeting in the bank."""
    import logging

    caplog.set_level(logging.INFO, logger="invoice_be_telemetry")

    telemetry.track_eval_result(
        "chat.default_path",
        "drift-case",
        True,
        context_drift_score=0.5,
        script_id="drift_subject_switch_vendor",
        turn_index=2,
    )
    telemetry.track_eval_result("chat.default_path", "single-turn-case", True)

    drift = next(r for r in caplog.records if getattr(r, "case_id", None) == "drift-case")
    single = next(
        r for r in caplog.records if getattr(r, "case_id", None) == "single-turn-case"
    )

    assert drift.context_drift_score == 0.5
    assert drift.script_id == "drift_subject_switch_vendor"
    assert drift.turn_index == 2
    assert not hasattr(single, "context_drift_score")
    assert not hasattr(single, "script_id")


def test_context_drift_is_in_the_mirrored_dimension_list():
    """The guard on the other side of `test_every_eval_scores_dimension_is_mirrored`:
    a dimension scored and then dropped from the trend is scored for nobody."""
    assert "context_drift" in telemetry.EVAL_SCORE_DIMENSIONS
