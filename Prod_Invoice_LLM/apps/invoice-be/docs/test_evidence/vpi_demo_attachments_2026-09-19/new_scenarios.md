# VPI demo — 11 NEW chat-attachment scenarios (control set for the generic fix)

Authored 2026-09-19 as the **control** for the fixes made after
`README.md` (this directory). The founder's instruction on those fixes was
*"can these have generic fix, dont fix on the test case based fields."*
Re-running the original 11 turns cannot tell a real fix from one shaped to
those 11 cases. **These 11 are different questions, different document→question
pairings, and different answer shapes, aimed at the *rules* the fixes claim to
establish.** None of them is a re-run of a §5 turn.

**Ground truth below was computed by querying Postgres directly**
(`postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db`, tenant
`00000000-0000-0000-0000-000000000000`, 26 invoices, read-only) and by reading
`showcase/vpi_demo/make_financial_docs.py` for what each attachment actually
prints. **No figure here was taken from a product answer.** Every derivation is
shown in §3 so a reader can re-check the arithmetic.

`as_of` for every date-dependent expectation: **2026-09-15** (same convention as
README §6), except scenario 11 which names 15-Sep explicitly in the question.

---

## 1. The rules under test

| Rule | What it means | Scenarios |
|---|---|---|
| **R1 — a PAID invoice is never a term in "amount owed"** | The worst defect found (₹1,63,607 where truth was ₹60,416). Tested in four shapes, not one. | 1, 2, 3, 4, 7, 8, 11 |
| **R2 — direction comes from the data, not from whose name is on the page** | Ambiguous party, tenant's own name, no party at all. | 5, 6 |
| **R3 — a document with content but no invoice references is still usable** | The bank statement failed here; the credit note has the same property. | 2, 6, 11 |
| **R4 — "still reading" is never rendered as "ambiguous"** | Asking before extraction reaches a terminal state must show a *processing* state, not the read-vs-compare card and not an abstention. | 4 |
| **R5 — an honest "I cannot tell" is a correct answer** | Two cases where abstention is *right*, so a good refusal can be told apart from a capability gap. The old set had none. | 9, 10 |
| **R6 — the same question, two phrasings, one answer** | Routing keyword-matches the sentence today; 7 and 8 are the same question and must return the identical figure. | 7, 8 |

**R1 has a subtlety that must be honoured:** on this tenant **every INBOUND PAID
row has `paid_at = NULL`** — `status = 'PAID'` is the *only* payment signal on the
payable side. A fix that keys the exclusion off `paid_at` will pass nothing here.
(Verified: `BHA-2002`, `OM -2000`, `SHR-2004` all `status='PAID'`, `paid_at IS NULL`.
Only the two OUTBOUND paid rows carry a `paid_at`.)

---

## 2. The scenarios (README §5 table shape — executable the same way)

