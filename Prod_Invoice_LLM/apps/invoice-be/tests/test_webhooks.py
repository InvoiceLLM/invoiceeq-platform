"""Tests for Feature 15 (Outbound Webhooks): CRUD endpoints
(routers/webhooks.py), SSRF validation, HMAC signing, retry/backoff, and
auto-disable (services/webhooks.py).

Gap 194 split the delivery path in two, and the tests follow that split:
  * `dispatch_webhook_event` only *enqueues* -- it must never make an HTTP
    call on the caller's thread.
  * `deliver_webhook_now` (run by queue_worker.handlers.handle_deliver_webhook)
    performs the HTTP call, records a WebhookDeliveryLog row, and does the
    per-event-type failure accounting / auto-disable.
"""
import json
from unittest.mock import patch, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Tenant, WebhookDeliveryLog, WebhookSubscription
from services.webhooks import (
    validate_webhook_target_url,
    InvalidWebhookUrlError,
    dispatch_webhook_event,
    deliver_webhook_now,
    _sign_payload,
    DELIVERY_TASK_NAME,
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


# ── Gap 194 shared fixtures/helpers ───────────────────────────────────────────

@pytest.fixture(name="queue")
def queue_fixture():
    """Stand in for the Azure Storage Queue so the enqueue path is observable.

    Returns the mock QueueClient instance `dispatch_webhook_event` will use;
    assert on `queue.send_message`.
    """
    with patch("services.webhooks.get_settings") as mock_get_settings, \
         patch("services.webhooks.QueueClient") as mock_queue_cls:
        mock_get_settings.return_value = MagicMock(
            AZURE_STORAGE_CONNECTION_STRING="UseDevelopmentStorage=true"
        )
        yield mock_queue_cls.from_connection_string.return_value


def _seed_subscription(db_session, **overrides) -> WebhookSubscription:
    kwargs = {
        "tenant_id": MOCK_TENANT_ID,
        "target_url": "https://example.com/hook",
        "secret": "s3cr3t",
        "subscribed_events": ["invoice.completed"],
    }
    kwargs.update(overrides)
    sub = WebhookSubscription(**kwargs)
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return sub


def _queued_messages(queue) -> list[dict]:
    return [json.loads(call.args[0]) for call in queue.send_message.call_args_list]


def _logs_for(db_session, sub) -> list[WebhookDeliveryLog]:
    return list(
        db_session.exec(
            select(WebhookDeliveryLog).where(WebhookDeliveryLog.subscription_id == sub.id)
        ).all()
    )


# ── Gap 194: dispatch_webhook_event enqueues, never delivers inline ───────────

def test_dispatch_enqueues_delivery_without_calling_the_subscriber(db_session, queue):
    """The whole point of Gap 194: the thread that just committed the invoice
    must not pay the subscriber's latency (up to ~19s of retries/backoff)."""
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        dispatch_webhook_event(
            db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc", "status": "COMPLETED"}
        )
        # No HTTP client is even constructed on the dispatching thread.
        mock_client_cls.assert_not_called()

    messages = _queued_messages(queue)
    assert len(messages) == 1
    assert messages[0]["task"] == DELIVERY_TASK_NAME
    assert messages[0]["kwargs"] == {
        "tenant_id": str(MOCK_TENANT_ID),
        "subscription_id": str(sub.id),
        "event_type": "invoice.completed",
        "payload": {"invoice_id": "abc", "status": "COMPLETED"},
    }


def test_dispatch_only_enqueues_subscribed_events(db_session, queue):
    _seed_tenant(db_session)
    _seed_subscription(db_session, subscribed_events=["invoice.completed"])

    dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.audit_required", {"invoice_id": "x"})
    queue.send_message.assert_not_called()

    dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "x"})
    assert queue.send_message.call_count == 1


def test_dispatch_skips_disabled_subscriptions(db_session, queue):
    _seed_tenant(db_session)
    _seed_subscription(db_session, enabled=False)

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc"})

    mock_client_cls.assert_not_called()
    queue.send_message.assert_not_called()


