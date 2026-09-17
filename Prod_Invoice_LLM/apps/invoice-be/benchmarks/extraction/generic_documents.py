"""BE Gap 687: extraction ground truth for non-invoice document types.

Before this module the benchmark had four `InvoiceSpec` instances and no
equivalent for anything else, so field-level extraction accuracy, line-item
parsing and alert recall were measurable **for invoices only**. A regression in
delivery-note, purchase-order, credit-note, GRN or quotation extraction was
undetectable before deployment.

── The number that must not be misread ───────────────────────────────────────

`tests/fixtures/doc_types/MANIFEST.md` records 16 fixtures taking **classification**
coverage to every type in the taxonomy. Those exercise `classify_doc_type()` --
"is this a delivery note?" -- and say nothing about whether the fields were read
off it correctly. Classification coverage and extraction coverage are two
numbers and they have been read as one. This module is the second one.

── Scope, stated rather than assumed ─────────────────────────────────────────

`DOC_TYPES` currently holds **15 values** (it grew from 10 when `BANK_STATEMENT`
was split out under BE Gap 516.1 on 2026-09-14), so BE Gap 687's filed text --
"10 doc types, 1/10 with extraction ground truth" -- is stale: it is 14
non-invoice types.

The five specs below are **not** an arbitrary five. Each one exercises a
structural shape that `GenericDocumentSchema` has fields for and
`InvoiceExtractionSchema` does not, and between them they cover every such shape:

  * `in_delivery_note_unpriced`   -- no prices *at all*: `currency`, `subtotal`,
    `grand_total`, `unit_price` and `amount` must all come back null. This is the
    shape `prebuilt-invoice` force-fits into an invoice, inventing a
    `VendorName`/`InvoiceTotal` that the document does not print.
  * `us_purchase_order_priced`    -- priced, with `po_number` equal to
    `doc_number`, plus `incoterms` and `delivery_terms`.
  * `eu_credit_note_negative`     -- every figure negative, with
    `reference_numbers` citing the invoice it adjusts. Pins sign preservation.
  * `in_grn_three_quantity_columns` -- `quantity_ordered`, `quantity_delivered`
    and `quantity_received` printed side by side on each row.
  * `in_quotation_with_validity`  -- `valid_until` printed explicitly, which the
    schema forbids deriving from `doc_date`, plus a CGST/SGST split.

**Priority note:** the remaining nine types are a deliberate gap, not an
oversight. Which of them to author next should follow production volume per
`doc_type` -- authoring ground truth is the slowest work in this area and doing
it for types nobody uploads buys nothing. Adding one is mechanical from here:
write a `DocumentSpec`, add it to `CLEAN_GENERIC_DOCUMENTS`, and the harness and
the shape tests pick it up automatically.

── Why a separate tuple from `CLEAN_DOCUMENTS` ───────────────────────────────

`tests/test_extraction_benchmark.py` parametrises invoice-specific assertions
over `CLEAN_DOCUMENTS` -- `sum(line.amount) == spec.subtotal`,
`line.quantity * line.unit_price == line.amount`. A delivery note prints no
prices, so it would fail those by design. These live in
`CLEAN_GENERIC_DOCUMENTS`, and `ALL_CLEAN_DOCUMENTS` is the union for callers
that want everything.
"""

from dataclasses import dataclass
from typing import Any, Optional

from benchmarks.extraction.documents import TaxLineSpec

__all__ = [
    "ALL_CLEAN_DOCUMENTS",
    "CLEAN_GENERIC_BY_ID",
    "CLEAN_GENERIC_DOCUMENTS",
    "DocumentSpec",
    "GenericLineSpec",
]


@dataclass(frozen=True)
class GenericLineSpec:
    """One printed row on a non-invoice document.

    Every money field is optional, which is the whole point: a delivery note row
    is a part number and a quantity, a GRN row is three quantities and no price,
    and a contract line may be a rate with no total. `LineSpec` in
    `documents.py` requires `quantity`, `unit_price` and `amount` because an
    invoice line always prints all three.
    """

    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    quantity_ordered: Optional[float] = None
    quantity_delivered: Optional[float] = None
    quantity_received: Optional[float] = None
    uom: Optional[str] = None
    batch_or_serial: Optional[str] = None


