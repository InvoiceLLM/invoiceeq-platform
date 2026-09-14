# VPI demo tenant — Vishwa Precision Industries Pvt Ltd (INR)

Built 2026-09-08 (credit note removed from scope 2026-09-09, see Feature 31) from the invoices in `Downloads/invoiceeq_test_pdfs_india/india`
plus 10 generated financial documents in `upload/` (regenerate with
`make_financial_docs.py`). Everything is INR, GST 9% + 9%, Pune-based.

## 1. Create the tenant (you do this — a tenant is a Clerk organisation)

1. Open the dev website: `https://ca-invoice-website-dev.thankfulmeadow-4281ea23.eastus2.azurecontainerapps.io`
2. Sign up with a NEW email (e.g. `accounts@vishwaprecision.in` or a +alias of yours).
   The website calls `POST /auth/provision` after admin signup and creates the tenant.
3. Company name at signup: **Vishwa Precision Industries Pvt Ltd**.

## 2. Upload order

| Step | Files | Why this order |
|---|---|---|
| A | the 11 `inbound_*.pdf` invoices (NOT `inbound_creditnote_BharatHardware_BHF-CN-2010.pdf`) | builds vendor master + inbound ledger |
| B | the 9 `outbound_*.pdf` | receivables + the planted math error |
| B2 | `invoices_other_formats/` — 3 inbound + 3 outbound as PNG / JPG (scanned look) / TIFF / WEBP / BMP | exercises image OCR; new numbers, no duplicates (see §3b) |
| C | mark PAID via audit console: BHA-2002, OM -2000, SHR-2004, VPI-OUT-2012, VPI-OUT-2015 | they are paid on the bank statement; leaves the real overdue ones |
| D | chat attachments, one per turn, from `upload/` (see §5) | insight bubble |

## 3. Ground truth (computed from the PDFs)

