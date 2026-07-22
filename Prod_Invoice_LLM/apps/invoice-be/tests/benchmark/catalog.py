"""Vendor/customer/product pools per region, used by generator.py to build
varied, realistic-looking invoices without repeating the same content every day.
"""

US_VENDORS = [
    ("Summit Office Supply", "410 Commerce Ave, Denver, CO 80202"),
    ("BrightPath Consulting LLC", "88 Market St, San Francisco, CA 94103"),
    ("Ironclad Logistics Inc.", "1200 Freight Way, Memphis, TN 38103"),
    ("Northwind Manufacturing", "77 Industrial Pkwy, Columbus, OH 43215"),
    ("Vantage IT Solutions", "500 Tech Blvd, Austin, TX 78701"),
    ("Cascade Facilities Group", "220 Rainier Ave, Seattle, WA 98104"),
    ("Meridian Legal Services", "150 Court St, Boston, MA 02108"),
    ("Palmetto Print & Design", "33 Palm Row, Charleston, SC 29401"),
]

US_CUSTOMERS = [
    ("Harbor Point Retail Group", "900 Bayview Dr, San Diego, CA 92101"),
    ("Greenline Foods Corp.", "45 Orchard Rd, Portland, OR 97204"),
    ("Redwood Financial Partners", "12 Wall St, New York, NY 10005"),
    ("Prairie Health Systems", "300 Wellness Ave, Kansas City, MO 64105"),
    ("Sunbelt Realty Holdings", "60 Palm Terrace, Phoenix, AZ 85004"),
]

US_PRODUCTS = [
    ("Ergonomic Office Chair", 180, 420),
    ("24-Port Network Switch", 300, 900),
    ("Managed IT Support (monthly)", 800, 2500),
    ("Freight Delivery Service", 200, 1500),
    ("Custom Signage - 4x8ft", 250, 700),
    ("Legal Consultation (hourly)", 150, 450),
    ("Warehouse Pallet Racking", 90, 260),
    ("Business Card Printing (1000 units)", 60, 150),
    ("Cloud Backup Subscription (annual)", 500, 1800),
    ("Commercial HVAC Maintenance", 300, 950),
]

INDIA_VENDORS = [
    ("Shree Precision Components Pvt. Ltd.", "Plot 14, MIDC Industrial Area, Pune, Maharashtra 411019", "27AABCS1234F1Z9"),
    ("Ganges Textile Mills", "Sector 63, Noida, Uttar Pradesh 201301", "09AABCG5678L1ZR"),
    ("Bharat Electricals & Controls", "Peenya Industrial Estate, Bengaluru, Karnataka 560058", "29AABCB4321M1Z2"),
    ("Konkan Agro Exports Pvt. Ltd.", "MIDC Taloja, Navi Mumbai, Maharashtra 410208", "27AABCK8765N1Z4"),
    ("Nilgiri Pharma Solutions", "SIPCOT Industrial Complex, Chennai, Tamil Nadu 600058", "33AABCN2468P1Z1"),
]

INDIA_CUSTOMERS = [
    ("Kestrel Manufacturing Co.", "Hoskote Industrial Estate, Bengaluru Rural, Karnataka 562114", "29AAGCK5678L1ZR"),
    ("Vindhya Retail Chain Ltd.", "Sector 18, Gurugram, Haryana 122015", "06AAGCV1357Q1ZA"),
    ("Coromandel Agro Traders", "Anna Salai, Chennai, Tamil Nadu 600002", "33AAGCC9753R1Z6"),
    ("Himalayan Cold Chain Pvt. Ltd.", "Baddi Industrial Area, Solan, Himachal Pradesh 173205", "02AAGCH8642S1Z3"),
]

# (description, hsn_sac, gst_rate_percent, unit_price_low, unit_price_high)
INDIA_PRODUCTS = [
    ("Precision Ball Bearing Assembly", "8483.10", 18, 400, 1200),
    ("Hex Socket Head Cap Screw (Pack of 100)", "7318.15", 18, 900, 1600),
    ("Single Phase Induction Motor 1HP", "8501.10", 18, 5000, 9000),
    ("Industrial PVC Conveyor Belt (per metre)", "3926.90", 12, 250, 400),
    ("Modular Contactor Relay 3-Pole 40A", "8536.50", 18, 1500, 2400),
    ("Cotton Yarn (per kg)", "5205.11", 5, 180, 320),
    ("Printed Cotton Fabric (per metre)", "5208.52", 12, 90, 180),
    ("Fresh Turmeric (per kg)", "0910.30", 5, 60, 110),
    ("Basmati Rice (per 25kg bag)", "1006.30", 5, 1200, 2200),
    ("Paracetamol Tablets (per 1000 strip)", "3004.90", 12, 800, 1500),
    ("Surgical Gloves (per box of 100)", "4015.19", 12, 350, 650),
    ("Freight & Handling Charges (Non-GST)", "9999.00", 0, 2000, 6000),
]

UK_VENDORS = [
    ("Thames Valley Office Solutions Ltd.", "14 Kingsway, London WC2B 6AN", "GB123456789"),
    ("Northgate Manufacturing plc", "Unit 8 Aldermoor Rd, Birmingham B12 0LU", "GB987654321"),
    ("Caledonian Cloud Services Ltd.", "22 St Vincent St, Glasgow G2 5TZ", "GB456789123"),
    ("Severn Logistics Group", "5 Dockside Rd, Bristol BS1 6UN", "GB321654987"),
]

UK_CUSTOMERS = [
    ("Thistledown Retail Ltd.", "88 Deansgate, Manchester M3 2ER", "GB654321789"),
    ("Ashford Property Holdings", "17 Bank St, Leeds LS1 5AT", "GB789123456"),
    ("Wyvern Healthcare Trust", "3 Priory Rd, Cardiff CF10 3AT", "GB159753486"),
]

# (description, vat_rate_percent, unit_price_low, unit_price_high) - vat_rate: 20 standard, 5 reduced, 0 zero-rated
UK_PRODUCTS = [
    ("Cloud Hosting - Standard Tier (monthly)", 20, 60, 150),
    ("Office Furniture - Desk & Chair Set", 20, 200, 500),
    ("Technical Support Retainer (monthly)", 20, 400, 900),
    ("Domestic Energy Surcharge Passthrough", 5, 30, 90),
    ("Children's Educational Workbooks (set)", 0, 15, 40),
    ("Printed Reference Books (set of 10)", 0, 50, 120),
    ("On-site Consulting (Reverse Charge, per day)", 0, 400, 900),
    ("Network Switch 24-Port", 20, 250, 600),
    ("Managed Print Services (monthly)", 20, 150, 400),
]

REGIONS = {
    "US": {"vendors": US_VENDORS, "customers": US_CUSTOMERS, "products": US_PRODUCTS, "currency_symbol": "$"},
    "INDIA": {"vendors": INDIA_VENDORS, "customers": INDIA_CUSTOMERS, "products": INDIA_PRODUCTS, "currency_symbol": "₹"},
    "UK": {"vendors": UK_VENDORS, "customers": UK_CUSTOMERS, "products": UK_PRODUCTS, "currency_symbol": "£"},
}
