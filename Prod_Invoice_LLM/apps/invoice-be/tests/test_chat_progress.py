"""Gap 365 — live per-seam chat progress, and D8's per-session serialisation.

Two halves, deliberately in one file because they are one change:

  * `run_query_agent(..., on_progress=...)` publishes at the real seams inside a
    turn (routing, each SQL generation attempt, execution, synthesis, RAG
    retrieval), replacing the two hardcoded steps
    `queue_worker/handlers.py` used to publish *around* the call. The tests
    assert that the seams really fire, in a sane order, carrying no internals --
    not that any particular sentence was used, which is copy and will change.

  * `queue_worker/handlers.py::chat_session_lock` serialises turns within one
    session while leaving different sessions fully parallel.

Scope note: this file deliberately does not touch `tests/test_chat_queue.py`
(Gap 364's file) and asserts nothing about the enqueue-side concurrency limit.
"""

import logging
import threading
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from dependencies import MOCK_TENANT_ID
import models  # noqa: F401 - imported for its `SQLModel.metadata` side effect

logger = logging.getLogger(__name__)

_ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(_ENGINE)
    with Session(_ENGINE) as session:
        yield session
    SQLModel.metadata.drop_all(_ENGINE)


class _ScriptedSqlLLM:
    """One scripted SQL-generation result, then a fixed summary answer.

    Same shape as `tests/test_telemetry.py::_ScriptedSqlLLM`, kept local so this
    file stays runnable on its own.
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


class _Recorder:
    """Collects `(step, details)` exactly as a real publisher would receive them."""

    def __init__(self):
        self.events: list[tuple[str, dict | None]] = []

    def __call__(self, step, details=None):
        self.events.append((step, details))

    @property
    def steps(self):
        return [s for s, _ in self.events]

    def details_for(self, step):
        return [d for s, d in self.events if s == step]


def _run_turn(
    db_session,
    llm,
    message,
    *,
    on_progress=None,
    execute=None,
    route="SQL",
    chunks=None,
    prior_turn_sql=None,
    session_id=None,
):
    """One turn through the real `run_query_agent()`, with only the boundaries
    (classifier, LLM, cache, Chroma) stubbed -- the seams under test are the real
    ones inside the function."""
    from contextlib import ExitStack

    from agents import query_agent

    patches = [
        patch("agents.query_agent.classify_query", return_value=route),
        patch("agents.query_agent.query_invoice_chunks", return_value=chunks or []),
        patch("agents.query_agent.get_llm", return_value=llm),
        patch("agents.query_agent.get_cached_answer", return_value=None),
        patch("agents.query_agent.set_cached_answer"),
        patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
    ]
    if execute is not None:
        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=execute))
    if prior_turn_sql is not None:
        patches.append(
            patch("agents.query_agent.get_prior_turn_sql", return_value=prior_turn_sql)
        )

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return query_agent.run_query_agent(
            str(session_id or uuid4()),
            message,
            str(MOCK_TENANT_ID),
            db_session,
            on_progress=on_progress,
        )


def _rows(sql, tenant_id, db_sess, snapshot=None):  # noqa: ARG001 - shape only
    if snapshot is not None:
        snapshot.append(str(uuid4()))
    return "\n\nid | currency\n--- | ---\nrow | USD"


# --- the seams -----------------------------------------------------------------


def test_a_sql_turn_publishes_at_every_real_seam(db_session):
    """Flip criterion 1 in `config.py`: one turn, at least 6 DISTINCT steps.

    Asserted as membership plus ordering rather than exact wording -- the step
    vocabulary is the contract, the sentences are copy.
    """
    rec = _Recorder()
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    _run_turn(db_session, llm, "what did we spend?", on_progress=rec, execute=_rows)

    for expected in (
        "understanding_question",
        "route_selected",
        "building_query",
        "generating_sql",
        "running_query",
        "summarizing_results",
        "answer_ready",
    ):
        assert expected in rec.steps, f"missing seam {expected}: got {rec.steps}"

    assert len(set(rec.steps)) >= 6
    # Sane order: the turn announces itself first and finishes last.
    assert rec.steps[0] == "understanding_question"
    assert rec.steps[-1] == "answer_ready"
    assert rec.steps.index("route_selected") < rec.steps.index("generating_sql")
    assert rec.steps.index("generating_sql") < rec.steps.index("running_query")
    assert rec.steps.index("running_query") < rec.steps.index("summarizing_results")


def test_progress_details_never_carry_sql_or_model_text(db_session):
    """Gap 294's discipline, applied to the new channel: these strings reach the
    browser, so the seam publishes counts and attempt numbers -- never the
    generated statement, never model prose."""
    rec = _Recorder()
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    _run_turn(db_session, llm, "what did we spend?", on_progress=rec, execute=_rows)

    for step, details in rec.events:
        # `step` names are a fixed vocabulary; only `details` could ever carry a
        # value from inside the turn, so that is what is checked.
        blob = str(details).lower()
        assert "select " not in blob
        assert "from invoice" not in blob
        assert str(MOCK_TENANT_ID).lower() not in blob
        assert "formatted summary" not in blob
        # Every detail value is a scalar fact -- a route name, an attempt number,
        # a count -- never free text.
        for value in (details or {}).values():
            assert isinstance(value, (int, str))
            assert len(str(value)) <= 32

    from agents.query_agent import _PROGRESS_STEPS

    assert set(rec.steps) <= set(_PROGRESS_STEPS)


def test_every_sql_repair_attempt_is_published_individually(db_session):
    """The seam users actually wait on. Attempt 1 fails, attempt 2 succeeds --
    both must be visible, or the feed goes silent for the retry."""
    rec = _Recorder()
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    calls = {"n": 0}

    def _flaky(sql, tenant_id, db_sess, snapshot=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("syntax error at or near")
        return _rows(sql, tenant_id, db_sess, snapshot)

    _run_turn(db_session, llm, "what did we spend?", on_progress=rec, execute=_flaky)

    attempts = [d.get("attempt") for d in rec.details_for("generating_sql")]
    assert attempts == [1, 2], f"expected one event per attempt, got {attempts}"
    assert [d.get("max_attempts") for d in rec.details_for("generating_sql")] == [3, 3]


def test_a_rag_turn_publishes_retrieval_start_and_a_count(db_session):
    rec = _Recorder()
    llm = _ScriptedSqlLLM(None)
    chunks = [
        {"document": "invoice text", "metadata": {"invoice_id": str(uuid4()), "vendor_name": "Acme", "page": 1}},
        {"document": "more text", "metadata": {"invoice_id": str(uuid4()), "vendor_name": "Acme", "page": 2}},
    ]

    _run_turn(db_session, llm, "what does the contract say?", on_progress=rec, route="RAG", chunks=chunks)

    assert "searching_documents" in rec.steps
    assert rec.details_for("documents_found") == [{"count": 2}]
    assert rec.steps.index("searching_documents") < rec.steps.index("documents_found")
    assert "composing_answer" in rec.steps


def test_the_gap_237_route_override_is_visible_on_the_channel(db_session):
    """An overridden route has to show on the feed: a turn the classifier sent to
    RAG and the deterministic override pulled back to SQL is exactly the case an
    operator reading a transcript needs to be able to see."""
    rec = _Recorder()
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    _run_turn(
        db_session,
        llm,
        "can you explain the 3 USD ones in detail?",
        on_progress=rec,
        route="RAG",
        execute=_rows,
        prior_turn_sql="SELECT id FROM invoice WHERE currency = 'USD'",
    )

    override = rec.details_for("route_override")
    assert override, f"override seam never fired: {rec.steps}"
    assert override[0]["route"] == "SQL"
    assert override[0]["from"] == "RAG"
    # And the turn really did take the SQL route afterwards.
    assert "generating_sql" in rec.steps


def test_a_callback_that_raises_cannot_break_the_turn(db_session):
    """Progress is decoration on a working turn. A publisher that blows up
    (Redis gone mid-turn) must not cost the user their answer."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    def _explode(step, details=None):
        raise RuntimeError("redis is on fire")

    result = _run_turn(db_session, llm, "what did we spend?", on_progress=_explode, execute=_rows)
    assert "Formatted summary." in result["content"]