@dataclass(frozen=True)
class DocumentSpec:
    """One non-invoice document, as data. Renders to OCR text and ground truth.

    Offers the same three methods the harness asks of `InvoiceSpec`
    (`render_ocr_text`, `ground_truth`, `initial_extraction`) plus `doc_id` and
    `flow_direction`, so `run_clean_case` and `score_clean_run` need no special
    casing -- see `ExtractionSpec` in `harness.py`.

    **`flow_direction` is `"INBOUND"`, not `"GENERIC"`.** This is easy to get
    wrong: `_DIRECTION_PROFILES` does contain a `"GENERIC"` entry, but
    `resolve_direction_profile("GENERIC")` raises `UnknownFlowDirectionError` on
    purpose (`agents/extraction_agent.py:1495`) -- `"GENERIC"` is not a value a
    caller may pass. The generic profile is selected *downstream*, by
    `resolve_extraction_profile(flow_direction, doc_type)`, which returns it for
    an INBOUND document whose `doc_type` is a known non-invoice value while
    `ENABLE_GENERIC_EXTRACTION` is on. So the routing is carried by `doc_type`,
    and `flow_direction` stays `"INBOUND"` because that is what these documents
    are: things arriving at the tenant.
    """

    doc_id: str
    doc_type: str
    region: str
    #: The party that ISSUED the document, per `GenericDocumentSchema.party_name`.
    party_name: str
    party_address: str
    #: The party it is ADDRESSED TO. Graded -- the generic schema has a field for
    #: it, unlike either invoice schema.
    counterparty_name: str
    doc_number: str
    doc_date: str
    lines: tuple[GenericLineSpec, ...]
    currency: Optional[str] = None
    po_number: Optional[str] = None
    reference_numbers: tuple[str, ...] = ()
    valid_until: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    grand_total: Optional[float] = None
    freight_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    taxes: tuple[TaxLineSpec, ...] = ()
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    incoterms: Optional[str] = None
    notes: Optional[str] = None
    #: Free prose on what makes this document non-trivial, copied into the review
    #: manifest so a reviewer sees the intent rather than only the numbers.
    rationale: str = ""

    @property
    def flow_direction(self) -> str:
        return "INBOUND"

    # -- rendering ---------------------------------------------------------

    def render_ocr_text(self) -> str:
        """The OCR text the pipeline is fed.

        Column-aligned rather than pipe-delimited, for the same reason
        `InvoiceSpec.render_ocr_text` is: Document Intelligence emits table cells
        as whitespace-separated runs, and the source-text faithfulness checks
        tokenise on whitespace-adjacent numbers. A markdown table would make
        those checks easier than they are in production.

        Every figure in `ground_truth()` is printed here verbatim, including
        negative signs -- `test_generic_documents.py` asserts exactly that.
        """
        money = lambda v: f"{v:,.2f}"  # noqa: E731 - local formatting alias
        cur = self.currency or ""
        out: list[str] = [self.party_name, self.party_address, ""]
        out.append(self.doc_type.replace("_", " "))
        out.append(f"Document Number: {self.doc_number}")
        out.append(f"Date: {self.doc_date}")
        if self.valid_until:
            out.append(f"Valid Until: {self.valid_until}")
        if self.po_number:
            out.append(f"PO Number: {self.po_number}")
        for ref in self.reference_numbers:
            out.append(f"Reference: {ref}")
        out.append("")
        out.append(f"To: {self.counterparty_name}")
        out.append("")

        priced = any(line.unit_price is not None for line in self.lines)
        qty_columns = any(line.quantity_ordered is not None for line in self.lines)

        header = ["#", "Description"]
        if qty_columns:
            header += ["Ordered", "Delivered", "Received"]
        else:
            header += ["Qty"]
        header += ["UOM"]
        if any(line.batch_or_serial for line in self.lines):
            header += ["Batch/Serial"]
        if priced:
            header += ["Unit Price", f"Amount ({cur})"]
        out.append("   ".join(header))

        for idx, line in enumerate(self.lines, start=1):
            row = [str(idx), line.description]
            if qty_columns:
                row += [
                    f"{line.quantity_ordered:g}" if line.quantity_ordered is not None else "-",
                    f"{line.quantity_delivered:g}" if line.quantity_delivered is not None else "-",
                    f"{line.quantity_received:g}" if line.quantity_received is not None else "-",
                ]
            else:
                row += [f"{line.quantity:g}" if line.quantity is not None else "-"]
            row += [line.uom or "-"]
            if any(l.batch_or_serial for l in self.lines):
                row += [line.batch_or_serial or "-"]
            if priced:
                row += [
                    money(line.unit_price) if line.unit_price is not None else "-",
                    money(line.amount) if line.amount is not None else "-",
                ]
            out.append("   ".join(row))

        out.append("")
        if self.subtotal is not None:
            out.append(f"Subtotal: {cur} {money(self.subtotal)}")
        if self.discount_amount is not None:
            out.append(f"Discount: {cur} {money(self.discount_amount)}")
        if self.freight_amount is not None:
            out.append(f"Freight: {cur} {money(self.freight_amount)}")
        for tax in self.taxes:
            rate = f" @ {tax.rate_percent:g}%" if tax.rate_percent is not None else ""
            out.append(f"{tax.tax_type}{rate}: {cur} {money(tax.amount)}")
        if self.tax_amount is not None and not self.taxes:
            out.append(f"Tax: {cur} {money(self.tax_amount)}")
        if self.grand_total is not None:
            out.append(f"TOTAL: {cur} {money(self.grand_total)}")
        if self.grand_total is None and not priced:
            # Said explicitly rather than left absent: an unpriced document that
            # merely omits a total reads the same to a model as one whose total
            # was cropped, and the schema requires `grand_total` to be null here
            # rather than computed.
            out.append("This document is for delivery/receipt purposes and states no monetary value.")
        out.append("")
        if self.payment_terms:
            out.append(f"Payment Terms: {self.payment_terms}")
        if self.delivery_terms:
            out.append(f"Delivery Terms: {self.delivery_terms}")
        if self.incoterms:
            out.append(f"Incoterms: {self.incoterms}")
        if self.notes:
            out.append(self.notes)
        return "\n".join(out)

    # -- ground truth ------------------------------------------------------

    def ground_truth(self) -> dict[str, Any]:
        """The known-correct extraction, in `GenericDocumentSchema`'s field names.

        Field-for-field with the schema so a comparison against a real
        extraction needs no translation layer, exactly as
        `InvoiceSpec.ground_truth()` is field-for-field with the invoice schemas.
        """
        return {
            "doc_type": self.doc_type,
            "party_name": self.party_name,
            "counterparty_name": self.counterparty_name,
            "doc_number": self.doc_number,
            "po_number": self.po_number,
            "reference_numbers": list(self.reference_numbers),
            "doc_date": self.doc_date,
            "valid_until": self.valid_until,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "freight_amount": self.freight_amount,
            "discount_amount": self.discount_amount,
            "grand_total": self.grand_total,
            "items": [
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "amount": line.amount,
                }
                for line in self.lines
            ],
        }

    def initial_extraction(self) -> dict[str, Any]:
        """A perfect extraction, as `extract_node` would return it.

        What verify-only mode feeds `verify_node` for a clean case. Distinct from
        `ground_truth()` in carrying the fields the schema has but the accuracy
        comparison does not grade -- the per-row quantity columns, `taxes`, and
        the terms strings -- because `verify_node` reads some of them.
        """
        data = dict(self.ground_truth())
        data["items"] = [
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount": line.amount,
                "quantity_ordered": line.quantity_ordered,
                "quantity_delivered": line.quantity_delivered,
                "quantity_received": line.quantity_received,
                "uom": line.uom,
                "batch_or_serial": line.batch_or_serial,
            }
            for line in self.lines
        ]
        data["taxes"] = [
            {"tax_type": t.tax_type, "rate_percent": t.rate_percent, "amount": t.amount}
            for t in self.taxes
        ]
        data["payment_terms"] = self.payment_terms
        data["delivery_terms"] = self.delivery_terms
        data["incoterms"] = self.incoterms
        data["notes"] = self.notes
        return data


