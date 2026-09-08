"""Feature 30 tasks 30.1 / 30.2 / 30.12 / 30.17 — the chat-attachment
intelligence bubble.

WHAT THIS IS
------------
A user attaches a non-invoice financial document in the chat composer. Before
they ask anything, the system speaks first: a deterministic block of findings
about that document, posted as an assistant turn.

    verdict line   one sentence  (template at the sync stage, model-written at
                                  the async stage, gated on every figure)
    findings       max 3 shown, each with a currency impact, a confidence and
                   the evidence it was computed from
    checks not run the cards that were skipped, and why (30.12)
    actions        hold / dispute / paid / note / discuss / dismiss (R4)

THE RULE THAT SHAPES EVERY LINE OF THIS FILE
--------------------------------------------
Hard rule 3 (CONVENTIONS.md) and spec §8.9: **every figure the user sees is
computed here or in a view. The model writes prose and a ranking, never a
number.** So each card is a plain function over the attachment row, its
`extracted_json` and the linked invoice rows; the narration step is given the
finished JSON and is told the figures are already decided; and what it writes
back is checked against those figures by `agents/query_agent._answer_contract_gate()`
before it is allowed to replace the template text.

TWO STAGES (§8.6, ruling R3)
----------------------------
`build_insight_block(stage="sync")` runs the cards that need nothing but this
document and the invoices already linked to it — target under three seconds, no
model, no queue. `stage="async"` re-runs those and adds the ones that need the
heavier history queries. The async block REPLACES the sync block on the same
chat message and bumps `insights_version`, so there is one bubble that improves
rather than two bubbles that disagree.

FAILURE
-------
A card never takes the bubble down. Missing inputs -> `skipped` with a reason
the user can read ("no PO on file"). An exception -> `blocked`, logged with the
attachment id, and the remaining cards still run. The whole hook is wrapped
again at the call site, because an insight is an extra, and an extra that can
fail an upload is a regression in Feature 26.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional, Sequence
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

#: The eight document types ruling R2 named, in the vocabulary the Feature 27
#: classifier actually emits (`services/document_type_classifier.py`).
#:
#: Two folds, both from R2: ORDER_CONFIRMATION is a PO for our purposes, and GRN
#: is a challan. One substitution: R2 says "bank statement"; the classifier's
#: type is STATEMENT_OF_ACCOUNT and **the taxonomy is frozen** (`active-work.md`,
#: "no taxonomy/schema amendment work ... until F27's existing ledger closes"),
#: so this feature uses the existing value rather than adding a fourteenth type.
#: The ledger table (30.0c) is keyed on the attachment, not on the type name, so
#: nothing downstream depends on the spelling.
#:
#: INVOICE and OTHER are deliberately absent. An invoice attached in chat is
#: Feature 26's existing comparison path, and OTHER means we do not know what
#: the document is — there is no card we could defend running on it.
INSIGHT_DOC_TYPES: frozenset = frozenset(
    {
        "PURCHASE_ORDER",
        "ORDER_CONFIRMATION",
        "QUOTATION",
        "DELIVERY_NOTE",
        "GRN",
        "CREDIT_NOTE",
        "DEBIT_NOTE",
        "STATEMENT_OF_ACCOUNT",
        "CONTRACT",
        "REMITTANCE_ADVICE",
    }
)

#: What the bubble CALLS each type. Internal names never reach the user (§8.2):
#: "challan", not "GRN"; "statement", not "STATEMENT_OF_ACCOUNT".
DOC_TYPE_LABELS: dict = {
    "PURCHASE_ORDER": "purchase order",
    "ORDER_CONFIRMATION": "order confirmation",
    "QUOTATION": "quotation",
    "DELIVERY_NOTE": "delivery note",
    "GRN": "delivery note",
    "CREDIT_NOTE": "credit note",
    "DEBIT_NOTE": "debit note",
    "STATEMENT_OF_ACCOUNT": "bank statement",
    "CONTRACT": "contract",
    "REMITTANCE_ADVICE": "remittance advice",
}


def is_insight_doc_type(doc_type: Optional[str]) -> bool:
    """The trigger gate. INVOICE and OTHER never qualify."""
    if not doc_type:
        return False
    return str(doc_type).strip().upper() in INSIGHT_DOC_TYPES


def insights_enabled() -> bool:
    """Read at call time so a test's monkeypatch is seen — the same rule
    `agents/query_agent._answer_gate_enabled()` follows."""
    try:
        from config import get_settings

        return bool(getattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", False))
    except Exception:  # pragma: no cover - defensive
        return False


# ---------------------------------------------------------------------------
# The card and the block
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_BLOCKED = "blocked"


@dataclass
class InsightCard:
    """One card's result.

    `figures` is the contract with the narration step: it is the complete set of
    numbers the model is allowed to repeat. Anything not in here, across all
    cards, fails the answer-contract gate.

    `findings` are the user-facing items — each one becomes an `insight` row and
    a line in the bubble. A card can be `ok` with no findings, and that is a
    real, useful answer ("we checked, nothing is wrong"), not an empty result.
    """

    card: str
    status: str = STATUS_SKIPPED
    title: str = ""
    figures: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "card": self.card,
            "status": self.status,
            "title": self.title,
            "figures": self.figures,
            "findings": self.findings,
            "evidence": self.evidence,
            "reason": self.reason,
        }


def finding(
    key: str,
    title: str,
    *,
    card: str,
    impact_amount: float | None = None,
    currency: str | None = None,
    confidence: str = "med",
    confidence_reason: str = "",
    evidence: dict | None = None,
) -> dict:
    """One finding, in the one shape the bubble, the `insight` row and the
    dashboard all read. A helper rather than a literal at nine call sites,
    because a finding that is missing `finding_key` is a finding that opens a
    duplicate row on every async update."""
    return {
        "finding_key": key,
        "card": card,
        "title": title,
        "impact_amount": impact_amount,
        "currency": currency,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "evidence": evidence or {},
    }


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _dec(value: Any) -> Optional[Decimal]:
    """Money as `Decimal`, or None. Never float arithmetic on currency."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _f(value: Optional[Decimal]) -> Optional[float]:
    """`Decimal` -> the float the JSON block carries. Rounded to 2dp so the
    figure the model is shown is the figure the user is shown."""
    if value is None:
        return None
    return float(round(value, 2))


