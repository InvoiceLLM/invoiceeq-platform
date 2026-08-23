"""A large, multi-page invoice — and a one-page one built the same way.

Why this exists
---------------
`chroma_client.get_all_invoice_chunks()` returns **every** indexed chunk for an
invoice, unranked and unthresholded, and `agents/query_tools.get_full_record()`
puts all of them into the synthesis prompt (`sage_orchestrator._synthesize_node`
renders them under "EVERY INDEXED PAGE OF THIS INVOICE'S DOCUMENT"). Neither
function has a page, chunk or character bound. Every fixture this repo had for
the SAGE path is a two-chunk, ~150-character stand-in, so nothing in it could
ever have shown what that costs on a real multi-page document.

This module builds the missing measurement input, and builds it the same way the
product does rather than by writing plausible-looking chunk text by hand:

  1. `tests/e2e/pdf_builder.build_invoice_pdf()` renders a real PDF — the same
     builder the e2e regional fixtures use.
  2. PyMuPDF (`fitz`) extracts each page's text, and each page gets the exact
     `[Vendor: ... | Document ID: ... | Page N]` header that
     `chroma_client.index_invoice_document()` prepends before indexing.

So a chunk from here is byte-for-byte the shape a chunk in Chroma has for a PDF
of this size: one chunk per page, whole page text, no truncation.

The two specs differ **only** in how many line items they carry, which is the
point — an A/B where the single independent variable is document length isolates
what `get_full_record` alone contributes to a turn's token bill.

Not real, stated plainly: the numbers on these invoices are synthetic, and the
text comes from a reportlab render rather than a scanned vendor document. Page
*text volume* is what is being measured, and that is real — it is whatever
`page.get_text()` returns from an actual rendered A4 invoice page.
"""
from __future__ import annotations

import hashlib
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

_CACHE_DIR = _BE_ROOT / "tests" / "fixtures" / "large_invoice"

# Repeating catalogue rows, cycled to whatever length a spec asks for. Real
# consolidated invoices (logistics, telecom, MRO supply) look like this: the same
# handful of SKUs, over and over, on different dates and reference numbers.
_CATALOGUE = [
    ("Hex bolt M12x60 galvanised, box of 100", 100, "18.40"),
    ("Hydraulic hose assembly 3/8in x 2400mm", 6, "142.75"),
    ("Bearing grease NLGI 2, 400g cartridge", 24, "9.85"),
    ("Safety gloves, cut level D, pair", 60, "7.20"),
    ("Weld wire ER70S-6 1.2mm, 15kg spool", 8, "96.50"),
    ("Air filter element, heavy plant", 12, "58.30"),
    ("Cutting disc 230mm x 3mm, pack of 25", 10, "41.00"),
    ("Threaded rod M16 x 1m, zinc plated", 30, "12.65"),
    ("Coolant concentrate, 20L drum", 4, "187.90"),
    ("Shackle bow type 3.25t, galvanised", 20, "16.75"),
    ("Pallet wrap 500mm x 300m, 20 micron", 36, "8.95"),
    ("Cable gland M20 brass IP68, pack of 50", 14, "33.40"),
]


