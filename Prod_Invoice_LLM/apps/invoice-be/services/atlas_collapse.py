"""Feature 34 (ATLAS) task 34.7g — assignment and collapse.

Spec: `docs/feature_34_atlas.md` §2.2 · §7.3 · `atlas_discussion.md` **D20**,
**D37**, **D41**.

    The Admin is the superset -- every line type, nothing withheld. But items
    another grant-holder is actively working **collapse to one row per area**:

        Corrections -- 34 pending, 3 untouched for a week.

    Openable for the full list. **Coverage is total; volume is not.**

What this is not
----------------
* **Not escalation** (D37). Nothing travels anywhere after a delay, there is no
  absence clock and no unhandled-item timer. D20 already gives the Admin every
  line type; an item does not need to be sent to someone who is already looking
  at it. This module groups what is already in the payload and nothing else.
* **Not a filter.** `collapse()` returns rows *describing* lines; it never
  removes a line from anything. The payload keeps every line it had, which is
  what makes "openable in place" a matter of the client expanding a row it
  already holds rather than fetching. Coverage is total by construction, not by
  the client remembering to ask for the rest.
* **Not a second concept from §7.3's volume threshold** (D41). Q5 asked where a
  list becomes a queue and was ruled: it does not. The same collapse mechanism
  serves both reasons, so an area collapses either because somebody else is
  working it **or** because there is simply a lot of it. One row shape, two
  reasons, and the row says which.
* **Not a solo owner's problem.** "A solo owner collapses nothing" falls out of
  the rule rather than being special-cased: with no other grant-holder there is
  no other-holder collapse, and a solo owner under the volume threshold sees a
  plain list.

What real data changed here, and why (2026-09-18)
-------------------------------------------------
Both halves of this module were wrong on the first tenant that was not a fixture,
and both passed every test, because the tests asserted the shape of a row rather
than the sentence printed on it.

**1. The predicate asked the wrong question.** It was
`capabilities_held_by_others()`: does any *other user row* in this tenant hold
this grant? On a workspace with one working owner and a few seeded colleague rows
that answered "yes", so every area printed *"someone else is working this"* when
nobody was. D20's words are "items another grant-holder is **actively
working**" -- that is a statement about work, not about a permission. A
capability existing is not a person holding it. The predicate now asks whether
another user has **actually touched a line in that area**
(`capabilities_worked_by_others()`), which is the only form of "actively
working" this product has evidence for.

**2. The count counted lines.** "Decisions -- 5 pending" on a tenant with two
invoices awaiting a decision: the five were two approve lines, two "attach the
quotation" doubt asks about *the same two invoices*, and the cash position tile,
which is not pending and is not a decision. An area count is read as "how much
work is in here", so it counts **work**: distinct subjects, tiles excluded. The
same two invoices now read "Decisions -- 2 pending", and the tile stays out of
the area entirely rather than being folded away inside it.

What counts as work
-------------------
A line is work when it is about a **record** -- an invoice, a vendor, an
ingestion source. A line whose `what.entity_kind` is `"tenant"` is about the
workspace itself: the cash position, the runway, the shortfall warning. Those are
standing facts, always true, never "pending", and never somebody else's job to
clear. They are excluded from an area and stay in the plain list where the user
can always see them -- which is also the only reading of §2.2's "nothing
withheld" that survives contact with an Admin's own cash line.

Two lines about the same invoice are **one** piece of work, so the count is over
distinct `what.entity_id`. The lines themselves are all still in `line_ids`: the
row expands to everything ATLAS has to say about those subjects.

The aging figure
----------------
"3 untouched for a week" comes from `Recommendation.since`, which the emitters
state (§14.3, task 34.7f). A line with no `since` is counted in the total and
**not** counted as untouched: "I do not know how old this is" and "this is
fresh" are different facts, and reporting the first as the second is the kind of
quiet wrong number §5.2 puts at the top of its cost table.

Aging is measured per **subject**, for the same reason the count is: a subject
whose oldest line is a week old is a week-old piece of work, and a subject is of
unknown age only when **no** line about it states a `since`. Counting per line
made a single invoice with an undated doubt ask report as "1 of unknown age"
beside itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Sequence
from uuid import UUID

from sqlmodel import Session, select

from services.atlas_capabilities import AtlasCapability, GrantSet
from services.atlas_contract import Recommendation

__all__ = [
    "COLLAPSE_THRESHOLD",
    "UNTOUCHED_DAYS",
    "WORKING_WITHIN_DAYS",
    "TENANT_ENTITY_KIND",
    "CollapsedArea",
    "capabilities_worked_by_others",
    "collapse",
    "group_work_by_capability",
    "is_work",
]

#: The volume at which an area collapses even with nobody else working it (D41).
#:
#: **A stated guess, not a measured threshold.** §13.5 names it explicitly as one
#: of two build-time unknowns "to be answered by measurement, not by ruling", and
#: there is no customer to measure yet. Twelve is one screenful; the number is
#: here, named, so the argument has something to point at.
COLLAPSE_THRESHOLD = 12

#: How old a line has to be to count as "untouched" in the aging figure. §2.2's
#: own example says a week, so a week is what it means.
UNTOUCHED_DAYS = 7

#: How recently somebody else must have touched an area for them to count as
#: **actively working** it (D20).
#:
#: A week, deliberately the same span as `UNTOUCHED_DAYS`: §2.2 already treats a
#: week as the point at which a line stops looking handled and starts looking
#: dropped, and having one span mean "still being worked" and a different one
#: mean "untouched" would let a row say both at once.
WORKING_WITHIN_DAYS = 7

#: `What.entity_kind` for a line about the workspace rather than about a record.
#: The cash position, the runway and the shortfall warning use it. Never work,
#: therefore never collapsed away from anybody -- see the module docstring.
TENANT_ENTITY_KIND = "tenant"  # hardcode-ok: a `What.entity_kind` token from this repo's own ATLAS contract, not domain data

#: The area name per capability -- §2.2's "Corrections", in the user's words.
_AREA_LABEL: dict[AtlasCapability, str] = {  # hardcode-ok: four UI labels for a closed four-value enum, not domain data
    AtlasCapability.AUDIT: "Decisions",
    AtlasCapability.TRAIN: "Corrections",
    AtlasCapability.LOAD: "Documents",
    AtlasCapability.ADMIN: "Position",
}


@dataclass(frozen=True)
class CollapsedArea:
    """One row standing for a group of lines that are still in the payload."""

    capability: AtlasCapability
    label: str
    #: **Distinct pieces of work**, not lines. Two lines about one invoice are
    #: one thing to do, and a tenant-level tile is not work at all -- see the
    #: module docstring on what real data found here.
    count: int
    #: How many **subjects** are older than `UNTOUCHED_DAYS`, measured on the
    #: oldest line about each. Subjects with no `since` anywhere are not counted
    #: here -- see the module docstring on why unknown is not fresh.
    untouched: int
    #: How many subjects carried no `since` on any line, so the aging figure is
    #: honest about what it could not measure rather than quietly under-reporting.
    age_unknown: int
    #: Why this collapsed: somebody else is working it, or there is a lot of it.
    reason: str
    #: The ids of the lines this row stands for. They are **in the payload**;
    #: this is how a client expands the row in place without another request.
    line_ids: list[str] = field(default_factory=list)
    #: §2.2's sentence, composed here so two clients cannot word it differently.
    headline: str = ""


def capabilities_worked_by_others(
    db: Session,
    tenant_id: UUID,
    *,
    exclude_user_id: str,
    line_ids_by_capability: Mapping[AtlasCapability, Sequence[str]],
    now: datetime | None = None,
    within_days: int = WORKING_WITHIN_DAYS,
) -> set[AtlasCapability]:
    """Which areas somebody *other than this caller* is actively working (§2.2, D20).

    **Replaces `capabilities_held_by_others()`, which asked the wrong question.**
    That one returned a capability whenever any other user row in the tenant held
    the grant -- so a workspace with one working owner and a couple of colleague
    rows printed *"someone else is working this"* on every area, with nobody
    working anything. D20 says "items another grant-holder is **actively
    working**": holding a grant is a permission, not a piece of work in progress,
    and treating the two as the same thing is what produced a sentence that was
    simply false on the first real tenant.

    **What counts as evidence, and why it is these two tables.** ATLAS has no
    assignment concept and no presence: there is no "Priya has claimed this"
    anywhere, and D38 forbids the background job that would be needed to invent
    one. What it does have is a record of what people did -- `atlas_action_log`
    (every write, attributed and timestamped, §5.3's "never writes silently") and
    `atlas_dismissals` (D49, per person). A row in either, by another user, on a
    line **currently in this area**, within `within_days`, is somebody working
    this area. Nothing else in the schema knows.

    **The bias when there is no evidence is to collapse nothing**, and that is
    the safe direction: an Admin who is shown a plain list sees every line, which
    is §2.2's "coverage is total". An Admin wrongly shown a collapsed row is
    told a colleague has it in hand when nobody does, which is the one outcome
    §2.2 exists to prevent -- work disappearing because it looked handled.

    `AtlasCapability.ADMIN` can never be returned, because a tenant-level line is
    excluded from every area upstream (see `collapse()`): the Admin's own cash
    position is not an area of work somebody else is handling, and folding it
    away from them would be the one thing §2.2's "nothing withheld" forbids.
    """
    from models import AtlasActionLog, AtlasDismissal

    candidates: dict[str, AtlasCapability] = {}
    for capability, ids in line_ids_by_capability.items():
        if capability is AtlasCapability.ADMIN:
            continue
        for line_id in ids:
            candidates[line_id] = capability
    if not candidates:
        return set()

    since = (now or datetime.utcnow()) - timedelta(days=within_days)
    ids = list(candidates)

    touched: set[str] = set()
    touched.update(
        db.exec(
            select(AtlasActionLog.recommendation_id).where(
                AtlasActionLog.tenant_id == tenant_id,
                AtlasActionLog.user_id != exclude_user_id,
                AtlasActionLog.performed_at >= since,
                AtlasActionLog.recommendation_id.in_(ids),  # type: ignore[attr-defined]
            )
        ).all()
    )
    touched.update(
        db.exec(
            select(AtlasDismissal.recommendation_id).where(
                AtlasDismissal.tenant_id == tenant_id,
                AtlasDismissal.user_id != exclude_user_id,
                AtlasDismissal.dismissed_at >= since,
                AtlasDismissal.recommendation_id.in_(ids),  # type: ignore[attr-defined]
            )
        ).all()
    )

    return {candidates[line_id] for line_id in touched if line_id in candidates}


def collapse(
    lines: Iterable[Recommendation],
    grants: GrantSet,
    *,
    held_by_others: set[AtlasCapability],
    today: date,
    threshold: int = COLLAPSE_THRESHOLD,
) -> list[CollapsedArea]:
    """The rows the Admin's screen shows instead of a wall of other people's work.

    Returns `[]` for anyone who is not an Admin. §2.2's collapse exists because
    the Admin is the superset and therefore sees everything; a Trainer sees only
    their own lines, so there is nothing to fold up and a row saying
    "Corrections -- 4 pending" above their four corrections would be noise.

    Order is by count, descending, then by capability value, so two recomputes of
    the same screen produce the same rows in the same order.
    """
    rows: list[CollapsedArea] = []
    if not grants.is_admin:
        return rows

    by_capability = group_work_by_capability(lines)

    for capability, group in by_capability.items():
        if capability is AtlasCapability.ADMIN:
            # The Admin's own position. Never folded away from them.
            continue

        # §2.2 counts **work**, not lines: two lines about one invoice are one
        # thing to do. `subjects` is ordered so the rows and the aging figures
        # are stable across two recomputes of the same screen.
        subjects: dict[str, list[Recommendation]] = {}
        for line in group:
            subjects.setdefault(line.what.entity_id, []).append(line)

        count = len(subjects)
        somebody_else = capability in held_by_others
        a_lot_of_it = count >= threshold
        if count == 0 or not (somebody_else or a_lot_of_it):
            continue

        untouched = 0
        age_unknown = 0
        for subject_lines in subjects.values():
            dates = [line.since for line in subject_lines if line.since is not None]
            if not dates:
                age_unknown += 1
            elif (today - min(dates)).days >= UNTOUCHED_DAYS:
                # The **oldest** line about a subject is how long that work has
                # been sitting there. Taking the newest would let a fresh doubt
                # ask on a month-old invoice report the invoice as fresh.
                untouched += 1

        label = _AREA_LABEL.get(capability, capability.value)
        reason = "someone else is working this" if somebody_else else "there is a lot of it"
        rows.append(
            CollapsedArea(
                capability=capability,
                label=label,
                count=count,
                untouched=untouched,
                age_unknown=age_unknown,
                reason=reason,
                line_ids=[line.id for line in group],
                headline=_headline(label, count, untouched, age_unknown),
            )
        )

    rows.sort(key=lambda row: (-row.count, row.capability.value))
    return rows


def is_work(line: Recommendation) -> bool:
    """Whether this line is a piece of work, or a standing fact about the tenant.

    The one rule, stated once so the collapse, the count and the threshold cannot
    each decide it differently: a line about a **record** is work; a line whose
    `what.entity_kind` is `"tenant"` is the position, the runway or the shortfall
    warning, and none of those is pending, assignable or clearable.

    This is what kept `audit-cash-INR` inside "Decisions -- 5 pending" on the
    first real tenant: it declares `AtlasCapability.AUDIT` (D44 gives Auditors
    the cash view), so grouping by capability alone swept the cash tile into the
    decisions queue and counted it as a fifth decision.
    """
    return line.what.entity_kind != TENANT_ENTITY_KIND


def group_work_by_capability(
    lines: Iterable[Recommendation],
) -> dict[AtlasCapability, list[Recommendation]]:
    """The work lines, by area, in payload order. Tiles are not in any area.

    Public because the router needs exactly this grouping to ask
    `capabilities_worked_by_others()` which lines are in which area, and two
    modules deciding independently what belongs to an area is how the two halves
    of a collapsed row come to disagree about the same screen.
    """
    grouped: dict[AtlasCapability, list[Recommendation]] = {}
    for line in lines:
        if not is_work(line):
            continue
        grouped.setdefault(line.capability, []).append(line)
    return grouped


def _headline(label: str, count: int, untouched: int, age_unknown: int) -> str:
    """§2.2's sentence: "Corrections — 34 pending, 3 untouched for a week."

    Composed here rather than on each client so the wording cannot drift between
    two surfaces. Every number in it is a **count**, not money: §12.4 is explicit
    that "fixes 60 invoices a month" is prose a recommendation is supposed to
    contain, and a collapsed row is counts all the way down. Nothing here needs a
    `Figure`, and nothing here is validated by `validate_recommendation()`,
    because this is not a recommendation -- it is a summary of several.
    """
    parts = [f"{count} pending"]  # hardcode-ok: a count of lines, not a money figure -- see this function's docstring
    if untouched:
        parts.append(f"{untouched} untouched for a week")  # hardcode-ok: a count of lines, not a money figure
    if age_unknown:
        parts.append(f"{age_unknown} of unknown age")  # hardcode-ok: a count of lines, not a money figure
    return f"{label} — " + ", ".join(parts) + "."
