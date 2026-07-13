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
    """Verify auth fallback when no authorization header is passed (local development fallback)."""
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

def test_auth_me_unpaid_payment_required():
    """Verify that a test_unpaid token blocks requests with a 402 error."""
    headers = {"Authorization": "Bearer test_unpaid_user"}
    response = client.get("/auth/me", headers=headers)
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

def test_get_db_session():
    """Verify that get_db_session dependency correctly yields a session."""
    session_gen = get_db_session()
    db_session = next(session_gen)
    assert isinstance(db_session, Session)
    try:
        next(session_gen)
    except StopIteration:
        pass
