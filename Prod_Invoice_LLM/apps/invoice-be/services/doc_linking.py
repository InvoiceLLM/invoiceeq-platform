"""Feature 30 task 30.0b — linking an attached document to invoices, with a
first-link confirmation per vendor.

WHAT THIS ADDS OVER FEATURE 26
------------------------------
`services/document_comparison.find_candidate_invoices()` already proposes
invoices for an attachment: tier 1 on an exact normalised PO number, tier 2 on
vendor + date window, tier 3 on content similarity. That function is not
replaced and not reimplemented here — it is called.

Two things sit on top of it, and both come from §8.4 30.0b:

1. **The vendor master decides who the supplier is.** The tier-2 matcher
   compares `invoice.vendor_name` as free text, so "SHREE PACKAGING" and "Shree
   Packaging Pvt Ltd" are different vendors to it. `link_attachment()` resolves
   the document's party through `services/vendor_master.resolve_vendor()` first
   and, when the tenant has confirmed who that is, widens the candidate set to
   every spelling of that one supplier — and rejects candidates that belong to a
   DIFFERENT confirmed vendor, which is the "wrong-vendor never links" case.

2. **The first link to a new vendor is confirmed by a human.** After that,
   links to the same vendor auto-confirm. The reasoning is the same as Feature
   26 D4's: the first time we bind a supplier's documents to a supplier's
   invoices we are making a claim we cannot check, and the cost of getting it
   wrong is comparing one company's negotiated prices against another's bills.
   Once the tenant has said "yes, these are the same supplier", repeating the
   question on every later document is friction with no information in it.

WHAT IT DOES NOT DO (Gap 492)
-----------------------------
Nothing here writes to `invoice`. A link is a statement about which rows a
finding was computed from; it is never an action on those rows.

Hard rule 3: every decision in this module is a table lookup, a normalised
string comparison or a date/amount arithmetic check. No model call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

#: A candidate whose total is within this fraction of the document's total is
#: corroborated by amount. Used only to RANK and to explain, never to bind on its
#: own — an amount match with the wrong vendor is a coincidence, not a link.
AMOUNT_CORROBORATION_RATIO = Decimal("0.02")  # 2%

#: Same window `find_candidate_invoices()` tier 2 uses, restated here because
#: this module reports it in `LinkResult.reason` and a second number would make
#: the explanation disagree with the search.
DATE_CORROBORATION_DAYS = 30


@dataclass
class LinkResult:
    """What linking decided, and everything needed to explain it to the user.

    `requires_confirmation` is the whole point of the type: a caller that ignores
    it and uses `invoice_ids` anyway has skipped the gate, and that is visible in
    review because the flag is right there on the object it took the ids from.
    """

    status: str  # "linked" | "needs_confirmation" | "none"
    invoice_ids: list = field(default_factory=list)
    tier: int = 0
    vendor_id: Any = None
    vendor_status: str = "none"  # from VendorResolution
    requires_confirmation: bool = False
    reason: str = ""
    rejected: list = field(default_factory=list)
    #: Per-candidate "why we think this one", for the confirmation prompt.
    corroboration: list = field(default_factory=list)

    @property
    def is_linked(self) -> bool:
        """True only when the ids may be USED. A proposal is not a link."""
        return self.status == "linked" and bool(self.invoice_ids)


def vendor_link_policy(tenant_id: Any, vendor_id: Any, db_session: Any) -> dict:
    """Has this tenant already confirmed a link for this vendor?

    Returns `{"auto_confirm": bool, "reason": str, "confirmed_count": int}`.

    The evidence is a CONFIRMED alias on the vendor: `confirm_alias()` is what a
    human confirmation writes, so "has anybody confirmed this supplier" and "is
    there a confirmed alias" are the same question, and the policy needs no
    table of its own.
    """
    from sqlmodel import select

    from models import VendorAlias

    if vendor_id is None:
        return {
            "auto_confirm": False,
            "confirmed_count": 0,
            "reason": "this supplier is not in your vendor list yet",
        }
    try:
        rows = db_session.exec(
            select(VendorAlias).where(
                VendorAlias.tenant_id == tenant_id, VendorAlias.vendor_id == vendor_id
            )
        ).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("vendor_link_policy lookup failed: %s", exc)
        _rollback(db_session)
        return {"auto_confirm": False, "confirmed_count": 0, "reason": "vendor lookup failed"}

    confirmed = [r for r in rows if r.confirmed_by]
    if confirmed:
        return {
            "auto_confirm": True,
            "confirmed_count": len(confirmed),
            "reason": "you have already confirmed documents from this supplier",
        }
    return {
        "auto_confirm": False,
        "confirmed_count": 0,
        "reason": "this is the first document we have linked from this supplier",
    }


def _amount_corroborates(doc_total: Any, invoice_total: Any) -> bool:
    from services.attachment_insights import _dec

    a, b = _dec(doc_total), _dec(invoice_total)
    if a is None or b is None or a == 0:
        return False
    return abs(b - a) / abs(a) <= AMOUNT_CORROBORATION_RATIO


def _date_corroborates(doc_date: Optional[date], invoice_date: Optional[date]) -> bool:
    if not doc_date or not invoice_date:
        return False
    return abs((invoice_date - doc_date).days) <= DATE_CORROBORATION_DAYS


def link_attachment(row: Any, tenant_id: Any, db_session: Any) -> LinkResult:
    """Which invoices this attachment refers to, and whether we may use them.

    Order of decisions, each one narrowing rather than widening:

      1. resolve the party through the vendor master;
      2. get the deterministic candidates from Feature 26's matcher;
      3. drop any candidate whose `vendor_name` resolves to a DIFFERENT confirmed
         vendor (wrong-vendor never links);
      4. decide confirmation from `vendor_link_policy()` — except on a tier-1
         exact document-number match, which is an identifier the two documents
         were meant to share and needs no vendor opinion at all.

    Never raises: any failure returns `status="none"` with the reason, because a
    linker that throws would take the whole bubble down with it.
    """
    from services.vendor_master import normalise_vendor_name, resolve_vendor

    try:
        resolution = resolve_vendor(row.party_name, tenant_id, db_session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("link_attachment vendor resolution failed: %s", exc)
        resolution = None

    vendor = getattr(resolution, "vendor", None) if resolution else None
    vendor_status = getattr(resolution, "status", "none") if resolution else "none"
    vendor_id = vendor.id if (vendor is not None and getattr(resolution, "is_bound", False)) else None

    try:
        from services.document_comparison import find_candidate_invoices

        data = row.extracted_json or {}
        found = find_candidate_invoices(
            tenant_id=row.tenant_id,
            po_number=data.get("po_number") or row.doc_number,
            party_name=row.party_name,
            doc_date=row.doc_date,
            db_session=db_session,
        )
    except Exception as exc:
        logger.error("link_attachment candidate search failed for %s: %s", row.id, exc)
        _rollback(db_session)
        return LinkResult(status="none", reason="the invoice search could not be completed")

    tier = int(found.get("tier") or 0)
    candidates = list(found.get("invoices") or [])
    if not candidates:
        return LinkResult(
            status="none",
            tier=tier,
            vendor_id=vendor_id,
            vendor_status=vendor_status,
            reason=f"no invoice from {row.party_name or 'this supplier'} matches this document yet",
        )

    # --- 3. wrong-vendor rejection -----------------------------------------
    kept, rejected = [], []
    doc_key = normalise_vendor_name(row.party_name)
    for inv in candidates:
        inv_key = normalise_vendor_name(inv.vendor_name)
        if vendor_id is not None:
            # We know who the supplier is. A candidate belongs to them only if
            # its spelling resolves to the SAME vendor.
            try:
                inv_resolution = resolve_vendor(inv.vendor_name, tenant_id, db_session)
            except Exception:  # pragma: no cover - defensive
                inv_resolution = None
            same = (
                inv_resolution is not None
                and getattr(inv_resolution, "is_bound", False)
                and inv_resolution.vendor.id == vendor_id
            )
            if not same and inv_key != doc_key:
                rejected.append(
                    {
                        "invoice_number": inv.invoice_number,
                        "vendor_name": inv.vendor_name,
                        "reason": "belongs to a different supplier",
                    }
                )
                continue
        kept.append(inv)

    if not kept:
        return LinkResult(
            status="none",
            tier=tier,
            vendor_id=vendor_id,
            vendor_status=vendor_status,
            rejected=rejected,
            reason="the invoices we found belong to a different supplier",
        )

    ids = [str(i.id) for i in kept]

    # --- 4. confirmation ----------------------------------------------------
    if tier == 1:
        return LinkResult(
            status="linked",
            invoice_ids=ids,
            tier=tier,
            vendor_id=vendor_id,
            vendor_status=vendor_status,
            rejected=rejected,
            reason="the document number matches exactly, so no confirmation is needed",
        )

    policy = vendor_link_policy(tenant_id, vendor_id, db_session)
    if policy["auto_confirm"]:
        return LinkResult(
            status="linked",
            invoice_ids=ids,
            tier=tier,
            vendor_id=vendor_id,
            vendor_status=vendor_status,
            rejected=rejected,
            reason=policy["reason"],
        )

    corroboration = [
        {
            "invoice_number": i.invoice_number,
            "amount_matches": _amount_corroborates(row.grand_total, i.grand_total),
            "date_within_window": _date_corroborates(row.doc_date, i.invoice_date),
        }
        for i in kept
    ]
    result = LinkResult(
        status="needs_confirmation",
        invoice_ids=ids,
        tier=tier,
        vendor_id=vendor_id,
        vendor_status=vendor_status,
        requires_confirmation=True,
        rejected=rejected,
        reason=policy["reason"],
    )
    # Carried so the confirmation prompt can say WHY each invoice was proposed
    # ("same amount, dated 4 days later") instead of asking the user to trust a
    # list. `requires_confirmation` still means the ids may not be used.
    result.corroboration = corroboration
    return result


def confirm_link(
    row: Any,
    invoice_ids: Sequence[str],
    tenant_id: Any,
    db_session: Any,
    confirmed_by: str | None = None,
) -> LinkResult:
    """The user's answer to a first link. Writes `confirmed_invoice_ids`.

    Restricted to ids the matcher actually proposed — the same rule
    `confirm_attachment_matches()` enforces in Feature 26, and for the same
    reason: letting a caller confirm an arbitrary invoice id would turn this
    into an oracle for "does invoice X exist in my tenant".

    The confirmation ALSO records the vendor identity, by confirming the
    document's spelling as an alias of the resolved vendor. That is what makes
    the *next* document from this supplier link automatically — without it the
    user would answer the same question forever.
    """
    proposed = {str(i) for i in (row.candidate_invoice_ids or [])}
    requested = [str(i) for i in invoice_ids]
    unknown = [i for i in requested if i not in proposed]
    if not requested:
        raise ValueError("Confirm at least one invoice.")
    if unknown:
        raise ValueError(
            "Only invoices offered as candidates for this attachment can be confirmed."
        )

    row.confirmed_invoice_ids = requested
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    vendor_id = None
    try:
        from services.vendor_master import confirm_alias, get_or_create_vendor, resolve_vendor

        if row.party_name:
            resolution = resolve_vendor(row.party_name, tenant_id, db_session)
            vendor = (
                resolution.vendor
                if resolution.is_bound
                else get_or_create_vendor(row.party_name, tenant_id, db_session)
            )
            confirm_alias(
                row.party_name, vendor.id, tenant_id, db_session, confirmed_by=confirmed_by
            )
            vendor_id = vendor.id
    except Exception as exc:
        # The link itself is confirmed and committed above; failing to record the
        # vendor identity costs one more confirmation later, not this one.
        logger.warning("Could not record vendor identity on link confirm: %s", exc)
        _rollback(db_session)

    return LinkResult(
        status="linked",
        invoice_ids=requested,
        tier=row.match_tier or 0,
        vendor_id=vendor_id,
        vendor_status="confirmed",
        reason="you confirmed this link",
    )


def _rollback(db_session: Any) -> None:
    try:
        db_session.rollback()
    except Exception:
        pass
