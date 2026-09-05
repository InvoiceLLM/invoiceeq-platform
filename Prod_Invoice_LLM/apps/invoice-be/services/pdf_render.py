"""Feature 17: the structured re-render, and the branding harvested from the
source PDF that keeps it recognisable.

**This is the only renderer.** BE Gap 462 (2026-09-05) deleted the in-place
substitution path (`services/pdf_substitute.py`) and with it founder decisions
D1 and D3: every clone is laid out again from scratch with reportlab — but with
the source's own logo, header block, page size and number formatting lifted off
page 1, so the result still looks like the tenant's invoice rather than a
generic template. The accepted tradeoff, stated by the founder when approving
the deletion: a clone is a clean re-render carrying the source's branding, NOT
a pixel-identical copy of the source layout.

The substitution path was deleted rather than fixed because it chose itself on
row count alone and then refused, with a 422, on the *ordinary* clone — new
dates and new totals over the same number of rows — asking the user to add or
remove a row to work around an internal renderer limitation.

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
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

import fitz  # PyMuPDF

from services.invoice_builder import BuildRequest, Totals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------
#
# BE Gap 462 (2026-09-05): these two helpers moved here verbatim from the
# deleted `services/pdf_substitute.py`. They were always about *reading the
# source's printed money style and reproducing it*, which the re-render needs
# just as much as substitution did — `render_invoice()` formats every figure
# through `format_like()`, and `routers/outbound_invoices.py` samples the
# source's own grand total through `number_renderings()` to find that style.

_NUM_RE = re.compile(
    r"^(?P<pre>[^0-9-]*)(?P<sign>-?)(?P<num>[0-9][0-9.,\s ']*[0-9]|[0-9])(?P<post>.*)$"
)
_GROUP_CHARS = ".,  '"


def format_like(sample: str, value: Decimal) -> str:
    """Render `value` using the separator style and decimal places of `sample`.

    Pure. `format_like("1.250,00", Decimal("2000"))` → `"2.000,00"`;
    `format_like("1,250.00", Decimal("2000"))` → `"2,000.00"`;
    `format_like("1250.00", ...)` → `"2000.00"` (no grouping was observed, so
    none is invented). Any prefix/suffix in the sample (a currency symbol, a
    trailing code) is preserved around the new number.

    A separator followed by exactly three digits is read as grouping, not as a
    decimal point — the standard, and the only reading under which `1.250` and
    `1,250` both mean one thousand two hundred and fifty.
    """
    match = _NUM_RE.match((sample or "").strip())
    if not match:
        dec_sep, grp_sep, places, pre, post = ".", "", 2, "", ""
    else:
        pre, post = match.group("pre"), match.group("post")
        num = match.group("num")
        seps = [(i, c) for i, c in enumerate(num) if c in _GROUP_CHARS]
        dec_sep, grp_sep, places = "", "", 0
        if seps:
            last_i, last_c = seps[-1]
            tail = len(num) - last_i - 1
            if last_c in ".," and 1 <= tail <= 2:
                dec_sep, places = last_c, tail
                others = [c for i, c in seps[:-1]]
            else:
                others = [c for i, c in seps]
            if others:
                grp_sep = others[-1]

    quant = Decimal(1).scaleb(-places)
    q = value.quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    digits = f"{abs(q):f}"
    if "." in digits:
        int_part, frac = digits.split(".", 1)
    else:
        int_part, frac = digits, ""

    if grp_sep:
        chunks = []
        while len(int_part) > 3:
            chunks.insert(0, int_part[-3:])
            int_part = int_part[:-3]
        chunks.insert(0, int_part)
        int_part = grp_sep.join(chunks)

    body = int_part + (dec_sep + frac if places and dec_sep else "")
    return f"{pre}{sign}{body}{post}"


def number_renderings(value: Decimal) -> list[str]:
    """Every plausible way the source might have printed `value`, most likely
    first. Used as the search list; whichever one the page actually contains
    becomes the `format_like` sample for the re-rendered figures."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    plain = f"{abs(q):.2f}"
    int_part, frac = plain.split(".")
    sign = "-" if q < 0 else ""

    def grouped(sep: str) -> str:
        chunks, rest = [], int_part
        while len(rest) > 3:
            chunks.insert(0, rest[-3:])
            rest = rest[:-3]
        chunks.insert(0, rest)
        return sep.join(chunks)

    out = [
        f"{sign}{grouped(',')}.{frac}",
        f"{sign}{int_part}.{frac}",
        f"{sign}{grouped('.')},{frac}",
        f"{sign}{int_part},{frac}",
        f"{sign}{grouped(' ')},{frac}",
        f"{sign}{grouped(' ')}.{frac}",
    ]
    if frac == "00":
        out += [f"{sign}{grouped(',')}", f"{sign}{int_part}", f"{sign}{grouped('.')}"]
    # Quantities print as `2` or `2.5` far more often than `2.00`.
    trimmed = f"{q.normalize():f}"
    if trimmed not in out:
        out.append(trimmed)
    seen, unique = set(), []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique

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
    # BE Gap 463: the PO number and the secondary references. Before this they
    # were carried by `BuildRequest` at all only if `harvest_branding()` had
    # scraped them into the header band, which it deliberately does not (they
    # match `_META_LINE` and are dropped as the *source's* metadata).
    if req.po_number:
        story.append(Paragraph(f"PO Number: {_escape(req.po_number)}", normal))
    for reference in req.references:
        label = (reference.ref_type or "Reference").strip()
        if (reference.value or "").strip():
            story.append(Paragraph(f"{_escape(label)}: {_escape(reference.value)}", normal))
    story.append(Spacer(1, 10))

    usable = doc.width

    # --- the party blocks (BE Gap 463) --------------------------------------
    #
    # "From" is the tenant; "Bill To" and "Ship To" are the customer's. Each
    # column is omitted entirely when it has nothing in it, rather than printed
    # as an empty heading — an invoice with no shipping address should not
    # print the words "Ship To".
    party_columns: list[list] = []
    vendor_block = _party_block("From", req.vendor_name, _address_text(req.addresses, "vendor"), normal)
    if vendor_block:
        party_columns.append(vendor_block)
    party_columns.append(
        _party_block("Bill To", req.customer_name, _address_text(req.addresses, "billing"), normal)
        or [Paragraph("<b>Bill To</b>", normal)]
    )
    ship_block = _party_block("Ship To", None, _address_text(req.addresses, "shipping"), normal)
    if ship_block:
        party_columns.append(ship_block)
    # Any address whose type is none of the three known values still prints —
    # losing an address because the extractor called it something unexpected is
    # exactly the failure this gap exists to stop.
    other_block = _party_block("Address", None, _address_text(req.addresses, None), normal)
    if other_block:
        party_columns.append(other_block)

    party_table = Table(
        [party_columns],
        colWidths=[usable / len(party_columns)] * len(party_columns),
    )
    party_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(party_table)
    story.append(Spacer(1, 12))

    def fmt(value: Decimal) -> str:
        return format_like(number_style, value)

    # --- the line-item table ------------------------------------------------
    #
    # Columns appear only when at least one row uses them (BE Gap 463): a plain
    # invoice still prints exactly Description / Qty / Unit Price / Amount, the
    # four columns this table had before, at the same widths.
    show_hsn = any((i.hsn_sac_code or "").strip() for i in req.items)
    show_uom = any((i.uom or "").strip() for i in req.items)
    show_line_discount = any(d for d in totals.line_discounts)
    show_line_tax = any(t for t in totals.line_taxes)

    spec: list[tuple[str, float]] = [("Description", 0.52)]
    if show_hsn:
        spec.append(("HSN/SAC", 0.10))
    spec.append(("Qty", 0.10))
    if show_uom:
        spec.append(("UOM", 0.08))
    spec.append(("Unit Price", 0.19))
    if show_line_discount:
        spec.append(("Discount", 0.13))
    if show_line_tax:
        spec.append(("Tax", 0.13))
    spec.append(("Amount", 0.19))
    weight_total = sum(weight for _heading, weight in spec)
    col_widths = [usable * weight / weight_total for _heading, weight in spec]

    rows = [[heading for heading, _weight in spec]]
    for idx, item in enumerate(req.items):
        amount = totals.line_amounts[idx] if idx < len(totals.line_amounts) else Decimal("0.00")
        row: list = [Paragraph(_escape(item.description or ""), normal)]
        if show_hsn:
            row.append(_escape(item.hsn_sac_code or ""))
        row.append(_quantity_text(item.quantity))
        if show_uom:
            row.append(_escape(item.uom or ""))
        row.append(fmt(item.unit_price if item.unit_price is not None else Decimal("0")))
        if show_line_discount:
            row.append(fmt(totals.line_discounts[idx]) if idx < len(totals.line_discounts) else "")
        if show_line_tax:
            row.append(fmt(totals.line_taxes[idx]) if idx < len(totals.line_taxes) else "")
        row.append(fmt(amount))
        rows.append(row)

    table = Table(rows, colWidths=col_widths, repeatRows=1)
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

    # --- the totals block ---------------------------------------------------
    #
    # One row per printed figure. Every value comes from `Totals`, i.e. from
    # `compute_totals()`; nothing here does arithmetic of its own, because two
    # places computing the same total is how they come to disagree.
    currency = (req.currency or "").strip()
    summary_rows: list[list[str]] = [["Subtotal", fmt(totals.subtotal)]]
    for idx, discount in enumerate(req.discounts):
        resolved = totals.discount_lines[idx] if idx < len(totals.discount_lines) else Decimal("0.00")
        summary_rows.append([_rate_label(discount.discount_type or "Discount", discount.percent), fmt(-resolved)])
    if not req.discounts and totals.discount_total:
        summary_rows.append([_rate_label("Discount", req.discount_percent), fmt(-totals.discount_total)])
    if req.taxes:
        for idx, tax in enumerate(req.taxes):
            resolved = totals.tax_lines[idx] if idx < len(totals.tax_lines) else Decimal("0.00")
            summary_rows.append([_rate_label(tax.tax_type or "Tax", tax.rate_percent), fmt(resolved)])
    else:
        summary_rows.append(["Tax", fmt(totals.tax_amount)])
    for idx, deduction in enumerate(req.deductions):
        resolved = totals.deduction_lines[idx] if idx < len(totals.deduction_lines) else Decimal("0.00")
        summary_rows.append([_escape(deduction.deduction_type or "Deduction"), fmt(-resolved)])
    summary_rows.append([
        f"Total Due{(' (' + currency + ')') if currency else ''}",
        fmt(totals.grand_total),
    ])

    summary = Table(summary_rows, colWidths=[usable * 0.81, usable * 0.19])
    last = len(summary_rows) - 1
    summary.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, last), (-1, last), 0.75, colors.black),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
    ]))
    story.append(summary)

    # --- payment, notes, compliance (BE Gap 463) ----------------------------
    if req.payment_instructions:
        story.append(Spacer(1, 14))
        story.append(Paragraph("<b>Payment Instructions</b>", normal))
        for instruction in req.payment_instructions:
            label = (instruction.method_type or "").strip()
            details = (instruction.details or "").strip()
            if not (label or details):
                continue
            story.append(Paragraph(
                f"{_escape(label)}: {_escape(details)}" if label else _escape(details), normal,
            ))

    if (req.notes or "").strip():
        story.append(Spacer(1, 14))
        story.append(Paragraph("<b>Notes</b>", normal))
        for line in str(req.notes).splitlines():
            if line.strip():
                story.append(Paragraph(_escape(line), normal))

    compliance_lines = [
        f"{(t.id_type or 'Tax ID').strip()}"
        + (f" ({t.party.strip()})" if (t.party or "").strip() else "")
        + f": {(t.value or '').strip()}"
        for t in req.tax_ids
        if (t.value or "").strip()
    ] + [
        f"{(c.key or '').strip()}: {(c.value or '').strip()}"
        for c in req.compliance_metadata
        if (c.value or "").strip()
    ]
    if compliance_lines:
        story.append(Spacer(1, 14))
        for line in compliance_lines:
            story.append(Paragraph(_escape(line), small))

    if branding.footer_lines:
        story.append(Spacer(1, 18))
        for line in branding.footer_lines:
            story.append(Paragraph(_escape(line), small))

    doc.build(story)
    return buf.getvalue()


