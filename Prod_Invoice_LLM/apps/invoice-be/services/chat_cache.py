"""Chat answer cache versioning and invalidation service.

Addresses BE Gap 576 (CH-9) and BE Gap 577 (CH-10).
- BE Gap 576: Answer cache is restricted to provably self-contained questions.
- BE Gap 577: Invalidation is handled via an O(1) per-tenant data_version integer in Redis,
  bumped by any write touching invoice state (ingestion, status change, correction,
  resolve, line-item edit, deletion).
"""
from __future__ import annotations

import logging
from uuid import UUID
from typing import Any

logger = logging.getLogger(__name__)

CHAT_DATA_VERSION_PREFIX = "chat_data_version:"
DEFAULT_DATA_VERSION = 1


def _get_redis_client():
    from agents.query_agent import _get_redis_client as _get_client
    return _get_client()


def get_tenant_data_version(tenant_id: str | UUID, client: Any = None) -> int:
    """Retrieve the current data version integer for the tenant.

    If Redis is unavailable, unconfigured, or the key is not set, defaults to 1.
    """
    if client is None:
        try:
            client = _get_redis_client()
        except Exception:
            return DEFAULT_DATA_VERSION

    if client is None:
        return DEFAULT_DATA_VERSION

    try:
        val = client.get(f"{CHAT_DATA_VERSION_PREFIX}{tenant_id}")
        if val is None:
            return DEFAULT_DATA_VERSION
        if isinstance(val, bytes):
            val = val.decode("utf-8")
        return int(val)
    except Exception as e:
        logger.debug("Failed to read chat data version for tenant %s: %s", tenant_id, e)
        return DEFAULT_DATA_VERSION


def bump_tenant_data_version(tenant_id: str | UUID, client: Any = None) -> int:
    """Increment the tenant's data version in Redis (BE Gap 577 / CH-10).

    Any write touching invoice state (ingestion, status change, correction,
    resolve, line-item edit, deletion) calls this helper. By incrementing
    the data version, all existing cached answers under previous versions
    become instantly unreachable and will expire on their own TTL.
    No Redis keys scan or deletion required.
    """
    if client is None:
        try:
            client = _get_redis_client()
        except Exception:
            return DEFAULT_DATA_VERSION

    if client is None:
        return DEFAULT_DATA_VERSION

    try:
        new_version = int(client.incr(f"{CHAT_DATA_VERSION_PREFIX}{tenant_id}"))
        # If the key did not exist before incr, incr returned 1 which equals DEFAULT_DATA_VERSION.
        # Advance it to 2 so the bumped version is strictly greater than the initial default.
        if new_version <= DEFAULT_DATA_VERSION:
            new_version = int(client.incr(f"{CHAT_DATA_VERSION_PREFIX}{tenant_id}"))
        logger.info(
            "Bumped chat data version for tenant %s to %d", tenant_id, new_version
        )
        return new_version
    except Exception as e:
        logger.warning(
            "Failed to bump chat data version for tenant %s: %s", tenant_id, e
        )
        return DEFAULT_DATA_VERSION
