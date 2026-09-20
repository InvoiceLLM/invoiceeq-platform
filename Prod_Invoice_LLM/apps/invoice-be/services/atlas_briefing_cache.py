"""Feature 35 (ATLAS Intelligence) task 35.6 — the briefing, kept for the day.

Spec: `docs/feature_35_atlas_intelligence.md` §3.1 steps 2/7/8 · §4 · §8 ruling 4.

Three functions and nothing else: `get_cached()`, `store()`, `invalidate()`.

**Why this is a cache and `GET /atlas/lines` is not.** D38's rule for Feature 34
is recompute-on-open, no cache, no job, no clock -- and that rule is right there
because every line is assembled by deterministic code from rows the request was
going to read anyway. The briefing is the one thing in ATLAS written by a
language model: roughly 30k input tokens across six rounds on Terra per run
(§3.6). Re-running it on every tab focus would spend real money to produce prose
that says the same thing about the same day. So the compute stays uncached and
the *writing* is cached.

**The cache is invalidated, never refreshed in the background** (§8 ruling 4).
`invalidate()` sets `stale = true` and stops. Nothing regenerates until the next
`GET /atlas/briefing`, and in particular the screen is not rewritten underneath
somebody who is reading it. §3.1 step 8 says this in as many words, and §7 open
decision 2 accepted the consequence for v1: a busy session regenerates on its
next open, with no minimum interval.

**Stale rather than deleted.** Three reasons, and the third is the one that is
easy to miss:

1. "Has this user been briefed today" stays answerable.
2. The row is the cost record. §3.6 says the per-open figure is to be *measured*
   from `cost_usd`, which means a superseded run has to still be there to be
   added up.
3. `tool_calls` is what §8 ruling 2's caps (6 / 12 / 20 s) get measured from.
   Deleting superseded runs would throw away most of that sample.

**What is stored is what reached the wire.** The guards in
`services/atlas_contract.py` run inside the loop, before an event is yielded, so
`store()` only ever sees paragraphs that passed. A replay is therefore identical
to the original stream, and a dropped paragraph cannot be resurrected by a cache
hit -- which matters, because a cache that could replay something the guard
refused would be a way round the guard.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Sequence
from uuid import UUID

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

__all__ = [
    "get_cached",
    "store",
    "invalidate",
    "replay_events",
]


def get_cached(db: Session, tenant_id: UUID, user_id: str, today: date):
    """This caller's briefing for today, or `None`.

    Returns the row **including** a stale one, and the caller decides: the route
    treats stale as a miss, but a stale row is still the record of what was
    spent, and a function that hid it would make `store()`'s upsert path
    unreachable. `routers/atlas.py` tests `row.stale` explicitly so the rule is
    visible at the place that applies it rather than buried here.
    """
    from models import AtlasBriefing

    return db.exec(
        select(AtlasBriefing).where(
            AtlasBriefing.tenant_id == tenant_id,
            AtlasBriefing.user_id == (user_id or ""),
            AtlasBriefing.briefing_date == today,
        )
    ).first()


def store(db: Session, run: Any, events: Iterable[Any], *, today: date):
    """Persist one finished run, with the frames it actually streamed.

    `events` is the list of `BriefingEvent`s the route yielded, not the model's
    output: the paragraphs and the question are taken from the frames that went
    to the browser, so what a replay sends tomorrow is byte-for-byte what was
    sent today. Taking them from the model's parsed answer instead would let a
    guarded-out paragraph reappear on the second open.

    Upserts on `(tenant_id, user_id, briefing_date)` -- there is one briefing per
    person per day and a regeneration replaces the previous one in place, keeping
    the same row so `created_at` remains the day's first briefing. The unique
    constraint is what makes this safe under two simultaneous opens.

    A `welcome`-only stream is **not** stored (see `routers/atlas.py`): it costs
    nothing to produce, it is not a briefing, and a stored welcome would make the
    cold tenant look briefed.
    """
    from models import AtlasBriefing

    paragraphs, question = _payload_from(events)
    row = get_cached(db, run.tenant_id, run.user_id, today)
    if row is None:
        row = AtlasBriefing(
            tenant_id=run.tenant_id,
            user_id=run.user_id or "",
            briefing_date=today,
        )
        db.add(row)

    row.model = str(getattr(run, "model", "") or "")[:128]
    row.paragraphs = paragraphs
    row.question = question
    row.tool_calls = list(getattr(run, "tool_calls", None) or [])
    row.tokens_in = int(getattr(run, "tokens_in", 0) or 0)
    row.tokens_out = int(getattr(run, "tokens_out", 0) or 0)
    row.cost_usd = float(getattr(run, "cost_usd", 0.0) or 0.0)
    row.truncated = str(getattr(run, "truncated", "") or "")[:32]
    row.dropped = int(getattr(run, "dropped", 0) or 0)
    # A freshly stored run is by definition current. Set explicitly rather than
    # left at its default, because on the regeneration path the row being
    # written is the stale one that caused the regeneration.
    row.stale = False

    db.commit()
    db.refresh(row)
    return row


def invalidate(db: Session, tenant_id: UUID, user_id: str, *, today: date | None = None) -> bool:
    """Mark today's briefing out of date. Returns whether a row was flipped.

    Called by dismiss, act, memory add and the interview answer (task 35.8/35.9),
    each of which changes something the briefing described. It deliberately does
    **not** regenerate: §8 ruling 4 and §3.1 step 8 both say the next open is what
    regenerates, and a background rewrite would change the screen under the
    person who just clicked.

    Returns `False` when there is nothing to invalidate -- the ordinary case for
    a user who has not opened the briefing today -- so a caller that wants to log
    it can, and no caller has to treat "no row" as an error.
    """
    from models import AtlasBriefing

    row = get_cached(db, tenant_id, user_id, today or date.today())
    if row is None or row.stale:
        return False
    row.stale = True
    db.commit()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────

def _payload_from(events: Iterable[Any]) -> tuple[list[dict], dict | None]:
    """The paragraphs and the question, out of the frames that were streamed.

    Reads `BriefingEvent.data` rather than re-serialising a model object: the
    data dict is exactly what the SSE frame carried, so a replay built from it
    cannot drift from the original stream the way a second `model_dump()` could
    if the contract's field set ever changed between the two.
    """
    paragraphs: list[dict] = []
    question: dict | None = None
    for event in events or ():
        kind = str(getattr(event, "type", "") or "")
        data = dict(getattr(event, "data", None) or {})
        if kind == "paragraph":
            paragraphs.append(data)
        elif kind == "question" and question is None:
            question = data
    return paragraphs, question


def replay_events(row: Any) -> Sequence[Any]:
    """A stored briefing, back as the frames it was streamed as.

    Kept beside `store()` rather than in the router so the two halves of the
    round trip are one file: whatever `_payload_from()` takes out, this puts
    back, and a change to one that forgot the other would be a change to this
    module rather than a change across two.

    The `done` frame is **not** replayed here -- the route builds it, because
    only the route knows `cached: true` (§3.3).
    """
    from services.atlas_contract import BriefingEvent

    out: list[Any] = [
        BriefingEvent(type="paragraph", data=dict(p or {}))
        for p in (getattr(row, "paragraphs", None) or [])
    ]
    question = getattr(row, "question", None)
    if question:
        out.append(BriefingEvent(type="question", data=dict(question)))
    truncated = str(getattr(row, "truncated", "") or "")
    if truncated:
        # §3.3 and the track-2 ordering decision: a reader learns the briefing is
        # partial before reading it, on a replay exactly as on a fresh run.
        out.insert(0, BriefingEvent(type="truncated", data={"reason": truncated}))
    return out
