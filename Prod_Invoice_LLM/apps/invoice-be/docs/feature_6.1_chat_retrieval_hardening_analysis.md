# Feature 6.1 — SAGE chat retrieval hardening: enhancement analysis

**Status: analysis only, not a spec.** The founder decides which items become a
`feature_6.x` spec. Nothing here is implemented. Architect persona, 2026-09-03.

**Baseline confirmed before starting:** `4c40207` (Gap 413) is on `origin/master`
(`git branch -r --contains 4c40207` → `origin/master`; HEAD there is `e53aefc`).

**Trigger.** The founder's Phase 1–4 walkthrough of the chat pipeline (2026-09-03)
found the architecture sound on correctness — deterministic money
(`_computed_figures_block_for`, `services/document_comparison.py`), structural tenant
isolation (per-tenant Chroma collections, `tenant_id` predicate check), an SQL
generate/execute/repair loop — but behind current practice in six places. Gap 413
was the symptom: an invoice *attribute* ("discount amount") was treated as a
line-item *keyword*, the generated SQL filtered `item->>'description' LIKE
'%discount%'`, matched nothing, and the turn returned `NO_RECORDS_FOUND` as a
successful answer.

**Constraints that hold for every item below.** Hard rule 3 — no model decides a
figure. Hard rule 2 — "verified" means a recorded Postgres run. Every existing chat
test keeps passing. Tenant isolation never weakens. Feature 26's pre-route gate
(`_run_query_agent` L4014–4035: an `attachment_id` turn never reaches
`classify_query` or the cache) is untouched.

**Telemetry basis for the latency item, stated up front because it is thin.**
`chat_turn` events in `appi-invoicellm-dev`, last 30 days, **13 turns total**:

| route | turns | p50 LLM calls | p95 LLM calls | p50 latency | p95 latency | errors |
|---|---|---|---|---|---|---|
| SQL | 7 | 3 | 3 | 27.8 s | 89.2 s | 1 |
| cached | 4 | 0 | 0 | 1.3 s | 1.8 s | 4* |
| RAG | 1 | 2 | 2 | 16.0 s | — | 0 |
| CHAT | 1 | 2 | 2 | 7.9 s | — | 0 |

\* the four "cached" rows carry `status != success` — worth a look on its own, but
it is a telemetry-labelling question, not a retrieval one, and is out of scope here.
Seven SQL turns is not a distribution; every latency claim below is a bound, not
a measurement.

---

## Item 1 — SQL knowledge: rules → structure

### What exists today

`build_sql_system_prompt` (`agents/query_agent.py:2707`) assembles, in order:
`CHAT_PERSONA_BLOCK` → schema block (`_HAND_TYPED_SCHEMA_BLOCK` + `_derived_schema_supplement()`, Gap 413) →
**16 numbered rules** (1, 2, 3, 4, 4a, 5, 6, 6a, 6b, 6c, 7, 8, 8a, 9, 10, 11) →
`{line_item_rule}` (rule 6d, built per dialect by `_line_item_rule`, L1089) →
three deterministic grounding blocks — `_tax_term_block_for` (L2122),
`_payment_status_block_for` (L2181), `_attribute_term_block_for` (L2157) →
prior-turn SQL → tenant stats → history.

Which gap added or last changed each rule, from the tracker lines that name it:

| Rule | Subject | Gaps |
|---|---|---|
| 1, 2 | tenant predicate, read-only | original |
| 3 | audit status lives in `status`/`sa_alerts` | 294, 306, 315 |
| 4 / 4a | flow direction from phrasing / named entity | 126, 270, 298 |
| 5 | combined-direction questions | — |
| 6 | tags / items JSON | — |
| 6a | vendor filters never `=` | 238, 268 |
| 6b | category questions, one shape | 253, 271, 306 |
| 6c | never decompose a category phrase | — |
| **6d** | line-item extraction, per dialect | **253, 255, 271, 273, 287, 294, 306, 310, 315, 413** |
| 7 | always select `currency` | 313 |
| 8 / 8a | when to return null SQL | 313 |
| 9 | narrowing follow-ups reuse prior WHERE | 253, 276 |
| 10 | two-entity comparisons | 268 |
| 11 | "details" questions select a person's columns | 274 |
| tax block | Gap 263 → 310 | |
| payment block | Gap 267 | |
| attribute block | Gap 413 | |

Rule 6d alone has been amended by **ten gaps**. That is the measurement that
matters: it is the rule that decides *what a word in the question is* — a thing you
buy, or a property of the invoice — and every amendment has been a new prose
exception for a class the previous prose missed. Gap 413's own detector is already
the structural version of one of those exceptions.

### Proposed change

A deterministic **schema-linking step before generation**, whose output is handed
to the model as facts rather than as rules to apply:

1. **Term → column linking.** `detect_invoice_attribute_term()` and
   `detect_tax_component_term()` already exist and are ORM-derived. Add the third
   member: a small **named-metric layer** defined once in code —
   `spend` (Σ `grand_total` by direction), `tax` (`tax_amount`), `outstanding`
   (`due_date` past and not paid), `subtotal`, `discount` — each mapped to the
   exact column expression. The linking step emits a block like *"linked:
   'discount amount' → `discount_amount`; entity: vendor 'apex consulting group';
   no product phrase found"*.
2. **Invert rule 6d's default.** Today: product phrase + money word ⇒ line-item
   join. Proposed: line-item description search is the **fallback when no column
   links**, and only when a free-text phrase remains after linking. The
   attribute/tax exemptions stop being exceptions and become the main path.
3. **Retrieved few-shot examples.** A curated question → SQL set, retrieved per
   query by embedding similarity (bge-m3 is already loaded), 3–5 examples in the
   prompt. **Seed reality check:** the Feature 13 golden sample
   (`benchmarks/agent_eval_golden_sample.py`) has **35 `GoldenCase`s with
   `question` and `expected_answer` but no SQL field** — the seed needs SQL
   written for each, which is a functional-tester task of ~1 day on its own.

The NL2SQL Handbook (HKUSTDial) frames exactly this split: schema linking and
demonstration retrieval under *Pre-Processing* ("Knapsack Optimization-based
Schema Linking", "OpenSearch-SQL … Dynamic Few-shot", "SchemaRAG"), execution
feedback and verification under *Post-Processing*. This repo already has the
post-processing half (repair loop, zero-row nets); it has none of the
pre-processing half except the two detectors Gaps 310/413 added ad hoc.

### What becomes deletable once this exists

Rules **6** (items JSON), **6d**'s main body, the tax exemption paragraph and the
attribute exemption paragraph inside 6d, and the two grounding blocks they feed —
because the linking output *is* the grounding. Rules **7** and **11** shrink to
one line each (the named-metric layer carries `currency`; the "details" column
set becomes a named projection). Rules 1, 2, 4/4a, 5, 6a–6c, 8/8a, 9, 10 stay:
they are about direction, categories, follow-ups and refusal, not about what a
word means. Honest count: **~40% of the prompt's rule text**, and — more
importantly — the *class* of gap that has amended 6d ten times.

### Size

BE ~3 days (linking step + metric layer + prompt restructure + example retrieval),
functional-tester ~1 day to write SQL for the 35 seed cases, plus a Postgres
benchmark run before/after. **~4.5 days.**

### Risks and what must NOT change

- **Gap 226 precedent:** a prompt change passed the mocked suite and regressed
  live. The proving evidence is the Feature 13 benchmark on Postgres, not
  `test_chat_sql_quality.py`.
- The inverted default must not lose the genuine line-item case rule 6d was
  written for ("the amount only for training and onboarding"). The linking step's
  "no column linked, free-text phrase remains" branch is that case; it needs its
  own test.
- `_full_record_block_for` and `_computed_figures_block_for` are untouched — they
  are the hard-rule-3 mechanism and are downstream of this.
- Few-shot examples are **retrieved text the model sees**: they must come from the
  curated set only, never from a tenant's prior turns (cross-tenant leakage by
  example).

### Test that proves it

`benchmarks/agent_eval_golden_sample.py` on Postgres, before and after, same 35
cases: pass count must not drop, and the new attribute/metric cases (discount,
subtotal, outstanding, tax component) must pass. Plus a unit test that
`"the amount only for training and onboarding"` still links to *no* column and
still produces the line-item join.

