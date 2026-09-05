"""Feature 17: the structured re-render, and the branding harvested from the
source PDF that keeps it recognisable.

This is the "rows were added or removed" half of founder decision D3. You
cannot insert a line into a fixed printed layout by painting over words, so
when `plan_render_mode()` says `rerender` the invoice is laid out again from
scratch with reportlab — but with the source's own logo, header block, page
size and number formatting lifted off page 1, so the result still looks like
the tenant's invoice rather than a generic template.

Everything here is deterministic. `harvest_branding()` picks the logo by pixel
area and position, not by asking a model which image is the logo, and returns
empty branding rather than raising when the source has no image at all (the
`vector_text_only` fixture).
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from typing import Iterable

import fitz  # PyMuPDF

from services.invoice_builder import BuildRequest, Totals
from services.pdf_substitute import format_like

logger = logging.getLogger(__name__)

#: A logo lives in the top band of page 1 and is not a hairline rule or a
#: background wash. Both thresholds are fractions of the page.
_LOGO_TOP_BAND = 0.40
_LOGO_MIN_AREA = 0.0005
_LOGO_MAX_AREA = 0.35
#: Text blocks in this top band are the printed letterhead.
_HEADER_BAND = 0.30
#: The footer is taken from the source's LAST text block, provided it sits
#: below this fraction of the page and reads like prose (>= 4 words) rather
#: than a totals row — "Payment within 30 days…", the registration number, the
#: bank details. A short invoice puts that block at 50% of the page, so a fixed
#: bottom-of-page band finds nothing on exactly the invoices this feature was
#: measured against.
_FOOTER_BAND = 0.40
_FOOTER_MIN_WORDS = 4


@dataclass
class Branding:
    """What could be lifted off the source page. Every field is optional —
    an invoice with no logo and no footer renders perfectly well without."""
    logo_bytes: bytes | None = None
    logo_width: float = 0.0   # points, as printed on the source page
    logo_height: float = 0.0
    logo_pixels: tuple[int, int] = (0, 0)
    header_lines: list[str] = dc_field(default_factory=list)
    footer_lines: list[str] = dc_field(default_factory=list)
    page_size: tuple[float, float] = (595.276, 841.89)  # A4 default


#: A harvested header line that is really the *source invoice's own metadata*
#: — its number, its dates, its "Bill To:" — must not be reprinted above the
#: new invoice's own header, or the re-rendered PDF carries last month's
#: invoice number at the top of the page. Caught here rather than trusted to
#: the band cut-off, because a letterhead and a header block share that band.
_META_LINE = re.compile(
    r"^\s*(invoice|inv\.?|bill\s*to|ship\s*to|sold\s*to|customer|client|due|date|"
    r"po\b|purchase\s*order|terms|rechnung|kunde|f.llig|no\.?|number|#)\b",
    re.IGNORECASE,
)
_DOCUMENT_TITLES = {"invoice", "tax invoice", "rechnung", "facture", "factura"}
#: The column headings of the line-item table. Reaching one of these means the
#: letterhead is over, whatever band of the page we are in — a one-line invoice
#: puts its table well inside the top 30%.
_TABLE_HEADINGS = {
    "description", "item", "items", "qty", "quantity", "unit price", "unit",
    "price", "amount", "total", "beschreibung", "menge", "einzelpreis", "betrag",
}


def _is_metadata_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.lower().strip(" .:") in _DOCUMENT_TITLES:
        return True
    if not _META_LINE.match(stripped):
        return False
    # A tenant genuinely called "Invoice Systems Ltd" prints no colon and no
    # digits on its letterhead line; the source's own `Invoice Number: 0042`
    # prints both.
    return ":" in stripped or any(ch.isdigit() for ch in stripped)


def harvest_branding(
    source_pdf_bytes: bytes,
    exclude_texts: "Iterable[str] | None" = None,
) -> Branding:
    """Logo, letterhead, footer and page size from page 1 of the source.

    The logo is the largest raster image whose rectangle starts in the top 40%
    of the page and which covers between 0.05% and 35% of it — the lower bound
    drops decorative rules and 1×1 spacer images, the upper bound drops a
    full-page background scan (on which every value would be invisible text
    over a picture anyway).

    `exclude_texts` is the caller's second line of defence: the source row's own
    printed values (invoice number, customer name), so that any header line
    quoting them is dropped even if the label heuristic misses it.
    """
    excluded = [t.strip().lower() for t in (exclude_texts or []) if t and str(t).strip()]
    branding = Branding()
    try:
        doc = fitz.open(stream=source_pdf_bytes, filetype="pdf")
    except Exception as exc:
        logger.warning("harvest_branding could not open the source PDF: %s", exc)
        return branding
    try:
        if doc.page_count == 0:
            return branding
        page = doc[0]
        pw, ph = page.rect.width, page.rect.height
        branding.page_size = (pw, ph)
        page_area = max(pw * ph, 1.0)

        best = None
        for image in page.get_images(full=True):
            xref = image[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:  # pragma: no cover - malformed image entry
                continue
            for rect in rects:
                area = rect.get_area()
                if rect.y0 > ph * _LOGO_TOP_BAND:
                    continue
                if not (page_area * _LOGO_MIN_AREA <= area <= page_area * _LOGO_MAX_AREA):
                    continue
                if best is None or area > best[1]:
                    best = (xref, area, rect)

        if best is not None:
            xref, _area, rect = best
            try:
                extracted = doc.extract_image(xref)
                branding.logo_bytes = extracted["image"]
                branding.logo_pixels = (extracted.get("width", 0), extracted.get("height", 0))
                branding.logo_width = rect.width
                branding.logo_height = rect.height
            except Exception as exc:  # pragma: no cover
                logger.warning("harvest_branding could not extract image %s: %s", xref, exc)

        table_reached = False
        last_prose_block: list[str] = []
        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
            lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
            if not lines:
                continue
            if y1 <= ph * _HEADER_BAND and not table_reached:
                if branding.logo_bytes and y1 <= (best[2].y1 if best else 0):
                    continue
                for line in lines:
                    if line.strip().lower() in _TABLE_HEADINGS:
                        table_reached = True
                        break
                    if _is_metadata_line(line):
                        continue
                    if any(x and x in line.lower() for x in excluded):
                        continue
                    branding.header_lines.append(line)
            elif y0 >= ph * _FOOTER_BAND and len(" ".join(lines).split()) >= _FOOTER_MIN_WORDS:
                last_prose_block = lines

        branding.header_lines = branding.header_lines[:6]
        branding.footer_lines = last_prose_block[-4:]
        return branding
    finally:
        doc.close()


def render_invoice(
    req: BuildRequest,
    totals: Totals,
    branding: Branding,
    number_style: str,
) -> bytes:
    """Lay the invoice out fresh, any number of rows, on the source's page size.

    `number_style` is a sample of how the source printed money (its grand
    total, normally); every figure here is rendered through `format_like()`
    with that sample, so a tenant whose invoices read `1.250,00` gets
    `1.250,00` back rather than a US default.

    The line-item table repeats its header row across pages and the totals
    block follows the table, so a 40-line invoice paginates with the totals on
    the last page — reportlab's own flow, not a hand-rolled page counter.
    """
    from reportlab.lib import colors
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

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    title = ParagraphStyle("BuilderTitle", parent=styles["Heading1"], fontSize=16)
    small = ParagraphStyle("BuilderSmall", parent=normal, fontSize=8, textColor=colors.HexColor("#444444"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=branding.page_size,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
    )
    story: list = []

    if branding.logo_bytes:
        try:
            story.append(RLImage(
                io.BytesIO(branding.logo_bytes),
                width=branding.logo_width or 60 * mm,
                height=branding.logo_height or 20 * mm,
            ))
            story.append(Spacer(1, 8))
        except Exception as exc:  # pragma: no cover - unsupported codec
            logger.warning("render_invoice could not place the harvested logo: %s", exc)

    for line in branding.header_lines:
        story.append(Paragraph(_escape(line), normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("INVOICE", title))
    if req.invoice_number:
        story.append(Paragraph(f"Invoice Number: {_escape(req.invoice_number)}", normal))
    if req.invoice_date:
        story.append(Paragraph(f"Invoice Date: {req.invoice_date.isoformat()}", normal))
    if req.due_date:
        story.append(Paragraph(f"Due Date: {req.due_date.isoformat()}", normal))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Bill To:</b>", normal))
    story.append(Paragraph(_escape(req.customer_name or ""), normal))
    story.append(Spacer(1, 12))

    def fmt(value: Decimal) -> str:
        return format_like(number_style, value)

    rows = [["Description", "Qty", "Unit Price", "Amount"]]
    for idx, item in enumerate(req.items):
        amount = totals.line_amounts[idx] if idx < len(totals.line_amounts) else Decimal("0.00")
        rows.append([
            Paragraph(_escape(item.description or ""), normal),
            _quantity_text(item.quantity),
            fmt(item.unit_price if item.unit_price is not None else Decimal("0")),
            fmt(amount),
        ])

    usable = doc.width
    table = Table(rows, colWidths=[usable * 0.52, usable * 0.10, usable * 0.19, usable * 0.19], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3B57")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))

    currency = (req.currency or "").strip()
    summary = Table(
        [
            ["Subtotal", fmt(totals.subtotal)],
            ["Tax", fmt(totals.tax_amount)],
            [f"Total Due{(' (' + currency + ')') if currency else ''}", fmt(totals.grand_total)],
        ],
        colWidths=[usable * 0.81, usable * 0.19],
    )
    summary.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.black),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
    ]))
    story.append(summary)

    if branding.footer_lines:
        story.append(Spacer(1, 18))
        for line in branding.footer_lines:
            story.append(Paragraph(_escape(line), small))

    doc.build(story)
    return buf.getvalue()


def _quantity_text(quantity: Decimal | None) -> str:
    """`5` not `5.00`, `2.5` not `2.500` — quantities are printed as typed."""
    if quantity is None:
        return ""
    normalized = quantity.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return f"{normalized:f}"


def _escape(text: str) -> str:
    """reportlab's Paragraph parses a mini-HTML; a customer called `A & B` must
    not be able to break the render (or inject markup into it)."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
