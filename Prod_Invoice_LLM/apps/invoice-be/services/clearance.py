"""Feature 33 (ATLAS Analyst Agent) — Role & Clearance Utilities.

Task 33.11: Clearance enforcement across all read paths.

Rules:
- Role assignment: Admin -> exec; Auditor & Trainer -> ops.
- Clearance filter:
    - ops: only rows where clearance == 'ops'.
    - exec: all rows (both 'ops' and 'exec').
"""
from __future__ import annotations

from typing import Any, Optional


def clearance_for_role(role: str) -> str:
    """Map user role to clearance level."""
    if not role:
        return "ops"
    return "exec" if str(role).strip().lower() == "admin" else "ops"


def clearance_filter(stmt: Any, model: Any, clearance: str = "ops") -> Any:
    """Apply clearance predicate to a select statement.

    If clearance is 'exec', returns the statement unchanged (exec can read both ops and exec).
    If clearance is 'ops' (or anything non-exec), filters to model.clearance == 'ops'.
    """
    if str(clearance).strip().lower() == "exec":
        return stmt

    if hasattr(model, "clearance"):
        return stmt.where(model.clearance == "ops")

    return stmt
