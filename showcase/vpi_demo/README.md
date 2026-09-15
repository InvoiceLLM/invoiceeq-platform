# VPI demo tenant — Vishwa Precision Industries Pvt Ltd (INR)

Built 2026-09-08 from the invoices in `Downloads/invoiceeq_test_pdfs_india/india`
plus 10 generated financial documents in `upload/` (regenerate with
`make_financial_docs.py`). Everything is INR, GST 9% + 9%, Pune-based.

**Credit note (updated 2026-09-15).** `inbound_creditnote_BharatHardware_BHF-CN-2010.pdf` **is in scope** — as **chat attachment turn 11** (§5), not as an uploaded invoice. Feature 31 (credit/debit-note lifecycle, sub-type routing, partial payments) was **cancelled 2026-09-14**; the credit note is now a Feature 30 `card_net_position` bubble plus a Feature 33 `auto_apply_credit_notes` convention proposal. It never becomes an `Invoice` row and it moves no aggregate.

**With ATLAS:** see §8.

## 1. Create the tenant (you do this — a tenant is a Clerk organisation)

1. Open the dev website: `https://ca-invoice-website-dev.thankfulmeadow-4281ea23.eastus2.azurecontainerapps.io`
2. Sign up with a NEW email (e.g. `accounts@vishwaprecision.in` or a +alias of yours).
   The website calls `POST /auth/provision` after admin signup and creates the tenant.
3. Company name at signup: **Vishwa Precision Industries Pvt Ltd**.

## 2. Upload order

| Step | Files | Why this order |
|---|---|---|
| A | the 11 `inbound_*.pdf` tax invoices (the credit note is NOT uploaded — it is attachment turn 11 in step D) | builds vendor master + inbound ledger |
| B | the 9 `outbound_*.pdf` | receivables + the planted math error |
| B2 | `invoices_other_formats/` — 3 inbound + 3 outbound as PNG / JPG (scanned look) / TIFF / WEBP / BMP | exercises image OCR; new numbers, no duplicates (see §3b) |
| C | mark PAID via audit console: BHA-2002, OM -2000, SHR-2004, VPI-OUT-2012, VPI-OUT-2015 | they are paid on the bank statement; leaves the real overdue ones |
| D | chat attachments, one per turn, from `upload/` and then the credit note from `invoices_pdf/` (see §5, turns 1–11) | insight bubble |

**Upload order within step A matters for ATLAS.** Discover fires on the 10th completed extraction (`ANALYST_ONBOARD_MIN_DOCS = 10`). In filename order the 10th file is `inbound_Shree_Packaging_Industries_SHR-2004.pdf`, so the first business profile is built from **10 invoices, not 11** — SHR-2005 arrives after it. Every Day-1 figure in the ATLAS scenario document depends on this; pin the order when running the eval.

## 3. Ground truth (computed from the PDFs)

**Inbound** (11 tax invoices; `BHF-CN-2010` is a credit note and is handled as attachment turn 11, not as an invoice)

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
- Every inbound line passes `qty × rate = amount` and `subtotal + CGST + SGST = total`. **No inbound invoice has a math error** — an inbound line-math alert is a false positive.

**Credit note** (attachment turn 11, not an invoice): `BHF-CN-2010`, Bharat Hardware, 17-Aug-2026, one line `Hex Bolts M10x40, box 100` 25 @ 1,450 = −36,250.00, CGST −3,262.50, SGST −3,262.50, **total −42,775.00**. It prints **no invoice reference** — resolution is by counterparty + identical line + date + open status, and the identical line also appears on the already-paid BHA-2002, so a correct bubble names both candidates and says why it chose BHA-2003. Net on BHA-2003: 103,191.00 − 42,775.00 = **60,416.00**.

**Image-format invoices** (§3b — `invoices_other_formats/`, regenerate with `make_image_invoices.py`)

