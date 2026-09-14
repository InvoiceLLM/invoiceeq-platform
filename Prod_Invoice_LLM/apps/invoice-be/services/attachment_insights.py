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
# Task 30.19 — the three-state check result
# ---------------------------------------------------------------------------
#
# THE DEFECT CLASS THIS EXISTS TO CLOSE (spec §11.2)
# -------------------------------------------------
# `InsightCard.status` describes the CARD. An individual comparison inside a card
# had no way to say "I could not evaluate this" — it just `continue`d, and the card
# still returned `ok`. So **"we compared nothing" and "everything matches" produced
# the same output**: Gap 517.1 (a delivery line whose description does not pair is
# skipped silently), Gap 515.2 (an unmatched bank row reported as a problem rather
# than as an unknown), Gap 510 (zero compliance rules run, reported as a plausible
# reason).
#
# Every check now returns one of three states. `NOT_CHECKED` is never rendered as
# clean, is counted separately from `FAIL`, and names what it could not evaluate.
#
# This is a TYPE, not a rule. It needs no edit when a new vendor, language, item
# description, bank or document type arrives — which is the test spec §11.2 sets
# for any fix in this layer.

CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_NOT_CHECKED = "not_checked"


@dataclass
class CheckLog:
    """The checks one card performed, each with its own outcome.

    A card builds this instead of counting `checked` by hand, so that the count
    it reports and the findings it emits cannot drift apart.
    """

    card: str
    passed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    not_checked: list = field(default_factory=list)

    def check_passed(self, subject: str) -> None:
        self.passed.append(str(subject))

    def check_failed(self, subject: str, finding_row: dict) -> None:
        self.failed.append(str(subject))
        self._findings.append(finding_row)

    def check_not_checked(self, subject: str, reason: str) -> None:
        """A comparison that could not be made. `reason` is shown to the user."""
        self.not_checked.append({"subject": str(subject), "reason": reason})

    def __post_init__(self) -> None:
        self._findings: list = []

    @property
    def findings(self) -> list:
        return list(self._findings)

    @property
    def evaluated(self) -> int:
        return len(self.passed) + len(self.failed)

    @property
    def total(self) -> int:
        return self.evaluated + len(self.not_checked)

    def title(self, noun: str) -> str:
        """"3 invoices checked, 2 not checked" — never "3 checked" when 2 were not.

        The second clause is the whole point: a title that omits it is the defect
        this task closes.
        """
        if not self.total:
            return f"No {noun} could be checked"
        text = f"{self.evaluated} {noun} checked"
        if self.not_checked:
            text += f", {len(self.not_checked)} not checked"
        return text

    def unchecked_detail(self) -> list:
        """The subjects that could not be evaluated, grouped by reason, for the
        bubble's "checks not run" section — so "2 delivered lines could not be
        paired with a billed line" names WHICH two."""
        by_reason: dict = {}
        for entry in self.not_checked:
            by_reason.setdefault(entry["reason"], []).append(entry["subject"])
        return [
            {"reason": reason, "subjects": subjects, "count": len(subjects)}
            for reason, subjects in by_reason.items()
        ]

    def as_card(
        self,
        noun: str,
        *,
        figures: dict | None = None,
        evidence: dict | None = None,
    ) -> InsightCard:
        """The card this log implies.

        `ok` even when nothing could be evaluated is deliberate: the card ran, and
        its honest result is "0 checked, N not checked". `skipped` means the card
        never got as far as checking anything, and that is the caller's decision,
        not this method's.
        """
        card_evidence = dict(evidence or {})
        if self.not_checked:
            card_evidence["not_checked"] = self.unchecked_detail()
        return InsightCard(
            card=self.card,
            status=STATUS_OK,
            title=self.title(noun),
            figures=figures or {},
            findings=self.findings,
            evidence=card_evidence,
        )


# ---------------------------------------------------------------------------
# Task 30.20 — cards emit claims, not prose
# ---------------------------------------------------------------------------
#
# THE DEFECT CLASS THIS EXISTS TO CLOSE (spec §11.3)
# -------------------------------------------------
# Every card wrote its own f-strings, so every formatting and wording bug was paid
# for once per card: raw floats in sentences while the figure column formatted
# correctly (Gap 509, and eight more instances the anti-hardcoding guard found on
# 2026-09-13), a correct computation described with the wrong words (Gap 511), and
# two cards asserting contradictory things in one bubble because neither could see
# the other's conclusion (Gap 512).
#
# A card now emits a structured claim and ONE renderer turns claims into sentences.
# `money_text()` is the only path from a number to user-facing text.
#
# NOTE ON §11.3's "do not add a fifth money()": the four helpers it names
# (`invoice_builder.money`, `query_agent._money`, `query_tools._money`,
# `document_comparison._money2`) all quantize a `Decimal` and NONE of them formats
# to text, so the number-to-text step did not exist. `money_text()` is that step and
# it delegates its quantization to `invoice_builder.money` rather than rounding
# again — no fifth quantizer is introduced. Recorded in spec §11.3.

#: ISO 4217 -> the symbol a reader expects. A currency that is not listed renders
#: as its own code ("SGD 1,200.00"), so a new currency needs no edit here.
CURRENCY_SYMBOLS = {
    "INR": "₹",
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "JPY": "¥",
}


def money_text(value: Any, currency: Any = None) -> str:
    """A figure as the user reads it: symbol, thousands separators, 2 dp.

    The ONLY number-to-text path in this layer. Gap 509 is what happens when a
    card interpolates the raw value instead.
    """
    from services.invoice_builder import money as _quantize

    amount = _dec(value)
    if amount is None:
        return "an unknown amount"
    amount = _quantize(amount)

    code = str(currency).strip().upper() if currency else ""
    symbol = CURRENCY_SYMBOLS.get(code, "")

    negative = amount < 0
    digits = f"{abs(amount):,.2f}"
    if symbol:
        rendered = f"{symbol}{digits}"
    elif code:
        rendered = f"{code} {digits}"
    else:
        rendered = digits
    return f"-{rendered}" if negative else rendered


