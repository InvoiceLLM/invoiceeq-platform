from contextlib import contextmanager
from datetime import datetime
import asyncio
import threading
from uuid import UUID, uuid4

import pytest
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import (
    AuthenticatedClerkIdentity,
    get_authenticated_clerk_identity,
    get_db_session,
    MOCK_TENANT_ID,
    MOCK_USER_ID,
)
from models import Invoice, RoleMapper, Tenant, TenantConnection, TenantEmailSender, User
from services.api_keys import (
    API_KEY_PREFIX,
    generate_api_key,
    generate_salt,
    hash_api_key,
    key_prefix,
    verify_api_key,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields clean isolated test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides dependencies database session."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_auth_me_fallback():
    """
    Mock fallback still works when ALLOW_MOCK_AUTH is enabled.

    Gap 4: this is now conditional behaviour -- conftest.py enables the flag for
    the suite. With it disabled this same request is a 401
    (see test_no_header_is_401_when_mock_auth_disabled).
    """
    response = client.get("/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == str(MOCK_TENANT_ID)
    assert data["user_id"] == MOCK_USER_ID
    assert data["role"] == "Admin"
    assert data["billing_plan"] == "active"

def test_auth_me_test_token():
    """Verify auth behavior with standard test token."""
    headers = {"Authorization": "Bearer test_token"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == str(MOCK_TENANT_ID)
    assert data["billing_plan"] == "active"

def test_auth_me_unpaid_is_allowed_through():
    """
    Gap 71 (deliberate behaviour change): /auth/me no longer 402s for an unpaid
    tenant.

    It previously did, which was harmless only because nothing ever *set*
    'unpaid'. Now that billing lapse really demotes tenants, /auth/me is the FE's
    identity source (hooks/useAuth.ts) -- 402ing it would leave the app unable to
    read its own billing_plan and therefore unable to explain why everything else
    is failing or to offer checkout. The 402 gate still applies to every other
    endpoint (see test_unpaid_tenant_is_402_on_a_normal_endpoint).
    """
    headers = {"Authorization": "Bearer test_unpaid_user"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["billing_plan"] == "unpaid"


def test_unpaid_tenant_is_402_on_a_normal_endpoint():
    """The 402 gate itself is unchanged -- it just moved off /auth/me."""
    headers = {"Authorization": "Bearer test_unpaid_user"}
    response = client.get("/api/v1/dashboard/metrics", headers=headers)
    assert response.status_code == 402
    assert "subscription is unpaid" in response.json()["detail"].lower()

def test_auth_me_custom_tenant_uuid():
    """Verify parsing of custom tenant UUIDs in test tokens."""
    custom_uuid = "12345678-1234-5678-1234-567812345678"
    headers = {"Authorization": f"Bearer test_{custom_uuid}"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == custom_uuid

# ---------------------------------------------------------------------------
# Gap 4 — auth enforcement
#
# The mock/test fallback is gated behind settings.ALLOW_MOCK_AUTH (default
# False). These cover both sides of that gate plus the fail-closed config path.
# ---------------------------------------------------------------------------

def test_no_header_is_401_when_mock_auth_disabled(mock_auth_disabled):
    """No Authorization header must be rejected, not downgraded to mock Admin."""
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert "authorization header" in response.json()["detail"].lower()
    # A 401 must advertise the scheme.
    assert response.headers.get("www-authenticate") == "Bearer"


def test_malformed_header_is_401_when_mock_auth_disabled(mock_auth_disabled):
    """A header that isn't 'Bearer <token>' takes the same rejection path."""
    response = client.get("/auth/me", headers={"Authorization": "Basic abc123"})
    assert response.status_code == 401


def test_test_token_is_401_when_mock_auth_disabled(mock_auth_disabled):
    """'Bearer test_*' must not be a backdoor once enforcement is on."""
    response = client.get("/auth/me", headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 401
    assert "test tokens are rejected" in response.json()["detail"].lower()


def test_test_token_with_admin_role_is_401_when_mock_auth_disabled(mock_auth_disabled):
    """The privileged variants are rejected too -- no role escalation via test_."""
    for token in ("test_admin", f"test_{MOCK_TENANT_ID}", "test_viewer"):
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, f"{token} was not rejected"


def test_invalid_jwt_is_401(clerk_jwt_configured):
    """A syntactically invalid token is rejected by JWT verification."""
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"}
    )
    assert response.status_code == 401
    assert "invalid token" in response.json()["detail"].lower()


def test_invalid_jwt_is_401_with_mock_auth_disabled(mock_auth_disabled, clerk_jwt_configured):
    """Same rejection with enforcement on -- no fallback to mock on bad tokens."""
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"}
    )
    assert response.status_code == 401


def test_missing_clerk_config_fails_closed(clerk_jwt_unconfigured):
    """
    Gap 4 fail-closed: with Clerk JWT config missing, a real-looking token must
    error rather than fall through to a mock context.

    ALLOW_MOCK_AUTH is enabled here (conftest default) precisely to prove the
    request is NOT silently downgraded -- incomplete config denies access.
    """
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer some.real.looking.token"}
    )
    assert response.status_code == 500
    detail = response.json()["detail"].lower()
    assert "misconfigured" in detail
    assert "clerk_jwks_url" in detail
    assert "clerk_jwt_issuer" in detail


def test_missing_issuer_alone_fails_closed(monkeypatch):
    """
    An empty issuer with a populated JWKS URL must also fail closed.

    This is the specific pre-Gap-4 hole: `verify_iss` was
    `bool(settings.CLERK_JWT_ISSUER)`, so a blank issuer disabled the check and
    a correctly signed token from ANY Clerk instance would have been accepted.
    """
    import dependencies

    monkeypatch.setattr(
        dependencies.settings,
        "CLERK_JWKS_URL",
        "https://example.clerk.accounts.dev/.well-known/jwks.json",
    )
    monkeypatch.setattr(dependencies.settings, "CLERK_JWT_ISSUER", "")

    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer some.real.looking.token"}
    )
    assert response.status_code == 500
    assert "clerk_jwt_issuer" in response.json()["detail"].lower()


def test_mock_auth_defaults_to_disabled():
    """
    The shipped default must be secure.

    Asserts the declared field default rather than an instantiated Settings,
    so the result doesn't depend on the developer's local `.env` (which is
    expected to set ALLOW_MOCK_AUTH=true) or on conftest's env var.
    """
    from config import Settings

    assert Settings.model_fields["ALLOW_MOCK_AUTH"].default is False


def test_mock_auth_refused_outside_non_production_environment():
    """
    Gap 359. Constructs real `Settings` instances (not the module-level
    singleton -- required fields like DATABASE_URL still come from the
    developer's real `.env`/env, only ALLOW_MOCK_AUTH/ENVIRONMENT are
    overridden) and calls the guard function directly, so this doesn't need
    to reload `config` -- the module already ran this exact check at import
    time, which is what makes the whole suite provable: if the guard were
    broken, collection itself would already have failed.
    """
    from config import Settings, _enforce_mock_auth_not_in_production

    with pytest.raises(RuntimeError, match="ALLOW_MOCK_AUTH=true"):
        _enforce_mock_auth_not_in_production(
            Settings(ALLOW_MOCK_AUTH=True, ENVIRONMENT="production")
        )

    # A recognized non-production environment must not raise.
    _enforce_mock_auth_not_in_production(
        Settings(ALLOW_MOCK_AUTH=True, ENVIRONMENT="dev")
    )

    # ALLOW_MOCK_AUTH=False must never raise regardless of ENVIRONMENT --
    # nothing is bypassed, there is nothing for this guard to refuse.
    _enforce_mock_auth_not_in_production(
        Settings(ALLOW_MOCK_AUTH=False, ENVIRONMENT="production")
    )


# ---------------------------------------------------------------------------
# Gap 133 — POST /auth/provision, and the removal of request-time tenant
# invention in get_tenant_context_allow_unpaid().
#
# This endpoint had zero test coverage before this gap, which is a large part of
# why three separate defects survived in it: a 500 on the second sign-up from a
# shared email domain, silent adoption (rename + takeover) of a populated
# tenant, and no authentication at all.
# ---------------------------------------------------------------------------

def _provision_body(**overrides) -> dict:
    body = {
        "clerk_org_id": f"org_{uuid4().hex[:12]}",
        "org_name": "Acme Ops",
        "admin_email": "admin@acme.com",
        "clerk_user_id": f"user_{uuid4().hex[:12]}",
    }
    body.update(overrides)
    return body


@contextmanager
def _as_caller(**identity_fields):
    """
    Simulate a verified Clerk token on POST /auth/provision.

    Overriding the identity dependency is how verified claims are simulated
    without minting a real RS256-signed token in-process. Checkpoint 3c widened
    what that dependency returns from a bare `sub` to sub + org_id + email,
    because the handler now binds the body to all three.
    """
    identity = AuthenticatedClerkIdentity(is_mock=False, **identity_fields)
    app.dependency_overrides[get_authenticated_clerk_identity] = lambda: identity
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_authenticated_clerk_identity, None)


def _token_for(body: dict, **overrides) -> dict:
    """The claims a legitimate caller's own token would carry for `body`."""
    claims = {
        "clerk_user_id": body["clerk_user_id"],
        "org_id": body["clerk_org_id"],
        "email": "real.admin@acme.com",
    }
    claims.update(overrides)
    return claims


def test_provision_creates_tenant_and_admin_user(db_session):
    """Baseline for the cases below: the happy path still provisions."""
    body = _provision_body()
    response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_new"] is True
    assert data["clerk_org_id"] == body["clerk_org_id"]

    tenant = db_session.exec(
        select(Tenant).where(Tenant.clerk_org_id == body["clerk_org_id"])
    ).first()
    assert tenant is not None
    assert tenant.domain == "acme.com"

    user = db_session.exec(
        select(User).where(User.clerk_user_id == body["clerk_user_id"])
    ).first()
    assert user is not None and user.tenant_id == tenant.id


def test_provision_is_idempotent_on_clerk_org_id():
    """A repeated call for the same org returns the same tenant, is_new False."""
    body = _provision_body()
    first = client.post("/auth/provision", json=body)
    second = client.post("/auth/provision", json=body)

    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["is_new"] is False
    assert second.json()["tenant_id"] == first.json()["tenant_id"]


def test_second_signup_on_claimed_domain_gets_its_own_tenant(db_session):
    """
    Gap 133 (the 500): `Tenant.domain` is unique, so the second organisation
    signing up from the same email domain used to raise IntegrityError straight
    out of the handler -- a bare 500, with the Clerk user already created and no
    tenant anywhere. It must now succeed with a *distinct* tenant: two unrelated
    companies (or two teams on gmail.com) must not be merged into one workspace
    just because their email domains match.
    """
    first_body = _provision_body(org_name="First Org", admin_email="a@shared.com")
    first = client.post("/auth/provision", json=first_body)
    assert first.status_code == 200, first.text

    second_body = _provision_body(org_name="Second Org", admin_email="b@shared.com")
    second = client.post("/auth/provision", json=second_body)

    assert second.status_code == 200, second.text
    assert second.json()["is_new"] is True
    assert second.json()["tenant_id"] != first.json()["tenant_id"]
    assert second.json()["org_name"] == "Second Org"

    # The first tenant keeps its name and its org id -- it was not adopted.
    first_tenant = db_session.get(Tenant, UUID(first.json()["tenant_id"]))
    assert first_tenant.name == "First Org"
    assert first_tenant.clerk_org_id == first_body["clerk_org_id"]

    # The disambiguated domain is derived from the org id, so it is unique and
    # obviously synthetic (.invalid is reserved by RFC 2606).
    second_tenant = db_session.get(Tenant, UUID(second.json()["tenant_id"]))
    assert second_tenant.domain == f"org-{second_body['clerk_org_id']}.invalid"


def test_provision_does_not_adopt_a_domain_tenant_that_has_users(db_session):
    """
    Gap 133 (the takeover): the adoption branch only checked for a missing
    clerk_org_id. A tenant created by the old request-time auto-provision path
    has no clerk_org_id but does have real users and real invoices -- and
    adopting it renamed somebody else's workspace and pointed a stranger's org
    at their data.
    """
    victim = Tenant(id=uuid4(), name="Existing Workspace", domain="victim.com", clerk_org_id=None)
    db_session.add(victim)
    db_session.commit()
    db_session.add(
        User(id=uuid4(), tenant_id=victim.id, email="real@victim.com", clerk_user_id="user_real", role="Admin")
    )
    db_session.commit()

    body = _provision_body(org_name="Attacker Org", admin_email="attacker@victim.com")
    response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] != str(victim.id)

    db_session.refresh(victim)
    assert victim.name == "Existing Workspace"
    assert victim.clerk_org_id is None