| # | Attach | Ask | Expected bubble |
|---|---|---|---|
| 1 | `upload/PO_PO-VPI-1043_SHR.pdf` | "Going by this order, how much of Shree Packaging's balance is still unpaid?" | **₹2,44,614.00** — SHR-2005 1,21,894 + SHR-2006 1,22,720. SHR-2004 (1,21,894, `PAID`) carries the *identical lines to this PO* and must be named and then **excluded**. **3,66,508 is the fail.** Rule: R1 (mixed paid/open vendor) |
| 2 | `upload/BankStatement_HDFC_4471_Aug2026.pdf` | "Of the vendor payments on this statement, is any of them still showing as unpaid in our books?" | **No — ₹0.00 outstanding across all three.** The statement's three NEFT DR vendor lines are OM -2000 41,654 (05-Aug), BHA-2002 1,03,191 (06-Aug), SHR-2004 1,21,894 (07-Aug); all three are `status='PAID'`. **2,66,739 — or any non-zero — is the fail.** The statement prints invoice numbers only inside narration text, never as a reference list, and must still be usable. Rules: R1 (all-paid shape), R3 |
| 3 | `upload/PA_PA-VPI-0072_BHA.pdf` | "After this advice, what's left on our Bharat Hardware account?" | **₹1,03,191.00 — BHA-2003, one open invoice.** BHA-2002 (the invoice this advice settles, same amount) is `PAID` and is not a term. **2,06,382 is the fail.** Rule: R1 (exactly one open invoice) |
| 4 | `upload/DC_DC-NMT-2291_NAT.pdf` | Turn A, sent **immediately on attach, before extraction reaches a terminal state**: "Check this against what National MRO invoiced us." Turn B, re-sent after `extraction_status` is terminal: same sentence. | **Turn A: a *processing* state** — "still reading this document", with no question back to the user. The read-vs-compare card, an abstention, or a ₹0 are all fails: nothing about this document is ambiguous, it is merely not read yet. **Turn B: 5 / 12 / 8 delivered = NAT-2006, ₹79,956.80 owed.** NAT-2007 is the same date and same total, `AUDIT_REQUIRED`, `possible_duplicate` of NAT-2006 — named, not added. **1,59,913.60 is the fail.** The challan cites **PO-VPI-1039, not on file** → order leg `NOT_CHECKED`, so this is not a clean 3-way match. Rules: R4, R1 (duplicate exclusion) |
| 5 | `upload/PO_PO-VPI-1041_RAJ.pdf` | "Is this a sales order one of our customers sent us, or a purchase we placed?" | **A purchase VPI placed**, with Rajesh Steel Corporation as the supplier. The tenant's own name is the most prominent party on the page (printed as **Buyer**, and again in the "Ship to" line and the "Authorised by" line) — that must not make this outbound. The evidence is in the data: the matching invoice RAJ-2008 is `flow_direction='INBOUND'` with `vendor_name='Rajesh Steel Corporation'`; VPI appears as `vendor_name` only on OUTBOUND rows and never as a counterparty. Rajesh is not a customer. Rule: R2 (tenant's own name on the page) |
| 6 | `upload/BankStatement_HDFC_4471_Aug2026.pdf` | "This statement has no party column. Which of these lines are money we owed and which are money owed to us?" | **Payables side (money out), 3 lines, ₹2,66,739.00:** OM -2000 41,654 · BHA-2002 1,03,191 · SHR-2004 1,21,894 — all INBOUND, all `PAID`. **Receivables side (money in), 3 lines, ₹11,97,985.00:** VPI-OUT-2012 4,83,210 (09-Aug) · VPI-OUT-2015 5,14,775 (11-Aug) · a 2,00,000 advance naming VPI-OUT-2018 — all OUTBOUND. **Neither side, 6 lines, ₹18,25,910.00:** GST 1,84,320 · electricity 96,410 · salary 14,86,000 · AMC 58,000 · bank charges 1,180 — these match no invoice and must be reported as unmatched, not forced onto a ledger side. The account holder named on the document is **VPI itself**, which is not a counterparty. Rules: R2 (party absent), R3 |
| 7 | `upload/PA_PA-VPI-0071_OM.pdf` | "What do we still owe Om Stationery Mart?" | **₹70,446.00** — OM -2001 41,654 + OM -2002 28,792. OM -2000 41,654 (the invoice this advice settles) is `PAID` and excluded. **1,12,100 is the fail.** Must not list unrelated OUTBOUND receivables. Rules: R1, R6 (phrasing A) |
| 8 | `upload/PA_PA-VPI-0071_OM.pdf` | "What is our outstanding payable balance with Om Stationery Mart?" | **Identical to #7: ₹70,446.00**, same two invoices. Same attachment, same question, different words. **Any divergence between #7 and #8 — different figure, one answering and one abstaining, one listing receivables — is a fail even if one of the two is right.** Rule: R6 (phrasing B) |
| 9 | `upload/DC_DC-RSC-0812_RAJ.pdf` | "What's the rupee value of this delivery, going by the challan itself?" | **"I cannot tell from this document"** — and that is the *correct* answer. The challan's table is `Description · HSN · Qty ordered · Qty delivered · Unit`: **no rate column, no amount column, no total anywhere on the page**. A correct answer says the document carries no values, and *may* add that the matching invoice RAJ-2008 prices the same quantities at ₹4,37,190.00 — **explicitly labelled as coming from the invoice, not from the challan**. Any figure presented as the challan's own value is a fail; so is ₹0.00. Rule: R5 (honest abstention) |
| 10 | `invoices_pdf/inbound_creditnote_BharatHardware_BHF-CN-2010.pdf` | "Which invoice number does this credit note quote?" | **"It doesn't quote one"** — the correct answer is an abstention on the literal question. The document's closing line reads *"This credit note reduces the balance owed on the referenced invoice"* but **no invoice number is printed anywhere on it** (verified against the PDF text). A correct answer says so, and may then offer the inference — BHA-2003 over BHA-2002, same 17-Aug date, still open — **clearly marked as an inference, not as something read off the page**. Naming a number as if it were printed is a hallucination and a fail. Rules: R5 (honest abstention), R3 |
| 11 | `invoices_pdf/inbound_creditnote_BharatHardware_BHF-CN-2010.pdf` | "Bharat sent this. Does it change what we pay on the 15 September run?" | **Yes. Bharat's line in that run drops from ₹1,03,191.00 to ₹60,416.00; the run total drops from ₹7,83,885.80 to ₹7,41,110.80.** The note resolves to **BHA-2003** (17-Aug, due 15-Sep, open) and not to the identical-line BHA-2002 (`PAID` 06-Aug) — both must be named, with the reason for the choice. **BHA-2002 must not be a term.** No `Invoice` row is created and no aggregate moves (Feature 26 D2/D3): Bharat spend stays 2,06,382 and BHA-2003 stays open at 1,03,191. The note's own arithmetic is correct and must raise **no** line-math alert (Gap 502). Rules: R1, R3 |

