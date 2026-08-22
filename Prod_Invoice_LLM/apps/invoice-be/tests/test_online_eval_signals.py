"""Feature 23 — tests for `services/online_eval_signals.py`.

Seeded SQLite, real rows, real assertions per signal. The point of each test is
the *shape* the doc named as a known-real failure, not a generic "the query
runs": Gap 224's confident zero, Gap 278's slow turn, a thumbs-down cluster, a
budget-exhausted eval turn.

Two tests exist specifically to stop this module lying about itself: the
`NO_RECORDS_FOUND` drift test (a silently-changed literal would zero the
zero-result signal without failing anything) and the sample-floor test (a
1-of-1 bad turn must not raise an alert).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models import AgentEvalRun, ChatFeedback, ChatMessage, ChatSession
from services.online_eval_signals import (
    CONFIDENCE_HEURISTIC,
    CONFIDENCE_MEASURED,
    CONFIDENCE_OFFLINE_ONLY,
    CONFIDENCE_PROXY,
    MIN_SAMPLE_FOR_ALERT,
    NO_RECORDS_FOUND,
    SLOW_TURN_THRESHOLD_SECONDS,
    budget_exhaustion_rate,
    clarification_rate,
    compute_online_signals,
    emit_online_signals,
    looks_like_clarification,
    slow_turn_rate,
    thumbs_down_clustering,
    zero_result_rate,
)

NOW = datetime(2026, 8, 21, 12, 0, 0)
WINDOW = {"window_start": NOW - timedelta(days=7), "window_end": NOW}

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(name="db")
def db_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def make_session(db: Session, tenant_id: UUID = TENANT_A) -> UUID:
    chat_session = ChatSession(tenant_id=tenant_id, title="t", created_at=NOW - timedelta(days=1))
    db.add(chat_session)
    db.commit()
    return chat_session.id


def add_turn(
    db: Session,
    session_id: UUID,
    *,
    question: str = "how much did we spend",
    answer: str = "You spent USD 1,000.00.",
    asked_at: datetime | None = None,
    latency_seconds: float = 5.0,
    citations: list | None = None,
    job_id: str | None = None,
) -> tuple[ChatMessage, ChatMessage]:
    asked_at = asked_at or (NOW - timedelta(hours=1))
    user = ChatMessage(
        session_id=session_id, role="user", content=question, created_at=asked_at, job_id=job_id
    )
    assistant = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer,
        citations=citations or [],
        created_at=asked_at + timedelta(seconds=latency_seconds),
        job_id=job_id,
    )
    db.add(user)
    db.add(assistant)
    db.commit()
    return user, assistant


def add_eval_run(db: Session, notes: str, *, tenant_id: UUID = TENANT_A) -> AgentEvalRun:
    row = AgentEvalRun(
        agent_name="sage.agentic_path",
        run_at=NOW - timedelta(hours=2),
        question="q",
        actual_answer="a",
        tenant_id=tenant_id,
        notes=notes,
    )
    db.add(row)
    db.commit()
    return row


def add_vote(
    db: Session,
    session_id: UUID,
    vote: str,
    *,
    reason: str | None = None,
    tenant_id: UUID = TENANT_A,
    at: datetime | None = None,
) -> ChatFeedback:
    row = ChatFeedback(
        tenant_id=tenant_id,
        session_id=session_id,
        message_id=uuid4(),
        vote=vote,
        reason=reason,
        created_at=at or (NOW - timedelta(hours=3)),
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Signal 1 — budget exhaustion
# ---------------------------------------------------------------------------


def test_budget_exhaustion_is_read_out_of_the_eval_notes(db):
    add_eval_run(db, "route=sage; stop_reason=tool_call_budget_exhausted; accuracy: 0.5")
    add_eval_run(db, "route=sage; stop_reason=clarification_requested")
    add_eval_run(db, "route=sage; stop_reason=synthesis_complete")
    add_eval_run(db, "route=chat; no stop reason recorded at all")

    signal = budget_exhaustion_rate(db, **WINDOW)
    # Denominator is turns that recorded *a* stop_reason, not all eval rows —
    # a row with none is not evidence the budget held.
    assert signal.denominator == 3
    assert signal.numerator == 1
    assert signal.value == pytest.approx(1 / 3)
    assert signal.detail["eval_rows_in_window"] == 4
    assert signal.detail["stop_reasons_seen"]["tool_call_budget_exhausted"] == 1


def test_budget_exhaustion_declares_itself_offline_only_and_names_the_gap(db):
    """The doc calls budget exhaustion a trace-level property "currently
    invisible outside a debugger". This module must not pretend otherwise."""
    signal = budget_exhaustion_rate(db, **WINDOW)
    assert signal.confidence == CONFIDENCE_OFFLINE_ONLY
    assert "GAP:" in signal.caveat
    assert "stop_reason" in signal.caveat


