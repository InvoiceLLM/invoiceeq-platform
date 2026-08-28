"""Feature 23, Gap 305 — tests for `scripts/emit_online_signals_job.py`.

These are the six tests that were worth keeping when Feature 24's ops-digest
agent was deleted on 2026-08-25. They lived in `tests/test_ops_digest.py`'s
"Gap 305" section and drove the emitter through Feature 24's digest job; they now
drive it through the standalone job the extraction produced. What they assert is
unchanged, because none of it was ever about the digest — it was about the
emitter having a *caller* at all, the window being the job's own window rather
than the module's seven-day default, the ordering against the telemetry exporter,
and the two fail-soft contracts.

Driven through the real `main()`, not by calling the helpers directly: the whole
gap was that nothing *called* `emit_online_signals()`, so a test that calls it
proves nothing. `tests/test_online_eval_signals.py` already covers the signal
computation itself and is not re-tested here.

One seam is stubbed — `configure_telemetry()`, which would otherwise reconfigure
root logging for the rest of the suite. The database is a real SQLite one with
real `ChatMessage`/`ChatFeedback` rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Imported at module scope, not inside the fixture: `SQLModel.metadata` only
# knows about a table once its model class has been imported, so a lazy import
# would have `create_all()` build an empty schema.
from models import ChatFeedback, ChatMessage, ChatSession
from services.online_eval_signals import NO_RECORDS_FOUND


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
    SQLModel.metadata.drop_all(engine)


def _seed_live_traffic(db_session, *, turns: int = 3, down_votes: int = 0):
    """Real `ChatMessage`/`ChatFeedback` rows inside the job's own 6-hour window.

    Seeded against the wall clock rather than a frozen timestamp, because
    `main()` computes over the six hours ending *now* — a fixed timestamp would
    fall outside the window and the test would pass on an empty denominator,
    which is exactly the "nothing has run" state this gap is about.
    """
    tenant_id = uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    chat_session = ChatSession(
        tenant_id=tenant_id, title="t", created_at=now - timedelta(hours=1)
    )
    db_session.add(chat_session)
    db_session.commit()

    for index in range(turns):
        asked_at = now - timedelta(minutes=30 + index)
        db_session.add(
            ChatMessage(
                session_id=chat_session.id, role="user", content="q", created_at=asked_at
            )
        )
        db_session.add(
            ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                content=f"{NO_RECORDS_FOUND} ({index})",
                created_at=asked_at + timedelta(seconds=5),
            )
        )
    for _ in range(down_votes):
        db_session.add(
            ChatFeedback(
                tenant_id=tenant_id,
                session_id=chat_session.id,
                message_id=uuid4(),
                vote="down",
                reason="wrong_data",
                created_at=now - timedelta(minutes=20),
            )
        )
    db_session.commit()
    return chat_session.id


def _run_job(monkeypatch, db_session, argv=()):
    import sys

    import scripts.emit_online_signals_job as job

    monkeypatch.setattr(job, "_open_session", lambda: db_session)
    # The real one calls setup_structured_logging(), which re-points root logging
    # for every test that runs after this one.
    monkeypatch.setattr(job, "configure_telemetry", lambda: False)
    monkeypatch.setattr(sys, "argv", ["emit_online_signals_job.py", *argv])
    return job.main()


def _signal_records(caplog):
    from telemetry import ONLINE_SIGNAL_EVENT_NAME

    return [r for r in caplog.records if r.getMessage() == ONLINE_SIGNAL_EVENT_NAME]


def test_the_job_emits_an_online_eval_signal_event_for_every_signal(
    db_session, monkeypatch, caplog
):
    """Gap 305's closing condition. Before a caller existed, `emit_online_signals()`
    had zero callers anywhere in production code, so all signals rendered
    empty forever no matter how much real traffic existed. Four, not five, as
    of the same-day founder decision to retire `budget_exhaustion_rate` from
    the default online set (permanently dead, see `online_eval_signals.py`)."""
    _seed_live_traffic(db_session, turns=3, down_votes=3)

    with caplog.at_level(logging.INFO):
        exit_code = _run_job(monkeypatch, db_session)

    assert exit_code == 0
    records = _signal_records(caplog)
    assert {r.signal_name for r in records} == {
        "clarification_rate",
        "zero_result_rate",
        "slow_turn_rate",
        "thumbs_down_clustering",
    }


def test_real_chat_rows_produce_a_real_measured_rate_not_an_empty_event(
    db_session, monkeypatch, caplog
):
    """The seeded rows are three genuine "no records found" answers, so the event
    has to carry a measured 1.0 over a denominator of 3 — an event with an empty
    denominator would look identical to the pre-fix state on a dashboard."""
    _seed_live_traffic(db_session, turns=3, down_votes=3)

    with caplog.at_level(logging.INFO):
        _run_job(monkeypatch, db_session)

    by_name = {r.signal_name: r for r in _signal_records(caplog)}
    zero_result = by_name["zero_result_rate"]
    assert zero_result.denominator == 3
    assert zero_result.value == 1.0
    assert zero_result.confidence == "measured"
    # `ChatFeedback` is read too, not just `ChatMessage`: three downs on one
    # session is a cluster, which breaches even below the sample floor.
    assert by_name["thumbs_down_clustering"].breached == 1


def test_the_emitted_window_is_the_jobs_window_not_the_modules_seven_day_default(
    db_session, monkeypatch, caplog
):
    """`compute_online_signals()` defaults to 7 days; this job's default window is
    six hours. Emitting a 7-day window four times a day would restate the same
    week's traffic as if it were new, and a `window_days` of `0` — what the old
    `int()` cast in `track_online_signal()` produced for a fractional window —
    would read as a zero-length window."""
    _seed_live_traffic(db_session, turns=3)

    with caplog.at_level(logging.INFO):
        _run_job(monkeypatch, db_session)

    records = _signal_records(caplog)
    assert records
    assert all(abs(r.window_days - 0.25) < 1e-6 for r in records)


def test_a_failure_computing_the_signals_is_reported_rather_than_emitted_empty(
    db_session, monkeypatch, caplog
):
    """Fail-soft in one direction only: a broken computation must not raise out of
    the job, but it must also not be dressed up as a clean measured window."""
    import services.online_eval_signals as online

    def _explode(*_args, **_kwargs):
        raise RuntimeError("chat_message is unreadable")

    monkeypatch.setattr(online, "compute_online_signals", _explode)
    _seed_live_traffic(db_session, turns=3)

    with caplog.at_level(logging.INFO):
        exit_code = _run_job(monkeypatch, db_session)

    assert exit_code == 1
    assert _signal_records(caplog) == []


def test_a_broken_signal_emitter_does_not_raise_out_of_the_job(
    db_session, monkeypatch, caplog
):
    """A telemetry outage must not lose the run or turn into a job execution
    failure — the window was still computed correctly."""
    import services.online_eval_signals as online

    def _explode(*_args, **_kwargs):
        raise RuntimeError("Application Insights is down")

    monkeypatch.setattr(online, "emit_online_signals", _explode)
    _seed_live_traffic(db_session, turns=3)

    with caplog.at_level(logging.INFO):
        exit_code = _run_job(monkeypatch, db_session)

    assert exit_code == 0


def test_the_signals_are_emitted_after_the_exporter_is_attached(
    db_session, monkeypatch, caplog
):
    """The load-bearing ordering property. `track_online_signal()` logs through
    `invoice_be_telemetry`, and that logger only reaches `customEvents` once
    `configure_telemetry()` has attached the Azure Monitor handler — emitting at
    computation time (the obvious place, since that is where the signals already
    exist) would produce stdout lines and nothing in Application Insights, which
    is indistinguishable from the gap it closes."""
    import sys

    import scripts.emit_online_signals_job as job
    import services.online_eval_signals as online

    order: list[str] = []
    real_emit = online.emit_online_signals

    def _spy_emit(signals, **kwargs):
        order.append("emit_online_signals")
        return real_emit(signals, **kwargs)

    def _spy_configure():
        order.append("configure_telemetry")
        return False

    monkeypatch.setattr(online, "emit_online_signals", _spy_emit)
    monkeypatch.setattr(job, "configure_telemetry", _spy_configure)
    monkeypatch.setattr(job, "_open_session", lambda: db_session)
    monkeypatch.setattr(sys, "argv", ["emit_online_signals_job.py"])
    _seed_live_traffic(db_session, turns=3)

    assert job.main() == 0
    assert order == ["configure_telemetry", "emit_online_signals"]


def test_a_run_with_no_database_session_emits_no_signals_rather_than_empty_ones(
    monkeypatch, caplog
):
    """No session means the signals were never computed. Emitting five
    zero-denominator events for that case would report "measured, nothing found"
    for a window nothing was measured in."""
    import sys

    import scripts.emit_online_signals_job as job

    monkeypatch.setattr(job, "_open_session", lambda: None)
    monkeypatch.setattr(job, "configure_telemetry", lambda: False)
    monkeypatch.setattr(sys, "argv", ["emit_online_signals_job.py"])

    with caplog.at_level(logging.INFO):
        assert job.main() == 1

    assert _signal_records(caplog) == []


def test_dry_run_computes_the_window_but_emits_nothing(db_session, monkeypatch, caplog):
    """The digest job's `--dry-run` skipped delivery but still emitted these
    events, because there it was riding a job with its own reason to run. Here the
    emission *is* the run, so `--dry-run` has to suppress it."""
    _seed_live_traffic(db_session, turns=3)

    with caplog.at_level(logging.INFO):
        exit_code = _run_job(monkeypatch, db_session, argv=("--dry-run",))

    assert exit_code == 0
    assert _signal_records(caplog) == []
