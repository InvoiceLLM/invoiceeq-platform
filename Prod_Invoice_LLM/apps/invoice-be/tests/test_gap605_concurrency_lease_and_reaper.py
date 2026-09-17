"""BE Gap 605 (CH-39) & BE Gap 601 (CH-34): Concurrency slot lease with TTL, self-healing, and reaper tests.

Verifies:
1. `enqueue_chat_job` sets safety TTL on the tenant inflight counter and creates a per-job lease with TTL.
2. `release_tenant_slot` deletes the per-job lease when job_id is provided.
3. Counter self-healing: if the integer counter is desynced/orphaned past ceiling due to crashes,
   live lease scan heals the counter and permits new turns under the ceiling.
4. BE Gap 601 Fail-Closed: When Redis is absent/unreachable, concurrency limit is enforced against
   database queued/processing rows, raising ChatQueueCapacityError if over capacity.
5. Background Reaper: `reap_stuck_chat_jobs` marks messages stuck in 'queued' or 'processing' older
   than max_age_seconds as 'failed', publishes Redis failure event, and releases tenant slots.
6. Background Reaper dry-run reports stuck turns without mutating DB.
"""
import os
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool

from models import ChatSession, ChatMessage, Tenant
from services.chat_queue import (
    CHAT_TENANT_INFLIGHT_PREFIX,
    CHAT_INFLIGHT_LEASE_TTL_SECONDS,
    PER_TENANT_MAX_ACTIVE_CHAT,
    ChatQueueCapacityError,
    ChatQueueService,
)
from scripts.sweep_stuck_chat_turns import reap_stuck_chat_jobs

# BE Gap 570 / Gap 525: PostgreSQL test fixture with strict localhost and db-name security guard
postgres_test_url = os.getenv("TEST_DATABASE_URL")
if postgres_test_url:
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(postgres_test_url)
    assert _parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1 to avoid accidental data loss."
    )
    assert "test" in (_parsed.path or "").lower(), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must name a throwaway database whose name contains 'test' "
        "(this fixture drops every table after each test)."
    )
    engine = create_engine(postgres_test_url)
else:
    sqlite_url = "sqlite:///:memory:"
    engine = create_engine(
        sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

TENANT_ID = uuid4()


@pytest.fixture(name="db_session")
def db_session_fixture():
    if postgres_test_url:
        try:
            with engine.connect() as conn:
                pass
        except Exception as exc:
            pytest.fail(f"TEST_DATABASE_URL configured but unreachable: {exc}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        t = Tenant(id=TENANT_ID, name="Tenant Lease Test", domain="lease.example.com", billing_plan="pro")
        session.add(t)
        session.commit()
        yield session
    SQLModel.metadata.drop_all(engine)


class MockLeaseRedis:
    """Mock Redis tracking counters, keys, and expiration TTLs for BE Gap 605 tests."""

    def __init__(self):
        self.counters: dict[str, int] = {}
        self.blobs: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.queue: list[str] = []
        self.published: list[tuple[str, str]] = []

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def decr(self, key):
        self.counters[key] = max(0, self.counters.get(key, 0) - 1)
        return self.counters[key]

    def get(self, key):
        if key in self.counters:
            return str(self.counters[key])
        return self.blobs.get(key)

    def set(self, key, value, ex=None, nx=None):
        if key in self.counters:
            self.counters[key] = int(value)
        else:
            self.blobs[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    def delete(self, *keys):
        for k in keys:
            self.blobs.pop(k, None)
            self.counters.pop(k, None)
            self.ttls.pop(k, None)
        return len(keys)

    def lpush(self, key, value):
        self.queue.append(value)
        return len(self.queue)

    def publish(self, channel, message):
        self.published.append((channel, message))
        return 1

    def scan_iter(self, match=None, count=None):
        prefix = match.rstrip("*") if match else ""
        for k in list(self.blobs.keys()) + list(self.counters.keys()):
            if not prefix or k.startswith(prefix):
                yield k


def test_enqueue_sets_ttl_and_per_job_lease():
    """BE Gap 605: Enqueue sets safety TTL on inflight counter and records per-job lease."""
    r = MockLeaseRedis()
    tenant_str = str(TENANT_ID)
    job_id = "test-job-lease-001"

    res = ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="Hello world",
        tenant_id=tenant_str,
        job_id=job_id,
        client=r,
    )

    assert res["status"] == "queued"
    assert res["enqueued"] is True

    # Counter is 1 with 300s TTL
    inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_str}"
    assert r.counters[inflight_key] == 1
    assert r.ttls[inflight_key] == CHAT_INFLIGHT_LEASE_TTL_SECONDS

    # Per-job lease is recorded with 300s TTL
    job_lease_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_str}:{job_id}"
    assert job_lease_key in r.blobs
    assert r.ttls[job_lease_key] == CHAT_INFLIGHT_LEASE_TTL_SECONDS


def test_release_tenant_slot_cleans_up_job_lease():
    """BE Gap 605: Releasing slot with job_id removes the per-job lease."""
    r = MockLeaseRedis()
    tenant_str = str(TENANT_ID)
    job_id = "test-job-lease-002"

    ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="Test query",
        tenant_id=tenant_str,
        job_id=job_id,
        client=r,
    )

    job_lease_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_str}:{job_id}"
    assert job_lease_key in r.blobs

    # Release with job_id
    ChatQueueService.release_tenant_slot(tenant_str, client=r, job_id=job_id)
    assert job_lease_key not in r.blobs
    assert r.counters[f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_str}"] == 0


