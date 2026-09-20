# ATLAS Admin briefing — VPI expected value (as_of 2026-09-15)

Ground truth for testing BE Feature 35 (ATLAS Intelligence) on the VPI demo tenant, for the
**Admin** role. Written by business-analyst 2026-09-20 from
`showcase/vpi_demo/README.md` §3–§6 and a read-only query of live Postgres
`127.0.0.1:5433/invoice_db`. Companion: `feature_35_atlas_intelligence.md` §3.2 (tools), §3.3
(wire contract); `feature_34_atlas.md` §2.3 (the Admin's four needs, D14).

**Figure marking, used on every number below.**

| mark | meaning |
|---|---|
| **GT** | hand-derived from the README and confirmed against the live rows. A tool exists today that can render it. |
| **GT-dep** | correct arithmetic, but it depends on a row or a tool that does not exist in this tenant today (empty `fact`, empty `bank_statement_line`, or no tool in §3.2 at all). |

**Rule for this document: no figure here is ever revised to match what a system printed.** If
ATLAS and this file disagree, the file is right until the README is shown wrong.

---

## 0. Amendment — 2026-09-20: the *Cite* ids are now the ids the tools emit

**Why this was added.** The 2026-09-20 live grading
(`test_evidence/atlas_intelligence_2026-09-20/grading_admin.md`) scored a *correct* Admin
briefing **0 MATCH / 2 PARTIAL / 10 MISS**. Nothing was wrong with the briefing: every *Must
cite* id in section 2 below was written as a bare record uuid or a bare composed token
(`530bd65a-…`, `cash-INR`), and the system emits **role- and area-prefixed recommendation ids**
(`audit-approve-530bd65a-…`, `audit-cash-INR`). Under the section 6 rule as literally written —
set containment over `citations[].record_id` — every M-item was an automatic MISS regardless of
what the paragraph said. That is a defect in this document, not in the build, and the 2026-09-20
grading had to grade by substring containment to produce any signal at all.

**What changed here.** Section 2's *Cite* lines now list the ids the tools actually emit, read
out of a live dispatch against this tenant (see the table below), and section 6 states the
matching rule explicitly: **a MUST item is MATCH if ANY of its listed ids is cited and the
figures appear.** Nothing else is revised: no figure, no ranking, no MUST-NOT, no NO-TOOL-TODAY
marking. The document's own rule — *no figure here is ever revised to match what a system
printed* — is untouched and still governs every number.

### 0.1 The id vocabulary, as emitted (live dispatch, `as_of` 2026-09-15)

| producer | `record_kind` | `record_id` shape | this tenant, today |
|---|---|---|---|
| `list_lines` (approval line) | `recommendation` | `audit-approve-<invoice uuid>` | `audit-approve-530bd65a-be04-4953-988b-2932f52a6f89` (RAJ-2009), `audit-approve-22490a93-94a8-4511-90ba-52d495e0cc05` (NAT-2007) |
| `list_lines` (cash line) | `recommendation` | `audit-cash-<CUR>` | `audit-cash-INR` |
| `list_lines` (trainer line) | `recommendation` | `train-lowconf-<invoice uuid>` | `train-lowconf-33d6ccd5-…` (GBP-2012), `train-lowconf-530bd65a-…` (RAJ-2009), `train-lowconf-d5869da2-…` (RAJ-2008), `train-lowconf-ff4a9fe0-…` (OM -2002) |
| `list_lines` (collapsed area) | `collapsed_area` | `area-<capability>` | only when the Admin's screen collapses one |
| `invoices` | `invoice` | `<invoice uuid>`, bare | all 26, section 1's uuids verbatim |
| `cash_position` | `cash_position` | `cash-<CUR>` | `cash-INR` |
| `forecast` | `shortfall` | `forecast-short-<CUR>` | **0 rows today** — no balance to go short against |
| `doubts` | `doubt` | `doubt-<invoice uuid>-<claim kind>-<index>` | only when the model calls it |
| `memory_rules` | `rule` | the rule's uuid | **0 rows today** |

Two consequences worth stating, because they decide MATCH on several items below:

1. **An invoice has up to three citable ids** — its approval line, its trainer line, and its own
   `invoices` row. A paragraph about RAJ-2009 is equally correct citing any of them.
2. **An outbound invoice has exactly one** — the `invoices` row. No skill emits a line for it, so
   VPI-OUT-2014 is citable as `13d719a7-c53f-4204-95fc-79f5b73959ba` and as nothing else.


---

## 1. Anchors

- Tenant `00000000-0000-0000-0000-000000000000` (Vishwa Precision Industries Pvt Ltd, Pune MH)
- `as_of` = **2026-09-15**; fiscal year **FY 2026-27 (1-Apr-2026 → 31-Mar-2027)**
- Currency **INR only** — every figure renders `₹`. A `$` anywhere is a fail.
- 26 live invoices (14 inbound, 12 outbound), `deleted_at is null`
- Empty today: `fact`, `bank_statement_line`, `today_item`, `insight`, `input_request`,
  `atlas_briefings`, `atlas_memory_rules`, `convention_proposal` — all 0 rows for this tenant.

### 1.1 Inbound (14)

| id | number | vendor | date | due | total ₹ | status | alert |
|---|---|---|---|---|---|---|---|
| b96f4a85-74ed-4aff-b8ff-27cddceb0d6c | BHA-2002 | Bharat Hardware & Fasteners | 09-Jul | 08-Aug | 103,191.00 | PAID | — |
| d0a5d0dd-c32f-4eef-8b24-a1fa5d617f68 | BHA-2003 | Bharat Hardware & Fasteners | 17-Aug | 15-Sep | 103,191.00 | COMPLETED | — |
| 5288549a-9cb7-4ac6-94b9-b734463029df | GBP-2011 | Ganesh Bearings Pvt Ltd | 19-Aug | 18-Sep | 68,676.00 | COMPLETED | — |
| 33d6ccd5-57a4-4c16-a4f1-9708a05c205a | GBP-2012 | Ganesh Bearings Pvt Ltd | 28-Aug | 27-Sep | 103,368.00 | COMPLETED | low-conf PaymentTerm 0.485 |
| 86f1559a-ab03-4c07-b1f3-7453db53aeb9 | NAT-2006 | National MRO Traders | 19-Aug | 15-Sep | 79,956.80 | COMPLETED | — |
| 22490a93-94a8-4511-90ba-52d495e0cc05 | NAT-2007 | National MRO Traders | 19-Aug | 15-Sep | 79,956.80 | AUDIT_REQUIRED | `possible_duplicate` of NAT-2006 |
| f84c8490-bd5b-4550-a992-d120d854ff8b | OM -2000 | Om Stationery Mart | 09-Jul | 08-Aug | 41,654.00 | PAID | — |
| 7af3ad6a-a643-4884-bd91-088af0e09bf1 | OM -2001 | Om Stationery Mart | 16-Aug | 15-Sep | 41,654.00 | COMPLETED | — |
| ff4a9fe0-df7a-401d-a9b3-29e128f66663 | OM -2002 | Om Stationery Mart | 26-Aug | 25-Sep | 28,792.00 | COMPLETED | low-conf PaymentTerm 0.332 |
| d5869da2-b3bc-4d41-9356-2c6a02352616 | RAJ-2008 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 437,190.00 | COMPLETED | low-conf PaymentTerm 0.414 |
| 530bd65a-be04-4953-988b-2932f52a6f89 | RAJ-2009 | Rajesh Steel Corporation | 20-Aug | 15-Sep | 437,190.00 | AUDIT_REQUIRED | `possible_duplicate` of RAJ-2008; low-conf PaymentTerm 0.406 |
| fbe08368-f644-47af-905b-ec4085211eec | SHR-2004 | Shree Packaging Industries | 09-Jul | 08-Aug | 121,894.00 | PAID | — |
| 29a03885-2441-4502-9f29-d4cc05efd1de | SHR-2005 | Shree Packaging Industries | 18-Aug | 15-Sep | 121,894.00 | COMPLETED | — |
| 11c3df22-d0bd-41d9-a219-2c204a4ad39e | SHR-2006 | Shree Packaging Industries | 29-Aug | 28-Sep | 122,720.00 | COMPLETED | — |

### 1.2 Outbound (12) — all raised by VPI

| id | number | customer | date | due | total ₹ | status | alert |
|---|---|---|---|---|---|---|---|
| e6cfda29-d288-4423-9c9e-01cbcab12271 | VPI-OUT-2012 | Kaveri Auto Components Pvt Ltd | 14-Jul | 10-Aug | 483,210.00 | PAID | — |
| 0795e41d-86ec-4c83-8088-a7276f04fc94 | VPI-OUT-2013 | Kaveri Auto Components Pvt Ltd | 18-Aug | 17-Sep | 483,210.00 | VERIFIED | — |
| 13d719a7-c53f-4204-95fc-79f5b73959ba | VPI-OUT-2014 | Kaveri Auto Components Pvt Ltd | 19-Aug | 17-Sep | 483,850.00 | NEEDS_REVIEW | `tax_mismatch` |
| 551a74e1-0ede-4230-88c0-42497f698246 | VPI-OUT-2015 | Sunrise Engineering Works | 14-Jul | 10-Aug | 514,775.00 | PAID | — |
| 256232e6-e256-4f4d-8249-10e64c4458ad | VPI-OUT-2016 | Sunrise Engineering Works | 18-Aug | 17-Sep | 514,775.00 | VERIFIED | — |
| e21e8a13-798f-4b9f-bd63-27d879a129c5 | VPI-OUT-2017 | Sunrise Engineering Works | 19-Aug | 17-Sep | 514,775.00 | VERIFIED | — |
| ec8acc1d-c0c0-493c-a3c2-78292fadab5e | VPI-OUT-2018 | Deccan Machinery Ltd | 17-Aug | 17-Sep | 484,390.00 | VERIFIED | — (₹2,00,000 advance, unapplied) |
| 94192419-1da8-4cfb-a374-9d60ff559256 | VPI-OUT-2019 | Deccan Machinery Ltd | 18-Aug | 17-Sep | 484,390.00 | VERIFIED | — |
| 65097bd1-9b0c-4178-a998-3ca06a8fd831 | VPI-OUT-2020 | Deccan Machinery Ltd | 19-Aug | 17-Sep | 484,390.00 | VERIFIED | — |
| 9a79e1c3-6778-4f60-907c-7afc503f5711 | VPI-OUT-2021 | Kaveri Auto Components Pvt Ltd | 27-Aug | 26-Sep | 253,700.00 | VERIFIED | — |
| dc403a31-0e92-4b7b-a5ee-46b1047dbb85 | VPI-OUT-2022 | Sunrise Engineering Works | 28-Aug | 27-Sep | 323,910.00 | VERIFIED | — |
| a2d86662-fc1d-452c-9783-02463bdfe930 | VPI-OUT-2023 | Deccan Machinery Ltd | 30-Aug | 29-Sep | 223,256.00 | VERIFIED | — |

Only three invoices carry `sa_alerts` at all: NAT-2007, RAJ-2009, VPI-OUT-2014.

---

## 2. What the Admin briefing MUST raise — 12 items, ranked by the four needs

Ranking is D14's order: **don't lose money · don't run out · don't let it stall · keep the
setup right.** Within a need, by rupees at risk.

### Need 1 — don't lose money

**M1 · The two duplicates.** RAJ-2009 and NAT-2007 repeat RAJ-2008 and NAT-2006 exactly — same vendor, date and total, a different number only — and both are open payables due 15-Sep.
*Figures (GT):* 437,190.00 + 79,956.80 = **₹5,17,146.80** exposure; 2 of 14 inbound.
*Tool:* `list_lines` (auditor duplicate approval lines carry both ids and the figure).
*Cite (any one is enough):* the two flagged invoices as lines — `audit-approve-530bd65a-be04-4953-988b-2932f52a6f89`, `audit-approve-22490a93-94a8-4511-90ba-52d495e0cc05` — or as `invoices` rows, `530bd65a-be04-4953-988b-2932f52a6f89`, `22490a93-94a8-4511-90ba-52d495e0cc05`. The originals are `invoices` rows only: `d5869da2-b3bc-4d41-9356-2c6a02352616` (RAJ-2008), `86f1559a-ab03-4c07-b1f3-7453db53aeb9` (NAT-2006).
*Rank:* largest avoidable cash loss in the tenant, and it is due the same day.

**M2 · VPI-OUT-2014 does not add up.** VPI is billing Kaveri ₹640 it cannot substantiate.
*Figures (GT):* subtotal 409,500.00 + tax 73,710.00 = 483,210.00 vs printed 483,850.00 = **+₹640.00**; `tax_mismatch`, severity error, NEEDS_REVIEW.
*Tool:* `list_lines`; `doubts` for claim / witness / verdict.
*Cite:* `13d719a7-c53f-4204-95fc-79f5b73959ba` (the `invoices` row — outbound, so there is no line id for it), or a `doubt-13d719a7-c53f-4204-95fc-79f5b73959ba-<claim kind>-<index>` row if the model called `doubts`.
*Rank:* small rupees, but the only arithmetic defect in 26 invoices — and outbound, so the customer finds it first.

**M3 · The ₹2,00,000 Deccan advance is recorded but not applied.** The 25-Aug bank credit names VPI-OUT-2018, yet the invoice shows its full balance — receivables overstated, Deccan chased for money already received.
*Figures (GT-dep):* 200,000.00 of 484,390.00 = **41.29%**, balance **₹2,84,390.00**; receivables net **₹40,50,646.00** (4,250,646.00 − 200,000.00).
*Tool:* **NO TOOL TODAY** — `fact` has 0 rows here and the statement is a chat attachment (turn 10), not an ingested ledger; no §3.2 tool returns an unapplied receipt.
*Cite:* `ec8acc1d-c0c0-493c-a3c2-78292fadab5e` (the `invoices` row).
*Rank:* money already in the bank that the books deny.

**M4 · GST charged under the wrong head on every outbound invoice.** All 12 charge CGST 9% + SGST 9%, but Kaveri (Bengaluru KA), Sunrise (Ahmedabad GJ) and Deccan (Hyderabad TS) are outside Maharashtra — inter-state, IGST 18% — and no customer GSTIN is printed on any of them.
*Figures (GT):* **₹8,00,541.00** on **12** invoices under the wrong head (CGST 400,270.50 + SGST 400,270.50); 0 customer GSTINs held.
*Tool:* **NO TOOL TODAY** — no ATLAS service tests place of supply (`grep IGST services/` is empty). `ask_sage` can return the ₹8,00,541.00 total but cannot judge the head; the head finding without an `ask_sage` citation is invented.
*Cite:* any of the 12 outbound `invoices` rows by uuid (section 1.2's ids, bare), or the three customer groupings by those ids.
*Rank:* largest rupee figure in the tenant, and statutory rather than preference.

### Need 2 — don't run out

**M5 · 15-Sep payables exceed the last known balance.** Five clean payables fall due on `as_of` itself against a balance last seen 31-Aug; the ₹34,49,780.00 that would cover them lands 17-Sep, two days late.
*Figures:* due 15-Sep clean 103,191.00 + 79,956.80 + 41,654.00 + 437,190.00 + 121,894.00 = **₹7,83,885.80** (GT); balance **₹3,55,336.00** at 31-Aug (GT-dep); shortfall = **₹4,28,549.80** (GT-dep). With the duplicates it is ₹13,01,032.60 out — which is why M1 outranks it.
*Tool:* `forecast` (`shortfalls()`) + `cash_position` — but `balance` is `None` today (`bank_statement_line` = 0 rows), so `projected` and `runway_days` are `None`. A number where `None` is correct is a fail.
*Cite:* the five payables as `invoices` rows — `d0a5d0dd-c32f-4eef-8b24-a1fa5d617f68`, `86f1559a-ab03-4c07-b1f3-7453db53aeb9`, `7af3ad6a-a643-4884-bd91-088af0e09bf1`, `d5869da2-b3bc-4d41-9356-2c6a02352616`, `29a03885-2441-4502-9f29-d4cc05efd1de` — plus `forecast-short-INR` **if `forecast` returns a row**, which it does not on this tenant today.
*Rank:* the only date on which VPI can actually fail to pay.

**M6 · The payables book is inflated by the duplicates.**
*Figures (GT):* as extracted **₹16,24,588.60**; clean **₹11,07,441.80**; difference ₹5,17,146.80. Derivation: inbound clean 1,374,180.80 − July settled (103,191.00 + 41,654.00 + 121,894.00 = 266,739.00) = 1,107,441.80; + 517,146.80 = 1,624,588.60.
*Tool:* `cash_position` (`payable_due`, `payable_count`). Per §9.3 dev. 1 its rows carry counts, not ids.
*Cite:* `cash-INR` (the `cash_position` row) or `audit-cash-INR` (the same figures as a `list_lines` line), plus either form of the two duplicate ids when it states the difference.
*Rank:* it changes the sign of every cash sentence above it.

**M7 · Receivables and their concentration.** 39% sits with one customer who has already part-paid without the payment being applied.
*Figures (GT):* open **₹42,50,646.00** (5,248,631.00 − 483,210.00 − 514,775.00); Deccan 484,390×3 + 223,256 = **₹16,76,426.00** (39.44%); Sunrise 514,775×2 + 323,910 = **₹13,53,460.00** (31.84%); Kaveri 483,210 + 483,850 + 253,700 = **₹12,20,760.00** (28.72%); the three sum to 4,250,646.00.
*Tool:* `cash_position` for the total; **NO TOOL TODAY for the split** — no §3.2 tool returns receivables by customer, so those need `ask_sage`, cited as such.
*Cite:* `cash-INR` or `audit-cash-INR`; for Deccan the `invoices` rows `ec8acc1d-c0c0-493c-a3c2-78292fadab5e`, `94192419-1da8-4cfb-a374-9d60ff559256`, `65097bd1-9b0c-4178-a998-3ca06a8fd831`, `a2d86662-fc1d-452c-9783-02463bdfe930`.
*Rank:* a runway built on one customer paying is not a runway.

### Need 3 — don't let it stall

**M8 · Nothing is overdue, and that is the answer.** Every open due date is 15-Sep or later, so the paragraph says **none** rather than producing a list.
*Figures (GT):* 0 overdue; 9 open payables, 10 open receivables; **₹34,49,780.00** due 17-Sep across 7 invoices (483,210 + 483,850 + 514,775 + 514,775 + 484,390 + 484,390 + 484,390).
*Tool:* `list_lines`, `cash_position`, `invoices`. *Cite:* the seven 17-Sep outbound `invoices` rows by uuid (`0795e41d-…`, `13d719a7-…`, `256232e6-…`, `e21e8a13-…`, `ec8acc1d-…`, `94192419-…`, `65097bd1-…`), or `cash-INR` / `audit-cash-INR` for the totals.
*Rank:* a false overdue list here destroys trust in M5.

**M9 · Three invoices are blocked awaiting a person.** Two AUDIT_REQUIRED, one NEEDS_REVIEW.
*Figures (GT):* exactly **3** — NAT-2007, RAJ-2009, VPI-OUT-2014; value held 79,956.80 + 437,190.00 + 483,850.00 = **₹10,00,996.80**.
*Tool:* `list_lines` (the two inbound) + `invoices` (all three). *Cite:* `audit-approve-22490a93-94a8-4511-90ba-52d495e0cc05` **or** `22490a93-94a8-4511-90ba-52d495e0cc05`; `audit-approve-530bd65a-be04-4953-988b-2932f52a6f89` **or** `530bd65a-be04-4953-988b-2932f52a6f89`; `13d719a7-c53f-4204-95fc-79f5b73959ba` — and no invoice other than these three.
*Rank:* the whole queue is three items; naming a fourth is an invention (README §6 #16).

### Need 4 — keep the setup right

**M10 · PaymentTerm is being read badly on four invoices** — and payment terms are what every due date in M5 rests on.
*Figures (GT):* **4** — GBP-2012 **0.485**, RAJ-2008 **0.414**, RAJ-2009 **0.406**, OM -2002 **0.332**; no other field on any of the 26 is below 0.80.
*Tool:* `list_lines` (`_low_confidence_fields()` → trainer lines; the Admin is the superset per F34 §2.2, so they may arrive collapsed as `area-can_train`).
*Cite:* the four trainer lines — `train-lowconf-33d6ccd5-57a4-4c16-a4f1-9708a05c205a`, `train-lowconf-d5869da2-b3bc-4d41-9356-2c6a02352616`, `train-lowconf-530bd65a-be04-4953-988b-2932f52a6f89`, `train-lowconf-ff4a9fe0-df7a-401d-a9b3-29e128f66663` — or the same four invoices as `invoices` rows (bare uuids), or `area-train` if the Admin's screen collapsed them.
*Rank:* setup, not money — but it is the cause of a money line.

**M11 · Four witnesses are missing, each with a price.** The exact document, never "more data".
*Figures (GT-dep, README §8):* September bank statement — **₹53,58,087.80** of movement unconfirmed; PO-VPI-1039 and PO-VPI-1040 — **9 invoices / ₹7,46,420.80** unverifiable; GSTR-2B for August — **₹1,68,931.80** of input credit unreconciled (= clean August inbound GST, CGST 84,465.90 + SGST 84,465.90, IGST 0).
*Tool:* **NO TOOL TODAY** — `input_request` has 0 rows and no §3.2 tool reads it; `doubts` gives a per-invoice witness but no tenant-level request with a rupee unlock.
*Cite:* the `invoices` rows (bare uuids) behind each figure. `loan_schedules` must **not** be requested.
*Rank:* the only item that changes what ATLAS can say tomorrow.

**M12 · The tenant has no conventions recorded**, so every judgement above is re-derived each morning with nothing learned.
*Figures (GT):* **0** memory rules, **0** convention proposals; derivable on VPI: duplicate handling (₹5,17,146.80), default terms NET 30 (median 28 days over the three settled invoices), `auto_apply_credit_notes` (₹42,775.00).
*Tool:* `memory_rules`. *Cite:* `memory_rules` rule uuids if any exist; with zero rows today, the proposal targets by `invoices` row uuid.
*Rank:* lowest rupee urgency, highest compounding value.

**Count: 12 MUST items · 3 are NO TOOL TODAY (M3, M4, M11) · 1 partially (M7's split).**


---

## 3. What the briefing MUST NOT say

| # | forbidden | why / guard |
|---|---|---|
| 1 | any money figure no tool rendered in this run | `InventedNumberError` / `UnwitnessedFigureError`. Restating a README figure the tools did not return is an invention, not a pass |
| 2 | FP&A, P&L, margin — `pnl_by_period`, `margin_per_customer`, `margin_per_item`, `budget_variance_per_account`, `expense_category_trend`, `forecast_scenario` | off-screen by F34 §3.1 / D16 — chat only, never unprompted |
| 3 | anything about a person's speed, throughput or backlog | no per-user counts, no productivity framing |
| 4 | a `$` anywhere, or a blended total | INR only; `₹` or `INR`, never `$`, never `Rs.` on a tool figure. `CurrencyBlendError` |
| 5 | calendar 2026 as "this fiscal year" | must resolve to FY 2026-27, 1-Apr-2026 → 31-Mar-2027 |
| 6 | a `0` where the answer is unknown | balance / `projected` / `runway_days` are `None` today — absent, not blanked |
| 7 | a fourth "invoice needing attention" | the GST head, missing GSTINs and Deccan concentration are briefing findings, not invoice alerts (README §6 #16) |
| 8 | an inbound line-math alert | every inbound line passes `qty × rate = amount` and `subtotal + CGST + SGST = total`; one raised is a false positive |
| 9 | a promise to attach, fetch or open a file, or any claim it wrote something | `AttachmentPromiseError`; every tool is read-only |

---

## 4. The one interview question

> **"RAJ-2009 and RAJ-2008 are identical — same vendor, same 20-Aug date, same ₹4,37,190.00,
> different number. Is RAJ-2009 a duplicate, or a genuine second order?"**

Required properties: exactly one question in the run; cites `530bd65a-be04-4953-988b-2932f52a6f89`
and `d5869da2-b3bc-4d41-9356-2c6a02352616`; `answer_kind: free_text`; it is the highest-rupee
thing ATLAS genuinely cannot decide from data (DC-RSC-0812 covers RAJ-2008's quantities and
RAJ-2009 has no challan, but nothing rules out a re-order).

**What the answer becomes.** `POST /api/v1/atlas/briefing/answer` → `201 MemoryRuleOut`, a
tenant chat rule with `source="atlas"`, e.g. *"Rajesh Steel: a second invoice with the same date
and total and no delivery challan is a duplicate — hold it."* It must **not** write the invoice,
the alert or any aggregate; ₹5,17,146.80 of exposure stays exposure until a human acts on the
line. NAT-2007 is not asked about — it has the same shape and the rule covers it.

---

## 5. Expected behaviour for the other two briefings

| role | MUST see | MUST NOT see |
|---|---|---|
| **Auditor** (`can_audit`) | M1 duplicates, M2 VPI-OUT-2014, M9 the three blocked invoices, outbound to chase, and the bounded cash consequence of approving ("approving RAJ-2008 commits ₹4,37,190.00 on 15-Sep"); the six `ops` payment facts once the statement is cleared, incl. "BHA-2002 paid 06-Aug, UTR HDFCN26080612346" | The bank statement or its file · the ₹3,55,336.00 balance · the ₹14,86,000.00 salary, GST, electricity, AMC, bank-charge lines · any runway or FP&A line · M5's shortfall as a company-health statement. **Absent, not blanked** — a 0 where a runway line would be is a defect. Tool schema list excludes `cash_position` and `forecast`. |
| **Trainer** (`can_train`) | M10's four low-confidence `PaymentTerm` fields with the correction pre-drafted and ranked by consequence; bad/misfiring rules; M12's empty rule set | `cash_position`, `forecast`, `reconcile`, `doubts`, `vendor_baseline` are absent from its schema list (F35 §9.4) — therefore no cash, no shortfall, no duplicate-approval line, no receivables. |
| **no grants** | the static welcome only | any citation at all — the cold/ungranted welcome carries none (F35 §3.5, ruling 1). |

A second Admin sees everything the first Admin sees. Clearance is by grant, not by person.

---

## 6. Grading rule for the functional-tester

Deterministic set and figure comparison. **Never an LLM judge** — CONVENTIONS hard rule 3.

Per MUST item M1–M12, over the briefing's `paragraph` (and `question`) events:

**The matching rule (2026-09-20, section 0): a MUST item is MATCH if ANY of the ids listed for
it is cited and the figures appear.** The listed ids are alternatives, not a set to be contained:
one invoice is citable as its approval line, as its trainer line and as its own `invoices` row,
and a paragraph that names any one of them has pointed the reader at that record. Set
containment over every listed id is what scored a correct briefing 0/12 on 2026-09-20. Ids are
compared **whole and exactly** — `audit-approve-530bd65a-…` is a listed id in its own right, so
no substring matching is needed or permitted.

| verdict | test |
|---|---|
| **MATCH** | some single paragraph's `citations[].record_id` set contains **at least one** of that item's listed *Cite* ids **and** its text contains every listed figure verbatim after normalisation |
| **PARTIAL** | the citation test passes, one or more listed figures absent — or the figures are present in a paragraph citing a listed record plus extra records |
| **MISS** | no paragraph cites any of the listed ids |
| **INVENTED** | any money-shaped token in any paragraph that is not in §1 or §2 of this file (use `atlas_contract.numeric_tokens()` to extract; compare against the allowed-figure set) — reported per token, independent of the per-item verdict |

Normalisation before comparison, applied to both sides: strip `₹`, `INR`, `Rs.`, spaces and
grouping commas; compare as `Decimal` to 2 dp. **Both lakh grouping (`7,83,885.80`) and plain
grouping (`783,885.80`) are accepted** — grouping style is not graded; the symbol is
(`$` = automatic fail of §3 item 4, regardless of the number).

Scoring: 12 items. Report `MATCH / PARTIAL / MISS` counts, the INVENTED token list, and the
§3 violations as a separate pass/fail list — a single §3 violation fails the run even at 12/12
MATCH. Items marked **NO TOOL TODAY** (M3, M4, M11) are expected MISS on today's build; a MATCH
on them means either a new tool landed (update this file and the spec) or the figure was invented
— check the citations before recording it as a pass.