def _address_text(addresses, address_type: str | None) -> str:
    """The address text for one block. `None` means "every address whose type
    is not one of the three the renderer already places" — an unexpected type
    is printed rather than dropped (BE Gap 463)."""
    known = {"billing", "shipping", "vendor"}
    parts: list[str] = []
    for address in addresses or []:
        kind = (address.address_type or "").strip().lower()
        if address_type is None:
            if kind in known:
                continue
        elif kind != address_type:
            continue
        text = (address.text or "").strip()
        country = (address.country or "").strip()
        if country and country.lower() not in text.lower():
            text = f"{text}\n{country}" if text else country
        if text:
            parts.append(text)
    return "\n".join(parts)


def _party_block(heading: str, name: str | None, address: str, style) -> list:
    """A titled address column, or `[]` when there is nothing to print."""
    from reportlab.platypus import Paragraph

    name = (name or "").strip()
    if not name and not address:
        return []
    block = [Paragraph(f"<b>{_escape(heading)}</b>", style)]
    if name:
        block.append(Paragraph(_escape(name), style))
    for line in address.splitlines():
        if line.strip():
            block.append(Paragraph(_escape(line), style))
    return block


def _rate_label(label: str, percent: Decimal | None) -> str:
    """`CGST` → `CGST`, `CGST` + 9 → `CGST (9%)`. The rate is printed as typed
    (`9`, not `9.00`), the same rule `_quantity_text()` follows."""
    text = _escape((label or "").strip())
    if percent is None:
        return text
    normalized = Decimal(percent).normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return f"{text} ({normalized:f}%)"


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
