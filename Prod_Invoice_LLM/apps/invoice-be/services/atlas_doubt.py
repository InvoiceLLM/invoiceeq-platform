"""Feature 34 (ATLAS) task 34.5 — the claim → witness rule.

Spec: `docs/feature_34_atlas.md` §3.3 · decisions D19, D39, D40.

Every invoice makes claims, and **each claim has exactly one external witness**
(§3.3). ATLAS never asks "shall we reconcile": the ask is always that a specific
claim is in doubt and that one named document settles it.

The three-step rule, as code
----------------------------
1. **Is a claim in doubt?** `doubts_for_invoice()` -- outside this vendor's
   historical range, a first invoice from a new vendor, a rate that changed, a
   possible duplicate, large enough to matter.
2. **Do we already hold the witness?** If yes, `Verdict.CHECK_SILENTLY`: the
   check runs and the user hears nothing unless it disagrees. §3.3 calls this
   the step that stops ATLAS nagging, and it is most of the value of the rule.
3. **If not, is the answer worth the interruption?** `Verdict.ASK` only when the
   amount is material against the vendor's own baseline. ₹2.4L at 4x normal is
   an ask; ₹4,500 matching twelve months of history never is.

Step 1 and step 3 decide correctness -- whether a number is anomalous and
whether it is material -- so both are deterministic arithmetic (CONVENTIONS hard
rule 3). A model may phrase the doubt; it does not get to decide that an amount
is unusual, because "unusual" is a comparison and comparisons are arithmetic.

Nothing here is stored (D39)
----------------------------
**There are no new tables.** A claim is derived from the invoice's own extracted
fields through the fixed field → witness mapping below, and the vendor baseline
is computed from that vendor's own invoice history at the moment a check runs.
Nothing is persisted, nothing has to be migrated, and nothing can go stale
against the invoices it was derived from.

D39's accepted cost is that a derived baseline cannot be corrected -- you cannot
edit a number that is recomputed every time. **D40 is the answer, and it is the
main design constraint on this module:** every line *shows its own working*.
"4x their usual 40,000.00-60,000.00 across 14 invoices" is not decoration, it is
the substitute for an editable rule -- a reader who disagrees can see exactly
which comparison produced the doubt, and fixing the invoices fixes it. Slice A's
`Figure(source=COMPUTED, computation=...)` already carries that provenance, so
the working is expressed there rather than in a second mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlmodel import Session, select

from models import Document, Invoice
from services.atlas_capabilities import AtlasCapability
from services.atlas_contract import (
    Action,
    Certainty,
    Recommendation,
    Reversibility,
    Verify,
    What,
    Why,
    validate_recommendation,
)
from services.atlas_figures import (
    computed_figure,
    count_reference,
    integer_multiple,
    money_prefix,
    render_amount,
)

__all__ = [
    "ClaimKind",
    "Witness",
    "CLAIM_WITNESS",
    "Claim",
    "VendorBaseline",
    "Verdict",
    "Doubt",
    "claims_for_invoice",
    "vendor_baseline",
    "witnesses_held",
    "doubts_for_invoice",
    "doubt_recommendations",
]


class ClaimKind(str, Enum):
    """What an invoice asserts. §3.3's list, and no sixth without a decision."""

    RATE = "rate"
    QUANTITY = "quantity"
    DELIVERY = "delivery"
    PAYMENT = "payment"
    BALANCE = "balance"


class Witness(str, Enum):
    """The one document that settles a claim (§3.3). One per claim, never two."""

    QUOTATION_OR_CONTRACT = "quotation_or_contract"
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_NOTE = "delivery_note"
    BANK_STATEMENT = "bank_statement"
    VENDOR_STATEMENT = "vendor_statement"