---

## 3. Derivations — every figure above, worked from the database

Base query (read-only), run 2026-09-19:

```sql
SELECT invoice_number, flow_direction, vendor_name, customer_name,
       invoice_date, due_date, subtotal, tax_amount, grand_total, status
FROM invoice
WHERE tenant_id = '00000000-0000-0000-0000-000000000000'
  AND deleted_at IS NULL
ORDER BY flow_direction, invoice_number;          -- 26 rows
```

Payment status on the tenant, as it actually is in the table:

| status | invoices |
|---|---|
| `PAID` | BHA-2002, OM -2000, SHR-2004 (inbound, `paid_at IS NULL`); VPI-OUT-2012, VPI-OUT-2015 (outbound, `paid_at` set) |
| `AUDIT_REQUIRED` | NAT-2007, RAJ-2009 — both `sa_alerts[].type = 'possible_duplicate'` |
| `NEEDS_REVIEW` | VPI-OUT-2014 — `tax_mismatch`, 4,09,500 + 73,710 ≠ 4,83,850 |
| `COMPLETED` / `VERIFIED` | the remaining 18, all open |

Per-vendor inbound split:

```sql
SELECT vendor_name, COUNT(*), SUM(grand_total) AS total,
       SUM(CASE WHEN status  = 'PAID' THEN grand_total ELSE 0 END) AS paid,
       SUM(CASE WHEN status <> 'PAID' THEN grand_total ELSE 0 END) AS open_incl_dupes,
       SUM(CASE WHEN status NOT IN ('PAID','AUDIT_REQUIRED')
                THEN grand_total ELSE 0 END)                       AS open_clean
FROM invoice
WHERE tenant_id = '00000000-0000-0000-0000-000000000000'
  AND deleted_at IS NULL AND flow_direction = 'INBOUND'
GROUP BY 1 ORDER BY 1;
```

| vendor | n | total | paid | open (incl. dupes) | open (clean) |
|---|---|---|---|---|---|
| Bharat Hardware & Fasteners | 2 | 2,06,382.00 | 1,03,191.00 | 1,03,191.00 | **1,03,191.00** |
| Ganesh Bearings Pvt Ltd | 2 | 1,72,044.00 | 0.00 | 1,72,044.00 | 1,72,044.00 |
| National MRO Traders | 2 | 1,59,913.60 | 0.00 | 1,59,913.60 | **79,956.80** |
| Om Stationery Mart | 3 | 1,12,100.00 | 41,654.00 | 70,446.00 | **70,446.00** |
| Rajesh Steel Corporation | 2 | 8,74,380.00 | 0.00 | 8,74,380.00 | 4,37,190.00 |
| Shree Packaging Industries | 3 | 3,66,508.00 | 1,21,894.00 | 2,44,614.00 | **2,44,614.00** |

**Scenario 1** — Shree: 1,21,894 (SHR-2005) + 1,22,720 (SHR-2006) = **2,44,614.00**.
Cross-check: 3,66,508 total − 1,21,894 paid = 2,44,614. ✔
The trap is that PO-VPI-1043 was raised for SHR-2005's lines, and SHR-2004 carries
the *same three lines at the same rates* — so line-identity matching surfaces the
paid invoice as a candidate. It is a correct candidate to surface and a wrong
term to sum.

**Scenario 2** — the statement's three vendor debits, matched by the invoice
number printed verbatim in each narration:
41,654.00 (`INV OM -2000`) + 1,03,191.00 (`INV BHA-2002`) + 1,21,894.00 (`INV SHR-2004`)
= 2,66,739.00 — of which **2,66,739.00 is `PAID`**, so outstanding = 2,66,739.00 −
2,66,739.00 = **0.00**. The all-paid shape: the naive sum and the truth differ by
the entire amount.

**Scenario 3** — Bharat: 2,06,382.00 total − 1,03,191.00 (BHA-2002, `PAID`) =
**1,03,191.00**, a single open invoice (BHA-2003, due 15-Sep). The one-open shape
is included deliberately: a fix that drops *all* candidates, or that returns 0
whenever any candidate is paid, fails here while passing scenario 2.

