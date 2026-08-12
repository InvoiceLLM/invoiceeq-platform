"""Redis-backed store for transient AI Trainer sandbox sessions.

Feature 10 Task 10.9: the trainer sandbox used to keep active sessions in an
in-process ``TRAINER_SESSIONS: dict`` inside ``routers/trainer.py``. That breaks
as soon as ``invoice-be`` runs more than one replica — a follow-up ``/chat`` or
``/commit`` request can land on a different worker that never saw the session.

This module stores each session as a JSON blob in Redis under a TTL, so any
replica can serve any follow-up request and stale sessions expire on their own.

Session dict shape (built by ``routers/trainer.py``):
    {
        "session_id":        str,
        "tenant_id":         str,
        "scope":             "global" | "existing_vendor" | "new_vendor",
        "vendor_name":       str | None,
        "file_path":         str | None,   # transient PDF path, or a production invoice's blob path
        "sample_invoice_id": str | None,   # set for existing_vendor sessions (drives the PDF viewer URL)
        "ocr_text":          str,
        "constraints":       list[str],    # active rule candidates
        "extracted_data":    dict,         # latest extraction result
        "chat_history":      list[dict],   # [{id, sender, text, timestamp, suggestedRule?}]
        "created_at":        str,          # ISO timestamp
    }

If Redis cannot be reached (e.g. local dev without Redis running), the store
transparently falls back to an in-process dict and logs a warning. In a real
multi-replica deployment Redis is always present, so the fallback only affects
single-process local/test runs — it never silently degrades production.
"""

import json
import logging
import threading
from typing import Any

import redis

from config import get_settings

logger = logging.getLogger(__name__)

# Sessions are short-lived sandbox scratch space; expire them after an hour of inactivity.
SESSION_TTL_SECONDS = 3600
_KEY_PREFIX = "trainer:session:"

# _redis_client is a small state machine:
#   None  -> not yet initialised
#   False -> tried and unavailable (use the in-process fallback)
#   client-> a live, ping'd Redis connection
_redis_client: Any = None

# Dev/test-only fallback used when Redis is unavailable. Not shared across replicas.
#
# Guarded by _memory_lock: FastAPI runs sync endpoints on a threadpool, so two
# requests can hit the fallback concurrently. Plain dict mutation from several
# threads can raise "RuntimeError: dictionary changed size during iteration"
# (Gap 211). Every read/write/delete below takes the lock; the critical sections
# are single dict operations, so contention is negligible.
_memory_lock = threading.Lock()
_memory_store: dict[str, str] = {}


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


def _get_redis():
    """Return a live Redis client, or None if Redis is unavailable (fallback mode)."""
    global _redis_client
    if _redis_client is None:
        try:
            client = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
            client.ping()
            _redis_client = client
        except Exception as e:  # connection refused, bad URL, etc.
            logger.warning(
                "Trainer session store: Redis unavailable (%s); using in-process fallback.", e
            )
            _redis_client = False
    return _redis_client or None


def save_session(session_id: str, data: dict, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
    """Persist (or overwrite) a session and (re)set its TTL."""
    payload = json.dumps(data, default=str)
    client = _get_redis()
    if client is not None:
        client.set(_key(session_id), payload, ex=ttl_seconds)
    else:
        with _memory_lock:
            _memory_store[_key(session_id)] = payload


def get_session(session_id: str) -> dict | None:
    """Load a session by id, or None if it doesn't exist / has expired."""
    client = _get_redis()
    if client is not None:
        raw = client.get(_key(session_id))
    else:
        with _memory_lock:
            raw = _memory_store.get(_key(session_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as e:
        logger.warning("Trainer session store: could not decode session %s: %s", session_id, e)
        return None


def update_session(session_id: str, changes: dict, ttl_seconds: int = SESSION_TTL_SECONDS) -> dict | None:
    """Merge top-level keys into an existing session and re-save it (refreshing TTL).

    Returns the updated session, or None if the session no longer exists.
    """
    session = get_session(session_id)
    if session is None:
        return None
    session.update(changes)
    save_session(session_id, session, ttl_seconds=ttl_seconds)
    return session


def delete_session(session_id: str) -> None:
    """Remove a session (called on commit / cleanup)."""
    client = _get_redis()
    if client is not None:
        client.delete(_key(session_id))
    else:
        with _memory_lock:
            _memory_store.pop(_key(session_id), None)
