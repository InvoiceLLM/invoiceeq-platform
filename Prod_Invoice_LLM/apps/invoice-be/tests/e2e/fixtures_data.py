"""Fixture invoice definitions for the e2e regional test suite.

Each fixture is (build_kwargs for pdf_builder.build_invoice_pdf, expectation dict).
Expectations use tolerant assertions (see test_e2e_regional_invoices.py) because
these go through a real LLM extraction call, not a deterministic parser.
"""

PRINTMAX_FALSE_POSITIVE = (
    dict(
        vendor_lines=["<b>PrintMax Solutions</b>", "80 Print Blvd, Tampa, FL 33601"],
        meta_lines=["Invoice Number: INV-2026-0002", "Invoice Date: 12 Jan 2026", "Due Date: 27 Jan 2026"],
        bill_to_lines=["ADM Softtech Pvt. Ltd.", "Plot 5, Tech Zone, Kolkata 700001, India"],
        columns=["#", "Description", "Qty", "Unit Price (USD)", "Amount (USD)"],
        rows=[["1", "Stationery Bundle", "10", "$248.72", "$2,487.20"]],
        summary_rows=[
            ["Subtotal:", "$2,487.20"],
            ["Tax (5%):", "$124.36"],
            ["TOTAL DUE:", "$2,611.56"],
        ],
    ),
    {
        "name": "printmax_false_positive",
        "description": "Regression case for the invoice-level-tax-copied-to-line-item bug. Single line, tax shown once at invoice level only.",
        "expected_status": "COMPLETED",
        "expected_grand_total": 2611.56,
        "expected_tax_amount": 124.36,
        "must_not_contain_alert_type": "line_item_calculation_mismatch",
    },
)

FURNITUREPRO_CLEAN_DISCOUNT_TAX = (
    dict(
        vendor_lines=["<b>FurniturePro Corp.</b>", "700 Workspace Drive, Nashville, TN 37201"],
        meta_lines=["Invoice Number: INV-2025-0027", "Invoice Date: 17 Dec 2025", "Due Date: 15 Feb 2026"],
        bill_to_lines=["ADM Softtech Pvt. Ltd.", "Plot 5, Tech Zone, Kolkata 700001, India"],
        columns=["#", "Description", "Qty", "Unit Price (USD)", "Amount (USD)"],
        rows=[
            ["1", "Office Furniture Set", "20", "$3,809.86", "$76,197.20"],
            ["2", "Whiteboard 6x4ft", "18", "$307.18", "$5,529.24"],
            ["3", "Printer Ink Cartridges (set)", "11", "$162.08", "$1,782.88"],
            ["4", "A4 Copy Paper (per ream)", "13", "$8.00", "$104.00"],
            ["5", "Electricity Bill", "15", "$2,231.67", "$33,475.05"],
            ["6", "Water Dispenser Rental", "19", "$291.50", "$5,538.50"],
        ],
        summary_rows=[
            ["Subtotal:", "$122,626.87"],
            ["Discount (10%):", "-$12,262.69"],
            ["After Discount:", "$110,364.18"],
            ["Tax (12%):", "$13,243.70"],
            ["TOTAL DUE:", "$123,607.88"],
        ],
    ),
    {
        "name": "furniturepro_clean_discount_tax",
        "description": "Baseline happy path: multi-line, discount + single invoice-level tax, internally consistent. Should sail through clean.",
        "expected_status": "COMPLETED",
        "expected_grand_total": 123607.88,
        "expected_tax_amount": 13243.70,
        "must_not_contain_alert_type": "line_item_calculation_mismatch",
    },
)

SYNTHEX_DELIBERATE_MISMATCH = (
    dict(
        vendor_lines=["<b>Synthex Analytics</b>", "200 Data Street, New York, NY 10001"],
        meta_lines=["Invoice Number: INV-2025-0040", "Invoice Date: 25 Dec 2025", "Due Date: 23 Feb 2026"],
        bill_to_lines=["NovaTech Solutions", "800 Innovation Blvd, Toronto, ON M5H 2N2, Canada"],
        columns=["#", "Description", "Qty", "Unit Price (USD)", "Amount (USD)"],
        rows=[
            ["1", "Enterprise License - Annual", "3", "$1,097.44", "$3,292.32"],
            ["2", "API Access - Pro Tier", "19", "$610.22", "$11,594.18"],
            ["3", "Cloud Storage (per TB/month)", "18", "$361.95", "$6,515.10"],
            ["4", "Analytics Dashboard Add-on", "14", "$507.58", "$7,106.12"],
        ],
        summary_rows=[
            ["Subtotal:", "$28,507.72"],
            ["Tax (5%):", "$1,425.39"],
            ["TOTAL DUE:", "$30,366.97"],
        ],
        notes=["Note: Please verify total amount with accounts department before payment."],
    ),
    {
        "name": "synthex_deliberate_mismatch",
        "description": "Subtotal + tax (28507.72 + 1425.39 = 29933.11) does not match the printed TOTAL DUE (30366.97) by design. Must still be caught.",
        "expected_status": "AUDIT_REQUIRED",
        "must_contain_alert_type": "tax_mismatch",
    },
)

