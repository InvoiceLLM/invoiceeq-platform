# Feature 31 — Invoice-family sub-types: credit / debit notes as adjustments, proforma as commitment, receipt as proof of payment

**App:** invoice-be (+ FE section §7) · **Status:** lives in `be_features_tracker.md` · **Depends on:** `feature_2_pipeline_extraction.md` (Gap 502 sign-aware verification), `feature_27_generic_extraction.md` (G9 `Invoice.doc_type`), `feature_30_business_intelligence.md` (net-position card, `v_overdue`), `feature_7_audit.md` (resolve endpoint).

**Founder rulings 2026-09-09:**
- "credit note should be considered something as paid or outstanding" → neither; it is an **adjustment** with its own lifecycle (§3).
- "should credit note be considered as invoice or a separate financial doc" → stays in `invoice` (Feature 27 A2), own doc type, own behaviour.
- "above has to fix for credit note as well as debit note" → both types, symmetric.
- "in dashboard it should be shown under paid and outstanding box respectively maybe with a small note" → no new tile; the **Paid** box carries a note for applied credit notes, the **Outstanding** box carries a note for open debit notes (§3.4).
- "we need to check what other docs comes under invoice family" → the MONEY family is INVOICE, PROFORMA_INVOICE, RECEIPT, CREDIT_NOTE, DEBIT_NOTE (`services/document_type_classifier.py`). "update the feature 31 for all above" → this spec covers all four non-INVOICE sub-types (§3.8, §3.9).

## 1. Overview

**Scope.** The four MONEY-family sub-types that today behave exactly like a tax invoice although none of them is one:

| Sub-type | What it is | Today | Target |
|---|---|---|---|
| CREDIT_NOTE | vendor reduces what we owe (negative) | COMPLETED, Mark as Paid offered, shrinks total invoiced | adjustment: OPEN_ADJUSTMENT → APPLIED / REFUNDED (§3.1–3.7) |
| DEBIT_NOTE | vendor increases what we owe (positive) | indistinguishable from an invoice | adjustment: OPEN_ADJUSTMENT → APPLIED (§3.1–3.7) |
| PROFORMA_INVOICE | request for payment before supply; not a tax document | counts as invoiced, outstanding, at-risk, can be marked paid, goes overdue | commitment: PROFORMA → SUPERSEDED when the tax invoice arrives (§3.8) |
| RECEIPT | proof that money was paid (cash memo, fiscal receipt, simplified invoice) | counts as outstanding, can go overdue | already paid: lands PAID with `paid_at` = receipt date (§3.9) |

Today a credit note is an ordinary `invoice` row with a negative `grand_total` and `doc_type = CREDIT_NOTE`: it shows as "Completed", offers **Mark as Paid**, shrinks "Total invoiced", and would count as at-risk if it ever carried an alert. A debit note (vendor bills extra) is the mirror image with a positive total and is indistinguishable from an invoice. Neither has a due date, so neither reaches `v_overdue`, which is the only thing that is correct by accident.

After this feature both are **adjustments** against a vendor balance: a credit note reduces what we owe, a debit note increases it. Each has its own status pair, its own action, its own place on the dashboard, and never asks to be "paid".

## 2. File coordinates

| File | Function / component | Change |
|---|---|---|
| `models.py` | `Invoice.applied_to_invoice_id: UUID \| None` (FK `invoice.id`, nullable, indexed), `Invoice.applied_at: datetime \| None` | add-only migration `a1b2c3f31001_adjustment_notes.py` |
| `services/adjustment_notes.py` (new) | `is_adjustment(doc_type)`, `ADJUSTMENT_DOC_TYPES = {"CREDIT_NOTE","DEBIT_NOTE"}`, `apply_note(db, note, target_invoice_id, actor)`, `mark_refunded(db, note, actor)`, `unapplied_notes(db, tenant_id, older_than_days)` | new |
| `queue_worker/handlers.py` | `handle_process_invoice()` | a CREDIT_NOTE / DEBIT_NOTE lands `OPEN_ADJUSTMENT` (not COMPLETED); `due_date` forced NULL; no near-duplicate check against invoices |
| `routers/invoices.py` | `POST /invoices/{id}/apply` (body `{target_invoice_id}`), `POST /invoices/{id}/refund` | new; 400 if the row is not an adjustment; target must be same tenant, same vendor, INBOUND, not an adjustment |
| `routers/audit.py` | `resolve_audit_invoice()` | rejects `PAID` for an adjustment row (400 "a credit/debit note is applied, not paid") |
| `routers/dashboard.py` | `get_dashboard_metrics()` | `total_invoiced` excludes adjustments; `paid_amount` unchanged plus `credits_applied` note; `outstanding_amount` = open invoices − open credit notes + open debit notes, plus `debits_open` note; `at_risk_amount` excludes adjustments |
| `alembic/versions/a1b2c3f30002_semantic_views.py` successor `a1b2c3f31002_views_adjustments.py` | `v_vendor_spend`, `v_overdue`, `v_3way_match` | `v_overdue` excludes adjustments explicitly (not by NULL due date); `v_vendor_spend` gains `credits`, `debits`, `net_spend` columns |
| `services/attachment_insights.py` | `card_net_position` | reads `applied_to_invoice_id` so an applied note is not netted twice |
| `agents/sage_prompts.py` | SQL rule 6 | states: adjustments carry `doc_type IN ('CREDIT_NOTE','DEBIT_NOTE')`, status `OPEN_ADJUSTMENT`/`APPLIED`/`REFUNDED`, answer gross and net when a vendor has open notes |
| `utils/alert_registry.py` | `unapplied_adjustment` | new soft alert type (severity warning), relabel-only, not flaggable as missed |
| `services/invoice_reconciliation.py` (or the nightly job) | `sweep_unapplied_adjustments()` | after 30 days OPEN_ADJUSTMENT → append `unapplied_adjustment` alert (soft), no status change |

