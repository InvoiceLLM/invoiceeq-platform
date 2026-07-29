"""Tests for Feature 15 (Outbound Webhooks): CRUD endpoints
(routers/webhooks.py), SSRF validation, HMAC signing, retry/backoff, and
auto-disable (services/webhooks.py)."""
import json
from unittest.mock import patch, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant, WebhookSubscription
from services.webhooks import (
    validate_webhook_target_url,
    InvalidWebhookUrlError,
    dispatch_webhook_event,
    _sign_payload,
    MAX_CONSECUTIVE_FAILURES,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

client = TestClient(app)


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


def _seed_tenant(db_session) -> Tenant:
    tenant = Tenant(id=MOCK_TENANT_ID, name="Test Workspace", domain="test.example.com")
    db_session.add(tenant)
    db_session.commit()
    return tenant


# ── SSRF validation ───────────────────────────────────────────────────────────

def test_validate_target_url_rejects_loopback():
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_target_url("http://127.0.0.1:8000/hook")


def test_validate_target_url_rejects_private_ip():
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_target_url("http://10.0.0.5/hook")


def test_validate_target_url_rejects_link_local():
    # 169.254.169.254 is the cloud-provider metadata endpoint -- the classic SSRF target.
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_target_url("http://169.254.169.254/hook")


def test_validate_target_url_rejects_bad_scheme():
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_target_url("ftp://example.com/hook")


def test_validate_target_url_accepts_public_host():
    with patch("services.webhooks.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
        validate_webhook_target_url("https://example.com/hook")  # must not raise


# ── CRUD endpoints ────────────────────────────────────────────────────────────

def test_create_webhook_rejects_private_target(db_session):
    _seed_tenant(db_session)
    response = client.post("/api/v1/webhooks", json={"target_url": "http://127.0.0.1/hook", "subscribed_events": ["invoice.completed"]})
    assert response.status_code == 400


def test_create_webhook_rejects_unknown_event_type(db_session):
    _seed_tenant(db_session)
    with patch("services.webhooks.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
        response = client.post("/api/v1/webhooks", json={"target_url": "https://example.com/hook", "subscribed_events": ["not.a.real.event"]})
    assert response.status_code == 400


def test_create_webhook_returns_secret_once(db_session):
    _seed_tenant(db_session)
    with patch("services.webhooks.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
        response = client.post("/api/v1/webhooks", json={"target_url": "https://example.com/hook", "subscribed_events": ["invoice.completed"]})
    assert response.status_code == 201
    data = response.json()
    assert "secret" in data and len(data["secret"]) > 0

    # The secret must never come back on a subsequent list/get.
    list_response = client.get("/api/v1/webhooks")
    assert list_response.status_code == 200
    assert all("secret" not in sub for sub in list_response.json())


def test_update_and_delete_webhook(db_session):
    _seed_tenant(db_session)
    with patch("services.webhooks.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
        created = client.post("/api/v1/webhooks", json={"target_url": "https://example.com/hook", "subscribed_events": ["invoice.completed"]}).json()

    update_response = client.put(f"/api/v1/webhooks/{created['id']}", json={"enabled": False})
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False

    delete_response = client.delete(f"/api/v1/webhooks/{created['id']}")
    assert delete_response.status_code == 204
    assert client.get("/api/v1/webhooks").json() == []


def test_webhook_tenant_isolation(db_session):
    _seed_tenant(db_session)
    other_tenant_sub = WebhookSubscription(
        tenant_id=uuid4(), target_url="https://other.example.com/hook", secret="s3cr3t", subscribed_events=["invoice.completed"],
    )
    db_session.add(other_tenant_sub)
    db_session.commit()

    response = client.get("/api/v1/webhooks")
    assert response.status_code == 200
    assert response.json() == []

    update_response = client.put(f"/api/v1/webhooks/{other_tenant_sub.id}", json={"enabled": False})
    assert update_response.status_code == 404


# ── dispatch_webhook_event: signing, filtering, retry, auto-disable ─────────

def test_dispatch_signs_payload_and_only_fires_subscribed_events(db_session):
    _seed_tenant(db_session)
    sub = WebhookSubscription(
        tenant_id=MOCK_TENANT_ID, target_url="https://example.com/hook", secret="s3cr3t",
        subscribed_events=["invoice.completed"],
    )
    db_session.add(sub)
    db_session.commit()

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=200)

        # Not subscribed to this one -- must not deliver at all.
        dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.audit_required", {"invoice_id": "x"})
        mock_client.post.assert_not_called()

        # Subscribed -- must deliver with a correct HMAC signature.
        dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc", "status": "COMPLETED"})
        mock_client.post.assert_called_once()
        _, kwargs = mock_client.post.call_args
        raw_body = kwargs["content"]
        expected_signature = _sign_payload("s3cr3t", raw_body)
        assert kwargs["headers"]["X-Webhook-Signature"] == expected_signature
        assert json.loads(raw_body)["event"] == "invoice.completed"


def test_dispatch_retries_then_succeeds(db_session):
    _seed_tenant(db_session)
    sub = WebhookSubscription(
        tenant_id=MOCK_TENANT_ID, target_url="https://example.com/hook", secret="s3cr3t",
        subscribed_events=["invoice.completed"],
    )
    db_session.add(sub)
    db_session.commit()

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.side_effect = [
            httpx.ConnectTimeout("timeout"),
            MagicMock(status_code=500),
            MagicMock(status_code=200),
        ]
        dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc"})

    assert mock_client.post.call_count == 3
    db_session.refresh(sub)
    assert sub.consecutive_failures == 0


def test_dispatch_auto_disables_after_max_consecutive_failures(db_session):
    _seed_tenant(db_session)
    sub = WebhookSubscription(
        tenant_id=MOCK_TENANT_ID, target_url="https://example.com/hook", secret="s3cr3t",
        subscribed_events=["invoice.completed"], consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
    )
    db_session.add(sub)
    db_session.commit()

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=500)
        dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc"})

    db_session.refresh(sub)
    assert sub.consecutive_failures == MAX_CONSECUTIVE_FAILURES
    assert sub.enabled is False


def test_dispatch_skips_disabled_subscriptions(db_session):
    _seed_tenant(db_session)
    sub = WebhookSubscription(
        tenant_id=MOCK_TENANT_ID, target_url="https://example.com/hook", secret="s3cr3t",
        subscribed_events=["invoice.completed"], enabled=False,
    )
    db_session.add(sub)
    db_session.commit()

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc"})
        mock_client_cls.assert_not_called()
