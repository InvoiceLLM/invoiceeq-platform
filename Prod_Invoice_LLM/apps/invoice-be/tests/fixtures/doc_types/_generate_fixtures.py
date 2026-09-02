"""Generates realistic synthetic PDFs for Feature 27 (generic document
extraction) taxonomy fixtures -- Task F, functional-tester.

Standalone generator (deliberately not reusing tests/e2e/pdf_builder.py,
which hardcodes a literal INVOICE title -- exactly the title band this
feature classifier must NOT see on a delivery note or proforma). Layout
fidelity mirrors that file own stated standard: not pixel-perfect, but
every field a human reader would see on the real regional document is
present, in the real regional format (Indian GSTIN/HSN, German USt-IdNr.,
EU comma-decimal currency, US customs framing).

Run manually to regenerate:
    uv run python tests/fixtures/doc_types/_generate_fixtures.py

Each fixture function below is independent and documents, in its own
docstring, which section 7 table cell it fills and why the layout choices
were made. See MANIFEST.md in this directory for the ground-truth record
this script output is checked against.
"""
from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

HERE = os.path.dirname(os.path.abspath(__file__))


def _build(path, title, header_lines, meta_lines, party_label, party_lines,
           columns, rows, summary_rows, notes):
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16)
    normal = styles["Normal"]

    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    story = [Paragraph(title, title_style), Spacer(1, 8)]

    for line in header_lines:
        story.append(Paragraph(line, normal))
    story.append(Spacer(1, 6))
    for line in meta_lines:
        story.append(Paragraph(line, normal))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>" + party_label + "</b>", normal))
    for line in party_lines:
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

    if summary_rows:
        summary_table = Table(summary_rows, colWidths=[300, 100])
        summary_style = [
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ]
        summary_table.setStyle(TableStyle(summary_style))
        story.append(summary_table)

    if notes:
        story.append(Spacer(1, 16))
        for line in notes:
            story.append(Paragraph(line, ParagraphStyle("Note", parent=normal, fontSize=7,
                                                          textColor=colors.grey)))
    doc.build(story)


def gen_in_delivery_note_01():
    """India inbound DELIVERY_NOTE -- Delivery Challan synonym, Rule 55
    CGST Rules framing. No prices printed (the case the quantity rubric
    exists for; the whole point of a challan is that warehouse staff
    receiving it cannot see pricing). Section 7 cell: DELIVERY_NOTE /
    India (required).
    """
    path = os.path.join(HERE, "delivery_note", "india_inbound", "IN-DN-01_delivery_challan_no_prices.pdf")
    _build(
        path=path,
        title="DELIVERY CHALLAN",
        header_lines=[
            "Ashoka Precision Components Pvt Ltd",
            "Plot 47, MIDC Industrial Area, Pune, MH 411019, India",
            "GSTIN: 27AAJCA9988P1Z3",
        ],
        meta_lines=[
            "<b>Challan No:</b> DC-2026-0871 &nbsp;&nbsp; <b>Challan Date:</b> 2026-08-14",
            "<b>PO Reference:</b> PO-IN-6102 &nbsp;&nbsp; <b>Vehicle No:</b> MH-12-AB-4471",
            "<b>Transporter:</b> Bharat Road Carriers",
            "(Delivery Challan issued under Rule 55 of the CGST Rules, 2017)",
        ],
        party_label="Consignee (Ship To):",
        party_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        columns=["S.No", "Description of Goods", "HSN Code", "Qty", "UOM"],
        rows=[
            ["1", "CNC Machined Bracket - Type A", "8479", "250", "Nos"],
            ["2", "CNC Machined Bracket - Type B", "8479", "120", "Nos"],
            ["3", "Mounting Plate Assembly", "8479", "60", "Nos"],
        ],
        summary_rows=None,
        notes=[
            "This is a Delivery Challan for the movement of goods and is NOT a Tax Invoice. "
            "No value or tax is charged on this document.",
            "Goods dispatched as per Purchase Order PO-IN-6102. E-way Bill No: 341122009987.",
            "Received in good condition (signature and date): ______________________",
        ],
    )
    return path