---

## Item 2 — Tenant guard: regex → AST

### What exists today

`execute_generated_sql` (`agents/query_agent.py:1323`):

- strips fences, runs `_normalize_string_equality` (L1335), then
- forbids `mutating = ["insert","update","delete","drop","alter","create","replace","truncate"]` by `\bword\b` regex on the lowered text (L1341–1343),
- requires `sql_lower.startswith("select")` (L1346),
- asserts the tenant predicate with
  `rf"\btenant_id\s*=\s*['\"]?{tenant_id}['\"]?\b"` (L1351–1353).

`_normalize_string_equality` (L323–387) rewrites `column = 'v'`, `column IN (...)`
and `column LIKE '...'` to `TRIM(LOWER(...))` forms with three compiled regexes
per column (L354, L372, L377). Gap 253 already retired one regex rewriter on this
route (the execution-time dialect rewriter) after it corrupted SQL.

**sqlglot is not installed** (absent from `pyproject.toml` and `uv.lock`).

### Empirical probe (run 2026-09-03 under `uvx --from sqlglot`, v30.17.0)

Parsing the **verbatim Gap 413 query** — `LEFT JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(items) = 'array' …) AS item ON true`, `item->>'description'`, `(…)::numeric`, `TRIM(LOWER(…)) LIKE LOWER(…)` — as `dialect="postgres"`:

| Check | Result |
|---|---|
| Parses | yes, root `exp.Select` |
| `tenant_id` predicate located on the AST | `exp.EQ` with `exp.Column("tenant_id")` under the **top-level** `WHERE` |
| LATERAL join | represented as `exp.Lateral` |
| `jsonb_array_elements`, `jsonb_typeof` | `exp.Anonymous` (unknown function, preserved verbatim) |
| `->>` | `exp.JSONExtractScalar` ×4 |
| `::numeric`, `::jsonb` | `exp.Cast` to `DECIMAL`, `JSONB` |
| DML anywhere | none found by `find_all(exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)` |
| AST case-insensitivity rewrite | `.transform()` produced `WHERE LOWER(vendor_name) = LOWER('Acme') AND status IN ('A','B')` — `IN` untouched, as intended |
| **Hostile:** `WHERE tenant_id = 't1' OR 1=1` | **regex guard passes** (the literal is present); on the AST the top-level `WHERE` node is `exp.Or`, which an AST guard rejects |
| Transpile to SQLite | emits `LEFT JOIN LATERAL JSONB_ARRAY_ELEMENTS(…)` — **invalid SQLite**. sqlglot does not translate Postgres JSON un-nesting to `json_each` |

Two conclusions follow. First, the AST guard is strictly stronger than the regex:
it can require the tenant predicate to be a **conjunct of the top-level WHERE**,
not merely present somewhere in the text, and it detects DML structurally rather
than by word (`Invoice.created_at` contains "create" — Gap 32's false positive
goes away). Second, **sqlglot does not replace `_line_item_rule`'s per-dialect
prompt**: the SQLite path still needs its own `json_each` spelling generated at
prompt time. The proposal is a guard and a rewriter, not a transpiler.

### Proposed change

1. Add `sqlglot` (MIT, pure Python, optional C extension) as a dependency.
2. `execute_generated_sql`: parse with `dialect=_sql_dialect_name(db_session)`;
   reject if the root is not `exp.Select`, if any DML/DDL node exists, or if the
   `tenant_id = '<caller>'` `exp.EQ` is not reachable from the top-level `WHERE`
   through `exp.And` nodes only. **Keep the regex checks as a second, independent
   layer** — two guards is the right number for tenant isolation, and the regex
   is free.
3. Alternative to verifying: **wrap** — `SELECT * FROM (<generated>) AS q WHERE
   tenant_id = :tenant`. Simpler and unconditional, but it changes the result
   shape (aggregates lose the column) and would need every generated query to
   project `tenant_id`. Verification is the better fit for this route; wrapping
   suits a future API-key route.
4. Move `_normalize_string_equality` onto the AST: `transform()` on `exp.EQ` /
   `exp.In` / `exp.Like` whose left side is a substring-fuzzy column. Regenerate
   with `.sql(dialect=…)`.
5. On any parse failure: **fail closed** (reject the query, feed the error to the
   repair loop) — never fall back to executing unparsed text.

### Size

BE ~1.5 days including a Postgres run of every SQL-route test and the benchmark.

### Risks and what must NOT change

- Parse failure on a legitimate query would turn a working turn into a repair
  attempt. sqlglot's parser is "intentionally lenient" and the probe parsed the
  hardest shape this route emits, but the benchmark must run before/after.
- `.sql()` regeneration must not reformat in a way that changes semantics
  (quoting, `LATERAL` placement). Compare regenerated vs original on the 35 cases.
- The regex guard **stays**. Removing a working isolation check to replace it with
  a new one is the wrong order; add, prove, then decide.
- `_sql_dialect_name` and the per-dialect rule 6d stay — see the transpile result.

### Test that proves it

A parametrised test of hostile shapes the regex passes and the AST rejects:
`… OR 1=1`, tenant predicate inside a subquery only, tenant predicate on the
wrong side of a `UNION`, a comment-smuggled `; DROP`. Plus the existing
`test_chat_sql_quality.py` suite unchanged, and the benchmark on Postgres.

---

## Item 3 — Retrieval quality

### What exists today

- **Chunking** — `chroma_client.index_invoice_document` (L464): one chunk per PDF
  page, `header = f"[Vendor: {vendor} | Document ID: {invoice_id} | Page {n}]\n"`
  prepended (L503), **no overlap**, id `f"{invoice_id}_page_{n}"`. The line-item
  table and the totals block land in whichever page they fall on, mixed with
  everything else on that page.
- **Retrieval** — `query_invoice_chunks` (L854): bge-m3 embedding, cosine, `n_results = limit×3 = 15`, hybrid rerank `combined_score = vec_dist − 0.1 × keyword_hits` (L915), cutoff `RELEVANCE_DISTANCE_THRESHOLD = 0.49` plus `min(2, len(keywords))` keyword hits (L933), top 5 returned.
- **0.49 is empirical**, not intuitive (L31–57): derived 2026-08-17 from the 8-turn NovaTech set as the midpoint of `[0.4749, 0.5062]` — the widest margin that still separates "found the right invoice" from "honestly nothing for a category the tenant lacks". One genuine match (CMC-330217 at 0.5331) is knowingly excluded.
- **Cold start** — `warm_rag_dependencies` (L274, Gap 278) primes Chroma and the bge-m3 singleton at boot; the tracker records 177 s and 40 s first-request stalls before it existed.

### Proposed change

**(a) Structure-aware chunking.** Emit, per invoice, three chunk kinds with the same header: `page` (as today), `line_items` (the extracted `items` rendered as one table-text block), `totals` (subtotal / tax / discount / grand total / terms). The extraction already produces the structured fields; this is re-rendering them for the index, not new parsing. The arXiv text-and-table benchmark (2604.01733) reports "table structure mismatch is the dominant failure mode (73%)" — "the answer resides in a table whose markdown representation does not embed well as continuous text" — which is precisely the invoice line-item case. Same paper: "avoid HyDE for domains with precise numerical or entity-centric queries" — noted so nobody proposes it.