# ---------------------------------------------------------------------------
# The clean generic set
# ---------------------------------------------------------------------------
# Every priced spec is internally consistent: each line amount equals
# qty x unit_price, the line amounts sum to the subtotal, and
# subtotal + tax equals the grand total. Every unpriced spec states no monetary
# value anywhere, so a non-null `currency` or `grand_total` in an extraction is
# a hallucination and must be scored as one.


_IN_DELIVERY_NOTE = DocumentSpec(
    doc_id="in_delivery_note_unpriced",
    doc_type="DELIVERY_NOTE",
    region="IN",
    party_name="Sunrise Polymers Pvt Ltd",
    party_address="Plot 42, Chakan Industrial Area, Pune 410501, Maharashtra",
    counterparty_name="Lakshmi Auto Components Ltd",
    doc_number="DC/2026/00418",
    doc_date="2026-09-02",
    po_number="PO-LAC-88213",
    currency=None,
    lines=(
        GenericLineSpec(
            description="HDPE Granules Grade B5308",
            quantity=1200, uom="KG", batch_or_serial="B-26-4471",
        ),
        GenericLineSpec(
            description="Masterbatch Black MB-77",
            quantity=45, uom="KG", batch_or_serial="B-26-4472",
        ),
        GenericLineSpec(
            description="Moulded End Caps 32mm",
            quantity=800, uom="NOS", batch_or_serial="B-26-4480",
        ),
    ),
    delivery_terms="Ex-works Pune; consignee arranges transport",
    notes=(
        "Goods despatched against the above purchase order. "
        "Please check quantities on receipt and report discrepancies within 48 hours."
    ),
    rationale=(
        "A delivery challan that prints no prices at all -- the shape "
        "`prebuilt-invoice` force-fits into an invoice, inventing a VendorName and "
        "an InvoiceTotal the document does not contain. `currency`, `subtotal`, "
        "`tax_amount` and `grand_total` must all come back null, and every line's "
        "`unit_price` and `amount` with them. A non-null total here is the single "
        "most consequential hallucination in non-invoice extraction: it puts a "
        "money figure on a document that owes nothing."
    ),
)