def gen_eu_delivery_note_01():
    """EU (Germany) inbound DELIVERY_NOTE -- Lieferschein synonym, the
    exact E4 example. No prices printed. Section 7 cell: DELIVERY_NOTE /
    EU (required -- proves synonym recognition beyond the India label).
    """
    path = os.path.join(HERE, "delivery_note", "eu_inbound", "EU-DN-01_lieferschein_no_prices.pdf")
    _build(
        path=path,
        title="LIEFERSCHEIN",
        header_lines=[
            "Muller Praezisionstechnik GmbH",
            "Industriestrasse 22, 70565 Stuttgart, Deutschland",
            "USt-IdNr.: DE813456712",
        ],
        meta_lines=[
            "<b>Lieferschein-Nr.:</b> LS-2026-4471 &nbsp;&nbsp; <b>Lieferdatum:</b> 2026-08-11",
            "<b>Bestellnummer:</b> PO-EU-3390 &nbsp;&nbsp; <b>Spediteur:</b> DACH Logistik GmbH",
        ],
        party_label="Empfaenger (Lieferadresse):",
        party_lines=[
            "Nordwind Handels GmbH",
            "Hafenstrasse 8, 20457 Hamburg, Deutschland",
            "USt-IdNr.: DE298471166",
        ],
        columns=["Pos.", "Beschreibung", "Menge", "Einheit"],
        rows=[
            ["1", "Hydraulikzylinder HZ-400", "40", "Stk"],
            ["2", "Dichtungssatz HZ-400", "80", "Stk"],
            ["3", "Montageplatte Typ C", "20", "Stk"],
        ],
        summary_rows=None,
        notes=[
            "Dies ist ein Lieferschein und keine Rechnung. Es wird kein Betrag berechnet.",
            "Die Ware wurde gemaess Bestellung PO-EU-3390 vollstaendig geliefert.",
            "Wareneingang bestaetigt (Unterschrift, Datum): ______________________",
        ],
    )
    return path


def gen_in_proforma_invoice_01():
    """India inbound PROFORMA_INVOICE -- structurally invoice-shaped
    (line items, tax-like figures, grand total) but explicitly NOT a tax
    document; used to open an LC / arrange advance payment. Zero existing
    fixtures anywhere in the repo for this type (spec-flagged gap).
    """
    path = os.path.join(HERE, "proforma_invoice", "india_inbound", "IN-PI-01_proforma_invoice.pdf")
    _build(
        path=path,
        title="PROFORMA INVOICE",
        header_lines=[
            "Vishwakarma Forgings Ltd",
            "Sector 58, Industrial Estate, Faridabad, HR 121004, India",
            "GSTIN: 06AAECV4321R1Z8",
        ],
        meta_lines=[
            "<b>Proforma Invoice No:</b> PI-2026-1187 &nbsp;&nbsp; <b>Date:</b> 2026-08-05",
            "<b>Buyer PO Reference:</b> PO-IN-7710 &nbsp;&nbsp; <b>Validity:</b> 30 days from date",
            "<b>Payment Terms:</b> 50% advance by wire transfer against this Proforma; balance against Tax Invoice before shipment",
            "<b>Incoterms:</b> FOB Nhava Sheva",
        ],
        party_label="Buyer:",
        party_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        columns=["Description", "HSN Code", "Qty", "Unit Price (Rs)", "Amount (Rs)"],
        rows=[
            ["Forged Steel Flange - 6 inch", "7326", "500", "1,250.00", "6,25,000.00"],
            ["Forged Steel Flange - 8 inch", "7326", "300", "1,850.00", "5,55,000.00"],
        ],
        summary_rows=[
            ["Subtotal", "Rs 11,80,000.00"],
            ["Estimated GST (18 percent, payable on final Tax Invoice, not this document)", "Rs 2,12,400.00"],
            ["Estimated Total", "Rs 13,92,400.00"],
        ],
        notes=[
            "This is a Proforma Invoice, issued to enable the Buyer to arrange advance "
            "payment / open a Letter of Credit. It is NOT a Tax Invoice, creates no GST "
            "input-tax credit, and is not a demand for payment in itself.",
            "A Tax Invoice under Section 31 of the CGST Act will be issued at the time of "
            "actual shipment, reflecting final quantities and applicable GST.",
        ],
    )
    return path