class InvoiceSpec:
    """One synthetic invoice: its stored row, its PDF, and its page chunks."""

    def __init__(
        self,
        *,
        key: str,
        vendor_name: str,
        invoice_number: str,
        invoice_date: str,
        due_date: str,
        currency: str,
        line_count: int,
        tax_rate: str = "0.08",
    ) -> None:
        self.key = key
        self.vendor_name = vendor_name
        self.invoice_number = invoice_number
        self.invoice_date = invoice_date
        self.due_date = due_date
        self.currency = currency
        self.line_count = line_count
        self.tax_rate = Decimal(tax_rate)

    # -- money -------------------------------------------------------------

    def line_items(self) -> list[dict]:
        items = []
        for index in range(self.line_count):
            description, quantity, unit_price = _CATALOGUE[index % len(_CATALOGUE)]
            price = Decimal(unit_price)
            amount = (price * quantity).quantize(Decimal("0.01"))
            items.append(
                {
                    "line": index + 1,
                    "description": f"{description} [ref {self.invoice_number}-{index + 1:03d}]",
                    "quantity": quantity,
                    "unit_price": float(price),
                    "amount": float(amount),
                }
            )
        return items

    def subtotal(self) -> Decimal:
        return sum(
            (Decimal(str(item["amount"])) for item in self.line_items()), Decimal("0")
        ).quantize(Decimal("0.01"))

    def tax_amount(self) -> Decimal:
        return (self.subtotal() * self.tax_rate).quantize(Decimal("0.01"))

    def grand_total(self) -> Decimal:
        return (self.subtotal() + self.tax_amount()).quantize(Decimal("0.01"))

    # -- artefacts ---------------------------------------------------------

    def pdf_path(self) -> Path:
        """Build the PDF once and cache it; the render is deterministic."""
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(
            f"{self.invoice_number}|{self.line_count}".encode("utf-8")
        ).hexdigest()[:12]
        path = _CACHE_DIR / f"{self.key}_{digest}.pdf"
        if path.exists():
            return path

        from tests.e2e.pdf_builder import build_invoice_pdf

        symbol = {"USD": "$", "INR": "₹", "EUR": "€"}.get(self.currency, "")
        rows = [
            [
                str(item["line"]),
                item["description"],
                str(item["quantity"]),
                f"{symbol}{item['unit_price']:,.2f}",
                f"{symbol}{item['amount']:,.2f}",
            ]
            for item in self.line_items()
        ]
        build_invoice_pdf(
            str(path),
            vendor_lines=[f"<b>{self.vendor_name}</b>", "Unit 14, Kingsway Industrial Estate, Leeds LS12 6DP"],
            meta_lines=[
                f"Invoice Number: {self.invoice_number}",
                f"Invoice Date: {self.invoice_date}",
                f"Due Date: {self.due_date}",
                f"Currency: {self.currency}",
            ],
            bill_to_lines=["ADM Softtech Pvt. Ltd.", "Plot 5, Tech Zone, Kolkata 700001, India"],
            columns=["#", "Description", "Qty", f"Unit Price ({self.currency})", f"Amount ({self.currency})"],
            rows=rows,
            summary_rows=[
                ["Subtotal:", f"{symbol}{self.subtotal():,.2f}"],
                [f"Tax ({self.tax_rate * 100:.0f}%):", f"{symbol}{self.tax_amount():,.2f}"],
                ["TOTAL DUE:", f"{symbol}{self.grand_total():,.2f}"],
            ],
            notes=[
                "Payment terms: net 45 days from invoice date. Late payment interest 2% per month.",
                "Goods remain the property of the supplier until paid in full.",
            ],
        )
        return path

    def page_chunks(self, invoice_id: str) -> list[dict]:
        """The chunks Chroma would hold for this document, in `get_all_invoice_chunks()`'s shape.

        One per page, whole page text, with `index_invoice_document()`'s header —
        i.e. no ranking, no threshold, no truncation, because that is exactly what
        the function being measured does.
        """
        import fitz

        chunks: list[dict] = []
        document = fitz.open(str(self.pdf_path()))
        try:
            for index, page in enumerate(document):
                text = page.get_text()
                if not text.strip():
                    continue
                header = f"[Vendor: {self.vendor_name} | Document ID: {invoice_id} | Page {index + 1}]\n"
                chunks.append(
                    {
                        "id": f"{invoice_id}_page_{index + 1}",
                        "document": header + text,
                        "metadata": {
                            "tenant_id": None,
                            "invoice_id": str(invoice_id),
                            "vendor_name": self.vendor_name,
                            "page": index + 1,
                        },
                        "matched_by": "invoice_id",
                    }
                )
        finally:
            document.close()
        return chunks

    def row(self) -> dict:
        """The `invoice` row, in the shape `tests/run_agentic_sage_live._seed()` inserts."""
        import json

        return dict(
            vendor_name=self.vendor_name,
            customer_name=None,
            flow_direction="INBOUND",
            invoice_number=self.invoice_number,
            grand_total=float(self.grand_total()),
            tax_amount=float(self.tax_amount()),
            currency=self.currency,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status="COMPLETED",
            items=json.dumps(self.line_items()),
        )


# 400 catalogue lines renders to an 11-page document; 1 line renders to a single
# page. Nothing else differs between them. 400 is chosen as a *plausible* large
# invoice rather than a worst case — a consolidated monthly MRO/logistics invoice
# of this length is ordinary — and the measured page/char/token curve for other
# sizes is in `feature_21_architecture.md`'s B4 section so the shape is visible
# without re-running anything.
LARGE = InvoiceSpec(
    key="large",
    vendor_name="Meridian Industrial Supply",
    invoice_number="MIS-2026-0881",
    invoice_date="2026-07-14",
    due_date="2026-08-28",
    currency="USD",
    line_count=400,
)

SMALL = InvoiceSpec(
    key="small",
    vendor_name="Kingsway Fasteners",
    invoice_number="KWF-2026-0042",
    invoice_date="2026-07-16",
    due_date="2026-08-30",
    currency="USD",
    line_count=1,
)

SPECS = {LARGE.invoice_number: LARGE, SMALL.invoice_number: SMALL}


def spec_for_invoice_number(invoice_number: Optional[str]) -> Optional[InvoiceSpec]:
    return SPECS.get(str(invoice_number or ""))


if __name__ == "__main__":  # a quick, honest look at what these actually are
    for spec in (SMALL, LARGE):
        chunks = spec.page_chunks("00000000-0000-0000-0000-0000000000ff")
        chars = sum(len(chunk["document"]) for chunk in chunks)
        print(
            f"{spec.key:6s} {spec.invoice_number}: {spec.line_count:>3d} lines, "
            f"{len(chunks):>2d} pages, {chars:>7,d} chunk chars, "
            f"grand_total {spec.currency} {spec.grand_total():,.2f}"
        )
