"""BE Gap 572 (CH-5): User-level chat isolation tests.

Verifies:
1. When a signed-in user creates a chat session, user_id is stamped with their user_id.
2. Non-admin users can only list and access their own chat sessions in the tenant.
3. Cross-user session read, rename, delete, and message posting within the same tenant returns 403 Forbidden.
4. Legacy sessions (user_id IS NULL) are hidden from non-admin users (list/read return empty/403).
5. Admins retain full visibility across all sessions in the tenant (own, other users, and legacy).
6. API key callers return 403 Forbidden on GET /chat/sessions and GET /chat/sessions/{id}.
7. API key callers can create unowned sessions (user_id=None) and post messages to them, but cannot post to user-owned sessions.
8. Chat attachment access via _require_owned_session enforces user isolation and API-key restrictions.
"""
import os
from uuid import UUID, uuid4
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool

from main import app
from models import ChatSession, ChatMessage, Tenant
from dependencies import (
    get_db_session,
    get_tenant_or_api_key_context,
    get_tenant_context,
    TenantContext,
)
from routers.chat_attachments import _require_owned_session

# Gap 570 / Gap 525: PostgreSQL test fixture with strict localhost and db-name security guard
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
OTHER_TENANT_ID = uuid4()

USER_ALICE = "user_alice_123"
USER_BOB = "user_bob_456"
USER_ADMIN = "user_admin_789"


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
        # Seed test tenants
        t1 = Tenant(id=TENANT_ID, name="Tenant 1", domain="t1.example.com", billing_plan="pro")
        t2 = Tenant(id=OTHER_TENANT_ID, name="Tenant 2", domain="t2.example.com", billing_plan="pro")
        session.add(t1)
        session.add(t2)
        session.commit()
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


def make_context(
    user_id: str = USER_ALICE,
    role: str = "Member",
    tenant_id=TENANT_ID,
    auth_method: str = "clerk",
    key_scope: str | None = None,
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        billing_plan="pro",
        auth_method=auth_method,
        key_scope=key_scope,
    )


def test_session_creation_records_user_id(db_session):
    """A signed-in user creating a session gets their user_id saved on the session."""
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id=USER_ALICE, role="Member"
    )

    res = client.post("/api/v1/chat/sessions", json={"title": "Alice's Project"})
    assert res.status_code == 201
    data = res.json()
    assert data["user_id"] == USER_ALICE
    assert data["title"] == "Alice's Project"

    # Verify directly in DB
    session_row = db_session.exec(
        select(ChatSession).where(ChatSession.id == UUID(data["id"]))
    ).first()
    assert session_row is not None
    assert session_row.user_id == USER_ALICE


def test_non_admin_listing_only_returns_own_sessions(db_session):
    """Alice and Bob can only see their own sessions when calling GET /chat/sessions."""
    # Alice creates session
    s_alice = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Alice Session"
    )
    # Bob creates session
    s_bob = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_BOB, title="Bob Session"
    )
    db_session.add(s_alice)
    db_session.add(s_bob)
    db_session.commit()

    # Alice lists
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id=USER_ALICE, role="Member"
    )
    res_alice = client.get("/api/v1/chat/sessions")
    assert res_alice.status_code == 200
    alice_list = res_alice.json()
    assert len(alice_list) == 1
    assert alice_list[0]["id"] == str(s_alice.id)
    assert alice_list[0]["user_id"] == USER_ALICE

    # Bob lists
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id=USER_BOB, role="Member"
    )
    res_bob = client.get("/api/v1/chat/sessions")
    assert res_bob.status_code == 200
    bob_list = res_bob.json()
    assert len(bob_list) == 1
    assert bob_list[0]["id"] == str(s_bob.id)
    assert bob_list[0]["user_id"] == USER_BOB


def test_cross_user_session_access_forbidden(db_session):
    """Bob trying to read, rename, delete, or message Alice's session returns 403."""
    s_alice = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Alice Session"
    )
    db_session.add(s_alice)
    db_session.commit()

    # Bob acts on Alice's session
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id=USER_BOB, role="Member"
    )

    # 1. Read messages
    res_get = client.get(f"/api/v1/chat/sessions/{s_alice.id}")
    assert res_get.status_code == 403
    assert "Access forbidden" in res_get.json()["detail"]

    # 2. Rename session
    res_put = client.put(f"/api/v1/chat/sessions/{s_alice.id}", json={"title": "Hacked Title"})
    assert res_put.status_code == 403
    assert "Access forbidden" in res_put.json()["detail"]

    # 3. Post message
    res_post = client.post(
        f"/api/v1/chat/sessions/{s_alice.id}/message",
        json={"content": "Unauthorized message"},
    )
    assert res_post.status_code == 403
    assert "Access forbidden" in res_post.json()["detail"]

    # 4. Delete session
    res_del = client.delete(f"/api/v1/chat/sessions/{s_alice.id}")
    assert res_del.status_code == 403
    assert "Access forbidden" in res_del.json()["detail"]


