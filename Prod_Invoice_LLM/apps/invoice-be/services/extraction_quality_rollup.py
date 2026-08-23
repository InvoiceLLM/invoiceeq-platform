"""
Feature 23 (2026-08-23 rescope) — extraction quality rollups.

Field-level correction rate and alert precision, computed from the audit
trail `RESOLVE_INVOICE`/`REOPEN_INVOICE` already writes in
`routers/audit.py::_apply_corrections()` and its caller — no new event
logging needed, this reads what's already durably recorded per resolve:

    details = {
        "corrections": {field: {"old": ..., "new": ...}, ...},  # only changed fields
        "previous_alerts": [{"type", "message", "field"?}, ...],
        "dismissed_alerts_input": [alert_id/type/message, ...],
        "remaining_alerts": [...],
    }

Two things this can measure that nothing else in the app currently rolls up:

- **Field correction rate**: how often a given field actually gets changed by
  a human at resolve time — the real accuracy signal, since it's a human
  catching a real extraction error, not a proxy.
- **Alert precision**: of the alerts a human explicitly dismissed, how many
  were dismissed *with* a matching field correction (a real issue, fixed) vs.
  dismissed with no correction at all (more likely a false positive) — an
  alert is matched to a correction via its own `field` key, same linkage the
  FE review console already uses (Gap 112 item 4).

Deliberately NOT measured here (see feature_23_ai_control_tower.md's "Known,
accepted gap"): alert *recall* (issues never flagged at all) — that needs the
seeded-document benchmark (Track 1), not a rollup over real resolves, since a
missed alert leaves no trace in this data by definition.
"""
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from models import AuditLog

_RESOLVE_ACTIONS = ("RESOLVE_INVOICE", "REOPEN_INVOICE")


def _resolve_logs(db_session: Session, tenant_id: UUID, since: datetime | None):
    query = select(AuditLog).where(
        AuditLog.tenant_id == tenant_id,
        AuditLog.action.in_(_RESOLVE_ACTIONS),  # type: ignore[attr-defined]
    )
    if since is not None:
        query = query.where(AuditLog.timestamp >= since)
    return db_session.exec(query).all()


def field_correction_rollup(
    db_session: Session, tenant_id: UUID, since: datetime | None = None
) -> list[dict[str, Any]]:
    """One row per corrected field: how many resolves touched it, out of how
    many resolves total in the window — the correction *rate*, not just a
    raw count, since a rare field correcting 100% of the time it appears is a
    different signal than a common field correcting 1% of the time."""
    logs = _resolve_logs(db_session, tenant_id, since)
    total_resolves = len(logs)
    field_counts: dict[str, int] = defaultdict(int)

    for log in logs:
        corrections = (log.details or {}).get("corrections") or {}
        for field in corrections:
            field_counts[field] += 1

    return sorted(
        (
            {
                "field": field,
                "correction_count": count,
                "total_resolves": total_resolves,
                "correction_rate": round(count / total_resolves, 4) if total_resolves else None,
            }
            for field, count in field_counts.items()
        ),
        key=lambda r: r["correction_count"],
        reverse=True,
    )


def _alert_key(alert: Any) -> str | None:
    """The same identity a dismissal is matched against in
    `routers/audit.py`'s resolve handler — id, then type, then message."""
    if isinstance(alert, str):
        return alert
    if isinstance(alert, dict):
        return alert.get("id") or alert.get("type") or alert.get("message")
    return None


def alert_precision_rollup(
    db_session: Session, tenant_id: UUID, since: datetime | None = None
) -> list[dict[str, Any]]:
    """One row per alert type: how many dismissals of that type carried a
    matching field correction (true positive) vs. none (likely false
    positive). `type` is preferred over id/message as the grouping key since
    it's the one stable, human-meaningful label across many invoices."""
    logs = _resolve_logs(db_session, tenant_id, since)
    corrected: dict[str, int] = defaultdict(int)
    uncorrected: dict[str, int] = defaultdict(int)

    for log in logs:
        details = log.details or {}
        previous_alerts = details.get("previous_alerts") or []
        dismissed_input = set(details.get("dismissed_alerts_input") or [])
        corrections = details.get("corrections") or {}

        for alert in previous_alerts:
            if not isinstance(alert, dict):
                continue
            key = _alert_key(alert)
            if key is None or key not in dismissed_input:
                continue  # not dismissed in this resolve
            alert_type = alert.get("type") or "unknown"
            alert_field = alert.get("field")
            if alert_field and alert_field in corrections:
                corrected[alert_type] += 1
            else:
                uncorrected[alert_type] += 1

    all_types = set(corrected) | set(uncorrected)
    return sorted(
        (
            {
                "alert_type": alert_type,
                "dismissed_with_correction": corrected.get(alert_type, 0),
                "dismissed_without_correction": uncorrected.get(alert_type, 0),
                "total_dismissed": corrected.get(alert_type, 0) + uncorrected.get(alert_type, 0),
                "precision": round(
                    corrected.get(alert_type, 0)
                    / (corrected.get(alert_type, 0) + uncorrected.get(alert_type, 0)),
                    4,
                )
                if (corrected.get(alert_type, 0) + uncorrected.get(alert_type, 0)) > 0
                else None,
            }
            for alert_type in all_types
        ),
        key=lambda r: r["total_dismissed"],
        reverse=True,
    )
