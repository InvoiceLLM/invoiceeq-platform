"""Pure DB-free unit tests for BE Gap 680 Part 1:
- Poison message dead-letter queue routing & telemetry
- Fix for missing conn_str bug (guaranteed primary queue purge)
- Exact log line preservation (POISON MESSAGE ISOLATED) for Bicep alert rule KQL contract
"""
import json
import logging
from unittest.mock import MagicMock, patch
import pytest

from queue_worker.main_worker import _route_to_dead_letter_queue, DEAD_LETTER_QUEUE_NAME, MAX_DEQUEUE_ATTEMPTS
from telemetry import track_poison_message, POISON_MESSAGE_EVENT_NAME


def _create_mock_message(msg_id="msg-12345", content=None, dequeue_count=5):
    if content is None:
        content = json.dumps({
            "task": "process_invoice",
            "kwargs": {
                "batch_id": "batch-abc-999",
                "file_path": "azure://invoices/tenants/t-1/inv-1.pdf",
                "tenant_id": "tenant-001-uuid",
            }
        })
    msg = MagicMock()
    msg.id = msg_id
    msg.pop_receipt = "pop-receipt-xyz"
    msg.content = content
    msg.dequeue_count = dequeue_count
    return msg


# ===========================================================================
# 1. Exact Log Line Preservation (Alert Rule KQL Contract Lock)
# ===========================================================================

def test_route_to_dead_letter_queue_emits_exact_log_phrase(caplog):
    """Bicep alert rule (infra/modules/monitoring/alert-rules.bicep:415-455)
    triggers on 'POISON MESSAGE ISOLATED'. This test locks that exact string."""
    mock_qc = MagicMock()
    msg = _create_mock_message("msg-lock-check")
    err = ValueError("Invalid PDF payload")

    with caplog.at_level(logging.ERROR):
        with patch("queue_worker.main_worker.QueueClient") as mock_qc_cls:
            _route_to_dead_letter_queue(mock_qc, msg, err)

    assert "POISON MESSAGE ISOLATED: Message msg-lock-check failed 5 times." in caplog.text
    assert f"Moved to Dead-Letter Queue '{DEAD_LETTER_QUEUE_NAME}' and purged from main queue." in caplog.text
    # Primary queue delete must have been called
    mock_qc.delete_message.assert_called_once_with("msg-lock-check", "pop-receipt-xyz")


# ===========================================================================
# 2. Structured Telemetry Emission
# ===========================================================================

def test_route_to_dead_letter_queue_emits_structured_telemetry():
    """Verifies track_poison_message is called with all entity dimensions and error details."""
    mock_qc = MagicMock()
    msg = _create_mock_message(
        "msg-telemetry-test",
        content=json.dumps({
            "task": "import_connector_file",
            "kwargs": {
                "provider": "google_drive",
                "file_id": "gd-999-file",
                "tenant_id": "tenant-777",
                "batch_id": "batch-888",
            }
        }),
        dequeue_count=5,
    )
    err = RuntimeError("Google Drive token permanently revoked")

    with patch("telemetry.track_poison_message") as mock_track:
        with patch("queue_worker.main_worker.QueueClient"):
            _route_to_dead_letter_queue(mock_qc, msg, err)

    mock_track.assert_called_once()
    kwargs = mock_track.call_args.kwargs
    assert kwargs["task"] == "import_connector_file"
    assert kwargs["tenant_id"] == "tenant-777"
    assert kwargs["error_type"] == "RuntimeError"
    assert "permanently revoked" in kwargs["error_message"]
    assert kwargs["dequeue_count"] == 5
    assert kwargs["payload_ids"]["provider"] == "google_drive"
    assert kwargs["payload_ids"]["file_id"] == "gd-999-file"
    assert kwargs["payload_ids"]["batch_id"] == "batch-888"
    assert kwargs["dlq_copied"] is True


# ===========================================================================
# 3. Bug Fix: Empty conn_str Must Still Purge Primary Queue
# ===========================================================================

