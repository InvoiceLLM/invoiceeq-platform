"""
Unit tests for BE Gap 680 Part 3: Dead-Letter Queue (DLQ) replay, inspect, and purge script.
Pure mock unit tests — DB-free, network-free.
"""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from scripts.replay_deadletter_queue import (
    inspect_dlq,
    requeue_messages,
    purge_messages,
    parse_dlq_message,
)


def test_gap680_parse_dlq_message():
    """Verify parse_dlq_message correctly parses json envelopes and fallbacks."""
    # Envelope structure
    envelope = {
        "original_message_id": "msg-123",
        "error_type": "ValueError",
        "error_message": "Invalid date",
        "payload": {"invoice_id": "inv-456"},
    }
    parsed = parse_dlq_message(json.dumps(envelope))
    assert parsed["original_message_id"] == "msg-123"
    assert parsed["payload"]["invoice_id"] == "inv-456"

    # Non-json string
    plain = parse_dlq_message("not-json")
    assert plain["payload"] == "not-json"


def test_gap680_inspect_dlq():
    """Verify inspect_dlq peeks messages without removing them."""
    mock_msg = MagicMock()
    mock_msg.id = "dlq-msg-1"
    mock_msg.insertion_time = None
    mock_msg.dequeue_count = 1
    mock_msg.content = json.dumps({
        "original_message_id": "orig-1",
        "error_type": "KeyError",
        "error_message": "Missing grand_total",
        "failed_at": "2026-09-17T12:00:00Z",
        "payload": {"invoice_id": "inv-999"},
    })

    with patch("scripts.replay_deadletter_queue.QueueClient.from_connection_string") as mock_qc_cls:
        mock_client = MagicMock()
        mock_qc_cls.return_value = mock_client
        mock_client.peek_messages.return_value = [mock_msg]

        results = inspect_dlq("fake_conn_str", limit=10)
        assert len(results) == 1
        assert results[0]["message_id"] == "dlq-msg-1"
        assert results[0]["invoice_id"] == "inv-999"
        assert results[0]["task"] is None
        assert results[0]["error_type"] == "KeyError"
        mock_client.peek_messages.assert_called_once_with(max_messages=10)


def _worker_message(msg_id, invoice_id, batch_id="batch-1", tenant_id="tenant-1"):
    """A DLQ envelope around the REAL worker payload shape (routers/invoices.py): the
    original message is {"task", "kwargs"} and carries no invoice_id -- the invoice id
    only appears inside the upload file path."""
    msg = MagicMock()
    msg.id = msg_id
    msg.pop_receipt = f"pop-{msg_id}"
    msg.content = json.dumps({
        "original_message_id": f"orig-{msg_id}",
        "error_type": "RuntimeError",
        "payload": {
            "task": "process_invoice",
            "kwargs": {
                "batch_id": batch_id,
                "file_path": f"azure://invoices/tenants/{tenant_id}/invoices/{invoice_id}.pdf",
                "tenant_id": tenant_id,
            },
        },
    })
    return msg


def _clients(mock_qc_cls):
    dlq, target = MagicMock(), MagicMock()
    mock_qc_cls.side_effect = lambda conn, qname: dlq if "deadletter" in qname else target
    return dlq, target


def test_gap680_requeue_messages():
    """Requeue sends the ORIGINAL worker payload unchanged, then deletes from the DLQ."""
    inv_id = str(uuid4())
    msg = _worker_message("dlq-msg-1", inv_id)

    with patch("scripts.replay_deadletter_queue.QueueClient.from_connection_string") as mock_qc_cls:
        dlq, target = _clients(mock_qc_cls)
        dlq.receive_messages.return_value = [msg]

        results = requeue_messages("fake_conn_str", limit=5)

    assert [(r["invoice_id"], r["status"]) for r in results] == [(inv_id, "requeued")]
    sent_body = json.loads(target.send_message.call_args[0][0])
    assert sent_body == json.loads(msg.content)["payload"]
    dlq.delete_message.assert_called_once_with("dlq-msg-1", "pop-dlq-msg-1")


def test_gap680_requeue_filters_by_invoice_id_read_from_the_file_path():
    wanted, other = str(uuid4()), str(uuid4())
    with patch("scripts.replay_deadletter_queue.QueueClient.from_connection_string") as mock_qc_cls:
        dlq, target = _clients(mock_qc_cls)
        dlq.receive_messages.return_value = [_worker_message("m-other", other), _worker_message("m-wanted", wanted)]

        results = requeue_messages("fake_conn_str", invoice_id=wanted)

    assert [r["dlq_message_id"] for r in results] == ["m-wanted"]
    dlq.delete_message.assert_called_once_with("m-wanted", "pop-m-wanted")


def test_gap680_requeue_send_failure_keeps_the_message_in_the_dlq():
    with patch("scripts.replay_deadletter_queue.QueueClient.from_connection_string") as mock_qc_cls:
        dlq, target = _clients(mock_qc_cls)
        dlq.receive_messages.return_value = [_worker_message("m-1", str(uuid4())), _worker_message("m-2", str(uuid4()))]
        target.send_message.side_effect = [Exception("queue down"), None]

        results = requeue_messages("fake_conn_str")

    assert [r["status"] for r in results] == ["send_failed", "requeued"]
    dlq.delete_message.assert_called_once_with("m-2", "pop-m-2")


def test_gap680_requeue_messages_dry_run():
    """Verify requeue_messages with dry_run=True does not send or delete messages."""
    mock_msg = MagicMock()
    mock_msg.id = "dlq-msg-1"
    mock_msg.pop_receipt = "pop-1"
    mock_msg.content = json.dumps({"payload": {"invoice_id": "inv-123"}})

    with patch("scripts.replay_deadletter_queue.QueueClient.from_connection_string") as mock_qc_cls:
        mock_dlq_client = MagicMock()
        mock_target_client = MagicMock()
        mock_qc_cls.side_effect = lambda conn, qname: mock_dlq_client if "deadletter" in qname else mock_target_client
        mock_dlq_client.receive_messages.return_value = [mock_msg]

        results = requeue_messages("fake_conn_str", dry_run=True)
        assert len(results) == 1
        assert results[0]["status"] == "dry_run_requeued"
        mock_target_client.send_message.assert_not_called()
        mock_dlq_client.delete_message.assert_not_called()


def test_gap680_purge_messages():
    """Verify purge_messages clears all messages when purge_all=True."""
    with patch("scripts.replay_deadletter_queue.QueueClient.from_connection_string") as mock_qc_cls:
        mock_dlq_client = MagicMock()
        mock_qc_cls.return_value = mock_dlq_client

        count = purge_messages("fake_conn_str", purge_all=True)
        assert count == 1
        mock_dlq_client.clear_messages.assert_called_once()
