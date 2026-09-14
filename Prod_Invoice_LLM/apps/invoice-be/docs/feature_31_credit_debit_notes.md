# Feature 31 — Only invoices are ledger records: credit / debit notes, proformas and receipts are reconciliation inputs, not payables

> **CANCELLED 2026-09-14 — founder ruling.** "Only invoice documents should be ingested" is a matter of **user training**, not code: the ingestion doors (upload, email, Drive, API) are for invoices; a credit / debit note, proforma or receipt is attached in chat, where the existing Feature 26 comparison and Feature 30 cards tell the user what it means for the impacted invoice, and the user acts by hand. No routing change, no schema change, no new lifecycle. The guidance lives in the Help Center (FE Gap 259 articles), the first-run onboarding (FE Feature 22 `FirstRun`) and Feature 33 §3.5's input requests ("forward invoices here"). Known, accepted: `CARDS_BY_DOC_TYPE` has no bubble card for `PROFORMA_INVOICE` or `RECEIPT` (they still get the comparison turn); add as a Feature 30 gap only if customers attach those. The spec below is kept for the record only.


**App:** invoice-be (+ FE section §7) · **Status:** lives in `be_features_tracker.md` · **Depends on:** `feature_27_generic_extraction.md` (E10 `documents` routing, G9 `Invoice.doc_type`; A2's schema ruling kept, its storage consequence superseded here), `feature_26_chat_attached_documents.md` (attachment path, D2/D3), `feature_30_business_intelligence.md` (`card_net_position`, the claim renderer 30.20), `feature_2_pipeline_extraction.md` (Gap 502 sign-aware verification).

**Rewritten 2026-09-14.** The 2026-09-09 version of this spec made credit / debit notes adjustments with their own status pair, gave proformas a `PROFORMA → SUPERSEDED` lifecycle and let receipts land `PAID` — four sub-types living in the `invoice` table with their own workflows. The founder reversed that on 2026-09-14:

> "only invoice needs to be stored and all other documents should be considered to make some decisions or intelligence based on reconciliation with the impacted invoice uploaded in the system" … "only when these documents are attached in chat the system will suggest the end user, end user can take manual decision based on the intelligence shared."

So: **INVOICE is the only document that becomes a ledger row.** A credit note, debit note, proforma or receipt is never a payable, never has a status, never moves a metric and is never applied by the system. It is a document a person attaches in chat to be told what it means for the invoice it touches; the person then acts on the invoice by hand. Nothing in the old spec's lifecycle, endpoints, alerts, bank-matching extensions or dashboard notes survives.

## 1. Overview

| Sub-type | What it is | Today (wrong) | After |
|---|---|---|---|
| CREDIT_NOTE | vendor reduces what we owe | an `invoice` row: "Completed", Mark as Paid offered, shrinks Total invoiced | a `documents` row; attached in chat → "reduces BHA-2003 by ₹42,775"; person edits / settles the invoice |
| DEBIT_NOTE | vendor increases what we owe | an `invoice` row indistinguishable from an invoice | a `documents` row; attached in chat → "adds ₹5,000 to BHA-2003"; person decides |
| PROFORMA_INVOICE | request for payment before supply; not a tax document | an `invoice` row: outstanding, at-risk, goes overdue, can be marked paid | a `documents` row; attached in chat → "agreed ₹437,190 on 1-Aug; tax invoice RAJ-2008 bills ₹441,020 — 0.9% above" |
| RECEIPT | proof that money was paid | an `invoice` row: outstanding, can go overdue | a `documents` row; attached in chat → "matches open OM-2001 (₹4,800, 20-Aug) — mark it paid?"; person clicks Mark as Paid |

**The one rule.** `LEDGER_DOC_TYPES = {"INVOICE"}`. Every consumer that asks "is this a payable" asks that one constant (§3.1). The MONEY family (`DOC_TYPE_FAMILY`) is unchanged and still governs **extraction**: a credit note is still read with `InvoiceExtractionSchema` and Gap 502's sign-aware arithmetic (Feature 27 A2), because that is what makes its figures trustworthy when it is reconciled. A2 decided the *schema*; it no longer decides the *table*.

**What this is not.**
- Not an accounting ledger for adjustments. No `OPEN_ADJUSTMENT`, no `/apply`, no `/refund`, no `applied_to_invoice_id`, no vendor-balance netting in the dashboard. Dropped, not deferred.
- Not automatic reconciliation. The system never changes an invoice's money fields or status because a note or receipt arrived. It suggests; a person acts through the surfaces that already exist (Mark as Paid, the review console's edits, Reject).
- Not ingestion-time intelligence. A credit note that arrives by email or Drive is stored and visible; nothing links it to an invoice until someone attaches it in chat (founder ruling). Feature 33's tenant-scope run may later read these `documents` rows as facts — that is Feature 33's decision, not this feature's behaviour.

