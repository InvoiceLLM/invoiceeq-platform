"""Feature 17 (Invoice Builder — Clone & Edit): the pure, deterministic core.

An outbound invoice is created by cloning an existing outbound invoice and
editing what changes. Everything in this module is a pure function over the
source `Invoice` row and the user's `BuildRequest` — no database, no PDF, no
LLM. That is deliberate and is CONVENTIONS hard rule 3: totals arithmetic, the
invoice-number increment and the choice of renderer all decide correctness, so
none of them may be a prompt rule. The LLM only ever sees the *generated* PDF,
through the ordinary extraction pipeline, exactly as it sees an upload.

The rendering half lives entirely in `services/pdf_render.py`. There is one
renderer and no choice to make: BE Gap 462 (2026-09-05) deleted the in-place
substitution path and the `plan_render_mode()` that picked between the two.
That planner keyed off row count alone, so the ordinary clone — same rows, new
dates, new totals — committed to substitution and then failed with a 422 it
asked the *user* to work around by adding or removing a row. A clone is now
always a re-render carrying the source's harvested branding; the founder
accepted, explicitly, that it is not a pixel-identical copy of the source.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
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


# --- BE Gap 463: reading the source row's JSON columns ----------------------
#
# `Invoice.addresses`, `.taxes`, `.references` and friends are JSON columns
# written by the extractor. They are trusted for *shape* nowhere: a row that is
# not a dict, a key that is absent, a number that arrived as a string are all
# ordinary and none of them may turn the prefill endpoint into a 500.

def _opt_dec(value: Any) -> Decimal | None:
    """Decimal, or None for absent/blank/unparseable. Never raises."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _opt_str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _src(invoice: Any, name: str) -> Any:
    """One column off the source row, or None when the object does not carry it.

    `invoice` is typed loosely on purpose (see `default_build_from_source`) —
    this module never imports `models`, so it is handed a real `Invoice` in
    production and a plain object in the pure unit tests. `getattr` with a
    default is what keeps both callers valid; a real `Invoice` always has every
    name used here, so this never silently drops a column that exists.
    """
    return getattr(invoice, name, None)


def _rows(raw: Any, model: type[BaseModel]) -> list:
    """Coerce a stored JSON list into `model`, dropping what cannot be read."""
    out: list = []
    for entry in (raw or []):
        if not isinstance(entry, dict):
            continue
        try:
            out.append(model.model_validate(entry))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# The editable surface
# ---------------------------------------------------------------------------

#: BE Gap 463 (2026-09-05): the nested shapes below are copied, field for
#: field, from the extraction schemas in `agents/extraction_agent.py`
#: (`AddressItem`, `ReferenceItem`, `PaymentInstructionItem`, `TaxIdItem`,
#: `TaxItem`, `DiscountItem`, `DeductionItem`, `ComplianceMetadataItem`) —
#: which are the shapes actually stored in the matching `Invoice` JSON columns.
#: Nothing here is invented: a builder field that did not already exist on the
#: model could never be prefilled from a source invoice, and could never be
#: read back off the generated PDF either.
#:
#: Every field is optional and every list defaults empty, so a `BuildRequest`
#: posted by an older client (the pre-463 body: customer, number, dates,
#: currency, items, tax) still validates and still renders exactly as it did.

class BuildAddress(BaseModel):
    """`AddressItem`. `address_type` is 'billing', 'shipping' or 'vendor' —
    the renderer keys its Bill To / Ship To / From blocks off that value."""
    address_type: str = ""
    text: str = ""
    country: str | None = None


class BuildReference(BaseModel):
    """`ReferenceItem` — 'Sales Order', 'e-Way Bill', 'Delivery Note'…"""
    ref_type: str = ""
    value: str = ""


class BuildPaymentInstruction(BaseModel):
    """`PaymentInstructionItem` — how the customer is meant to pay."""
    method_type: str = ""
    details: str = ""


class BuildTaxId(BaseModel):
    """`TaxIdItem`. `party` is 'vendor' or 'buyer' when the source said so."""
    id_type: str = ""
    value: str = ""
    party: str | None = None


class BuildTax(BaseModel):
    """`TaxItem`. `amount` is optional here where the extraction schema makes
    it required: a user editing a CGST 9% line normally changes the *rate* and
    expects the amount to follow, so `compute_totals()` derives it from
    `rate_percent` when it is left blank. A supplied amount always wins — a
    printed tax figure that does not reconcile is a real thing invoices do, and
    this feature never silently corrects one."""
    tax_type: str = ""
    rate_percent: Decimal | None = None
    amount: Decimal | None = None