def gen_eu_proforma_invoice_01():
    """EU (Germany) inbound PROFORMA_INVOICE -- Proforma-Rechnung, the
    real regional label used interchangeably with the English term on
    German commercial paperwork. Reverse-charge note included since that
    is the common EU cross-border case.
    """
    path = os.path.join(HERE, "proforma_invoice", "eu_inbound", "EU-PI-01_proforma_rechnung.pdf")
    _build(
        path=path,
        title="PROFORMA-RECHNUNG / PROFORMA INVOICE",
        header_lines=[
            "Bergmann Elektrotechnik GmbH",
            "Ringstrasse 14, 90411 Nuernberg, Deutschland",
            "USt-IdNr.: DE145278933",
        ],
        meta_lines=[
            "<b>Proforma-Rechnung Nr.:</b> PF-2026-0562 &nbsp;&nbsp; <b>Datum:</b> 2026-08-09",
            "<b>Bestellnummer:</b> PO-EU-4415 &nbsp;&nbsp; <b>Gueltigkeit:</b> 21 Tage",
            "<b>Zahlungsbedingungen:</b> 100% Vorauszahlung vor Versand",
            "<b>Incoterms:</b> EXW Nuernberg",
        ],
        party_label="Kaeufer / Buyer:",
        party_lines=[
            "Meridian Automation Ltd",
            "12 Kettering Road, Manchester M1 4BT, United Kingdom",
            "VAT No: GB741852963",
        ],
        columns=["Beschreibung", "Menge", "Einzelpreis (EUR)", "Betrag (EUR)"],
        rows=[
            ["Frequenzumrichter FU-750", "15", "620,00", "9.300,00"],
            ["Bediengeraet BG-10", "15", "145,00", "2.175,00"],
        ],
        summary_rows=[
            ["Zwischensumme / Subtotal", "11.475,00 EUR"],
            ["USt. (Reverse Charge, innergemeinschaftlich -- 0%)", "0,00 EUR"],
            ["Gesamtbetrag / Total (voraussichtlich)", "11.475,00 EUR"],
        ],
        notes=[
            "Dies ist eine Proforma-Rechnung / This is a Proforma Invoice. Sie ist keine "
            "Handelsrechnung im steuerlichen Sinne und begruendet keine Zahlungsverpflichtung "
            "aus sich selbst heraus.",
            "Reverse-Charge-Verfahren: Steuerschuldnerschaft des Leistungsempfaengers gemaess "
            "Art. 196 MwStSystRL. Die endgueltige Rechnung wird nach Versand ausgestellt.",
        ],
    )
    return path


def gen_us_proforma_invoice_01():
    """US inbound PROFORMA_INVOICE -- customs-declaration framing, the
    common US usage (a pro forma invoice submitted with a shipment for
    customs valuation before the real commercial invoice exists).
    """
    path = os.path.join(HERE, "proforma_invoice", "us_inbound", "US-PI-01_pro_forma_invoice.pdf")
    _build(
        path=path,
        title="PRO FORMA INVOICE",
        header_lines=[
            "Cascade Industrial Supply LLC",
            "4820 Harborview Drive, Seattle, WA 98134, USA",
            "EIN: 91-2233445",
        ],
        meta_lines=[
            "<b>Pro Forma Invoice No:</b> PF-2026-2209 &nbsp;&nbsp; <b>Date:</b> 08/07/2026",
            "<b>Buyer PO Reference:</b> PO-US-8841 &nbsp;&nbsp; <b>Validity:</b> 15 days",
            "<b>Payment Terms:</b> Advance wire transfer, 100% before shipment",
        ],
        party_label="Buyer / Consignee:",
        party_lines=[
            "Northgate Manufacturing Inc.",
            "220 Commerce Park Blvd, Austin, TX 78701, USA",
        ],
        columns=["Description", "Qty", "Unit Price ($)", "Amount ($)"],
        rows=[
            ["Stainless Steel Fastener Kit, Grade 316", "800", "4.25", "3,400.00"],
            ["Industrial Gasket Set, Model IG-90", "200", "11.50", "2,300.00"],
        ],
        summary_rows=[
            ["Subtotal", "$5,700.00"],
            ["Estimated Freight and Insurance", "$310.00"],
            ["Estimated Total", "$6,010.00"],
        ],
        notes=[
            "FOR CUSTOMS PURPOSES ONLY. This Pro Forma Invoice is issued to facilitate "
            "advance payment and import documentation. It is NOT a demand for payment and "
            "is not the final Commercial Invoice.",
            "A final Commercial Invoice will be issued upon shipment reflecting actual "
            "quantities shipped and any applicable sales tax.",
        ],
    )
    return path



