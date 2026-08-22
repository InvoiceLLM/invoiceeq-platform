# Feature 21: SAGE as a Tool-Calling Agent

Rewritten 2026-08-21, consolidating the full design discussion in one place. Supersedes the previous version of this doc (which described a design that was never actually implemented in code — Phase 1/2's `query_invoices` still used the old narrow, hand-maintained SQL schema, not a full-record fetch). This version is what should actually be built — and **as of 2026-08-21 it is built**: `agents/query_tools.py`, the new `agents/sage_prompts.py` and `agents/sage_orchestrator.py` now match this design. See "What was actually built" further down for what landed, which parts differ from the drafted text and why, and what is still open (Phase 3 verification, and two undecided policy questions). The "Where the existing code stands" section below is kept as the record of what the code looked like when this design was written.

## The problem, stated once, precisely

This repo's extraction pipeline already captures rich, real, structured data per invoice — a combined `tax_amount` *and* an itemized `taxes` breakdown (CGST/SGST/IGST, each with rate and amount), `tax_ids` (GSTIN and equivalents), `compliance_metadata` (IRN, e-Way Bill, QR code, Peppol ID), `payment_instructions`, `references` (PO/SO/delivery notes), `addresses`, `discounts`, `deductions`, and more, confirmed live against real invoice rows. Chat fails on tax and other detail questions not because the data is missing, but because the SQL-generation prompt only knows about a curated ~19-column subset that was hand-typed once and never kept in sync as extraction grew richer. Every incident this session traced to a tax question (Gap 263, Gap 285, the SGST live regression) is the same root cause wearing a different symptom.

The fix is not a bigger prompt. It's not asking the model to remember more facts about the schema. It's removing the need for the model to know the schema at all, for the case that actually matters most: a question about one or a few identified invoices.

## Target architecture

### 1. Identify, then fetch — the core structural fix

Split what is currently one narrow, overloaded SQL query into two steps with different jobs:

- **Identify** (`identify_invoices`) — a narrow, cheap lookup that finds *which* invoice(s) a question concerns, using only the columns that matter for finding a row: `vendor_name`, `customer_name`, `invoice_number`, `invoice_date`, `flow_direction`, `tenant_id`. Rules 1, 4, 4a, 6a, 9, 10 (tenant scoping, direction, ambiguous-entity both-sides check, follow-up narrowing, no-`LIMIT`-on-comparisons) still apply here — they are about *finding the right row*, which is exactly this step's job. This is the *only* place a hand-maintained schema description should exist, and it should stay small on purpose.
- **Vendor identity is a name-matching problem, not just a string filter** (business-analyst review, 2026-08-21) — a real vendor is captured inconsistently across invoices ("Om Packaging" / "Om Packaging Pvt Ltd" / "OM PACKAGING"), and a plain `LIKE` in `identify_invoices`/`aggregate` treats these as different vendors, silently undercounting a real vendor's true total. `identify_invoices` needs normalized/fuzzy matching (case-fold, strip legal suffixes like Pvt Ltd/LLC/Inc, whitespace-insensitive), not exact/substring match alone.
- **When a name match is genuinely ambiguous, ask — don't try to resolve it automatically** (decision, 2026-08-21) — a near-duplicate name could be the same vendor typed inconsistently, or two real, distinct legal entities that happen to share a name. Considered and rejected: disambiguating via `tax_ids`/GSTIN match — we don't reliably know which vendor the user means, and picking one silently risks answering the wrong entity's question with confidence. Instead, when normalized matching surfaces more than one distinct-looking candidate for the same name, `identify_invoices` routes to `ask_clarifying_question` and lets the user pick, rather than guessing via any secondary field.
- **Fetch** (`get_full_record`) — once invoice(s) are identified, load the real ORM row(s) in full — every field the `Invoice` model actually has, reflected at call time (`invoice.model_dump()` or equivalent), never a hand-typed column list. A column added to the schema tomorrow is visible to this tool tomorrow, with zero prompt edit required. This is what actually closes the class of bug found today.

### 2. Full document context for identified invoices

Once an invoice is identified, `get_full_record` also pulls *every* indexed ChromaDB chunk for that specific `invoice_id` — a direct metadata filter, not a top-k semantic search hoping the right page surfaces. Semantic search (`search_invoices`, below) stays reserved for genuine discovery questions where no specific invoice is identified yet.

### 3. The aggregate case — deliberately kept separate, but its field coverage is narrow today and needs the same fix as everything else

"How much did we spend on office supplies this quarter" is not a question about one or a few identified invoices — dumping full records of hundreds of rows doesn't scale and isn't what full-record-fetch is for. This stays its own tool, `aggregate(question)`, built on the existing rule 5/6b/6c/6d logic. This is intentionally the *one* remaining place a curated, schema-aware query still exists — narrowing the schema-drift surface to a single, known, auditable location instead of leaving it spread across every tax/detail question the way it is today.

**Rule 6b's field coverage is itself an instance of the schema-drift bug, confirmed by reading the actual rule text** (`query_agent.py:1337-1350`): the category-match OR-clause only checks 4 hardcoded columns — `tags`, `items`, `vendor_name`, `customer_name`. Not because those are the only fields that can carry a category word — because someone hand-picked those 4 when the rule was written and it was never revisited as the `Invoice` model grew to 44 columns. Real category-relevant text also sits in `references` (PO/SO/delivery notes), `payment_instructions`, `compliance_metadata`, `discounts`, `deductions` — a packaging expense referenced only in a PO note is invisible to `aggregate` today. **The fix is the same principle as `get_full_record`**: `aggregate`'s category-match clause must be built from every text/JSONB-bearing column reflected off the live model at runtime, not a hand-typed 4-column list — **excluding `addresses`** specifically, since a street/branch address is identity/routing content, not economic content, and is the one column most likely to produce a false-positive category match (a "packaging" street name matching a packaging-spend query). Every other column stays in scope — this is a single, deliberate exclusion, not a tiered-evidence system.

On the ChromaDB side, this gap does not exist — confirmed by reading `chroma_client.py:403-410`: each chunk is the *entire raw OCR page text* (`page.get_text()`), not a curated field subset, plus the `[Vendor: ... | Document ID: ... | Page ...]` header. Whatever text appears anywhere on the invoice is already searchable. So "check everything we have" is already true for ChromaDB; it was only ever a Postgres/SQL-side gap.

**Vendor-name-as-category-evidence, now folded into the general fix rather than a special case**: because `vendor_name` becomes one column among the full set `aggregate` scans, a vendor named "Om Packaging" continues to surface under a "packaging expenses" query — same as it does today, and same as ChromaDB already does via the header/metadata. This remains a deliberate behavior worth the user explicitly confirming (a vendor whose name coincidentally contains a category word is a false-positive risk), but it's no longer a special carve-out to design around — it falls naturally out of "scan every field."

**Multi-currency roll-ups must never be silently summed** (business-analyst review, 2026-08-21) — verified directly against rule 5's own live example query (`query_agent.py:1331-1335`): its conditional-aggregation `SUM(CASE WHEN flow_direction=... THEN grand_total ...)` sums `grand_total` across every currency present, unconditionally. A tenant with both USD and INR invoices gets one meaningless blended number today. `aggregate` must either (a) `GROUP BY currency` and return one total per currency, or (b) ask a clarifying question when a combined/net question spans more than one currency — never collapse mixed currencies into a single figure.

**Fiscal-year-ambiguous date ranges** (business-analyst review, 2026-08-21) — "this quarter"/"this year" is genuinely ambiguous (calendar year vs. April–March fiscal year, common in India); no `fiscal_year` setting exists on the tenant model today (confirmed by grepping `models.py`), so this is not a new-column ask. Instead: `aggregate` should either state its calendar-year assumption explicitly in the answer, or use `ask_clarifying_question` when the ambiguity is material to the number — faithfulness by construction applies to date-range assumptions too, not just to the figures themselves.

### 4. A real skilled persona — its own maintained block

A dedicated system-prompt layer carrying actual invoice/tax/business-document domain knowledge, separate from the identify/fetch/aggregate prompts so it can't drift the way everything else in this codebase's prompts already has. At minimum:
- How CGST/SGST/IGST structurally relate (CGST+SGST together = intra-state GST, legally equal halves; IGST alone = inter-state) — so the model reads an IGST-only invoice as *correct*, not as "missing data."
- What GST/VAT/sales-tax conventions mean and how they differ by jurisdiction (this repo already has India/US/EU tenant data).
- What common compliance identifiers represent (GSTIN, IRN, e-Way Bill, Peppol ID) — so a question about one is answered from real understanding, not just echoed from a field name.
- Reverse charge under GST (business-analyst review, 2026-08-21) — some transactions shift GST liability from vendor to recipient; the persona must not assume forward-charge (vendor collects, remits) is universal when a question touches "GST paid" or tax liability.
- Surface `sa_alerts` when present, don't stay silent on it (business-analyst review, 2026-08-21) — `sa_alerts` (duplicate/audit flags) is already part of every record `get_full_record` fetches; if a fetched invoice carries a duplicate or audit flag and the question concerns its amount, the answer should mention it rather than quietly treating the figure as clean.
- Judgment for the vendor-name-vs-category question above, once that decision is made.

Its job is to help the model *interpret* real fetched data correctly — never to substitute for data it doesn't have, and never to override what a fetched record actually says.

### 5. Faithfulness — a property of what's in the prompt, not a rule fighting other rules

The original Feature 21 failed because "never speculate" was a prose instruction added to a prompt that already had other, equally necessary prose instructions, and they collided. The fix here is structural: if the synthesis step's prompt contains *only* the fetched full record, the full document chunks, the persona, and pre-computed arithmetic, there is nothing else in it to speculate from — the instruction becomes true by construction rather than something the model has to remember not to contradict. Where a fetched record genuinely has an empty `taxes: []`, the model is looking at that fact directly, not weighing a prose rule about what the schema supports.

### 6. Arithmetic — unchanged, it was already right

`compute()` (`sum_by_currency`, `reconcile_line_items`) stays exactly as built in Phase 1. Deterministic, LLM-free, and it's the one piece of the current implementation that was correct on the first pass.

### 7. The orchestrator loop — unchanged shape, confirmed correct

The existing `agents/sage_orchestrator.py` loop is a genuine Think → Act → Observe → React cycle, verified directly against its own routing code: `_plan_node` (think) → `_act_node` (act, and the tool's real result is appended to the message history — observe) → `_route_after_act` returns to `"plan"` after every act unless a clarification fired or the call budget is spent (react — the model re-reasons with what it just learned) → repeats until no tool call, then `_synthesize_node`. This shape is sound and should be kept; what needs rework is which tools it calls, not the loop around them.

## Tool set

| Tool | Job | LLM inside? |
|---|---|---|
| `identify_invoices(question)` | Narrow lookup — which invoice(s) match. Returns IDs plus enough to disambiguate (name, date, total) if several match | Yes, narrow schema (rules 1/4/4a/6a/9/10 only) |
| `get_full_record(invoice_id)` | The real fix — complete ORM row, zero curation, plus every ChromaDB chunk for that invoice | No |
| `search_invoices(question)` | Discovery — semantic + structured hybrid, for "which invoices relate to X" when nothing is identified yet | Yes, rules 6b/6c |
| `aggregate(question)` | Cross-invoice totals — the one remaining narrow, schema-aware, auditable path. Category match scans every text/JSONB column reflected at runtime except `addresses`, not a hardcoded 4-column list | Yes, rules 5/6b/6c/6d |
| `compute(operation, values)` | Deterministic arithmetic | No |
| `ask_clarifying_question(question, reason)` | Stop and ask instead of guessing | No |

## Draft prompt text

Exact draft text for the three new/changed prompts. Not yet wired into code — for review before implementation.

### Skilled persona block (shared: planner prompt + synthesis prompt)

```
You are SAGE, a financial-documents assistant embedded in an accounts-payable/accounts-receivable
platform. Your audience is accounts-payable staff, controllers, and auditors -- professionals who
read your answers against real invoices and real money, and who will catch it if you're vague or wrong.

TAX DOMAIN KNOWLEDGE
- CGST + SGST together represent one intra-state Indian GST transaction; by law CGST always equals
  SGST on the same invoice. An invoice showing only IGST is an inter-state transaction -- this is
  correct, not a missing component. Never describe an IGST-only invoice as "missing CGST/SGST."
- GSTIN is India's tax registration ID; VAT number and EIN/TIN serve the equivalent role in the EU
  and US respectively. These are jurisdiction-specific labels for the same underlying concept: whose
  tax registration this transaction is filed against.
- IRN, e-Way Bill number, and Peppol ID are compliance/logistics identifiers, not tax amounts -- IRN
  is the invoice reference number issued by India's invoice registration portal, e-Way Bill authorizes
  goods movement, Peppol ID is an e-invoicing network address. Answer from what they represent, not
  just by echoing the field name.
- Under reverse charge (RCM), tax_amount = 0 on the invoice itself is CORRECT -- the recipient
  self-assesses and remits the tax separately. Do not describe an RCM invoice's zero tax_amount as
  an error or an extraction gap; if the question concerns tax liability on such an invoice, surface
  the self-assessed liability, don't just stay silent on it.
- Tax regimes are not interchangeable in meaning: US sales tax is an unrecoverable cost to the
  business; Indian GST is typically a recoverable input tax credit (an asset, not a pure cost); EU
  VAT has its own intra-community reverse-charge rules. "How much tax did we pay" means a different
  thing depending on the tenant's jurisdiction -- answer according to that tenant's regime, don't
  assume US sales-tax conventions apply everywhere.

CATEGORY AND ENTITY JUDGMENT
- A vendor's own name is legitimate evidence for a spend category (a vendor named "Om Packaging" is
  real evidence for a "packaging expenses" question), same as a matching tag or line-item description.
  Do not treat a name match as weaker evidence than a tag match.
- If a name match is ambiguous between what could be two distinct vendors, you were not given enough
  information to guess -- that case has already been routed to a clarifying question before you see it.

DATA HONESTY
- If a fetched record's structured field and a document chunk's raw text disagree, say so -- the
  structured field is authoritative for the number, the chunk is corroboration/citation only, but a
  real conflict is worth surfacing, never silently resolved in favor of one side.
- If an audit or duplicate flag (sa_alerts) is present on a record relevant to the question, mention
  it -- do not answer around it.
- Never present a zero total as a confident answer. A zero means "no matching records under this
  filter" -- say that explicitly, don't hand back "$0.00" as if it were a real total.
- Never sum amounts across different currencies into one number. If a question spans more than one
  currency, report each currency separately unless the user has explicitly asked for and accepted a
  conversion at a stated rate.
- If a date range like "this quarter" or "this year" is ambiguous between calendar-year and a fiscal
  year, state which one you used.

You answer only from what your tools actually returned. If a tool didn't return it, you don't know
it -- say so rather than filling the gap from general knowledge or a prior turn's conversation text.
```

### `identify_invoices` prompt

```
You are generating a narrow lookup query to find which invoice(s) a question concerns. You are NOT
computing totals, tax breakdowns, or any other detail here -- only finding the right row(s). A
separate tool fetches full detail once the invoice is identified.

Schema (only these columns are visible to you):
- id: UUID
- tenant_id: UUID
- vendor_name: VARCHAR (INBOUND only)
- customer_name: VARCHAR (OUTBOUND only)
- invoice_number: VARCHAR
- invoice_date: DATE
- flow_direction: VARCHAR ('INBOUND' = a vendor's invoice sent to this tenant; 'OUTBOUND' = this
  tenant's own invoice sent to a customer)
- grand_total, currency: for disambiguating between several same-named matches only

Rules:
1. Always filter by tenant_id = '{tenant_id}'.
2. A question about a vendor/bill received means flow_direction='INBOUND', filtered by vendor_name.
   A question about a customer/invoice sent means flow_direction='OUTBOUND', filtered by
   customer_name. Never mix the two for the wrong direction. If the entity could plausibly be
   either, check both sides rather than guessing one.
3. Normalize vendor/customer names before matching: case-fold, trim whitespace, strip common legal
   suffixes (Pvt Ltd, Ltd, LLC, Inc, Corp) before comparing.
4. If normalized matching surfaces more than one distinct-looking candidate for the same name
   (different ids, nothing in the question disambiguates them), do NOT guess which one the user
   means -- return every candidate and let the caller invoke ask_clarifying_question.
5. Follow-up questions that narrow a previous answer: reuse the previous turn's WHERE clause
   verbatim, only ADD the new restriction.
6. Comparison questions naming two or more specific entities: return a row for every named entity,
   never ORDER BY ... LIMIT 1.
```

### `aggregate` prompt

```
You are generating a cross-invoice aggregation query -- the question needs a total, count, or
breakdown across more than one invoice, not a single identified invoice's detail (that is
identify_invoices + get_full_record's job).

Schema: the full Invoice model, reflected at runtime -- every column, not a hand-typed subset.

Rules:
1. Always filter by tenant_id.
2. Direction: same rule as identify_invoices. For a combined/net question spanning both directions
   ("how much do we owe vs. are owed"), use ONE query with conditional aggregation
   (SUM(CASE WHEN flow_direction='INBOUND' THEN grand_total ELSE 0 END), same for OUTBOUND) rather
   than two separate queries.
3. CURRENCY: never blend currencies into one SUM. GROUP BY currency. If the question implies one
   number is wanted across mixed currencies, do not silently pick one -- flag it so the caller can
   invoke ask_clarifying_question.
4. CATEGORY MATCH: when the question refers to a tag, line-item description, or general category
   word, OR together a LOWER(CAST(col AS TEXT)) LIKE match across every JSONB/text column in the
   schema EXCEPT `addresses` (identity/routing content, not economic content -- excluded to avoid
   false positives). This includes tags, items, vendor_name, customer_name, references,
   payment_instructions, compliance_metadata, discounts, deductions. Cast JSONB columns to text
   before LOWER/LIKE; plain VARCHAR columns must NOT be cast.
5. LINE ITEMS: per rule 6d, unnest items via jsonb_array_elements (Postgres) / json_each (SQLite)
   rather than matching against the whole JSON blob.
6. STATUS INCLUSION: [DECISION REQUIRED -- not yet defined which Invoice.status values count toward
   "spend." Do not silently include/exclude rejected, duplicate, unextracted, or soft-deleted rows
   without this being an explicit, documented choice.]
7. ZERO RESULTS: a query returning zero rows or a zero total must never be handed back as a
   confident answer -- return enough for the caller to route to ask_clarifying_question or an
   explicit "no matching records" response.
8. PROVENANCE: always return the invoice_ids behind any total, the filter applied, and the
   currency -- needed for drill-down and audit.
9. FISCAL YEAR: if the date range in the question is ambiguous between calendar-year and a fiscal
   year, state the assumption used.
10. Whenever monetary columns are selected, also select currency.
```

## Where the existing code stands, honestly

**Superseded 2026-08-21 by "What was actually built" below — the rework this section calls for has
since been done. Kept as the record of what the code looked like when this design was written.**

`agents/query_tools.py` (Phase 1) and `agents/sage_orchestrator.py` (Phase 2) are real, working, well-structured code — the loop, the tool-call budget, the compute-grounded synthesis, the citation verification, the clarification short-circuit are all genuinely built and wired in behind `ENABLE_AGENTIC_SAGE` (default off, confirmed nothing runs for any tenant today). What they are missing is the actual fix: `query_invoices` still calls `build_sql_system_prompt()`, the same ~19-column hand-maintained schema every other route already uses — it was never reworked into `identify_invoices` + `get_full_record`. None of Phase 1/2's own verification steps (parity test, real-LLM run, full suite delta) were confirmed complete before work was paused — the tasklist has every box unchecked. Treat the loop/compute/clarification machinery as reusable; treat `query_invoices` as needing to be replaced, not patched.

**Cost and latency, measured 2026-08-21** (this was the open item with no number anywhere): both
paths were run end-to-end against the real Azure deployment, 36 turns. SAGE Phase 2 **does** run
end-to-end today on `query_invoices`, at **+38% model calls, +12% median latency, +56% worst-case
latency and +22% cost per turn** versus the current default path. Full table, method and caveats in
[`feature_21_architecture.md`](./feature_21_architecture.md) § "B4 — Cost and latency budget:
MEASURED". Read the clarification-rate finding there before setting any budget from it.

## Rollout plan

Unchanged from before: parallel, flagged path (`ENABLE_AGENTIC_SAGE`, default off), tested against real tenant data — NovaTech/US question banks plus every named incident this session found (rule 4a, 6b-vs-6d, the tax-component case, the SGST fabrication, Gap 285) as regression cases — before any default-on decision for any tenant.

## Phases

- **Phase 1 (reworked and built, 2026-08-21)** — `query_invoices` is replaced by `identify_invoices` + `get_full_record`; `search_documents` is now `search_invoices`; `aggregate` is built. `compute` and `ask_clarifying_question` carried over unchanged, as planned. See "What was actually built" below.
- **Phase 2 (rewired, 2026-08-21)** — the orchestrator loop, its routing conditions and its budgets are unchanged (they were already right). The tool schemas, `_ToolBox`, the planner prompt, `planner_view` and `_synthesize_node`'s per-tool rendering were rewritten around the new tool set, and the skilled-persona block is now in both the planner and the synthesis prompt.
- **Phase 3 (not started)** — regression suite against every named historical incident, real-LLM verification (not yet confirmed for any of this despite code comments implying at least one live run happened — reconcile that before trusting it), live tenant testing, before any default-on decision.

## Known limitations — real gaps, not fixable inside this feature

Two items from the business-analyst review are genuine real-world gaps but not chat problems — verified by grepping `models.py`, which has no `document_type`/credit-debit distinction and no `paid_amount`/`balance_due` field:

- **Credit notes / debit notes** — every captured row is a plain invoice; there is no sign convention or document-type distinction to net a credit note against the invoice it corrects. Chat can only reflect `grand_total` as extraction captured it. Fixing this means an extraction/schema change (a `document_type` column, a sign or offsetting-amount convention), which is outside Feature 21's scope. Until then, a "how much did we spend with X" answer may overstate spend if X issued any credit notes.
- **Partial payments / outstanding balance** — `status` is an enum (e.g. PAID/UNPAID), with no partial-payment amount captured. "How much do we owe X" can only ever answer with `grand_total`, not a true outstanding balance, until extraction captures payment amounts. Same conclusion: a schema/extraction change, not a chat-layer fix.

Both are worth a future gap/feature of their own; flagging here so nobody assumes chat already accounts for either.

## Explicitly out of scope

- Removing or replacing the existing `run_query_agent()` pipeline — stays live and default until Phase 3 passes against real tenant data.
- Anything in `chroma_client.py`'s indexing/embedding logic itself (what gets embedded, chunk size, the vendor-name header) — this feature is about how SAGE *uses* what's already indexed, not how indexing works. The vendor-name-in-category-match question is a *usage* decision (which tools/rules apply it), not an indexing change.

## What was actually built, 2026-08-21

The target tool set above is now real code, behind `ENABLE_AGENTIC_SAGE` (still default off,
untouched — nothing in this build runs for any tenant). Files:

- **`agents/sage_prompts.py`** (new) — `PERSONA_BLOCK`, `IDENTIFY_SCHEMA_BLOCK`,
  `IDENTIFY_RULES_BLOCK`, `AGGREGATE_RULES_BLOCK` as separate named constants, plus
  `build_identify_system_prompt()` / `build_aggregate_system_prompt()` that assemble them at call
  time. The aggregate schema block and rule 4's category columns are **reflected off the live
  `Invoice` model** (`aggregate_schema_block()`, `category_match_columns()`,
  `render_category_match_clause()`), so a column added to `models.py` is in the prompt with no
  prompt edit. That reflection is the fix; everything else is plumbing around it.
- **`agents/query_tools.py`** — `query_invoices` and `search_documents` are gone. `identify_invoices`
  (narrow 6-column lookup + deterministic normalized-name retry + ambiguity clarification),
  `get_full_record` (`Invoice.model_dump()` + every Chroma chunk for that `invoice_id` by direct
  metadata filter), `search_invoices` (semantic retrieval + a structured category match built in
  code), `aggregate` (reflected schema, currency/zero/provenance/fiscal-year checks). `compute` and
  `ask_clarifying_question` are byte-for-byte unchanged.
- **`chroma_client.get_all_invoice_chunks()`** (new) — every indexed page of one invoice, no
  ranking and no relevance threshold. Once the invoice is identified, "the page with the tax table
  didn't score high enough" is silent data loss, not a relevance decision.
- **`agents/sage_orchestrator.py`** — six tool schemas instead of four, `_ToolBox.dispatch` rewired,
  planner prompt rewritten around identify→fetch, `planner_view` and `_synthesize_node` given a
  branch per tool, and `PERSONA_BLOCK` prepended to **both** the planner and the synthesis prompt.
  The loop itself (`_plan_node`/`_act_node`/`_clarify_node`/`_synthesize_node` and every routing
  condition) is unchanged — it was already the right shape.
- **`agents/query_agent.py`** — one additive parameter, `run_sql_generation_loop(...,
  telemetry_agent_name=...)`, default unchanged, so the new tools emit `sage.identify`/
  `sage.aggregate` Feature 23 events rather than nesting a second `tracked_llm_call`.

**Several rules are enforced in code as well as in prose, deliberately.** Normalized name matching,
the more-than-one-candidate clarification, the zero-total and blended-currency checks, rule 6c's
phrase handling and the fiscal-year assumption are all functions, not instructions. A prose rule
fires when a phrasing resembles what it was written against (rule 6d's tax-component miss is the
standing example in this repo); a function fires every time. Nine specific places where the code
deliberately differs from `feature_21_architecture.md`'s literal text — including one worked SQL
example in that doc that does not parse, because `references` is a reserved word — are listed in
that doc's "As built" section.

**Verified**: `tests/test_query_tools.py` 84 passed (rewritten for the new tool set),
`tests/test_agentic_sage.py` 37 passed (rewritten; this also fixed 3 assertions that had been
failing against the real prompt text since before this work). Full suite: **888 passed / 3 failed /
6 skipped**, against a pre-change baseline of 837 / 6 / 6 — the 3 fixed failures are those
assertions, and the 3 that remain are the same pre-existing ones (2 x `test_connectors.py` needing
a live Redis, 1 x `test_rag.py`'s stale `post_chat_message` signature), untouched by this work.

## What the first live run changed, 2026-08-21

Everything above was mocked at the LLM boundary. The tools were then run against real
`gpt-5-mini` — 44 measured turns, `scripts/run_agent_eval.py`, full numbers in
`feature_21_architecture.md`'s B4 section. Three things came out of it that the 121 passing mocked
tests could not have found:

1. **`identify_invoices` did not work at all.** `IDENTIFY_SCHEMA_BLOCK` listed the six lookup
   columns but never named the table, so the model wrote `FROM invoices` and kept writing it through
   every repair attempt: every single-invoice lookup ended as `no such table: invoices`. The block
   now names `invoice` in its first line. Every identify→fetch turn in the sample worked afterwards.
2. **`get_full_record`'s document dump was a real, unbounded cost.** Measured: 15,977 tokens of page
   text on an 11-page invoice, linear in page count, no bound anywhere; the resulting
   `sage.synthesis` prompt was 129,818 input tokens against 1,906 for the identical question on a
   one-page invoice, at ~8x the default path's median turn cost. Bounded in
   `query_tools.bound_document_pages()` (`MAX_FULL_RECORD_CHUNK_CHARS`, first and last page always
   kept, `pages_omitted` disclosed to both the planner and the answer step, exactly like
   `columns_omitted`). **`get_all_invoice_chunks()` itself is unchanged** — section 2 above says
   retrieval must be complete once an invoice is identified, and it still is; what is bounded is how
   much of it one answer carries, and the truncation is told to the model rather than hidden.
   Accuracy on the large-invoice case was 1.0 before and after the bound.
3. **The same record was fetched three times per turn**, in every identify→fetch turn, spending the
   whole tool-call budget and putting three copies of the record and its pages into the prompt.
   `_act_node` now answers an identical repeat call (UUID arguments canonicalised first, after the
   model passed the same id dashed and dashless in one turn) from the turn's own results.

After 2 and 3: the large-invoice turn went 142,596 → 50,001 input tokens and $0.0396 → $0.0175, and
the sample's worst turn went 167.5s → 68.8s.

**What is still open after the run** is in the task list below, and one item is new: on the large
invoice the page dump was only ~40% of the fetch. The other 26,800 tokens are the `record` itself,
almost entirely the 400-entry `items` JSON, and that is deliberately untouched — "every column, no
curation" is this feature's mandate and `items` is what line-item questions are answered from.

## Tasks

- [x] Rework `query_invoices` into `identify_invoices` (narrow) + `get_full_record` (full ORM row + full per-invoice ChromaDB chunks) — built 2026-08-21; `get_full_record` omits five storage-plumbing columns and reports them in `columns_omitted` (deviation 3 in the architecture doc). Live run 2026-08-21 then fixed `identify_invoices`' prompt (it never named the `invoice` table, so every lookup generated `FROM invoices` and failed) and bounded the document half (`bound_document_pages()`, `pages_omitted` disclosed) — see "What the first live run changed"
- [x] Rename/adapt `search_documents` → `search_invoices` for the discovery case — built, and made a real hybrid: semantic retrieval plus a structured category match whose SQL is built in code from extracted phrases
- [x] Build `aggregate` for cross-invoice totals, reusing rules 5/6b/6c/6d, with rule 6b's category-match clause rebuilt to scan every text/JSONB column reflected at runtime except `addresses` — built; the rule 4 (relevance) vs. rule 5 (line-item value) boundary is explicit in `AGGREGATE_RULES_BLOCK`, and rule 5 is composed from the existing `_line_item_rule()` dialect constants rather than a second copy
- [x] `aggregate` provenance: reuse `_harvest_invoice_ids_via_companion_query()` for row-identity recovery on `GROUP BY`/`SUM` results (Gap 231) — done, and `aggregate` never adds `id` to its own SELECT list
- [ ] Confirm with the user whether vendor-name-as-category-evidence should stay unconditional or require a real line-item/tag backing it up — **still open**. Built as unconditional (the current behaviour, and what the persona block states); no user decision has been taken
- [x] Add normalized/fuzzy vendor-name matching to `identify_invoices` (strip legal suffixes, case/whitespace-insensitive) — done in code as `normalize_entity_name()` + a deterministic retry. **Not added to `aggregate`**: an aggregate's WHERE clause is generated freely by the model and rewriting predicates inside generated SQL by regex is a mechanism this repo already tried and removed. A vendor-total question routed through `identify_invoices` first gets the normalized behaviour; one routed straight to `aggregate` does not, and that gap is real
- [x] When normalized matching surfaces more than one distinct-looking vendor candidate for the same name, route to `ask_clarifying_question` rather than auto-disambiguating via `tax_ids`/GSTIN — done structurally: the tool itself returns the clarification, keyed per named entity phrase so a two-entity comparison is not affected
- [x] Make `aggregate` group by currency (or ask) instead of silently summing `grand_total` across currencies — the prompt says group; the code verifies it against the tenant's real currencies under the same filter and returns `multi_currency` (figure withheld) when it was genuinely blended
- [x] Make `aggregate`/synthesis state or clarify the fiscal-vs-calendar-year assumption on ambiguous date ranges — deterministic detector (`detect_ambiguous_date_range()`), calendar-year assumption carried into the synthesis prompt
- [x] Write the skilled persona block (incl. reverse-charge GST, surfacing `sa_alerts`); add to planner + synthesis prompts — verbatim from the architecture doc, in both prompts, asserted by test
- [x] Re-wire the orchestrator against the reworked tools — six tools bound, `_ToolBox` rewired, loop shape unchanged
- [ ] **Decide which `status` values count toward "spend"** (aggregate rule 6) — still undecided. The prompt and every aggregate result now say so explicitly instead of pretending it is settled; soft-deleted rows are excluded nowhere today
- [x] **Bound `get_full_record`'s document context** — closed 2026-08-21 by measurement, not by assumption. `get_all_invoice_chunks()` had no size/count/threshold bound and cost a measured 15,977 tokens on an 11-page invoice (129,818-token synthesis prompt, ~8x a baseline turn); `bound_document_pages()` caps it at `MAX_FULL_RECORD_CHUNK_CHARS` keeping the first and last page and disclosing `pages_omitted`. Retrieval itself is unchanged — section 2's "every indexed page" still holds for what is *fetched*
- [x] **Stop re-fetching the same record inside one turn** — closed 2026-08-21. Live, the planner called `get_full_record` on the same id three times in every identify→fetch turn; `_act_node` now reuses the turn's own result for an identical call (UUID arguments canonicalised)
- [ ] **Decide whether `record.items` needs a bound too** — new, and open. On a 400-line invoice the record is 26,800 tokens, ~60% of a full-record fetch and now the largest single term in a large-invoice turn. Deliberately not decided here: truncating `items` trades token cost against the line-item and reconciliation questions this feature exists to answer, and that is a product decision with a real correctness cost either way
- [ ] **Decide what to do about clarify-instead-of-answer** — new, and open. Measured in both live runs: 3 of 11 questions end in a clarifying question having called no tool at all, including `rajesh_steel_cgst`, the case the earlier round cited as SAGE's flagship win. Cheap turns that answer nothing; any latency/cost budget for SAGE has to be set on answered questions, not on turns
- [~] Phase 3: regression suite, real-LLM verification, live tenant testing — **partly done**. Real-LLM verification happened 2026-08-21 (44 turns, `scripts/run_agent_eval.py`, numbers in `feature_21_architecture.md` B4), and it found two defects mocked tests could not. **Live tenant testing has not**: still seeded SQLite with fixture chunks, no live Postgres and no real Chroma embeddings. No default-on decision should be taken until that has run
