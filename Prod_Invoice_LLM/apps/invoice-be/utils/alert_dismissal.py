"""Removing the alerts an auditor dismissed (BE Gaps 537, 538).

Shared by `routers/audit.py` and `routers/outbound_audit.py`.

Before these gaps a dismissal entry was compared with every alert's id, type and
message, and every alert that matched was removed — so dismissing the subtotal's
"not verified in source" alert also removed the grand total's, whose message is
the same formatted number. Now each entry removes at most ONE alert, and the
entries that matched nothing are returned so the caller can say so.

Alerts are not given ids here: they are produced in the extraction pipeline
(`agents/extraction_agent.py`, `queue_worker/handlers.py`), outside the audit
flow. An alert that already carries an `id` is matched by it; any other alert is
matched by type + field + message (founder ruling 2026-09-15), which is exactly
what separates the alerts this gap was about. Two alerts equal in all three are
indistinguishable to the auditor too, and removing one of them is the right result.
"""
from typing import Any, Callable, Optional


def dismiss_alerts(alerts: list, dismissals: list) -> tuple[list, list, list]:
    """Returns `(remaining, dismissed, unmatched)`.

    A dismissal entry is an alert object — `{"id": ...}` or `{"type", "field", "message"}` —
    or, from older integrations, a string naming an alert id, a plain-text alert, a message
    or a type (tried in that order). Each entry removes the first alert it matches.
    """
    remaining = list(alerts)
    dismissed: list = []
    unmatched: list = []
    for entry in dismissals:
        index = _match_index(remaining, entry)
        if index is None:
            unmatched.append(entry)
        else:
            dismissed.append(remaining.pop(index))
    return remaining, dismissed, unmatched


def _match_index(alerts: list, entry: Any) -> Optional[int]:
    if isinstance(entry, dict):
        if entry.get("id") is not None:
            return _first(alerts, lambda a: isinstance(a, dict) and a.get("id") == entry["id"])
        key = (entry.get("type"), entry.get("field"), entry.get("message"))
        index = _first(alerts, lambda a: isinstance(a, dict) and (a.get("type"), a.get("field"), a.get("message")) == key)
        if index is None and entry.get("type") is None and entry.get("field") is None:
            index = _first(alerts, lambda a: isinstance(a, str) and a == entry.get("message"))
        return index
    if isinstance(entry, str):
        for matches in (
            lambda a: isinstance(a, dict) and a.get("id") == entry,
            lambda a: isinstance(a, str) and a == entry,
            lambda a: isinstance(a, dict) and a.get("message") == entry,
            lambda a: isinstance(a, dict) and a.get("type") == entry,
        ):
            index = _first(alerts, matches)
            if index is not None:
                return index
    return None


def _first(alerts: list, predicate: Callable[[Any], bool]) -> Optional[int]:
    return next((i for i, alert in enumerate(alerts) if predicate(alert)), None)