def gen_in_purchase_order_01():
    """India inbound PURCHASE_ORDER -- section 7 cell, zero prior coverage.
    Buyer-issued commercial PO with GSTIN on both sides, HSN codes and a
    printed order value (COMMITMENT family runs arithmetic where a total IS
    printed -- unlike CONTRACT, a PO conventionally states its own value).
    Dispatch-B priority group 1 (direct T-R-2/commitment-family subject).
    """
    path = os.path.join(HERE, "purchase_order", "india_inbound", "IN-PO-01_purchase_order.pdf")
    _build(
        path=path,
        title="PURCHASE ORDER",
        header_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        meta_lines=[
            "<b>PO No:</b> PO-IN-6102 &nbsp;&nbsp; <b>PO Date:</b> 2026-07-28",
            "<b>Vendor Ref/Quotation:</b> QTN-IN-2214 &nbsp;&nbsp; <b>Delivery Terms:</b> FOB Pune, within 3 weeks",
            "<b>Payment Terms:</b> 30 days from receipt of Tax Invoice",
        ],
        party_label="Vendor (Bill From):",
        party_lines=[
            "Vishwakarma Forgings Ltd",
            "Sector 58, Industrial Estate, Faridabad, HR 121004, India",
            "GSTIN: 06AAECV4321R1Z8",
        ],
        columns=["S.No", "Description", "HSN Code", "Qty", "Rate (Rs)", "Amount (Rs)"],
        rows=[
            ["1", "Forged Steel Flange - 6 inch", "7326", "400", "1,150.00", "4,60,000.00"],
            ["2", "Forged Steel Flange - 8 inch", "7326", "250", "1,700.00", "4,25,000.00"],
        ],
        summary_rows=[
            ["Subtotal", "Rs 8,85,000.00"],
            ["GST at 18 percent", "Rs 1,59,300.00"],
            ["Order Value (Grand Total)", "Rs 10,44,300.00"],
        ],
        notes=[
            "This Purchase Order is issued subject to our Standard Terms and Conditions "
            "of Purchase. Please confirm acceptance and expected delivery schedule "
            "within 5 working days.",
            "This is a Purchase Order and NOT a Tax Invoice. Please quote this PO number "
            "on your Delivery Challan and Tax Invoice.",
        ],
    )
    return path


def gen_us_purchase_order_01():
    """US inbound PURCHASE_ORDER -- section 7 cell. Multi-line delivery
    schedule (two distinct requested ship dates per line), the terms-heavy
    COMMITMENT-family shape E4 describes, with sales tax and a printed order
    total.
    """
    path = os.path.join(HERE, "purchase_order", "us_inbound", "US-PO-01_purchase_order.pdf")
    _build(
        path=path,
        title="PURCHASE ORDER",
        header_lines=[
            "Northgate Manufacturing Inc.",
            "220 Commerce Park Blvd, Austin, TX 78701, USA",
            "EIN: 74-1029384",
        ],
        meta_lines=[
            "<b>PO No:</b> PO-US-8841 &nbsp;&nbsp; <b>PO Date:</b> 08/12/2026",
            "<b>Incoterms:</b> FOB Origin &nbsp;&nbsp; <b>Payment Terms:</b> Net 45",
        ],
        party_label="Vendor:",
        party_lines=[
            "Cascade Industrial Supply LLC",
            "4820 Harborview Drive, Seattle, WA 98134, USA",
        ],
        columns=["Line", "Description", "Qty", "Unit Price ($)", "Amount ($)", "Requested Ship Date"],
        rows=[
            ["1", "Industrial Conveyor Belt, Model CB-500", "10", "2,450.00", "24,500.00", "09/20/2026"],
            ["2", "Replacement Roller Assembly", "40", "185.00", "7,400.00", "10/05/2026"],
        ],
        summary_rows=[
            ["Subtotal", "$31,900.00"],
            ["Sales Tax (8.5 percent)", "$2,711.50"],
            ["Order Total (Grand Total)", "$34,611.50"],
        ],
        notes=[
            "This Purchase Order is an offer subject to Buyer's standard terms and "
            "conditions of purchase, attached by reference. Please confirm acceptance "
            "within 5 business days.",
            "This is a Purchase Order and does not authorize payment. Invoice against "
            "this PO number only upon shipment of the corresponding line.",
        ],
    )
    return path


def gen_in_contract_01():
    """India inbound CONTRACT -- Rate Contract, the required no-grand-total
    case (E4/T-R-2: "a CONTRACT frequently has no grand total at all --
    rate cards, framework agreements"). "Rate Contract" is an exact
    _DOC_TYPE_SYNONYMS entry, so this is the deterministic-pass proof for
    CONTRACT. Deliberately carries per-unit rates only, no quantities, no
    amounts, no summary table at all -- actual order value is determined by
    future Release Orders raised against this Rate Contract, which is stated
    explicitly rather than left to be inferred from an absent total.
    """
    path = os.path.join(HERE, "contract", "india_inbound", "IN-CT-01_rate_contract_no_total.pdf")
    _build(
        path=path,
        title="RATE CONTRACT",
        header_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        meta_lines=[
            "<b>Rate Contract No:</b> RC-IN-2026-014 &nbsp;&nbsp; <b>Effective Date:</b> 2026-09-01",
            "<b>Validity Period:</b> 12 months from Effective Date &nbsp;&nbsp; "
            "<b>Vendor Ref:</b> VQ-2214",
        ],
        party_label="Vendor:",
        party_lines=[
            "Vishwakarma Forgings Ltd",
            "Sector 58, Industrial Estate, Faridabad, HR 121004, India",
            "GSTIN: 06AAECV4321R1Z8",
        ],
        columns=["S.No", "Item Description", "HSN Code", "Unit Rate (Rs, excl. GST)", "UOM"],
        rows=[
            ["1", "Forged Steel Flange - 6 inch", "7326", "1,150.00", "Nos"],
            ["2", "Forged Steel Flange - 8 inch", "7326", "1,700.00", "Nos"],
        ],
        summary_rows=None,
        notes=[
            "This Rate Contract establishes fixed unit prices, valid for the Validity "
            "Period stated above. It states no order quantity and no total contract "
            "value. Actual quantities and order value will be determined by individual "
            "Release Orders issued against this Rate Contract from time to time.",
            "GST will be charged additionally at the rate applicable on the date of the "
            "corresponding Release Order / Tax Invoice.",
            "Either party may terminate this Rate Contract on 30 days written notice.",
        ],
    )
    return path


