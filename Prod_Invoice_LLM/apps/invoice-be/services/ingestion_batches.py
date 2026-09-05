"""BE Gap 464 — record one ingestion RUN, from whichever door started it.

Every ingestion door already mints a `batch_id` and stamps it on the rows it
creates. This module is the one line each of those doors gains: a durable
`IngestionBatch` row so the run itself is a fact, not something inferred from
its output. See `models.IngestionBatch`'s docstring for why inference is not
sufficient (a run that produces no `Invoice` row is not hypothetical — it is
Feature 27 decision E10's ordinary case).

Deliberately ONE function with a swallow-and-log failure mode. The doors this is
called from are the upload endpoint, the inbound-mail webhook and the connector
queue handler; a bookkeeping row that could not be written must never turn a
successful ingestion into a 500. A missing history line is a visibility defect;
a refused upload is a product outage. The log line is ERROR precisely so the
first one is still noticed.

Autopilot is NOT written here. `services/autopilot_sync.py` already writes
`tenant_autopilot_logs` with a `batch_id` and a `trigger` (Gap 427), and the
History screen reads that table through unchanged — the founder's decision was
explicit that the Autopilot screen and its table are untouched by Gap 464.
"""
import logging
from datetime import datetime
from uuid import UUID

from sqlmodel import Session

from models import IngestionBatch

logger = logging.getLogger(__name__)

# The three doors a tenant can start a run from. Autopilot is absent on purpose
# (see the module docstring); the History screen synthesises its own
# `trigger: "autopilot"` when it merges `tenant_autopilot_logs` in.
TRIGGERS = ("manual", "email", "connector")


def record_ingestion_batch(
    db_session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    trigger: str,
    file_count: int,
    flow_direction: str = "INBOUND",
    started_at: datetime | None = None,
) -> IngestionBatch | None:
    """Write the `IngestionBatch` row for one run. Returns it, or None on failure.

    Idempotent by primary key: a door that calls this twice for the same
    `batch_id` (a retry, a re-entrant handler) updates the existing row's
    `file_count` rather than raising an integrity error. `started_at` and
    `archived_at` are left alone on that second call — the run started when it
    started, and a re-record must not silently un-archive a row the user
    archived.
    """
    if trigger not in TRIGGERS:
        # Deterministic guard rather than a free-text column: the History
        # screen's trigger filter is a fixed set of chips, and a typo'd value
        # would render as a run nothing can filter to.
        raise ValueError(
            f"Unknown ingestion trigger {trigger!r}; expected one of {TRIGGERS}."
        )
    try:
        existing = db_session.get(IngestionBatch, batch_id)
        if existing is not None:
            existing.file_count = file_count
            existing.flow_direction = flow_direction
            db_session.add(existing)
            db_session.commit()
            return existing

        row = IngestionBatch(
            batch_id=batch_id,
            tenant_id=tenant_id,
            flow_direction=flow_direction,
            trigger=trigger,
            file_count=file_count,
            started_at=started_at or datetime.utcnow(),
        )
        db_session.add(row)
        db_session.commit()
        return row
    except Exception as exc:  # pragma: no cover - defensive, see module docstring
        logger.error(
            "Gap 464: failed to record ingestion batch %s (tenant %s, trigger %s): %s",
            batch_id, tenant_id, trigger, exc,
        )
        try:
            db_session.rollback()
        except Exception:
            pass
        return None