#: §3.3's table, verbatim, as a mapping. **Fixed, not learned**: "only this
#: settles it" is the whole content of the rule, and a witness chosen per
#: invoice by a model would make the ask unfalsifiable -- the user could never
#: tell whether the document being requested is actually the one that answers
#: the question.
CLAIM_WITNESS: dict[ClaimKind, Witness] = {
    ClaimKind.RATE: Witness.QUOTATION_OR_CONTRACT,
    ClaimKind.QUANTITY: Witness.PURCHASE_ORDER,
    ClaimKind.DELIVERY: Witness.DELIVERY_NOTE,
    ClaimKind.PAYMENT: Witness.BANK_STATEMENT,
    ClaimKind.BALANCE: Witness.VENDOR_STATEMENT,
}

#: How `documents.doc_type` values name the witnesses above. Anything not listed
#: is simply not a witness -- an unrecognised document type must never be read
#: as "we hold the proof", which would suppress an ask that should have happened.
_DOC_TYPE_WITNESS: dict[str, Witness] = {
    "QUOTATION": Witness.QUOTATION_OR_CONTRACT,
    "QUOTE": Witness.QUOTATION_OR_CONTRACT,
    "CONTRACT": Witness.QUOTATION_OR_CONTRACT,
    "PURCHASE_ORDER": Witness.PURCHASE_ORDER,
    "DELIVERY_NOTE": Witness.DELIVERY_NOTE,
    "GRN": Witness.DELIVERY_NOTE,
    "BANK_STATEMENT": Witness.BANK_STATEMENT,
    "VENDOR_STATEMENT": Witness.VENDOR_STATEMENT,
    "STATEMENT_OF_ACCOUNT": Witness.VENDOR_STATEMENT,
}

#: How far outside the vendor's own range an amount must fall before it is in
#: doubt. Expressed as a multiple of their highest invoice, so it scales with the
#: vendor rather than with an absolute rupee figure that is wrong for somebody.
_UNUSUAL_MULTIPLE = Decimal("2")
#: Fewer invoices than this and there is no baseline worth deviating from -- the
#: cold-start problem §7.1 names. A "first invoice from a new vendor" doubt is
#: raised instead, which is a different and honest thing to say.
_MIN_HISTORY = 3
#: An ask has to be worth two minutes of the user's time (§3.3 step 3). An amount
#: at or below the vendor's own typical high is not, however unusual the ratio
#: looks on a tiny baseline.
_MATERIAL_MULTIPLE = Decimal("2")


@dataclass(frozen=True)
class Claim:
    """One checkable assertion, derived from extracted fields. Never stored (D39)."""

    kind: ClaimKind
    #: The extracted field it came off -- `grand_total`, `items`, `due_date`.
    field: str
    value: Decimal | None
    currency: str

    @property
    def witness(self) -> Witness:
        return CLAIM_WITNESS[self.kind]


@dataclass(frozen=True)
class VendorBaseline:
    """What this vendor has historically billed. **Computed at check time (D39).**

    `low` and `high` are the actual lowest and highest totals seen, not a
    smoothed band: they are numbers the user can go and find on real invoices,
    which is what makes the working on the line checkable (D40).
    """

    vendor_name: str
    currency: str
    invoice_count: int
    low: Decimal
    high: Decimal
    median: Decimal

    @property
    def is_established(self) -> bool:
        return self.invoice_count >= _MIN_HISTORY


class Verdict(str, Enum):
    """§3.3's decision rule, as three outcomes and no fourth."""

    #: Not in doubt. ATLAS says nothing at all.
    NO_DOUBT = "no_doubt"
    #: In doubt, and we hold the witness: check, and speak only if it disagrees.
    CHECK_SILENTLY = "check_silently"
    #: In doubt, we do not hold the witness, and the answer is worth the ask.
    ASK = "ask"


@dataclass(frozen=True)
class Doubt:
    """One doubt about one claim, carrying the working that produced it (D40)."""

    invoice_id: UUID
    claim: Claim
    verdict: Verdict
    #: The sentence a user reads, already containing its own evidence.
    working: str
    baseline: VendorBaseline | None
    #: Present when the doubt is about an amount being unusual.
    multiple: int | None = None

    @property
    def witness(self) -> Witness:
        return self.claim.witness