def test_route_to_dead_letter_queue_isolates_when_conn_str_missing(caplog):
    """Teammate bug: with AZURE_STORAGE_CONNECTION_STRING unset the handler used to
    return early -- the message was neither copied nor purged and retried forever.
    Now the DLQ client is built from the main queue client's own account, the copy is
    made, and only then is the message purged."""
    mock_qc = MagicMock()
    mock_qc.url = "https://stinvoice.queue.core.windows.net/extraction-tasks-queue?sv=token"
    msg = _create_mock_message("msg-no-conn-str")
    err = KeyError("Missing required field")

    with patch("queue_worker.main_worker.get_settings") as mock_settings, \
         patch("queue_worker.main_worker.QueueClient") as mock_qc_cls:
        mock_settings.return_value.AZURE_STORAGE_CONNECTION_STRING = ""
        with caplog.at_level(logging.ERROR):
            _route_to_dead_letter_queue(mock_qc, msg, err)

    mock_qc_cls.assert_called_once_with(
        account_url="https://stinvoice.queue.core.windows.net",
        queue_name=DEAD_LETTER_QUEUE_NAME,
        credential=mock_qc.credential,
    )
    mock_qc_cls.return_value.send_message.assert_called_once()
    mock_qc.delete_message.assert_called_once_with("msg-no-conn-str", "pop-receipt-xyz")
    assert "POISON MESSAGE ISOLATED: Message msg-no-conn-str" in caplog.text


# ===========================================================================
# 4. DLQ copy failure: the message is NOT deleted (it would be lost)
# ===========================================================================

def test_route_to_dead_letter_queue_keeps_message_when_dlq_send_fails(caplog):
    """If the copy to the DLQ fails, deleting from the main queue would lose the job
    with no copy anywhere. The message must stay, the isolation log must NOT claim it
    was isolated, and a critical routing-failure log plus dlq_copied=False telemetry
    must say what happened."""
    mock_qc = MagicMock()
    msg = _create_mock_message("msg-dlq-fail")
    err = ValueError("Malformed JSON")

    with patch("queue_worker.main_worker.QueueClient") as mock_qc_cls, \
         patch("telemetry.track_poison_message") as mock_track:
        mock_dlq_instance = MagicMock()
        mock_dlq_instance.send_message.side_effect = Exception("DLQ Queue storage outage")
        mock_qc_cls.from_connection_string.return_value = mock_dlq_instance

        with caplog.at_level(logging.ERROR):
            _route_to_dead_letter_queue(mock_qc, msg, err)

    mock_qc.delete_message.assert_not_called()
    assert "POISON MESSAGE ISOLATED" not in caplog.text
    assert "POISON MESSAGE ROUTING FAILED: Message msg-dlq-fail" in caplog.text
    assert mock_track.call_args.kwargs["dlq_copied"] is False


# ===========================================================================
# 5. Pure Telemetry Helper Unit Test
# ===========================================================================

def test_track_poison_message_pure_emits_event():
    """Verifies track_poison_message shapes attributes and calls _emit_event."""
    with patch("telemetry._emit_event") as mock_emit:
        track_poison_message(
            task="process_invoice",
            tenant_id="tenant-abc",
            payload_ids={"batch_id": "b-1", "file_bytes": b"raw binary", "file_path": "azure://path"},
            error_type="ZeroDivisionError",
            error_message="division by zero",
            dequeue_count=5,
        )

    mock_emit.assert_called_once()
    event_name, props = mock_emit.call_args[0]
    assert event_name == POISON_MESSAGE_EVENT_NAME
    assert props["task"] == "process_invoice"
    assert props["tenant_id"] == "tenant-abc"
    assert props["error_type"] == "ZeroDivisionError"
    assert props["error_message"] == "division by zero"
    assert props["dequeue_count"] == 5
    assert props["severity"] == "high"
    assert props["payload_batch_id"] == "b-1"
    assert props["payload_file_path"] == "azure://path"
    # Invariant: Never serialize raw file bytes into customDimensions
    assert "payload_file_bytes" not in props