def gen_eu_contract_01():
    """EU (Germany) inbound CONTRACT -- Rahmenvertrag (framework agreement).
    Deliberately titled ONLY with the German label, which is NOT in
    _DOC_TYPE_SYNONYMS (that map lists the English "framework agreement" but
    no German synonym -- a documented, deliberate scope gap in the module's
    own comments). This is the fixture that genuinely exercises the E7 LLM
    fallback path end to end (not mocked) rather than the deterministic pass,
    and is real evidence for whether a German CONTRACT synonym should be
    added to the table. Also carries no grand total, for the same reason as
    the India rate-contract fixture -- per-unit rates only.
    """
    path = os.path.join(HERE, "contract", "eu_inbound", "EU-CT-01_rahmenvertrag_no_total.pdf")
    _build(
        path=path,
        title="RAHMENVERTRAG",
        header_lines=[
            "Nordwind Handels GmbH",
            "Hafenstrasse 8, 20457 Hamburg, Deutschland",
            "USt-IdNr.: DE298471166",
        ],
        meta_lines=[
            "<b>Rahmenvertrag-Nr.:</b> RV-2026-0091 &nbsp;&nbsp; <b>Vertragsbeginn:</b> 01.09.2026",
            "<b>Laufzeit:</b> 24 Monate &nbsp;&nbsp; <b>Kundennummer:</b> KD-40218",
        ],
        party_label="Vertragspartner (Lieferant):",
        party_lines=[
            "Muller Praezisionstechnik GmbH",
            "Industriestrasse 22, 70565 Stuttgart, Deutschland",
            "USt-IdNr.: DE813456712",
        ],
        columns=["Pos.", "Leistungsbeschreibung", "Einheitspreis (EUR)", "Einheit"],
        rows=[
            ["1", "Wartungsdienstleistung - Standardanlage", "480,00", "pro Einsatz"],
            ["2", "Wartungsdienstleistung - Grossanlage", "950,00", "pro Einsatz"],
        ],
        summary_rows=None,
        notes=[
            "Dieser Rahmenvertrag legt Einheitspreise fuer die genannte Vertragslaufzeit "
            "fest. Er nennt keine Bestellmenge und keinen Gesamtwert. Die tatsaechliche "
            "Bestellmenge und der Auftragswert werden durch einzelne Abrufauftraege "
            "(Einzelbestellungen) auf Grundlage dieses Rahmenvertrags bestimmt.",
            "Kuendigung: Beide Parteien koennen diesen Rahmenvertrag mit einer Frist von "
            "60 Tagen zum Monatsende schriftlich kuendigen.",
        ],
    )
    return path


def gen_in_quotation_01():
    """India inbound QUOTATION -- section 7 cell, zero prior coverage.
    Structurally distinguished from PROFORMA_INVOICE by being an open-ended
    offer (no committed buyer PO reference, prices explicitly "subject to
    change" and "subject to confirmation") -- the exact distinction section 7
    calls out for the proforma fixtures in reverse. COMMITMENT family per
    document_type_classifier.py's provisional mapping.
    """
    path = os.path.join(HERE, "quotation", "india_inbound", "IN-QT-01_quotation.pdf")
    _build(
        path=path,
        title="QUOTATION",
        header_lines=[
            "Vishwakarma Forgings Ltd",
            "Sector 58, Industrial Estate, Faridabad, HR 121004, India",
            "GSTIN: 06AAECV4321R1Z8",
        ],
        meta_lines=[
            "<b>Quotation No:</b> QTN-IN-2214 &nbsp;&nbsp; <b>Date:</b> 2026-07-20",
            "<b>Validity:</b> 15 days from date of issue &nbsp;&nbsp; "
            "<b>In response to your RFQ dated:</b> 2026-07-15",
        ],
        party_label="To (Prospective Buyer):",
        party_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        columns=["Description", "HSN Code", "Qty (Indicative)", "Unit Price (Rs)", "Amount (Rs)"],
        rows=[
            ["Hydraulic Cylinder Assembly HC-250", "8412", "50", "3,200.00", "1,60,000.00"],
            ["Seal Kit HC-250", "8412", "50", "450.00", "22,500.00"],
        ],
        summary_rows=[
            ["Subtotal (Indicative)", "Rs 1,82,500.00"],
            ["GST at 18 percent (Indicative)", "Rs 32,850.00"],
            ["Total (Indicative)", "Rs 2,15,350.00"],
        ],
        notes=[
            "This is a Quotation only and does not constitute an order, a commitment, or "
            "a demand for payment. No Purchase Order has been received against this "
            "Quotation.",
            "Prices are indicative and subject to change without notice; final pricing "
            "is subject to confirmation at the time a Purchase Order is placed.",
        ],
    )
    return path