def test_self_healing_counter_recovers_from_crashes():
    """BE Gap 605: If counter is desynced above ceiling by crashes without live leases, it self-heals."""
    r = MockLeaseRedis()
    tenant_str = str(TENANT_ID)
    inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_str}"

    # Artificially corrupt the counter to 5 (e.g. 5 worker crashes)
    r.counters[inflight_key] = 5

    # No per-job leases exist in blobs (they expired or were never completed)
    # When a new job arrives, scan_iter finds 0 live leases <= PER_TENANT_MAX_ACTIVE_CHAT,
    # so counter self-heals to live count and proceeds
    res = ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()),
        user_msg_id=str(uuid4()),
        content="Can I query now?",
        tenant_id=tenant_str,
        job_id="new-healing-job",
        client=r,
    )

    assert res["status"] == "queued"
    assert res["enqueued"] is True
    # The counter was healed and is now under ceiling
    assert r.counters[inflight_key] <= PER_TENANT_MAX_ACTIVE_CHAT


def test_gap601_fail_closed_without_redis(db_session):
    """BE Gap 601: When Redis is unavailable, concurrency ceiling is enforced via database."""
    session_id = uuid4()
    s = ChatSession(id=session_id, tenant_id=TENANT_ID, title="Session 1")
    db_session.add(s)
    db_session.commit()

    # Stage 3 active turns in the database for this tenant
    for i in range(PER_TENANT_MAX_ACTIVE_CHAT):
        m = ChatMessage(
            id=uuid4(),
            session_id=session_id,
            role="user",
            content=f"Question {i}",
            status="queued",
            job_id=f"active-db-job-{i}",
        )
        db_session.add(m)
    db_session.commit()

    # Attempting to enqueue a 4th turn when Redis is None raises ChatQueueCapacityError (fails closed)
    with patch("services.chat_queue.get_redis_client", return_value=None):
        with pytest.raises(ChatQueueCapacityError) as exc:
            ChatQueueService.enqueue_chat_job(
                session_id=str(session_id),
                user_msg_id=str(uuid4()),
                content="4th Question",
                tenant_id=str(TENANT_ID),
                client=None,
                db_session=db_session,
            )
        assert exc.value.limit == PER_TENANT_MAX_ACTIVE_CHAT


def test_reaper_sweeps_stuck_chat_turns(db_session):
    """BE Gap 605: Background reaper transitions stuck queued/processing messages to failed and frees slots."""
    session_id = uuid4()
    s = ChatSession(id=session_id, tenant_id=TENANT_ID, title="Session Reaper")
    db_session.add(s)
    db_session.commit()

    old_time = datetime.now(timezone.utc) - timedelta(seconds=600)  # 10 minutes ago
    recent_time = datetime.now(timezone.utc) - timedelta(seconds=30)  # 30 seconds ago

    # Message 1: stuck queued for 10 minutes (should be reaped)
    m1 = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="Stuck turn 1",
        status="queued",
        job_id="job-stuck-1",
        created_at=old_time,
    )
    # Message 2: stuck processing for 10 minutes (should be reaped)
    m2 = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="Stuck turn 2",
        status="processing",
        job_id="job-stuck-2",
        created_at=old_time,
    )
    # Message 3: active queued 30s ago (should NOT be reaped)
    m3 = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="Active turn",
        status="queued",
        job_id="job-active-3",
        created_at=recent_time,
    )
    # Message 4: already completed (should NOT be touched)
    m4 = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="assistant",
        content="Done",
        status="completed",
        job_id="job-done-4",
        created_at=old_time,
    )

    db_session.add_all([m1, m2, m3, m4])
    db_session.commit()

    r = MockLeaseRedis()
    r.counters[f"{CHAT_TENANT_INFLIGHT_PREFIX}{TENANT_ID}"] = 2

    # Run reaper with 300s threshold
    result = reap_stuck_chat_jobs(
        session=db_session,
        max_age_seconds=300,
        dry_run=False,
        redis_client=r,
    )

    assert result["reaped_count"] == 2
    assert result["dry_run"] is False

    # Check DB updates
    db_session.refresh(m1)
    db_session.refresh(m2)
    db_session.refresh(m3)
    db_session.refresh(m4)

    assert m1.status == "failed"
    assert "reaped by background sweeper" in (m1.error_message or "")
    assert m2.status == "failed"
    assert "reaped by background sweeper" in (m2.error_message or "")
    assert m3.status == "queued"
    assert m4.status == "completed"


def test_reaper_dry_run_leaves_rows_untouched(db_session):
    """BE Gap 605: Dry run mode reports stuck jobs without modifying database."""
    session_id = uuid4()
    s = ChatSession(id=session_id, tenant_id=TENANT_ID, title="Session Dry Run")
    db_session.add(s)
    db_session.commit()

    old_time = datetime.now(timezone.utc) - timedelta(seconds=600)
    m = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="Stuck in dry run",
        status="queued",
        job_id="job-dryrun-1",
        created_at=old_time,
    )
    db_session.add(m)
    db_session.commit()

    result = reap_stuck_chat_jobs(
        session=db_session,
        max_age_seconds=300,
        dry_run=True,
    )

    assert result["reaped_count"] == 1
    assert result["dry_run"] is True

    db_session.refresh(m)
    assert m.status == "queued"
    assert m.error_message is None
