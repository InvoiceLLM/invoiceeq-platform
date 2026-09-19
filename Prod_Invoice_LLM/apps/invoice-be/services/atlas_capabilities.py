"""Feature 34 (ATLAS) task 34.1 — the capability declaration.

Spec: `docs/feature_34_atlas.md` §2.1 / §2.2 · decisions D1, D2, D3, D6, D20.

What this is
------------
**Every recommendation ATLAS produces declares the capability required to act on
it**, and the work screen filters on that declaration. This module is that
declaration: the capability vocabulary, the grant set a request resolves to, and
the one filter both are for.

Why it is not a clearance rank
------------------------------
Feature 33 specified an `ops` / `exec` clearance binary derived from role in a
single line (`clearance = "exec" if role == "Admin" else "ops"`). It collapsed a
four-flag permission model into Admin-or-not, so Trainer, Auditor and no-role
users would have received byte-identical screens, and a zero-permission user --
the `NO_ROLE` fallback an unmapped IDP role lands in (BE Gap 337) -- would have
read every ops finding in the tenant. D1 removes it.

**It is removed by never being built.** Feature 33 was never implemented: there
is no `services/clearance.py`, no `routers/today.py`, no capability registry and
no `AnalystScope` in this backend (verified by repo-wide grep, 2026-09-17). So
spec §8's "remove the clearance service, the rank comparison, the stream filter"
is a no-op, and task 34.1 reduces to the half that is real: build the capability
declaration, and introduce no `ops`/`exec` concept at any point. Nothing in this
module, or anything that imports it, may grow a rank.

What it is built on
-------------------
The four grant flags are real columns that predate ATLAS -- `models.py`
(`User.can_train` / `can_audit` / `can_load` / `can_send_invoices`),
`RoleMapper.ROLE_PERMISSION_DEFAULTS`, `TenantContext` (`dependencies.py`),
resolved per request by `resolve_permissions()` (Feature 1.1 / Gap 73). This
module reads them; it does not define a second permission model beside them.

Three rules that are easy to get subtly wrong
---------------------------------------------
1. **Absent, not disabled** (§2.1). A line whose capability the caller lacks is
   not in the response at all. A greyed-out row still leaks the vendor, the
   amount and the fact that something is wrong with it -- which is most of the
   finding. `visible_to()` drops; it never annotates.
2. **Zero grants means zero lines** (D3), and D3 is about *grants*, not roles. A
   user with no assigned role but `can_load` granted is a Loader and sees
   document work. Only a genuinely ungranted user gets the empty state.
3. **`can_send_invoices` is not an audience** (D6). Outbound work -- invoices to
   send, payments to chase -- declares `AtlasCapability.AUDIT` like every other
   audit line. This deliberately reverses BE Gap 405, which defaulted the flag
   False for every role on least-privilege grounds; it is a recorded reversal,
   not drift. The column stays where it is and keeps its meaning for the Feature
   2.1 / 7.1 outbound surfaces. ATLAS simply stops branching on it, which is why
   `GrantSet` has no field for it: an unused field is an invitation to branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol, TypeVar

__all__ = [
    "AtlasCapability",
    "GrantSet",
    "CapabilityDeclaring",
    "visible_to",
]


class AtlasCapability(str, Enum):
    """The capability a recommendation requires in order to be acted on.

    Four values and no fifth without a decision recorded in
    `atlas_discussion.md` -- the point of §2.1 is that the audience of a line is
    a small closed set the FE can switch on, not a free-text label.

    The values are the wire values. FE Feature 23 consumes these strings; this
    spec owns them and that spec never restates them.
    """

    #: Invoices to approve / reject / query, payment mismatches, duplicates,
    #: amount discrepancies, and outbound to send or chase (D6).
    AUDIT = "audit"
    #: Extraction wrong, vendor unmapped, rule misfiring, low-confidence fields.
    TRAIN = "train"
    #: Missing documents, failed uploads, unreadable scans, connector errors.
    LOAD = "load"
    #: Cash position, forecast, runway, FP&A -- Admin only (D2). This is the one
    #: thing the old `exec` clearance was genuinely protecting, kept as a
    #: capability rule rather than as a column on six tables.
    ADMIN = "admin"


@dataclass(frozen=True)
class GrantSet:
    """What one caller is allowed to act on, resolved once per request.

    Frozen because a request's grants are resolved by `resolve_permissions()`
    before any ATLAS code runs and must not be widened by anything downstream.

    `is_admin` is carried separately from the three flags rather than derived
    from them, because the two questions are different: "may this person act on
    audit work" is a grant, and "is this person the owner of the business" is
    what D2's cash/forecast/runway/FP&A audience means. An Admin is the
    superset (§2.2) -- every line type, nothing withheld -- so `holds()` answers
    True for all four when `is_admin` is set, even if an individual flag was
    explicitly revoked on the `User` row. Volume is what the Admin's screen
    reduces via the collapse rule (D20, task 34.7); coverage is never reduced.
    """

    can_audit: bool = False
    can_train: bool = False
    can_load: bool = False
    is_admin: bool = False

    # `can_send_invoices` is deliberately absent -- see the module docstring, D6.

    @classmethod
    def from_context(cls, ctx) -> "GrantSet":
        """Build from a `TenantContext` (or anything carrying the same names).

        Duck-typed rather than importing `dependencies`, which imports
        `database` and `services.billing_lifecycle` at module scope; a service
        reaching back into the dependency layer for a type hint is how import
        cycles start.
        """
        return cls(
            can_audit=bool(getattr(ctx, "can_audit", False)),
            can_train=bool(getattr(ctx, "can_train", False)),
            can_load=bool(getattr(ctx, "can_load", False)),
            is_admin=str(getattr(ctx, "role", "") or "") == "Admin",
        )

    @classmethod
    def from_user(cls, role: str, user=None) -> "GrantSet":
        """Build from a persisted `User` row the way a request would.

        Delegates to `RoleMapper.resolve_permissions()` -- the same function
        `dependencies.resolve_permissions()` calls -- so a grant resolved for an
        ATLAS line and a grant resolved for an API route can never disagree.
        Imported lazily: `models` pulls SQLModel metadata, and this module is
        also used by pure-logic paths that should not pay for that.
        """
        from models import RoleMapper

        can_train, can_audit, can_load, _can_send_invoices = RoleMapper.resolve_permissions(
            role, user
        )
        return cls(
            can_audit=bool(can_audit),
            can_train=bool(can_train),
            can_load=bool(can_load),
            is_admin=str(role or "") == "Admin",
        )

    def holds(self, capability: AtlasCapability) -> bool:
        """Whether this caller may act on a line declaring `capability`."""
        if self.is_admin:
            return True  # §2.2: the Admin is the superset.
        if capability is AtlasCapability.AUDIT:
            return self.can_audit
        if capability is AtlasCapability.TRAIN:
            return self.can_train
        if capability is AtlasCapability.LOAD:
            return self.can_load
        if capability is AtlasCapability.ADMIN:
            return False  # D2: cash, forecast, runway and FP&A are Admin-only.
        raise ValueError(f"unknown ATLAS capability: {capability!r}")

    def capabilities(self) -> frozenset[AtlasCapability]:
        """Every capability this caller holds. Grants stack (§2.1).

        `can_audit` + `can_load` produces one merged list, not tabs -- filtering
        is per line, so stacking needs no special handling here or on the
        screen.
        """
        return frozenset(c for c in AtlasCapability if self.holds(c))

    def is_ungranted(self) -> bool:
        """True when this caller gets the empty state: "No tasks assigned" (D3)."""
        return not (self.can_audit or self.can_train or self.can_load or self.is_admin)


class CapabilityDeclaring(Protocol):
    """Anything ATLAS can put on the screen declares its capability.

    `Recommendation` (task 34.2) satisfies this, and so must every future line
    type -- the filter takes the protocol, not the concrete class, precisely so
    a new line type cannot reach the screen without declaring an audience.
    """

    capability: AtlasCapability


_T = TypeVar("_T", bound=CapabilityDeclaring)


def visible_to(lines: Iterable[_T], grants: GrantSet) -> list[_T]:
    """The lines this caller may act on, in the order given.

    Order is preserved because ranking (§7.3, task 34.9's neighbour) happens
    before filtering, not after: ATLAS ranks, it does not hide, and a filter
    that reorders would quietly become a second ranking.

    Returns `[]` for an ungranted caller -- that is D3, and it falls straight
    out of the per-line test rather than being special-cased.
    """
    return [line for line in lines if grants.holds(line.capability)]
