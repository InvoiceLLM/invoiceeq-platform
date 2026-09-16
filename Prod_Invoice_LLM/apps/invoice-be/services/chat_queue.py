from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import time
from typing import Optional
from uuid import uuid4
import redis
from sqlmodel import Session, select

from config import get_settings
from models import ChatMessage

logger = logging.getLogger(__name__)

# Gap 280 Constants
CHAT_QUEUE_KEY = "chat_tasks_queue"
CHAT_JOB_STATUS_PREFIX = "chat_job_status:"
CHAT_JOB_CHANNEL_PREFIX = "chat_job_channel:"
CHAT_TENANT_INFLIGHT_PREFIX = "chat_inflight:"

# Fair-share concurrency ceiling per tenant (Gap 280)
# Prevents single tenant bursts from monopolizing worker threads or triggering Azure OpenAI 429s
PER_TENANT_MAX_ACTIVE_CHAT = 3
JOB_STATUS_TTL_SECONDS = 3600  # 1 hour TTL for cached job outcomes
CHAT_INFLIGHT_LEASE_TTL_SECONDS = 300  # Gap 605: 5 minutes self-healing lease TTL for tenant concurrency slots

# Gap 364: how long the caller is told to wait before retrying a rejected turn.
# Lives here rather than in the router because the ceiling it belongs to lives
# here -- the router should not have to invent a number for a limit it does not
# own.
CHAT_CAPACITY_RETRY_AFTER_SECONDS = 5

# Gap 365 / Gap 587: Per-session lock constants
CHAT_SESSION_LOCK_PREFIX = "chat_session_lock:"
CHAT_SESSION_LOCK_TTL_SECONDS = 300
CHAT_SESSION_LOCK_WAIT_SECONDS = 120
CHAT_SESSION_LOCK_POLL_SECONDS = 0.1


class ChatSessionLockedError(Exception):
    """Gap 587 (CH-20): A turn is already running in this chat session.

    Founder ruling 2026-09-16: return 409 immediately on lock contention.
    A second turn arriving while the session lock is held is refused with
    'A chat turn is already running in this session.' -- no waiting, no held
    worker thread, no implicit queueing.
    """

    def __init__(
        self,
        session_id: str,
        message: str = "A chat turn is already running in this session.",
    ):
        super().__init__(message)
        self.session_id = session_id
        self.message = message


class ChatQueueCapacityError(Exception):
    """Gap 364: the tenant already has `PER_TENANT_MAX_ACTIVE_CHAT` chat jobs
    in flight, so this turn was not enqueued and no slot is held for it.

    Shaped like `services/sandbox.py::SandboxClaimError`: the machine-readable
    fields (`active`, `limit`, `retry_after_seconds`) are attributes so the
    router can build a status code and a `Retry-After` header without parsing
    prose, and without hard-coding the ceiling a second time.

    Raising is deliberate rather than returning a `{"status": "rejected"}` dict:
    every existing caller of `enqueue_chat_job()` treats its return value as a
    successfully queued job, so a sentinel return would have been silently
    ignored exactly the way the unenforced counter was.
    """

    def __init__(
        self,
        tenant_id: str,
        active: int,
        limit: int = PER_TENANT_MAX_ACTIVE_CHAT,
        retry_after_seconds: int = CHAT_CAPACITY_RETRY_AFTER_SECONDS,
    ):
        message = (
            f"Tenant {tenant_id} already has {min(active, limit)} of {limit} "
            "concurrent chat turns in flight."
        )
        super().__init__(message)
        self.tenant_id = tenant_id
        self.active = active
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        self.message = message


def get_redis_client() -> redis.Redis | None:
    """Returns a connected Redis client, or None if unreachable."""
    try:
        settings = get_settings()
        if not settings.REDIS_URL:
            return None
        return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning("Could not connect to Redis for chat queue: %s", e)
        return None


