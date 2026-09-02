# Feature 27 — Generic Document Extraction

Status lives in `docs/be_features_tracker.md`. This document is the durable
design record. The source-verified audit that produced it is
`docs/feature_26_generic_document_analysis_2026-09-02.md` — **which no longer exists in
`docs/` (verified 2026-09-02); its content survives in git history only.** The founder's
resolved decisions are recorded here as E1–E10 rather than left in working state: E1–E9
as originally written, E10 and Amendments A1–A3 from the 2026-09-02 founder review (§2A).

Collision check at creation time (2026-09-02): max BE feature doc was 26
(`feature_26_chat_attached_documents.md`, plus the dated analysis file of the
same number); max FE feature 18; the consolidated `feature_20_23_24_ops_workbook.md`
occupies 20/23/24. **27 is free.** Gap numbers must be re-checked immediately
before writing the tracker entry. **Superseded 2026-09-02:** Gap 367 has since been
filed (`be_features_tracker.md`, `[x]` Gap 367 — the `get_llm(temperature=0)` TypeError).
Repo-wide max filed across all three trackers is now **367** (BE 367, FE 358, website
351), so the next free number is 368 — still re-check immediately before writing. Do not
assume 368. **Superseded again 2026-09-02 (design-completion pass):** repo-wide max *in
use* is **385** — Gaps 384 and 385 are cited from code and tests but have no tracker entry
(§10B task R0) — and **386** was taken the same day by Feature 26's H16. Next free is 387;
re-check before writing.

## Build status — 2026-09-02 (source: `reports/audits/2026-09-02-f26-f27-status-audit.md`)

This block is the one place in this document that says what *exists* rather than what was
*decided*. Every build note below it describes uncommitted code.

- **Commits: none.** `git log --all -- "*feature_27*"` is empty. Every Feature 27 change
  lives in the uncommitted working tree: `agents/extraction_agent.py` +1508,
  `queue_worker/handlers.py` +338, `models.py` +163, `chroma_client.py` +319,
  `routers/invoices.py` +202, `services/billing_quota.py` +42 (all `M`); untracked
  `services/document_type_classifier.py` (603 lines), `routers/documents.py` (215),
  `alembic/versions/e4f5a6b7c8d9_add_doc_type_and_documents_table.py` (154),
  `tests/test_generic_extraction.py` (2885), `tests/test_document_type_classifier.py`
  (501), `tests/test_documents_table.py` (1075), `tests/fixtures/doc_types/` (16 PDFs).
- **Migration `e4f5a6b7c8d9` IS applied to the dev Postgres, and is proven reversible.**
  *(Corrected 2026-09-02 by task R3 — this block previously said it had never been
  applied, on the strength of a container log line showing
  `column invoice.doc_type does not exist` at 10:21 UTC. That log predates the migration;
  it is not current state, and reading it as such was the error.)* Verified against
  `invoice-postgres-local`: `alembic_version` = `e4f5a6b7c8d9`; `invoice.doc_type` /
  `doc_type_evidence` present, varchar, nullable, no server default; `documents` present
  with 35 columns and 7 indexes, both composite ones tenant-led. `downgrade -1` drops
  `documents` and the two `invoice` columns **without touching Feature 26's
  `d3e4f5a6b7c8` beneath it**, and `upgrade head` restores an identical shape. Evidence:
  `docs/test_evidence/f26_f27_shared_r3_r4_2026-09-02/01_r3_migration_postgres.md`.
  **R-27-26 is satisfied.** Alembic single head confirmed via the Python API —
  `alembic.exe` is blocked by this machine's Application Control policy.
- **Every executed test is SQLite or pure-Python with the LLM patched.**
  `tests/test_generic_extraction.py` + `tests/test_document_type_classifier.py` → **409
  passed** (in-memory SQLite at `test_generic_extraction.py:1965`; `_run_ocr` and
  `run_extraction_agent` patched **without** `autospec` at `:2357–2359`).
  `tests/test_documents_table.py` (38 collected, real-Postgres-only by its own
  `pg_engine_or_skip()` at `:60–79`) **skips its Postgres tests** — the dev container is
  paused, so `psycopg2.connect` returns `Connection refused` and the harness skips
  correctly. (While the container was *paused-but-listening* it hung instead: the harness
  passes no `connect_timeout`, so a frozen-but-accepting socket blocks forever. Fixing
  that is R2 — the skip only works because the container is now fully down.)
- **The full backend suite runs.** `uv run pytest -q
  --ignore=tests/us/run_chat_live_test.py` (2026-09-02, 48m47s, stack down):
  **14 failed, 2280 passed, 26 skipped, 5 deselected.** `pytest -x -q` as written
  **aborts at collection** on a git-ignored basename collision
  (`tests/us/run_chat_live_test.py` vs `tests/realworld_tenant/run_chat_live_test.py`),
  and `addopts = -m "not e2e"` deselects the 5 e2e tests.
- **R4 — the targeted run with the full dev stack up (2026-09-02, 52s): 5 failed, 211
  passed, ZERO skipped.** Seven suites: `test_documents_table.py`,
  `test_chat_attachments.py`, `test_chat_doc_content_branch.py`,
  `test_chat_document_search.py`, `test_chat_queue.py`, `test_chat_progress.py`,
  `test_rag.py`. **Zero skips is the headline** — `pg_engine_or_skip()` did not skip, so
  **T-E10-1..5 executed against real Postgres and passed**. That satisfies R-27-20
  through R-27-24, which every prior record listed as "built, never run".
  Of the 5 failures, **none is a Feature 27 defect**:
  - `test_documents_table.py::test_the_lifecycle_functions_never_open_a_collection_without_the_metadata`
    — **the test was wrong, not the code** (**Gap 389**, fixed): it asserted on a
    substring of `inspect.getsource()`, and `delete_document_chunks`'s docstring *names*
    `get_or_create_collection()` while explaining why it does not call it. Re-asserted
    over the parsed call graph; now passes, with a negative control. **The earlier
    reading of this as "a real G10 lifecycle defect" was wrong and is withdrawn** — the
    documents-side lifecycle functions all exist (`chroma_client.py:639`, `:676`, `:704`,
    `:723`) and all route through `get_document_collection()`.
  - 4 × `test_rag.py` — 3 assert `200` from the chat endpoint and get `202 Accepted`
    because the local `.env` sets `ENABLE_ASYNC_CHAT_QUEUE=true` and Redis is now up
    (**Gap 390**); 1 is the long-known `background_tasks` `TypeError`. Neither touches
    this feature.
  Every `test_generic_extraction.py` and `test_document_type_classifier.py` test passed
  in the 48-minute run, consistent with the 409 above.
- **Task V not started.** No `docs/test_evidence/` folder exists for this feature.
  T-OFF-1, T-R-6 and T-E10-1..5 have no Postgres run — every T-E10 test **skipped** in
  the full-suite run above rather than passing.
- **Flag**: `config.py:115 ENABLE_GENERIC_EXTRACTION: bool = False`. Must stay off in any
  user-facing deployment — §2A/N1's rollout gate (G11 `[~]`, FE Gap 378) is still shut.
- **Invariant (A2), restated as a build fact:** the INVOICE family (`INVOICE`,
  `PROFORMA_INVOICE`, `CREDIT_NOTE`, `DEBIT_NOTE`) keeps `InvoiceExtractionSchema` /
  `OutboundInvoiceExtractionSchema` and the existing `_DirectionProfile` machinery
  untouched in both flag states; `GenericDocumentSchema` (`extraction_agent.py:311`)
  applies **only** to non-INVOICE `doc_type`s, through `resolve_extraction_profile()`
  (`:1353`). Asserted by `test_generic_extraction.py`'s A2 truth-table tests.
- **OCR**: `prebuilt-invoice` is the only Document Intelligence model string in any `.py`
  file; `prebuilt-layout` was never coded and will not be (§2A/A1 "Considered and
  rejected").
- **Doc drift corrected by this pass**: G6, G8 and task F were marked open while their
  code and fixtures existed and passed — now `[x]` with evidence in §10.

---

## 1. Overview — what this feature is, and what the real gap was

Today the extraction pipeline is *implicitly* an invoice pipeline. Not because
anything gates on document type — the 2026-09-02 audit confirmed **no hardcoded
"must be an invoice" check exists anywhere** — but because three separate
choices, each individually reasonable, compound into one:

1. **The OCR model is `prebuilt-invoice`, hardcoded.** `queue_worker/handlers.py::_run_ocr()`
   (L131, model string at L204) is the only Document Intelligence model string
   in the repo. It returns an invoice-shaped dict (`content`, `coordinates`,
   `field_confidence`, `tax_details_sum`, `source_document_json`, L325–331).
   Run a delivery note through it and Azure returns a low-confidence invoice
   analysis of a document that is not an invoice.
2. **Document type is decided *inside* the extraction call**, not before it.
   `ReferenceDocExtractionSchema.doc_type` (`agents/extraction_agent.py` L215)
   is an LLM-populated free-text field with a three-value instruction
   (`PURCHASE_ORDER` / `QUOTATION` / `OTHER`), read off the printed title. There
   is no classifier step and no closed vocabulary.
3. **`verify_node` assumes money.** `agents/extraction_agent.py::verify_node()`
   (L694) runs `verify_line_items_math` and `verify_totals_math` unconditionally
   — subtotal, tax, grand total. A delivery note has quantities and no prices,
   so every one of those checks fires as a discrepancy on a document that is
   perfectly correct.

The result the founder actually hit: a delivery challan uploads fine, extracts
partially, and comes back looking broken. It is not broken. It is being graded
against the wrong rubric.

**This feature makes document type an explicit, first-class, deterministic
decision made *before* extraction, and makes everything downstream — the schema,
the prompt, the verification rubric — a function of that decision.**

## 2. What this is NOT

- **Not a second pipeline.** One LangGraph, one compiled `graph` object
  (`agents/extraction_agent.py` L913–930). This feature adds one node and
  parameterises the existing ones. There is no parallel graph.
- **Not a per-tenant capability.** See E2 — the flag is software-level. There is
  no tenant-level override, no `tenant.features` column, no per-tenant enum.
- **Not a change to invoice behaviour.** With the flag OFF the pipeline is
  byte-identical to today (E3), with exactly one deliberate exception (E9).
- **Not an OCR-model change.** `prebuilt-invoice` remains the only Document Intelligence
  model string in the repo, in both flag states. The document *family* chooses how much
  of that one response is consumed, never which model runs — see §2A/A1, including its
  "Considered and rejected" note, which is the single canonical statement on
  `prebuilt-layout` in this document.
- **Not a widening of what the `invoice` table means.** A delivery note, a PO and a
  contract are not `Invoice` rows. They go to a new `documents` table with its own Chroma
  collection — E10 — for the same reason Feature 26 decision D2 kept chat attachments out
  of `invoice`.
- **Not transport-document support.** Bills of lading, air waybills and India's
  e-way bill are explicitly out of v1 (E5).
- **Not a chat feature.** The chat/grounding surface is Feature 26 Part 2. This
  feature ends when a typed, extracted, verified document exists.

---

## 2A. Amendments A1–A3 — founder review, 2026-09-02

§1–§11 were written before any code existed against them. A founder review then found
three defects that would each have regressed the *existing* invoice pipeline the moment
`ENABLE_GENERIC_EXTRACTION` was turned on. They are recorded here as amendments rather
than by rewriting §3–§11 in place, so the original reasoning and the correction to it
both survive review. Each amendment names the sections it edits; those edits are applied
inline and marked "(A1)" / "(A2)" / "(E10)" where they land.

### A1 — The OCR model does not change. `prebuilt-invoice` stays, for every document, in both flag states.

**Decision.** `queue_worker/handlers.py::_run_ocr()` keeps `model_id="prebuilt-invoice"`
unconditionally. There is **no `prebuilt-layout` branch in v1**, no OCR-model selector,
and therefore no ordering problem between model choice and classification. What changes
instead is *which parts of the prebuilt-invoice response are trusted for a non-INVOICE
document*.

**What the original spec got wrong.** §4's `_run_ocr` row and §10's G7 specified
"`prebuilt-invoice` when the flag is off, `prebuilt-layout` when on". Feature 2 depends on
`prebuilt-invoice`-specific output in four places: `field_confidence` (the Critic node,
Task 2.32 — `extraction_agent.py` L806–813), `coordinates` (the auditor overlay, Task
2.15/Gap 16, normalised by Gap 330), `source_document_json` (Gap 178) and
`tax_details_sum` (the null-`tax_amount` backfill, **Gap 68** — `extraction_agent.py`
L681–689). `classify_invoice_complexity` additionally keys on `field_confidence` presence
(`services/invoice_classifier.py` L24–29). `prebuilt-layout` returns none of these. With
the flag ON, an invoice would have been extracted with the Critic starved and the
complexity classifier degraded to keyword-only — so **T-R-3 ("an INVOICE produces the
identical alert set it produces today") could not have passed, by construction.**

**Why no model switch is needed at all — verified against the SDK, not assumed.**

- `AnalyzeResult` is one model shared by every `model_id`
  (`azure-ai-documentintelligence`, `models/_models.py` L420–475): **`content: str` and
  `pages: List[DocumentPage]` are required on every response**; `documents`, `tables`,
  `paragraphs`, `key_value_pairs`, `figures`, `sections` are all optional.
  `prebuilt-invoice` populates `content`, `pages` **and** `documents[].fields`;
  `prebuilt-layout` populates the first two and not the third. Layout is a strict subset
  of what we already receive, for everything this feature needs.
- The generic text is therefore already in hand. `_run_ocr` returns `result.content`
  (handlers.py L326) — that string *is* the `ocr_text` every extraction prompt is built
  from today, and it is the only input `classify_doc_type`'s deterministic title-band pass
  needs. `result.pages[].width/height` is already read at L254–257.
- **Nothing in this repo reads the layout-only members.** Repo-wide grep, 2026-09-02: zero
  non-vendored references to `.tables`, `paragraphs`, `key_value_pairs`, `figures` or
  `sections`. Switching models would have traded four consumed fields for five nobody reads.
- One OCR call, not two. The "run invoice, classify, re-run layout if non-invoice"
  sequence considered in review is coherent but pointless in v1: it doubles the Document
  Intelligence call and the wall-clock OCR stage for every non-invoice document in exchange
  for members no code consumes.

**What replaces G7 — trust boundaries, not a model switch.** With the flag ON and
`DOC_TYPE_FAMILY[doc_type] != "INVOICE"`:

| prebuilt-invoice output | Today | Non-INVOICE family, flag ON |
|---|---|---|
| `field_confidence` → `verify_field_confidence` (Critic, Task 2.32) | consumed unconditionally, `verify_node` L806–813 | **not consulted.** `_VerificationRubric` gains `run_field_confidence: bool`, `False` for every non-INVOICE family. The check maps DI's invoice field names onto invoice schema names (`InvoiceTotal`→`grand_total`, `VendorName`→`vendor_name`, `utils/verification_tools.py` L641–649). On a delivery note DI force-fits those fields and returns them at low confidence, so the Critic emits `low_confidence_field` alerts naming fields the document does not have — and since that type is in `NON_RETRYABLE_ALERT_TYPES` (L891) and any alert sets `profile.review_status` (L822), a perfectly correct delivery note lands in review carrying an alert no retry can clear. **This is the founder's original symptom reproduced by a second, independent route** — fixing only the money rubric (E6) would have left it in place. |
| `tax_details_sum` → null-`tax_amount` backfill (Gap 68) | fires whenever the LLM's `tax_amount` is `None`, any direction | **gated to the money family.** `_VerificationRubric` gains `run_di_tax_backfill: bool`. A delivery note prints no tax; DI's `TaxDetails` read on one is a misparse, and backfilling it writes a tax figure onto a document that states none — the plausible-wrong-answer class E9 exists to prevent. |
| `coordinates` → auditor overlay (Task 2.15, Gap 330) | persisted for every row | **persisted for the INVOICE family only**; non-INVOICE persists `[]`. Every box is labelled with a DI *invoice* field name, so rendering them over a purchase order draws a "grand_total" box around whatever DI guessed. An empty overlay is honest; a mislabelled one is not. |
| `source_document_json` (Gap 178) | persisted for every row | **unchanged.** It is a raw diagnostic snapshot and it is already excluded from every LLM-visible projection (`agents/query_tools.py` L168–169, `agents/sage_prompts.py` L271–273), so a misfit DI read cannot reach an answer. |
| `classify_invoice_complexity`'s `field_confidence` keying | keys on DI field presence, falls through to content keywords | **unchanged and still correct**, because the response still comes from `prebuilt-invoice`. §8 trap 3 is void — it described a hazard created solely by the model switch. |

**The sequence, stated so a coding task can be written directly from it:**

```
_run_ocr            prebuilt-invoice, unconditional, unchanged
  → classify_doc_type   deterministic title-band pass over result.content;
                        LLM fallback only on ambiguity (E7)
  → classify            complexity, unchanged
  → dynamic_qa          unchanged
  → extract             schema + prompt selected by family (A2)
  → verify              rubric selected by family, incl. run_field_confidence
                        and run_di_tax_backfill (A1)
```

There is no point at which an OCR model must be chosen before the document type is known,
because only one model is ever used. The ordering question raised in review is dissolved,
not resolved by sequencing.

**Considered and rejected — `prebuilt-layout`. (Restated 2026-09-02, design-completion
pass.)** It was **never coded** — repo-wide grep 2026-09-02: the string appears in no `.py`
file, only in this document and two other markdown files — and it **will not be coded in
this feature.** The rule, stated once so every other "layout" mention in this document can
point here: *the OCR model is a function of nothing; the consumption of its output is a
function of the document family.* The INVOICE family consumes `content`, `pages` and
`documents[].fields` exactly as today; every non-INVOICE family consumes `content` and
`pages` only, with invoice-field consumption switched off by the rubric
(`run_field_confidence=False`, `run_di_tax_backfill=False`), no `coordinates` persisted,
and — after E10 — no `invoice` row at all. The only condition that would ever reopen this
is a *measured* extraction deficit on task F's real non-invoice fixtures attributable to
OCR rather than to the prompt; it would then be a second, post-classification call for
non-INVOICE families only, with the doubled DI cost accepted explicitly. Not v1, not
planned, not in §10B's remaining list.

**Edits:** §4 (`_run_ocr` row), §5 (steps 2, 6, 7), §6, §8 (trap 3), §9 (T-O-1), §10 (G7),
§11, E3, E6.

### A2 — The INVOICE family keeps its existing schema, prompts and direction profile. Flag ON or OFF.

**Decision.** `GenericDocumentSchema`, `GenericLineItem` and `_DOC_TYPE_OVERLAYS` apply
**only** to non-INVOICE `doc_type`s. The INVOICE family (`INVOICE`, `PROFORMA_INVOICE`,
`CREDIT_NOTE`, `DEBIT_NOTE`) keeps `InvoiceExtractionSchema` /
`OutboundInvoiceExtractionSchema` and the existing `_DIRECTION_PROFILES` machinery
byte-for-byte, in both flag states.

**Why.** §5 step 6 as originally written applied the generic schema to every document.
Tasks 2.21–2.31 put eight structured lists on `InvoiceExtractionSchema` — `taxes[]`,
`discounts[]`, `deductions[]`, `tax_ids[]`, `payment_instructions[]`, `references[]`,
`addresses[]`, `compliance_metadata[]` — plus `round_off`, `discount_percent`/`_amount`,
and per-line `hsn_sac_code`/`uom`/`tax_percent`/`tax_amount`. The Gap 31/33/36/43/44/46
faithfulness checks and Gap 293's round-off/discount handling all read specific keys off
that shape. `GenericDocumentSchema`'s spine (E8) carries **none** of
`compliance_metadata`, `payment_instructions`, `deductions`, `tax_ids`, `addresses`,
`round_off`, `discount_percent` or `hsn_sac_code`. Putting an invoice on it would silently
drop the India e-invoicing block (IRN/QR — the very block E4 cites as the reason
`INVOICE` is one type with sub-cases), the GST HSN codes and the round-off handling. Years
of gap fixes, lost to a flag flip, with no error raised anywhere.

**Profile resolution — the exact rule to implement:**

- `resolve_direction_profile` is otherwise untouched; its only change is E9's fail-loud.
- New `resolve_extraction_profile(flow_direction, doc_type)` returns
  `resolve_direction_profile(flow_direction)` **unless all four hold**: the flag is ON,
  `flow_direction` resolves to `INBOUND`, `doc_type is not None`, and
  `DOC_TYPE_FAMILY[doc_type] != "INVOICE"` — in which case it returns the new `GENERIC`
  profile (`GenericDocumentSchema`, the generic prompt builders, `required_fields=()`,
  the `EXTRACTED`/`EXTRACT_FAILED` status pair, `legacy_audit_path_shim=False`).
- `OUTBOUND` and `REFERENCE` are unchanged in v1. OUTBOUND is the tenant's own AR invoice
  and its downstream consumers (`routers/outbound_audit.py`,
  `queue_worker/outbound_handlers.py`) are written against `OutboundInvoiceExtractionSchema`;
  REFERENCE is Feature 26's chat-attachment path with its own schema and vocabulary.
  `doc_type` is still classified and recorded for both — it simply never changes their
  schema or rubric.
- `doc_type is None` (flag OFF, or a caller-supplied skip via `run_extraction_agent`'s
  `doc_type` override) → the existing profile, exactly as today. **Fail-closed to invoice
  behaviour**, matching E1's reasoning for the flag default.

**Verification.** New **T-R-6** (§9): flag ON, an INVOICE-family fixture produces an
extracted dict field-for-field equal to the flag-OFF output on the same fixture. It is the
ON-case mirror of T-OFF-1, and equality is the only assertion strong enough to catch this
class of bug — a generic-schema extraction of an invoice still returns plausible
`vendor_name` and `grand_total`, so anything weaker passes green while
`compliance_metadata` is being dropped on the floor.

**Edits:** §4 (`agents/extraction_agent.py` row), §5 (step 6), §9 (new T-R-6), §10 (G3,
new G3b), E8.

### A3 → E10 — Non-invoice documents get their own table and their own Chroma collection.

*(The decision itself is recorded as **E10** in §3, so it sits with E1–E9 rather than only
in this amendments section. The reasoning below is E10's; §3's E10 entry states it in
full.)*

**Decision.** Option (b). Non-INVOICE-family documents are **not** `Invoice` rows. They
land in a new `documents` table with a `docs_{tenant_id}` sibling Chroma collection.
`Invoice.doc_type` / `Invoice.doc_type_evidence` are still added — an invoice's own
sub-type (Tax Invoice vs proforma vs credit note) is real information and the INVOICE
family stays in `invoice` — but **no non-INVOICE row is ever written to `invoice`.**

**Reasoning, on the real numbers option (a) was to be judged on:**

1. **Site count, actually counted (repo-wide grep, 2026-09-02): 39 tenant-scoped `Invoice`
   query sites across 19 files.** `routers/invoices.py` (9), `agents/query_agent.py` (6),
   `routers/dashboard.py` (3), `routers/chat.py` (3), `routers/outbound_dashboard.py` (2),
   `routers/outbound_invoices.py` (2), `routers/trainer.py` (2),
   `queue_worker/handlers.py` (2), and one each in `routers/audit.py`,
   `routers/outbound_audit.py`, `queue_worker/outbound_handlers.py`,
   `services/billing_quota.py`, `services/document_comparison.py`,
   `services/invoice_reconciliation.py`, `services/outbound_overdue.py`,
   `services/rule_impact.py`, `scripts/reembed_chroma_collections.py`,
   `scripts/sweep_sandbox_tenants.py`. The bar for choosing (a) was "roughly under 10".
   This is four times that — ~39 filters plus ~39 exclusion tests, and a new obligation on
   every `Invoice` query anyone writes from now on, forever.
2. **One of those sites cannot be filtered deterministically at all.** The chat SQL route
   generates free-form `SELECT … FROM invoice …` (`agents/query_agent.py`,
   `build_sql_system_prompt` L2407+). `execute_generated_sql` (L1211) is a **validator, not
   a rewriter**: it denies mutating statements and checks that a tenant predicate is
   *present* by regex (L1238–1241). It does not inject predicates. Enforcing a doc_type
   filter there means either resurrecting an execution-time SQL rewriter — deleted at Gap
   253, and the origin of CONVENTIONS hard rule 3 — or writing a prompt rule, which is not
   a control. Under (a), "how much did we spend last month?" would count delivery notes
   every time the model omitted a filter it was merely *asked* to add.
3. **This decision was already made, shipped, and written into the code.** `models.py`
   L244–251, the `ChatAttachment` docstring, verbatim: *"This is deliberately NOT an
   `Invoice` row (Feature 26, decision D2). A quotation is not a payable. Writing one into
   `invoice` would silently corrupt spend aggregates, /dashboard/insights, the
   AUDIT_REQUIRED count, billing quota and the RAG index — five separate consumers that all
   read `invoice` as 'money we owe or are owed'."* Option (a) would make the same purchase
   order a `chat_attachments` row when attached in chat and an `Invoice` row when uploaded
   through ingestion — two contradictory answers to one question inside one codebase.
4. **The failure mode is not hypothetical; it already happened, on this exact table.** Gap
   329: `flow_direction` was added to `Invoice` and `/dashboard/metrics` was never filtered
   on it, so OUTBOUND rows blended into every inbound aggregate — inflating totals and
   coalescing into a phantom "Unknown Vendor" bucket, found only because the founder
   noticed it on screen (post-mortem in `routers/dashboard.py` L146–154). That was **one**
   new row-kind and **one** missed file. This feature adds nine new kinds.

**Shape.**

- **`Document` (`__tablename__ = "documents"`)** — `id`, `tenant_id` (index), `batch_id`,
  `file_path`, `file_hash` (index), `doc_type`, `doc_type_evidence`,
  `doc_type_confidence`, `party_name`, `counterparty_name`, `doc_number`, `po_number`,
  `reference_numbers` (JSON), `doc_date`, `valid_until`, `currency`, `subtotal`,
  `tax_amount`, `discount_amount`, `grand_total`, `items` (JSON), `taxes` (JSON),
  `payment_terms`, `delivery_terms`, `incoterms`, `notes`, `status`, `sa_alerts` (JSON),
  `source_document_json`, `created_at`, `completed_at`, `deleted_at`, `last_enqueued_at`,
  `processing_attempts`, `submitted_by_email`. It mirrors `Invoice`'s *operational*
  columns (Gap 192 soft delete, FE Gap 81/84 re-enqueue bookkeeping) so the existing
  sweeps and audit-trail patterns transfer unchanged, and carries `GenericDocumentSchema`'s
  spine and nothing money-specific beyond what a PO or contract genuinely prints. Status
  vocabulary is **`EXTRACTED` / `EXTRACT_FAILED`** — the same pair the REFERENCE direction
  profile already uses (`agents/extraction_agent.py` L543–544), for the same reason stated
  there: a delivery note has no audit lifecycle; it is never approved, sent or paid.
- **Chroma:** `_document_collection_name(tenant_id) -> f"docs_{tenant_id}"`, created
  through `_collection_metadata()` (§8.2 — non-negotiable, and the reason `index_document_chunks`
  exists at all). Sibling of the invoice collection, the same pattern Feature 26 Part 2
  specifies for `chat_docs_{tenant_id}` (`feature_26_chat_attached_documents.md`,
  §P2.4/E-2). Stated honestly: that collection is **designed, not yet built** —
  `chroma_client.py` has no `_chat_doc_collection_name` today — so the precedent is an
  approved decision, not shipped code. `query_invoice_chunks()` cannot reach
  `docs_{tenant}`: that unreachability-by-construction is exactly what (b) buys and what
  39 hand-maintained filters would only approximate.
- **Where the row is created.** Classification happens inside the graph, after OCR, so the
  ingestion door cannot know the type at row-creation time. Resolution: the door creates the
  `Invoice` row exactly as today; when `classify_doc_type` returns a non-INVOICE family,
  `queue_worker/handlers.py` writes the `documents` row and deletes the placeholder
  `invoice` row **in the same transaction**. The residual exposure, bounded and stated
  openly: between upload and classification the placeholder exists with
  `status=PROCESSING` and `grand_total=NULL`, so during that window it is counted in
  `/dashboard/metrics`' status breakdown and in the `PROCESSING` branch of
  `outstanding_amount` (`routers/dashboard.py` L193) — contributing **zero** to every money
  total, since NULL `grand_total` coalesces to 0, and **one** to a transient count. That is
  the whole of it, and it lasts one OCR+extract run.
- **Billing quota — the one filter that must be *widened*, not narrowed.**
  `services/billing_quota.py::count_billable_uploads` (L45–63) dedups against the set of
  existing `Invoice.file_hash`. Once non-invoice documents leave `invoice`, that set must
  become `Invoice.file_hash ∪ Document.file_hash`, or re-uploading the same delivery note
  is charged again every time. A non-invoice upload **is** billable: it consumed a real
  Document Intelligence page and a real extraction call. Gap 343 already established that
  every door which creates a row shares this logic — the same rule applies to the new door.
- **Product consequence, stated rather than discovered later.** With the placeholder
  deleted, a non-invoice upload disappears from the ingestion status table until a
  `GET /documents` list endpoint and an FE surface exist. This does **not** block
  G1–G10/G12–G13 or F/V (all API-level — see N1), but it **does** block turning the flag ON
  in any deployment a user can see. Tracked as G14 (BE endpoint) and the G11 note.

**Edits:** §3 (new E10), §4 (`models.py`, alembic, `chroma_client.py` rows; new
`routers/documents.py`), §5 (steps 8, 9), §6, §9 (new T-E10 block), §10 (G9, G10, new G14).

### Two carried notes

**N1 — G11 (the FE tasks) is a follow-up, not part of the G1–G10/G12–G13 track.** Checked
before deciding: §9's verification plan is entirely pytest/API-level (T-OFF-1..3, T-C-1..4,
T-R-1..6, T-O-1..2, T-E10-1..3) and §7's fixture task produces files on disk consumed by
pytest. Nothing in F or V exercises the upload UI, the status table or the audit detail
view, so no FE change is required for functional-tester to execute the plan or for
senior-dev to finish the backend. G11 moves to a marked follow-up. The one caveat, from
E10: G11 plus G14 are prerequisites for turning the flag ON in a *user-facing* deployment,
because without them a classified non-invoice upload is invisible in the product. Build
gate: no. Rollout gate: yes.

**N2 — the classifier's `< 0.6` confidence threshold is a placeholder, not a calibrated
number.** It was chosen before any real fixture existed. It must be validated against the
real India delivery-challan fixtures (and at least one EU synonym sample) once §7's task F
produces them, and adjusted if the observed confidence distribution says so, **before** it
is treated as settled. Until then, every statement of `0.6` in this document — E7, T-C-3
— carries this caveat. Task F's manifest must therefore record the classifier's returned
confidence per fixture, not only whether the type was right: without the distribution
there is nothing to calibrate against.

### Corrections of fact found while amending

- The header's cited audit file, `docs/feature_26_generic_document_analysis_2026-09-02.md`,
  **does not exist** in `docs/` (verified 2026-09-02). It was deleted; its content survives
  in git history only. Header corrected.
- The header's Gap-number note is superseded: **Gap 367 has been filed** (`[x]` in
  `be_features_tracker.md`). Repo-wide max across the three trackers is now 367
  (BE 367 / FE 358 / website 351); next free is **368** — re-check immediately before
  writing, per the original instruction.
