"""Feature 34 (ATLAS) tasks 34.10 and 34.14 — memory, and "you missed this".

Spec: `docs/feature_34_atlas.md` §7.2 (D31, bounded by D40) · §5.2 Q13 (D34) ·
D12's noise pruning.

34.10 — memory as visible, editable rules
------------------------------------------
    Everything ATLAS learns becomes a visible, editable rule in plain language
    -- whether it came from a direct answer, a dismissal, a correction or
    something said in chat. If ATLAS believes something about the business, the
    user can read it, change it or delete it. **A wrong lesson that cannot be
    found haunts the system forever.**

**D40 is the bound, and it removes most of what ATLAS knows from this module.**
Vendor baselines, claims and every other derived observation are computed when a
check runs and thrown away (D39). They are **not** rules and they never become
rows here; the line shows its own working instead -- "4x their usual
Rs 40,000-Rs 60,000 across 4 invoices" -- which is provenance without
persistence. What is left, and what this module stores, is what ATLAS was *told*
or what a user *agreed* it should remember.

That boundary is invisible at the call site, so `tests/test_atlas_memory.py`
asserts that **no emitter module imports this one**. The day a baseline is
written here, a recomputed observation becomes a stored belief that outlives the
invoices that produced it, and nothing would fail.

34.14 — the "you missed this" affordance (D34)
-----------------------------------------------
§5.2's asymmetry: a false positive is cheap, visible and self-correcting; a false
negative is real money and **invisible**. Q13 asked how one is ever detected and
D34 ruled that the user reports it -- there is no automatic detector and there is
not going to be one. Under-reporting is **accepted, explicitly** (§13.4): the
miss rate stays unknown, including whether it is worsening.

So `report_missed()` does the one thing that makes a report worth more than a
support email: it writes the user's own sentence into §7.2's memory, where it can
be read, edited and deleted like any other lesson. **The sentence is never
paraphrased** -- it is the evidence that ATLAS was wrong, and rewriting it would
be ATLAS editing that evidence.

D12's noise pruning, and why it is a suggestion and not a rule
--------------------------------------------------------------
    A repeatedly dismissed alert becomes a recommendation to stop showing it.

`noise_suggestions()` counts dismissals per **line family** and, above a
threshold, produces a sentence the user may accept as a rule. It does **not**
write one. §5.3: "never learns a permanent rule from one instance -- one
dismissal is noise, forty are a pattern", and even forty are a pattern about
which a person should get the last word. Writing the rule automatically would be
the silent write §5.3 forbids, arriving through the door marked "learning".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import UUID

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

__all__ = [
    "RuleSource",
    "ID_FAMILIES",
    "NOISE_THRESHOLD",
    "NoiseSuggestion",
    "list_rules",
    "add_rule",
    "edit_rule",
    "delete_rule",
    "report_missed",
    "noise_suggestions",
    "family_of",
]


class RuleSource:
    """Where a lesson came from. Four values, and no fifth without a decision.

    Recorded because §5.2's "wrong lesson" is far easier to judge when you know
    whether ATLAS was told it, worked it out from a correction, or inferred it
    from somebody clicking Dismiss forty times.
    """

    TOLD = "told"
    CORRECTION = "correction"
    MISSED_REPORT = "missed_report"
    DISMISSAL_PATTERN = "dismissal_pattern"

    ALL = (TOLD, CORRECTION, MISSED_REPORT, DISMISSAL_PATTERN)  # hardcode-ok: this class's own four values, not domain data


#: Every `Recommendation.id` prefix any emitter produces, with the words D12's
#: suggestion uses for it.
#:
#: **A registry, not a parse.** The obvious implementation -- split the id on
#: hyphens and take the front -- does not work, because the tail is a UUID and a
#: UUID is full of hyphens. Guessing where the family ends would silently group
#: two unrelated line types the first time an id shape changed, and D12's whole
#: output is a sentence naming what to stop showing. `tests/test_atlas_memory.py`
#: greps every `id=f"..."` out of the emitter modules and asserts this covers
#: them, so a family added later fails a test instead of being counted as
#: "unknown" forever.
ID_FAMILIES: dict[str, str] = {
    "audit-approve-": "invoices waiting on your decision",
    "audit-cash-": "the cash position",
    "train-arithmetic-": "invoices whose totals do not add up",
    "train-lowconf-": "fields I was unsure I read correctly",
    "load-failed-": "files that did not load",
    "load-quiet-": "sources that have gone quiet",
    "load-stuck-": "invoices stuck in processing",
    "doubt-": "asks for a document that would settle a question",
    "recon-missing-ours-": "invoices on a vendor statement that we do not have",
    "recon-missing-theirs-": "our invoices missing from a vendor statement",
    "recon-differs-": "invoices where their amount and ours disagree",
    "forecast-short-": "warnings that you are short on a day",
}

#: How many dismissals of one family it takes before ATLAS suggests stopping.
#:
#: §5.3 says "one dismissal is noise, forty are a pattern". Forty is the figure
#: in the spec and it is the figure here; it is deliberately high, because the
#: cost of suggesting too early is that ATLAS proposes to stop showing the one
#: line type that was working.
NOISE_THRESHOLD = 40


@dataclass(frozen=True)
class NoiseSuggestion:
    """D12: "you have dismissed this 40 times — shall I stop showing it?"

    **A suggestion, never a written rule.** It is computed on read from the
    dismissal rows and persists nothing; accepting it is the user calling
    `add_rule()`, which is a deliberate act with their name on it.
    """

    family: str
    description: str
    count: int
    text: str


def family_of(recommendation_id: str) -> str | None:
    """Which line family an id belongs to, or `None` if nothing matches.

    Longest prefix wins, so `recon-missing-ours-` is not swallowed by a shorter
    `recon-` were one ever added.
    """
    matches = [p for p in ID_FAMILIES if recommendation_id.startswith(p)]
    if not matches:
        return None
    return max(matches, key=len)


# ─────────────────────────────────────────────────────────────────────────────
# 34.10 — the rules
# ─────────────────────────────────────────────────────────────────────────────

def list_rules(db: Session, tenant_id: UUID, *, include_inactive: bool = True) -> list:
    """Every lesson ATLAS holds about this business, newest first.

    Inactive rules are included by default: §7.2's promise is that a user can
    *find* a wrong lesson, and a switched-off rule they cannot see is one they
    cannot switch back on or delete.
    """
    from models import AtlasMemoryRule

    stmt = select(AtlasMemoryRule).where(AtlasMemoryRule.tenant_id == tenant_id)
    if not include_inactive:
        stmt = stmt.where(AtlasMemoryRule.active.is_(True))  # type: ignore[union-attr]
    return list(
        db.exec(stmt.order_by(AtlasMemoryRule.created_at.desc())).all()  # type: ignore[union-attr]
    )


def add_rule(
    db: Session,
    tenant_id: UUID,
    user_id: str,
    *,
    text: str,
    source: str = RuleSource.TOLD,
    origin_ref: str | None = None,
):
    """Record one lesson, in the words it was given in.

    **The text is stored as written.** Normalising it into a predicate would make
    it unreadable to the person §7.2 says has to judge it, and summarising it
    would make ATLAS the author of a belief a user was supposed to own.
    """
    from models import AtlasMemoryRule

    text = (text or "").strip()
    if not text:
        raise ValueError("a rule needs to say something")
    if source not in RuleSource.ALL:
        raise ValueError(f"unknown rule source {source!r}; expected one of {RuleSource.ALL}")

    rule = AtlasMemoryRule(
        tenant_id=tenant_id,
        text=text[:2000],
        source=source,
        origin_ref=origin_ref,
        active=True,
        created_by=user_id or "",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def edit_rule(
    db: Session,
    tenant_id: UUID,
    rule_id: UUID,
    *,
    text: str | None = None,
    active: bool | None = None,
):
    """Change a lesson, or switch it off without losing what it said.

    `active=False` is not a soft delete and must not be read as one: it is a user
    saying "not right now" about a rule they want to keep. Removing it is
    `delete_rule()`, which removes the row.
    """
    from models import AtlasMemoryRule

    rule = db.exec(
        select(AtlasMemoryRule).where(
            AtlasMemoryRule.id == rule_id,
            AtlasMemoryRule.tenant_id == tenant_id,
        )
    ).first()
    if rule is None:
        return None
    if text is not None:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("a rule needs to say something")
        rule.text = cleaned[:2000]
    if active is not None:
        rule.active = bool(active)
    rule.updated_at = datetime.utcnow()
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, tenant_id: UUID, rule_id: UUID) -> bool:
    """Remove a lesson. **A hard delete** — the row goes.

    The founder's rule, and §7.2's reason for it agree here: a wrong lesson that
    cannot be found haunts the system forever, and a lesson kept in a
    `deleted_at` limbo is exactly a lesson that cannot be found. Any report of
    a miss that produced this rule keeps its own row and its own sentence, which
    is why `AtlasMissedReport.rule_id` is not a foreign key.
    """
    from models import AtlasMemoryRule

    rule = db.exec(
        select(AtlasMemoryRule).where(
            AtlasMemoryRule.id == rule_id,
            AtlasMemoryRule.tenant_id == tenant_id,
        )
    ).first()
    if rule is None:
        return False
    db.delete(rule)
    db.commit()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 34.14 — "you missed this"
# ─────────────────────────────────────────────────────────────────────────────

def report_missed(
    db: Session,
    tenant_id: UUID,
    user_id: str,
    *,
    entity_kind: str,
    entity_id: str,
    description: str,
):
    """Record what ATLAS should have caught, and turn it into a lesson (D34).

    Returns `(report, rule)`. The rule is the half that does any work: a stored
    complaint changes nothing, and §7.2's memory is the place a pattern goes if
    it is to protect the next invoice.

    **The user's sentence is copied, not paraphrased.** It is the evidence that
    ATLAS was wrong, and an ATLAS-written summary of it would be the system
    editing its own report card. The rule is prefixed with a fixed phrase naming
    what it is, and nothing else about the sentence changes.
    """
    from models import AtlasMissedReport

    description = (description or "").strip()
    if not description:
        raise ValueError("tell me what I missed")
    entity_kind = (entity_kind or "").strip()
    entity_id = (entity_id or "").strip()
    if not entity_kind or not entity_id:
        raise ValueError("a report has to name what it is about")

    rule = add_rule(
        db,
        tenant_id,
        user_id,
        # hardcode-ok: a fixed label naming the lesson's provenance; the user's
        # own sentence follows it unedited
        text=f"I missed this, and you told me: {description}",
        source=RuleSource.MISSED_REPORT,
        origin_ref=f"{entity_kind}:{entity_id}",
    )

    report = AtlasMissedReport(
        tenant_id=tenant_id,
        user_id=user_id or "",
        entity_kind=entity_kind[:64],
        entity_id=entity_id[:255],
        description=description[:2000],
        rule_id=rule.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report, rule


# ─────────────────────────────────────────────────────────────────────────────
# D12 — noise pruning, as a suggestion
# ─────────────────────────────────────────────────────────────────────────────

def noise_suggestions(
    db: Session, tenant_id: UUID, *, threshold: int = NOISE_THRESHOLD
) -> list[NoiseSuggestion]:
    """"You have dismissed this many times — shall I stop?" (D12).

    Counted **tenant-wide across users**, not per user: forty dismissals spread
    over three auditors is the same pattern as forty by one, and a per-user count
    would take three times as long to notice a line type that is wrong for the
    whole business.

    Ids whose family is unknown are counted into nothing and reported nowhere.
    That is the safe direction: a family this module has never heard of is one
    whose sentence it cannot write, and inventing "you have dismissed
    `weird-prefix-` 40 times" would be a suggestion the user cannot evaluate.
    """
    from models import AtlasDismissal

    rows = db.exec(
        select(AtlasDismissal.recommendation_id).where(
            AtlasDismissal.tenant_id == tenant_id
        )
    ).all()

    counts: dict[str, int] = {}
    for recommendation_id in rows:
        family = family_of(str(recommendation_id))
        if family is None:
            continue
        counts[family] = counts.get(family, 0) + 1

    out = [
        NoiseSuggestion(
            family=family,
            description=ID_FAMILIES[family],
            count=count,
            text=(
                f"You have dismissed {ID_FAMILIES[family]} {count} times. "  # hardcode-ok: a count of dismissals, not money
                "Shall I stop bringing them to you?"
            ),
        )
        for family, count in counts.items()
        if count >= threshold
    ]
    out.sort(key=lambda s: (-s.count, s.family))
    return out