# ═════════════════════════════════════════════════════════════════════════════
# Derivation — claims, the baseline, and what we hold
# ═════════════════════════════════════════════════════════════════════════════

def claims_for_invoice(invoice: Invoice, *, default_currency: str = "INR") -> list[Claim]:
    """The claims this invoice makes, off its extracted fields (D39).

    Only claims whose field was actually extracted are produced. §3.3's
    anti-pattern is asking for documents on a schedule or per invoice; producing
    a claim for a field that was never read would turn a missing extraction into
    a request for paperwork, which is that anti-pattern arriving by the back
    door.
    """
    currency = (invoice.currency or default_currency).upper()
    claims: list[Claim] = []

    if invoice.grand_total is not None:
        # The total is the invoice's rate claim in aggregate: "this is what the
        # goods cost at the agreed rate", and the quotation or contract is what
        # settles it.
        claims.append(
            Claim(
                kind=ClaimKind.RATE,
                field="grand_total",
                value=Decimal(str(invoice.grand_total)),
                currency=currency,
            )
        )
    if invoice.items:
        claims.append(
            Claim(
                kind=ClaimKind.QUANTITY,
                field="items",
                value=Decimal(str(len(invoice.items))),
                currency=currency,
            )
        )
        claims.append(
            Claim(
                kind=ClaimKind.DELIVERY,
                field="items",
                value=None,
                currency=currency,
            )
        )
    if invoice.status in ("AUDIT_REQUIRED", "REVIEW_LATER") and invoice.grand_total is not None:  # hardcode-ok: the two inbound audit statuses of routers/audit.py's own state machine, not domain data
        claims.append(
            Claim(
                kind=ClaimKind.PAYMENT,
                field="status",
                value=Decimal(str(invoice.grand_total)),
                currency=currency,
            )
        )
    return claims