**(b) Hybrid BM25 + dense, fused by RRF.** Replace the `−0.1×hits` heuristic with a real sparse index (BM25 over the chunk text, in-process — `rank_bm25` or Chroma's own sparse support if adopted) and Reciprocal Rank Fusion, `score(d) = Σ 1/(k + rank(d))`, **k = 60** (denser.ai 2026 guide: "default 60 in Elasticsearch and most implementations", from Cormack et al. 2009; k = 30–40 "favors top-1 precision"). Candidate lists: top-20 from each side (the guide's 50–500 is for corpora far larger than one tenant's invoices).

**(c) Cross-encoder reranker** over the fused top-20: `BAAI/bge-reranker-v2-m3` (same BAAI family and MIT-style posture as bge-m3; open-source, self-hostable — the denser.ai guide lists "bge-reranker-v2 (8K context)"). Return top 5. The 2604.01733 benchmark's headline is that "reranking is the single most impactful component" — "+12.1pp Recall@5 over unreranked hybrid retrieval" (Hybrid RRF 0.695 → Hybrid + rerank 0.816).

**bge-m3 itself stays.**

### The 0.49 threshold under RRF — this is the part that needs a decision

RRF scores are **rank-based**, bounded roughly by `n/(k+1)`; they carry no distance semantics. The denser.ai guide "does not discuss relevance cutoff thresholds for RRF scores" at all. So the 0.49 cutoff cannot be applied *after* fusion. Two options, one recommended:

- **Recommended: apply 0.49 to the dense side before fusion.** The dense candidate list is filtered by cosine distance exactly as today; BM25 candidates that the dense side did not admit can still enter via fusion only if they also pass a BM25 floor. The semantics of 0.49 — "is there anything in this tenant's documents about this at all" — is preserved where it was derived, and an empty dense list still means "nothing" (the Gap 244 honesty property).
- Alternative: use the **reranker's own score** as the cutoff, re-derived by the same 8-turn method. Cleaner long-term, but it re-opens a threshold that was measured once and needs the measurement repeated on a bigger set.

### Size

(a) ~1 day incl. a re-index of dev; (b) ~1.5 days; (c) ~1 day + warm-up work. **~3.5 days**, plus a re-derivation run of the threshold on Postgres + Chroma.

### Risks and what must NOT change

- **Cold start doubles.** A second ~560 MB model must be added to `warm_rag_dependencies` and to the readiness probe, or Gap 278's 177 s stall returns for the first RAG turn. Memory on `ca-invoice-be-dev` must be checked against the module's limits.
- Reranking adds latency ("100–300 ms … per query", denser.ai) — negligible against 16 s RAG turns.
- The re-index changes chunk ids; `delete_invoice_chunks`/`has_invoice_chunks` (Gap 239) key on `invoice_id` metadata, not on chunk id, so they survive — verify, do not assume.
- `_wrap_retrieved_document_text` markers and the Gap 239 citation-existence check are downstream and unchanged.

### Test that proves it

Re-run the Gap 244 8-turn derivation set plus the 35 golden cases that route RAG, on Postgres + real Chroma, before/after: Recall@5 of the correct `invoice_id` and the false-positive rate on "category the tenant lacks" questions. Both numbers recorded in `docs/test_evidence/`.

---

## Item 4 — Routing: exclusive → fan-out

### What exists today

`classify_query` (`agents/query_agent.py:211`) returns exactly one of `SQL` / `RAG` / `CHAT`. Keyword pass first: **15 `_SQL_KEYWORDS`** (`total`, `spent`, `sum`, `average`, `how many`, `count`, …) → `SQL`; **5 `_CHAT_KEYWORDS`** (`hello`, `hi `, …) → `CHAT`; there is **no `_RAG_KEYWORDS`** — RAG is reached only through the LLM router (`with_structured_output(QueryRoutingSchema)`, L250–272). Gap 182's tradeoff is written in the docstring: the keyword pass is coarser than the LLM router, and "vendor" is an SQL keyword.

Chroma: every chunk carries `invoice_id` metadata (L509); `.get(where={"invoice_id": …})` is used at L796/L826; `collection.query` at L878 takes **no `where`** today. Chroma's docs confirm `query` accepts `where` with `$in` / `$and` / `$or` — filtering *before* or *after* the ANN search is not documented, so the performance shape needs one measurement.

### Proposed change

A fourth route, `SQL+RAG`, with a **deterministic trigger** — no LLM decides it:

> trigger ⇔ (column-linking hit **or** an entity predicate — vendor / customer / invoice number / date) **and** a free-text term that links to no column and is not a category phrase.

"Invoices from Acme that mention warranty": entity = Acme (SQL identifies ids), free-text = "warranty" (RAG over those ids only). Execution: run the SQL route to obtain `result_invoice_ids`, then
`query_invoice_chunks(…, where={"invoice_id": {"$in": ids}})`, then one narration
with both the rows and the chunks. The item-1 linking step is the natural source
of the trigger; this item is small once item 1 exists and awkward before it.

### Size

~1.5 days after item 1 (trigger + `where` plumbing + one combined narration + tests). ~2.5 days standalone (a cut-down linker just for the trigger).

### Risks and what must NOT change

- Over-triggering sends ordinary SQL questions through an extra retrieval and a longer prompt. The trigger must require a *residual* free-text term after linking, not merely any noun.
- Two sources in one narration is where a model can blend a figure from the chunk with one from the rows. **Hard rule 3:** figures come only from `db_result` / `_computed_figures_block_for`; chunk text is for the textual question only, and the narration prompt must say so.
- The pre-route attachment gate is upstream and untouched; `classify_query` keeps returning one of three values — `SQL+RAG` is decided after it, from the linking output.

### Test that proves it

A parametrised trigger test (fires / does not fire) on ~20 phrasings; an integration test on Postgres + Chroma that "invoices from Acme that mention warranty" returns only Acme's `invoice_id`s in citations and a `grand_total` that matches the SQL rows; and a test that a pure aggregate ("total spend last month") does **not** trigger.

---

## Item 5 — Answer cache correctness

### What exists today

`get_cached_answer` (`agents/query_agent.py:142`), key `chat_answer_cache:{tenant}:{normalised}` where `_normalize_query` is whitespace-collapse + lowercase (L134), TTL `CACHE_TTL_SECONDS = 3600` (L107). Checked at `_run_query_agent` **L4045** — after the attachment gate (L4035) and **before** `classify_query` (L4097) and before `_is_narrowing_followup` is consulted.

**F26 B1 bypass confirmed intact:** an `attachment_id` turn returns from `_run_attached_document_turn` at L4035, and the docstring at L4030 says the cache is "deliberately bypassed too". Verified by reading, and by `test_chat_attachments.py`'s gate tests.

The defect this creates: "which of those are overdue" asked in two different sessions, after two different first questions, hits the **same** cache key and the second user gets the first user's narrowed answer. Same tenant, so not a leak — but a wrong answer served as a cached right one, and served fast, which makes it convincing.

### Proposed change

1. Skip the cache read **and write** when `_is_narrowing_followup(user_message)` fires (the `_FOLLOWUP_BACKREF_PATTERNS`: "those 3", "explain them", "the … ones").
2. Skip both when the message references prior context by other means — a bare pronoun subject ("what about its tax"), or when `get_prior_turn_sql` is non-null **and** rule 9 would apply. The narrowing detector already exists; extend it rather than add a second.
3. For follow-ups that are still worth caching, key on `(tenant, session, normalised)` — a session-scoped entry. Same TTL.
4. Move the check to **after** `classify_query`'s keyword pass? No — the cache exists to avoid that LLM call. Keep it before; just gate it on the deterministic follow-up test, which is free.

### Size

~0.5 day, including a Postgres-backed test with Redis.

### Risks and what must NOT change

- The attachment bypass stays exactly where it is (L4030–4035), ahead of the cache.
- Cache invalidation on trainer-rule commits (`_invalidate_chat_answer_cache`, `routers/chat.py:40`) keys on the tenant prefix and is unaffected by a session dimension as long as the prefix is unchanged.
- Don't widen "references prior context" into an LLM judgement — that would reintroduce a model deciding whether to trust a cached figure.

### Test that proves it

Two sessions, same tenant: session A asks "invoices over 1000" then "which of those are overdue"; session B asks "invoices from Acme" then the same follow-up. Assert session B's answer is computed, not A's cached one; assert `set_cached_answer` was not called for either follow-up; assert an attachment turn never calls `get_cached_answer`. On Postgres + Redis.

---

## Item 6 — Latency: 3–4 LLM calls per SQL turn

### What exists today

Per SQL turn: `classify_query` (LLM only when no keyword matches) → `run_sql_generation_loop` (1 generation + up to 2 repairs, `max_attempts=3`) → summary `llm.invoke`. Measured (table at top): SQL turns **p50 = 3 calls, 27.8 s; p95 = 89 s**, over seven turns. The 89 s turn is almost certainly a repair loop; the 28 s median is three sequential calls to `gpt-5-mini` at ~9 s each, which is the model, not the code.

### Proposed change

1. **Merge route + generate** when the keyword pass already chose SQL: skip nothing today, because on a keyword hit there is no routing LLM call already. The merge only pays when the keyword pass *misses* and the LLM router runs — then one structured call can return `{route, sql}` together. Saves one call on the LLM-routed minority; saves nothing on the keyword-routed majority. Honest value: small.
2. **Faster deployment for the summary call.** The summary step formats rows it is handed; it decides no figure (hard rule 3 is enforced by `_computed_figures_block_for`, not by the summariser's model quality). A smaller/faster Azure deployment for that one call is the biggest single latency win available — roughly one third of the median turn — with the least accuracy exposure, because the arithmetic is already done before the model runs.
3. **Do not** reduce `max_attempts`; the repair loop is what turns a bad first generation into an answer, and p95 is where it earns its keep.

### Size

(1) ~0.5 day. (2) ~0.5 day BE + a bicep/param for the second deployment name + the eval harness's candidate-model override (`build_llm(model=…)` already exists for exactly this). **~1 day.**

### Risks — the accuracy question, stated per change

- (1) A merged call asks one generation to do two jobs; the routing reasoning field is what catches "this is really RAG" — dropping it risks more SQL-route zero-rows, which is the failure this whole analysis is about. Only do it with the item-1 linking output in the prompt, which makes the route nearly deterministic anyway.
- (2) A weaker summariser can mis-read a row (wrong currency on a figure, wrong row labelled). Mitigation exists already: the `line_item_total_instruction` template and `_computed_figures_block_for` hand it pre-formatted facts. Prove with the Feature 13 benchmark's faithfulness judge on the summary output only.
- Measure before acting: seven turns cannot show a p95 improvement. Turn on the flags in dev, collect ≥100 turns, then decide. The instrumentation exists (`llm_call_count`, `latency_ms` per `chat_turn`).

### Test that proves it

Benchmark faithfulness score on the summary step, same 35 cases, `gpt-5-mini` vs the candidate deployment, on Postgres; and a telemetry query showing p50/p95 latency per route over ≥100 turns before/after.

---

## Item 7 (founder addition, 2026-09-03) — zero rows is a diagnosis, never an answer

Not one of the six, but the founder's review produced it and it interacts with items 1, 3 and 4, so it is ranked with them.

### What exists today

`execute_generated_sql` returns the sentinel `NO_RECORDS_FOUND = "No records found matching the query criteria."` (L1116) and the summary narrates it. Two deterministic nets exist — `lookup_invoice_by_number_fallback` (L392, exact invoice-number miss) and `recover_missed_category_match` (L661, category phrase miss). **No vendor-name recovery exists**; `_normalize_string_equality` gives case/substring tolerance only (Gap 238). No fallback to the vector store on a SQL miss.

### Proposed flow, deterministic throughout

| Step | Function (new) | Rule |
|---|---|---|
| 1 | `_diagnose_zero_rows(sql)` | Split WHERE into identifying (vendor/customer/number/PO/date) vs narrowing (description, status, amount) predicates — on the AST once item 2 lands, on text until then |
| 2 | `_probe_identifiers()` | Re-run identifying predicates only. Rows ⇒ narrowing was wrong → drop it → `_full_record_block_for` answers. No identifiers in the question ⇒ skip to 3 |
| 3 | vector probe | `query_invoice_chunks(user_message)`; chunks above threshold ⇒ answer from documents with citations; chunk `vendor_name` metadata feeds step 4 |
| 4 | `_nearest_entity_names()` | `difflib` over the tenant's distinct vendor/customer names (one `SELECT DISTINCT`, cached per turn). ≥ 0.85 and unambiguous ⇒ auto-correct and say so; several ⇒ clarify with options (reuse the `attachment_clarification` wire shape, H16) |
| 5 | ask back | "No vendor resembles X and nothing in your documents mentions it — check the spelling or give me an invoice number?" |
| 6 | telemetry | `zero_result_diagnosis ∈ {narrowing_dropped, auto_corrected, vector_answered, clarified, no_candidates}` |

Order matters: the identifier probe precedes the vector probe so a question with a precise stored answer is answered from the row, never narrated from OCR text. Clarification is last because every clarifying turn costs the user a round-trip.

### Size

~1.5 days BE with Postgres tests, ~0.5 day FE to render the clarification on the SQL route (the component exists). Two gaps: this net, and the upstream keyword-router over-routing that item 4's trigger also addresses.

### Risks and what must NOT change

Hard rule 3: the vector probe answers the *textual* question; it never supplies a money figure the SQL could not find — that is what step 2's full-record path is for. Scope of the vector probe is `invoice_chunks_{tenant}` only in v1 (not `docs_`, not `chat_docs_`).

### Test that proves it

On Postgres: "discount amount for apex consultng grp" (typo) → auto-corrected, answer from the full record, `zero_result_diagnosis = auto_corrected`; "what does the vendor's contract say about penalties" (mis-routed to SQL) → `vector_answered` with citations; "invoices from Zzyzx Ltd" (no such vendor, nothing in documents) → clarification payload, never the sentinel.

---

## Ranking by value ÷ cost

| Rank | Item | Value | Cost | Why here |
|---|---|---|---|---|
| **1** | **7 — zero rows is a diagnosis** | High: converts every silent miss into a recovery or a question; the founder's stated principle | 2 days | Highest value per day; covers typos and mis-routing that no other item touches; testable end to end |
| **2** | **5 — cache correctness** | Medium-high: a wrong answer served fast is worse than a slow right one | 0.5 day | Cheapest item on the list; a real defect, not a refinement |
| **3** | **2 — AST tenant guard** | High on the one axis that cannot be allowed to fail; the probe showed a hostile shape the regex passes | 1.5 days | Strictly additive (regex stays); also gives item 7 its predicate parser and retires the regex-rewrite class Gap 253 already bit on |
| **4** | **1 — rules → structure** | Highest long-run: retires the class of gap that amended rule 6d ten times | 4.5 days | Largest and the one with the Gap 226 regression precedent; do after 2 and 7 so its tests have an AST and a zero-row net beneath them |
| **5** | **3 — retrieval quality** | Medium: real Recall gains in the literature, but RAG is 1 of 13 turns in the last 30 days | 3.5 days + threshold re-derivation | Value is certain, urgency is not; the cold-start and threshold questions need answers first |
| **6** | **4 — SQL+RAG fan-out** | Medium, for a question shape nobody has asked yet in telemetry | 1.5 days after item 1 | Cheap *after* item 1, awkward before; sequence it there |
| **7** | **6 — latency** | Low until measured: seven turns, and the median is three model round-trips, not code | 1 day | Do (2) — the summariser deployment — when there are 100 turns to compare against; skip (1) unless item 1 lands |

**Suggested order if all are approved:** 7 → 5 → 2 → 1 → 4 → 3 → 6.

---

## Sources actually opened

- HKUSTDial, *NL2SQL Handbook* — https://github.com/HKUSTDial/NL2SQL_Handbook (Pre-Processing: schema linking, few-shot retrieval; Post-Processing: execution feedback, verification).
- tobymao, *sqlglot* README — https://github.com/tobymao/sqlglot (dialects incl. Postgres and SQLite; `parse_one`, `find_all`, `transform`, `.sql(dialect=…)`; MIT, pure Python). Plus the empirical probe recorded in item 2 (v30.17.0).
- Denser.ai, *Hybrid Search for RAG: Combining BM25 and Dense Vector Search (2026 Guide)* — https://denser.ai/blog/hybrid-search-for-rag/ (RRF formula, k = 60, candidate sizes, reranker latency, bge-reranker-v2).
- *From BM25 to Corrective RAG: Benchmarking Retrieval Strategies for Text-and-Table Documents* — https://arxiv.org/html/2604.01733v1 (hybrid + rerank +12.1pp Recall@5; table-structure mismatch 73% of failures; avoid HyDE for numeric queries).
- Chroma docs, *Metadata filtering* — https://docs.trychroma.com/docs/querying-collections/metadata-filtering (`where` on `query`; `$in`, `$and`, `$or`).

Not opened, therefore not cited: the digitalapplied.com reference and the other arXiv results the search returned.

---

# §Founder recommendation and proposed execution order

Architect review of the founder's nine-item recommendation (2026-09-03). Docs only.
Every disagreement below carries a `file:line`, a measured number, or an opened
source. Sizes are working days. Additional sources opened for this section:
Azure OpenAI *reasoning models* (learn.microsoft.com/…/openai/how-to/reasoning,
2026-08-20) and *prompt caching* (…/openai/how-to/prompt-caching, 2026-08-11);
installed `langchain-openai` 1.3.3 source; `az cognitiveservices account
deployment list` on `openai-invoicellm-dev`.

## Caveat on the data — challenged, with evidence

The nine turns did **not** come from a local session. They are Azure:

- They were read from App Insights resource `appi-invoicellm-dev` (`customEvents`
  where `name == 'chat_turn'`), and the same window has matching `requests` rows
  for `POST /api/v1/chat/sessions/{session_id}/message` (n = 5, p50 789 ms) and
  `GET /api/v1/chat/jobs/{job_id}/stream` (n = 4, p50 28.8 s) — server-side
  request records that only the Container App emits.
- They ran on revision `ca-invoice-be-dev--0000117` (created 04:22 UTC; turns
  05:01–05:07 UTC).
- Local Postgres was **refused** (`localhost:5433`, error 10061) for the entire
  measurement window, so no local turn could have produced telemetry at all.

So the requested "run the same nine against the dev Container App" is already
the dataset. There is no second environment to compare, and the questions
themselves cannot be re-run by the architect: `chat_turn` does not carry message
text, and the `ChatMessage` rows sit in dev Postgres behind the API. **The real
caveat is sample size** — nine turns from one session, one tenant, one hour. The
before/after for every Block A item is therefore the founder re-asking the same
nine questions in dev (they are in that session's history) plus the 35-case
golden set; the analysis does not build on the nine alone.

## Block A — config and prompt-shape

### A1. SQL generation: `reasoning_effort="low"` + a completion cap — **confirmed, with two corrections**

**Evidence.** gpt-5-mini (2025-08-07) supports `reasoning_effort` with `minimal`,
`low`, `medium`, `high` — the reasoning doc's GPT-5 support table marks it ✅, and
its feature note says *"`minimal` is only supported with the original GPT-5
reasoning models"*, which this is. `none` is **not** available on gpt-5-mini
(footnote 7 lists gpt-5.1 and later). Reasoning tokens *"are billed as output
tokens"* and *"never appear in the message content"* — which is what the 1,688
p50 output tokens for a ~100-token SELECT are (`llm_agent_call`,
`chat.sql_generation`). The LangChain in use passes both through:
`reasoning_effort: str | None` is a constructor field
(`langchain_openai/chat_models/base.py:748`), and `max_tokens` is aliased to
`max_completion_tokens` and remapped at request time
(`chat_models/azure.py:574`, `:742`) — so `build_llm(max_tokens=…)` already sends
the right parameter name. Structured Outputs on gpt-5-mini: ✅ in the same table.

**Correction 1 — the cap.** 2,048 is too low. The cap *"cover[s] reasoning tokens,
visible output tokens, and formatting tokens"* (reasoning doc), p50 output is
already 1,688 at the default effort, and the one declined turn averaged ~3,450
per attempt (10,354 / 3). A request that runs out *"can occur before the model
produces any visible output. You pay for input and reasoning tokens but receive
no answer."* — i.e. a hard cap turns a slow success into an empty SQL and a
repair attempt. Set **4,096** with `low`; only lower it after
`completion_tokens_details.reasoning_tokens` has been recorded per call (not
captured today — `telemetry.py:1473–1476` reads `prompt_tokens`/`completion_tokens`
only; add it in B1).

**Correction 2 — the A/B.** `minimal` disables parallel tool calls (footnote 1),
irrelevant here (single structured call), so include it. The non-reasoning arm
can only be `gpt-4o` (see A2's capacity note). Report per arm: golden-set pass
count, p50/p95 latency, reasoning tokens, output tokens.

**Size** 0.5 d code + 1 d golden runs (3 arms). **Test:** golden set on Postgres,
per arm, recorded in `docs/test_evidence/`; pick by accuracy first. **Must not
change:** `SQLGenerationSchema`, the repair loop, `execute_generated_sql`.

### A2. Classify / summary / RAG / attachment narration → fast non-reasoning deployment — **confirmed in principle; one hard constraint**

**Evidence.** The dev resource `openai-invoicellm-dev` has exactly two deployments:
`gpt-5-mini` (2025-08-07, GlobalStandard, **capacity 300**) and `gpt-4o`
(2024-11-20, GlobalStandard, **capacity 10**). There is no gpt-4o-mini or
gpt-4.1-mini. Per turn these four call sites consume ≈ 268 + 1,947 + 2,809 input
tokens (`chat.classify`, `chat.sql_summary`, `chat.rag_answer`; attachment
narration unmeasured) ≈ 5 k tokens — at 10 K TPM that is **two turns per minute
before 429s**. So A2 is gated on either raising `gpt-4o` capacity or creating a
smaller deployment; that is a resource change, not code.

Structured output for classify (`with_structured_output(QueryRoutingSchema)`):
gpt-4o 2024-11-20 is a post-2024-08-06 snapshot and the deployment exists, but I
did not open a source that lists gpt-4o structured-output support, so **verify on
the first golden run** rather than assume. `build_llm(model=…)` already accepts a
per-call deployment override (`utils/llm.py`), so the code change is a parameter
at four call sites (`query_agent.py:248, 3599, 3867, 4142`).

**Size** 0.5 d + deployment capacity. **Test:** golden set with judge faithfulness
on the summary; classify agreement vs gpt-5-mini on the 35 questions. **Must not
change:** `_computed_figures_block_for` / `_full_record_block_for` — they are why a
weaker summariser is safe; F26 narration's "no figure not in the diff table" rule.

### A3. Stream summary and narration — **confirmed, value bounded by the numbers**

**Evidence.** The summary emits **258 output tokens (p50)** and takes 3.6 s p50 /
12.8 s p95. Streaming changes *perceived* latency by at most that call's duration
minus time-to-first-token; it changes total latency by zero, and the generation
call (15.6 s) cannot be streamed usefully because it is a structured-output SELECT.

**What changes.** `query_agent.py:4114` (`llm.invoke(summary_prompt)`) and `:4466`
(RAG) become `llm.stream(...)` accumulating chunks. Sync path:
`routers/chat.py::run_sync_chat_turn` returns one `MessageResponse` after
completion (L646) — streaming there means a new streaming response on the sync
route, or routing all turns through the async path. Async path: the worker's
`on_progress` → `ChatQueueService.publish_progress` (`handlers.py:~1515`) gains a
`partial_content` field; `stream_chat_job` already relays events — but **without
Redis in dev the pub/sub path is inert and the Redis-status poll runs every
1.5 s** (`routers/chat.py:896`), so a 3.6 s summary would arrive as ≤ 2 partial
updates. FE: `useChatSession.ts::attachJobListener` renders `details.message`
today; it would append `partial_content` to the placeholder bubble.

**Size** 1.5 d BE + FE. **Test:** Playwright asserts the bubble grows before
`status: completed`; the persisted `ChatMessage.content` equals the final text.
**Must not change:** partials are never persisted; `extract_attachment_payload`
runs on the completed output only.

### A4. Prompt caching by reordering — **confirmed, with a correction to what is "static"**

**Evidence (prompt-caching doc).** *"A minimum of 1,024 tokens … The first 1,024
tokens in the prompt must be identical"*; hits *"occur in 128-token increments"*
on models before GPT-5.6; *"All Azure OpenAI models GPT-4o or newer support
in-memory prompt cache retention"* (cleared after 5–10 min idle); hits appear as
`prompt_tokens_details.cached_tokens`; *"Prompt caching is enabled by default"*;
*"Structured output schema is appended as a prefix to the system message"* (so
the schema does not break the prefix). `gpt-5-mini` is not in the *extended*
(24 h) retention list; in-memory applies.

**Correction.** The three grounding notes (`_tax_term_block_for`,
`_attribute_term_block_for`, `_payment_status_block_for`) are **per-question**, not
static — they must go to the dynamic tail, not the static head. Today they sit at
prompt lines 2771–2774, between rule 6c and rule 7, so the identical prefix
already runs persona (947) + schema (743) + rules 1–6c + rule 6d (1,734) ≈
**5,400 tokens** before the first dynamic byte — caching is very likely already
hitting on gpt-5-mini today, unmeasured. The reorder moves rules 7–11
(~1,600 tokens) into the prefix and adds nothing else. `{tenant_id}` in rule 1
makes the prefix per-tenant, which is fine. Measurement needs `cached_tokens`
captured — not today (`telemetry.py:1473`); B1.

**Size** 0.5 d. **Test:** on the second turn within 5 min, `cached_tokens ≥ 60%`
of `prompt_tokens`; golden set unchanged. **Must not change:** rule semantics or
order *within* the static block once cached — every edit is a cache miss.

## Block B — measurement and the suspected bug

### B1. Dependency spans — **confirmed; add two token fields**

Wrap `get_embeddings`, `query_invoice_chunks`, `execute_generated_sql`,
`_full_record_block_for` + `_computed_figures_block_for`, `get_chat_history`,
`_get_tenant_stats_summary`, and the enqueue→pickup gap, as `dependencies` rows
(the table is empty for `invoice-be` today). Also record
`prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens`
on `llm_agent_call` — A1 and A4 are unmeasurable without them.

**The 5.5 s — hypotheses ranked by evidence, none proven:** (1)
`_get_tenant_stats_summary` recomputes aggregates on every turn when Redis is
absent — dev has no Redis, and the local run logged `Tenant stats cache lookup
failed … 6379`; (2) telemetry `_emit_event` posts to App Insights **inline** —
the BE log shows `POST …applicationinsights…/v2.1/track` request/response pairs
between turn steps; (3) `get_chat_history` with `tiktoken` (`query_agent.py:2053`);
(4) `_full_record_block_for` reflection. B1 decides. **Size** 1 d. **Test:** one
turn shows every span; sum of spans + LLM calls ≈ `latency_ms` within 10%.

### B2. Chroma HttpClient timeout — **confirmed as correctness; diagnosis scoped**

**Evidence.** `chroma_client.py:236–252`: `_build_chroma_client` tries
`chromadb.HttpClient` under a **3.0 s connect** / 30 s read budget
(`CHROMA_CONNECT_TIMEOUT_SECONDS`, L28–29) and on **any** exception returns
`chromadb.PersistentClient(path=<app dir>/temp_chroma_db)`. `get_chroma_client`
(L255) caches that singleton for the **process lifetime — no retry**. In a
Container App that path is ephemeral and empty on every new revision. So a single
slow connect at startup turns a replica's RAG into "search an empty local store"
until the next deploy, silently. `ca-chromadb-dev` is Running/Healthy
(revision from 2026-08-05, min 1 / max 1 replica, 0.5 vCPU / 1 Gi, internal
ingress); the worker's last 300 log lines show **0** fallbacks; the API logged
**one** at 05:50:48 UTC on revision `--0000120`, 3.1 s after startup — the
warm-up racing the 3 s budget.

**Are the measured turns affected?** No: they ran on `--0000117`, and its one RAG
turn had 3,078 input tokens — consistent with five retrieved chunks, impossible
from an empty local store. **Is `--0000120` affected now?** Undetermined —
nothing exposes the client type (`/health/readiness` does not report it).
**Does it explain RAG being 1 of 13?** No — see Q1; that is routing.

### B2 correction — measured 2026-09-03, after the section above was written

The paragraphs above are left intact as the record of what was believed, and are
**wrong on two points**. Log Analytics (`ContainerAppConsoleLogs_CL`,
`ca-invoice-be-dev`, 12 h) shows the fallback on **every** revision, not one:

| revision | attempt | outcome | warm-up then logged |
|---|---|---|---|
| `--0000116` | 04:12:16 | `timed out` -> PersistentClient | `chroma=ok (3.4s)` |
| `--0000117` | 04:23:28 | `timed out` -> PersistentClient | `chroma=ok (3.2s)` |
| `--0000118` | 05:01:37 | `timed out` -> PersistentClient | `chroma=ok (3.5s)` |
| `--0000119` | 05:07:52 | `timed out` -> PersistentClient | `chroma=ok (3.2s)` |
| `--0000120` | 05:50:45 | `timed out` -> PersistentClient | `chroma=ok (3.2s)` |

**Correction 1 — "are the measured turns affected? No."** They are. The section
argued `--0000117` was clean because its one RAG turn carried 3,078 input tokens,
"consistent with five retrieved chunks, impossible from an empty local store".
`--0000117` fell back at 04:23:31, before those turns ran. The 3,078 tokens are
history plus prompt, not chunks. That inference was the weakest link in the
section and it did not hold.

**Correction 2 — "a single slow connect at startup."** It is not a race. Five out
of five, always ~3.1 s against a 3.0 s budget: the internal ACA connect path is
simply slower than the budget on a cold replica. Nothing is intermittent here.

**And a third finding the section did not anticipate:** the health signal was
false. `warm_rag_dependencies()` heartbeats whatever `get_chroma_client()`
returned, and a local `PersistentClient` answers a heartbeat perfectly well — so
it logged `chroma=ok` about three seconds after logging that the HttpClient had
failed. The diagnosis step the section proposed (expose the client kind) turned
out to be the fix for the monitoring bug as much as an instrument.

Filed as **Gap 415**, with **Gap 416** for the missing `.dockerignore` found
alongside it. Both are in `be_features_tracker.md`.

**Diagnosis steps (0.5 d):** expose the client class in `warm_rag_dependencies()`'s
result and `/health/readiness`; query it on the live revision. **Fix if
confirmed (0.5 d):** retry `HttpClient` on the next call instead of caching the
fallback; raise the connect budget at warm-up only; alert on fallback. File as
its own gap **when confirmed** — not filed now, because the current-revision
state is unproven. **Must not change:** per-tenant collection naming,
`_collection_metadata()` (Gap 244's cosine space).

## Block C — hardening, in the founder's order

| item | verdict | size | proving test | must not change |
|---|---|---|---|---|
| **C1** AST tenant guard | **Confirmed. Filed today as Gap 414, P0.** The `… OR 1=1` shape passes the regex (`execute_generated_sql`, L1351) and is rejected on the AST; sqlglot parses the real LATERAL/jsonb shape but emits `JSONB_ARRAY_ELEMENTS` for SQLite, so the per-dialect rule 6d stays | 1.5 d | hostile-shape parametrised test + golden set on Postgres | regex layer stays; `_sql_dialect_name`; fail closed on parse error |
| **C2** cache correctness | Confirmed. `get_cached_answer` at `query_agent.py:4045` runs before `classify_query` (4097) and never consults `_is_narrowing_followup`. F26 B1 bypass intact: the attachment gate returns at L4035, before the cache read | 0.5 d | two-session narrowing test on Postgres + Redis; attachment turn never calls `get_cached_answer` | the gate at L4030–4035; `_invalidate_chat_answer_cache` prefix |
| **C3** zero rows = diagnosis | Confirmed, **with the founder's rule adopted**: every recovery ends in a proposal the user confirms — auto-correction becomes *"I read X as Y — confirm?"*, one click, the same D4 gate Tier 3 uses. Cost: one round-trip per typo, which is the price of never answering about the wrong vendor | 2 d BE + 0.5 d FE | typo → confirm card; mis-routed text question → `vector_answered` with citations; unknown vendor → clarification, never the sentinel | hard rule 3: the vector probe answers text, never supplies a figure SQL could not find; scope `invoice_chunks_` only |
| **C4** rules → structure | Confirmed as analysed; ~40% of rule text deletable, not most. Also the largest A4 win: fewer static tokens to cache and a shorter dynamic tail | 4.5 d incl. 1 d to write SQL for the 35 golden cases (they have none today) | golden set before/after; the genuine line-item case still links to no column | `_full_record_block_for`, `_computed_figures_block_for`; few-shot examples from the curated set only |
| **C5** items 4, 3, 6 deferred | Confirmed. Gate: ≥ 100 Azure turns in telemetry and B2 resolved | — | — | — |

## Q1 — Is RAG rare because users rarely need it, or because the router sends everything to SQL?

**What the nine turns say.** `chat.classify` fired on **4 of the 5 non-cached
turns** — so 80% *missed* the keyword pass and were routed by the LLM, which chose
SQL 3× and RAG 1×; the keyword pass decided only one turn. In this sample the
router is not what starved RAG: an LLM looked at the questions and judged four of
five structural, and the questions (discount, totals, an invoice's details)
were structural. That is one session and proves nothing about the population.

**How to tell, once B1 lands.** Three fields on `chat_turn`: `route_source`
(`keyword` | `llm`), the router's `reasoning` string, and C3's
`zero_result_diagnosis`. Then: (a) the share of keyword-routed SQL turns that a
weekly offline re-route through the LLM router would have sent elsewhere
(disagreement rate); (b) the share of SQL turns rescued by `vector_answered` —
each one is a mis-route by definition; (c) RAG share by `route_source`. If (a) < 5%
and (b) ≈ 0 over ≥ 100 turns, users rarely need it; if either is material, the
keyword pass is over-routing and item 4's trigger is the fix.

## Q2 — Projected p50 SQL turn after A1–A4, arithmetic shown

Baseline p50 (Azure, n = 4): **27.8 s** = classify 3.1 s (fires on ~80% of turns)
+ generation 15.6 s + summary 3.6 s + non-LLM ≈ 5.5 s (derived).

| step | now | after | basis |
|---|---|---|---|
| classify | 3.1 s | **≈ 1.0 s** | A2: gpt-4o, ~30 visible tokens instead of 243 reasoning+output; TTFT-dominated. *Assumed*, not measured |
| generation | 15.6 s | **≈ 5.6 s** | A1: measured throughput 1,688 tok / 15.6 s ≈ 108 tok/s; at `low` assume ~500 output tokens (Azure: fewer tokens on simple tasks — no number given) → 4.6 s + ~1 s TTFT. *The assumption is the token count* |
| summary | 3.6 s | **≈ 2.0 s** | A2: 258 tokens on gpt-4o at ~130 tok/s + TTFT. *Assumed* |
| prefix cache | — | **−0.5 s** | A4: Azure says caching *"reduces overall request latency"* with no figure; counted conservatively |
| non-LLM | 5.5 s | **5.5 s** | untouched until B1 |
| **total** | **27.8 s** | **≈ 13.6 s** | ≈ 12 s *perceived* with A3 streaming |

**Correction to the founder's 8–10 s.** A1–A4 alone land at **≈ 13–14 s**, not
8–10, because 5.5 s of the turn is not model time and Block A does not touch it.
8–10 s is reachable only if B1 finds ~4 s in the non-LLM remainder and it is
removed — the tenant-stats recompute (no Redis in dev) and inline telemetry posts
are the two candidates with evidence. Every number in the "after" column is an
assumption until the golden runs record it; the "now" column is measured.

## Final proposed order

**C1 → B2 → A1 → A2 → A4 → B1 → C2 → C3 → A3 → C4 → C5** — the P0 guard and the
correctness diagnosis first because they are cheap and gate everything measured
afterwards; then the three config-level wins; then the instrumentation that makes
A1/A4 provable and explains the 5.5 s; then the two correctness items; streaming
last in Block A because its value is bounded at ~2 s perceived; C4 once the golden
set carries SQL.

## What the founder gets after Block A alone

A median SQL turn of roughly 13–14 s instead of 28 (perceived ≈ 12 s with
streaming), classify and summary on a non-reasoning model with reasoning tokens
and cache hits visible per call, a golden set that carries generated SQL from its
first run, and a recorded before/after for every change — with **no** improvement
to correctness: the `… OR 1=1` guard gap, the cross-session cache answer and the
silent zero-row failure that started this review all remain until Block C, and
the 8–10 s target stays out of reach until B1 explains the non-model 5.5 s.

---

# §Execution record

Written **before** any code, per the founder's run instruction of 2026-09-03
(11:56 IST, 30-minute hardstop). One block per item reached in the run. Order is
the founder's: **C1 → B2 → B1 → A1 → A2-pre → A2 → A4 → C2 → C3 → A3 → C4 → C5**.
Nothing here is committed by the agent; every block ends at the approval gate.

## C1 — AST tenant guard (Gap 414, P0) — *in progress, run 1*

**What changes.** `execute_generated_sql` gains a second, independent isolation
layer that runs *after* the existing regex predicate check and before
`db_session.execute`. The regex layer is not touched, weakened or removed — it
stays as the cheap first pass. The new layer parses the statement and decides
tenant safety on the parse tree, so a predicate the regex reads as present but
that the engine can satisfy without it (`WHERE tenant_id = '<t>' OR 1=1`) is
rejected.

**Safety rule, stated deterministically** (hard rule 3 — no model decides this):

| node | safe when |
|---|---|
| leaf `tenant_id = '<this tenant>'` | always |
| any other leaf | never |
| `A AND B` | `A` safe **or** `B` safe |
| `A OR B` | `A` safe **and** `B` safe |
| `NOT X` | never |
| missing `WHERE` | never |

A `SELECT` is checked only if it reads at least one **physical table**; a select
over functions alone (the `LATERAL jsonb_array_elements(...)` shape, `SELECT 1`)
has nothing to isolate and is exempt. Every checked select in the tree —
top level, subquery and CTE — must be safe. Parse failure is a **rejection**
(fail closed), not a pass-through.

**file:function.**

- `Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py`
  - new `_ast_tenant_predicate_is_safe(node, tenant_id) -> bool` — the table above
  - new `_selects_reading_physical_tables(tree) -> list` — which selects are in scope
  - new `assert_tenant_isolation_on_ast(sql_clean, tenant_id, dialect) -> None` —
    parses, applies both, raises `ValueError` with the existing "Access Denied"
    prefix so the retry loop and `user_safe_error_detail` behave unchanged
  - `execute_generated_sql` — call the above immediately after Safety Check 3
    (new Safety Check 4); signature unchanged, so no caller changes
- `Prod_Invoice_LLM/apps/invoice-be/requirements.txt` — `sqlglot` pinned to the
  version actually probed (30.17.0). New runtime dependency; container rebuild
  required before this reaches Azure.

**Dialect.** Resolved from `_sql_dialect_name(db_session)` (`query_agent.py:822`)
and mapped `postgresql → "postgres"`, `sqlite → "sqlite"`. Only the parse uses
it — nothing is transpiled, because the 2026-09-03 probe showed sqlglot emits
`JSONB_ARRAY_ELEMENTS` for SQLite, which is why per-dialect rule 6d stays.

**The test that proves it.** `tests/test_sql_tenant_guard_ast.py`, parametrised
over hostile shapes, on **Postgres** (hard rule 2):

| shape | expected |
|---|---|
| `SELECT … WHERE tenant_id = '<t>'` | accepted |
| `SELECT … WHERE tenant_id = '<t>' AND status = 'PAID'` | accepted |
| `SELECT … WHERE tenant_id = '<t>' OR 1=1` | **rejected** — the gap |
| `SELECT … WHERE (tenant_id = '<t>') OR (total > 0)` | **rejected** |
| `SELECT … WHERE tenant_id = '<other tenant>'` | rejected (regex already) |
| `SELECT … WHERE status = 'PAID'` (no predicate) | rejected (regex already) |
| subquery reading a table with no tenant predicate | **rejected** |
| the real `LATERAL jsonb_array_elements(line_items)` shape | accepted |
| unparseable text | rejected, fail closed |

Plus the existing `tests/test_chat_sql_quality.py` (143 passed / 5 Redis skips as
of Gap 413) must stay green — it is the regression witness that real generated
SQL still executes.

**What must not change.** The regex layer stays exactly as written. Tenant
isolation only ever gets *stronger* — no shape accepted today by the regex is
accepted by fewer checks after this. `_sql_dialect_name` and both rule 6d
variants are untouched. `user_safe_error_detail`'s redaction still runs, so a
rejection never prints the statement. `execute_generated_sql`'s signature and its
`snapshot` contract are unchanged.

**Known risk, recorded rather than hidden.** If the model emits a subquery that
reads a physical table without repeating the tenant predicate, this layer rejects
SQL that previously ran. That surfaces as a retry (the loop is max 3) with the
error fed back, not as a user-visible failure — but if the golden set shows it
happening, the finding is filed as its own gap and the subquery rule is
reconsidered. It is not silently relaxed.

### C1 result — run 1 (2026-09-03, 11:56–12:31 IST)

**Landed, uncommitted.** `agents/query_agent.py` +182 lines (the four helpers and
Safety Check 4), `pyproject.toml` +1 (`sqlglot==30.17.0`), `uv.lock` updated,
`tests/test_sql_tenant_guard_ast.py` new (32 cases).

| run | command | result |
|---|---|---|
| new guard tests, SQLite env | `uv run pytest tests/test_sql_tenant_guard_ast.py -p no:randomly -q` | `30 passed, 2 skipped in 6.01s` (the 2 skips are the Postgres-only pair, skipped loudly by design) |
| new guard tests, `DATABASE_URL` → local Postgres | same, with `DATABASE_URL=postgresql://…@localhost:**5433**/invoice_db` | **`32 passed in 8.87s`** — hard rule 2 satisfied, both execution-path cases included |
| regression witness | `uv run pytest tests/test_chat_sql_quality.py -p no:randomly -q` | `143 passed, 5 skipped in 28.88s` — **identical to the pre-work baseline**, so no correct generated SQL was rejected by the new layer |

**`… OR 1=1` is now refused.** `test_or_true_is_refused_before_it_reaches_postgres`
passes: `execute_generated_sql` raises `Access Denied` before `db_session.execute`
is called at all. That is the Gap 414 defect, closed.

**The earlier failure was the port, not the code.** The first Postgres attempt
used `localhost:5432`; the local compose stack publishes Postgres on **5433**
(`invoice-postgres-local`, `postgres:16-alpine`). Re-run against the correct
port: `32 passed in 8.87s`, with no skips — both
`test_or_true_is_refused_before_it_reaches_postgres` and
`test_a_tenant_bound_query_still_executes_on_postgres` green. The positive and
negative execution paths are therefore both verified on real Postgres, and C1
meets hard rule 2.

**Two defects found and fixed inside the run, both mine, both in the new code:**
sqlglot 30 renamed two `Select` args (`from` → `from_`, `with` → `with_`). Reading
the old keys made `_select_reads_physical_table` return `False` for every select,
which the `checked_any` fail-closed branch turned into a blanket rejection —
loud, not silent, which is why it surfaced on the first run rather than in
production. Both key lookups now accept either spelling, with a comment saying
why, so a future dependency bump cannot quietly turn the guard into a no-op. No
tracker gap filed: this is new code corrected before it left the working tree,
not shipped behaviour.

**Not done, carried to run 2:** B2 and B1 (both documented above, neither
started). C1 itself is complete.

### C1 correction — Gap 417, found after `ab4a986` was pushed

The first cut of the guard compared the SQL literal to `tenant_id` as raw text.
Under the `OR` rule (safe only when both branches are safe) that rejected

    WHERE (tenant_id = '<dashed uuid>' OR tenant_id = '<dashless hex>') AND ...

— the same tenant written two ways, which binds one tenant and is safe. Four
`tests/test_rag.py` cases failed on it. `_normalized_tenant_literal()` now strips
quotes and dashes and case-folds both sides; a different tenant still fails on its
hex however it is punctuated, so isolation is unchanged.

**Why the Gap 414 run missed it, kept here because the lesson outlives the bug.**
The witness chosen was `tests/test_chat_sql_quality.py` alone, on the reasoning
that it is the suite exercising real generated SQL. `tests/test_rag.py` also calls
`execute_generated_sql` directly and was not run — and the code was committed and
pushed on that evidence. A guard added to a shared choke point takes **every**
suite that touches that choke point as its witness, found by grepping the function
name, not by picking the suite that seems most relevant.

**What was live in between.** `ab4a986` deployed as revision `--0000121`
(Healthy, so the new `sqlglot` dependency imports cleanly). The production prompt
emits a single dashed spelling (`tenant_id = '{tenant_id}'`), so the over-rejection
was not reachable from the normal generation path; the dual spelling came from the
test helper `_tenant_filter()`. The corrected code is in the working tree.

## B2 — Chroma fallback: diagnose, then fix if confirmed — *documented, not started*

**What changes, step 1 (diagnosis only, no behaviour change).**
`chroma_client.py` exposes which client the process actually holds:
`get_chroma_client_kind() -> "http" | "persistent-fallback" | "uninitialised"`,
surfaced in `warm_rag_dependencies()`'s result and in `/health/readiness`
(`main.py`). Then the live dev revision is queried and the answer recorded here.

**What changes, step 2 (only if the live revision is on the fallback).** Stop
caching the fallback for the process lifetime: retry `HttpClient` on the next
call, raise the connect budget at warm-up only (`CHROMA_CONNECT_TIMEOUT_SECONDS`,
`chroma_client.py:28–29`), and log/alert on every fallback.

**file:function.** `chroma_client.py::_build_chroma_client` (L236–252),
`get_chroma_client` (L255), `warm_rag_dependencies`; `main.py` readiness handler.

**The test that proves it.** A unit test that forces `HttpClient` to raise once
and asserts the next call retries rather than returning the cached fallback;
`/health/readiness` reports `"http"` against a running chromadb. Postgres not
required — this is not a DB path.

**What must not change.** Per-tenant collection naming, and
`_collection_metadata()`'s cosine space (Gap 244).

**Gap.** Filed **when confirmed on the live revision**, not before — the
current-revision state is still unproven, and a gap for a condition that may not
exist is noise.

### B2 result — run 2 (2026-09-03)

**Landed, uncommitted.** The item was specced as "diagnose, then fix if
confirmed". The logs confirmed it before any instrument was built, so this run
went straight to the fix.

**Built.** `chroma_client.py`: `_chroma_client_kind` / `_chroma_fallback_at`;
`_build_chroma_client(connect_timeout=None)` records the kind it produced;
`get_chroma_client()` retries the real server once the fallback is older than
`CHROMA_FALLBACK_RETRY_COOLDOWN_SECONDS` (60 s) and promotes the singleton on
success; new `get_chroma_client_kind()`; `CHROMA_WARMUP_CONNECT_TIMEOUT_SECONDS`
(15 s) used only by `warm_rag_dependencies()`, which now reports `ok` only when
the kind is `http`. `main.py`: `/health/readiness` reports the client kind,
non-fatal.

| run | command | result |
|---|---|---|
| new B2 tests | `uv run pytest tests/test_chroma_fallback_retry.py -p no:randomly -q` | `10 passed in 7.96s` |
| regression witness | `pytest tests/test_rag.py tests/test_chat_document_search.py tests/test_documents_table.py tests/test_chat_sql_quality.py` on Postgres | `4 failed, 256 passed in 89.27s` — down from `9 failed, 103 passed` before the Gap 417 fix; the 4 that remain are Gap 418, pre-existing |

**What must not change, and did not:** the 3.0 s request-path connect budget
(Gap 278) is pinned by its own test; per-tenant collection naming and
`_collection_metadata()`'s cosine space (Gap 244) are untouched.

**Not claimable yet.** The fix is green in tests but **unobserved on Azure** — it
needs a deploy. The evidence to look for afterwards is `RAG warm-up complete:
chroma=ok` with no preceding `HttpClient failed` line, and `/health/readiness`
returning `"chroma": "ok"`. Until then dev is still on the fallback.

## B1 — dependency spans + two token fields — *documented, not started*

**What changes.** `dependencies` rows (the table is empty for `invoice-be`) around
`get_embeddings`, `query_invoice_chunks`, `execute_generated_sql`,
`_full_record_block_for` + `_computed_figures_block_for`, `get_chat_history`,
`_get_tenant_stats_summary`, and the enqueue→pickup gap. On `llm_agent_call`, two
new fields read from the API response: `prompt_tokens_details.cached_tokens` and
`completion_tokens_details.reasoning_tokens` (`telemetry.py:1473–1476` reads
neither today).

**Why it precedes A1/A2/A4 in this run's order.** Those three are config changes
whose entire claim is latency and token cost. Without the two fields there is no
before/after, only an assertion — the "after" column of Q2 stays assumed.

**The test that proves it.** One chat turn emits a span per wrapped dependency,
and the sum of spans plus LLM call durations is within 10% of the turn's recorded
`latency_ms`. On Postgres.

**What must not change.** Telemetry stays best-effort — a failure to emit a span
never fails a chat turn. No new inline network call on the request path (the
inline App Insights post is itself hypothesis 2 for the unexplained 5.5 s).