def test_budget_exhaustion_with_no_eval_rows_is_none_not_zero(db):
    signal = budget_exhaustion_rate(db, **WINDOW)
    assert signal.value is None
    assert signal.denominator == 0
    assert signal.breached is False


# ---------------------------------------------------------------------------
# Signal 2 — clarification rate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content,expected",
    [
        ("Which invoice did you mean - BRL-7702 or BRL-7703?", True),
        ("Could you clarify whether you mean money we owe or money owed to us?", True),
        ("Do you mean the inbound or the outbound invoice?", True),
        ("The total is USD 450.00.", False),
        ("", False),
    ],
)
def test_clarification_heuristic_on_real_phrasings(content, expected):
    message = ChatMessage(session_id=uuid4(), role="assistant", content=content)
    assert looks_like_clarification(message) is expected


def test_an_answer_with_a_results_table_is_never_a_clarification():
    """A turn that answered from data is an answer, whatever it ends with."""
    message = ChatMessage(
        session_id=uuid4(),
        role="assistant",
        content="Which vendor?\n\n### Query Results\n\ntotal\n---\n450.0",
    )
    assert looks_like_clarification(message) is False


def test_an_answer_with_citations_is_never_a_clarification():
    message = ChatMessage(
        session_id=uuid4(),
        role="assistant",
        content="Did you mean the Blue Ridge invoice?",
        citations=[{"invoice_id": str(uuid4()), "page": 1}],
    )
    assert looks_like_clarification(message) is False


def test_a_long_essay_ending_in_a_question_mark_is_not_a_clarification():
    message = ChatMessage(
        session_id=uuid4(),
        role="assistant",
        content=("Here is a very long answer. " * 40) + "Would you like more detail?",
    )
    assert looks_like_clarification(message) is False


def test_clarification_rate_counts_assistant_turns_and_reports_the_offline_exact(db):
    session_id = make_session(db)
    add_turn(db, session_id, answer="Which invoice did you mean?")
    add_turn(db, session_id, answer="The total is USD 450.00.")
    add_eval_run(db, "route=sage; stop_reason=clarification_requested")
    add_eval_run(db, "route=sage; stop_reason=synthesis_complete")

    signal = clarification_rate(db, **WINDOW)
    assert signal.denominator == 2
    assert signal.numerator == 1
    assert signal.value == pytest.approx(0.5)
    assert signal.confidence == CONFIDENCE_HEURISTIC
    assert signal.detail["offline_exact_clarification_turns"] == 1
    assert signal.detail["offline_exact_rate"] == pytest.approx(0.5)
    assert "ENABLE_AGENTIC_SAGE" in signal.caveat


# ---------------------------------------------------------------------------
# Signal 3 — zero results and Gap 224's shape
# ---------------------------------------------------------------------------


def test_no_records_found_literal_matches_the_products_own_constant():
    """If `agents/query_agent.py` ever rewords this string, the zero-result
    signal silently drops to zero and nothing else notices. This is the tripwire."""
    from agents.query_agent import NO_RECORDS_FOUND as PRODUCT_LITERAL

    assert NO_RECORDS_FOUND == PRODUCT_LITERAL


def test_zero_result_rate_counts_honest_empty_answers(db):
    session_id = make_session(db)
    add_turn(db, session_id, answer=f"I found nothing.\n\n### Query Results\n{NO_RECORDS_FOUND}")
    add_turn(db, session_id, answer="The total is USD 450.00.")
    add_turn(db, session_id, answer="The total is USD 2,386.31.")

    signal = zero_result_rate(db, **WINDOW)
    assert signal.numerator == 1
    assert signal.denominator == 3
    assert signal.confidence == CONFIDENCE_MEASURED


def test_gap224_confident_zero_is_reported_separately_from_the_honest_zero(db):
    """Rolling the two together would make a fleet of correct refusals look like
    a fleet of fabrications — and vice versa, which is the dangerous direction."""
    session_id = make_session(db)
    add_turn(db, session_id, answer=f"Nothing matched.\n{NO_RECORDS_FOUND}")
    add_turn(
        db,
        session_id,
        question="How much did we spend on furniture, chairs, or desks?",
        answer="You spent USD 0.00 on furniture, chairs, or desks.",
    )
    add_turn(db, session_id, answer="The total is USD 450.00.")

    signal = zero_result_rate(db, **WINDOW)
    assert signal.numerator == 1  # the honest one only
    assert signal.detail["false_confident_zero_turns"] == 1
    assert signal.detail["false_confident_zero_rate"] == pytest.approx(1 / 3)
    assert len(signal.detail["example_message_ids"]) == 1


