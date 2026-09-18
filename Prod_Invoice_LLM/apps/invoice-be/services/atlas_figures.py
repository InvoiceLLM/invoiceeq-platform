"""Feature 34 (ATLAS) Slice B — the one place a number becomes a rendered string.

Spec: `docs/feature_34_atlas.md` §5.3 ("never invents a number"), §7.4 (one
currency per line) · decisions D28, D32, D40.

Every skill in Slice B (`atlas_skills`, `atlas_recon`, `atlas_doubt`) needs the
same two moves: turn a `Decimal` into the exact string the user reads, and
attach the witness that makes it a `Figure` rather than an assertion. Doing that
in three modules would produce three rounding conventions, and §5.2 says a wrong
number is the most damaging failure there is because trust in numbers is binary
and does not recover. So it is done once, here.

**The rendering rule is exactness, not prettiness.** Two decimal places, grouped,
never abbreviated: 241300 renders "2,41,300.00" and never "2.4 lakh" or "₹2.4L".
The spec calls the abbreviation the easiest rule to break by accident, because
prose comes from a model and models round -- these helpers exist so that no
emitter is ever in a position to write the number itself.

**Indian grouping** (2,41,300.00) is used for INR and western grouping
(241,300.00) for everything else, because the rendered form is what a user
compares against a document their own accountant produced. Both forms are the
same digits, so `assert_no_undeclared_numbers` is indifferent; the reader is not.

**Non-money quantities are deliberately not `Figure`s.** `Figure` requires a
currency, and a ratio ("4x their usual") or a count ("across 14 invoices") has
none. Rather than widen the contract to carry currency-less figures -- which
would make "is this money" a per-emitter judgement -- Slice B renders ratios as
**integers** ("over 4x") and counts as plain integers, neither of which is
money-shaped under the contract's rule unless it reaches four digits. Counts that
could reach four digits go through `count_reference()`, which declares them on
`Why.references` where identifiers already live.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from services.atlas_contract import Figure, FigureSource

__all__ = [
    "render_amount",
    "money_prefix",
    "computed_figure",
    "document_figure",
    "integer_multiple",
    "count_reference",
]

#: The symbol a user of that currency expects to see. Anything not listed
#: renders with its ISO code, which is never wrong, only plainer.
_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _group_indian(whole: str) -> str:
    """1234567 -> '12,34,567'. The last three digits, then pairs."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def render_amount(value: Decimal | float | int, currency: str) -> str:
    """The exact string the user reads. Two decimals, grouped, never rounded away.

    `Decimal` in and string out with no intermediate float: a float round-trip is
    how 2,41,300.00 quietly becomes 2,41,299.99, and §5.2 has nothing worse than a
    wrong number.
    """
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    digits = f"{abs(amount):.2f}"
    whole, frac = digits.split(".")
    grouped = _group_indian(whole) if currency == "INR" else f"{int(whole):,}"
    return f"{sign}{grouped}.{frac}"


def money_prefix(currency: str) -> str:
    """The symbol to put in front of a rendered amount in prose."""
    return _SYMBOLS.get(currency, currency + " ")


def computed_figure(
    value: Decimal | float | int, currency: str, computation: str
) -> Figure:
    """A number ATLAS worked out, carrying **what it did** (§5.3, D40).

    `computation` is the line's working in a user's words -- "the 14 line items
    added up", "this vendor's 14 invoices, lowest to highest". D40 makes this the
    substitute for a stored baseline: an observation that shows its own working
    does not need to be persisted to be checkable.
    """
    return Figure(
        rendered=render_amount(value, currency),
        value=Decimal(str(value)),
        currency=currency,
        source=FigureSource.COMPUTED,
        computation=computation,
    )


def document_figure(
    value: Decimal | float | int, currency: str, document_id: str, quote: str
) -> Figure:
    """A number a document says, carrying the document and the line it says it on."""
    return Figure(
        rendered=render_amount(value, currency),
        value=Decimal(str(value)),
        currency=currency,
        source=FigureSource.DOCUMENT,
        document_id=document_id,
        quote=quote,
    )


def integer_multiple(value: Decimal, baseline: Decimal) -> int:
    """"4x their usual" -- floored, so the claim is never larger than the truth.

    Floored rather than rounded on purpose: 4.9x rendered as "5x" is a number
    ATLAS invented in the user's favour, and the direction of an exaggeration
    does not make it true. The exact amounts are on the same line as figures, so
    a reader who wants the precise ratio has both numbers.
    """
    if baseline <= 0:
        return 0
    return int((value / baseline).quantize(Decimal("1"), rounding=ROUND_DOWN))


def count_reference(count: int) -> str:
    """A count rendered for `Why.references`.

    Four-digit-and-longer counts are money-shaped under the contract's rule
    ("across 1204 invoices"), so every count a line prints is declared as a
    reference. Cheap, and it removes a whole class of emitter mistake that only
    shows up on the customer with the most data.

    **Print what this returns, verbatim.** It is ungrouped on purpose: a prose
    "1,204" and a declared "1204" are different tokens to
    `assert_no_undeclared_numbers`, and the check is right to say so -- grouping
    a count is a rendering decision, and rendering decisions about numbers are
    exactly what this module centralises.
    """
    return str(count)