def days_text(count: Any) -> str:
    """"1 day" / "5 days". A card must never build this by hand — that is how
    "0 days" and "1 days" reach a user."""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return "an unknown number of days"
    return "1 day" if abs(n) == 1 else f"{n} days"


def count_text(count: Any, singular: str, plural: str | None = None) -> str:
    """"1 invoice" / "3 invoices", so no card writes "invoice(s)"."""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return f"an unknown number of {plural or singular + 's'}"
    return f"{n} {singular}" if abs(n) == 1 else f"{n} {plural or singular + 's'}"


SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_BREACH = "breach"

#: How a card's own statement of seriousness orders findings. Gap 519: before this, the
#: presence of a currency amount was the primary sort key, so anything unquantifiable —
#: every compliance breach — sank below everything with a number on it.
SEVERITY_RANK = {SEVERITY_INFO: 1, SEVERITY_WARN: 2, SEVERITY_BREACH: 3}


@dataclass
class Claim:
    """What a card concluded, before anyone has chosen words for it.

    `kind` selects the sentence. `entity` is what the claim is ABOUT (an invoice
    number, a vendor, this document) and is what makes two claims comparable —
    which is how Gap 512's contradiction becomes detectable instead of being two
    unrelated strings.

    `asserts` is the L1 half: the facts this claim depends on being true, as
    `{fact_name: value}`. Two cards that assert different values for the same fact
    about the same entity contradict each other, and `verify_claims()` finds that
    without knowing anything about either card.
    """

    kind: str
    entity: str = ""
    figures: dict = field(default_factory=dict)
    subjects: list = field(default_factory=list)
    severity: str = SEVERITY_INFO
    currency: Optional[str] = None
    asserts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "entity": self.entity,
            "figures": jsonable(self.figures),
            "subjects": list(self.subjects),
            "severity": self.severity,
            "currency": self.currency,
            "asserts": jsonable(self.asserts),
        }


def verify_claims(block: dict) -> list:
    """L1 — is the CLAIM true, not merely are its FIGURES real?

    Feature 29's answer-contract gate checks that every number the model repeats
    already appears in the block. That is a real control and it is not this one: it
    cannot tell that two cards said incompatible things about the same order, or
    that a card asserted "nothing is linked" while another named the link. Gap 512
    and Gap 480 are both that hole (spec §11.7 step 4).

    The mechanism is generic. A claim declares the facts it depends on in
    `asserts`; two claims about the same entity that assert DIFFERENT values for the
    same fact are a contradiction. There is no table of incompatible card pairs to
    maintain — a new card participates the moment it declares a fact, and a new
    document type needs no edit here.

    Returns a list of contradiction records. The caller decides what to do with
    them; nothing here rewrites a card's own figures.
    """
    seen: dict = {}
    contradictions: list = []

    for row in block.get("findings") or []:
        claim = row.get("claim") or {}
        entity = claim.get("entity")
        if not entity:
            continue
        for fact, value in (claim.get("asserts") or {}).items():
            key = (str(entity), str(fact))
            previous = seen.get(key)
            if previous is None:
                seen[key] = (value, row.get("card"), row.get("finding_key"))
                continue
            if previous[0] != value:
                contradictions.append(
                    {
                        "entity": str(entity),
                        "fact": str(fact),
                        "left": {
                            "card": previous[1],
                            "finding_key": previous[2],
                            "value": previous[0],
                        },
                        "right": {
                            "card": row.get("card"),
                            "finding_key": row.get("finding_key"),
                            "value": value,
                        },
                    }
                )

    if contradictions:
        logger.warning(
            "insight block asserts contradictory facts: %s",
            "; ".join(f"{c['entity']}.{c['fact']}" for c in contradictions),
        )
    return contradictions


#: kind -> a function from a claim to its sentence. Adding a card means adding a
#: template here, not another f-string in the card body.
CLAIM_TEMPLATES: dict = {}


def claim_template(kind: str):
    """Register the sentence for one claim kind."""

    def register(fn):
        CLAIM_TEMPLATES[kind] = fn
        return fn

    return register


def render_claim(claim: Claim) -> str:
    """The one path from a claim to a user-facing sentence.

    An unregistered kind is a programming error, not a user-facing one: it renders
    as a plain, honest description rather than raising and taking the bubble down.
    """
    template = CLAIM_TEMPLATES.get(claim.kind)
    if template is None:
        logger.warning("no claim template registered for kind %r", claim.kind)
        return f"{claim.entity}: {claim.kind.replace('_', ' ')}".strip(": ")
    try:
        return template(claim)
    except Exception:  # pragma: no cover - defensive, same reason as the card wrapper
        logger.exception("claim template %r failed", claim.kind)
        return f"{claim.entity}: {claim.kind.replace('_', ' ')}".strip(": ")