def gen_in_grn_01():
    """India inbound GRN -- Goods Receipt Note, section 7 cell. Realistic
    synthetic per E4's explicit allowance ("low-frequency/internal-origin...
    realistic synthetic sample is acceptable here where a real sample cannot
    be obtained"). Modelled on E4's stated real-world appearance: an
    enterprise buyer's internal receiving-department document, shared with
    the supplier specifically to substantiate a short-delivery claim (line 2
    deliberately shows Qty Received less than Qty Ordered, with a Remarks
    note) -- not a schematic placeholder. QUANTITY family, same as
    DELIVERY_NOTE.
    """
    path = os.path.join(HERE, "grn", "india_inbound", "IN-GRN-01_goods_receipt_note.pdf")
    _build(
        path=path,
        title="GOODS RECEIPT NOTE",
        header_lines=[
            "Infinevo Cloud Pvt Ltd -- Stores and Warehouse Department",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        meta_lines=[
            "<b>GRN No:</b> GRN-2026-0341 &nbsp;&nbsp; <b>GRN Date:</b> 2026-08-15",
            "<b>PO Reference:</b> PO-IN-6102 &nbsp;&nbsp; "
            "<b>Delivery Challan Reference:</b> DC-2026-0871",
            "<b>Vehicle No:</b> MH-12-AB-4471",
        ],
        party_label="Supplier:",
        party_lines=[
            "Ashoka Precision Components Pvt Ltd",
            "Plot 47, MIDC Industrial Area, Pune, MH 411019, India",
            "GSTIN: 27AAJCA9988P1Z3",
        ],
        columns=["S.No", "Description", "HSN Code", "Qty Ordered", "Qty Received", "UOM", "Remarks"],
        rows=[
            ["1", "CNC Machined Bracket - Type A", "8479", "250", "250", "Nos", "OK"],
            ["2", "CNC Machined Bracket - Type B", "8479", "120", "110", "Nos", "Short by 10 -- 2 damaged, 8 not loaded"],
            ["3", "Mounting Plate Assembly", "8479", "60", "60", "Nos", "OK"],
        ],
        summary_rows=None,
        notes=[
            "Internal Goods Receipt Note issued by the Stores and Warehouse Department "
            "for goods physically received against the referenced Purchase Order and "
            "Delivery Challan. Shared with the Supplier to substantiate the "
            "short-delivery/damage claim noted on Line 2.",
            "Inspected by: ______________________  Received by: ______________________",
        ],
    )
    return path


def gen_in_other_bill_of_lading_01():
    """India-origin OTHER -- Bill of Lading, section 7 / E5 / T-C-4. Proves
    the classifier routes a transport/custody document to OTHER cleanly
    rather than mis-typing it -- no synonym in _DOC_TYPE_SYNONYMS matches
    "BILL OF LADING" (deliberately, per E5), so this exercises the real LLM
    fallback path, not a mocked one. Real B/L legal boilerplate included
    (negotiable-original clause) since a schematic placeholder would not
    exercise the classifier's actual judgement.
    """
    path = os.path.join(HERE, "other", "india_inbound", "IN-OTH-01_bill_of_lading.pdf")
    _build(
        path=path,
        title="BILL OF LADING",
        header_lines=[
            "Meridian Ocean Lines Pvt Ltd",
            "Nhava Sheva International Container Terminal, Maharashtra, India",
        ],
        meta_lines=[
            "<b>B/L No:</b> MAEU-4471902 &nbsp;&nbsp; <b>Vessel:</b> MV Northern Star "
            "&nbsp;&nbsp; <b>Voyage:</b> 118W",
            "<b>Port of Loading:</b> Nhava Sheva &nbsp;&nbsp; <b>Port of Discharge:</b> "
            "Rotterdam",
            "<b>Freight Terms:</b> PREPAID",
        ],
        party_label="Shipper:",
        party_lines=[
            "Ashoka Precision Components Pvt Ltd",
            "Plot 47, MIDC Industrial Area, Pune, MH 411019, India",
        ],
        columns=["Marks and Nos", "No. of Packages", "Description of Goods", "Gross Weight (kg)"],
        rows=[
            ["2 x 40HC", "48 crates", "Machine Parts, Not Otherwise Specified (NOS)", "18,400"],
        ],
        summary_rows=None,
        notes=[
            "Consignee: To Order.",
            "Received in apparent good order and condition, the goods described above, "
            "to be transported and delivered as stated herein. This Bill of Lading is a "
            "document of title. One of three (3) originals, any one of which being "
            "accomplished the others to stand void.",
        ],
    )
    return path


def gen_in_other_eway_bill_01():
    """India-origin OTHER -- e-Way Bill quoting its own Tax Invoice number,
    section 7 / E5 / T-C-4, the hard real-world case the classifier's
    title-band coverage guard must handle: an e-Way Bill quoting a
    tax-invoice number in its body must NOT classify as INVOICE. This is the
    same shape test_document_type_classifier.py's
    test_an_e_way_bill_quoting_its_tax_invoice_number_is_still_not_an_invoice
    uses as raw text, now as an actual rendered PDF fixture. The "Document
    Details: Tax Invoice No ..." line is written as a full sentence (not the
    bare phrase) precisely so its title-band coverage stays well under the
    0.6 threshold and it reads as a body reference, not a second title.
    """
    path = os.path.join(HERE, "other", "india_inbound", "IN-OTH-02_eway_bill_quoting_tax_invoice.pdf")
    _build(
        path=path,
        title="e-Way Bill",
        header_lines=[
            "Ashoka Precision Components Pvt Ltd",
            "Plot 47, MIDC Industrial Area, Pune, MH 411019, India",
            "GSTIN: 27AAJCA9988P1Z3",
        ],
        meta_lines=[
            "<b>EWB No:</b> 1810 0034 5567 &nbsp;&nbsp; <b>Generated Date:</b> "
            "2026-08-20 14:22",
            "<b>Valid Until:</b> 2026-08-22 &nbsp;&nbsp; <b>Mode:</b> Road &nbsp;&nbsp; "
            "<b>Approx Distance:</b> 412 km",
            "<b>Vehicle No:</b> MH-12-CD-9987",
            "<b>Document Details:</b> Tax Invoice No INV-2026-0447 dated 2026-08-20",
        ],
        party_label="Consignee (Ship To):",
        party_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        columns=["HSN Code", "Description of Goods", "Qty", "Taxable Value (Rs)"],
        rows=[
            ["7326", "Forged Steel Flange - 6 inch", "400", "4,60,000.00"],
            ["7326", "Forged Steel Flange - 8 inch", "250", "4,25,000.00"],
        ],
        summary_rows=None,
        notes=[
            "From: Pune, Maharashtra   To: Gurugram, Haryana.",
            "This e-Way Bill is generated for the movement of goods under Rule 138 of "
            "the CGST Rules, 2017 and is not itself a Tax Invoice or a demand for "
            "payment.",
        ],
    )
    return path


def gen_in_credit_note_01():
    """India inbound CREDIT_NOTE -- section 7 cell, zero prior coverage.
    MONEY family, so full arithmetic verification applies -- built internally
    consistent (qty x rate = amount, subtotal + GST = grand total) so it
    raises no discrepancy once verified end to end. Issued against a named
    original Tax Invoice, per real GST Section 34 practice, which is also
    the field a future matching feature would use to link this row back to
    the invoice it adjusts.
    """
    path = os.path.join(HERE, "credit_note", "india_inbound", "IN-CN-01_credit_note.pdf")
    _build(
        path=path,
        title="CREDIT NOTE",
        header_lines=[
            "Vishwakarma Forgings Ltd",
            "Sector 58, Industrial Estate, Faridabad, HR 121004, India",
            "GSTIN: 06AAECV4321R1Z8",
        ],
        meta_lines=[
            "<b>Credit Note No:</b> CN-2026-0091 &nbsp;&nbsp; <b>Date:</b> 2026-08-28",
            "<b>Against Original Tax Invoice No:</b> INV-2026-0447 &nbsp;&nbsp; "
            "<b>Invoice Date:</b> 2026-08-20",
            "<b>Reason for Credit:</b> Sales Return -- Item found defective on "
            "inspection",
        ],
        party_label="Issued To (Buyer):",
        party_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        columns=["Description", "HSN Code", "Qty", "Rate (Rs)", "Amount (Rs)"],
        rows=[
            ["Forged Steel Flange - 8 inch (Returned)", "7326", "20", "1,850.00", "37,000.00"],
        ],
        summary_rows=[
            ["Subtotal", "Rs 37,000.00"],
            ["GST Reversal at 18 percent", "Rs 6,660.00"],
            ["Total Credit Amount", "Rs 43,660.00"],
        ],
        notes=[
            "This Credit Note is issued under Section 34 of the CGST Act, 2017 against "
            "the original Tax Invoice referenced above.",
        ],
    )
    return path


def gen_in_debit_note_01():
    """India inbound DEBIT_NOTE -- section 7 cell, zero prior coverage.
    Mirror-image counterpart to the credit note above (price escalation
    against an original invoice rather than a return), same internal
    arithmetic consistency, MONEY family.
    """
    path = os.path.join(HERE, "debit_note", "india_inbound", "IN-DB-01_debit_note.pdf")
    _build(
        path=path,
        title="DEBIT NOTE",
        header_lines=[
            "Infinevo Cloud Pvt Ltd",
            "Tower B, Cyber Hub, Gurugram, HR 122002, India",
            "GSTIN: 06AABCI5678F1Z9",
        ],
        meta_lines=[
            "<b>Debit Note No:</b> DN-2026-0053 &nbsp;&nbsp; <b>Date:</b> 2026-08-30",
            "<b>Against Original Tax Invoice No:</b> INV-2026-0512 &nbsp;&nbsp; "
            "<b>Invoice Date:</b> 2026-08-22",
            "<b>Reason for Debit:</b> Price escalation -- raw material cost increase "
            "per agreed Rate Contract clause 4.2",
        ],
        party_label="Issued To (Vendor):",
        party_lines=[
            "Vishwakarma Forgings Ltd",
            "Sector 58, Industrial Estate, Faridabad, HR 121004, India",
            "GSTIN: 06AAECV4321R1Z8",
        ],
        columns=["Description", "HSN Code", "Qty", "Additional Rate (Rs)", "Amount (Rs)"],
        rows=[
            ["Forged Steel Flange - 6 inch (price escalation)", "7326", "400", "45.00", "18,000.00"],
        ],
        summary_rows=[
            ["Subtotal", "Rs 18,000.00"],
            ["GST at 18 percent", "Rs 3,240.00"],
            ["Total Debit Amount", "Rs 21,240.00"],
        ],
        notes=[
            "This Debit Note is issued under Section 34(3) of the CGST Act, 2017 "
            "against the original Tax Invoice referenced above.",
        ],
    )
    return path


def gen_us_delivery_note_01():
    """US inbound DELIVERY_NOTE -- Packing Slip variant, completing the
    three-region proof section 7 recommends (India challan + Germany
    Lieferschein already existed; US was the missing recommended cell). No
    prices printed, same as the other two DELIVERY_NOTE fixtures -- a US
    packing slip conventionally lists contents and quantities only.
    """
    path = os.path.join(HERE, "delivery_note", "us_inbound", "US-DN-01_packing_slip_no_prices.pdf")
    _build(
        path=path,
        title="PACKING SLIP",
        header_lines=[
            "Cascade Industrial Supply LLC",
            "4820 Harborview Drive, Seattle, WA 98134, USA",
        ],
        meta_lines=[
            "<b>Packing Slip No:</b> PS-2026-3390 &nbsp;&nbsp; <b>Ship Date:</b> "
            "09/20/2026",
            "<b>Order Reference:</b> PO-US-8841 &nbsp;&nbsp; "
            "<b>Carrier / Tracking No:</b> FedEx Freight 881204471",
        ],
        party_label="Ship To:",
        party_lines=[
            "Northgate Manufacturing Inc.",
            "220 Commerce Park Blvd, Austin, TX 78701, USA",
        ],
        columns=["Item No", "Description", "Qty Shipped", "UOM"],
        rows=[
            ["1", "Industrial Conveyor Belt, Model CB-500", "10", "EA"],
            ["2", "Replacement Roller Assembly", "40", "EA"],
        ],
        summary_rows=None,
        notes=[
            "This Packing Slip lists the contents of this shipment. It is not an "
            "invoice and no payment is due based on this document.",
            "Please inspect contents upon receipt and report any discrepancy within 5 "
            "business days.",
        ],
    )
    return path


if __name__ == "__main__":
    generated = [
        gen_in_delivery_note_01(),
        gen_eu_delivery_note_01(),
        gen_us_delivery_note_01(),
        gen_in_proforma_invoice_01(),
        gen_eu_proforma_invoice_01(),
        gen_us_proforma_invoice_01(),
        gen_in_purchase_order_01(),
        gen_us_purchase_order_01(),
        gen_in_contract_01(),
        gen_eu_contract_01(),
        gen_in_quotation_01(),
        gen_in_grn_01(),
        gen_in_other_bill_of_lading_01(),
        gen_in_other_eway_bill_01(),
        gen_in_credit_note_01(),
        gen_in_debit_note_01(),
    ]
    for p in generated:
        print("wrote " + p)