def test_a_confident_zero_that_also_says_no_records_found_is_not_flagged(db):
    """Saying "$0.00" while also saying nothing was found is the honest shape."""
    session_id = make_session(db)
    add_turn(db, session_id, answer=f"USD 0.00 — {NO_RECORDS_FOUND}")
    signal = zero_result_rate(db, **WINDOW)
    assert signal.detail["false_confident_zero_turns"] == 0
    assert signal.numerator == 1


def test_a_non_zero_amount_does_not_trip_the_zero_detector(db):
    session_id = make_session(db)
    add_turn(db, session_id, answer="The total is USD 1,000.00 across USD 40,000.00 of spend.")
    signal = zero_result_rate(db, **WINDOW)
    assert signal.detail["false_confident_zero_turns"] == 0


# ---------------------------------------------------------------------------
# Signal 4 — Gap 278's shape
# ---------------------------------------------------------------------------


def test_slow_turn_rate_finds_the_gap278_shape(db):
    """Gap 278: two real turns at ~177s, zero 4xx/5xx on the path. An error rate
    would have shown nothing; a slow-turn rate is the only shape that catches it."""
    session_id = make_session(db)
    for index in range(8):
        add_turn(db, session_id, latency_seconds=12.0, asked_at=NOW - timedelta(hours=index + 2))
    add_turn(db, session_id, latency_seconds=177.8, asked_at=NOW - timedelta(hours=20))
    add_turn(db, session_id, latency_seconds=176.8, asked_at=NOW - timedelta(hours=21))

    signal = slow_turn_rate(db, **WINDOW)
    assert signal.denominator == 10
    assert signal.numerator == 2
    assert signal.value == pytest.approx(0.2)
    assert signal.confidence == CONFIDENCE_PROXY
    assert signal.detail["max_seconds"] == pytest.approx(177.8)
    assert len(signal.detail["slowest_message_ids"]) == 2


def test_the_default_threshold_sits_above_gap278s_documented_normal_tail(db):
    """Gap 278 recorded that "a long tail of otherwise-'normal' chat turns
    already sits at 20-40s". A threshold inside that band would alert on the
    pre-existing slowness that gap explicitly ruled out as the bug."""
    assert SLOW_TURN_THRESHOLD_SECONDS > 40.0
    session_id = make_session(db)
    for index in range(5):
        add_turn(db, session_id, latency_seconds=38.0, asked_at=NOW - timedelta(hours=index + 2))
    assert slow_turn_rate(db, **WINDOW).numerator == 0


def test_turn_pairing_prefers_the_queue_job_id(db):
    """Gap 280's queue path writes a `job_id` on both rows. Pairing on it is
    exact; the "nearest preceding user row" fallback is not, once two turns
    overlap in one session."""
    session_id = make_session(db)
    add_turn(db, session_id, latency_seconds=100.0, asked_at=NOW - timedelta(hours=5), job_id="j1")
    add_turn(db, session_id, latency_seconds=2.0, asked_at=NOW - timedelta(hours=5), job_id="j2")

    signal = slow_turn_rate(db, **WINDOW)
    assert signal.denominator == 2
    assert signal.numerator == 1


def test_negative_latency_is_discarded_not_clamped(db):
    """A clock-skewed or re-ordered write is not a 0ms turn."""
    session_id = make_session(db)
    add_turn(db, session_id, latency_seconds=-30.0, asked_at=NOW - timedelta(hours=5))
    add_turn(db, session_id, latency_seconds=10.0, asked_at=NOW - timedelta(hours=6))

    signal = slow_turn_rate(db, **WINDOW)
    assert signal.denominator == 1
    assert signal.detail["p50_seconds"] == pytest.approx(10.0)


def test_custom_threshold_is_honoured(db):
    session_id = make_session(db)
    add_turn(db, session_id, latency_seconds=30.0)
    assert slow_turn_rate(db, threshold_seconds=20.0, **WINDOW).numerator == 1
    assert slow_turn_rate(db, threshold_seconds=60.0, **WINDOW).numerator == 0


# ---------------------------------------------------------------------------
# Signal 5 — thumbs-down clustering
# ---------------------------------------------------------------------------


