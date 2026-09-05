"""Regenerates the Feature 17 (Invoice Builder) fixtures.

Run from `apps/invoice-be` with the dev dependencies installed (`uv sync`, no
`--no-dev` — `reportlab` is a dev dependency):

    ./.venv/Scripts/python.exe tests/fixtures/invoice_builder/_generate.py

Five source invoices, each written as a PDF plus a JSON sidecar holding the
`Invoice` field values a real extraction run would have produced *and* the
`Invoice.coordinates` list Document Intelligence would have stored for it. The
sidecar coordinates are computed here by locating each field's printed text
with PyMuPDF and normalising the rect to 0–100 percentages of the page, which
is exactly the shape `queue_worker/handlers.py::_run_ocr` writes after Gap 330.
Committing them keeps `tests/test_invoice_builder.py` free of any Azure call.

  us_style        — `1,250.00` separators, ISO dates
  eu_style        — `1.250,00` separators, `dd.mm.yyyy` dates
  date_twice      — the invoice date printed in the header AND in the footer
  raster_logo     — a real embedded PNG logo (branding harvest must find it)
  vector_text_only — no image at all (branding harvest must not crash)
"""
from __future__ import annotations

import io
import json
import pathlib

import fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

HERE = pathlib.Path(__file__).parent

#: Field value → the Document Intelligence field name whose polygon we store.
DI_NAMES = {
    "customer_name": "CustomerName",
    "invoice_number": "InvoiceId",
    "invoice_date": "InvoiceDate",
    "due_date": "DueDate",
    "subtotal": "SubTotal",
    "tax_amount": "TotalTax",
    "grand_total": "InvoiceTotal",
}


def _logo_png() -> bytes:
    """A tiny solid-colour PNG, written by hand so the fixture needs no binary
    asset checked in beside it."""
    from PIL import Image

    img = Image.new("RGB", (240, 80), (31, 59, 87))
    for x in range(240):
        for y in range(80):
            if (x // 20 + y // 20) % 2 == 0:
                img.putpixel((x, y), (255, 190, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_pdf(path: pathlib.Path, spec: dict, printed: dict) -> None:
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    title = ParagraphStyle("T", parent=styles["Heading1"], fontSize=18)

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []

    if spec.get("logo"):
        story.append(RLImage(io.BytesIO(_logo_png()), width=60 * mm, height=20 * mm))
        story.append(Spacer(1, 6))
    else:
        story.append(Paragraph("<b>ACME ENGINEERING</b>", title))

    story.append(Paragraph("ACME Engineering Ltd · 14 Foundry Road · Sheffield S1 2AB", normal))
    story.append(Spacer(1, 10))
    story.append(Paragraph("INVOICE", title))
    story.append(Paragraph(f"Invoice Number: {printed['invoice_number']}", normal))
    story.append(Paragraph(f"Invoice Date: {printed['invoice_date']}", normal))
    story.append(Paragraph(f"Due Date: {printed['due_date']}", normal))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Bill To:</b>", normal))
    story.append(Paragraph(printed["customer_name"], normal))
    story.append(Spacer(1, 12))

    rows = [["Description", "Qty", "Unit Price", "Amount"]] + [
        [i["description"], i["quantity"], i["unit_price"], i["amount"]]
        for i in printed["items"]
    ]
    table = Table(rows, colWidths=[240, 60, 90, 90], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3B57")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))

    summary = Table(
        [["Subtotal", printed["subtotal"]],
         ["Tax", printed["tax_amount"]],
         ["Total Due", printed["grand_total"]]],
        colWidths=[390, 90],
    )
    summary.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.black),
    ]))
    story.append(summary)
    story.append(Spacer(1, 18))
    for line in spec.get("footer", []):
        story.append(Paragraph(line, normal))
    doc.build(story)


def _coordinates(pdf_path: pathlib.Path, printed: dict) -> list[dict]:
    """Locate each header/total field's printed text and store its rect as the
    0–100 page percentages `Invoice.coordinates` holds."""
    out = []
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        pw, ph = page.rect.width, page.rect.height
        for key, di_name in DI_NAMES.items():
            text = printed[key]
            hits = page.search_for(text)
            if not hits:
                continue
            # Header fields take the FIRST hit in reading order — the
            # `date_twice` fixture repeats the invoice date in the footer and
            # the polygon deliberately points at the header occurrence only.
            # The three totals take the LAST hit, because a single-line invoice
            # prints the same figure as the line amount higher up the page and
            # Document Intelligence would label the totals-block occurrence,
            # not the table cell. (Getting this backwards is not academic: the
            # first cut of these fixtures pointed `SubTotal` at the line-item
            # cell, and `substitute()` then rewrote that cell twice and left the
            # real subtotal printing the old figure.)
            if key in ("subtotal", "tax_amount", "grand_total"):
                rect = max(hits, key=lambda r: (round(r.y0, 1), r.x0))
            else:
                rect = min(hits, key=lambda r: (round(r.y0, 1), r.x0))
            out.append({
                "field": di_name,
                "x": round(rect.x0 / pw * 100, 3),
                "y": round(rect.y0 / ph * 100, 3),
                "width": round(rect.width / pw * 100, 3),
                "height": round(rect.height / ph * 100, 3),
                "page": 1,
            })
    return out