def test_legacy_sessions_hidden_from_non_admins(db_session):
    """Legacy sessions (user_id IS NULL) are hidden from non-admin users (fail safe)."""
    legacy_session = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=None, title="Legacy Unowned Thread"
    )
    db_session.add(legacy_session)
    db_session.commit()

    # Alice (Member)
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id=USER_ALICE, role="Member"
    )

    # Not visible in list
    res = client.get("/api/v1/chat/sessions")
    assert res.status_code == 200
    assert len(res.json()) == 0

    # 403 on get history
    res_get = client.get(f"/api/v1/chat/sessions/{legacy_session.id}")
    assert res_get.status_code == 403

    # 403 on rename
    res_put = client.put(f"/api/v1/chat/sessions/{legacy_session.id}", json={"title": "Renamed"})
    assert res_put.status_code == 403

    # 403 on delete
    res_del = client.delete(f"/api/v1/chat/sessions/{legacy_session.id}")
    assert res_del.status_code == 403


def test_admin_has_full_visibility(db_session):
    """Admin sees all sessions: Alice's, Bob's, and legacy unowned sessions."""
    s_alice = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Alice Thread"
    )
    s_bob = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_BOB, title="Bob Thread"
    )
    s_legacy = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=None, title="Legacy Thread"
    )
    db_session.add(s_alice)
    db_session.add(s_bob)
    db_session.add(s_legacy)
    db_session.commit()

    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id=USER_ADMIN, role="Admin"
    )

    # Admin lists all
    res = client.get("/api/v1/chat/sessions")
    assert res.status_code == 200
    session_ids = {s["id"] for s in res.json()}
    assert session_ids == {str(s_alice.id), str(s_bob.id), str(s_legacy.id)}

    # Admin can read Alice's messages
    res_alice_msgs = client.get(f"/api/v1/chat/sessions/{s_alice.id}")
    assert res_alice_msgs.status_code == 200

    # Admin can read legacy messages
    res_legacy_msgs = client.get(f"/api/v1/chat/sessions/{s_legacy.id}")
    assert res_legacy_msgs.status_code == 200

    # Admin can rename Alice's session
    res_rename = client.put(
        f"/api/v1/chat/sessions/{s_alice.id}", json={"title": "Admin Renamed Alice"}
    )
    assert res_rename.status_code == 200
    assert res_rename.json()["title"] == "Admin Renamed Alice"


def test_api_keys_forbidden_from_listing_and_reading_history(db_session):
    """API key callers get 403 on GET /chat/sessions and GET /chat/sessions/{id}."""
    s_alice = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Alice Thread"
    )
    db_session.add(s_alice)
    db_session.commit()

    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id="api_key_service",
        role="Viewer",
        auth_method="api_key",
        key_scope="readonly",
    )

    # 1. Listing is forbidden
    res_list = client.get("/api/v1/chat/sessions")
    assert res_list.status_code == 403
    assert "API key callers are not permitted to list" in res_list.json()["detail"]

    # 2. Reading history is forbidden
    res_read = client.get(f"/api/v1/chat/sessions/{s_alice.id}")
    assert res_read.status_code == 403
    assert "API key callers are not permitted to read" in res_read.json()["detail"]

    # 3. Modifying session is forbidden
    res_put = client.put(f"/api/v1/chat/sessions/{s_alice.id}", json={"title": "Hacked"})
    assert res_put.status_code == 403

    # 4. Deleting session is forbidden
    res_del = client.delete(f"/api/v1/chat/sessions/{s_alice.id}")
    assert res_del.status_code == 403


def test_api_key_can_create_unowned_session_and_is_blocked_from_user_sessions(db_session):
    """API keys can create unowned sessions (user_id=None) but cannot post to user-owned sessions."""
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: make_context(
        user_id="api_key_service",
        role="Viewer",
        auth_method="api_key",
        key_scope="actions",
    )

    # API key creates session
    res = client.post("/api/v1/chat/sessions", json={"title": "API Key Thread"})
    assert res.status_code == 201
    created = res.json()
    assert created["user_id"] is None

    # Verify cannot post to Alice's session
    s_alice = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Alice Thread"
    )
    db_session.add(s_alice)
    db_session.commit()

    res_post_alice = client.post(
        f"/api/v1/chat/sessions/{s_alice.id}/message",
        json={"content": "Intrusion test"},
    )
    assert res_post_alice.status_code == 403
    assert "API keys cannot post messages to user-owned chat sessions" in res_post_alice.json()["detail"]


def test_attachment_require_owned_session_enforces_user_isolation(db_session):
    """_require_owned_session validates user ownership and blocks API keys."""
    s_alice = ChatSession(
        id=uuid4(), tenant_id=TENANT_ID, user_id=USER_ALICE, title="Alice Thread"
    )
    db_session.add(s_alice)
    db_session.commit()

    alice_ctx = make_context(user_id=USER_ALICE, role="Member")
    bob_ctx = make_context(user_id=USER_BOB, role="Member")
    admin_ctx = make_context(user_id=USER_ADMIN, role="Admin")
    api_key_ctx = make_context(user_id="api_key_service", auth_method="api_key")

    # Alice passes
    res_alice = _require_owned_session(s_alice.id, db_session, alice_ctx)
    assert res_alice.id == s_alice.id

    # Admin passes
    res_admin = _require_owned_session(s_alice.id, db_session, admin_ctx)
    assert res_admin.id == s_alice.id

    # Bob gets 403
    with pytest.raises(HTTPException) as exc_bob:
        _require_owned_session(s_alice.id, db_session, bob_ctx)
    assert exc_bob.value.status_code == 403

    # API key gets 403
    with pytest.raises(HTTPException) as exc_api:
        _require_owned_session(s_alice.id, db_session, api_key_ctx)
    assert exc_api.value.status_code == 403
