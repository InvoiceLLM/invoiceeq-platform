"""
Gap 184: programmatic API key issuance, hashing, rotation and token auth.

The properties these tests exist to hold, since this is credential handling:
  * the raw key is never persisted -- only a salted digest of it;
  * the raw key is returned by exactly one response (rotate) and never again;
  * rotating actually revokes the previous key, not just issues another one;
  * a key authenticates its own tenant only, via either accepted header;
  * rotation is Admin-only.
"""
import pytest
from uuid import uuid4
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import (
    get_db_session,
    MOCK_TENANT_ID,
    # Feature 25 (Gap 335): two-tier API key action scope.
    KEY_SCOPE_ACTIONS,
    KEY_SCOPE_READONLY,
    api_key_service_clerk_id,
    permissions_for_key_scope,
    resolve_api_key_context,
)
from models import RoleMapper, Tenant, User
from services.api_keys import (
    API_KEY_PREFIX,
    generate_api_key,
    generate_salt,
    hash_api_key,
    key_prefix,
    looks_like_api_key,
    verify_api_key,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

ROTATE_URL = "/api/v1/settings/security/api-key/rotate"
STATUS_URL = "/api/v1/settings/security/api-key"
VERIFY_URL = "/api/v1/settings/security/api-key/verify"


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


def _seed_tenant(db_session: Session, tenant_id=None, billing_plan: str = "pro") -> Tenant:
    tenant = Tenant(
        id=tenant_id or MOCK_TENANT_ID,
        name="Test Workspace",
        domain=f"test-{uuid4().hex[:8]}.example.com",
        billing_plan=billing_plan,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _issue_key_directly(db_session: Session, tenant: Tenant) -> str:
    """Issue a key for a tenant the mock-auth caller is NOT, for isolation tests."""
    raw = generate_api_key()
    salt = generate_salt()
    tenant.api_key_hash = hash_api_key(raw, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw)
    db_session.add(tenant)
    db_session.commit()
    return raw


# --- hashing primitives ----------------------------------------------------


def test_hash_is_not_the_raw_key_and_is_salted():
    raw = generate_api_key()
    salt_a, salt_b = generate_salt(), generate_salt()

    hash_a = hash_api_key(raw, salt_a)
    hash_b = hash_api_key(raw, salt_b)

    assert raw not in hash_a
    assert hash_a != raw
    # Same key, different salt -> different digest: a dump cannot be attacked
    # once and replayed across tenants.
    assert hash_a != hash_b
    # Deterministic under the same salt, or verification could never succeed.
    assert hash_a == hash_api_key(raw, salt_a)


def test_verify_accepts_only_the_matching_key():
    raw = generate_api_key()
    other = generate_api_key()
    salt = generate_salt()
    stored = hash_api_key(raw, salt)

    assert verify_api_key(raw, salt, stored) is True
    assert verify_api_key(other, salt, stored) is False
    assert verify_api_key(raw, generate_salt(), stored) is False


def test_verify_is_false_when_tenant_has_no_key():
    # "never issued a key" must answer exactly like "wrong key", not raise.
    assert verify_api_key(generate_api_key(), None, None) is False
    assert verify_api_key("", None, None) is False


def test_looks_like_api_key_separates_keys_from_clerk_jwts():
    assert looks_like_api_key(generate_api_key()) is True
    assert looks_like_api_key("eyJhbGciOiJSUzI1NiIsImtpZCI6ImFiYyJ9.eyJzdWIiOiJ4In0.sig") is False
    assert looks_like_api_key(None) is False


# --- issuance / status -----------------------------------------------------


def test_status_reports_no_key_before_first_rotation(db_session):
    _seed_tenant(db_session)
    response = client.get(STATUS_URL)
    assert response.status_code == 200
    data = response.json()
    assert data["has_key"] is False
    assert data["masked_key"] is None
    assert data["rotated_at"] is None
    # Mock auth resolves an Admin context, so the UI may offer the button.
    assert data["can_rotate"] is True


def test_rotate_issues_a_key_and_stores_only_its_hash(db_session):
    tenant = _seed_tenant(db_session)

    response = client.post(ROTATE_URL)
    assert response.status_code == 200
    data = response.json()

    raw_key = data["api_key"]
    assert raw_key.startswith(API_KEY_PREFIX)
    assert data["has_key"] is True
    assert data["key_prefix"] == raw_key[: len(API_KEY_PREFIX) + 6]
    assert data["rotated_at"] is not None

    db_session.refresh(tenant)
    assert tenant.api_key_hash is not None
    assert tenant.api_key_salt is not None
    # The raw key must not be recoverable from any stored column.
    assert tenant.api_key_hash != raw_key
    assert raw_key not in (tenant.api_key_hash or "")
    assert raw_key not in (tenant.api_key_salt or "")
    assert tenant.api_key_prefix != raw_key
    assert verify_api_key(raw_key, tenant.api_key_salt, tenant.api_key_hash) is True


def test_raw_key_is_returned_once_and_never_again(db_session):
    _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]

    status_response = client.get(STATUS_URL)
    assert status_response.status_code == 200
    # Not "no field named api_key" -- the raw value must not appear anywhere in
    # the payload, under any field name.
    assert raw_key not in status_response.text
    assert "api_key" not in status_response.json()
    assert status_response.json()["masked_key"].startswith(API_KEY_PREFIX)

    # And the masked form is genuinely not enough to reconstruct the key.
    assert raw_key not in status_response.json()["masked_key"]


# --- rotation revokes the previous key -------------------------------------


def test_rotation_invalidates_the_previous_key(db_session):
    _seed_tenant(db_session)

    first_key = client.post(ROTATE_URL).json()["api_key"]
    assert client.get(VERIFY_URL, headers={"X-API-Key": first_key}).status_code == 200

    second_key = client.post(ROTATE_URL).json()["api_key"]
    assert second_key != first_key

    # The old key is dead from the very next request.
    revoked = client.get(VERIFY_URL, headers={"X-API-Key": first_key})
    assert revoked.status_code == 401
    assert client.get(VERIFY_URL, headers={"X-API-Key": second_key}).status_code == 200


def test_rotation_clears_last_used_at(db_session):
    tenant = _seed_tenant(db_session)
    first_key = client.post(ROTATE_URL).json()["api_key"]
    client.get(VERIFY_URL, headers={"X-API-Key": first_key})
    db_session.refresh(tenant)
    assert tenant.api_key_last_used_at is not None

    client.post(ROTATE_URL)
    db_session.refresh(tenant)
    # A brand-new key has authenticated nothing yet.
    assert tenant.api_key_last_used_at is None


# --- token authentication --------------------------------------------------


def test_key_authenticates_via_both_accepted_headers(db_session):
    tenant = _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]

    via_x_header = client.get(VERIFY_URL, headers={"X-API-Key": raw_key})
    assert via_x_header.status_code == 200
    assert via_x_header.json()["tenant_id"] == str(tenant.id)

    via_bearer = client.get(VERIFY_URL, headers={"Authorization": f"Bearer {raw_key}"})
    assert via_bearer.status_code == 200
    assert via_bearer.json()["tenant_id"] == str(tenant.id)