def claim_finding(
    claim: Claim,
    key: str,
    *,
    card: str,
    impact_amount: float | None = None,
    confidence: str = "med",
    confidence_reason: str = "",
    evidence: dict | None = None,
) -> dict:
    """A finding whose title came from a claim, with the claim kept alongside it.

    The retained `claim` is what lets a later stage compare two cards' conclusions
    about the same entity; the rendered `title` is what the user reads.
    """
    row = finding(
        key,
        render_claim(claim),
        card=card,
        impact_amount=impact_amount,
        currency=claim.currency,
        confidence=confidence,
        confidence_reason=confidence_reason,
        evidence=evidence,
    )
    row["claim"] = claim.as_dict()
    return row


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

    figures: dict = {}
    log = CheckLog(card="agreed_vs_billed")
    label = _label(row.doc_type)

    for c in comparison.get("comparisons", []):
        number = c.get("invoice_number") or c.get("invoice_id")

        # Task 30.19: a pair we could not compare is NOT a pair that matched. A currency
        # mismatch used to be emitted as a finding, which read as a defect in the invoice;
        # it is an unknown, and the card now counts it as one.
        if c.get("outcome") == "currency_mismatch":
            log.check_not_checked(
                number,
                f"the invoice is in a different currency from this {label}, and this system "
                "holds no exchange rate",
            )
            continue

        overbilled = None
        for f_ in c.get("fields", []):
            if f_.get("field") != "grand_total" or f_.get("status") != "invoice_higher":
                continue
            delta = _dec(f_.get("delta"))
            if delta is None:
                continue
            overbilled = (delta, f_)
            break

        if overbilled is None:
            log.check_passed(number)
            continue

        delta, f_ = overbilled
        figures[f"overbilled_{number}"] = _f(delta)
        figures[f"agreed_{number}"] = _f(_dec(f_.get("reference_value")))
        figures[f"billed_{number}"] = _f(_dec(f_.get("invoice_value")))
        log.check_failed(
            number,
            claim_finding(
                Claim(
                    kind="billed_over_agreed",
                    entity=str(number),
                    figures={"excess": delta},
                    subjects=[label],
                    severity=SEVERITY_BREACH,
                    currency=row.currency,
                    # Gap 512: this card and `card_open_po_value` answer the same question
                    # from different sources. Declaring the fact lets L1 catch any future
                    # disagreement instead of shipping both statements to the user.
                    asserts={"has_linked_invoices": True},
                ),
                f"agreed_vs_billed:{number}",
                card="agreed_vs_billed",
                impact_amount=_f(delta),
                confidence=confidence,
                confidence_reason=why,
                evidence={
                    "invoice_number": number,
                    "agreed": f_.get("reference_value"),
                    "billed": f_.get("invoice_value"),
                    "difference": f_.get("delta"),
                },
            ),
        )

    card = log.as_card("invoices", figures=figures, evidence={"comparison": comparison})
    card.title += f" against this {label}"
    return card


@claim_template("billed_over_agreed")
def _render_billed_over_agreed(claim: Claim) -> str:
    excess_text = money_text(claim.figures.get("excess"), claim.currency)
    against_text = claim.subjects[0] if claim.subjects else "document"
    return f"{claim.entity} bills {excess_text} more than this {against_text} agreed"


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
    log = CheckLog(card="terms_check")

    for inv in invoices:
        # Task 30.19: an invoice we cannot measure is NOT a passing check. Before this,
        # it was `continue` and the card still reported "checked on N invoice(s)".
        if not (inv.invoice_date and inv.due_date):
            log.check_not_checked(
                inv.invoice_number,
                "the invoice carries no invoice date and due date to measure a payment "
                "window from",
            )
            continue

        granted = (inv.due_date - inv.invoice_date).days
        figures[f"payment_days_{inv.invoice_number}"] = float(granted)
        if granted == agreed_days:
            log.check_passed(inv.invoice_number)
            continue

        log.check_failed(
            inv.invoice_number,
            claim_finding(
                # Gap 511: `granted` is the window the invoice ITSELF grants
                # (due date minus invoice date), not days remaining from today. The
                # old sentence said "is due in 26 days" for an invoice due in 6.
                Claim(
                    kind="terms_deviation",
                    entity=inv.invoice_number,
                    figures={"granted_days": granted, "agreed_days": agreed_days},
                    subjects=[_label(row.doc_type)],
                    severity=SEVERITY_WARN,
                ),
                f"terms_check:{inv.invoice_number}",
                card="terms_check",
                confidence=confidence,
                confidence_reason=why,
                evidence={
                    "invoice_number": inv.invoice_number,
                    "agreed_days": agreed_days,
                    "invoice_days": granted,
                    "payment_terms_text": data.get("payment_terms"),
                    "doc_type_label": _label(row.doc_type),
                },
            ),
        )

    if not log.total:
        return InsightCard(
            card="terms_check",
            status=STATUS_SKIPPED,
            reason="the linked invoices have no invoice date and due date to measure",
        )
    return log.as_card("invoices", figures=figures)


