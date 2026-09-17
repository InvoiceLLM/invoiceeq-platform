"""
Unit tests for BE Gap 677: Worker concurrency loop & visibility heartbeat.
Pure mock unit tests — DB-free, network-free.
"""
import time
import json
from unittest.mock import MagicMock, patch
import pytest

from queue_worker.main_worker import (
    MessageHeartbeat,
    VISIBILITY_TIMEOUT_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    _process_message,
)


def test_message_heartbeat_renewal_and_stop():
    """Verify MessageHeartbeat periodically renews visibility timeout and updates pop_receipt."""
    mock_queue = MagicMock()
    mock_update_res = MagicMock()
    mock_update_res.pop_receipt = "receipt-renewed-1"
    mock_queue.update_message.return_value = mock_update_res

    # Use very short interval for test
    hb = MessageHeartbeat(
        queue_client=mock_queue,
        msg_id="msg-101",
        initial_pop_receipt="receipt-initial",
        visibility_timeout=120,
        renew_interval_seconds=0.05,
    )
    assert hb.get_pop_receipt() == "receipt-initial"

    hb.start()
    time.sleep(0.12)
    hb.stop()

    assert mock_queue.update_message.called
    assert hb.get_pop_receipt() == "receipt-renewed-1"
    mock_queue.update_message.assert_any_call(
        "msg-101",
        "receipt-initial",
        visibility_timeout=120,
    )


def test_process_message_uses_heartbeat_and_latest_receipt():
    """Verify _process_message starts heartbeat and deletes message with latest pop_receipt."""
    mock_queue = MagicMock()
    mock_update_res = MagicMock()
    mock_update_res.pop_receipt = "receipt-renewed-99"
    mock_queue.update_message.return_value = mock_update_res

    mock_msg = MagicMock()
    mock_msg.id = "msg-invoice-1"
    mock_msg.pop_receipt = "receipt-initial"
    mock_msg.content = json.dumps({
        "task": "process_invoice",
        "kwargs": {
            "batch_id": "b-1",
            "file_path": "path.pdf",
            "tenant_id": "t-1",
        }
    })

    with patch("queue_worker.main_worker._acquire_tenant_slot", return_value=True), \
         patch("queue_worker.main_worker._release_tenant_slot"), \
         patch("queue_worker.main_worker.handle_process_invoice") as mock_handle, \
         patch("queue_worker.main_worker.HEARTBEAT_INTERVAL_SECONDS", 0.05):

        def slow_handle(*args, **kwargs):
            time.sleep(0.12)

        mock_handle.side_effect = slow_handle

        _process_message(mock_queue, mock_msg)

        # Must delete message with the renewed receipt!
        mock_queue.delete_message.assert_called_with("msg-invoice-1", "receipt-renewed-99")


def test_visibility_timeout_and_heartbeat_constants():
    """Verify Decision D8 constants: 120s timeout, renewed every 45s."""
    assert VISIBILITY_TIMEOUT_SECONDS == 120
    assert HEARTBEAT_INTERVAL_SECONDS == 45.0


# ---------------------------------------------------------------------------
# Review additions (2026-09-17)
# ---------------------------------------------------------------------------
import threading
from concurrent.futures import ThreadPoolExecutor

from queue_worker import main_worker


def test_stop_waits_for_an_in_flight_renewal_and_returns_its_receipt():
    """A renewal already on the wire when stop is called must finish first, and the
    receipt it produced must be the one handed back -- otherwise delete uses a stale one."""
    renewal_started = threading.Event()
    calls = []

    def slow_update(msg_id, receipt, visibility_timeout):
        calls.append(receipt)
        renewal_started.set()
        time.sleep(0.2)
        result = MagicMock()
        result.pop_receipt = f"renewed-{len(calls)}"
        return result

    queue = MagicMock()
    queue.update_message.side_effect = slow_update
    hb = MessageHeartbeat(queue, "m-1", "initial", visibility_timeout=120, renew_interval_seconds=0.01).start()
    assert renewal_started.wait(1.0)

    final = hb.stop_and_get_receipt()
    calls_at_stop = len(calls)
    time.sleep(0.1)

    assert final == "renewed-1"
    assert len(calls) == calls_at_stop == 1