FIXTURES: dict[str, dict] = {
    "us_style": {
        "printed": {
            "customer_name": "Northwind Traders",
            "invoice_number": "INV-0042",
            "invoice_date": "2026-07-15",
            "due_date": "2026-08-14",
            "items": [
                {"description": "Precision machining", "quantity": "5", "unit_price": "250.00", "amount": "1,250.00"},
                {"description": "Surface treatment", "quantity": "2", "unit_price": "175.00", "amount": "350.00"},
            ],
            "subtotal": "1,600.00",
            "tax_amount": "320.00",
            "grand_total": "1,920.00",
        },
        "values": {
            "currency": "USD",
            "invoice_date": "2026-07-15",
            "due_date": "2026-08-14",
            "subtotal": 1600.0, "tax_amount": 320.0, "grand_total": 1920.0,
        },
        "footer": ["Payment within 30 days. ACME Engineering Ltd, registered in England 09182736."],
    },
    "eu_style": {
        "printed": {
            "customer_name": "Blaue See GmbH",
            "invoice_number": "RE-2026-0117",
            "invoice_date": "15.07.2026",
            "due_date": "14.08.2026",
            "items": [
                {"description": "Konstruktionsleistung", "quantity": "5", "unit_price": "250,00", "amount": "1.250,00"},
                {"description": "Oberflaechenbehandlung", "quantity": "2", "unit_price": "175,00", "amount": "350,00"},
            ],
            "subtotal": "1.600,00",
            "tax_amount": "304,00",
            "grand_total": "1.904,00",
        },
        "values": {
            "currency": "EUR",
            "invoice_date": "2026-07-15",
            "due_date": "2026-08-14",
            "subtotal": 1600.0, "tax_amount": 304.0, "grand_total": 1904.0,
        },
        "footer": ["Zahlbar innerhalb von 30 Tagen."],
    },
    "date_twice": {
        "printed": {
            "customer_name": "Harbour Logistics",
            "invoice_number": "INV-0500",
            "invoice_date": "15/07/2026",
            "due_date": "14/08/2026",
            "items": [
                {"description": "Freight handling", "quantity": "10", "unit_price": "80.00", "amount": "800.00"},
            ],
            "subtotal": "800.00",
            "tax_amount": "160.00",
            "grand_total": "960.00",
        },
        "values": {
            "currency": "GBP",
            "invoice_date": "2026-07-15",
            "due_date": "2026-08-14",
            "subtotal": 800.0, "tax_amount": 160.0, "grand_total": 960.0,
        },
        "footer": [
            "This invoice was issued on 15/07/2026 and supersedes any prior quotation.",
            "Queries within 14 days of 15/07/2026 please.",
        ],
    },
    "raster_logo": {
        "logo": True,
        "printed": {
            "customer_name": "Cobalt Systems",
            "invoice_number": "INV-0900",
            "invoice_date": "2026-07-01",
            "due_date": "2026-07-31",
            "items": [
                {"description": "Site survey", "quantity": "1", "unit_price": "1,000.00", "amount": "1,000.00"},
                {"description": "Report preparation", "quantity": "4", "unit_price": "125.00", "amount": "500.00"},
            ],
            "subtotal": "1,500.00",
            "tax_amount": "300.00",
            "grand_total": "1,800.00",
        },
        "values": {
            "currency": "USD",
            "invoice_date": "2026-07-01",
            "due_date": "2026-07-31",
            "subtotal": 1500.0, "tax_amount": 300.0, "grand_total": 1800.0,
        },
        "footer": ["ACME Engineering Ltd · VAT GB 123 4567 89"],
    },
    "vector_text_only": {
        "printed": {
            "customer_name": "Pine Ridge Dairy",
            "invoice_number": "INV-1200",
            "invoice_date": "2026-06-02",
            "due_date": "2026-07-02",
            "items": [
                {"description": "Chilled transport", "quantity": "3", "unit_price": "210.00", "amount": "630.00"},
            ],
            "subtotal": "630.00",
            "tax_amount": "126.00",
            "grand_total": "756.00",
        },
        "values": {
            "currency": "USD",
            "invoice_date": "2026-06-02",
            "due_date": "2026-07-02",
            "subtotal": 630.0, "tax_amount": 126.0, "grand_total": 756.0,
        },
        "footer": ["Thank you for your business."],
    },
}


def _numeric(text: str) -> float:
    """`1.250,00` / `1,250.00` → 1250.0. The sidecar stores the *extracted*
    float, which is what an `Invoice` row holds; the PDF keeps the printing."""
    body = text.strip()
    if "," in body and "." in body:
        dec = max(body.rfind(","), body.rfind("."))
        body = body[:dec].replace(",", "").replace(".", "") + "." + body[dec + 1:]
    elif "," in body:
        body = body.replace(",", "." if len(body) - body.rfind(",") - 1 in (1, 2) else "")
    return float(body)


def main() -> None:
    for name, spec in FIXTURES.items():
        printed = spec["printed"]
        pdf_path = HERE / f"{name}.pdf"
        _build_pdf(pdf_path, spec, printed)

        items = [
            {
                "description": i["description"],
                "quantity": _numeric(i["quantity"]),
                "unit_price": _numeric(i["unit_price"]),
                "amount": _numeric(i["amount"]),
            }
            for i in printed["items"]
        ]
        sidecar = {
            "pdf": f"{name}.pdf",
            "customer_name": printed["customer_name"],
            "invoice_number": printed["invoice_number"],
            "items": items,
            "coordinates": _coordinates(pdf_path, printed),
            **spec["values"],
        }
        (HERE / f"{name}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        print(f"wrote {pdf_path.name} + {name}.json ({len(sidecar['coordinates'])} polygons)")


if __name__ == "__main__":
    main()
