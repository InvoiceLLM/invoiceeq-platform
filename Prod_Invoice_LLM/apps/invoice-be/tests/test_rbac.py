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
True via resolve_permissions). A `Bearer test_viewer` token resolves to
`RoleMapper.NO_ROLE`, whose permissions come off the User row — which defaults
to all False. That pair is what makes both sides of the gate testable without a
real Clerk token.

Gap 337 note: the role that token resolves to used to be the literal "Viewer".
"Viewer" is retired from the user-facing vocabulary (the three assignable roles
are Admin / Auditor / Trainer) and the zero-permission fallback now has its own
never-assignable name, `RoleMapper.NO_ROLE`. The *token spelling* `test_viewer`
is deliberately kept — it is fixture vocabulary used across the whole suite, and
churning it would touch six unrelated test files for no behavioural gain — but
every assertion on the resolved role now names NO_ROLE.
"""
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from dependencies import MOCK_USER_ID, resolve_permissions
from main import app
from models import RoleMapper, User

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
    """The User row the mock permission-less identity resolves to (provisioned on first call)."""
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
    """Admin is a role, not a per-permission flag -- it grants all four
    (can_send_invoices added by Gap 369) regardless of the row."""
    user = User(
        email="a@example.com", role="Admin", clerk_user_id="user_admin",
        can_train=False, can_audit=False, can_load=False, can_send_invoices=False,
    )
    assert resolve_permissions("Admin", user) == (True, True, True, True)


def test_resolve_permissions_reads_the_user_row_for_non_admins():
    user = User(
        email="v@example.com", role=RoleMapper.NO_ROLE, clerk_user_id="user_v",
        can_train=True, can_audit=False, can_load=True, can_send_invoices=True,
    )
    assert resolve_permissions(RoleMapper.NO_ROLE, user) == (True, False, True, True)


# --- Feature 25 (Gap 337): the retired "Viewer" name ------------------------


def test_user_facing_roles_are_admin_auditor_trainer():
    """The founder's role vocabulary, asserted so a fourth role cannot be
    reintroduced silently. NO_ROLE is deliberately NOT in this set: it is an
    internal fallback, never something an Admin can hand out."""
    assert RoleMapper.USER_FACING_ROLES == ("Admin", "Auditor", "Trainer")
    assert RoleMapper.NO_ROLE not in RoleMapper.USER_FACING_ROLES
    assert "Viewer" not in RoleMapper.USER_FACING_ROLES
    assert "Viewer" not in RoleMapper.ROLE_PERMISSION_DEFAULTS


@pytest.mark.parametrize(
    "raw_role",
    [None, "", "viewer", "Viewer", "member", "org:member", "some_unmapped_idp_role"],
)
def test_zero_permission_fallback_never_grants_anything(raw_role):
    """The point of Gap 337. The fallback slot must not be one of the three
    real roles -- if it were Trainer, every unknown IDP role string and every
    org-mismatched session would silently acquire can_train."""
    role = RoleMapper.normalize_role(raw_role)
    assert role != "Trainer"
    assert RoleMapper.resolve_permissions(role, None) == (False, False, False, False)


def test_legacy_viewer_rows_still_resolve_to_no_permissions():
    """A `users` row written before this gap's data migration (or by an
    un-migrated database) still carries the literal 'Viewer'. It must resolve to
    zero permissions via the unmapped-role fallback, not raise a KeyError."""
    assert RoleMapper.resolve_permissions("Viewer", None) == (False, False, False, False)


def test_auth_me_exposes_permissions_for_admin():
    """GET /auth/me returns the 4 booleans (can_send_invoices added by Gap
    369) -- this is the FE's only source for them."""
    data = client.get("/auth/me").json()
    assert data["can_train"] is True
    assert data["can_audit"] is True
    assert data["can_load"] is True
    assert data["can_send_invoices"] is True


def test_auth_me_exposes_permissions_for_unpermissioned_user():
    """Default for a new non-Admin user: nothing beyond the 3 universal screens."""
    data = client.get("/auth/me", headers=VIEWER).json()
    assert data["role"] == RoleMapper.NO_ROLE
    assert data["can_train"] is False
    assert data["can_audit"] is False
    assert data["can_load"] is False
    assert data["can_send_invoices"] is False


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
# Gap 369: can_send_invoices — a 4th, independent gate on outbound upload,
# layered on top of can_load rather than folded into it.
# ---------------------------------------------------------------------------

