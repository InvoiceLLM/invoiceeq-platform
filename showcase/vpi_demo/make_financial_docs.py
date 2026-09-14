"""Generate the financial documents for the Vishwa Precision Industries (VPI) demo tenant.

Every document matches an invoice in Downloads/invoiceeq_test_pdfs_india/india exactly
(vendor, lines, quantities, amounts, dates) — "all clean matches" per the founder's
2026-09-08 choice. The invoice set itself already carries the exceptions the
attention area needs (see README.md next to this file).

    python make_financial_docs.py      -> writes PDFs into ./upload/
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).parent / "upload"
OUT.mkdir(exist_ok=True)

VPI = ("Vishwa Precision Industries Pvt Ltd", "Plot 47, MIDC Bhosari, Pune, MH 411026", "GSTIN: 27AAFCV1234M1Z5")
VENDORS = {
    "RAJ": ("Rajesh Steel Corporation", "Gate 2, Chakan MIDC, Pune 410501", "GSTIN: 27AARSC5555P1Z5"),
    "GBP": ("Ganesh Bearings Pvt Ltd", "Unit 7, Ambad MIDC, Nashik 422010", "GSTIN: 27AAGBP6666P1Z6"),
    "SHR": ("Shree Packaging Industries", "Plot 9, Bhosari Industrial Area, Pune 411026", "GSTIN: 27AASPI3333P1Z3"),
    "NAT": ("National MRO Traders", "14 Shivar Chowk, Pimpri, Pune 411034", "GSTIN: 27AANMT4444P1Z4"),
    "BHA": ("Bharat Hardware & Fasteners", "Gala 4, MIDC Chinchwad, Pune 411019", "GSTIN: 27AABHF2222P1Z2"),
    "OM": ("Om Stationery Mart", "Shop 12, Laxmi Market, Pune 411001", "GSTIN: 27AAAOS1111P1Z1"),
}
# (description, hsn, qty, rate) -- verbatim from the invoices
LINES = {
    "RAJ-2008": [("HR Steel Coil 2mm", "7208", 6, 48500.00), ("Steel Angle Bar 2x2x1/4, 20ft", "7216", 30, 2650.00)],
    "GBP-2011": [("Deep Groove Ball Bearing 6205", "8482", 60, 520.00), ("Tapered Roller Bearing 30205", "8482", 25, 1080.00)],
    "SHR-2005": [("Corrugated Boxes 24x18x18", "4819", 150, 220.00), ("Wooden Pallets 48x40", "4415", 50, 950.00), ("Stretch Wrap Film 20 rolls", "3920", 6, 3800.00)],
    "NAT-2006": [("Industrial Lubricant 20L", "2710", 5, 5600.00), ("Replacement V-Belts", "4010", 12, 1680.00), ("Safety Gloves case of 60", "4015", 8, 2450.00)],
    "BHA-2003": [("Hex Bolts M10x40, box 100", "7318", 25, 1450.00), ("SS Washers box 500", "7318", 15, 1120.00), ("Torque Wrench 1/2in", "8204", 4, 8600.00)],
}

ss = getSampleStyleSheet()
H = ParagraphStyle("h", parent=ss["Title"], fontSize=16, spaceAfter=6)
B = ss["BodyText"]
SM = ParagraphStyle("sm", parent=B, fontSize=8.5, leading=11)


def rs(x):
    return f"Rs. {x:,.2f}"


def party(title, p):
    return Paragraph(f"<b>{title}</b><br/>{p[0]}<br/>{p[1]}<br/>{p[2]}", SM)


def grid(rows, widths, header=True):
    t = Table(rows, colWidths=widths)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (2, 1), (-1, -1), "RIGHT")]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def build(name, story):
    doc = SimpleDocTemplate(str(OUT / name), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    doc.build(story)
    print("wrote", name)


def two_col(left, right):
    t = Table([[left, right]], colWidths=[85 * mm, 85 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


# ---------------------------------------------------------------- purchase orders
def purchase_order(po_no, po_date, vendor_key, inv_no, delivery_by, terms="Net 30"):
    v = VENDORS[vendor_key]
    lines = LINES[inv_no]
    rows = [["Description", "HSN", "Qty", "Rate", "Amount"]]
    sub = 0
    for d, h, q, r in lines:
        a = q * r
        sub += a
        rows.append([d, h, str(q), f"{r:,.2f}", rs(a)])
    cgst = round(sub * 0.09, 2)
    story = [
        Paragraph("PURCHASE ORDER", H),
        two_col(party("Buyer", VPI), party("Supplier", v)),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>PO No:</b> {po_no}&nbsp;&nbsp;&nbsp; <b>PO Date:</b> {po_date}&nbsp;&nbsp;&nbsp; "
                  f"<b>Deliver by:</b> {delivery_by}&nbsp;&nbsp;&nbsp; <b>Payment terms:</b> {terms}", B),
        Paragraph("Ship to: Vishwa Precision Industries Pvt Ltd, Plot 47, MIDC Bhosari, Pune, MH 411026 (Stores, Gate 2)", SM),
        Spacer(1, 3 * mm),
        grid(rows, [78 * mm, 18 * mm, 16 * mm, 26 * mm, 32 * mm]),
        Spacer(1, 3 * mm),
        grid([["Subtotal", rs(sub)], ["CGST 9%", rs(cgst)], ["SGST 9%", rs(cgst)], ["PO Value", rs(sub + 2 * cgst)]],
             [138 * mm, 32 * mm], header=False),
        Spacer(1, 5 * mm),
        Paragraph("Please quote this PO number on your tax invoice and delivery challan. Goods are subject to "
                  "inspection at receipt. Prices are firm for the delivery period.", SM),
        Spacer(1, 8 * mm),
        Paragraph("Authorised by: Purchase Manager, Vishwa Precision Industries Pvt Ltd", SM),
    ]
    build(f"PO_{po_no}_{vendor_key}.pdf", story)


# ---------------------------------------------------------------- delivery challans
def delivery_challan(dc_no, dc_date, vendor_key, inv_no, po_no, vehicle):
    v = VENDORS[vendor_key]
    lines = LINES[inv_no]
    rows = [["Description", "HSN", "Qty ordered", "Qty delivered", "Unit"]]
    for d, h, q, _ in lines:
        rows.append([d, h, str(q), str(q), "Nos"])
    story = [
        Paragraph("DELIVERY CHALLAN", H),
        two_col(party("Consignor", v), party("Consignee", VPI)),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Challan No:</b> {dc_no}&nbsp;&nbsp;&nbsp; <b>Date:</b> {dc_date}&nbsp;&nbsp;&nbsp; "
                  f"<b>Against PO:</b> {po_no}&nbsp;&nbsp;&nbsp; <b>Vehicle:</b> {vehicle}", B),
        Spacer(1, 3 * mm),
        grid(rows, [78 * mm, 18 * mm, 24 * mm, 26 * mm, 24 * mm]),
        Spacer(1, 5 * mm),
        Paragraph("Goods delivered in good condition. Tax invoice to follow / as per invoice "
                  f"<b>{inv_no}</b>. Not for sale — delivery challan only.", SM),
        Spacer(1, 10 * mm),
        two_col(Paragraph("Received by (VPI Stores): ____________________<br/>Name / Date / Stamp", SM),
                Paragraph("For " + v[0] + ": ____________________<br/>Authorised signatory", SM)),
    ]
    build(f"DC_{dc_no}_{vendor_key}.pdf", story)


# ---------------------------------------------------------------- payment advices
def payment_advice(pa_no, pa_date, vendor_key, inv_no, inv_date, amount, utr):
    v = VENDORS[vendor_key]
    story = [
        Paragraph("PAYMENT ADVICE", H),
        two_col(party("From", VPI), party("To", v)),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Advice No:</b> {pa_no}&nbsp;&nbsp;&nbsp; <b>Date:</b> {pa_date}&nbsp;&nbsp;&nbsp; "
                  f"<b>Mode:</b> NEFT&nbsp;&nbsp;&nbsp; <b>UTR:</b> {utr}", B),
        Spacer(1, 3 * mm),
        grid([["Invoice No", "Invoice Date", "Invoice Amount", "Deduction", "Amount Paid"],
              [inv_no, inv_date, rs(amount), rs(0), rs(amount)]],
             [34 * mm, 30 * mm, 36 * mm, 30 * mm, 40 * mm]),
        Spacer(1, 3 * mm),
        grid([["Total paid", rs(amount)]], [138 * mm, 32 * mm], header=False),
        Spacer(1, 5 * mm),
        Paragraph("Paid from HDFC Bank current account ending 4471, Bhosari branch. Please acknowledge receipt "
                  "and update your ledger. Any short-payment query to accounts@vishwaprecision.in.", SM),
        Spacer(1, 8 * mm),
        Paragraph("Accounts Payable, Vishwa Precision Industries Pvt Ltd", SM),
    ]
    build(f"PA_{pa_no}_{vendor_key}.pdf", story)


# ---------------------------------------------------------------- bank statement
def bank_statement():
    opening = 1_250_000.00
    txns = [  # (date, description, debit, credit)
        ("01-Aug-2026", "OPENING BALANCE", None, None),
        ("03-Aug-2026", "NEFT DR HDFC0000123 GST PAYMENT JUL-26 CIN 26081234567", 184_320.00, None),
        ("05-Aug-2026", "NEFT DR OM STATIONERY MART INV OM -2000 UTR HDFCN26080512345", 41_654.00, None),
        ("06-Aug-2026", "NEFT DR BHARAT HARDWARE & FASTENERS INV BHA-2002 UTR HDFCN26080612346", 103_191.00, None),
        ("07-Aug-2026", "NEFT DR SHREE PACKAGING INDUSTRIES INV SHR-2004 UTR HDFCN26080712347", 121_894.00, None),
        ("09-Aug-2026", "NEFT CR KAVERI AUTO COMPONENTS PVT LTD VPI-OUT-2012", None, 483_210.00),
        ("11-Aug-2026", "NEFT CR SUNRISE ENGINEERING WORKS VPI-OUT-2015", None, 514_775.00),
        ("12-Aug-2026", "ACH DR MSEDCL ELECTRICITY BILL AUG-26", 96_410.00, None),
        ("14-Aug-2026", "NEFT DR SALARY AUG-26 BATCH 1 (42 EMPLOYEES)", 1_486_000.00, None),
        ("20-Aug-2026", "IMPS DR TECHSOL SERVICES ANNUAL AMC 2026-27", 58_000.00, None),
        ("25-Aug-2026", "NEFT CR DECCAN MACHINERY LTD ADVANCE AGAINST VPI-OUT-2018", None, 200_000.00),
        ("31-Aug-2026", "BANK CHARGES NEFT/RTGS AUG-26 INCL GST", 1_180.00, None),
    ]
    rows = [["Date", "Narration", "Withdrawal (Dr)", "Deposit (Cr)", "Balance"]]
    bal = opening
    for d, n, dr, cr in txns:
        if dr:
            bal -= dr
        if cr:
            bal += cr
        rows.append([d, Paragraph(n, SM), f"{dr:,.2f}" if dr else "", f"{cr:,.2f}" if cr else "", f"{bal:,.2f}"])
    story = [
        Paragraph("HDFC BANK LIMITED — STATEMENT OF ACCOUNT", H),
        Paragraph("Branch: Bhosari MIDC, Pune 411026 &nbsp;&nbsp; IFSC: HDFC0000471 &nbsp;&nbsp; Account type: Current", SM),
        Paragraph("Account holder: <b>Vishwa Precision Industries Pvt Ltd</b>, Plot 47, MIDC Bhosari, Pune, MH 411026", SM),
        Paragraph("Account No: XXXXXXXX4471 &nbsp;&nbsp; Statement period: 01-Aug-2026 to 31-Aug-2026 &nbsp;&nbsp; Currency: INR", SM),
        Spacer(1, 4 * mm),
        grid(rows, [22 * mm, 82 * mm, 24 * mm, 22 * mm, 24 * mm]),
        Spacer(1, 4 * mm),
        grid([["Opening balance", rs(opening)],
              ["Total withdrawals", rs(sum(t[2] for t in txns if t[2]))],
              ["Total deposits", rs(sum(t[3] for t in txns if t[3]))],
              ["Closing balance", rs(bal)]], [138 * mm, 32 * mm], header=False),
        Spacer(1, 5 * mm),
        Paragraph("This is a computer-generated statement and does not require a signature.", SM),
    ]
    build("BankStatement_HDFC_4471_Aug2026.pdf", story)


if __name__ == "__main__":
    # POs raised before the matching invoices, referenced on the challans
    purchase_order("PO-VPI-1041", "05-Aug-2026", "RAJ", "RAJ-2008", "20-Aug-2026")
    purchase_order("PO-VPI-1042", "08-Aug-2026", "GBP", "GBP-2011", "20-Aug-2026", terms="Net 30 (new vendor)")
    purchase_order("PO-VPI-1043", "06-Aug-2026", "SHR", "SHR-2005", "18-Aug-2026")
    # Challans delivered on the invoice dates, quantities exactly as invoiced
    delivery_challan("DC-RSC-0812", "20-Aug-2026", "RAJ", "RAJ-2008", "PO-VPI-1041", "MH 14 GT 4471")
    delivery_challan("DC-NMT-2291", "19-Aug-2026", "NAT", "NAT-2006", "PO-VPI-1039", "MH 12 AB 9032")
    delivery_challan("DC-BHF-0455", "17-Aug-2026", "BHA", "BHA-2003", "PO-VPI-1040", "MH 14 CD 1187")
    # Payment advices for the three July invoices, matching the bank debits
    payment_advice("PA-VPI-0071", "05-Aug-2026", "OM", "OM -2000", "09-Jul-2026", 41_654.00, "HDFCN26080512345")
    payment_advice("PA-VPI-0072", "06-Aug-2026", "BHA", "BHA-2002", "09-Jul-2026", 103_191.00, "HDFCN26080612346")
    payment_advice("PA-VPI-0073", "07-Aug-2026", "SHR", "SHR-2004", "09-Jul-2026", 121_894.00, "HDFCN26080712347")
    bank_statement()
