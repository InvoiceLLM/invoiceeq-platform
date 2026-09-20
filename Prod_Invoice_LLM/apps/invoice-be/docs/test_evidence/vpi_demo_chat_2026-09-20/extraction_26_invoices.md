# What extraction did — 26 invoices, VPI tenant, 2026-09-20

Read from Postgres only (`invoice` table, `127.0.0.1:5433/invoice_db`, tenant
`00000000-0000-0000-0000-000000000000`), no re-extraction, no invoices
uploaded or modified. Ground truth is `showcase/vpi_demo/README.md` §3.
Query: `select invoice_number, vendor_name, customer_name, flow_direction,
invoice_date, due_date, grand_total, status, sa_alerts, field_confidence,
items, duplicate_of_invoice_id from invoice where tenant_id=... order by
flow_direction desc, invoice_date, invoice_number`.

Field-confidence lows = any key with value < 0.4. Items count = `len(items)`.

## Inbound (14)

| Invoice | Vendor | Date | Due | Extracted total | README total | Status | sa_alerts (verbatim) | Low field_confidence | Items | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| BHA-2002 | Bharat Hardware & Fasteners | 09-Jul | 08-Aug | 103,191.00 | 103,191.00 | PAID | none | none | 3 | MATCH |
| BHA-2003 | Bharat Hardware & Fasteners | 17-Aug | 15-Sep | 103,191.00 | 103,191.00 | COMPLETED | none | none | 3 | MATCH |
| GBP-2011 | Ganesh Bearings Pvt Ltd | 19-Aug | 18-Sep | 68,676.00 | 68,676.00 | COMPLETED | none | none | 2 | MATCH |
| NAT-2006 | National MRO Traders | 19-Aug | 15-Sep | 79,956.80 | 79,956.80 | COMPLETED | none | none | 3 | MATCH |
| NAT-2007 | National MRO Traders | 19-Aug | 15-Sep | 79,956.80 | 79,956.80 (duplicate) | AUDIT_REQUIRED | `possible_duplicate`: "Possible duplicate: National MRO Traders invoice NAT-2006 (ID: 86f1559a-...) has the same date and total (79,956.80) but a different number (NAT-2007). Check whether this is a re-issue." | none | 3 | MATCH (total + expected alert both present) |
| OM -2000 | Om Stationery Mart | 09-Jul | 08-Aug | 41,654.00 | 41,654.00 | PAID | none | none | 3 | MATCH |
| OM -2001 | Om Stationery Mart | 16-Aug | 15-Sep | 41,654.00 | 41,654.00 | COMPLETED | none | none | 3 | MATCH |
| RAJ-2008 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 437,190.00 | 437,190.00 | COMPLETED | none | none | 2 | MATCH |
| RAJ-2009 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 437,190.00 | 437,190.00 (duplicate) | AUDIT_REQUIRED | `possible_duplicate`: "Possible duplicate: Rajesh Steel Corporation invoice RAJ-2008 (ID: d5869da2-...) has the same date and total (437,190.00) but a different number (RAJ-2009). Check whether this is a re-issue." | none | 2 | MATCH (total + expected alert both present) |
| SHR-2004 | Shree Packaging Industries | 09-Jul | 08-Aug | 121,894.00 | 121,894.00 | PAID | none | none | 3 | MATCH |
| SHR-2005 | Shree Packaging Industries | 18-Aug | 15-Sep | 121,894.00 | 121,894.00 | COMPLETED | none | none | 3 | MATCH |
| OM -2002 | Om Stationery Mart | 26-Aug | 25-Sep | 28,792.00 | 28,792.00 | COMPLETED | none | `PaymentTerm`: 0.332 | 2 | MATCH |
| GBP-2012 | Ganesh Bearings Pvt Ltd | 28-Aug | 27-Sep | 103,368.00 | 103,368.00 | COMPLETED | none | none | 2 | MATCH |
| SHR-2006 | Shree Packaging Industries | 29-Aug | 28-Sep | 122,720.00 | 122,720.00 | COMPLETED | none | none | 2 | MATCH |

Inbound sum (as stored): 1,891,327.60 — matches README §6 Q1's "1,891,327.60 across 14 invoices as uploaded". No inbound row carries a line-math alert, per README §3 ("No inbound invoice has a math error"). **MATCH.**

## Outbound (12)

| Invoice | Customer | Date | Due | Extracted total | README total | Status | sa_alerts (verbatim) | Low field_confidence | Items | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| VPI-OUT-2012 | Kaveri Auto Components | 14-Jul | 10-Aug | 483,210.00 | 483,210.00 | PAID | none | none | 2 | MATCH |
| VPI-OUT-2013 | Kaveri Auto Components | 18-Aug | 17-Sep | 483,210.00 | 483,210.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2014 | Kaveri Auto Components | 19-Aug | 17-Sep | 483,850.00 | 483,850.00 (printed, math error) | NEEDS_REVIEW | `tax_mismatch`: "Subtotal (409500.00) + Tax (73710.00) does not match Grand Total (483850.00)" | none | 2 | MATCH (total + expected alert both present) |
| VPI-OUT-2015 | Sunrise Engineering Works | 14-Jul | 10-Aug | 514,775.00 | 514,775.00 | PAID | none | none | 2 | MATCH |
| VPI-OUT-2016 | Sunrise Engineering Works | 18-Aug | 17-Sep | 514,775.00 | 514,775.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2017 | Sunrise Engineering Works | 19-Aug | 17-Sep | 514,775.00 | 514,775.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2018 | Deccan Machinery Ltd | 17-Aug | 17-Sep | 484,390.00 | 484,390.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2019 | Deccan Machinery Ltd | 18-Aug | 17-Sep | 484,390.00 | 484,390.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2020 | Deccan Machinery Ltd | 19-Aug | 17-Sep | 484,390.00 | 484,390.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2021 | Kaveri Auto Components | 27-Aug | 26-Sep | 253,700.00 | 253,700.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2022 | Sunrise Engineering Works | 28-Aug | 27-Sep | 323,910.00 | 323,910.00 | VERIFIED | none | none | 2 | MATCH |
| VPI-OUT-2023 | Deccan Machinery Ltd | 30-Aug | 29-Sep | 223,256.00 | 223,256.00 | VERIFIED | none | none | 2 | MATCH |

Outbound sum (as stored): 5,248,631.00 — matches README §3/§6.

Exactly one outbound row carries `tax_mismatch` (VPI-OUT-2014) and no other outbound row carries any alert. **MATCH.**

## Score

26/26 rows MATCH on total. 3/3 expected alerts present (NAT-2007, RAJ-2009 `possible_duplicate`; VPI-OUT-2014 `tax_mismatch`) and no unexpected alert (in particular no inbound line-math alert — Gap 502's contract holds). Field confidence is populated and only one key on one row (OM -2002 `PaymentTerm` 0.332) is below 0.4.

Checked `customer_name` directly (not just the derived table above): all 12 OUTBOUND rows correctly carry the real customer (Kaveri/Sunrise/Deccan) in `customer_name`, and `vendor_name` correctly carries the tenant's own name (VPI is the issuer on an outbound invoice) — this is correct by design, not the REMITTANCE_ADVICE party-name defect from `vpi_demo_attachments_2026-09-19/README.md` root cause 2 (that one is chat-attachment-specific and unaffected by this check).