def test_dispatch_logs_a_failed_delivery_when_it_cannot_queue(db_session, queue):
    """An enqueue failure is our fault, not the subscriber's: it's recorded so
    the tenant can see the event never went out, but it must not count toward
    auto-disable."""
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)
    queue.send_message.side_effect = RuntimeError("queue unreachable")

    dispatch_webhook_event(db_session, MOCK_TENANT_ID, "invoice.completed", {"invoice_id": "abc"})

    logs = _logs_for(db_session, sub)
    assert len(logs) == 1
    assert logs[0].success is False
    assert "Not queued" in logs[0].error

    db_session.refresh(sub)
    assert sub.consecutive_failures == 0
    assert sub.enabled is True


# ── Gap 194: deliver_webhook_now -- signing, retry, delivery log ──────────────

def test_deliver_signs_payload_with_subscription_secret(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=200)
        result = deliver_webhook_now(
            db_session, sub.id, "invoice.completed", {"invoice_id": "abc", "status": "COMPLETED"}
        )

    assert result.success is True
    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    raw_body = kwargs["content"]
    assert kwargs["headers"]["X-Webhook-Signature"] == _sign_payload("s3cr3t", raw_body)
    assert json.loads(raw_body)["event"] == "invoice.completed"


def test_deliver_retries_then_succeeds_and_records_one_log_row(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.side_effect = [
            httpx.ConnectTimeout("timeout"),
            MagicMock(status_code=500),
            MagicMock(status_code=200),
        ]
        deliver_webhook_now(db_session, sub.id, "invoice.completed", {"invoice_id": "abc"})

    assert mock_client.post.call_count == 3
    db_session.refresh(sub)
    assert sub.consecutive_failures == 0
    assert sub.event_failure_counts == {"invoice.completed": 0}

    # One row per attempt *series*, not per HTTP call.
    logs = _logs_for(db_session, sub)
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].status_code == 200
    assert logs[0].attempts == 3
    assert logs[0].error is None


def test_delivery_log_records_failure_detail(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=503)
        deliver_webhook_now(db_session, sub.id, "invoice.completed", {"invoice_id": "abc"})

    logs = _logs_for(db_session, sub)
    assert len(logs) == 1
    assert logs[0].success is False
    assert logs[0].status_code == 503
    assert logs[0].error == "HTTP 503"
    assert logs[0].event_type == "invoice.completed"


def test_deliver_drops_message_for_disabled_or_unsubscribed_subscription(db_session):
    """A queued delivery must not be able to resurrect a subscription the
    tenant disabled (or unsubscribed from that event) after it was enqueued."""
    _seed_tenant(db_session)
    disabled = _seed_subscription(db_session, enabled=False)
    unsubscribed = _seed_subscription(db_session, subscribed_events=["invoice.approved"])

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        assert deliver_webhook_now(db_session, disabled.id, "invoice.completed", {}) is None
        assert deliver_webhook_now(db_session, unsubscribed.id, "invoice.completed", {}) is None
        assert deliver_webhook_now(db_session, uuid4(), "invoice.completed", {}) is None

    mock_client_cls.assert_not_called()
    assert _logs_for(db_session, disabled) == []


# ── Gap 194: auto-disable is scoped so a healthy event type isn't punished ────

def test_auto_disables_when_no_event_type_is_delivering(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(
        db_session,
        subscribed_events=["invoice.completed"],
        event_failure_counts={"invoice.completed": MAX_CONSECUTIVE_FAILURES - 1},
        consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
    )

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=500)
        deliver_webhook_now(db_session, sub.id, "invoice.completed", {"invoice_id": "abc"})

    db_session.refresh(sub)
    assert sub.event_failure_counts["invoice.completed"] == MAX_CONSECUTIVE_FAILURES
    assert sub.consecutive_failures == MAX_CONSECUTIVE_FAILURES
    assert sub.enabled is False


def test_one_failing_event_type_does_not_disable_a_healthy_one(db_session):
    """Gap 194's core scoping fix: `outbound_invoice.overdue` failing 10 times
    must not take `invoice.completed` -- which the same endpoint has been
    accepting -- offline with it."""
    _seed_tenant(db_session)
    sub = _seed_subscription(
        db_session,
        subscribed_events=["invoice.completed", "outbound_invoice.overdue"],
        event_failure_counts={
            "invoice.completed": 0,  # last delivery of this event succeeded
            "outbound_invoice.overdue": MAX_CONSECUTIVE_FAILURES - 1,
        },
        consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
    )

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=500)
        deliver_webhook_now(db_session, sub.id, "outbound_invoice.overdue", {"invoice_id": "abc"})

    db_session.refresh(sub)
    assert sub.event_failure_counts["outbound_invoice.overdue"] == MAX_CONSECUTIVE_FAILURES
    assert sub.event_failure_counts["invoice.completed"] == 0
    assert sub.enabled is True, "a healthy event type must keep the subscription alive"

    # And the still-healthy event type keeps being delivered.
    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=200)
        assert deliver_webhook_now(db_session, sub.id, "invoice.completed", {}).success is True


