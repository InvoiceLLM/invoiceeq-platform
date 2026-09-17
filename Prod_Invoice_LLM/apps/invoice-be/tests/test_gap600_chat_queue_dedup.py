"""BE Gap 600 (CH-33): Chat queue duplicate execution elimination tests.

Verifies:
1. `ChatQueueService.enqueue_chat_job` reports `enqueued: True` when successfully pushed to Redis,
   and `enqueued: False` when Redis is unavailable or enqueue fails.
2. In `POST /chat/sessions/{id}/message`:
   - If `enqueued: True`, the job is pushed to Redis ONLY and `_chat_background_pool.submit`
     is SKIPPED (preventing double execution).
   - If `enqueued: False` (fallback mode), `_chat_background_pool.submit` is invoked so in-process
     execution continues to work when Redis is absent.
3. In `handle_process_chat_job`:
   - The first worker/runner claims `chat_job_claimed:{job_id}` in Redis and runs.
   - Any second worker/runner attempting the same `job_id` detects the claim, logs, and aborts
     immediately without running `run_query_agent` or committing a duplicate assistant message.
4. Database duplicate guard:
   - If an assistant message with `job_id` already exists, a duplicate runner returns the existing
     message and avoids inserting a second assistant message row.
"""
import os
import json
from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool

from main import app
from models import ChatSession, ChatMessage, Tenant
from dependencies import (
    get_db_session,
    get_tenant_or_api_key_context,
    TenantContext,
)
from services.chat_queue import ChatQueueService
from queue_worker.handlers import handle_process_chat_job

# BE Gap 570 / Gap 525: PostgreSQL test fixture with strict localhost and db-name security guard
postgres_test_url = os.getenv("TEST_DATABASE_URL")
if postgres_test_url:
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(postgres_test_url)
    assert _parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1 to avoid accidental data loss."
    )
    assert "test" in (_parsed.path or "").lower(), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must name a throwaway database whose name contains 'test' "
        "(this fixture drops every table after each test)."
    )
    engine = create_engine(postgres_test_url)
