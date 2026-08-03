"""Feature 1.1 (Granular RBAC) — Verification Plan coverage.

Covers the three claims in feature_1.1_rbac.md's Verification Plan:
  1. A non-permissioned user hitting Trainer / Audit / Ingestion-upload
     endpoints directly gets a real 403.
  2. An Admin can grant/revoke, and the effect is immediate on the next
     request (no re-login, because permissions come from the User row and not
     from the JWT).
  3. Dashboard / Chat / Help remain reachable regardless of permission state.

Test identity: conftest.py enables ALLOW_MOCK_AUTH suite-wide. A request with
no Authorization header resolves to the mock **Admin** (all three permissions
True via resolve_permissions). A `Bearer test_viewer` token resolves to role
"Viewer", whose permissions come off the User row — which defaults to all
False. That pair is what makes both sides of the gate testable without a real
Clerk token.
"""
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from dependencies import MOCK_USER_ID, resolve_permissions
from main import app
from models import User

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

VIEWER = {"Authorization": "Bearer test_viewer"}


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    from dependencies import get_db_session

    def get_db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def _viewer_row(db_session) -> User:
    """The User row the mock Viewer identity resolves to (provisioned on first call)."""
    client.get("/auth/me", headers=VIEWER)
    user = db_session.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).first()
    assert user is not None
    return user


def _grant(db_session, **flags) -> None:
    user = _viewer_row(db_session)
    for name, value in flags.items():
        setattr(user, name, value)
    db_session.add(user)
    db_session.commit()


# ---------------------------------------------------------------------------
# Task 1.1.3 — TenantContext carries the permissions; Admin implies all three
# ---------------------------------------------------------------------------

def test_resolve_permissions_admin_implies_all():
    """Admin is a role, not a 4th flag -- it grants all three regardless of the row."""
    user = User(
        email="a@example.com", role="Admin", clerk_user_id="user_admin",
        can_train=False, can_audit=False, can_load=False,
    )
    assert resolve_permissions("Admin", user) == (True, True, True)


def test_resolve_permissions_reads_the_user_row_for_non_admins():
    user = User(
        email="v@example.com", role="Viewer", clerk_user_id="user_v",
        can_train=True, can_audit=False, can_load=True,
    )
    assert resolve_permissions("Viewer", user) == (True, False, True)


def test_auth_me_exposes_permissions_for_admin():
    """GET /auth/me returns the 3 booleans -- this is the FE's only source for them."""
    data = client.get("/auth/me").json()
    assert data["can_train"] is True
    assert data["can_audit"] is True
    assert data["can_load"] is True


def test_auth_me_exposes_permissions_for_unpermissioned_user():
    """Default for a new non-Admin user: nothing beyond the 3 universal screens."""
    data = client.get("/auth/me", headers=VIEWER).json()
    assert data["role"] == "Viewer"
    assert data["can_train"] is False
    assert data["can_audit"] is False
    assert data["can_load"] is False


# ---------------------------------------------------------------------------
# Task 1.1.2 — a non-permissioned user gets a real 403
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/api/v1/trainer/vendors", {}),
        ("post", "/api/v1/trainer/sessions/global", {"json": {}}),
        ("get", "/api/v1/trainer/templates/history", {}),
    ],
)
def test_trainer_requires_can_train(method, path, kwargs):
    response = getattr(client, method)(path, headers=VIEWER, **kwargs)
    assert response.status_code == 403
    assert "ai trainer" in response.json()["detail"].lower()


def test_audit_requires_can_audit():
    response = client.put(
        f"/api/v1/audit/resolve/{uuid4()}",
        headers=VIEWER,
        json={"action": "approve"},
    )
    assert response.status_code == 403
    assert "audit queue" in response.json()["detail"].lower()


def test_outbound_audit_requires_can_audit():
    response = client.put(
        f"/api/v1/outbound-audit/resolve/{uuid4()}",
        headers=VIEWER,
        json={"action": "approve"},
    )
    assert response.status_code == 403