def test_thumbs_down_rate_and_reason_breakdown(db):
    session_id = make_session(db)
    add_vote(db, session_id, "up")
    add_vote(db, session_id, "down", reason="wrong_data")
    add_vote(db, session_id, "down", reason="wrong_interpretation")

    signal = thumbs_down_clustering(db, **WINDOW)
    assert signal.numerator == 2
    assert signal.denominator == 3
    assert signal.detail["up_votes"] == 1
    assert signal.detail["by_reason"] == {"wrong_data": 1, "wrong_interpretation": 1}


def test_a_cluster_is_surfaced_even_when_the_overall_rate_is_calm(db):
    """The whole point of clustering: three downs all in one session, drowned in
    a hundred ups, is a specific broken thing and must not be averaged away."""
    quiet = make_session(db)
    for _ in range(60):
        add_vote(db, quiet, "up")
    hot = make_session(db)
    for _ in range(3):
        add_vote(db, hot, "down", reason="wrong_data")

    signal = thumbs_down_clustering(db, **WINDOW)
    assert signal.value == pytest.approx(3 / 63)
    assert signal.detail["rate_alert_breached"] is False
    assert signal.breached is True  # the cluster is what fires it
    dimensions = {cluster["dimension"] for cluster in signal.detail["clusters"]}
    assert {"session", "reason"} <= dimensions
    session_cluster = next(c for c in signal.detail["clusters"] if c["dimension"] == "session")
    assert session_cluster["key"] == str(hot)
    assert session_cluster["down_votes"] == 3


def test_scattered_downs_below_the_cluster_size_do_not_fire(db):
    for _ in range(2):
        add_vote(db, make_session(db), "down", at=NOW - timedelta(days=3))
    for _ in range(40):
        add_vote(db, make_session(db), "up", at=NOW - timedelta(days=4))

    signal = thumbs_down_clustering(db, **WINDOW)
    assert signal.detail["clusters"] == []
    assert signal.breached is False


# ---------------------------------------------------------------------------
# Windowing, tenant scoping, alerting
# ---------------------------------------------------------------------------


def test_rows_outside_the_window_are_excluded(db):
    session_id = make_session(db)
    add_turn(db, session_id, answer=f"{NO_RECORDS_FOUND}", asked_at=NOW - timedelta(days=30))
    add_turn(db, session_id, answer="The total is USD 450.00.", asked_at=NOW - timedelta(days=1))

    signal = zero_result_rate(db, **WINDOW)
    assert signal.denominator == 1
    assert signal.numerator == 0


def test_tenant_scoping_goes_through_chat_session(db):
    """`ChatMessage` has no `tenant_id` — only `session_id`. A filter that
    assumed otherwise would silently return every tenant's traffic."""
    a = make_session(db, TENANT_A)
    b = make_session(db, TENANT_B)
    add_turn(db, a, answer=f"{NO_RECORDS_FOUND}")
    add_turn(db, b, answer="The total is USD 450.00.")
    add_turn(db, b, answer="The total is USD 99.00.")

    assert zero_result_rate(db, tenant_id=TENANT_A, **WINDOW).denominator == 1
    assert zero_result_rate(db, tenant_id=TENANT_B, **WINDOW).denominator == 2
    assert zero_result_rate(db, **WINDOW).denominator == 3


def test_tenant_scoping_applies_to_feedback_and_eval_rows(db):
    add_vote(db, make_session(db, TENANT_A), "down", tenant_id=TENANT_A)
    add_vote(db, make_session(db, TENANT_B), "up", tenant_id=TENANT_B)
    add_eval_run(db, "stop_reason=tool_call_budget_exhausted", tenant_id=TENANT_A)
    add_eval_run(db, "stop_reason=synthesis_complete", tenant_id=TENANT_B)

    assert thumbs_down_clustering(db, tenant_id=TENANT_A, **WINDOW).denominator == 1
    assert budget_exhaustion_rate(db, tenant_id=TENANT_B, **WINDOW).numerator == 0
    assert budget_exhaustion_rate(db, tenant_id=TENANT_A, **WINDOW).numerator == 1


def test_a_single_bad_turn_does_not_raise_an_alert(db):
    """The commonest way a quality dashboard cries wolf: 1 of 1 is 100%."""
    session_id = make_session(db)
    add_turn(db, session_id, answer=f"{NO_RECORDS_FOUND}")

    signal = zero_result_rate(db, **WINDOW)
    assert signal.value == pytest.approx(1.0)
    assert signal.denominator < MIN_SAMPLE_FOR_ALERT
    assert signal.breached is False


def test_the_alert_fires_once_there_is_enough_evidence(db):
    session_id = make_session(db)
    for index in range(MIN_SAMPLE_FOR_ALERT):
        add_turn(
            db, session_id, answer=NO_RECORDS_FOUND, asked_at=NOW - timedelta(minutes=index + 1)
        )

    signal = zero_result_rate(db, **WINDOW)
    assert signal.denominator == MIN_SAMPLE_FOR_ALERT
    assert signal.breached is True