def test_omitting_the_callback_is_identical_to_before(db_session):
    """The additive-change proof: the default (None) path produces the same
    result dict as one that passes a callback, so every existing caller --
    `routers/chat.py`'s synchronous path, `agents/query_tools.py`, the eval
    harnesses -- is untouched by this change."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    def _fixed(sql, tenant_id, db_sess, snapshot=None):  # noqa: ARG001 - shape only
        return "\n\nid | currency\n--- | ---\nrow | USD"

    without = _run_turn(db_session, llm, "what did we spend?", execute=_fixed)
    with_cb = _run_turn(db_session, llm, "what did we spend?", on_progress=_Recorder(), execute=_fixed)

    strip = lambda r: {k: v for k, v in r.items() if k != "turn_telemetry"}  # noqa: E731
    assert strip(without) == strip(with_cb)
    # And the signature still accepts the old positional call shape.
    import inspect

    from agents.query_agent import run_query_agent

    params = list(inspect.signature(run_query_agent).parameters)
    assert params[:4] == ["session_id", "user_message", "tenant_id", "db_session"]
    assert inspect.signature(run_query_agent).parameters["on_progress"].default is None


# --- D8: per-session serialisation ---------------------------------------------


class _FakeRedis:
    """Just enough Redis for the lock: SET NX, GET, DEL, thread-safe."""

    def __init__(self):
        self._data = {}
        self._guard = threading.Lock()

    def set(self, key, value, nx=False, ex=None):  # noqa: ARG002 - TTL not simulated
        with self._guard:
            if nx and key in self._data:
                return None
            self._data[key] = value
            return True

    def get(self, key):
        with self._guard:
            return self._data.get(key)

    def delete(self, key):
        with self._guard:
            self._data.pop(key, None)


def _overlap_probe(session_ids, fake_redis):
    """Run one 'turn' per session id concurrently; report whether any two of them
    were ever inside their lock at the same moment."""
    from queue_worker.handlers import chat_session_lock

    inside = []
    overlapped = {"value": False}
    guard = threading.Lock()
    acquired_flags = []

    def _turn(sid):
        with chat_session_lock(sid, client=fake_redis, wait_seconds=5, poll_seconds=0.01) as got:
            acquired_flags.append(got)
            with guard:
                inside.append(sid)
                if len(inside) > 1:
                    overlapped["value"] = True
            time.sleep(0.25)
            with guard:
                inside.remove(sid)

    threads = [threading.Thread(target=_turn, args=(sid,)) for sid in session_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    return overlapped["value"], acquired_flags


def test_two_turns_in_the_same_session_are_serialised():
    same = str(uuid4())
    overlapped, acquired = _overlap_probe([same, same], _FakeRedis())
    assert acquired == [True, True], "both turns must really hold the lock, not skip it"
    assert overlapped is False, "two turns in one session ran concurrently"


def test_two_turns_in_different_sessions_run_in_parallel():
    overlapped, acquired = _overlap_probe([str(uuid4()), str(uuid4())], _FakeRedis())
    assert acquired == [True, True]
    assert overlapped is True, "different sessions must not block each other"


def test_the_lock_is_released_after_the_turn():
    from queue_worker.handlers import CHAT_SESSION_LOCK_PREFIX, chat_session_lock

    r = _FakeRedis()
    sid = str(uuid4())
    with chat_session_lock(sid, client=r) as got:
        assert got is True
        assert r.get(f"{CHAT_SESSION_LOCK_PREFIX}{sid}") is not None
    assert r.get(f"{CHAT_SESSION_LOCK_PREFIX}{sid}") is None


def test_the_lock_is_released_even_when_the_turn_raises():
    from queue_worker.handlers import CHAT_SESSION_LOCK_PREFIX, chat_session_lock

    r = _FakeRedis()
    sid = str(uuid4())
    with pytest.raises(RuntimeError):
        with chat_session_lock(sid, client=r):
            raise RuntimeError("turn blew up")
    assert r.get(f"{CHAT_SESSION_LOCK_PREFIX}{sid}") is None


def test_redis_being_down_degrades_to_unserialised_rather_than_blocking():
    """Flip criterion 5's sibling on the worker side: no Redis must never mean no
    chat. The turn proceeds, it just isn't serialised."""
    from queue_worker.handlers import chat_session_lock

    class _DeadRedis:
        def set(self, *a, **kw):
            raise ConnectionError("connection refused")

    ran = False
    with chat_session_lock(str(uuid4()), client=_DeadRedis(), wait_seconds=5) as got:
        ran = True
        assert got is False
    assert ran


def test_a_lock_timeout_still_lets_the_turn_run():
    """A held lock that never clears must degrade to a stale-context answer, not
    a dropped turn."""
    from queue_worker.handlers import CHAT_SESSION_LOCK_PREFIX, chat_session_lock

    r = _FakeRedis()
    sid = str(uuid4())
    r.set(f"{CHAT_SESSION_LOCK_PREFIX}{sid}", "someone-else")

    started = time.monotonic()
    with chat_session_lock(sid, client=r, wait_seconds=0.3, poll_seconds=0.05) as got:
        assert got is False
    assert time.monotonic() - started >= 0.3
    # The other holder's lock is untouched -- a timed-out waiter must not steal
    # or delete it.
    assert r.get(f"{CHAT_SESSION_LOCK_PREFIX}{sid}") == "someone-else"