VERTEX_INDIA_GST_COMPLEX = (
    dict(
        vendor_lines=[
            "<b>VERTEX INDUSTRIAL SUPPLY PVT. LTD.</b>",
            "Plot 42, Peenya Industrial Area, Phase II, Bengaluru, Karnataka 560058, India",
            "GSTIN: 29AABCV1234F1Z5 | PAN: AABCV1234F",
        ],
        meta_lines=["Invoice No: VIS/26-27/0847", "Invoice Date: 03-Jul-2026", "Due Date: 02-Aug-2026", "Place of Supply: Karnataka (29)"],
        bill_to_lines=["Kestrel Manufacturing Co.", "Survey No. 118/2, Hoskote Industrial Estate, Bengaluru Rural, Karnataka 562114", "GSTIN: 29AAGCK5678L1ZR"],
        columns=["#", "HSN/SAC", "Description", "Qty", "Rate (INR)", "Discount", "Taxable Value", "GST %", "Amount (INR)"],
        rows=[
            ["1", "8483.10", "Precision Ball Bearing Assembly - PB-2240", "120", "842.50", "5%", "96,045.00", "18%", "1,13,333.10"],
            ["2", "7318.15", "Hex Socket Head Cap Screw M10x40mm - Pack of 100", "35", "1,275.00", "-", "44,625.00", "18%", "52,657.50"],
            ["3", "8501.10", "Single Phase Induction Motor, 1HP, 1440 RPM", "8", "6,940.00", "10%", "49,968.00", "18%", "58,962.24"],
            ["4", "3926.90", "Industrial PVC Conveyor Belt, 600mm width", "210", "318.75", "-", "66,937.50", "12%", "74,970.00"],
            ["5", "8536.50", "Modular Contactor Relay 3-Pole, 40A", "46", "1,890.00", "7.5%", "80,406.15", "18%", "94,879.26"],
            ["6", "9999.00", "Freight & Handling Charges (Non-GST)", "1", "4,500.00", "-", "4,500.00", "0%", "4,500.00"],
        ],
        summary_rows=[
            ["Subtotal (Taxable Value):", "4,16,249.91"],
            ["Total Discount Applied:", "(-) 8,822.35"],
            ["Total CGST:", "35,049.37"],
            ["Total SGST:", "35,049.37"],
            ["Round Off:", "0.35"],
            ["GRAND TOTAL (INR):", "4,86,349.00"],
        ],
    ),
    {
        "name": "vertex_india_gst_complex",
        "description": (
            "Real per-line GST that genuinely varies (18/18/18/12/18/0%) — the C guard must NOT suppress tax "
            "checking here. Known-unresolved issues (documented, not yet fixed): line 5 has a ~13.35 rounding "
            "gap against a strict 0.01 tolerance; the invoice-level subtotal is already post-discount (GST "
            "convention) which verify_totals_math doesn't yet account for; CGST+SGST split isn't reconciled "
            "into a single tax_amount; there's no Round Off term. Expect AUDIT_REQUIRED — this fixture exists "
            "to prove those gaps stay visible, not to pass clean yet."
        ),
        "expected_status": "AUDIT_REQUIRED",
        "loose_check_only": True,
    },
)

EU_VAT_REVERSE_CHARGE = (
    dict(
        vendor_lines=["<b>NordCloud B.V.</b>", "Keizersgracht 123, 1015 CJ Amsterdam, Netherlands", "VAT: NL123456789B01"],
        meta_lines=["Invoice Number: NC-2026-0451", "Invoice Date: 15 Jun 2026", "Due Date: 15 Jul 2026"],
        bill_to_lines=["Bergmann Industrieteile GmbH", "Hauptstrasse 45, 10115 Berlin, Germany", "VAT: DE987654321"],
        columns=["#", "Description", "Qty", "Unit Price (EUR)", "VAT %", "Amount (EUR)"],
        rows=[
            ["1", "Cloud Hosting - Standard Tier", "12", "89.00", "21%", "1,068.00"],
            ["2", "Technical Support Retainer", "6", "150.00", "21%", "900.00"],
            ["3", "On-site Consulting (Reverse Charge)", "3", "500.00", "0%", "1,500.00"],
        ],
        summary_rows=[
            ["Subtotal:", "3,468.00"],
            ["VAT (21% on EUR 1,968.00):", "413.28"],
            ["VAT (Reverse Charge, EUR 1,500.00):", "0.00"],
            ["TOTAL DUE:", "3,881.28"],
        ],
        notes=[
            "Line 3: Reverse charge - VAT to be accounted for by the recipient (Art. 196 EU VAT Directive).",
            "Bergmann Industrieteile GmbH VAT ID: DE987654321",
        ],
    ),
    {
        "name": "eu_vat_reverse_charge",
        "description": (
            "EU-style VAT invoice with two genuinely different per-line rates (21% standard, 0% reverse-charge) "
            "plus a legal reverse-charge note. Tests that the C guard doesn't suppress when rates genuinely "
            "differ, and that reverse-charge language doesn't get misread as a discount or exemption error."
        ),
        "expected_status": "COMPLETED",
        "expected_grand_total": 3881.28,
        "expected_tax_amount": 413.28,
        "must_not_contain_alert_type": "line_item_calculation_mismatch",
    },
)

ALL_FIXTURES = [
    PRINTMAX_FALSE_POSITIVE,
    FURNITUREPRO_CLEAN_DISCOUNT_TAX,
    SYNTHEX_DELIBERATE_MISMATCH,
    VERTEX_INDIA_GST_COMPLEX,
    EU_VAT_REVERSE_CHARGE,
]