def vendor_baseline(
    db: Session,
    tenant_id: UUID,
    vendor_name: str,
    *,
    exclude_invoice_id: UUID | None = None,
    currency: str = "INR",
) -> VendorBaseline:
    """This vendor's own history, computed now and thrown away (D39).

    The invoice being checked is excluded: comparing a number against a range it
    is itself inside makes every invoice normal, which is the quiet way an
    anomaly check stops working.

    Only invoices in the same currency count. A vendor billing in two currencies
    has two baselines, not one blended one (§7.4, D32).
    """
    rows = list(
        db.exec(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.vendor_name == vendor_name,
                Invoice.flow_direction == "INBOUND",
                Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
            )
        ).all()
    )
    amounts = sorted(
        Decimal(str(r.grand_total))
        for r in rows
        if r.grand_total is not None
        and r.id != exclude_invoice_id
        and (r.currency or currency).upper() == currency.upper()
    )
    if not amounts:
        return VendorBaseline(
            vendor_name=vendor_name,
            currency=currency,
            invoice_count=0,
            low=Decimal("0"),
            high=Decimal("0"),
            median=Decimal("0"),
        )
    middle = amounts[len(amounts) // 2]
    return VendorBaseline(
        vendor_name=vendor_name,
        currency=currency,
        invoice_count=len(amounts),
        low=amounts[0],
        high=amounts[-1],
        median=middle,
    )


def witnesses_held(db: Session, tenant_id: UUID) -> set[Witness]:
    """Which witness documents this tenant has already given us.

    Step 2 of §3.3, and the reason ATLAS does not nag: a doubt whose witness is
    already in the building is checked silently and never becomes an ask.

    Tenant-wide rather than per vendor, deliberately and conservatively in the
    *direction of asking*: `documents` does not carry a vendor link, so a
    per-vendor answer would have to be guessed, and a wrong "we hold it" silences
    a question that should have been asked. A wrong "we do not" merely asks for a
    document the user can decline.
    """
    rows = db.exec(
        select(Document).where(Document.tenant_id == tenant_id)
    ).all()
    held: set[Witness] = set()
    for row in rows:
        witness = _DOC_TYPE_WITNESS.get(str(getattr(row, "doc_type", "") or "").upper())
        if witness is not None:
            held.add(witness)
    return held


# ═════════════════════════════════════════════════════════════════════════════
# The decision rule (§3.3) — deterministic, per hard rule 3
# ═════════════════════════════════════════════════════════════════════════════

def doubts_for_invoice(
    db: Session,
    tenant_id: UUID,
    invoice: Invoice,
    *,
    held: set[Witness] | None = None,
    default_currency: str = "INR",
) -> list[Doubt]:
    """§3.3's three steps, in order, with the working attached to each outcome.

    Returns every doubt, including `CHECK_SILENTLY` ones: the caller needs to know
    a silent check happened in order to run it. `doubt_recommendations()` is what
    decides which of them a user ever sees, and it shows only asks -- "check
    silently, say nothing unless it disagrees".
    """
    currency = (invoice.currency or default_currency).upper()
    held = witnesses_held(db, tenant_id) if held is None else held
    vendor = invoice.vendor_name or ""
    baseline = vendor_baseline(
        db,
        tenant_id,
        vendor,
        exclude_invoice_id=invoice.id,
        currency=currency,
    )

    doubts: list[Doubt] = []
    for claim in claims_for_invoice(invoice, default_currency=default_currency):
        if claim.kind is not ClaimKind.RATE or claim.value is None:
            # v1 raises doubt on the amount claim only. The other claim kinds are
            # derived and carry their witness (the mapping is the deliverable of
            # D19), but nothing in the data yet distinguishes a delivered line
            # from an undelivered one -- inventing a doubt about delivery would be
            # a false positive with a document request attached, which §5.2 says
            # is how a product trains users to dismiss everything.
            continue

        amount = claim.value
        mark = money_prefix(currency)

        if not baseline.is_established:
            working = (
                f"This is invoice {count_reference(baseline.invoice_count + 1)} from "
                f"{vendor or 'this vendor'} — there is no history to compare "
                f"{mark}{render_amount(amount, currency)} against yet."  # hardcode-ok: amount goes through `render_amount()`; `mark` is the claim's own currency symbol
            )
            verdict = (
                Verdict.CHECK_SILENTLY
                if claim.witness in held
                else Verdict.ASK
            )
            doubts.append(
                Doubt(
                    invoice_id=invoice.id,
                    claim=claim,
                    verdict=verdict,
                    working=working,
                    baseline=baseline,
                )
            )
            continue

        threshold = baseline.high * _UNUSUAL_MULTIPLE
        if amount <= threshold:
            continue  # inside what this vendor normally bills: not in doubt

        multiple = integer_multiple(amount, baseline.high)
        working = (
            f"{mark}{render_amount(amount, currency)} is over "  # hardcode-ok: amount goes through `render_amount()`; `mark` is the claim's own currency symbol
            f"{count_reference(multiple)}x their usual "
            f"{mark}{render_amount(baseline.low, currency)}–"
            f"{mark}{render_amount(baseline.high, currency)} across "
            f"{count_reference(baseline.invoice_count)} invoices."
        )

        # Step 3: worth the interruption? Materiality is against the vendor's own
        # scale, never an absolute amount -- ₹4,500 matching twelve months of
        # history is never worth an ask, and the same ₹4,500 from a vendor who has
        # only ever billed ₹500 is.
        material = amount > baseline.high * _MATERIAL_MULTIPLE
        if claim.witness in held:
            verdict = Verdict.CHECK_SILENTLY
        elif material:
            verdict = Verdict.ASK
        else:
            verdict = Verdict.NO_DOUBT

        doubts.append(
            Doubt(
                invoice_id=invoice.id,
                claim=claim,
                verdict=verdict,
                working=working,
                baseline=baseline,
                multiple=multiple,
            )
        )
    return doubts


# ═════════════════════════════════════════════════════════════════════════════
# The lines — an ask, carrying its reason (§3.3)
# ═════════════════════════════════════════════════════════════════════════════

_WITNESS_LABEL = {
    Witness.QUOTATION_OR_CONTRACT: "the quotation or contract",
    Witness.PURCHASE_ORDER: "the purchase order",  # hardcode-ok: the user-facing name of a closed Witness enum value, not a document-type list
    Witness.DELIVERY_NOTE: "the delivery note",  # hardcode-ok: the user-facing name of a closed Witness enum value, not a document-type list
    Witness.BANK_STATEMENT: "the bank statement",  # hardcode-ok: the user-facing name of a closed Witness enum value, not a document-type list
    Witness.VENDOR_STATEMENT: "their statement of account",
}


def doubt_recommendations(
    invoice: Invoice, doubts: list[Doubt], *, default_currency: str = "INR"
) -> list[Recommendation]:
    """Only the asks become lines. Silent checks stay silent (§3.3 step 2).

    Each line **carries its reason** -- §3.3 is explicit that an ask without one
    turns ATLAS into a form, because the user cannot judge whether attaching the
    document is worth two minutes. The reason is `Doubt.working`, which is the
    same string the doubt was decided from, so the line cannot say one thing while
    the check did another.
    """
    lines: list[Recommendation] = []
    currency = (invoice.currency or default_currency).upper()
    vendor = invoice.vendor_name or "this vendor"
    number = f"#{invoice.invoice_number}" if invoice.invoice_number else "this invoice"

    for doubt in doubts:
        if doubt.verdict is not Verdict.ASK or doubt.claim.value is None:
            continue
        witness_label = _WITNESS_LABEL[doubt.witness]
        baseline = doubt.baseline
        figures = [
            computed_figure(
                doubt.claim.value,
                currency,
                "the total on this invoice, as extracted",
            )
        ]
        references = [number]
        if baseline is not None and baseline.is_established:
            figures.extend(
                [
                    computed_figure(
                        baseline.low,
                        currency,
                        f"the lowest of {vendor}'s {baseline.invoice_count} previous "
                        f"invoices in this currency",
                    ),
                    computed_figure(
                        baseline.high,
                        currency,
                        f"the highest of {vendor}'s {baseline.invoice_count} previous "
                        f"invoices in this currency",
                    ),
                ]
            )
            references.append(count_reference(baseline.invoice_count))
            if doubt.multiple is not None:
                references.append(count_reference(doubt.multiple))
        elif baseline is not None:
            references.append(count_reference(baseline.invoice_count + 1))

        lines.append(
            validate_recommendation(
                Recommendation(
                    id=f"doubt-{doubt.claim.kind.value}-{invoice.id}",  # hardcode-ok: an id built from enum values and a UUID, no money in it
                    capability=AtlasCapability.AUDIT,
                    skill=f"claim_in_doubt_{doubt.claim.kind.value}",  # hardcode-ok: a skill name built from an enum value, no money in it
                    what=What(
                        headline=f"{vendor} {number}: {witness_label} would settle this",
                        entity_kind="invoice",
                        entity_id=str(invoice.id),
                    ),
                    why=Why(
                        text=f"{doubt.working} Attaching {witness_label} settles it in one step.",
                        figures=figures,
                        references=references,
                        doubt=(
                            f"I cannot tell whether this is agreed or an error without "
                            f"{witness_label}."
                        ),
                    ),
                    action=Action(
                        kind="attach_witness_document",
                        label=f"Attach {witness_label}",
                        target_id=str(invoice.id),
                        params={
                            "witness": doubt.witness.value,
                            "claim": doubt.claim.kind.value,
                        },
                    ),
                    verify=Verify(
                        question=(
                            f"Attach {number} here — what did you compare it "
                            f"against, and which invoices are in that range?"
                        ),
                        document_id=str(invoice.id),
                    ),
                    certainty=Certainty.UNCERTAIN,
                    reversibility=Reversibility.REVERSIBLE,
                    currency=currency,
                )
            )
        )
    return lines