def test_key_auth_never_resolves_to_a_privileged_role(db_session):
    """Feature 25 (Gap 335) rewrite of `test_key_auth_runs_as_viewer_with_no_permissions`.

    The old test asserted `role == "Viewer"` as a proxy for "this key has no
    permissions". That proxy stopped being accurate once scope existed: an
    `actions`-scoped key has can_audit/can_load and is STILL the same role,
    because scope is not a role. So role is now asserted for what it actually
    guarantees -- that a key never satisfies require_admin, at any scope -- and
    the permissions themselves are asserted directly, from the scope, in
    test_scope_derives_permissions below.

    No behaviour changed for any existing tenant: the default scope is
    `readonly`, which resolves to the same (False, False, False) the Viewer
    label produced before this gap.

    Gap 337 then retired the "Viewer" name itself; a key now reports
    `RoleMapper.NO_ROLE`, which is the honest answer -- no user-facing role was
    established for this request at all. Nothing is gated on this field.
    """
    _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]

    # Issuing a key must not hand an integration Admin/permission-gated access,
    # even though only an Admin can issue one.
    role = client.get(VERIFY_URL, headers={"X-API-Key": raw_key}).json()["role"]
    assert role == RoleMapper.NO_ROLE
    assert role not in RoleMapper.USER_FACING_ROLES


# --- Feature 25 (Gap 335): two-tier action scope ---------------------------


def test_api_key_scope_defaults_to_readonly(db_session):
    """Fail-closed. A tenant that has never made a choice must not have action powers."""
    tenant = _seed_tenant(db_session)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY


@pytest.mark.parametrize(
    "scope,expected",
    [
        # readonly reproduces exactly what the pre-Gap-335 hardcoded Viewer
        # produced -- this row is the regression guard on "nothing changed for
        # existing tenants".
        (KEY_SCOPE_READONLY, (False, False, False)),
        # actions grants the five financial actions' permissions -- and NOT
        # can_train. The founder's definition of full automation named
        # approve/reject/verify/send/mark-paid; training was not among them.
        (KEY_SCOPE_ACTIONS, (False, True, True)),
        # Anything unrecognised falls back to readonly, never to actions.
        (None, (False, False, False)),
        ("nonsense", (False, False, False)),
    ],
)
def test_scope_derives_permissions(scope, expected):
    assert permissions_for_key_scope(scope) == expected


def test_readonly_key_resolves_with_no_permissions_and_no_service_user(db_session):
    tenant = _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]

    context = resolve_api_key_context(raw_key, db_session)

    assert context.auth_method == "api_key"
    assert context.key_scope == KEY_SCOPE_READONLY
    assert (context.can_train, context.can_audit, context.can_load) == (False, False, False)
    # A readonly key can never reach a route that writes an AuditLog, so it
    # creates no service user -- db_user_id stays None exactly as before Gap 335.
    assert context.db_user_id is None
    assert (
        db_session.exec(
            select(User).where(User.clerk_user_id == api_key_service_clerk_id(tenant.id))
        ).first()
        is None
    )