def test_delete_uses_the_newest_receipt_and_no_renewal_follows_it():
    events = []
    issued = ["r0"]
    queue = MagicMock()

    def update(msg_id, receipt, visibility_timeout):
        events.append("update")
        result = MagicMock()
        result.pop_receipt = f"r{len(issued)}"
        issued.append(result.pop_receipt)
        return result

    def delete(msg_id, receipt):
        events.append("delete")
        # Azure rejects a stale receipt; the one used must be the newest ever issued.
        assert receipt == issued[-1], f"deleted with stale receipt {receipt}, newest is {issued[-1]}"

    queue.update_message.side_effect = update
    queue.delete_message.side_effect = delete
    msg = MagicMock()
    msg.id, msg.pop_receipt = "m-2", "r0"
    msg.content = json.dumps({"task": "process_invoice", "kwargs": {"batch_id": "b", "file_path": "p", "tenant_id": "t"}})

    with patch.object(main_worker, "_acquire_tenant_slot", return_value=True), \
         patch.object(main_worker, "_release_tenant_slot"), \
         patch.object(main_worker, "HEARTBEAT_INTERVAL_SECONDS", 0.005), \
         patch.object(main_worker, "handle_process_invoice", side_effect=lambda **k: time.sleep(0.05)):
        _process_message(queue, msg)
    time.sleep(0.05)

    assert events[-1] == "delete"
    assert events.count("delete") == 1
    assert "update" in events  # the heartbeat really renewed during processing
    assert not queue.delete_message.call_args is None
    # _process_message swallows exceptions, so a stale-receipt assertion inside the fake
    # delete would be hidden; check its recorded argument directly as well.
    assert queue.delete_message.call_args.args[1] == issued[-1]


def _fake_queue(messages):
    queue = MagicMock()
    pending = list(messages)

    def receive(messages_per_page, visibility_timeout):
        batch, pending[:] = pending[:messages_per_page], pending[messages_per_page:]
        return iter(batch)

    queue.receive_messages.side_effect = receive
    return queue


def _msg(name):
    m = MagicMock()
    m.id = name
    return m


def test_a_slow_message_does_not_block_new_receives():
    """Head-of-line blocking: with one slow job running, finished slots are refilled."""
    release_slow = threading.Event()

    def fake_process(queue_client, msg):
        if msg.id == "slow":
            release_slow.wait(2.0)

    queue = _fake_queue([_msg("slow"), _msg("fast-1"), _msg("fast-2"), _msg("fast-3"), _msg("fast-4")])
    with patch.object(main_worker, "MAX_WORKERS", 3), \
         patch.object(main_worker, "_process_redis_chat_tasks", return_value=None), \
         patch.object(main_worker, "_process_message", side_effect=fake_process), \
         ThreadPoolExecutor(max_workers=3) as executor:
        active = main_worker._poll_once(queue, executor, set())
        deadline = time.time() + 2.0
        while sum(1 for f in active if not f.done()) > 1 and time.time() < deadline:
            time.sleep(0.01)
        active = main_worker._poll_once(queue, executor, active)
        pages = [c.kwargs["messages_per_page"] for c in queue.receive_messages.call_args_list]
        slow_still_running = not release_slow.is_set()
        release_slow.set()

    assert pages[:2] == [3, 2]
    assert slow_still_running


def test_redis_chat_jobs_count_against_worker_capacity():
    release = threading.Event()
    queue = _fake_queue([_msg(f"m-{i}") for i in range(5)])
    with patch.object(main_worker, "MAX_WORKERS", 2), \
         patch.object(main_worker, "_process_message", side_effect=lambda q, m: release.wait(2.0)), \
         ThreadPoolExecutor(max_workers=2) as executor:
        chat_future = executor.submit(release.wait, 2.0)
        with patch.object(main_worker, "_process_redis_chat_tasks", return_value=chat_future):
            active = main_worker._poll_once(queue, executor, set())
        first_page = queue.receive_messages.call_args.kwargs["messages_per_page"]
        with patch.object(main_worker, "_process_redis_chat_tasks", return_value=None):
            main_worker._poll_once(queue, executor, active)
        calls_when_full = queue.receive_messages.call_count
        release.set()

    assert first_page == 1  # one slot already taken by the chat job
    assert calls_when_full == 1  # no receive at all while every slot is busy
