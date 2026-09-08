"""Feature 30 task 30.5 — matching a bank statement's rows to invoices.

RULING R5, IN CODE
------------------
"± 1 currency unit, ± 5 days, vendor must match; per-tenant override." All three
are read through `services/insight_thresholds.threshold()`, so a tenant who deals
in a currency with different rounding can move the tolerance without a deploy and
the "checks not run" card can quote the number that was actually used.

The three are conjunctive and the vendor clause is the load-bearing one. Amount
and date alone match coincidences: two suppliers invoicing the same round number
in the same week is ordinary, and binding a payment to the wrong one produces a
confident wrong answer about who has been paid.

WHAT A MATCH IS AND IS NOT
--------------------------
A matched row means "this debit looks like the payment of that invoice". It does
NOT mean the invoice is paid, and after Gap 492 nothing here writes to `invoice`
at all — the bubble is information. The verdict is written to
`bank_statement_line.match_status` only.

Four verdicts, and the fourth is the one worth having:

    MATCHED             exactly one invoice satisfies all three rules
    AMBIGUOUS           several do -- the user picks, we do not
    POSSIBLE_DUPLICATE  the single match is an invoice that is ALREADY PAID, or
                        two statement rows match the same invoice: the most
                        valuable thing a statement can tell an SMB owner is that
                        they paid the same bill twice
    UNMATCHED           nothing satisfies the rules

Hard rule 3: every figure here is `Decimal` arithmetic over stored values.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

MATCH_MATCHED = "MATCHED"
MATCH_AMBIGUOUS = "AMBIGUOUS"
MATCH_DUPLICATE = "POSSIBLE_DUPLICATE"
MATCH_UNMATCHED = "UNMATCHED"

#: Statuses that mean "our records already say this bill was settled".
_SETTLED_STATUSES = frozenset({"PAID"})


def _dec(value: Any) -> Optional[Decimal]:
    from services.attachment_insights import _dec as shared

    return shared(value)


def _amount_of(line: Any) -> tuple[Optional[Decimal], str]:
    """The row's amount and which side it is on.

    A debit is money we paid (a supplier bill); a credit is money we received (a
    customer receipt). The side decides which invoices are even candidates, which
    is why it is returned rather than absolute-valued away.
    """
    debit, credit = _dec(line.debit), _dec(line.credit)
    if debit is not None and debit != 0:
        return debit, "debit"
    if credit is not None and credit != 0:
        return credit, "credit"
    return None, "none"


def _vendor_matches(line_narration: Optional[str], invoice: Any, aliases: Sequence[str]) -> bool:
    """Does this row name this invoice's counterparty?

    Checked against the vendor master's spellings when the tenant has confirmed
    them (`aliases`), else against the invoice's own `vendor_name` /
    `customer_name`. Comparison is on normalised names, and a name must appear
    IN the narration -- a bank narration is "NEFT SHREE PACKAGING PVT LTD 12345",
    so containment is the right test and equality would match nothing.
    """
    from services.vendor_master import normalise_vendor_name

    narration = normalise_vendor_name(line_narration)
    if not narration:
        return False
    candidates = [invoice.vendor_name, invoice.customer_name, *aliases]
    for name in candidates:
        key = normalise_vendor_name(name)
        if key and key in narration:
            return True
    return False


def match_statement_lines(
    lines: Sequence[Any],
    invoices: Sequence[Any],
    tenant_id: Any = None,
    db_session: Any = None,
    aliases_by_invoice: Optional[dict] = None,
) -> dict:
    """Match every ledger row against the tenant's invoices. Pure computation.

    Returns
        {"matched": [...], "unmatched_debits": [...], "unmatched_credits": [...],
         "possible_duplicates": [...], "ambiguous": [...], "tolerances": {...}}

    It does NOT write: `apply_matches()` persists, separately, so the same
    function can be used to preview a match ("what would this do?") without
    touching the ledger.
    """
    from services.insight_thresholds import threshold

    amount_tolerance = Decimal(
        str(threshold("bank_amount_tolerance", tenant_id, db_session))
    )
    day_tolerance = int(threshold("bank_date_tolerance_days", tenant_id, db_session))

    result: dict = {
        "matched": [],
        "unmatched_debits": [],
        "unmatched_credits": [],
        "possible_duplicates": [],
        "ambiguous": [],
        "tolerances": {
            "amount": float(amount_tolerance),
            "days": day_tolerance,
            "vendor_must_match": True,
        },
    }
    aliases_by_invoice = aliases_by_invoice or {}
    #: invoice id -> the statement row already matched to it, for duplicate
    #: detection across rows (the "paid twice?" case).
    claimed: dict = {}

    for line in lines:
        amount, side = _amount_of(line)
        if amount is None:
            # A row with neither a debit nor a credit is a header, a carried
            # balance or an unreadable row. Not a failure, and not a match.
            continue

        candidates = []
        for inv in invoices:
            total = _dec(inv.grand_total)
            if total is None:
                continue
            if abs(total - amount) > amount_tolerance:
                continue
            if not _date_within(line.line_date, inv, day_tolerance):
                continue
            if not _vendor_matches(
                line.narration, inv, aliases_by_invoice.get(str(inv.id), [])
            ):
                continue
            # A debit pays an INBOUND bill; a credit settles an OUTBOUND one.
            wanted_direction = "INBOUND" if side == "debit" else "OUTBOUND"
            if (inv.flow_direction or "INBOUND") != wanted_direction:
                continue
            candidates.append(inv)

        entry = {
            "line_id": str(line.id),
            "line_date": line.line_date.isoformat() if line.line_date else None,
            "narration": line.narration,
            "amount": float(amount),
            "side": side,
            "utr_ref": line.utr_ref,
        }

        if not candidates:
            (result["unmatched_debits"] if side == "debit" else result["unmatched_credits"]).append(
                entry
            )
            continue

        if len(candidates) > 1:
            entry["candidates"] = [
                {"invoice_id": str(c.id), "invoice_number": c.invoice_number} for c in candidates
            ]
            result["ambiguous"].append(entry)
            continue

        invoice = candidates[0]
        entry["invoice_id"] = str(invoice.id)
        entry["invoice_number"] = invoice.invoice_number
        entry["invoice_total"] = float(_dec(invoice.grand_total) or 0)
        entry["invoice_status"] = invoice.status

        already_claimed = claimed.get(str(invoice.id))
        if already_claimed is not None:
            entry["duplicate_of_line_id"] = already_claimed
            entry["reason"] = "two payments on this statement match the same bill"
            result["possible_duplicates"].append(entry)
            continue
        if (invoice.status or "") in _SETTLED_STATUSES:
            entry["reason"] = "this bill is already marked paid in your records"
            result["possible_duplicates"].append(entry)
            claimed[str(invoice.id)] = entry["line_id"]
            continue

        claimed[str(invoice.id)] = entry["line_id"]
        result["matched"].append(entry)

    return result


def _date_within(line_date: Optional[date], invoice: Any, days: int) -> bool:
    """Is the row close enough in time to this invoice?

    Measured against the DUE date when there is one and the invoice date
    otherwise: a payment lands near when it was due, not near when the bill was
    written, and a 60-day term would otherwise put every on-time payment outside
    the window.
    """
    if line_date is None:
        return False
    reference = invoice.due_date or invoice.invoice_date
    if reference is None:
        return False
    return abs((line_date - reference).days) <= days


def apply_matches(match_result: dict, lines: Sequence[Any], db_session: Any) -> int:
    """Write the verdicts onto the ledger rows. Returns how many rows changed.

    Separate from `match_statement_lines()` so a match can be computed and shown
    without being committed. Nothing outside `bank_statement_line` is written --
    Gap 492.
    """
    by_id = {str(line.id): line for line in lines}
    changed = 0

    def _write(entry: dict, status: str, confidence: str, invoice_id=None) -> None:
        nonlocal changed
        line = by_id.get(entry["line_id"])
        if line is None:
            return
        line.match_status = status
        line.match_confidence = confidence
        if invoice_id is not None:
            from uuid import UUID

            try:
                line.matched_invoice_id = UUID(str(invoice_id))
            except (ValueError, TypeError):
                line.matched_invoice_id = None
        db_session.add(line)
        changed += 1

    for entry in match_result.get("matched", []):
        _write(entry, MATCH_MATCHED, "high", entry.get("invoice_id"))
    for entry in match_result.get("possible_duplicates", []):
        _write(entry, MATCH_DUPLICATE, "med", entry.get("invoice_id"))
    for entry in match_result.get("ambiguous", []):
        # No invoice id: the whole point of AMBIGUOUS is that we do not know
        # which one, and writing the first candidate would turn "we cannot tell"
        # into a wrong answer.
        _write(entry, MATCH_AMBIGUOUS, "low")

    if changed:
        db_session.commit()
    return changed


def cash_cover(
    balance: Optional[float],
    overdue_rows: Sequence[dict],
    upcoming_rows: Sequence[dict],
    statement_date: Optional[date],
) -> dict:
    """The async cash-cover card's arithmetic: what is due against what is there.

    Buckets are 7 / 30 / 60 days FROM THE STATEMENT DATE, not from today (§8.5:
    every figure is labelled "as of <statement date>"). A statement three weeks
    old describes three-week-old money, and silently re-basing it on today is the
    most misleading thing this card could do.

    Returns figures only; the prose is the narrator's and the thresholds are not
    involved -- this is arithmetic, not a gate.
    """
    from decimal import Decimal as D

    as_of = statement_date
    buckets = {"due_7": D("0"), "due_30": D("0"), "due_60": D("0")}
    overdue_total = D("0")

    for row in overdue_rows or []:
        overdue_total += _dec(row.get("grand_total")) or D("0")

    for row in upcoming_rows or []:
        due = row.get("due_date")
        amount = _dec(row.get("grand_total")) or D("0")
        if due is None or as_of is None:
            continue
        days = (due - as_of).days
        if days < 0:
            continue
        if days <= 7:
            buckets["due_7"] += amount
        if days <= 30:
            buckets["due_30"] += amount
        if days <= 60:
            buckets["due_60"] += amount

    bal = _dec(balance)
    shortfall_30 = None
    if bal is not None:
        shortfall_30 = float(round(buckets["due_30"] + overdue_total - bal, 2))

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "closing_balance": float(bal) if bal is not None else None,
        "overdue_total": float(round(overdue_total, 2)),
        "due_within_7_days": float(round(buckets["due_7"], 2)),
        "due_within_30_days": float(round(buckets["due_30"], 2)),
        "due_within_60_days": float(round(buckets["due_60"], 2)),
        # Positive means the 30-day commitments plus what is already overdue
        # exceed the closing balance. None when there is no balance to compare
        # against -- an unknown is not a zero.
        "shortfall_within_30_days": shortfall_30,
    }
