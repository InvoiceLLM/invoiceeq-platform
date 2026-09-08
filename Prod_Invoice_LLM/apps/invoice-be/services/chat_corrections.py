"""Feature 30 task 30.13 (was Feature 29 task 29.19) — the correction flywheel.

THE LOOP
--------
    thumbs-down on a card  ->  record_correction()   -> chat_correction (PENDING)
    a human reviews it     ->  promote_to_example()  -> certified_sql_example
                                                        (certified, retrievable)
                           or  reject_correction()   -> nothing is learned

Three properties make it a flywheel rather than a suggestion box:

1. **A correction is attached to a FINDING, not to a turn.** `ChatFeedback`
   (Gap 54/232) already votes on a whole answer and routes to Feature 18's
   triage. This is narrower on purpose: "the overbilling figure on this bubble
   is wrong because the PO was revised" is a statement about one computation,
   and only a per-card record can be turned into a per-card fix.
2. **Nothing is learned automatically.** A correction is PENDING until a human
   promotes it. The alternative — learning from every thumbs-down — means one
   confused user permanently reshapes every later answer, invisibly.
3. **A promoted correction produces a CERTIFIED example**, which is the only
   kind the retrieval layer will return (30.8). The loop therefore closes on the
   same gate it started from.

Gap 492: a correction never touches an invoice. It records what the user said.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATUS_PENDING = "PENDING"
STATUS_PROMOTED = "PROMOTED"
STATUS_REJECTED = "REJECTED"

#: Why the user says it is wrong. Deliberately the same vocabulary Feature 18
#: uses for turn-level feedback plus one Feature 30 needs, so a reviewer reading
#: both queues sees one set of words.
#:
#:   wrong_figure         -- the number is wrong (the most actionable of all)
#:   wrong_interpretation -- the number is right, the conclusion is not
#:   not_relevant         -- a true finding that does not matter here
#:   wrong_document       -- we linked the wrong invoice
CORRECTION_REASONS = frozenset(
    {"wrong_figure", "wrong_interpretation", "not_relevant", "wrong_document", "other"}
)


class CorrectionError(ValueError):
    """An unknown reason, or a promotion of something that cannot be promoted."""


def record_correction(
    tenant_id: Any,
    db_session: Any,
    *,
    message_id: Any = None,
    insight_id: Any = None,
    card: str | None = None,
    finding_key: str | None = None,
    vote: str = "down",
    reason: str | None = None,
    corrected_text: str | None = None,
    corrected_sql: str | None = None,
    evidence: dict | None = None,
    created_by: str | None = None,
) -> Any:
    """Record one piece of feedback about one card. Always PENDING.

    Everything except the tenant is optional, on purpose: a thumbs-down with no
    explanation is still signal, and requiring prose would suppress the cheapest
    feedback there is.
    """
    from models import ChatCorrection

    if reason is not None and reason not in CORRECTION_REASONS:
        raise CorrectionError(f"Unknown reason {reason!r}. Known: {sorted(CORRECTION_REASONS)}")

    row = ChatCorrection(
        tenant_id=tenant_id,
        message_id=message_id,
        insight_id=insight_id,
        card=card,
        finding_key=finding_key,
        vote=vote,
        reason=reason,
        corrected_text=(corrected_text or None),
        corrected_sql=(corrected_sql or None),
        evidence=evidence,
        status=STATUS_PENDING,
        created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    try:
        import telemetry

        telemetry.track_insight_feedback(
            tenant_id=str(tenant_id),
            card=row.card or "",
            vote=row.vote or "",
            reason=row.reason or "",
            status=row.status,
            promoted=False,
        )
    except Exception as exc:  # pragma: no cover - telemetry never fails a write
        logger.warning("insight_feedback telemetry failed: %s", exc)

    return row


def promote_to_example(
    correction_id: Any,
    db_session: Any,
    tenant_id: Any,
    question: str | None = None,
    sql: str | None = None,
    certified_by: str | None = None,
    doc_type: str | None = None,
) -> Any:
    """Turn a reviewed correction into a certified example. Returns the example.

    Requires SQL — either on the correction (`corrected_sql`, what the user or
    reviewer supplied) or passed in by the reviewer. A promotion with no SQL
    would create an example with nothing to learn from, which is worse than no
    example because it still consumes a slot in the retrieved set.

    Tenant-scoped, and idempotent: promoting twice returns the first example
    rather than writing a second.
    """
    from sqlmodel import select

    from models import ChatCorrection
    from services.certified_examples import certify_example

    row = db_session.exec(
        select(ChatCorrection).where(
            ChatCorrection.id == correction_id, ChatCorrection.tenant_id == tenant_id
        )
    ).first()
    if row is None:
        return None
    if row.status == STATUS_PROMOTED and row.promoted_example_id:
        from models import CertifiedSqlExample

        return db_session.get(CertifiedSqlExample, row.promoted_example_id)
    if row.status == STATUS_REJECTED:
        raise CorrectionError("A rejected correction cannot be promoted.")

    final_sql = sql or row.corrected_sql
    final_question = question or row.corrected_text
    if not (final_sql or "").strip():
        raise CorrectionError(
            "Promoting a correction needs the SQL that answers it correctly."
        )
    if not (final_question or "").strip():
        raise CorrectionError("Promoting a correction needs the question it answers.")

    example = certify_example(
        final_question,
        final_sql,
        db_session,
        tenant_id=tenant_id,
        doc_type=doc_type,
        certified_by=certified_by,
        source_correction_id=row.id,
        certified=True,
    )
    row.status = STATUS_PROMOTED
    row.promoted_example_id = example.id
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return example


def reject_correction(
    correction_id: Any, db_session: Any, tenant_id: Any, note: str | None = None
) -> Any:
    """Close a correction without learning from it. Returns the row.

    Kept as an explicit action rather than leaving it PENDING for ever: "we
    looked and disagreed" and "nobody has looked" are different states, and the
    quality panel counts the second.
    """
    from sqlmodel import select

    from models import ChatCorrection

    row = db_session.exec(
        select(ChatCorrection).where(
            ChatCorrection.id == correction_id, ChatCorrection.tenant_id == tenant_id
        )
    ).first()
    if row is None:
        return None
    if row.status == STATUS_PROMOTED:
        raise CorrectionError("A promoted correction cannot be rejected; retire the example instead.")
    row.status = STATUS_REJECTED
    if note:
        row.corrected_text = (row.corrected_text or "") + f"\n[reviewer] {note}"
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def correction_stats(tenant_id: Any, db_session: Any) -> dict:
    """What the "chat quality trend" panel counts, computed here rather than in KQL.

    The workbook renders this shape; keeping the arithmetic in Python means the
    number in the panel and the number in an API response cannot disagree.
    """
    from sqlmodel import select

    from models import ChatCorrection

    rows = db_session.exec(
        select(ChatCorrection).where(ChatCorrection.tenant_id == tenant_id)
    ).all()
    by_card: dict = {}
    for row in rows:
        by_card.setdefault(row.card or "unknown", 0)
        by_card[row.card or "unknown"] += 1
    return {
        "total": len(rows),
        "pending": sum(1 for r in rows if r.status == STATUS_PENDING),
        "promoted": sum(1 for r in rows if r.status == STATUS_PROMOTED),
        "rejected": sum(1 for r in rows if r.status == STATUS_REJECTED),
        "by_card": by_card,
        "by_reason": {
            reason: sum(1 for r in rows if r.reason == reason)
            for reason in sorted({r.reason for r in rows if r.reason})
        },
    }