| File | Doc | Party | Date | Due | Total |
|---|---|---|---|---|---|
| inbound_Om_Stationery_Mart_OM-2002.png | OM -2002 | Om Stationery Mart | 26-Aug | 25-Sep | 28,792.00 |
| inbound_Ganesh_Bearings_GBP-2012_scanned.jpg | GBP-2012 | Ganesh Bearings Pvt Ltd | 28-Aug | 27-Sep | 103,368.00 |
| inbound_Shree_Packaging_SHR-2006.tiff | SHR-2006 | Shree Packaging Industries | 29-Aug | 28-Sep | 122,720.00 |
| outbound_Kaveri_Auto_VPI-OUT-2021.png | VPI-OUT-2021 | Kaveri Auto Components | 27-Aug | 26-Sep | 253,700.00 |
| outbound_Sunrise_Engineering_VPI-OUT-2022.webp | VPI-OUT-2022 | Sunrise Engineering Works | 28-Aug | 27-Sep | 323,910.00 |
| outbound_Deccan_Machinery_VPI-OUT-2023.bmp | VPI-OUT-2023 | Deccan Machinery Ltd | 30-Aug | 29-Sep | 223,256.00 |

With these uploaded: inbound total (no duplicates, gross) 1,119,300.80 + 254,880 = **1,374,180.80**; outbound total 4,447,765 + 800,866 = **5,248,631**. **The §6 answers below are for the full 26-invoice set** (14 inbound + 12 outbound), i.e. step B2 done.

**Outbound** (9 invoices, all due 17-Sep except the two July ones)

| Doc | Customer | Date | Due | Total | Note |
|---|---|---|---|---|---|
| VPI-OUT-2012 | Kaveri Auto Components | 14-Jul | 10-Aug | 483,210.00 | received 09-Aug |
| VPI-OUT-2013 | Kaveri Auto Components | 18-Aug | 17-Sep | 483,210.00 | |
| VPI-OUT-2014 | Kaveri Auto Components | 19-Aug | 17-Sep | 483,850.00 | **MATH ERROR**: lines+tax = 483,210, printed 483,850 (+640) |
| VPI-OUT-2015 | Sunrise Engineering Works | 14-Jul | 10-Aug | 514,775.00 | received 11-Aug |
| VPI-OUT-2016/2017 | Sunrise Engineering Works | 18/19-Aug | 17-Sep | 514,775.00 each | |
| VPI-OUT-2018/2019/2020 | Deccan Machinery Ltd | 17/18/19-Aug | 17-Sep | 484,390.00 each | 200,000 advance on the bank statement 25-Aug; a payment fact is recorded against VPI-OUT-2018, but it is **not applied** to the invoice balance (partial-payment application was Feature 31, cancelled 2026-09-14) |

- Receivables total as printed: **4,447,765.00**; by customer: Sunrise 1,544,325 · Deccan 1,453,170 · Kaveri 1,450,270
- Outstanding after step C: 3,449,780 (2013, 2014, 2016, 2017, 2018, 2019, 2020)
- Total GST charged on the 12 outbound invoices: **800,541.00**

**GST head — a real finding, not a fixture footnote.** All 12 outbound invoices charge **CGST 9% + SGST 9%**, but every customer is outside Maharashtra (Kaveri: Bengaluru KA · Sunrise: Ahmedabad GJ · Deccan: Hyderabad TS). Inter-state supply should carry **IGST 18%**, and no customer GSTIN is printed on any outbound invoice. That is **800,541.00 of GST under the wrong head on 12 invoices**. Founder decision pending: fix the generator, or keep it as the demo's headline compliance finding (see the scenario document §0, D-5).

## 4. What the "needs attention" areas should show

| Area | Expected items | Source |
|---|---|---|
| Audit alert queue | VPI-OUT-2014 total mismatch (+640, after Gap 504); NAT-2007 and RAJ-2009 as possible duplicates (Gap 503) | extraction alerts |
| Overdue / unpaid (semantic views, Feature 30) | before step C: BHA-2002, OM -2000, SHR-2004 (payables), VPI-OUT-2012, VPI-OUT-2015 (receivables). After step C, as of 15-Sep-2026: **none overdue**; 9 payables and 10 receivables open, with 5 payables (783,885.80 clean) due that day | `v_overdue` |
| Insight lifecycle | one finding per attachment in §5, all OPEN until you act (hold / snooze / dispute / paid) | Feature 30 bubble |
| Vendor master | Ganesh Bearings asks for first-link confirmation when PO-VPI-1042 is attached | doc_linking |
| Forecast depth | only **one** bank statement exists (August). The `recurring` and `estimated` tiers stay `NOT_CHECKED` until the **June and July statements are generated — task 33.38, still pending**. Do not expect salary / GST / electricity recurrence in a demo run today | Feature 33 §3.4 |

