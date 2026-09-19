"""Feature 34 / D49 — the dismissal store, and the filter every line passes.

Spec: `docs/feature_34_atlas.md` §16 (D49 as built) · `atlas_discussion.md` D49.

The problem this closes
-----------------------
D38 puts every computation on the open-the-app path: no job, no cache, nothing
stored. So there is no state a user's action can change, and a line they have
already handled -- by attaching the document in chat and comparing it there,
which is exactly what D47 now tells them to do -- is recomputed identically on
the next open and **returns forever**.

D49 rules for a **manual dismiss that persists**. Not a snooze: there is no
expiry in this module and no code path that brings a dismissed line back. Not an
automatic resolution either: nothing infers that the underlying problem was
solved, and the honest reading of that cost is recorded in the decision entry,
not softened here.

Why the id is enough
--------------------
`Recommendation.id` is deterministic at every emitter --
`audit-approve-<invoice id>`, `train-arithmetic-<invoice id>`,
`doubt-<invoice id>-<claim>`, `recon-differs-<invoice number>`. No emitter mints
a per-run UUID. So the id a user dismissed today is the id the recompute
produces tomorrow, and matching on it needs nothing else stored.

That property is load-bearing and invisible, which is the dangerous combination:
an emitter added later that puts a `uuid4()` in an id would silently break
dismissal for that line type and nothing would fail. `tests/test_atlas_dismissals.py`
asserts id stability across two recomputes for that reason.

Where the filter runs
---------------------
**Server-side, in the line-producing path, before the response is assembled**
(founder, 2026-09-18). A dismissed line must not appear in the payload at all --
not flagged, not marked, not present. The FE filters nothing (FE §3), so a line
that reached the wire is a line the screen shows.

`drop_dismissed()` is therefore applied to **every** producer, not only the
skills: the §3.3 doubt asks are lines too, and so are the recon lines. One
`dismissed_ids()` read per request serves all of them.
"""

from __future__ import annotations

import logging
from typing import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from models import AtlasDismissal
from services.atlas_contract import Recommendation

logger = logging.getLogger(__name__)


def dismissed_ids(db: Session, tenant_id: UUID, user_id: str) -> set[str]:
    """Every recommendation id this caller has dismissed.

    One query per request. Returned as a set because the only thing done with it
    is membership, and a list would invite a caller to re-query per line on the
    open-the-app path D38 already loads with every computation ATLAS does.
    """
    if not user_id:
        # No identity, no dismissals. Returning an empty set rather than raising
        # keeps an unauthenticated-shaped caller seeing *more*, never less --
        # a filter that fails open is the safe direction here, because failing
        # closed would hide work from someone.
        return set()
    rows = db.exec(
        select(AtlasDismissal.recommendation_id).where(
            AtlasDismissal.tenant_id == tenant_id,
            AtlasDismissal.user_id == user_id,
        )
    ).all()
    return {row for row in rows}


def drop_dismissed(
    lines: Iterable[Recommendation], dismissed: set[str]
) -> list[Recommendation]:
    """Remove dismissed lines. **Drops, never annotates.**

    The same rule as `visible_to()` (§2.1, "absent, not disabled"): a line the
    caller has dealt with does not reach the response carrying a flag the client
    is trusted to honour, because the client that forgets to honour it is the
    one that ships.
    """
    if not dismissed:
        return list(lines)
    return [line for line in lines if line.id not in dismissed]


def dismiss(
    db: Session, tenant_id: UUID, user_id: str, recommendation_id: str
) -> bool:
    """Record one dismissal. Returns True if this call created the row.

    **Idempotent**, and deliberately so: the click can be repeated from a stale
    screen, and a second row would be a lie to any future count of dismissals
    (D12's noise pruning reads exactly this table). The unique constraint is the
    real guarantee; the pre-check only avoids the round trip in the common case.

    **The id is not validated against a recomputed line set.** Doing so would
    mean running every skill on a dismiss click, on the open-the-app path, to
    reject an id that is harmless when unknown: a dismissal for a line that no
    longer exists suppresses nothing and costs one row. Refusing it would also
    make the click fail precisely when the underlying problem had *just* been
    fixed by someone else, which is the worst moment to argue with the user.
    """
    recommendation_id = (recommendation_id or "").strip()
    if not recommendation_id:
        raise ValueError("a dismissal needs a recommendation id")

    existing = db.exec(
        select(AtlasDismissal).where(
            AtlasDismissal.tenant_id == tenant_id,
            AtlasDismissal.user_id == user_id,
            AtlasDismissal.recommendation_id == recommendation_id,
        )
    ).first()
    if existing is not None:
        return False

    row = AtlasDismissal(
        tenant_id=tenant_id,
        user_id=user_id,
        recommendation_id=recommendation_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Two clicks racing. The constraint did its job; the caller's intent is
        # satisfied either way.
        db.rollback()
        logger.info(
            "ATLAS dismissal already recorded for %s", recommendation_id
        )
        return False
    return True