def test_provision_still_adopts_an_empty_orgless_domain_tenant(db_session):
    """
    The legitimate half of the same branch is preserved: a tenant with no
    clerk_org_id AND no users is genuinely unclaimed (the pre-Clerk-Organizations
    case the branch was written for), so linking it is still correct.
    """
    orphan = Tenant(id=uuid4(), name="Legacy Placeholder", domain="legacy.com", clerk_org_id=None)
    db_session.add(orphan)
    db_session.commit()

    body = _provision_body(org_name="Legacy Co", admin_email="admin@legacy.com")
    response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == str(orphan.id)
    assert response.json()["is_new"] is False

    db_session.refresh(orphan)
    assert orphan.clerk_org_id == body["clerk_org_id"]
    assert orphan.name == "Legacy Co"


def test_provision_is_rejected_when_unauthenticated(mock_auth_disabled, db_session):
    """
    Gap 133 (the auth hole): this endpoint took no auth dependency at all.
    Reproduced live in Checkpoint 3a -- an anonymous caller could POST any
    clerk_org_id/org_name and claim or rename a tenant.
    """
    body = _provision_body()
    response = client.post("/auth/provision", json=body)

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert db_session.exec(select(Tenant)).first() is None


def test_provision_rejects_a_token_for_a_different_user(db_session):
    """The token must belong to the user being provisioned."""
    body = _provision_body(clerk_user_id="user_victim")
    # org_id deliberately matches, so this isolates the `sub` check.
    with _as_caller(**_token_for(body, clerk_user_id="user_somebody_else")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 403
    assert "does not match" in response.json()["detail"]
    assert db_session.exec(select(Tenant)).first() is None


def test_provision_accepts_a_token_for_the_same_user():
    """The matching-subject case still provisions, i.e. the check is not blanket."""
    body = _provision_body()
    with _as_caller(**_token_for(body)):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["is_new"] is True


# ---------------------------------------------------------------------------
# Gap 133 — Checkpoint 3c.
#
# Checkpoint 3b authenticated *who* was calling POST /auth/provision but never
# checked *what org or email they were entitled to claim*, and the role used for
# a request was still read straight off the token. These are the five holes the
# security review found in that implementation.
# ---------------------------------------------------------------------------

def test_provision_rejects_an_org_id_the_token_does_not_claim(db_session):
    """
    Finding 1: `clerk_org_id` came entirely from the request body. Any
    authenticated user could POST an arbitrary org id -- e.g. one belonging to
    an organisation that had not been provisioned yet -- and claim it as their
    own tenant. It must match the caller's own active-organisation claim.
    """
    body = _provision_body(clerk_org_id="org_belonging_to_someone_else")
    with _as_caller(**_token_for(body, org_id="org_my_own_throwaway")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 403
    assert "active organisation does not match" in response.json()["detail"]
    assert db_session.exec(select(Tenant)).first() is None
    assert db_session.exec(select(User)).first() is None


def test_provision_rejects_a_caller_with_no_active_org(db_session):
    """A token carrying no `org_id` at all cannot claim an org id either."""
    body = _provision_body()
    with _as_caller(**_token_for(body, org_id=None)):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 403
    assert db_session.exec(select(Tenant)).first() is None


def test_provision_does_not_leak_another_tenants_details(db_session):
    """
    Finding 3: the idempotent early return echoed back the existing tenant's
    UUID, name, billing plan and remaining free quota for whatever
    `clerk_org_id` the caller supplied -- a cross-tenant read for anyone who
    could guess or observe an org id. With the org bound to the token there is
    no request that reaches that branch for somebody else's org.
    """
    victim = Tenant(
        id=uuid4(),
        name="Victim Holdings",
        domain="victimco.com",
        clerk_org_id="org_victim",
        billing_plan="pro_combined",
        free_invoices_remaining=7,
    )
    db_session.add(victim)
    db_session.commit()

    body = _provision_body(clerk_org_id="org_victim")
    with _as_caller(**_token_for(body, org_id="org_attacker")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 403
    payload = response.text
    for leaked in (str(victim.id), "Victim Holdings", "pro_combined", "victimco.com"):
        assert leaked not in payload, f"{leaked!r} leaked in the 403 body"

    db_session.refresh(victim)
    assert victim.name == "Victim Holdings"


def test_provision_ignores_an_attacker_supplied_admin_email(db_session):
    """
    Finding 3 (email half): `admin_email` was caller-controlled and `User.email`
    is globally unique, so an attacker could provision with a stranger's real
    address -- squatting it, and turning the real owner's later sign-up into an
    unhandled IntegrityError. The address must come from the caller's own
    verified `email` claim.
    """
    body = _provision_body(admin_email="ceo@bigcorp.com")
    with _as_caller(**_token_for(body, email="attacker@throwaway.test")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text

    created = db_session.exec(
        select(User).where(User.clerk_user_id == body["clerk_user_id"])
    ).first()
    assert created is not None
    assert created.email == "attacker@throwaway.test"
    # The victim's address was never written, so it is still available to them.
    assert db_session.exec(select(User).where(User.email == "ceo@bigcorp.com")).first() is None
    # And the tenant's domain follows the token's address, not the body's.
    tenant = db_session.get(Tenant, UUID(response.json()["tenant_id"]))
    assert tenant.domain == "throwaway.test"


def test_provision_with_no_email_claim_uses_the_synthetic_placeholder(db_session):
    """
    A Clerk JWT Template that omits `email` must not fall back to the body's
    address either -- it gets the same `user_<id>@domain.com` placeholder
    dependencies.py uses, and (Checkpoint 3c) the domain-adoption lookup is
    skipped entirely for it, since every such caller shares the literal domain
    "domain.com" and matching on it is what merged unrelated sign-ups originally.
    """
    decoy = Tenant(id=uuid4(), name="Decoy", domain="domain.com", clerk_org_id=None)
    db_session.add(decoy)
    db_session.commit()

    body = _provision_body(admin_email="ceo@bigcorp.com")
    with _as_caller(**_token_for(body, email=None)):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] != str(decoy.id)

    created = db_session.exec(
        select(User).where(User.clerk_user_id == body["clerk_user_id"])
    ).first()
    assert created.email == f"{body['clerk_user_id']}@domain.com"

    db_session.refresh(decoy)
    assert decoy.clerk_org_id is None and decoy.name == "Decoy"


@pytest.mark.parametrize(
    "make_data_bearing",
    [
        pytest.param(
            lambda s, t: setattr(t, "billing_plan", "pro_combined"),
            id="non_default_billing_plan",
        ),
        pytest.param(
            lambda s, t: setattr(t, "payu_customer_id", "cust_123"),
            id="payu_customer_id",
        ),
        pytest.param(
            lambda s, t: s.add(
                TenantConnection(
                    id=uuid4(),
                    tenant_id=t.id,
                    provider="google_drive",
                    encrypted_access_token="x",
                    token_expiry=datetime.utcnow(),
                )
            ),
            id="tenant_connection",
        ),
        pytest.param(
            lambda s, t: s.add(
                Invoice(id=uuid4(), tenant_id=t.id, file_path="blob://legacy.pdf")
            ),
            id="invoice",
        ),
    ],
)
def test_provision_refuses_to_adopt_a_userless_tenant_that_holds_data(
    db_session, make_data_bearing
):
    """
    Finding 4: adoption only required "no clerk_org_id and no User rows", but a
    user-less tenant can still hold a paid plan, a PayU customer id, live OAuth
    connections and invoices (a legacy pre-Clerk-org tenant whose users were
    never created or were deleted). Adopting it handed all of that to whoever
    signed up next from the same email domain.
    """
    legacy = Tenant(id=uuid4(), name="Legacy Holdings", domain="legacy.com", clerk_org_id=None)
    db_session.add(legacy)
    db_session.commit()
    make_data_bearing(db_session, legacy)
    db_session.add(legacy)
    db_session.commit()

    body = _provision_body(org_name="Squatter Ltd")
    with _as_caller(**_token_for(body, email="squatter@legacy.com")):
        response = client.post("/auth/provision", json=body)

    # Safe failure mode: a fresh isolated tenant, exactly as for "has users".
    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] != str(legacy.id)

    db_session.refresh(legacy)
    assert legacy.name == "Legacy Holdings"
    assert legacy.clerk_org_id is None


def test_provision_still_adopts_a_genuinely_empty_domain_tenant(db_session):
    """The legitimate half of the branch survives the tightened check."""
    orphan = Tenant(id=uuid4(), name="Legacy Placeholder", domain="empty.com", clerk_org_id=None)
    db_session.add(orphan)
    db_session.commit()

    body = _provision_body(org_name="Empty Co")
    with _as_caller(**_token_for(body, email="admin@empty.com")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == str(orphan.id)
    assert response.json()["is_new"] is False


def test_provision_409_does_not_leak_raw_db_constraint_text(db_session):
    """
    Finding 5: the unresolvable-collision 409 interpolated `e.orig` -- the raw
    driver exception -- straight into the response body, which on Postgres
    names the table, the constraint and the colliding value.

    Both domains this handler can try are pre-taken here (the real one, and the
    `org-<clerk_org_id>.invalid` fallback), and no tenant holds the org id, so
    the handler reaches that 409 branch.
    """
    body = _provision_body(org_name="Unlucky Co")

    blocker = Tenant(id=uuid4(), name="Domain Holder", domain="taken.com", clerk_org_id=None)
    db_session.add(blocker)
    db_session.commit()
    # Give it a user so it is not adoptable -- otherwise the request never gets
    # as far as an INSERT.
    db_session.add(
        User(id=uuid4(), tenant_id=blocker.id, email="held@taken.com",
             clerk_user_id="user_holder", role="Admin")
    )
    db_session.add(
        Tenant(
            id=uuid4(),
            name="Fallback Domain Holder",
            domain=f"org-{body['clerk_org_id']}.invalid",
            clerk_org_id=None,
        )
    )
    db_session.commit()

    with _as_caller(**_token_for(body, email="admin@taken.com")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert body["clerk_org_id"] in detail          # the caller's own org id is fine
    for leaked in ("UNIQUE", "unique", "constraint", "INSERT", "sqlite", "psycopg", "tenant.domain"):
        assert leaked not in detail, f"{leaked!r} leaked in the 409 body"


def test_provision_survives_an_admin_user_insert_conflict(db_session):
    """
    Finding 3 (defence in depth): the admin `User` INSERT is IntegrityError-
    guarded, so a conflict on the globally-unique email is a handled 409 with
    the session rolled back -- never a bare 500.

    Seeding the victim row directly is the only way to reach this now that the
    address is bound to the token; before Checkpoint 3c an attacker could reach
    it on demand by putting the victim's address in the body.
    """
    db_session.add(
        Tenant(id=uuid4(), name="Squatted", domain="squat.com", clerk_org_id="org_squatter")
    )
    db_session.commit()
    db_session.add(
        User(
            id=uuid4(),
            tenant_id=db_session.exec(select(Tenant)).first().id,
            email="owner@realco.com",
            clerk_user_id="user_squatter",
            role="Admin",
        )
    )
    db_session.commit()

    body = _provision_body(org_name="Real Co")
    with _as_caller(**_token_for(body, email="owner@realco.com")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 409, response.text
    assert "already in use" in response.json()["detail"]
    assert "IntegrityError" not in response.text


# --- the request-time fallback that Gap 133 removed --------------------------

@pytest.fixture
def fake_clerk_token(monkeypatch):
    """
    Drive the real-JWT branch of get_tenant_context_allow_unpaid() without a
    signed token: patch verify_clerk_jwt to return whatever claims the test
    wants. Anything not starting with 'test_' takes that branch.
    """
    import dependencies

    def _install(claims: dict) -> dict:
        monkeypatch.setattr(dependencies, "verify_clerk_jwt", lambda token: claims)
        return {"Authorization": "Bearer real.looking.token"}

    return _install


def test_unmatched_org_with_placeholder_email_is_409_not_a_shared_tenant(
    fake_clerk_token, db_session
):
    """
    Gap 133, the core defect: a token whose org_id matches no tenant, carrying no
    real `email` claim, used to fall through to the email-domain fallback. The
    synthetic address is always `user_<id>@domain.com`, so every such user
    matched the literal domain "domain.com" and they were all merged into one
    generic "Domain Workspace" tenant that had nothing to do with any of them
    (confirmed live on the dev database: 2 of 3 users).

    There is no fallback any more -- an unprovisioned account is refused.
    """
    headers = fake_clerk_token(
        {"sub": "user_never_provisioned", "org_id": "org_no_such_tenant", "org_role": "org:admin"}
    )
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "not linked to a provisioned organisation" in detail
    assert "org_no_such_tenant" in detail
    # Nothing was invented on the way out.
    assert db_session.exec(select(Tenant)).first() is None
    assert db_session.exec(select(User)).first() is None


def test_two_unprovisioned_users_are_not_merged(fake_clerk_token, db_session):
    """The specific live symptom: two unrelated sign-ups, one shared tenant."""
    headers_a = fake_clerk_token({"sub": "user_aaa", "org_id": "org_aaa"})
    assert client.get("/auth/me", headers=headers_a).status_code == 409

    headers_b = fake_clerk_token({"sub": "user_bbb", "org_id": "org_bbb"})
    assert client.get("/auth/me", headers=headers_b).status_code == 409

    assert db_session.exec(select(Tenant)).all() == []


def test_provisioned_org_still_resolves_and_returns_its_tenant_name(
    fake_clerk_token, db_session
):
    """
    The other side of the gate: an org that WAS provisioned resolves normally,
    and /auth/me now carries tenant_name so the FE can show the tenant the
    backend actually resolved rather than Clerk's unreconciled
    unsafeMetadata.orgName.
    """
    tenant = Tenant(id=uuid4(), name="Provisioned Co", domain="prov.com", clerk_org_id="org_prov")
    db_session.add(tenant)
    db_session.commit()

    headers = fake_clerk_token(
        {
            "sub": "user_prov_admin",
            "org_id": "org_prov",
            "org_role": "org:admin",
            "email": "admin@prov.com",
        }
    )
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["tenant_id"] == str(tenant.id)
    assert data["tenant_name"] == "Provisioned Co"
    assert data["role"] == "Admin"


# --- Checkpoint 3c, finding 2: role must be reconciled with org_matches ------


def _seed_tenant_with_user(db_session, *, role: str, clerk_org_id: str | None = "org_real"):
    tenant = Tenant(id=uuid4(), name="Real Co", domain="realco.test", clerk_org_id=clerk_org_id)
    db_session.add(tenant)
    db_session.commit()
    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="member@realco.test",
        clerk_user_id="user_member",
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    return tenant, user


def test_org_role_from_an_unmatched_org_does_not_elevate_the_context(
    fake_clerk_token, db_session
):
    """
    Finding 2, the escalation itself: Gap 173 computed `org_matches` but only
    used it to gate *persisting* `user.role`. The role handed to TenantContext
    still came straight off the token, so the attack it was written to stop
    still worked -- a permission-less user creates a throwaway Clerk Organization
    (Clerk makes its creator org:admin), switches their active org to it, and
    every request that session carries `org_role=org:admin` while still resolving
    to their real tenant. Admin context, Admin permissions, on somebody else's
    workspace.

    Gap 337: the seeded role is `RoleMapper.NO_ROLE`, the zero-permission
    fallback that replaced the retired "Viewer" name. Same permissions, and it is
    deliberately NOT one of the three assignable roles.
    """
    tenant, user = _seed_tenant_with_user(db_session, role=RoleMapper.NO_ROLE)

    headers = fake_clerk_token(
        {
            "sub": "user_member",
            "org_id": "org_throwaway_i_just_made",
            "org_role": "org:admin",
            "email": "member@realco.test",
        }
    )
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()
    # Still their real tenant...
    assert data["tenant_id"] == str(tenant.id)
    # ...and still permission-less, with none of the Admin-implied permissions.
    assert data["role"] == RoleMapper.NO_ROLE
    assert (data["can_train"], data["can_audit"], data["can_load"]) == (False, False, False)

    # The stored role was already protected before Checkpoint 3c; still is.
    db_session.refresh(user)
    assert user.role == RoleMapper.NO_ROLE


def test_unsafe_metadata_role_from_an_unmatched_org_does_not_elevate(
    fake_clerk_token, db_session
):
    """The same via the `role` claim (sourced from user-writable unsafe_metadata)."""
    tenant, _ = _seed_tenant_with_user(db_session, role=RoleMapper.NO_ROLE)

    headers = fake_clerk_token(
        {
            "sub": "user_member",
            "org_id": "org_throwaway",
            "role": "Trainer",
            "email": "member@realco.test",
        }
    )
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["role"] == RoleMapper.NO_ROLE
    assert response.json()["can_train"] is False


def test_unmatched_org_falls_back_to_the_persisted_role_not_a_clamp(
    fake_clerk_token, db_session
):
    """
    The fallback is the persisted role, not a blanket demotion: a real Admin
    whose session momentarily carries no org claim (the Gap 157 stale-cookie
    window) keeps their Admin context, because that role is our own data.
    """
    tenant, _ = _seed_tenant_with_user(db_session, role="Admin")

    headers = fake_clerk_token({"sub": "user_member", "email": "member@realco.test"})
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "Admin"
    assert (data["can_train"], data["can_audit"], data["can_load"]) == (True, True, True)


def test_matching_org_role_still_applies(fake_clerk_token, db_session):
    """
    The check is not a blanket distrust of `org_role`: when the token's org IS
    the org this tenant is tied to, Clerk's role still governs (and still syncs
    to the stored role, exactly as Gap 173 left it).
    """
    tenant, user = _seed_tenant_with_user(db_session, role=RoleMapper.NO_ROLE)

    headers = fake_clerk_token(
        {
            "sub": "user_member",
            "org_id": "org_real",
            "org_role": "org:admin",
            "email": "member@realco.test",
        }
    )
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "Admin"
    db_session.refresh(user)
    assert user.role == "Admin"


def test_get_db_session():
    """Verify that get_db_session dependency correctly yields a session."""
    session_gen = get_db_session()
    db_session = next(session_gen)
    assert isinstance(db_session, Session)
    try:
        next(session_gen)
    except StopIteration:
        pass


# ---------------------------------------------------------------------------
# BE Gap 133: Orphan Tenant Prevention Tests (2026-08-18)
# ---------------------------------------------------------------------------

def test_provision_rejects_user_already_in_another_workspace(db_session):
    """
    BE Gap 133: If a user already belongs to a workspace (existing_user.tenant_id
    is not None), a second provision attempt for a new organisation must be
    rejected with 409 BEFORE creating a new Tenant. No orphan tenant is created.
    """
    initial_tenant = Tenant(
        id=uuid4(),
        name="Existing Workspace",
        domain="first.com",
        clerk_org_id="org_first",
    )
    db_session.add(initial_tenant)
    db_session.commit()

    existing_user = User(
        id=uuid4(),
        tenant_id=initial_tenant.id,
        email="user@first.com",
        clerk_user_id="user_already_provisioned",
        role="Admin",
    )
    db_session.add(existing_user)
    db_session.commit()

    # User attempts to provision a second organization
    body = _provision_body(
        clerk_user_id="user_already_provisioned",
        clerk_org_id="org_second",
        org_name="Second Org",
        admin_email="user@second.com",
    )
    with _as_caller(**_token_for(body, email="user@second.com", clerk_user_id="user_already_provisioned", org_id="org_second")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 409
    assert "already provisioned to another workspace" in response.json()["detail"]

    # Verify no orphan Tenant was created in DB
    all_tenants = db_session.exec(select(Tenant)).all()
    assert len(all_tenants) == 1
    assert all_tenants[0].id == initial_tenant.id


def test_provision_rejects_email_conflict_before_creating_tenant(db_session):
    """
    BE Gap 133: If the admin email is already in use by a different user,
    provision must fail with 409 before committing a new Tenant row.
    """
    initial_tenant = Tenant(
        id=uuid4(),
        name="First Company",
        domain="firstco.com",
        clerk_org_id="org_firstco",
    )
    db_session.add(initial_tenant)
    db_session.commit()

    existing_user = User(
        id=uuid4(),
        tenant_id=initial_tenant.id,
        email="ceo@sharedcorp.com",
        clerk_user_id="user_first_ceo",
        role="Admin",
    )
    db_session.add(existing_user)
    db_session.commit()

    # Different user attempts to provision with the same email
    body = _provision_body(
        clerk_user_id="user_second_attacker",
        clerk_org_id="org_secondco",
        org_name="Second Co",
        admin_email="ceo@sharedcorp.com",
    )
    with _as_caller(**_token_for(body, email="ceo@sharedcorp.com", clerk_user_id="user_second_attacker", org_id="org_secondco")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 409
    assert "already in use" in response.json()["detail"]

    # Verify no second Tenant was created
    all_tenants = db_session.exec(select(Tenant)).all()
    assert len(all_tenants) == 1
    assert all_tenants[0].id == initial_tenant.id


def test_provision_allows_user_with_null_tenant_id(db_session):
    """
    If an existing user row has tenant_id=None (e.g. pre-created invited user),
    provisioning should succeed and attach the user to the newly created tenant.
    """
    unlinked_user = User(
        id=uuid4(),
        tenant_id=None,
        email="unlinked@freshco.com",
        clerk_user_id="user_unlinked",
        role="Admin",
    )
    db_session.add(unlinked_user)
    db_session.commit()

    body = _provision_body(
        clerk_user_id="user_unlinked",
        clerk_org_id="org_freshco",
        org_name="Fresh Co",
        admin_email="unlinked@freshco.com",
    )
    with _as_caller(**_token_for(body, email="unlinked@freshco.com", clerk_user_id="user_unlinked", org_id="org_freshco")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["is_new"] is True

    db_session.refresh(unlinked_user)
    assert unlinked_user.tenant_id is not None
    assert str(unlinked_user.tenant_id) == response.json()["tenant_id"]


# ---------------------------------------------------------------------------
# Gap 342 — provisioning finishes the job: a production API key and one
# authorized inbound email sender, so the `api` and `email` input channels the
# setup wizard offers are usable on day one.
#
# The case that actually matters here is the *double* provision. Keys are one
# per tenant by design, and issuing works by overwriting hash+salt+prefix -- so
# a second mint does not add a key, it revokes the first one. A Clerk webhook
# retry doing that silently is the bug these tests exist to prevent.
# ---------------------------------------------------------------------------

def test_provision_mints_a_production_api_key_for_a_new_tenant(db_session):
    body = _provision_body()
    with _as_caller(**_token_for(body)):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    raw_key = response.json()["api_key"]
    assert raw_key and raw_key.startswith(API_KEY_PREFIX)

    tenant = db_session.get(Tenant, UUID(response.json()["tenant_id"]))
    # Stored as a PBKDF2 digest under a per-key salt -- never the raw value.
    assert tenant.api_key_hash and tenant.api_key_hash != raw_key
    assert tenant.api_key_salt and tenant.api_key_salt != raw_key
    assert verify_api_key(raw_key, tenant.api_key_salt, tenant.api_key_hash) is True
    # Only the non-secret leading slice is kept for display.
    assert tenant.api_key_prefix and raw_key.startswith(tenant.api_key_prefix)
    assert tenant.api_key_rotated_at is not None
    assert tenant.api_key_last_used_at is None


def test_provisioned_key_is_readonly_scoped_not_actions(db_session):
    """Gap 335's fail-closed rule: signing up must never hand a machine the
    right to approve or send invoices. Widening is an explicit act through
    PUT /settings/workflow, never a side effect of provisioning."""
    body = _provision_body()
    with _as_caller(**_token_for(body)):
        response = client.post("/auth/provision", json=body)

    tenant = db_session.get(Tenant, UUID(response.json()["tenant_id"]))
    assert tenant.api_key_scope == "readonly"


def test_provision_seeds_the_admin_email_sender(db_session):
    """Without this row, routers/email_ingestion.py's webhook cannot resolve a
    tenant from the From address, so a new workspace's first forwarded invoice
    is dropped as an unregistered sender."""
    body = _provision_body()
    with _as_caller(**_token_for(body, email="Real.Admin@Acme.com")):
        response = client.post("/auth/provision", json=body)

    tenant_id = UUID(response.json()["tenant_id"])
    senders = db_session.exec(
        select(TenantEmailSender).where(TenantEmailSender.tenant_id == tenant_id)
    ).all()
    assert len(senders) == 1
    # Normalised exactly the way routers/email_ingestion.py::add_email_sender does.
    assert senders[0].email == "real.admin@acme.com"
    assert senders[0].email_set == "inbound"


def test_provision_seeds_no_sender_for_a_placeholder_email(db_session):
    """A JWT Template that omits `email` yields `{sub}@domain.com`, which is not
    a deliverable address -- and TenantEmailSender.email is *globally* unique, so
    seeding placeholders would collide across unrelated tenants."""
    body = _provision_body()
    with _as_caller(**_token_for(body, email=None)):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    tenant_id = UUID(response.json()["tenant_id"])
    assert db_session.exec(
        select(TenantEmailSender).where(TenantEmailSender.tenant_id == tenant_id)
    ).all() == []
    # The key is still minted -- the two additions are independent.
    assert response.json()["api_key"].startswith(API_KEY_PREFIX)


def test_second_provision_does_not_mint_a_second_key_or_sender(db_session):
    """The webhook-retry case. A repeat call must be a genuine no-op: the same
    key still works, and no duplicate sender row appears. A second mint would
    silently invalidate the first key -- discovered only as a 401 inside the
    tenant's integration."""
    body = _provision_body()
    with _as_caller(**_token_for(body)):
        first = client.post("/auth/provision", json=body)
    assert first.status_code == 200, first.text
    raw_key = first.json()["api_key"]

    tenant_id = UUID(first.json()["tenant_id"])
    tenant = db_session.get(Tenant, tenant_id)
    hash_before, salt_before, prefix_before = (
        tenant.api_key_hash, tenant.api_key_salt, tenant.api_key_prefix
    )

    with _as_caller(**_token_for(body)):
        second = client.post("/auth/provision", json=body)

    assert second.status_code == 200, second.text
    assert second.json()["is_new"] is False
    assert second.json()["tenant_id"] == first.json()["tenant_id"]
    # No new raw key was issued...
    assert second.json()["api_key"] is None

    db_session.expire_all()
    tenant = db_session.get(Tenant, tenant_id)
    # ...and the stored credential is byte-identical, so the first key still works.
    assert (tenant.api_key_hash, tenant.api_key_salt, tenant.api_key_prefix) == (
        hash_before, salt_before, prefix_before
    )
    assert verify_api_key(raw_key, tenant.api_key_salt, tenant.api_key_hash) is True

    assert len(db_session.exec(
        select(TenantEmailSender).where(TenantEmailSender.tenant_id == tenant_id)
    ).all()) == 1


def test_adopted_domain_tenant_gets_no_key_and_no_sender(db_session):
    """Recorded decision, not an oversight: the legacy domain-adoption branch
    returns is_new=False and is deliberately left alone. Such a tenant uses the
    existing rotate / add-sender endpoints."""
    orphan = Tenant(id=uuid4(), name="Legacy Placeholder", domain="legacy342.com", clerk_org_id=None)
    db_session.add(orphan)
    db_session.commit()

    body = _provision_body(org_name="Legacy Co", admin_email="admin@legacy342.com")
    response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == str(orphan.id)
    assert response.json()["api_key"] is None

    db_session.refresh(orphan)
    assert orphan.api_key_hash is None
    assert db_session.exec(
        select(TenantEmailSender).where(TenantEmailSender.tenant_id == orphan.id)
    ).all() == []


def test_provision_concurrency_locking(db_session):
    """
    Unit-level check: provision_tenant issues PostgreSQL advisory-lock statements
    when the bind reports postgresql. The DB execute path is mocked here — see
    test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres for the
    real-engine concurrency proof (BE Gap 133 sub-item 1).
    """
    from unittest.mock import patch, MagicMock
    from sqlalchemy.orm import Session as BaseSession
    from sqlalchemy.dialects.sqlite.base import SQLiteDialect

    # Mock db_session.execute to inspect advisory lock calls
    original_execute = BaseSession.execute
    execute_calls = []

    def mock_execute(self, statement, *args, **kwargs):
        stmt_str = str(statement)
        execute_calls.append(stmt_str)
        if "pg_advisory_xact_lock" in stmt_str:
            return MagicMock()
        return original_execute(self, statement, *args, **kwargs)

    # Set up normal provision request
    body = _provision_body(
        clerk_user_id="user_lock_test",
        clerk_org_id="org_lock_test",
        org_name="Lock Co",
        admin_email="admin@lockco.com",
    )
    
    # Patch SQLiteDialect name to report as postgresql during endpoint execution
    with patch.object(BaseSession, 'execute', new=mock_execute):
        with patch.object(SQLiteDialect, 'name', 'postgresql'):
            with _as_caller(**_token_for(body, email="admin@lockco.com", clerk_user_id="user_lock_test", org_id="org_lock_test")):
                response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    
    # Assert pg_advisory_xact_lock was called twice (once for org_key, once for domain_key)
    lock_statements = [stmt for stmt in execute_calls if "pg_advisory_xact_lock" in stmt]
    assert len(lock_statements) == 2, f"Executed statements: {execute_calls}"
    assert any("org_key" in stmt for stmt in lock_statements)
    assert any("domain_key" in stmt for stmt in lock_statements)


def test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres():
    """
    BE Gap 133 sub-item (1): two genuinely concurrent provision_tenant() calls
    for the same clerk_org_id against real Postgres must create exactly one
    tenant row and return the same tenant_id from both calls.

    BE Gap 342 extends the same run rather than duplicating the harness: the two
    things provisioning now *also* does must be equally singular. Exactly one
    API key must survive (a second mint overwrites hash+salt+prefix and would
    silently revoke the first) and exactly one TenantEmailSender row may exist.
    This is the assertion SQLite cannot make: the endpoint's idempotency rests on
    `pg_advisory_xact_lock`, a Postgres primitive that is a no-op elsewhere.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings
    from routers.auth import provision_tenant, TenantProvisionRequest

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()  # R2: a paused-but-listening
        # container accepts the TCP handshake and never answers; without a timeout
        # this blocks the whole suite forever instead of skipping.
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    unique_tag = uuid4().hex[:12]
    org_id = f"org_concurrent_{unique_tag}"
    user_id = f"user_concurrent_{unique_tag}"
    email = f"admin-{unique_tag}@gap133-{unique_tag}.invalid"

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)

    # Clear any leftover rows from a prior interrupted run targeting the same ids.
    with Session(pg_engine) as session:
        for user in session.exec(select(User).where(User.clerk_user_id == user_id)).all():
            session.delete(user)
        for sender in session.exec(
            select(TenantEmailSender).where(TenantEmailSender.email == email)
        ).all():
            session.delete(sender)
        for tenant in session.exec(select(Tenant).where(Tenant.clerk_org_id == org_id)).all():
            session.delete(tenant)
        session.commit()

    body = TenantProvisionRequest(
        clerk_org_id=org_id,
        org_name="Concurrency Test Org",
        admin_email=email,
        clerk_user_id=user_id,
    )
    caller = AuthenticatedClerkIdentity(
        is_mock=False,
        clerk_user_id=user_id,
        org_id=org_id,
        email=email,
    )

    barrier = threading.Barrier(2)
    results: list = []
    errors: list[BaseException] = []

    def _worker() -> None:
        barrier.wait()
        with Session(pg_engine) as session:
            try:
                results.append(asyncio.run(provision_tenant(body, caller, session)))
            except BaseException as exc:  # pragma: no cover - surfaced via assert
                errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "provision_tenant worker timed out"

    assert not errors, f"Unexpected errors: {errors}"
    assert len(results) == 2

    tenant_ids = {result.tenant_id for result in results}
    assert len(tenant_ids) == 1, f"Expected one tenant id across both calls, got {tenant_ids}"
    assert {result.is_new for result in results} == {True, False}

    # Gap 342: exactly one of the two calls may report a freshly minted key.
    raw_keys = [r.api_key for r in results if r.api_key]
    assert len(raw_keys) == 1, f"Expected one raw key across both calls, got {len(raw_keys)}"

    with Session(pg_engine) as session:
        tenants = session.exec(select(Tenant).where(Tenant.clerk_org_id == org_id)).all()
        users = session.exec(select(User).where(User.clerk_user_id == user_id)).all()
        senders = session.exec(
            select(TenantEmailSender).where(TenantEmailSender.tenant_id == tenants[0].id)
        ).all() if tenants else []
        try:
            assert len(tenants) == 1, f"Expected exactly one tenant row, found {len(tenants)}"
            assert len(users) == 1, f"Expected exactly one user row, found {len(users)}"
            assert str(tenants[0].id) == next(iter(tenant_ids))
            assert users[0].tenant_id == tenants[0].id
            # Gap 342: the surviving key is the one that was actually returned --
            # i.e. the losing thread did not overwrite the winner's credential.
            assert verify_api_key(
                raw_keys[0], tenants[0].api_key_salt, tenants[0].api_key_hash
            ) is True
            assert tenants[0].api_key_scope == "readonly"
            assert len(senders) == 1, f"Expected exactly one sender row, found {len(senders)}"
            assert senders[0].email == email.lower()
        finally:
            for sender in senders:
                session.delete(sender)
            for user in users:
                session.delete(user)
            session.flush()
            for tenant in tenants:
                session.delete(tenant)
            session.commit()


# ---------------------------------------------------------------------------
# Gap 344 — a tenant holding a live API key is not "unclaimed".
#
# Found in Feature 25's security review. _tenant_adoption_blockers() checked
# rows and plan state but never credentials, so a tenant that was empty by every
# one of those measures could still hold a minted key -- and adoption rewrites
# clerk_org_id and name while leaving api_key_hash/salt/prefix completely
# untouched. Whoever held the raw key would keep authenticating, unchanged,
# against what is now a different, real company's workspace.
# ---------------------------------------------------------------------------

def _mint_key_onto(tenant: Tenant) -> str:
    """Give `tenant` a real key exactly the way the two production writers do
    (routers/auth.py::_mint_provisioning_api_key and
    routers/settings.py::rotate_api_key) -- a real PBKDF2 digest under a real
    salt, not a stub string, so verify_api_key() below means something."""
    raw_key = generate_api_key()
    salt = generate_salt()
    tenant.api_key_hash = hash_api_key(raw_key, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw_key)
    tenant.api_key_rotated_at = datetime.utcnow()
    return raw_key


def test_provision_refuses_to_adopt_an_empty_tenant_that_holds_an_api_key(db_session):
    """
    The exact pre-fix failure scenario. This tenant satisfies *every* blocker
    condition that existed before Gap 344 -- no clerk_org_id, `free` plan, no
    PayU ids, no paid_through, no users, and not one row in any table in
    _TENANT_SCOPED_TABLES -- and was therefore adoptable. It holds a live key.
    """
    holder = Tenant(
        id=uuid4(),
        name="Key Holder Ltd",
        domain="keyholder.com",
        clerk_org_id=None,
        billing_plan="free",
    )
    raw_key = _mint_key_onto(holder)
    db_session.add(holder)
    db_session.commit()

    # Sanity: this row really is clean by every pre-Gap-344 measure, so the test
    # is exercising the new blocker and not passing for some incidental reason.
    assert holder.clerk_org_id is None
    assert holder.billing_plan == "free"
    assert (holder.payu_customer_id, holder.payu_subscription_id, holder.paid_through) == (
        None, None, None
    )
    assert db_session.exec(select(User).where(User.tenant_id == holder.id)).all() == []
    assert db_session.exec(select(Invoice).where(Invoice.tenant_id == holder.id)).all() == []

    body = _provision_body(org_name="Unrelated Real Company")
    with _as_caller(**_token_for(body, email="founder@keyholder.com")):
        response = client.post("/auth/provision", json=body)

    # Safe outcome: a fresh isolated tenant, same as every other blocker.
    assert response.status_code == 200, response.text
    new_tenant_id = response.json()["tenant_id"]
    assert new_tenant_id != str(holder.id)

    # The old workspace is untouched -- not renamed, not claimed.
    db_session.expire_all()
    holder = db_session.get(Tenant, holder.id)
    assert holder.name == "Key Holder Ltd"
    assert holder.clerk_org_id is None

    # And this is the part that mattered: the old key still resolves to the old
    # tenant only. Pre-fix, `holder` *was* the new company's workspace at this
    # point and this same raw key still opened it.
    assert verify_api_key(raw_key, holder.api_key_salt, holder.api_key_hash) is True
    new_tenant = db_session.get(Tenant, UUID(new_tenant_id))
    assert new_tenant.api_key_hash != holder.api_key_hash
    assert verify_api_key(raw_key, new_tenant.api_key_salt, new_tenant.api_key_hash) is False


@pytest.mark.parametrize(
    "column",
    ["api_key_hash", "api_key_salt", "api_key_prefix"],
)
def test_partially_written_key_material_also_blocks_adoption(db_session, column):
    """The blocker is OR across all three columns, not just the digest. A row
    half-written by a crash between the assignments in _mint_provisioning_api_key
    is a reason to be more suspicious of it, not less."""
    holder = Tenant(
        id=uuid4(),
        name="Partial Key Ltd",
        domain=f"partial-{column}.com",
        clerk_org_id=None,
        billing_plan="free",
    )
    setattr(holder, column, "inv_live_partial" if column != "api_key_salt" else "abc123")
    db_session.add(holder)
    db_session.commit()

    body = _provision_body(org_name="Unrelated Real Company")
    with _as_caller(**_token_for(body, email=f"founder@partial-{column}.com")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] != str(holder.id)

    db_session.expire_all()
    assert db_session.get(Tenant, holder.id).clerk_org_id is None


def test_new_tenant_creation_is_unaffected_by_the_key_blocker(db_session):
    """
    Gap 342 interaction check. Provisioning now mints a key for every new tenant,
    so the obvious worry is that the new blocker makes fresh tenants
    un-adoptable in a case that is supposed to work.

    It cannot: _mint_provisioning_api_key() runs only on the create-a-new-tenant
    branch, *after* the adoption-vs-create decision has already been made and
    after the adoption branch has returned. A tenant is never evaluated for
    adoption in the same request that mints its key. This asserts the normal
    signup path end to end, on a domain nothing else holds.
    """
    body = _provision_body(org_name="Brand New Co")
    with _as_caller(**_token_for(body, email="founder@brandnew344.com")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_new"] is True
    assert data["api_key"].startswith(API_KEY_PREFIX)

    tenant = db_session.get(Tenant, UUID(data["tenant_id"]))
    assert tenant.domain == "brandnew344.com"
    assert verify_api_key(data["api_key"], tenant.api_key_salt, tenant.api_key_hash) is True
    # The admin User row is still created -- the new blocker sits on the adoption
    # branch only and does not short-circuit the create path.
    assert db_session.exec(
        select(User).where(User.clerk_user_id == body["clerk_user_id"])
    ).first() is not None


def test_a_keyless_empty_domain_tenant_is_still_adoptable(db_session):
    """The legitimate half of the branch survives Gap 344 too: a legacy
    pre-Clerk-Organizations placeholder that never had a key minted is still
    adopted, so the fix is not a blanket disable of the adoption path."""
    orphan = Tenant(
        id=uuid4(),
        name="Legacy Placeholder",
        domain="keyless344.com",
        clerk_org_id=None,
        billing_plan="free",
    )
    db_session.add(orphan)
    db_session.commit()
    assert (orphan.api_key_hash, orphan.api_key_salt, orphan.api_key_prefix) == (
        None, None, None
    )

    body = _provision_body(org_name="Keyless Co")
    with _as_caller(**_token_for(body, email="admin@keyless344.com")):
        response = client.post("/auth/provision", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == str(orphan.id)
    assert response.json()["is_new"] is False


def test_api_key_blocks_adoption_on_postgres():
    """
    Gap 344 against real Postgres, following the same harness as
    test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres:
    provision_tenant() called directly with a real Postgres session, real
    NULL/NOT NULL column semantics, real unique constraints.

    This is an A/B on one run rather than a single assertion, because the claim
    being made is comparative -- "the key is what blocks it, and nothing else
    does". Two domain tenants are seeded identically (no clerk_org_id, `free`
    plan, no PayU state, no users, no tenant-scoped rows); one holds a live key
    and one does not. The keyless one must still be adopted (proving every other
    blocker genuinely passes for this row shape, so the keyed row was adoptable
    before this fix) and the keyed one must not be.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings
    from routers.auth import provision_tenant, TenantProvisionRequest

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()  # R2: a paused-but-listening
        # container accepts the TCP handshake and never answers; without a timeout
        # this blocks the whole suite forever instead of skipping.
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    tag = uuid4().hex[:12]
    keyed_domain = f"gap344-keyed-{tag}.invalid"
    keyless_domain = f"gap344-keyless-{tag}.invalid"

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)

    created_tenant_ids: list[UUID] = []

    def _call(domain: str):
        """One provision as an unrelated real signup from `domain`."""
        org_id = f"org_gap344_{uuid4().hex[:12]}"
        user_id = f"user_gap344_{uuid4().hex[:12]}"
        email = f"founder-{uuid4().hex[:8]}@{domain}"
        body = TenantProvisionRequest(
            clerk_org_id=org_id,
            org_name="Unrelated Real Company",
            admin_email=email,
            clerk_user_id=user_id,
        )
        caller = AuthenticatedClerkIdentity(
            is_mock=False, clerk_user_id=user_id, org_id=org_id, email=email,
        )
        with Session(pg_engine) as session:
            return asyncio.run(provision_tenant(body, caller, session))

    try:
        with Session(pg_engine) as session:
            keyed = Tenant(
                id=uuid4(), name="Key Holder Ltd", domain=keyed_domain,
                clerk_org_id=None, billing_plan="free",
            )
            raw_key = _mint_key_onto(keyed)
            keyless = Tenant(
                id=uuid4(), name="Legacy Placeholder", domain=keyless_domain,
                clerk_org_id=None, billing_plan="free",
            )
            session.add(keyed)
            session.add(keyless)
            session.commit()
            keyed_id, keyless_id = keyed.id, keyless.id
            created_tenant_ids += [keyed_id, keyless_id]

        # Control: identical row shape, no key -> still adopted. If this fails,
        # the keyed assertion below proves nothing.
        keyless_result = _call(keyless_domain)
        assert keyless_result.tenant_id == str(keyless_id), (
            "the keyless control was not adopted, so some other blocker fired "
            "and this run cannot attribute the keyed outcome to the key"
        )
        assert keyless_result.is_new is False

        # The fix: same shape, plus a key -> refused, fresh isolated tenant.
        keyed_result = _call(keyed_domain)
        assert keyed_result.tenant_id != str(keyed_id)
        assert keyed_result.is_new is True
        created_tenant_ids.append(UUID(keyed_result.tenant_id))

        with Session(pg_engine) as session:
            holder = session.get(Tenant, keyed_id)
            # Untouched: not renamed, not claimed, key still its own.
            assert holder.name == "Key Holder Ltd"
            assert holder.clerk_org_id is None
            assert verify_api_key(raw_key, holder.api_key_salt, holder.api_key_hash) is True
            # And the raw key does not open the new company's workspace.
            new_tenant = session.get(Tenant, UUID(keyed_result.tenant_id))
            assert verify_api_key(
                raw_key, new_tenant.api_key_salt, new_tenant.api_key_hash
            ) is False
    finally:
        with Session(pg_engine) as session:
            for tenant_id in created_tenant_ids:
                for sender in session.exec(
                    select(TenantEmailSender).where(TenantEmailSender.tenant_id == tenant_id)
                ).all():
                    session.delete(sender)
                for user in session.exec(
                    select(User).where(User.tenant_id == tenant_id)
                ).all():
                    session.delete(user)
            session.commit()
            for tenant_id in created_tenant_ids:
                tenant = session.get(Tenant, tenant_id)
                if tenant is not None:
                    session.delete(tenant)
            session.commit()



