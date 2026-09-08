"""Feature 30 task 30.0c — landing a bank statement's rows as a ledger.

WHY A TABLE AND NOT JUST `extracted_json`
-----------------------------------------
Every other document type in this feature is answered from its header: a PO has
a total, a credit note has an amount. A statement's value is entirely in its
ROWS — "which of these 40 debits are payments we already recorded?" — and three
things follow from that:

* the matcher writes a verdict PER ROW (`match_status`, `matched_invoice_id`),
  and there is nowhere in a JSON blob to put a verdict that survives a reload;
* the same question is asked again later ("is that debit still unmatched?"), and
  re-parsing the blob each time would let the answer drift as the ledger moves;
* a user confirming one match must not have to re-confirm the other 39.

So the rows are landed once, here, and everything downstream reads the table.

WHAT THIS IS NOT
----------------
Not invoices, not payments. A debit on a statement is EVIDENCE that a payment may
have happened, not the payment itself — Feature 26 decision D2's rule, applied one
document type further along. Nothing in this module writes to `invoice`, and
after Gap 492 nothing in this feature does.

IDEMPOTENCE
-----------
`land_statement_lines()` replaces the attachment's existing rows. A statement is
re-read only when it is re-extracted, and the second read is the truth; keeping
both would double every figure the cash-cover card computes. Matches confirmed by
a user are preserved across the replace — see `_carry_forward_matches()`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

#: Narration prefixes that mean the row is a bank's own charge, not a payment to
#: a supplier. Used only to LABEL a row; nothing is excluded from the ledger,
#: because a charge is still money that left the account.
BANK_CHARGE_HINTS = (
    "bank charge", "service charge", "sms charge", "amc", "atm", "interest",
    "gst on", "cheque return", "penalty",
)


def _to_date(value: Any) -> Optional[date]:
    """A printed date as a `date`, or None. Never guesses a format it cannot read."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    """A printed amount as a float, or None.

    None and 0.0 are different answers and stay different: an empty debit column
    is `None`, and a genuinely printed 0.00 is `0.0`. Collapsing them is the
    `None`-is-not-zero defect Gap 283 fixed on the invoice side.
    """
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_statement_lines(extracted_json: Optional[dict]) -> list:
    """Normalised rows from an extraction, in printed order.

    Reads `statement_lines` (the field Feature 30 added to the REFERENCE schema)
    and falls back to `referenced_documents` for a statement that was extracted
    BEFORE that field existed — an old row still has a list of references, and a
    reference with an amount is a usable, if poorer, ledger line. The fallback is
    marked so the confidence of anything computed from it can say where it came
    from.
    """
    data = extracted_json or {}
    out: list = []

    for raw in data.get("statement_lines") or []:
        if not isinstance(raw, dict):
            continue
        out.append(
            {
                "line_date": _to_date(raw.get("line_date")),
                "narration": (raw.get("narration") or None),
                "debit": _to_float(raw.get("debit")),
                "credit": _to_float(raw.get("credit")),
                "balance": _to_float(raw.get("balance")),
                "utr_ref": (raw.get("utr_ref") or None),
                "source": "statement_lines",
            }
        )
    if out:
        return out

    for raw in data.get("referenced_documents") or []:
        if not isinstance(raw, dict):
            continue
        amount = _to_float(raw.get("amount"))
        if amount is None:
            continue
        # A reference carries no side, so the SIGN is the only signal available:
        # a negative amount on a statement's reference list is a credit. This is
        # weaker than a real debit/credit column and is why `source` is recorded.
        out.append(
            {
                "line_date": _to_date(raw.get("doc_date")),
                "narration": raw.get("doc_number"),
                "debit": amount if amount > 0 else None,
                "credit": abs(amount) if amount < 0 else None,
                "balance": None,
                "utr_ref": raw.get("doc_number"),
                "source": "referenced_documents",
            }
        )
    return out


def detect_statement_date(extracted_json: Optional[dict], lines: Sequence[dict]) -> Optional[date]:
    """The "as of" date every statement figure is true at.

    The printed `statement_date` first, then the document's own `doc_date`, then
    the LATEST line date — in that order, because the first two are statements of
    fact by the document and the third is an inference from its contents. Nothing
    falls back to today: "as of today" on a statement that is three weeks old is
    the single most misleading thing this feature could print.
    """
    data = extracted_json or {}
    for key in ("statement_date", "doc_date"):
        parsed = _to_date(data.get(key))
        if parsed:
            return parsed
    dates = [line["line_date"] for line in lines if line.get("line_date")]
    return max(dates) if dates else None


def is_bank_charge(narration: Optional[str]) -> bool:
    """Is this row the bank's own charge rather than a business payment?"""
    text = (narration or "").lower()
    return any(hint in text for hint in BANK_CHARGE_HINTS)


