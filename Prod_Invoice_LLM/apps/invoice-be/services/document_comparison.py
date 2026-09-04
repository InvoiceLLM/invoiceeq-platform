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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
# ---------------------------------------------------------------------------
# Tier 3 — vector discovery (E-4, task H6/R9)
# ---------------------------------------------------------------------------

# Tighter than Tier 2's 20, deliberately (E-4). A date-window list degrades
# gracefully -- the 20th entry is still the same vendor in the same quarter. A
# similarity list does not: past the first handful the entries are only "nearest
# available", and a long one invites a user to scroll until something looks
# plausible, which is the failure mode the confirmation gate exists to prevent.
TIER3_CANDIDATE_LIMIT = 10


def _tier3_candidates(
    *,
    tenant_id: str,
    query_text: str,
    db_session: Session,
    limit: int = TIER3_CANDIDATE_LIMIT,
) -> List[Invoice]:
    """Nearest invoices by vector similarity over the tenant's OWN collection.

    E-4's motivating case, which Tier 2 cannot serve: Tier 2 needs BOTH a party
    name AND a date, so a scan with a smudged date finds nothing at all -- not a
    poor match, nothing. That is the concrete mechanism behind the founder's
    complaint, and this is the fallback for it.

    WHAT MAKES THIS SAFE, and it is not the ranking. A vector search is
    non-deterministic and this function's output is therefore never an answer: it
    is a LIST OF PROPOSALS that goes through the same confirmation gate as
    everything else (D4). The human decides; the arithmetic that follows is the
    identical `compare_reference_to_invoices()` on the identical `Decimal` math.
    Tier 3 changes only WHICH invoices get compared.

    Tenant isolation is structural, not filtered: `query_invoice_chunks()` reads
    `invoice_chunks_{tenant_id}`, a per-tenant collection (Gap 55), so another
    tenant's invoice cannot appear in this list by construction rather than by a
    predicate someone has to remember.

    Soft-deleted invoices are excluded here rather than left to the caller --
    Chroma has no idea a row was deleted (Gap 192's soft delete is a Postgres
    concern), so a chunk for a deleted invoice is still indexed and would
    otherwise be proposed.
    """
    if not query_text or not query_text.strip():
        return []

    try:
        from chroma_client import query_invoice_chunks

        # Over-fetch: several chunks routinely belong to one invoice (one per
        # page), so `limit` chunks can collapse to far fewer distinct invoices.
        chunks = query_invoice_chunks(str(tenant_id), query_text, limit=limit * 3)
    except Exception as e:
        # Never fail the turn on a retrieval problem. Tier 3 is a fallback for a
        # case that already returned nothing; an unreachable Chroma means the
        # user gets Part 1's honest "no matches found", which is exactly what
        # they would have got before this tier existed.
        logger.warning("Tier 3 vector discovery unavailable for tenant %s: %s", tenant_id, e)
        return []

    ordered_ids: List[str] = []
    for chunk in chunks or []:
        invoice_id = (chunk.get("metadata") or {}).get("invoice_id")
        if invoice_id and invoice_id not in ordered_ids:
            ordered_ids.append(invoice_id)
        if len(ordered_ids) >= limit:
            break

    if not ordered_ids:
        return []

    # One query for the whole set, then reordered in Python to preserve SIMILARITY
    # order -- SQL `IN` returns rows in whatever order it likes, and the ranking is
    # the only thing Tier 3 has to offer. `tenant_id` is re-asserted here as a
    # second, independent check: the collection is already per-tenant, but a row
    # this function returns is about to be compared against money, and two
    # independent guarantees is the right number for that.
    rows = db_session.exec(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.deleted_at.is_(None),
        )
    ).all()
    by_id = {str(row.id): row for row in rows}
    return [by_id[i] for i in ordered_ids if i in by_id]


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
        #
        # Tier 3 (E-4) fires HERE as well as after an empty Tier 2, and this is
        # the path that matters most: a scan with a smudged date lands on exactly
        # this branch, and it is the founder's own motivating case. Returning
        # tier 0 from here would have left the tier unreachable for the document
        # it was designed for -- which is what the first implementation did, and
        # what V-12's "fires only when both earlier tiers are empty" caught.
        tier3 = _tier3_candidates(
            tenant_id=tenant_id,
            query_text=" ".join(
                str(part) for part in (party_name, po_number, doc_date) if part
            ),
            db_session=db_session,
        )
        if tier3:
            return {"tier": 3, "invoices": tier3, "truncated": False}
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
        # Tier 3 (E-4): only when Tiers 1 AND 2 are both empty. Never a
        # supplement -- running it alongside a real match would dilute an exact
        # identifier join with a pile of "nearest available" guesses, which is
        # the same reasoning that makes Tier 2 a fallback rather than an addition.
        tier3 = _tier3_candidates(
            tenant_id=tenant_id,
            query_text=" ".join(
                str(part) for part in (party_name, po_number, doc_date) if part
            ),
            db_session=db_session,
        )
        if tier3:
            return {"tier": 3, "invoices": tier3, "truncated": False}
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

    # E-4: a Tier-3 proposal must NEVER read like a Tier-1 join. The tier is the
    # user's only signal of how much the system actually knows, and the three
    # strengths are genuinely different claims -- an exact identifier both
    # documents were meant to share, a name-and-date heuristic, and "these came
    # back nearest in a vector search". Presenting the third in the second's
    # language is how a guess gets confirmed by someone skim-reading.
    how = {
        1: "by an exact PO-number match",
        2: "by supplier name and date (no PO number matched), so please check these carefully",
        3: (
            "by similarity only — no PO number and no supplier-and-date match was found, "
            "so these are the closest documents on record rather than a match. "
            "Please confirm they are the right invoices before I compare anything"
        ),
    }.get(tier, "by supplier name and date (no PO number matched), so please check these carefully")
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