## 3. Functionality

### 3.1 Status pair for adjustments
`OPEN_ADJUSTMENT` (set by the worker at extraction, replaces COMPLETED for these doc types) → `APPLIED` (via `/apply`, records `applied_to_invoice_id`, `applied_at`, one `AuditLog` row `APPLY_ADJUSTMENT`) or `REFUNDED` (via `/refund`, credit notes only, `AuditLog` `REFUND_CREDIT_NOTE`). `AUDIT_REQUIRED` still applies when extraction alerts fire; resolving it returns the row to `OPEN_ADJUSTMENT`, never to COMPLETED or PAID. `paid_at` is never set on an adjustment.

### 3.2 Sign convention (unchanged, made explicit)
A credit note's `grand_total`, `subtotal`, `tax_amount` and line amounts are **negative** as printed; a debit note's are **positive**. Nothing flips signs; every aggregate simply sums. Gap 502 keeps the line verifier sign-aware.

### 3.3 Vendor balance
`owed(vendor) = Σ open invoices + Σ open debit notes − Σ open credit notes`. An APPLIED or REFUNDED note is excluded (its effect is already in the invoice it settled or the refund received). Chat answers gross and net when any open note exists for the vendor, naming the notes.

### 3.4 Dashboard (founder ruling)
- **Total invoiced**: invoices only (`doc_type` not in adjustments).
- **Paid** box: unchanged figure; small note beneath: *"incl. ₹42,775 in credit notes applied"* when `credits_applied > 0` for the period. (An applied credit note is money you did not have to pay.)
- **Outstanding** box: figure = open invoices − open credit notes + open debit notes; small note beneath: *"incl. ₹X debit notes open"* when `debits_open > 0`, and *"₹42,775 credit notes not yet applied"* when `credits_open > 0`.
- **At-risk**: invoices only.
- Response keys added, all additive: `credits_applied`, `credits_open`, `debits_open`, `adjustment_count`.

### 3.5 Needs attention
Adjustments never appear as overdue. An OPEN_ADJUSTMENT older than 30 days carries the soft alert `unapplied_adjustment` ("Unapplied credit from Bharat Hardware, ₹42,775, 31 days") and therefore shows in the attention list until applied or refunded.

### 3.6 Reconciliation
`services/bank_matching.py`: a credit note matches a **credit** line (refund) on the statement, or explains a short payment on its applied invoice (invoice total − note = debit amount, within R5 tolerance). A debit note matches a debit line on its own or added to its applied invoice. Never a bare debit for a credit note.

### 3.7 Duplicate detection
Layer 2/3 run within the same doc type only (a credit note is never a duplicate of an invoice with the same total; a proforma and its tax invoice share number and total by design and must not flag each other, §3.8 links them instead).

