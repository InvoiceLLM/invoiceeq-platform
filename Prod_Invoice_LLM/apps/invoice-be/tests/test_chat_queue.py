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
from services.chat_queue import ChatQueueService
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


def test_chat_job_status_and_stream_endpoints(db_session):
    """Gap 280: Verify /chat/jobs/{id}/status and /stream endpoints."""
    job_id = "job-stream-789"
    client = TestClient(app)

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