@contextmanager
def chat_session_lock(
    session_id: str,
    *,
    client: Optional[redis.Redis] = None,
    wait_seconds: float = CHAT_SESSION_LOCK_WAIT_SECONDS,
    ttl_seconds: int = CHAT_SESSION_LOCK_TTL_SECONDS,
    poll_seconds: float = CHAT_SESSION_LOCK_POLL_SECONDS,
    raise_on_contention: bool = False,
):
    """Hold `chat_session_lock:{session_id}` for the duration of one turn.

    Yields True if the lock was really held, False if it was skipped (no Redis,
    no session id) or timed out. Never raises unless raise_on_contention=True:
    Redis being unreachable degrades to today's behaviour (unserialised) rather than
    taking chat down with it, which is criterion 5 of the flip criteria in
    `config.py`.

    If raise_on_contention=True and Redis is reachable and the lock cannot be acquired
    immediately, raises ChatSessionLockedError without waiting (Founder ruling 2026-09-16:
    return 409 immediately on lock contention, no waiting, no held worker thread, no implicit queueing).

    Released with a token check so a turn that overran the TTL cannot delete a
    lock the *next* turn has since acquired.
    """
    r = client
    if r is None and session_id:
        try:
            r = get_redis_client()
        except Exception as e:
            logger.warning("Redis unavailable for chat session lock: %s", e)
            r = None

    key = f"{CHAT_SESSION_LOCK_PREFIX}{session_id}"
    token = str(uuid4())
    acquired = False

    if r is not None and session_id:
        if raise_on_contention:
            try:
                acquired = bool(r.set(key, token, nx=True, ex=ttl_seconds))
            except Exception as e:
                logger.warning(
                    "Could not acquire chat session lock for %s (%s); "
                    "processing without per-session serialisation",
                    session_id, e,
                )
                r = None
                acquired = False

            if not acquired and r is not None:
                raise ChatSessionLockedError(session_id)
        else:
            deadline = time.monotonic() + wait_seconds
            while True:
                try:
                    acquired = bool(r.set(key, token, nx=True, ex=ttl_seconds))
                except Exception as e:
                    # Redis went away mid-wait. Same degradation as above.
                    logger.warning(
                        "Could not acquire chat session lock for %s (%s); "
                        "processing without per-session serialisation",
                        session_id, e,
                    )
                    r = None
                    acquired = False
                    break
                if acquired or time.monotonic() >= deadline:
                    break
                time.sleep(poll_seconds)
            if not acquired and r is not None:
                logger.warning(
                    "Timed out after %ss waiting on chat session lock for %s; "
                    "processing without per-session serialisation",
                    wait_seconds, session_id,
                )

    try:
        yield acquired
    finally:
        if acquired and r is not None:
            try:
                if r.get(key) == token:
                    r.delete(key)
            except Exception as e:
                logger.warning(
                    "Failed to release chat session lock for %s: %s", session_id, e
                )


def is_chat_session_locked(session_id: str, client: Optional[redis.Redis] = None) -> bool:
    """Returns True if a chat turn is currently holding the session lock in Redis."""
    if not session_id:
        return False
    r = client
    if r is None:
        try:
            r = get_redis_client()
        except Exception as e:
            logger.warning("Could not connect to Redis to check session lock: %s", e)
            return False
    if r is None:
        return False
    try:
        val = r.get(f"{CHAT_SESSION_LOCK_PREFIX}{session_id}")
        return val is not None
    except Exception as e:
        logger.warning("Could not check chat session lock for %s: %s", session_id, e)
        return False