### 3.8 PROFORMA_INVOICE, a commitment, not a payable
- Lands **`PROFORMA`** (new status) instead of COMPLETED. `due_date` kept (the requested payment date) but the row is **excluded** from `total_invoiced`, `outstanding_amount`, `at_risk_amount` and `v_overdue`. Mark as Paid rejected (400 "a proforma is not a payable; record the tax invoice or the receipt").
- **Supersession.** When a tax INVOICE from the same vendor arrives with the same number, or the same total within R5 tolerance and a date within 60 days, the worker sets `proforma.status = SUPERSEDED`, `proforma.superseded_by_invoice_id = <invoice.id>` and the invoice gets `proforma_id` back; the invoice's insight card "Agreed vs billed" compares the two (price drift between proforma and final invoice is a finding, Feature 30 R2 rules apply).
- **Advance paid against a proforma** (bank debit matching the proforma total before the invoice exists): bank matching records an **advance** on the vendor (`bank_statement_line.matched_invoice_id` = proforma id, `match_kind = ADVANCE`); when the tax invoice arrives the advance is netted in the vendor balance (§3.3): `owed(vendor) −= advances`.
- Chat: "what do we owe X" never counts a PROFORMA; "what have we committed to X" does. Prompt rule 6 states both.
- Attention: a PROFORMA older than 45 days with no superseding invoice and no advance → soft alert `stale_proforma` (relabel-only, not flaggable as missed).

