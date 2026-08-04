import pytest
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID, MOCK_USER_ID

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


def test_get_db_session():
    """Verify that get_db_session dependency correctly yields a session."""
    session_gen = get_db_session()
    db_session = next(session_gen)
    assert isinstance(db_session, Session)
    try:
        next(session_gen)
    except StopIteration:
        pass
