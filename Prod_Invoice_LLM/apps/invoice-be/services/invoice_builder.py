"""Feature 17 (Invoice Builder — Clone & Edit): the pure, deterministic core.

An outbound invoice is created by cloning an existing outbound invoice and
editing what changes. Everything in this module is a pure function over the
source `Invoice` row and the user's `BuildRequest` — no database, no PDF, no
LLM. That is deliberate and is CONVENTIONS hard rule 3: totals arithmetic, the
invoice-number increment and the choice of renderer all decide correctness, so
none of them may be a prompt rule. The LLM only ever sees the *generated* PDF,
through the ordinary extraction pipeline, exactly as it sees an upload.

The rendering half lives in `services/pdf_substitute.py` (in-place value
substitution on the source PDF) and `services/pdf_render.py` (structured
re-render when the line count changed) — see `plan_render_mode()` below for
which one runs, founder decision D3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

#: Money is rounded to 2 dp, half-up, everywhere in this feature. Banker's
#: rounding (Python's default for `round()`) would turn 0.005 into 0.00 and
#: disagree with both the FE mirror (`lib/invoiceBuilderMath.ts`) and with what
#: every invoice this product has ever ingested actually prints.
CENTS = Decimal("0.01")


def _q(value: Decimal | int | float | str | None) -> Decimal:
    """Coerce to Decimal, treating None/blank as zero. Never float arithmetic."""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: Decimal | int | float | str | None) -> Decimal:
    """Quantize to 2 dp, ROUND_HALF_UP."""
    return _q(value).quantize(CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# The editable surface
# ---------------------------------------------------------------------------

class BuildItem(BaseModel):
    """One editable line. `amount` is deliberately absent: the client never
    sends a line total, the server always computes it (`compute_totals`)."""
    description: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None


class BuildRequest(BaseModel):
    """Everything a user may change when cloning. Anything not listed here —
    the tenant's own name and address, the logo, the layout, the legal footer —
    is inherited from the source PDF because the source PDF *is* the template.
    """
    source_invoice_id: UUID
    customer_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    items: list[BuildItem] = Field(default_factory=list)
    tax_amount: Decimal | None = None


class Totals(BaseModel):
    """Server-computed totals. Never read from the request."""
    line_amounts: list[Decimal] = Field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    grand_total: Decimal = Decimal("0.00")


def compute_totals(items: list[BuildItem], tax_amount: Decimal | None) -> Totals:
    """`amount = round(qty × unit_price, 2)` per line, `subtotal = Σ amount`,
    `grand_total = subtotal + tax_amount`. Half-up, Decimal throughout.

    A missing quantity or unit price contributes a 0.00 line rather than
    raising: the FE grid can hold a half-typed row and a preview must still
    render something rather than 500.
    """
    amounts = [money(_q(i.quantity) * _q(i.unit_price)) for i in items]
    subtotal = money(sum(amounts, Decimal("0")))
    tax = money(tax_amount)
    return Totals(
        line_amounts=amounts,
        subtotal=subtotal,
        tax_amount=tax,
        grand_total=money(subtotal + tax),
    )


# ---------------------------------------------------------------------------
# Invoice number suggestion
# ---------------------------------------------------------------------------

_TRAILING_DIGITS = re.compile(r"(\d+)(\D*)$")


def next_invoice_number(source_number: str | None) -> str | None:
    """Increment the trailing digit run, preserving zero-padding.

    `INV-0042` → `INV-0043`, `2026/07` → `2026/08`, `INV-0099` → `INV-0100`
    (the pad width is kept, so a carry widens the run only when it has to).
    Returns None when there is no digit run to increment (`ACME`), which the
    endpoint surfaces as an empty suggestion the user must fill in — never a
    guess, and never enforced: D5's uniqueness refusal is the only hard rule
    about invoice numbers.
    """
    if not source_number:
        return None
    match = _TRAILING_DIGITS.search(source_number)
    if not match:
        return None
    digits, tail = match.group(1), match.group(2)
    incremented = str(int(digits) + 1).rjust(len(digits), "0")
    start = match.start(1)
    return f"{source_number[:start]}{incremented}{tail}"


# ---------------------------------------------------------------------------
# Prefill
# ---------------------------------------------------------------------------

def default_build_from_source(invoice: Any, today: date) -> BuildRequest:
    """Everything copied, the number incremented, the dates rolled forward by
    the source's own payment term (`due_date − invoice_date`). When the source
    carried only one of the two dates there is no term to roll, so `due_date`
    comes back None and the user picks one.

    `invoice` is typed loosely on purpose — this module never imports `models`,
    which keeps it unit-testable without a database session.
    """
    term = None
    if invoice.due_date and invoice.invoice_date:
        term = invoice.due_date - invoice.invoice_date

    items: list[BuildItem] = []
    for raw in (invoice.items or []):
        if not isinstance(raw, dict):
            continue
        items.append(
            BuildItem(
                description=str(raw.get("description") or ""),
                quantity=(None if raw.get("quantity") is None else _q(raw.get("quantity"))),
                unit_price=(None if raw.get("unit_price") is None else _q(raw.get("unit_price"))),
            )
        )

    return BuildRequest(
        source_invoice_id=invoice.id,
        customer_name=invoice.customer_name,
        invoice_number=next_invoice_number(invoice.invoice_number),
        invoice_date=today,
        due_date=(today + term) if term is not None else None,
        currency=invoice.currency,
        items=items,
        tax_amount=(None if invoice.tax_amount is None else _q(invoice.tax_amount)),
    )


# ---------------------------------------------------------------------------
# Render mode (founder decision D3)
# ---------------------------------------------------------------------------

RenderMode = Literal["substitute", "rerender"]


def plan_render_mode(source: Any, req: BuildRequest) -> RenderMode:
    """`substitute` iff the line count is unchanged, otherwise `rerender`.

    D1 said "substitution only"; D3 then allowed adding and removing rows.
    Those conflict — you cannot insert a row into a fixed printed layout by
    painting over words — so the founder's ruling is the hybrid: keep the
    exact-copy look whenever the layout still fits, and fall back to a
    structured re-render with the source's harvested branding when it cannot.
    The FE mirrors this rule in `predictRenderMode()` purely to label the
    screen; the decision is made here and is never taken from the request.
    """
    source_count = len(source.items or [])
    return "substitute" if len(req.items) == source_count else "rerender"


# ---------------------------------------------------------------------------
# Substitution plan
# ---------------------------------------------------------------------------

@dataclass
class Substitution:
    """One printed value to paint over and reprint.

    `old_text` / `new_text` are the canonical renderings (ISO for dates,
    plain `1234.56` for money) and are what the plan asserts. For `number` and
    `date` substitutions they are only the *first* candidate: the source PDF
    prints `1.250,00` or `15/07/2026` and `substitute()` searches a list of
    equivalent renderings, then re-formats the new value to match whichever one
    the page actually printed (`format_like`). `old_value` / `new_value` carry
    the typed values that search list is generated from.
    """
    field: str
    old_text: str
    new_text: str
    align: str = "left"
    kind: str = "text"  # "text" | "number" | "date"
    old_value: Any = None
    new_value: Any = None
    #: Extra strings that mean the same printed value, tried in order after
    #: `old_text`. Populated by the planner for numbers and dates.
    old_candidates: list[str] = dc_field(default_factory=list)


def _plain_number(value: Decimal) -> str:
    return f"{value:f}"


def _num_sub(field: str, old: Decimal | None, new: Decimal, dp: int = 2) -> Substitution | None:
    if old is not None and money(old) == money(new):
        return None
    old_q = money(old) if old is not None else None
    return Substitution(
        field=field,
        old_text=_plain_number(old_q) if old_q is not None else "",
        new_text=_plain_number(money(new)),
        align="right",
        kind="number",
        old_value=old_q,
        new_value=money(new),
    )


def plan_substitutions(source: Any, req: BuildRequest, totals: Totals) -> list[Substitution]:
    """Diff the source row against the request, field by field.

    Only *changed* values produce a substitution, which is the whole point: a
    clone that only takes a new number and new dates touches two or three spans
    of the source PDF and leaves every other pixel — logo, layout, fonts, legal
    footer — untouched.
    """
    subs: list[Substitution] = []

    if (req.customer_name or None) != (source.customer_name or None):
        subs.append(Substitution(
            field="customer_name",
            old_text=source.customer_name or "",
            new_text=req.customer_name or "",
            kind="text",
        ))

    if (req.invoice_number or None) != (source.invoice_number or None):
        subs.append(Substitution(
            field="invoice_number",
            old_text=source.invoice_number or "",
            new_text=req.invoice_number or "",
            kind="text",
        ))

    for name in ("invoice_date", "due_date"):
        old = getattr(source, name, None)
        new = getattr(req, name, None)
        if old == new:
            continue
        subs.append(Substitution(
            field=name,
            old_text=old.isoformat() if old else "",
            new_text=new.isoformat() if new else "",
            kind="date",
            old_value=old,
            new_value=new,
        ))

    source_items = [i for i in (source.items or []) if isinstance(i, dict)]
    for idx, item in enumerate(req.items):
        old_item = source_items[idx] if idx < len(source_items) else {}
        old_desc = str(old_item.get("description") or "")
        if (item.description or "") != old_desc:
            subs.append(Substitution(
                field=f"items[{idx}].description",
                old_text=old_desc,
                new_text=item.description or "",
                kind="text",
            ))
        for key, attr in (("quantity", "quantity"), ("unit_price", "unit_price")):
            old_raw = old_item.get(key)
            new_raw = getattr(item, attr)
            if old_raw is None and new_raw is None:
                continue
            sub = _num_sub(
                f"items[{idx}].{key}",
                None if old_raw is None else _q(old_raw),
                _q(new_raw),
            )
            if sub:
                subs.append(sub)
        old_amount = old_item.get("amount")
        new_amount = totals.line_amounts[idx] if idx < len(totals.line_amounts) else Decimal("0.00")
        sub = _num_sub(
            f"items[{idx}].amount",
            None if old_amount is None else _q(old_amount),
            new_amount,
        )
        if sub:
            subs.append(sub)

    for name, new_value in (
        ("subtotal", totals.subtotal),
        ("tax_amount", totals.tax_amount),
        ("grand_total", totals.grand_total),
    ):
        old_raw = getattr(source, name, None)
        sub = _num_sub(name, None if old_raw is None else _q(old_raw), new_value)
        if sub:
            subs.append(sub)

    return subs


def builder_intent(req: BuildRequest, totals: Totals, render_mode: RenderMode) -> dict:
    """What `Invoice.builder_intent` stores: exactly what the builder intended
    to print, so `verify_builder_readback()` can compare it against what the
    extractor read back off the generated PDF. JSON-safe (Decimals become
    strings, dates ISO), because it lands in a JSON column.
    """
    payload = req.model_dump(mode="json")
    payload["totals"] = totals.model_dump(mode="json")
    payload["render_mode"] = render_mode
    return payload