### 3.9 RECEIPT, proof of payment
- Lands **`PAID`** directly: `paid_at` = receipt date (`invoice_date`), `paid_source = RECEIPT` (new nullable column). Never COMPLETED; never AUDIT_REQUIRED for a missing buyer / unit price / VAT amount (Feature 27's relaxed rubric already suppresses those; this closes the loop so the relaxed rubric does not land the row in review for `missing_required_field`).
- Included in `paid_amount` and in spend; excluded from `outstanding_amount`, `at_risk_amount`, `v_overdue`.
- **Linking.** If an open INVOICE from the same vendor matches the receipt total within R5 tolerance and a date within 30 days, the receipt is applied to it: invoice → PAID, `paid_at` = receipt date, `paid_source = RECEIPT`, `receipt.applied_to_invoice_id` = invoice. A linked receipt then contributes nothing further to `paid_amount` (no double counting of the same money).
- **Bank matching**: a receipt matches a bank **debit** of its total (±R5); an unlinked receipt with no bank debit after 30 days → soft alert `receipt_without_payment_trace` (relabel-only).
- Chat: receipts answer "what did we pay in cash / by card in August" and are cited as the evidence for a PAID invoice.

### 3.10 Status vocabulary, complete
`Invoice.status` for the MONEY family after this feature: INVOICE → PROCESSING / COMPLETED / AUDIT_REQUIRED / PAID / REJECTED / DUPLICATE (unchanged); CREDIT_NOTE, DEBIT_NOTE → OPEN_ADJUSTMENT / APPLIED / REFUNDED (+ AUDIT_REQUIRED, DUPLICATE); PROFORMA_INVOICE → PROFORMA / SUPERSEDED (+ AUDIT_REQUIRED, DUPLICATE); RECEIPT → PAID (+ AUDIT_REQUIRED for arithmetic alerts only, DUPLICATE). `services/adjustment_notes.py` becomes `services/invoice_subtypes.py` and owns `status_after_extraction(doc_type)`, `may_mark_paid(doc_type)`, `counts_in(metric, doc_type, status)`: one table consulted by the worker, the audit resolve endpoint, the dashboard and the views, so no consumer re-derives the rules.

## 4. Data & schema changes (add-only)
Migration `a1b2c3f31001`: `invoice.applied_to_invoice_id UUID NULL REFERENCES invoice(id)`, index `(tenant_id, applied_to_invoice_id)`; `invoice.applied_at TIMESTAMP NULL`; `invoice.superseded_by_invoice_id UUID NULL REFERENCES invoice(id)`; `invoice.proforma_id UUID NULL REFERENCES invoice(id)`; `invoice.paid_source VARCHAR(16) NULL` (AUDIT / RECEIPT / BANK); `bank_statement_line.match_kind VARCHAR(16) NULL` (PAYMENT / REFUND / ADVANCE). No backfill: existing credit notes keep COMPLETED until re-uploaded or until the founder runs the optional one-off `scripts/reclassify_adjustments.py` (COMPLETED + doc_type in adjustments → OPEN_ADJUSTMENT). Views recreated by `a1b2c3f31002`.

## 5. Tasks
- [ ] 31.1 Migration + model fields + `services/adjustment_notes.py`
- [ ] 31.2 Worker: adjustments land OPEN_ADJUSTMENT, due_date NULL, duplicate layers scoped by doc type
- [ ] 31.3 `/apply`, `/refund`; audit resolve rejects PAID for adjustments
- [ ] 31.4 Dashboard metrics per §3.4 (+ Postgres test with one invoice, one applied credit, one open credit, one open debit)
- [ ] 31.5 Views `a1b2c3f31002`; semantic views tests updated
- [ ] 31.6 Chat: prompt rule + full-record block shows adjustments with their state; golden case "what do we owe Bharat after the credit note" → 60,416 with both documents cited
- [ ] 31.7 `unapplied_adjustment` alert + nightly sweep + registry entry
- [ ] 31.8 Bank matching per §3.6 (+ test: refund credit line ↔ credit note; short payment ↔ invoice − note)
- [ ] 31.9 Insight `card_net_position` respects applied notes
- [ ] 31.10 FE (§7)
- [ ] 31.11 `scripts/reclassify_subtypes.py` (dry-run default): COMPLETED + CREDIT/DEBIT → OPEN_ADJUSTMENT; COMPLETED + PROFORMA → PROFORMA; COMPLETED + RECEIPT → PAID with `paid_source` RECEIPT
- [ ] 31.12 PROFORMA status, exclusion from the four metrics and `v_overdue`, Mark-as-Paid rejection, supersession by the tax invoice (number, or total + date window), `stale_proforma` alert (§3.8)
- [ ] 31.13 RECEIPT lands PAID with `paid_source`, links to an open invoice by total + date, `receipt_without_payment_trace` alert, bank debit matching (§3.9)
- [ ] 31.14 `services/invoice_subtypes.py` single rules table (§3.10) + a test that every consumer (worker, audit resolve, dashboard, views) agrees with it
- [ ] 31.15 Advance-against-proforma in bank matching and vendor balance (§3.8)

## 6. Verification plan
Real Postgres. Seed: BHA-2002 (paid), BHA-2003 (open 103,191), BHF-CN-2010 (−42,775), a debit note DN-1 (+5,000) for Bharat. Assert: dashboard `total_invoiced` = 206,382; `outstanding_amount` = 103,191 − 42,775 + 5,000 = 65,416; `credits_open` = 42,775; after `/apply` on BHA-2003 → `credits_applied` = 42,775, `credits_open` = 0, `outstanding_amount` = 65,416 still (the credit is now inside the invoice's remaining balance); `v_overdue` never lists the notes; `PUT /audit/resolve` with PAID on the note → 400; chat "what do we owe Bharat" → 65,416 naming BHA-2003, BHF-CN-2010, DN-1. Ingestion of the note → status OPEN_ADJUSTMENT, no alerts (Gap 502).

Proforma / receipt (same tenant): seed PF-77 (proforma, Rajesh, 437,190, dated 1-Aug) and a cash memo RC-9 (receipt, Om Stationery, 4,800, dated 20-Aug) plus OM -2001 open. Assert: PF-77 status PROFORMA, absent from `total_invoiced` / `outstanding_amount` / `v_overdue`; resolve PAID on it → 400; upload RAJ-2008 (same total, 20-Aug) → PF-77 SUPERSEDED, `superseded_by_invoice_id` = RAJ-2008, RAJ-2008 `proforma_id` = PF-77, no possible_duplicate alert between them; RC-9 status PAID, `paid_source` RECEIPT, `paid_amount` += 4,800, absent from outstanding; a receipt of 41,654 dated 17-Aug for Om → OM -2001 becomes PAID with `paid_source` RECEIPT and the receipt no longer counts in `paid_amount`. Chat "what do we owe Rajesh" before RAJ-2008 → 0 with PF-77 named as a commitment; after → 437,190.

## 7. FE section (FE Feature 22, `apps/invoice-fe/docs/feature_22_credit_debit_notes.md` to be written from this)
- Invoice list / recent invoices: "Credit Note" / "Debit Note" badge; negative totals in credit colour; status chip Open adjustment / Applied / Refunded; action menu: **Apply to invoice…** (picker limited to the same vendor's open invoices), **Mark refunded** (credit only); no Mark as Paid.
- Review console: header "Credit Note (against BHA-2002)" when `referenced_documents` names one; totals block negative; line "Reduces Bharat Hardware balance by ₹42,775".
- Dashboard: Paid and Outstanding boxes render the small notes from §3.4 when the keys are non-zero; nothing else changes.
- Needs attention: `unapplied_adjustment` rows with an **Apply** shortcut.
- Ingestion ledger: doc-type badge already shown (FE Gap 378); total renders negative (FE Gap 477).
- Proforma: badge "Proforma", status chip Proforma / Superseded (the superseding invoice number as a link); no Mark as Paid; list filter "Commitments" groups proformas with POs.
- Receipt: badge "Receipt", status chip Paid with a "via receipt" sub-label; a linked invoice row shows "Paid by receipt RC-9" in the audit console.
- Dashboard notes (§3.4) extended: the Paid box also notes "incl. ₹X paid by receipt"; the Outstanding box excludes proformas and shows "₹Y committed (proforma)" as a small note when any PROFORMA is open.