If NAT-2007 / RAJ-2009 are NOT flagged, that is a real finding: they differ only by invoice number.

## 5. Attachment turns (insight bubble), with expected content

Ask each with the file attached in chat. Expected figures come from the ground truth above.

| # | Attach | Ask | Expected bubble |
|---|---|---|---|
| 1 | `PO_PO-VPI-1041_RAJ.pdf` | "Does this PO match the Rajesh Steel invoice?" | Links to RAJ-2008; 2 lines match qty and rate; PO value 437,190 = invoice; flags RAJ-2009 as a second invoice against the same PO |
| 2 | `PO_PO-VPI-1042_GBP.pdf` | "Is the Ganesh Bearings invoice within this PO?" | New vendor → confirm first link; then GBP-2011 matches 60 @ 520 and 25 @ 1,080, total 68,676 |
| 3 | `PO_PO-VPI-1043_SHR.pdf` | "Compare with Shree Packaging's August invoice" | SHR-2005 matches 3 lines, 121,894; SHR-2004 (July) is a different, already-paid invoice with identical lines — a good answer names both and says which it used |
| 4 | `DC_DC-RSC-0812_RAJ.pdf` | "Was everything on this challan invoiced?" | 6 coils + 30 bars delivered = RAJ-2008 quantities; 3-way match clean; RAJ-2009 duplicates it |
| 5 | `DC_DC-NMT-2291_NAT.pdf` | "Check delivery against invoice" | 5 / 12 / 8 delivered = NAT-2006; NAT-2007 has no challan → duplicate. The challan cites **PO-VPI-1039, which is not on file**, so the order leg is `NOT_CHECKED` — not a clean 3-way match |
| 6 | `DC_DC-BHF-0455_BHA.pdf` | "Any short delivery here?" | 25 / 15 / 4 delivered = BHA-2003; no shortage. Cites **PO-VPI-1040, not on file** → order leg `NOT_CHECKED` |
| 7 | `PA_PA-VPI-0071_OM.pdf` | "Which invoice does this payment settle?" | OM -2000, 41,654 paid in full 05-Aug, UTR HDFCN26080512345; OM -2001 still open |
| 8 | `PA_PA-VPI-0072_BHA.pdf` | "Is Bharat Hardware fully paid?" | BHA-2002 settled 103,191; BHA-2003 open **103,191** |
| 9 | `PA_PA-VPI-0073_SHR.pdf` | "What do we still owe Shree Packaging?" | SHR-2004 paid; open = SHR-2005 121,894 **+ SHR-2006 122,720 = 244,614** (if step B2 was done) |
| 10 | `BankStatement_HDFC_4471_Aug2026.pdf` — attach it in a **private (`exec`) session** to exercise clearance | "Match this statement to our books" | 3 debits match OM -2000, BHA-2002, SHR-2004 (±1, ±5 days); 2 credits match VPI-OUT-2012, VPI-OUT-2015; the **200,000 Deccan credit names VPI-OUT-2018** and is reported as a 41.3% partial receipt (balance 284,390) that is **recorded but not applied**; unmatched debits: GST 184,320, electricity 96,410, salary 1,486,000, AMC 58,000, charges 1,180 (= 1,825,910); closing balance **355,336.00 as of 31-Aug-2026**. `recurring` cash cover is `NOT_CHECKED` — one month of depth (see §4) |
| 11 | `inbound_creditnote_BharatHardware_BHF-CN-2010.pdf` | "Bharat sent this — what do we actually owe them?" | `card_net_position`: credit note −42,775 resolves to **BHA-2003** (same 17-Aug date, still open) over the identical-line **BHA-2002** (settled 06-Aug) — both named; net owed **60,416**. No `Invoice` row, no aggregate moves (Feature 26 D2/D3): Bharat spend stays 206,382 and BHA-2003 stays open at 103,191. Its own arithmetic is correct and must raise **no** line-math alert (Gap 502). Also raises the `auto_apply_credit_notes` convention proposal: 1 credit note / 14 inbound invoices (7.1%), 42,775 |

