"""Feature 34 (ATLAS) task 34.12 — cold start: what day one is, per role.

Spec: `docs/feature_34_atlas.md` §7.1 · `atlas_discussion.md` **D24**, **D25**.

The trap this exists for
------------------------
Almost everything ATLAS does needs history -- vendor baselines, payment
behaviour, recurrence, dismissals. So **its first month is its weakest, and that
is the month a customer decides whether it was worth buying.**

§7.1's answer is not to fake findings. It is that **day one is comprehension, not
findings**: teach the working relationship per role, in their terms, and state
plainly what ATLAS cannot do yet and when it will be able to.

The three parts, and why the third is the one that matters
----------------------------------------------------------
1. **What your job looks like with ATLAS** -- per role, in their terms.
2. **How to verify me** -- "attach the document and ask 'is this right?' -- I
   will show you exactly what I compared. Try it on this one now." Trust is not
   built by telling a user ATLAS is reliable; it is built by letting them check
   it once, cheaply (D24).
3. **What I will be able to do as I learn** -- *"right now I do not know your
   vendors, so I cannot tell you a number is unusual. In a month I will."* **A
   stated plan, not a disappointment.** A product that is quietly worse in month
   one reads as a product that is broken; the same product that said so in
   advance reads as one that is honest about its mechanism.

D25 — teach once, then keep teaching in place
---------------------------------------------
Capabilities are explained the first time they become relevant, never dumped on
day one. So this is not an onboarding tour and there is no step counter, no
"next" and no completion flag: `orientation()` reports whether the tenant has any
history yet, and the screen shows the orientation while they do not. Nothing is
persisted, nothing is dismissed, and a tenant that goes quiet for a month and
comes back to an empty workspace gets the same honest explanation again rather
than a screen that assumes they remember.

Why this is data and not a prompt
---------------------------------
It would be very easy to have a model write this per visit. It must not: the
third part is a **commitment about what the product will do**, and a sentence
that varies per run is a commitment nobody can be held to. Hard rule 3 is about
correctness, and "what we promised the customer we would be able to do in a
month" is a correctness question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlmodel import Session, func, select

from services.atlas_capabilities import AtlasCapability, GrantSet

__all__ = [
    "OrientationPart",
    "Orientation",
    "orientation",
    "tenant_has_history",
]


@dataclass(frozen=True)
class OrientationPart:
    """One of §7.1's three parts, already in the reader's words."""

    key: str
    title: str
    body: str


@dataclass(frozen=True)
class Orientation:
    """What a new workspace is told, for the capabilities this caller holds."""

    #: False once the tenant has any invoices at all. **Reported, not enforced**
    #: -- the client decides whether to show it, and a user who wants to read it
    #: again is not something this needs to prevent.
    needed: bool
    #: The capabilities this is written for, so a screen can say who it is for.
    capabilities: list[str]
    parts: list[OrientationPart] = field(default_factory=list)
    #: What ATLAS finds on day one with zero history (§7.1). Real, checkable
    #: work, listed so that "comprehension, not findings" does not read as
    #: "nothing until next month".
    day_one_finds: list[str] = field(default_factory=list)
    #: §7.1's historical import, **an offer and never a gate**. Reconciling the
    #: past produces real findings in the first session and silently builds every
    #: baseline; a product that refused to work until it was done would be
    #: holding the customer's first session hostage to a file they may not have.
    historical_import_offer: str = ""


#: Part 1, per capability: what this person's job looks like with ATLAS.
#:
#: **Per capability, not per role.** Grants stack (§2.1), so a user with
#: `can_audit` and `can_load` reads both and neither is a "role" that had to be
#: invented for them. Keyed on the enum so a fifth capability cannot be added
#: without this failing to compile in the reader's head.
_JOB_WITH_ATLAS: dict[AtlasCapability, str] = {
    AtlasCapability.AUDIT: (
        "Invoices waiting on your decision arrive here with what is odd about "
        "them already worked out, and the cash picture the decision sits "
        "inside. You approve or reject; I never move money, and I never pay "
        "anything."
    ),
    AtlasCapability.TRAIN: (
        "When an invoice is read wrong I bring you the fix already drafted, "
        "with the field as it reads now and as it would read, side by side. "
        "You decide whether the fix is right — I apply nothing on my own."
    ),
    AtlasCapability.LOAD: (
        "Files that did not load arrive with the fix, not the fault, and a "
        "source that has gone quiet is told to you rather than waiting to be "
        "noticed. Your job here is designed to shrink."
    ),
    AtlasCapability.ADMIN: (
        "You see every line type, with work other people are handling folded "
        "into one row per area so the volume is theirs and the coverage is "
        "still yours. Cash, the forecast and the runway are here too."
    ),
}

#: Part 2, identical for everyone. D24: trust is built by checking once, cheaply.
_HOW_TO_VERIFY = (
    "On any line, the question beside it opens chat with that question already "
    "written. Attach the document there and ask me — I will show you exactly "
    "what I compared and where I read each number. Try it on a line now, while "
    "it costs you nothing to find out I am wrong."
)

#: Part 3. **A stated plan, not a disappointment**, and the sentence is fixed
#: because it is a commitment (see the module docstring).
_WHAT_I_WILL_LEARN = (
    "Right now I do not know your vendors, so I cannot tell you that an amount "
    "is unusual for them — I can only check what an invoice says against "
    "itself. In a month of invoices I will know each vendor's usual range. In "
    "three months I will know who pays late, and the forecast will be built on "
    "how people actually pay instead of on due dates."
)

#: §7.1's day-one findings, verbatim: what needs no history at all.
_DAY_ONE_FINDS = [
    "an invoice whose line items do not add up to its total, or whose tax is on the wrong base",
    "a malformed GSTIN, or a due date before the invoice date",
    "two invoices in the same batch that look like the same invoice",
    "a purchase order or delivery note in the batch that disagrees with the invoice it belongs to",
]

_HISTORICAL_IMPORT_OFFER = (
    "If you have last year's bank statements I can check them now — I usually "
    "find a duplicate payment or two, and it teaches me your vendors much "
    "faster. It is an offer, not a step: everything here works without it."
)


def tenant_has_history(db: Session, tenant_id: UUID) -> bool:
    """Whether this workspace has seen any invoice at all.

    The cheapest honest test of "is this day one". Deliberately **not** a stored
    onboarding flag: a flag records that somebody once clicked past a screen,
    which is a different fact from whether ATLAS has anything to go on, and it is
    the second one that decides whether the orientation is still true.
    """
    from models import Invoice

    count = db.exec(
        select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant_id)
    ).one()
    return bool(count and int(count if not isinstance(count, tuple) else count[0]) > 0)


def orientation(db: Session, tenant_id: UUID, grants: GrantSet) -> Orientation:
    """§7.1's three parts, for the capabilities this caller actually holds.

    An ungranted user (D3) gets `needed=False` and no parts: they have no work,
    so a description of the work they cannot do would be an explanation of a
    product they do not have access to. The empty state already says the true
    thing ("No tasks assigned. Ask your admin for access.").
    """
    held = sorted(grants.capabilities(), key=lambda c: c.value)
    if not held:
        return Orientation(needed=False, capabilities=[])

    jobs = [_JOB_WITH_ATLAS[c] for c in held if c in _JOB_WITH_ATLAS]
    parts = [
        OrientationPart(
            key="your_job",
            title="What your job looks like with me",
            # Joined rather than one part per capability: grants stack into one
            # merged list, not tabs (§2.1), and the orientation reads the same
            # way the screen does.
            body=" ".join(jobs),
        ),
        OrientationPart(
            key="how_to_verify",
            title="How to check me",
            body=_HOW_TO_VERIFY,
        ),
        OrientationPart(
            key="what_i_will_learn",
            title="What I will be able to do as I learn",
            body=_WHAT_I_WILL_LEARN,
        ),
    ]

    return Orientation(
        needed=not tenant_has_history(db, tenant_id),
        capabilities=[c.value for c in held],
        parts=parts,
        day_one_finds=list(_DAY_ONE_FINDS),
        historical_import_offer=_HISTORICAL_IMPORT_OFFER,
    )
