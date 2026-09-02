import json
import logging
from datetime import datetime, timezone
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

# Gap 364: how long the caller is told to wait before retrying a rejected turn.
# Lives here rather than in the router because the ceiling it belongs to lives
# here -- the router should not have to invent a number for a limit it does not
# own.
CHAT_CAPACITY_RETRY_AFTER_SECONDS = 5


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
        client: redis.Redis | None = None,
    ) -> dict:
        """Enqueues a chat query into the Redis task queue with fair-share throttling.

        Gap 364 made the throttle real. Before it, this function incremented
        `chat_inflight:{tenant_id}` and never compared it to anything --
        `PER_TENANT_MAX_ACTIVE_CHAT` was referenced nowhere in the application,
        so the "fair-share concurrency limiter" enforced no limit at all. Same
        class of defect as Gap 352: a declared meter that did not meter.

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
            "status": "queued",
            "created_at": now_iso,
        }

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

                try:
                    active_count = int(active)
                except (TypeError, ValueError):
                    # Counter unreadable (non-numeric value in the key). Fail
                    # open -- this limiter exists to smooth bursts, not to
                    # authorise anything, so a broken counter must not deny an
                    # otherwise valid turn.
                    active_count = 0

                if active_count > PER_TENANT_MAX_ACTIVE_CHAT:
                    # Over the ceiling: hand the slot straight back. Not doing
                    # this would leave the counter permanently above the limit
                    # and lock the tenant out for good, since nothing else ever
                    # decrements it for a job that never ran.
                    ChatQueueService.release_tenant_slot(tenant_id, r)
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

                # 3. Push to queue
                r.lpush(CHAT_QUEUE_KEY, json.dumps(job_payload))

                logger.info(
                    "Enqueued chat job %s for tenant %s (session %s)",
                    job_id,
                    tenant_id,
                    session_id,
                )
            except ChatQueueCapacityError:
                raise
            except Exception as e:
                # Gap 364, second half: this except used to swallow a failed
                # `lpush` that happened AFTER the INCR, leaking a slot that
                # nothing would ever release -- three such failures and the
                # tenant could never chat again until the key expired (it has no
                # TTL) or was deleted by hand. Give the slot back before
                # swallowing.
                if slot_reserved:
                    ChatQueueService.release_tenant_slot(tenant_id, r)
                logger.error("Failed to enqueue chat job %s to Redis: %s", job_id, e)

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

                # 3. Release tenant concurrency slot
                ChatQueueService.release_tenant_slot(tenant_id, r)
            except Exception as e:
                logger.error("Error finalizing chat job %s in Redis: %s", job_id, e)

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

                # Release tenant concurrency slot
                ChatQueueService.release_tenant_slot(tenant_id, r)
            except Exception as e:
                logger.error("Error failing chat job %s in Redis: %s", job_id, e)

    @staticmethod
    def release_tenant_slot(tenant_id: str, client: redis.Redis | None = None) -> None:
        """Safely decrements the tenant in-flight counter (clamped at >= 0)."""
        r = client or get_redis_client()
        if not r:
            return
        try:
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
