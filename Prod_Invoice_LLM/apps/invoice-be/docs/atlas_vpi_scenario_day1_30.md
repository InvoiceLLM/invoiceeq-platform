# ATLAS × VPI demo — the expected run, Day 1 to Day 30

Authored 2026-09-15 by business-analyst, per architect brief §B4. Ground truth for BE tasks **33.21** and **33.40**, and the acceptance narrative for `feature_33_analyst_agent.md` §9's six approved steps.

**What this document is.** Every figure below is pre-computed from the demo PDFs and `make_image_invoices.py`, by hand, before any system run. It is the expected value a deterministic comparison checks ATLAS against. It is **not** a record of what ATLAS produced, and nothing in it may be revised to match a system output — if the system disagrees, the system is wrong until the arithmetic here is shown to be wrong.

**What it is not.** Not a grading rubric and not a test file. functional-tester compares mechanically (`33.40`: deterministic set comparison, never the LLM judge — Gap 484's rule). Nothing here judges narration quality.

---

## §0. Ground truth vs illustrative, and eight figures that do not reconcile

### 0.1 Marking convention

| mark | meaning |
|---|---|
| **GT** | Ground truth. Derived by arithmetic from a committed demo file (`invoices_pdf/`, `upload/`, `make_image_invoices.py`). Deterministic; an ATLAS figure that differs is a defect. |
| **GT-dep** | Ground truth **conditional on a config default** that is not yet fixed in code (a threshold, a severity ordering). The arithmetic is GT; the trigger is not. Named at each use. |
| **ILL** | Illustrative. Depends on files that do not exist yet (the June/July statements, task **33.38**) or on a period beyond the demo data. **Day 30 is entirely ILL**, and so is every `recurring`/`estimated` forecast tier anywhere in this document. |

Every Day 1 – Day 8 figure is **GT** or **GT-dep**. Day 30 is **ILL**.

### 0.2 Discrepancies found while computing — these change expectations, do not work around them

| # | Claim in an existing doc | What the PDFs actually say | Consequence |
|---|---|---|---|
| **D-1** | `feature_33` §3.7 and brief §B4: `default_terms` proposal — "Rajesh Steel is paid at 47 days; set default terms to NET 45?" | **There is no Rajesh payment anywhere in the demo data.** RAJ-2008 and RAJ-2009 are both unpaid, and no statement line, payment advice or receipt names Rajesh. The only three settled payables are Om (27 d), Bharat (28 d), Shree (29 d) — median **28 days** against printed terms of Net 30. | The expected proposal is **`default_terms` NET 30, median 28 days over 3 settled invoices**, and it is **not derivable on Day 1** (no payment facts exist until the payment advices land on Day 3). "Rajesh at 47 days / NET 45" is a spec illustration, not VPI ground truth, and must not be an expected value in `analyst_golden.json`. |
| **D-2** | README §6 Q15: HSN 8483 → "outbound VPI-OUT-2012 to 2017 … VPI-OUT-2021, VPI-OUT-2022; inbound GBP-2012" | VPI-OUT-**2018/2019/2020** each carry `Drive Sprocket Set, HSN 8483` — the README's own parenthesis names Drive Sprocket but its list omits the three invoices it is on. | Correct answer is **12 invoices**: VPI-OUT-2012 … 2020 (nine PDFs), VPI-OUT-2021, VPI-OUT-2022, inbound GBP-2012. VPI-OUT-2023 is 8428-only and excluded. README corrected. |
| **D-3** | README §5 turn 11 / `feature_31` line 62: the credit note bubble "reduces BHA-2003 from ₹103,191 to ₹60,416" | `BHF-CN-2010` **prints no invoice reference at all** — the footer says only "the referenced invoice". Its single line (`Hex Bolts M10x40, box 100`, 25 @ 1,450) is **identical on BHA-2002 and BHA-2003**, and its date (17-Aug) equals BHA-2003's. | Resolution is by counterparty + line identity + date + open status, **not** by a printed reference. The expected bubble must name **why** it chose BHA-2003 over the identical BHA-2002 ("same date, and BHA-2002 is settled"), and `resolve_overlap()` must return *both* candidates with BHA-2003 ranked first. A bubble that silently picks one is a fail. |
| **D-4** | `feature_33` §3.4 forecast example: "₹4.4L still to be invoiced on PO-1041" | PO-VPI-1041 value 437,190 = RAJ-2008 total 437,190, fully invoiced and fully delivered (DC-RSC-0812). Same for PO-1042 (= GBP-2011) and PO-1043 (= SHR-2005). | The **`committed` forecast tier on VPI is ₹0.00**, on all three POs. Any non-zero committed line is a defect (most likely double-counting RAJ-2009). ₹4.4L is the PO *value*, not a balance. |
| **D-5** | *(new — not in any doc)* Outbound GST head | All 12 outbound invoices charge **CGST 9% + SGST 9%**, but every customer is outside Maharashtra: Kaveri (Bengaluru, KA), Sunrise (Ahmedabad, GJ), Deccan (Hyderabad, TS). Inter-state supply must carry **IGST 18%**. No customer GSTIN is printed either. | **₹800,541.00 of GST is charged under the wrong head on 12 inter-state invoices.** This is either a fixture defect for 33.38 to fix or the demo's best compliance finding — it must be one of them, decided by the founder, not left silent. Expected `card_compliance` behaviour stated in §5.6. |
| **D-6** | brief §B4: `auto_apply_credit_notes` evidence "6% of invoices" | 1 credit note against 14 inbound invoices = **7.14%** (9.09% against the 11 PDFs). | Evidence text is **1 credit note / 14 inbound invoices (7.1%)**, value **₹42,775.00**. Whether 7.1% trips the proposal threshold is **GT-dep** — the threshold has no default in the spec. |
| **D-7** | `feature_33` §4 `Fact.kind` vocabulary (six emitters) | None of `commitment · delivery_event · payment_event · terms · period_accounts · budget` describes a credit note. A credit note is a negative adjustment to a receivable/payable, not a commitment and not a payment. | Expected outcome for turn 11 is a bubble + a proposal and **zero `Fact` rows**. That is correct against the current spec and it is also a **gap**: the ledger cannot remember that a credit note ever arrived once the attachment TTL expires, so next quarter's "Bharat credits us ~7% of billings" is uncomputable. Raise as a new gap; do not invent a seventh kind here. |
| **D-8** | README §3 outbound note: the ₹200,000 Deccan advance "shows as an unmatched credit (no partial-payment support yet)" + `feature_33` §5 Option C | The statement narration names the invoice: `NEFT CR DECCAN MACHINERY LTD ADVANCE AGAINST VPI-OUT-2018`. Under Option C — "facts about records operations can already see flow down" — this **is** a payment fact on a visible invoice and must be `ops`, not `exec`. | Expected: one `payment_event` fact, subject `invoice VPI-OUT-2018`, `clearance="ops"`, ₹200,000, as_of 2026-08-25, `evidence.partial=true`. The *application* to the invoice balance stays unbuilt (Feature 31 cancelled) — the **fact** is still visible. Clearance and partial-payment support are two different questions and the README conflated them. |

---

## §1. Anchors

| anchor | value |
|---|---|
| Tenant | Vishwa Precision Industries Pvt Ltd (VPI), Pune, Maharashtra — Clerk org, single tenant |
| Currency | **INR only**. One currency ⇒ one runway, one P&L projection. No conversion anywhere (`§3.4` multi-currency ruling is exercised only negatively here: exactly one currency block, never a blended figure) |
| Tax regime | India GST, intra-state CGST 9% + SGST 9% on **all inbound**; outbound *should* be IGST 18% — see **D-5** |
| Fiscal year | **1-Apr-2026 → 31-Mar-2027 (FY 2026-27)**. All demo data is Jul–Sep 2026 = **Q2 FY27**. "This fiscal year" must never resolve to calendar 2026 |
| Currency symbol | **₹** on every rendered figure. A `$` or `€` on any VPI line is a fail |
| `as_of` for §9's SAGE questions | **2026-09-15 (Tuesday)** |

### Day calendar

| day | date | what happens |
|---|---|---|
| **Day 1** | Mon **7-Sep-2026** | Admin signup + provision; path choice; the 11 inbound PDFs uploaded; Discover fires on the **10th** extraction; routine questionnaire |
| **Day 2** | Tue **8-Sep-2026** | the 9 outbound PDFs, then the 6 image-format invoices; mark-paid on 5 invoices |
| **Day 3** | Wed **9-Sep-2026** | chat attachment turns **1 – 11**, turn 10 in a **private (`exec`) session** |
| **Day 4** | Thu **10-Sep-2026** | an Auditor logs in — clearance walkthrough |
| **Day 8** | Mon **14-Sep-2026, 06:00 UTC** | the **first real weekly run** (`ANALYST_WEEKLY_ENABLED`) |
| *(as_of)* | Tue **15-Sep-2026** | the §9 SAGE regression questions are asked here |
| **Day 30** | Tue **6-Oct-2026** | steady state — **ILL** |

Note on Day 1: the Monday weekly cron also fires on 7-Sep at 06:00 UTC, **before signup**. Expected: a no-op — zero tenants at or above `ANALYST_ONBOARD_MIN_DOCS`, zero `today_item` rows written, one log line. A weekly run that writes anything on Day 1 is a fail.

### Upload order matters — which document is the 10th

Step A uploads the 11 `inbound_*.pdf` files. In filename order (ASCII — uppercase `NEWVENDOR` sorts before `National`):

| # | file | doc |
|---|---|---|
| 1 | `inbound_Bharat_..._BHA-2002.pdf` | BHA-2002 |
| 2 | `inbound_Bharat_..._BHA-2003.pdf` | BHA-2003 |
| 3 | `inbound_NEWVENDOR_GaneshBearings_GBP-2011.pdf` | GBP-2011 |
| 4 | `inbound_National_MRO_Traders_NAT-2006.pdf` | NAT-2006 |
| 5 | `inbound_National_MRO_Traders_NAT-2007.pdf` | NAT-2007 |
| 6 | `inbound_Om_Stationery_Mart_OM -2000.pdf` | OM -2000 |
| 7 | `inbound_Om_Stationery_Mart_OM -2001.pdf` | OM -2001 |
| 8 | `inbound_Rajesh_Steel_Corporation_RAJ-2008.pdf` | RAJ-2008 |
| 9 | `inbound_Rajesh_Steel_Corporation_RAJ-2009.pdf` | RAJ-2009 |
| **10** | `inbound_Shree_Packaging_Industries_SHR-2004.pdf` | **SHR-2004 ← Discover fires here** |
| 11 | `inbound_Shree_Packaging_Industries_SHR-2005.pdf` | SHR-2005 (arrives *after* Discover) |

**Consequence, and it is load-bearing:** the Day-1 profile is built from **10 invoices, not 11**. SHR-2005 (₹121,894) is absent from every Day-1 figure. If the eval expects 11-invoice Day-1 totals it is expecting the wrong thing. (`GT` — if the demo is ever run with a different upload order, this whole section is recomputed, and the eval fixture must pin the order.)

---

## §2. The arithmetic base — recomputed from the files (all **GT**)

### 2.1 Inbound (11 tax invoices, `invoices_pdf/`)

| doc | vendor | date | due | subtotal | CGST 9% | SGST 9% | total |
|---|---|---|---|---|---|---|---|
| BHA-2002 | Bharat Hardware & Fasteners | 09-Jul | 08-Aug | 87,450.00 | 7,870.50 | 7,870.50 | **103,191.00** |
| BHA-2003 | Bharat Hardware & Fasteners | 17-Aug | 15-Sep | 87,450.00 | 7,870.50 | 7,870.50 | **103,191.00** |
| GBP-2011 | Ganesh Bearings Pvt Ltd | 19-Aug | 18-Sep | 58,200.00 | 5,238.00 | 5,238.00 | **68,676.00** |
| NAT-2006 | National MRO Traders | 19-Aug | 15-Sep | 67,760.00 | 6,098.40 | 6,098.40 | **79,956.80** |
| NAT-2007 | National MRO Traders | 19-Aug | 15-Sep | 67,760.00 | 6,098.40 | 6,098.40 | **79,956.80** (dup of 2006) |
| OM -2000 | Om Stationery Mart | 09-Jul | 08-Aug | 35,300.00 | 3,177.00 | 3,177.00 | **41,654.00** |
| OM -2001 | Om Stationery Mart | 16-Aug | 15-Sep | 35,300.00 | 3,177.00 | 3,177.00 | **41,654.00** |
| RAJ-2008 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 370,500.00 | 33,345.00 | 33,345.00 | **437,190.00** |
| RAJ-2009 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 370,500.00 | 33,345.00 | 33,345.00 | **437,190.00** (dup of 2008) |
| SHR-2004 | Shree Packaging Industries | 09-Jul | 08-Aug | 103,300.00 | 9,297.00 | 9,297.00 | **121,894.00** |
| SHR-2005 | Shree Packaging Industries | 18-Aug | 15-Sep | 103,300.00 | 9,297.00 | 9,297.00 | **121,894.00** |

Every line verified: `qty × rate = amount`, `Σ amount = subtotal`, `subtotal × 0.09 = CGST = SGST`, `subtotal + CGST + SGST = total`. **All 11 inbound invoices are arithmetically clean.** Any inbound line-math alert is a false positive.

Sum, as uploaded: `206,382.00 (Bharat×2) + 68,676.00 + 159,913.60 (National×2) + 83,308.00 (Om×2) + 874,380.00 (Rajesh×2) + 243,788.00 (Shree×2) = **1,636,447.60**`

### 2.2 Credit note (a chat attachment only — never an `Invoice` row)

`BHF-CN-2010`, Bharat Hardware, **17-Aug-2026**, one line `Hex Bolts M10x40, box 100` 25 @ 1,450 = **−36,250.00**; CGST −3,262.50, SGST −3,262.50; **total −42,775.00**. No invoice reference printed (**D-3**). Net against BHA-2003: `103,191.00 − 42,775.00 = **60,416.00**`.

### 2.3 Image-format invoices (`invoices_other_formats/`, from `make_image_invoices.py`)

| file / doc | party | date | due | subtotal | GST (9+9) | total |
|---|---|---|---|---|---|---|
| OM -2002 (PNG) | Om Stationery Mart | 26-Aug | 25-Sep | 24,400.00 | 2,196.00 ×2 | **28,792.00** |
| GBP-2012 (JPG, scanned) | Ganesh Bearings | 28-Aug | 27-Sep | 87,600.00 | 7,884.00 ×2 | **103,368.00** |
| SHR-2006 (TIFF) | Shree Packaging | 29-Aug | 28-Sep | 104,000.00 | 9,360.00 ×2 | **122,720.00** |
| VPI-OUT-2021 (PNG) | Kaveri Auto | 27-Aug | 26-Sep | 215,000.00 | 19,350.00 ×2 | **253,700.00** |
| VPI-OUT-2022 (WEBP) | Sunrise Engineering | 28-Aug | 27-Sep | 274,500.00 | 24,705.00 ×2 | **323,910.00** |
| VPI-OUT-2023 (BMP) | Deccan Machinery | 30-Aug | 29-Sep | 189,200.00 | 17,028.00 ×2 | **223,256.00** |

Inbound images 28,792.00 + 103,368.00 + 122,720.00 = **254,880.00**. Outbound images 253,700.00 + 323,910.00 + 223,256.00 = **800,866.00**.

### 2.4 Outbound (9 PDFs + 3 images = 12)

| doc | customer | date | due | subtotal | GST ×2 | printed total |
|---|---|---|---|---|---|---|
| VPI-OUT-2012 | Kaveri Auto | 14-Jul | 10-Aug | 409,500.00 | 36,855.00 | 483,210.00 (received 09-Aug) |
| VPI-OUT-2013 | Kaveri Auto | 18-Aug | 17-Sep | 409,500.00 | 36,855.00 | 483,210.00 |
| VPI-OUT-2014 | Kaveri Auto | 19-Aug | 17-Sep | 409,500.00 | 36,855.00 | **483,850.00 ← +640.00 error** |
| VPI-OUT-2015 | Sunrise Engineering | 14-Jul | 10-Aug | 436,250.00 | 39,262.50 | 514,775.00 (received 11-Aug) |
| VPI-OUT-2016 | Sunrise Engineering | 18-Aug | 17-Sep | 436,250.00 | 39,262.50 | 514,775.00 |
| VPI-OUT-2017 | Sunrise Engineering | 19-Aug | 17-Sep | 436,250.00 | 39,262.50 | 514,775.00 |
| VPI-OUT-2018 | Deccan Machinery | 17-Aug | 17-Sep | 410,500.00 | 36,945.00 | 484,390.00 (₹200,000 advance 25-Aug) |
| VPI-OUT-2019 | Deccan Machinery | 18-Aug | 17-Sep | 410,500.00 | 36,945.00 | 484,390.00 |
| VPI-OUT-2020 | Deccan Machinery | 19-Aug | 17-Sep | 410,500.00 | 36,945.00 | 484,390.00 |

VPI-OUT-2014: `409,500.00 + 36,855.00 + 36,855.00 = 483,210.00` vs printed `483,850.00` ⇒ **+640.00**. This is the Gap 220 probe: an outbound invoice whose line math does not reach its printed total.

Outbound totals: Kaveri 1,450,270.00 · Sunrise 1,544,325.00 · Deccan 1,453,170.00 = **4,447,765.00** printed; + images 800,866.00 = **5,248,631.00**.
Cross-check against subtotals: `Σ subtotals 4,447,450.00 + Σ GST 800,541.00 = 5,247,991.00`, and `5,248,631.00 − 5,247,991.00 = 640.00` — the single planted error, and nothing else. **Total outbound GST charged = ₹800,541.00** (the exposure figure in **D-5**).

### 2.5 Bank statement `BankStatement_HDFC_4471_Aug2026.pdf` (01-Aug → 31-Aug-2026)

| date | narration | Dr | Cr | balance |
|---|---|---|---|---|
| 01-Aug | OPENING BALANCE | | | 1,250,000.00 |
| 03-Aug | GST PAYMENT JUL-26 | 184,320.00 | | 1,065,680.00 |
| 05-Aug | OM STATIONERY MART INV OM -2000, UTR HDFCN26080512345 | 41,654.00 | | 1,024,026.00 |
| 06-Aug | BHARAT HARDWARE INV BHA-2002, UTR HDFCN26080612346 | 103,191.00 | | 920,835.00 |
| 07-Aug | SHREE PACKAGING INV SHR-2004, UTR HDFCN26080712347 | 121,894.00 | | 798,941.00 |
| 09-Aug | KAVERI AUTO VPI-OUT-2012 | | 483,210.00 | 1,282,151.00 |
| 11-Aug | SUNRISE ENGINEERING VPI-OUT-2015 | | 514,775.00 | 1,796,926.00 |
| 12-Aug | MSEDCL ELECTRICITY AUG-26 | 96,410.00 | | 1,700,516.00 |
| 14-Aug | SALARY AUG-26 BATCH 1 (42 EMPLOYEES) | 1,486,000.00 | | 214,516.00 |
| 20-Aug | TECHSOL SERVICES ANNUAL AMC 2026-27 | 58,000.00 | | 156,516.00 |
| 25-Aug | DECCAN MACHINERY ADVANCE AGAINST VPI-OUT-2018 | | 200,000.00 | 356,516.00 |
| 31-Aug | BANK CHARGES NEFT/RTGS AUG-26 INCL GST | 1,180.00 | | **355,336.00** |

`1,250,000.00 − 2,092,649.00 + 1,197,985.00 = 355,336.00` ✓. Withdrawals and deposits each re-added and agree with the printed totals. `balance_on_date` fact = **355,336.00 as of 2026-08-31**.

### 2.6 Purchase orders and challans

| doc | counterparty | date | value / quantities | resolves to |
|---|---|---|---|---|
| PO-VPI-1041 | Rajesh Steel | 05-Aug, deliver 20-Aug, Net 30 | 370,500 + 33,345 ×2 = **437,190.00** | RAJ-2008 exactly; DC-RSC-0812 |
| PO-VPI-1042 | Ganesh Bearings | 08-Aug, deliver 20-Aug, Net 30 (new vendor) | 58,200 + 5,238 ×2 = **68,676.00** | GBP-2011 exactly |
| PO-VPI-1043 | Shree Packaging | 06-Aug, deliver 18-Aug, Net 30 | 103,300 + 9,297 ×2 = **121,894.00** | SHR-2005 exactly |
| DC-RSC-0812 | Rajesh Steel | 20-Aug, against **PO-VPI-1041** | 6 / 6 coil, 30 / 30 bar | RAJ-2008 — no shortage |
| DC-NMT-2291 | National MRO | 19-Aug, against **PO-VPI-1039** *(not on file)* | 5/5, 12/12, 8/8 | NAT-2006 — no shortage |
| DC-BHF-0455 | Bharat Hardware | 17-Aug, against **PO-VPI-1040** *(not on file)* | 25/25, 15/15, 4/4 | BHA-2003 — no shortage |

**All three POs are fully invoiced ⇒ committed balance ₹0.00 each (D-4).** **Two POs are referenced and absent** (PO-VPI-1039, PO-VPI-1040) — named evidence for the `purchase_orders` input request. **There is no short delivery anywhere in the demo data**, so a `repeat_short_delivery` or `partial_delivery_balance` finding is a false positive.

### 2.7 Payment behaviour (**GT**, the only payment evidence that exists)

| we paid | invoice date | paid | days | source |
|---|---|---|---|---|
| Om Stationery (OM -2000) | 09-Jul | 05-Aug (Wed) | **27** | PA-VPI-0071 + statement 05-Aug |
| Bharat Hardware (BHA-2002) | 09-Jul | 06-Aug (Thu) | **28** | PA-VPI-0072 + statement 06-Aug |
| Shree Packaging (SHR-2004) | 09-Jul | 07-Aug (Fri) | **29** | PA-VPI-0073 + statement 07-Aug |

Median days-to-pay = **28**; median payment **day-of-month = 6**; the three cleared on three consecutive days in the first week of the month. No Rajesh, Ganesh or National MRO payment exists (**D-1**).

| they paid us | invoice date | due | received | days from issue | vs due |
|---|---|---|---|---|---|
| Kaveri (VPI-OUT-2012) | 14-Jul | 10-Aug | 09-Aug | **26** | 1 day early |
| Sunrise (VPI-OUT-2015) | 14-Jul | 10-Aug | 11-Aug | **28** | 1 day late |
| Deccan (VPI-OUT-2018) | 17-Aug | 17-Sep | 25-Aug, **partial ₹200,000 of 484,390 (41.3%)** | 8 | advance |

**Deccan is the slowest/weakest payer by exposure, not by days:** 3 unpaid PDF invoices (₹1,453,170.00) + VPI-OUT-2023 (₹223,256.00) = **₹1,676,426.00** billed, less the ₹200,000 advance = **₹1,476,426.00** net exposure, and the only customer with no completed settlement. That is the evidence sentence for the Day-1/Day-8 top-ranked receivable line.

### 2.8 Coverage over `INPUT_KINDS` (**GT**, restated per day in §3/§5/§7)

| kind | present on Day 3 end | depth | evidence |
|---|---|---|---|
| `invoices_in` | **yes** | Jul + Aug 2026 = 2 months | 14 inbound |
| `invoices_out` | **yes** | Jul + Aug 2026 = 2 months | 12 outbound |
| `purchase_orders` | **partial** | 1 month (Aug) | 3 on file, 2 referenced and absent |
| `delivery_notes` | **partial** | 1 month (Aug) | 3 on file |
| `bank_statements` | **yes, 1 month** | **Aug only** | stale 14 d at Day 8; Jun/Jul pending **33.38** |
| `remittances` | **partial** | 1 month | 3 outbound payment advices; **zero** customer remittances |
| `contracts` | **absent** | 0 | — |
| `period_accounts` | **absent** | 0 | — |
| `tax_returns` | **absent** | 0 | — |
| `loan_schedules` | **absent** | 0 | **and must not be requested** — no loan or EMI line appears on the statement, so nothing justifies the ask. An `InputRequest` for `loan_schedules` on VPI is a fail (it is the "ask for everything" failure mode `unlock_value()` exists to prevent) |
| `budgets` | **absent** | 0 | — |

---

## §3. Day 1 — Mon 7-Sep-2026

### 3.1 Before the 10th extraction — `pre_onboarding` (task 33.37)

Admin signs up, `POST /auth/provision` creates the tenant, the Admin lands on `/today`.

Expected `GET /today` from 0 documents through the 9th extraction:

```
{ "state": "pre_onboarding", "docs_seen": N, "docs_required": 10 }
```

with `N` ∈ 0…9 and **nothing else**: zero findings, zero FP&A lines, zero input requests, zero convention proposals, zero action proposals. The surface renders "upload to begin", the `N / 10` progress, the inbox address, a drop zone. Expected bubbles: **none** (no attachment turns yet).

`expected_behavior_type: exact_value` — the state string and the two counters. A single finding before the 10th extraction is a fail (33.24's asserted "a login before the threshold triggers nothing").

### 3.2 Path choice and the routine questionnaire (tasks 33.28 – 33.31)

Path taken in this script: **"Ingest documents first"** ⇒ the questionnaire fires **immediately after the first Discover completes**, not at login. (Setup path is the other branch: questionnaire at first login, Discover later at the 10th extraction; both branches are separately expected and separately tested.)

One question per `GET /today/questionnaire` call, in order. Chip **or** free text; every question skippable; a skip is recorded as skipped.

| # | key | question | chips | VPI owner's answer | free text |
|---|---|---|---|---|---|
| 1 | `payment_run` | When do you pay vendors? | `weekly_run` · `on_due_date` · `month_end` · `when_cash_allows` | **`month_end`** | — |
| 2 | `po_before_invoice` | Do you raise a PO before the invoice arrives? | `always` · `materials_only` · `rarely` | **`materials_only`** | — |
| 3 | `invoice_approval` | Who approves an invoice? | `owner_only` · `accounts_then_owner_above_threshold` · `accounts_alone` | **`accounts_then_owner_above_threshold`** | — |
| 4 | `month_close_day` | Which day do you close the month? | free | — | **7** |
| 5 | `collections_owner` | Who chases overdue receivables? | free / picker | — | **"Priya Kulkarni, Accounts"** |

`month_end` is chosen deliberately: it is **contradicted by the data** (§2.7 — the three settled payments cleared on 5, 6 and 7 August, day-of-month 6), so it is the Day-8 re-ask probe for task 33.31. Expected store per answer: **one `TenantChatRule` row**, `source="atlas_onboarding"`, `category` = the key, no new table.

**Expected downstream Today effects (task 33.30) — all deterministic:**

| answer | effect on Today | figure at Day 8 (**GT**) |
|---|---|---|
| `payment_run = month_end` | payables `TodayItem`s grouped under one month-end payment-run header | the 15-Sep group, ₹783,885.80 — and the group date **contradicts** the five invoices' own 15-Sep due dates, which is the finding |
| `po_before_invoice = materials_only` | one line per **materials** invoice with no resolved PO | **3 open materials invoices**: BHA-2003 103,191.00, GBP-2012 103,368.00, SHR-2006 122,720.00 = **329,279.00**. *(Materials = fasteners/steel/bearings/packaging: Bharat, Rajesh, Ganesh, Shree. Non-materials = Om stationery, National MRO consumables.)* **Open question, flag to founder:** whether settled materials invoices (BHA-2002, SHR-2004) also get a line. This document expects **open only** — 3 lines, not 5 |
| `invoice_approval = accounts_then_owner_above_threshold` | a "pending sign-off" line per open invoice above the threshold | **GT-dep** — the threshold has no default (brief §D open question 2). At an illustrative ₹100,000: 5 open clean payables above it — BHA-2003 103,191.00 + RAJ-2008 437,190.00 + SHR-2005 121,894.00 + GBP-2012 103,368.00 + SHR-2006 122,720.00 = **888,363.00** |
| `month_close_day = 7` | a month-close countdown line | at as_of 15-Sep: "month close for September is in **22 days** (7-Oct)"; at Day 8 (14-Sep): **23 days** |
| `collections_owner = "Priya Kulkarni, Accounts"` | overdue-receivable lines addressed to her | at Day 8 and as_of 15-Sep there are **no overdue receivables**, so **zero addressed lines** — and that is the expected value. Addressing text appearing with no overdue receivable is a fail |

### 3.3 Discover at the 10th extraction — the expected `BusinessProfile`

Built from **10 inbound invoices** (§1, SHR-2005 excluded). All **GT**.

| profile field | expected content |
|---|---|
| Document types seen | `INVOICE` (inbound) × 10. One type only |
| Flow directions | inbound only |
| Vendor clusters | **6**: Bharat Hardware & Fasteners · Ganesh Bearings Pvt Ltd · National MRO Traders · Om Stationery Mart · Rajesh Steel Corporation · Shree Packaging Industries. **Zero customers** (no outbound yet) |
| Currencies | **INR only** |
| Tax regime | India GST, intra-state CGST 9% + SGST 9% on 10 / 10; supplier GSTINs all `27…` (Maharashtra); buyer GSTIN `27AAFCV1234M1Z5` on 10 / 10 |
| Fields consistently present | doc number, date, due date, vendor name, vendor GSTIN, buyer GSTIN, HSN per line, qty, rate, amount, subtotal, CGST, SGST, total — **100 %** |
| Fields consistently absent | PO reference on the invoice face (0 / 10), payment terms text (0 / 10), bank details (0 / 10) |
| Payment habits | **unknown — no payment fact exists on Day 1.** Median days-to-pay is `NOT_CHECKED("needs bank_statements or remittances")`. This is the **D-1** correction: no `default_terms` proposal is possible today |
| Document chains observed | invoice only. PO → delivery → invoice → payment coverage = **0 / 10 on every leg** |
| Duplicate signal | **2 exact pairs** — NAT-2006/NAT-2007 and RAJ-2008/RAJ-2009, identical vendor + date + due + line set + total, differing only in doc number |
| Spend, as extracted | 1,636,447.60 − 121,894.00 (SHR-2005 absent) = **1,514,553.60** |
| Spend, duplicates excluded | 1,514,553.60 − 79,956.80 − 437,190.00 = **997,406.80** |
| Open payables (nothing marked paid yet) | **997,406.80** clean, across 8 invoices |
| Overdue at 7-Sep | **3**: BHA-2002, OM -2000, SHR-2004, all due 08-Aug ⇒ **30 days overdue**, ₹266,739.00 *(103,191.00 + 41,654.00 + 121,894.00)*. The system does not yet know they were paid on the August statement — that is Day 2/3 |
| `coverage_for()` | `invoices_in` present (2 months: Jul, Aug); everything else in §2.8 **absent** |

Re-run stability: a second Discover over the same 10 rows must return a byte-identical profile (33.22).

**The 11th extraction (SHR-2005) must NOT re-trigger Discover:** same vendor, same doc type, same currency, same flow ⇒ not a material coverage change. Plus the 1-hour debounce (33.33). Expected: zero second Discover run, one suppression log line.

### 3.4 Day 1 Today — expected lines in rank order

Ranking rule: **severity first, then amount** (Gap 519 — severity comes from the card, never inferred from the presence of a number).

| rank | kind | line (figure) | why it ranks here |
|---|---|---|---|
| **1** | finding, `high` | **RAJ-2009 duplicates RAJ-2008 — ₹437,190.00 at risk of double payment** | "Highest single exposure on the board: an exact duplicate of your largest invoice, same vendor, same date, same two lines, and both are unpaid." |
| **2** | finding, `high` | **NAT-2007 duplicates NAT-2006 — ₹79,956.80 at risk** | "Same defect, one fifth the amount; severity is equal, amount ranks it second." |
| **3** | finding, `medium` | **3 payables are 30 days past due — ₹266,739.00** (SHR-2004 121,894.00 · BHA-2002 103,191.00 · OM -2000 41,654.00, all due 08-Aug) | "Oldest money on the board and no payment evidence on file; ranked below the duplicates because paying late costs goodwill, paying twice costs cash." |
| **4** | convention proposal | **Duplicate handling** — "Block payment on an invoice matching an existing one on vendor + date + total + line set, and require an override?" Evidence: 2 pairs, **₹517,146.80**. Target store: `TenantChatRule` (`source="atlas"`) | "Ranked by the same `unlock_value()` as the findings: ₹517,146.80 — the largest number on this screen, and a decision, not a task." |
| **5** | input request | **Bank statement** — "Attach your August bank statement. It would confirm settlement on **₹997,406.80** of open payables and is the only thing standing between you and a cash runway." | "Nothing on this screen about cash is computable without it; `unlock_value` ₹997,406.80." |
| **6** | input request | **Purchase orders** — "Attach the POs behind these invoices. **8 invoices / ₹997,406.80** currently have no order to check against, so I cannot tell you whether you were billed what you agreed." | "Second-largest unlock; it turns 8 invoices from unverifiable to three-way-matchable." |
| **7** | action proposal (Admin) | **Set up the inbound email address for invoice ingest** — "10 documents arrived by hand today. Turn on the ingest address and they arrive themselves." `Confirm` | "Not a finding — the one thing on this screen that removes work rather than adding it." |
| **8** | input request | **Contracts / terms** — "No payment terms are printed on any of your 10 invoices. Attach a vendor contract or agreement and I can check terms adherence across **₹997,406.80** with 6 vendors." | "Ranked below the POs: it unlocks judgement, not verification." |
| **9** | input request | **Last quarter's P&L (`period_accounts`)** — "Attach your Q1 FY 2026-27 (Apr–Jun) P&L and the margin, expense-trend and P&L-projection cards start working. Today they are all `NOT_CHECKED`." | "First FP&A ask; ranked after the operational asks because nothing on Today depends on it yet." |
| **10** | input request | **This year's budget (`budgets`)** — "Attach your FY 2026-27 budget and I can show variance per account." | "Lowest unlock of the asks that are justified at all." |
| **11** | input request | **GST returns (`tax_returns`)** — "Attach GSTR-2B for August and I can reconcile **₹168,931.80** of input credit against what your vendors filed." *(the ₹168,931.80 is the full-set August figure, §9 Q7; at Discover only the 10-doc subset exists — see the note below)* | "Named last because the return period is not closed yet." |

**Notes on rank 11.** At Discover the August GST on the 10-invoice subset is `15,741.00 (BHA-2003) + 10,476.00 (GBP-2011) + 12,196.80 (NAT-2006) + 6,354.00 (OM -2001) + 66,690.00 (RAJ-2008) = **111,457.80** clean` (NAT-2007 and RAJ-2009 excluded, SHR-2005 not yet uploaded). The ₹168,931.80 figure belongs to the full set and is the right expected value from Day 2 onward.

**Explicitly NOT expected on Day 1** (each of these appearing is a fail):

| must not appear | why |
|---|---|
| `default_terms` proposal | no payment fact exists yet (**D-1**) |
| `auto_apply_credit_notes` proposal | no credit note has been seen — it arrives as attachment turn 11 on Day 3 |
| `treat_proformas_as_commitments` proposal | **zero** proforma invoices in the entire demo set |
| any `committed` forecast line | no PO on file yet; and from Day 3 the committed balance is ₹0.00 anyway (**D-4**) |
| any `recurring` or `estimated` forecast line | depth 0 statements. Both are `NOT_CHECKED("needs bank_statements")` |
| a cash runway figure | no `balance_on_date` fact |
| any receivable line, any customer name | zero outbound documents on Day 1 |
| an `InputRequest` for `loan_schedules` | nothing justifies it (§2.8) |
| any `$` or `€` symbol | INR tenant (Gap 225) |

**FP&A cards on Day 1 — the "never an empty tile" contract.** All five render, all `NOT_CHECKED`, each with exactly one input request attached and a named reason:

| capability | state | reason text | attached request |
|---|---|---|---|
| `pnl_by_period` | `NOT_CHECKED` | "no periodised accounts on file" | P&L (rank 9) |
| `margin_per_customer` | `NOT_CHECKED` | "no outbound invoices on file" | *(resolved on Day 2)* |
| `margin_per_item` | `NOT_CHECKED` | "no outbound invoices on file" | *(see §7.5 — still `NOT_CHECKED` on Day 8 for a different reason)* |
| `budget_variance_per_account` | `NOT_CHECKED` | "no budget and no periodised accounts on file" | budget (rank 10) |
| `expense_category_trend` | `NOT_CHECKED` | "no periodised accounts on file" | P&L (rank 9) |

---

## §4. Day 2 — Tue 8-Sep-2026: outbound, image formats, mark paid

### 4.1 Uploads

9 outbound PDFs, then the 6 image-format invoices (3 inbound + 3 outbound: PNG, JPG-scanned, TIFF, WEBP, BMP). Running extraction count: 11 + 9 + 6 = **26**.

### 4.2 Discover re-trigger — expected exactly once

The outbound batch is a **material coverage change** on three axes at once: a new flow direction (outbound), a new counterparty cluster kind (3 customers), and new source formats. Expected: **one** Discover re-run. The image batch arriving inside the same hour is **suppressed by the 1-hour debounce** (33.33) and logged, never queued for later. Two Discover runs on Day 2 is a fail; zero is also a fail.

### 4.3 Profile delta after the re-run (**GT**)

| field | Day 1 | Day 2 |
|---|---|---|
| Doc types | INVOICE inbound | INVOICE inbound + outbound |
| Vendors | 6 | 6 |
| Customers | 0 | **3** — Kaveri Auto Components Pvt Ltd (Bengaluru, KA) · Sunrise Engineering Works (Ahmedabad, GJ) · Deccan Machinery Ltd (Hyderabad, TS) |
| Inbound total, as uploaded | 1,514,553.60 | **1,891,327.60** (14 invoices) |
| Inbound clean | 997,406.80 | **1,374,180.80** (12 invoices) |
| Outbound total | — | **5,248,631.00** (12 invoices, as printed) |
| Fields consistently absent | *(as §3.3)* | **+ customer GSTIN missing on 12 / 12 outbound invoices** |
| New tax observation | — | **12 / 12 outbound invoices charge CGST+SGST to out-of-state customers** (**D-5**, ₹800,541.00) |
| Line-math signal | inbound 11 / 11 clean | **VPI-OUT-2014: lines + tax 483,210.00 vs printed 483,850.00, +640.00** |

### 4.4 Mark paid via the audit console

BHA-2002, OM -2000, SHR-2004 (payables) and VPI-OUT-2012, VPI-OUT-2015 (receivables).

Expected Today lifecycle: the **rank-3 overdue-payables line from Day 1 clears** — `cleared_at` set, gone from the next `GET /today`. It clears because the finding resolved, not because anyone dismissed it, so **nothing feeds `learn()`** and the kind is **not** counted toward `ANALYST_SUPPRESS_AFTER`. A dismissal counter that moves here is a fail.

Post-mark-paid open positions (**GT**, and the baseline for every later figure):

- Open clean payables = 1,374,180.80 − (103,191.00 + 41,654.00 + 121,894.00) = **1,107,441.80** across 9 invoices
- Open receivables = 5,248,631.00 − (483,210.00 + 514,775.00) = **4,250,646.00** across 10 invoices
- Of which arithmetically correct = 4,250,646.00 − 640.00 = **4,250,006.00** (VPI-OUT-2014 corrected)
- Net of the unapplied Deccan advance = 4,250,646.00 − 200,000.00 = **4,050,646.00**

### 4.5 New Day-2 Today lines (added above the ranks that survive from Day 1)

| rank | kind | line | why it ranks here |
|---|---|---|---|
| **1** | finding, `high` | **VPI-OUT-2014's total does not add up — lines + tax ₹483,210.00 against a printed ₹483,850.00, ₹640.00 over** | "It is a receivable you issued: the customer will pay the printed figure or dispute it, and either way your books are ₹640.00 out. Small money, certain defect — severity, not amount, puts it first." |
| **2** | finding, `high` | *(carried)* RAJ-2009 duplicates RAJ-2008 — ₹437,190.00 | as Day 1 |
| **3** | finding, `high` | **12 outbound invoices charge CGST+SGST on inter-state supplies — ₹800,541.00 of GST under the wrong head** (**D-5**) | "Every customer is outside Maharashtra; inter-state supply carries IGST 18%. This is the largest compliance exposure on the board and it repeats on every invoice you issue." |
| **4** | finding, `high` | *(carried)* NAT-2007 duplicates NAT-2006 — ₹79,956.80 | as Day 1 |
| **5** | finding, `medium` | **No customer GSTIN on 12 / 12 outbound invoices** | "Your customers cannot claim input credit against an invoice with no GSTIN on it; it is also what makes the head above impossible to verify automatically." |
| **6** | finding, `medium` | **Deccan Machinery: ₹1,676,426.00 billed, ₹200,000.00 received as an unapplied advance, no completed settlement** | "Your largest receivable concentration sits with the only customer who has never paid an invoice in full — 4 open invoices, ₹1,476,426.00 net of the advance." |
| 7+ | proposals / input requests | *(carried from Day 1, re-ranked — the bank-statement request's unlock rises, see below)* | |

Bank-statement input request, re-quantified at Day 2 (**GT**): confirming settlement now covers open payables ₹1,107,441.80 **+** open receivables ₹4,250,646.00 = **₹5,358,087.80** of unconfirmed cash movement. It becomes rank 1 among the input requests and stays there.

`margin_per_customer` flips from `NOT_CHECKED("no outbound invoices")` — both sides are now present. `margin_per_item` does **not** (§7.5).

---

## §5. Day 3 — Wed 9-Sep-2026: attachment turns 1 – 11

Contract for every turn: **no `Invoice` row is written and no aggregate moves** (Feature 26 D2/D3, unrevoked). What each turn leaves behind is **facts** (§4 of the spec) — that is the new, testable half.

Turns 1–9 and 11 are attached in the Admin's **normal (`ops`) session**. **Turn 10 is attached in a private (`exec`) session.**

### 5.1 Turns 1 – 3 — purchase orders

| # | attach | ask | expected bubble | expected facts |
|---|---|---|---|---|
| 1 | `PO_PO-VPI-1041_RAJ.pdf` | "Does this PO match the Rajesh Steel invoice?" | `card_agreed_vs_billed` **PASS**: resolves to RAJ-2008; 2 / 2 lines match qty and rate (6 @ 48,500 · 30 @ 2,650); PO value ₹437,190.00 = invoice total, variance **₹0.00 / 0.0 %**. Second claim: **RAJ-2009 is a second invoice against the same PO** — ₹437,190.00, taking PO-1041 to 200 % invoiced | `commitment` · subject `po:PO-VPI-1041` · counterparty Rajesh · as_of **2026-08-05** · `{INR: subtotal 370500.00, tax 66690.00, total 437190.00, lines 2}`<br>`terms` · subject `vendor:Rajesh` · as_of 2026-08-05 · `{payment_terms: "Net 30"}` |
| 2 | `PO_PO-VPI-1042_GBP.pdf` | "Is the Ganesh Bearings invoice within this PO?" | **New vendor ⇒ first-link confirmation asked before any claim**, then `card_agreed_vs_billed` **PASS**: GBP-2011, 60 @ 520 and 25 @ 1,080, ₹68,676.00 = ₹68,676.00, variance ₹0.00 | `commitment` · `po:PO-VPI-1042` · Ganesh · as_of **2026-08-08** · total 68,676.00, lines 2<br>`terms` · `vendor:Ganesh` · `{payment_terms: "Net 30", note: "new vendor"}` |
| 3 | `PO_PO-VPI-1043_SHR.pdf` | "Compare with Shree Packaging's August invoice" | `card_agreed_vs_billed` **PASS** against **SHR-2005** (18-Aug), 3 / 3 lines, ₹121,894.00 = ₹121,894.00. Second claim: **SHR-2004 is a different, already-paid July invoice with identical lines and total** — named so the user is not left wondering which one matched | `commitment` · `po:PO-VPI-1043` · Shree · as_of **2026-08-06** · total 121,894.00, lines 3<br>`terms` · `vendor:Shree` · `Net 30` |

Turn 3's second claim is the Gap 224 probe in bubble form: two candidate invoices are identical in every figure and differ only by date and paid status. Naming both, ranked, is the pass; picking one silently is the fail.

### 5.2 Turns 4 – 6 — delivery challans

| # | attach | ask | expected bubble | expected facts |
|---|---|---|---|---|
| 4 | `DC_DC-RSC-0812_RAJ.pdf` | "Was everything on this challan invoiced?" | `card_delivery_vs_order` **PASS**: 6 / 6 HR Steel Coil and 30 / 30 Steel Angle Bar, against **PO-VPI-1041** and **RAJ-2008**; three-way match **clean** (PO = delivery = invoice). Second claim: **RAJ-2009 has no challan of its own** ⇒ corroborates the duplicate | 2 × `delivery_event` · subject `po:PO-VPI-1041` (cross-ref `invoice:RAJ-2008`) · as_of **2026-08-20** · `{item: "HR Steel Coil 2mm", qty_ordered: 6, qty_delivered: 6}` and `{item: "Steel Angle Bar 2x2x1/4, 20ft", qty_ordered: 30, qty_delivered: 30}` |
| 5 | `DC_DC-NMT-2291_NAT.pdf` | "Check delivery against invoice" | `card_delivery_vs_order` **PASS** on quantities (5 / 5, 12 / 12, 8 / 8) = **NAT-2006**, **but** `NOT_CHECKED` on the order leg: the challan cites **PO-VPI-1039, which is not on file** — three-way match cannot be completed, and the card must say so rather than claim a clean match. Second claim: **NAT-2007 has no challan ⇒ duplicate** | 3 × `delivery_event` · subject `invoice:NAT-2006` · as_of **2026-08-19** · qty 5/5, 12/12, 8/8 · `evidence.po_ref = "PO-VPI-1039"` (unresolved) |
| 6 | `DC_DC-BHF-0455_BHA.pdf` | "Any short delivery here?" | `card_delivery_vs_order` **PASS**: 25 / 25, 15 / 15, 4 / 4 = **BHA-2003**; **no shortage**. Order leg `NOT_CHECKED` — **PO-VPI-1040 not on file** | 3 × `delivery_event` · `invoice:BHA-2003` · as_of **2026-08-17** · qty 25/25, 15/15, 4/4 · `evidence.po_ref = "PO-VPI-1040"` (unresolved) |

Across turns 4–6: **zero short deliveries**. A `repeat_short_delivery` or `partial_delivery_balance` finding on VPI is a false positive (§2.6). And the two unresolved PO references are the named evidence the `purchase_orders` input request must quote from Day 3 on — "PO-VPI-1039 and PO-VPI-1040 are cited on challans you have but are not on file".

### 5.3 Turns 7 – 9 — payment advices

| # | attach | ask | expected bubble | expected facts |
|---|---|---|---|---|
| 7 | `PA_PA-VPI-0071_OM.pdf` | "Which invoice does this payment settle?" | `card_payment_application`: **OM -2000**, ₹41,654.00 paid in full 05-Aug-2026, NEFT, UTR **HDFCN26080512345**, deduction ₹0.00. Second claim: **OM -2001 (₹41,654.00, same amount, 16-Aug) is still open** — explicitly not this payment | `payment_event` · `invoice:OM -2000` · counterparty Om · as_of **2026-08-05** · `{INR: 41654.00}` · `evidence {utr: "HDFCN26080512345", mode: "NEFT", advice: "PA-VPI-0071"}` · **clearance `ops`** |
| 8 | `PA_PA-VPI-0072_BHA.pdf` | "Is Bharat Hardware fully paid?" | `card_net_position`: BHA-2002 settled ₹103,191.00 (06-Aug, UTR HDFCN26080612346); **BHA-2003 open ₹103,191.00**; net owed to Bharat = **₹103,191.00** | `payment_event` · `invoice:BHA-2002` · as_of **2026-08-06** · 103,191.00 · UTR HDFCN26080612346 · `ops` |
| 9 | `PA_PA-VPI-0073_SHR.pdf` | "What do we still owe Shree Packaging?" | `card_net_position`: SHR-2004 paid ₹121,894.00 (07-Aug); **open = SHR-2005 ₹121,894.00 + SHR-2006 ₹122,720.00 = ₹244,614.00**. *(The README's older "SHR-2005 open 121,894" predates the image-format invoices; with SHR-2006 uploaded the correct net is ₹244,614.00.)* | `payment_event` · `invoice:SHR-2004` · as_of **2026-08-07** · 121,894.00 · UTR HDFCN26080712347 · `ops` |

Turns 7–9 are what make the **`default_terms` proposal** computable: three `payment_event` facts with explicit dates ⇒ days-to-pay 27 / 28 / 29, median **28** (**D-1**).

### 5.4 Turn 10 — the bank statement, attached in a **private (`exec`) session**

Ask: "Match this statement to our books."

Expected bubble (`card_bank_reconcile` + `card_cash_cover`), **visible only to `exec`**:

| claim | expected figure |
|---|---|
| Debits matched to payables | **3** — OM -2000 ₹41,654.00 (05-Aug), BHA-2002 ₹103,191.00 (06-Aug), SHR-2004 ₹121,894.00 (07-Aug); each within ±₹1 and ±5 days, each corroborating the UTR already on file from turns 7–9 |
| Credits matched to receivables | **2** — VPI-OUT-2012 ₹483,210.00 (09-Aug), VPI-OUT-2015 ₹514,775.00 (11-Aug) |
| Partial credit | **₹200,000.00 (25-Aug) against VPI-OUT-2018** — named by the narration. Reported as a **partial receipt of 41.3 %**, balance ₹284,390.00 still open. Application to the invoice balance is **not** performed (Feature 31 cancelled) and the bubble must say that plainly, not silently drop it (**D-8**) |
| Unmatched debits | GST ₹184,320.00 (03-Aug) · electricity ₹96,410.00 (12-Aug) · salary ₹1,486,000.00 (14-Aug) · AMC ₹58,000.00 (20-Aug) · bank charges ₹1,180.00 (31-Aug) = **₹1,825,910.00** |
| Balance | opening ₹1,250,000.00 · withdrawals ₹2,092,649.00 · deposits ₹1,197,985.00 · **closing ₹355,336.00 as of 31-Aug-2026** |
| Doc type | **`BANK_STATEMENT`** (not `STATEMENT_OF_ACCOUNT`) — BE Gap 516; only `BANK_STATEMENT` lands rows into the bank ledger |
| Cash cover | **`NOT_CHECKED("needs ≥3 months of statements")`** for the `recurring` tier; the `certain` runway is computable and is stated in §7.4 |

**Expected facts, with clearance (Option C, task 33.11) — the load-bearing table:**

| fact | subject | as_of | figures | clearance | note |
|---|---|---|---|---|---|
| `balance_on_date` | `account:HDFC ****4471` | 2026-08-31 | 355,336.00 | **`exec`** | the statement is the source row |
| `payment_event` | `invoice:OM -2000` | 2026-08-05 | 41,654.00 | **`ops`** | **must de-duplicate against turn 7 on the UTR** — one fact, not two |
| `payment_event` | `invoice:BHA-2002` | 2026-08-06 | 103,191.00 | **`ops`** | de-dup vs turn 8 on UTR |
| `payment_event` | `invoice:SHR-2004` | 2026-08-07 | 121,894.00 | **`ops`** | de-dup vs turn 9 on UTR |
| `payment_event` | `invoice:VPI-OUT-2012` | 2026-08-09 | 483,210.00 | **`ops`** | receipt |
| `payment_event` | `invoice:VPI-OUT-2015` | 2026-08-11 | 514,775.00 | **`ops`** | receipt |
| `payment_event` | `invoice:VPI-OUT-2018` | 2026-08-25 | 200,000.00, `partial: true` | **`ops`** | **D-8** — the narration names a visible invoice |
| `payment_event` | `account:…4471` (GST) | 2026-08-03 | 184,320.00 | **`exec`** | not about a record ops can see |
| `payment_event` | `account:…4471` (electricity) | 2026-08-12 | 96,410.00 | **`exec`** | |
| `payment_event` | `account:…4471` (salary, 42 employees) | 2026-08-14 | 1,486,000.00 | **`exec`** | |
| `payment_event` | `account:…4471` (AMC, TechSol, annual) | 2026-08-20 | 58,000.00 | **`exec`** | |
| `payment_event` | `account:…4471` (bank charges) | 2026-08-31 | 1,180.00 | **`exec`** | |

**Exactly 6 `ops` facts and 6 `exec` facts.** Double-counting any of the three vendor payments (once from the advice, once from the statement) is a fail; so is emitting the salary or loan-style lines as `ops`.

### 5.5 Turn 11 — the credit note `BHF-CN-2010` (ruling 7)

Ask: "Bharat sent this — what do we actually owe them?"

Expected bubble, `card_net_position`:

| claim | expected |
|---|---|
| Resolution | credit note **−₹42,775.00**, 17-Aug-2026, Bharat Hardware. **Two candidate invoices** carry the identical line (`Hex Bolts M10x40, box 100`, 25 @ 1,450): BHA-2002 and BHA-2003. Ranked: **BHA-2003 first** — same document date (17-Aug) and still open; **BHA-2002 second** — settled 06-Aug, before the note was raised. The bubble must **name both and say why** (**D-3**) |
| Net figure | **₹103,191.00 − ₹42,775.00 = ₹60,416.00** owed to Bharat on BHA-2003 |
| Tax detail | reversal of CGST ₹3,262.50 + SGST ₹3,262.50 on a taxable reversal of ₹36,250.00 — the credit note's own arithmetic is **internally correct** and must not raise a line-math alert (BE Gap 502: `SIGN_FLIPPED_DOC_TYPES`) |
| Aggregates | **unchanged.** No `Invoice` row, `total_invoiced` / `outstanding_amount` / `v_vendor_spend` all still show Bharat at ₹206,382.00 and BHA-2003 open at ₹103,191.00 (D2/D3) |
| Facts left behind | **none** — see **D-7**. Correct against the current six-emitter vocabulary, and a gap |

Expected **convention proposal** raised by this turn: **`auto_apply_credit_notes`** — "Credit notes arrive for **1 of your 14 inbound invoices (7.1 %)**. Apply them to the open invoice automatically? It would net **₹42,775.00** off what you owe Bharat Hardware today." Target store: **`TenantChatRule`**, `source="atlas"`. `unlock_value` = **₹42,775.00**. Whether 7.1 % clears the emission threshold is **GT-dep** (**D-6**).

Expected proposal **not** raised: `enable_partial_payments`. The evidence exists (₹200,000 Deccan advance) but Feature 31 is cancelled, so there is **no store to accept it into** — a proposal whose `/accept` has nowhere to write must not be offered. The ₹200,000 surfaces as the finding in §4.5 rank 6 instead. *(Flag to founder: confirm this is the intended behaviour rather than a silently dropped proposal.)*

### 5.6 The compliance card at attachment scope (**D-5**)

Any turn that resolves to an outbound invoice must have `card_compliance` return, for VPI: **`FAIL` — inter-state supply charged CGST+SGST on 12 invoices, ₹800,541.00 of GST under the wrong head; customer GSTIN absent on 12 / 12, so the place-of-supply cannot be verified from the document.** `PASS` on the outbound set is a fail of the check, not a pass of the demo.

---

## §6. Day 4 — Thu 10-Sep-2026: an Auditor logs in (clearance walkthrough)

Clearance is **by role**: every Admin holds `exec`; **Auditor and Trainer hold `ops`**.

### 6.1 What the Auditor (`ops`) may see

| may see | figure |
|---|---|
| All 14 inbound and 12 outbound invoices, unchanged | inbound 1,891,327.60 as uploaded / 1,374,180.80 clean; outbound 5,248,631.00 |
| The `ops` payment facts from turn 10 — **including the ones that only the private statement proved** | OM -2000 ₹41,654.00 (05-Aug) · BHA-2002 ₹103,191.00 (06-Aug) · SHR-2004 ₹121,894.00 (07-Aug) · VPI-OUT-2012 ₹483,210.00 (09-Aug) · VPI-OUT-2015 ₹514,775.00 (11-Aug) · VPI-OUT-2018 ₹200,000.00 partial (25-Aug) — **6 facts** |
| Every finding at `ops` clearance | the two duplicates, VPI-OUT-2014's ₹640.00, the IGST finding, the missing customer GSTINs, the Deccan concentration |
| The commitment / delivery / terms facts from turns 1–9 | all `ops` |

Asking SAGE "was BHA-2002 paid?" as the Auditor must answer **"yes — ₹103,191.00 on 06-Aug-2026, UTR HDFCN26080612346"**. That answer is derived from a document the Auditor may not open, and that is the point of Option C.

### 6.2 What the Auditor must **not** see

| must not see | figure |
|---|---|
| The `chat_attachments` row, the file, the stream, or the preview of `BankStatement_HDFC_4471_Aug2026.pdf` | — |
| The Admin's private session, its message list, or any message in it | — |
| `balance_on_date` | ₹355,336.00 |
| Salary | ₹1,486,000.00 (14-Aug) |
| GST payment | ₹184,320.00 (03-Aug) |
| Electricity | ₹96,410.00 (12-Aug) |
| AMC | ₹58,000.00 (20-Aug) |
| Bank charges | ₹1,180.00 (31-Aug) |
| Any cash-runway or cash-cover line, any statement-derived total (withdrawals ₹2,092,649.00, deposits ₹1,197,985.00) | — |
| The `{tenant}_exec` Chroma collection | — |

Expected `GET /today` as the Auditor: the `ops` findings only, **with the cash lines and the exec input requests absent — not blanked, absent.** A zero, a dash or "₹0" where a runway line would be is a **Gap 224 / Gap 221 failure**, not a redaction.

Also expected absent for a non-Admin: the questionnaire-derived lines (payment-run grouping, pending sign-off, month-close countdown, collections addressing) are Admin-facing. *(Flag: FE spec §7 Q4 — "Today for an Auditor" — is still open; this document expects Admin-only and must be revised if the founder rules otherwise.)*

### 6.3 A second Admin

A second Admin sees the first Admin's private session and the statement **in full**. This is accepted, ruled behaviour (§8 Q3), not a leak — and it is an assertion, not an omission.

---

## §7. Day 8 — Mon 14-Sep-2026, 06:00 UTC: the first weekly run

`as_of = 2026-09-14`. Nothing new has been ingested since Day 3.

### 7.1 Overdue position at 14-Sep (**GT**)

| | |
|---|---|
| Overdue payables | **none.** The five 15-Sep payables are due **tomorrow** |
| Overdue receivables | **none.** The seven 17-Sep receivables are due in 3 days |
| Due within 24 h (payables, clean) | BHA-2003 103,191.00 · NAT-2006 79,956.80 · OM -2001 41,654.00 · RAJ-2008 437,190.00 · SHR-2005 121,894.00 = **₹783,885.80** |
| Same, if the duplicates are paid too | + 79,956.80 + 437,190.00 = **₹1,301,032.60** |

### 7.2 The `certain` forecast, computed from due dates (**GT**)

Starting point: `balance_on_date` **₹355,336.00 at 31-Aug-2026** — depth 1 month, stale by 14 days.

| date | out | in | running balance |
|---|---|---|---|
| 31-Aug (known) | | | **355,336.00** |
| 15-Sep | 783,885.80 | | **−428,549.80** |
| 17-Sep | | 3,449,780.00 | 3,021,230.20 |
| 18-Sep | 68,676.00 | | 2,952,554.20 |
| 25-Sep | 28,792.00 | | 2,923,762.20 |
| 26-Sep | | 253,700.00 | 3,177,462.20 |
| 27-Sep | 103,368.00 | 323,910.00 | 3,398,004.20 |
| 28-Sep | 122,720.00 | | 3,275,284.20 |
| 29-Sep | | 223,256.00 | **3,498,540.20** |

Totals: certain out **₹1,107,441.80**, certain in **₹4,250,646.00**. 17-Sep inflow = 483,210 + 483,850 + 514,775 + 514,775 + 484,390 × 3 = **3,449,780.00**.

**The single most important line on Day 8: a ₹428,549.80 shortfall on 15-Sep**, two days before ₹3,449,780.00 lands. Every arithmetic step above is reproducible from §2; if ATLAS reports a different shortfall, the arithmetic is the reference.

### 7.3 Other tiers

| tier | expected | why |
|---|---|---|
| `certain` | as §7.2 | due dates on issued invoices |
| `committed` | **₹0.00** | PO-1041/1042/1043 are each fully invoiced (**D-4**). Two POs referenced by challans are absent, so the *unknown* commitment is an input request, not a number |
| `recurring` | **`NOT_CHECKED("needs 3 months of statements, have 1")`** | only the August statement exists; June/July pending **33.38** |
| `estimated` | **`NOT_CHECKED("needs N months, have 1")`** | same |
| P&L projection | **partially `NOT_CHECKED`** — revenue side computable from certain + committed receivables (₹4,250,646.00, of which ₹4,250,006.00 arithmetically correct); cost side missing `recurring` outflow and `expense_category_trend` ⇒ the projection renders with its cost leg `NOT_CHECKED` and the two input requests attached, **never as a number** | |

### 7.4 Day 8 Today — expected lines in rank order

| rank | kind | line (figure) | why it ranks here |
|---|---|---|---|
| **1** | forecast, `high` | **₹428,549.80 short on 15-Sep** — ₹783,885.80 of payables fall due tomorrow against a last-known balance of ₹355,336.00 (31-Aug, 14 days old). ₹3,449,780.00 arrives 17-Sep | "One day of warning on a cash shortfall outranks everything else on this screen; and the two days between the outflow and the inflow are the whole problem." |
| **2** | finding, `high` | **RAJ-2009 duplicates RAJ-2008 — ₹437,190.00, and it falls due tomorrow with the rest** | "Same duplicate as last week, now one day from the payment run: the exposure became a deadline." |
| **3** | action proposal, `high` (Auditor) | **Hold NAT-2007 and RAJ-2009 before tomorrow's run — ₹517,146.80** · `Confirm` | "The one thing on this screen that stops money leaving tomorrow; ranked with the findings it resolves." |
| **4** | finding, `high` | **VPI-OUT-2014's total is ₹640.00 over its own lines** | "Unchanged, unresolved, and the only defect in a receivable you issued." |
| **5** | finding, `high` | **₹800,541.00 of GST on 12 inter-state invoices is under the wrong head** (**D-5**) | "Largest compliance exposure; it repeats on every invoice you issue, so it gets worse by doing nothing." |
| **6** | input request, `high` | **September's bank statement** — "Your last statement ends 31-Aug, 14 days ago. September's would confirm **₹5,358,087.80** of movement (₹1,107,441.80 out, ₹4,250,646.00 in) and is what the shortfall above is guessing at." | "Rank 1 is only as good as a 14-day-old balance; this is the line that fixes rank 1." |
| **7** | contradiction re-ask (task 33.31) | **"You told me you pay vendors at month end. Your three settled invoices cleared on 5, 6 and 7 August — day 6 of the month. Shall I change it?"** | "I am about to group ₹783,885.80 of payables by a rule that your own payments contradict; asked once, with the evidence." |
| **8** | convention proposal | **`default_terms` NET 30** — "Om, Bharat and Shree were each paid at 27, 28 and 29 days; median **28**, and all three POs print Net 30. Set NET 30 as the default term?" Target: `ExtractionTemplate.rules`, vendor scope, `source="atlas"` | "First week it was computable — the payment advices arrived on Day 3. It sharpens the timing of ₹783,885.80 of outflow." |
| **9** | convention proposal | **`duplicate_handling`** — 2 pairs, **₹517,146.80** · Accept / Edit / Reject | "Carried from Day 1: the action at rank 3 fixes tomorrow, this fixes next month." |
| **10** | convention proposal | **`auto_apply_credit_notes`** — 1 note / 14 invoices (7.1 %), **₹42,775.00** off Bharat today (**GT-dep**, **D-6**) | "Small money, and the only proposal that lowers a bill rather than preventing a mistake." |
| **11** | finding, `medium` | **Deccan: ₹1,676,426.00 billed, ₹1,476,426.00 net of the advance, no completed settlement**, addressed to **Priya Kulkarni, Accounts** — *(addressed, but see §3.2: with nothing overdue this is a concentration finding, not an overdue-collections line)* | "Your largest receivable concentration with your least-proven payer." |
| **12** | line (questionnaire) | **Month close for September in 23 days (7-Oct)** | "Answered, so it is shown; it expects nothing today." |
| **13** | line (questionnaire) | **Pending owner sign-off: 5 invoices, ₹888,363.00** (**GT-dep** at a ₹100,000 threshold) | "Every one of them is in tomorrow's payment run; sign-off is the gate you said you wanted." |
| **14–18** | input requests | P&L (`period_accounts`) · budget (`budgets`) · GSTR-2B (`tax_returns`, **₹168,931.80** of August input credit) · vendor contracts (`contracts`) · the two missing POs **PO-VPI-1039 / PO-VPI-1040** covering **9 invoices / ₹746,420.80** | ranked below the operational lines by `unlock_value()`; each names an exact document kind and a figure |

**Cleared, not shown:** the Day-1 overdue-payables line (resolved Day 2) and the Day-1 bank-statement request (fulfilled Day 3, now superseded by the staleness request at rank 6).

**Input-request phrasing contract (task 33.35).** Every line above quotes an exact document kind ("September's bank statement", "GSTR-2B for August", "your FY 2026-27 budget", "PO-VPI-1039") and a quantified unlock. A rendered string containing "more data", "additional documents" or "further information" is a fail regardless of the figure beside it.

### 7.5 FP&A at Day 8 (**GT**)

| capability | expected state | figure / reason |
|---|---|---|
| `pnl_by_period` | `NOT_CHECKED` | no `period_accounts` fact. Attached request: "Q1 FY 2026-27 P&L" |
| `margin_per_customer` | **computed, with a named limitation** | gross billed per customer — Kaveri 1,450,270.00 + 253,700.00 = **1,703,970.00** · Sunrise 1,544,325.00 + 323,910.00 = **1,868,235.00** · Deccan 1,453,170.00 + 223,256.00 = **1,676,426.00**. **Cost cannot be attributed to a customer** from invoices alone, so the margin column is `NOT_CHECKED("cost allocation needs period accounts")` — revenue by customer is a real number, margin is not |
| `margin_per_item` | **`NOT_CHECKED("0 items resolve on both sides")`** | **GT, and worth stating precisely:** not a single item description appears on both an inbound and an outbound invoice. Inbound is raw material and consumables (steel coil, angle bar, bolts, washers, wrench, lubricant, v-belts, gloves, paper, toner, pens, markers, boxes, pallets, film, bearings, bearing housing); outbound is finished goods (stamped bracket, shaft coupling, machined housing, mounting plate, conveyor roller, drive sprocket, idler bracket). A per-item margin number on VPI is fabricated |
| `budget_variance_per_account` | `NOT_CHECKED` | no `budgets` fact. Unlock: "variance against **₹2,092,649.00** of August outflow" |
| `expense_category_trend` | `NOT_CHECKED` | no `period_accounts`; and 1 month of statement data would not support a trend even if the kind were present |

Every one renders as a card with its reason and its request. **Zero empty tiles, zero ₹0 tiles.**

### 7.6 Admin `Run now` (task 33.32)

Expected: `POST /today/run` by the Admin enqueues one tenant run; a second call inside 10 minutes returns **429** with `retry_after_seconds`; a non-Admin gets **403**. In the demo the Admin presses it once at 09:00 IST on Day 8 to see the run land, then again immediately — the button must show the countdown inline, not a toast.

---

## §8. Day 30 — Tue 6-Oct-2026: steady state — **ILL, every figure**

Everything in this section depends on files that do not exist yet: the **June and July 2026 bank statements (task 33.38, pending)** and a September statement. Nothing here may be used as an eval expectation until 33.38 lands and this section is recomputed as GT.

### 8.1 Assumed arrivals between Day 8 and Day 30 (**ILL**)

June and July statements attached (33.38), the September statement attached, the 15-Sep payment run executed, the 17-Sep receipts landed.

### 8.2 What the added depth unlocks (**ILL**)

With Jun + Jul + Aug (+ Sep) statements, `detect_recurrence()` reaches depth 3–4 months and the `recurring` tier lights up:

| detected series | amount (from the August statement, **GT**) | period | depth | tier |
|---|---|---|---|---|
| Salary batch (42 employees) | ≈ 1,486,000.00 | ~30 d, mid-month (14-Aug) | 3–4 months | `recurring` |
| GST payment | ≈ 184,320.00 | ~30 d, early month (03-Aug) | 3–4 months | `recurring` |
| MSEDCL electricity | ≈ 96,410.00 | ~30 d (12-Aug) | 3–4 months | `recurring` |
| Bank charges | ≈ 1,180.00 | month-end (31-Aug) | 3–4 months | `recurring` |
| TechSol **annual** AMC | 58,000.00 | **~365 d (20-Aug)** | 1 occurrence in 4 months | **must NOT be classified monthly-recurring** |

**Flag for 33.38.** `feature_33` §3.7 and the architect brief both list "AMC ≈" among the series expected to light up. A one-off annual charge appearing once in three or four months **must not** be detected as a monthly recurring outflow — that would overstate monthly cash need by ₹58,000.00. Whichever way the generator emits it, the expected value must match: if the generator writes AMC only in August, the expectation is `not recurring`; if it writes it monthly, the fixture is wrong. Recorded here so 33.38 decides it deliberately rather than by accident.

Recurring monthly outflow (excluding AMC): `1,486,000.00 + 184,320.00 + 96,410.00 + 1,180.00 = **1,767,910.00**` (**ILL** — the amounts are GT from August, the recurrence is not).

### 8.3 Day 30 Today — expected shape (**ILL**)

| rank | kind | line | why it ranks here |
|---|---|---|---|
| 1 | forecast, `recurring` | "Monthly fixed outflow ≈ **₹1,767,910.00** (salary, GST, electricity, charges), depth 4 months — next salary ~14-Oct" | "First month the forecast can tell you what leaves without an invoice; it is the largest number on the board and nobody sent you a bill for it." |
| 2 | forecast, `certain` + `recurring` | October runway by week, opening from the September statement's closing balance | "Rank 1 becomes actionable only against a real balance." |
| 3 | finding | whatever the 15-Sep run and 17-Sep receipts left unresolved — e.g. a receivable that did not arrive on 17-Sep | "A promise that broke ranks above a promise not yet due." |
| 4 | finding, `high` | the IGST finding, **still open** and now on October invoices too | "It compounds; this is its fourth week on your screen." |
| 5 | input request | October statement staleness, once it passes threshold | — |
| 6 | convention proposal | any proposal still unanswered — **suppressed after 3 dismissals** for that kind, that tenant only | — |
| 7+ | FP&A | still `NOT_CHECKED` unless a P&L and a budget were attached — in which case `pnl_by_period`, `budget_variance_per_account` and `expense_category_trend` produce their first real figures | — |

Steady-state expectation on volume: a Day-30 Today with **more** lines than Day 8 on the same data is a fail — resolution, dismissal and suppression must be net-reducing.

---

## §9. The 17 §6 SAGE questions, restated at `as_of = 2026-09-15` — the regression contract

**Scope:** all 26 invoices uploaded (14 inbound, 12 outbound), the credit note attached in chat only (**never uploaded, never an `Invoice` row**), step C done. "Clean" = NAT-2007 and RAJ-2009 excluded. All ATLAS flags **on**, facts ledger populated, clearance live, asked by an **Admin**.

**The contract: all 17 answers must be byte-identical to their pre-ATLAS values.** The facts ledger, the clearance filters and the Today surface must not move a single SAGE figure. Two answers differ from the README's older text, and both are README errors, not ATLAS effects: **Q5** (was anchored to an implied "today 9-Sep") and **Q15** (**D-2**).

| # | ask | expected answer at as_of 2026-09-15 | derivation | type |
|---|---|---|---|---|
| 1 | What is our total inbound spend? | **₹1,891,327.60** across 14 invoices as uploaded; names NAT-2007 and RAJ-2009 as duplicates and offers the clean **₹1,374,180.80** | 1,636,447.60 (11 PDF) + 254,880.00 (3 image) = 1,891,327.60; clean = − 79,956.80 − 437,190.00 | `exact_value` |
| 2 | Which vendor did we spend the most with? | **Rajesh Steel Corporation, ₹437,190.00** clean (₹874,380.00 if RAJ-2009 counts — saying which basis is used is part of a correct answer). Then Shree 366,508.00 · Bharat 206,382.00 · Ganesh 172,044.00 · Om 112,100.00 · National MRO 79,956.80 | Shree 121,894 + 121,894 + 122,720; Bharat 103,191 × 2; Ganesh 68,676 + 103,368; Om 41,654 × 2 + 28,792. Σ = 1,374,180.80 ✓ | `exact_value` |
| 3 | List all vendors | the **6** inbound vendors — Bharat Hardware & Fasteners, Ganesh Bearings Pvt Ltd, National MRO Traders, Om Stationery Mart, Rajesh Steel Corporation, Shree Packaging Industries. **Customers are not vendors** | §3.3 clusters | `exact_value` |
| 4 | Do we have any duplicate invoices? | **NAT-2006 / NAT-2007** and **RAJ-2008 / RAJ-2009**, both flagged `possible_duplicate`; ₹517,146.80 of duplicate exposure | identical vendor + date + due + line set + total | `exact_value` |
| 5 | Which invoices are overdue? | **None as of 15-Sep-2026** — and a good answer adds that **5 clean payables (₹783,885.80) are due today**: BHA-2003, NAT-2006, OM -2001, RAJ-2008, SHR-2005 | all other due dates are 17-Sep or later; nothing is past its due date at 15-Sep | `exact_value` |
| 6 | How much do we owe Bharat Hardware? | **₹103,191.00** — BHA-2003 open, BHA-2002 paid 06-Aug. If the credit note is mentioned: the **books** say ₹103,191.00 and the **net position after BHF-CN-2010** is ₹60,416.00; the note is a chat attachment and moves no aggregate | 103,191.00; 103,191.00 − 42,775.00 | `exact_value` |
| 7 | Total GST on inbound invoices in August | **₹168,931.80** — BHA-2003 15,741.00 + GBP-2011 10,476.00 + NAT-2006 12,196.80 + OM -2001 6,354.00 + RAJ-2008 66,690.00 + SHR-2005 18,594.00 + OM -2002 4,392.00 + GBP-2012 15,768.00 + SHR-2006 18,720.00 | each = subtotal × 0.18; duplicates excluded; Σ re-added twice | `exact_value` |
| 8 | What did we buy from National MRO Traders? | Industrial Lubricant 20L × 5 (₹5,600) · Replacement V-Belts × 12 (₹1,680) · Safety Gloves case of 60 × 8 (₹2,450) — ₹67,760.00 + GST = ₹79,956.80, **once**, not twice (NAT-2007 is a duplicate) | NAT-2006 lines | `exact_value` |
| 9 | Show outbound invoices to Deccan Machinery | **VPI-OUT-2018 / 2019 / 2020** at ₹484,390.00 each, due 17-Sep, and **VPI-OUT-2023** at ₹223,256.00, due 29-Sep — **₹1,676,426.00** total, all open, with ₹200,000.00 received as an unapplied advance | 484,390 × 3 + 223,256 | `exact_value` |
| 10 | Which outbound invoice has a total that doesn't add up? | **VPI-OUT-2014** — lines + tax ₹483,210.00 against a printed ₹483,850.00, **+₹640.00**, flagged `tax_mismatch`, status Needs review. It is the only one | §2.4 cross-check: Σ subtotals + Σ GST differs from Σ printed by exactly 640.00 | `exact_value` |
| 11 | Total receivables outstanding | **₹4,250,646.00** as printed across 10 open invoices. A good answer adds: ₹4,250,006.00 if VPI-OUT-2014 is corrected, and ₹4,050,646.00 net of the unapplied ₹200,000.00 Deccan advance | 5,248,631.00 − 483,210.00 − 514,775.00 | `exact_value` |
| 12 | What is the invoice number of the Ganesh Bearings invoice and when is it due? | **Ambiguous — must ask, or list both**: GBP-2011 ₹68,676.00 due 18-Sep and GBP-2012 ₹103,368.00 due 27-Sep. Answering with one invoice and no mention of the other, or with ₹0, is a fail | two Ganesh invoices on file | `should_clarify` |
| 13 | Give me inbound spend per month for July and August | **July ₹266,739.00** (BHA-2002 103,191.00 + OM -2000 41,654.00 + SHR-2004 121,894.00); **August ₹1,107,441.80** clean (₹1,624,588.60 with the duplicates) | 1,374,180.80 − 266,739.00 = 1,107,441.80; + 517,146.80 = 1,624,588.60 | `exact_value` |
| 14 | Convert Rajesh Steel's invoice to USD | **Must abstain** — no exchange rate exists anywhere in the data. Naming a rate is a fabrication; an INR figure relabelled `$` is a Gap 225 failure | no FX field in any document or view | `should_reject` |
| 15 | Which invoices have HSN 8483? | **12 invoices** — outbound **VPI-OUT-2012 … VPI-OUT-2020** (Precision Shaft Coupling B-9 on 2012–2014; Machined Housing H-3 **and** Gearbox Mounting Plate on 2015–2017; **Drive Sprocket Set on 2018–2020**), plus **VPI-OUT-2021** (Shaft Coupling) and **VPI-OUT-2022** (both lines); inbound **GBP-2012** (Bearing Housing P205). VPI-OUT-2023 is 8428-only and excluded | line-level HSN scan of all 26 invoices (**D-2** — the README omitted 2018–2020) | `exact_value` |
| 16 | Which invoices need my attention? | **Exactly three**: VPI-OUT-2014 (total mismatch), NAT-2007 and RAJ-2009 (possible duplicates). *ATLAS's Today findings — the IGST head, the missing customer GSTINs, the Deccan concentration — are* **not** *invoice-level alerts and must not change this answer* | extraction alerts only | `exact_value` |
| 17 | Did we pay Om Stationery twice? | **No.** OM -2000 (09-Jul, paid 05-Aug ₹41,654.00, UTR HDFCN26080512345) and OM -2001 (16-Aug, open ₹41,654.00) are different invoices for the same amount; OM -2002 (26-Aug, ₹28,792.00) is a third, smaller one. Total Om spend ₹112,100.00, of which ₹41,654.00 paid | §2.1, §2.3, §2.7 | `exact_value` |

### 9.1 Three additional questions worth asking post-ATLAS

| # | ask | expected | type | probes |
|---|---|---|---|---|
| 18 | "What's our spend this fiscal year?" | **Must resolve to FY 2026-27 (1-Apr-2026 → 31-Mar-2027)**, not calendar 2026: inbound **₹1,374,180.80** clean, outbound **₹5,248,631.00**, all of it in Q2 FY27. A calendar-2026 framing is wrong even though the figure coincides | `exact_value` | fiscal-year boundary, India |
| 19 | "How much is outstanding?" | **Ambiguous — must ask which side.** Payables ₹1,107,441.80, receivables ₹4,250,646.00. A single number, or ₹0, is a Gap 224 failure | `should_clarify` | Gap 224 |
| 20 | "Show me the CGST/SGST split for August" | Inbound is intra-state: CGST **₹84,465.90** and SGST **₹84,465.90** (= 168,931.80 ÷ 2). **IGST ₹0.00** on inbound. And the correct answer flags that the outbound side charges CGST+SGST on inter-state supplies where IGST is due (**D-5**) | `exact_value` | GST head correctness |

---

## §10. Open items handed back

| # | item | who decides |
|---|---|---|
| 1 | **D-5** — is the outbound CGST/SGST-on-inter-state a fixture defect to fix in 33.38, or the demo's headline compliance finding? It cannot be both and it cannot be silent | founder |
| 2 | **D-7** — no `Fact` kind fits a credit note; turn 11 leaves zero facts. New gap? | founder / senior-dev |
| 3 | **D-6** — the emission threshold for `auto_apply_credit_notes`; 7.1 % on one document | senior-dev (config default) |
| 4 | Approval threshold for `invoice_approval` (brief §D open question 2) — ₹100,000 used here as illustrative; the ₹888,363.00 sign-off figure moves with it | founder |
| 5 | `po_before_invoice = materials_only`: line per **open** materials invoice (3, ₹329,279.00) or per **all** materials invoices (5)? This document expects open-only | founder |
| 6 | `enable_partial_payments` — suppressed here because Feature 31 is cancelled and `/accept` has nowhere to write. Confirm | founder |
| 7 | FE spec §7 Q4 — whether an Auditor's Today carries the questionnaire-derived lines. This document expects Admin-only | founder |
| 8 | 33.38's AMC treatment (§8.2) — annual, must not be monthly-recurring | senior-dev |
| 9 | The upload order in §1 must be **pinned in the eval fixture**; every Day-1 figure depends on SHR-2004 being the 10th document | senior-dev (33.21 / 33.40) |
