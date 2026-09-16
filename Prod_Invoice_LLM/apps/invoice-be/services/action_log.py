"""Feature 33 Task 33.26 — Action Execution & Audit Logging.

WHAT THIS MODULE DOES
---------------------
1. `log_action()`: Writes one `ActionLog` row in the same DB transaction as the action execution.
2. `execute_action()`:
   - Validates role permissions using `agents.capabilities.role_allows()`.
   - Executes the action capability's `fn` exactly once.
   - Logs the outcome (success or error) via `log_action()`.
   - Never retries silently on failure.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union
from uuid import UUID

from sqlmodel import Session

from models import ActionLog
from agents.capabilities import ACTIONS, role_allows
from config import get_settings

logger = logging.getLogger(__name__)


class ActionPermissionError(PermissionError):
    """Raised when a user role is not permitted to execute an action."""


class ActionExecutionError(RuntimeError):
    """Raised when an action execution fails."""


def log_action(
    tenant_id: Union[str, UUID],
    user_id: str,
    capability: str,
    args: Optional[dict] = None,
    result: Optional[dict] = None,
    db_session: Optional[Session] = None,
    outcome: str = "success",
    error_message: Optional[str] = None,
) -> ActionLog:
    """Write an ActionLog entry to DB in the current session."""
    t_uuid = UUID(str(tenant_id)) if isinstance(tenant_id, (str, UUID)) else tenant_id
    entry = ActionLog(
        tenant_id=t_uuid,
        user_id=str(user_id),
        capability=str(capability),
        args=args or {},
        result=result or {},
        outcome=outcome,
        error_message=error_message,
    )
    if db_session is not None:
        db_session.add(entry)
        db_session.flush()
    return entry


def execute_action(
    tenant_id: Union[str, UUID],
    user_id: str,
    capability_name: str,
    args: Optional[dict] = None,
    role: str = "Admin",
    db_session: Optional[Session] = None,
    enforce_feature_flag: bool = True,
) -> dict:
    """Execute a confirmed action capability with role gating and audit logging.

    Steps:
    1. Role gate: role_allows(capability_name, role) -> raises ActionPermissionError if denied.
    2. Global feature flag gate: ENABLE_ANALYST_ACTIONS check (if enforce_feature_flag=True).
    3. Lookup in ACTIONS registry.
    4. Execute capability function.
    5. Log action execution in db_session.
    """
    args = args or {}
    t_uuid = UUID(str(tenant_id))

    # 1. Role permission check
    if not role_allows(capability_name, role):
        logger.warning(
            "execute_action: role %r denied for capability %r (tenant=%s user=%s)",
            role, capability_name, tenant_id, user_id,
        )
        raise ActionPermissionError(f"Role '{role}' is not permitted to execute '{capability_name}'")

    # 2. Global feature flag check (defense-in-depth)
    if enforce_feature_flag:
        settings = get_settings()
        if not getattr(settings, "ENABLE_ANALYST_ACTIONS", False):
            logger.warning(
                "execute_action: ENABLE_ANALYST_ACTIONS is False (tenant=%s user=%s capability=%s)",
                tenant_id, user_id, capability_name,
            )
            raise ActionPermissionError("Analyst actions are currently disabled tenant-wide.")

    cap = ACTIONS.get(capability_name)
    if cap is None:
        logger.error("execute_action: unknown action capability %r", capability_name)
        raise ActionExecutionError(f"Unknown action capability '{capability_name}'")

    if cap.fn is None:
        logger.info(
            "execute_action: stub capability %r executed with args %s",
            capability_name, args,
        )
        res = {"ok": True, "action": capability_name, "status": "executed_stub"}
        if db_session:
            log_action(t_uuid, user_id, capability_name, args, res, db_session, outcome="success")
        return res

    # 3. Execute
    try:
        res = cap.fn(tenant_id=t_uuid, user_id=user_id, db_session=db_session, **args)
        if not isinstance(res, dict):
            res = {"result": res, "ok": True}
        if db_session:
            log_action(t_uuid, user_id, capability_name, args, res, db_session, outcome="success")
        return res
    except Exception as exc:
        logger.error(
            "execute_action: execution of %r failed for tenant %s: %s",
            capability_name, tenant_id, exc, exc_info=True,
        )
        if db_session:
            log_action(
                t_uuid, user_id, capability_name, args, None,
                db_session, outcome="failure", error_message=str(exc),
            )
        raise ActionExecutionError(f"Action '{capability_name}' failed: {exc}") from exc
