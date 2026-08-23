"""The clean document set: one spec per invoice, ground truth computed not typed.

Why a spec object and a renderer rather than a folder of PDFs
-------------------------------------------------------------
`tests/benchmark/generator.py` already generates invoice PDFs, and it was read
before this module was written rather than duplicated by accident. It is not
reusable here for two reasons, both structural:

  1. It renders straight to a PDF and its consumer (`tests/benchmark/
     run_benchmark.py`) uploads through the live `/invoices/upload` HTTP
     endpoint, so it needs a running API, Postgres, Azure Blob and Document
     Intelligence. This track has to be runnable as a plain script (and, in
     verify-only mode, as a pytest) against nothing but the extraction module.
  2. Its ground truth is six scalar fields. Field-level accuracy needs the whole
     extracted record — line items included — because the line-item checks are
     three of the ten alert types being measured.

So the unit here is an `InvoiceSpec`: the invoice as data. From one spec we
derive **both** halves of a benchmark case, and derive them from the same
numbers, which is the point:

  * `render_ocr_text()` — the OCR text the extraction pipeline is fed. Shaped
    like Azure Document Intelligence's `content` output for a PDF invoice
    (header block, a pipe-free column-aligned line-item table, a totals block),
    because that is what `agents/extraction_agent.py` actually receives in
    production.
  * `ground_truth()` — the known-correct extraction of that same text.

There is therefore no transcription step in which the ground truth could drift
from the document. A mutation (see `mutations.py`) changes one of the two and
records exactly which, which is what makes "the planted issue" a precise claim
rather than a description.

Honest limits of this corpus, stated here rather than found later
------------------------------------------------------------------
  * **Text only.** The real pipeline also sends page images to the model when
    `LLM_PROVIDER=azure` and images are present. These cases have no PDF, so the
    live mode exercises the text-prompt branch of `extract_node`. That is a real
    branch (it is the non-Azure and no-image path), but it is not the full
    multimodal one, and an accuracy figure from here is not a claim about
    multimodal extraction.
  * **Synthetic vendors, synthetic numbers.** Nothing here is customer data, by
    construction — which is also why this corpus can be committed while
    `tests/{us,india,eu}` cannot.
  * **Clean means internally consistent, not "easy".** The four specs
    deliberately span US flat sales tax, Indian CGST/SGST with a round-off line,
    an EU reverse-charge zero-VAT invoice (a real past failure mode: zero tax
    that is *correct*, not missing), and an outbound invoice with a trade
    discount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineSpec:
    """One printed line-item row.

    `amount` is stated explicitly rather than computed so a spec can express a
    genuinely mis-printed line (the vendor's own arithmetic being wrong is a
    real thing invoices do). For every spec in `CLEAN_DOCUMENTS` it does equal
    the arithmetic — that is what makes them clean.
    """

    description: str
    quantity: float
    unit_price: float
    amount: float
    hsn_sac_code: Optional[str] = None
    tax_percent: Optional[float] = None


@dataclass(frozen=True)
class TaxLineSpec:
    """One printed tax component (CGST 9%, SGST 9%, VAT 20%, ...)."""

    tax_type: str
    rate_percent: Optional[float]
    amount: float


@dataclass(frozen=True)
class InvoiceSpec:
    """One invoice, as data. Renders to OCR text and to its own ground truth."""

    doc_id: str
    flow_direction: str  # "INBOUND" | "OUTBOUND"
    region: str
    currency: str
    #: The party the extraction schema names: `vendor_name` on an INBOUND
    #: document, `customer_name` on an OUTBOUND one. Always the graded field.
    party_name: str
    party_address: str
    #: The other side. The buyer on an INBOUND document, the issuing tenant on
    #: an OUTBOUND one. Never graded — neither schema has a field for it.
    counterparty_name: str
    invoice_number: str
    invoice_date: str
    due_date: str
    lines: tuple[LineSpec, ...]
    subtotal: float
    tax_amount: float
    grand_total: float
    taxes: tuple[TaxLineSpec, ...] = ()
    po_number: Optional[str] = None
    round_off: Optional[float] = None
    discount_amount: Optional[float] = None
    discount_percent: Optional[float] = None
    tax_ids: tuple[tuple[str, str, str], ...] = ()  # (id_type, value, party)
    notes: tuple[str, ...] = ()
    #: Free prose describing what makes this document non-trivial. Copied into
    #: the review manifest so a reviewer sees the intent, not just the numbers.
    rationale: str = ""

    # -- rendering ---------------------------------------------------------

    def render_ocr_text(self) -> str:
        """The OCR text the extraction pipeline is fed.

        Column-aligned rather than pipe-delimited on purpose: Document
        Intelligence's `content` field emits table cells as whitespace-separated
        runs, and the source-text faithfulness checks
        (`verify_*_in_source_text`) tokenise on whitespace-adjacent numbers. A
        markdown table here would make those checks easier than they are in
        production.
        """
        money = lambda v: f"{v:,.2f}"  # noqa: E731 - local formatting alias
        out: list[str] = []
        inbound = self.flow_direction == "INBOUND"
        out.append(self.party_name if inbound else self.counterparty_name)
        if inbound:
            out.append(self.party_address)
        for id_type, value, _party in self.tax_ids:
            out.append(f"{id_type}: {value}")
        out.append("")
        out.append("TAX INVOICE")
        out.append(f"Invoice Number: {self.invoice_number}")
        out.append(f"Invoice Date: {self.invoice_date}")
        out.append(f"Due Date: {self.due_date}")
        if self.po_number:
            out.append(f"PO Number: {self.po_number}")
        out.append("")
        if inbound:
            out.append(f"Bill To: {self.counterparty_name}")
        else:
            out.append(f"Bill To: {self.party_name}")
            out.append(self.party_address)
        out.append("")

        header = ["#", "Description", "HSN/SAC", "Qty", "Unit Price", "Tax %", f"Amount ({self.currency})"]
        out.append("   ".join(header))
        for idx, line in enumerate(self.lines, start=1):
            out.append(
                "   ".join(
                    [
                        str(idx),
                        line.description,
                        line.hsn_sac_code or "-",
                        f"{line.quantity:g}",
                        money(line.unit_price),
                        (f"{line.tax_percent:g}" if line.tax_percent is not None else "-"),
                        money(line.amount),
                    ]
                )
            )
        out.append("")
        out.append(f"Subtotal: {self.currency} {money(self.subtotal)}")
        if self.discount_amount is not None:
            label = (
                f"Discount ({self.discount_percent:g}%)"
                if self.discount_percent is not None
                else "Discount"
            )
            out.append(f"{label}: -{self.currency} {money(self.discount_amount)}")
        for tax in self.taxes:
            rate = f" @ {tax.rate_percent:g}%" if tax.rate_percent is not None else ""
            out.append(f"{tax.tax_type}{rate}: {self.currency} {money(tax.amount)}")
        if not self.taxes:
            out.append(f"Tax: {self.currency} {money(self.tax_amount)}")
        if self.round_off is not None:
            out.append(f"Round Off: {self.currency} {money(self.round_off)}")
        out.append(f"TOTAL DUE: {self.currency} {money(self.grand_total)}")
        out.append("")
        for note in self.notes:
            out.append(note)
        return "\n".join(out)

    # -- ground truth ------------------------------------------------------

    def ground_truth(self) -> dict[str, Any]:
        """The known-correct extraction of `render_ocr_text()`.

        Shaped as the extraction schema's own field names (inbound
        `InvoiceExtractionSchema` / outbound `OutboundInvoiceExtractionSchema`)
        so a comparison against a real extraction is field-for-field with no
        translation layer in between.
        """
        items = [
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount": line.amount,
            }
            for line in self.lines
        ]
        truth: dict[str, Any] = {
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "due_date": self.due_date,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
            "currency": self.currency,
            "items": items,
        }
        if self.flow_direction == "OUTBOUND":
            truth["customer_name"] = self.party_name
        else:
            truth["vendor_name"] = self.party_name
            truth["po_number"] = self.po_number
            truth["round_off"] = self.round_off
            truth["discount_amount"] = self.discount_amount
        return truth

    def initial_extraction(self) -> dict[str, Any]:
        """A perfect extraction, as `extract_node` would return it.

        This is what verify-only mode feeds `verify_node` for a clean case, and
        what a `field` mutation edits for a seeded one. Distinct from
        `ground_truth()` only in that it also carries the fields the extraction
        schema has but the accuracy comparison does not grade (`taxes`, the
        per-line HSN/tax columns), because `verify_node` reads some of them —
        `verify_tax_amount_in_source_text` consults `taxes` for its
        component-aware fallback.
        """
        data = dict(self.ground_truth())
        data["items"] = [
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount": line.amount,
                "hsn_sac_code": line.hsn_sac_code,
                "tax_percent": line.tax_percent,
            }
            for line in self.lines
        ]
        data["taxes"] = [
            {"tax_type": t.tax_type, "rate_percent": t.rate_percent, "amount": t.amount}
            for t in self.taxes
        ]
        if self.flow_direction == "INBOUND":
            data["discount_percent"] = self.discount_percent
        return data


# ---------------------------------------------------------------------------
# The clean set
# ---------------------------------------------------------------------------
# Four documents. Each is internally consistent: every line amount equals
# qty x unit_price, the line amounts sum to the subtotal (or to subtotal + tax
# under the Indian post-tax convention `verify_line_items_math` also accepts),
# and subtotal - discount + tax + round_off equals the grand total. Every number
# that appears in `ground_truth()` is printed verbatim somewhere in
# `render_ocr_text()`, so all five source-text faithfulness checks must stay
# silent on all four.


_US_FLAT_TAX = InvoiceSpec(
    doc_id="us_flat_sales_tax",
    flow_direction="INBOUND",
    region="US",
    currency="USD",
    party_name="Cascade Industrial Supply LLC",
    party_address="1180 Wharf Street, Seattle, WA 98101, United States",
    counterparty_name="Northwind Manufacturing Inc.",
    invoice_number="CIS-2026-4417",
    invoice_date="2026-07-14",
    due_date="2026-08-13",
    po_number="PO-58213",
    lines=(
        LineSpec("Hex bolts M12 x 60mm, galvanised", 480, 1.25, 600.00),
        LineSpec("Structural steel angle 50x50x5, 6m", 24, 138.50, 3324.00),
        LineSpec("Welding consumables, ER70S-6 spool", 12, 96.75, 1161.00),
    ),
    subtotal=5085.00,
    tax_amount=432.23,
    grand_total=5517.23,
    taxes=(TaxLineSpec("Sales Tax", 8.5, 432.23),),
    notes=("Payment terms: net 30 from invoice date. Remit by ACH.",),
    rationale=(
        "The baseline shape: single invoice-level flat sales tax, no discount, "
        "no per-line tax. If any check fires here the check is miscalibrated."
    ),
)

_INDIA_GST_SPLIT = InvoiceSpec(
    doc_id="india_cgst_sgst_round_off",
    flow_direction="INBOUND",
    region="INDIA",
    currency="INR",
    party_name="Rajesh Steel Traders Pvt Ltd",
    party_address="Plot 42, MIDC Industrial Area, Pune 411019, Maharashtra, India",
    counterparty_name="Deccan Fabricators Pvt Ltd",
    invoice_number="RST-2627-0091",
    invoice_date="2026-07-22",
    due_date="2026-08-21",
    lines=(
        LineSpec("TMT reinforcement bars Fe500D 12mm", 8, 5400.00, 43200.00, hsn_sac_code="7214", tax_percent=18),
        LineSpec("MS plate 10mm, cut to size", 5, 7800.00, 39000.00, hsn_sac_code="7208", tax_percent=18),
        LineSpec("Freight and handling", 1, 4300.00, 4300.00, hsn_sac_code="9965", tax_percent=18),
    ),
    subtotal=86500.00,
    tax_amount=15570.00,
    grand_total=102070.00,
    taxes=(
        TaxLineSpec("CGST", 9.0, 7785.00),
        TaxLineSpec("SGST", 9.0, 7785.00),
    ),
    round_off=0.00,
    tax_ids=(
        ("GSTIN", "27AABCR1234M1ZP", "vendor"),
        ("GSTIN", "27AAECD5678Q1Z9", "buyer"),
    ),
    notes=(
        "Reverse charge applicable: No",
        "Payment terms: net 30. Interest at 1.5% per month on overdue amounts.",
    ),
    rationale=(
        "The split-tax shape Gaps 263/264 are about: two printed components "
        "(CGST 9% + SGST 9%) that must be summed into one `tax_amount` of "
        "15,570.00 -- a figure that is NOT printed anywhere as a single number. "
        "This is the case `verify_tax_amount_in_source_text`'s component-aware "
        "fallback (Gap 69) exists for, so it is also the case that would "
        "false-positive if that fallback ever broke."
    ),
)

_EU_REVERSE_CHARGE = InvoiceSpec(
    doc_id="eu_reverse_charge_zero_vat",
    flow_direction="INBOUND",
    region="EU",
    currency="EUR",
    party_name="Nordlicht Datentechnik GmbH",
    party_address="Hafenstrasse 88, 20359 Hamburg, Germany",
    counterparty_name="Meridian Analytics BV",
    invoice_number="NDT-2026-00612",
    invoice_date="2026-06-30",
    due_date="2026-07-30",
    po_number="PO-EU-3391",
    lines=(
        LineSpec("Data platform engineering, senior consultant", 96, 145.00, 13920.00, tax_percent=0),
        LineSpec("Platform licence, quarterly", 1, 4250.00, 4250.00, tax_percent=0),
    ),
    subtotal=18170.00,
    tax_amount=0.00,
    grand_total=18170.00,
    taxes=(TaxLineSpec("VAT", 0.0, 0.00),),
    tax_ids=(
        ("EU VAT", "DE811234567", "vendor"),
        ("EU VAT", "NL004567890B01", "buyer"),
    ),
    notes=(
        "Reverse charge - VAT to be accounted for by the recipient under Article 196 of "
        "Council Directive 2006/112/EC.",
        "Payment terms: net 30 days.",
    ),
    rationale=(
        "Zero tax that is CORRECT, not missing -- the reverse-charge case the "
        "persona rubric in `services/agent_eval.py` already names as a real past "
        "failure. A benchmark that only contains taxed invoices cannot tell a "
        "correctly-zero tax from a dropped one."
    ),
)

_OUTBOUND_DISCOUNT = InvoiceSpec(
    doc_id="outbound_trade_discount",
    flow_direction="OUTBOUND",
    region="US",
    currency="USD",
    party_name="Ridgeway Components Corp.",  # the customer -> `customer_name`
    party_address="4400 Halsey Boulevard, Columbus, OH 43215, United States",
    counterparty_name="Meridian Analytics BV",  # the issuing tenant, never graded
    invoice_number="OUT-2026-0308",
    invoice_date="2026-07-09",
    due_date="2026-08-08",
    lines=(
        LineSpec("Managed integration service, July 2026", 1, 9600.00, 9600.00),
        LineSpec("Additional connector seats", 15, 120.00, 1800.00),
    ),
    subtotal=11400.00,
    discount_amount=570.00,
    discount_percent=5.0,
    tax_amount=758.10,
    grand_total=11588.10,
    taxes=(TaxLineSpec("Sales Tax", 7.0, 758.10),),
    notes=("Payment terms: net 30. Late payments subject to 1.5% monthly interest.",),
    rationale=(
        "The only OUTBOUND document in the set, and the only one where "
        "`missing_required_field` can fire at all -- `_DIRECTION_PROFILES`' "
        "`required_fields` is empty for INBOUND by design. It also carries a 5% "
        "trade discount, which is arithmetically consistent on the document "
        "(11,400.00 - 570.00 + 758.10 = 11,588.10) but which "
        "`OutboundInvoiceExtractionSchema` has no field for -- see "
        "`docs/extraction_benchmark/README.md`, 'What the first run found'. "
        "This case is deliberately left in the clean set rather than "
        "sanitised: it is the only reason the false-positive rate is a "
        "measurement rather than a formality."
    ),
)


CLEAN_DOCUMENTS: tuple[InvoiceSpec, ...] = (
    _US_FLAT_TAX,
    _INDIA_GST_SPLIT,
    _EU_REVERSE_CHARGE,
    _OUTBOUND_DISCOUNT,
)

CLEAN_BY_ID: dict[str, InvoiceSpec] = {spec.doc_id: spec for spec in CLEAN_DOCUMENTS}


__all__ = [
    "CLEAN_BY_ID",
    "CLEAN_DOCUMENTS",
    "InvoiceSpec",
    "LineSpec",
    "TaxLineSpec",
]
