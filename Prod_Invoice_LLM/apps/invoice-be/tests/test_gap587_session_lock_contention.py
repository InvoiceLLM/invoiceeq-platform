"""Tests for BE Gap 587 (CH-20): Synchronous and widget turns run under chat_session_lock,
returning HTTP 409 Conflict immediately on lock contention.

Founder ruling 2026-09-16: return 409 immediately on lock contention.
A second turn arriving while the session lock is held is refused with
"A chat turn is already running in this session." -- no waiting, no held worker
thread, no implicit queueing.
"""

import os
import threading
import time
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from config import get_settings
from dependencies import (
    get_db_session,
    get_tenant_or_api_key_context,
    get_tenant_context,
    TenantContext,
    MOCK_TENANT_ID,
)
from models import ChatSession, ChatMessage, Tenant
from services.chat_queue import (
    CHAT_SESSION_LOCK_PREFIX,
    ChatSessionLockedError,
    chat_session_lock,
    is_chat_session_locked,
)
from services.widget_tokens import issue_widget_token

# Gap 570 / Gap 525: Allow running against Postgres with strict localhost guard
postgres_test_url = os.getenv("TEST_DATABASE_URL")
if postgres_test_url:
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(postgres_test_url)
    assert _parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1"
    )
    assert "test" in (_parsed.path or "").lower(), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must name a throwaway test database"
    )
    engine = create_engine(postgres_test_url)
else:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)


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
        tenant = Tenant(id=MOCK_TENANT_ID, name="Mock Tenant", domain="example.com", billing_plan="pro")
        session.add(tenant)
        session.commit()
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_deps(db_session):
    def get_db_session_override():
        yield db_session

    def get_context_override():
        return TenantContext(
            tenant_id=MOCK_TENANT_ID,
            user_id="test-user-id",
            role="Admin",
            billing_plan="pro",
        )

    app.dependency_overrides[get_db_session] = get_db_session_override
    app.dependency_overrides[get_tenant_or_api_key_context] = get_context_override
    app.dependency_overrides[get_tenant_context] = get_context_override
    yield
    app.dependency_overrides.clear()