# ===========================================================================
# compare_documents() — B3/B7/B8, task R10
#
# A SIBLING of `compare_reference_to_invoices()`, not a replacement and not a
# wrapper. That function's determinism is the control the whole feature rests on
# and it is deliberately NOT modified, NOT called from here, and NOT rewritten.
# Everything below is additive.
#
# No LLM appears anywhere in this module and none may be added (hard rule 3).
# ===========================================================================

MONEY_MODE = "money"
QUANTITY_MODE = "quantity"
BOTH_MODE = "both"
LIST_RECONCILE_MODE = "list_reconcile"
COMPARISON_MODES: Tuple[str, ...] = (MONEY_MODE, QUANTITY_MODE, BOTH_MODE, LIST_RECONCILE_MODE)

# B7's mode table, keyed on the ATTACHMENT's doc_type. Exhaustive over Feature
# 27's fourteen values so a new type cannot silently inherit a mode that suits
# something else -- an omission here resolves to None, which clarifies rather
# than guesses.
_MODE_BY_DOC_TYPE: Dict[str, str] = {
    # Commitment vs claim: both what was agreed AND how much.
    "PURCHASE_ORDER": BOTH_MODE,
    "ORDER_CONFIRMATION": BOTH_MODE,
    "QUOTATION": BOTH_MODE,
    "PROFORMA_INVOICE": BOTH_MODE,
    "CONTRACT": BOTH_MODE,
    # Prices are frequently absent BY DESIGN, so "did they bill what they
    # shipped?" is a quantity question and pricing one would manufacture the
    # false discrepancy Feature 27 exists to remove.
    "DELIVERY_NOTE": QUANTITY_MODE,
    "GRN": QUANTITY_MODE,
    # Money document against a money row.
    "INVOICE": MONEY_MODE,
    "CREDIT_NOTE": MONEY_MODE,
    "DEBIT_NOTE": MONEY_MODE,
    "RECEIPT": MONEY_MODE,
    # No line items to diff -- a list of pointers at other documents (B8).
    "STATEMENT_OF_ACCOUNT": LIST_RECONCILE_MODE,
    "REMITTANCE_ADVICE": LIST_RECONCILE_MODE,
    # OTHER is deliberately absent: we do not know what it is, so there is no
    # defensible mode and the turn clarifies instead.
}

# L3's floor. Two lines must share this proportion of their description tokens
# AND corroborate on quantity or price before L3 will accept them.
L3_TOKEN_OVERLAP_THRESHOLD = 0.6


def resolve_comparison_mode(doc_type: Optional[str]) -> Optional[str]:
    """Which comparison this document type gets, or None to clarify.

    Deterministic and total: a table lookup, never a model and never a
    heuristic over the content. `None` for `OTHER` and for an unknown or absent
    type -- we do not know what the document is, so there is no mode we could
    defend, and Feature 26 B9 routes that to the clarifying turn rather than
    picking one.
    """
    if not doc_type:
        return None
    return _MODE_BY_DOC_TYPE.get(str(doc_type).strip().upper())


