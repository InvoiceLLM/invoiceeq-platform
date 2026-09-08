"""Gap 500 -- the second-pass bubble reaches the browser BEFORE its stream closes.

The browser opens one SSE stream on the extraction job and closes it on the
first `completed` status. Gap 497 put the `insight_update` event on that same
stream; this file pins the ordering that makes it useful: the extraction job's
`completed` is published AFTER `insight_update`, and never lost when the second
pass fails or was never queued. All on a fake Redis: the assertion is about the
order of events on one channel, nothing else.
"""
from __future__ import annotations

import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.chat_queue import ChatQueueService, CHAT_JOB_CHANNEL_PREFIX  # noqa: E402


class _FakeRedis:
    """SET/GET/DEL/LPUSH/PUBLISH with a per-channel event log."""

    def __init__(self):
        self._data: dict = {}
        self.published: list[tuple[str, dict]] = []
        self._guard = threading.Lock()

    def set(self, key, value, nx=False, ex=None):  # noqa: ARG002
        with self._guard:
            if nx and key in self._data:
                return None
            self._data[key] = value
            return True

    def get(self, key):
        with self._guard:
            return self._data.get(key)

    def delete(self, key):
        with self._guard:
            self._data.pop(key, None)

    def lpush(self, key, value):
        with self._guard:
            self._data.setdefault(key, []).insert(0, value)

    def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))

    # slot bookkeeping the completion path touches; irrelevant here
    def incr(self, *a, **k):
        return 0

    def decr(self, *a, **k):
        return 0

    def expire(self, *a, **k):
        return True

    def events(self, job_id):
        chan = f"{CHAT_JOB_CHANNEL_PREFIX}{job_id}"
        return [m.get("step") or m.get("status") for c, m in self.published if c == chan]


@pytest.fixture
def fake(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr("services.chat_queue.get_redis_client", lambda: r)
    monkeypatch.setattr(ChatQueueService, "release_tenant_slot", staticmethod(lambda *a, **k: None), raising=False)
    return r


def test_insight_update_arrives_before_the_extraction_stream_closes(fake):
    """The order the browser needs: ... -> insight_update -> completed."""
    ext = "ext-job-1"
    ChatQueueService.publish_progress(ext, "matching", {"attachment_id": "a1"})
    assert ChatQueueService.defer_completion(ext, {"attachment_id": "a1", "extraction_status": "EXTRACTED"})
    # the second pass runs later and publishes on the extraction channel (Gap 497)
    ChatQueueService.publish_progress(ext, "insight_update", {"attachment_id": "a1", "insights_version": 2})
    assert ChatQueueService.complete_deferred(ext, "tenant-1", {"insights_version": 2})

    events = fake.events(ext)
    assert events.index("insight_update") < events.index("completed")
    assert events[-1] == "completed"
    final = [m for c, m in fake.published if m.get("status") == "completed"][-1]
    assert final["result"]["extraction_status"] == "EXTRACTED"
    assert final["result"]["insights_version"] == 2


def test_a_failed_second_pass_still_closes_the_stream(fake):
    ext = "ext-job-2"
    assert ChatQueueService.defer_completion(ext, {"attachment_id": "a2", "extraction_status": "EXTRACTED"})
    # the insight handler's except-path calls this with a marker
    assert ChatQueueService.complete_deferred(ext, "tenant-1", {"insight_stage": "failed"})
    assert fake.events(ext)[-1] == "completed"


def test_complete_deferred_is_a_no_op_when_nothing_was_parked(fake):
    """An extraction with no second pass completes itself; the insight job must
    not complete it a second time."""
    assert ChatQueueService.complete_deferred("never-parked", "tenant-1") is False
    assert ChatQueueService.complete_deferred(None, "tenant-1") is False
    assert fake.events("never-parked") == []


def test_defer_reports_false_without_redis_so_the_caller_completes_now(monkeypatch):
    monkeypatch.setattr("services.chat_queue.get_redis_client", lambda: None)
    assert ChatQueueService.defer_completion("ext-job-3", {"attachment_id": "a3"}) is False


def test_the_deferred_step_is_visible_on_the_stream(fake):
    """The chip can say 'checking for findings' instead of looking stuck."""
    ext = "ext-job-4"
    ChatQueueService.defer_completion(ext, {"attachment_id": "a4"})
    assert "insight_pending" in fake.events(ext)