- §1's attribution of the DI tax backfill is corrected wherever it appears: the
  `tax_details_sum` backfill is **Gap 68**; Gap 69 is the sibling fix to
  `verify_tax_amount_in_source_text` for CGST+SGST splits.

### A4 — E10 security hardening (security-tester review, 2026-09-02)

A dedicated tenant-isolation review of E10 found the structural decision sound —
`docs_{tenant_id}` inherits Gap 55's guarantee, `query_invoice_chunks()` genuinely cannot
reach it by construction, and `tenant_id` is never client-controllable on any path into a
Chroma collection name. But five places were under-specified enough that a coder following
the spec literally would ship a hole. All five are spec clarifications, not design changes;
no G-task numbers change.

1. **`routers/documents.py`'s detail endpoint has no stated ownership check.** §4 and G14
   currently say `GET /documents` is "tenant-scoped" but say nothing about
   `GET /documents/{id}` — the asymmetry a single-tenant test would never catch, and the
   exact shape of a pre-Gap-341 IDOR. **Required:** name
   `_require_owned_document(document_id, db_session, tenant_context)`, mirroring
   `routers/chat_attachments.py:109–120` exactly — single query on
   `id == … AND tenant_id == tenant_context.tenant_id`, 404 (never 403) on a cross-tenant
   hit, for the same reason `chat_attachments.py:103–105` states: confirming another
   tenant's row exists is itself a disclosure. Name the auth dependency explicitly
   (`get_tenant_context`, not the sandbox-key variant, unless a reason is given to widen
   it). New **T-E10-5**: tenant B requesting tenant A's `document_id` gets 404; `GET
   /documents` for B returns zero of A's rows.
2. **The billing-quota dedup union needs the tenant predicate stated, not implied.** The
   existing `Invoice.file_hash` check (`services/billing_quota.py:45–54`) is correctly
   tenant-scoped; the spec's "`Invoice.file_hash ∪ Document.file_hash`" phrasing (§4, E10,
   G14) reads as an unscoped set and invites one. Without the predicate, a common vendor's
   identical PO template uploaded by two tenants lets tenant B's quota counter go
   un-decremented on a real DI+extraction spend, **and** turns the counter into a
   cross-tenant oracle (B can learn whether any other tenant has a given file's bytes by
   watching whether its own quota moves). **Required:** state the check as
   `{Invoice.file_hash WHERE tenant_id = :t} ∪ {Document.file_hash WHERE tenant_id = :t}`
   everywhere it's written. T-E10-3 extended: a second tenant's first upload of a file
   already present under a different tenant **does** consume that second tenant's quota.
3. **The sibling collection's lifecycle, not just its creation, needs a stated answer.**
   §4/G10 specify `_document_collection_name()` / `index_document_chunks()` /
   `_collection_metadata()` — creation and writes only. The invoice collection has four
   more functions around it (`delete_invoice_chunks`, `has_invoice_chunks`,
   `get_all_invoice_chunks`) plus two operational scripts
   (`scripts/reembed_chroma_collections.py`'s `COLLECTION_PREFIX = "invoice_chunks_"`
   orphan-prune sweep, `scripts/sweep_sandbox_tenants.py`'s tenant-expiry sweep — neither
   touches Chroma for the `documents` table at all). Left as-is, a sandbox tenant's expiry
   deletes its `Invoice`/`Document` rows but leaves `docs_{tenant_id}` orphaned
   indefinitely — full page text of that tenant's POs and contracts, counterparty names and
   negotiated pricing, in a store nothing any longer associates with a live tenant. Same
   shape as Gap 239's orphan-citation problem. **Required:** either commit to the sibling
   delete/has/get-all functions and add `docs_` to the reembed script's prefix set as part
   of G10, or state explicitly that this is deferred and why — a decision either way, not
   silence.
4. **The placeholder-delete transaction (§2A/A3) needs two things stated, not implied.**
   Confirmed *not* currently exploitable — `file_path` is tenant-prefixed
   (`services/storage.py:20`) so the existing untenanted `file_path` lookups in
   `handlers.py` cannot cross a tenant boundary, and a mid-transaction crash leaves the
   placeholder with its original, correct `tenant_id`. Still, the spec should say, so the
   implementation doesn't drift from the safer of two available idioms: **(a)** the new
   `Document` row's `tenant_id` comes from the already-loaded `Invoice` DB row (the pattern
   every other persistence write in `handle_process_invoice` already uses —
   `handlers.py:692`, `:760`, `:785`, `:809` — not the raw `tenant_id` payload argument);
   **(b)** the placeholder is deleted by its resolved `id` (plus `tenant_id` as a
   belt-and-braces second predicate), never by `file_path` — `file_path` is not unique
   within a tenant (`routers/invoices.py:85`'s `DUPLICATE` rows share their original's
   `file_path`), so a `file_path`-keyed delete risks removing an unrelated duplicate
   pointer row.
5. **A second dedup site exists and E10 doesn't rule on it.** `routers/invoices.py:73–78`
   — the ingestion door's own duplicate-detection hash check, tenant-scoped today — will
   stop matching once a re-uploaded delivery note's original lives in `documents` instead
   of `invoice`, so every re-upload reprocesses (real OCR + extraction cost, contradicting
   E10's own billing reasoning). Widening it the same way §4's billing-quota fix does is
   reasonable, but the failure mode if the tenant predicate is dropped is worse than F2's:
   `routers/invoices.py:85` copies the matched row's `file_path` into the new row, so an
   unscoped match would durably write tenant A's blob path into tenant B's `Invoice` row.
   **Required:** the spec states one of — widen `_ingest_single_file`'s duplicate check the
   same tenant-scoped way as the billing-quota fix, **or** state explicitly that non-invoice
   re-uploads are left to reprocess in v1. Silence is the one option not available, given
   E10 already establishes "every door which creates a row shares this logic" (Gap 343).
   **Ruled and built 2026-09-02 (BE Gap 385, unfiled — §10B R0):** the check is widened,
   tenant-scoped on both sides, at `routers/invoices.py:80–113`; when the match is a
   `Document`, only the storage pointer (`file_path`) is copied — never `party_name` as
   `vendor_name`, never `doc_number` as `invoice_number`. Tests:
   `tests/test_ingestion.py:412 test_a_document_match_copies_the_storage_pointer_and_nothing_else`,
   `tests/test_documents_table.py:818`, `:981`.

---

## 2B. Amendments A5–A9 — taxonomy, attributes, advisory family, classifier, fixtures (founder-approved 2026-09-02)

**Numbering note, stated so it is not mistaken for a drift.** The founder's draft labelled
these A4–A8. **A4 is already taken** by the E10 security-hardening amendment above, and
that label is cited from code (`routers/invoices.py` "§2A/A4/F5", Gap 385) and from
`tests/test_documents_table.py`; renumbering it would orphan those references. The draft
numbers are therefore shifted by one: draft A4 → **A5**, A5 → **A6**, A6 → **A7**,
A7 → **A8**, A8 → **A9**. Draft A3 (the `documents` table) *is* the existing A3/E10 and
needs no new number — it is recorded as built under E10.

**Status of everything in this section: approved design, NOT code.** `DOC_TYPES` is still
the ten-value tuple at `services/document_type_classifier.py:74–85`; `DOC_TYPE_FAMILY` has
three families plus `OTHER`; `GenericDocumentSchema` carries E8's spine and nothing from
A6/A7. Each amendment names the E-items it edits (annotated in place) and the §10B task
that builds it. **Sequencing constraint carried from `active-work.md`:** none of A5–A9
starts until the existing ledger closes — commit, Postgres migration, task V — because
amending the taxonomy on top of an unverified ledger puts two unproven layers underneath
each other.

Source for all five: `docs/financial-document-taxonomy-research-2026-09-02.md` (§2 the
regional table, §5 the traps, §6 the actionable verdict). Cited as "research §n" below.

### A5 — `DOC_TYPES` widens from ten to fourteen. `PACKING_LIST` folds into `DELIVERY_NOTE`. Transport, customs, tax-certificate and timesheet documents are named as deferred `OTHER`.

**Decision.** Four values are added, in lifecycle position:

```python
DOC_TYPES = (
    "QUOTATION",
    "PROFORMA_INVOICE",
    "PURCHASE_ORDER",
    "ORDER_CONFIRMATION",     # A5 — new
    "CONTRACT",
    "DELIVERY_NOTE",          # A5 — now also absorbs PACKING_LIST
    "GRN",
    "INVOICE",
    "RECEIPT",                # A5 — new
    "CREDIT_NOTE",
    "DEBIT_NOTE",
    "REMITTANCE_ADVICE",      # A5 — new
    "STATEMENT_OF_ACCOUNT",   # A5 — new
    "OTHER",
)
```

| Added | Family (E4 / A7) | Why it is its own value (research §6.1) |
|---|---|---|
| `ORDER_CONFIRMATION` | Commitment (MQ) | Seller→buyer acknowledgement of a PO (Auftragsbestätigung, AB, Sales Order, OA, EDI 855). Very common in DE/IT/NL manufacturing and wholesale, and frequently the *real* agreed price rather than the PO. Distinguished from `PURCHASE_ORDER` by **direction** (A6), not by layout. |
| `RECEIPT` | Money, **relaxed rubric** | Payment receipts, fiscal receipts and simplified invoices (DE Kleinbetragsrechnung ≤ €250, IT scontrino / fattura semplificata ≤ €400, ES ticket / factura simplificada, PL ≤ PLN 450, India cash memo / B2C < ₹200 consolidated). By law they may lack the buyer's name, the unit price and the VAT amount (rate only) — research §5 trap 9 — so grading them on the full money rubric manufactures false discrepancies. Expenses volume is high. |
| `REMITTANCE_ADVICE` | **Advisory (A7)** | Payment advice with invoice-level allocations and deductions (India: TDS, GST-TDS, UTR; US: EDI 820 / CTX addenda, chargebacks; EU: Zahlungsavis, camt.054). The natural document for "what did they short-pay?". Never a payable. |
| `STATEMENT_OF_ACCOUNT` | **Advisory (A7)** | Monthly vendor statement / ledger / balance confirmation (SOA, Khata, Kontoauszug, Saldenbestätigung, relevé de compte, aging statement). Highest-value non-invoice for "which of these are missing or unpaid?". Research §5 trap 10: **must never be booked as a payable.** |

**Folded, not added:** `PACKING_LIST` → `DELIVERY_NOTE`. Same quantity rubric, same
absent-price expectation; the synonym table (A8) maps "Packing List", "Pack List", "Pick
Ticket", "Packliste", "Liste de colisage", "Distinta di imballaggio", "Paklijst" onto
`DELIVERY_NOTE`. `CORRECTIVE_INVOICE` and `CANCELLATION_INVOICE` are likewise **not**
types — they are a `CREDIT_NOTE` / `DEBIT_NOTE` with `correction_method` (A6); a separate
value is added only if ES/PL volume ever justifies it.

**Deferred to `OTHER`, named:** the list is written into E5 above so the omission is a
decision on record. `DUNNING` and `PAYMENT_PROOF` are also `OTHER` in v1 — advisory by
nature, and A7's family is built so that promoting either later is one enum entry plus
one synonym block.

**What does not change.** The three-family rubric table in E4 stands for the ten existing
values. `INVOICE` remains one value with sub-cases carried as attributes (A6), not as enum
entries — the reasoning in E4 ("splitting the enum would fragment every downstream
aggregate") is unchanged and A6 is how the sub-cases become data. Lifecycle ordering is
kept: quote → proforma → order → confirmation → contract → delivery → receipt-of-goods →
invoice → receipt-of-payment → adjustments → settlement → reconciliation.

**Edits:** E4 (annotated), E5 (deferred list written in), E7 (via A8), §7 (via A9),
`DOC_TYPE_FAMILY`, `_DOC_TYPE_OVERLAYS` (four new overlays; the `INVOICE`-family rule from
G3 — overlays written even where A2 makes them unreachable — applies to `RECEIPT`),
`_RUBRIC_BY_DOC_TYPE` (derived, so it follows the family map automatically — G5),
Feature 26's `_INTENT_BIAS_BY_DOC_TYPE` (Feature 26 B9). **Task: §10B R7.**

### A6 — Classification attributes: direction, invoice sub-type, correction method, cumulative block, regional identifiers, fiscal markers. Attributes on the row, not values in the enum.

**Decision.** Six attribute groups are recorded per classified document. They are the
mechanism by which research §5's traps 2, 5, 7, 8 and 9 become data rather than
guesses, and by which `INVOICE` stays one value (E4).

| Attribute | Values | Derived by | Consumed by |
|---|---|---|---|
| `direction` | `SUPPLIER_ISSUED` \| `BUYER_ISSUED` \| `SELF` | **Deterministic**: issuer tax ID vs recipient tax ID vs the tenant's own registered IDs. Same GSTIN/VAT-ID on both sides → `SELF`. Never from the printed title. | Disambiguates the German *Gutschrift* (self-billing vs commercial credit), a buyer-issued "credit note" (actually a debit claim), an RCM self-invoice (Rule 47A), ERS/pay-on-receipt. Feeds A8's ambiguity rule and Feature 26's comparison direction. |
| `invoice_subtype` | `STANDARD` \| `ADVANCE` \| `PARTIAL_PROGRESS` \| `FINAL` \| `SELF_BILLED` \| `SIMPLIFIED` \| `EXPORT` \| `RCM_SELF_INVOICE` \| `ISD` \| `BILL_OF_SUPPLY` | Deterministic title/marker pass first (A8), LLM fallback second, same two-stage shape as E7. `None` when not an INVOICE-family document. | The money rubric's **expected-absent** set per sub-type: `FINAL` must reference prior advances (DE §14(5)); `ISD` has no HSN and no taxable value; `BILL_OF_SUPPLY` has no tax; `SIMPLIFIED` may lack buyer and unit price. Same checks, different tolerated absences — no new branch in `verify_node`, a per-sub-type absence set the rubric reads. |
| `correction_method` + `references_original[]` | `DELTA` \| `SUBSTITUTION` \| `REVERSAL`; a list of referenced original document numbers | `references_original` from the extraction (`references[]` on `InvoiceExtractionSchema` already exists — Task 2.28); `correction_method` deterministic from region + markers (ES series "R" *por sustitución* → `SUBSTITUTION`, *por diferencias* → `DELTA`; PL *korygująca* → `DELTA`; IT TD04/TD05 → `DELTA`, storno in full → `REVERSAL`; DE Storno → `REVERSAL`; FR *avoir* → `DELTA`), LLM fallback otherwise. | Feature 26's comparison: a `SUBSTITUTION` credit note replaces the invoice's figures, a `DELTA` adjusts them, a `REVERSAL` zeroes them — three different diffs from one document type (Feature 26 B7). Also the reason `CORRECTIVE_INVOICE` is not an enum value (A5). |
| **Cumulative block**: `cumulative: bool`, `previous_billed`, `retention`, `advance_adjusted`, `current_due` | Decimal-or-`None` | Extraction fields, additive `Optional` — on `GenericDocumentSchema`, and for the INVOICE family carried in the existing `deductions[]` / `references[]` / `compliance_metadata[]` blocks so `InvoiceExtractionSchema`'s field set is **not** widened (A2 holds). Populated for RA bills, AIA G702/G703 pay applications, Abschlagsrechnung, facture de situation, SAL. | A new deterministic check in the money rubric, gated on `cumulative is True`: `previous_billed + current_due (+ retention held) == cumulative_to_date` — research §5 trap 5. "This bill" and "cumulative" are never conflated. **Out of v1 for Feature 26**: cumulative-vs-previous-bill comparison across two documents (Feature 26 "Not in scope"). |
| `regional_ids` | JSON map | Extraction, additive: GSTIN / PAN / IRN, VAT ID / USt-IdNr / SIREN / NIF / NIP / Codice Fiscale, EIN, EORI, KSeF number, SDI Codice Destinatario, Leitweg-ID. | Direction derivation above; tenant-identity matching in Feature 26 Tier 1/2; nothing in verification adjudicates on them (hard rule 3). |
| `fiscal_markers` | set of enum strings: `IRN_QR`, `SDI_ID`, `KSEF_NO`, `ATCUD`, `TSE_SIGNATURE`, `MYDATA_MARK`, `PEPPOL_TYPE_CODE:<n>` | **Deterministic** regex pass over `result.content` (A8 pre-check 1). | Strong evidence that a document *is* a real invoice-family document (research §5 trap 1(d)); consumed by the classifier as a pre-check, never as the whole verdict. A Peppol type code, where present, maps directly: 380 invoice, 381 credit note, 384 corrected, 386 prepayment, 389 self-billed. |

**Where the attributes live.** Classification-time attributes (`direction`,
`invoice_subtype`, `correction_method`, `fiscal_markers`, and a derived `rule_era` from
A8) are **columns on the row** — `Invoice` and `Document` both gain a nullable
`doc_attributes` JSON column (one migration, additive, NULL = never classified) — **not**
fields on the extraction schemas. This is what keeps A2 true: `InvoiceExtractionSchema` is
not widened by A6. Extraction-time attributes (`references_original`, the cumulative
block, `regional_ids`) are additive `Optional` fields on `GenericDocumentSchema` and are
carried by existing blocks on the invoice schema. Every attribute is nullable; `None`
means "not determined", never a default value — the Gap 283 discipline.

**Edits:** E4 (INVOICE sub-cases now enumerated as `invoice_subtype`), E6 (per-sub-type
expected-absent set; cumulative check), E7 (direction pre-check), E8 (additive fields),
E10 (`doc_attributes` on `Document`), §4 `models.py` row. **Task: §10B R8.**

### A7 — A fourth verification family, `ADVISORY`, with `referenced_documents[]` and `deductions[]`.

**Decision.** `DOC_TYPE_FAMILY` gains `ADVISORY_FAMILY` — research §2's "A" family —
holding `STATEMENT_OF_ACCOUNT` and `REMITTANCE_ADVICE` (and, when promoted from `OTHER`,
`DUNNING` and `PAYMENT_PROOF`). Its rubric, `_ADVISORY_RUBRIC`:

| Field | Value | Why |
|---|---|---|
| `run_line_item_math`, `run_totals_math` | `False` | Money-only documents with no line arithmetic (research §5 trap 6). A statement carries a running balance, not a subtotal/tax/total triple. |
| `require_currency` | `True` (declarative, as G5 left it) | Amounts without a currency are meaningless for reconciliation. |
| `price_fields_optional` | `True` | A remittance may list references and net amounts only. |
| `advisory_only` | `True` | **Never sets a review status, never enters spend.** These rows go to `documents` (E10), never `invoice`; `/dashboard/*` cannot see them by construction. |
| `run_field_confidence`, `run_di_tax_backfill` | `False` | DI's invoice fields force-fit onto a statement are wrong by construction (§8 trap 1). |
| status pair | `EXTRACTED` / `EXTRACT_FAILED` | Same as the GENERIC profile; no audit lifecycle. |

**Schema, additive on `GenericDocumentSchema` (E8), populated for this family:**

- `referenced_documents[]` — `{doc_number, doc_date, amount, currency, status_hint}`
  per referenced invoice/credit note; `status_hint` ∈ `OPEN` | `PAID` | `PARTIALLY_PAID`
  | `DISPUTED` | `None`, exactly as printed and never inferred.
- `deductions[]` — `{kind, amount, currency, reference}`; `kind` ∈ `TDS` | `GST_TDS` |
  `CHARGEBACK` | `SKONTO` | `EARLY_PAYMENT_DISCOUNT` | `RETENTION` | `OTHER`. This is
  what makes "what did they short-pay?" answerable from a remittance advice.

Both lists are `Optional`, default `None`, and are the input to Feature 26's
**list-reconciliation** comparison mode (Feature 26 B8): the document's referenced
numbers are joined to `Invoice` rows by normalised document number
(`services/document_comparison.py::normalize_doc_number`, exists), and the outcome per
reference is one of `found` / `not_found` / `status_mismatch` / `amount_mismatch` —
deterministic, `Decimal`, no LLM. Line-item diffing is **not** applied to this family;
there are no lines to diff.

**What the family is not.** Not `OTHER` with a friendlier name: `OTHER` means "we do not
know what this is", `ADVISORY` means "we know exactly what it is and it is not a
payable". The two share `advisory_only=True` and nothing else — `ADVISORY` has a schema
and a comparison mode; `OTHER` has neither.

**Edits:** E4 (family table gains a fourth row), E6 (rubric), E8 (two additive lists),
E10 (routing: `ADVISORY` → `documents`, already implied by "non-INVOICE family"),
`document_type_classifier.py::ADVISORY_FAMILY` constant beside the existing four,
`_GENERIC_FAMILY_STANCE` (one paragraph). **Task: §10B R9.**

### A8 — The classifier gains the research synonym table, two pre-checks, a mandatory ambiguity, and a rule era.

**Decision.** E7's two-stage mechanism is unchanged. Four inputs are added to it, in this
order of execution:

1. **Pre-check — fiscal markers (deterministic).** Before the title-band scan, a regex
   pass over `result.content` collects `fiscal_markers` (A6). A hit is *strong evidence
   for the INVOICE family* and is recorded as evidence; it is **not** the verdict — a
   credit note also carries an IRN, and an e-way bill quotes one (the T-C-4 case the
   title-band guard already handles).
2. **Pre-check — disclaimers (deterministic).** A second regex pass for phrases that mean
   *this is not a tax document*: "kein Vorsteuerabzug", "ne vaut pas facture", "non
   valido ai fini fiscali", "Proforma – not for ITC", "This is not a tax invoice", "not a
   VAT invoice". A hit **vetoes** `INVOICE` (and its sub-types) as a deterministic
   outcome for that document; the title-band scan then runs over the remaining values.
   This is research §5 trap 1(c) as code, and it is why a proforma that reuses an invoice
   template does not classify as an invoice on the strength of the word "Invoice" in its
   title.
3. **Synonym table (research §6.5), added to `_DOC_TYPE_SYNONYMS` in the module's
   normalised form** — beyond E4's `DELIVERY_NOTE` table, which stands:
   - `PROFORMA_INVOICE`: Pro forma, Proforma-Rechnung, Facture pro forma, Fattura
     proforma, Factura proforma, Proforma factuur, Faktura pro forma, Preliminary Invoice.
   - `ORDER_CONFIRMATION`: Auftragsbestätigung, AB, Order Acknowledgment, Order
     Acknowledgement, Conferma d'ordine, Confirmación de pedido, Orderbevestiging,
     Accusé de réception de commande, Potwierdzenie zamówienia, Sales Order, OA, PO
     Acknowledgment.
   - `DELIVERY_NOTE` (the A5 fold): Packing List, Pack List, Pick Ticket, Case List,
     Packliste, Liste de colisage, Distinta di imballaggio, Lista de embalaje, Paklijst,
     Lista pakowa, Dispatch Note, Job Work Challan, WZ, Guia de remessa.
   - `CREDIT_NOTE`: Avoir, Nota di credito, Factura rectificativa, Faktura korygująca,
     Creditnota, Credit Memo, Credit Memorandum, Jama, Sales Return, Rechnungskorrektur,
     Stornorechnung. **Not** "Gutschrift" — see 4.
   - `DEBIT_NOTE`: Debit Memo, Chargeback, Deduction Notice, Short-pay, Supplementary
     Invoice, Belastungsanzeige, Note de débit, Nota di debito, Debetnota, Naame.
   - `STATEMENT_OF_ACCOUNT`: Statement of Account, SOA, Kontoauszug, Saldenbestätigung,
     Relevé de compte, Estratto conto, Extracto de cuenta, Rekeningoverzicht, Ledger,
     Khata, Balance Confirmation, Vendor Statement, Account Statement, Aging Statement,
     Open Items, Vendor Reconciliation Statement.
   - `REMITTANCE_ADVICE`: Remittance Advice, Payment Advice, Zahlungsavis, Avis de
     paiement, Avviso di pagamento, Aviso de pago, Betalingsspecificatie, Check Stub,
     EFT Advice, Bhugtan vivaran.
   - `RECEIPT`: Receipt, Cash Memo, Register Receipt, Expense Receipt, Kleinbetragsrechnung,
     Facture simplifiée, Fattura semplificata, Scontrino, Factura simplificada, Ticket,
     Faktura uproszczona, Quittung, Reçu, Quietanza, Recibo.
   - `INVOICE` sub-type markers (feed `invoice_subtype`, A6, not the type): Bijak, Bill
     of Supply, Receipt Voucher, Payment Voucher, Self Invoice, ISD Invoice, RA Bill,
     Running Account Bill, Pay Application, AIA G702, Anzahlungsrechnung,
     Abschlagsrechnung, Schlussrechnung, Facture d'acompte, Facture de situation,
     Fattura di acconto, SAL, Export Invoice.
   - `OTHER` (deferred, deterministic so they never fall to the LLM): E-Way Bill, Lorry
     Receipt, Bilty, Bill of Lading, Air Waybill, CMR, Shipping Bill, Bill of Entry, CBP
     7501, Mahnung, Zahlungserinnerung, Relance, Mise en demeure, Sollecito, Past Due,
     Reminder, Timesheet, Form 16A, W-9, 1099.
   The G2 build note's constraints carry over unchanged: no two-letter synonyms except
   where the title-band coverage guard can redeem them (`AB`, `OA`, `WZ` are accepted
   only as the *entire* title line), containment resolves specificity, accents and
   acronym stops fold.
4. **"Gutschrift" is mandatory-ambiguous.** In §14 UStG it legally means a self-billing
   invoice issued by the customer; commercially it is used for a credit note. The word
   therefore **never** resolves deterministically. It goes to the LLM fallback **with the
   `direction` attribute (A6) supplied in the prompt**, and the fallback's answer is
   constrained by rule: `direction == SELF` or `BUYER_ISSUED` with no
   `references_original` → `INVOICE` / `invoice_subtype = SELF_BILLED`;
   `SUPPLIER_ISSUED` with `references_original` non-empty → `CREDIT_NOTE`. Research §5
   trap 2 and §3.3, verbatim: "classification must key on issuer direction + reference to
   prior invoice + sign of VAT, never on the word."
5. **`doc_date` drives the rule era.** A deterministic `rule_era` is derived from the
   document's date and region and stored with A6's attributes: India GST slab
   rationalisation (22 Sep 2025), India TDS section renumbering (1 Apr 2026), the EU
   e-invoicing go-lives (BE 1 Jan 2026, PL 1 Feb / 1 Apr 2026, FR 1 Sep 2026, DE 1 Jan
   2027/2028). **The classifier does not consume it** — it is a verification input: a
   credit note dated before 22 Sep 2025 legitimately carries a GST rate that no longer
   exists, and the rubric must not flag it. HSN→rate is never hard-coded (research §3.1).

**Threshold (N2) unchanged and still uncalibrated** at `DOC_TYPE_CONFIDENCE_THRESHOLD =
0.6`; A9's fixture cells are what calibrate it. Task F Dispatch B's three real LLM-path
data points (0.90 / 0.92 / 0.95) suggest 0.75–0.8 but are too few to move it.

**Edits:** E7 (annotated), `_DOC_TYPE_SYNONYMS`, two new module-level pre-check tables,
`_classify_with_llm`'s prompt (direction supplied), `DocTypeClassification` (unchanged —
still a `Literal` over `DOC_TYPES`, now fourteen). **Task: §10B R10.**

### A9 — Fixture cells and tests for A5–A8.

**Fixture cells added to §7's table** (research §6.6): `ORDER_CONFIRMATION` (DE
Auftragsbestätigung, IT conferma d'ordine); `STATEMENT_OF_ACCOUNT` (IN, US, DE);
`REMITTANCE_ADVICE` (IN with TDS + GST-TDS lines, US with EDI-820-style deductions);
`RECEIPT` (DE Kleinbetragsrechnung, ES ticket, IT scontrino); a DE "Gutschrift" of
**each** meaning (self-billing and commercial credit — the pair that proves A8 item 4);
an ES factura rectificativa *por sustitución* and one *por diferencias*; an Indian Rule
55 delivery challan **with** taxable value and tax (the quantity-family-with-prices case
E4 already requires); an Indian RA bill and a US AIA G702 (the cumulative block); an
E-Way Bill and a Bill of Entry (to prove `OTHER` routing stays deterministic). Same
rules as §7: real where obtainable, realistic synthetic where not, provenance and the
expected evidence phrase in `MANIFEST.md`, classifier confidence recorded per file.

**Tests added to §9** (numbering avoids the existing T-R-6/T-R-7 — the founder's draft
"T-R-6..9" maps to T-R-8..11 here):

- **T-C-5** — the two pre-checks: a proforma on an invoice template with "ne vaut pas
  facture" classifies `PROFORMA_INVOICE` deterministically and `get_llm` is
  `assert_not_called()`; a document carrying an IRN+QR marker and the title "Tax Invoice"
  classifies `INVOICE` with the marker recorded in `fiscal_markers`; **both** DE
  Gutschrift fixtures go to the fallback (`doc_type_method == "llm"`), and the fallback
  resolves them differently on `direction` alone.
- **T-C-6** — every A8 synonym, parametrised, classifies deterministically to its A5
  canonical value with no model call (the T-C-1 shape over the widened table); the
  `PACKING_LIST` fold lands on `DELIVERY_NOTE`; every deferred-`OTHER` synonym lands on
  `OTHER` deterministically.
- **T-R-8** — `ADVISORY` family: a statement and a remittance advice produce zero
  arithmetic alerts, no `low_confidence_field` alert, `EXTRACTED`, `referenced_documents`
  and `deductions` populated from the fixture, and **no `invoice` row** (T-E10-1's shape).
- **T-R-9** — `RECEIPT`: a Kleinbetragsrechnung with no buyer name and no unit price
  produces no missing-field or arithmetic alert; the same document as `INVOICE` (control)
  does.
- **T-R-10** — cumulative block: an RA bill whose `previous_billed + current_due (+
  retention)` equals `cumulative_to_date` passes; one that does not raises exactly one
  alert naming the three figures; a non-cumulative invoice never runs the check.
- **T-R-11** — `correction_method` / `references_original`: the ES *por sustitución* and
  *por diferencias* fixtures classify `CREDIT_NOTE` with `SUBSTITUTION` and `DELTA`
  respectively and both carry the original's number; a `REVERSAL` (DE Storno) too.
- **T-A-1** — `direction` is derived from tax IDs, never from the title: swapping the
  printed title on a fixture does not change `direction`; swapping the GSTINs does.

**Edits:** §7 table, §9, `tests/fixtures/doc_types/MANIFEST.md`. **Task: §10B R11
(functional-tester for fixtures, senior-dev for tests).**

---

## 2C. Not in scope (v1) — stated so absence is a decision

- **`prebuilt-layout`** or any OCR-model selector (§2A/A1 "Considered and rejected").
- **A per-tenant flag** for `ENABLE_GENERIC_EXTRACTION` (E2). If a per-tenant rollout is
  wanted, it is a separate deployment.
- **Transport, customs, tax-certificate and timesheet documents as typed values** — they
  route to `OTHER` (E5, A5). E-Way Bill and Bill of Entry are the named v2 candidates.
- **`CORRECTIVE_INVOICE` / `CANCELLATION_INVOICE` as enum values** — carried as
  `correction_method` on `CREDIT_NOTE` / `DEBIT_NOTE` (A6).
- **Chat over documents** — the attached-document surface is Feature 26; the `documents`
  table is invisible to the NL→SQL route in v1 (Gap 381 open item 5) and "show me my
  delivery notes" is unanswerable from chat until a scoped Feature 6/26 task adds it.
- **A backend-flag exposure endpoint for the FE** — the mechanism G11's `DropZone`
  widening needs does not exist and is a BE product decision (§10B R5), not part of this
  feature's ledger.
- **Widening `InvoiceExtractionSchema`** — A2 and A6 both preserve it; sub-type data
  rides in existing blocks and on the row.
- **Attachment-vs-attachment three-way matching**, cross-source questions, and
  cumulative-vs-previous-bill comparison — Feature 26's "Not in scope" list; recorded
  here because A6's cumulative block would otherwise look like an invitation.
- **Rate lookups** — HSN→rate tables, VAT-rate tables, simplified-invoice thresholds per
  country (research §7 lists them as unverified). The rubric reads what the document
  prints; it never adjudicates against an external rate.

---

## 3. Design decisions — E1 to E10

### E1 — The flag is named `ENABLE_GENERIC_EXTRACTION`.

Matches this repo's existing convention exactly. `config.py` already carries
`ENABLE_ASYNC_CHAT_QUEUE` (L61) and `ENABLE_PRODUCTION_QUALITY_JUDGE` (L311) —
both `bool`, both defaulting `False`, both pydantic-settings fields read from
env, both carrying a long docstring that states what turning them on costs and
what evidence flips them. `FF_*` prefixes appear nowhere in this codebase.
`ENABLE_GENERIC_EXTRACTION: bool = False` sits alongside them with the same
shape and the same fail-closed default, for the same reason every other flag in
that file has one: a deployment that has not thought about this must get
today's behaviour.

### E2 — The flag is software-level, NOT per-tenant. Stated so nobody re-adds it.

Founder's decision, verbatim: *"This switch is not at tenant level its at
software level."*

**There is no per-tenant override in this design.** Not a `Tenant` column, not a
row in the rules table, not an entry in the plug-and-play workflow config, not a
header. One global env-driven boolean, resolved once through
`config.get_settings()`, identical for every tenant in the deployment.

This is recorded as a decision rather than an omission because the obvious
"improvement" — letting a pilot tenant opt in — is specifically the thing not to
build. Reasons, so the decision survives review:

- **The mechanism does not exist.** `config.py` has no per-tenant flag pattern
  at all. Every `ENABLE_*` there is process-wide. Building the first per-tenant
  feature-flag system as a side effect of a document-type change means designing
  flag storage, precedence, caching and an admin surface, none of which is this
  feature.
- **The extraction graph has no tenant plumbing to hang it on.**
  `run_extraction_agent()` (L943–951) takes `tenant_id` for telemetry only — the
  audit confirmed it never queries per-tenant configuration. A per-tenant flag
  would have to be resolved by every one of the **eight** call sites
  (`agents/outbound_extraction_agent.py:66`, `agents/trainer_agent.py:166`,
  `benchmarks/extraction/harness.py:125`, `queue_worker/handlers.py:652` and
  `:672`, `routers/audit.py:304`, `routers/chat_attachments.py:218`,
  `routers/trainer.py:623`) and threaded in — a much larger blast radius than
  the feature itself.
- **Mixed-mode data is worse than either mode.** With a per-tenant flag, two
  tenants' documents in the same Chroma/Postgres shape would have been extracted
  under different schemas and verified under different rubrics, with nothing on
  the row saying which. Benchmarks, the quality judge and the workbooks would
  all be averaging across two incomparable populations.

If a per-tenant rollout is ever genuinely wanted, the correct shape is a
separate deployment (the dev/prod split already in `infra/params.*.json`), not a
row-level flag. **Do not add one to this feature.**

### E3 — Flag OFF is byte-identical to today's behaviour.

Not "equivalent", not "should be the same" — *identical*, and it is a testable
claim, not an aspiration. With `ENABLE_GENERIC_EXTRACTION=False`:

- `_run_ocr()` calls `model_id="prebuilt-invoice"` for every document, in both flag
  states. **(A1, rewritten 2026-09-02.)** The OCR model is never chosen by flag or by
  type. What the document family chooses is **how much of the one response is
  consumed**: the INVOICE family consumes `content`, `pages` and `documents[].fields`
  (→ `field_confidence`, `coordinates`, `tax_details_sum`, `source_document_json`)
  exactly as today; non-INVOICE families consume `content` and `pages` with
  invoice-field consumption disabled by the rubric (G7) and no `invoice` row written
  (G9/E10). With the flag OFF the INVOICE path is the only path, so the OCR stage is not
  merely equivalent — it is the same call with the same consumers. `prebuilt-layout` was
  never coded and will not be: §2A/A1 "Considered and rejected".
- **The INVOICE family's schema, prompts and direction profile are untouched in both
  flag states** (A2): `InvoiceExtractionSchema` / `OutboundInvoiceExtractionSchema`,
  `_DirectionProfile`, `_DIRECTION_PROFILES["INBOUND"|"OUTBOUND"|"REFERENCE"]` and
  `resolve_direction_profile()` (other than E9's fail-loud) are byte-identical.
  `GenericDocumentSchema` is reachable only for a non-INVOICE `doc_type` through
  `resolve_extraction_profile()`.
- The compiled graph's entry point is `classify` (complexity), the existing
  `classify_node` (L837). The new `classify_doc_type` node is not in the
  executed path.
- `_DIRECTION_PROFILES` resolves to exactly the three entries that exist today
  (`INBOUND`, `OUTBOUND`, `REFERENCE`), with the same schemas, prompts,
  `required_fields`, status vocabularies and `legacy_audit_path_shim` values.
- `verify_node` runs the money rubric unconditionally, as it does now.
- No embedding call is made from the extraction path.
- `ReferenceDocExtractionSchema` keeps its current three-value `doc_type`
  instruction.

The verification for this is not "the tests still pass" — it is a named test
(T-OFF-1, §9) that runs the same fixture through the pipeline with the flag off
and asserts the extracted dict is equal, field for field, to the recorded
pre-change output.

**Exception, stated openly:** E9's `resolve_direction_profile` fail-loud change
ships regardless of flag state. It is the one deliberate unconditional change,
and §3.E9 explains why and bounds its blast radius.

### E4 — The document-type taxonomy. Ten values, research-derived, closed enum.

*(Annotation 2026-09-02: **Amendment A5 widens this to fourteen values** and A7 adds a
fourth family, `ADVISORY`. The ten below are what is coded —
`services/document_type_classifier.py:74–85` — and the text of this section is left as
the record of that decision. The fourteen-value enum is design, not code, until §10B
task R7 lands.)*

The original engineering sketch guessed
`{INVOICE, PURCHASE_ORDER, QUOTATION, CHALLAN, GRN, CREDIT_NOTE, DEBIT_NOTE, CONTRACT, OTHER}`.
That guess is superseded. The shipped vocabulary, derived from how the
procure-to-pay document chain actually works across the three regions this
product targets (US, EU, India), is:

```python
DOC_TYPES = (
    "QUOTATION",
    "PROFORMA_INVOICE",
    "PURCHASE_ORDER",
    "CONTRACT",
    "DELIVERY_NOTE",
    "GRN",
    "INVOICE",
    "CREDIT_NOTE",
    "DEBIT_NOTE",
    "OTHER",
)
```

Listed in **commercial-lifecycle order**, deliberately: quote → proforma →
order → contract → delivery → receipt → invoice → adjustments. That ordering is
not cosmetic — it is the order a matching/reconciliation feature will eventually
walk, and keeping the enum in it means the enum itself documents the chain.

**Two real additions the original guess missed:**

- **`PROFORMA_INVOICE`** is a distinct, high-frequency type, not a synonym for
  quotation and not a variant of invoice. It sits *after* commitment and
  *before* shipment: it is issued once the buyer has committed, states the exact
  goods, values and terms, and is used to open letters of credit, arrange
  advance payment and clear customs. Structurally it looks like an invoice
  (line items, taxes, grand total) but it is **not a tax document** — it creates
  no receivable, no input-tax credit, and no payment obligation of its own.
  Folding it into `INVOICE` would put a non-payable into the payable family;
  folding it into `QUOTATION` would put a committed value into the negotiating
  family. It gets its own value.
- **`DELIVERY_NOTE`** replaces the original guess's India-specific `CHALLAN`
  label. This is one canonical type with **regional synonyms the classifier must
  recognise and normalise**:

  | Region | Printed on the document |
  |---|---|
  | India | "Delivery Challan", "Challan", "Goods Delivery Note" |
  | US | "Packing Slip", "Packing List", "Delivery Note", "Shipping List" |
  | Germany / DACH | "Lieferschein" |
  | Italy | "DDT" (*Documento di Trasporto*) |
  | France | "Bon de livraison" |
  | Netherlands | "Pakbon" |
  | Spain | "Albarán" |

  Naming the canonical value after a region-specific label (`CHALLAN`) would
  have been an actual defect: a `Lieferschein` and a delivery challan are the
  same document type and must land on the same value, and no future reader
  should have to know Hindi commercial vocabulary to understand a German
  supplier's paperwork. The synonym table above ships **in the classifier's
  prompt and in a deterministic normalisation map**, not as a comment.

**`GRN` is kept, and is flagged low-frequency / internal-origin.** A Goods
Receipt Note is not a standard externally-exchanged commercial document in the
US, the EU or India — it is generated by the *buyer's* own receiving process and
in most organisations never leaves the buyer's ERP. It appears in this product's
world in one specific circumstance: a large enterprise buyer sharing its GRN
with a supplier to substantiate a short-delivery or damage claim. It stays in
the enum because when it does appear it is unambiguous and its handling is
genuinely different (see the quantity family below), but implementers should
expect it to be rare and should **not** treat low GRN volume as a classifier
defect. Fixture sourcing (§7, F-6) treats it accordingly: a realistic synthetic
sample is acceptable here where a real sample cannot be obtained.

**`INVOICE` is one top-level type with documented sub-cases, not a family of
types.** The following are all `INVOICE`:

- India: **Tax Invoice** (GST, with GSTIN/HSN/place-of-supply, CGST+SGST or
  IGST split), **E-Invoice** (a Tax Invoice that additionally carries an IRN and
  signed QR from the IRP), **Bill of Supply** (issued by a composition dealer or
  for exempt supplies — no tax charged, structurally still an invoice).
- EU: **VAT Invoice** (Article 226 mandatory particulars), including
  reverse-charge and intra-community-supply variants.
- US: a commercial invoice with sales tax where applicable.

These are **sub-cases carried in the extracted fields**, not separate enum
values. The existing `InvoiceExtractionSchema` already has a
`compliance_metadata` block (`ComplianceMetadataItem`, L105) built precisely to
hold IRN/QR/Peppol identifiers, and the existing complexity classifier
(`services/invoice_classifier.py::classify_invoice_complexity`) already keys on
`gst`/`cgst`/`sgst`/`igst`/`hsn`/`vat`/`reverse charge`. Splitting the enum
would fragment every downstream aggregate — spend, dashboard insights, the
AUDIT_REQUIRED count — across values that all mean "a bill we owe".

**The three verification families.** This is the taxonomy's real payload, and
what E6's mode-aware `verify_node` keys on:

| Family | Types | Rubric |
|---|---|---|
| **Money** | `INVOICE`, `PROFORMA_INVOICE`, `CREDIT_NOTE`, `DEBIT_NOTE` | Full existing arithmetic: line-item sum vs subtotal, subtotal + tax − discount vs grand total, currency present, faithfulness against OCR. This is today's rubric, unchanged. |
| **Quantity** | `DELIVERY_NOTE`, `GRN` | Price fields are **optional and frequently absent by design** — a delivery note commonly prints quantity and description only, precisely so the recipient's warehouse staff cannot see pricing. Absent price is **not** a discrepancy. Checks: quantities present and numeric; line count sane; no total-arithmetic check attempted unless prices are actually present, in which case the money checks run additionally, not instead. |
| **Money + quantity, terms-heavy, longer-horizon** | `PURCHASE_ORDER`, `CONTRACT` | Do **not** structurally conflate with `INVOICE`. These carry commitments over a horizon: delivery schedules, milestones, validity windows, payment terms, incoterms, penalty/liquidated-damages clauses, renewal and termination terms. Arithmetic checks run where totals are printed, but an unpriced or partially-priced schedule line is normal, and a `CONTRACT` frequently has no grand total at all (rate cards, framework agreements). Missing-total is not a failure for this family. |

`OTHER` runs the money rubric in **advisory mode only**: alerts are recorded but
never set a review status, because we do not know what the document is and have
no rubric we can defend.

### E5 — v1 scope exclusion: transport documents and e-way bills. A decision, not an omission.

`BILL_OF_LADING`, air waybills, `CMR` consignment notes, and **India's e-way
bill** are real, regulated, high-volume documents. They are deliberately **out
of v1** and route to `OTHER`.

Stated as a decision because the omission is otherwise indistinguishable from an
oversight, and because someone will ask:

- They are **transport/custody** documents, not commercial-value documents. A
  bill of lading is a document of title — it can be negotiable, endorsed and
  transferred, and possession of the original can constitute possession of the
  goods. That is a materially different legal object from any of the ten types
  above and should not inherit a rubric designed for commercial values.
- Their identifiers are **carrier-issued and externally verifiable** (an e-way
  bill has an EWB number issued by the NIC portal with its own validity window
  keyed to distance). Extracting them without validating them against their
  issuing authority produces a number that *looks* authoritative and is not —
  which is the failure class hard rule 3 exists to prevent.
- Nothing downstream consumes them yet. There is no logistics surface in this
  product for a transport document to feed.

**Behaviour today:** a bill of lading classifies as `OTHER`, extracts against
the universal base schema, verifies in advisory mode, and produces no false
discrepancy. That is the correct v1 outcome. Adding them later is a new enum
value plus an overlay plus a rubric — additive, not a rework.

**The deferred-to-`OTHER` list, named in full (A5, 2026-09-02).** So the omission is
never mistaken for an oversight, these are the document kinds the research
(`docs/financial-document-taxonomy-research-2026-09-02.md` §6.3) identified and this
feature **deliberately routes to `OTHER` in v1**: `TRANSPORT_DOCUMENT` (Lorry Receipt /
Bilty, **E-Way Bill**, Bill of Lading, Air Waybill, CMR, ASN); `CUSTOMS_DOCUMENT`
(Shipping Bill, Bill of Entry, CBP 7501, SAD); `TAX_CERTIFICATE` (Form 16A, GSTR-7A,
W-9, 1099, resale/exemption certificates); `TIMESHEET` / `COMPLETION_CERTIFICATE`
(timesheet, SES, acceptance certificate, measurement book, lien waiver). Two are named
as **v2 candidates with a stated reason**: the India E-Way Bill carries value and tax
breakup and users will ask "does the EWB match the invoice?" (a money+quantity rubric);
the Bill of Entry auto-populates GSTR-2B input-tax credit. `TIMESHEET` is the services
equivalent of `GRN` and would join the quantity family if service invoices become a
real use case. `PACKING_LIST` is **not** deferred — A5 folds it into `DELIVERY_NOTE`.

### E6 — Mode-aware `verify_node`, keyed on the family, not on the type.

`verify_node` (L694) gains a rubric selector. It does **not** get a
`if doc_type == "DELIVERY_NOTE"` chain — the family table in E4 is the single
declaration, one lookup, so adding an eleventh type later is one map entry and
not a new branch in verification code.

Concretely:

- A `_VerificationRubric` dataclass alongside `_DirectionProfile`, declaring:
  `run_line_item_math: bool`, `run_totals_math: bool`,
  `require_currency: bool`, `price_fields_optional: bool`,
  `advisory_only: bool`, and the status pair to emit — plus two fields added by A1,
  which govern the *Document Intelligence*-derived checks rather than the arithmetic ones:
  - `run_field_confidence: bool` — gates the Gap 3 / Task 2.32 Critic step
    (`verify_field_confidence`, `verify_node` L806–813). `True` for the money family only.
    `False` elsewhere because that check maps DI's *invoice* field names onto invoice
    schema names, so on a delivery note it emits `low_confidence_field` alerts about
    fields the document does not have — and that alert type is non-retryable and forces
    a review status, which is the exact false-failure this feature exists to remove.
  - `run_di_tax_backfill: bool` — gates the Gap 68 `tax_details_sum` backfill in
    `extract_node` (L681–689). `True` for the money family only; a document that prints
    no tax must not acquire one from DI's misparse.
- `_RUBRIC_BY_DOC_TYPE: Dict[str, _VerificationRubric]` — one entry per enum
  value, derived from the family table.
- With the flag OFF, `verify_node` never consults the map. With it ON, the map
  is consulted once and the existing check calls are gated on the resolved
  rubric's booleans. **The check functions themselves
  (`utils/verification_tools.py::verify_line_items_math` /
  `verify_totals_math`) are not modified** — they are correct; what was wrong
  was running them unconditionally.

Hard rule 3 note: every one of these checks stays deterministic Python. The
classifier (E7) picks the rubric; it does not adjudicate any figure. No LLM
decides whether a document reconciles.

### E7 — `classify_doc_type` becomes the graph's new first node.

New node, new entry point when the flag is ON. OCR runs before the graph and is
unconditional `prebuilt-invoice` (A1), so the classifier reads `result.content` — the
same string every extraction prompt is already built from — and no OCR-model decision
has to precede it:

```
_run_ocr (prebuilt-invoice, unconditional)
  → classify_doc_type → classify (complexity) → dynamic_qa → extract → verify
```

- The existing `classify_node` (complexity STANDARD/COMPLEX,
  `services/invoice_classifier.py`) is **unchanged and keeps its position** —
  the two classifications are orthogonal (an invoice and a contract can each be
  simple or complex) and merging them would couple two things that change for
  different reasons.
- `classify_doc_type` is a **two-stage** classifier, deterministic-first:
  1. **Deterministic pass** over the OCR text's first page / title band against
     `_DOC_TYPE_SYNONYMS` — the E4 synonym table, plus each canonical name.
     A high-confidence unambiguous hit short-circuits with **no LLM call at
     all**. This is not an optimisation, it is the control: "Lieferschein" in
     the title band is a fact about the document, not a judgement, and facts
     belong in code. It also makes the common case free and offline-testable.
  2. **LLM fallback** only when the deterministic pass is empty or ambiguous
     (two families matched), using `with_structured_output` against a closed
     `DocTypeClassification` pydantic model — `doc_type: Literal[...]` over the
     ten values, plus `confidence: float` and `evidence: str` (the verbatim
     printed phrase it decided from). `Literal` over the closed enum means an
     invented value is a validation error, not a silently-stored string.
- Low confidence (`< 0.6`) or a validation failure → `OTHER`, recorded with the
  reason. Never a guess promoted to a type. **`0.6` is a placeholder, not a calibrated
  number (§2A/N2):** it was chosen before any real fixture existed and must be validated
  against §7 task F's real India delivery-challan and EU synonym fixtures — whose manifest
  records the classifier's returned confidence per file for exactly this purpose — before
  it is treated as fixed.
- The decision is written to `ExtractionState["doc_type"]` and
  `["doc_type_evidence"]`, and both are persisted, so a misclassification is
  reviewable after the fact rather than only being a wrong answer.
- Telemetry: one `tracked_llm_call("extraction.classify_doc_type", ...)` on the
  fallback path only, matching the pattern `dynamic_qa_node` already uses
  (L875–881), so the deterministic path costs nothing and shows as nothing.

*(Annotation 2026-09-02: **Amendment A8** extends the deterministic pass with the
research's synonym table, two pre-checks that run before the title-band scan — fiscal
markers and disclaimers — a mandatory *ambiguous* verdict for "Gutschrift", and a
`doc_date`-derived rule era. The mechanism above is unchanged; A8 adds inputs to it.
Design, not code, until §10B task R10.)*

### E8 — Universal base schema plus per-type overlays. One schema object, not ten.

**Scope, amended by A2: this section applies to non-INVOICE `doc_type`s only.** The INVOICE
family (`INVOICE`, `PROFORMA_INVOICE`, `CREDIT_NOTE`, `DEBIT_NOTE`) keeps
`InvoiceExtractionSchema` / `OutboundInvoiceExtractionSchema` and the existing
`_DIRECTION_PROFILES` machinery unchanged in both flag states. Nothing below is ever
applied to an invoice.

`ReferenceDocExtractionSchema` (L213) is widened into
`GenericDocumentSchema` — **additively; the existing class stays and keeps
working for the flag-OFF path** — carrying the union spine every commercial
document has:

`doc_type`, `party_name`, `counterparty_name`, `doc_number`, `po_number`,
`reference_numbers[]`, `doc_date`, `valid_until`, `currency`, `subtotal`,
`tax_amount`, `discount_amount`, `grand_total`, `items[]`, `taxes[]`,
`payment_terms`, `delivery_terms`, `incoterms`, `notes`.

`GenericLineItem` widens `ReferenceDocLineItem` (L205) with the quantity family's
needs: `quantity_ordered`, `quantity_delivered`, `quantity_received`, `uom`,
`batch_or_serial`, alongside the existing `description`, `quantity`,
`unit_price`, `amount`. Every field `Optional` with a `None` default — a
delivery note legitimately has no `unit_price` and a contract legitimately has
no `grand_total`, and **`None` must mean "the document did not state it", never
zero.** That distinction already exists in the codebase's discipline (see
`verify_node`'s Gap 283 correction at L720–730, which fixed exactly the
truthiness bug where a real 0.00 was read as missing) and must not be
re-introduced here.

**Overlays are prompt-level, not schema-level.** `_DOC_TYPE_OVERLAYS: Dict[str, str]`
maps each type to extra prompt instructions appended to the base extraction
prompt — e.g. for `DELIVERY_NOTE`: "prices are frequently absent by design; do
not infer them, leave them null, and do not compute a total"; for `CONTRACT`:
"capture validity window, renewal and termination terms into `notes`; a
framework agreement may have no grand total". One structured-output schema means
one `with_structured_output` call shape and one place where a field can drift —
ten schemas would mean ten.

### E9 — `resolve_direction_profile` fails loud. Ships regardless of flag state.

Today (L550–553):

```python
return _DIRECTION_PROFILES.get((flow_direction or "INBOUND").upper(), _DIRECTION_PROFILES["INBOUND"])
```

An unrecognised direction silently becomes INBOUND — meaning
`InvoiceExtractionSchema`, the inbound prompt, `COMPLETED`/`AUDIT_REQUIRED`, and
the `"audit" in file_path` legacy shim. A typo (`"REFERNCE"`) or a future fourth
direction added to one caller and not to the map produces a *plausible wrong
answer* rather than an error. That is the highest-severity class of defect this
file can have, and it is latent today.

**Fix, precisely bounded so it cannot break the eight existing call sites:**

- `flow_direction` that is `None`, absent, or empty/whitespace → **still
  defaults to `INBOUND`**, unchanged. This is what
  `agents/trainer_agent.py:166`, `routers/trainer.py:623` and
  `benchmarks/extraction/harness.py:125` rely on, and what every pre-Gap-283
  persisted state dict relies on. Preserving it is required, not optional.
- A **non-empty string that is not a key in `_DIRECTION_PROFILES`** → raise
  `UnknownFlowDirectionError(ValueError)` naming the value received and listing
  the valid keys.
- **Applies with the flag ON or OFF.** This is deliberate and is the single
  exception to E3. Gating a fail-loud correction behind the flag would mean the
  footgun stays armed in exactly the configuration that is in production today,
  and this feature is the change that makes a fourth/fifth direction value
  likely.
- Blast radius, enumerated so the risk is a known quantity: the eight call sites
  pass, in total, `"OUTBOUND"` (outbound agent), `"REFERENCE"`
  (chat_attachments), an explicit direction from the invoice row
  (handlers/audit), or nothing at all (trainer ×2, benchmark harness). None can
  reach the raise. The raise is reachable only by new or typo'd code — which is
  the point.

### E10 — Non-invoice documents live in their own table and their own Chroma collection.

**Decision.** A non-INVOICE-family document is not an `Invoice` row. It is a row in a new
`documents` table, indexed into a `docs_{tenant_id}` sibling Chroma collection.
`Invoice.doc_type` / `Invoice.doc_type_evidence` are still added — an invoice's own
sub-type is real information — but no non-INVOICE row is ever written to `invoice`.

The full reasoning, the counted site list, the table shape, the row-creation sequence and
the billing-quota consequence are in **§2A/A3**, which is where this decision was made and
where its evidence lives. Summarised so E10 stands on its own: option (a) — keeping
non-invoice documents in `invoice` and filtering everywhere — was measured, not estimated,
and comes to **39 tenant-scoped query sites across 19 files**, one of which (the chat
NL→SQL route) cannot be filtered deterministically at all without resurrecting the SQL
rewriter deleted at Gap 253. The same decision was already taken and shipped for chat
attachments (Feature 26 D2, `models.py` L244–251), and the failure mode has already
occurred once on this table (Gap 329, `flow_direction`). Structural separation is the only
form of this that survives the next person adding a query.

**Built (uncommitted) — 2026-09-02, Gap 381. Evidence from the status audit, so E10 is a
decision with code behind it rather than a decision alone:** `models.py:206 class
Document` / `:207 __tablename__ = "documents"`, `models.py:192–193 Invoice.doc_type` /
`doc_type_evidence`; `queue_worker/handlers.py:385 _routes_to_documents_table()`, `:493
Document(`, `:936` (the persistence fork); `routers/documents.py:165 @router.get("")`,
`:208 @router.get("/{document_id}")`, registered at `main.py:181`; `chroma_client.py:383
_document_collection_name()`, `:411 get_document_collection()`;
`alembic/versions/e4f5a6b7c8d9_add_doc_type_and_documents_table.py:81–100`; the
billing-quota union in `services/billing_quota.py`; and — closing A4/F5, which the Gap 381
note below still lists as open — the ingestion-door dedup widened tenant-scoped to
`Document.file_hash` at `routers/invoices.py:80–113` (**Gap 385**, unfiled; §10B R0).
**Unproven:** the migration has never been applied to Postgres and
`tests/test_documents_table.py` has never completed a run (Build status header). One
stale remark in A3 above: "`chroma_client.py` has no `_chat_doc_collection_name` today" —
Feature 26 H2 has since built it (`chroma_client.py:340`); the precedent is now shipped
code.

---

## 4. File Coordinates

### BE — new files

| File | Contents |
|---|---|
| `services/document_type_classifier.py` | `DOC_TYPES` (the closed tuple), `DOC_TYPE_FAMILY` map, `_DOC_TYPE_SYNONYMS` (E4's regional synonym table), `classify_doc_type_deterministic(ocr_text) -> tuple[str|None, str]`, `DocTypeClassification` (pydantic, `Literal` over `DOC_TYPES`), `classify_doc_type(ocr_text, ocr_result) -> dict`. Deliberately its own module, not appended to `services/invoice_classifier.py`: that file answers "how hard is this to extract", this one answers "what is it", and they are consulted at different points for different reasons. |
| `tests/test_document_type_classifier.py` | Deterministic-pass coverage per synonym per region; ambiguity → fallback; invented value → validation error; low confidence → `OTHER`. |
| `tests/test_generic_extraction.py` | Flag-ON pipeline tests: per-family rubric selection, quantity-family no-false-discrepancy, contract-with-no-total, `OTHER` advisory mode. |
| `tests/test_extraction_flag_off_parity.py` | E3's byte-identical assertion (T-OFF-1). |
| `routers/documents.py` | `GET /documents` (list, tenant-scoped, soft-delete aware) + `GET /documents/{id}` — the minimum surface that keeps a classified non-invoice upload visible to its uploader (E10). **Both endpoints go through `_require_owned_document(document_id, db_session, tenant_context)` (A4/F1), mirroring `routers/chat_attachments.py:109–120` exactly — 404, never 403, on a cross-tenant hit.** Task G14. |
| `tests/test_documents_table.py` | E10's proof: a `DELIVERY_NOTE` ingestion leaves no `invoice` row; `/dashboard/insights` totals are byte-identical before and after; the same file re-uploaded is not billed twice; **tenant B requesting tenant A's document id gets 404 (A4/T-E10-5).** |

### BE — modified files

| File | Change |
|---|---|
| `config.py` | `ENABLE_GENERIC_EXTRACTION: bool = False`, with a docstring in the house style (what it turns on, what it costs, what evidence flips it, and an explicit "this is software-level, not per-tenant — see `feature_27_generic_extraction.md` E2"). Placed adjacent to `ENABLE_ASYNC_CHAT_QUEUE` (L61) / `ENABLE_PRODUCTION_QUALITY_JUDGE` (L311). |
| `agents/extraction_agent.py` | `GenericDocumentSchema` + `GenericLineItem` (additive, beside `ReferenceDocExtractionSchema` L213 which is untouched) — **non-INVOICE families only (A2)**; `_DOC_TYPE_OVERLAYS`; `build_generic_multimodal_prompt` / `_build_generic_text_prompt`; a fourth `GENERIC` entry in the profile map plus **`resolve_extraction_profile(flow_direction, doc_type)`**, which delegates to `resolve_direction_profile` in every case except (flag ON ∧ INBOUND ∧ `doc_type` not None ∧ family ≠ INVOICE); `_VerificationRubric` (incl. A1's `run_field_confidence` / `run_di_tax_backfill`) + `_RUBRIC_BY_DOC_TYPE`; the Gap 68 DI tax backfill (L681–689) gated on `run_di_tax_backfill`; `classify_doc_type_node`; `verify_node` rubric gating (L694+); `resolve_direction_profile` fail-loud (L550) + `UnknownFlowDirectionError`; `pdf_to_base64_images` → `document_to_base64_images` (E-non-PDF, below); graph assembly (L913–930) conditional entry point; `run_extraction_agent()` (L943) gains `doc_type: Optional[str] = None` (a caller-supplied override that **skips** classification — used by `routers/chat_attachments.py` when the user has already told us what they attached) and returns `doc_type` / `doc_type_evidence` in its result dict. |
| `queue_worker/handlers.py` | **(A1) `_run_ocr()` is unchanged — no model selector, no `prebuilt-layout` branch.** `model_id="prebuilt-invoice"` (L204) stays for every document in both flag states; `result.content` and `result.pages` are all this feature needs and are required members of `AnalyzeResult` regardless of model. What *does* change in this file: the persistence step gates `invoice.coordinates` on the INVOICE family (non-INVOICE persists `[]`, since DI's boxes are labelled with invoice field names), and the post-classification routing (E10) writes the `documents` row and deletes the placeholder `invoice` row in one transaction. |
| `models.py` | `Invoice.doc_type` (nullable, default `None`) + `Invoice.doc_type_evidence` — nullable so every existing row is valid without a backfill, and so flag-OFF writes `None` exactly as today. **Plus (E10) a new `Document` model, `__tablename__ = "documents"`** — the full column list is in §2A/A3. `Invoice` gains no other column; non-invoice rows never land in it. |
| `alembic/versions/<new>_add_doc_type.py` | Two nullable columns on `invoice`, **plus `create_table("documents")` (E10)** — one migration, since a `documents` row's existence is what makes the `invoice` columns' INVOICE-only meaning true. `down_revision` = whatever is current head at write time (`c2d3e4f5a6b7` today — re-check, Feature 26 Part 2 may land a migration first). |
| `chroma_client.py` | `_document_collection_name(tenant_id) -> f"docs_{tenant_id}"` and `index_document_chunks()` — a generalisation of `index_invoice_document()` (L370) writing to the **sibling** collection, never the tenant invoice collection (E10). **Must pass `_collection_metadata()`** (see §8.2 — a collection created without it is permanently on L2 and needs a drop + re-embed). `query_invoice_chunks()` is untouched and, by construction, cannot reach `docs_{tenant}`. |
| `utils/llm.py` | No change required by this feature. Listed here only to record that it was checked: `get_llm()` takes `max_tokens` only, and this feature adds no new keyword to it. |
| `services/billing_quota.py` | `count_billable_uploads()` dedup set widened to **`{Invoice.file_hash WHERE tenant_id = :t} ∪ {Document.file_hash WHERE tenant_id = :t}` (E10, tenant predicate mandatory per A4/F2)** — the union must stay per-tenant on both sides, or a file two tenants happen to share (a vendor's standard template) lets one tenant's upload go unbilled and turns the counter into a cross-tenant oracle. The **only** filter in this feature that widens rather than narrows — miss the predicate and it also leaks. |

### FE — modified files (additive section into `apps/invoice-fe/docs/feature_3_ingestion.md`)

| File | Change |
|---|---|
| `types/invoice.ts` | Optional `doc_type?: string` on the invoice/status shapes. |
| `components/ingestion/StatusTable.tsx` | A document-type column/badge, rendered only when `doc_type` is present. Absent → the table renders exactly as today. |
| `components/ingestion/DropZone.tsx` | Accept list widened from `.pdf` to `.pdf,.png,.jpg,.jpeg,.tiff` **only when the flag is on** (surfaced via the existing config/feature endpoint, not hardcoded). `MAX_FILE_SIZE` (L22, 25 MB) unchanged. The suffix guard (~L57) and the `accept` attribute (~L121) are the two places to change — they are separate checks and both must agree, or a user drags a PNG past the picker and is rejected after selection. |
| `components/audit/*` detail view | Show `doc_type` + `doc_type_evidence` on the record, so a misclassification is visible and reportable rather than only being wrong. |

### Non-PDF image support

`pdf_to_base64_images()` (L256–277) opens bytes with
`fitz.open(stream=pdf_bytes, filetype="pdf")`. Hand it a PNG and the `except`
at L275 logs and returns `[]` — the multimodal visual channel is **silently
lost** and extraction degrades to OCR-text-only with no warning anywhere. That
silent degradation is the actual defect, more than the missing format.

Rename to `document_to_base64_images(file_path)`, dispatch on suffix:

- `.pdf` → today's `fitz` page-render path, unchanged.
- `.png` / `.jpg` / `.jpeg` / `.tiff` / `.bmp` / `.webp` → single-page: read
  bytes, normalise to PNG via `pillow` (already a dependency, `pillow>=12.2.0`),
  base64-encode, return a one-element list.
- Anything else → return `[]` **and log at WARNING with the extension**, so the
  degradation is at least visible.

Keep `pdf_to_base64_images` as a thin alias so no existing caller or test
breaks.

---

## 5. Functionality — end to end, flag ON

1. A file arrives by any existing route (upload, connector sync, email
   ingestion, chat attachment). Nothing about the routes changes.
2. `_run_ocr()` runs `prebuilt-invoice` — **for every document, in both flag states; the
   model is never selected (A1, rewritten 2026-09-02)**. It returns `result.content` (the
   full document text) and `result.pages` (page geometry), which are required members of
   `AnalyzeResult` for every model, plus the invoice-specific `documents[].fields`. **What
   the document family decides is how much of that response is consumed downstream**: the
   INVOICE family keeps every consumer it has today (Critic, Gap 68 backfill, coordinates
   overlay, complexity classifier); a non-INVOICE family consumes `content` and `pages`
   only — steps 6–8 switch the invoice-field consumers off by rubric and by table
   routing. There is no `prebuilt-layout` call anywhere in this flow (§2A/A1 "Considered
   and rejected").
3. `classify_doc_type_node` runs the deterministic synonym pass over the title
   band. "Lieferschein" → `DELIVERY_NOTE`, no LLM call. Ambiguous → one
   structured-output call against `DocTypeClassification`. Low confidence →
   `OTHER`. The decision and its evidence phrase are written to state.
4. `classify_node` runs unchanged, deciding STANDARD/COMPLEX independently.
5. `dynamic_qa_node` runs unchanged for COMPLEX documents.
6. `extract_node` resolves its profile through `resolve_extraction_profile(flow_direction,
   doc_type)` **(A2)**:
   - **INVOICE family** (or `doc_type is None`, or `flow_direction` is OUTBOUND/REFERENCE)
     → the existing profile, unchanged: `InvoiceExtractionSchema` /
     `OutboundInvoiceExtractionSchema` / `ReferenceDocExtractionSchema`, the existing
     prompts, the existing required-field set and status vocabulary. Tasks 2.21–2.31's
     field set and the Gap 31/33/36/43/44/46 faithfulness checks stay wired exactly as
     they are today. **Nothing about an invoice changes when the flag is on.**
   - **Non-INVOICE family** → the `GENERIC` profile: the base template plus the type's
     overlay, `with_structured_output(GenericDocumentSchema)`. Missing fields come back
     `None`, never zero.
   The Gap 68 DI tax backfill runs only where the rubric's `run_di_tax_backfill` is set —
   i.e. the money family (A1).
7. `verify_node` resolves the rubric from `_RUBRIC_BY_DOC_TYPE`. A delivery note with no
   prices raises **no** arithmetic alerts, **and no `low_confidence_field` alerts either**
   — `run_field_confidence` is False for its family, so DI's confidence scores for
   invoice fields it force-fit onto a non-invoice are never consulted (A1). An invoice
   raises exactly the alerts it raises today, from exactly the same checks on exactly the
   same DI output. An `OTHER` records alerts advisory-only.
8. **Persistence forks on the family (E10).** INVOICE family → the `invoice` row is
   updated as today, now also carrying `doc_type` / `doc_type_evidence`, with
   `coordinates` persisted as usual. Non-INVOICE family → a `documents` row is written
   with the extracted spine, `doc_type`, `doc_type_evidence`, `doc_type_confidence` and a
   status of `EXTRACTED` / `EXTRACT_FAILED`, and the placeholder `invoice` row created at
   upload is deleted **in the same transaction**. `coordinates` are not carried over —
   DI's boxes are labelled with invoice field names and would mislabel a PO (A1).
9. **Embed step:** if the status is indexable (`should_index_status()` semantics
   preserved), the chunks are embedded and written **to the collection that matches the
   row's table** — `index_invoice_document()` → the tenant invoice collection for an
   invoice, `index_document_chunks()` → `docs_{tenant_id}` for a document (E10). Both
   pass `_collection_metadata()`. Chunks are header-prefixed with the document type so a
   future retrieval path can distinguish a quotation's price from an invoice's; in v1 no
   invoice-side retrieval path can see `docs_{tenant}` at all, which is the point.
10. The FE shows the type as a badge and the evidence phrase on the detail view.

---

## 6. Files-touched table

| Path | New/Modified | Owner | Notes |
|---|---|---|---|
| `apps/invoice-be/config.py` | M | senior-dev | Flag + docstring |
| `apps/invoice-be/agents/extraction_agent.py` | M | senior-dev | Largest single change; schema, overlays, node, rubric, fail-loud, image dispatch, graph |
| `apps/invoice-be/services/document_type_classifier.py` | N | senior-dev | Classifier + taxonomy + synonyms |
| `apps/invoice-be/queue_worker/handlers.py` | M | senior-dev | (A1) no OCR model change; coordinates gated to INVOICE family; (E10) documents-row routing |
| `apps/invoice-be/routers/documents.py` | N | senior-dev | E10 — `GET /documents` list + detail (G14) |
| `apps/invoice-be/services/billing_quota.py` | M | senior-dev | E10 — dedup set widened, not narrowed |
| `apps/invoice-be/tests/test_documents_table.py` | N | senior-dev | E10's exclusion + no-double-billing proof |
| `apps/invoice-be/models.py` | M | senior-dev | Two nullable columns |
| `apps/invoice-be/alembic/versions/<new>.py` | N | senior-dev | Re-check `down_revision` at write time |
| `apps/invoice-be/chroma_client.py` | M | senior-dev | `index_document_chunks()`, must pass `_collection_metadata()` |
| `apps/invoice-be/tests/test_document_type_classifier.py` | N | senior-dev | Narrow, per convention |
| `apps/invoice-be/tests/test_generic_extraction.py` | N | senior-dev | |
| `apps/invoice-be/tests/test_extraction_flag_off_parity.py` | N | senior-dev | E3's proof |
| `apps/invoice-be/tests/fixtures/doc_types/**` | N | functional-tester | §7 — the named prerequisite |
| `apps/invoice-fe/types/invoice.ts` | M | senior-dev | |
| `apps/invoice-fe/components/ingestion/StatusTable.tsx` | M | senior-dev | |
| `apps/invoice-fe/components/ingestion/DropZone.tsx` | M | senior-dev | Two guards, both must change |
| `apps/invoice-fe/docs/feature_3_ingestion.md` | M | senior-dev | **Additive section only** (hard rule 4) |
| `apps/invoice-be/docs/be_features_tracker.md` | M | senior-dev | Gap entry, same change as the code |

---

## 7. PREREQUISITE TASK — F: real sample documents for every type. Named, owned, not assumed.

**This is a blocking prerequisite for the benchmark plan and for any accuracy
claim about this feature. It is called out as its own task with its own owner
because the founder chose the thorough option over a lighter subset, and because
a taxonomy nobody has real documents for is a hypothesis, not a capability.**

**Owner: functional-tester.** Output: `apps/invoice-be/tests/fixtures/doc_types/`
plus a manifest row per file and a coverage entry in
`apps/invoice-be/docs/test_coverage_map.md`.

Precedent for the shape: `tests/india/inbound/` and `tests/eu/inbound/` already
hold six graded PDFs each (`*_correct_simple/medium/complex`,
`*_erroneous_simple/medium/complex`) with `ground_truth_line_items.md` alongside.
**Follow that structure**, do not invent a second one.

Required coverage — at least one sample per cell, real where obtainable,
realistic synthetic where not, and the manifest must record which:

| Type | India | EU | US | Notes |
|---|---|---|---|---|
| `QUOTATION` | Yes | Yes | Yes | |
| `PROFORMA_INVOICE` | Yes | Yes | Yes | Must be a genuine proforma, not a quotation relabelled |
| `PURCHASE_ORDER` | Yes | Yes | Yes | |
| `CONTRACT` | Yes | Yes | Yes | Include at least one with **no grand total** (rate card / framework) |
| `DELIVERY_NOTE` | Yes — required ("delivery challan") | Yes — required (at least one of Lieferschein / DDT / bon de livraison / albarán) | Recommended ("packing slip") | **The synonym-recognition proof.** India + at least one of EU/US is the minimum bar; all three preferred. At least one sample must have **no prices at all** — that is the case the quantity rubric exists for |
| `GRN` | Yes | — | — | Low-frequency/internal-origin (E4). Realistic synthetic acceptable and expected |
| `INVOICE` | Yes — Tax Invoice, E-Invoice (IRN+QR), Bill of Supply | Yes — VAT invoice, reverse-charge | Yes | Partly covered by existing `tests/india`, `tests/eu` fixtures — **reuse, do not duplicate** |
| `CREDIT_NOTE` | Yes | Yes | Yes | |
| `DEBIT_NOTE` | Yes | Yes | Yes | |
| `OTHER` | Yes | | | At least one **bill of lading** and one **e-way bill**, to prove E5 routes them to `OTHER` cleanly rather than mis-typing them |

Rules for the fixture set:

- **No real customer data.** Any real sample is anonymised — party names,
  addresses, tax IDs, bank details, contact details all replaced. Record the
  provenance and the anonymisation in the manifest.
- **Synthetic must be realistic, not schematic** — real layout, real regional
  tax structure, real title band wording, real regional date/number formats
  (Indian lakh/crore grouping, EU comma decimal separator). A synthetic sample
  that is trivially easy to classify proves nothing about the classifier.
- **Ground truth per file**: expected `doc_type`, expected family, and the
  expected `doc_type_evidence` phrase (the printed title the classifier should
  cite). Without the expected evidence phrase, a right answer for the wrong
  reason is indistinguishable from a right answer.
- **Cap the set**: aim for ~30–40 files, not hundreds. The goal is one defensible
  sample per cell, not a benchmark corpus.

**Sequencing:** F can and should run **in parallel** with the code tasks — it
does not block writing the classifier, it blocks *claiming the classifier
works*. Nothing in §9's verification plan may be marked passing before F is
complete for the cells that verification touches.

---

## 8. Known traps carried forward from the audit — read before starting

1. ~~**The dict-shape contract out of `_run_ocr`.**~~ **Void as of A1** — this trap
   existed only because of the `prebuilt-layout` switch, which is no longer part of this
   feature. `_run_ocr`'s dict shape is unchanged, `_serialize_di_document_fields` and the
   `tax_details_sum` derivation still receive `documents[].fields`, and
   `classify_invoice_complexity` keeps its `field_confidence` keying with no behaviour
   change for any document.

   **Replaced by the trap A1 actually found: DI's invoice fields are populated for
   non-invoice documents, and they are wrong.** `prebuilt-invoice` does not decline to
   analyse a delivery note — it force-fits `VendorName` / `InvoiceId` / `InvoiceTotal`
   onto it at low confidence. Anything that reads `documents[].fields` without first
   checking the family therefore produces a confident-looking wrong answer rather than an
   empty one. The three sites: `verify_field_confidence` (the Critic — gated by
   `run_field_confidence`), the Gap 68 `tax_details_sum` backfill (gated by
   `run_di_tax_backfill`), and `coordinates` persistence (gated on the family at the
   handler). `source_document_json` is left populated deliberately — it is diagnostic and
   is already excluded from every LLM-visible projection (`agents/query_tools.py`
   L168–169, `agents/sage_prompts.py` L271–273). **Absence of data is not the hazard here;
   presence of confident wrong data is.**

2. **`MockInvoiceLLM` (`utils/llm.py`).** It implements exactly
   `with_structured_output()` and `invoke()`. This feature's classifier uses
   `with_structured_output`, so it works in mock mode **provided** the mock's
   `_generate_structured` fallback (`try: return schema_cls()`) can construct
   `DocTypeClassification`. Give every field on that model a default so it can.
   If it cannot, mock mode raises inside a `try/except Exception` and the failure
   presents as a classification miss, not an error. This is the same class of
   masking that hid the `get_llm(temperature=0)` bug for as long as it did.
3. **Chroma `hnsw:space`.** Any new `get_or_create_collection()` call added by
   the embed step (§5 step 9) **must** pass `_collection_metadata()`
   (`chroma_client.py` L84–101 → `{"hnsw:space": "cosine"}`). Verified live
   against chromadb 1.5.9: passing it to a collection that *already exists*
   silently returns the existing collection still on `l2`, with no error and no
   warning — so a collection created without it is permanently wrong and
   requires a drop + re-embed (`scripts/reembed_chroma_collections.py`).
   `RELEVANCE_DISTANCE_THRESHOLD = 0.49` is calibrated in cosine space and means
   nothing in L2. **Latent instance found 2026-09-02:**
   `scripts/migrate_chroma_to_per_tenant.py:67` calls
   `get_or_create_collection(name=target_name)` with **no metadata** — a one-shot
   legacy migration script, not on the live path, but it is the exact trap and
   should be corrected or explicitly marked dead in the same pass. Applies equally
   to E10's `docs_{tenant_id}` collection.

---

## 9. Verification Plan

Design intent. The live record of what is actually automated goes in
`apps/invoice-be/docs/test_coverage_map.md`.

**Flag-OFF parity (the E3 proof)**
- **T-OFF-1** — the same fixture through the pipeline with the flag off produces
  an extracted dict equal, field for field, to the recorded pre-change output.
  Not "tests pass" — an equality assertion against a committed golden.
- **T-OFF-2** — the full existing backend suite passes with the flag off. Named
  files that must remain green and are most exposed: `tests/test_sse.py` (relies
  on the `legacy_audit_path_shim`), `tests/test_extraction*`,
  `tests/test_chat_attachments.py` (24 passing today), `tests/test_rag.py`,
  `tests/test_chat_progress.py` (13), `tests/test_chat_queue.py` (19).
- **T-OFF-3** — E9's fail-loud is the only behaviour change visible with the flag
  off: `None`/`""` still resolves INBOUND; `"REFERNCE"` raises.

**Classifier**
- **T-C-1** — every synonym in E4's table classifies to its canonical value via
  the **deterministic** pass, asserted by patching `get_llm` and proving it was
  **not called** (the same assertion shape Gap 366 used for `classify_query`).
- **T-C-2** — an ambiguous document falls back to the LLM path and its output is
  constrained: an invented `doc_type` raises a pydantic validation error rather
  than being stored.
- **T-C-3** — confidence below threshold → `OTHER`, with the reason recorded.
- **T-C-4** — a bill of lading and an e-way bill both classify `OTHER` (E5).

**Rubrics**
- **T-R-1** — a `DELIVERY_NOTE` with quantities and **no prices** produces zero
  arithmetic alerts and a passing status.
- **T-R-2** — a `CONTRACT` with no grand total produces no missing-total alert.
- **T-R-3** — an `INVOICE` produces the identical alert set it produces today.
- **T-R-4** — `OTHER` records alerts but never sets a review status.
- **T-R-5** — `None` is never coerced to `0` anywhere in the base schema
  (regression guard on the Gap 283 truthiness class of bug).
- **T-R-6** — **the ON-case mirror of T-OFF-1 (A2).** With the flag **ON**, an
  INVOICE-family fixture through the pipeline produces an extracted dict equal, field for
  field, to the flag-OFF output on that same fixture. An equality assertion against the
  same committed golden T-OFF-1 uses — not a spot-check of a few fields, because a
  generic-schema extraction of an invoice still returns plausible `vendor_name` and
  `grand_total` and would pass anything weaker while silently dropping
  `compliance_metadata`, `tax_ids`, `payment_instructions`, `addresses`, `deductions`,
  `round_off` and per-line `hsn_sac_code`. This is the single test that proves turning the
  flag on does not regress the product's existing business.
- **T-R-7** — a `DELIVERY_NOTE` produces **no `low_confidence_field` alerts** even when
  `ocr_result["field_confidence"]` contains low scores for `VendorName` / `InvoiceTotal`
  (A1). Asserted on a hand-built `ocr_result` so the case is deterministic and offline.

**OCR + images**
- **T-O-1** — **(A1, replaces the `prebuilt-layout` flow test, which no longer has a
  subject.)** `_run_ocr` issues `model_id="prebuilt-invoice"` with the flag ON, asserted
  against the mocked Document Intelligence client. This is a negative test on purpose: it
  is the guard that stops a future change from reintroducing a model selector without
  also reinstating the four consumers that depend on the invoice-specific response.
- **T-O-2** — a PNG produces a non-empty `document_to_base64_images` result; an
  unsupported extension returns `[]` **and logs a WARNING**.

**Table separation (E10)**
- **T-E10-1** — ingesting a `DELIVERY_NOTE` end-to-end leaves **zero** rows in `invoice`
  for that file and exactly one in `documents`, with `status="EXTRACTED"`.
- **T-E10-2** — the Gap 329-shaped assertion: `/dashboard/insights` (totals by currency,
  status breakdown, top vendors, spend-over-time) returns byte-identical output before and
  after a `DELIVERY_NOTE` and a `PURCHASE_ORDER` are ingested for the same tenant. This is
  the test that would have caught Gap 329, applied pre-emptively to the new row kind.
- **T-E10-3** — re-uploading the same non-invoice file does not consume quota twice
  (`count_billable_uploads` dedups across `Invoice.file_hash ∪ Document.file_hash`), and a
  first upload of one **does** consume quota once.
- **T-E10-4** — `docs_{tenant_id}` is created with `hnsw:space == "cosine"` (§8.3), and
  `query_invoice_chunks()` on the same tenant never returns a chunk from it.

**Table separation, continued (A4)**
- **T-E10-5** — *(from §2A/A4 item 1)* tenant B requesting tenant A's `document_id` gets
  404, never 403; `GET /documents` for B returns zero of A's rows; soft-deleted rows are
  invisible on both endpoints. Built in `tests/test_documents_table.py`; no recorded run.

**Amendments A5–A9 (design; none built)**
- **T-C-5**, **T-C-6**, **T-R-8**, **T-R-9**, **T-R-10**, **T-R-11**, **T-A-1** — as
  specified in §2B/A9. None exists in code.

**Evidence standard:** hard rule 2 — any "verified" claim cites a Postgres run.
SQLite-only is not evidence. The classifier tests are pure-Python and may run
anywhere, but the pipeline and persistence tests must cite Postgres. **T-E10-1/2/3 are
persistence and aggregate tests and therefore must cite a Postgres run**; an SQLite pass on
these proves nothing, and the SQLite/Postgres fidelity gap has already caused 4+ incidents
in this repo.

---

## 9A. Acceptance requirements — R-27-nn

One ID per acceptance item, so a test, a build note and a tracker entry can all point at
the same thing. Each names its E-item and the test(s) that prove it. **Status** is the
2026-09-02 audit's: *built* = code exists in the working tree; *SQLite* = passing tests
exist but none against Postgres; *Postgres* = a recorded hard-rule-2 run exists;
*design* = no code.

| ID | Requirement | Decision | Proof | Status |
|---|---|---|---|---|
| R-27-01 | `ENABLE_GENERIC_EXTRACTION` exists, defaults `False`, is process-wide, has no per-tenant override | E1, E2 | `config.py:115`; docstring | built |
| R-27-02 | Flag OFF: the compiled graph has no `classify_doc_type` node and `resolve_extraction_graph()` returns the module-level `graph` by identity | E3, E7 | T-OFF-1 (graph-structure half), G4 note | SQLite |
| R-27-03 | Flag OFF: the same fixture yields an extracted dict field-for-field equal to the committed golden | E3 | T-OFF-1 (equality half) | design — no golden committed |
| R-27-04 | Flag OFF: the full existing backend suite passes | E3 | T-OFF-2 | **FAILING** — 14 failed / 2280 passed (2026-09-02); 1 is this feature's (`test_documents_table.py::test_the_lifecycle_functions_never_open_a_collection_without_the_metadata` → R6), 13 are not |
| R-27-05 | A non-empty unknown `flow_direction` raises `UnknownFlowDirectionError`; `None`/blank still resolves INBOUND; in both flag states | E9 | T-OFF-3; `test_a_padded_or_typod_direction_now_raises`, `test_e9_raises_with_the_flag_off_too[…]` | SQLite (Gap 384) |
| R-27-06 | `prebuilt-invoice` is the only OCR model string; `_run_ocr` is unchanged | A1 | T-O-1; repo grep | built |
| R-27-07 | Every E4 synonym classifies deterministically with no model call | E7 | T-C-1 (47 parametrised) | SQLite / pure-Python |
| R-27-08 | Ambiguous title → LLM fallback; an invented value is a validation error, never stored | E7 | T-C-2 | pure-Python |
| R-27-09 | Confidence below `DOC_TYPE_CONFIDENCE_THRESHOLD` → `OTHER` with reason recorded | E7, N2 | T-C-3 | pure-Python; threshold uncalibrated |
| R-27-10 | Bill of lading and e-way bill (incl. one quoting a tax-invoice number) → `OTHER` | E5 | T-C-4 | pure-Python |
| R-27-11 | Title-band coverage guard: a reference number quoted in body text never decides the type | G2 build note | `test_a_purchase_order_number_quoted_on_an_invoice_is_not_a_purchase_order` | pure-Python |
| R-27-12 | INVOICE family keeps `InvoiceExtractionSchema` / `OutboundInvoiceExtractionSchema` and its profile in both flag states; generic schema only for non-INVOICE | A2 | T-R-6; A2 truth-table tests | SQLite (T-R-6 equality half: design) |
| R-27-13 | `DELIVERY_NOTE`/`GRN` with no prices: zero arithmetic alerts, both check functions never called; with prices present, money checks run additionally | E4, E6 | T-R-1 | SQLite |
| R-27-14 | `CONTRACT` with no grand total: no missing-total alert; commitment family still runs arithmetic where printed | E4, E6 | T-R-2 | SQLite |
| R-27-15 | An INVOICE produces the identical alert set, status and `call_args_list` with the flag on and off | E6, A2 | T-R-3 | SQLite |
| R-27-16 | `OTHER` records alerts but never sets a review status; `extraction_failed` is not suppressed | E4, E6 | T-R-4 | SQLite |
| R-27-17 | `None` is never coerced to `0` anywhere on the generic schema | E8 | T-R-5 | SQLite |
| R-27-18 | Non-INVOICE family: no `low_confidence_field` alerts, no DI tax backfill, no coordinates persisted | A1, G7 | T-R-7; backfill tests; `_should_persist_coordinates` tests | SQLite (Gap 379) |
| R-27-19 | A PNG/JPG/TIFF/BMP/WEBP yields one base64 page; unsupported extension returns `[]` **and** logs WARNING; `pdf_to_base64_images` alias unchanged | §4 image support | T-O-2; G8 tests | SQLite (Gap 384) |
| R-27-20 | A non-INVOICE ingestion leaves zero `invoice` rows and exactly one `documents` row, `EXTRACTED`, placeholder deleted in one transaction, `tenant_id` from the loaded row, delete keyed on id+tenant | E10, A4/F4 | T-E10-1 | **built, never run** |
| R-27-21 | `/dashboard/insights` is byte-identical before and after non-invoice ingestion | E10 | T-E10-2 | built, never run |
| R-27-22 | Billing dedup is `{Invoice.file_hash WHERE tenant} ∪ {Document.file_hash WHERE tenant}`; a second tenant's first upload **is** charged | E10, A4/F2 | T-E10-3 | built, never run |
| R-27-23 | `docs_{tenant}` is cosine-space and unreachable from `query_invoice_chunks()` | E10, §8 trap 3 | T-E10-4 | built, never run |
| R-27-24 | Cross-tenant `GET /documents/{id}` → 404 never 403; list is tenant-scoped; soft-delete invisible | A4/F1 | T-E10-5 | built, never run |
| R-27-25 | Ingestion-door duplicate check matches `Document.file_hash` tenant-scoped; only `file_path` is copied from a `Document` match | A4/F5 | `test_a_document_match_copies_the_storage_pointer_and_nothing_else` | SQLite (Gap 385, unfiled) |
| R-27-26 | Migration `e4f5a6b7c8d9` applies, downgrades and re-applies on Postgres | G9 | task V | **never applied** |
| R-27-27 | Fixture set covers every §7 cell with provenance and expected evidence phrase; confidence recorded per file | §7 | `MANIFEST.md` | 10/10 types × 1 sample (16 files); regional matrix incomplete |
| R-27-28 | `DOC_TYPES` is the fourteen-value A5 tuple; `PACKING_LIST` synonyms → `DELIVERY_NOTE`; deferred types → `OTHER` deterministically | A5, A8 | T-C-6 | design |
| R-27-29 | A6 attributes are derived and stored; `direction` from tax IDs only; `Gutschrift` is never deterministic | A6, A8 | T-C-5, T-A-1, T-R-11 | design |
| R-27-30 | `ADVISORY` family: no arithmetic, no review status, no `invoice` row, `referenced_documents[]` + `deductions[]` populated | A7 | T-R-8 | design |
| R-27-31 | `RECEIPT` relaxed rubric; cumulative-block check for progress bills | A5, A6 | T-R-9, T-R-10 | design |
| R-27-32 | G11 rollout gate: a classified non-invoice is visible to its uploader before the flag is on anywhere user-facing | N1, E10 | FE Gap 378; `GET /documents` consumer | `[~]` |

## 9B. Traceability — senior-dev fills one row per R-id as each task lands

Rules: `file:function` is the real symbol, not the file alone; *test name* is the exact
pytest node; *status* is one of `design` / `built` / `SQLite` / `Postgres` / `blocked`
with the blocker named. A row may cite the audit as its source but must be re-verified
at fill time.

| R-id | file:function | test name | status |
|---|---|---|---|
| R-27-01 | | | |
| R-27-02 | | | |
| R-27-03 | | | |
| R-27-04 | | | |
| R-27-05 | | | |
| R-27-06 | | | |
| R-27-07 | | | |
| R-27-08 | | | |
| R-27-09 | | | |
| R-27-10 | | | |
| R-27-11 | | | |
| R-27-12 | | | |
| R-27-13 | | | |
| R-27-14 | | | |
| R-27-15 | | | |
| R-27-16 | | | |
| R-27-17 | | | |
| R-27-18 | | | |
| R-27-19 | | | |
| R-27-20 | | | |
| R-27-21 | | | |
| R-27-22 | | | |
| R-27-23 | | | |
| R-27-24 | | | |
| R-27-25 | | | |
| R-27-26 | | | |
| R-27-27 | | | |
| R-27-28 | | | |
| R-27-29 | | | |
| R-27-30 | | | |
| R-27-31 | | | |
| R-27-32 | | | |

---

## 10. Tasks

**Rebuilt 2026-09-02 (design-completion pass).** §10 is now two lists: a **status
ledger** of what is built, each row carrying the audit's `file:line` evidence, and
**§10B, the only open items**, sequenced. The build notes that follow §10B are the
per-task records and are unchanged. Everything in the ledger is **uncommitted** (Build
status header).

### 10.1 Status ledger — G1–G14, F

| Task | Status | Gap | Evidence (working tree, 2026-09-02) |
|---|---|---|---|
| G1 flag + docstring (E1, E2) | `[x]` | 369 | `config.py:115` |
| G2 classifier module (E4, E7) | `[x]` | 369 | `services/document_type_classifier.py:74 DOC_TYPES`, `:363 classify_doc_type_deterministic`, `:407 DocTypeClassification`, `:500 classify_doc_type`, `:587 _classify_with_llm`; `tests/test_document_type_classifier.py` (21 defs, all pass) |
| G3 generic schema + overlays + prompt builders (E8, A2) | `[x]` | 371 | `agents/extraction_agent.py:311 GenericDocumentSchema`, `:739 _DOC_TYPE_OVERLAYS`, `:1173` |
| G3b `resolve_extraction_profile` + `GENERIC` entry (A2) | `[x]` | 372 | `extraction_agent.py:1353`; A2 truth-table tests |
| G4 `classify_doc_type_node` + conditional graph (E7, E3) | `[x]` | 375 | `extraction_agent.py:2039`, `:2214 add_node`, `:2261 resolve_extraction_graph` |
| G5 rubric + `verify_node` gating (E6) | `[x]` | 377 | `extraction_agent.py:1387 _VerificationRubric`, `:1448–1533` rubrics/maps, `:1640` lookup |
| **G6** fail-loud `UnknownFlowDirectionError` (E9) | **`[x]` — corrected 2026-09-02; was marked open while built** | **384 (unfiled)** | `extraction_agent.py:1185 class UnknownFlowDirectionError`, `:1205 _VALID_FLOW_DIRECTIONS = ("INBOUND","OUTBOUND","REFERENCE")` (G3b's carried constraint honoured — not `_DIRECTION_PROFILES.keys()`), `:1255 raise`; tests `test_a_padded_or_typod_direction_now_raises[…]` (`:649`), `test_e9_raises_with_the_flag_off_too[…]` ×4, `…_on_too[…]` ×4, `test_generic_is_not_an_accepted_flow_direction[…]` ×4, `test_the_generic_profile_is_not_reachable_through_any_real_flow_direction` (`:540`) — all PASSED |
| G7 DI trust boundaries (A1) | `[x]` | 379 | `queue_worker/handlers.py:364 _should_persist_coordinates`; `verify_node` / `extract_node` gates; T-R-7 |
| **G8** `document_to_base64_images` + dispatch + alias (§4) | **`[x]` — corrected 2026-09-02; was marked open while built** | **384 (unfiled)** | `extraction_agent.py:420 _IMAGE_SUFFIXES`, `:425 def document_to_base64_images`, `:531 def pdf_to_base64_images` (alias wrapper, `:535–544`); 19 tests PASSED (`test_a_png_yields_one_base64_page_instead_of_an_empty_list`, `test_every_declared_image_suffix_is_dispatched_to_the_image_branch[…]` ×8, `test_a_jpeg_is_normalised_to_png_not_relabelled`, `test_an_unsupported_extension_returns_empty_and_logs_a_warning_naming_it`, `test_the_alias_is_a_wrapper_not_the_same_object`, …). Correction of fact recorded at `:436`: against PyMuPDF 1.28 a PNG did **not** return `[]` from the old function — MuPDF sniffs the container — so §4's motivating claim was stale; the new path does not rely on sniffing |
| G9 `Invoice.doc_type` + `Document` + migration (E10) | `[x]` **built, migration never applied** | 381 | `models.py:192–193`, `:206–207`; `alembic/versions/e4f5a6b7c8d9…:81–100`; handlers fork `:385`, `:493`, `:936` |
| G10 `docs_{tenant}` sibling collection (E10) | `[x]` **no lifecycle** | 381 | `chroma_client.py:383`, `:411`, `:428` |
| G14 `GET /documents` + detail + quota union (E10, A4) | `[x]` | 381 | `routers/documents.py:165`, `:208`; `main.py:181`; `services/billing_quota.py` |
| A4/F5 ingestion-door dedup ruling | `[x]` | **385 (unfiled)** | `routers/invoices.py:80–113`; `tests/test_ingestion.py:412`; `tests/test_documents_table.py:818`, `:981` |
| **F** fixture sourcing (§7) | **`[x]` for one sample per type — corrected 2026-09-02; was marked open while 16 fixtures existed.** Regional matrix (~30–40 files) still open → §10B R11 | — | `tests/fixtures/doc_types/` — 10/10 types, 16 PDFs (`EU-CT-01_rahmenvertrag_no_total.pdf`, `IN-DN-01_delivery_challan_no_prices.pdf`, `US-DN-01_packing_slip_no_prices.pdf`, `IN-OTH-02_eway_bill_quoting_tax_invoice.pdf`, …), `MANIFEST.md`, `_generate_fixtures.py`, 9× `ground_truth_line_items.md`; `docs/test_coverage_map.md:57` — 16/16 classified correctly by the real `classify_doc_type()`, 13 deterministic, 3 via the live Azure `gpt-5-mini` at 0.90/0.92/0.95 |
| G11 FE (rollout gate) | `[~]` | FE 378 | `StatusTable.tsx`, review page; `DropZone.tsx:50 ACCEPTED_EXTENSIONS = [".pdf"]` — **blocked** on flag exposure; no documents-list surface. See the G11 build note |
| G12 narrow tests per task | `[x]` per task; **full suite RUN 2026-09-02 and RED** | — | 409 passed across the two F27 files, and both files fully green inside the full run; but the suite is **14 failed / 2280 passed / 26 skipped** and **one failure is this feature's** — `test_documents_table.py::test_the_lifecycle_functions_never_open_a_collection_without_the_metadata`, a no-database test, so it is a real G10 lifecycle defect (→ R6), not an environment artefact. Every T-E10 test **skipped** (no Postgres) rather than passing |
| G13 tracker entries | `[~]` | — | 369/371/372/375/377/379/381 filed; **384 and 385 not filed** → §10B R0 |
| V Postgres verification (§9) | `[ ]` | — | no `test_evidence/` folder; `test_documents_table.py` never completed → §10B R4 |

### 10B-STATUS — run 2, 2026-09-03 (00:28–03:28)

**R7, R8, R9, R10 are BUILT and pushed.** The table below is the original plan;
this block is what actually happened, so a reader does not have to diff them.

| Task | Status | Commit |
|---|---|---|
| **R7** — 14-value `DOC_TYPES` (A5) | `[x]` | `f3ed94b` |
| **R8** — `doc_attributes` + `services/doc_attributes.py` (A6) | `[x]`, migration `a6b7c8d9e0f1` **applied to Postgres** | `9f87ab8` |
| **R9** — `ADVISORY` family (A7) | `[x]` | `0cda980` |
| **R10** — classifier pre-checks, Gutschrift, `rule_era` (A8) | `[x]` | `c82a751` |
| **R11** — fixture matrix + A-series tests | `[x]` — **8 new fixtures for A5's four uncovered types (24 total, 13/14 values), all 24 measured through the real classifier: 24/24 correct, 24/24 deterministic, zero model calls.** `DOC_TYPE_CONFIDENCE_THRESHOLD` recalibrated 0.6 → 0.75 on six measured confidences (0.90/0.92/0.93/0.95/0.95/0.95, nothing between 0.60 and 0.90); both numbers kept in `MANIFEST.md` per the standing ruling. Found and fixed **Gap 396** (German transliteration missing from the synonym table — three fixtures were paying for an LLM call and getting the right answer by luck). `tests/test_a_series_fixtures.py` → 55 passed | `478fb89` |
| **R5** — rollout gate | `[x]` — **(a) FOUNDER RULING given and built**: `GET /config/features` returns the process-wide `ENABLE_*` flags as a flat boolean map, tenant-agnostic, allow-listed **structurally** (name prefix + bool type) rather than by a curated list a forgetful edit could add a secret to; `tests/test_config_features.py` → 7, weighted towards what it must NOT publish. **(b) DropZone widened on BOTH guards** from one flag-derived list — FE Gap 378 closed. **(c) documents-list surface** (`510c444`) | `eb22a7e`, `510c444` |
| **R6** — `docs_` lifecycle | `[x]` — the functions exist (`chroma_client.py:639/676/704/723`), Gap 389 withdrew the "defect", and the **sweep wiring landed at Gap 385** (`ORPHAN_SWEEP_PREFIXES`, `delete_tenant_document_collection()` in the sandbox sweep). What was genuinely missing was the **soft-delete path itself** — `deleted_at` existed on the model and nothing ever set it. Now `DELETE /documents/{id}` plus **Gap 397**'s batch-rollback fix, both dropping chunks. Gap 381 item 3 → explicitly deferred as **Gap 399**, anchored by a test | see §10B R6 build note |
| **R12** — flag-removal criterion text | `[x]` — the four-part criterion is now in `config.py`'s `ENABLE_GENERIC_EXTRACTION` block, with build-gate item 3 marked satisfied and the 0.6 → 0.75 recalibration recorded there so the docstring does not keep citing a number that has changed | — |

**R5(a) is the one thing this run could not decide and did not invent.** The spec
names two options — a new `GET /config/features` endpoint, or the response-shape
adaptation `ENABLE_ASYNC_CHAT_QUEUE` uses — and picks neither, and the task row
assigns it to *architect*. R5(b)'s `DropZone` widening depends on the answer:
widening the accept list without the mechanism would let a user select a PNG
that, with the flag off, silently loses the multimodal channel — the exact
degradation §4 calls the real defect.

**New gaps filed this run:** 393 (`Invoice.doc_type` never written since G9 —
fixed), 394 (two Postgres-only tests silently skipping — filed, not fixed),
395 (Azure's own jailbreak filter blocks the content branch, and the retry copy
was wrong — fixed).

### 10B. Remaining tasks — the only open items, sequenced

Sizes are honest working-day estimates for one specialist not debugging anything else.
Order is a dependency chain, not a preference: nothing after R4 starts before R4 is
recorded, and no A5–A9 work starts before R6.

| # | Task | Owner | Size | Blocks |
|---|---|---|---|---|
| **R0** | **File Gaps 384 (G6+G8) and 385 (A4/F5) in `be_features_tracker.md`** — retroactive reconciliation entries in Gap 381's shape, collision-checked (386 is taken by Feature 26 H16; next free 387). Fix the stale "Gap 367 / next 368" text at the top of G13 and this doc's header (done for the header). | senior-dev | 0.25 d | R1 (nothing is committed with unfiled gaps) |
| **R1** | **Commit the working tree on a branch** — `feature/f27-f26-uncommitted-2026-09-02` (shared with Feature 26 Part 2; the two features share `models.py`, `chroma_client.py`, `handlers.py` and the migration chain). One commit per feature is acceptable; no squash across the two. Push, per the no-invisible-unpushed-commits rule. | senior-dev | 0.25 d | everything |
| **R2** | **Unblock the test environment**: `docker unpause` the four `invoice-*-local` containers; add `connect_timeout=5` to `psycopg2.connect()` in `tests/test_documents_table.py::pg_engine_or_skip()` and its two siblings (`test_chat_queue.py:481`, `test_auth.py:1267`) so a frozen server *skips* instead of hanging the suite; resolve the local `tests/us/` vs `tests/realworld_tenant/` basename collision (both git-ignored — rename locally or `--ignore`). Record the first full `pytest -q` result as T-OFF-2's baseline. | senior-dev | 0.25 d | R3, R4 |
| **R3** | **`alembic upgrade head` on the dev Postgres**, then `downgrade -1` / `upgrade head` for `e4f5a6b7c8d9` (and `d3e4f5a6b7c8`, Feature 26's, which sits beneath it). Read column types/nullability back from `information_schema`. Record in `test_evidence/`. This is what clears `column invoice.doc_type does not exist` for the running dev app. | senior-dev | 0.25 d | R4 |
| **R4** | **Task V — the Postgres run.** `tests/test_documents_table.py` (T-E10-1..5) against the migrated dev Postgres; T-OFF-1 with a committed golden and T-R-6 as its ON mirror (the two equality proofs A2 rests on — a golden must be committed first, `tests/fixtures/`); T-R-1/2/7 re-run with the real handler. Update `test_coverage_map.md`; raw proof in `docs/test_evidence/feature27_v_<date>/`. **Until this is recorded, "built" in this document means "written and reviewed".** | functional-tester | 1–1.5 d | flag-on in dev; every A-task |
| **R5** | **G11 remainder — the rollout gate.** (a) BE decision: how a backend `ENABLE_*` flag reaches the FE — the only options that are not hardcoding are a `GET /config/features` endpoint (new, read-only, tenant-agnostic) or the response-shape adaptation `ENABLE_ASYNC_CHAT_QUEUE` uses; decide, then (b) `DropZone.tsx` widening on both guards, (c) a documents-list surface consuming `GET /documents`. Additive section in `feature_3_ingestion.md`; FE Gap 378 closes. | architect (a), senior-dev (b, c) | 1–1.5 d | flag-on in any user-facing deployment |
| **R6** | **G10 lifecycle** (Gap 381 open item 2, A4/F3): `delete_document_chunks` / `has_document_chunks` / `get_all_document_chunks`; `docs_` added to `scripts/reembed_chroma_collections.py`'s prefix set; `scripts/sweep_sandbox_tenants.py` deletes `docs_{tenant}`; soft-delete of a `Document` removes its chunks. Plus Gap 381 open item 3 — a re-enqueue path for stuck `Document` rows — **or** an explicit deferral of it. | senior-dev | 0.5 d | A5–A9 |
| **R7** | **A5** — fourteen-value `DOC_TYPES`, `DOC_TYPE_FAMILY`, four overlays, `PACKING_LIST` fold, E5 deferred list honoured in the synonym table; migration-free (the column is `max_length=32`). T-C-6. Also **settle the two open decisions** G5 carried: `QUOTATION`'s family and the `MONEY` vs `"INVOICE"` family-key name — founder ruling, one line each. | senior-dev; founder for the two rulings | 1 d | R8–R11 |
| **R8** | **A6** — `doc_attributes` JSON column on `Invoice` and `Document` (one migration); `direction` derivation from tax IDs; `invoice_subtype`, `correction_method`, `references_original`, cumulative block, `regional_ids`, `fiscal_markers`; per-sub-type expected-absent set in the money rubric; cumulative check. T-A-1, T-R-10, T-R-11. | senior-dev | 1 d | R9, F26 B7 |
| **R9** | **A7** — `ADVISORY_FAMILY`, `_ADVISORY_RUBRIC`, `referenced_documents[]` + `deductions[]` on `GenericDocumentSchema`, family stance. T-R-8. | senior-dev | 0.5–1 d | F26 B8 |
| **R10** | **A8** — synonym table, fiscal-marker and disclaimer pre-checks, Gutschrift mandatory-ambiguous with direction in the fallback prompt, `rule_era`. T-C-5. N2 recalibration once R11's fixtures exist. | senior-dev | 1 d | R11 |
| **R11** | **A9 + the rest of F** — the §7 regional matrix (EU/US `QUOTATION`, `CREDIT_NOTE`, `DEBIT_NOTE`; India E-Invoice IRN+QR and Bill of Supply sub-cases) plus A9's new cells; confidence recorded per file; then T-C-5/6, T-R-8..11, T-A-1 written and run, and a **second Postgres run** for the A-series (R4's shape). | functional-tester (fixtures), senior-dev (tests) | 1–1.5 d | flag graduation |
| **R12** | **Flag removal criterion** — write into `config.py`'s docstring and §3/E1 the condition under which `ENABLE_GENERIC_EXTRACTION` is *removed* rather than flipped: R4 and R11's Postgres runs recorded, R5's rollout gate closed, one dev soak of ≥ 7 days with zero `doc_type_reason == "llm_error"` and zero misrouted `documents` rows, and T-R-3's equality still holding on the then-current invoice suite. At that point the flag-OFF graph is deleted, not kept. | architect (text), senior-dev (later removal) | 0.1 d text | — |

**Total remaining, BE:** ~5.5–7 working days plus 2–3 functional-tester days, in this order.
§11's original per-track table is retained below as the historical estimate; **§10B is
the live one.**

**Sequencing against Feature 26:** R0–R4 are shared with Feature 26's R0–R4 (same commit,
same containers, same migration chain, same Postgres session) and should be done once for
both. Feature 26's H16 (`MessageResponse`, Gap 386) follows immediately after the shared
R4. **A5–A9 (R7–R11) run before Feature 26's B7–B10** — the chat comparison modes consume
`doc_type`, `direction`, `correction_method` and the advisory lists, and building the
consumer before the producer would pin Feature 26 to the ten-value vocabulary.

### Build note — G1 + G2, 2026-09-02 (tracker Gap 369)

What was actually built, where it deviated from §3–§7 above, and the two decisions
deliberately left open rather than settled in code. Additive record per hard rule 4;
nothing above is rewritten.

**G1 — `config.py::ENABLE_GENERIC_EXTRACTION: bool = False`,** placed immediately after
`ENABLE_ASYNC_CHAT_QUEUE` (L61 confirmed current at write time, as is
`ENABLE_PRODUCTION_QUALITY_JUDGE` at L311 — E1's line citations still hold). The docstring
follows the house shape: what it turns on, what it costs (the deterministic pass is free;
only an ambiguous or untitled document pays for one `extraction.classify_doc_type` call;
non-invoice rows then leave the `invoice` table entirely, which is why the flip is not
free), and a numbered list of what flips it — T-OFF-1, T-R-6, N2's threshold calibration
against task F's fixtures, and T-E10-1/2/3 against real Postgres — plus the separate G11+G14
rollout gate. E2's "software-level, not per-tenant" statement is written into the docstring
in full, with the reasoning (no per-tenant flag mechanism exists, the graph carries
`tenant_id` for telemetry only, mixed-mode data is worse than either mode) and the
instruction not to add one.

**G2 — `services/document_type_classifier.py`,** standalone and called from nowhere yet.
`DOC_TYPES` (E4's ten values, lifecycle order, with a comment saying the ordering is
load-bearing), `DOC_TYPE_FAMILY`, `_DOC_TYPE_SYNONYMS`,
`classify_doc_type_deterministic(ocr_text) -> tuple[str|None, str]`,
`DocTypeClassification`, `classify_doc_type(ocr_text, ocr_result) -> dict`. The module
deliberately does **not** read `ENABLE_GENERIC_EXTRACTION` — it is a pure function of its
input so it can be tested in isolation, and G4's node is where the flag is consulted.

Four implementation decisions §4/E7 did not specify, recorded because a later reader will
otherwise assume they were arbitrary:

1. **What counts as the "title band" — the guard that does the real work.** A line is
   treated as a *title* only if it is within the first 20 non-blank lines **and** the
   synonym matches cover ≥ 60% of its non-space characters (`_TITLE_BAND_LINES`,
   `_TITLE_LINE_COVERAGE`). "DELIVERY CHALLAN" scores 1.0; "Purchase Order No: PO-2024-1188"
   scores ~0.5 and is ignored. Without this, any invoice quoting its PO number, and any
   e-way bill quoting its tax-invoice number, classifies off the *reference* rather than the
   document. Negative control run while writing the test: with `_TITLE_LINE_COVERAGE`
   temporarily 0.0, the e-way-bill sample classifies `INVOICE` with evidence "Document
   Details: Tax Invoice No INV-2026-0447 dated 01/09/2026". The guard is load-bearing.
2. **Containment resolves specificity, length does not.** "PROFORMA INVOICE" matches both
   `proforma invoice` and `invoice`; the second is the first's tail, not evidence of a
   second type, so a match wholly inside a longer one is dropped before ambiguity is
   assessed (`_drop_subsumed`). Second negative control: with that step disabled, "PROFORMA
   INVOICE" reads as ambiguous and pays for a model call it does not need. Two *disjoint*
   matches in one title line ("TAX INVOICE CUM DELIVERY NOTE" — a real Indian document) are
   genuine ambiguity and go to the fallback.
3. **Normalisation folds accents and acronym stops** before matching, so "Albarán" matches
   `albaran` and "D.D.T." matches `ddt` as printed, rather than requiring a tidied OCR
   string. Synonym entries are written in that normalised form.
4. **Return shape.** `classify_doc_type` returns
   `{doc_type, doc_type_evidence, doc_type_confidence, doc_type_method, doc_type_reason}` and
   never raises. `doc_type_method` is `deterministic` | `llm` | `fallback`;
   `doc_type_reason` is `None` unless it fell back (`ambiguous_title_band`,
   `no_title_band_match`, `empty_ocr_text`, `validation_error`, `llm_error`,
   `low_confidence …` — the last records both the score and what the model proposed, so a
   miss is reviewable). Evidence on the deterministic path is the verbatim printed line.

Deviations from the spec as written above:

- **`classify_doc_type` gained a keyword-only `tenant_id: str = ""`.** §4 gives the
  signature as `(ocr_text, ocr_result)`, but E7 requires `tracked_llm_call` on the fallback
  path and that wrapper attributes to a tenant. Carried for telemetry only, exactly as
  `ExtractionState["tenant_id"]` is — no classification decision reads it, and the answer is
  identical whether it is present, empty or absent. `ocr_result` is optional and only its
  `content` key is read, as a source for `ocr_text` when the caller passed none; nothing
  invoice-specific in that dict is consulted (§8 trap 1).
- **Empty OCR text short-circuits to `OTHER` with no model call.** E7 sends "empty or
  ambiguous" to the fallback, meaning an empty *deterministic result*; an empty *document*
  is not an ambiguity a model can resolve and a call on it would buy a hallucination.
- **`PURCHASE_ORDER` has no `po` synonym**, deliberately: two letters match too much
  ordinary text for the title-band guard to redeem.
- **Non-English synonyms outside E4's `DELIVERY_NOTE` table were not invented.** E4 gives a
  full regional table for delivery notes and names the `INVOICE` sub-cases; for the other
  eight types the map carries the canonical name plus widely-printed English variants only.
  A German invoice titled "Rechnung" therefore classifies correctly but via the LLM
  fallback, at the cost of one call. **§7 task F is what should close this** — real fixtures
  with the printed title recorded per file, not vocabulary guessed at a desk.

**Two open decisions, flagged in code and not settled unilaterally:**

- **The money family's key is `MONEY`, per E4's own family table — but A1 and A2 compare
  against the string `"INVOICE"` (`DOC_TYPE_FAMILY[doc_type] != "INVOICE"`).** Same family,
  two names, and the amendments were written after E4. `MONEY` shipped because `INVOICE` is
  already an enum *value*, and a map whose keys and values overlap is how
  `!= "INVOICE"` ends up silently true for every document. The module exports
  `MONEY_FAMILY`/`QUANTITY_FAMILY`/`COMMITMENT_FAMILY`/`OTHER_FAMILY` constants; **G3b and
  G5 must compare against those, not a bare literal**, whichever name the founder settles
  on.
- **E4's family table never assigns `QUOTATION`.** It is mapped to `COMMITMENT` here,
  provisionally: a quotation is priced and arithmetically checkable but is not a payable,
  and a partially-priced quote is normal, so `MONEY` — which requires a currency and a
  reconciling grand total — would recreate the false-discrepancy class this feature exists
  to remove. Needs founder confirmation when G5 builds `_RUBRIC_BY_DOC_TYPE`.

**Tests — `tests/test_document_type_classifier.py`, 88 passing** (`python -m pytest
tests/test_document_type_classifier.py -q` → 88 passed in 7.30s, 2026-09-02). T-C-1 is
parametrised over **every** entry in `_DOC_TYPE_SYNONYMS` (47 pairs) with `get_llm` patched
and `assert_not_called()`, plus a dedicated pass over E4's regional delivery-note table as
printed (incl. "Albarán" and "D.D.T."). T-C-2 covers ambiguity → fallback and an invented
`doc_type` raising `ValidationError` instead of being stored. T-C-3 covers the threshold in
both directions, reading `DOC_TYPE_CONFIDENCE_THRESHOLD` rather than hardcoding `0.6`, so
N2's recalibration will not require rewriting the test. T-C-4 covers a bill of lading and an
e-way bill (minimal representative text — task F has produced no fixtures yet) plus the
harder real-world variant, an e-way bill quoting its tax-invoice number. §8 trap 2 is
asserted directly: `DocTypeClassification()` constructs with no arguments and the real
`MockInvoiceLLM` returns one. **Evidence caveat:** pure-Python, no DB, no network — which §9
explicitly allows for the classifier tests. Nothing here is a hard-rule-2 verification of
the *pipeline*; that remains task V.

**Not built, deliberately:** no wiring into `agents/extraction_agent.py`,
`queue_worker/handlers.py` or `models.py` — G3/G3b/G4/G5 onward. With the module called from
nowhere and the flag `False`, this change is inert in every deployment.

### Build note — G3, 2026-09-02 (tracker Gap 371)

Continues the G1/G2 note above. Additive per hard rule 4; §3–§9 are unchanged, and the two
decisions that note left open are honoured here rather than re-litigated. **G3 is the
schema, the overlays and the prompt builders only — it is called from nowhere.** G3b's
`resolve_extraction_profile()` and `GENERIC` profile entry, G4's node and entry point, G5's
rubric and G7's handler gating are all still unbuilt. `git diff --stat` on
`agents/extraction_agent.py` is **430 insertions, 0 deletions**, so E8's "additively; the
existing class stays and keeps working" is checkable rather than asserted.

**What exists now, in `agents/extraction_agent.py`:**

- **`GenericLineItem`** — `description`, `quantity`, `unit_price`, `amount` plus E8's
  quantity-family additions `quantity_ordered`, `quantity_delivered`, `quantity_received`,
  `uom`, `batch_or_serial`. Every field `Optional`, default `None`, no validator anywhere
  that turns absence into `0`/`0.0`/`""`.
- **`GenericDocumentSchema`** — E8's spine exactly as listed, in that order.
- **`_GENERIC_FAMILY_STANCE` + `_DOC_TYPE_OVERLAYS` + `resolve_doc_type_overlay()`** — two
  keyed lookups, never an `if doc_type == …` chain, for the reason E6 gives for the rubric
  map. Nine overlays, one per non-INVOICE value in `DOC_TYPES`.
- **`build_generic_multimodal_prompt()` / `_build_generic_text_prompt()`** — modelled on
  `build_reference_multimodal_prompt` / `_build_reference_text_prompt`: framing +
  `GAP_46_VERBATIM_DIRECTIVE` + the resolved overlay + `normalize_constraints()` rules +
  (text path) the dynamic-QA block + the OCR text.

**Three decisions E8 did not specify, recorded so a later reader does not assume they were
arbitrary:**

1. **`GenericDocumentSchema.doc_type` is `Optional[str]`, not a `Literal` over `DOC_TYPES`
   — a deliberate asymmetry with `DocTypeClassification.doc_type`, which *is* a `Literal`.**
   The difference is the blast radius of a violation. In the classifier, an
   out-of-vocabulary value is the whole answer and failing it closed to `OTHER` costs
   nothing. Here it would fail the **entire extraction** — every line item, every total —
   over a disagreement about a label the deterministic classifier already decided
   upstream. This field is a cross-check on that decision, not the decision.
2. **A family-stance layer sits above the per-type overlays.** `_GENERIC_FAMILY_STANCE` is
   keyed on `DOC_TYPE_FAMILY[doc_type]` — one short paragraph per family — and
   `resolve_doc_type_overlay()` returns stance + overlay. E8 specifies only the per-type
   table; the extra layer exists so an eleventh document type added to `DOC_TYPES`
   inherits a conservative, family-correct instruction *before* anyone writes it a
   specific overlay, rather than falling through to whatever the default happens to be.
   It is also where the family constants earn their keep: the module compares against
   `MONEY_FAMILY`/`QUANTITY_FAMILY`/`COMMITMENT_FAMILY`/`OTHER_FAMILY`, never the bare
   literal `"INVOICE"` — the collision the G1/G2 note flagged for exactly this task.
3. **`party_name` / `counterparty_name` are defined by ROLE, once.** `party_name` is
   whoever ISSUED the document; `counterparty_name` is whoever it is ADDRESSED TO. Stated
   in the field descriptions and again in the base prompt, because nine types with nine
   word-pairs for the same two roles (vendor/buyer, supplier/consignee, quoting
   party/prospect) is how one field acquires a different meaning per document type — the
   thing a union spine exists to prevent.

**Deviations and judgement calls:**

- **`INVOICE` has no overlay entry, and `resolve_doc_type_overlay("INVOICE")` logs a
  WARNING** before falling back to `OTHER`. Per A2 an invoice never reaches this path, so
  arriving here means G3b has a defect; a silent conservative prompt would hide it. Unknown,
  empty and `None` types take the same conservative fallback without the warning.
- **`PROFORMA_INVOICE`, `CREDIT_NOTE` and `DEBIT_NOTE` have overlays that are currently
  unreachable.** They are `MONEY_FAMILY`, so A2 routes them to `InvoiceExtractionSchema`.
  Written anyway, with a comment saying so at each entry, so the table is complete against
  `DOC_TYPES` (the completeness test is keyed on the enum, not on the family) and so a later
  family change cannot leave a type with no instructions at all.
- **`GenericLineItem.description` is Optional** where `ReferenceDocLineItem.description` is
  required. A delivery-note row can be a bare part number and a quantity, and a required
  field on a structured-output schema invites the model to invent one.
- **The absent-is-not-zero rule is stated at prompt level as well as in the field
  descriptions.** Not a control — hard rule 3 means no figure's correctness is decided by
  prompt text — but a model told it is reading an invoice will produce a total for a
  document that prints none, and a fabricated zero reads exactly like a real one downstream.

**Hand-off contract for G3b and G4, so the shapes are not rediscovered:**

- `build_generic_multimodal_prompt(ocr_text, images, rules=None, doc_type=None)` — `doc_type`
  is a **trailing keyword with a default**, so the function stays call-compatible with
  `_DirectionProfile.build_multimodal_prompt`'s three-argument signature. G3b binds the
  classified type (e.g. `functools.partial`) when it adds the `GENERIC` entry.
- `_build_generic_text_prompt(state, rules)` — reads `state.get("doc_type")`, the key G4's
  node will write. **`ExtractionState` was NOT widened by G3**; with the key absent the
  builder produces the conservative `OTHER` overlay, and adding the key stays G4's change.

**Tests — `tests/test_generic_extraction.py`, 53 passing** (`python -m pytest
tests/test_generic_extraction.py -q` → 53 passed in 9.10s, 2026-09-02). §4 reserves this
file for the flag-ON *pipeline* tests (per-family rubric selection, quantity-family
no-false-discrepancy, contract-with-no-total, `OTHER` advisory mode) — **none of those have
a subject yet and none are claimed**; they land as G3b/G4/G5 land, in this same file. What
is covered today: T-R-5's shape at the schema level in **both** directions (a delivery note
with no prices keeps every money field `None`; a genuinely printed `0.00` survives as
`0.0` — asserted with `is None` / `== 0.0`, never truthiness, since `not None` and `not 0.0`
are both `True` and that equivalence is how Gap 283 happened); **loop-based overlay
completeness parametrised over `DOC_TYPES`**, plus set-equality in both directions so a
stale entry for a removed type fails too; a stance for every family; `DELIVERY_NOTE`'s and
`CONTRACT`'s E8-specified substance asserted by string; the fallback/warning behaviour; and
both builders' output containing the resolved stance and overlay. A2's guarantee is asserted
directly — the invoice-only field set (`compliance_metadata`, `payment_instructions`,
`deductions`, `tax_ids`, `addresses`, `round_off`, `discount_percent`, per-line
`hsn_sac_code`) is disjoint from the generic schema's, `ReferenceDocExtractionSchema`'s field
set is unchanged, and `_DIRECTION_PROFILES` still holds exactly INBOUND/OUTBOUND/REFERENCE.
**Negative control**: with the `GRN` overlay deleted and `unit_price` defaulted to `0.0`,
exactly 7 tests failed (the three `None`-coercion tests and the four `GRN`
completeness/resolution/prompt tests) while the other 46 stayed green; restored from backup
and re-run green. Regression check on everything importing this module:
`test_extraction.py`, `test_outbound_extraction.py`, `test_document_type_classifier.py`,
`test_rule_schema.py`, `test_verification_overrides.py` + the new file → **187 passed**;
`test_chat_attachments.py` + `test_sse.py` (the REFERENCE path and the
`legacy_audit_path_shim`, the two most exposed) → **37 passed**. **Evidence caveat**: pure
Python / in-memory SQLite / mocked LLM — per hard rule 2 nothing here is a Postgres-backed
verification of the pipeline, and T-OFF-1/T-R-6 are not attempted; that is task V, blocked
on §7 task F.

### Build note — G3b, 2026-09-02 (tracker Gap 372)

Continues the G3 note above. Additive per hard rule 4; §3–§9 are unchanged, and the two
decisions the G1/G2 note left open are again honoured rather than re-litigated. **G3b is
`resolve_extraction_profile()` and the `GENERIC` profile entry only — the function is
called from nowhere.** `extract_node`, `verify_node` and `run_extraction_agent` still call
`resolve_direction_profile` directly, so no document has been extracted on
`GenericDocumentSchema` in any deployment, in either flag state. G4's node and entry point,
G5's rubric, G6's fail-loud and G7's handler gating are all still unbuilt. `git diff --stat`
on `agents/extraction_agent.py` is **590 insertions, 0 deletions** against HEAD for G3+G3b
together (G3 alone was 430), so this slice is ~160 lines and the additive claim stays
checkable.

**What exists now, in `agents/extraction_agent.py`:**

- **A fourth `GENERIC` entry in `_DIRECTION_PROFILES`** — `GenericDocumentSchema`,
  `build_generic_multimodal_prompt` / `_build_generic_text_prompt`, `required_fields=()`,
  `EXTRACTED`/`EXTRACT_FAILED`, `legacy_audit_path_shim=False`, `max_tokens=8192`.
- **`resolve_extraction_profile(flow_direction, doc_type)`** — A2's rule verbatim: returns
  `resolve_direction_profile(flow_direction)` unless the flag is ON **and** the direction
  resolves to INBOUND **and** `doc_type is not None` **and**
  `DOC_TYPE_FAMILY[doc_type] != MONEY_FAMILY`, in which case it returns the `GENERIC`
  profile. Every fall-through is fail-closed to today's behaviour, for the reason E1 gives
  for the flag default: the failure mode of guessing wrong is an invoice on the generic
  spine, which drops `compliance_metadata`, `tax_ids`, `payment_instructions`, `addresses`,
  `deductions`, `round_off` and per-line `hsn_sac_code` while still returning a plausible
  `vendor_name` and `grand_total`. Nothing raises; the wrong answer just looks right.

**The two field choices A2 states but does not justify, and one it does not state:**

1. **`EXTRACTED`/`EXTRACT_FAILED` was confirmed against the real REFERENCE entry
   (L973–974) before being copied**, per E10's claim that it is "the same pair the REFERENCE
   direction profile already uses". It is, and the reason transfers exactly: a delivery note
   has no audit lifecycle — it is never approved, sent or paid. E10 gives the `documents`
   table the same two values, so the profile and the table agree by construction rather than
   through a mapping table someone has to maintain.
2. **`required_fields=()`** for the same reason INBOUND and REFERENCE have none, and one
   more specific to this feature: `missing_required_field` on a document type whose fields
   are absent *by design* is precisely the false failure Feature 27 exists to remove.
3. **`max_tokens=8192` — A2 does not specify it.** REFERENCE's figure rather than INBOUND's
   16384: the generic spine is wider than `ReferenceDocExtractionSchema` but far narrower
   than `InvoiceExtractionSchema`. Written into the code as a **starting value, not a
   measured one** — if §7 task F's fixtures show a long multi-page delivery note truncating,
   this is the number to raise.

**Three decisions A2 does not rule on, taken here rather than left implicit:**

1. **An out-of-vocabulary `doc_type`** (`"LIEFERSCHEIN"`, `""`, a typo from a caller-supplied
   override) **falls closed to the existing profile and logs a WARNING.** Explicitly *not*
   treated as "not the money family" — that reading routes every typo onto the generic
   schema. It does not raise, unlike E9's treatment of an unknown `flow_direction`: raising
   here would fail an entire extraction over a label, whereas falling back merely produces
   today's behaviour. The log is what makes the caller's defect visible.
2. **`doc_type` is normalised (`str().strip().upper()`) before the family lookup.** The
   classifier's output is `Literal`-constrained to `DOC_TYPES`, but `run_extraction_agent`'s
   caller-supplied override is free text. Without this, `" invoice "` would miss the money
   family and take the unknown-type branch — safe, but for the wrong reason, and a
   lower-cased `"delivery_note"` would silently get invoice behaviour.
3. **`doc_type` has no default parameter value.** A caller that forgets it gets a
   `TypeError` at the call site instead of silently taking the invoice path — the whole
   decision this function exists to make explicit.

**Two notes on where the rule's edges actually fall:**

- **The direction test reuses `resolve_direction_profile`'s own normalising expression**
  (`(flow_direction or "INBOUND").upper()`) so the two cannot drift. Consequence: `None` and
  `""` resolve to INBOUND and *are* eligible — E9 requires that default and
  `agents/trainer_agent.py`, `routers/trainer.py` and `benchmarks/extraction/harness.py` all
  rely on it — while a padded or typo'd value (`"  inbound "`, `"REFERNCE"`) is **not**
  eligible and gets today's behaviour, until G6 makes that same input raise.
- **`GENERIC` sits in `_DIRECTION_PROFILES` but is not a direction.** It is keyed into that
  map because `_DirectionProfile` is exactly the shape a profile needs and a second
  near-identical dataclass would be the duplication Gap 283 removed. Nothing any of the eight
  `run_extraction_agent` call sites can pass reaches it, and a test asserts that.
  **Carried note for G6:** the set of valid *directions* is INBOUND/OUTBOUND/REFERENCE and is
  no longer `_DIRECTION_PROFILES.keys()`. E9's fail-loud must validate against the three
  named directions, or `"GENERIC"` silently becomes an accepted `flow_direction` value. This
  is stated in a comment at the entry itself as well as here.

**Hand-off contract for G4, so the shapes are not rediscovered:**

- `resolve_extraction_profile(flow_direction, doc_type)` is what `extract_node` and
  `verify_node` should call instead of `resolve_direction_profile` — both arguments
  explicit, `doc_type` read from `state.get("doc_type")` once `ExtractionState` is widened
  (G4's change; G3's `_build_generic_text_prompt` already reads that key).
- `build_generic_multimodal_prompt`'s `doc_type` is still an unbound trailing keyword. Called
  through `profile.build_multimodal_prompt(ocr_text, images, rules)` as `extract_node` does
  today, it produces the conservative `OTHER` overlay — correct but not type-specific.
  Binding the classified type (e.g. `functools.partial`) at that call site is G4's, and is
  the one piece of the generic path that is present-but-not-yet-precise.
- The `GENERIC` profile's status pair is `EXTRACTED`/`EXTRACT_FAILED`, so whatever G4/G9
  writes the row must not assume `COMPLETED`/`AUDIT_REQUIRED`.

**Tests — `tests/test_generic_extraction.py`, 120 passing** (`python -m pytest
tests/test_generic_extraction.py -q` → 120 passed in 6.68s, 2026-09-02; 53 before this
change). The rule is written as an **explicit truth table**: all four conditions true →
`GENERIC` (parametrised over every non-money value in `DOC_TYPES`), then each condition
false in turn — flag off, OUTBOUND, `doc_type is None`, money family — with every
fall-through asserting **identity with the result of calling `resolve_direction_profile`
directly** rather than merely "not GENERIC", since the guarantee A2 makes is that those
paths are unchanged, not that they avoid one particular wrong answer. Also covered: OUTBOUND
and REFERENCE unchanged for every `DOC_TYPES` value plus `None`; an exhaustive flag-OFF
sweep over 7 direction spellings × 11 doc_type values (E3); the `GENERIC` entry's shape,
with its status pair asserted **equal to REFERENCE's** rather than to two string literals;
its unreachability through `resolve_direction_profile`; the normalisation and
out-of-vocabulary branches, with and without the warning; and a dedicated test over
`PROFORMA_INVOICE`/`CREDIT_NOTE`/`DEBIT_NOTE` — the three documents a literal
`!= "INVOICE"` family comparison would misroute, which is the collision the G1/G2 build note
flagged for this task. The two G3-era scope tests were updated: the profile map now holds
four entries (the three real directions still resolving to the same schemas), and the
"wired into nothing" test now reads the source of `extract_node`/`verify_node`/
`run_extraction_agent` and asserts each still calls `resolve_direction_profile` and none
calls `resolve_extraction_profile`. **Negative controls, both run:** `family == "INVOICE"`
instead of `family == MONEY_FAMILY` failed exactly 8 tests (112 green); deleting the flag
check and the direction check together failed 23 (97 green); restored from backup after each
and re-run → 120 passed. Regression sweep: `test_extraction.py`,
`test_outbound_extraction.py`, `test_document_type_classifier.py`, `test_rule_schema.py`,
`test_verification_overrides.py` + this file → **254 passed**; `test_chat_attachments.py` +
`test_sse.py` (the REFERENCE path and the `legacy_audit_path_shim`) → **37 passed**.
**Evidence caveat**: pure Python, mocked LLM, no Postgres — per hard rule 2 nothing here is
a verification of the *pipeline*, and T-OFF-1/T-R-6 (the equality proofs that would truly
close A2) are not attempted. That remains task V, blocked on §7 task F.

### Build note — G4, 2026-09-02 (tracker Gap 375)

Continues the G3b note above. Additive per hard rule 4; §3–§9 are unchanged, and the two
decisions the G1/G2 note left open are again honoured rather than re-litigated. **G4 is the
node, the conditional entry point, and — stated openly because it is scoped elsewhere — one
narrow slice of G6: `extract_node` and `verify_node` now resolve through
`resolve_extraction_profile()`.** That slice had to move here. G3b's function was dead code
until something called it with a real `doc_type`, and `classify_doc_type_node` is what makes
a `doc_type` exist; shipping the node without the wiring would have left the classified type
inert and the task unverifiable end to end. **The rest of G6 is not built** — E9's
`UnknownFlowDirectionError` fail-loud is untouched — and neither is G5's rubric, G7's DI
trust boundaries, G8's image dispatch, G9's persistence, G10's collection or G14's endpoint.
`git diff --numstat` on `agents/extraction_agent.py` is **822 insertions / 24 deletions**
against HEAD for G3+G3b+G4 together (590/0 after G3b), and **all 24 deletions are moves**:
the module-level graph-assembly block lifted verbatim into `_build_extraction_graph()`, the
two `resolve_direction_profile` call lines, the multimodal-builder call line and the two
`graph.stream`/`graph.invoke` lines.

**What exists now, in `agents/extraction_agent.py`:**

- **`classify_doc_type_node(state) -> Dict[str, Any]`** — E7's node, in the house shape
  (`classify_node`/`dynamic_qa_node`): reads state, returns a partial update. Calls
  `services.document_type_classifier.classify_doc_type(ocr_text, ocr_result, tenant_id=…)`
  and writes `doc_type` / `doc_type_evidence` / `doc_type_confidence`.
- **`_build_extraction_graph(*, include_doc_type_classifier: bool)`** — the old module-level
  assembly block, now a function with one conditional. `False` produces exactly the
  pre-Feature-27 graph; `True` adds the node, moves the entry point onto it and adds the
  single `classify_doc_type -> classify` edge. Nothing else about the graph changes.
- **`_compiled_extraction_graph(include_doc_type_classifier)`** (`@lru_cache(maxsize=2)`) and
  **`resolve_extraction_graph()`**, which reads the flag once per run and returns the graph
  whose *structure* matches it. `graph` is still a module-level name and is still the
  flag-OFF object — returned by identity, not rebuilt.
- **`ExtractionState`** widened by three keys, and **`_NODE_LOG_MESSAGES`** by one
  (`"Identifying document type..."`, Gap 2's FE terminal feed; without it the user would see
  the raw `Running classify_doc_type...` fallback).

**Five decisions E7 does not specify, recorded so a later reader does not assume they were
arbitrary:**

1. **The conditional is at graph-BUILD time, and that is the whole of E3.** A runtime branch
   inside the node would satisfy "flag off changes nothing" only behaviourally; E3's claim is
   structural, and the test that proves it asserts on the compiled graph's node set. With the
   flag off the node is **absent**, not inert — there is no execution path through it to
   reason about. The cache exists because a single import-time compile could not do this: its
   structure would be fixed by whichever module imported this one first, and no test could
   ever flip the flag and see the graph change. Two compiled graphs, each with a fixed node
   set, is the shape that makes both true at once.
2. **The node emits no telemetry of its own.** E7 asks for exactly one
   `tracked_llm_call("extraction.classify_doc_type", ...)` on the fallback path, and G2
   already put it inside `_classify_with_llm` — the only place that knows a call is actually
   being made. A second wrapper here would emit an event for the *deterministic* path, which
   E7 requires to cost nothing and show as nothing, and would double-count the fallback; the
   event count would stop being a direct measure of how often the printed title band was not
   enough. Which path ran comes from the classifier's own `doc_type_method`
   (`deterministic` | `llm` | `fallback`) for the log line, not from re-deriving it here, and
   `doc_type_reason` is logged alongside so a fallback is reviewable rather than merely wrong.
3. **A classifier failure degrades to "unclassified", never to a failed extraction.**
   `classify_doc_type` documents itself as never raising, so the `except` is for something
   structural — but if reached, `doc_type=None` sends `resolve_extraction_profile` straight
   back to today's direction profile, the fail-closed answer E1 gives for the flag itself.
   Same shape as `dynamic_qa_node`'s except, for the same reason: a pre-analysis step must not
   be able to take down the extraction it precedes.
4. **Three state keys, not five.** `doc_type` and `doc_type_evidence` are E7's;
   `doc_type_confidence` rides along because it is a column on E10's `documents` table and
   because N2's threshold calibration has nothing to calibrate against without it.
   `doc_type_method` / `doc_type_reason` are logged and **not** carried — they have no
   persistence target in E10's column list. `run_extraction_agent`'s `initial_state` seeds all
   three as `None`, so a flag-OFF run carries them unset for its whole life.
5. **`verify_node` moved with `extract_node`, not after it.** The status vocabulary a document
   is verified against must be the vocabulary of the schema it was extracted on, or a delivery
   note extracted on `GenericDocumentSchema` comes back `COMPLETED` — an inbound-invoice status
   for a document with no audit lifecycle. This is profile resolution only: **the money checks
   still run for every type**, which is G5's to gate, and the DI-derived Critic step and the
   Gap 68 backfill are still ungated, which is G7's.

**Deviations and judgement calls:**

- **`run_extraction_agent` keeps `resolve_direction_profile`, deliberately.** Its one use of a
  profile is the pre-flight token-guardrail early return, which happens before OCR text
  reaches the graph and therefore before any `doc_type` exists. §4's caller-supplied `doc_type`
  override (and returning `doc_type`/`doc_type_evidence` in the result dict) is **not built**:
  it belongs with G9, since what needs the classified type back out of the graph is the
  persistence step, and adding keys to the returned dict now would change the flag-OFF return
  shape for no consumer.
- **G3's hand-off closed: the classified type is bound into the generic multimodal prompt**
  with `functools.partial`, guarded on `profile is _DIRECTION_PROFILES["GENERIC"]` rather than
  by widening `_DirectionProfile`. `GENERIC` is the only profile whose prompt depends on the
  type, and the text builder already reads the same key off state; every other profile is
  called with the same three positional arguments as before, asserted by a test.
- **`classify_doc_type` is imported at module level**, beside the family constants this module
  already imports from that file, rather than locally inside the node the way `classify_node`
  imports `classify_invoice_complexity`. A local import would imply a cycle that does not
  exist. The name is still resolved on this module at call time, so tests patch
  `ea.classify_doc_type`.

**Hand-off contract for G5, G6 and G7, so the shapes are not rediscovered:**

- `state["doc_type"]` is populated by the time `extract_node` and `verify_node` run whenever
  the flag is on; it is `None` in every other case, including a caller that builds a state
  dict by hand. G5's `_RUBRIC_BY_DOC_TYPE` lookup should read the same key and must handle
  `None` (advisory/unchanged), for the same fail-closed reason `resolve_extraction_profile`
  does.
- G6's remaining half is E9's fail-loud only, and must validate against the three **named**
  directions rather than `_DIRECTION_PROFILES.keys()` (G3b's carried note) — `"GENERIC"` is a
  profile key, not a direction.
- G7's two rubric fields do not exist yet on `_DirectionProfile`, and a test asserts their
  absence on `__dataclass_fields__` — that test is the marker to update, not to delete.

**Tests — `tests/test_generic_extraction.py`, 144 passing** (`python -m pytest
tests/test_generic_extraction.py -q` → 144 passed in 6.51s, 2026-09-02; 120 before this
change). **Flag OFF is asserted on graph structure**, which is E3's actual standard: the node
set is exactly `{classify, dynamic_qa, extract, verify}`, `"classify_doc_type" not in
graph.nodes`, the `__start__` edge still points at `classify`, and `resolve_extraction_graph()`
returns the module-level `graph` **by identity**. Plus the end-to-end half on the founder's own
symptom document: a delivery challan through `run_extraction_agent` with the flag off is
extracted on `InvoiceExtractionSchema`, lands on `COMPLETED`, and the classifier is asserted
never called on a **call count** — not on "doc_type came back None", which a node that ran and
returned nothing would also satisfy. **Flag ON**: the node set differs by exactly
`{classify_doc_type}` and the edge set by exactly the two new edges, with
`("__start__", "classify")` the only edge that goes away; the execution trace of a real run is
`classify_doc_type → classify → dynamic_qa → extract → verify` (§2A/A1's sequence, asserted as
an order rather than an edge list); an unambiguous "DELIVERY CHALLAN" costs **no model call**
(T-C-1's shape at pipeline level) while "TAX INVOICE CUM DELIVERY NOTE" does fall back and
fires exactly one `tracked_llm_call` keyed `extraction.classify_doc_type`; the classified type
reaches both nodes, so that challan is extracted on `GenericDocumentSchema` and verified to
`EXTRACTED`; and an invoice under the same flag still runs on `InvoiceExtractionSchema` to
`COMPLETED` (A2 at pipeline level — the shape T-R-6 will prove properly once §7 task F's
fixtures exist). These are the first tests in this repo that drive `run_extraction_agent` end
to end, which is the point: execution order and profile selection are properties of a run.
**Negative controls, both run:** the entry-point conditional removed so the node is always in
the graph — the "inert when off" implementation E3 rules out — failed exactly 4 tests (140
green); reverting both nodes to `resolve_direction_profile` failed exactly 5 (139 green);
restored from backup after each and re-run → 144 passed. Regression sweep: the five suites
importing this module + this file → **278 passed**; `test_chat_attachments.py`,
`test_sse.py`, `test_trainer.py`, `test_audit.py` (the REFERENCE path, the
`legacy_audit_path_shim`, and the trainer/audit re-extraction entry points, the callers most
exposed to a change in how the graph is compiled) → **118 passed**. **Evidence caveat**: pure
Python, fake LLM, in-memory SQLite, no Postgres and no real Document Intelligence call — per
hard rule 2 nothing here is a verification of the *pipeline*, and T-OFF-1/T-R-6 are not
attempted. That remains task V, blocked on §7 task F.

**Rollout status unchanged: the flag must stay off.** With it on, a classified non-invoice is
now genuinely extracted on the generic schema — but `verify_node` still runs the full money
rubric against it (G5) and the DI-derived Critic still fires `low_confidence_field` alerts for
invoice fields the document does not have (G7), which is the founder's original symptom by its
second route. Nothing persists `doc_type` yet (G9), and §2A/N1's G11+G14 rollout gate is
additionally still open.


### Build note — G5, 2026-09-02 (tracker Gap 377)

Continues the G4 note above. Additive per hard rule 4; §3–§9 are unchanged, and the two
decisions the G1/G2 note left open are again honoured rather than re-litigated (one of them
— `QUOTATION`'s family — was G5's to raise, and it is raised below rather than settled).
**G5 is the arithmetic rubric and the review-status decision only.** The DI-derived trust
boundaries are still ungated (G7), E9's fail-loud is still unbuilt (the rest of G6), and
nothing persists `doc_type` (G9). `git diff --numstat` on `agents/extraction_agent.py` is
**1157 insertions / 41 deletions** against HEAD for G3+G3b+G4+G5 together (822/24 after G4),
so this slice is ~335 added lines and **17 deletions, every one of them a re-indent or a
comment replacement**: the two existing check-call blocks moved under an `if`, the status
line becoming an `if/else`, and G4's "the rubric is not built yet" comment replaced by what
is now true.

**This is the task that fixes the founder's originally reported bug.** Before it,
`verify_node` ran `verify_line_items_math` and `verify_totals_math` for every document type
unconditionally — §1's third compounding choice — so a delivery challan, which prints
quantities and no prices *by design*, was graded against a money rubric it could not
satisfy. It was never broken; it was being graded against the wrong rubric.

**What exists now, in `agents/extraction_agent.py`:**

- **`_VerificationRubric`** — E6's fields (`run_line_item_math`, `run_totals_math`,
  `require_currency`, `price_fields_optional`, `advisory_only`, the status pair) plus A1's
  two (`run_field_confidence`, `run_di_tax_backfill`).
- **Four family rubrics + `_RUBRIC_BY_FAMILY` + `_RUBRIC_BY_DOC_TYPE`.** The per-type map
  is a **comprehension over `DOC_TYPES`**, not ten hand-written entries: a new document
  type is complete the moment it has a family, and a family with no rubric is a `KeyError`
  at import rather than a silently wrong rubric at runtime. E6's "one lookup, so adding an
  eleventh type later is one map entry and not a new branch" is structural here, not a
  convention.
- **`resolve_verification_rubric(flow_direction, doc_type)`** — returns `None`, meaning *do
  not consult the rubric; run today's checks exactly as they have always run*, unless the
  flag is ON **and** the direction resolves to INBOUND **and** `doc_type` is a known value
  in `DOC_TYPES`.
- **`_prices_present(data)`** — E4's "unless prices are actually present" test, every
  comparison `is not None` and never truthiness.
- **`verify_node`** gates checks 1 and 2 on the resolved rubric and applies `advisory_only`
  to the status. The check functions in `utils/verification_tools.py` are **untouched**, as
  E6 requires: they are correct, and what was wrong was calling them unconditionally.

**Six decisions E6 does not settle, taken here rather than left implicit:**

1. **The resolver has three conditions, not `resolve_extraction_profile`'s four, and the
   missing one is deliberate.** A2 excludes the money family from the *schema* change; it
   is **not** excluded from the rubric, because `_MONEY_RUBRIC` *is* today's behaviour
   written down — every boolean `True`, nothing optional, nothing advisory — so consulting
   it for an INVOICE resolves to the same two calls with the same arguments. Excluding the
   money family instead would have produced identical behaviour by a second code path, and
   two paths that must agree are how they stop agreeing. T-R-3 asserts the equality on the
   call arguments, not just on the output.
2. **OUTBOUND and REFERENCE never reach the map.** A2, verbatim: `doc_type` "is still
   classified and recorded for both — it simply never changes their schema **or rubric**".
   A classified `DELIVERY_NOTE` on the outbound path must not switch off arithmetic that
   `routers/outbound_audit.py` and `queue_worker/outbound_handlers.py` are written against.
   This is why the resolver takes `flow_direction` at all.
3. **The rubric's status pair is carried but is not what `verify_node` emits.** E6 predates
   A2, which put the status vocabulary on `_DirectionProfile`, and G4 wired `verify_node` to
   emit the resolved *profile's* pair. Two sources for one decision is how they drift, and
   the rubric is the weaker of the two: it is keyed on `doc_type` alone, so letting it win
   would hand an OUTBOUND invoice the inbound `COMPLETED`/`AUDIT_REQUIRED` pair instead of
   its own `VERIFIED`/`NEEDS_REVIEW`. The field is kept because E6 asks for it and because
   it makes each family's intent readable in one table, and a test pins it to the profile
   resolved on the one path where the rubric is actually consulted.
4. **`require_currency` is declarative today, and said so rather than quietly implemented.**
   There is no currency check anywhere in `verify_node` or `utils/verification_tools.py` to
   gate. Adding one under this flag would change the alert set an INVOICE produces and break
   T-R-3 — the single test proving this task regresses nothing — so the field records the
   family's intent and whoever adds the check wires it here.
5. **The commitment family needs no code beyond the table.** E4's "missing-total is not a
   failure" is already true: `verify_totals_math` returns `None` when `grand_total` or
   `subtotal` is `None`, `verify_line_items_math` returns `None` when `subtotal` is `None`,
   and the `GENERIC` profile has `required_fields=()` so no `missing_required_field` is
   raised either. Both math flags therefore stay **True** for `PURCHASE_ORDER`/`CONTRACT`/
   `QUOTATION` — that is E4's "arithmetic checks run where totals are printed" — and T-R-2
   asserts the no-grand-total case end to end rather than assuming it.
6. **`advisory_only` does not suppress `extraction_failed`.** That early return is the
   pipeline reporting *its own* failure, not the rubric judging the document; suppressing it
   would mark a row with no extracted data at all as successfully extracted. `OTHER` with a
   failed extraction still lands on `EXTRACT_FAILED`, and a test says so.

**E4's quantity escalation, implemented literally.** E4: "no total-arithmetic check
attempted unless prices are actually present, **in which case the money checks run
additionally, not instead**". So `DELIVERY_NOTE`/`GRN` carry
`run_line_item_math=False, run_totals_math=False, price_fields_optional=True`, and
`verify_node` turns both back on when `_prices_present(extracted_data)` — any of
`subtotal`/`grand_total`/`tax_amount`/`discount_amount`, or any line's `unit_price`/
`amount`, being `is not None`. A packing slip that *does* print values is still arithmetic
and a wrong one is still caught.

**The open decision G5 was asked to close is not closed.** `QUOTATION` → `COMMITMENT`
remains **provisional** (Gap 369's build note, naming note 2). G5 reads `DOC_TYPE_FAMILY`
rather than re-deriving the mapping, and a test asserts that it does, so the founder's
ruling is a one-line change in `services/document_type_classifier.py` that automatically
moves the rubric with it. Recorded here as still-open rather than silently ratified by
shipping. The `MONEY` vs `"INVOICE"` naming collision is honoured the same way G3b honoured
it: every comparison in this slice is against the imported family constants.

**Tests — `tests/test_generic_extraction.py`, 229 passing** (`python -m pytest
tests/test_generic_extraction.py -q` → 229 passed in 8.12s, 2026-09-02; 144 before this
change). §9's four rubric tests are all present and all written so they fail for exactly one
reason:

- **T-R-1** — a `DELIVERY_NOTE` (parametrised over the whole quantity family) with
  quantities and no prices: **zero** alerts, `EXTRACTED`, and — the load-bearing assertion —
  both check functions `assert_not_called`. An alerts-only assertion would pass against
  completely ungated code, because both checks already return `None` when their inputs are
  absent; what is proved here is that they were never *attempted*. Its negative half is a
  test too: the same document with the flag **off** still calls both and still lands on
  `COMPLETED`, so the difference the flag makes is visible rather than asserted.
- **T-R-2** — a `CONTRACT` rate card with no grand total: no missing-total alert, no
  alerts at all, `EXTRACTED`, **and `verify_totals_math` was still called** — the commitment
  family does not switch arithmetic off. Paired with a `PURCHASE_ORDER` that prints
  inconsistent totals and does raise both alerts, which is the test that fails if the
  commitment rubric is ever written as a copy of the quantity one.
- **T-R-3** — the regression proof. The same inconsistent invoice through `verify_node`
  with the flag off and then on: equal alerts, equal status (`AUDIT_REQUIRED`), equal
  feedback, and **equal `call_args_list` for both checks**. Two differently-argued calls
  that happen to agree would pass an output-only comparison. The flag being genuinely on for
  the second run is asserted, not assumed, so the equality cannot be vacuous.
- **T-R-4** — `OTHER` produces both arithmetic alerts, still surfaces them in `feedback`,
  and lands on the *passing* status; the control is the identical document as a
  `PURCHASE_ORDER`, which produces the identical alert list and lands on `EXTRACT_FAILED`.
  Without that control, a bug that dropped `OTHER`'s alerts entirely would pass T-R-4.
- **Flag OFF never consults the map** — asserted by substituting a `dict` subclass that
  records every `get`/`__getitem__` and checking `lookups == []`, both for the resolver
  directly and through `verify_node`. This is the assertion the dispatch asked for and it
  cannot be made any other way: an invoice produces identical alerts either way, so an
  output comparison would pass against a fully-gated implementation and prove nothing about
  the flag. The same recorder shows exactly one lookup (`["DELIVERY_NOTE"]`) with the flag
  on, and zero for `doc_type=None`, OUTBOUND and REFERENCE.

Also covered: the map's completeness against `DOC_TYPES` and its by-identity derivation from
`_RUBRIC_BY_FAMILY[DOC_TYPE_FAMILY[...]]` (a hand-written per-type entry holding equal values
would still fail — that is E6's rejected `if doc_type == …` chain, spelled as a table); each
family's booleans against E4's table; A1's "money family only" for the two G7 fields, over
every type; the status-pair/profile agreement; normalisation and the out-of-vocabulary
fail-closed warning; and `_prices_present`'s zero-is-not-absent behaviour in both directions.

**Fixtures**: §7 task F has produced `tests/fixtures/doc_types/` with **two** covered types
(`delivery_note`, `proforma_invoice`) and seven still marked NOT YET SOURCED in its
`MANIFEST.md`. Those are PDFs for the *classifier*, and none of them is a `CONTRACT`, a
`PURCHASE_ORDER` or an `OTHER`, so the rubric tests use minimal representative state dicts —
the same shape the G3/G3b/G4 tests use, and the shape §9 requires anyway, since T-R-1..4 are
assertions about `verify_node`'s inputs rather than about OCR.

**Negative controls, three, all run.** (a) The gating removed so both checks run
unconditionally — the state the file was in before this task — failed **exactly 3** tests
(the scope marker and both T-R-1 parametrisations), 226 green. (b) The `advisory_only` branch
removed — failed **exactly 3** (the scope marker, T-R-4 and its control), 226 green. (c)
`QUANTITY_FAMILY` mapped to `_MONEY_RUBRIC`, i.e. the family table wrong rather than the
wiring — failed **exactly 8** across the table tests and both T-R-1 cases, 221 green.
`agents/extraction_agent.py` was restored from backup after each and re-run → 229 passed.

**Regression sweep**: `test_generic_extraction.py`, `test_extraction.py`,
`test_outbound_extraction.py`, `test_document_type_classifier.py`, `test_rule_schema.py`,
`test_verification_overrides.py` → **363 passed**; `test_chat_attachments.py`,
`test_sse.py`, `test_trainer.py`, `test_audit.py` → **118 passed**; and the remaining four
suites that reach the graph or `verify_node` (`test_direction_aware_chat.py`,
`test_extraction_benchmark.py`, `test_outbound_ingestion.py`, `test_trace_scrubbing.py`) →
**160 passed, 1 skipped** (pre-existing skip). **Evidence caveat**: pure Python, fake LLM,
in-memory SQLite where a DB is touched at all, no Postgres and no real Document Intelligence
call. Per hard rule 2 nothing here is a Postgres-backed verification of the pipeline;
T-OFF-1 and T-R-6 remain task V, blocked on §7 task F.

**Rollout status: the flag can now be turned on without the arithmetic half of the founder's
bug — but it must still stay off.** `verify_node` no longer runs the money rubric against a
delivery note, which is what G4's note said was blocking. What remains: the DI-derived Critic
still fires `low_confidence_field` alerts for invoice fields a non-invoice document does not
have, and that alert type is non-retryable and forces a review status (G7 — a test asserts
this is still true, deliberately, as the marker to flip); the Gap 68 tax backfill can still
write a tax figure onto a document that prints none (G7); nothing persists `doc_type` (G9);
and §2A/N1's G11+G14 rollout gate is still open.

### Build note — G7, 2026-09-02 (tracker Gap 379)

Continues the G5 note above. Additive per hard rule 4; §3–§9 are unchanged, and the two
decisions the G1/G2 note left open are again honoured rather than re-litigated (`QUOTATION`'s
family is still provisional and still read from `DOC_TYPE_FAMILY`; every family comparison in
this slice is against the imported constants, never the bare literal `"INVOICE"`). **G7 is
the three trust boundaries on `prebuilt-invoice`'s invoice-specific output, and nothing
else.** `_run_ocr` is untouched (A1 — `model_id="prebuilt-invoice"` stays, unconditionally,
for every document in both flag states), `utils/verification_tools.py` is untouched, the Gap
68 backfill's own logic is untouched, and no persistence *routing* was written (G9/E10 —
`models.py`, `services/billing_quota.py`, `routers/invoices.py` and the `documents` table are
all unchanged). E9's fail-loud (rest of G6), G8, G10 and G14 remain unbuilt.

**This is the other half of the founder's original bug.** G5 fixed the arithmetic; what
survived it was §8 trap 1 — `prebuilt-invoice` does not decline to analyse a delivery note,
it **force-fits `VendorName` / `InvoiceId` / `InvoiceTotal` onto one at low confidence**, so
the Gap 3 Critic emitted `low_confidence_field` alerts naming fields the document does not
have. That alert type is in `NON_RETRYABLE_ALERT_TYPES` and any alert sets the review status,
so a perfectly correct delivery challan landed in review carrying an alert **no retry could
ever clear**. Absence of data was never the hazard; presence of confident wrong data was.

**What exists now:**

- **`verify_node`** — the `verify_field_confidence` block is inside
  `if rubric is None or rubric.run_field_confidence:`, using the rubric G5 already resolves
  in that function. Feature 18's `threshold_override` is still resolved *outside* the `if`
  and still passed in: the check moved under a condition, it did not lose its parameter.
- **`extract_node`** — resolved no rubric at all before this; it now calls G5's
  `resolve_verification_rubric(flow_direction, doc_type)` (imported and called, not a
  re-derived family lookup) and gates the Gap 68 `tax_details_sum` backfill on
  `run_di_tax_backfill`. Gap 68's own invariant is untouched and re-asserted by a test: the
  backfill still fires **only** where `tax_amount is None`. The gate narrows *when* it may
  fire, never *what* it may overwrite.
- **`queue_worker/handlers.py::_should_persist_coordinates(doc_type)`** — `True` for `None`,
  `True` for an out-of-vocabulary value (with a WARNING), `True` for the money family,
  `False` otherwise, so a non-invoice row persists `[]`. `DOC_TYPE_FAMILY`/`MONEY_FAMILY` are
  imported at module level rather than inside the function: this module already imports
  `agents.extraction_agent`, which imports the classifier, so a local import would imply a
  cycle that does not exist.
- **`run_extraction_agent`** returns a fourth key, `doc_type`.

**The one deviation from the plan, stated plainly.** G4's note deferred returning `doc_type`
from `run_extraction_agent` to G9, reasoning that persistence is what needs the type back out
of the graph. Gate 3 **is** a persistence decision, and the handler cannot know the family
unless the graph hands the type back — so the key ships here. Bounded deliberately:
**only `doc_type`**, not `doc_type_evidence` / `doc_type_confidence`, which still have no
consumer until G9; the value is `None` in every flag-OFF run (the classifier node is not in
the compiled graph at all); the three existing keys are untouched; and the pre-flight
token-guardrail early return still returns three keys, which is why every consumer reads it
with `.get()` — as do the several existing tests that patch `run_extraction_agent` with a
pre-G7 dict. `agents/outbound_extraction_agent.py` got a **docstring-only** change, because
it forwards this dict and claimed "the same `{status, alerts, extracted_data}` shape".

**Three decisions A1 does not spell out:**

1. **`field_confidence` and `source_document_json` are deliberately NOT gated**, and two
   tests assert they are still written for a non-invoice row. A1 gates exactly one of the
   three persisted DI outputs; the other two are diagnostic, and `source_document_json` is
   already excluded from every LLM-visible projection (`agents/query_tools.py`,
   `agents/sage_prompts.py`). Over-narrowing here would be its own defect.
2. **Every gate's `None` branch is a fall-through to today's behaviour, not to "off".** Flag
   off, a non-INBOUND direction, an unclassified document and an out-of-vocabulary type all
   resolve to the unconditional pre-G7 code path — the same fail-closed default
   `resolve_extraction_profile` and `resolve_verification_rubric` take, for E1's reason.
3. **The money family goes *through* the gate rather than around it.** `run_field_confidence`
   / `run_di_tax_backfill` are `True` there, so an invoice resolves to the same call with the
   same arguments rather than to a second code path that must agree with the first. T-R-3
   asserts that on `call_args_list`, re-confirmed with this change layered on G5's.

**Tests — `tests/test_generic_extraction.py`, 273 passing** (`python -m pytest
tests/test_generic_extraction.py -q` → 273 passed in 20.52s, 2026-09-02; 229 before this
change). **T-R-7** is present and is parametrised over **every non-money type** rather than
`DELIVERY_NOTE` alone — a purchase order and a contract get the same force-fitted invoice
fields from the same model, and `OTHER` would otherwise pass on `advisory_only` while still
recording nonsense alerts on the row. Hand the Critic exactly what DI returns for a challan
(`{"VendorName": 0.31, "InvoiceTotal": 0.22}`) and it produces zero alerts, `EXTRACTED`,
empty feedback, with `assert_not_called` as the load-bearing assertion: an alerts-only check
would be satisfied by a gate that ran the check and threw the result away. Its negative half
is a test too (flag off → two alerts, `AUDIT_REQUIRED`, check called). Also covered: the
money family still consulting DI confidence, over all four types; `route_after_verification`
returning END for a `low_confidence_field` alert set, so A1's "no retry can clear it"
reasoning is checked rather than repeated; the tenant's confidence-threshold override still
reaching the gated call; the tax backfill absent for every non-money type and present for
every money type, for `doc_type=None` and for OUTBOUND; the backfill still never overriding
a transcribed value; `_should_persist_coordinates` over all ten types plus `None`, with
normalisation and the unknown-type warning; and **three tests driving the real
`handle_process_invoice` persistence block** — an INVOICE's coordinates persisted exactly as
today, a `DELIVERY_NOTE` never reaching the gate (see the G9 collision below), and a pre-G7
three-key result dict persisting coordinates unchanged.

**A parallel dispatch landed G9/E10 into these same two files while this task was being
verified. Two tests were rewritten as a result, and the consequence for gate 3 is recorded
rather than hidden.** G7's suite was green at 273, then red at 271/2 an hour later, for two
reasons — both correct behaviour changes, neither a defect: (1) `run_extraction_agent` now
also returns `doc_type_evidence` / `doc_type_confidence`, so an exact key-set assertion was
relaxed to a subset check (G7 does not own those keys); (2) **a non-money document no longer
has an `Invoice` row at all** — `_routes_to_documents_table()` writes the `documents` row and
deletes the placeholder, returning *before* the coordinates line — so
`test_a_delivery_notes_persisted_coordinates_are_empty` became
`test_a_delivery_note_never_reaches_the_coordinates_gate_after_g9`, asserting that the gate
still answers `False` for that type and that no `Invoice` row survives.

**The honest consequence: after G9, `_should_persist_coordinates()` always resolves `True`
wherever it is still reached**, because G9 returns early for exactly the types this gate
returns `False` for. It is kept, and a comment at the call site says why: the two questions
fail closed towards different things (a mislabelled box vs. a deleted row), so they are
deliberately not written as each other's negation, and A1's hazard is now prevented one layer
up by the row not existing rather than by the `[]`. Defence in depth, stated as such.

**Two marker tests were flipped, not deleted**, exactly as G5 asked. `test_g5s_honest_scope_…`
became `test_g7s_honest_scope_…` and now asserts both `rubric.*` reads are present, and
`test_the_di_critic_still_fires_on_a_delivery_note_which_is_g7s_job_not_g5s` became
T-R-7's `== []` assertion with its old assertions preserved verbatim as the flag-OFF twin.

**Negative controls, three, all run.** (a) Critic gate removed (`if True:`) — failed
**exactly 8** (the scope marker, all six T-R-7 parametrisations, the non-retryable test), 265
green. (b) Tax-backfill gate removed — failed **exactly 6**, 267 green. (c)
`_should_persist_coordinates` comparing against the literal `"INVOICE"` instead of
`MONEY_FAMILY` — failed **exactly 7** (all four money types, the normalisation/unknown test,
the family-constant test, the real-handler INVOICE regression), 266 green. Both source files
restored from backup after each and re-run → 273 passed.

**Regression sweep** (final run, with G9 present in the tree): the five suites importing this
module + this file → **407 passed**; `test_sse.py`, `test_chat_attachments.py`,
`test_trainer.py`, `test_audit.py` → **118 passed**; `test_direction_aware_chat.py`,
`test_extraction_benchmark.py`, `test_outbound_ingestion.py`, `test_trace_scrubbing.py`,
`test_source_document_json.py`, `test_webhooks.py` → **189 passed, 1 skipped** (the first
four are G5's set at 160+1, unchanged). Because `queue_worker/handlers.py` changed, the remaining suites
referencing it were run too → **168 passed, 1 failed**, the failure being
`test_connectors.py::test_connectors_status_google_drive_only_on_postgres`, which fails
identically alone; that file and `routers/connectors.py` are unmodified in this working tree
and nothing here touches the connectors/auth path, but a HEAD re-run to *prove* pre-existence
was not performed, because the two files this task edited also carry other dispatches'
uncommitted Feature 27 work. **Evidence caveat**: pure Python, fake LLM, in-memory SQLite for
the three handler tests, no Postgres and no real Document Intelligence call — per hard rule 2
nothing here is a Postgres-backed verification of the pipeline, and T-OFF-1/T-R-6 remain task
V, blocked on §7 task F.

**Rollout status — both halves of the founder's original bug are now fixed. The flag can be
turned on for TESTING; it must not be turned on in a user-facing deployment.** With
`ENABLE_GENERIC_EXTRACTION=True` a delivery challan is classified, extracted on the generic
schema, verified against the quantity rubric, raises no arithmetic alerts, raises **no
`low_confidence_field` alerts**, acquires no tax figure it never printed, and stores no
mislabelled overlay. Nothing on the extraction/verification path is known-wrong any more.
What is still open is coherence as a product, not correctness: **G9** — nothing persists
`doc_type` and the `documents` table does not exist, so a classified non-invoice is still
written into `invoice` as an ordinary row carrying an `EXTRACTED` status the ledger does not
know; and §2A/N1's **G11+G14** gate (no `GET /documents`, no documents-list surface). Also
unbuilt: E9's fail-loud (rest of G6), `document_to_base64_images` (G8), the sibling Chroma
collection (G10).

---

### Build note — G9/G10/G14, 2026-09-02 (tracker Gap 381)

Additive record per hard rule 4; nothing in §3–§10 is rewritten. This is **E10 built**, and
it is written up after the fact: the build dispatch shipped the code without filing its gap
entry, so Gap 381 and this note are a reconciliation pass over work already in the tree.
Said plainly rather than presented as a normal same-change filing.

**What exists now.** Two new source files — `routers/documents.py` and
`alembic/versions/e4f5a6b7c8d9_add_doc_type_and_documents_table.py` — plus `models.py`,
`chroma_client.py`, `queue_worker/handlers.py`, `services/billing_quota.py`, one router
registration in `main.py`, and a new `tests/test_documents_table.py`.

- **G9, the schema.** `Invoice.doc_type` / `Invoice.doc_type_evidence`, both nullable with a
  `None` default and no backfill — NULL means *never classified*, never *not an invoice*, and
  a flag-OFF run writes NULL exactly as it writes nothing today. `Document`
  (`__tablename__ = "documents"`) carries E8's spine plus `Invoice`'s operational columns
  (Gap 192's `deleted_at`, FE Gap 81/84's re-enqueue bookkeeping, Gap 125's
  `submitted_by_email`, Gap 178's `source_document_json`) and two composite indexes led by
  `tenant_id` (FE Gap 29's pattern). Every money column is nullable and never coerced to zero;
  `status` is the `EXTRACTED`/`EXTRACT_FAILED` pair the GENERIC profile emits, not the invoice
  vocabulary, because a delivery note has no audit lifecycle. **No `coordinates` column
  exists** — A1's mislabelled-overlay hazard removed by having nowhere to put them.
- **G9, the persistence fork.** `_routes_to_documents_table(doc_type)` in
  `queue_worker/handlers.py` — fail-closed, so `None` (every flag-OFF run) and any
  out-of-vocabulary value keep the `Invoice` row, with a WARNING — and
  `_persist_non_invoice_document()`, which writes the `documents` row and deletes the
  upload-time placeholder in **one** transaction. A4/F4 honoured on both points: `tenant_id`
  comes from the loaded `Invoice` row rather than the queue payload, and the delete is keyed
  on the resolved `id` **plus** `tenant_id`, never on `file_path` (which is not unique within
  a tenant — `routers/invoices.py` copies it onto `DUPLICATE` rows). The fork returns before
  the invoice-specific tail, so no `invoice.completed` webhook fires for a purchase order and
  nothing lands in `invoice_chunks_{tenant}`.
- **G10, the sibling collection.** `_document_collection_name()` → `docs_{tenant_id}`,
  opened only through `get_document_collection()`, which passes `_collection_metadata()`
  (§8 trap 3 / Gap 244 — Chroma pins HNSW space at creation and silently hands back an
  existing collection on its original space). `index_document_chunks()` mirrors the invoice
  indexer's page-per-chunk shape with a type-named header and **no `invoice_id` metadata key**.
- **G14, the read surface and the quota union.** `GET /documents` (tenant-scoped from the
  auth context, soft-delete aware, `doc_type`/`batch_id` filters, `X-Total-Count`) and
  `GET /documents/{id}`, both through `_require_owned_document()` — one query carrying `id`,
  `tenant_id` and `deleted_at IS NULL`, **404 and never 403** on a cross-tenant id (A4/F1).
  An explicit `DocumentOut` keeps `source_document_json` off the wire.
  `count_billable_uploads()` dedups against
  `{Invoice.file_hash WHERE tenant_id = :t} ∪ {Document.file_hash WHERE tenant_id = :t}` —
  **the predicate is inside each side**, per A4/F2.

**Decisions this spec did not specify, recorded so a later reader does not assume they were
arbitrary.**

1. **`Document.doc_type_confidence` — a third column E10's list does not name.** §2A/N2's 0.6
   threshold is an uncalibrated placeholder, and it has nothing to calibrate against unless
   the distribution is persisted. Storing the number costs a float per row; not storing it
   makes N2 unresolvable forever.
2. **The auth dependency on both endpoints is `get_tenant_context` (Clerk session), not
   `get_tenant_or_api_key_context`.** Feature 25's API-key scopes were written against the
   invoice lifecycle and no integration has ever been told this table exists. Widening machine
   access to a new document population is a product decision with its own scope question, not
   a side effect of adding a read endpoint. Narrower is the reversible direction — but it is a
   narrowing §4 did not ask for.
3. **The terminal SSE event carries both ids.** `invoice_id` (the placeholder's, read before
   the delete) *and* `document_id`. An open stream is keyed on the id the upload returned, so
   omitting it would leave that row on `PROCESSING` forever rather than reaching a terminal
   state. E10's product consequence — the upload vanishes from the ingestion status table
   until G11 exists — is unchanged by this; it is a rollout gate, not a bug in this path.
4. **`should_index_status()` is reused rather than reimplemented**, so "is this worth
   indexing?" stays in one place (Gaps 240/243): `EXTRACTED` passes, `EXTRACT_FAILED` does not.

**Deviations from §4 / E10 / §2A, stated rather than absorbed.**

- **The migration's real head is `d3e4f5a6b7c8`, not §4's cited `c2d3e4f5a6b7`.** Feature 26
  Part 2's H4 chat-attachment-index migration landed on top of that revision during the same
  session. The chain was re-walked at write time rather than trusted from the spec — the check
  Gap 60's multi-head incident exists for. **§4's citation is stale; do not follow it.**
- **`apps/invoice-fe/types/invoice.ts` (§4's FE row) does not exist** — already recorded in
  G11's note below, repeated here because §4 is the file a next dispatch will read first.
- **A4/F5's required ruling was not made, in code or in prose.** See the open items.

**The coupling with G7, carried forward.** `_should_persist_coordinates()` (Gap 379's third
gate) **now always resolves `True` wherever it is still reached**, because G9 returns early
for exactly the types that gate returned `False` for. It is kept, not deleted: the two
questions fail closed towards different things — a mislabelled box vs. a deleted row — so they
are deliberately not written as each other's negation, and A1's hazard is now prevented one
layer up by the row not existing. Defence in depth, and this note says so rather than leaving
a gate that quietly does nothing. G7's `test_a_delivery_notes_persisted_coordinates_are_empty`
became `test_a_delivery_note_never_reaches_the_coordinates_gate_after_g9` for the same reason.

**Tests, and the evidence caveat — read this before citing any of it.**
`tests/test_documents_table.py` exists and is a real §9 T-E10 implementation: 21 test
functions covering T-E10-1 (with an `EXTRACT_FAILED` variant and an invoice-family control so
it cannot pass vacuously), T-E10-2 (the Gap-329-shaped aggregate byte-identity assertion),
T-E10-3 (including A4/F2's second-tenant case and soft-deleted rows still deduping), T-E10-4
(cosine space, and `query_invoice_chunks()` unable to reach the collection), T-E10-5
(cross-tenant 404, scoped list, soft-delete invisible on both endpoints), plus eight
no-database tests over the routing decision and the model's column list. It is written to hard
rule 2 correctly — `pg_engine_or_skip()` requires a real `postgresql://` URL and **skips**
rather than falling back to SQLite. **But no run of this file is recorded anywhere in the
repo, and the documentation pass that wrote this note ran nothing.** A skip-guarded suite with
no recorded run is not evidence. **The migration has never been applied to any Postgres
instance**, so `upgrade`/`downgrade` are unproven; environments reaching this code today are
schema-built by `SQLModel.metadata.create_all()`. The only real runs touching this code are
Gap 379's regression sweeps, which ran *other* suites with G9 present — that shows G9 did not
break them, not that G9 works. T-OFF-1 and T-R-6 remain task V, blocked on §7 task F.

**Open items — not done, and each named rather than omitted.**

1. **§2A/A4/F5's ruling.** `routers/invoices.py` is unmodified, so the ingestion door's own
   hash check still looks only at `Invoice.file_hash`; once a non-invoice's original lives in
   `documents`, **every re-upload of it reprocesses** at real OCR + extraction cost. A4/F5
   requires the spec to state one of: widen `_ingest_single_file`'s check the same
   tenant-scoped way the quota fix was widened, **or** state explicitly that non-invoice
   re-uploads reprocess in v1. **Silence is what currently exists**, which A4/F5 names as the
   one unavailable option. Needs a scoped BE dispatch; not decided here.
2. **`docs_{tenant}` has no lifecycle.** No documents-side counterpart to
   `delete_invoice_chunks()`; `scripts/reembed_chroma_collections.py` and the sandbox tenant
   sweep do not know the collection exists; soft-deleting a `Document` leaves its chunks
   indexed.
3. **`Document` rows have no reconciliation sweep.** `last_enqueued_at` /
   `processing_attempts` mirror FE Gap 81/84's pattern but nothing writes or reads them after
   the insert, so a stuck document has no re-enqueue path an invoice would have.
4. **G14 has no FE consumer** (G11 is `[~]`), so the §2A/N1 rollout gate stays shut.
5. **The table is invisible to chat.** The NL→SQL route knows only `invoice` — intended for
   v1 by E10, but it means "show me my delivery notes" cannot be answered at all.

**Rollout status — unchanged by this slice, and deliberately not improved.**
`ENABLE_GENERIC_EXTRACTION` **stays off** and must not be turned on in a user-facing
deployment. The extraction/verification path was already correct behind the flag after Gap 379;
what G9/G10/G14 add is that a classified non-invoice now lands somewhere coherent instead of in
`invoice`. What still blocks a user-facing flip is unchanged: **no FE surface** (G11 `[~]`,
itself blocked on a flag-exposure mechanism that does not exist), plus E9's fail-loud (rest of
G6), `document_to_base64_images` (G8), §7 task F's fixtures at ~2 of 10 document types, and
task V, which F blocks. **The honest summary: E10 is built and unproven — correct by
construction and by review, with no executed test evidence and no Postgres migration run
behind it.**

---

### Build note — G11 (FE), 2026-09-02 (FE tracker Gap 378)

Additive record per hard rule 4; nothing in §3–§10 is rewritten. Full FE-side detail lives
in `apps/invoice-fe/docs/feature_3_ingestion.md`'s new section "Document type on the
ingestion surfaces". This note records what a *backend* reader needs to know.

**Two of four pieces built; two blocked. G11 is `[~]`, and the rollout gate stays shut.**

**Built.** `components/ingestion/StatusTable.tsx` renders a document-type badge in the File
cell, and `app/invoices/review/[id]/page.tsx` (the auditor console) shows `doc_type` plus
`doc_type_evidence` as two rows in its existing "Additional Extracted Metadata" panel. Both
render **only when the field is present**, which is never, today: G9 has not landed
(`models.py` still has no `Invoice.doc_type`) and the flag defaults `False`. A Playwright
regression test asserts the absent case renders identically to before, including that the
ledger still has exactly three column headers — no column was added, because FE Gap 113
removed the old "Type" column for being constant on every row.

**Blocked (1) — `DropZone.tsx`'s accept list is still `.pdf`, and this needs a backend
decision before G11 can close.** §4 requires the widening be gated on
`ENABLE_GENERIC_EXTRACTION` "surfaced via the existing config/feature endpoint, not
hardcoded". **That endpoint does not exist.** Verified repo-wide 2026-09-02: every `ENABLE_*`
in `config.py` is consumed server-side only — `ENABLE_ASYNC_CHAT_QUEUE` is read inside
`routers/chat.py` and the FE adapts to the *response shape*, never to a flag value —
`main.py` registers no `/config` or `/features` router, `routers/settings.py` exposes tenant
configuration and credentials but no software flags, and the only flag-shaped values the FE
can see are build-time `NEXT_PUBLIC_*` env vars, which cannot reflect a backend process
setting. Hardcoding the widening would let a user select a PNG that, with the flag off,
`pdf_to_base64_images()` returns `[]` for — silently losing the multimodal channel, the exact
degradation §4's "Non-PDF image support" subsection calls the real defect. Inventing a
`/features` endpoint was outside this task's authorisation. The two guards were instead
refactored onto one shared `ACCEPTED_EXTENSIONS` constant so they cannot drift apart when
the mechanism does arrive. **Whoever picks this up: the missing piece is flag exposure, and
it is BE scope. This is not an FE oversight.**

**Blocked (2) — no documents-list surface.** E10 sends non-invoice documents to the
`documents` table and G14's `GET /documents` does not exist yet. Deliberately not built.

**Correction to §4's FE row — `apps/invoice-fe/types/invoice.ts` does not exist.** That
app's `types/` directory contains only `chat.ts` (Feature 5). The invoice/status shapes live
beside their consumers: `StatusItem` exported from `StatusTable.tsx`, `InvoiceDetail` in the
review page. Both were extended in place; no new shared types module was created for one
optional field. §4's row is left as written (hard rule 4) — this note is the correction.

**Verification.** `npx tsc --noEmit` exit 0; new `e2e/feature27-doc-type.spec.ts`, 6 tests,
all passing against a real Next dev server with `/api/**` stubbed. Four failures in two
pre-existing FE specs were confirmed pre-existing by stashing the changes and re-running at
HEAD (identical 4 failed / 11 passed). **Not verified:** nothing was run against a backend
that actually returns `doc_type`, because none does — that end-to-end claim belongs to
functional-tester after G9.

---

### Build note — R6 (`docs_` lifecycle + soft-delete), 2026-09-03 (tracker Gaps 397/398/399)

Additive per hard rule 4; §1–§9 and every earlier build note are unchanged.

**Two thirds of R6 were already done, and the row said so imprecisely.** The
lifecycle functions landed at Gap 385, and so did both pieces of "sweep wiring"
the task named: `scripts/reembed_chroma_collections.py` carries
`DOCUMENT_COLLECTION_PREFIX = "docs_"` in `ORPHAN_SWEEP_PREFIXES` (`:101–102`,
with the scope note explaining why `docs_` sweeps but does not *rebuild*), and
`scripts/sweep_sandbox_tenants.py` drops the whole collection per tenant via
`delete_tenant_document_collection()` (`:179–181`). Re-checked against the code
before writing anything, per the audit rule that a doc claim must be shown, not
paraphrased.

**What was genuinely missing was the third clause — "soft-delete of a `Document`
removes its chunks" — and it was missing at the root: there was no soft-delete of
a `Document` at all.** G14 shipped `deleted_at` on the model and a
`deleted_at IS NULL` predicate on both read endpoints, so every reader was
correct about a state nothing could ever produce. The column was dead weight and
a tenant who uploaded the wrong contract had no way to withdraw it.

- **`routers/documents.py::delete_document`** — `DELETE /documents/{id}`,
  resolved through the existing `_require_owned_document()` so the cross-tenant
  answer is 404 and not 403, identical to the two read endpoints. Soft-deletes,
  then drops the row's chunks.
- **Order is load-bearing: commit first, chunks second.**
  `delete_document_chunks()` logs and swallows its own failures, so a Chroma
  outage after the commit leaves orphaned chunks that the reembed sweep can still
  reach. The reverse order, on a failed commit, would leave a **live** document
  that had silently stopped being retrievable — the failure nobody would notice.
  `test_the_row_is_committed_before_the_chunks_are_touched` asserts this from a
  second Postgres connection, since the request's own session would see the
  pending change either way.
- **Chunks are deleted here even though `delete_invoice` deliberately retains
  them.** Gap 239 settled the invoice policy the other way — retention serves a
  restore path, and `agents/query_agent.py` (`~:4198`) checks citation
  *existence* rather than visibility, so a soft-deleted invoice stays a
  legitimate citation. That reasoning does not transfer, for a specific reason:
  **nothing reads `docs_{tenant}` yet.** It is write-only today, so there is no
  retrieval path carrying an equivalent guard, and a retained chunk of a
  withdrawn document would become answerable the moment someone adds the first
  reader — silently, in their code, not here. Deleting now creates no obligation
  on a future author.

**Gap 397, found while writing the above and fixed in the same change.**
`DELETE /invoices/batches/{id}` had been rolling back only half of every mixed
batch since E10: it selects `Invoice` rows by `batch_id`, and a classified
non-invoice leaves that table while keeping the same `batch_id`. Worse, a batch
whose files *all* classified as non-invoices matched zero rows and returned
**404 — "no such batch"** about a batch that was entirely live. Both halves are
dormant with the flag off (no `documents` row can exist) and activate on the flip,
which is the class of defect this run exists to find first. The endpoint now
covers both tables on the same three predicates, drops document chunks after the
commit, and reports `document_count` as a **separate** key so `count` keeps
meaning "invoices" for existing callers.

**Gap 398, filed and deliberately not fixed.** A document can now be deleted and
the product's audit trail does not record it, because `AuditLog.invoice_id` is
non-nullable and a document id in a column of that name is exactly the type
confusion E10 exists to prevent. The honest fix is a migration plus a sweep of
every audit reader — its own change. Both delete paths log at INFO in the
meantime, and `delete_document`'s docstring names the gap so the omission is a
recorded decision.

**Gap 381 open item 3 — the re-enqueue sweep for stuck `Document` rows — is
deferred as Gap 399, and the deferral is anchored rather than promised.** A
`Document` has exactly one construction site (`queue_worker/handlers.py:494`,
called at `:944`); it runs *after* the extraction graph returns and builds the row
with `status` already EXTRACTED or EXTRACT_FAILED and `completed_at` stamped.
There is no window in which a `Document` exists and is still owed an answer — a
stall in a non-invoice upload is a stall of the **placeholder `Invoice`**, which
the existing sweep already finds and whose retry re-runs the same handler and
reaches the same fork. Because that is true of the code rather than of the
design, `test_a_document_row_is_only_ever_created_in_a_terminal_status` fails
with a message naming Gap 399 if a `Document` is ever created at upload time, and
the reasoning sits beside `STUCK_STATUSES` in
`services/invoice_reconciliation.py` where the person building the second sweep
will look.

**Evidence.** `tests/test_document_delete.py` → **11 passed against real
Postgres** (hard rule 2), covering the soft delete and both read endpoints, the
chunk call and its exact arguments, commit ordering, an unreachable Chroma not
failing the request, a repeated delete not re-hitting Chroma, a cross-tenant
delete destroying nothing, all four batch-rollback cases and the Gap 399 anchor.
`tests/test_batches.py` + `tests/test_documents_table.py` → 39 passed, unchanged.

## 11. Size estimate — realistic, multi-day

*(Historical, 2026-09-02 original. **Superseded for the remaining work by §10B**, which
carries a per-item size for every open task. Kept as the record of what was estimated
before any code existed; G1–G10/G14 came in inside these figures, F and V did not start.)*

This is **not** a time-boxed session. Honest figures, assuming the specialist is
not simultaneously debugging something else:

| Track | Estimate |
|---|---|
| G1–G2 (flag, classifier, taxonomy, synonyms) | 1 day |
| G3–G5 (schema, overlays, node, rubrics) | 1.5–2 days |
| G3b (profile resolution, A2) | 0.5 day |
| G6–G8 (fail-loud, DI trust boundaries, image dispatch) | 0.5–1 day — down from the original figure: A1 removed the OCR-model selector, which was the largest and riskiest part of G7 |
| G9–G10 + G14 (migration incl. `documents`, sibling collection, list endpoint, quota dedup) | 1.5–2 days — up from 0.5, E10 |
| G11 (FE) — follow-up, excluded from the total | 1–1.5 days |
| G12 (narrow tests alongside) | folded into the above |
| **F (fixture sourcing)** | **1–2 days, parallel, functional-tester** |
| **V (verification against Postgres)** | **1 day, after F** |
| **Total BE** | **~5.5–6.5 working days**, plus F/V in parallel/after (G11 excluded — follow-up, rollout gate only) |

The items most likely to overrun, stated so the overrun is not a surprise. **G7 is no
longer one of them** — A1 established that the `prebuilt-layout` dict-shape contract was
the risk, and there is no longer a `prebuilt-layout` call to have a contract with; what
remains is three gated call sites. The two that stand:
**G9/G14 (E10)** — the `documents` table touches the ingestion door, the worker's
persistence step, billing quota and a new router, and the placeholder-delete transaction
has to be right or an upload can vanish or double-bill; and **F** (sourcing a genuine
Italian DDT or a real GRN is a procurement problem, not an engineering one — start it
first). **F is also now on N2's critical path:** the `0.6` confidence threshold cannot be
called final until F's fixtures produce a real confidence distribution.

The estimate explicitly **excludes** anything in Feature 26.1, which is a
separate spec with its own estimate. If both are wanted, sequence Feature 27
first — 26.1's Tier-3 vector discovery and its per-type answer behaviour both
consume this feature's `doc_type`.