@claim_template("terms_deviation")
def _render_terms_deviation(claim: Claim) -> str:
    granted = claim.figures.get("granted_days")
    agreed = claim.figures.get("agreed_days")
    source_text = claim.subjects[0] if claim.subjects else "this document"
    return (
        f"{claim.entity} allows {days_text(granted)} to pay; "
        f"this {source_text} agrees {days_text(agreed)}"
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
            claim_finding(
                Claim(kind="net_payable_after_document", entity=str(row.doc_number or "this document"),
                      figures={"net": net}, subjects=[_label(row.doc_type)],
                      severity=SEVERITY_INFO, currency=owed.get("currency") or row.currency),
                f"net_position:{row.doc_number or row.id}",
                card="net_position",
                impact_amount=_f(_dec(row.grand_total)),
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
    figures: dict = {}
    log = CheckLog(card="delivery_vs_order")

    # Billed quantity per (invoice, normalised description). Gap 517.2: the figure keys used
    # to be `delivered_<desc>` with no invoice in them, so two linked invoices billing the
    # same item overwrote each other's figures inside one bubble.
    billed_by_invoice: dict = {}
    for inv in invoices:
        for item in inv.items or []:
            if not isinstance(item, dict):
                continue
            key = _norm_desc(item.get("description"))
            qty = _dec(item.get("quantity"))
            if key and qty is not None:
                bucket = billed_by_invoice.setdefault(inv.invoice_number, {})
                bucket[key] = bucket.get(key, Decimal("0")) + qty

    for item in delivered:
        key = _norm_desc(item.get("description"))
        got = _dec(item.get("quantity"))
        label = str(item.get("description") or "unnamed line")
        if not key or got is None:
            log.check_not_checked(label, "the delivered line has no readable description")
            continue

        pairs = [(num, b[key]) for num, b in billed_by_invoice.items() if key in b]
        # Gap 517.1 / task 30.19: a delivered line that pairs with NO billed line was silently
        # `continue`d and the card still said "N delivered line(s) checked". It is an unknown,
        # named to the user; no synonym table or fuzzy threshold is added (spec §11.2 ruling).
        if not pairs:
            log.check_not_checked(label, "no billed line on the linked invoices pairs with this description")
            continue

        for number, billed_qty in pairs:
            subject = f"{label} on {number}"
            figures[f"delivered_{number}_{key[:32]}"] = _f(got)
            figures[f"billed_qty_{number}_{key[:32]}"] = _f(billed_qty)
            diff = billed_qty - got
            if diff == 0:
                log.check_passed(subject)
                continue
            log.check_failed(
                subject,
                claim_finding(
                    Claim(
                        kind="delivery_quantity_mismatch",
                        entity=str(number),
                        figures={"billed": billed_qty, "delivered": got},
                        subjects=[label],
                        severity=SEVERITY_WARN,
                    ),
                    f"delivery_vs_order:{number}:{key[:64]}",
                    card="delivery_vs_order",
                    confidence=confidence,
                    confidence_reason=why,
                    evidence={
                        "invoice_number": number,
                        "description": label,
                        "delivered_quantity": str(got),
                        "billed_quantity": str(billed_qty),
                        "direction": "short_delivery" if diff > 0 else "excess_delivery",
                    },
                ),
            )

    card = log.as_card("delivered lines", figures=figures)
    card.title += " against the linked invoices"
    return card


@claim_template("delivery_quantity_mismatch")
def _render_delivery_quantity_mismatch(claim: Claim) -> str:
    what_text = claim.subjects[0] if claim.subjects else "this line"
    billed_text = _qty_text(claim.figures.get("billed"))
    delivered_text = _qty_text(claim.figures.get("delivered"))
    return f"{claim.entity} bills {billed_text} of '{what_text}' but {delivered_text} was delivered"


def _qty_text(value: Any) -> str:
    """A quantity as printed: no trailing .00 on whole units, 2 dp otherwise."""
    q = _dec(value)
    if q is None:
        return "an unknown quantity"
    return str(int(q)) if q == q.to_integral_value() else f"{q.quantize(Decimal('0.01'))}"



def card_payment_application(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """Gap 518 — which invoice does this remittance / payment advice settle, and how much?

    The document prints its own answer: `referenced_documents` (number + amount) and a UTR.
    Before this card, nothing read them; `card_net_position` fed only `row.grand_total`
    into a VENDOR-level net and the bubble answered a question the document did not ask.

    Each printed reference is resolved EXACTLY against this tenant's invoices (the Gap 490
    resolver's lookup). Unresolved = NOT_CHECKED, named — never a guess, never a fuzzy match.
    """
    from agents.entity_resolver import _exact_invoice_lookup

    data = row.extracted_json or {}
    refs = [r for r in (data.get("referenced_documents") or []) if isinstance(r, dict) and r.get("doc_number")]
    if not refs:
        return InsightCard(
            card="payment_application",
            status=STATUS_SKIPPED,
            reason="this advice prints no invoice references we can read",
        )

    found = _exact_invoice_lookup([str(r["doc_number"]) for r in refs], row.tenant_id, db_session)
    by_number = {str(inv.invoice_number).strip().lower(): inv for inv in _tenant_invoices(row, db_session)}
    log = CheckLog(card="payment_application")
    figures: dict = {"referenced_count": float(len(refs)), "advice_total": _f(_dec(row.grand_total))}
    utr = data.get("utr_ref") or data.get("payment_reference")

    for ref in refs:
        number = str(ref["doc_number"]).strip()
        key = number.lower()
        inv = by_number.get(key) if key in found else None
        if inv is None:
            log.check_not_checked(number, "no invoice on file carries this reference number")
            continue
        paid = _dec(ref.get("amount"))
        due = _dec(inv.grand_total)
        if paid is None or due is None:
            log.check_not_checked(number, "the advice or the invoice prints no amount to compare")
            continue
        figures[f"paid_{number}"] = _f(paid)
        figures[f"invoice_total_{number}"] = _f(due)
        shortfall = due - paid
        evidence = {"invoice_number": number, "paid": str(paid), "invoice_total": str(due), "utr_ref": utr}
        if shortfall == 0:
            log.check_passed(number)
            # A full settlement is worth saying out loud — it is the answer the document asks for.
            log._findings.append(
                claim_finding(
                    Claim(kind="payment_settles_in_full", entity=number, figures={"paid": paid},
                          severity=SEVERITY_INFO, currency=row.currency,
                          asserts={"settled_in_full": True}),
                    f"payment_application:{number}", card="payment_application",
                    impact_amount=_f(paid), confidence="high",
                    confidence_reason="the advice names this invoice and the amounts agree",
                    evidence=evidence,
                )
            )
            continue
        log.check_failed(
            number,
            claim_finding(
                Claim(kind="payment_partial_or_over", entity=number,
                      figures={"paid": paid, "invoice_total": due, "difference": abs(shortfall)},
                      subjects=["short" if shortfall > 0 else "over"],
                      severity=SEVERITY_WARN, currency=row.currency,
                      asserts={"settled_in_full": False}),
                f"payment_application:{number}", card="payment_application",
                impact_amount=_f(abs(shortfall)), confidence="high",
                confidence_reason="the advice names this invoice and the amounts differ",
                evidence=evidence,
            ),
        )

    return log.as_card("referenced invoices", figures=figures)


@claim_template("payment_settles_in_full")
def _render_payment_settles_in_full(claim: Claim) -> str:
    paid_text = money_text(claim.figures.get("paid"), claim.currency)
    return f"this payment settles {claim.entity} in full ({paid_text})"


@claim_template("payment_partial_or_over")
def _render_payment_partial_or_over(claim: Claim) -> str:
    paid_text = money_text(claim.figures.get("paid"), claim.currency)
    total_text = money_text(claim.figures.get("invoice_total"), claim.currency)
    diff_text = money_text(claim.figures.get("difference"), claim.currency)
    direction = claim.subjects[0] if claim.subjects else "short"
    if direction == "short":
        return f"this payment of {paid_text} against {claim.entity} ({total_text}) leaves {diff_text} still owed"
    return f"this payment of {paid_text} against {claim.entity} ({total_text}) exceeds the invoice by {diff_text}"


def card_linked_duplicates(row: Any, db_session: Any, ctx: dict) -> InsightCard:
    """Gap 517.3 — two linked invoices that look like the same bill (challan / GRN types).

    Same supplier, same total, same date, DIFFERENT number: the Layer 3 near-duplicate
    rule (Gap 503) applied to the invoices this document links to. Deterministic; an
    invoice missing a date or total is NOT_CHECKED rather than silently excluded.
    """
    invoices = ctx.get("invoices") or []
    if len(invoices) < 2:
        return InsightCard(card="linked_duplicates", status=STATUS_SKIPPED,
                           reason="fewer than two invoices are linked, so there is nothing to compare")
    log = CheckLog(card="linked_duplicates")
    groups: dict = {}
    for inv in invoices:
        total = _dec(inv.grand_total)
        if total is None or not inv.invoice_date:
            log.check_not_checked(inv.invoice_number, "the invoice has no total and date to compare on")
            continue
        key = (_norm_desc(inv.vendor_name), str(inv.invoice_date), str(total))
        groups.setdefault(key, []).append(inv)
    figures: dict = {}
    for key, members in groups.items():
        numbers = sorted({str(m.invoice_number) for m in members})
        if len(numbers) < 2:
            for m in members:
                log.check_passed(m.invoice_number)
            continue
        total = _dec(members[0].grand_total)
        figures["duplicate_total_" + "_".join(numbers)[:40]] = _f(total)
        log.check_failed(
            " / ".join(numbers),
            claim_finding(
                Claim(kind="linked_possible_duplicate", entity=" and ".join(numbers),
                      figures={"total": total}, subjects=[str(members[0].invoice_date)],
                      severity=SEVERITY_BREACH, currency=members[0].currency or row.currency),
                "linked_duplicates:" + "|".join(numbers), card="linked_duplicates",
                impact_amount=_f(total), confidence="med",
                confidence_reason="same supplier, date and total; only the number differs",
                evidence={"invoice_numbers": numbers, "date": key[1], "total": key[2]},
            ),
        )
    return log.as_card("linked invoices", figures=figures)


@claim_template("linked_possible_duplicate")
def _render_linked_possible_duplicate(claim: Claim) -> str:
    total_text = money_text(claim.figures.get("total"), claim.currency)
    when_text = claim.subjects[0] if claim.subjects else "the same date"
    return f"{claim.entity} look like one bill entered twice: {total_text} on {when_text}"



# --- templates for the six async / net cards migrated 2026-09-14 ---------------------


@claim_template("net_payable_after_document")
def _render_net_payable_after_document(claim: Claim) -> str:
    net_text = money_text(claim.figures.get("net"), claim.currency)
    doc_text = claim.subjects[0] if claim.subjects else "document"
    return f"After this {doc_text}, {net_text} is payable"


@claim_template("overdue_with_party")
def _render_overdue_with_party(claim: Claim) -> str:
    total_text = money_text(claim.figures.get("overdue_total"), claim.currency)
    bills_text = count_text(claim.figures.get("bill_count"), "bill")
    oldest_text = claim.subjects[0] if claim.subjects else "the oldest"
    age_text = days_text(claim.figures.get("oldest_days"))
    return (f"{total_text} is already overdue with {claim.entity} across {bills_text}; "
            f"the oldest is {oldest_text} at {age_text}")


@claim_template("orders_invoiced_more_than_once")
def _render_orders_invoiced_more_than_once(claim: Claim) -> str:
    multi_text = str(int(claim.figures.get("multi") or 0))
    orders_text = count_text(claim.figures.get("orders"), "order")
    return f"{multi_text} of {orders_text} from {claim.entity} were invoiced more than once"


@claim_template("invoices_drift_from_quote")
def _render_invoices_drift_from_quote(claim: Claim) -> str:
    avg_text = money_text(claim.figures.get("average"), claim.currency)
    quoted_text = money_text(claim.figures.get("quoted"), claim.currency)
    return f"invoices from {claim.entity} since this quote average {avg_text} against a quoted {quoted_text}"


@claim_template("repeat_short_delivery")
def _render_repeat_short_delivery(claim: Claim) -> str:
    lines_text = count_text(claim.figures.get("short_lines"), "short-delivered line")
    notes_text = count_text(claim.figures.get("notes"), "delivery note")
    return f"{lines_text} across {notes_text} from {claim.entity}"


@claim_template("contract_term_deviations")
def _render_contract_term_deviations(claim: Claim) -> str:
    dev_text = str(int(claim.figures.get("deviating") or 0))
    inv_text = count_text(claim.figures.get("invoices"), "invoice")
    window_text = days_text(claim.figures.get("agreed_days"))
    return f"{dev_text} of {inv_text} from {claim.entity} do not use the contract's {window_text} payment window"


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

    # Gaps 515.1 / 515.2, task 30.19. `match_statement_lines()` returns FIVE buckets and
    # this card used to render three, so unmatched CREDITS were computed, counted and never
    # spoken. Worse, an unmatched DEBIT was rendered as a finding — "money left with no
    # invoice on file" — which made every ordinary business payment (salary, a tax
    # remittance, a utility bill) read as a problem.
    #
    # The honest split: a row we could not match is an UNKNOWN, not a defect. Only a payment
    # against an already-settled bill is a finding. This is the three-state result doing the
    # work, and it needs no list of ignorable narrations — the fix §11.2 explicitly rejected.
    log = CheckLog(card="bank_reconcile")

    for _ in result["matched"]:
        log.check_passed("matched transaction")

    for entry in result["possible_duplicates"]:
        log.check_failed(
            entry["line_id"],
            claim_finding(
                Claim(
                    kind="bank_duplicate_payment",
                    entity=entry.get("invoice_number") or "a bill",
                    figures={"amount": entry["amount"]},
                    subjects=[str(entry["line_date"])],
                    severity=SEVERITY_BREACH,
                    currency=row.currency,
                ),
                f"bank_reconcile:duplicate:{entry['line_id']}",
                card="bank_reconcile",
                impact_amount=entry["amount"],
                confidence="med",
                confidence_reason=entry.get("reason", "matched a bill that is already settled"),
                evidence=entry,
            ),
        )

    tolerance_text = (
        f"within {money_text(result['tolerances']['amount'], row.currency)} and "
        f"{days_text(result['tolerances']['days'])}"
    )

    for entry in result["unmatched_debits"]:
        figures[f"unmatched_debit_{entry['line_id'][:8]}"] = entry["amount"]
        log.check_not_checked(
            _bank_line_subject(entry, row.currency),
            f"no invoice on file matches this payment {tolerance_text} with the same supplier",
        )

    # Gap 515.1: the bucket the spec's own 30.5 verification asked for and the card never
    # rendered. A receipt with no outbound invoice behind it is unknown, not wrong.
    for entry in result["unmatched_credits"]:
        figures[f"unmatched_credit_{entry['line_id'][:8]}"] = entry["amount"]
        log.check_not_checked(
            _bank_line_subject(entry, row.currency),
            f"no outbound invoice matches this receipt {tolerance_text} with the same customer",
        )

    for entry in result["ambiguous"]:
        log.check_not_checked(
            _bank_line_subject(entry, row.currency),
            count_text(len(entry.get("candidates", [])), "invoice")
            + " fit this row equally on amount, date and supplier",
        )

    card = log.as_card(
        "transactions",
        figures=figures,
        evidence={
            "tolerances": result["tolerances"],
            "matched": result["matched"][:20],
            "closing_balance": balance,
            "statement_date": row.statement_date.isoformat() if row.statement_date else None,
        },
    )
    if row.statement_date:
        card.title += f", as of {row.statement_date.isoformat()}"
    return card


def _bank_line_subject(entry: dict, currency: Any) -> str:
    """One statement row, named the way a reader recognises it."""
    narration = (entry.get("narration") or "").strip()
    text = f"{money_text(entry.get('amount'), currency)} on {entry.get('line_date')}"
    return f"{text} ({narration})" if narration else text


# NAMING CONVENTION inside claim templates: a local holding ALREADY-RENDERED text ends in
# `_text`. It reads honestly at the point of use ("this is a string, not a number") and it is
# what both anti-hardcoding guards look for when deciding whether a figure reached a sentence
# unformatted. A raw number bound to a `_text` name would be a deliberate lie, not an oversight.


@claim_template("bank_duplicate_payment")
def _render_bank_duplicate_payment(claim: Claim) -> str:
    when_text = claim.subjects[0] if claim.subjects else "an unknown date"
    paid_text = money_text(claim.figures.get("amount"), claim.currency)
    return f"{paid_text} paid on {when_text} looks like {claim.entity} being paid twice"


@claim_template("cash_shortfall")
def _render_cash_shortfall(claim: Claim) -> str:
    short_text = money_text(claim.figures.get("shortfall"), claim.currency)
    balance_text = money_text(claim.figures.get("closing_balance"), claim.currency)
    horizon_text = days_text(claim.figures.get("horizon_days"))
    return (
        f"{short_text} more is due in the next {horizon_text} than the "
        f"{balance_text} on this statement"
    )


@claim_template("order_not_fully_invoiced")
def _render_order_not_fully_invoiced(claim: Claim) -> str:
    remaining_text = money_text(claim.figures.get("remaining"), claim.currency)
    return f"{remaining_text} of this order has not been invoiced yet"


@claim_template("order_over_invoiced")
def _render_order_over_invoiced(claim: Claim) -> str:
    excess_text = money_text(claim.figures.get("excess"), claim.currency)
    return f"{excess_text} more has been invoiced than this order authorised"


@claim_template("expected_outflow")
def _render_expected_outflow(claim: Claim) -> str:
    total_text = money_text(claim.figures.get("total"), claim.currency)
    when_text = claim.subjects[0] if claim.subjects else "an unknown date"
    return f"{total_text} is likely to be payable around {when_text}"


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
            claim_finding(
                Claim(
                    kind="cash_shortfall",
                    entity="this statement",
                    figures={
                        "shortfall": shortfall,
                        "closing_balance": figures["closing_balance"],
                        "horizon_days": 30,
                    },
                    severity=SEVERITY_WARN,
                    currency=row.currency,
                ),
                f"cash_cover:{row.id}",
                card="cash_cover",
                impact_amount=shortfall,
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
            claim_finding(
                Claim(kind="overdue_with_party", entity=str(row.party_name),
                      figures={"overdue_total": overdue_total, "bill_count": len(overdue),
                               "oldest_days": oldest["days_overdue"]},
                      subjects=[str(oldest["invoice_number"])],
                      severity=SEVERITY_WARN, currency=row.currency),
                f"cash_impact:overdue:{row.party_name}",
                card="cash_impact",
                impact_amount=_f(overdue_total),
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

    # Gap 512: this card used to say "no invoice has been recorded against this order number
    # yet" whenever `v_3way_match` returned nothing, while `card_agreed_vs_billed` — reading
    # `ctx["invoices"]`, a DIFFERENT source of truth for the same question — named a probable
    # match in the same bubble. Both statements were internally true and together they read
    # as a contradiction.
    #
    # The fix is one fact, declared once and asserted by both cards, so L1 can see any future
    # disagreement rather than the user finding it.
    linked = ctx.get("invoices") or []
    has_linked = bool(rows) or bool(linked)
    if rows:
        link_reason = "from the invoices recorded against this order number"
    elif linked:
        link_reason = (
            "no invoice carries this order number, but "
            + count_text(len(linked), "invoice")
            + " is linked to this document by supplier, amount and date"
        )
    else:
        link_reason = "no invoice has been recorded against this order number yet"

    figures = {
        "ordered_value": _f(ordered),
        "invoiced_against_order": _f(invoiced),
        "not_yet_invoiced": _f(remaining),
    }
    findings = []
    if remaining > 0:
        findings.append(
            claim_finding(
                Claim(
                    kind="order_not_fully_invoiced",
                    entity=str(po_number),
                    figures={"remaining": remaining, "ordered": ordered, "invoiced": invoiced},
                    severity=SEVERITY_INFO,
                    currency=row.currency,
                    asserts={"has_linked_invoices": has_linked},
                ),
                f"open_po_value:{po_number}",
                card="open_po_value",
                impact_amount=_f(remaining),
                confidence="high" if rows else "med",
                confidence_reason=link_reason,
                evidence={"po_number": str(po_number), "matched": rows[:5]},
            )
        )
    elif remaining < 0:
        findings.append(
            claim_finding(
                Claim(
                    kind="order_over_invoiced",
                    entity=str(po_number),
                    figures={"excess": abs(remaining), "ordered": ordered, "invoiced": invoiced},
                    severity=SEVERITY_BREACH,
                    currency=row.currency,
                    asserts={"has_linked_invoices": has_linked},
                ),
                f"open_po_value:over:{po_number}",
                card="open_po_value",
                impact_amount=_f(abs(remaining)),
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
            claim_finding(
                Claim(
                    kind="expected_outflow",
                    entity=str(row.doc_number or "this document"),
                    figures={"total": total},
                    subjects=[expected.isoformat()],
                    severity=SEVERITY_INFO,
                    currency=row.currency,
                ),
                f"cash_out_timing:{row.doc_number or row.id}",
                card="cash_out_timing",
                impact_amount=_f(total),
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
            claim_finding(
                Claim(kind="orders_invoiced_more_than_once", entity=str(row.party_name),
                      figures={"multi": len(multi), "orders": len(pairs)},
                      severity=SEVERITY_WARN, currency=row.currency),
                f"over_invoicing_history:{row.party_name}",
                card="over_invoicing_history",
                impact_amount=_f(
                    sum((_dec(p["invoiced_amount"]) or Decimal("0")) for p in multi)
                ),
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
            claim_finding(
                Claim(kind="invoices_drift_from_quote", entity=str(row.party_name),
                      figures={"average": average, "quoted": quoted, "drift": drift},
                      severity=SEVERITY_WARN, currency=row.currency),
                f"quote_drift:{row.doc_number or row.id}",
                card="quote_drift",
                impact_amount=_f(drift),
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
            claim_finding(
                Claim(kind="repeat_short_delivery", entity=str(row.party_name),
                      figures={"short_lines": len(shortfalls), "notes": len(theirs)},
                      severity=SEVERITY_WARN),
                f"repeat_short_delivery:{row.party_name}",
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
            claim_finding(
                Claim(kind="contract_term_deviations", entity=str(row.party_name),
                      figures={"deviating": len(deviations), "invoices": len(rows), "agreed_days": agreed_days},
                      severity=SEVERITY_WARN),
                f"contract_deviations:{row.doc_number or row.id}",
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

    from services.rule_cards import load_rule_cards, run_compliance_checks

    results = run_compliance_checks(row, region)

    # Task 30.9 x task 30.19. `run_compliance_checks()` only ever sees VERIFIED cards --
    # correct, a rule nobody sourced must never be shown as a rule. But before this, an
    # unverified card simply vanished, and a region whose cards are ALL unverified (IN, as of
    # 2026-09-14: every CBIC / GSTN primary source probed is a JS shell, a 404, an
    # ECONNRESET or a TLS failure) produced "no IN rule card applies" -- which is false.
    # Three exist. They are now surfaced as NOT_CHECKED, naming the rule and why it could
    # not run, so the reader knows a check is missing rather than believing it passed.
    doc_type = str(row.doc_type or "").strip().upper()
    unverified = [
        c for c in load_rule_cards(region=region, include_unverified=True)
        if not getattr(c, "is_showable", False)
        and (not getattr(c, "applies_to_doc_types", None) or doc_type in [str(d).upper() for d in c.applies_to_doc_types])
    ]

    if not results and not unverified:
        return InsightCard(
            card="compliance",
            status=STATUS_SKIPPED,
            reason=f"no {region} rule card applies to a {_label(row.doc_type)} yet",
        )

    log = CheckLog(card="compliance")
    entity = str(getattr(row, "doc_number", None) or "this document")
    for result in results:
        outcome = result.get("outcome")
        if outcome == "pass":
            log.check_passed(result["title"])
        elif outcome == "fail":
            log.check_failed(
                result["title"],
                claim_finding(
                    Claim(
                        kind="compliance_rule_failed",
                        entity=entity,
                        subjects=[result["title"], result.get("detail") or "", result.get("source_title") or "the published rule"],
                        severity=SEVERITY_BREACH,
                    ),
                    f"compliance:{result['card_id']}",
                    card="compliance",
                    confidence="high",
                    confidence_reason=f"checked against {result.get('source_title') or 'the published rule'}",
                    evidence=result,
                ),
            )
        elif outcome == "not_applicable":
            continue
        else:  # informational -- guidance, not a check; recorded, never counted as passed
            continue

    for card in unverified:
        log.check_not_checked(
            card.title,
            f"rule text not yet sourced from {card.source_title or card.source_url or 'its primary source'} "
            "-- the official page could not be retrieved, so this check did not run",
        )

    result_card = log.as_card(f"{region} rules", evidence={"region": region, "checks": results,
                                                            "unverified_card_ids": [c.id for c in unverified]})
    return result_card


@claim_template("compliance_rule_failed")
def _render_compliance_rule_failed(claim: Claim) -> str:
    title_text = claim.subjects[0] if claim.subjects else "a compliance rule"
    detail_text = claim.subjects[1] if len(claim.subjects) > 1 and claim.subjects[1] else ""
    return f"{title_text} -- {detail_text}" if detail_text else title_text


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
        card_what_this_is, card_delivery_vs_order, card_linked_duplicates, card_partial_delivery_balance,
        card_repeat_short_delivery, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "GRN": (
        card_what_this_is, card_delivery_vs_order, card_linked_duplicates, card_partial_delivery_balance,
        card_repeat_short_delivery, card_compliance, card_suggested_questions, card_confidence_gaps,
    ),
    "CREDIT_NOTE": (card_what_this_is, card_net_position, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps),
    "DEBIT_NOTE": (card_what_this_is, card_net_position, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps),
    "REMITTANCE_ADVICE": (card_what_this_is, card_payment_application, card_net_position, card_cash_impact, card_compliance, card_suggested_questions, card_confidence_gaps),  # Gap 518
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
        # Task 30.19: a card that never ran AND, now, the individual checks inside a card
        # that ran but could not be evaluated. Before this, only the first kind reached the
        # user, so "we compared nothing" inside an `ok` card was invisible — the card said
        # "3 checked" and the two it could not pair were never mentioned.
        "checks_not_run": [
            {"card": c.card, "reason": c.reason}
            for c in cards
            if c.status in (STATUS_SKIPPED, STATUS_BLOCKED)
        ]
        + [
            {
                "card": c.card,
                "reason": entry["reason"],
                "subjects": entry["subjects"],
                "count": entry["count"],
            }
            for c in cards
            for entry in (c.evidence.get("not_checked") or [])
        ],
        "actions": list(BUBBLE_ACTIONS),
        "verdict": "",
        "verdict_source": "template",
        "generated_at": datetime.utcnow().isoformat(),
    }
    block["findings"] = rank_findings(block)
    # L1 (spec §11.7 step 4): the answer-contract gate proves a figure is real, never that
    # the claim about it is true. This is the other half — two cards that assert different
    # values for the same fact about the same entity are recorded here rather than both
    # being shown as confident statements (Gap 512).
    block["contradictions"] = verify_claims(block)
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
        # Gap 519: the old primary key was `1 if amount else 0`, so EVERY finding without a
        # currency impact sorted below EVERY finding with one. Only the top 3 reach the
        # narrator, so a compliance breach — which never carries an amount — could not be
        # spoken at all, no matter how serious.
        #
        # Severity now leads. It comes from the claim (30.20), so a card states how bad a
        # thing is rather than relying on the size of a number to imply it, and an
        # unquantifiable breach can outrank a large but routine figure. Money still orders
        # findings of equal severity.
        severity = (f_.get("claim") or {}).get("severity", SEVERITY_INFO)
        return (
            SEVERITY_RANK.get(severity, SEVERITY_RANK[SEVERITY_INFO]),
            abs(float(amount or 0.0)) * weight,
        )

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
    "EVERY FIGURE HAS ALREADY BEEN COMPUTED AND ALREADY SPELLED OUT for you in "
    "the JSON below: `figures_text` and each finding's `impact_text` are the ONLY "
    "forms of a number you may use. Copy that spelling character for character -- "
    "currency symbol, thousands separators, 'days', 'invoices' -- and never write a "
    "bare number of your own. You must not compute, sum, convert, estimate or round "
    "anything. If a figure you want is not in the JSON, do not state it.\n\n"
    "Write ONE sentence, plain words, no jargon: say 'overbilled', 'short "
    "delivered', 'paid twice?', never 'variance', 'delta', '3-way match' or "
    "'tier'. Name the supplier and the action if there is one. Do not add "
    "advice that is not supported by the findings."
)


def figure_text(key: str, value: Any, currency: Any) -> str:
    """One block figure as the narration model is allowed to see it.

    The KEY decides the shape, not the value: `*days*` is a duration, `*count*` /
    `*_lines*` / `*_pairs*` is a count, everything else is money in the document's
    currency. A non-numeric value is passed through as text. This is the same rule
    the cards' own templates follow, applied once at the model boundary.
    """
    k = str(key).lower()
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return str(value)
    if "days" in k:
        return days_text(value)
    if "count" in k or k.endswith("_lines") or k.endswith("_pairs") or k.endswith("_orders") or k.endswith("_notes"):
        try:
            return str(int(Decimal(str(value))))
        except (InvalidOperation, ValueError):
            return str(value)
    return money_text(value, currency)


def narration_payload(block: dict) -> dict:
    """What the narration model is shown. Gap 522: NO raw number reaches this payload.

    Before this, `figures` were the `_f()` floats the block carries for arithmetic
    (`23200.0`, `45.0`) and the model, correctly refusing to invent, copied them
    verbatim into 17 of 20 verdicts. Task 30.20 gave the cards one number-to-text
    path; this is the same path applied at the model boundary, so the model can only
    ever repeat a spelling that `money_text()` / `days_text()` produced.
    """
    currency = block.get("currency")
    figures = block.get("figures") or {}
    return {
        "document": {
            "type": block.get("doc_type_label"),
            "currency": currency,
        },
        "findings": [
            {
                "title": f_.get("title"),
                "impact_text": (
                    money_text(f_.get("impact_amount"), f_.get("currency") or currency)
                    if f_.get("impact_amount") is not None else None
                ),
                "confidence": f_.get("confidence"),
            }
            for f_ in (block.get("findings") or [])[:3]
        ],
        "figures_text": {str(k): figure_text(k, v, currency) for k, v in figures.items()},
        "checks_not_run": block.get("checks_not_run") or [],
    }


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

    payload = narration_payload(block)
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

        allowed = _gate_evidence_numbers(
            json.dumps(payload, default=str),
            json.dumps(block.get("figures") or {}, default=str),
            json.dumps([f_.get("impact_amount") for f_ in (block.get("findings") or [])], default=str),
        )
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
            # FE Gap 472 (BE half): the bubble's note / dismiss actions are keyed by the
            # `insight` row id, and the finding the browser renders never carried it -- so
            # the FE issued a second read and joined on finding_key + card. The id is
            # written back onto the finding here, and both stages now open rows BEFORE
            # `post_insight_turn()` persists the block, so the payload carries it.
            opened = open_insight(
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
            if getattr(opened, "id", None) is not None:
                f_["insight_id"] = str(opened.id)
            out.append(opened)
        except Exception as exc:
            logger.error("Could not open finding %s on %s: %s", f_.get("finding_key"), row.id, exc)
    return out


def run_sync_insights(row: Any, db_session: Any, ocr_text: Optional[str] = None) -> Optional[dict]:
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

        set_attachment_region(row, db_session, ocr_text)  # BE Gap 510
        block = build_insight_block(row, db_session, row.tenant_id, stage="sync")
        open_insights_from_block(row, block, db_session)  # FE Gap 472: ids before the payload is written
        message = post_insight_turn(row, block, db_session)
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