def test_legacy_flat_failure_counter_is_backfilled_into_the_event_map(db_session):
    """A subscription that was already 9 failures deep before the per-event
    column existed must not get a free reset from the upgrade."""
    _seed_tenant(db_session)
    sub = _seed_subscription(
        db_session,
        consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
        event_failure_counts={},
    )

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=500)
        deliver_webhook_now(db_session, sub.id, "invoice.completed", {})

    db_session.refresh(sub)
    assert sub.event_failure_counts == {"invoice.completed": MAX_CONSECUTIVE_FAILURES}
    assert sub.enabled is False


def test_reenabling_clears_the_per_event_failure_map(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(
        db_session,
        enabled=False,
        consecutive_failures=MAX_CONSECUTIVE_FAILURES,
        event_failure_counts={"invoice.completed": MAX_CONSECUTIVE_FAILURES},
    )

    response = client.put(f"/api/v1/webhooks/{sub.id}", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["event_failure_counts"] == {}

    db_session.refresh(sub)
    assert sub.event_failure_counts == {}
    assert sub.consecutive_failures == 0


# ── Gap 194: delivery-log endpoint ───────────────────────────────────────────

def test_list_deliveries_returns_newest_first(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session, subscribed_events=["invoice.completed", "invoice.approved"])

    with patch("services.webhooks.httpx.Client") as mock_client_cls, patch("services.webhooks.time.sleep"):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=200)
        deliver_webhook_now(db_session, sub.id, "invoice.completed", {})
        mock_client.post.return_value = MagicMock(status_code=500)
        deliver_webhook_now(db_session, sub.id, "invoice.approved", {})

    response = client.get(f"/api/v1/webhooks/{sub.id}/deliveries")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {row["event_type"] for row in body} == {"invoice.completed", "invoice.approved"}
    failed = next(row for row in body if row["event_type"] == "invoice.approved")
    assert failed["success"] is False
    assert failed["status_code"] == 500


def test_list_deliveries_is_tenant_scoped(db_session):
    _seed_tenant(db_session)
    other = WebhookSubscription(
        tenant_id=uuid4(), target_url="https://other.example.com/hook", secret="s",
        subscribed_events=["invoice.completed"],
    )
    db_session.add(other)
    db_session.commit()

    assert client.get(f"/api/v1/webhooks/{other.id}/deliveries").status_code == 404


def test_deleting_a_webhook_removes_its_delivery_logs(db_session):
    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=200)
        deliver_webhook_now(db_session, sub.id, "invoice.completed", {})
    assert len(_logs_for(db_session, sub)) == 1

    assert client.delete(f"/api/v1/webhooks/{sub.id}").status_code == 204
    assert _logs_for(db_session, sub) == []


# ── Gap 194: the queue-worker handler that actually delivers ─────────────────

def test_queue_worker_handler_delivers_and_records(db_session):
    from queue_worker.handlers import handle_deliver_webhook

    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = MagicMock(status_code=202)
        result = handle_deliver_webhook(
            tenant_id=str(MOCK_TENANT_ID),
            subscription_id=str(sub.id),
            event_type="invoice.completed",
            payload={"invoice_id": "abc"},
            db_session=db_session,
        )

    assert result == {"delivered": True, "skipped": False, "status_code": 202, "attempts": 1}
    assert len(_logs_for(db_session, sub)) == 1


def test_queue_worker_handler_swallows_delivery_errors(db_session):
    """A raise here would leave the queue message undeleted and redeliver the
    same event to a subscriber that may already have received it."""
    from queue_worker.handlers import handle_deliver_webhook

    _seed_tenant(db_session)
    sub = _seed_subscription(db_session)

    with patch("services.webhooks.deliver_webhook_now", side_effect=RuntimeError("boom")):
        result = handle_deliver_webhook(
            tenant_id=str(MOCK_TENANT_ID),
            subscription_id=str(sub.id),
            event_type="invoice.completed",
            payload={},
            db_session=db_session,
        )

    assert result["delivered"] is False
    assert "boom" in result["error"]