class ChatQueueService:
    """Core Service managing asynchronous chat jobs, tenant concurrency limits,
    and real-time event publishing."""

    @staticmethod
    def enqueue_chat_job(
        session_id: str,
        user_msg_id: str,
        content: str,
        tenant_id: str,
        job_id: str | None = None,
        # E-5 / task H7. Optional with a None default, so every existing caller
        # and every existing test body stays valid byte-for-byte -- the same
        # shape C5b used when it threaded the id onto MessageCreate.
        attachment_id: str | None = None,
        # Gap 439: the same shape H7 used for the single id -- optional, default
        # None, so a pre-Phase-2 caller and every existing test body are valid
        # unchanged and a message already in the queue at deploy time still runs.
        attachment_ids: list | None = None,
        client: redis.Redis | None = None,
        db_session: Session | None = None,
    ) -> dict:
        """Enqueues a chat query into the Redis task queue with fair-share throttling.

        Gap 364 made the throttle real. Before it, this function incremented
        `chat_inflight:{tenant_id}` and never compared it to anything --
        `PER_TENANT_MAX_ACTIVE_CHAT` was referenced nowhere in the application,
        so the "fair-share concurrency limiter" enforced no limit at all. Same
        class of defect as Gap 352: a declared meter that did not meter.

        Gap 605 / 601: Slot reservations now use a lease model with TTL and
        per-job tracking (`chat_inflight:{tenant_id}:{job_id}`). If worker
        pods crash without graceful release, slots self-heal when the TTL expires.
        When Redis is unreachable, the concurrency ceiling fails closed by
        verifying in-flight messages against the database (Gap 601).

        Order matters here. The slot is reserved (INCR) and checked *first*, so
        a rejected turn leaves nothing behind at all -- no status blob for a job
        that will never run, and nothing on the queue. The two write steps that
        follow are what the reservation was taken for.

        Returns:
            dict containing `job_id` and initial status (`"queued"`).

        Raises:
            ChatQueueCapacityError: the tenant is already at the ceiling. No
                slot is held and nothing was queued -- the caller may safely
                turn this into a 429 (routers/chat.py does).
        """
        r = client or get_redis_client()
        job_id = job_id or str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        job_payload = {
            "job_id": job_id,
            "session_id": session_id,
            "user_msg_id": user_msg_id,
            "content": content,
            "tenant_id": tenant_id,
            # E-5/H7: WITHOUT this key the worker answers an attached-document
            # question as an ordinary chat turn -- the attachment silently
            # dropped, a plausible answer returned, and nothing to show for it.
            # That is the exact silent-drop failure the pre-route gate exists to
            # prevent, which is why C5b routed these turns AWAY from the queue
            # rather than through it while the key was missing.
            "attachment_id": attachment_id,
            "attachment_ids": attachment_ids,
            "status": "queued",
            "created_at": now_iso,
        }

        enqueued_to_redis = False
        if r:
            slot_reserved = False
            try:
                # 1. Reserve the tenant's in-flight slot, and enforce the
                #    ceiling on the value INCR returned. INCR-then-check rather
                #    than GET-then-INCR: only the atomic return value is safe
                #    against two concurrent turns both reading 2 and both
                #    proceeding. The slot is released again below if we are over.
                inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}"
                active = r.incr(inflight_key)
                slot_reserved = True

                # Gap 605: Set safety TTL on tenant inflight key so crashes self-heal
                if hasattr(r, "expire"):
                    try:
                        r.expire(inflight_key, CHAT_INFLIGHT_LEASE_TTL_SECONDS)
                    except Exception:
                        pass

                try:
                    active_count = int(active)
                except (TypeError, ValueError):
                    active_count = 0

                if active_count > PER_TENANT_MAX_ACTIVE_CHAT:
                    # Gap 605 self-healing: check if counter was orphaned by crashed workers
                    actual_active = None
                    if hasattr(r, "scan_iter"):
                        try:
                            lease_keys = [
                                k for k in r.scan_iter(match=f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}:*", count=50)
                                if k != inflight_key
                            ]
                            actual_active = len(lease_keys)
                        except Exception:
                            actual_active = None

                    if actual_active is not None and actual_active <= PER_TENANT_MAX_ACTIVE_CHAT:
                        try:
                            r.set(inflight_key, actual_active)
                            if hasattr(r, "expire"):
                                r.expire(inflight_key, CHAT_INFLIGHT_LEASE_TTL_SECONDS)
                            active_count = actual_active
                        except Exception:
                            pass

                    if active_count > PER_TENANT_MAX_ACTIVE_CHAT:
                        # Over the ceiling: hand the slot straight back.
                        ChatQueueService.release_tenant_slot(tenant_id, r, job_id=job_id)
                        slot_reserved = False
                        logger.info(
                            "Rejected chat job %s for tenant %s: %s in flight, limit %s",
                            job_id,
                            tenant_id,
                            active_count - 1,
                            PER_TENANT_MAX_ACTIVE_CHAT,
                        )
                        raise ChatQueueCapacityError(
                            tenant_id=tenant_id,
                            active=active_count,
                            limit=PER_TENANT_MAX_ACTIVE_CHAT,
                        )

                # 2. Store initial job status cache
                r.set(
                    f"{CHAT_JOB_STATUS_PREFIX}{job_id}",
                    json.dumps(job_payload),
                    ex=JOB_STATUS_TTL_SECONDS,
                )

                # Gap 605: Per-job lease key with TTL for accepted jobs
                job_lease_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}:{job_id}"
                try:
                    r.set(job_lease_key, "1", ex=CHAT_INFLIGHT_LEASE_TTL_SECONDS)
                except Exception:
                    pass

                # 3. Push to queue
                r.lpush(CHAT_QUEUE_KEY, json.dumps(job_payload))
                enqueued_to_redis = True

                logger.info(
                    "Enqueued chat job %s for tenant %s (session %s)",
                    job_id,
                    tenant_id,
                    session_id,
                )
            except ChatQueueCapacityError:
                raise
            except Exception as e:
                enqueued_to_redis = False
                # Gap 364 / 605: give the slot and lease back before swallowing
                if slot_reserved:
                    ChatQueueService.release_tenant_slot(tenant_id, r, job_id=job_id)
                logger.error("Failed to enqueue chat job %s to Redis: %s", job_id, e)
        else:
            # Gap 601 (CH-34): Concurrency ceiling fail-closed check when Redis is unconfigured or unreachable.
            # Query the database for active (queued or processing) turns for this tenant.
            session_to_close = None
            try:
                cur_session = db_session
                if cur_session is None:
                    try:
                        from database import engine
                        if engine:
                            session_to_close = Session(engine)
                            cur_session = session_to_close
                    except Exception:
                        cur_session = None

                if cur_session is not None:
                    from models import ChatSession
                    from uuid import UUID
                    try:
                        t_uuid = UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
                    except Exception:
                        t_uuid = None

                    if t_uuid:
                        msg_uuid = None
                        if user_msg_id:
                            try:
                                msg_uuid = UUID(user_msg_id) if isinstance(user_msg_id, str) else user_msg_id
                            except Exception:
                                pass

                        conditions = [
                            ChatSession.tenant_id == t_uuid,
                            ChatMessage.status.in_(["queued", "processing"]),
                        ]
                        if msg_uuid:
                            conditions.append(ChatMessage.id != msg_uuid)
                        if job_id:
                            conditions.append(ChatMessage.job_id != job_id)

                        stmt = (
                            select(ChatMessage.id)
                            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
                            .where(*conditions)
                        )
                        active_msgs = cur_session.exec(stmt).all()
                        active_db_count = len(active_msgs)
                        if active_db_count >= PER_TENANT_MAX_ACTIVE_CHAT:
                            raise ChatQueueCapacityError(
                                tenant_id=str(tenant_id),
                                active=active_db_count + 1,
                                limit=PER_TENANT_MAX_ACTIVE_CHAT,
                            )
            finally:
                if session_to_close:
                    session_to_close.close()

        return {"job_id": job_id, "status": "queued", "created_at": now_iso, "enqueued": enqueued_to_redis}

    @staticmethod
    def enqueue_attachment_extraction(
        attachment_id: str,
        tenant_id: str,
        job_id: str | None = None,
        client: "redis.Redis | None" = None,
    ) -> dict | None:
        """Feature 26 Phase 3.3 (Gap 452): queue one attachment's extraction.

        Rides the SAME list the chat jobs use, tagged with a `task` key, so the
        worker's existing drain and the browser's existing SSE channel both work
        unchanged. A second queue would have needed a second drain loop, a second
        channel and a second failure mode, for one more job type.

        It deliberately does NOT take a tenant chat slot. Gap 364's ceiling
        exists to stop one tenant's QUESTIONS starving another's; charging an
        upload against it would let a user who attached three documents be
        unable to ask anything about them.

        Returns None when Redis is unreachable, and that return value is the
        caller's instruction to extract inline instead -- an upload must not fail
        because a queue is down.
        """
        r = client or get_redis_client()
        if not r:
            return None

        job_id = job_id or str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "task": "extract_attachment",
            "job_id": job_id,
            "attachment_id": attachment_id,
            "tenant_id": tenant_id,
            "status": "queued",
            "created_at": now_iso,
        }
        try:
            r.set(
                f"{CHAT_JOB_STATUS_PREFIX}{job_id}",
                json.dumps(payload),
                ex=JOB_STATUS_TTL_SECONDS,
            )
            r.lpush(CHAT_QUEUE_KEY, json.dumps(payload))
        except Exception as e:
            logger.error("Failed to enqueue attachment extraction %s: %s", attachment_id, e)
            return None
        return {"job_id": job_id, "status": "queued", "created_at": now_iso}

    @staticmethod
    def enqueue_insight_job(
        attachment_id: str,
        tenant_id: str,
        message_id: str | None = None,
        job_id: str | None = None,
        client: "redis.Redis | None" = None,
        notify_job_id: str | None = None,
    ) -> dict | None:
        """Feature 30 task 30.2: queue stage 2 of one attachment's insight bubble.

        `notify_job_id` (Gap 497) is the EXTRACTION job's id -- the channel the
        browser is already listening on. The worker publishes `insight_update`
        there; the insight job's own id is only its queue identity.

        Rides the same list as the chat turns and the attachment extractions,
        tagged `task: "insight"`, for the reason `enqueue_attachment_extraction()`
        already gives: a second queue would need a second drain loop, a second
        channel and a second failure mode.

        Like the extraction job and unlike a chat turn, it does NOT take a tenant
        chat slot. Gap 364's ceiling exists to stop one tenant's QUESTIONS
        starving another's, and an insight update is not a question -- charging
        it would mean a user who uploaded three documents could not ask anything
        about them.

        `message_id` is the assistant turn the SYNC stage already posted. The job
        updates THAT message in place (§8.6 step 4); without it the worker would
        post a second bubble that argues with the first.

        Returns None when Redis is unreachable, and that is not an error: the
        sync bubble is already on screen with a template verdict that is true.
        The async stage is an improvement, never a prerequisite.
        """
        r = client or get_redis_client()
        if not r:
            return None

        job_id = job_id or str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "task": "insight",
            "job_id": job_id,
            "attachment_id": attachment_id,
            "tenant_id": tenant_id,
            "message_id": message_id,
            "notify_job_id": notify_job_id,
            "status": "queued",
            "created_at": now_iso,
        }
        try:
            r.set(
                f"{CHAT_JOB_STATUS_PREFIX}{job_id}",
                json.dumps(payload),
                ex=JOB_STATUS_TTL_SECONDS,
            )
            r.lpush(CHAT_QUEUE_KEY, json.dumps(payload))
        except Exception as e:
            logger.error("Failed to enqueue insight job for %s: %s", attachment_id, e)
            return None
        return {"job_id": job_id, "status": "queued", "created_at": now_iso}

    @staticmethod
    def publish_progress(
        job_id: str,
        step: str,
        details: dict | str | None = None,
        client: redis.Redis | None = None,
    ) -> None:
        """Publishes an intermediate progress update to the job's Redis Pub/Sub channel."""
        r = client or get_redis_client()
        if not r:
            return

        event_payload = {
            "job_id": job_id,
            "status": "processing",
            "step": step,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Update cache status
            status_key = f"{CHAT_JOB_STATUS_PREFIX}{job_id}"
            existing = r.get(status_key)
            if existing:
                try:
                    data = json.loads(existing)
                    data.update({"status": "processing", "step": step, "details": details})
                    r.set(status_key, json.dumps(data), ex=JOB_STATUS_TTL_SECONDS)
                except Exception:
                    pass

            # Publish to channel
            channel = f"{CHAT_JOB_CHANNEL_PREFIX}{job_id}"
            r.publish(channel, json.dumps(event_payload))
        except Exception as e:
            logger.warning("Failed to publish progress for chat job %s: %s", job_id, e)

    @staticmethod
    def complete_job(
        job_id: str,
        tenant_id: str,
        result_payload: dict,
        client: redis.Redis | None = None,
    ) -> None:
        """Marks a chat job as completed, publishes final payload, and releases tenant slot."""
        r = client or get_redis_client()
        now_iso = datetime.now(timezone.utc).isoformat()

        if r:
            try:
                # 1. Update status cache with result
                final_data = {
                    "job_id": job_id,
                    "status": "completed",
                    "step": "completed",
                    "result": result_payload,
                    "completed_at": now_iso,
                }
                r.set(
                    f"{CHAT_JOB_STATUS_PREFIX}{job_id}",
                    json.dumps(final_data),
                    ex=JOB_STATUS_TTL_SECONDS,
                )

                # 2. Publish completion event
                channel = f"{CHAT_JOB_CHANNEL_PREFIX}{job_id}"
                r.publish(channel, json.dumps(final_data))

                # 3. Release tenant concurrency slot and per-job lease (Gap 605)
                ChatQueueService.release_tenant_slot(tenant_id, r, job_id=job_id)
            except Exception as e:
                logger.error("Error finalizing chat job %s in Redis: %s", job_id, e)

    #: Gap 500. An extraction job whose insight stage was queued keeps its SSE
    #: stream open until the insight job has published `insight_update`; the
    #: extraction result is parked here and the insight job completes both.
    DEFERRED_RESULT_PREFIX = "chat_job_deferred:"

    @staticmethod
    def defer_completion(job_id: str, result_payload: dict, client: "redis.Redis | None" = None) -> bool:
        """Park an extraction job's final payload instead of completing it now.

        The browser's stream on `job_id` closes on the first `completed`
        status, and the second-pass bubble arrives later on the same channel
        (Gap 497). So the extraction job stays `processing` with a
        `insight_pending` step until `complete_deferred()` runs. Returns False
        (and the caller completes normally) when Redis is unreachable.
        """
        r = client or get_redis_client()
        if not r:
            return False
        try:
            r.set(
                f"{ChatQueueService.DEFERRED_RESULT_PREFIX}{job_id}",
                json.dumps(result_payload),
                ex=JOB_STATUS_TTL_SECONDS,
            )
            ChatQueueService.publish_progress(job_id, "insight_pending", {"attachment_id": result_payload.get("attachment_id")})
            return True
        except Exception as e:
            logger.error("Could not defer completion of job %s: %s", job_id, e)
            return False

    @staticmethod
    def complete_deferred(job_id: str | None, tenant_id: str, extra: dict | None = None, client: "redis.Redis | None" = None) -> bool:
        """Complete a job parked by `defer_completion()`. No-op (False) when
        nothing was parked -- the extraction job then already completed itself."""
        if not job_id:
            return False
        r = client or get_redis_client()
        if not r:
            return False
        try:
            key = f"{ChatQueueService.DEFERRED_RESULT_PREFIX}{job_id}"
            raw = r.get(key)
            if not raw:
                return False
            payload = json.loads(raw)
            payload.update(extra or {})
            r.delete(key)
        except Exception as e:
            logger.error("Could not read deferred result for job %s: %s", job_id, e)
            return False
        ChatQueueService.complete_job(job_id, tenant_id, payload, client=r)
        return True

    @staticmethod
    def fail_job(
        job_id: str,
        tenant_id: str,
        error_message: str,
        client: redis.Redis | None = None,
    ) -> None:
        """Marks a chat job as failed, publishes failure notice, and releases tenant slot."""
        r = client or get_redis_client()
        now_iso = datetime.now(timezone.utc).isoformat()

        if r:
            try:
                fail_data = {
                    "job_id": job_id,
                    "status": "failed",
                    "step": "failed",
                    "error": error_message,
                    "failed_at": now_iso,
                }
                r.set(
                    f"{CHAT_JOB_STATUS_PREFIX}{job_id}",
                    json.dumps(fail_data),
                    ex=JOB_STATUS_TTL_SECONDS,
                )

                # Publish error event
                channel = f"{CHAT_JOB_CHANNEL_PREFIX}{job_id}"
                r.publish(channel, json.dumps(fail_data))

                # Release tenant concurrency slot and per-job lease (Gap 605)
                ChatQueueService.release_tenant_slot(tenant_id, r, job_id=job_id)
            except Exception as e:
                logger.error("Error failing chat job %s in Redis: %s", job_id, e)

    @staticmethod
    def release_tenant_slot(tenant_id: str, client: redis.Redis | None = None, job_id: str | None = None) -> None:
        """Safely decrements the tenant in-flight counter (clamped at >= 0) and deletes per-job lease (Gap 605)."""
        r = client or get_redis_client()
        if not r:
            return
        try:
            # Clear per-job lease if job_id provided
            if job_id and hasattr(r, "delete"):
                try:
                    r.delete(f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}:{job_id}")
                except Exception:
                    pass

            key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}"
            val = r.decr(key)
            if isinstance(val, int) and val < 0:
                r.set(key, 0)
        except Exception as e:
            logger.warning("Failed to release tenant slot for %s: %s", tenant_id, e)

    @staticmethod
    def get_job_status(
        job_id: str,
        db_session: Session | None = None,
        client: redis.Redis | None = None,
    ) -> dict:
        """Retrieves real-time status of a job from Redis or PostgreSQL fallback."""
        r = client or get_redis_client()
        if r:
            try:
                cached = r.get(f"{CHAT_JOB_STATUS_PREFIX}{job_id}")
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning("Could not read job status from Redis for %s: %s", job_id, e)

        # Fallback to database lookup if provided
        if db_session:
            statement = select(ChatMessage).where(ChatMessage.job_id == job_id)
            msg = db_session.exec(statement).first()
            if msg:
                return {
                    "job_id": job_id,
                    "status": msg.status,
                    "error": msg.error_message,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }

        return {"job_id": job_id, "status": "unknown"}

    @staticmethod
    def get_tenant_inflight_count(tenant_id: str, client: redis.Redis | None = None) -> int:
        """Returns the current number of active in-flight chat jobs for the tenant."""
        r = client or get_redis_client()
        if not r:
            return 0
        try:
            val = r.get(f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_id}")
            return int(val) if val else 0
        except Exception:
            return 0