## 2. File coordinates

| File | Function / component | Change |
|---|---|---|
| `services/ledger_scope.py` (new) | `LEDGER_DOC_TYPES: frozenset[str] = frozenset({"INVOICE"})`, `is_ledger_doc_type(doc_type) -> bool`, `is_reconciliation_doc_type(doc_type) -> bool` (MONEY family minus ledger) | the single rules table; fail-closed: `None` → ledger (today's behaviour), out-of-vocabulary → ledger + warning, same as `_routes_to_documents_table` |
| `queue_worker/handlers.py` | `_routes_to_documents_table()` | `return not is_ledger_doc_type(doc_type)` — the four sub-types now take the E10 path (`documents` row, placeholder `invoice` row deleted in the same transaction) |
| `queue_worker/handlers.py` | `_should_persist_coordinates()` | unchanged (MONEY family still gets `prebuilt-invoice`-labelled boxes, which are correct for a credit note) |
| `queue_worker/handlers.py` | `_persist_non_invoice_document()` | already persists `grand_total`, `subtotal`, `tax_amount`, `currency`, `doc_number`, `doc_attributes`; nothing new. A2's richer `InvoiceExtractionSchema` output for these types is stored in `doc_attributes` verbatim so the reconciliation cards read the same figures the verifier checked |
| `services/document_type_classifier.py` | — | untouched. `DOC_TYPE_FAMILY` stays as is |
| `services/attachment_insights.py` | `CARDS_BY_DOC_TYPE["PROFORMA_INVOICE"]`, `["RECEIPT"]`; `card_agreed_vs_billed()`, `card_payment_evidence()` (new) | CREDIT_NOTE / DEBIT_NOTE already get `card_net_position` (Feature 30); proforma and receipt get their own reconciliation card (§3.3) |
| `services/document_comparison.py` | `match_proforma_to_invoice()`, `match_receipt_to_invoice()` | deterministic, `Decimal`; number match first, else same counterparty + total within Gap 504 tolerance + date window (60 d proforma, 30 d receipt); returns candidates with the reason each matched, never picks silently when ≥ 2 tie |
| `routers/audit.py` | `resolve_audit_invoice()` | unchanged — `documents` rows never reach it |
| `routers/dashboard.py`, `alembic/versions/a1b2c3f30002_semantic_views.py` | — | unchanged. Metrics and views read `invoice`; once the four sub-types stop landing there they are correct by construction. **Test only** (31.5) |
| `agents/sage_prompts.py` | SQL rule 6 | one sentence: credit / debit notes, proformas and receipts are in `documents`, never in `invoice`; "what do we owe X" is invoices only; to see a note's effect, attach it in chat |
| `scripts/reclassify_ledger_scope.py` (new, dry-run default) | rows in `invoice` with `doc_type` in the four sub-types → moved to `documents` (same tenant, same blob, same extracted figures), `invoice` row hard-deleted with its audit history and Chroma chunks (Gap 460's delete path), one log line per row | run once per environment on founder go; not an Alembic migration (no schema change) |
| `docs/feature_27_generic_extraction.md` | A2, E10 | one dated note each: A2 governs schema only; E10's "money family stays in `invoice`" superseded by this feature |

## 3. Functionality

### 3.1 Ledger scope — one constant
`is_ledger_doc_type()` is the only place the product answers "does this document owe or get owed money". Worker routing (`_routes_to_documents_table`), the reclassify script and the tests all import it. `DOC_TYPE_FAMILY` is not consulted for storage decisions anywhere after this feature; a test asserts `queue_worker/handlers.py` no longer compares a `doc_type` to `MONEY_FAMILY` for routing.

### 3.2 Ingestion — the four sub-types take the documents path
Upload, email, Drive, public API: the classifier (Feature 27 G4 / Gap 516's title-segment classifier) labels the document; if `doc_type` is not `INVOICE`, `_persist_non_invoice_document()` writes the `documents` row and deletes the placeholder `invoice` row in one transaction — exactly what already happens for a PO or delivery note. Consequences, all by construction: no status lifecycle, no `due_date`, no Mark as Paid, absent from `total_invoiced` / `outstanding_amount` / `at_risk_amount` / `v_overdue` / `v_vendor_spend`, never a Layer 2/3 duplicate candidate against an invoice, no `sa_alerts` beyond extraction-time ones, visible in History (FE Gap 464) and Records › Documents (FE Feature 22) with its doc-type badge (FE Gap 378).

Extraction is unchanged: A2 keeps these on `InvoiceExtractionSchema`, the verifier keeps Gap 502's sign-awareness, `field_confidence` and `source_document_json` are persisted as today. Only the destination row changes.

### 3.3 Reconciliation intelligence — on chat attachment only
The Feature 26 attachment path already classifies, extracts and runs Feature 30's cards. This feature completes the card set so every reconciliation sub-type produces one finding against the impacted invoice, as a claim (30.20), never prose the model computed:

| Attached | Card | Says | Suggested action (a person does it) |
|---|---|---|---|
| CREDIT_NOTE / DEBIT_NOTE | `card_net_position` (exists) | "CN-2010 reduces BHA-2003 from ₹103,191 to ₹60,416" / "DN-1 adds ₹5,000" | edit the invoice in the review console, or settle for the net amount and Mark as Paid |
| PROFORMA_INVOICE | `card_agreed_vs_billed` (new) | "PF-77 agreed ₹437,190 on 1-Aug; RAJ-2008 bills ₹441,020 on 20-Aug — 0.9% above" or "no tax invoice from Rajesh matches PF-77 yet" | question the vendor, or nothing |
| RECEIPT | `card_payment_evidence` (new) | "RC-9 ₹4,800 on 20-Aug matches open OM-2001 (₹4,800, due 25-Aug)" or "no open invoice matches; 2 candidates within tolerance — which?" | Mark as Paid on OM-2001 |

Linking uses `resolve_entities()` for the counterparty and `match_*_to_invoice()` for the figure; a tie or a miss is stated as NOT_CHECKED / NOT_FOUND per Feature 30's three-state result (30.19), never guessed. The card carries the candidate invoice id so the FE can deep-link to it (§7). The insight is stored per attachment as today (`Insight` row, Feature 30) and is what Feature 33's attachment scope will later plan over.

### 3.4 What the system never does
Change `Invoice.grand_total`, `status`, `paid_at` or any money field because a reconciliation document arrived or was attached; create an `AuditLog` row on the invoice for an attachment; link an ingested (non-chat) note to an invoice; treat a receipt as payment. Each is a test (31.6).

### 3.5 Existing rows
Dev and any tenant that uploaded notes before this feature have them as `invoice` rows. `scripts/reclassify_ledger_scope.py --dry-run` lists them; `--apply` moves them (§2). Per the founder's dev-phase rule this is an ops script run once on go, not a migration and not a backfill built into deploy.

## 4. Data & schema changes
**None.** No new columns, no new statuses, no new tables. `documents` already holds everything a reconciliation card reads. (The 2026-09-09 draft's `applied_to_invoice_id`, `applied_at`, `superseded_by_invoice_id`, `proforma_id`, `paid_source`, `bank_statement_line.match_kind` are all dropped.)

## 5. Tasks
- [ ] 31.1 `services/ledger_scope.py` + `_routes_to_documents_table()` reads it; the "no `MONEY_FAMILY` routing comparison left" test
- [ ] 31.2 Worker Postgres test: an upload classified CREDIT_NOTE / DEBIT_NOTE / PROFORMA_INVOICE / RECEIPT lands in `documents` with its signed figures in `doc_attributes`, the placeholder `invoice` row is gone, and `invoice` count is unchanged
- [ ] 31.3 `match_proforma_to_invoice()`, `match_receipt_to_invoice()` in `services/document_comparison.py` (pure, `Decimal`, tie → candidates, miss → empty)
- [ ] 31.4 `card_agreed_vs_billed`, `card_payment_evidence`; register in `CARDS_BY_DOC_TYPE`; claims through 30.20, three-state through 30.19; anti-hardcoding harness green
- [ ] 31.5 Metric / view tests: seed one of each sub-type as a `documents` row and one open invoice; `total_invoiced`, `outstanding_amount`, `at_risk_amount`, `v_overdue`, `v_vendor_spend` count the invoice only
- [ ] 31.6 "Never does" tests (§3.4): attach CN / receipt in chat → invoice row byte-identical after the turn; no `AuditLog` row; ingested CN → no `Insight` row, no link
- [ ] 31.7 SAGE prompt rule 6 sentence + golden case "what do we owe Bharat" → 103,191 (invoice only) and the answer names that a credit note exists in documents and how to reconcile it
- [ ] 31.8 `scripts/reclassify_ledger_scope.py` (dry-run default); Postgres test on a seeded tenant; run on dev on founder go, result line filed here
- [ ] 31.9 Feature 27 A2 / E10 dated notes; `feature_30_business_intelligence.md` card table gains the two cards
- [ ] 31.10 FE (§7) — part of FE Feature 22

## 6. Verification plan
Real Postgres. Seed tenant T: BHA-2003 (invoice, Bharat, open 103,191, due in 10 d), OM-2001 (invoice, Om Stationery, open 4,800). Upload via `POST /invoices/upload`: BHF-CN-2010 (credit note, Bharat, −42,775), DN-1 (debit note, Bharat, +5,000), PF-77 (proforma, Rajesh, 437,190, 1-Aug), RC-9 (receipt, Om, 4,800, 20-Aug). Assert: `invoice` rows = 2, `documents` rows = 4, each with the signed `grand_total` in `doc_attributes`; dashboard `total_invoiced` = 107,991, `outstanding_amount` = 107,991, `at_risk_amount` = 0; `v_overdue` empty; `v_vendor_spend` Bharat = 103,191.
Chat, session on T: attach BHF-CN-2010 → `net_position` card claims 103,191 → 60,416 naming BHA-2003; attach RC-9 → `payment_evidence` card names OM-2001 with reason "counterparty + total + 5 d"; attach PF-77 → `agreed_vs_billed` NOT_FOUND (no Rajesh invoice); then upload RAJ-2008 (invoice, Rajesh, 441,020, 20-Aug) and re-attach PF-77 → card claims +0.9 %. After every attachment: BHA-2003 and OM-2001 rows unchanged (all columns), no new `AuditLog` rows. Mark as Paid on OM-2001 by the user → PAID (the existing path; the receipt did not do it).
Reclassify: seed 3 legacy CN rows in `invoice`; `--dry-run` lists 3 and changes nothing; `--apply` → 0 in `invoice`, 3 in `documents`, blobs and Chroma chunks re-homed, audit rows for the deleted invoice ids gone (Gap 460 delete semantics).
Harness: `pytest tests/test_no_hardcoding.py -q` green.

## 7. FE section (FE Feature 22)
- Records › Documents / History: the four sub-types show their doc-type badge (exists) and a **Reconcile in chat** action that opens Ask with the document pre-attached (the Feature 26 composer already accepts an existing `documents` row by id — confirm, else one small BE endpoint). No status chip, no Mark as Paid, no due date, no overdue colour.
- Invoice list / dashboard: nothing changes; these rows are no longer there.
- Chat bubble: the three cards render through Feature 21's bubble; the candidate invoice number is a link to the review console; the "suggested action" line is plain text, no button — the person goes and does it (founder: manual decision).
- Review console for an invoice: unchanged. A future "documents that mention this invoice" panel is Feature 33's, not this feature's.
