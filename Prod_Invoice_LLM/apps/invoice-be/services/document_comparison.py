"""Feature 26 (Gap 366) — deterministic comparison of an attached reference
document (purchase order / quotation) against the tenant's invoices.

**There is no LLM anywhere in this module, and there must never be one.**
Hard rule 3 of `.claude/CONVENTIONS.md`: any check that decides correctness
(math, reconciliation, sign handling, validation) is deterministic code. Gaps
220-225 and 253 are all the same failure mode — a prompt rule used as a control.
The LLM's role in this feature is strictly downstream: it receives the diff
table this module returns and narrates it. It never computes a figure and never
decides whether two documents agree.

Money is `Decimal`, never `float`, for the arithmetic. The stored columns are
floats (`Invoice.grand_total`), so the conversion happens once at the boundary
via `_to_decimal()` and every comparison after that is exact.

The value-normalisation shape is deliberately modelled on Feature 18's
`_normalize_for_diff` / `_DIFFABLE_FIELDS` (`routers/chat.py` L884-913) rather
than being a second invention. That function already solves "the stored column
is a float `110.0` and the rendered value is the string `'$110.00'`, and those
are the same money".
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from sqlmodel import Session, select

from models import Invoice

logger = logging.getLogger(__name__)

#: Tier 2's date window, either side of the reference document's own date.
CANDIDATE_DATE_WINDOW_DAYS = 90

#: Tier 2's hard cap. A vendor-substring match with no PO number to pin it down
#: can legitimately return hundreds of rows for a frequent supplier; asking a
#: user to confirm 300 invoices is not a confirmation, it is a rubber stamp.
CANDIDATE_LIMIT = 20

#: Money fields compared line-for-line between the reference doc and an invoice.
#: Deliberately the stored scalar columns only, exactly as `_DIFFABLE_FIELDS`
#: restricts itself — diffing a JSON items blob against prose has no defensible
#: definition of "match", and neither does diffing a PO's delivery terms.
_COMPARED_AMOUNT_FIELDS = ("subtotal", "tax_amount", "grand_total")

#: Below this, two figures are the same money. Not zero: the reference document
#: and the invoice are two independently-OCR'd printed pages, and a half-cent
#: apart is a rounding artefact, not an over-bill.
AMOUNT_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalize_doc_number(value: Optional[str]) -> str:
    """Comparable form of a PO/document number.

    Vendors print the same PO as `PO-2024/0043`, `PO 2024 0043` and
    `po20240043`. Tier 1 is an *exact* join and would miss all three of each
    other, so the join happens on this normalised form: uppercased, with every
    character that is not a letter or a digit removed.

    Deliberately NOT a fuzzy match. Dropping punctuation is a formatting
    equivalence; dropping a digit is a different purchase order. `PO-1` and
    `PO-11` must not collapse, and they do not.
    """
    if value is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Money as an exact `Decimal`, or None if there is no figure at all.

    None means "the document did not state this", which is a materially
    different thing from zero and is reported as `missing` rather than as a
    variance of the full amount.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "").lstrip("$€£₹").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _normalize_currency(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _normalize_party(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _coerce_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2 candidate matching (decision D4)
# ---------------------------------------------------------------------------
def find_candidate_invoices(
    *,
    tenant_id: str,
    po_number: Optional[str],
    party_name: Optional[str],
    doc_date: Any,
    db_session: Session,
) -> Dict[str, Any]:
    """Find the invoices an attached reference document plausibly corresponds to.

    Two tiers, and the second runs **only** when the first returns nothing:

    - **Tier 1** — normalised `po_number` exact match. A PO number is an
      identifier the two documents were meant to share; when it is present and
      it matches, that is not a heuristic, it is the answer.
    - **Tier 2** — vendor-name substring AND `invoice_date` within
      ±`CANDIDATE_DATE_WINDOW_DAYS` of the document's date, capped at
      `CANDIDATE_LIMIT`. This IS a heuristic, which is precisely why the flow
      never acts on it without the user confirming (D4).

    Tier 2 is a fallback, not a supplement: running it alongside Tier 1 would
    dilute an exact identifier match with a pile of same-vendor near-misses and
    hand the user a confirmation list where the right answer is not obviously
    the right answer.

    Returns `{"tier": 1|2|0, "invoices": [...], "truncated": bool}`. Tier 0 means
    no candidates at all — a real, reportable outcome, never a reason to widen
    the search until something turns up.
    """
    normalized_po = normalize_doc_number(po_number)

    base = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.deleted_at == None,  # noqa: E711 — SQLAlchemy IS NULL
    )

    # --- Tier 1 -------------------------------------------------------------
    if normalized_po:
        # The normalisation has no SQL equivalent that is portable across
        # Postgres and SQLite (Postgres has regexp_replace, SQLite does not), so
        # the candidate set is narrowed in SQL on `po_number IS NOT NULL` and
        # the normalised equality is applied in Python. This is the deliberate
        # opposite of Gap 253's mistake: the SQL here is a parameterised query
        # we wrote, and the string handling is plain Python on values we already
        # hold — not a regex rewriter over model-generated SQL.
        rows = db_session.exec(base.where(Invoice.po_number != None)).all()  # noqa: E711
        tier1 = [r for r in rows if normalize_doc_number(r.po_number) == normalized_po]
        if tier1:
            return {"tier": 1, "invoices": tier1, "truncated": False}

    # --- Tier 2 -------------------------------------------------------------
    normalized_party = _normalize_party(party_name)
    reference_date = _coerce_date(doc_date)
    if not normalized_party or reference_date is None:
        # Both halves of Tier 2 are required (AND, not OR). Without a date,
        # "every invoice from this vendor ever" is not a candidate set; without
        # a party, "every invoice in this quarter" is worse.
        return {"tier": 0, "invoices": [], "truncated": False}

    window_start = reference_date - timedelta(days=CANDIDATE_DATE_WINDOW_DAYS)
    window_end = reference_date + timedelta(days=CANDIDATE_DATE_WINDOW_DAYS)

    dated = db_session.exec(
        base.where(
            Invoice.invoice_date != None,  # noqa: E711
            Invoice.invoice_date >= window_start,
            Invoice.invoice_date <= window_end,
        )
    ).all()

    matches = []
    for row in dated:
        # Either side of the invoice's party naming, because the tenant's own
        # outbound invoices carry `customer_name` and inbound bills carry
        # `vendor_name` — a quotation the tenant ISSUED matches the former.
        for candidate_party in (row.vendor_name, row.customer_name):
            normalized_candidate = _normalize_party(candidate_party)
            if not normalized_candidate:
                continue
            if (
                normalized_party in normalized_candidate
                or normalized_candidate in normalized_party
            ):
                matches.append(row)
                break

    truncated = len(matches) > CANDIDATE_LIMIT
    if truncated:
        # Nearest by date first, so the cap keeps the most plausible ones rather
        # than whichever the database happened to return first.
        matches.sort(key=lambda r: abs((r.invoice_date - reference_date).days))
        matches = matches[:CANDIDATE_LIMIT]

    if not matches:
        return {"tier": 0, "invoices": [], "truncated": False}
    return {"tier": 2, "invoices": matches, "truncated": truncated}


# ---------------------------------------------------------------------------
# The comparison itself (decision D5)
# ---------------------------------------------------------------------------
def _compare_one(reference: Dict[str, Any], invoice: Invoice) -> Dict[str, Any]:
    """One reference document against one invoice. Pure arithmetic."""
    ref_currency = _normalize_currency(reference.get("currency"))
    inv_currency = _normalize_currency(invoice.currency)

    # --- Currency mismatch: a HARD STOP, not a diff row ---------------------
    # If the PO is in EUR and the invoice is in INR, there is no honest
    # arithmetic to do. This module holds no FX rate, and inventing one to make
    # the comparison "work" would produce a confident wrong answer about money —
    # the exact outcome this feature exists to prevent. It is also not silently
    # dropped: the outcome is reported so the user sees WHY there is no number.
    if ref_currency and inv_currency and ref_currency != inv_currency:
        return {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "invoice_status": invoice.status,
            "flow_direction": invoice.flow_direction,
            "outcome": "currency_mismatch",
            "reference_currency": ref_currency,
            "invoice_currency": inv_currency,
            "fields": [],
            "blocked_reason": (
                f"The attached document is in {ref_currency} and this invoice is in "
                f"{inv_currency}. No amounts were compared: converting between "
                f"currencies is not something this comparison does."
            ),
        }

    fields: List[Dict[str, Any]] = []
    any_variance = False
    any_missing = False

    for field in _COMPARED_AMOUNT_FIELDS:
        ref_value = _to_decimal(reference.get(field))
        inv_value = _to_decimal(getattr(invoice, field, None))

        if ref_value is None or inv_value is None:
            any_missing = True
            fields.append(
                {
                    "field": field,
                    "reference_value": str(ref_value) if ref_value is not None else None,
                    "invoice_value": str(inv_value) if inv_value is not None else None,
                    "delta": None,
                    "status": "missing",
                }
            )
            continue

        delta = inv_value - ref_value
        if abs(delta) <= AMOUNT_TOLERANCE:
            status = "match"
        elif delta > 0:
            # The invoice asks for more than the document authorised.
            status = "invoice_higher"
            any_variance = True
        else:
            status = "invoice_lower"
            any_variance = True

        fields.append(
            {
                "field": field,
                "reference_value": str(ref_value),
                "invoice_value": str(inv_value),
                "delta": str(delta),
                "status": status,
            }
        )

    # Line-count only, not a line-by-line text diff: matching a PO line to an
    # invoice line requires deciding that "Widget, blue, 10pk" and "Blue widget
    # x10" are the same item, which is a judgement call and therefore not
    # something a deterministic module should assert.
    ref_items = reference.get("items") or []
    inv_items = invoice.items or []
    line_delta = len(inv_items) - len(ref_items)

    if any_variance:
        outcome = "variance"
    elif any_missing:
        outcome = "incomplete"
    else:
        outcome = "match"

    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "invoice_status": invoice.status,
        "flow_direction": invoice.flow_direction,
        "outcome": outcome,
        "reference_currency": ref_currency or None,
        "invoice_currency": inv_currency or None,
        "fields": fields,
        "reference_line_count": len(ref_items),
        "invoice_line_count": len(inv_items),
        "line_count_delta": line_delta,
        "blocked_reason": None,
    }


def compare_reference_to_invoices(
    reference: Dict[str, Any],
    invoices: Sequence[Invoice],
) -> Dict[str, Any]:
    """The diff table. Deterministic, `Decimal`, no LLM (D5).

    `reference` is the extracted reference-document payload (the
    `ReferenceDocExtractionSchema` shape, or a `ChatAttachment`'s
    `extracted_json`). The return value is what gets handed to the synthesis
    prompt, and the prompt's instruction is that it may not state a number that
    is not present here.
    """
    comparisons = [_compare_one(reference, inv) for inv in invoices]
    return {
        "reference": {
            "doc_type": reference.get("doc_type"),
            "doc_number": reference.get("doc_number"),
            "party_name": reference.get("party_name"),
            "doc_date": reference.get("doc_date"),
            "currency": _normalize_currency(reference.get("currency")) or None,
            "grand_total": (
                str(_to_decimal(reference.get("grand_total")))
                if _to_decimal(reference.get("grand_total")) is not None
                else None
            ),
        },
        "comparisons": comparisons,
        "compared_count": len(comparisons),
        "blocked_count": sum(
            1 for c in comparisons if c["outcome"] == "currency_mismatch"
        ),
    }


# ---------------------------------------------------------------------------
# Suggested actions (decision D6)
# ---------------------------------------------------------------------------
# A deterministic map, NOT an LLM choice, because the real endpoints have legal
# transition rules an LLM would cheerfully violate. Each entry states the
# precondition the endpoint itself enforces; the builder checks it before it
# emits the link, so a suggestion is never one the endpoint would 400 on.
#
# Two semantics that are easy to get wrong and are respected in the copy below:
#   * OVERDUE is computed at read time and is never a stored status — nothing
#     here suggests "mark it overdue", because there is nothing to mark.
#   * Inbound AUDIT_REQUIRED means a math/data flag was raised, NOT that the
#     invoice is unpaid. The copy says "review the flagged figures", not "pay".
#
# Everything here is a LINK. Chat does not call any of these (D6). There is no
# new flag/dispute/hold/escalate route and none is proposed.
_OUTBOUND_CONFIRM_SEND_STATUSES = {"VERIFIED", "NEEDS_REVIEW"}
_OUTBOUND_MARK_PAID_STATUSES = {"SENT"}
_INBOUND_AUDIT_RESOLVE_STATUSES = {"AUDIT_REQUIRED"}


def build_suggested_actions(comparison: Dict[str, Any]) -> List[Dict[str, str]]:
    """0-3 deep-links for one invoice comparison, from the deterministic map.

    Returns an empty list when nothing legal applies — an empty list is a
    correct answer here, and padding it with a link the endpoint would reject
    would be worse than offering nothing.
    """
    actions: List[Dict[str, str]] = []
    status = (comparison.get("invoice_status") or "").upper()
    direction = (comparison.get("flow_direction") or "INBOUND").upper()
    outcome = comparison.get("outcome")
    invoice_id = comparison.get("invoice_id")

    if not invoice_id:
        return actions

    if outcome in ("variance", "currency_mismatch", "incomplete"):
        if direction == "INBOUND":
            if status in _INBOUND_AUDIT_RESOLVE_STATUSES:
                actions.append(
                    {
                        "label": "Review the flagged figures on this invoice",
                        "endpoint": f"/api/v1/audit/resolve/{invoice_id}",
                        "method": "PUT",
                        "href": f"/auditor/{invoice_id}",
                        # Precondition: routers/audit.py restricts the
                        # resolution status to PAID / REJECTED /
                        # AUDIT_REQUIRED. Not stated as "pay this" — inbound
                        # AUDIT_REQUIRED is a data flag, not an unpaid marker.
                        "precondition": "status is AUDIT_REQUIRED",
                    }
                )
            actions.append(
                {
                    "label": "Open this invoice in the Trainer to correct extraction",
                    "endpoint": f"/api/v1/trainer/invoice/{invoice_id}",
                    "method": "GET",
                    "href": f"/trainer/{invoice_id}",
                    "precondition": "none (read-only destination)",
                }
            )
        else:
            if status in _OUTBOUND_CONFIRM_SEND_STATUSES:
                actions.append(
                    {
                        "label": "Review before sending this invoice",
                        "endpoint": f"/api/v1/outbound-invoices/{invoice_id}/confirm-send",
                        "method": "POST",
                        "href": f"/outbound/{invoice_id}",
                        "precondition": "status is VERIFIED or NEEDS_REVIEW",
                    }
                )
            actions.append(
                {
                    "label": "Resolve the audit findings on this invoice",
                    "endpoint": f"/api/v1/outbound-audit/{invoice_id}/resolve",
                    "method": "PUT",
                    "href": f"/outbound-auditor/{invoice_id}",
                    # This endpoint never changes status, so it has no
                    # status precondition to check.
                    "precondition": "none (does not change status)",
                }
            )

    if outcome == "match" and direction == "OUTBOUND":
        if status in _OUTBOUND_CONFIRM_SEND_STATUSES:
            actions.append(
                {
                    "label": "Send this invoice",
                    "endpoint": f"/api/v1/outbound-invoices/{invoice_id}/confirm-send",
                    "method": "POST",
                    "href": f"/outbound/{invoice_id}",
                    "precondition": "status is VERIFIED or NEEDS_REVIEW",
                }
            )
        elif status in _OUTBOUND_MARK_PAID_STATUSES:
            actions.append(
                {
                    "label": "Mark this invoice paid",
                    "endpoint": f"/api/v1/outbound-invoices/{invoice_id}/mark-paid",
                    "method": "POST",
                    "href": f"/outbound/{invoice_id}",
                    "precondition": "status is SENT",
                }
            )

    return actions[:3]


# ---------------------------------------------------------------------------
# The confirmation gate (decision D4)
# ---------------------------------------------------------------------------
def build_confirmation_payload(
    *,
    attachment_id: str,
    doc_type: Optional[str],
    doc_number: Optional[str],
    tier: int,
    invoices: Sequence[Invoice],
    truncated: bool = False,
) -> Dict[str, Any]:
    """What the assistant returns INSTEAD of an answer, until the user confirms.

    This is the whole point of D4: never a silent match on financial data. A
    Tier 2 candidate set in particular is a heuristic guess, and telling a user
    "you were over-billed by 4,000" against an invoice the system guessed at is
    a worse outcome than asking one extra question.

    Zero candidates says so plainly and offers manual entry. It never widens the
    search, and it never picks the closest thing it found.
    """
    label = {"PURCHASE_ORDER": "purchase order", "QUOTATION": "quotation"}.get(
        (doc_type or "").upper(), "document"
    )
    if not invoices:
        return {
            "kind": "attachment_match_confirmation",
            "attachment_id": attachment_id,
            "tier": 0,
            "candidates": [],
            "requires_manual_entry": True,
            "message": (
                f"I could not find any invoice matching that {label}"
                + (f" ({doc_number})" if doc_number else "")
                + ". Tell me the invoice number you want it compared against and "
                "I will use that."
            ),
        }

    how = (
        "by an exact PO-number match"
        if tier == 1
        else "by supplier name and date (no PO number matched), so please check these carefully"
    )
    return {
        "kind": "attachment_match_confirmation",
        "attachment_id": attachment_id,
        "tier": tier,
        "requires_manual_entry": False,
        "truncated": truncated,
        "candidates": [
            {
                "invoice_id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "party_name": inv.vendor_name or inv.customer_name,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "grand_total": inv.grand_total,
                "currency": inv.currency,
                "status": inv.status,
                "flow_direction": inv.flow_direction,
            }
            for inv in invoices
        ],
        "message": (
            f"I found {len(invoices)} invoice(s) that may correspond to this {label} "
            f"{how}. Confirm which one(s) I should compare it against and I will "
            "give you the figures."
            + (
                f" (Showing the {CANDIDATE_LIMIT} closest by date; there were more.)"
                if truncated
                else ""
            )
        ),
    }