def test_invoice_upload_requires_can_load():
    response = client.post(
        "/api/v1/invoices/upload",
        headers=VIEWER,
        files={"files": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code == 403
    assert "ingestion" in response.json()["detail"].lower()


def test_watcher_start_requires_can_load():
    """The bulk directory ingest is /upload by another door -- same gate."""
    response = client.post(
        "/api/v1/invoices/watcher/start",
        headers=VIEWER,
        json={"directory_path": "/tmp/does-not-matter"},
    )
    assert response.status_code == 403


def test_outbound_upload_requires_can_load():
    response = client.post(
        "/api/v1/outbound-invoices/upload",
        headers=VIEWER,
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Dashboard / Chat / Help stay reachable regardless of permission state
# ---------------------------------------------------------------------------

def test_universal_surfaces_reachable_without_any_permission():
    """
    A user with all three permissions off is the design's "Viewer": they must
    still reach Dashboard, Chat and the invoice list. None of these may 403.
    """
    for method, path in [
        ("get", "/auth/me"),
        ("get", "/api/v1/dashboard/metrics"),
        ("get", "/api/v1/invoices"),
        ("get", "/api/v1/chat/sessions"),
    ]:
        response = getattr(client, method)(path, headers=VIEWER)
        assert response.status_code != 403, f"{path} 403'd for a permission-less user"


# ---------------------------------------------------------------------------
# Grant / revoke takes effect on the very next request
# ---------------------------------------------------------------------------

def test_grant_takes_effect_immediately(db_session):
    """No re-login required -- permissions are read per-request from the DB row."""
    assert client.get("/api/v1/trainer/vendors", headers=VIEWER).status_code == 403
    _grant(db_session, can_train=True)
    assert client.get("/api/v1/trainer/vendors", headers=VIEWER).status_code == 200


def test_revoke_takes_effect_immediately(db_session):
    _grant(db_session, can_train=True)
    assert client.get("/api/v1/trainer/vendors", headers=VIEWER).status_code == 200
    _grant(db_session, can_train=False)
    assert client.get("/api/v1/trainer/vendors", headers=VIEWER).status_code == 403


def test_permissions_are_independent(db_session):
    """Granting can_audit must not open the Trainer."""
    _grant(db_session, can_audit=True, can_train=False, can_load=False)
    assert client.get("/api/v1/trainer/vendors", headers=VIEWER).status_code == 403
    resolved = client.get("/auth/me", headers=VIEWER).json()
    assert resolved["can_audit"] is True
    assert resolved["can_train"] is False
    assert resolved["can_load"] is False


# ---------------------------------------------------------------------------
# Task 1.1.6 — Admin console permission-granting endpoints
# ---------------------------------------------------------------------------

def test_admin_users_list_is_admin_only():
    assert client.get("/api/v1/admin/users", headers=VIEWER).status_code == 403


def test_set_permissions_is_admin_only(db_session):
    user = _viewer_row(db_session)
    response = client.put(
        f"/api/v1/admin/users/{user.id}/permissions",
        headers=VIEWER,
        json={"can_train": True, "can_audit": True, "can_load": True},
    )
    assert response.status_code == 403


def test_admin_lists_tenant_users(db_session):
    _viewer_row(db_session)
    response = client.get("/api/v1/admin/users")
    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert "test@example.com" in emails
    assert all({"can_train", "can_audit", "can_load"} <= set(u) for u in response.json())


def test_admin_sets_permissions_by_backend_uuid(db_session):
    user = _viewer_row(db_session)
    response = client.put(
        f"/api/v1/admin/users/{user.id}/permissions",
        json={"can_train": True, "can_audit": False, "can_load": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["can_train"], body["can_audit"], body["can_load"]) == (True, False, True)
    # And it is the same row the request context resolves from.
    assert client.get("/api/v1/trainer/vendors", headers=VIEWER).status_code == 200


def test_admin_sets_permissions_by_clerk_user_id(db_session):
    _viewer_row(db_session)
    response = client.put(
        f"/api/v1/admin/users/{MOCK_USER_ID}/permissions",
        json={"can_train": False, "can_audit": True, "can_load": False},
    )
    assert response.status_code == 200
    assert response.json()["can_audit"] is True


def test_admin_pre_provisions_a_brand_new_clerk_user(db_session):
    """
    Create-time checkboxes must persist even though the new Clerk user has no
    `users` row yet -- get_tenant_context only writes one on their first API
    call, which happens after the Admin finishes the create flow.
    """
    response = client.put(
        "/api/v1/admin/users/user_freshly_created/permissions",
        json={
            "can_train": True, "can_audit": False, "can_load": True,
            "email": "new.hire@example.com", "first_name": "New", "last_name": "Hire",
        },
    )
    assert response.status_code == 200
    assert response.json()["role"] == "Viewer"
    stored = db_session.exec(
        select(User).where(User.clerk_user_id == "user_freshly_created")
    ).first()
    assert stored is not None
    assert (stored.can_train, stored.can_audit, stored.can_load) == (True, False, True)


def test_admin_permissions_unknown_user_is_404():
    response = client.put(
        f"/api/v1/admin/users/{uuid4()}/permissions",
        json={"can_train": True, "can_audit": True, "can_load": True},
    )
    assert response.status_code == 404


def test_admin_cannot_touch_another_tenants_user(db_session):
    """Cross-tenant writes must 404, not silently succeed or leak existence."""
    other = User(
        tenant_id=uuid4(),
        email="other-tenant@example.com",
        role="Viewer",
        clerk_user_id="user_other_tenant",
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    response = client.put(
        f"/api/v1/admin/users/{other.id}/permissions",
        json={"can_train": True, "can_audit": True, "can_load": True},
    )
    assert response.status_code == 404
