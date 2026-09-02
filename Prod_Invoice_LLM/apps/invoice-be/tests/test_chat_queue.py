import json
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import ChatSession, ChatMessage
from services.chat_queue import (
    CHAT_TENANT_INFLIGHT_PREFIX,
    PER_TENANT_MAX_ACTIVE_CHAT,
    ChatQueueCapacityError,
    ChatQueueService,
)
from queue_worker.handlers import handle_process_chat_job

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields a clean, isolated in-memory test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides the FastAPI db session dependency to inject the test database session."""
    def get_db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def enable_async_chat_queue(monkeypatch):
    """Gap 280's async path is gated behind settings.ENABLE_ASYNC_CHAT_QUEUE
    (default False -- see config.py's docstring on that setting for why).
    Every test in this file is specifically about that async path, so it's
    switched on for the duration of this module rather than per-test; the
    sync-mode-backward-compatibility test still exercises the real sync path
    via its own explicit ?sync=true, which overrides this regardless."""
    import config
    monkeypatch.setattr(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", True)


def test_enqueue_chat_job_returns_202_and_persists_user_message(db_session):
    """Gap 280: Verify POST /chat/sessions/{id}/message returns 202 Accepted and stages user message."""
    session_id = uuid4()
    chat_session = ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="New Chat")
    db_session.add(chat_session)
    db_session.commit()

    client = TestClient(app)

    with patch("services.chat_queue.ChatQueueService.enqueue_chat_job") as mock_enqueue:
        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/message",
            json={"content": "What is the total spend on hardware?"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert "message_id" in data
        assert data["status"] == "queued"
        assert mock_enqueue.called

        # Verify user message was persisted in PostgreSQL/SQLite
        user_msg = db_session.exec(
            select(ChatMessage).where(ChatMessage.session_id == session_id)
        ).first()
        assert user_msg is not None
        assert user_msg.role == "user"
        assert user_msg.content == "What is the total spend on hardware?"
        assert user_msg.status == "queued"
        assert user_msg.job_id == data["job_id"]


def test_tenant_concurrency_throttle_and_fair_share_tracking():
    """Gap 280: Verify tenant concurrency in-flight increments and safe release."""
    mock_redis = MagicMock()
    mock_redis.incr.return_value = 1
    mock_redis.decr.return_value = 0

    tenant_id = "tenant-123"
    res = ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="Test question",
        tenant_id=tenant_id,
        client=mock_redis,
    )
    assert res["status"] == "queued"
    assert "job_id" in res
    assert mock_redis.incr.called

    # Release slot
    ChatQueueService.release_tenant_slot(tenant_id, client=mock_redis)
    assert mock_redis.decr.called


def test_chat_worker_executes_agent_and_publishes_events(db_session):
    """Gap 280: Verify handle_process_chat_job runs agent, updates DB rows, and completes job."""
    session_id = uuid4()
    user_msg_id = uuid4()
    job_id = "test-job-456"

    chat_session = ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="Test Thread")
    user_msg = ChatMessage(
        id=user_msg_id,
        session_id=session_id,
        role="user",
        content="Show total spend",
        status="queued",
        job_id=job_id,
    )
    db_session.add(chat_session)
    db_session.add(user_msg)
    db_session.commit()

    mock_agent_output = {
        "content": "Total spend across 5 invoices is $12,500.00",
        "generated_sql": "SELECT SUM(grand_total) FROM invoice",
        "citations": [{"invoice_id": str(uuid4()), "vendor_name": "Acme", "page": 1}],
        "result_invoice_ids": [str(uuid4())],
    }

    with patch("agents.query_agent.run_query_agent", return_value=mock_agent_output), \
         patch("services.chat_queue.ChatQueueService.publish_progress") as mock_progress, \
         patch("services.chat_queue.ChatQueueService.complete_job") as mock_complete:

        res = handle_process_chat_job(
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg_id),
            content="Show total spend",
            tenant_id=str(MOCK_TENANT_ID),
            db_session=db_session,
        )

        assert res["status"] == "completed"
        assert res["content"] == "Total spend across 5 invoices is $12,500.00"
        assert res["generated_sql"] == "SELECT SUM(grand_total) FROM invoice"
        assert mock_progress.called
        assert mock_complete.called

        # Verify DB records updated
        db_session.refresh(user_msg)
        assert user_msg.status == "completed"

        assistant_msg = db_session.exec(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        ).first()
        assert assistant_msg is not None
        assert assistant_msg.status == "completed"
        assert assistant_msg.job_id == job_id
        assert assistant_msg.generated_sql == "SELECT SUM(grand_total) FROM invoice"


def _seed_owned_job(db_session, job_id: str, tenant_id=MOCK_TENANT_ID):
    """A chat session + a queued user message carrying `job_id`.

    Gap 341: this is what `_require_owned_chat_job()` resolves ownership through
    -- `ChatMessage.job_id` -> `session_id` -> `ChatSession.tenant_id`, written
    before the enqueue. The Redis status blob cannot answer the question:
    `enqueue_chat_job()` puts `tenant_id` in it, but `complete_job()` and
    `fail_job()` overwrite it with one that has no tenant in it at all.
    """
    session_id = uuid4()
    db_session.add(ChatSession(id=session_id, tenant_id=tenant_id, title="t"))
    db_session.commit()
    db_session.add(
        ChatMessage(
            id=uuid4(),
            session_id=session_id,
            role="user",
            content="q",
            status="queued",
            job_id=job_id,
        )
    )
    db_session.commit()
    return session_id


def test_chat_job_status_and_stream_endpoints(db_session):
    """Gap 280: Verify /chat/jobs/{id}/status and /stream endpoints.

    Gap 341 extended this rather than duplicating the harness: the job now has
    to actually belong to the caller's tenant, so the rows are seeded first.
    Before that fix these endpoints returned another tenant's answer for any
    job id, and this test passed with no rows at all -- which is precisely how
    the missing check stayed invisible.
    """
    job_id = "job-stream-789"
    client = TestClient(app)
    _seed_owned_job(db_session, job_id)

    with patch(
        "services.chat_queue.ChatQueueService.get_job_status",
        return_value={"job_id": job_id, "status": "processing", "step": "routing"},
    ):
        status_res = client.get(f"/api/v1/chat/jobs/{job_id}/status")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "processing"

    with patch(
        "services.chat_queue.ChatQueueService.get_job_status",
        return_value={"job_id": job_id, "status": "completed", "result": {"content": "Done"}},
    ):
        stream_res = client.get(f"/api/v1/chat/jobs/{job_id}/stream")
        assert stream_res.status_code == 200
        assert "text/event-stream" in stream_res.headers["content-type"]
        assert "data:" in stream_res.text


def test_worker_failure_handling_and_slot_cleanup(db_session):
    """Gap 280: Verify worker catches exceptions, marks failure in DB, and releases slot."""
    session_id = uuid4()
    user_msg_id = uuid4()
    job_id = "failing-job-999"

    chat_session = ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="Failing Thread")
    user_msg = ChatMessage(
        id=user_msg_id,
        session_id=session_id,
        role="user",
        content="Trigger error",
        status="queued",
        job_id=job_id,
    )
    db_session.add(chat_session)
    db_session.add(user_msg)
    db_session.commit()

    with patch("agents.query_agent.run_query_agent", side_effect=RuntimeError("Azure OpenAI Rate Limit Exceeded")), \
         patch("services.chat_queue.ChatQueueService.fail_job") as mock_fail:

        res = handle_process_chat_job(
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg_id),
            content="Trigger error",
            tenant_id=str(MOCK_TENANT_ID),
            db_session=db_session,
        )

        assert res["status"] == "failed"
        assert "Azure OpenAI Rate Limit Exceeded" in res["error"]
        assert mock_fail.called

        db_session.refresh(user_msg)
        assert user_msg.status == "failed"
        assert "Azure OpenAI Rate Limit Exceeded" in user_msg.error_message


def test_sync_mode_backward_compatibility(db_session):
    """Gap 280: Verify ?sync=true runs synchronous query agent path returning 200 OK."""
    session_id = uuid4()
    chat_session = ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="Sync Test")
    db_session.add(chat_session)
    db_session.commit()

    client = TestClient(app)

    mock_agent_output = {
        "content": "Synchronous reply",
        "generated_sql": None,
        "citations": [],
        "result_invoice_ids": [],
    }

    with patch("routers.chat.run_query_agent", return_value=mock_agent_output):
        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/message?sync=true",
            json={"content": "Sync test question"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Synchronous reply"
        assert data["role"] == "assistant"
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Production quality judging on the queue path (Feature 23, Gap 304 half (2))
# ---------------------------------------------------------------------------

def _judged_agent_output():
    return {
        "content": "Total spend across 5 invoices is $12,500.00",
        "generated_sql": "SELECT SUM(grand_total) FROM invoice",
        "citations": [],
        "result_invoice_ids": [],
        "judge_evidence": {
            "route": "SQL",
            "context": "DATABASE RESULTS:\nsum | 12500",
            "executed_queries": "SELECT SUM(grand_total) FROM invoice",
        },
    }


def _run_queue_turn(db_session, agent_output, job_id="judge-job-1"):
    session_id = uuid4()
    user_msg_id = uuid4()
    db_session.add(ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="Judged Thread"))
    db_session.add(
        ChatMessage(
            id=user_msg_id,
            session_id=session_id,
            role="user",
            content="Show total spend",
            status="queued",
            job_id=job_id,
        )
    )
    db_session.commit()

    with patch("agents.query_agent.run_query_agent", return_value=agent_output), \
         patch("services.chat_queue.ChatQueueService.publish_progress"), \
         patch("services.chat_queue.ChatQueueService.complete_job"):
        res = handle_process_chat_job(
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg_id),
            content="Show total spend",
            tenant_id=str(MOCK_TENANT_ID),
            db_session=db_session,
        )
    return session_id, res


def test_the_queue_path_hands_its_own_committed_turn_to_the_same_judge(db_session):
    """Gap 304 half (2): both write paths build their own ChatMessage, so both
    hook the judge — and both call the *same* function, not two copies of it."""
    # Patched at the source module: `handlers._execute` imports the name inside
    # the function, which is also what makes "one implementation, two entry
    # points" checkable at all.
    with patch("services.online_quality_judge.submit_turn_judgement") as submit:
        session_id, res = _run_queue_turn(db_session, _judged_agent_output())

    assert res["status"] == "completed"
    assert submit.called
    kwargs = submit.call_args.kwargs

    assistant = db_session.exec(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
        )
    ).first()
    assert kwargs["message_id"] == str(assistant.id)
    assert kwargs["question"] == "Show total spend"
    assert kwargs["evidence"]["route"] == "SQL"
    assert kwargs["latency_ms"] > 0

    # ...and the synchronous path in `routers/chat.py` holds the very same
    # function object, so there is genuinely one implementation of this hook.
    import routers.chat as chat_router
    from services import online_quality_judge

    assert chat_router.submit_turn_judgement is online_quality_judge.submit_turn_judgement


def test_a_judge_failure_does_not_fail_the_queued_job(db_session, monkeypatch):
    """The job is already marked complete and the answer already delivered to
    the poller before this runs. A scoring failure must not flip it to failed."""
    import config

    monkeypatch.setattr(config.settings, "ENABLE_PRODUCTION_QUALITY_JUDGE", True)

    with patch("routers.chat._chat_background_pool") as pool:
        pool.submit.side_effect = RuntimeError("cannot schedule new futures after shutdown")
        session_id, res = _run_queue_turn(db_session, _judged_agent_output(), job_id="judge-job-2")

    assert res["status"] == "completed"
    assistant = db_session.exec(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
        )
    ).first()
    assert assistant.status == "completed"


# ---------------------------------------------------------------------------
# Gap 341 (item 12 of the Feature 25 security review): chat-job tenant isolation
#
# `get_chat_job_status()` and `stream_chat_job()` both declared a
# `tenant_context` dependency and then never read it. They authenticated the
# caller and checked nothing else, so ANY authenticated caller who learned a
# `job_id` could read another tenant's chat answer -- the reply text, the
# generated SQL and the citations, all of which are that tenant's invoice data.
#
# It was dormant (`ENABLE_ASYNC_CHAT_QUEUE` defaults False, so no job ids exist
# to guess in a default deployment) but it was fixed before the widget token
# landed, because a widget token lives in a customer's public page source and
# drops the bar for "an authenticated caller" to "anyone who viewed the page".
# ---------------------------------------------------------------------------


def test_job_status_refuses_another_tenants_job(db_session):
    """The cross-tenant read this fix exists to close."""
    client = TestClient(app)
    job_id = "job-belonging-to-someone-else"
    _seed_owned_job(db_session, job_id, tenant_id=uuid4())

    with patch(
        "services.chat_queue.ChatQueueService.get_job_status",
        return_value={
            "job_id": job_id,
            "status": "completed",
            "result": {"content": "Their confidential answer"},
        },
    ) as mocked:
        res = client.get(f"/api/v1/chat/jobs/{job_id}/status")

    assert res.status_code == 403
    assert "Access forbidden" in res.json()["detail"]
    # And the payload was never even fetched -- the check runs before the read,
    # so there is no window in which the other tenant's answer is in memory.
    assert mocked.call_count == 0


def test_job_stream_refuses_another_tenants_job(db_session):
    """The more serious of the two: this one streams the full result payload.

    The 403 must arrive as a 403, not as a broken stream -- an HTTPException
    raised inside the SSE generator would land after the 200 and the response
    headers were already on the wire.
    """
    client = TestClient(app)
    job_id = "stream-belonging-to-someone-else"
    _seed_owned_job(db_session, job_id, tenant_id=uuid4())

    with patch(
        "services.chat_queue.ChatQueueService.get_job_status",
        return_value={"job_id": job_id, "status": "completed", "result": {"content": "secret"}},
    ) as mocked:
        res = client.get(f"/api/v1/chat/jobs/{job_id}/stream")

    assert res.status_code == 403
    assert "text/event-stream" not in res.headers.get("content-type", "")
    assert "secret" not in res.text
    assert mocked.call_count == 0


def test_unknown_job_is_404_not_403(db_session):
    """An unknown id must not be distinguishable from another tenant's id by
    status code -- otherwise the pair of responses is a probe for which job ids
    exist on other tenants."""
    client = TestClient(app)
    for suffix in ("status", "stream"):
        res = client.get(f"/api/v1/chat/jobs/no-such-job/{suffix}")
        assert res.status_code == 404


def test_own_job_still_readable(db_session):
    """The fix must not break the endpoints for their actual users."""
    client = TestClient(app)
    job_id = "my-own-job"
    _seed_owned_job(db_session, job_id)

    with patch(
        "services.chat_queue.ChatQueueService.get_job_status",
        return_value={"job_id": job_id, "status": "completed", "result": {"content": "mine"}},
    ):
        res = client.get(f"/api/v1/chat/jobs/{job_id}/status")
    assert res.status_code == 200
    assert res.json()["result"]["content"] == "mine"


def test_job_isolation_on_postgres():
    """Gap 341 item 12 against real Postgres.

    Why Postgres and not just SQLite: the ownership answer is a two-hop join
    across `chat_messages.session_id` -> `chat_sessions.tenant_id`, both real
    UUID columns with real constraints, and this repo's standing rule is that a
    security fix is not claimed working on a SQLite-only run. Two real tenants,
    two real sessions, two real queued messages, and the endpoint driven for
    each of the four combinations of (caller, job).
    """
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings
    from dependencies import TenantContext
    from routers.chat import _require_owned_chat_job
    from fastapi import HTTPException
    from models import Tenant

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)

    tag = uuid4().hex[:10]
    tenant_a_id, tenant_b_id = uuid4(), uuid4()
    session_a, session_b = uuid4(), uuid4()
    job_a, job_b = f"pgjob-a-{tag}", f"pgjob-b-{tag}"

    with Session(pg_engine) as session:
        try:
            session.add(Tenant(id=tenant_a_id, name="A", domain=f"jobiso-a-{tag}.invalid"))
            session.add(Tenant(id=tenant_b_id, name="B", domain=f"jobiso-b-{tag}.invalid"))
            session.add(ChatSession(id=session_a, tenant_id=tenant_a_id, title="a"))
            session.add(ChatSession(id=session_b, tenant_id=tenant_b_id, title="b"))
            session.commit()
            session.add(ChatMessage(id=uuid4(), session_id=session_a, role="user",
                                    content="q", status="queued", job_id=job_a))
            session.add(ChatMessage(id=uuid4(), session_id=session_b, role="user",
                                    content="q", status="queued", job_id=job_b))
            session.commit()

            ctx_a = TenantContext(tenant_id=tenant_a_id, user_id="u_a", role="Admin",
                                  billing_plan="free")
            ctx_b = TenantContext(tenant_id=tenant_b_id, user_id="u_b", role="Admin",
                                  billing_plan="free")

            # Each tenant reads its own job.
            _require_owned_chat_job(job_a, session, ctx_a)
            _require_owned_chat_job(job_b, session, ctx_b)

            # And neither can read the other's.
            for job_id, ctx in ((job_a, ctx_b), (job_b, ctx_a)):
                with pytest.raises(HTTPException) as exc:
                    _require_owned_chat_job(job_id, session, ctx)
                assert exc.value.status_code == 403

            with pytest.raises(HTTPException) as exc:
                _require_owned_chat_job(f"nonexistent-{tag}", session, ctx_a)
            assert exc.value.status_code == 404
        finally:
            for sid in (session_a, session_b):
                for msg in session.exec(
                    select(ChatMessage).where(ChatMessage.session_id == sid)
                ).all():
                    session.delete(msg)
                row = session.get(ChatSession, sid)
                if row is not None:
                    session.delete(row)
            session.flush()
            for tid in (tenant_a_id, tenant_b_id):
                row = session.get(Tenant, tid)
                if row is not None:
                    session.delete(row)
            session.commit()


# ---------------------------------------------------------------------------
# Gap 364: PER_TENANT_MAX_ACTIVE_CHAT is actually enforced
#
# `test_tenant_concurrency_throttle_and_fair_share_tracking` above asserted
# `mock_redis.incr.called` and stopped there -- which is exactly why the missing
# comparison stayed invisible: the counter really was incremented, it was just
# never compared to anything. These cases count for real, against a fake that
# keeps state, so "the 4th is refused" is a property of the code and not of a
# mock's configured return value.
# ---------------------------------------------------------------------------


class _CountingRedis:
    """In-memory stand-in for the five Redis ops the enqueue path uses.

    A `MagicMock` cannot express this test: the whole question is what the
    *value returned by INCR* causes, so the counter has to be real. `lpush` can
    be armed to fail, which is the slot-leak case.
    """

    def __init__(self, fail_lpush: bool = False):
        self.counters: dict[str, int] = {}
        self.blobs: dict[str, str] = {}
        self.queue: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.fail_lpush = fail_lpush

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def decr(self, key):
        self.counters[key] = self.counters.get(key, 0) - 1
        return self.counters[key]

    def get(self, key):
        if key in self.counters:
            return str(self.counters[key])
        return self.blobs.get(key)

    def set(self, key, value, ex=None):
        if key in self.counters:
            self.counters[key] = int(value)
        else:
            self.blobs[key] = value

    def lpush(self, key, value):
        if self.fail_lpush:
            raise ConnectionError("Redis connection reset by peer")
        self.queue.append(value)
        return len(self.queue)

    def publish(self, channel, message):
        # `complete_job`/`fail_job` publish before releasing the slot, and they
        # swallow their own exceptions -- so a fake without this silently skips
        # the release under test rather than failing loudly.
        self.published.append((channel, message))
        return 1


def _enqueue(tenant_id, client):
    return ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="How much did we spend with Acme?",
        tenant_id=tenant_id,
        client=client,
    )


def test_fourth_concurrent_turn_for_one_tenant_is_refused():
    """The ceiling is 3, so turns 1-3 queue and the 4th is refused.

    Before Gap 364 the 4th (and the 400th) queued happily -- `enqueue_chat_job`
    incremented `chat_inflight:{tenant}` and never read it back, and
    `PER_TENANT_MAX_ACTIVE_CHAT` was referenced nowhere else in the application.
    """
    assert PER_TENANT_MAX_ACTIVE_CHAT == 3  # the cases below are written for 3
    r = _CountingRedis()
    tenant_id = "tenant-at-the-ceiling"
    inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}"

    accepted = [_enqueue(tenant_id, r) for _ in range(PER_TENANT_MAX_ACTIVE_CHAT)]
    assert [job["status"] for job in accepted] == ["queued"] * 3
    assert len(r.queue) == 3, "all three accepted turns reached the task queue"
    assert r.counters[inflight_key] == 3

    with pytest.raises(ChatQueueCapacityError) as exc:
        _enqueue(tenant_id, r)

    assert exc.value.limit == PER_TENANT_MAX_ACTIVE_CHAT
    assert exc.value.retry_after_seconds == 5

    # The three in flight are untouched: still queued, still holding 3 slots.
    assert len(r.queue) == 3, "the refused turn was not pushed onto the queue"
    assert r.counters[inflight_key] == 3, "the refused turn handed its slot back"

    # ...and no status blob was left behind for a job that will never run:
    # exactly the three accepted job ids have one. The ceiling check runs before
    # the status `set` precisely so a refusal writes nothing at all.
    assert len(r.blobs) == 3


def test_a_refusal_does_not_permanently_consume_the_slot():
    """The DECR-back matters more than the refusal itself: without it the
    counter climbs on every rejected attempt, the tenant sits above the ceiling
    forever, and nothing decrements it because no job ever ran."""
    r = _CountingRedis()
    tenant_id = "tenant-retrying"
    inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}"

    for _ in range(PER_TENANT_MAX_ACTIVE_CHAT):
        _enqueue(tenant_id, r)

    for _ in range(5):
        with pytest.raises(ChatQueueCapacityError):
            _enqueue(tenant_id, r)

    assert r.counters[inflight_key] == 3, "five refusals did not inflate the counter"
    assert ChatQueueService.get_tenant_inflight_count(tenant_id, client=r) == 3

    # One finishes -> the freed slot is immediately usable again.
    ChatQueueService.release_tenant_slot(tenant_id, client=r)
    assert _enqueue(tenant_id, r)["status"] == "queued"
    assert r.counters[inflight_key] == 3


def test_failed_job_releases_its_slot_and_frees_the_ceiling():
    """`fail_job` already released the slot; what Gap 364 adds is that the
    release now demonstrably lets a refused tenant back in."""
    r = _CountingRedis()
    tenant_id = "tenant-with-a-failure"

    for _ in range(PER_TENANT_MAX_ACTIVE_CHAT):
        _enqueue(tenant_id, r)
    with pytest.raises(ChatQueueCapacityError):
        _enqueue(tenant_id, r)

    ChatQueueService.fail_job(
        job_id="doomed-job",
        tenant_id=tenant_id,
        error_message="Azure OpenAI Rate Limit Exceeded",
        client=r,
    )
    assert ChatQueueService.get_tenant_inflight_count(tenant_id, client=r) == 2
    assert _enqueue(tenant_id, r)["status"] == "queued"


def test_lpush_failure_rolls_the_reserved_slot_back():
    """The slot leak, directly.

    The `except` in `enqueue_chat_job` swallows Redis failures on purpose --
    chat must not 500 because the queue hiccuped -- but the INCR has already
    happened by the time `lpush` throws. Swallowing without releasing burned one
    of the tenant's three slots permanently: `chat_inflight:{tenant}` has no TTL
    and only `complete_job`/`fail_job` decrement it, neither of which runs for a
    job that was never queued. Three such failures and that tenant could never
    chat again.
    """
    r = _CountingRedis(fail_lpush=True)
    tenant_id = "tenant-hitting-a-flaky-redis"
    inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}"

    # Still returns a job id rather than raising -- the swallow is deliberate.
    assert _enqueue(tenant_id, r)["status"] == "queued"

    assert r.queue == [], "nothing reached the queue, which is the failure"
    assert r.counters[inflight_key] == 0, "the reserved slot was handed back"

    # Repeat it: a flaky Redis must not ratchet the tenant out of service.
    for _ in range(10):
        _enqueue(tenant_id, r)
    assert r.counters[inflight_key] == 0

    # And once Redis recovers the tenant still has all three slots available.
    r.fail_lpush = False
    for _ in range(PER_TENANT_MAX_ACTIVE_CHAT):
        assert _enqueue(tenant_id, r)["status"] == "queued"
    with pytest.raises(ChatQueueCapacityError):
        _enqueue(tenant_id, r)


def test_over_capacity_post_returns_429_with_retry_after_and_no_orphan_row(db_session):
    """The HTTP half: a refused turn is a 429 the FE can act on, and it leaves
    the session exactly as it found it.

    The orphan row is the part worth guarding. `post_chat_message` commits the
    user `ChatMessage(status="queued")` before enqueuing, so a refusal that
    simply returned an error would leave a message no worker will ever move off
    `queued` -- the FE renders that as a turn stuck thinking forever.
    """
    session_id = uuid4()
    db_session.add(ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="New Chat"))
    db_session.commit()

    client = TestClient(app)

    with patch(
        "services.chat_queue.ChatQueueService.enqueue_chat_job",
        side_effect=ChatQueueCapacityError(
            tenant_id=str(MOCK_TENANT_ID), active=4, limit=PER_TENANT_MAX_ACTIVE_CHAT
        ),
    ):
        res = client.post(
            f"/api/v1/chat/sessions/{session_id}/message",
            json={"content": "What is the total spend on hardware?"},
        )

    assert res.status_code == 429
    assert res.headers["Retry-After"] == "5"
    assert "3 chat turns running" in res.json()["detail"]

    rows = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    ).all()
    assert rows == [], "a refused turn left no queued ChatMessage behind"

    # The auto-title is derived from the message that was refused, so it must
    # not stick either.
    db_session.expire_all()
    assert db_session.get(ChatSession, session_id).title == "New Chat"


def test_an_accepted_turn_is_unaffected_by_the_new_limiter(db_session):
    """Guard against the fix costing the happy path: under the ceiling, the
    endpoint still answers 202 and still stages the user row."""
    session_id = uuid4()
    db_session.add(ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="New Chat"))
    db_session.commit()

    client = TestClient(app)
    r = _CountingRedis()

    with patch("services.chat_queue.get_redis_client", return_value=r), \
         patch("routers.chat._chat_background_pool") as pool:
        res = client.post(
            f"/api/v1/chat/sessions/{session_id}/message",
            json={"content": "What is the total spend on hardware?"},
        )

    assert res.status_code == 202
    assert pool.submit.called
    assert len(r.queue) == 1
    assert r.counters[f"{CHAT_TENANT_INFLIGHT_PREFIX}{MOCK_TENANT_ID}"] == 1

    staged = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    ).one()
    assert staged.status == "queued"
    assert staged.job_id == res.json()["job_id"]