_US_PURCHASE_ORDER = DocumentSpec(
    doc_id="us_purchase_order_priced",
    doc_type="PURCHASE_ORDER",
    region="US",
    party_name="Cascade Robotics Inc",
    party_address="2200 Harbor Ave SW, Seattle, WA 98126, United States",
    counterparty_name="Northwind Bearings LLC",
    doc_number="PO-2026-4471",
    doc_date="2026-09-04",
    # On a purchase order the document's own number *is* the PO number -- the
    # schema says so explicitly, and getting `po_number` null here is a common
    # miss because the model looks for a referenced order instead of this one.
    po_number="PO-2026-4471",
    currency="USD",
    lines=(
        GenericLineSpec(description="Thrust bearing 6208-2RS", quantity=40,
                        unit_price=18.50, amount=740.00, uom="EA"),
        GenericLineSpec(description="Harmonic drive gearset HD-32", quantity=12,
                        unit_price=132.00, amount=1584.00, uom="EA"),
        GenericLineSpec(description="Precision shim set 0.1-0.5mm", quantity=6,
                        unit_price=95.25, amount=571.50, uom="SET"),
    ),
    subtotal=2895.50,
    tax_amount=231.64,
    grand_total=3127.14,
    taxes=(TaxLineSpec(tax_type="Sales Tax", rate_percent=8.0, amount=231.64),),
    payment_terms="Net 45 days from receipt of invoice",
    delivery_terms="Required on site by 2026-10-15; partial shipments not accepted",
    incoterms="FOB Seattle",
    rationale=(
        "A priced purchase order. Exercises `po_number` equal to `doc_number`, "
        "`incoterms` and `delivery_terms` -- three fields no invoice schema has -- "
        "while still carrying arithmetic the totals checks can reconcile "
        "(2,895.50 + 231.64 = 3,127.14). Also checks direction: the issuer is the "
        "*buyer* here, the reverse of an invoice, so `party_name` and "
        "`counterparty_name` are easy to swap."
    ),
)


_EU_CREDIT_NOTE = DocumentSpec(
    doc_id="eu_credit_note_negative",
    doc_type="CREDIT_NOTE",
    region="EU",
    party_name="Bremen Hydraulik GmbH",
    party_address="Industriestrasse 14, 28197 Bremen, Germany",
    counterparty_name="Atlas Marine Services BV",
    doc_number="CN-2026-0177",
    doc_date="2026-09-08",
    reference_numbers=("INV-2026-3391",),
    currency="EUR",
    lines=(
        GenericLineSpec(description="Returned hose assembly HA-500", quantity=4,
                        unit_price=-48.75, amount=-195.00, uom="EA"),
        GenericLineSpec(description="Credit for short-delivered valve block", quantity=1,
                        unit_price=-320.00, amount=-320.00, uom="EA"),
    ),
    subtotal=-515.00,
    tax_amount=-97.85,
    grand_total=-612.85,
    taxes=(TaxLineSpec(tax_type="VAT", rate_percent=19.0, amount=-97.85),),
    notes=(
        "Credit raised against invoice INV-2026-3391 for goods returned on "
        "2026-09-05 and one short-delivered item."
    ),
    rationale=(
        "Every figure negative, which is the point. The extraction prompt requires "
        "signs transcribed exactly as printed and explicitly forbids flipping them "
        "'to make the document read like an invoice'. This spec is the regression "
        "test for that: an extraction returning +612.85 reverses the direction of "
        "money on the ledger and reads as perfectly correct. It also pins "
        "`reference_numbers`, which is how a credit note is tied back to the "
        "invoice it adjusts, and the arithmetic still reconciles "
        "(-515.00 + -97.85 = -612.85) so a sign-agnostic totals check stays silent."
    ),
)