def _tokens(value: Optional[str]) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (value or "").lower()) if t]


def _token_overlap(a: Optional[str], b: Optional[str]) -> float:
    """Jaccard overlap of two descriptions. 0.0 when either side is empty --
    never 1.0, which is what comparing two empty sets would otherwise give and
    would match every unlabelled line to every other."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _norm_key(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _line_of(row: Any) -> Dict[str, Any]:
    """One line, from either a schema object or a plain mapping."""
    get = row.get if isinstance(row, dict) else (lambda k, d=None: getattr(row, k, d))
    return {
        "description": get("description"),
        "quantity": get("quantity"),
        "unit_price": get("unit_price"),
        "amount": get("amount"),
        "hsn_sac_code": get("hsn_sac_code"),
        "uom": get("uom"),
        "line_number": get("line_number"),
        # Gap 454: which page the row was read from, carried so an answer can say
        # where a figure came from. Null whenever the extractor did not know --
        # never defaulted to 1, because a wrong page reference sends a reader to
        # the wrong place to check a number, which is worse than no reference.
        "page_number": get("page_number"),
    }


def _match_lines(
    reference_lines: List[Dict[str, Any]], invoice_lines: List[Dict[str, Any]]
) -> Tuple[List[Tuple[int, int, str]], List[int], List[int]]:
    """Deterministic, tiered line matching. Returns (pairs, unmatched_ref, unmatched_inv).

    THREE TIERS, STRICTLY IN ORDER, and nothing below L3 is ever accepted:

      L1  normalised `hsn_sac_code` + normalised `uom`, both present on both
          sides and equal. A tax code is an identifier the two documents were
          meant to share -- not a heuristic.
      L2  normalised description, exact after case/whitespace/punctuation
          folding.
      L3  description token overlap >= L3_TOKEN_OVERLAP_THRESHOLD **AND**
          corroboration from quantity (equal) or unit price (within
          AMOUNT_TOLERANCE). The corroboration is not optional: token overlap
          alone matches "Steel Bolt M8" to "Steel Bolt M10", which is a
          different part.

    Anything else is UNMATCHED and is reported as such. That is the whole design
    point and it is what `_compare_one()` refused to guess at: an unmatched line
    is a real, reportable outcome exactly as Tier 0 is in
    `find_candidate_invoices()`, never a line fuzzily attached to the nearest
    thing found.

    Each line is consumed at most once. Matching is greedy within a tier, and
    tiers run to exhaustion in order, so a strong L1 match can never be stolen by
    a weaker L3 one.
    """
    pairs: List[Tuple[int, int, str]] = []
    used_ref: set = set()
    used_inv: set = set()

    # L1 -- shared tax code + unit.
    for i, ref in enumerate(reference_lines):
        if i in used_ref:
            continue
        rk, ru = _norm_key(ref.get("hsn_sac_code")), _norm_key(ref.get("uom"))
        if not rk or not ru:
            continue
        for j, inv in enumerate(invoice_lines):
            if j in used_inv:
                continue
            if rk == _norm_key(inv.get("hsn_sac_code")) and ru == _norm_key(inv.get("uom")):
                pairs.append((i, j, "L1"))
                used_ref.add(i)
                used_inv.add(j)
                break

    # L2 -- exact folded description.
    for i, ref in enumerate(reference_lines):
        if i in used_ref:
            continue
        rd = _norm_key(ref.get("description"))
        if not rd:
            continue
        for j, inv in enumerate(invoice_lines):
            if j in used_inv:
                continue
            if rd == _norm_key(inv.get("description")):
                pairs.append((i, j, "L2"))
                used_ref.add(i)
                used_inv.add(j)
                break

    # L3 -- token overlap WITH corroboration.
    for i, ref in enumerate(reference_lines):
        if i in used_ref:
            continue
        best: Optional[Tuple[float, int]] = None
        for j, inv in enumerate(invoice_lines):
            if j in used_inv:
                continue
            overlap = _token_overlap(ref.get("description"), inv.get("description"))
            if overlap < L3_TOKEN_OVERLAP_THRESHOLD:
                continue
            rq, iq = _to_decimal(ref.get("quantity")), _to_decimal(inv.get("quantity"))
            rp, ip = _to_decimal(ref.get("unit_price")), _to_decimal(inv.get("unit_price"))
            corroborated = (
                (rq is not None and iq is not None and rq == iq)
                or (rp is not None and ip is not None and abs(rp - ip) <= AMOUNT_TOLERANCE)
            )
            if corroborated and (best is None or overlap > best[0]):
                best = (overlap, j)
        if best is not None:
            pairs.append((i, best[1], "L3"))
            used_ref.add(i)
            used_inv.add(best[1])

    unmatched_ref = [i for i in range(len(reference_lines)) if i not in used_ref]
    unmatched_inv = [j for j in range(len(invoice_lines)) if j not in used_inv]
    return pairs, unmatched_ref, unmatched_inv


def _within_tolerance(reference, invoice, percent: Optional[float]) -> bool:
    """Gap 447: is this delta inside the tenant's band?

    False whenever the question cannot be answered -- no band, a missing side, or
    a zero reference (any delta from zero is infinite in percentage terms). The
    fail-closed direction is deliberate: an unanswerable tolerance question must
    report the variance, never swallow it.
    """
    if not percent or percent <= 0:
        return False
    ref, inv = _to_decimal(reference), _to_decimal(invoice)
    if ref is None or inv is None or ref == 0:
        return False
    return abs((inv - ref) / ref) * 100 <= Decimal(str(percent))


def _line_row(
    ref: Dict[str, Any],
    inv: Dict[str, Any],
    tier: str,
    mode: str,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One rendered comparison row. Every figure is Decimal-derived and every
    delta is None when either side is missing -- absent is never zero (Gap 283)."""
    def _delta(a, b):
        da, db = _to_decimal(a), _to_decimal(b)
        if da is None or db is None:
            return None
        return str(db - da)

    row: Dict[str, Any] = {
        "match_tier": tier,
        # Gap 454: both sides' pages, separately. They are different documents,
        # so one "page" field would have to pick a side and silently lose the
        # other -- and "page 2 of the purchase order" and "page 2 of the invoice"
        # are not the same claim.
        "reference_page": ref.get("page_number"),
        "invoice_page": inv.get("page_number"),
        "description": ref.get("description") or inv.get("description"),
        "hsn_sac_code": ref.get("hsn_sac_code") or inv.get("hsn_sac_code"),
        "uom": ref.get("uom") or inv.get("uom"),
        "reference_quantity": ref.get("quantity"),
        "invoice_quantity": inv.get("quantity"),
        "quantity_delta": _delta(ref.get("quantity"), inv.get("quantity")),
        "reference_unit_price": ref.get("unit_price"),
        "invoice_unit_price": inv.get("unit_price"),
        "price_delta": _delta(ref.get("unit_price"), inv.get("unit_price")),
        "reference_amount": ref.get("amount"),
        "invoice_amount": inv.get("amount"),
        "amount_delta": _delta(ref.get("amount"), inv.get("amount")),
    }

    # A UoM mismatch is its OWN outcome, never a quantity delta: 40 cartons
    # against 40 pieces is not a quantity agreement, and reporting it as one
    # would be a confident wrong answer.
    ru, iu = _norm_key(ref.get("uom")), _norm_key(inv.get("uom"))
    if ru and iu and ru != iu:
        row["status"] = "uom_mismatch"
        return row

    quantity_differs = row["quantity_delta"] not in (None, "0")
    price_differs = row["price_delta"] not in (None, "0")

    # Gap 447: a delta inside the tenant's band is still REPORTED -- the figure
    # stays on the row -- but it is not a discrepancy, and saying so is the whole
    # point of having a policy. Silently dropping the delta would be worse than
    # having no tolerance at all.
    policy = policy or {}
    if quantity_differs and _within_tolerance(
        ref.get("quantity"), inv.get("quantity"), policy.get("quantity_tolerance_percent")
    ):
        quantity_differs = False
        row["quantity_within_tolerance"] = True
    if price_differs and _within_tolerance(
        ref.get("unit_price"), inv.get("unit_price"), policy.get("price_tolerance_percent")
    ):
        price_differs = False
        row["price_within_tolerance"] = True
    if mode == QUANTITY_MODE:
        # Absent price is NOT a discrepancy here -- Feature 27 E4's quantity
        # rubric, and the founder's original symptom.
        row["status"] = "quantity_delta" if quantity_differs else "match"
    elif mode == MONEY_MODE:
        row["status"] = "price_delta" if price_differs else "match"
    else:
        if quantity_differs and price_differs:
            row["status"] = "quantity_delta"
        elif quantity_differs:
            row["status"] = "quantity_delta"
        elif price_differs:
            row["status"] = "price_delta"
        else:
            row["status"] = "match"
    return row


