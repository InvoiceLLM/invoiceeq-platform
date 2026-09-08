"""Feature 30 task 30.0e — the insight lifecycle.

WHY A LIFECYCLE AND NOT A PIN
-----------------------------
The original spec (section 1) made the intelligence bubble temporary unless the
user pinned it. Ruling R1 replaced that: a finding is a piece of work, not a
rendering. "Shree Packaging billed 23,200 over the PO" is either dealt with or
it is not, and that state has to survive the chat message, the session, and the
chat-document TTL. Pinning a *message* was a worse way of tracking a *finding*,
so the pin endpoint was dropped (R7) and this module took its place.

THE FOUR STATES
---------------
    OPEN       -- nobody has dealt with it. The only state the dashboard ranks.
                  OPEN and SNOOZED both hold an attachment back from the TTL
                  sweep (30.0a, see `unresolved_insights_for_attachment()`).
    ACTED      -- the user recorded a note about what they did OFFLINE (R4 as
                  corrected by Gap 492: the system never acts on an invoice).
                  `outcome` records which; `acted_by` and `acted_at` record who
                  and when, because "who put this invoice on hold" is an audit
                  question the moment money stops moving.
    SNOOZED    -- deferred to `snoozed_until`, after which it is OPEN again.
                  Re-opening is computed at read time (`is_effectively_open()`),
                  never by a sweeper that has to run for the state to be true:
                  a finding that silently stays snoozed because a nightly job
                  failed is exactly the failure mode this table exists to avoid.
    DISMISSED  -- terminal. The user says it is not a finding.

IDEMPOTENCE
-----------
`open_insight()` is an upsert on `(attachment_id, finding_key)`, enforced by a
unique constraint in the migration rather than by a select-then-insert, because
the sync stage and the async stage of the same bubble recompute the same cards
(section 8.6) and two workers can run concurrently. Re-opening a finding the user
has already ACTED on or DISMISSED does NOT resurrect it -- the figures are
refreshed, the status is left alone. Anything else would make "dismiss" mean
"dismiss until the next update", which is not a dismiss.

Hard rule 3: nothing in this module computes a figure. It stores figures the
cards computed, and it ranks by them.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

STATUS_OPEN = "OPEN"
STATUS_ACTED = "ACTED"
STATUS_SNOOZED = "SNOOZED"
STATUS_DISMISSED = "DISMISSED"

#: Which transitions are legal, as data rather than as a chain of ifs -- the
#: transition endpoint validates against this and the test asserts against the
#: same table, so a new state cannot be accepted by the API without appearing
#: here first.
ALLOWED_TRANSITIONS: dict[str, frozenset] = {
    STATUS_OPEN: frozenset({STATUS_ACTED, STATUS_SNOOZED, STATUS_DISMISSED, STATUS_OPEN}),
    # A snoozed finding can be acted on or dismissed directly from the bubble
    # without waiting for its timer, and can be woken by hand.
    STATUS_SNOOZED: frozenset({STATUS_ACTED, STATUS_DISMISSED, STATUS_OPEN, STATUS_SNOOZED}),
    # ACTED is not terminal: "I marked it paid and it bounced" has to be
    # expressible, or the user's only recourse is a second, duplicate finding.
    STATUS_ACTED: frozenset({STATUS_OPEN, STATUS_DISMISSED}),
    # DISMISSED is terminal. Reopening a dismissed finding means the card should
    # not have raised it, which is flywheel feedback (30.13), not a state change.
    STATUS_DISMISSED: frozenset(),
}

#: The outcomes ruling R4 named, plus the two the bubble writes itself. Validated
#: so a client cannot invent an outcome the dashboard then has to render.
#: Gap 492 (founder 2026-09-08: "intelligence is just information, no act to be
#: taken by system, user need to take action offline"). "hold" / "dispute" /
#: "paid" are gone: the bubble never moves an invoice, so the only outcomes are
#: the user's own record-keeping about the finding.
ALLOWED_OUTCOMES = frozenset({"note", "dismissed", "snoozed"})

#: Ranking weights for `rank_open_insights()`. A confidence label is not a
#: probability, and pretending it is one (0.9 / 0.6 / 0.3) would invite somebody
#: to multiply it into a currency figure and show the product to a user. These
#: are ordering weights and are used for nothing else.
_CONFIDENCE_WEIGHT = {"high": 1.0, "med": 0.6, "low": 0.3}


class InsightTransitionError(ValueError):
    """An illegal transition, or an outcome that is not in `ALLOWED_OUTCOMES`.

    A ValueError subclass so the router can turn it into a 400 without importing
    a bespoke exception hierarchy, and so a caller that forgets to catch it fails
    loudly rather than writing a nonsense state.
    """


def is_effectively_open(row: Any, now: Optional[datetime] = None) -> bool:
    """OPEN, or SNOOZED with the snooze already expired.

    Read-time re-opening (see module docstring): the dashboard, the TTL
    exemption and the bubble all agree about a woken finding at the same instant,
    with no job in between them.
    """
    now = now or datetime.utcnow()
    if row.status == STATUS_OPEN:
        return True
    if row.status == STATUS_SNOOZED:
        return row.snoozed_until is not None and row.snoozed_until <= now
    return False


def open_insight(
    *,
    tenant_id: Any,
    attachment_id: Any,
    card: str,
    finding_key: str,
    title: str = "",
    doc_type: str = "OTHER",
    session_id: Any = None,
    impact_amount: float | None = None,
    currency: str | None = None,
    confidence: str = "med",
    confidence_reason: str | None = None,
    evidence: dict | None = None,
    db_session: Any,
) -> Any:
    """Open a finding, or refresh the one already recorded for this key.

    Returns the `Insight` row. Never changes a status: see IDEMPOTENCE above.
    """
    from sqlmodel import select

    from models import Insight

    row = db_session.exec(
        select(Insight).where(
            Insight.attachment_id == attachment_id,
            Insight.finding_key == finding_key,
        )
    ).first()

    if row is None:
        row = Insight(
            tenant_id=tenant_id,
            attachment_id=attachment_id,
            session_id=session_id,
            doc_type=doc_type,
            card=card,
            finding_key=finding_key,
            title=title[:1024],
            impact_amount=impact_amount,
            currency=currency,
            confidence=confidence,
            confidence_reason=confidence_reason,
            evidence=evidence,
        )
    else:
        # Refresh the figures the async stage recomputed, leave the lifecycle
        # exactly where the user left it.
        row.title = title[:1024] or row.title
        row.impact_amount = impact_amount
        row.currency = currency or row.currency
        row.confidence = confidence
        row.confidence_reason = confidence_reason
        row.evidence = evidence
        row.doc_type = doc_type or row.doc_type
        row.session_id = row.session_id or session_id
        row.updated_at = datetime.utcnow()

    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    _sync_retained(row.tenant_id, row.attachment_id, db_session)
    return row


def transition_insight(
    insight_id: Any,
    *,
    tenant_id: Any,
    status: str,
    outcome: str | None = None,
    note: str | None = None,
    snoozed_until: datetime | None = None,
    acted_by: str | None = None,
    db_session: Any,
) -> Any:
    """Move one finding through the lifecycle, tenant-scoped.

    The tenant filter is in the WHERE clause, not checked after the fetch: a
    cross-tenant id must be indistinguishable from a non-existent one, the same
    rule `_require_owned_attachment()` follows in `routers/chat_attachments.py`.
    Returns None when the row is not this tenant's.
    """
    from sqlmodel import select

    from models import Insight

    status = (status or "").strip().upper()
    row = db_session.exec(
        select(Insight).where(Insight.id == insight_id, Insight.tenant_id == tenant_id)
    ).first()
    if row is None:
        return None

    allowed = ALLOWED_TRANSITIONS.get(row.status, frozenset())
    if status not in allowed:
        raise InsightTransitionError(
            f"A {row.status} finding cannot become {status}."
        )
    if outcome is not None and outcome not in ALLOWED_OUTCOMES:
        raise InsightTransitionError(f"Unknown outcome {outcome!r}.")
    if status == STATUS_SNOOZED and snoozed_until is None:
        raise InsightTransitionError("A snooze needs a `snoozed_until`.")

    row.status = status
    if outcome is not None:
        row.outcome = outcome
    if note is not None:
        row.note = note[:2000]
    if status == STATUS_SNOOZED:
        row.snoozed_until = snoozed_until
    if status in (STATUS_ACTED, STATUS_DISMISSED):
        row.acted_by = acted_by
        row.acted_at = datetime.utcnow()
        # A finding that has been dealt with is no longer waiting on a timer.
        row.snoozed_until = None
    if status == STATUS_OPEN:
        row.snoozed_until = None
    row.updated_at = datetime.utcnow()

    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    _sync_retained(row.tenant_id, row.attachment_id, db_session)
    return row


def open_insights_for_attachment(attachment_id: Any, db_session: Any) -> list:
    """Every finding on this attachment that still counts as open."""
    from sqlmodel import select

    from models import Insight

    rows = db_session.exec(select(Insight).where(Insight.attachment_id == attachment_id)).all()
    return [r for r in rows if is_effectively_open(r)]


def unresolved_insights_for_attachment(attachment_id: Any, db_session: Any) -> list:
    """Every finding that is still WORK: open, or snoozed and waiting.

    Wider than `open_insights_for_attachment()` on purpose, and this is the set
    the TTL exemption uses. A snooze is a deferral, not a resolution: if the
    attachment were swept while a finding slept, the finding would wake with its
    evidence deleted -- a claim about money with nothing behind it, which is the
    one outcome 30.0a exists to prevent. The dashboard still shows only the
    genuinely open ones.
    """
    from sqlmodel import select

    from models import Insight

    rows = db_session.exec(select(Insight).where(Insight.attachment_id == attachment_id)).all()
    return [r for r in rows if r.status in (STATUS_OPEN, STATUS_SNOOZED)]


def list_insights(
    tenant_id: Any,
    db_session: Any,
    status: str | None = STATUS_OPEN,
    attachment_id: Any = None,
    limit: int = 100,
) -> list:
    """`GET /chat/insights` behind one function, so the router does no filtering.

    `status="OPEN"` means *effectively* open (an expired snooze included), which
    is why the filter is applied in Python after a tenant-scoped fetch rather
    than as a SQL equality -- the wake rule is one definition
    (`is_effectively_open`) and must not be re-expressed as a second one here.
    """
    from sqlmodel import select

    from models import Insight

    stmt = select(Insight).where(Insight.tenant_id == tenant_id)
    if attachment_id is not None:
        stmt = stmt.where(Insight.attachment_id == attachment_id)
    rows = db_session.exec(stmt).all()

    if status:
        wanted = status.strip().upper()
        if wanted == STATUS_OPEN:
            rows = [r for r in rows if is_effectively_open(r)]
        else:
            rows = [r for r in rows if r.status == wanted]
    rows.sort(key=_rank_key, reverse=True)
    return rows[:limit]


def _rank_key(row: Any) -> float:
    """impact x confidence (section 8.6 step 6).

    An unquantified finding (`impact_amount is None`) ranks below every
    quantified one but above nothing: it is still a finding, and dropping it off
    the dashboard because nobody could put a number on it is how "no PO on file"
    stops being visible.
    """
    weight = _CONFIDENCE_WEIGHT.get((row.confidence or "med").lower(), 0.6)
    return abs(row.impact_amount or 0.0) * weight


def rank_open_insights(tenant_id: Any, db_session: Any, limit: int = 20) -> list:
    """The nightly dashboard ranking: open findings by impact x confidence."""
    return list_insights(tenant_id, db_session, status=STATUS_OPEN, limit=limit)


def _sync_retained(tenant_id: Any, attachment_id: Any, db_session: Any) -> None:
    """30.0a: hold the attachment back from the TTL sweep while work is open.

    Kept here rather than in the sweeper because the fact that decides it changes
    here: the moment the last finding closes, the attachment becomes ordinary
    again, and a sweeper that recomputed this itself would be a second copy of
    the "effectively open" rule.
    """
    try:
        from models import ChatAttachment

        row = db_session.get(ChatAttachment, attachment_id)
        if row is None:
            return
        should_retain = bool(unresolved_insights_for_attachment(attachment_id, db_session))
        if row.retained != should_retain:
            row.retained = should_retain
            db_session.add(row)
            db_session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not sync `retained` for attachment %s: %s", attachment_id, exc)
        try:
            db_session.rollback()
        except Exception:
            pass


def notify_insight_update(
    job_id: str | None,
    *,
    session_id: Any,
    attachment_id: Any,
    insights_version: int,
    message_id: Any = None,
    client: Any = None,
) -> None:
    """Push the async bubble update over the chat SSE channel (section 8.6 step 4).

    It rides `ChatQueueService.publish_progress()` on the EXTRACTION job's
    channel (`notify_job_id`, Gap 497) -- the channel the browser subscribed to
    when the upload returned an `extraction_job_id` -- rather than opening a
    second stream. A
    second channel would need a second subscription, a second timeout and a
    second failure mode to deliver one event.

    Best-effort by design: a closed session has nobody listening, and section 8.6
    already says that case is served by the dashboard. Redis being down must
    never fail the job that computed the findings.
    """
    if not job_id:
        return
    try:
        from services.chat_queue import ChatQueueService

        ChatQueueService.publish_progress(
            job_id,
            "insight_update",
            {
                "session_id": str(session_id) if session_id else None,
                "attachment_id": str(attachment_id),
                "insights_version": insights_version,
                "message_id": str(message_id) if message_id else None,
            },
            client=client,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("insight_update publish failed for attachment %s: %s", attachment_id, exc)