**Scenario 4** — National MRO: NAT-2006 79,956.80 `COMPLETED`; NAT-2007 79,956.80
`AUDIT_REQUIRED` with `possible_duplicate` naming NAT-2006 ("same date and total
… different number"). Owed = 1,59,913.60 − 79,956.80 = **79,956.80**. Challan
quantities 5 / 12 / 8 come from `LINES["NAT-2006"]` in `make_financial_docs.py`
(Industrial Lubricant 20L ×5, Replacement V-Belts ×12, Safety Gloves ×8) and are
emitted identically into `Qty ordered` and `Qty delivered` — so there is no
shortage. `delivery_challan(..., po_no="PO-VPI-1039")`, and no invoice row on this
tenant has `po_number = 'PO-VPI-1039'` (all 26 rows have `po_number IS NULL`),
so the order leg is `NOT_CHECKED`.

**Scenario 5** — direction evidence, from the table not the page:
`RAJ-2008.flow_direction = 'INBOUND'`, `vendor_name = 'Rajesh Steel Corporation'`,
`customer_name IS NULL`. `'Vishwa Precision Industries Pvt Ltd'` appears as
`vendor_name` on the 12 OUTBOUND rows and **never** as `vendor_name` or
`customer_name` on an INBOUND row, i.e. the tenant is never its own counterparty.
On the page, `purchase_order()` prints VPI as **Buyer**, in the **Ship to** line
and in the **Authorised by** line — three mentions to Rajesh's one.

**Scenario 6** — the 12 statement rows from `bank_statement()`, classified:

| side | lines | amount |
|---|---|---|
| payable (Dr, matches an INBOUND invoice) | OM -2000 41,654 · BHA-2002 1,03,191 · SHR-2004 1,21,894 | **2,66,739.00** |
| receivable (Cr, matches an OUTBOUND invoice) | VPI-OUT-2012 4,83,210 · VPI-OUT-2015 5,14,775 · VPI-OUT-2018 advance 2,00,000 | **11,97,985.00** |
| neither (no invoice) | GST 1,84,320 · electricity 96,410 · salary 14,86,000 · AMC 58,000 · charges 1,180 | **18,25,910.00** |

Balance check: 12,50,000 opening − 20,92,649 withdrawals + 11,97,985 deposits =
**3,55,336.00** closing, 31-Aug-2026. (Withdrawals: 1,84,320 + 41,654 + 1,03,191 +
1,21,894 + 96,410 + 14,86,000 + 58,000 + 1,180 = 20,92,649.) ✔ matches README §5.

**Scenarios 7 and 8** — Om: 1,12,100.00 − 41,654.00 (OM -2000, `PAID`) =
**70,446.00** = OM -2001 41,654 + OM -2002 28,792. Identical expected value for
both phrasings, by construction.

**Scenario 9** — from `delivery_challan()`:
`rows = [["Description","HSN","Qty ordered","Qty delivered","Unit"]]` and the row
builder is `[d, h, str(q), str(q), "Nos"]` — the rate `_` is explicitly discarded.
There is **no monetary figure of any kind on the document**. The referenced
invoice RAJ-2008 totals 4,37,190.00, which is the only place the value exists.

**Scenario 10** — full PDF text of the credit note (pypdf): doc # `BHF-CN-2010`,
date 17-Aug-2026, one line `Hex Bolts M10x40, box 100 · 7318 · 25 · 1,450.00 ·
-Rs. 36,250.00`, subtotal −36,250.00, CGST −3,262.50, SGST −3,262.50, total
−42,775.00, closing sentence *"This credit note reduces the balance owed on the
referenced invoice."* **The string "the referenced invoice" is the trap** — it
promises a reference the document never supplies.

**Scenario 11** — the 15-Sep payment run, clean payables due that day:

```sql
SELECT invoice_number, grand_total FROM invoice
WHERE tenant_id = '00000000-0000-0000-0000-000000000000' AND deleted_at IS NULL
  AND flow_direction = 'INBOUND' AND due_date = '2026-09-15'
  AND status NOT IN ('PAID','AUDIT_REQUIRED');
```

BHA-2003 1,03,191.00 + NAT-2006 79,956.80 + OM -2001 41,654.00 + RAJ-2008
4,37,190.00 + SHR-2005 1,21,894.00 = **7,83,885.80** ✔ (matches README §4/§6 #5).
Credit note applied: 1,03,191.00 − 42,775.00 = **60,416.00** on Bharat's line;
run total 7,83,885.80 − 42,775.00 = **7,41,110.80**.
BHA-2002 is `PAID`, is not due on 15-Sep, and is not a term in either figure.

---

## 4. What the demo data cannot cover

| Wanted | Why it can't be done today | What would fix it (described, **not generated**) |
|---|---|---|
| **A counterparty where *everything* is paid** | No such counterparty exists. Every one of the 6 vendors and 3 customers has at least one open invoice: Bharat 1/2 paid, Om 1/3, Shree 1/3, Kaveri 1/4, Sunrise 1/4; Rajesh, Ganesh, National MRO, Deccan have **none** paid. Scenario 2 reaches the all-paid shape by *document* scope (the statement's three vendor debits) rather than by vendor, which is a genuine test of the rule but not the vendor-level shape. | Mark a small existing vendor fully paid, or add a one-invoice vendor already settled. The cheapest real option: mark **OM -2001 and OM -2002 PAID** in the audit console as an extra step, making Om a fully-settled vendor and turning scenario 7/8's answer into ₹0.00. That changes §6 answers 1/2/13/19, so it must be a separate run, not the standing demo state. |
| **`recurring` / `estimated` forecast tiers** | **Known-unbuilt.** Only one bank statement exists (August). Task 33.38 (June + July statements) is still pending, so `detect_recurrence()` never reaches its ≥3-month depth. Every scenario above stays clear of these tiers; scenario 6 deliberately stops at "neither side, unmatched" and does not ask whether salary/GST/electricity recur. | Task 33.38, already specified. |
| **A cash position later than 31-Aug-2026** | No September bank statement. Any "what's our cash today" question is unanswerable by construction, so it would test the abstention path rather than the rules here. Noted as a *candidate third abstention* if more R5 coverage is wanted — but it is an abstention forced by missing data, which is weaker evidence than 9 and 10, where the data exists and only the *document* is silent. | Same fixture as 33.38, extended to September. |
| **A short delivery / over-delivery** | `delivery_challan()` writes `Qty delivered = Qty ordered` for every line of all three challans, by design ("all clean matches", founder 2026-09-08). No quantity variance exists anywhere in the fixture set. | A fourth challan with one line short-delivered. Not generated. |
| **A partial payment applied to a balance** | The 2,00,000 Deccan advance is *recorded but not applied* — partial-payment application was Feature 31, **cancelled 2026-09-14**. Scenario 6 therefore reports the advance as a receivable-side line and does not expect VPI-OUT-2018's balance to move. | Out of scope by founder ruling; do not test. |
| **A multi-invoice payment advice** | `payment_advice()` takes exactly one `inv_no`; all three advices settle a single invoice. The "advice covers several invoices, some already paid" shape — a strong R1 test — has no fixture. | A fourth advice listing two or three invoices. Not generated. |
| **`DC_DC-BHF-0455_BHA.pdf`** | Deliberately unused here. Its `items[]` extracts as `[]` against a 3-line table (README root cause 3) — an extraction defect, so any scenario on it would measure extraction, not the rules above, and would fail for the wrong reason. Re-test it separately once root cause 3 is closed. | — |
| **`PO_PO-VPI-1042_GBP.pdf`** | Usable, just not needed: Ganesh has nothing paid, so it adds no R1 shape the other scenarios lack. If an extra is wanted, "how much of *this order* is still unpaid?" is **₹68,676.00** (GBP-2011, on this PO) and must **not** include GBP-2012 (₹1,03,368.00, a later, different order) — a scope test rather than a paid-exclusion test; vendor-wide open is ₹1,72,044.00. | — |

---

## 5. How to run these

Same harness as the original set: `run_vpi_turns.py` in this directory — one fresh
chat session per row, attach, poll `extraction_status` to terminal, ask the exact
question, auto-confirm the "confirm which one" card once and re-ask.

Two deviations this set needs:

1. **Scenario 4 must send turn A *without* polling to terminal** — that is the whole
   point of R4. The harness's poll-then-ask loop has to be bypassed for that one row,
   and both bubbles (A and B) captured.
2. **Scenarios 7 and 8 must run as two independent sessions** against the same
   attachment, and the comparison between them is part of the result, not a
   side note.

**Pre-flight, both from the original run's findings:** confirm the queue worker
(`python -m queue_worker.main_worker`) is live before the first attachment — with it
down every attachment sits at `PENDING`/`OTHER` forever and every row fails for an
environment reason. And re-run the aggregate check before and after, to confirm
nothing was written: INBOUND 14 / 18,91,327.60, OUTBOUND 12 / 52,48,631.00,
Bharat spend 2,06,382.00, and zero invoice rows matching `BHF-CN%`.