def compare_documents(
    doc_a: Dict[str, Any],
    doc_b: Dict[str, Any],
    mode: str = BOTH_MODE,
    *,
    correction_method: Optional[str] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic line-item comparison of two extracted documents (B3/B7).

    Source-agnostic BY DESIGN: it takes two extracted-document mappings, and an
    `Invoice` row is adapted into that shape at the call site. v1 wires exactly
    one caller -- attachment vs confirmed invoices -- and attachment-vs-attachment
    stays out of scope (B4, deferred as BE Gap 387). Writing it source-agnostic is
    what makes that a wiring change later rather than a rewrite.

    `correction_method` (Feature 27 A6) changes the ARITHMETIC, not the mode. When
    it is None the comparison runs as DELTA and SAYS SO in
    `assumptions[]` -- the founder's ruling. An unstated assumption about which of
    three arithmetics produced a figure is exactly the silent wrongness this
    feature exists to remove, so it is stated rather than hidden.
    """
    if mode not in COMPARISON_MODES:
        raise ValueError(f"unknown comparison mode {mode!r}; expected one of {COMPARISON_MODES}")

    assumptions: List[str] = []
    effective_correction = correction_method
    if effective_correction is None:
        effective_correction = "DELTA"
        assumptions.append(
            "The document does not state how it corrects the original, so this "
            "comparison treats it as an adjustment (DELTA) rather than a replacement."
        )

    ref_lines = [_line_of(r) for r in (doc_a.get("items") or [])]
    inv_lines = [_line_of(r) for r in (doc_b.get("items") or [])]
    pairs, unmatched_ref, unmatched_inv = _match_lines(ref_lines, inv_lines)

    line_items = [_line_row(ref_lines[i], inv_lines[j], tier, mode, policy) for i, j, tier in pairs]
    if policy:
        # Stated in the output, not merely applied: a reader must be able to see
        # WHICH band produced "no discrepancy" (Feature 27 A6's own rule about
        # unstated assumptions, applied to tolerances).
        assumptions.append(
            "Tolerances applied: quantity "
            f"{policy.get('quantity_tolerance_percent', 0)}%, price "
            f"{policy.get('price_tolerance_percent', 0)}%."
        )

    return {
        "mode": mode,
        "policy": policy or None,
        "correction_method": effective_correction,
        "assumptions": assumptions,
        "line_items": line_items,
        "unmatched": {
            # Reported, never fuzzily attached. An unmatched line is often THE
            # answer -- a billed line that was never ordered.
            "reference_lines": [ref_lines[i] for i in unmatched_ref],
            "invoice_lines": [inv_lines[j] for j in unmatched_inv],
        },
        "matched_count": len(line_items),
        "unmatched_count": len(unmatched_ref) + len(unmatched_inv),
    }


# --- B8: list reconciliation, the ADVISORY family's comparison mode ----------


def reconcile_referenced_documents(
    *,
    tenant_id: Any,
    referenced_documents: List[Dict[str, Any]],
    deductions: Optional[List[Dict[str, Any]]] = None,
    db_session: Session,
    party_name: Optional[str] = None,
) -> Dict[str, Any]:
    """B8. A statement or remittance advice is a LIST OF POINTERS at other
    documents, not a document with comparable line items -- so it gets its own
    mode rather than having the L1-L3 matcher run over something that is not a
    line (research §5 trap 6).

    Five outcomes per reference, and the last one is why this mode exists at all:

      found_matching        an invoice exists and its total and status agree
      amount_mismatch       found, amounts differ -- the delta is reported
      status_mismatch       found, but they call it paid and we do not (or vice versa)
      not_found             they reference a number we hold no invoice for
      unreferenced_invoice  THE REVERSE DIRECTION: an open invoice of ours that
                            their statement does not list at all

    Walking only the document's own list would answer "is their statement
    right?"; adding the reverse direction answers "which of MY invoices are
    missing from it?", which is the question a finance team actually asks.

    Deterministic `Decimal` throughout, joined on `normalize_doc_number()` --
    the same normalisation Tier 1 uses, so a statement and a PO agree about what
    counts as the same number. No LLM.
    """
    references = referenced_documents or []
    normalized_refs = {}
    results: List[Dict[str, Any]] = []

    rows = db_session.exec(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.deleted_at.is_(None),
        )
    ).all()
    by_number = {
        normalize_doc_number(row.invoice_number): row
        for row in rows
        if row.invoice_number
    }

    for ref in references:
        number = ref.get("doc_number")
        key = normalize_doc_number(number)
        normalized_refs[key] = True
        invoice = by_number.get(key) if key else None
        if invoice is None:
            results.append({
                "doc_number": number,
                "invoice_id": None,
                "outcome": "not_found",
                "delta": None,
            })
            continue

        stated = _to_decimal(ref.get("amount"))
        actual = _to_decimal(invoice.grand_total)
        hint = (ref.get("status_hint") or "").strip().upper() or None
        outcome = "found_matching"
        delta = None

        if stated is not None and actual is not None and abs(actual - stated) > AMOUNT_TOLERANCE:
            outcome = "amount_mismatch"
            delta = str(actual - stated)
        elif hint == "PAID" and (invoice.status or "").upper() != "PAID":
            # Their claim vs our record. Reported, never reconciled away -- the
            # whole value of a statement is seeing where the two disagree.
            outcome = "status_mismatch"
        elif hint in ("OPEN", "PARTIALLY_PAID") and (invoice.status or "").upper() == "PAID":
            outcome = "status_mismatch"

        results.append({
            "doc_number": number,
            "invoice_id": str(invoice.id),
            "outcome": outcome,
            "delta": delta,
            "stated_amount": ref.get("amount"),
            "invoice_amount": invoice.grand_total,
            "stated_status": hint,
            "invoice_status": invoice.status,
        })

    # The reverse direction.
    unreferenced = []
    for row in rows:
        if not row.invoice_number:
            continue
        if normalize_doc_number(row.invoice_number) in normalized_refs:
            continue
        if party_name and _normalize_party(party_name) not in _normalize_party(
            row.vendor_name or row.customer_name or ""
        ):
            continue
        if (row.status or "").upper() == "PAID":
            continue
        unreferenced.append({
            "invoice_id": str(row.id),
            "invoice_number": row.invoice_number,
            "grand_total": row.grand_total,
        })

    return {
        "mode": LIST_RECONCILE_MODE,
        "party_name": party_name,
        "references": results,
        # Reported PER KIND and never netted: one unexplained 8,000 gap is a
        # support ticket, while "TDS 6,000 + chargeback 2,000" is an answer.
        "deductions": list(deductions or []),
        "unreferenced_invoices": unreferenced,
    }


# ---------------------------------------------------------------------------
# Gap 447 — the tenant's tolerances, read once per comparison
# ---------------------------------------------------------------------------
def get_match_policy(tenant_id: Any, db_session: Session) -> Dict[str, Any]:
    """One tenant's tolerance band, or the zero band.

    The zero band is not a placeholder for "unconfigured" -- it is the product's
    behaviour before this table existed, and it is the correct default: a
    tolerance is permission to ignore a real difference, and nobody should be
    granted that by omission.
    """
    from models import MatchPolicy

    zero = {
        "quantity_tolerance_percent": 0.0,
        "price_tolerance_percent": 0.0,
        "date_tolerance_days": 0,
    }
    try:
        row = db_session.exec(
            select(MatchPolicy).where(MatchPolicy.tenant_id == tenant_id)
        ).first()
    except Exception as e:
        logger.warning("Match policy lookup failed for tenant %s: %s", tenant_id, e)
        return zero
    if row is None:
        return zero
    return {
        "quantity_tolerance_percent": row.quantity_tolerance_percent,
        "price_tolerance_percent": row.price_tolerance_percent,
        "date_tolerance_days": row.date_tolerance_days,
    }


def record_comparison(
    *,
    db_session: Session,
    tenant_id: Any,
    kind: str,
    payload: Dict[str, Any],
    invoice_id: Any = None,
    attachment_id: Any = None,
    session_id: Any = None,
    doc_type: Optional[str] = None,
    mode: Optional[str] = None,
    outcome: Optional[str] = None,
):
    """Gap 448: keep the comparison as a record, not only as a sentence.

    Best-effort by construction. The user has already been given a correct
    answer by the time this runs; failing the turn because an audit row could not
    be written would trade the thing they asked for against the thing we wanted.
    """
    from models import DocumentComparison

    try:
        row = DocumentComparison(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            attachment_id=attachment_id,
            session_id=session_id,
            kind=kind,
            doc_type=doc_type,
            mode=mode,
            outcome=outcome,
            payload=payload,
        )
        db_session.add(row)
        db_session.commit()
        return row
    except Exception as e:
        logger.error("Recording comparison failed (tenant %s, kind %s): %s", tenant_id, kind, e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return None
