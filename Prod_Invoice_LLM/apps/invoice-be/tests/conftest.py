"""
Shared pytest configuration.

Gap 4: `settings.ALLOW_MOCK_AUTH` now defaults to False, so an unauthenticated
request is a 401. Almost the whole suite drives the API through TestClient
without an Authorization header (only test_auth.py and test_settings.py send one
at all), so the mock fallback has to be switched on for the suite to exercise
the endpoints it is actually testing.

This is set in os.environ rather than on the settings object because
`config.py` builds its `Settings` singleton at import time, and pytest imports
conftest.py before any test module (and therefore before `main`/`config`).
Real environment variables take precedence over `.env` values in
pydantic-settings, so this wins regardless of the developer's local `.env`.

Tests that need enforcement ON use the `mock_auth_disabled` fixture below.

Gap 359: `ENVIRONMENT` is set alongside it for the same reason. `config.py`
now refuses to import at all if `ALLOW_MOCK_AUTH=true` outside a recognized
non-production `ENVIRONMENT` -- without this, every test in the suite would
fail at collection, not just the ones this file is actually testing.
"""
import os

# Must happen before config/main are imported anywhere.
os.environ["ALLOW_MOCK_AUTH"] = "true"
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402


@pytest.fixture
def mock_auth_disabled(monkeypatch):
    """
    Turn off the mock-auth fallback for a single test, simulating production.

    `dependencies` does `from config import settings`, so it holds a reference
    to the same singleton -- patching the attribute is enough, and monkeypatch
    restores it afterwards.
    """
    import dependencies

    monkeypatch.setattr(dependencies.settings, "ALLOW_MOCK_AUTH", False)
    yield


@pytest.fixture
def clerk_jwt_configured(monkeypatch):
    """
    Pin both Clerk JWT settings to known non-empty values so tests that exercise
    real-token verification don't depend on the developer's local `.env`.
    """
    import dependencies

    monkeypatch.setattr(
        dependencies.settings, "CLERK_JWT_ISSUER", "https://example.clerk.accounts.dev"
    )
    monkeypatch.setattr(
        dependencies.settings,
        "CLERK_JWKS_URL",
        "https://example.clerk.accounts.dev/.well-known/jwks.json",
    )
    yield


@pytest.fixture
def clerk_jwt_unconfigured(monkeypatch):
    """Blank both Clerk JWT settings to exercise the fail-closed path."""
    import dependencies

    monkeypatch.setattr(dependencies.settings, "CLERK_JWT_ISSUER", "")
    monkeypatch.setattr(dependencies.settings, "CLERK_JWKS_URL", "")
    yield


@pytest.fixture(scope="session", autouse=True)
def use_ephemeral_chroma():
    """
    Gap 245: Force Chroma client to use EphemeralClient (in-memory) during tests
    to prevent orphan collections from accumulating on the live database.
    """
    import chroma_client
    import chromadb

    client = chromadb.EphemeralClient()
    chroma_client._chroma_client = client
    yield client