_IN_GRN = DocumentSpec(
    doc_id="in_grn_three_quantity_columns",
    doc_type="GRN",
    region="IN",
    party_name="Lakshmi Auto Components Ltd",
    party_address="Survey 118, Hosur Road, Bengaluru 560100, Karnataka",
    counterparty_name="Sunrise Polymers Pvt Ltd",
    doc_number="GRN-2026-00931",
    doc_date="2026-09-03",
    po_number="PO-LAC-88213",
    reference_numbers=("DC/2026/00418",),
    currency=None,
    lines=(
        GenericLineSpec(description="HDPE Granules Grade B5308", quantity=1200,
                        quantity_ordered=1200, quantity_delivered=1200,
                        quantity_received=1200, uom="KG"),
        GenericLineSpec(description="Masterbatch Black MB-77", quantity=45,
                        quantity_ordered=50, quantity_delivered=45,
                        quantity_received=45, uom="KG"),
        GenericLineSpec(description="Moulded End Caps 32mm", quantity=800,
                        quantity_ordered=800, quantity_delivered=800,
                        quantity_received=780, uom="NOS"),
    ),
    notes=(
        "20 end caps rejected on inspection for flash on the sealing face. "
        "Masterbatch short-supplied by 5 KG against order."
    ),
    rationale=(
        "Three quantity columns printed side by side -- ordered, delivered, "
        "received -- which only `GenericLineItem` can hold. The three rows are "
        "deliberately different: one matches throughout, one is short-delivered, "
        "one is short-received against a full delivery. Collapsing them into a "
        "single `quantity` loses the discrepancy that is the entire purpose of a "
        "goods receipt note. Pairs with `in_delivery_note_unpriced`: same parties, "
        "same PO, the receiving half of the same transaction."
    ),
)


_IN_QUOTATION = DocumentSpec(
    doc_id="in_quotation_with_validity",
    doc_type="QUOTATION",
    region="IN",
    party_name="Deccan Fabrication Works",
    party_address="Unit 7, MIDC Waluj, Aurangabad 431136, Maharashtra",
    counterparty_name="Vertex Infra Projects Pvt Ltd",
    doc_number="QT-2026-0455",
    doc_date="2026-09-05",
    valid_until="2026-10-05",
    currency="INR",
    lines=(
        GenericLineSpec(description="Fabricated steel bracket type A", quantity=25,
                        unit_price=1240.00, amount=31000.00, uom="NOS"),
        GenericLineSpec(description="Galvanised walkway grating 1m x 2m", quantity=8,
                        unit_price=3750.00, amount=30000.00, uom="NOS"),
    ),
    subtotal=61000.00,
    tax_amount=10980.00,
    grand_total=71980.00,
    taxes=(
        TaxLineSpec(tax_type="CGST", rate_percent=9.0, amount=5490.00),
        TaxLineSpec(tax_type="SGST", rate_percent=9.0, amount=5490.00),
    ),
    payment_terms="30% advance with order, balance against despatch",
    delivery_terms="4 weeks from receipt of confirmed order",
    rationale=(
        "`valid_until` printed explicitly, which the schema forbids deriving from "
        "`doc_date` -- a quotation whose expiry is guessed at doc_date + 30 days "
        "looks right and commits the business to a price it never offered. Also "
        "carries a CGST/SGST split summing to `tax_amount` (5,490 + 5,490 = "
        "10,980), so the component-aware tax fallback is exercised on a "
        "non-invoice document, and the totals reconcile "
        "(61,000 + 10,980 = 71,980)."
    ),
)


CLEAN_GENERIC_DOCUMENTS: tuple[DocumentSpec, ...] = (
    _IN_DELIVERY_NOTE,
    _US_PURCHASE_ORDER,
    _EU_CREDIT_NOTE,
    _IN_GRN,
    _IN_QUOTATION,
)

CLEAN_GENERIC_BY_ID: dict[str, DocumentSpec] = {
    spec.doc_id: spec for spec in CLEAN_GENERIC_DOCUMENTS
}


def _all_clean() -> tuple[Any, ...]:
    """Invoice specs plus generic specs, for callers that want the whole corpus.

    Imported lazily inside the function so `documents.py` and this module can be
    imported in either order without a cycle.
    """
    from benchmarks.extraction.documents import CLEAN_DOCUMENTS

    return tuple(CLEAN_DOCUMENTS) + CLEAN_GENERIC_DOCUMENTS


ALL_CLEAN_DOCUMENTS: tuple[Any, ...] = _all_clean()