class BuildDiscount(BaseModel):
    """`DiscountItem`, with the same optional-`amount` rule as `BuildTax`."""
    discount_type: str = ""
    percent: Decimal | None = None
    amount: Decimal | None = None


class BuildDeduction(BaseModel):
    """`DeductionItem` — retention, an advance already received. Always an
    absolute figure; the extraction schema carries no percent for these."""
    deduction_type: str = ""
    amount: Decimal | None = None


class BuildComplianceItem(BaseModel):
    """`ComplianceMetadataItem` — IRN, QR payload, Peppol address, SDI code."""
    key: str = ""
    value: str = ""


class BuildItem(BaseModel):
    """One editable line. `amount` is deliberately absent: the client never
    sends a line total, the server always computes it (`compute_totals`).

    BE Gap 463: widened to the rest of `InvoiceLineItem`'s printable surface —
    HSN/SAC, unit of measure, and the per-line discount/tax pairs. These are
    real keys in the `Invoice.items` JSON (written by inbound extraction, which
    is the same shared column), so `default_build_from_source()` copies
    whichever of them the source row actually carries and leaves the rest None.
    A line that carries none of them renders and totals exactly as before.
    """
    description: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    hsn_sac_code: str | None = None
    uom: str | None = None
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None
    tax_percent: Decimal | None = None
    tax_amount: Decimal | None = None


class BuildRequest(BaseModel):
    """Everything a user may change when cloning.

    BE Gap 463 (2026-09-05), founder-approved: "while building new invoice from
    an existing user can change everything… so all the fields address, anything
    thats there in the invoice". Before this the editable set was customer,
    number, dates, currency, items and one tax figure — which was survivable
    while BE Gap 462's substitution renderer painted the new values onto the
    source page and left everything else printed exactly where it was. Once
    substitution was deleted and every clone became a re-render, a field this
    model does not carry stopped being *inherited* and started being *lost*:
    it survived only if `harvest_branding()` happened to lift it into the
    header or footer band. So this widening is what puts addresses, PO number,
    references, payment instructions, tax IDs and compliance metadata back on
    the page at all, not merely what makes them editable.

    The field names and shapes are the `Invoice` model's own (models.py) —
    `vendor_name`, `po_number`, `addresses`, `references`,
    `payment_instructions`, `tax_ids`, `taxes`, `discounts`, `deductions`,
    `discount_percent`, `discount_amount`, `compliance_metadata`.

    `notes` used to be the one field with no column behind it — Gap 463 kept it
    in `builder_intent` only, and recorded the consequence honestly: it was not
    read back, and cloning a clone did not carry it forward. **BE Gap 467
    (2026-09-05) closes that**: `Invoice.notes` is a real nullable column, the
    outbound extraction schema reads the printed notes block back, and
    `default_build_from_source()` copies it like every other field. It is still
    also written into `builder_intent` (the whole request is), which is where
    the review screen reads it from.

    Still inherited, and still not listed here: the logo, the letterhead and
    the legal footer, which come from the source PDF via `harvest_branding()`.
    """
    source_invoice_id: UUID
    customer_name: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    currency: str | None = None
    items: list[BuildItem] = Field(default_factory=list)
    tax_amount: Decimal | None = None
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None
    addresses: list[BuildAddress] = Field(default_factory=list)
    references: list[BuildReference] = Field(default_factory=list)
    payment_instructions: list[BuildPaymentInstruction] = Field(default_factory=list)
    tax_ids: list[BuildTaxId] = Field(default_factory=list)
    taxes: list[BuildTax] = Field(default_factory=list)
    discounts: list[BuildDiscount] = Field(default_factory=list)
    deductions: list[BuildDeduction] = Field(default_factory=list)
    compliance_metadata: list[BuildComplianceItem] = Field(default_factory=list)
    notes: str | None = None


class Totals(BaseModel):
    """Server-computed totals. Never read from the request.

    BE Gap 463 added everything except `line_amounts`/`subtotal`/`tax_amount`/
    `grand_total`, whose meanings are unchanged. `line_amounts` is still what
    the Amount column prints and still what `verify_builder_readback()`
    compares against the extractor's per-line `amount` — it is now *net of any
    per-line discount*, which is the same number as before for every line that
    has no per-line discount (i.e. every line that existed before this change).
    """
    line_amounts: list[Decimal] = Field(default_factory=list)
    #: Per-line, index-aligned with `line_amounts`. All 0.00 when unused.
    line_discounts: list[Decimal] = Field(default_factory=list)
    line_taxes: list[Decimal] = Field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    #: Resolved amount for each entry in `BuildRequest.discounts`, index-aligned.
    discount_lines: list[Decimal] = Field(default_factory=list)
    discount_total: Decimal = Decimal("0.00")
    #: Resolved amount for each entry in `BuildRequest.taxes`, index-aligned.
    tax_lines: list[Decimal] = Field(default_factory=list)
    tax_amount: Decimal = Decimal("0.00")
    deduction_lines: list[Decimal] = Field(default_factory=list)
    deduction_total: Decimal = Decimal("0.00")
    grand_total: Decimal = Decimal("0.00")