def test_actions_key_resolves_with_action_permissions_and_a_service_user(db_session):
    tenant = _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]
    tenant.api_key_scope = KEY_SCOPE_ACTIONS
    db_session.add(tenant)
    db_session.commit()

    context = resolve_api_key_context(raw_key, db_session)

    assert context.key_scope == KEY_SCOPE_ACTIONS
    assert context.can_audit is True
    assert context.can_load is True
    # Training is deliberately excluded from `actions`.
    assert context.can_train is False
    # Scope is not a role: an actions key must still never satisfy require_admin.
    assert context.role == RoleMapper.NO_ROLE

    # The AuditLog actor problem: actor_user_id is a non-null FK to users.id, so
    # an actions key needs a real row to attribute its writes to.
    assert context.db_user_id is not None
    service_user = db_session.get(User, context.db_user_id)
    assert service_user is not None
    assert service_user.tenant_id == tenant.id
    # The row carries no authority of its own.
    assert (service_user.can_train, service_user.can_audit, service_user.can_load) == (
        False,
        False,
        False,
    )


def test_service_user_is_created_once_and_reused(db_session):
    tenant = _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]
    tenant.api_key_scope = KEY_SCOPE_ACTIONS
    db_session.add(tenant)
    db_session.commit()

    first = resolve_api_key_context(raw_key, db_session).db_user_id
    second = resolve_api_key_context(raw_key, db_session).db_user_id

    assert first == second
    rows = db_session.exec(
        select(User).where(User.clerk_user_id == api_key_service_clerk_id(tenant.id))
    ).all()
    assert len(rows) == 1


def test_clerk_context_reports_clerk_auth_method():
    """The other half of auth_method: a browser session must not look like a key."""
    data = client.get("/auth/me").json()
    assert data["auth_method"] == "clerk"
    assert data["key_scope"] is None


def test_key_auth_records_last_used(db_session):
    tenant = _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]
    db_session.refresh(tenant)
    assert tenant.api_key_last_used_at is None

    assert client.get(VERIFY_URL, headers={"X-API-Key": raw_key}).status_code == 200
    db_session.refresh(tenant)
    assert tenant.api_key_last_used_at is not None


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "inv_live_totally_wrong_value_here"},
        {"Authorization": "Bearer inv_live_totally_wrong_value_here"},
        {"Authorization": "Bearer not-even-our-prefix"},
        {"X-API-Key": ""},
    ],
)
def test_verify_rejects_missing_or_invalid_credentials(db_session, headers):
    _seed_tenant(db_session)
    client.post(ROTATE_URL)
    assert client.get(VERIFY_URL, headers=headers).status_code == 401


def test_key_resolves_only_its_own_tenant(db_session):
    _seed_tenant(db_session)                      # the mock-auth caller's tenant
    other = _seed_tenant(db_session, tenant_id=uuid4())
    other_key = _issue_key_directly(db_session, other)

    mine = client.post(ROTATE_URL).json()["api_key"]

    assert client.get(VERIFY_URL, headers={"X-API-Key": mine}).json()["tenant_id"] == str(MOCK_TENANT_ID)
    assert client.get(VERIFY_URL, headers={"X-API-Key": other_key}).json()["tenant_id"] == str(other.id)


def test_key_auth_blocks_unpaid_tenant(db_session):
    tenant = _seed_tenant(db_session)
    raw_key = client.post(ROTATE_URL).json()["api_key"]

    tenant.billing_plan = "unpaid"
    db_session.add(tenant)
    db_session.commit()

    # Same 402 gate the Clerk-session path enforces -- an integration is not a
    # way around a lapsed subscription.
    assert client.get(VERIFY_URL, headers={"X-API-Key": raw_key}).status_code == 402


# --- authorization on rotation ---------------------------------------------


def test_non_admin_cannot_rotate(db_session):
    _seed_tenant(db_session)
    response = client.post(ROTATE_URL, headers={"Authorization": "Bearer test_viewer"})
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_non_admin_status_reports_can_rotate_false(db_session):
    _seed_tenant(db_session)
    response = client.get(STATUS_URL, headers={"Authorization": "Bearer test_viewer"})
    assert response.status_code == 200
    assert response.json()["can_rotate"] is False


# --- Docs Hub source -------------------------------------------------------


def test_openapi_document_exposes_webhook_event_schemas():
    """Gap 184 part 3: the Docs Hub renders this document, so the outbound
    webhook payloads have to be in it, not only the inbound REST routes."""
    schema = client.get("/openapi.json").json()

    assert "webhooks" in schema
    for event in (
        "invoice.completed",
        "invoice.audit_required",
        "invoice.approved",
        "invoice.rejected",
        "outbound_invoice.sent",
        "outbound_invoice.overdue",
        "outbound_invoice.approved",
    ):
        assert event in schema["webhooks"], f"{event} missing from OpenAPI webhooks section"

    completed = schema["webhooks"]["invoice.completed"]["post"]
    assert "X-Webhook-Signature" in completed["description"]

    # The API-key endpoints themselves must be documented for an integrator.
    assert ROTATE_URL in schema["paths"]
    assert VERIFY_URL in schema["paths"]