else:
    sqlite_url = "sqlite:///:memory:"
    engine = create_engine(
        sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

client = TestClient(app)

TENANT_ID = uuid4()
USER_ALICE = "user_alice_test"


@pytest.fixture(name="db_session")
def db_session_fixture():
    if postgres_test_url:
        try:
            with engine.connect() as conn:
                pass
        except Exception as exc:
            pytest.fail(f"TEST_DATABASE_URL configured but unreachable: {exc}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        t = Tenant(id=TENANT_ID, name="Tenant 1", domain="t1.example.com", billing_plan="pro")
        session.add(t)
        session.commit()
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_dependencies(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: TenantContext(
        tenant_id=TENANT_ID,
        user_id=USER_ALICE,
        role="Admin",
        billing_plan="pro",
        auth_method="clerk",
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def enable_async_chat_queue(monkeypatch):
    import config
    monkeypatch.setattr(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", True)


def test_enqueue_chat_job_reports_enqueued_flag():
    """`enqueue_chat_job` returns enqueued=True when Redis push succeeds, enqueued=False when absent."""
    mock_redis = MagicMock()
    mock_redis.incr.return_value = 1

    # With healthy Redis
    res_ok = ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="Hello spend",
        tenant_id=str(TENANT_ID),
        job_id="job-test-1",
        client=mock_redis,
    )
    assert res_ok["enqueued"] is True
    assert mock_redis.lpush.called

    # Without Redis (client=None)
    res_no_redis = ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="Hello spend",
        tenant_id=str(TENANT_ID),
        job_id="job-test-2",
        # Review follow-up 2026-09-17: `client=None` does NOT mean "no Redis" --
        # `enqueue_chat_job` falls through to `get_redis_client()`, so on any machine
        # with a local Redis running this took the healthy path and `enqueued` came
        # back True. The absent-Redis case is expressed by patching the lookup, so the
        # test asserts the code path rather than the developer environment.
        client=None,
    )
    assert res_no_redis["enqueued"] in (True, False)  # depends on the live environment

    # The real "Redis is unavailable" path, independent of what is running locally.
    with patch("services.chat_queue.get_redis_client", return_value=None):
        res_absent = ChatQueueService.enqueue_chat_job(
            session_id=str(uuid4()),
            user_msg_id=str(uuid4()),
            content="Hello spend",
            tenant_id=str(TENANT_ID),
            job_id=f"job-absent-{uuid4()}",
            client=None,
        )
    assert res_absent["enqueued"] is False


def test_post_message_skips_local_pool_when_enqueued_to_redis(db_session):
    """When a job is enqueued to Redis, local _chat_background_pool.submit is NOT called."""
    s = ChatSession(id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Test Thread")
    db_session.add(s)
    db_session.commit()

    with patch("services.chat_queue.ChatQueueService.enqueue_chat_job") as mock_enqueue, \
         patch("routers.chat._chat_background_pool.submit") as mock_pool_submit:

        mock_enqueue.return_value = {
            "job_id": "job-test-success",
            "status": "queued",
            "created_at": "2026-09-16T12:00:00Z",
            "enqueued": True,
        }

        res = client.post(
            f"/api/v1/chat/sessions/{s.id}/message",
            json={"content": "What is our spend?"},
        )
        assert res.status_code == 202
        assert mock_enqueue.called
        # The critical assertion for BE Gap 600: local pool submit MUST NOT be called!
        assert not mock_pool_submit.called, "Local pool must not be submitted to when Redis enqueue succeeded"


def test_post_message_falls_back_to_local_pool_when_redis_unavailable(db_session):
    """When enqueue_chat_job reports enqueued=False (fallback), local pool submit IS called."""
    s = ChatSession(id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Test Thread")
    db_session.add(s)
    db_session.commit()

    with patch("services.chat_queue.ChatQueueService.enqueue_chat_job") as mock_enqueue, \
         patch("routers.chat._chat_background_pool.submit") as mock_pool_submit:

        mock_enqueue.return_value = {
            "job_id": "job-test-fallback",
            "status": "queued",
            "created_at": "2026-09-16T12:00:00Z",
            "enqueued": False,
        }

        res = client.post(
            f"/api/v1/chat/sessions/{s.id}/message",
            json={"content": "What is our spend?"},
        )
        assert res.status_code == 202
        assert mock_enqueue.called
        # When Redis enqueue is False, fallback submit MUST be called
        assert mock_pool_submit.called


def test_atomic_claim_blocks_duplicate_runner(db_session):
    """If a duplicate runner attempts the same job_id, Redis atomic claim halts it immediately."""
    session_id = uuid4()
    user_msg_id = uuid4()
    job_id = "job-atomic-claim-test"

    s = ChatSession(id=session_id, tenant_id=TENANT_ID, user_id=USER_ALICE, title="Test Session")
    u = ChatMessage(id=user_msg_id, session_id=session_id, role="user", content="Hi", status="queued", job_id=job_id)
    db_session.add(s)
    db_session.add(u)
    db_session.commit()

    mock_redis = MagicMock()
    claimed_jobs = set()

    def fake_set(name, value, *args, **kwargs):
        if str(name).startswith("chat_job_claimed:"):
            if name in claimed_jobs:
                return None
            claimed_jobs.add(name)
            return True
        return True

    mock_redis.set.side_effect = fake_set

    agent_output = {
        "content": "First answer",
        "generated_sql": "SELECT 1",
        "citations": [],
    }

    with patch("queue_worker.handlers._get_redis_sync", return_value=mock_redis), \
         patch("agents.query_agent.run_query_agent", return_value=agent_output) as mock_agent, \
         patch("services.chat_queue.ChatQueueService.publish_progress"), \
         patch("services.chat_queue.ChatQueueService.complete_job"):

        # 1. First runner executes successfully
        res1 = handle_process_chat_job(
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg_id),
            content="Hi",
            tenant_id=str(TENANT_ID),
            db_session=db_session,
        )
        assert res1["status"] == "completed"
        assert mock_agent.call_count == 1

        # 2. Duplicate runner with same job_id attempts execution
        res2 = handle_process_chat_job(
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg_id),
            content="Hi",
            tenant_id=str(TENANT_ID),
            db_session=db_session,
        )
        # Aborted via atomic claim guard
        assert res2["status"] == "duplicate_claimed"
        # Agent was NOT called a second time
        assert mock_agent.call_count == 1

    # Verify only ONE assistant message exists in the DB
    assistants = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
    ).all()
    assert len(assistants) == 1


def test_database_defense_in_depth_blocks_duplicate_assistant(db_session):
    """Even if Redis is unavailable, an existing assistant row for job_id prevents a second execution."""
    session_id = uuid4()
    user_msg_id = uuid4()
    job_id = "job-db-dedup-test"

    s = ChatSession(id=session_id, tenant_id=TENANT_ID, user_id=USER_ALICE, title="Test Session")
    u = ChatMessage(id=user_msg_id, session_id=session_id, role="user", content="Spend?", status="completed", job_id=job_id)
    # Assistant already created
    a = ChatMessage(id=uuid4(), session_id=session_id, role="assistant", content="Spend is $100", status="completed", job_id=job_id)
    db_session.add(s)
    db_session.add(u)
    db_session.add(a)
    db_session.commit()

    with patch("queue_worker.handlers._get_redis_sync", return_value=None), \
         patch("agents.query_agent.run_query_agent") as mock_agent:

        res = handle_process_chat_job(
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg_id),
            content="Spend?",
            tenant_id=str(TENANT_ID),
            db_session=db_session,
        )
        assert res["status"] == "completed"
        assert res["content"] == "Spend is $100"
        # Agent was never run because row was found
        assert not mock_agent.called

    # Ensure still exactly 1 assistant message in DB
    assistants = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
    ).all()
    assert len(assistants) == 1
