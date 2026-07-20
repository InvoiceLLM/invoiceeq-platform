"""Generates realistic-looking invoice PDFs from structured data for e2e fixtures.

Layout fidelity doesn't matter here (the pipeline reads via OCR + vision, not
pixel-perfect templates) — only that the same information a human would see
on a real invoice (header fields, a line-items table, a totals block) is
present and readable.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def build_invoice_pdf(path: str, vendor_lines: list[str], meta_lines: list[str],
                       bill_to_lines: list[str], columns: list[str], rows: list[list[str]],
                       summary_rows: list[list[str]], notes: list[str] | None = None) -> None:
    """
    vendor_lines: vendor name/address block (left header)
    meta_lines: invoice number/date/etc (right header)
    bill_to_lines: "Bill To" block
    columns: line-items table header row
    rows: line-items table data rows
    summary_rows: [[label, value], ...] rendered as a right-aligned totals block
    notes: optional footer notes/legal text lines
    """
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16)
    normal = styles["Normal"]

    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    story = [Paragraph("INVOICE", title_style), Spacer(1, 8)]

    for line in vendor_lines:
        story.append(Paragraph(line, normal))
    story.append(Spacer(1, 6))
    for line in meta_lines:
        story.append(Paragraph(line, normal))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Bill To:</b>", normal))
    for line in bill_to_lines:
        story.append(Paragraph(line, normal))
    story.append(Spacer(1, 12))

    table_data = [columns] + rows
    item_table = Table(table_data, repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3B57")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 12))

    summary_table = Table(summary_rows, colWidths=[300, 100])
    summary_style = [
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
    summary_style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    summary_style.append(("LINEABOVE", (0, -1), (-1, -1), 1, colors.black))
    summary_table.setStyle(TableStyle(summary_style))
    story.append(summary_table)

    if notes:
        story.append(Spacer(1, 16))
        for line in notes:
            story.append(Paragraph(line, ParagraphStyle("Note", parent=normal, fontSize=7, textColor=colors.grey)))

    doc.build(story)
