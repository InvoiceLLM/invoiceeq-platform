"""Image-format invoices for the VPI demo (the app accepts pdf/png/jpg/tiff/webp/bmp).

Six NEW invoice numbers (no duplicates of the PDF set), one file per format, GST 9%+9%.
    python make_image_invoices.py   -> ./invoices_other_formats/
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "invoices_other_formats"
OUT.mkdir(exist_ok=True)

VPI = ("Vishwa Precision Industries Pvt Ltd", "Plot 47, MIDC Bhosari, Pune, MH 411026", "GSTIN: 27AAFCV1234M1Z5")
PARTIES = {
    "OM": ("Om Stationery Mart", "Shop 12, Laxmi Market, Pune 411001", "GSTIN: 27AAAOS1111P1Z1"),
    "GBP": ("Ganesh Bearings Pvt Ltd", "Unit 7, Ambad MIDC, Nashik 422010", "GSTIN: 27AAGBP6666P1Z6"),
    "SHR": ("Shree Packaging Industries", "Plot 9, Bhosari Industrial Area, Pune 411026", "GSTIN: 27AASPI3333P1Z3"),
    "KAV": ("Kaveri Auto Components Pvt Ltd", "Plot 22, Hosur Rd, Bengaluru 560068", "GSTIN: 29AAKAC7777K1Z7"),
    "SUN": ("Sunrise Engineering Works", "55 GIDC Estate, Ahmedabad 382445", "GSTIN: 24AASEW8888S1Z8"),
    "DEC": ("Deccan Machinery Ltd", "Plot 8, Balanagar Industrial Area, Hyderabad 500037", "GSTIN: 36AADML9999D1Z9"),
}

# (file, fmt, direction, doc_no, date, due, party, lines[(desc, hsn, qty, rate)])
INVOICES = [
    ("inbound_Om_Stationery_Mart_OM-2002.png", "PNG", "in", "OM -2002", "26-Aug-2026", "25-Sep-2026", "OM",
     [("A4 Copier Paper, box of 5 reams", "4802", 20, 950.00), ("Whiteboard Markers box of 12", "9608", 15, 360.00)]),
    ("inbound_Ganesh_Bearings_GBP-2012_scanned.jpg", "JPEG", "in", "GBP-2012", "28-Aug-2026", "27-Sep-2026", "GBP",
     [("Deep Groove Ball Bearing 6205", "8482", 100, 520.00), ("Bearing Housing P205", "8483", 40, 890.00)]),
    ("inbound_Shree_Packaging_SHR-2006.tiff", "TIFF", "in", "SHR-2006", "29-Aug-2026", "28-Sep-2026", "SHR",
     [("Corrugated Boxes 24x18x18", "4819", 300, 220.00), ("Stretch Wrap Film 20 rolls", "3920", 10, 3800.00)]),
    ("outbound_Kaveri_Auto_VPI-OUT-2021.png", "PNG", "out", "VPI-OUT-2021", "27-Aug-2026", "26-Sep-2026", "KAV",
     [("Custom Stamped Bracket A-14", "8708", 400, 320.00), ("Precision Shaft Coupling B-9", "8483", 60, 1450.00)]),
    ("outbound_Sunrise_Engineering_VPI-OUT-2022.webp", "WEBP", "out", "VPI-OUT-2022", "28-Aug-2026", "27-Sep-2026", "SUN",
     [("Machined Housing Unit H-3", "8483", 30, 4850.00), ("Gearbox Mounting Plate", "8483", 60, 2150.00)]),
    ("outbound_Deccan_Machinery_VPI-OUT-2023.bmp", "BMP", "out", "VPI-OUT-2023", "30-Aug-2026", "29-Sep-2026", "DEC",
     [("Conveyor Roller Assembly", "8428", 50, 2600.00), ("Idler Roller Bracket", "8428", 80, 740.00)]),
]


def font(size, bold=False):
    for name in (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def rs(x):
    return f"Rs. {x:,.2f}"


def render(direction, doc_no, date, due, party_key, lines):
    W, H = 1240, 1754  # A4 @ 150 dpi
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_t, f_h, f_b, f_s = font(40, True), font(26, True), font(24), font(20)
    seller, buyer = (VPI, PARTIES[party_key]) if direction == "out" else (PARTIES[party_key], VPI)

    d.text((80, 70), "TAX INVOICE", font=f_t, fill="black")
    y = 140
    for i, line in enumerate(seller):
        d.text((80, y + i * 30), line, font=f_h if i == 0 else f_b, fill="black")
    d.text((760, 140), f"Doc #: {doc_no}", font=f_h, fill="black")
    d.text((760, 180), f"Date: {date}", font=f_b, fill="black")
    d.text((760, 215), f"Due: {due}", font=f_b, fill="black")
    d.text((80, 290), "Bill To:", font=f_h, fill="black")
    for i, line in enumerate(buyer):
        d.text((80, 325 + i * 30), line, font=f_b, fill="black")

    y = 460
    cols = [80, 640, 760, 860, 1010]
    for x, h in zip(cols, ["Description", "HSN", "Qty", "Rate", "Amount"]):
        d.text((x, y), h, font=f_h, fill="black")
    d.line((80, y + 38, 1160, y + 38), fill="black", width=2)
    y += 55
    sub = 0
    for desc, hsn, qty, rate in lines:
        amt = qty * rate
        sub += amt
        for x, v in zip(cols, [desc, hsn, str(qty), f"{rate:,.2f}", rs(amt)]):
            d.text((x, y), v, font=f_b, fill="black")
        y += 42
    d.line((80, y + 10, 1160, y + 10), fill="black", width=1)
    gst = round(sub * 0.09, 2)
    y += 40
    for label, val in [("Subtotal:", rs(sub)), ("CGST 9%:", rs(gst)), ("SGST 9%:", rs(gst)), ("TOTAL:", rs(sub + 2 * gst))]:
        d.text((760, y), label, font=f_h if label == "TOTAL:" else f_b, fill="black")
        d.text((1010, y), val, font=f_h if label == "TOTAL:" else f_b, fill="black")
        y += 40
    remit = "accounts@vishwaprecision.in" if direction == "out" else "accounts payable"
    d.text((80, y + 40), f"Payment due within terms. Please remit to {remit}.", font=f_s, fill="black")
    d.text((80, H - 80), "E. & O.E. This is a system generated invoice.", font=f_s, fill="gray")
    return img, sub + 2 * gst


def scanned_look(img):
    """Slight rotation, blur and speckle so OCR sees a photocopy rather than vector text."""
    random.seed(7)
    img = img.rotate(0.8, resample=Image.BICUBIC, expand=False, fillcolor="white")
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(4000):
        x, y = random.randrange(img.width), random.randrange(img.height)
        g = random.randrange(150, 235)
        px[x, y] = (g, g, g)
    return img


if __name__ == "__main__":
    print("| File | Doc | Party | Date | Due | Total |")
    for fname, fmt, direction, doc_no, date, due, party, lines in INVOICES:
        img, total = render(direction, doc_no, date, due, party, lines)
        if "scanned" in fname:
            img = scanned_look(img)
        kwargs = {"quality": 82} if fmt == "JPEG" else {}
        img.save(OUT / fname, fmt, **kwargs)
        print(f"| {fname} | {doc_no} | {PARTIES[party][0]} | {date} | {due} | {total:,.2f} |")
