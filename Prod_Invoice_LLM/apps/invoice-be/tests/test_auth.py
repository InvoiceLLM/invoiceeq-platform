from contextlib import contextmanager
from datetime import datetime
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
from models import Invoice, Tenant, TenantConnection, User

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
    still worked -- a Viewer creates a throwaway Clerk Organization (Clerk makes
    its creator org:admin), switches their active org to it, and every request
    that session carries `org_role=org:admin` while still resolving to their
    real tenant. Admin context, Admin permissions, on somebody else's workspace.
    """
    tenant, user = _seed_tenant_with_user(db_session, role="Viewer")

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
    # ...and still a Viewer, with none of the Admin-implied permissions.
    assert data["role"] == "Viewer"
    assert (data["can_train"], data["can_audit"], data["can_load"]) == (False, False, False)

    # The stored role was already protected before Checkpoint 3c; still is.
    db_session.refresh(user)
    assert user.role == "Viewer"


def test_unsafe_metadata_role_from_an_unmatched_org_does_not_elevate(
    fake_clerk_token, db_session
):
    """The same via the `role` claim (sourced from user-writable unsafe_metadata)."""
    tenant, _ = _seed_tenant_with_user(db_session, role="Viewer")

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
    assert response.json()["role"] == "Viewer"
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
    tenant, user = _seed_tenant_with_user(db_session, role="Viewer")

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
