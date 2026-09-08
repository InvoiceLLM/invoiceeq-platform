"""Feature 30 task 30.0f — the per-tenant vendor master (ruling R6).

THE PROBLEM
-----------
`invoice.vendor_name` is free text. "Shree Packaging Pvt Ltd", "SHREE PACKAGING"
and "Shree Packaging Private Limited" are three vendors to every query that
groups by that column — and grouping by that column is exactly what the PO,
quotation and contract cards do ("has this vendor over-invoiced before?",
"has this vendor drifted from the quote?"). A history that silently splits in
three is worse than no history: it under-counts, and it under-counts invisibly.

THE RULE THAT MATTERS
---------------------
A fuzzy name match NEVER binds on its own. `resolve_vendor()` returns a
`VendorResolution` whose `status` is one of:

    "canonical"  -- the name IS a vendor's canonical name (exact, normalised)
    "alias"      -- a CONFIRMED alias points at a vendor
    "proposed"   -- we found a likely vendor but nobody has confirmed it; the
                    caller must ask before treating the two names as one
    "none"       -- nothing close enough

Only "canonical" and "alias" carry a bound `vendor`. "proposed" carries
`candidates` and nothing else. This is the same shape as Feature 26 D4's
confirmation gate and the same shape as `agents/entity_resolver.py`'s
"suggested, never bound" rule for typo'd invoice numbers, and for the same
reason: binding one vendor's negotiated rates onto another vendor's invoices is
a financial error the user cannot see.

Per tenant, never shared: an alias is one tenant's claim about who two names
refer to, and is not evidence for anyone else (R6, explicit).

Hard rule 3: no model call anywhere in this module. Normalisation is a fixed
string transform and similarity is `difflib`.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

#: Above this `difflib` ratio, two normalised names are close enough to PROPOSE
#: as the same vendor. Deliberately the same 0.85 `agents/entity_resolver.py`
#: uses for vendor names (`VENDOR_FUZZY_RATIO`) -- two different thresholds for
#: "is this the same supplier" in one product is how the chat and the bubble
#: start disagreeing about who a vendor is.
VENDOR_PROPOSE_RATIO = 0.85

#: Legal-form suffixes stripped before comparison. They carry no identity: a
#: vendor does not become a different company between "Pvt Ltd" and "Private
#: Limited". Ordered longest-first so "private limited" is removed before
#: "limited" can match half of it.
_LEGAL_SUFFIXES = (
    "private limited",
    "public limited",
    "pvt ltd",
    "pvt. ltd.",
    "p ltd",
    "limited",
    "ltd",
    "llp",
    "llc",
    "inc",
    "incorporated",
    "corporation",
    "corp",
    "company",
    "co",
    "gmbh",
    "b v",
    "bv",
    "s a",
    "sa",
    "srl",
    "plc",
)

_PUNCT = re.compile(r"[^\w\s]+")
_SPACES = re.compile(r"\s+")


def normalise_vendor_name(name: Optional[str]) -> str:
    """The comparison key: casefolded, depunctuated, legal form removed.

    Returns "" for anything unusable, and "" never matches anything — an empty
    key must not collide with another empty key and merge two unnamed vendors.
    """
    if not name:
        return ""
    text = _PUNCT.sub(" ", str(name)).casefold()
    text = _SPACES.sub(" ", text).strip()
    if not text:
        return ""
    changed = True
    while changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return _SPACES.sub(" ", text).strip()


@dataclass
class VendorResolution:
    """What `resolve_vendor()` decided, and why.

    `reason` is carried so the "checks not run + why" card (30.12) and the
    confirmation prompt can both say *what* is being asked and *what* it was
    compared against, rather than "we think these might be the same".
    """

    status: str  # "canonical" | "alias" | "proposed" | "none"
    vendor: Any = None
    candidates: list = field(default_factory=list)
    query: str = ""
    normalised: str = ""
    reason: str = ""

    @property
    def is_bound(self) -> bool:
        """True only when the tenant has actually agreed to this identity."""
        return self.vendor is not None and self.status in ("canonical", "alias")

    @property
    def requires_confirmation(self) -> bool:
        return self.status == "proposed"


def resolve_vendor(name: str, tenant_id: Any, db_session: Any) -> VendorResolution:
    """Which vendor is this name? Bound, proposed, or nothing.

    Fail-soft: any database error resolves to "none" with the reason recorded,
    because a vendor master that is briefly unreadable must degrade to "we could
    not tell", never to a wrong binding.
    """
    key = normalise_vendor_name(name)
    if not key:
        return VendorResolution("none", query=name or "", reason="no usable vendor name")

    try:
        from sqlmodel import select

        from models import Vendor, VendorAlias

        vendors = db_session.exec(select(Vendor).where(Vendor.tenant_id == tenant_id)).all()

        for v in vendors:
            if normalise_vendor_name(v.canonical_name) == key:
                return VendorResolution(
                    "canonical", vendor=v, query=name, normalised=key,
                    reason="exact match on the canonical name",
                )

        alias_row = db_session.exec(
            select(VendorAlias).where(
                VendorAlias.tenant_id == tenant_id, VendorAlias.alias == key
            )
        ).first()
        if alias_row is not None:
            if alias_row.confirmed_by:
                vendor = db_session.get(Vendor, alias_row.vendor_id)
                if vendor is not None:
                    return VendorResolution(
                        "alias", vendor=vendor, query=name, normalised=key,
                        reason=f"confirmed alias of {vendor.canonical_name}",
                    )
            else:
                vendor = db_session.get(Vendor, alias_row.vendor_id)
                # An UNCONFIRMED alias is a proposal that has already been made
                # and not yet answered. It is returned as a proposal again --
                # never promoted by the passage of time.
                return VendorResolution(
                    "proposed",
                    candidates=[vendor] if vendor is not None else [],
                    query=name,
                    normalised=key,
                    reason="an alias was proposed for this spelling but nobody has confirmed it",
                )

        canon_keys = {normalise_vendor_name(v.canonical_name): v for v in vendors}
        close = difflib.get_close_matches(
            key, [k for k in canon_keys if k], n=3, cutoff=VENDOR_PROPOSE_RATIO
        )
        if close:
            return VendorResolution(
                "proposed",
                candidates=[canon_keys[k] for k in close],
                query=name,
                normalised=key,
                reason=(
                    f"'{name}' looks like "
                    + ", ".join(canon_keys[k].canonical_name for k in close)
                    + " but has not been confirmed as the same supplier"
                ),
            )
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        logger.warning("Vendor resolution failed for tenant %s: %s", tenant_id, exc)
        _rollback(db_session)
        return VendorResolution("none", query=name, normalised=key, reason=f"lookup failed: {exc}")

    return VendorResolution(
        "none", query=name, normalised=key, reason="no vendor on file with a similar name"
    )


def get_or_create_vendor(canonical_name: str, tenant_id: Any, db_session: Any) -> Any:
    """The canonical row for a name, created if this tenant has never seen it.

    Creating a vendor is not the same as merging two names: a brand-new
    canonical row asserts only that this supplier exists, which the document in
    hand already proves.
    """
    from sqlmodel import select

    from models import Vendor

    key = normalise_vendor_name(canonical_name)
    existing = db_session.exec(select(Vendor).where(Vendor.tenant_id == tenant_id)).all()
    for v in existing:
        if normalise_vendor_name(v.canonical_name) == key:
            return v

    row = Vendor(tenant_id=tenant_id, canonical_name=(canonical_name or "").strip()[:512])
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def propose_alias(alias: str, vendor_id: Any, tenant_id: Any, db_session: Any) -> Any:
    """Record an unconfirmed alias, so the same question is not asked twice.

    Returns the row. It does NOT bind: `resolve_vendor()` keeps answering
    "proposed" for it until `confirm_alias()` names a confirmer.
    """
    from sqlmodel import select

    from models import VendorAlias

    key = normalise_vendor_name(alias)
    if not key:
        raise ValueError("An alias needs a usable name.")

    row = db_session.exec(
        select(VendorAlias).where(VendorAlias.tenant_id == tenant_id, VendorAlias.alias == key)
    ).first()
    if row is None:
        row = VendorAlias(
            tenant_id=tenant_id, vendor_id=vendor_id, alias=key, raw_alias=(alias or "")[:512]
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
    return row


def confirm_alias(
    alias: str, vendor_id: Any, tenant_id: Any, db_session: Any, confirmed_by: str | None = None
) -> Any:
    """The tenant agrees that `alias` is this vendor. From here it binds.

    `confirmed_by` is required in spirit and permitted to be None only so a
    system-level confirmation (a test fixture, a migration of an existing
    mapping) is expressible; every user-driven call passes the user.
    """
    from models import VendorAlias  # noqa: F401  (imported for the caller's type)

    row = propose_alias(alias, vendor_id, tenant_id, db_session)
    row.vendor_id = vendor_id
    row.confirmed_by = confirmed_by or "system"
    row.confirmed_at = datetime.utcnow()
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def vendor_invoice_names(vendor_id: Any, tenant_id: Any, db_session: Any) -> list:
    """Every `invoice.vendor_name` spelling that belongs to this vendor.

    This is what the cards actually need: the vendor master exists so a history
    query can say `vendor_name IN (...)` instead of `vendor_name = '<one
    spelling>'`. Returns raw spellings, not normalised keys, because that is
    what the column holds.
    """
    from sqlalchemy import text
    from sqlmodel import select

    from models import Vendor, VendorAlias

    vendor = db_session.get(Vendor, vendor_id)
    # Compared as strings, not as objects: callers reach this from two
    # directions -- services hold a `UUID`, `agents/entity_resolver.py` holds the
    # `str` it was given by the chat turn -- and a `UUID != str` comparison is
    # silently True, which would refuse every vendor the resolver asked about
    # while looking like a tenant-isolation check doing its job.
    if vendor is None or str(vendor.tenant_id) != str(tenant_id):
        return []

    keys = {normalise_vendor_name(vendor.canonical_name)}
    for a in db_session.exec(
        select(VendorAlias).where(
            VendorAlias.tenant_id == tenant_id, VendorAlias.vendor_id == vendor_id
        )
    ).all():
        if a.confirmed_by:
            keys.add(a.alias)

    try:
        rows = db_session.execute(
            text(
                "SELECT DISTINCT vendor_name FROM invoice WHERE tenant_id = :tenant_id "
                "AND vendor_name IS NOT NULL AND TRIM(vendor_name) <> ''"
            ),
            {"tenant_id": str(tenant_id)},
        ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Vendor spelling lookup failed: %s", exc)
        _rollback(db_session)
        return []

    return sorted(
        {str(r[0]).strip() for r in rows if r[0] and normalise_vendor_name(r[0]) in keys}
    )


def _rollback(db_session: Any) -> None:
    try:
        db_session.rollback()
    except Exception:
        pass