**Statement depth (task 33.38, pending).** Only `BankStatement_HDFC_4471_Aug2026.pdf` exists today. 33.38 adds **June-2026 and July-2026** statements chaining opening/closing balances Jun → Jul → Aug, with the recurring lines (salary, GST, electricity, AMC, bank charges) present in all three, so `detect_recurrence()` and the `estimated` tier reach the ≥3 months of depth they need. Until then, every `recurring` / `estimated` expectation in the scenario document is marked illustrative. The August statement's existing lines and its 355,336.00 closing balance must not change when the generator is extended.

**Scenario 10, doc type (BE Gap 516, 2026-09-14).** The bank statement's own type is `BANK_STATEMENT`; it used to be filed as `STATEMENT_OF_ACCOUNT`, which is the SUPPLIER statement's type. Only `BANK_STATEMENT` has its rows landed into the bank ledger and matched to invoices. **Founder ruling 2026-09-14 ("Rename the demo file title"): this file's printed title is now "HDFC BANK LIMITED — BANK STATEMENT"**, regenerated from `make_financial_docs.py::bank_statement()`. It used to print "HDFC BANK LIMITED — STATEMENT OF ACCOUNT" — a title banks and suppliers both print — which left the demo's own headline document depending on the LLM stage while the other nine were deterministic. Executed against the real `classify_doc_type_deterministic()` over the text of the regenerated PDF: `('BANK_STATEMENT', 'HDFC BANK LIMITED — BANK STATEMENT')`. **No synonym was added and the supplier-statement vocabulary was not touched** (the fix is the demo fixture's title, not the rule): `'Statement of Account'` still returns `STATEMENT_OF_ACCOUNT`, and the ambiguous `'HDFC BANK LIMITED — STATEMENT OF ACCOUNT'` still returns `STATEMENT_OF_ACCOUNT` too — which is exactly why the demo file no longer prints it.

## 6. Chat walkthrough (no attachment), with expected answers

**`as_of` = 2026-09-15.** Every date-dependent answer below (notably #5) is stated against that date, not an implied "today". If you run the demo on another date, recompute #5 from the due-date columns in §3.

**Scope of these answers:** all 26 invoices uploaded (11 inbound PDF + 3 inbound image, 9 outbound PDF + 3 outbound image), the credit note attached in chat only and **never uploaded**, and step C done (BHA-2002, OM -2000, SHR-2004, VPI-OUT-2012, VPI-OUT-2015 marked paid). "Clean" means the two duplicates (NAT-2007, RAJ-2009) excluded.

| # | Ask | Expected answer |
|---|---|---|
| 1 | What is our total inbound spend? | **1,891,327.60** across 14 invoices as uploaded; a good answer names NAT-2007 and RAJ-2009 as duplicates and offers the clean **1,374,180.80** |
| 2 | Which vendor did we spend the most with? | Rajesh Steel Corporation, **437,190** clean (874,380 if RAJ-2009 is counted; saying which is used is part of a correct answer). Then Shree 366,508 · Bharat 206,382 · Ganesh 172,044 · Om 112,100 · National MRO 79,956.80 |
| 3 | List all vendors | the 6 inbound vendors; customers are not vendors |
| 4 | Do we have any duplicate invoices? | NAT-2006/NAT-2007 and RAJ-2008/RAJ-2009, both flagged `possible_duplicate`; 517,146.80 of duplicate exposure |
| 5 | Which invoices are overdue? | **none as of 15-Sep-2026** — all remaining due dates are 15-Sep or later. A good answer adds that **5 clean payables are due that same day**: BHA-2003, NAT-2006, OM -2001, RAJ-2008, SHR-2005 = **783,885.80** |
| 6 | How much do we owe Bharat Hardware? | **103,191** (BHA-2003 open); BHA-2002 paid. If the credit note comes up: the books say 103,191 and the net position after BHF-CN-2010 is 60,416 — the note is a chat attachment and moves no aggregate |
| 7 | Total GST on inbound invoices in August | clean August invoices: BHA-2003 15,741 + GBP-2011 10,476 + NAT-2006 12,196.80 + OM -2001 6,354 + RAJ-2008 66,690 + SHR-2005 18,594 + OM -2002 4,392 + GBP-2012 15,768 + SHR-2006 18,720 = **168,931.80** (all intra-state: CGST 84,465.90 + SGST 84,465.90, IGST 0) |
| 8 | What did we buy from National MRO Traders? | Industrial Lubricant 20L ×5, Replacement V-Belts ×12, Safety Gloves ×8 — 79,956.80 once, not twice (NAT-2007 is a duplicate) |
| 9 | Show outbound invoices to Deccan Machinery | VPI-OUT-2018/2019/2020 at 484,390 each (due 17-Sep) and VPI-OUT-2023 at 223,256 (due 29-Sep) = **1,676,426** open, with 200,000 received as an unapplied advance |
| 10 | Which outbound invoice has a total that doesn't add up? | **VPI-OUT-2014**: lines + tax 483,210 vs printed 483,850, flagged `tax_mismatch`, status Needs review — the only one |
| 11 | Total receivables outstanding | **4,250,646** as printed (12 outbound less the two received). A good answer adds 4,250,006 if VPI-OUT-2014 is corrected, and 4,050,646 net of the unapplied 200,000 Deccan advance |
| 12 | What is the invoice number of the Ganesh Bearings invoice and when is it due? | two now: GBP-2011 due 18-Sep and GBP-2012 due 27-Sep; a good answer asks which or lists both. One invoice named with no mention of the other — or a 0 — is a fail |
| 13 | Give me inbound spend per month for July and August | July **266,739** (BHA-2002, OM -2000, SHR-2004); August clean **1,107,441.80** (1,624,588.60 with the duplicates) |
| 14 | Convert Rajesh Steel's invoice to USD | must abstain: no exchange rate is held anywhere in the data. An INR figure relabelled `$` is a fail |
| 15 | Which invoices have HSN 8483? | **12 invoices**: outbound **VPI-OUT-2012 through VPI-OUT-2020** — Precision Shaft Coupling B-9 on 2012–2014, Machined Housing H-3 *and* Gearbox Mounting Plate on 2015–2017, **Drive Sprocket Set on 2018–2020** — plus VPI-OUT-2021 and VPI-OUT-2022; inbound GBP-2012 (Bearing Housing P205). VPI-OUT-2023 is 8428-only and is excluded. *(Corrected 2026-09-15: the earlier answer listed "2012 to 2017" while naming Drive Sprocket, which is on 2018–2020.)* |

Two questions worth asking because today's data makes them fail loudly if something regressed:

| # | Ask | Expected answer |
|---|---|---|
| 16 | Which invoices need my attention? | exactly three: VPI-OUT-2014 (total mismatch), NAT-2007 and RAJ-2009 (possible duplicates). ATLAS's Today findings (GST head, missing customer GSTINs, Deccan concentration) are not invoice-level alerts and must not change this answer |
| 17 | Did we pay Om Stationery twice? | no: OM -2000 (9-Jul, paid 5-Aug) and OM -2001 (16-Aug, open) are different invoices for the same amount; OM -2002 is a third, smaller one |

Three more that probe tenant conventions rather than extraction:

| # | Ask | Expected answer |
|---|---|---|
| 18 | What's our spend this fiscal year? | must resolve to **FY 2026-27 (1-Apr-2026 → 31-Mar-2027)**, not calendar 2026 — inbound 1,374,180.80 clean, outbound 5,248,631, all of it in Q2 FY27 |
| 19 | How much is outstanding? | ambiguous — must ask which side: payables 1,107,441.80 or receivables 4,250,646. A single number, or a 0, is a fail |
| 20 | Show me the CGST/SGST split for August | inbound CGST 84,465.90 + SGST 84,465.90, IGST 0; and a correct answer flags that the outbound side charges CGST+SGST on inter-state supplies where IGST is due (§3) |

## 7. Files

- `make_financial_docs.py` — generator (reportlab), deterministic. **Task 33.38 pending**: add the June-2026 and July-2026 bank statements (see §5)
- `make_image_invoices.py` — the 6 image-format invoices (PIL), deterministic
- `upload/` — 3 POs, 3 delivery challans, 3 payment advices, 1 bank statement
- `invoices_pdf/` — 21 PDFs (11 inbound tax invoices, 9 outbound, 1 credit note). The credit note is **attachment turn 11**, not an upload
- `invoices_other_formats/` — 6 image-format invoices

## 8. With ATLAS (BE Feature 33 / FE Feature 22)

Full expected run, day by day, with every figure pre-computed and every "why it ranks here" sentence:
**`Prod_Invoice_LLM/apps/invoice-be/docs/atlas_vpi_scenario_day1_30.md`** — the ground truth for tasks 33.21 and 33.40. Figures are **not** duplicated here; that document is the reference.

What the demo run should look like once ATLAS is on:

| moment | what to expect |
|---|---|
| **First login, before 10 documents** | `GET /today` returns `pre_onboarding` with `docs_seen / docs_required` and **nothing else** — no findings, no forecast, no input requests. "Upload to begin", the progress count, the inbox address, a drop zone |
| **The 10th extraction** | Discover runs (not at login). It profiles the tenant deterministically: 6 vendors, INR only, India GST intra-state, which fields are always present, which document chains exist, and `coverage_for()` over the 11 input kinds |
| **Right after Discover** | the **five routine questions**, one at a time, chip or free text, each skippable: when you pay vendors · whether a PO precedes the invoice · who approves an invoice · which day you close the month · who chases overdue receivables. Answers are stored as tenant chat rules with `source="atlas_onboarding"` and are editable in the Trainer. Each answer changes Today: payables grouped by payment-run day, a line per materials invoice with no PO, a pending-sign-off line, a month-close countdown, overdue receivables addressed to the named owner |
| **Convention proposals** | answered **in place** on Today with Accept / Edit / Reject — never on a second screen. On VPI the derivable ones are duplicate handling (517,146.80 of exposure), default terms NET 30 (median 28 days over the three settled invoices — *not* the "Rajesh at 47 days" example in the spec, which has no basis in this data) and `auto_apply_credit_notes` (42,775). An accepted rule is written to the existing store with `source="atlas"` |
| **Input requests** | each names an **exact document kind** and a **quantified unlock** — "September's bank statement: 5,358,087.80 of movement unconfirmed", "PO-VPI-1039 and PO-VPI-1040: 9 invoices / 746,420.80 unverifiable", "GSTR-2B for August: 168,931.80 of input credit unreconciled". "More data" is never acceptable phrasing. `loan_schedules` must **not** be requested — nothing in the data justifies it |
| **Run now** | an Admin-only button enqueues a tenant run immediately; a second press inside 10 minutes returns 429 with a countdown shown on the button |
| **Weekly** | Monday 06:00 UTC. On the first real run (14-Sep) the top line is a **428,549.80 cash shortfall on 15-Sep** — 783,885.80 of payables due against a 355,336.00 balance last known at 31-Aug, two days before 3,449,780.00 lands |
| **Clearance** | attach the August statement in a **private (`exec`)** session as the Admin. An Auditor then sees the six `ops` payment facts — including "BHA-2002 paid 06-Aug, UTR HDFCN26080612346", derived from a document they cannot open — and must **not** see the statement, the file, the 355,336.00 balance, the 1,486,000.00 salary, the GST, electricity, AMC or bank-charge lines, or any cash-runway line. Absent, not blanked: a 0 where a runway line would be is a defect. A second Admin **does** see everything — clearance is by role |
| **Upload / Attach** | both open the browser's own file picker and post to the existing ingestion / chat-attachment endpoints. Typing "upload my invoices" in Ask returns an attach **button**, not a directory listing — ATLAS never touches the disk |
| **Forecast tiers** | `certain` from due dates; `committed` is **0.00** on VPI (all three POs are fully invoiced — the spec's "4.4L still to be invoiced on PO-1041" is the PO value, not a balance); `recurring` and `estimated` stay `NOT_CHECKED` until the June/July statements exist (task 33.38) |
| **FP&A** | five cards, and on VPI most are `NOT_CHECKED` with a named reason and an attached request — never a blank or a 0 tile. `margin_per_item` is `NOT_CHECKED` because **no item appears on both an inbound and an outbound invoice**; revenue per customer is real, margin per customer is not, until a P&L is attached |
| **SAGE, after all of it** | re-ask all 20 questions in §6. **Every answer must be unchanged.** The facts ledger, the clearance filters and the Today surface must not move a single SAGE figure — that is the regression contract |