**Inbound** (11 tax invoices; the credit note BHF-CN-2010 is EXCLUDED from today's demo — its lifecycle is Feature 31, not built yet; do not upload it)

| Doc | Vendor | Date | Due | Total | Note |
|---|---|---|---|---|---|
| BHA-2002 | Bharat Hardware & Fasteners | 09-Jul | 08-Aug | 103,191.00 | paid 06-Aug |
| BHA-2003 | Bharat Hardware & Fasteners | 17-Aug | 15-Sep | 103,191.00 | |
| GBP-2011 | Ganesh Bearings Pvt Ltd | 19-Aug | 18-Sep | 68,676.00 | NEW vendor |
| NAT-2006 | National MRO Traders | 19-Aug | 15-Sep | 79,956.80 | |
| NAT-2007 | National MRO Traders | 19-Aug | 15-Sep | 79,956.80 | DUPLICATE of NAT-2006 |
| OM -2000 | Om Stationery Mart | 09-Jul | 08-Aug | 41,654.00 | paid 05-Aug |
| OM -2001 | Om Stationery Mart | 16-Aug | 15-Sep | 41,654.00 | |
| RAJ-2008 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 437,190.00 | |
| RAJ-2009 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 437,190.00 | DUPLICATE of RAJ-2008 |
| SHR-2004 | Shree Packaging Industries | 09-Jul | 08-Aug | 121,894.00 | paid 07-Aug |
| SHR-2005 | Shree Packaging Industries | 18-Aug | 15-Sep | 121,894.00 | |

- Inbound total, all 11 invoices as uploaded: **1,636,447.60**
- Excluding the two duplicates: **1,119,300.80**
- Spend by vendor (no duplicates, gross): Rajesh 437,190 · Shree 243,788 · Bharat 206,382 · Om 83,308 · National MRO 79,956.80 · Ganesh 68,676
- Unpaid inbound after step C (no duplicates): BHA-2003, GBP-2011, NAT-2006, OM -2001, RAJ-2008, SHR-2005 = **852,561.80**

**Image-format invoices** (§3b — `invoices_other_formats/`, regenerate with `make_image_invoices.py`)

| File | Doc | Party | Date | Due | Total |
|---|---|---|---|---|---|
| inbound_Om_Stationery_Mart_OM-2002.png | OM -2002 | Om Stationery Mart | 26-Aug | 25-Sep | 28,792.00 |
| inbound_Ganesh_Bearings_GBP-2012_scanned.jpg | GBP-2012 | Ganesh Bearings Pvt Ltd | 28-Aug | 27-Sep | 103,368.00 |
| inbound_Shree_Packaging_SHR-2006.tiff | SHR-2006 | Shree Packaging Industries | 29-Aug | 28-Sep | 122,720.00 |
| outbound_Kaveri_Auto_VPI-OUT-2021.png | VPI-OUT-2021 | Kaveri Auto Components | 27-Aug | 26-Sep | 253,700.00 |
| outbound_Sunrise_Engineering_VPI-OUT-2022.webp | VPI-OUT-2022 | Sunrise Engineering Works | 28-Aug | 27-Sep | 323,910.00 |
| outbound_Deccan_Machinery_VPI-OUT-2023.bmp | VPI-OUT-2023 | Deccan Machinery Ltd | 30-Aug | 29-Sep | 223,256.00 |

With these uploaded: inbound total (no duplicates, gross) 1,119,300.80 + 254,880 = **1,374,180.80**; outbound total 4,447,765 + 800,866 = **5,248,631**. The §6 answers below are for the PDF set only; add these if step B2 was done.

**Outbound** (9 invoices, all due 17-Sep except the two July ones)

| Doc | Customer | Date | Due | Total | Note |
|---|---|---|---|---|---|
| VPI-OUT-2012 | Kaveri Auto Components | 14-Jul | 10-Aug | 483,210.00 | received 09-Aug |
| VPI-OUT-2013 | Kaveri Auto Components | 18-Aug | 17-Sep | 483,210.00 | |
| VPI-OUT-2014 | Kaveri Auto Components | 19-Aug | 17-Sep | 483,850.00 | **MATH ERROR**: lines+tax = 483,210, printed 483,850 (+640) |
| VPI-OUT-2015 | Sunrise Engineering Works | 14-Jul | 10-Aug | 514,775.00 | received 11-Aug |
| VPI-OUT-2016/2017 | Sunrise Engineering Works | 18/19-Aug | 17-Sep | 514,775.00 each | |
| VPI-OUT-2018/2019/2020 | Deccan Machinery Ltd | 17/18/19-Aug | 17-Sep | 484,390.00 each | 200,000 advance on the bank statement 25-Aug; shows as an unmatched credit (no partial-payment support yet) |

- Receivables total as printed: **4,447,765.00**; by customer: Sunrise 1,544,325 · Deccan 1,453,170 · Kaveri 1,450,270
- Outstanding after step C: 3,449,780 (2013, 2014, 2016, 2017, 2018, 2019, 2020)

## 4. What the "needs attention" areas should show

| Area | Expected items | Source |
|---|---|---|
| Audit alert queue | VPI-OUT-2014 total mismatch (+640, after Gap 504); NAT-2007 and RAJ-2009 as possible duplicates (Gap 503) | extraction alerts |
| Overdue / unpaid (semantic views, Feature 30) | before step C: BHA-2002, OM -2000, SHR-2004 (payables), VPI-OUT-2012, VPI-OUT-2015 (receivables). After step C: none overdue today; 6 payables and 7 receivables open | `v_overdue` |
| Insight lifecycle | one finding per attachment in §5, all OPEN until you act (hold / snooze / dispute / paid) | Feature 30 bubble |
| Vendor master | Ganesh Bearings asks for first-link confirmation when PO-VPI-1042 is attached | doc_linking |

If NAT-2007 / RAJ-2009 are NOT flagged, that is a real finding: they differ only by invoice number.

## 5. Attachment turns (insight bubble), with expected content

Ask each with the file attached in chat. Expected figures come from the ground truth above.

| # | Attach | Ask | Expected bubble |
|---|---|---|---|
| 1 | `PO_PO-VPI-1041_RAJ.pdf` | "Does this PO match the Rajesh Steel invoice?" | Links to RAJ-2008; 2 lines match qty and rate; PO value 437,190 = invoice; flags RAJ-2009 as a second invoice against the same PO |
| 2 | `PO_PO-VPI-1042_GBP.pdf` | "Is the Ganesh Bearings invoice within this PO?" | New vendor → confirm first link; then GBP-2011 matches 60 @ 520 and 25 @ 1,080, total 68,676 |
| 3 | `PO_PO-VPI-1043_SHR.pdf` | "Compare with Shree Packaging's August invoice" | SHR-2005 matches 3 lines, 121,894; SHR-2004 (July) is a different, already-paid invoice |
| 4 | `DC_DC-RSC-0812_RAJ.pdf` | "Was everything on this challan invoiced?" | 6 coils + 30 bars delivered = RAJ-2008 quantities; 3-way match clean; RAJ-2009 duplicates it |
| 5 | `DC_DC-NMT-2291_NAT.pdf` | "Check delivery against invoice" | 5 / 12 / 8 delivered = NAT-2006; NAT-2007 has no challan → duplicate |
| 6 | `DC_DC-BHF-0455_BHA.pdf` | "Any short delivery here?" | 25 / 15 / 4 delivered = BHA-2003; no shortage |
| 7 | `PA_PA-VPI-0071_OM.pdf` | "Which invoice does this payment settle?" | OM -2000, 41,654 paid in full 05-Aug, UTR HDFCN26080512345; OM -2001 still open |
| 8 | `PA_PA-VPI-0072_BHA.pdf` | "Is Bharat Hardware fully paid?" | BHA-2002 settled 103,191; BHA-2003 open **103,191** |
| 9 | `PA_PA-VPI-0073_SHR.pdf` | "What do we still owe Shree Packaging?" | SHR-2004 paid; SHR-2005 open 121,894 |
| 10 | `BankStatement_HDFC_4471_Aug2026.pdf` | "Match this statement to our books" | 3 debits match OM -2000, BHA-2002, SHR-2004 (±1, ±5 days); 2 credits match VPI-OUT-2012, VPI-OUT-2015; 200,000 Deccan credit = UNMATCHED (advances/partial receipts are not supported yet, Feature 31 candidate); unmatched debits: GST 184,320, electricity 96,410, salary 1,486,000, AMC 58,000, charges 1,180; closing balance 355,336.00 |

**Scenario 10, doc type (BE Gap 516, 2026-09-14).** The bank statement's own type is `BANK_STATEMENT`; it used to be filed as `STATEMENT_OF_ACCOUNT`, which is the SUPPLIER statement's type. Only `BANK_STATEMENT` has its rows landed into the bank ledger and matched to invoices. **Founder ruling 2026-09-14 ("Rename the demo file title"): this file's printed title is now "HDFC BANK LIMITED — BANK STATEMENT"**, regenerated from `make_financial_docs.py::bank_statement()`. It used to print "HDFC BANK LIMITED — STATEMENT OF ACCOUNT" — a title banks and suppliers both print — which left the demo's own headline document depending on the LLM stage while the other nine were deterministic. Executed against the real `classify_doc_type_deterministic()` over the text of the regenerated PDF: `('BANK_STATEMENT', 'HDFC BANK LIMITED — BANK STATEMENT')`. **No synonym was added and the supplier-statement vocabulary was not touched** (the fix is the demo fixture's title, not the rule): `'Statement of Account'` still returns `STATEMENT_OF_ACCOUNT`, and the ambiguous `'HDFC BANK LIMITED — STATEMENT OF ACCOUNT'` still returns `STATEMENT_OF_ACCOUNT` too — which is exactly why the demo file no longer prints it.

## 6. Chat walkthrough (no attachment), with expected answers

**Scope of these answers:** all 20 invoices uploaded (11 inbound PDF + 3 inbound image, 9 outbound PDF + 3 outbound image), the credit note NOT uploaded, and step C done (BHA-2002, OM -2000, SHR-2004, VPI-OUT-2012, VPI-OUT-2015 marked paid). "Clean" means the two duplicates (NAT-2007, RAJ-2009) excluded.

| # | Ask | Expected answer |
|---|---|---|
| 1 | What is our total inbound spend? | **1,891,327.60** across 14 invoices as uploaded; a good answer names NAT-2007 and RAJ-2009 as duplicates and offers the clean **1,374,180.80** |
| 2 | Which vendor did we spend the most with? | Rajesh Steel Corporation, **437,190** clean (874,380 if RAJ-2009 is counted; saying which is used is part of a correct answer). Then Shree 366,508 · Bharat 206,382 · Ganesh 172,044 · Om 112,100 · National MRO 79,956.80 |
| 3 | List all vendors | the 6 inbound vendors; customers are not vendors |
| 4 | Do we have any duplicate invoices? | NAT-2006/NAT-2007 and RAJ-2008/RAJ-2009, both flagged `possible_duplicate` |
| 5 | Which invoices are overdue? | none after step C (today 9-Sep; all remaining due dates are 15-Sep or later) |
| 6 | How much do we owe Bharat Hardware? | **103,191** (BHA-2003 open); BHA-2002 paid |
| 7 | Total GST on inbound invoices in August | clean August invoices: BHA-2003 15,741 + GBP-2011 10,476 + NAT-2006 12,196.80 + OM -2001 6,354 + RAJ-2008 66,690 + SHR-2005 18,594 + OM -2002 4,392 + GBP-2012 15,768 + SHR-2006 18,720 = **168,931.80** |
| 8 | What did we buy from National MRO Traders? | Industrial Lubricant 20L ×5, Replacement V-Belts ×12, Safety Gloves ×8 |
| 9 | Show outbound invoices to Deccan Machinery | VPI-OUT-2018/2019/2020 at 484,390 each (due 17-Sep) and VPI-OUT-2023 at 223,256 (due 29-Sep) |
| 10 | Which outbound invoice has a total that doesn't add up? | **VPI-OUT-2014**: lines + tax 483,210 vs printed 483,850, flagged `tax_mismatch`, status Needs review |
| 11 | Total receivables outstanding | **4,250,646** (12 outbound less the two received) |
| 12 | What is the invoice number of the Ganesh Bearings invoice and when is it due? | two now: GBP-2011 due 18-Sep and GBP-2012 due 27-Sep; a good answer asks which or lists both |
| 13 | Give me inbound spend per month for July and August | July **266,739** (BHA-2002, OM -2000, SHR-2004); August clean **1,107,441.80** (1,624,588.60 with the duplicates) |
| 14 | Convert Rajesh Steel's invoice to USD | must abstain: no exchange rate is held anywhere in the data |
| 15 | Which invoices have HSN 8483? | outbound VPI-OUT-2012 to 2017 (Drive Sprocket / Shaft Coupling / Housing / Mounting Plate), VPI-OUT-2021, VPI-OUT-2022; inbound GBP-2012 (Bearing Housing P205) |

Two questions worth asking because today's data makes them fail loudly if something regressed:

| # | Ask | Expected answer |
|---|---|---|
| 16 | Which invoices need my attention? | exactly three: VPI-OUT-2014 (total mismatch), NAT-2007 and RAJ-2009 (possible duplicates) |
| 17 | Did we pay Om Stationery twice? | no: OM -2000 (9-Jul, paid 5-Aug) and OM -2001 (16-Aug, open) are different invoices for the same amount; OM -2002 is a third, smaller one |

## 7. Files

- `make_financial_docs.py` — generator (reportlab), deterministic
- `upload/` — 3 POs, 3 delivery challans, 3 payment advices, 1 bank statement
- `invoices_pdf/` — 21 PDFs (11 inbound, 9 outbound, 1 credit note). **Skip the credit note today** (Feature 31 pending)
- `invoices_other_formats/` — 6 image-format invoices