def _carry_forward_matches(existing: Sequence[Any]) -> dict:
    """Keep user-confirmed matches across a re-extraction.

    Keyed on (date, amount, reference) rather than on row id: the ids are
    regenerated by the replace, and a statement re-read from the same PDF prints
    the same rows. A row that has moved or changed is simply not carried, which
    is the safe direction — an unmatched row is a question, a wrongly carried
    match is a wrong answer.
    """
    carried = {}
    for row in existing:
        if row.match_status in ("MATCHED", "POSSIBLE_DUPLICATE") and row.matched_invoice_id:
            key = (row.line_date, row.debit, row.credit, (row.utr_ref or "").strip())
            carried[key] = (row.matched_invoice_id, row.match_status, row.match_confidence)
    return carried


def land_statement_lines(row: Any, db_session: Any) -> list:
    """Write this attachment's ledger rows and set `statement_date`. Returns them.

    Total by design: a statement whose rows could not be read lands zero rows and
    sets no date, and the bank card then reports "no transaction rows could be
    read" rather than a reconciliation that did not happen.
    """
    from sqlmodel import select

    from models import BankStatementLine

    parsed = parse_statement_lines(row.extracted_json)
    statement_date = detect_statement_date(row.extracted_json, parsed)

    try:
        existing = db_session.exec(
            select(BankStatementLine).where(BankStatementLine.attachment_id == row.id)
        ).all()
        carried = _carry_forward_matches(existing)
        for old in existing:
            db_session.delete(old)

        created = []
        for line in parsed:
            key = (line["line_date"], line["debit"], line["credit"], (line["utr_ref"] or "").strip())
            matched_id, match_status, match_confidence = carried.get(key, (None, "UNMATCHED", None))
            created.append(
                BankStatementLine(
                    tenant_id=row.tenant_id,
                    attachment_id=row.id,
                    statement_date=statement_date,
                    line_date=line["line_date"],
                    narration=(line["narration"] or None) and str(line["narration"])[:1024],
                    debit=line["debit"],
                    credit=line["credit"],
                    balance=line["balance"],
                    utr_ref=(line["utr_ref"] or None) and str(line["utr_ref"])[:128],
                    matched_invoice_id=matched_id,
                    match_status=match_status,
                    match_confidence=match_confidence,
                )
            )
        for line_row in created:
            db_session.add(line_row)

        row.statement_date = statement_date
        db_session.add(row)
        db_session.commit()
        for line_row in created:
            db_session.refresh(line_row)
        return created
    except Exception as exc:
        logger.error("Could not land statement lines for attachment %s: %s", row.id, exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []


def statement_lines_for(attachment_id: Any, db_session: Any) -> list:
    """This attachment's ledger, oldest row first."""
    from sqlmodel import select

    from models import BankStatementLine

    rows = db_session.exec(
        select(BankStatementLine).where(BankStatementLine.attachment_id == attachment_id)
    ).all()
    return sorted(rows, key=lambda r: (r.line_date or date.min, r.created_at))


def closing_balance(lines: Sequence[Any]) -> Optional[float]:
    """The balance on the last row that printed one.

    Read, never computed: a statement's own arithmetic is what it states, and
    summing debits and credits to "check" it would produce a second, competing
    figure for the same thing.
    """
    for row in reversed(list(lines)):
        if row.balance is not None:
            return float(row.balance)
    return None
