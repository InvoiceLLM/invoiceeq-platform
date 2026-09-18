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

The aging figure
----------------
"3 untouched for a week" comes from `Recommendation.since`, which the emitters
state (§14.3, task 34.7f). A line with no `since` is counted in the total and
**not** counted as untouched: "I do not know how old this is" and "this is
fresh" are different facts, and reporting the first as the second is the kind of
quiet wrong number §5.2 puts at the top of its cost table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable
from uuid import UUID

from sqlmodel import Session, select

from services.atlas_capabilities import AtlasCapability, GrantSet
from services.atlas_contract import Recommendation

__all__ = [
    "COLLAPSE_THRESHOLD",
    "UNTOUCHED_DAYS",
    "CollapsedArea",
    "capabilities_held_by_others",
    "collapse",
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
    count: int
    #: How many are older than `UNTOUCHED_DAYS`. Lines with no `since` are not
    #: counted here -- see the module docstring on why unknown is not fresh.
    untouched: int
    #: How many carried no `since` at all, so the aging figure is honest about
    #: what it could not measure rather than quietly under-reporting.
    age_unknown: int
    #: Why this collapsed: somebody else is working it, or there is a lot of it.
    reason: str
    #: The ids of the lines this row stands for. They are **in the payload**;
    #: this is how a client expands the row in place without another request.
    line_ids: list[str] = field(default_factory=list)
    #: §2.2's sentence, composed here so two clients cannot word it differently.
    headline: str = ""


def capabilities_held_by_others(
    db: Session, tenant_id: UUID, *, exclude_clerk_user_id: str
) -> set[AtlasCapability]:
    """Which capabilities somebody *other than this caller* holds (§2.2, D20).

    Resolved through `GrantSet.from_user()`, which goes through
    `RoleMapper.resolve_permissions()` -- the same call a request makes. A second
    way of reading a permission is a second answer waiting to disagree.

    `AtlasCapability.ADMIN` is deliberately never returned. It is not an area of
    work somebody else is handling; it is the cash position, and collapsing the
    Admin's own position away from the Admin would be the one thing §2.2's
    "nothing withheld" forbids.
    """
    from models import User

    held: set[AtlasCapability] = set()
    others = db.exec(
        select(User).where(
            User.tenant_id == tenant_id,
            User.clerk_user_id != exclude_clerk_user_id,
        )
    ).all()
    for user in others:
        grants = GrantSet.from_user(user.role, user)
        for capability in (
            AtlasCapability.AUDIT,
            AtlasCapability.TRAIN,
            AtlasCapability.LOAD,
        ):
            # `holds()` is True for every capability when `is_admin`, which is
            # right here: another Admin *is* someone else who can work it.
            if grants.holds(capability):
                held.add(capability)
    return held


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

    by_capability: dict[AtlasCapability, list[Recommendation]] = {}
    for line in lines:
        by_capability.setdefault(line.capability, []).append(line)

    for capability, group in by_capability.items():
        if capability is AtlasCapability.ADMIN:
            # The Admin's own position. Never folded away from them.
            continue
        somebody_else = capability in held_by_others
        a_lot_of_it = len(group) >= threshold
        if not (somebody_else or a_lot_of_it):
            continue

        untouched = 0
        age_unknown = 0
        for line in group:
            if line.since is None:
                age_unknown += 1
            elif (today - line.since).days >= UNTOUCHED_DAYS:
                untouched += 1

        label = _AREA_LABEL.get(capability, capability.value)
        reason = "someone else is working this" if somebody_else else "there is a lot of it"
        rows.append(
            CollapsedArea(
                capability=capability,
                label=label,
                count=len(group),
                untouched=untouched,
                age_unknown=age_unknown,
                reason=reason,
                line_ids=[line.id for line in group],
                headline=_headline(label, len(group), untouched, age_unknown),
            )
        )

    rows.sort(key=lambda row: (-row.count, row.capability.value))
    return rows


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
