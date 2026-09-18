"""Feature 34 (ATLAS) task 34.4 — vendor statement vs our ledger.

Spec: `docs/feature_34_atlas.md` §3.2 · decision D18.

**The first recon, and the first thing a customer will value** (§3.2): it is work
a person is definitely doing today, by hand, on a schedule, with documents they
already hold, and it has a definite answer. Attach the statement → **matched ·
they show and we do not · we show and they do not · amount differs**, every
bucket printed from the server's own rows.

The comparison is code, not a prompt
------------------------------------
CONVENTIONS hard rule 3. `reconcile()` decides whether two numbers agree, and it
is ordinary arithmetic over `Decimal`: no model sees the two amounts and offers
an opinion. A model may phrase the resulting line -- "they are showing an
invoice we never received" reads better than a bucket name -- but by the time it
speaks, which bucket each row is in has already been decided here and cannot be
changed by the phrasing. An LLM asked to compare 48,000 against 50,000 will
usually be right, and §5.2 explains why usually is the wrong standard for a
number: trust in numbers is binary and does not recover.

Matching, and what it deliberately does not do
----------------------------------------------
Rows are matched on the **invoice number**, normalised (casefolded, `#`, spaces,
punctuation and leading zeros removed). Not on amount: two invoices for the same
round amount in the same month are common, and a match made on amount alone
would silently pair the wrong two and then report that everything agrees --
which is a wrong answer wearing the costume of a right one. A statement line
with no invoice number is reported as unmatchable rather than guessed at.

Matching runs in two passes: the whole normalised key, then -- for whatever is
still unmatched -- the **digits alone, and only where exactly one row on each
side carries them**. "INV-01041" on their template against "1041" in our
extraction is the same invoice, and refusing to see that manufactures a
"they show an invoice we do not have" finding out of a formatting difference.
Two candidates for the same digits is a guess, and a guessed pair that then
reports agreement is the worst output this module could produce, so ambiguity
stays unmatched.

**One currency per reconciliation** (§7.4, D32). A statement in one currency
compared against a ledger in another is refused with `CurrencyBlendError`
rather than compared with a rate this system does not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from models import Invoice
from services.atlas_capabilities import AtlasCapability
from services.atlas_contract import (
    Action,
    Certainty,
    CurrencyBlendError,
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
    document_figure,
    money_prefix,
    render_amount,
)

__all__ = [
    "StatementLine",
    "LedgerLine",
    "MatchedPair",
    "AmountDifference",
    "ReconResult",
    "normalise_invoice_number",
    "ledger_lines_for_vendor",
    "statement_lines_from_items",
    "reconcile",
    "recon_recommendations",
]

#: Everything that is punctuation or space in an invoice number as printed.
_STRIP = re.compile(r"[^0-9a-z]")

#: Zeros that pad the front of a digit run ("inv001041" -> "inv1041"), and only
#: those: the lookbehind is what stops "1000" collapsing to "10".
_LEADING_ZEROS = re.compile(r"(?<!\d)0+(?=\d)")

#: Below this, two amounts are the same number printed differently (a rounding
#: convention on their side). It is not a tolerance for disagreement: 48,000
#: against 50,000 is a short payment and belongs in its own bucket, named.
_SAME_AMOUNT = Decimal("0.01")


def normalise_invoice_number(raw: str | None) -> str:
    """"INV #001041 " -> "inv1041". The key both sides are matched on.

    Leading zeros go because one side's template pads and the other's does not;
    everything else that survives is a character both sides actually printed.
    Returns "" for an unusable value, and "" never matches anything -- an empty
    key that matched would join every unnumbered row to every other.
    """
    if not raw:
        return ""
    cleaned = _STRIP.sub("", str(raw).casefold())
    # Leading zeros of any digit run, not just the string's first characters:
    # "INV #001041" pads *after* its prefix, and a plain `lstrip("0")` would
    # leave "inv001041" untouched and silently fail to match "inv-1041" -- a
    # missed match reads as "they show an invoice we do not have", which is a
    # manufactured finding.
    trimmed = _LEADING_ZEROS.sub("", cleaned)
    return trimmed or cleaned


@dataclass(frozen=True)
class StatementLine:
    """One row of the vendor's statement, as their document prints it.

    `raw_text` is the verbatim line it was read from and is what makes every
    figure on the resulting recommendation a DOCUMENT figure with a quote, per
    §5.3. A statement line with no `raw_text` can still be reconciled; it just
    cannot be quoted, and the line then computes rather than quotes.
    """

    invoice_number: str | None
    amount: Decimal
    currency: str
    line_date: date | None = None
    raw_text: str | None = None

    @property
    def key(self) -> str:
        return normalise_invoice_number(self.invoice_number)


@dataclass(frozen=True)
class LedgerLine:
    """One invoice of ours, as it stands in the database."""

    invoice_id: UUID
    invoice_number: str | None
    amount: Decimal
    currency: str
    invoice_date: date | None = None

    @property
    def key(self) -> str:
        return normalise_invoice_number(self.invoice_number)


@dataclass(frozen=True)
class MatchedPair:
    statement: StatementLine
    ledger: LedgerLine


@dataclass(frozen=True)
class AmountDifference:
    """Same invoice, two numbers. `difference` is theirs minus ours."""

    statement: StatementLine
    ledger: LedgerLine

    @property
    def difference(self) -> Decimal:
        return self.statement.amount - self.ledger.amount


@dataclass
class ReconResult:
    """The four buckets of §3.2, and nothing else.

    `unmatchable` is a fifth list and is not a fifth bucket: it holds statement
    rows with no invoice number, which are not a finding about the vendor but a
    statement about what could be read off their document. Reporting them as
    "they show and we do not" would manufacture findings out of an unreadable
    column.
    """

    currency: str
    vendor_name: str
    matched: list[MatchedPair] = dc_field(default_factory=list)
    they_show_we_do_not: list[StatementLine] = dc_field(default_factory=list)
    we_show_they_do_not: list[LedgerLine] = dc_field(default_factory=list)
    amount_differs: list[AmountDifference] = dc_field(default_factory=list)
    unmatchable: list[StatementLine] = dc_field(default_factory=list)

    @property
    def agrees(self) -> bool:
        return not (
            self.they_show_we_do_not or self.we_show_they_do_not or self.amount_differs
        )


def ledger_lines_for_vendor(
    db: Session,
    tenant_id: UUID,
    vendor_name: str,
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[LedgerLine]:
    """Our side of the comparison, read from our own rows.

    Deleted invoices are excluded and duplicates are not: a row the tenant marked
    DUPLICATE is still a row the vendor may be showing, and dropping it here would
    turn a duplicate into a "they show and we do not" finding pointing at a
    document already in the system.
    """
    stmt = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.vendor_name == vendor_name,
        Invoice.flow_direction == "INBOUND",
        Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
    )
    if since is not None:
        stmt = stmt.where(Invoice.invoice_date >= since)
    if until is not None:
        stmt = stmt.where(Invoice.invoice_date <= until)
    return [
        LedgerLine(
            invoice_id=inv.id,
            invoice_number=inv.invoice_number,
            amount=Decimal(str(inv.grand_total or 0)),
            currency=(inv.currency or "").upper(),
            invoice_date=inv.invoice_date,
        )
        for inv in db.exec(stmt).all()
    ]


#: A token that could be an invoice number: it carries at least one digit and is
#: not a date and not an amount. Dates and amounts are excluded by shape below
#: rather than by position, because statement templates order their columns
#: differently and a positional rule would be right on one vendor's paper only.
_DATE_SHAPED = re.compile(r"^\d{1,4}[-/.]\d{1,2}([-/.]\d{1,4})?$")
_AMOUNT_SHAPED = re.compile(r"^-?[\d,.']+$")


def _invoice_number_in(description: str | None) -> str | None:
    """The invoice number printed in a statement row's description, or `None`.

    **BE Gap 691 / FE Feature 23.** A vendor statement reaches us through Feature
    27's generic extraction, and `GenericLineItem` has no `invoice_number`
    column -- it has `description`, `quantity`, `unit_price`, `amount`. So the
    number a statement row refers to is inside prose, and this is the one place
    that is allowed to look for it.

    The rule is deterministic (hard rule 3) and it **refuses rather than
    guesses**, which is the same standard `reconcile()`'s second pass already
    holds itself to:

    * a candidate token carries at least one digit, and is neither date-shaped
      ("05/08/2026") nor amount-shaped ("12,000.00") -- both of which appear in
      the same string on most templates;
    * **exactly one** candidate means the number was read. Zero or several means
      it was not, and the row becomes `unmatchable` -- a row we could not read,
      reported as such -- rather than a key that might pair with the wrong
      invoice and then report agreement.

    A guessed pair reporting agreement is the worst output this module can
    produce (module docstring), and a wrong pair made here would be invisible by
    the time `reconcile()` saw it.
    """
    if not description:
        return None
    candidates = [
        token
        for token in str(description).split()
        if any(ch.isdigit() for ch in token)
        and not _DATE_SHAPED.match(token)
        and not _AMOUNT_SHAPED.match(token)
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]


def statement_lines_from_items(
    items: list | None, *, currency: str
) -> tuple[list[StatementLine], int]:
    """An attached statement's extracted rows, as rows this module can compare.

    Returns `(lines, unreadable_row_count)`. A row with **no amount** is not a
    statement line at all -- `GenericLineItem.amount` is `None` when the document
    printed none, and Gap 283's lesson is that `None` must never be read as zero,
    least of all here, where a zero would be reported to a vendor as a
    disagreement. Those rows are counted and reported, never invented.

    `raw_text` is deliberately left `None`: the row's description is what we
    extracted, not a verbatim transcription of the vendor's line, and
    `recon_recommendations()` already handles a line with no quote by computing
    rather than quoting (see `StatementLine`). Synthesising a quote so that a
    DOCUMENT figure could pass its own validator would defeat the validator.
    """
    lines: list[StatementLine] = []
    unreadable = 0
    for item in items or []:
        if not isinstance(item, dict):
            unreadable += 1
            continue
        amount = item.get("amount")
        if amount is None:
            unreadable += 1
            continue
        lines.append(
            StatementLine(
                invoice_number=_invoice_number_in(item.get("description")),
                amount=Decimal(str(amount)),
                currency=currency.upper(),
            )
        )
    return lines, unreadable


def reconcile(
    statement_lines: list[StatementLine],
    ledger_lines: list[LedgerLine],
    *,
    vendor_name: str,
    currency: str,
) -> ReconResult:
    """The comparison. Deterministic, total, and the only thing that decides agreement.

    Every statement row lands in exactly one bucket and every ledger row in at
    most one, so the four lists plus `unmatchable` account for the whole input --
    which is what makes "everything else agrees" a statement the caller may
    print rather than an assumption.

    Raises `CurrencyBlendError` if any row on either side is in another currency
    (§7.4, D32). Rows carrying no currency at all are taken as the stated
    `currency`: an `Invoice.currency` of NULL means the extractor did not read
    one, not that the invoice is in a different one, and the tenant's own ledger
    is the side that is allowed a default.
    """
    currency = currency.upper()
    for line in statement_lines:
        if line.currency and line.currency.upper() != currency:
            raise CurrencyBlendError(
                f"statement line {line.invoice_number!r} is in {line.currency}, "
                f"not {currency} -- refusing to reconcile across currencies"
            )
    for row in ledger_lines:
        if row.currency and row.currency.upper() != currency:
            raise CurrencyBlendError(
                f"invoice {row.invoice_number!r} is in {row.currency}, not "
                f"{currency} -- refusing to reconcile across currencies"
            )

    result = ReconResult(currency=currency, vendor_name=vendor_name)

    by_key: dict[str, list[LedgerLine]] = {}
    for row in ledger_lines:
        if row.key:
            by_key.setdefault(row.key, []).append(row)
    unseen: dict[str, list[LedgerLine]] = {k: list(v) for k, v in by_key.items()}

    def place(line: StatementLine, ours: LedgerLine) -> None:
        if abs(line.amount - ours.amount) < _SAME_AMOUNT:
            result.matched.append(MatchedPair(statement=line, ledger=ours))
        else:
            result.amount_differs.append(AmountDifference(statement=line, ledger=ours))

    leftover: list[StatementLine] = []
    for line in statement_lines:
        if not line.key:
            result.unmatchable.append(line)
            continue
        candidates = unseen.get(line.key) or []
        if not candidates:
            leftover.append(line)
            continue
        place(line, candidates.pop(0))

    # Second pass: the digits alone, and **only when they are unambiguous**.
    # One side prints "INV-01041" where the other recorded "1041" -- the same
    # invoice, and a missed match here is not a neutral outcome: it reads as
    # "they show an invoice we do not have", which is a finding ATLAS
    # manufactured out of a template difference. So digits are allowed to match,
    # but only where exactly one unmatched row on each side carries them. Two
    # candidates means the pairing would be a guess, and §3.2's whole value is
    # that recon has a definite answer -- a guessed pair that then reports
    # agreement is a wrong answer wearing the costume of a right one.
    remaining_ledger = [row for rows in unseen.values() for row in rows]
    by_digits_theirs: dict[str, list[StatementLine]] = {}
    for line in leftover:
        by_digits_theirs.setdefault(_digits(line.key), []).append(line)
    by_digits_ours: dict[str, list[LedgerLine]] = {}
    for row in remaining_ledger:
        by_digits_ours.setdefault(_digits(row.key), []).append(row)

    paired_ledger: set[int] = set()
    for line in leftover:
        digits = _digits(line.key)
        theirs = by_digits_theirs.get(digits) or []
        ours_rows = by_digits_ours.get(digits) or []
        if digits and len(theirs) == 1 and len(ours_rows) == 1:
            place(line, ours_rows[0])
            paired_ledger.add(id(ours_rows[0]))
        else:
            result.they_show_we_do_not.append(line)

    result.we_show_they_do_not.extend(
        row for row in remaining_ledger if id(row) not in paired_ledger
    )

    return result


def _digits(key: str) -> str:
    """The digit part of a normalised key -- "inv1041" -> "1041"."""
    return "".join(ch for ch in key if ch.isdigit())


# ═════════════════════════════════════════════════════════════════════════════
# The lines (§1) — one recommendation per bucket that has anything in it
# ═════════════════════════════════════════════════════════════════════════════

def recon_recommendations(
    result: ReconResult,
    *,
    document_id: str,
) -> list[Recommendation]:
    """The recon, as work (§1, D7).

    One line per non-empty disagreement bucket, each with what / why / action /
    verify. **No line is emitted for `matched`** -- agreement is not work, and a
    line saying "41 invoices agree" is the kind of false-positive volume §5.2
    says trains a user to dismiss the twenty-first item unread. The count of
    matched rows appears inside the lines that *are* emitted, as the context that
    makes the disagreement readable.

    `document_id` is the attached statement, and it is required: every figure
    read off the statement quotes the row it came from, and a quote with no
    document is an assertion.
    """
    lines: list[Recommendation] = []
    currency = result.currency
    mark = money_prefix(currency)
    vendor = result.vendor_name
    matched_count = count_reference(len(result.matched))

    if result.they_show_we_do_not:
        rows = result.they_show_we_do_not
        total = sum((r.amount for r in rows), Decimal("0"))
        figures = [
            computed_figure(
                total,
                currency,
                f"the {len(rows)} statement line(s) we hold no invoice for, added up",
            )
        ]
        numbers = [f"#{r.invoice_number}" for r in rows if r.invoice_number]
        lines.append(
            validate_recommendation(
                Recommendation(
                    id=f"recon-missing-ours-{document_id}",
                    capability=AtlasCapability.AUDIT,
                    skill="vendor_statement_they_show_we_do_not",
                    what=What(
                        headline=f"{vendor} shows {len(rows)} invoice(s) we do not have",
                        entity_kind="vendor",
                        entity_id=vendor,
                    ),
                    why=Why(
                        text=(
                            f"Their statement lists {count_reference(len(rows))} "
                            f"invoice(s) totalling {mark}{render_amount(total, currency)} "  # hardcode-ok: the amount goes through `render_amount()`; `mark` is this recon's single currency symbol
                            f"that we hold no record of: {', '.join(numbers) or 'no numbers printed'}. "
                            f"{matched_count} other line(s) match ours exactly."
                        ),
                        figures=figures,
                        references=numbers + [matched_count, count_reference(len(rows))],
                        doubt=(
                            "Either these never reached us, or they reached us under "
                            "a different number — I cannot tell which from the "
                            "statement alone."
                        ),
                    ),
                    action=Action(
                        kind="request_missing_invoices",
                        label="Ask them for these invoices",
                        target_id=vendor,
                        params={"invoice_numbers": numbers},
                    ),
                    verify=Verify(
                        question=(
                            "Attach their statement here — which of its lines did "
                            "you fail to find, and what did you search our "
                            "records for?"
                        ),
                        document_id=document_id,
                    ),
                    certainty=Certainty.UNCERTAIN,
                    # §5.3/D29: this drafts a message to the vendor. Outside the
                    # company is individual and read in full, always.
                    reversibility=Reversibility.LEAVES_COMPANY,
                    currency=currency,
                )
            )
        )

    if result.we_show_they_do_not:
        rows = result.we_show_they_do_not
        total = sum((r.amount for r in rows), Decimal("0"))
        numbers = [f"#{r.invoice_number}" for r in rows if r.invoice_number]
        lines.append(
            validate_recommendation(
                Recommendation(
                    id=f"recon-missing-theirs-{document_id}",
                    capability=AtlasCapability.AUDIT,
                    skill="vendor_statement_we_show_they_do_not",
                    what=What(
                        headline=f"We hold {len(rows)} invoice(s) {vendor} does not show",
                        entity_kind="vendor",
                        entity_id=vendor,
                    ),
                    why=Why(
                        text=(
                            f"We have {count_reference(len(rows))} invoice(s) from this "
                            f"vendor totalling {mark}{render_amount(total, currency)} "  # hardcode-ok: the amount goes through `render_amount()`; `mark` is this recon's single currency symbol
                            f"that their statement does not list: "
                            f"{', '.join(numbers) or 'no numbers recorded'}. Either they "
                            f"have already been settled and cleared off their side, or "
                            f"one of them is a duplicate of something we counted twice."
                        ),
                        figures=[
                            computed_figure(
                                total,
                                currency,
                                f"the {len(rows)} of our invoices their statement does "
                                f"not list, added up",
                            )
                        ],
                        references=numbers + [count_reference(len(rows))],
                        doubt=(
                            "Settled and duplicated look the same from here — the "
                            "bank statement is what separates them."
                        ),
                    ),
                    action=Action(
                        kind="review_unlisted_invoices",
                        label="Review these against payments",
                        target_id=vendor,
                        params={"invoice_ids": [str(r.invoice_id) for r in rows]},
                    ),
                    verify=Verify(
                        question=(
                            "Attach their statement here — which of our invoices are "
                            "missing from it, and what did you match the rest on?"
                        ),
                        document_id=document_id,
                    ),
                    certainty=Certainty.UNCERTAIN,
                    reversibility=Reversibility.REVERSIBLE,
                    currency=currency,
                )
            )
        )

    for diff in result.amount_differs:
        lines.append(_amount_difference_line(diff, result, document_id))

    return lines


def _amount_difference_line(
    diff: AmountDifference, result: ReconResult, document_id: str
) -> Recommendation:
    """One line per disagreeing amount — **one each**, never a group.

    The other three buckets group because the finding is the set ("they show five
    we do not"). A disagreement is per invoice: the amount, the direction and the
    likely reason differ row by row, and a grouped line would force the user to
    open every one to find out which is which -- the completeness test of §1/D33,
    failed.
    """
    currency = result.currency
    mark = money_prefix(currency)
    number = f"#{diff.statement.invoice_number or diff.ledger.invoice_number or ''}"
    theirs = diff.statement.amount
    ours = diff.ledger.amount
    gap = abs(diff.difference)

    figures = [
        (
            document_figure(
                theirs, currency, document_id, diff.statement.raw_text
            )
            if diff.statement.raw_text
            and render_amount(theirs, currency) in diff.statement.raw_text
            else computed_figure(
                theirs, currency, "the amount printed on their statement line"
            )
        ),
        computed_figure(ours, currency, "the invoice total we recorded"),
        computed_figure(gap, currency, "their amount less ours"),
    ]

    return validate_recommendation(
        Recommendation(
            id=f"recon-differs-{diff.ledger.invoice_id}",
            capability=AtlasCapability.AUDIT,
            skill="vendor_statement_amount_differs",
            what=What(
                headline=f"{result.vendor_name} {number}: amounts disagree",  # hardcode-ok: vendor name and invoice number, no figure in this string
                entity_kind="invoice",
                entity_id=str(diff.ledger.invoice_id),
            ),
            why=Why(
                text=(
                    f"Their statement shows {mark}{render_amount(theirs, currency)} "
                    f"for {number} and we recorded "
                    f"{mark}{render_amount(ours, currency)} — a difference of "
                    f"{mark}{render_amount(gap, currency)}. {_likely_reason(theirs, ours)}"
                ),
                figures=figures,
                references=[number],
                doubt=(
                    "I can see that the two numbers differ; which side is right is "
                    "what the invoice itself settles."
                ),
            ),
            action=Action(
                kind="open_invoice_against_statement",
                label="Compare this invoice with their line",
                target_id=str(diff.ledger.invoice_id),
                params={"document_id": document_id},
            ),
            verify=Verify(
                question=(
                    f"Attach their statement here and show me their line for "
                    f"{number} beside ours, and what you compared."
                ),
                document_id=document_id,
            ),
            certainty=Certainty.UNCERTAIN,
            reversibility=Reversibility.REVERSIBLE,
            currency=currency,
        )
    )


def _likely_reason(theirs: Decimal, ours: Decimal) -> str:
    """Name the likely reason, do not just flag a gap (§3.2's short-payment rule).

    The reasons are a **fixed list applied by arithmetic**, not a model's
    suggestion: a deduction near a common TDS rate, a deduction near a common
    early-payment discount, or neither. Each is phrased as a candidate ("looks
    like") because it is one -- naming a reason ATLAS cannot prove as if it were
    established is §5.2's "right flag, wrong reason", which erodes credibility
    quietly and is visible without anyone clicking.
    """
    if ours <= 0:
        return "Worth opening the invoice to see which figure the document supports."
    shortfall = ours - theirs
    if shortfall <= 0:
        return (
            "Their figure is the larger one, so this is not a deduction on our side "
            "— worth opening the invoice to see which figure the document supports."
        )
    share = (shortfall / ours) * Decimal(100)
    # Common statutory and commercial deductions, as percentages of the invoice.
    for low, high, reason in (
        (Decimal("0.9"), Decimal("1.1"), "This is about one percent of the invoice, which looks like TDS withheld."),
        (Decimal("1.9"), Decimal("2.1"), "This is about two percent of the invoice, which looks like an early-payment discount or TDS."),
        (Decimal("4.9"), Decimal("5.1"), "This is about five percent of the invoice, which looks like a retention or a disputed line."),
        (Decimal("9.9"), Decimal("10.1"), "This is about ten percent of the invoice, which looks like a retention or a withheld line."),
    ):
        if low <= share <= high:
            return reason
    return "Worth opening the invoice to see which figure the document supports."