def test_outbound_upload_still_403s_with_can_load_but_no_send_invoices(db_session):
    """can_load alone must not be enough -- that would make the new permission
    a no-op for anyone who already has ingestion access. Asserts the exact
    require_permission() wording, not just "contains 'send invoices'" --
    the handler's own tenant-level send_invoices_enabled check (unrelated to
    this permission, checked further down in the function body) 403s with a
    *different* message ("...is not enabled for this tenant...") that would
    also match a looser substring check and mask this gate not actually firing."""
    _grant(db_session, can_load=True, can_send_invoices=False)
    response = client.post(
        "/api/v1/outbound-invoices/upload",
        headers=VIEWER,
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code == 403
    assert "ask an admin to grant it" in response.json()["detail"].lower()


def test_outbound_upload_succeeds_with_both_permissions_granted(db_session):
    """Both gates satisfied, AND the tenant's own send_invoices_enabled toggle
    (Feature 16 -- a separate, pre-existing check in the handler body, not a
    Depends) also on -- the upload itself may still fail past that for
    unrelated reasons (storage, billing quota), so this only asserts past the
    403s, matching how test_outbound_upload_requires_can_load only asserts
    the 403 side for its own case."""
    from dependencies import MOCK_TENANT_ID
    from models import Tenant

    _grant(db_session, can_load=True, can_send_invoices=True)
    tenant = db_session.get(Tenant, MOCK_TENANT_ID)
    tenant.send_invoices_enabled = True
    tenant.billing_plan = "pro_combined"
    db_session.add(tenant)
    db_session.commit()

    response = client.post(
        "/api/v1/outbound-invoices/upload",
        headers=VIEWER,
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Dashboard / Chat / Help stay reachable regardless of permission state
# ---------------------------------------------------------------------------

def test_universal_surfaces_reachable_without_any_permission():
    """
    A user with all three permissions off must still reach Dashboard, Chat and
    the invoice list. None of these may 403.
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
    assert all({"can_train", "can_audit", "can_load", "can_send_invoices"} <= set(u) for u in response.json())


def test_admin_sets_can_send_invoices(db_session):
    """Gap 369's 4th flag round-trips through the same endpoint the other
    three already use -- no separate admin endpoint was added."""
    user = _viewer_row(db_session)
    response = client.put(
        f"/api/v1/admin/users/{user.id}/permissions",
        json={"can_train": False, "can_audit": False, "can_load": False, "can_send_invoices": True},
    )
    assert response.status_code == 200
    assert response.json()["can_send_invoices"] is True

    stored = db_session.exec(select(User).where(User.id == user.id)).first()
    assert stored.can_send_invoices is True

    # Revoke it again -- confirms the field is genuinely read both ways, not
    # just accepted once and ignored on a second write.
    response = client.put(
        f"/api/v1/admin/users/{user.id}/permissions",
        json={"can_train": False, "can_audit": False, "can_load": False, "can_send_invoices": False},
    )
    assert response.status_code == 200
    assert response.json()["can_send_invoices"] is False


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
    # Gap 337: pre-provisioned rows get the zero-permission fallback, never one
    # of the three assignable roles.
    assert response.json()["role"] == RoleMapper.NO_ROLE
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
        role=RoleMapper.NO_ROLE,
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


# ---------------------------------------------------------------------------
# Feature 25 (Gap 335) — dual-credential auth + two-tier API key action scope
#
# These sit in this file rather than test_api_keys.py because what they assert
# is a PERMISSION GATE, and the guarantee that matters most is that Gap 335 did
# not weaken any of the human gates above while widening the routes to keys.
# ---------------------------------------------------------------------------

def _tenant_with_key(db_session, scope):
    """Give the mock tenant a real API key at `scope`, and return the raw key."""
    from dependencies import MOCK_TENANT_ID
    from models import Tenant
    from services.api_keys import generate_api_key, generate_salt, hash_api_key, key_prefix

    tenant = db_session.get(Tenant, MOCK_TENANT_ID)
    if tenant is None:
        tenant = Tenant(
            id=MOCK_TENANT_ID,
            name="Test Workspace",
            domain=f"rbac-{uuid4().hex[:8]}.example.com",
            billing_plan="pro",
        )
    raw = generate_api_key()
    salt = generate_salt()
    tenant.api_key_hash = hash_api_key(raw, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw)
    tenant.api_key_scope = scope
    db_session.add(tenant)
    db_session.commit()
    return raw


def test_readonly_key_is_refused_the_audit_resolve_action(db_session):
    """Strict Review: the key stays read/upload-only, a human finalizes."""
    from dependencies import KEY_SCOPE_READONLY

    raw = _tenant_with_key(db_session, KEY_SCOPE_READONLY)
    response = client.put(
        f"/api/v1/audit/resolve/{uuid4()}",
        headers={"X-API-Key": raw},
        json={"status": "PAID"},
    )
    assert response.status_code == 403
    # The message must tell an integrator what to change, not just say no.
    assert "read-only" in response.json()["detail"].lower()


def test_actions_key_passes_the_audit_gate(db_session):
    """Full Automation: the key gets to call approve/reject/verify/send/mark-paid.

    404 (not 403) is the pass condition -- the gate let it through and the
    handler then failed to find a random invoice id, which is exactly right.
    """
    from dependencies import KEY_SCOPE_ACTIONS

    raw = _tenant_with_key(db_session, KEY_SCOPE_ACTIONS)
    response = client.put(
        f"/api/v1/audit/resolve/{uuid4()}",
        headers={"X-API-Key": raw},
        json={"status": "PAID"},
    )
    assert response.status_code != 403
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["confirm-send", "mark-paid"])
def test_readonly_key_is_refused_outbound_finalization(db_session, path):
    from dependencies import KEY_SCOPE_READONLY

    raw = _tenant_with_key(db_session, KEY_SCOPE_READONLY)
    response = client.put(
        f"/api/v1/outbound-invoices/{uuid4()}/{path}",
        headers={"X-API-Key": raw},
        json={},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["confirm-send", "mark-paid"])
def test_outbound_finalization_now_requires_can_audit_for_humans(path):
    """Gap 335's incidental security fix.

    Before this, confirm-send and mark-paid depended on bare get_tenant_context
    with NO permission gate: any authenticated user -- including this
    permission-less user -- could mark a tenant's outbound invoice SENT or
    PAID, fire the outbound webhook and trigger the staff notification email.
    """
    response = client.put(
        f"/api/v1/outbound-invoices/{uuid4()}/{path}",
        headers=VIEWER,
        json={},
    )
    assert response.status_code == 403
    assert "audit queue" in response.json()["detail"].lower()


def test_readonly_key_can_still_upload_and_read(db_session):
    """Upload is ingestion, not one of the five actions -- Strict Review allows it."""
    from dependencies import KEY_SCOPE_READONLY

    raw = _tenant_with_key(db_session, KEY_SCOPE_READONLY)

    # Reads: reachable at readonly scope.
    assert client.get("/api/v1/invoices", headers={"X-API-Key": raw}).status_code == 200

    # Upload: must not 403 on the permission gate. can_load is False for a
    # readonly key, so this is the case require_permission_or_api_key exists for.
    response = client.post(
        "/api/v1/invoices/upload",
        headers={"X-API-Key": raw},
        files={"files": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code != 403


def test_dual_credential_routes_still_401_without_any_credential(mock_auth_disabled):
    """Widening to two credential types must not open a third, anonymous one."""
    for method, path in [
        ("get", "/api/v1/invoices"),
        ("get", "/api/v1/chat/sessions"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, f"{path} did not 401 unauthenticated"

    bad = client.get("/api/v1/invoices", headers={"X-API-Key": "inv_live_not_a_real_key"})
    assert bad.status_code == 401


def test_api_key_never_reaches_tenant_administration(db_session):
    """An actions key finishes invoices; it does not manage the workspace."""
    from dependencies import KEY_SCOPE_ACTIONS

    raw = _tenant_with_key(db_session, KEY_SCOPE_ACTIONS)
    # require_admin resolves through the Clerk-only dependency, so an
    # `inv_live_` bearer is not a verifiable JWT -> 401. Either way it must not
    # be 200.
    response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code in (401, 403)


def test_service_user_is_hidden_from_the_admin_user_list(db_session):
    """It satisfies an FK; it is not a person and must not look like one."""
    from dependencies import KEY_SCOPE_ACTIONS, resolve_api_key_context

    _viewer_row(db_session)
    raw = _tenant_with_key(db_session, KEY_SCOPE_ACTIONS)
    context = resolve_api_key_context(raw, db_session)
    assert context.db_user_id is not None  # the row really was created

    listed = client.get("/api/v1/admin/users").json()
    assert all("api-key-service" not in u["email"] for u in listed), listed