class _MockRedis:
    """Thread-safe Redis mock supporting get, set(nx=True, ex=...), and delete."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            return self._data.get(key)

    def set(self, key, value, nx=False, ex=None):
        with self._lock:
            if nx and key in self._data:
                return False
            self._data[key] = str(value)
            return True

    def delete(self, *keys):
        with self._lock:
            count = 0
            for k in keys:
                if k in self._data:
                    del self._data[k]
                    count += 1
            return count

    def exists(self, key):
        with self._lock:
            return 1 if key in self._data else 0


@pytest.fixture
def mock_redis():
    return _MockRedis()


@pytest.fixture
def test_client():
    return TestClient(app)


def test_chat_session_lock_raise_on_contention_unit(mock_redis):
    """Direct unit test of chat_session_lock with raise_on_contention=True."""
    sid = str(uuid4())

    with chat_session_lock(sid, client=mock_redis, raise_on_contention=True) as held1:
        assert held1 is True
        assert is_chat_session_locked(sid, client=mock_redis) is True

        # Second concurrent acquisition must raise ChatSessionLockedError immediately
        with pytest.raises(ChatSessionLockedError) as exc_info:
            with chat_session_lock(sid, client=mock_redis, raise_on_contention=True):
                pass
        assert "A chat turn is already running in this session." in str(exc_info.value)

    # After releasing, lock is clear and can be acquired again
    assert is_chat_session_locked(sid, client=mock_redis) is False
    with chat_session_lock(sid, client=mock_redis, raise_on_contention=True) as held2:
        assert held2 is True


def test_sync_chat_turn_returns_409_on_lock_contention(db_session, mock_redis, test_client):
    """When a session lock is held, POST /api/v1/chat/sessions/{id}/message?sync=true returns 409 immediately."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Sync test session",
        user_id="test-user-id",
    )
    db_session.add(chat_session)
    db_session.commit()

    # Pre-hold the lock in Redis for this session
    mock_redis.set(f"{CHAT_SESSION_LOCK_PREFIX}{session_id}", "token-holder-1", nx=True)

    with patch("services.chat_queue.get_redis_client", return_value=mock_redis):
        response = test_client.post(
            f"/api/v1/chat/sessions/{session_id}/message?sync=true",
            headers={"X-User-Id": "test-user-id"},
            json={"content": "Hello while locked"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "A chat turn is already running in this session."


def test_widget_chat_turn_returns_409_on_lock_contention(db_session, mock_redis, test_client):
    """When a session lock is held, POST /api/v1/widget/chat/message returns 409 immediately."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Website widget chat",
    )
    db_session.add(chat_session)

    # Issue a widget token
    _token, raw_token = issue_widget_token(
        db_session=db_session,
        tenant_id=MOCK_TENANT_ID,
        label="Test Widget Token",
        allowed_origins=["https://example.com"],
    )

    # Pre-hold the lock in Redis for this session
    mock_redis.set(f"{CHAT_SESSION_LOCK_PREFIX}{session_id}", "token-holder-widget", nx=True)

    with patch("services.chat_queue.get_redis_client", return_value=mock_redis):
        response = test_client.post(
            "/api/v1/widget/chat/message",
            headers={
                "X-API-Key": raw_token,
                "Origin": "https://example.com",
            },
            json={
                "session_id": str(session_id),
                "content": "Hello from widget while locked",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "A chat turn is already running in this session."


def test_async_chat_turn_returns_409_on_lock_contention(db_session, mock_redis, test_client):
    """Async turn returns 409 immediately on session lock contention (no implicit queueing)."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Async test session",
        user_id="test-user-id",
    )
    db_session.add(chat_session)
    db_session.commit()

    # Pre-hold the lock in Redis for this session
    mock_redis.set(f"{CHAT_SESSION_LOCK_PREFIX}{session_id}", "token-holder-async", nx=True)

    with patch("services.chat_queue.get_redis_client", return_value=mock_redis), \
         patch.object(get_settings(), "ENABLE_ASYNC_CHAT_QUEUE", True):
        response = test_client.post(
            f"/api/v1/chat/sessions/{session_id}/message",
            headers={"X-User-Id": "test-user-id"},
            json={"content": "Second turn arriving while first is running"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "A chat turn is already running in this session."

    # Verify no queued row was created (no implicit queueing)
    queued_msgs = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    ).all()
    assert len(queued_msgs) == 0


def test_turn_returns_409_when_active_message_in_db(db_session, mock_redis, test_client):
    """When a previous turn is in 'queued' or 'processing' status in DB, subsequent turn gets 409."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Active message in DB session",
        user_id="test-user-id",
    )
    db_session.add(chat_session)
    active_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="First in-flight question",
        status="processing",
    )
    db_session.add(active_msg)
    db_session.commit()

    with patch("services.chat_queue.get_redis_client", return_value=mock_redis):
        response = test_client.post(
            f"/api/v1/chat/sessions/{session_id}/message",
            headers={"X-User-Id": "test-user-id"},
            json={"content": "Second question arriving"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "A chat turn is already running in this session."


def test_sync_turn_acquires_and_releases_lock_on_success(db_session, mock_redis, test_client):
    """When lock is free, sync turn acquires lock and releases it after completion."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Clean turn session",
        user_id="test-user-id",
    )
    db_session.add(chat_session)
    db_session.commit()

    mock_agent_output = {
        "content": "Here is the answer.",
        "generated_sql": "SELECT 1;",
        "citations": [],
        "result_invoice_ids": [],
        "turn_telemetry": {"status": "success", "route": "SQL"},
    }

    with patch("services.chat_queue.get_redis_client", return_value=mock_redis), \
         patch("routers.chat.run_query_agent", return_value=mock_agent_output):
        response = test_client.post(
            f"/api/v1/chat/sessions/{session_id}/message?sync=true",
            headers={"X-User-Id": "test-user-id"},
            json={"content": "Clean query"},
        )

    assert response.status_code == 200
    assert response.json()["content"] == "Here is the answer."
    # After completion, lock is released
    assert is_chat_session_locked(str(session_id), client=mock_redis) is False


def test_two_different_sessions_do_not_contend(db_session, mock_redis, test_client):
    """Holding lock on session A does not block session B."""
    session_a = uuid4()
    session_b = uuid4()

    chat_session_a = ChatSession(id=session_a, tenant_id=MOCK_TENANT_ID, title="Session A", user_id="test-user-id")
    chat_session_b = ChatSession(id=session_b, tenant_id=MOCK_TENANT_ID, title="Session B", user_id="test-user-id")
    db_session.add(chat_session_a)
    db_session.add(chat_session_b)
    db_session.commit()

    # Lock session A
    mock_redis.set(f"{CHAT_SESSION_LOCK_PREFIX}{session_a}", "holder-a", nx=True)

    mock_agent_output = {
        "content": "Answer for B",
        "generated_sql": None,
        "citations": [],
        "result_invoice_ids": [],
    }

    with patch("services.chat_queue.get_redis_client", return_value=mock_redis), \
         patch("routers.chat.run_query_agent", return_value=mock_agent_output):
        response_b = test_client.post(
            f"/api/v1/chat/sessions/{session_b}/message?sync=true",
            headers={"X-User-Id": "test-user-id"},
            json={"content": "Query for B"},
        )

    assert response_b.status_code == 200
    assert response_b.json()["content"] == "Answer for B"


def test_redis_down_degrades_gracefully_without_409(db_session, test_client):
    """When Redis is unreachable, turn degrades to unserialised execution without throwing 409 or 500."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Redis down session",
        user_id="test-user-id",
    )
    db_session.add(chat_session)
    db_session.commit()

    mock_agent_output = {
        "content": "Answer despite Redis down",
        "generated_sql": None,
        "citations": [],
        "result_invoice_ids": [],
    }

    # Simulate Redis connection failure
    with patch("services.chat_queue.get_redis_client", return_value=None), \
         patch("routers.chat.run_query_agent", return_value=mock_agent_output):
        response = test_client.post(
            f"/api/v1/chat/sessions/{session_id}/message?sync=true",
            headers={"X-User-Id": "test-user-id"},
            json={"content": "Query with Redis down"},
        )

    assert response.status_code == 200
    assert response.json()["content"] == "Answer despite Redis down"