def test_compute_online_signals_returns_all_five_named_by_the_doc(db):
    session_id = make_session(db)
    add_turn(db, session_id)
    add_vote(db, session_id, "down", reason="wrong_data")
    add_eval_run(db, "stop_reason=tool_call_budget_exhausted")

    result = compute_online_signals(db, now=NOW)
    assert [signal.name for signal in result.signals] == [
        "budget_exhaustion_rate",
        "clarification_rate",
        "zero_result_rate",
        "slow_turn_rate",
        "thumbs_down_clustering",
    ]
    assert result.window_end == NOW
    assert (result.window_end - result.window_start).days == 7
    assert result.by_name("zero_result_rate").denominator == 1


def test_every_signal_declares_a_confidence_and_a_caveat(db):
    """A dashboard that showed a heuristic and a measurement identically would
    be worse than no dashboard."""
    for signal in compute_online_signals(db, now=NOW).signals:
        assert signal.confidence in {
            CONFIDENCE_MEASURED,
            CONFIDENCE_PROXY,
            CONFIDENCE_HEURISTIC,
            CONFIDENCE_OFFLINE_ONLY,
        }
        assert signal.caveat.strip(), f"{signal.name} has no caveat"


def test_as_dict_is_serialisable(db):
    import json

    payload = compute_online_signals(db, now=NOW).as_dict()
    assert json.dumps(payload)
    assert payload["breached"] == []


def test_empty_database_produces_absent_values_not_zeroes(db):
    """"Nothing happened" and "nothing went wrong" are different facts. A
    dashboard that conflated them shows healthy green the day ingestion stops."""
    result = compute_online_signals(db, now=NOW)
    assert all(signal.value is None for signal in result.signals)
    assert result.breaches == []


# ---------------------------------------------------------------------------
# The telemetry mirror — the workbook's only possible data source for these
# ---------------------------------------------------------------------------


def test_emit_online_signals_mirrors_every_signal_with_its_confidence(db, caplog):
    """A workbook cannot query Postgres, so the online panel reads these events.
    `confidence` has to travel on the event: three of the five signals are a
    proxy/heuristic/offline-only measurement, and a panel that rendered all five
    as equally solid would be worse than no panel."""
    import logging

    import telemetry

    session_id = make_session(db, TENANT_A)
    for index in range(3):
        add_turn(db, session_id, answer=f"{NO_RECORDS_FOUND} ({index})")

    signals = compute_online_signals(db, now=NOW, tenant_id=TENANT_A)
    with caplog.at_level(logging.INFO):
        emitted = emit_online_signals(signals, window_days=7)

    assert emitted == 5
    records = [
        r for r in caplog.records if r.getMessage() == telemetry.ONLINE_SIGNAL_EVENT_NAME
    ]
    assert {r.signal_name for r in records} == {
        "budget_exhaustion_rate",
        "clarification_rate",
        "zero_result_rate",
        "slow_turn_rate",
        "thumbs_down_clustering",
    }
    by_name = {r.signal_name: r for r in records}
    assert by_name["zero_result_rate"].confidence == CONFIDENCE_MEASURED
    assert by_name["zero_result_rate"].value == 1.0
    assert by_name["slow_turn_rate"].confidence == CONFIDENCE_PROXY
    assert by_name["budget_exhaustion_rate"].confidence == CONFIDENCE_OFFLINE_ONLY
    assert by_name["clarification_rate"].confidence == CONFIDENCE_HEURISTIC
    assert all(r.window_days == 7 for r in records)


def test_an_unmeasured_signal_emits_no_value_rather_than_a_zero(db, caplog):
    """None means "the denominator was empty". Emitting it as 0.0 would render an
    ingestion outage as a perfectly healthy day on every chart."""
    import logging

    import telemetry

    with caplog.at_level(logging.INFO):
        emit_online_signals(compute_online_signals(db, now=NOW))

    records = [
        r for r in caplog.records if r.getMessage() == telemetry.ONLINE_SIGNAL_EVENT_NAME
    ]
    assert len(records) == 5
    assert all(not hasattr(r, "value") for r in records)
    assert all(r.denominator == 0 for r in records)


def test_a_broken_emitter_never_loses_a_computed_window(db, monkeypatch):
    import telemetry

    def _explode(*_args, **_kwargs):
        raise RuntimeError("Application Insights is down")

    monkeypatch.setattr(telemetry, "_emit_event", _explode)
    assert emit_online_signals(compute_online_signals(db, now=NOW)) == 5