def _pct(base: Decimal, percent: Decimal | None) -> Decimal:
    """`round(base × percent ÷ 100, 2)`, half-up. One place, because a second
    spelling of this is how the FE mirror and the server come to disagree."""
    return money(base * _q(percent) / Decimal("100"))


def compute_totals(
    items: list[BuildItem],
    tax_amount: Decimal | None,
    *,
    discount_percent: Decimal | None = None,
    discount_amount: Decimal | None = None,
    taxes: list[BuildTax] | None = None,
    discounts: list[BuildDiscount] | None = None,
    deductions: list[BuildDeduction] | None = None,
) -> Totals:
    """The only authority on what a built invoice totals. Decimal, half-up,
    deterministic — never a prompt rule (CONVENTIONS hard rule 3), and never
    read from the client, which is why `BuildRequest` has no total field.

    Per line:
        gross      = round(qty × unit_price, 2)
        discount   = discount_amount, else round(gross × discount_percent/100, 2), else 0
        amount     = gross − discount          ← what the Amount column prints
        line tax   = tax_amount, else round(amount × tax_percent/100, 2), else 0

    Then:
        subtotal        = Σ amount
        discount_total  = Σ discounts[]        (each: amount, else % of subtotal)
                          else invoice discount_amount
                          else round(subtotal × discount_percent/100, 2)
                          else 0
        taxable base    = subtotal − discount_total
        tax_amount      = Σ taxes[]            (each: amount, else % of the base)
                          else the invoice-level `tax_amount` argument
                          else Σ line tax
                          else 0
        deduction_total = Σ deductions[]
        grand_total     = subtotal − discount_total + tax_amount − deduction_total

    When a `taxes` list is given, it is the invoice's tax — the per-line tax
    column is then informational only (an Indian GST invoice prints both, and
    the two disagree by design once an invoice-level discount moves the base).
    The per-line figures are only summed into the total when nothing else says
    what the tax is.

    **An explicitly supplied amount always wins over a percentage**, at every
    level. Invoices routinely print a tax or discount figure that does not
    reconcile with its own stated rate, and this feature transcribes what the
    user entered rather than correcting it — the same rule the extractor
    follows (Gap 46's verbatim directive) and the same reason the read-back
    check exists at all.

    Backward compatibility is exact: with no discounts, no deductions and no
    `taxes` list, this reduces to the pre-Gap-463 `Σ round(qty × price)` +
    `tax_amount`, digit for digit.

    A missing quantity or unit price contributes a 0.00 line rather than
    raising: the FE grid can hold a half-typed row and a preview must still
    render something rather than 500.
    """
    line_amounts: list[Decimal] = []
    line_discounts: list[Decimal] = []
    line_taxes: list[Decimal] = []
    for item in items:
        gross = money(_q(item.quantity) * _q(item.unit_price))
        if item.discount_amount is not None:
            discount = money(item.discount_amount)
        elif item.discount_percent is not None:
            discount = _pct(gross, item.discount_percent)
        else:
            discount = Decimal("0.00")
        amount = money(gross - discount)
        if item.tax_amount is not None:
            line_tax = money(item.tax_amount)
        elif item.tax_percent is not None:
            line_tax = _pct(amount, item.tax_percent)
        else:
            line_tax = Decimal("0.00")
        line_amounts.append(amount)
        line_discounts.append(discount)
        line_taxes.append(line_tax)

    subtotal = money(sum(line_amounts, Decimal("0")))

    discount_lines: list[Decimal] = []
    for entry in (discounts or []):
        if entry.amount is not None:
            discount_lines.append(money(entry.amount))
        else:
            discount_lines.append(_pct(subtotal, entry.percent))
    if discount_lines:
        discount_total = money(sum(discount_lines, Decimal("0")))
    elif discount_amount is not None:
        discount_total = money(discount_amount)
    elif discount_percent is not None:
        discount_total = _pct(subtotal, discount_percent)
    else:
        discount_total = Decimal("0.00")

    taxable_base = money(subtotal - discount_total)
    tax_lines: list[Decimal] = []
    for entry in (taxes or []):
        if entry.amount is not None:
            tax_lines.append(money(entry.amount))
        else:
            tax_lines.append(_pct(taxable_base, entry.rate_percent))
    if tax_lines:
        tax_total = money(sum(tax_lines, Decimal("0")))
    elif tax_amount is not None:
        tax_total = money(tax_amount)
    else:
        tax_total = money(sum(line_taxes, Decimal("0")))

    deduction_lines = [money(d.amount) for d in (deductions or [])]
    deduction_total = money(sum(deduction_lines, Decimal("0")))

    return Totals(
        line_amounts=line_amounts,
        line_discounts=line_discounts,
        line_taxes=line_taxes,
        subtotal=subtotal,
        discount_lines=discount_lines,
        discount_total=discount_total,
        tax_lines=tax_lines,
        tax_amount=tax_total,
        deduction_lines=deduction_lines,
        deduction_total=deduction_total,
        grand_total=money(subtotal - discount_total + tax_total - deduction_total),
    )