def jsonable(value: Any) -> Any:
    """Everything in a block, in types JSON and JSONB can both hold.

    BE Gap 494. The block is written to THREE places that all serialise it --
    `ChatMessage.attachment_payload` (JSONB), `ChatAttachment.insights` (JSONB)
    and `Insight.evidence` (JSONB) -- and pushed over SSE as a fourth. A card
    that reads from a semantic view hands back `UUID`, `date` and `Decimal`
    objects straight from psycopg2, and the INSERT then fails with "Object of
    type UUID is not JSON serializable" -- taking the whole bubble down at the
    commit, long after the card that produced it returned successfully.

    Applied once, centrally, in `build_insight_block()` rather than in each card:
    a per-card rule is one card away from being forgotten, and the failure it
    produces is a transaction-level error with no obvious owner.

    `Decimal` becomes `float` only at this boundary. Every computation upstream
    stays in `Decimal`; this is the rendering step, not the arithmetic.
    """
    from decimal import Decimal as _D
    from uuid import UUID as _UUID

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, _D):
        return float(value)
    if isinstance(value, (_UUID,)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return str(value)


def _linked_invoices(row: Any, db_session: Any) -> list:
    """The invoices this attachment is compared against.

    CONFIRMED ids first and alone when there are any: Feature 26 decision D4
    says a proposal may not satisfy the comparison gate, and this feature does
    not get to relax that. Candidates are used only when nothing is confirmed,
    and every card that uses them says so in its confidence reason — that is the
    honest position ("we think this is the invoice") rather than either
    pretending certainty or refusing to say anything.
    """
    from models import Invoice

    ids = [str(i) for i in (row.confirmed_invoice_ids or [])]
    confirmed = bool(ids)
    if not ids:
        ids = [str(i) for i in (row.candidate_invoice_ids or [])]
    if not ids:
        return []

    try:
        from sqlmodel import select

        uuids = []
        for i in ids:
            try:
                uuids.append(UUID(str(i)))
            except (ValueError, AttributeError, TypeError):
                continue
        if not uuids:
            return []
        rows = db_session.exec(
            select(Invoice).where(
                Invoice.tenant_id == row.tenant_id, Invoice.id.in_(uuids)
            )
        ).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Insight linked-invoice lookup failed for %s: %s", row.id, exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []

    for inv in rows:
        # Carried on the object rather than returned alongside it so every card
        # that reads an invoice also sees how sure we are that it is the right
        # one, without a second parameter to forget.
        setattr(inv, "_link_confirmed", confirmed)
    return rows


def _confidence_for_link(invoices: Sequence[Any], row: Any) -> tuple[str, str]:
    """How sure we are that these invoices belong to this document.

    Tier 1 is an exact document-number match, which is as certain as this system
    gets; tier 2 is party + date window; tier 3 is content similarity, and a
    figure computed from a tier-3 link is explicitly low confidence.
    """
    if not invoices:
        return "low", "no invoice is linked to this document yet"
    if getattr(invoices[0], "_link_confirmed", False):
        return "high", "you confirmed which invoices this document refers to"
    tier = getattr(row, "match_tier", None)
    if tier == 1:
        return "high", "the document number matches exactly"
    if tier == 2:
        return "med", "matched on party and date, not confirmed by you yet"
    return "low", "matched on content similarity only, not confirmed by you yet"


def _label(doc_type: Optional[str]) -> str:
    return DOC_TYPE_LABELS.get(str(doc_type or "").strip().upper(), "document")


# ---------------------------------------------------------------------------
# The cards (30.1)
# ---------------------------------------------------------------------------


def card_what_this_is(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """"Here is what I read, and what it connects to."

    Never has findings and is never skipped: it is the card that makes the rest
    of the bubble checkable, because a user who disagrees with a figure needs to
    see which document and which invoices produced it.
    """
    data = row.extracted_json or {}
    invoices = ctx["invoices"]
    total = _dec(row.grand_total)
    figures = {}
    if total is not None:
        figures["document_total"] = _f(total)

    return InsightCard(
        card="what_this_is",
        status=STATUS_OK,
        title=(
            f"{_label(row.doc_type).capitalize()} "
            f"{row.doc_number or '(no number printed)'}"
            + (f" from {row.party_name}" if row.party_name else "")
        ),
        figures=figures,
        evidence={
            "doc_type": row.doc_type,
            "doc_number": row.doc_number,
            "party_name": row.party_name,
            "doc_date": row.doc_date.isoformat() if row.doc_date else None,
            "currency": row.currency,
            "line_count": len(data.get("items") or []),
            "linked_invoice_numbers": [i.invoice_number for i in invoices],
            "link_confirmed": bool(invoices) and getattr(invoices[0], "_link_confirmed", False),
        },
    )


def card_agreed_vs_billed(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """PO / quotation / contract vs the invoices actually received (§8.5).

    The arithmetic is `services/document_comparison.compare_reference_to_invoices()`
    verbatim — the same function Feature 26's comparison turn uses, so the bubble
    and the chat answer cannot report different overbilling for the same pair.
    """
    invoices = ctx["invoices"]
    if not invoices:
        return InsightCard(
            card="agreed_vs_billed",
            status=STATUS_SKIPPED,
            reason=f"no invoice from {row.party_name or 'this supplier'} is linked to this document yet",
        )

    from services.document_comparison import compare_reference_to_invoices

    comparison = compare_reference_to_invoices(row.extracted_json or {}, invoices)
    confidence, why = _confidence_for_link(invoices, row)

    findings: list = []
    figures: dict = {}
    for c in comparison.get("comparisons", []):
        number = c.get("invoice_number") or c.get("invoice_id")
        if c.get("outcome") == "currency_mismatch":
            findings.append(
                finding(
                    f"agreed_vs_billed:currency:{number}",
                    f"{number} is in a different currency from this "
                    f"{_label(row.doc_type)}, so nothing was compared",
                    card="agreed_vs_billed",
                    confidence="high",
                    confidence_reason="two different currencies, and this system holds no exchange rate",
                    evidence={"invoice_number": number, "blocked_reason": c.get("blocked_reason")},
                )
            )
            continue
        for f_ in c.get("fields", []):
            if f_.get("field") != "grand_total" or f_.get("status") != "invoice_higher":
                continue
            delta = _dec(f_.get("delta"))
            if delta is None:
                continue
            figures[f"overbilled_{number}"] = _f(delta)
            figures[f"agreed_{number}"] = _f(_dec(f_.get("reference_value")))
            figures[f"billed_{number}"] = _f(_dec(f_.get("invoice_value")))
            findings.append(
                finding(
                    f"agreed_vs_billed:{number}",
                    f"{number} bills {_f(delta)} more than this "
                    f"{_label(row.doc_type)} agreed",
                    card="agreed_vs_billed",
                    impact_amount=_f(delta),
                    currency=row.currency,
                    confidence=confidence,
                    confidence_reason=why,
                    evidence={
                        "invoice_number": number,
                        "agreed": f_.get("reference_value"),
                        "billed": f_.get("invoice_value"),
                        "difference": f_.get("delta"),
                    },
                )
            )

    return InsightCard(
        card="agreed_vs_billed",
        status=STATUS_OK,
        title=f"Checked {comparison.get('compared_count', 0)} invoice(s) against this {_label(row.doc_type)}",
        figures=figures,
        findings=findings,
        evidence={"comparison": comparison},
    )


#: How a payment term is printed: "30 days", "Net 45", "payable within 15 days".
_TERM_DAYS_PATTERNS = (
    r"net\s*(\d{1,3})",
    r"within\s*(\d{1,3})\s*days",
    r"(\d{1,3})\s*days",
)


def _payment_days(text: Optional[str]) -> Optional[int]:
    """The number of days a payment-terms string states, or None.

    Regex over the printed text, not a model: "Net 30" is a format, not a
    judgement, and a model asked to read one will occasionally return 45.
    """
    import re

    if not text:
        return None
    lowered = str(text).lower()
    for pattern in _TERM_DAYS_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def card_terms_check(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """What the contract/PO says about payment, vs what the invoices do (§8.5).

    Only the payment window is checked here, and deliberately so: it is the one
    term that is printed on both documents in a comparable form. Discount and
    tax-rate deviation need the rule cards (30.11) and are named in "checks not
    run" until those land, rather than being guessed at from prose.
    """
    data = row.extracted_json or {}
    agreed_days = _payment_days(data.get("payment_terms"))
    if agreed_days is None:
        return InsightCard(
            card="terms_check",
            status=STATUS_SKIPPED,
            reason="this document does not print a payment window we can read",
        )

    invoices = ctx["invoices"]
    if not invoices:
        return InsightCard(
            card="terms_check",
            status=STATUS_SKIPPED,
            reason="no invoice is linked yet, so there is nothing to check the terms against",
        )

    confidence, why = _confidence_for_link(invoices, row)
    figures = {"agreed_payment_days": float(agreed_days)}
    findings = []
    checked = 0
    for inv in invoices:
        if not (inv.invoice_date and inv.due_date):
            continue
        checked += 1
        actual = (inv.due_date - inv.invoice_date).days
        figures[f"payment_days_{inv.invoice_number}"] = float(actual)
        if actual == agreed_days:
            continue
        findings.append(
            finding(
                f"terms_check:{inv.invoice_number}",
                f"{inv.invoice_number} is due in {actual} days; this "
                f"{_label(row.doc_type)} says {agreed_days}",
                card="terms_check",
                confidence=confidence,
                confidence_reason=why,
                evidence={
                    "invoice_number": inv.invoice_number,
                    "agreed_days": agreed_days,
                    "invoice_days": actual,
                    "payment_terms_text": data.get("payment_terms"),
                },
            )
        )

    if not checked:
        return InsightCard(
            card="terms_check",
            status=STATUS_SKIPPED,
            reason="the linked invoices have no invoice date and due date to measure",
        )
    return InsightCard(
        card="terms_check",
        status=STATUS_OK,
        title=f"Payment window checked on {checked} invoice(s)",
        figures=figures,
        findings=findings,
    )


def card_net_position(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """Credit / debit note / remittance: what is actually payable now.

    `compute_amount_owed()` verbatim (Gap 475's signed arithmetic): the sign
    comes from the DOCUMENT TYPE, never from how the document printed its own
    total, which is the bug that made a credit note add instead of subtract.
    """
    invoices = ctx["invoices"]
    if not invoices:
        return InsightCard(
            card="net_position",
            status=STATUS_SKIPPED,
            reason="no invoice is linked yet, so there is nothing for this note to adjust",
        )

    from services.document_comparison import compute_amount_owed

    terms = [
        {
            "doc_type": row.doc_type,
            "doc_number": row.doc_number,
            "amount": row.grand_total,
            "currency": row.currency,
            "source": "attachment",
        }
    ]
    for inv in invoices:
        terms.append(
            {
                "doc_type": "INVOICE",
                "doc_number": inv.invoice_number,
                "amount": inv.grand_total,
                "currency": inv.currency,
                "source": "ledger",
            }
        )

    owed = compute_amount_owed(terms)
    if not owed:
        return InsightCard(
            card="net_position",
            status=STATUS_SKIPPED,
            reason="there is no adjustment to apply, so the invoice total stands as it is",
        )

    net = _dec(owed.get("net"))
    confidence, why = _confidence_for_link(invoices, row)
    figures = {}
    findings = []
    if net is not None:
        figures["net_payable"] = _f(net)
        findings.append(
            finding(
                f"net_position:{row.doc_number or row.id}",
                f"After this {_label(row.doc_type)}, {_f(net)} is payable",
                card="net_position",
                impact_amount=_f(_dec(row.grand_total)),
                currency=owed.get("currency") or row.currency,
                confidence=confidence if owed.get("complete") else "low",
                confidence_reason=(
                    why
                    if owed.get("complete")
                    else "one of the documents has a total we could not read, so this net is incomplete"
                ),
                evidence={"terms": owed.get("terms"), "ignored": owed.get("ignored_terms")},
            )
        )
    return InsightCard(
        card="net_position",
        status=STATUS_OK,
        title="Net position after this note",
        figures=figures,
        findings=findings,
        evidence={"amount_owed": owed},
    )


def _norm_desc(text: Any) -> str:
    import re

    return " ".join(re.split(r"[^a-z0-9]+", str(text or "").lower())).strip()


def card_delivery_vs_order(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """Challan / GRN: quantity delivered vs quantity billed (§8.5).

    QUANTITY only, never price. A delivery note omits prices by design, and
    comparing a blank price to a real one manufactures exactly the false
    discrepancy `resolve_comparison_mode()`'s QUANTITY_MODE exists to avoid.
    """
    data = row.extracted_json or {}
    delivered = [i for i in (data.get("items") or []) if _dec(i.get("quantity")) is not None]
    if not delivered:
        return InsightCard(
            card="delivery_vs_order",
            status=STATUS_SKIPPED,
            reason="no line quantities could be read from this delivery note",
        )
    invoices = ctx["invoices"]
    if not invoices:
        return InsightCard(
            card="delivery_vs_order",
            status=STATUS_SKIPPED,
            reason="no invoice is linked yet, so there is nothing to compare the delivery against",
        )

    confidence, why = _confidence_for_link(invoices, row)
    findings = []
    figures = {}
    for inv in invoices:
        billed = {}
        for item in inv.items or []:
            if not isinstance(item, dict):
                continue
            key = _norm_desc(item.get("description"))
            qty = _dec(item.get("quantity"))
            if key and qty is not None:
                billed[key] = billed.get(key, Decimal("0")) + qty

        for item in delivered:
            key = _norm_desc(item.get("description"))
            got = _dec(item.get("quantity"))
            if not key or got is None or key not in billed:
                continue
            diff = billed[key] - got
            if diff == 0:
                continue
            figures[f"delivered_{key[:32]}"] = _f(got)
            figures[f"billed_qty_{key[:32]}"] = _f(billed[key])
            short = diff > 0
            findings.append(
                finding(
                    f"delivery_vs_order:{inv.invoice_number}:{key[:64]}",
                    (
                        f"{inv.invoice_number} bills {_f(billed[key])} of "
                        f"'{item.get('description')}' but {_f(got)} was delivered"
                    ),
                    card="delivery_vs_order",
                    impact_amount=_f(abs(diff)),
                    confidence=confidence,
                    confidence_reason=why,
                    evidence={
                        "invoice_number": inv.invoice_number,
                        "description": item.get("description"),
                        "delivered_quantity": str(got),
                        "billed_quantity": str(billed[key]),
                        "direction": "short_delivery" if short else "excess_delivery",
                    },
                )
            )

    return InsightCard(
        card="delivery_vs_order",
        status=STATUS_OK,
        title=f"{len(delivered)} delivered line(s) checked against the linked invoice(s)",
        figures=figures,
        findings=findings,
    )


def _tenant_invoices(row: Any, db_session: Any, limit: int = 500) -> list:
    """The tenant's live invoices, for the cards that look beyond this document.

    Bounded and tenant-scoped. A bank statement is matched against the LEDGER,
    not against the handful of invoices linked to the attachment -- that is the
    difference between "does this PO agree with its invoice" and "which of these
    40 debits have we recorded".
    """
    from sqlmodel import select

    from models import Invoice

    try:
        return db_session.exec(
            select(Invoice)
            .where(Invoice.tenant_id == row.tenant_id, Invoice.deleted_at == None)  # noqa: E711
            .order_by(Invoice.invoice_date.desc())
            .limit(limit)
        ).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Insight ledger lookup failed for %s: %s", row.id, exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []


def card_bank_reconcile(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.5 sync card — match the statement's rows to invoices (ruling R5).

    Every figure comes from `services/bank_matching.match_statement_lines()`,
    which is `Decimal` arithmetic over the landed ledger (30.0c) with the R5
    tolerances read through `threshold()`. The card reports what matched, what
    did not, and -- the finding an SMB owner actually wants -- which debits look
    like a bill paid twice.

    Gap 492: matching writes `bank_statement_line.match_status` and nothing else.
    No invoice is marked paid by a statement.
    """
    from services.bank_ledger import closing_balance, statement_lines_for
    from services.bank_matching import apply_matches, match_statement_lines

    lines = statement_lines_for(row.id, db_session)
    if not lines:
        return InsightCard(
            card="bank_reconcile",
            status=STATUS_SKIPPED,
            reason="no transaction rows could be read from this statement",
        )

    invoices = _tenant_invoices(row, db_session)
    if not invoices:
        return InsightCard(
            card="bank_reconcile",
            status=STATUS_SKIPPED,
            reason="there are no invoices on file to match these transactions against",
        )

    result = match_statement_lines(
        lines, invoices, tenant_id=row.tenant_id, db_session=db_session
    )
    apply_matches(result, lines, db_session)
    ctx["bank_match"] = result
    ctx["bank_lines"] = lines

    balance = closing_balance(lines)
    figures = {
        "statement_line_count": float(len(lines)),
        "matched_count": float(len(result["matched"])),
        "unmatched_debit_count": float(len(result["unmatched_debits"])),
        "unmatched_credit_count": float(len(result["unmatched_credits"])),
    }
    if balance is not None:
        figures["closing_balance"] = balance

    findings = []
    for entry in result["possible_duplicates"]:
        findings.append(
            finding(
                f"bank_reconcile:duplicate:{entry['line_id']}",
                (
                    f"{entry['amount']} paid on {entry['line_date']} looks like "
                    f"{entry.get('invoice_number') or 'a bill'} being paid twice"
                ),
                card="bank_reconcile",
                impact_amount=entry["amount"],
                currency=row.currency,
                confidence="med",
                confidence_reason=entry.get("reason", "matched a bill that is already settled"),
                evidence=entry,
            )
        )
    for entry in result["unmatched_debits"]:
        figures[f"unmatched_debit_{entry['line_id'][:8]}"] = entry["amount"]
        findings.append(
            finding(
                f"bank_reconcile:unmatched_debit:{entry['line_id']}",
                (
                    f"{entry['amount']} left the account on {entry['line_date']} "
                    f"({entry['narration'] or 'no narration'}) with no invoice on file"
                ),
                card="bank_reconcile",
                impact_amount=entry["amount"],
                currency=row.currency,
                confidence="low",
                confidence_reason=(
                    "no invoice matches this row within "
                    f"{result['tolerances']['amount']} and "
                    f"{result['tolerances']['days']} days with the same supplier"
                ),
                evidence=entry,
            )
        )
    for entry in result["ambiguous"]:
        findings.append(
            finding(
                f"bank_reconcile:ambiguous:{entry['line_id']}",
                (
                    f"{entry['amount']} on {entry['line_date']} could be any of "
                    f"{len(entry.get('candidates', []))} bills -- pick which one"
                ),
                card="bank_reconcile",
                impact_amount=entry["amount"],
                currency=row.currency,
                confidence="low",
                confidence_reason="several invoices fit the amount, date and supplier equally",
                evidence=entry,
            )
        )

    return InsightCard(
        card="bank_reconcile",
        status=STATUS_OK,
        title=(
            f"{len(result['matched'])} of {len(lines)} transactions matched to invoices"
            + (f", as of {row.statement_date.isoformat()}" if row.statement_date else "")
        ),
        figures=figures,
        findings=findings,
        evidence={
            "tolerances": result["tolerances"],
            "matched": result["matched"][:20],
            "closing_balance": balance,
            "statement_date": row.statement_date.isoformat() if row.statement_date else None,
        },
    )


def card_cash_cover(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.5 async card — what is due against the balance, as of the statement date.

    Async because it reads the whole ledger through the semantic views rather
    than this document. Skipped, with the reason said out loud, when the
    statement printed no closing balance or no date: "as of" is not optional on
    a cash figure, and today's date is not a substitute for the statement's.
    """
    if ctx.get("stage") != "async":
        return InsightCard(
            card="cash_cover",
            status=STATUS_SKIPPED,
            reason="the cash view is computed a moment after the first answer",
        )

    from services.bank_ledger import closing_balance, statement_lines_for
    from services.bank_matching import cash_cover
    from services.semantic_views import query_metric

    lines = ctx.get("bank_lines") or statement_lines_for(row.id, db_session)
    balance = closing_balance(lines)
    if balance is None or row.statement_date is None:
        return InsightCard(
            card="cash_cover",
            status=STATUS_SKIPPED,
            reason=(
                "this statement prints no closing balance and date, and a cash "
                "figure without an 'as of' date would be misleading"
            ),
        )

    try:
        overdue = query_metric("overdue", row.tenant_id, db_session, flow_direction="INBOUND")
    except Exception as exc:
        logger.warning("cash_cover overdue lookup failed: %s", exc)
        return InsightCard(
            card="cash_cover", status=STATUS_BLOCKED, reason="the overdue list could not be read"
        )

    upcoming = _upcoming_payables(row, db_session)
    figures = cash_cover(balance, overdue, upcoming, row.statement_date)

    findings = []
    shortfall = figures.get("shortfall_within_30_days")
    if shortfall is not None and shortfall > 0:
        findings.append(
            finding(
                f"cash_cover:{row.id}",
                (
                    f"{shortfall} more is due in the next 30 days than the "
                    f"{figures['closing_balance']} on this statement"
                ),
                card="cash_cover",
                impact_amount=shortfall,
                currency=row.currency,
                confidence="med",
                confidence_reason=f"as of {figures['as_of']}, from your recorded bills",
                evidence=figures,
            )
        )

    return InsightCard(
        card="cash_cover",
        status=STATUS_OK,
        title=f"Cash position as of {figures['as_of']}",
        figures={k: v for k, v in figures.items() if isinstance(v, (int, float))},
        findings=findings,
        evidence=figures,
    )


def _upcoming_payables(row: Any, db_session: Any, horizon_days: int = 60) -> list:
    """Bills due within the horizon of the STATEMENT date, not of today.

    Written as one small parameterised query rather than a metric because it is
    the only consumer and the shape it needs (`due_date` + `grand_total`, dated
    from an arbitrary anchor) is not a metric anything else asks for.
    """
    from datetime import timedelta

    from sqlalchemy import text

    if row.statement_date is None:
        return []
    try:
        rows = db_session.execute(
            text(
                "SELECT invoice_number, grand_total, due_date FROM invoice "
                "WHERE tenant_id = :tenant_id AND deleted_at IS NULL "
                "AND status <> 'DUPLICATE' AND status <> 'PAID' AND paid_at IS NULL "
                "AND flow_direction = 'INBOUND' AND due_date IS NOT NULL "
                "AND due_date >= :anchor AND due_date <= :horizon"
            ),
            {
                "tenant_id": str(row.tenant_id),
                "anchor": row.statement_date,
                "horizon": row.statement_date + timedelta(days=horizon_days),
            },
        ).mappings().all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("upcoming payables lookup failed: %s", exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []
    return [dict(r) for r in rows]


def _vendor_spellings(row: Any, db_session: Any) -> list:
    """Every `invoice.vendor_name` spelling of this document's supplier.

    The vendor master's output when the tenant has confirmed who the supplier is,
    and the document's own party name otherwise. This is what turns "spend with
    this vendor" from a query over one spelling into a query over the supplier
    (30.0f), and every history card below takes it.
    """
    try:
        from services.vendor_master import resolve_vendor, vendor_invoice_names

        resolution = resolve_vendor(row.party_name, row.tenant_id, db_session)
        if resolution.is_bound:
            names = vendor_invoice_names(resolution.vendor.id, row.tenant_id, db_session)
            if names:
                return names
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("vendor spelling lookup failed for %s: %s", row.id, exc)
    return [row.party_name] if row.party_name else []


def _async_only(card: str) -> InsightCard:
    """The sync-stage answer for a card that needs the history queries.

    Said out loud rather than omitted: 30.12's "checks not run" lists it, so the
    user knows a second answer is coming instead of wondering why a card they
    saw once is missing.
    """
    return InsightCard(
        card=card,
        status=STATUS_SKIPPED,
        reason="this check runs a moment after the first answer",
    )


def card_cash_impact(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.6 — what this document means for money going out, for this supplier.

    Reads `v_overdue` and `v_vendor_spend` through `query_metric()`, so the
    figures are the views' definitions and not a second opinion written here.
    Async: both are ledger-wide queries.

    Currency is NOT converted. When the supplier's invoices are in a different
    currency from the document, the card says so and reports no total -- the same
    hard stop `_compare_one()` takes, for the same reason (this system holds no
    FX rate).
    """
    if ctx.get("stage") != "async":
        return _async_only("cash_impact")

    names = _vendor_spellings(row, db_session)
    if not names:
        return InsightCard(
            card="cash_impact",
            status=STATUS_SKIPPED,
            reason="this document does not name a supplier we can look up",
        )

    from services.semantic_views import query_metric

    overdue = query_metric(
        "overdue", row.tenant_id, db_session, vendor_names=names, flow_direction="INBOUND"
    )
    spend = query_metric("vendor_spend", row.tenant_id, db_session, vendor_names=names)

    currencies = {r.get("currency") for r in overdue if r.get("currency")}
    if row.currency and currencies and row.currency not in currencies:
        return InsightCard(
            card="cash_impact",
            status=STATUS_SKIPPED,
            reason=(
                f"this {_label(row.doc_type)} is in {row.currency} and the invoices on "
                f"file for {row.party_name} are in {', '.join(sorted(currencies))}; "
                "amounts in two currencies are not added together"
            ),
        )

    overdue_total = sum((_dec(r["grand_total"]) or Decimal("0")) for r in overdue)
    months = sorted({str(r["month"]) for r in spend})
    monthly = [
        {
            "month": str(r["month"]),
            "total": _f(_dec(r["total_amount"])),
            "invoice_count": int(r["invoice_count"]),
        }
        for r in spend[:12]
    ]
    average = (
        _f(sum((_dec(r["total_amount"]) or Decimal("0")) for r in spend) / Decimal(len(months)))
        if months
        else None
    )

    figures = {"overdue_total": _f(overdue_total), "overdue_count": float(len(overdue))}
    if average is not None:
        figures["average_month_with_this_supplier"] = average
    doc_total = _dec(row.grand_total)
    if doc_total is not None:
        figures["this_document_total"] = _f(doc_total)

    findings = []
    if overdue:
        oldest = max(overdue, key=lambda r: r["days_overdue"])
        findings.append(
            finding(
                f"cash_impact:overdue:{row.party_name}",
                (
                    f"{_f(overdue_total)} is already overdue with {row.party_name} "
                    f"across {len(overdue)} bill(s); the oldest is "
                    f"{oldest['invoice_number']} at {oldest['days_overdue']} days"
                ),
                card="cash_impact",
                impact_amount=_f(overdue_total),
                currency=row.currency,
                confidence="high",
                confidence_reason="computed from your own recorded due dates",
                evidence={
                    "overdue": overdue[:10],
                    "oldest_invoice": oldest["invoice_number"],
                },
            )
        )

    return InsightCard(
        card="cash_impact",
        status=STATUS_OK,
        title=f"What this means for cash with {row.party_name or 'this supplier'}",
        figures=figures,
        findings=findings,
        evidence={"monthly_spend": monthly, "vendor_spellings": names},
    )


def card_open_po_value(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — how much of this PO has not been invoiced yet.

    The PO's own total minus what `v_3way_match` says has been billed against
    that PO number. Ungated (no R9 threshold): it is arithmetic on this document,
    not a claim about the supplier's behaviour.
    """
    if ctx.get("stage") != "async":
        return _async_only("open_po_value")

    po_number = (row.extracted_json or {}).get("po_number") or row.doc_number
    ordered = _dec(row.grand_total)
    if not po_number or ordered is None:
        return InsightCard(
            card="open_po_value",
            status=STATUS_SKIPPED,
            reason="this document prints no order number and total we can track against",
        )

    from services.semantic_views import query_metric

    rows = query_metric("three_way_match", row.tenant_id, db_session, po_number=str(po_number))
    invoiced = sum((_dec(r["invoiced_amount"]) or Decimal("0")) for r in rows)
    remaining = ordered - invoiced

    figures = {
        "ordered_value": _f(ordered),
        "invoiced_against_order": _f(invoiced),
        "not_yet_invoiced": _f(remaining),
    }
    findings = []
    if remaining > 0:
        findings.append(
            finding(
                f"open_po_value:{po_number}",
                f"{_f(remaining)} of this order has not been invoiced yet",
                card="open_po_value",
                impact_amount=_f(remaining),
                currency=row.currency,
                confidence="high" if rows else "med",
                confidence_reason=(
                    "from the invoices recorded against this order number"
                    if rows
                    else "no invoice has been recorded against this order number yet"
                ),
                evidence={"po_number": str(po_number), "matched": rows[:5]},
            )
        )
    elif remaining < 0:
        findings.append(
            finding(
                f"open_po_value:over:{po_number}",
                f"{_f(abs(remaining))} more has been invoiced than this order authorised",
                card="open_po_value",
                impact_amount=_f(abs(remaining)),
                currency=row.currency,
                confidence="high",
                confidence_reason="from the invoices recorded against this order number",
                evidence={"po_number": str(po_number), "matched": rows[:5]},
            )
        )

    return InsightCard(
        card="open_po_value",
        status=STATUS_OK,
        title="What is still to come on this order",
        figures=figures,
        findings=findings,
    )


def card_cash_out_timing(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — when this order's money is likely to leave, from its own terms.

    The date is derived from the document's printed payment window and its own
    date; nothing is inferred from the supplier's past behaviour, because that
    would be a prediction and this card reports a term.
    """
    if ctx.get("stage") != "async":
        return _async_only("cash_out_timing")

    data = row.extracted_json or {}
    days = _payment_days(data.get("payment_terms"))
    total = _dec(row.grand_total)
    if days is None or total is None or row.doc_date is None:
        return InsightCard(
            card="cash_out_timing",
            status=STATUS_SKIPPED,
            reason="this document does not print a date, a total and a payment window together",
        )

    from datetime import timedelta as _td

    expected = row.doc_date + _td(days=days)
    return InsightCard(
        card="cash_out_timing",
        status=STATUS_OK,
        title=f"Expected to be payable around {expected.isoformat()}",
        figures={"expected_outflow": _f(total), "payment_days": float(days)},
        findings=[
            finding(
                f"cash_out_timing:{row.doc_number or row.id}",
                f"{_f(total)} is likely to be payable around {expected.isoformat()}",
                card="cash_out_timing",
                impact_amount=_f(total),
                currency=row.currency,
                confidence="med",
                confidence_reason=f"from this document's own '{data.get('payment_terms')}' terms",
                evidence={
                    "document_date": row.doc_date.isoformat(),
                    "payment_days": days,
                    "expected_date": expected.isoformat(),
                },
            )
        ],
    )


def card_over_invoicing_history(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — has this supplier billed over its orders before? (R9: >= 3 pairs.)

    The threshold is the point: below three linked PO/invoice pairs there is no
    "history", only an anecdote, and the card says so with the number it used.
    """
    if ctx.get("stage") != "async":
        return _async_only("over_invoicing_history")

    from services.insight_thresholds import threshold
    from services.semantic_views import query_metric

    names = _vendor_spellings(row, db_session)
    if not names:
        return InsightCard(
            card="over_invoicing_history",
            status=STATUS_SKIPPED,
            reason="this document does not name a supplier we can look up",
        )

    required = int(threshold("over_invoicing_pairs", row.tenant_id, db_session))
    pairs = query_metric("three_way_match", row.tenant_id, db_session, vendor_names=names)
    if len(pairs) < required:
        return InsightCard(
            card="over_invoicing_history",
            status=STATUS_SKIPPED,
            reason=(
                f"only {len(pairs)} order(s) from {row.party_name} have invoices against "
                f"them; this check needs {required} before it means anything"
            ),
        )

    total_invoiced = sum((_dec(p["invoiced_amount"]) or Decimal("0")) for p in pairs)
    multi = [p for p in pairs if int(p["invoice_count"]) > 1]
    figures = {
        "orders_with_invoices": float(len(pairs)),
        "total_invoiced_against_orders": _f(total_invoiced),
        "threshold_used": float(required),
    }
    findings = []
    if multi:
        findings.append(
            finding(
                f"over_invoicing_history:{row.party_name}",
                (
                    f"{len(multi)} of {len(pairs)} orders from {row.party_name} were "
                    "invoiced more than once"
                ),
                card="over_invoicing_history",
                impact_amount=_f(
                    sum((_dec(p["invoiced_amount"]) or Decimal("0")) for p in multi)
                ),
                currency=row.currency,
                confidence="med",
                confidence_reason=(
                    "several invoices against one order can be legitimate part-billing; "
                    "this is a pattern worth checking, not a finding on its own"
                ),
                evidence={"orders": multi[:5]},
            )
        )
    return InsightCard(
        card="over_invoicing_history",
        status=STATUS_OK,
        title=f"Order history with {row.party_name}",
        figures=figures,
        findings=findings,
    )


def card_quote_drift(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — has this supplier drifted from the quoted price? (R9: >= 2 invoices.)

    Compares the quotation's own total against the average invoice total from the
    same supplier AFTER the quote date. Two invoices is the floor because a
    single later invoice is a data point, not a drift.
    """
    if ctx.get("stage") != "async":
        return _async_only("quote_drift")

    from services.insight_thresholds import threshold
    from services.semantic_views import query_metric

    quoted = _dec(row.grand_total)
    if quoted is None or quoted == 0 or row.doc_date is None:
        return InsightCard(
            card="quote_drift",
            status=STATUS_SKIPPED,
            reason="this quotation prints no date and total we can measure against",
        )

    names = _vendor_spellings(row, db_session)
    required = int(threshold("quote_drift_invoices", row.tenant_id, db_session))
    rows = query_metric(
        "vendor_spend", row.tenant_id, db_session, vendor_names=names, since=row.doc_date
    )
    invoice_count = sum(int(r["invoice_count"]) for r in rows)
    if invoice_count < required:
        return InsightCard(
            card="quote_drift",
            status=STATUS_SKIPPED,
            reason=(
                f"only {invoice_count} invoice(s) from {row.party_name} since this quote; "
                f"drift needs {required}"
            ),
        )

    billed = sum((_dec(r["total_amount"]) or Decimal("0")) for r in rows)
    average = billed / Decimal(invoice_count)
    drift = average - quoted
    drift_pct = _f((drift / quoted) * Decimal("100"))

    figures = {
        "quoted_total": _f(quoted),
        "average_invoice_since_quote": _f(average),
        "drift_amount": _f(drift),
        "drift_percent": drift_pct,
        "invoices_since_quote": float(invoice_count),
        "threshold_used": float(required),
    }
    findings = []
    if drift > 0:
        findings.append(
            finding(
                f"quote_drift:{row.doc_number or row.id}",
                (
                    f"invoices from {row.party_name} since this quote average "
                    f"{_f(average)} against a quoted {_f(quoted)}"
                ),
                card="quote_drift",
                impact_amount=_f(drift),
                currency=row.currency,
                confidence="low",
                confidence_reason=(
                    "compares whole-invoice totals, not line rates, so a bigger order "
                    "reads as drift too"
                ),
                evidence={"months": [dict(r, month=str(r["month"])) for r in rows[:6]]},
            )
        )
    return InsightCard(
        card="quote_drift",
        status=STATUS_OK,
        title=f"Prices since this quote ({invoice_count} invoice(s))",
        figures=figures,
        findings=findings,
    )


def card_partial_delivery_balance(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — what is still owed on a part delivery.

    Ungated: it is arithmetic on this challan against the order it names, not a
    claim about the supplier.
    """
    if ctx.get("stage") != "async":
        return _async_only("partial_delivery_balance")

    data = row.extracted_json or {}
    po_number = data.get("po_number")
    if not po_number:
        return InsightCard(
            card="partial_delivery_balance",
            status=STATUS_SKIPPED,
            reason="this delivery note does not name the order it belongs to",
        )

    delivered = [i for i in (data.get("items") or []) if _dec(i.get("quantity")) is not None]
    if not delivered:
        return InsightCard(
            card="partial_delivery_balance",
            status=STATUS_SKIPPED,
            reason="no line quantities could be read from this delivery note",
        )

    from services.semantic_views import query_metric

    rows = query_metric("three_way_match", row.tenant_id, db_session, po_number=str(po_number))
    figures = {
        "delivered_line_count": float(len(delivered)),
        "invoiced_against_order": _f(
            sum((_dec(r["invoiced_amount"]) or Decimal("0")) for r in rows)
        ),
    }
    return InsightCard(
        card="partial_delivery_balance",
        status=STATUS_OK,
        title=f"Delivery against order {po_number}",
        figures=figures,
        evidence={"po_number": str(po_number), "invoices": rows[:5]},
    )


def card_repeat_short_delivery(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — does this supplier short-deliver repeatedly? (R9: >= 3 challans.)

    Counts the tenant's OWN delivery-note attachments from this supplier. The
    evidence is the documents the user uploaded, which is the only record of
    deliveries this system has -- there is no goods-receipt table, and inventing
    one from invoice lines would be a different claim entirely.
    """
    if ctx.get("stage") != "async":
        return _async_only("repeat_short_delivery")

    from sqlmodel import select

    from models import ChatAttachment
    from services.insight_thresholds import threshold
    from services.vendor_master import normalise_vendor_name

    required = int(threshold("repeat_short_delivery_challans", row.tenant_id, db_session))
    try:
        challans = db_session.exec(
            select(ChatAttachment).where(
                ChatAttachment.tenant_id == row.tenant_id,
                ChatAttachment.doc_type.in_(["DELIVERY_NOTE", "GRN"]),
            )
        ).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("challan history lookup failed: %s", exc)
        return InsightCard(
            card="repeat_short_delivery",
            status=STATUS_BLOCKED,
            reason="the delivery-note history could not be read",
        )

    key = normalise_vendor_name(row.party_name)
    theirs = [c for c in challans if normalise_vendor_name(c.party_name) == key]
    if len(theirs) < required:
        return InsightCard(
            card="repeat_short_delivery",
            status=STATUS_SKIPPED,
            reason=(
                f"only {len(theirs)} delivery note(s) from {row.party_name} are on file; "
                f"a repeat pattern needs {required}"
            ),
        )

    shortfalls = []
    for challan in theirs:
        for f_ in (challan.insights or {}).get("findings", []):
            if f_.get("card") == "delivery_vs_order" and (
                (f_.get("evidence") or {}).get("direction") == "short_delivery"
            ):
                shortfalls.append(
                    {
                        "attachment_id": str(challan.id),
                        "doc_number": challan.doc_number,
                        "description": (f_.get("evidence") or {}).get("description"),
                    }
                )

    figures = {
        "delivery_notes_on_file": float(len(theirs)),
        "short_delivered_lines": float(len(shortfalls)),
        "threshold_used": float(required),
    }
    findings = []
    if shortfalls:
        findings.append(
            finding(
                f"repeat_short_delivery:{row.party_name}",
                (
                    f"{len(shortfalls)} short-delivered line(s) across "
                    f"{len(theirs)} delivery notes from {row.party_name}"
                ),
                card="repeat_short_delivery",
                confidence="med",
                confidence_reason="from the delivery notes you have uploaded",
                evidence={"shortfalls": shortfalls[:10]},
            )
        )
    return InsightCard(
        card="repeat_short_delivery",
        status=STATUS_OK,
        title=f"Delivery record for {row.party_name}",
        figures=figures,
        findings=findings,
    )


def card_contract_deviations(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.18 — do this supplier's invoices follow the contract? (>= 2 invoices.)

    Only the payment window is measured, for the same reason `card_terms_check()`
    limits itself: it is the one term printed on both documents in a comparable
    form. Anything else needs the rule cards (30.11).
    """
    if ctx.get("stage") != "async":
        return _async_only("contract_deviations")

    from services.insight_thresholds import threshold

    data = row.extracted_json or {}
    agreed_days = _payment_days(data.get("payment_terms"))
    if agreed_days is None:
        return InsightCard(
            card="contract_deviations",
            status=STATUS_SKIPPED,
            reason="this contract does not print a payment window we can read",
        )

    names = _vendor_spellings(row, db_session)
    required = int(threshold("quote_drift_invoices", row.tenant_id, db_session))

    from sqlalchemy import text

    try:
        rows = db_session.execute(
            text(
                "SELECT invoice_number, invoice_date, due_date FROM invoice "
                "WHERE tenant_id = :tenant_id AND deleted_at IS NULL "
                "AND status <> 'DUPLICATE' AND flow_direction = 'INBOUND' "
                "AND vendor_name = ANY(:names) AND invoice_date IS NOT NULL "
                "AND due_date IS NOT NULL"
            ),
            {"tenant_id": str(row.tenant_id), "names": list(names)},
        ).mappings().all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("contract deviation lookup failed: %s", exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return InsightCard(
            card="contract_deviations", status=STATUS_BLOCKED, reason="the invoice history could not be read"
        )

    if len(rows) < required:
        return InsightCard(
            card="contract_deviations",
            status=STATUS_SKIPPED,
            reason=(
                f"only {len(rows)} invoice(s) from {row.party_name} carry both dates; "
                f"this check needs {required}"
            ),
        )

    deviations = [
        {
            "invoice_number": r["invoice_number"],
            "invoice_days": (r["due_date"] - r["invoice_date"]).days,
        }
        for r in rows
        if (r["due_date"] - r["invoice_date"]).days != agreed_days
    ]
    figures = {
        "contract_payment_days": float(agreed_days),
        "invoices_checked": float(len(rows)),
        "invoices_off_contract": float(len(deviations)),
        "threshold_used": float(required),
    }
    findings = []
    if deviations:
        findings.append(
            finding(
                f"contract_deviations:{row.doc_number or row.id}",
                (
                    f"{len(deviations)} of {len(rows)} invoices from {row.party_name} "
                    f"do not use the contract's {agreed_days}-day payment window"
                ),
                card="contract_deviations",
                confidence="med",
                confidence_reason="compares the printed contract term against recorded due dates",
                evidence={"deviations": deviations[:10]},
            )
        )
    return InsightCard(
        card="contract_deviations",
        status=STATUS_OK,
        title=f"Contract terms against {len(rows)} invoice(s)",
        figures=figures,
        findings=findings,
    )


def card_compliance(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.11 — the regional rule cards that apply to THIS document, each with a
    deterministic verdict and the primary source it came from.

    Three things this card refuses to do, all of them for the same reason (a
    compliance statement is quoted back to an accountant):

      * it never runs a rule from a region the document does not belong to --
        `detect_region()` (30.0d) decides, and no region means no checks;
      * it never shows a card whose source nobody fetched -- `load_rule_cards()`
        filters `status != verified` out (hard rule 8);
      * it never asks a model whether a document complies. The card supplies the
        rule and the citation; `CHECKS` supplies the verdict.

    A failed check is a finding with NO impact amount: "no GSTIN printed" costs
    an unknown amount of trouble, and inventing a number for it would be exactly
    the fabrication this feature is built to prevent.
    """
    region = getattr(row, "region", None)
    if not region:
        return InsightCard(
            card="compliance",
            status=STATUS_SKIPPED,
            reason=(
                "we could not tell which country's rules apply to this document "
                "(no GSTIN, VAT id or US address on it)"
            ),
        )

    from services.rule_cards import run_compliance_checks

    results = run_compliance_checks(row, region)
    if not results:
        return InsightCard(
            card="compliance",
            status=STATUS_SKIPPED,
            reason=f"no {region} rule card applies to a {_label(row.doc_type)} yet",
        )

    findings = []
    for result in results:
        if result["outcome"] != "fail":
            continue
        findings.append(
            finding(
                f"compliance:{result['card_id']}",
                f"{result['title']} — {result['detail']}",
                card="compliance",
                confidence="high",
                confidence_reason=(
                    f"checked against {result.get('source_title') or 'the published rule'}"
                ),
                evidence=result,
            )
        )

    passed = [r for r in results if r["outcome"] == "pass"]
    return InsightCard(
        card="compliance",
        status=STATUS_OK,
        title=f"{len(passed)} of {len(results)} {region} checks passed",
        findings=findings,
        evidence={"region": region, "checks": results},
    )


def card_suggested_questions(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.8 — three questions worth clicking about THIS document type.

    Certified examples for this type when the tenant has them, the built-in
    starters otherwise. Never has findings and never opens an `insight` row: a
    question is not a finding, and a bubble that opened work items for its own
    suggestions would fill the dashboard with prompts nobody asked for.
    """
    from services.certified_examples import suggested_questions

    try:
        questions = suggested_questions(
            str(row.doc_type or "").strip().upper(), db_session, row.tenant_id, k=3
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Suggested questions failed for %s: %s", row.id, exc)
        return InsightCard(
            card="suggested_questions",
            status=STATUS_BLOCKED,
            reason="the suggested questions could not be prepared",
        )
    return InsightCard(
        card="suggested_questions",
        status=STATUS_OK,
        title="You could ask",
        evidence={"questions": questions},
    )


def card_confidence_gaps(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """30.12 — "checks not run + why", and which fields we were unsure of.

    Built from what the OTHER cards actually reported, not from a static list:
    a card that is skipped for a new reason says so without this card being
    edited, and a card that is added is covered the day it is added.
    """
    skipped = [
        {"card": c.card, "reason": c.reason}
        for c in ctx.get("cards_so_far", [])
        if c.status in (STATUS_SKIPPED, STATUS_BLOCKED)
    ]
    confidences = (row.extracted_json or {}).get("field_confidence") or {}
    low = [
        field
        for field, score in confidences.items()
        if isinstance(score, (int, float)) and score < 0.6
    ]
    return InsightCard(
        card="confidence_gaps",
        status=STATUS_OK,
        title="What was not checked",
        evidence={
            "checks_not_run": skipped,
            "low_confidence_fields": sorted(low),
            "thresholds": ctx.get("thresholds", {}),
            "stage": ctx.get("stage"),
        },
    )


#: Which cards run for which document type, in render order (§8.5).
#: A table, not a chain of ifs, so "what does a credit note get?" is answerable
#: by reading one line, and so an unlisted type gets nothing rather than
#: whatever the last branch happened to be.
#: The async-only cards (30.6 / 30.18) are in these tuples too, not in a second
#: registry. One list per document type is what makes "what does a PO get?"
#: answerable by reading one line; each async card skips ITSELF at the sync stage
#: with a stated reason, so the sync bubble stays under three seconds and the
#: user is told a second answer is coming.
CARDS_BY_DOC_TYPE: dict = {
    "PURCHASE_ORDER": (
        card_what_this_is, card_agreed_vs_billed, card_terms_check,
        card_open_po_value, card_cash_out_timing, card_over_invoicing_history,
        card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "ORDER_CONFIRMATION": (
        card_what_this_is, card_agreed_vs_billed, card_terms_check,
        card_open_po_value, card_cash_out_timing, card_over_invoicing_history,
        card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "QUOTATION": (
        card_what_this_is, card_agreed_vs_billed, card_quote_drift,
        card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "CONTRACT": (
        card_what_this_is, card_terms_check, card_agreed_vs_billed,
        card_contract_deviations, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "DELIVERY_NOTE": (
        card_what_this_is, card_delivery_vs_order, card_partial_delivery_balance,
        card_repeat_short_delivery, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "GRN": (
        card_what_this_is, card_delivery_vs_order, card_partial_delivery_balance,
        card_repeat_short_delivery, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "CREDIT_NOTE": (card_what_this_is, card_net_position, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps),
    "DEBIT_NOTE": (card_what_this_is, card_net_position, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps),
    "REMITTANCE_ADVICE": (card_what_this_is, card_net_position, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps),
    # 30.5: the sync card matches the ledger rows; the cash-cover card is async
    # and skips itself at the sync stage with that as its reason.
    "STATEMENT_OF_ACCOUNT": (
        card_what_this_is,
        card_bank_reconcile,
        card_cash_cover,
        card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
}

#: Ruling R4's five actions, as data. The FE renders these; the BE endpoint that
#: executes them is `POST /chat/insights/{id}/transition` (+ `/discuss`).
# Gap 492: information only. No action here touches an invoice; the user acts
# offline and may record a note about it.
BUBBLE_ACTIONS: tuple = (
    {"action": "note", "label": "Add a note", "status": "ACTED", "outcome": "note"},
    {"action": "discuss", "label": "Discuss", "endpoint": "discuss"},
    {"action": "dismiss", "label": "Dismiss", "status": "DISMISSED", "outcome": "dismissed"},
)


# ---------------------------------------------------------------------------
# The block
# ---------------------------------------------------------------------------


def build_insight_block(
    row: Any, db_session: Any, tenant_id: Any = None, stage: str = "sync"
) -> dict:
    """Run this document type's cards and return the facts JSON. Never raises.

    `tenant_id` is accepted and checked rather than trusted from the row: every
    query this block runs is tenant-scoped, and a caller passing a different
    tenant than the row's is a bug that must not silently read another tenant's
    invoices.
    """
    doc_type = str(row.doc_type or "").strip().upper()
    if tenant_id is not None and str(tenant_id) != str(row.tenant_id):
        logger.error(
            "Insight block refused: tenant %s asked for attachment %s owned by %s",
            tenant_id, row.id, row.tenant_id,
        )
        return _empty_block(row, stage, "tenant mismatch")

    cards: list = []
    ctx: dict = {
        "stage": stage,
        "invoices": [],
        "cards_so_far": cards,
        "thresholds": {},
    }
    try:
        ctx["invoices"] = _linked_invoices(row, db_session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Insight linking failed for %s: %s", row.id, exc)
    try:
        from services.insight_thresholds import all_thresholds

        ctx["thresholds"] = all_thresholds(row.tenant_id, db_session)
    except Exception:  # pragma: no cover - defensive
        ctx["thresholds"] = {}

    for card_fn in CARDS_BY_DOC_TYPE.get(doc_type, ()):
        try:
            cards.append(card_fn(row, db_session, ctx))
        except Exception as exc:
            # BLOCKED, and the remaining cards still run. One card that cannot
            # read its input must not cost the user the other four.
            logger.error(
                "Insight card %s blocked on attachment %s: %s",
                getattr(card_fn, "__name__", "?"), row.id, exc, exc_info=True,
            )
            cards.append(
                InsightCard(
                    card=getattr(card_fn, "__name__", "card").replace("card_", ""),
                    status=STATUS_BLOCKED,
                    reason="this check could not be completed on this document",
                )
            )

    findings = [f for c in cards for f in c.findings]
    figures: dict = {}
    for c in cards:
        figures.update(c.figures)

    block = {
        "stage": stage,
        "doc_type": doc_type,
        "doc_type_label": _label(doc_type),
        "attachment_id": str(row.id),
        # Carried so the narration step can look up THIS tenant's glossary (30.7)
        # without being handed a session it has no other use for.
        "tenant_id": str(row.tenant_id),
        "currency": row.currency,
        "region": getattr(row, "region", None),
        "cards": [c.as_dict() for c in cards],
        "findings": findings,
        "figures": figures,
        "checks_not_run": [
            {"card": c.card, "reason": c.reason}
            for c in cards
            if c.status in (STATUS_SKIPPED, STATUS_BLOCKED)
        ],
        "actions": list(BUBBLE_ACTIONS),
        "verdict": "",
        "verdict_source": "template",
        "generated_at": datetime.utcnow().isoformat(),
    }
    block["findings"] = rank_findings(block)
    block["verdict"] = verdict_template(block)
    # BE Gap 494: one boundary where database types become JSON types. Nothing
    # downstream -- three JSONB columns and an SSE event -- can hold a `UUID`,
    # a `date` or a `Decimal`, and the failure lands at COMMIT rather than in
    # the card that produced it.
    return jsonable(block)


def _empty_block(row: Any, stage: str, reason: str) -> dict:
    return {
        "stage": stage,
        "doc_type": str(row.doc_type or "").strip().upper(),
        "attachment_id": str(row.id),
        "cards": [],
        "findings": [],
        "figures": {},
        "checks_not_run": [{"card": "all", "reason": reason}],
        "actions": list(BUBBLE_ACTIONS),
        "verdict": "",
        "verdict_source": "template",
        "generated_at": datetime.utcnow().isoformat(),
    }


def rank_findings(block: dict, llm: Any = None) -> list:
    """Order the findings. Deterministic by default (§8.3: the model may rank,
    the figures are not its to touch).

    Money first, biggest first, then everything unquantified in the order the
    cards produced it. `llm` is accepted for the async stage's optional
    model ranking; when it is None — which is every sync call and every test —
    this is pure arithmetic.
    """
    findings = list(block.get("findings") or [])

    def key(f_: dict):
        weight = {"high": 1.0, "med": 0.6, "low": 0.3}.get(f_.get("confidence", "med"), 0.6)
        amount = f_.get("impact_amount")
        return (1 if amount else 0, abs(float(amount or 0.0)) * weight)

    return sorted(findings, key=key, reverse=True)


def verdict_template(block: dict) -> str:
    """The sync stage's verdict line: template text from the top finding (§8.6.2).

    Deliberately plain and deliberately not clever. It is shown for the seconds
    before the narration arrives, and it has to be TRUE with no model involved —
    so it repeats the top finding's own words and its own figure, and says
    nothing else.
    """
    findings = block.get("findings") or []
    label = block.get("doc_type_label") or "document"
    if not findings:
        checks = block.get("checks_not_run") or []
        if checks and not any(c.get("card") == "what_this_is" for c in checks):
            return f"I read this {label}. Nothing to flag from what is on file right now."
        return f"I read this {label}."
    top = findings[0]
    extra = len(findings) - 1
    tail = f" (+{extra} more)" if extra > 0 else ""
    return f"{top.get('title')}.{tail}"


# ---------------------------------------------------------------------------
# Narration (30.2) — the only model call in this feature
# ---------------------------------------------------------------------------

NARRATION_SYSTEM_PROMPT = (
    "You write one short verdict line for a small business owner about a "
    "financial document they just uploaded.\n\n"
    "EVERY FIGURE HAS ALREADY BEEN COMPUTED and is given to you in the JSON "
    "below. You must not compute, sum, convert, estimate or round any number. "
    "If you state a figure, copy it exactly from the JSON. If a figure you want "
    "is not in the JSON, do not state it.\n\n"
    "Write ONE sentence, plain words, no jargon: say 'overbilled', 'short "
    "delivered', 'paid twice?', never 'variance', 'delta', '3-way match' or "
    "'tier'. Name the supplier and the action if there is one. Do not add "
    "advice that is not supported by the findings."
)


def narrate_insight_block(block: dict, llm: Any = None, glossary: dict | None = None) -> dict:
    """One fast-tier call that rewrites the verdict line, gated on its figures.

    Returns `{"verdict": str, "source": "model"|"template", "gate": {...}}`.

    THE GATE IS THE POINT. `_answer_contract_gate()` (Feature 29) checks every
    figure in the model's sentence against the block's own numbers; one that is
    not there means the model computed something, and the TEMPLATE TEXT STANDS.
    There is no retry: the sync bubble is already on screen with a true sentence
    on it, so the cost of a failed narration is zero and the cost of a second
    call is a second chance to invent a number.
    """
    import json

    template = block.get("verdict") or verdict_template(block)
    if llm is None:
        try:
            from utils.llm import get_llm_for_role

            llm = get_llm_for_role("chat_summary")
        except Exception as exc:  # pragma: no cover - env dependent
            logger.warning("Insight narration unavailable: %s", exc)
            return {"verdict": template, "source": "template", "gate": {"status": "skipped"}}

    if glossary is None:
        # 30.7: the tenant's own words, when the knowledge layer is on. `{}` when
        # it is off, and `{}` is a complete answer -- the narration is not
        # degraded without a glossary, it is simply in our words rather than
        # theirs.
        try:
            from services.knowledge import glossary_for_narration

            glossary = glossary_for_narration(block.get("tenant_id"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Glossary lookup failed for narration: %s", exc)
            glossary = {}

    payload = {
        "document": {
            "type": block.get("doc_type_label"),
            "currency": block.get("currency"),
        },
        "findings": [
            {
                "title": f_.get("title"),
                "impact_amount": f_.get("impact_amount"),
                "confidence": f_.get("confidence"),
            }
            for f_ in (block.get("findings") or [])[:3]
        ],
        "figures": block.get("figures") or {},
        "checks_not_run": block.get("checks_not_run") or [],
    }
    if glossary:
        payload["glossary"] = glossary
        # The glossary is vocabulary, never figures. Saying so in the prompt
        # keeps a canonical field name from being read as a value to repeat.
        payload["glossary_note"] = (
            "These are the words this business uses. Use their wording; they are "
            "not figures and contain nothing you may state as an amount."
        )

    try:
        response = llm.invoke(
            [
                {"role": "system", "content": NARRATION_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ]
        )
        prose = getattr(response, "content", None) or str(response)
    except Exception as exc:
        logger.warning("Insight narration call failed: %s", exc)
        return {"verdict": template, "source": "template", "gate": {"status": "failed"}}

    prose = str(prose).strip()
    if not prose:
        return {"verdict": template, "source": "template", "gate": {"status": "empty"}}

    try:
        from agents.query_agent import _answer_contract_gate, _gate_evidence_numbers

        allowed = _gate_evidence_numbers(json.dumps(payload, default=str))
        verdict = _answer_contract_gate(prose, allowed)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Insight answer-contract gate unavailable: %s", exc)
        return {"verdict": template, "source": "template", "gate": {"status": "unavailable"}}

    if verdict.get("status") != "ok":
        logger.warning(
            "Insight narration rejected for attachment %s: figures %s are not in the block",
            block.get("attachment_id"), verdict.get("unsupported"),
        )
        return {
            "verdict": template,
            "source": "template",
            "gate": {
                "status": "unsupported",
                "unsupported": [str(n) for n in verdict.get("unsupported", [])],
            },
        }
    return {"verdict": prose, "source": "model", "gate": {"status": "ok"}}


# ---------------------------------------------------------------------------
# Posting the turn (30.2)
# ---------------------------------------------------------------------------


def post_insight_turn(row: Any, block: dict, db_session: Any, message_id: Any = None) -> Any:
    """Write (or update) the assistant turn that carries the bubble.

    On the sync stage this creates the message. On the async stage it is given
    the SAME message id and REPLACES the payload in place, bumping
    `ChatAttachment.insights_version` — §8.6 step 4's "one bubble that improves"
    rather than a second turn that argues with the first.

    The block is written to two places on purpose: `ChatMessage.attachment_payload`
    is what the browser renders and what a session reload restores, and
    `ChatAttachment.insights` is what a LATER turn reads when the user asks
    "what did you flag on this?" without the message in context.
    """
    from models import ChatMessage

    message = None
    if message_id is not None:
        message = db_session.get(ChatMessage, message_id)

    payload = dict(message.attachment_payload or {}) if message is not None else {}
    payload["insights"] = block

    if message is None:
        message = ChatMessage(
            # No `tenant_id` on this table -- ownership is resolved through
            # `session_id` -> `ChatSession.tenant_id`, the way every other chat
            # turn is written.
            session_id=row.session_id,
            role="assistant",
            content=block.get("verdict") or "",
            attachment_payload=payload,
            status="completed",
        )
    else:
        message.content = block.get("verdict") or message.content
        message.attachment_payload = payload

    db_session.add(message)

    row.insights = block
    row.insights_version = int(getattr(row, "insights_version", 0) or 0) + 1
    db_session.add(row)
    db_session.commit()
    db_session.refresh(message)
    db_session.refresh(row)

    # 30.13's monitoring half. Counts and outcomes only -- never finding text or
    # a party name, because this event lands in a shared workspace.
    try:
        import telemetry

        cards = block.get("cards") or []
        findings = block.get("findings") or []
        telemetry.track_insight_bubble(
            tenant_id=str(row.tenant_id),
            attachment_id=str(row.id),
            doc_type=block.get("doc_type") or "",
            stage=block.get("stage") or "",
            region=block.get("region") or "",
            card_count=len(cards),
            ok_cards=sum(1 for c in cards if c.get("status") == STATUS_OK),
            skipped_cards=sum(1 for c in cards if c.get("status") == STATUS_SKIPPED),
            blocked_cards=sum(1 for c in cards if c.get("status") == STATUS_BLOCKED),
            finding_count=len(findings),
            impact_total=sum(abs(float(f.get("impact_amount") or 0.0)) for f in findings),
            verdict_source=block.get("verdict_source") or "",
            gate_status=(block.get("verdict_gate") or {}).get("status", ""),
        )
    except Exception as exc:  # pragma: no cover - telemetry never fails a turn
        logger.warning("insight_bubble telemetry failed for %s: %s", row.id, exc)

    return message


def open_insights_from_block(row: Any, block: dict, db_session: Any) -> list:
    """Every finding in the block becomes (or refreshes) an `insight` row.

    Called at both stages; `open_insight()` is keyed on `(attachment_id,
    finding_key)`, so the async stage updates the sync stage's rows instead of
    duplicating them, and a finding the user already dismissed stays dismissed.
    """
    from services.insights import open_insight

    out = []
    for f_ in block.get("findings") or []:
        try:
            out.append(
                open_insight(
                    tenant_id=row.tenant_id,
                    attachment_id=row.id,
                    session_id=row.session_id,
                    doc_type=block.get("doc_type") or row.doc_type,
                    card=f_.get("card") or "unknown",
                    finding_key=f_.get("finding_key") or "",
                    title=f_.get("title") or "",
                    impact_amount=f_.get("impact_amount"),
                    currency=f_.get("currency") or row.currency,
                    confidence=f_.get("confidence") or "med",
                    confidence_reason=f_.get("confidence_reason"),
                    evidence=f_.get("evidence"),
                    db_session=db_session,
                )
            )
        except Exception as exc:
            logger.error("Could not open finding %s on %s: %s", f_.get("finding_key"), row.id, exc)
    return out


def run_sync_insights(row: Any, db_session: Any) -> Optional[dict]:
    """The whole sync stage, as one call the extractor can make and forget.

    Returns the block, or None when the flag is off / the type does not qualify
    / anything at all goes wrong. NOTHING here may raise into the extraction
    path: an insight is an extra, and an extra that fails an upload is a
    Feature 26 regression.
    """
    if not insights_enabled() or not is_insight_doc_type(row.doc_type):
        return None
    try:
        from services.region import set_attachment_region

        set_attachment_region(row, db_session)
        block = build_insight_block(row, db_session, row.tenant_id, stage="sync")
        message = post_insight_turn(row, block, db_session)
        open_insights_from_block(row, block, db_session)
        block["message_id"] = str(message.id)
        # Persisted so the async stage updates the same message rather than
        # posting a second bubble.
        row.insights = block
        db_session.add(row)
        db_session.commit()
        return block
    except Exception as exc:
        logger.error("Sync insight stage failed for attachment %s: %s", row.id, exc, exc_info=True)
        try:
            db_session.rollback()
        except Exception:
            pass
        return None
