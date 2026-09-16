import logging
import secrets
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, List, Optional
from config import get_settings

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """
    Sliding-window rate limiter backed by Redis with an in-memory fallback.
    Used to throttle resolve operations (Gap 561) and protect write endpoints.
    """

    def __init__(self, key_prefix: str = "ratelimit:resolve:", max_requests: int = 60, window_seconds: int = 60):
        self.key_prefix = key_prefix
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._memory: OrderedDict[str, List[float]] = OrderedDict()
        self._lock = Lock()
        self._redis_client: Any = None
        # After a Redis failure the limiter degrades to the in-process window and retries
        # Redis after this many seconds, so a transient outage does not pin every replica
        # to its own private counter for the rest of its life.
        self._redis_retry_after: float = 0.0
        self.redis_retry_seconds: float = 30.0

    def _redis(self):
        if self._redis_client is False and time.monotonic() >= self._redis_retry_after:
            self._redis_client = None  # cooldown over: try Redis again
        if self._redis_client is None:
            try:
                import redis

                client = redis.Redis.from_url(
                    get_settings().REDIS_URL, decode_responses=True
                )
                client.ping()
                self._redis_client = client
            except Exception as exc:
                logger.warning(
                    "Rate limiter %s: Redis unavailable (%s); falling back to in-process window.",
                    self.key_prefix,
                    exc,
                )
                self._redis_client = False
                self._redis_retry_after = time.monotonic() + self.redis_retry_seconds
        return self._redis_client if self._redis_client is not False else None

    def check(self, identifier: str) -> bool:
        """Returns True if request is within limits, False if exceeded."""
        key = f"{self.key_prefix}{identifier}"
        client = self._redis()
        if client is not None:
            try:
                now = time.time()
                cutoff = now - self.window_seconds
                pipe = client.pipeline()
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zcard(key)
                counts = pipe.execute()
                current_count = counts[1]
                if int(current_count) >= self.max_requests:
                    return False

                member = f"{now}:{secrets.token_hex(4)}"
                pipe = client.pipeline()
                pipe.zadd(key, {member: now})
                pipe.expire(key, self.window_seconds)
                pipe.execute()
                return True
            except Exception as exc:
                logger.warning("Rate limiter Redis check failed (%s); degrading to in-process.", exc)
                self._redis_client = False
                self._redis_retry_after = time.monotonic() + self.redis_retry_seconds

        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            # Prune stale keys
            stale = [k for k, stamps in self._memory.items() if not any(t > cutoff for t in stamps)]
            for k in stale:
                del self._memory[k]

            live = [t for t in self._memory.get(key, []) if t > cutoff]
            if len(live) >= self.max_requests:
                self._memory[key] = live
                return False

            live.append(now)
            self._memory[key] = live
            self._memory.move_to_end(key)

            while len(self._memory) > 10_000:
                self._memory.popitem(last=False)
            return True

    def reset(self):
        with self._lock:
            self._memory.clear()
        client = self._redis()
        if client is not None:
            try:
                stale = list(client.scan_iter(match=f"{self.key_prefix}*", count=500))
                if stale:
                    client.delete(*stale)
            except Exception:
                pass


def rate_limit_key(context) -> str:
    """The window a resolve call is counted in: the tenant plus the principal acting for it.

    Keyed by tenant alone, one runaway integration key would exhaust the whole tenant's
    window and lock its auditors out of the review console. Keyed per principal, a Clerk
    user and the tenant's API key each get their own 60/min, and the tenant-wide ceiling is
    still bounded by how many principals it has.
    """
    if getattr(context, "auth_method", None) == "api_key":
        principal = f"key:{getattr(context, 'api_key_prefix', None) or '-'}"
    else:
        principal = f"user:{getattr(context, 'user_id', None) or '-'}"
    return f"{context.tenant_id}:{principal}"