def totals_for(req: BuildRequest) -> Totals:
    """`compute_totals()` over a whole request — what the endpoints call, so
    that adding a totals-bearing field to `BuildRequest` cannot be forgotten at
    one of the two call sites (BE Gap 463)."""
    return compute_totals(
        req.items,
        req.tax_amount,
        discount_percent=req.discount_percent,
        discount_amount=req.discount_amount,
        taxes=req.taxes,
        discounts=req.discounts,
        deductions=req.deductions,
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
                quantity=_opt_dec(raw.get("quantity")),
                unit_price=_opt_dec(raw.get("unit_price")),
                # BE Gap 463: present on `InvoiceLineItem`, so present in the
                # shared `Invoice.items` JSON whenever the source carried them.
                # An OUTBOUND row extracted by `OutboundInvoiceLineItem` has
                # none of these keys and every one comes back None — copied
                # when there, never invented when not.
                hsn_sac_code=_opt_str(raw.get("hsn_sac_code")),
                uom=_opt_str(raw.get("uom")),
                discount_percent=_opt_dec(raw.get("discount_percent")),
                discount_amount=_opt_dec(raw.get("discount_amount")),
                tax_percent=_opt_dec(raw.get("tax_percent")),
                tax_amount=_opt_dec(raw.get("tax_amount")),
            )
        )

    return BuildRequest(
        source_invoice_id=invoice.id,
        customer_name=invoice.customer_name,
        # BE Gap 463: everything from here down is new. All of it comes off the
        # source row's own columns; a column the source never populated copies
        # as None or an empty list, which renders as nothing rather than as a
        # placeholder the user has to delete.
        vendor_name=_src(invoice, "vendor_name"),
        invoice_number=next_invoice_number(invoice.invoice_number),
        invoice_date=today,
        due_date=(today + term) if term is not None else None,
        po_number=_src(invoice, "po_number"),
        currency=invoice.currency,
        items=items,
        tax_amount=_opt_dec(invoice.tax_amount),
        discount_percent=_opt_dec(_src(invoice, "discount_percent")),
        discount_amount=_opt_dec(_src(invoice, "discount_amount")),
        addresses=_rows(_src(invoice, "addresses"), BuildAddress),
        references=_rows(_src(invoice, "references"), BuildReference),
        payment_instructions=_rows(_src(invoice, "payment_instructions"), BuildPaymentInstruction),
        tax_ids=_rows(_src(invoice, "tax_ids"), BuildTaxId),
        taxes=_rows(_src(invoice, "taxes"), BuildTax),
        discounts=_rows(_src(invoice, "discounts"), BuildDiscount),
        deductions=_rows(_src(invoice, "deductions"), BuildDeduction),
        compliance_metadata=_rows(_src(invoice, "compliance_metadata"), BuildComplianceItem),
        # BE Gap 467: `Invoice.notes` now exists, so the notes block is copied
        # off the source row like every other field here. Gap 463 had to pass
        # None: there was no column, so a clone of a clone lost the notes the
        # user typed one generation earlier.
        notes=_opt_str(_src(invoice, "notes")),
    )


def builder_intent(req: BuildRequest, totals: Totals) -> dict:
    """What `Invoice.builder_intent` stores: exactly what the builder intended
    to print, so `verify_builder_readback()` can compare it against what the
    extractor read back off the generated PDF. JSON-safe (Decimals become
    strings, dates ISO), because it lands in a JSON column.
    """
    payload = req.model_dump(mode="json")
    payload["totals"] = totals.model_dump(mode="json")
    #: Always `"rerender"` since BE Gap 462 deleted the substitution path. The
    #: key is kept rather than dropped because `verify_builder_readback()` and
    #: the review screen already read it off stored rows, including rows written
    #: before the deletion.
    payload["render_mode"] = "rerender"
    return payload
