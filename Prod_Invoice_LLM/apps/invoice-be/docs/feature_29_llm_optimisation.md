# Feature 29 — LLM Optimisation

Status lives in `docs/be_features_tracker.md`. This document is the durable design record for
everything decided and measured on 2026-09-05/06 about **which models SAGE runs, what they are
grounded in, what they are forbidden to do, and how the chat area — with and without an attached
document — is made accurate for every scenario found so far and the ones not yet found.**

Collision check at creation time (2026-09-06): max BE feature is 28
(`feature_28_image_upload_pdf_boundary.md`); **29 is free.** Gap numbers in use up to **473**
(Gaps 470–473 filed today, all `[ ]`/`[~]`); next free is 474 — re-check before writing any tracker
entry. This is a BE-only feature. The FE is untouched by design: every change here is behind the
existing `/chat` contract, and the FE renders whatever payload keys it already knows.

Authorship note: the founder asked for "architect" to write this. It is written by the session that
ran the matrix, the probes and Gaps 470–473, because that session holds the evidence; the architect
persona's scope proposal is §9 (tasks by specialist).

---

## 1. Overview

**What this is.** One feature that closes the loop the last two days opened:

1. **Model roles** — five candidates were benchmarked on four tasks with a judge cross-check; the
   roles are decided and partly live in dev. This feature finishes the migration and records the gate
   a future swap must pass.
2. **Chat accuracy without an attachment** — the golden set passes 22–28% on every model. The
   diagnosis is that the model is given the wrong evidence (a 2–13-column SQL projection, zero
   document chunks) and asked to compute what it is forbidden to compute. Full records raised
   gpt-5-mini from 22.2% to 52.8% with no other change.
3. **Chat accuracy with an attachment** — 5 of 12 probe turns failed identically on three models.
   Four are fixed (Gaps 470–473) and each was two stacked defects: a routing miss and a missing
   deterministic computation.
4. **A generic answering architecture** so that a *new* scenario becomes a certified example or a
   new deterministic capability — never a new prompt branch or keyword. Research basis:
   `docs/architecture/chat-generic-answering-research.md` (repo root).
5. **A knowledge layer** (semantic views, glossary, certified Q→SQL, playbooks, regional rule
   cards) per `docs/architecture/knowledge-layer-plan.md`.

**What this is not.**
- Not a rewrite of Feature 6 (RAG / SQL agent) or Feature 26 (attached documents). Every change
  lands inside their existing branches and keeps their hard-rule-3 invariants. New design that
  supersedes a Feature 6 or 26 section is written here and cross-referenced from there, never edited
  in place (CONVENTIONS hard rule 4).
- Not Feature 13 (benchmark suite). It *uses* Feature 13's harness, `run_agent_eval.py`,
  `run_model_matrix.py` and `sweep_chat_attachments.py` and adds golden cases; it does not change
  how they score.
- Not a model fine-tune. Explicitly deferred until ~1k reviewed corrections and a stable schema.
- Not a prod rollout. Dev only until §10's gates pass; `params.prod.json` is untouched by every task
  here.

**Naming collision.** `feature_6_rag.md` §"Feature 6.1" already covers chat latency items A1–C4
(prompt caching, fast deployment, AST tenant guard, schema linking, examples retrieval). Feature 29
builds on C4's example retrieval and A2's fast deployment; it is numbered separately because it
spans extraction, SQL, chat, judge and infra roles, not one route.

---

## 2. Investigation record — everything measured, 2026-09-05/06

All numbers are from `docs/extraction_benchmark/runs/matrix-20260905T092330Z/` (`decision.md`,
`chat_report_20260906.md`, `*__chat_context_audit.md`, `*__extraction*.json`, `*__attachchat.json`,
`*__judge.json`). Judge for every chat score: gpt-5-mini, separate-metric mode. One pass per cell
unless stated; differences under ~3 points are within run-to-run noise on 27 invoices / 36 turns.

### 2.1 Five-model matrix (one pass each, api-version 2024-10-21, dev account)

| task | gpt-5-mini | gpt-5.6-luna | gpt-5.6-terra | gpt-5.6-sol | gpt-6-astra |
|---|---|---|---|---|---|
| (a) extraction score % / $ per 1k calls / p95 s | 98.8 / $2.97 / 65.3 | **99.3** / **$0.85** / 35.7 | 97.3 / $7.81 / 54.7 | 98.0 / $19.85 / **31.3** | 95.1 / $24.07 / 59.8 |
| (a) tax / total / line-F1 % | 96.3 / 100 / 100 | 100 / 100 / 97.8 | 96.3 / 100 / 95.6 | 96.3 / 100 / 97.8 | 92.6 / 92.6 / 100 |
| (b) doc-type acc % / $ per 1k / p95 s | 95.8 / $0.89 / 5.4 | **100** / **$0.38** / 2.7 | 100 / $3.70 / 2.6 | 100 / $9.25 / 2.7 | 100 / $16.93 / 4.1 |
| (c) SQL exec-correct % (n) / p95 s | 32.3 (31) / 34.0 | 40.7 (27) / **12.4** | **44.4** (27) / 13.2 | 28.0 (25) / 17.3 | **44.4** (27) / 21.5 |
| (d) chat judge acc / faithfulness / pass % | 0.542 / 0.783 / 22.2 | 0.583 / 0.824 / **27.8** | 0.622 / 0.727 / 25.0 | 0.514 / 0.833 / 22.2 | **0.639** / 0.785 / 25.0 |
| (d) $ per turn / p95 s | $0.0062 / 34.0 | **$0.0022** / **11.2** | $0.0198 / 11.3 | $0.0517 / 16.6 | $0.0847 / 20.6 |
| (e) judge mean abs δ vs current / pass flips % | **0.097 / 5.6** | 0.191 / 22.2 | 0.169 / 27.8 | 0.156 / 22.2 | 0.119 / 19.4 |

**Row (c) is not a deterministic measurement — annotated 2026-09-07 (Gap 484), not deleted.**
The harness never wrote `expected_invoice_numbers` into a turn record, so `digest_eval`'s
`set(expected) <= set(fetched)` branch never executed and these five figures were produced by
the **judge's** `accuracy_score >= 0.8` — the judge later measured at κ 0.151. The varying n
(31 / 27 / 27 / 25 / 27 for one 36-case set) is the floating denominator of the same defect.
Both are fixed; no figure in this row is comparable to one produced after 2026-09-07.

List price per 1M in/out: gpt-5-mini $0.25/$2.00 · Luna $0.20/$1.20 · Terra $2.00/$12.00 · Sol
$5.00/$30.00 · Astra $10.00/$12.50.

**Reading.** Extraction and doc-type are solved by every model (95–100%). SQL and chat are flat
across all five (28–44% and 22–28%). A flat line across a 100× price range is the signature of a
grounding problem, not a model problem.

### 2.2 Luna extraction, three runs (founder's stability check)

| run | tax / total / line-F1 % | composite | $ per invoice | p95 s |
|---|---|---|---|---|
| run 1 (2026-09-05) | 100 / 100 / 97.8 | 99.3 | $0.00201 | 35.7 |
| run 2 (2026-09-06, fresh tenant) | 96.3 / 100 / 100 | 98.8 | $0.00204 | 45.1 |
| run 3 (2026-09-06, fresh tenant) | 96.3 / 100 / 100 | 98.8 | $0.00207 | 47.1 |

The "Status" and "Alert Type" columns are excluded from the composite in run 1 (duplicate-flagged
by ingestion order, see `decision.md`) and score 70.4 / 55.6 in runs 2–3 on fresh tenants — that
is a harness artefact to fix (tasklist Step 2a), not an extraction defect. **Extraction on Luna is
closed at 98.8 / 98.8 / 99.3.**

### 2.3 Chat without attachment — as-is vs full-record (36 golden cases)

| model | mode | judge acc | faithfulness | pass % | tokens in / turn | p95 s |
|---|---|---|---|---|---|---|
| gpt-5-mini | as-is (router → SQL projection → summary) | 0.542 | 0.783 | 22.2 | 8,344 | 34.0 |
| gpt-5-mini | **full record** (every column + items/taxes/alerts, no router, no SQL) | **0.761** | **0.891** | **52.8** | 18,534 | 12.5 |
| gpt-5.6-luna | as-is | 0.583 | 0.824 | 27.8 | 8,618 | 11.2 |
| gpt-5.6-luna | full record | 0.671 | 0.846 | 37.1 (n=35) | 17,724 | 38.3 |
| gpt-5.6-luna | **as built, fixed judge (2026-09-07)** | **0.757** | **0.891** | **72.2** | 7,869 | — |

**What the context audit showed (Luna as-is, 36 turns).** The invoice table has 45 columns. The
generated SELECT projected 2–13 of them; `items`, `taxes`, `sa_alerts`, `payment_instructions`,
`notes`, `subtotal` were absent from the prompt in 29 of 36 turns; **0 document chunks were cited on
every turn**; 9 turns ran on the `general` route with **no rows at all** ("invoice not in the provided
context"). One turn returned 402 rows for an aggregate question. Failures therefore split into: no
evidence (9), wrong/partial evidence (~17), model forbidden to compute what the question needed (~6:
line-sum checks, cross-currency refusal, GST slab per line), and judge-strictness (~4: answer correct,
one sub-claim unsupported).

**The 2026-09-07 row is the first number in this table that is a measurement of the product.** Every
row above it was produced by the pre-Gap-479 judge, which failed 20 of the 28 answers a reader marks
correct (κ 0.151); the rows are kept because they are the history the fix was found from, not because
they are comparable. On the fixed judge, live (`runs/f29-golden-20260907/`, 36 turns, judge gpt-5-mini):
**κ 0.852 / agreement 94.4% against the reference verdicts, gate ≥ 0.6 passes, 0 false passes, 2 false
fails** — one a transient Postgres connection drop inside the run, one **Gap 480**. Task 29.5's evidence
wiring is confirmed on live data (Gap 478): `evidence_source = "app"` on 31 of 36 turns and the graded
context carries `FULL INVOICE RECORD(S)` on 22 of 36, against **0 of 36** on the same build the day
before. Failure taxonomy: `wrong_evidence` 9 → 4, `no_computation` 9 → 4, `narration` 4 → 0, `judge`
4 → 0, `no_route` 2, `no_evidence` 0.

**Cost.** Full-record turns are ~18k input tokens (≈$0.0045 gpt-5-mini, ≈$0.0037 Luna at list) versus
1–3k today, but replace 2–4 chained calls with one. Net per-turn cost is roughly flat; latency halves on
gpt-5-mini.

### 2.4 Chat with attachment — 16-turn probe, three models (8 generated documents, run-3 US tenant)

12 attachment turns + 4 plain questions in the same sessions. Answer cache flushed per model.

| model | attachment pass | plain pass | p95 s |
|---|---|---|---|
| gpt-5.6-luna | 4/12 | 4/4 | 8.0 |
| gpt-5-mini | 6/12 | 4/4 | 16.3 |
| gpt-5.6-terra | 7/12 | 4/4 | 5.4 |

**The same five turns failed on all three models** — A4, A7, B3, B4, B5 — which makes them agent
logic, not model choice:

| turn | question | expected | why every model failed | fix |
|---|---|---|---|---|
| A4 | PO + credit note: "after the credit, what do we owe Apex?" | $432 = PO total | nobody computed 452 − 20; question fell to the clarify card; two attachments routed to doc-vs-doc | **Gap 472** — signed money ledger on both branches; keywords |
| A7 | statement: "which lines do we have invoices for?" | BRL-200981 found, BRL-201044 missing | prose gave counts only ("1 agree. 1 no record") | **Gap 470** — every reference named |
| B3 | remittance: "which invoice does this pay, in full?" | IEQ-US-9001 paid $2,500 | clarify card; then counts only | **Gap 470** — pay/remit keywords, advisory default to reconcile |
| B4 | contract: "is the sales tax on RFG-500712 correct?" | 8.25% → $123.75 vs $90 | contract has no priced lines; text walled off from money prompt; model may not multiply | **Gap 473** — rate parsed + expected figure computed in Python; quoted span fenced |
| B5 | delivery note + contract: "which vendor needs follow-up?" | Redwood, tax under-charged | two attachments compared to each other, not each to its invoice | **open — task 29.7** |

The other 7 attachment turns and all 4 plain turns pass on ≥2 of 3 models; Terra's 7/12 vs Luna's 4/12
is the long-document recall gap the knowledge-layer plan flags (MRCR 41% Luna vs 89%+ Terra).

### 2.5 Judge reliability

Rescoring the same answers with each candidate as judge against the gpt-5-mini baseline: mean
absolute delta 0.10–0.19, pass flips 5.6% (gpt-5-mini vs itself, different run) to 27.8% (Terra).
**Any chat delta under ~10 points is inside judge noise today.** No prompt or model conclusion in
this feature is accepted on judge delta alone until task 29.2 calibrates it.

### 2.6 Gaps 470–473 — unit evidence (real Postgres, `localhost:5433/invoice_db`, 2026-09-06)

`tests/test_compare_documents.py` 32 → **51 passed** (19 added); `tests/test_chat_attachments.py` 34
→ **42 passed** (8 added); with `test_sweep_chat_attachments.py`, `test_direction_aware_chat.py`,
`test_invoice_reconciliation.py`, `test_chat_document_search.py` → **139 passed in 43.85s**. Gap 471
removed a live Azure call from the unit suite (found by a 30-second wall-clock drop). **The 16-turn
probe re-run is still owed** — Gaps 470/472/473 stay open until it is recorded (task 29.8).

---

## 3. Model roles — final (founder, 2026-09-06)

| role | deployment | used by | decision basis |
|---|---|---|---|
| **primary** | `gpt-5.6-luna` (2026-07-09) | extraction, SQL generation, trainer, dashboard | 99.3 extraction at 1/3 the cost of gpt-5-mini; SQL within noise of Terra at 1/9 the cost. Founder override of `decision.md`'s Terra-for-SQL (cost) |
| **fast** | `gpt-5.6-luna` | chat narration, routing, guards, classifier fallback | best pass % as-is; cheapest; lowest p95. Founder override of Astra (cost, 2 pts inside noise) |
| ~~**long_doc**~~ | **none — role removed 2026-09-07 (task 29.10, Gap 489)** | attached-doc answer stays on `fast` = Luna | Luna 3/3 vs Terra 3/3 on the gradable long-doc golden cases (§8 29.10 result); 2-pt rule keeps Luna; Terra deployment deleted; `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME` and `get_long_doc_llm()` removed rather than left as an inert variable |
| **judge** | `gpt-5-mini` | `run_agent_eval.py`, online quality signals | lowest pass-flip rate (5.6%); must differ from primary |
| **chat without attachment** | `gpt-5-mini` for the full-record summary call | the Step-4 full-record route | 52.8% vs Luna 37.1% on full records — the one place gpt-5-mini beat Luna outright |
| escalation | none | — | Sol/Astra did not beat Terra by >2 pts on extraction; **deleted** (task 29.1) |

**Registry corrections (task 29.1).** The 5.6 family context is **1.05M (922k input)**, not 400k as
`utils/model_registry.py` currently states for Luna/Terra/Sol. Add a `recall_note` to Luna's entry:
window ≠ recall (MRCR 41%); do not send it long documents on the strength of the window.

**Live state.** `params.dev.json`, local `.env`, `ca-invoice-be-dev` and `ca-queue-worker-dev` are on
luna/luna/gpt-5-mini, api-version 2024-10-21. The six `caj-*-dev` jobs are **not** yet updated.

---

## 4. Analysis of the proposed generic architecture

The research note proposes seven layers. This section is the critical read — what to adopt, what to
change, and what not to build yet.

### 4.1 Adopted as written

- **Answer contract + deterministic groundedness gate (L1).** Already the rule on the attachment
  branches; extending "every figure must be in the payload" to every route is the single cheapest
  correctness control we have, and it catches the judge's most common finding (a correct answer with
  one unsupported figure) *before* the judge.
- **Deterministic computation as a library (L5).** Validated three times today (Gaps 470/472/473) and
  at scale by CIFQA (95.5% on calculation queries with a 17B model). Rule adopted verbatim: a turn that
  fails because a figure was never computed gets a tested function, never a prompt.
- **Semantic layer + certified examples + full records (L4).** The largest measured effect in the
  literature (84–90% → 98–100% in scope) and our own largest measured effect (22.2% → 52.8%).
- **Flywheel with exactly three outcomes (L7).** Certified example / new capability or rule card /
  resolver fix. "Adjust the prompt" is excluded unless the taxonomy shows a narration-only defect.

### 4.2 Adopted with changes

- **Planner instead of classifier (L3) — adopt, but stage it.** The value is real: A4 and B4 did not
  fail for lack of keywords, they failed because nothing checked whether the question named things we
  could resolve. But a planner call adds one LLM round-trip (~1–3 s on Luna) to every turn and is a new
  failure surface. Stage: (i) deterministic **entity resolver** first, with automatic clarify on 0/>1
  matches — this alone retires most keyword lists; (ii) the typed-plan call second, behind a flag, on
  the attachment branches only where the scenario space is richest; (iii) all routes once the golden
  set shows no regression. Keyword lists stay as a fallback for one release, then are deleted.
- **Typed capability registry (L2) — adopt as a Python registry, not a framework.** A dict of
  `name → (callable, input schema, output schema, deterministic: bool)` in one module. No agent
  framework, no dynamic tool loop: the planner proposes, the registry validates, Python executes in
  order. This keeps the "exactly one narration call" shape the content branch already documents.
- **Reranker (L6/L4).** Adopt, but *after* RAG recall is measured. Today 0 chunks are cited on every
  chat turn — the problem is that retrieval is not called, not that it ranks badly. Measure first.

### 4.3 Not yet

- **Multi-agent orchestration.** The research progression is router → planner → verifier → (only
  then) multi-agent. We are at router.
- **Query decomposition for multi-hop.** Our golden set's multi-part questions are answered by full
  records + one computation; decomposition is a solution to a problem we have not measured.
- **Fine-tuning.** Deferred as stated.

### 4.4 Risks the design must carry

| risk | mitigation in this feature |
|---|---|
| Abstain rate rises and users read it as "the bot got dumber" | abstain payload names *what* is missing; taxonomy tracks abstain-when-answerable as its own bucket |
| Certified-example store drifts (Snowflake: bad examples actively hurt) | `certified_by` / `certified_at` mandatory; uncertified rows are never retrieved; re-certify on schema change |
| Full records blow the context on large tenants | cap N invoices per turn (founder to set, §11), rows beyond the cap summarised as a count with ids |
| Judge changes and every historical number moves | judge deployment pinned in the registry `judge` role; every eval JSON records it; calibration set is versioned |
| Planner introduces a hostile-text vector | planner never sees document text — manifest only (Gap 439 shape); evidence spans are fenced (Gap 473 shape) |

---

## 5. File Coordinates

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `utils/model_registry.py` | `MODEL_CATALOG`, `CatalogEntry.recall_note` | edit | 5.6-family context → 1,050,000 / 922,000 input; `recall_note` field; Sol/Astra entries marked deleted |
| `utils/llm.py` | ~~`get_long_doc_llm()`~~ | removed 2026-09-07 | added by 29.1, deleted by 29.10 / Gap 489 with the `long_doc` role and its setting |
| `agents/entity_resolver.py` | `resolve_entities()`, `ResolutionResult`, `ResolvedEntity`, `Candidate` | new (29.11) | deterministic invoice / vendor / attachment / session-reference binding; 0 or >1 → clarify card; wired into `_run_query_agent()` behind `ENABLE_ENTITY_RESOLVER` |
| `config.py` | `Settings.CHAT_FULL_RECORD_MAX_INVOICES`, `Settings.ENABLE_CHAT_PLANNER`, `Settings.ENABLE_ENTITY_RESOLVER` (~~`AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME`~~ removed, Gap 489) | edit | new settings, all defaulted to today's behaviour |
| `agents/query_agent.py` | `_run_query_agent()` | edit | after SQL identifies ids, calls `fetch_full_records()`; passes the full-record block + chunks to the summary prompt |
| `agents/query_agent.py` | `_amount_owed_block()`, `_contract_terms_block()` | exist (Gaps 472/473) | unchanged; listed because 29.7 wires them on the per-document path |
| `agents/query_agent.py` | `_run_attachment_pair_turn()` | edit | task 29.7: when both documents have confirmed invoices and the question is not "compare these two", run each document against its own invoice and merge |
| `agents/query_agent.py` | `_answer_contract_gate()` | new | extracts every number from the narration, checks each appears in the payload; one regeneration with the offending figure named, then abstain |
| `agents/query_agent.py` | `_abstain_payload()` | new | `{status:"insufficient_evidence", missing:[...]}` rendered as a specific sentence |
| `agents/entity_resolver.py` | `resolve_entities()`, `ResolvedEntity` | new | deterministic invoice-number / vendor / attachment / session-reference resolution; returns 0, 1 or N candidates per mention |
| `agents/chat_planner.py` | `plan_turn()`, `TurnPlan`, `CAPABILITIES` | new | one fast-model call → typed plan validated against `CAPABILITIES`; flag-gated |
| `services/full_records.py` | `fetch_full_records()`, `full_record_block()` | new | every column of N invoices, JSON parsed, plus their Chroma chunks, rendered as one block with a cap |
| `services/document_comparison.py` | `compute_amount_owed()`, `compare_contract_terms_to_invoice()`, `extract_contract_terms()` | exist | unchanged |
| `services/document_comparison.py` | `check_line_arithmetic()` | new | qty × unit price vs printed amount per line, and subtotal vs Σ lines — the computation `bolts_reconciliation`, `india_ganesh_*`, `eu_benelux_*` needed |
| `services/semantic_layer.py` | `METRICS`, `query_metric()` | new | metric name → certified view + definition; runs the view with tenant filter |
| `alembic/versions/<rev>_certified_views.py` | `upgrade()` | new | `CREATE VIEW v_vendor_spend, v_overdue, v_tax_summary, v_3way_match` (add-only) |
| `alembic/versions/<rev>_certified_examples.py` | `upgrade()` | new | table `certified_sql_example(id, tenant_id nullable, question, sql, metric, certified_by, certified_at, source, embedding_id)` |
| `services/certified_examples.py` | `retrieve_examples()`, `certify_example()` | new | top-5 by similarity from the Chroma `knowledge_{tenant}` collection, **certified rows only** |
| `services/knowledge_layer.py` | `KnowledgeDoc`, `index_knowledge()`, `lookup_rule()`, `lookup_glossary()` | new | one Chroma collection, metadata `kind/region/tenant_id/effective_from`; rule cards, glossary, playbooks |
| `chroma_client.py` | `get_knowledge_collection()` | edit | sibling of `chat_docs_{tenant}` |
| `agents/query_agent.py` | `_computed_figures_block_for()`, C4 examples tail | edit | prefers `query_metric()` when the schema link names a certified metric; examples tail reads `retrieve_examples()` |
| `services/chat_corrections.py` | `record_correction()`, `promote_to_example()` | new | thumbs-down + fix → `chat_correction` row → certified example after review |
| `alembic/versions/<rev>_chat_correction.py` | `upgrade()` | new | table `chat_correction(id, tenant_id, message_id, bucket, note, promoted_example_id, created_at)` |
| `scripts/run_agent_eval.py` | `--taxonomy`, `--calibration-set` | edit | emits one line per failed turn tagged with the §2.3 bucket; computes Cohen's κ against `tests/golden_calibration.json` |
| `scripts/attach_chat_eval.py` | `main()` | new (formalise the probe) | the 16-turn attachment probe as a versioned script: fresh sessions, cache flush, per-model JSON |
| `tests/golden_calibration.json` | — | new | ≥30 (target 100) hand-graded turns with human verdicts |
| `tests/golden_long_doc.json` | — | new | 5 long-document cases for the `long_doc` role gate |
| `infra/modules/compute/*.bicep`, `08-apps.bicep`, `params.dev.json` | ~~`azureOpenAiLongDocDeploymentName`~~ | added P0.4, removed 2026-09-07 | Gap 489: the param and env var are gone from all three modules, `08-apps` and both params files; `tests/test_model_role_env_wiring.py` pins that they stay gone |
| `infra/model-deployment.bicep` | comment | edit | Sol/Astra removed; roles documented |
| `docs/feature_6_rag.md`, `docs/feature_26_chat_attached_documents.md` | §"Superseded by Feature 29" | edit | cross-reference only |

---

## 6. Functionality — the runtime path after this feature

**A chat turn without an attachment.**
1. `_run_query_agent()` receives the question. `resolve_entities()` runs first — deterministic
   invoice-number, vendor-name (exact then fuzzy with threshold) and session-reference resolution.
   Zero matches for a named entity → `_abstain_payload()` ("no invoice from *Titan Steel Distributers*
   — did you mean Titan Steel Distributors?"). More than one → one clarify with the candidates.
2. With `ENABLE_CHAT_PLANNER` off (default until 29.13): the existing classifier routes. With it on:
   `plan_turn()` returns a `TurnPlan` naming capabilities from `CAPABILITIES`; an unknown capability or
   an operand the resolver could not bind is a validation error → clarify, never a guess.
3. SQL route: schema link → if it names a certified metric, `query_metric()` runs the view; otherwise
   `generate_sql()` with `retrieve_examples()` (certified only) in the tail and the existing 3-attempt
   execution-repair loop.
4. **Ids known → `fetch_full_records()`**: every column, `items`/`taxes`/`sa_alerts`/`notes`/
   `payment_instructions` parsed, plus that invoice's chunks from `invoice_chunks_{tenant}`, capped at
   `CHAT_FULL_RECORD_MAX_INVOICES`; beyond the cap, ids + a count. This block replaces the projection
   in the summary prompt.
5. `_computed_figures_block_for()` plus `check_line_arithmetic()` compute every figure the question
   needs; the summary model (gpt-5-mini on this route) narrates a payload it may not add to.
6. `_answer_contract_gate()`: numbers in the prose ⊆ numbers in the payload, else one regeneration
   naming the figure, else abstain. Provenance (invoice id / column / chunk id / function) is attached
   to the response for the FE's existing citation rendering.
7. Persisted: the turn, its plan (when on), the payload hash, the gate outcome. Nothing new is
   cached on the answer cache without a plan-keyed entry (task 29.12).

> **Build note, 2026-09-06 (task 29.5, as built).** Steps 4 and 5 above are live. What was built
> and where it departs from the paragraph above:
>
> 1. **`services/full_records.py` is new and `agents/query_agent._full_record_block_for()` now
>    delegates to it.** The block itself is not new — Gap 310 shipped it on the SQL route in August —
>    so this task is better described as *widening an existing block to what §2.3 measured* than as
>    building one. Keeping the old name and its `@tracked_dependency("chat.full_record_block")` span
>    means the dependency telemetry, the boundary test and every existing call site are unchanged.
>    `fetch_full_records()` returns a typed `FullRecordSet` (records, chunks, cap state,
>    `provenance()`) and `full_record_block()` renders it; `full_record_block_for()` is the one-call
>    fail-soft wrapper the agent uses.
> 2. **Two bounds, not one.** The invoice cap is 25 (decision 1) and is
>    `Settings.CHAT_FULL_RECORD_MAX_INVOICES`. Document pages have their **own** bound,
>    `Settings.CHAT_FULL_RECORD_CHUNK_INVOICES = 5`, because they are the expensive axis (an 11-page
>    invoice measured 16,010 tokens in `query_tools`) and they answer a detail question, not a
>    listing one. A turn over the page bound still gets all 25 structured rows and is **told** the
>    document wording is not attached, rather than being left to invent it. There is also a
>    turn-wide 24,000-character ceiling on page text.
> 3. **Over the cap now discloses instead of returning nothing.** Gap 310's bound returned `""` past
>    three invoices, which is how a 40-invoice turn ended up answering from a 2-column projection
>    with no hint that detail existed and had been withheld. Past 25 the block states the count,
>    lists the ids, forbids per-invoice detail and asks the user to narrow. `tests/
>    test_chat_sql_quality.py::test_full_record_block_is_bounded_to_a_few_identified_invoices` was
>    updated to assert the ruled behaviour instead of the old silence.
> 4. **Wired on three routes, not one.** §6 says "the SQL route after ids are known, and the general
>    route once the resolver binds an invoice". `resolve_entities()` is task 29.11 and is not built
>    yet, so the binding used on the non-SQL routes is a new deterministic helper,
>    `query_agent.invoice_ids_named_in()`: an exact, case- and whitespace-insensitive
>    `invoice_number` match on tokens of the shape `_INVOICE_NUMBER_PATTERN` already recognises,
>    parameterised and tenant-scoped. It either finds the number the user typed or finds nothing, so
>    it cannot bind the wrong invoice; fuzzy matching, vendor resolution and the "did you mean" path
>    stay in 29.11 where they can clarify. The RAG route also feeds it the invoice ids its own
>    citations already carried and never looked up.
> 5. **The summary model is chosen by the evidence in the prompt, not by the route's name.**
>    Decision 2 ruled gpt-5-mini for the full-record route and Luna for the attachment branches.
>    `utils/llm.get_chat_summary_llm()` resolves a new `chat_summary` registry role from
>    `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME` → the **judge** deployment → the primary. The judge
>    rung is deliberate: every environment already sets the judge to gpt-5-mini, so an environment
>    that has never heard of the new variable still behaves as decision 2 requires instead of quietly
>    narrating on Luna. `query_agent._chat_summary_llm()` is used only where a full-record block was
>    actually built; a turn that identified no invoice is bit-identical to before.
> 6. **Every full-record block is also appended to `judge_context_parts`** on all three routes (Gap
>    304 half 2). A figure read off `taxes` that the judge cannot see scores unfaithful for the sole
>    reason that the judge was shown less evidence than the model was.
>
> **Found while verifying, filed not fixed: Gap 477.** `tests/test_chat_sql_quality.py` has 18
> failures that predate this task — the Gap 471 live-Azure shape, one file over — and the standing
> 43-failure baseline does not include them. Proven not to be 29.5's by swapping `git show
> HEAD:agents/query_agent.py` in and getting the same 18 names. It is filed with a proposed fix and
> a founder go is pending, per the 2026-09-06 rule that every failure is discussed before it is
> fixed.

**A chat turn with one attachment.** Unchanged shape (Feature 26): intent → compare / reconcile /
read. `_amount_owed_block()` and `_contract_terms_block()` run on the compare branch; the narration
call uses the `fast` role (Luna) — 29.10 measured no long-document advantage for Terra, so there is no separate long-doc model (Gap 489). Gate as above.

**A chat turn with two attachments.** Task 29.7: if the question names or implies an invoice and both
documents have confirmed invoices, each document is compared to *its own* invoice and the two
payloads are merged under one narration; doc-to-doc runs only when the plan (or, pre-planner, an
explicit "compare these two / against each other") says so. The ledger and terms blocks run on the
merged payload.

> **Build note, 2026-09-06 (task 29.7, as built).** Three refinements, all found by building it:
>
> 1. **"Both documents have confirmed invoices" became "any".** Probe turn A4's credit note is
>    confirmed against nothing — which is the normal shape for an adjusting document — so the
>    *both* rule would have left A4 on the doc-to-doc branch, the exact place 29.7 exists to move it
>    from. The rule as built is: no explicit doc-to-doc request **and** at least one of the two
>    documents has a confirmed invoice → per-document merged branch. A document with nothing
>    confirmed is not dropped; it still reaches the manifest and the session-wide ledger, which is
>    where A4's credit note has to be counted anyway. Neither document confirmed → the doc-to-doc
>    diff is the only arithmetic available, so the pair branch stands as the fallback.
> 2. **"Explicit compare these two" needed a second, wider test.** `_wants_doc_to_doc()` is true on an
>    explicit pairing phrase (`_DOC_TO_DOC_PATTERN`) *or* on both documents' types being named
>    **together with a comparison verb** (`_PAIR_INTENT_VERB_PATTERN`). Naming alone — the Gap 387
>    signal — is what routed A4 to doc-to-doc: it names the PO and the credit note in one breath and
>    then asks what is owed, which no diff between those two documents answers.
> 3. **The clarify card had to be bypassed for two-document turns.** B5 ("which vendor needs
>    follow-up?") classifies as neither *read* nor *compare* and fell to the "read or compare?" card
>    one step *before* the routing defect — and that card is unanswerable with two documents on the
>    table ("read" which one?). When a turn carries two attachment ids and at least one document is
>    confirmed, the card is no longer the fail-safe; with nothing confirmed there is still nothing to
>    compute and the card stands.
>
> Implementation detail worth recording: the header diff, per-invoice line diff, comparison record
> and suggested actions were **lifted verbatim** out of `_run_attached_document_turn()` into
> `_compare_attachment_to_invoices()` so the one-document and two-document paths cannot drift apart.
> The session-wide blocks (`_amount_owed_block()`, `_contract_terms_block()`) are deliberately *not*
> in that helper — they must be summed once per turn, not once per document, or a credit note
> attached alongside a PO would be subtracted twice.

**A correction.** Thumbs-down with a note → `record_correction()` writes a `chat_correction` row
tagged with a §2.3 bucket. Review (founder, or a reviewer role later) either `promote_to_example()`
(certified Q→SQL / Q→plan), files a capability gap, or files a resolver gap. Weekly, `run_agent_eval.py
--taxonomy` reports bucket counts; a bucket that is not falling is the next task.

---

## 7. Data & schema changes

Add-only, dev rules (no backfill, no down/up ceremony):

| change | migration | notes |
|---|---|---|
| Views `v_vendor_spend`, `v_overdue`, `v_tax_summary`, `v_3way_match` | new | each tenant-filtered by a `WHERE tenant_id = current_setting(...)` or by the caller's parameter — decide in 29.5; views carry a comment with the metric definition |
| Table `certified_sql_example` | new | `tenant_id` nullable (global vs tenant-specific), `certified_by`/`certified_at` NOT NULL — an uncertified example cannot exist in this table |
| Table `chat_correction` | new | one row per thumbs-down with note |
| Chroma collection `knowledge_{tenant_id}` (+ `knowledge_global`) | none (Chroma) | metadata `kind ∈ {glossary, metric, example, playbook, rule_card}`, `region ∈ {IN, EU, US, ALL}`, `effective_from`, `source_url`, `owner`, `review_at` |
| `Invoice` model | none | no column changes; full records read what exists |
| Model registry | code | context 1,050,000; `recall_note` |

Single Alembic head confirmed via the Python API before and after each migration (`alembic.exe` is
blocked on this machine).

---

## 8. Tasks

Grouped into four tracks. Each task is independently completable and testable; §9 gives its check.

**Track A — close the migration (Step 1 leftovers)**
- **29.1** Registry: 5.6-family context → 1.05M/922k; `recall_note` on Luna; `long_doc` role +
  `get_long_doc_llm()` (falls back to fast). **Delete `gpt-5.6-sol` and `gpt-6-astra` now; keep
  `gpt-5.6-terra` until 29.10 decides the long_doc role** (decision 9). Update
  `model-deployment.bicep` comment. Set luna/luna/gpt-5-mini env on the six `caj-*-dev` jobs.
- **29.2** Judge calibration: `tests/golden_calibration.json` with **30 hand-graded turns now, 100
  with two raters before 29.13's flag flips** (decision 4); `run_agent_eval.py --calibration-set`
  reports Cohen's κ; **κ < 0.6 blocks every later accuracy claim in this feature.**
- **29.3** Failure taxonomy: `run_agent_eval.py --taxonomy` tags every failed golden turn with one of
  {no_route, no_evidence, wrong_evidence, no_computation, narration, judge}; baseline counts recorded.
- **29.4** Harness fixes from tasklist Step 2: `--fresh-tenants`; SQL eval fixed denominator (timeouts
  = wrong, n reported); extraction report lists all ground-truth fields with the composite as headline.
  Luna baseline re-run on the fixed harness → `runs/luna-baseline-<date>/`.

> **Build note, 2026-09-07 (tasks 29.1, 29.2, 29.3 as built).**
>
> **29.1.** The registry work landed as specified and the Azure half turned out to be already
> done. `az cognitiveservices account deployment list -n openai-invoicellm-dev -g
> rg-invoice-llm-dev` returns `gpt-5-mini`, `gpt-4o`, `gpt-5.6-luna`, `gpt-5.6-terra` and nothing
> else — `gpt-5.6-sol` and `gpt-6-astra` had already been deleted, and Terra is present as
> decision 9 requires — and `az containerapp job show` on all six `caj-*-dev` jobs shows
> luna / luna / gpt-5-mini with api-version `2024-10-21` already set. **No `az` mutation was
> run**; issuing a no-op `job update` would have created a new revision of six jobs for nothing.
> `infra/model-deployment.bicep`'s role comment was **wrong** — it claimed Terra had been
> deleted — and is rewritten. Two design points worth recording: the 5.6 family's context is
> **1,050,000 with a separate 922,000-token input budget** (`CatalogEntry.max_input_tokens`),
> because total context and usable prompt budget are different numbers; and `recall_note` exists
> because **a 1M-token window is not a 1M-token memory** — Luna's MRCR is ~41% against Terra's
> 89%+, which is the whole reason the `long_doc` role exists. `gpt-5.6-sol` and `gpt-6-astra`
> keep their catalog rows, marked `DELETED`: a deleted deployment still has historical telemetry
> and cost rows to price, and removing a row would silently reprice them at zero via
> `DEFAULT_SPEC`.
>
> **Env wiring completed 2026-09-07 (phase-2 P0.4, Gap 481).** 29.1 left the two roles
> readable only from code: `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME` and
> `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME` were on `Settings` but on no container, so both
> roles resolved by fallback and `params.dev.json` did not record which deployment was in
> force. Both are now params on `invoice-be.bicep`, `queue-worker.bicep` and
> `scheduled-job.bicep`, threaded from `08-apps.bicep` to all six module invocations that
> already take the judge param, with dev pinning chat_summary = `gpt-5-mini` (decision 2)
> and long_doc = `''` (inert until CP1) and prod carrying both keys empty. The wiring is
> pinned by `tests/test_model_role_env_wiring.py`, whose load-bearing test compares the
> bicep env names against the real `Settings` fields — pydantic ignores an unmatched name
> in silence, so a typo there is invisible everywhere else. `az bicep build` clean on all
> four files; **not deployed**, the push is the founder's.
>
> **29.2 — the result changes what the rest of this feature may claim.** κ = **0.151** on n = 36
> (agreement 0.444 against 0.346 expected by chance), against a gate of 0.6. **The gate fails.**
> The 2×2 is entirely one-directional: `both_pass 8, both_fail 8, judge_pass_human_fail 0,
> human_pass_judge_fail 20`. The judge never passes something a reader would fail, and fails 20
> of the 28 answers a reader marks correct against this file's own reference text. §2.5 already
> said "any chat delta under ~10 points is inside judge noise"; this is stronger than that — the
> **level** is wrong, not just the noise. Every accuracy claim in this feature is blocked until
> it clears, which is decision 4's rule applied to itself.
>
> The calibration file is honest about what it is. Every entry is
> `grader: "expected-text (founder to confirm)"`, the file declares `provisional: true` and
> `rater_count: 1`, and its `caveat` states that the rater is **the same session that wrote the
> code under test** — the exact bias decision 4's second rater exists to remove. Six entries are
> marked `FOUNDER TO CONFIRM` because the reference text does not decide them. `--calibration-set`
> calls no model, so the gate is free to check before any claim.
>
> **29.3.** Six buckets, deterministic, precedence earliest-in-the-pipeline-first so no turn can
> be counted twice, and the printer asserts the counts sum to the failure count. Baseline on the
> 2026-09-06 run: `wrong_evidence` 9, `no_computation` 9, `narration` 4, `judge` 4, `no_route` 2,
> `no_evidence` 0. The counts ride in every saved payload, printed only under `--taxonomy`, so a
> bucket trend costs nothing. **`no_evidence = 0` must be read with Gap 478** — the harness's
> context always carries the SQL results table, so that bucket cannot fire on this harness
> whatever the route did.


> **Build note, 2026-09-07 (task 29.4 a/b as built; phase-2 P1.1/P1.2, Gap 484).**
>
> **29.4b found something bigger than a denominator.** `digest_eval` grades SQL
> exec-correctness with `set(expected) <= set(fetched)` — but `run_turn()` never wrote
> `expected_invoice_numbers` into a turn record, so that branch had **never executed**,
> and every "SQL exec-correct %" this project has published came from its fallback: the
> judge's `accuracy_score >= 0.8`. §2.1's row (c) (32.3 / 40.7 / 44.4 / 28.0 / 44.4) is
> therefore a judge score labelled as a deterministic one, produced by the judge Gap 479
> later measured at κ 0.151. The row is annotated, not deleted — it is the measurement
> that led here. The ground truth is now recorded per turn, with `()` ("fetch nothing",
> a real expectation) kept distinct from `None` ("this case declares none", which stays
> unscored rather than counting as perfect).
>
> The denominator itself is now the **case set**: errored turns are graded, not dropped,
> and an errored turn fetched nothing so it scores zero with no special case — timeout =
> wrong by construction. `n`, `errored`, `no_statement` and `graded_by` ride in the
> payload so a percentage cannot be quoted without its base. The old behaviour is why one
> 36-case set reported n = 31/27/27/25/27 across five models.
>
> **29.4a `--fresh-tenants` is narrower than the task text implies, and the code says so.**
> "So cache and prior answers cannot leak between runs" is already guaranteed three times
> over — a new in-memory SQLite database per run, `get_cached_answer` stubbed to None, and
> Chroma stubbed with fixtures. What constant tenant ids still cost is the **persist path**
> (every run's `agent_eval_run` rows land under one tenant and cannot be separated) and any
> future run made without those stubs. `fresh_tenant_map()`'s docstring records that
> distinction so the flag is never cited as a fix for a leak it does not close.

**Track B — evidence and contract (chat without attachment)**
- **29.5** `fetch_full_records()` + `full_record_block()`; wired into the SQL route after ids are
  known and into the general route when the resolver binds an invoice; **cap = 25** (decision 1);
  **summary call on gpt-5-mini for this route, Luna stays on the attachment branches** (decision 2). Golden re-run; target: `no_evidence` bucket → 0.
- **29.6** `check_line_arithmetic()` in `document_comparison.py`; wired into
  `_computed_figures_block_for()`; the three line-check golden cases pass with the figure computed.
- **29.9** `_answer_contract_gate()` + `_abstain_payload()` on every route; provenance on every claim.
  Abstain wording per decision 3: name what is missing, state what *is* on file, offer the nearest
  next step.
- **29.12** Answer cache keyed on `(tenant, plan-or-normalised-question, attachment ids)`; the content
  branch's documented cache bypass becomes unnecessary and is removed.

**Track C — attachments**
- **29.7** Two attachments + invoice question: per-document comparison against each one's own invoice,
  merged; doc-to-doc only on explicit request. Probe turn B5 passes; A4 leaves the pair branch.
- **29.8** `scripts/attach_chat_eval.py` versioned; 16-turn probe re-run on Luna / gpt-5-mini / Terra
  with cache flushed and fresh sessions; results recorded under Gaps 470, 472, 473 and this feature.
  **Gaps 470/472/473 tick here.**

  > **Build note, 2026-09-06 (task 29.8, as built).** `scripts/attach_chat_eval.py` exists and is
  > versioned; the 16 turns, the eight generated documents, the `required`/`forbidden` regexes and the
  > confirm-card handling are in it, with `--flush-cache`, UTC-stamped fresh sessions, and the
  > deployment names in force written into every run JSON so a run cannot be misattributed.
  >
  > **Two of the three model legs ran.** gpt-5.6-luna **16/16** (from 8/16) and gpt-5-mini **15/16**
  > (from 10/16), run files under `docs/extraction_benchmark/runs/f29-probe-20260906/`. All five turns
  > that had failed identically on all three models — A4, A7, B3, B4, B5 — pass on both. gpt-5-mini's
  > single failure (B2) is a grading artefact, not a wrong answer. **Terra did not run**: its leg
  > stalled and was killed at the hard stop, and it moves to task 29.10, which decides the `long_doc`
  > role and re-runs it there. Gaps 470/472/473 tick on the two legs, because the original finding was
  > that all three models failed *identically* on agent logic — the model was never the variable.
  >
  > **The re-run earned its cost by finding two defects the unit tests could not.** Gap **475**: the
  > Apex credit note prints "Total Credit: -$21.60", so the ledger took the sign twice — once from the
  > document type, once from the printed total — and answered "amount owed 475.20" where the answer is
  > 432.00. Turn A4 **passed anyway**, because the `required` regex `432` matched the PO total quoted
  > in the sentence that contradicted the net. Gap **476**: task 29.7's own `_DOC_TO_DOC_PATTERN`
  > matched the bare phrase "both documents", which is B5's opening words, so B5 went straight back to
  > the branch 29.7 exists to move it off.
  >
  > Both were only visible by **reading the answers**, not the pass counts. That is a standing
  > instruction for this probe, and it is why the turn text is stored in full in each run JSON.
  >
  > **A grading weakness is recorded and not fixed:** A4's assertion can pass on a wrong net because
  > the expected figure also appears in the sentence denying it. Tightening the probe's assertions
  > (requiring the figure adjacent to "owed", or asserting on the payload rather than the prose once
  > Gap 474 is resolved) is follow-up work under this task.
  >
  > **Merged into the golden set 2026-09-07 (phase-2 P0.5, Gap 483).** The 16 turns are now
  > also `ATTACHMENT_CASES` in `benchmarks/agent_eval_golden_sample.py`, with `required` /
  > `forbidden` facts in `agent_eval_golden_facts.json` and the probe ids preserved
  > (`attach_a1`…`attach_b7`), so the branches Gaps 470/472/473 fixed are gradeable by the
  > same judge as everything else instead of by a private regex set. `attach_chat_eval.py`
  > is unchanged and kept. A drift test reads `SESSIONS` back out of the probe and compares
  > all 16 turns field by field, because two copies of the same questions would otherwise
  > diverge silently.
  >
  > **They are not yet runnable by the harness, and that is the open half.** Twelve need a
  > document attached; the probe gets its documents by uploading eight PDFs over HTTP and
  > waiting for the **queue worker** to extract them, while `run_agent_eval.py` runs
  > in-process with neither. `run_query_agent()` already accepts `attachment_id` /
  > `attachment_ids`, so the call site is fine — what is missing is seeding attachment rows
  > with their extraction results. **Task 29.10's `tests/golden_long_doc.json` needs exactly
  > the same seeding**, so it is one piece of work for both, and until it exists CP1's
  > "57 golden" is 36 golden plus a separately-run probe.
- **29.10** `tests/golden_long_doc.json` (5 cases: multi-page contract, 3-page statement, 2 long POs,
  long delivery note); Terra vs Luna on the attachment branches; role decided by the 2-pt rule; env +
  bicep for `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME`.

  > **29.10 result, 2026-09-07 — Luna kept, Terra deleted, role removed (Gap 489).** Both models
  > ran the five cases through `scripts/run_agent_eval.py --cases <the 5 long_doc ids> --fresh-tenants`
  > (`runs/f29-luna-longdoc-20260907/`, `runs/f29-terra-longdoc-20260907/`), hand-graded against
  > `tests/golden_long_doc.json` because the harness cannot score them (Gap 488):
  >
  > | case | golden | Luna | Terra |
  > |---|---|---|---|
  > | contract late fee | 1.5 %/month, clause 27.4 | pass (2.8 s) | pass (2.2 s) |
  > | PO outlier line | line 47, USD 212.75 | pass (3.5 s) | pass (3.8 s) |
  > | PO delivery term | partial shipments not permitted | pass (2.8 s) | pass (2.7 s) |
  > | statement unmatched line | BRL-201062 | harness (Gap 488 #3) | harness (Gap 488 #3) |
  > | delivery-note shortfall | lines 11, 29, 63 | harness (Gap 488 #4) | harness (Gap 488 #4) |
  >
  > Terra gains 0 points over Luna on the 3 gradable cases, so by the 2-point rule Luna keeps every
  > role. Founder 2026-09-07: "delete terra"; "lets delete AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME to
  > [not] maintain another unnecessary var". Done: `gpt-5.6-terra` deleted from
  > `openai-invoicellm-dev` (`az … deployment list` → gpt-5-mini, gpt-4o, gpt-5.6-luna); the
  > `long_doc` role, `get_long_doc_llm()`, the `Settings` field, `.env.example` line, bicep param /
  > env on all three compute modules and `08-apps`, and both params-file keys are removed. The
  > catalog row for Terra stays (historical cost rows must still price). Roles are now exactly
  > `primary | fast | judge | chat_summary`.

> **Build note, 2026-09-07 (tasks 29.6, 29.9, 29.12 as built; 29.5's measurement).**
>
> **29.6.** `check_line_arithmetic()` reads the invoice's own `items`, not the results table, and
> that is the whole point: the existing reconcile in `_computed_figures_block_for()` only fires
> when the generated SQL projected `line_qty`/`line_unit_price`/`line_amount`, which rules 6d and
> 11 discourage — so the golden line-check cases arrived with the lines in the record and no
> arithmetic done on them. Three rules are recorded in the code because each is a way to produce a
> *false* finding: a line with no quantity or unit price is **skipped, not zeroed**; its printed
> amount still counts toward the subtotal comparison; mismatches are never truncated by the
> reporting cap. Both halves render through one `_computed_block_wrapper()` so the model sees one
> block with one instruction, and the mismatch instruction sits in the **header** — an instruction
> placed where data sits reads as data, which a live gpt-5-mini demonstrated by copying one into a
> user's answer.
>
> **29.9, and where it stops.** The gate, the named-figure regeneration and the abstain payload
> are built, tested and live on the SQL route behind `ENABLE_ANSWER_CONTRACT_GATE` (default on),
> with the outcome on `ChatTurn.answer_gate` so the control is measurable. `result["provenance"]`
> is populated from 29.5's `FullRecordSet`. **`routers/chat.py::MessageResponse` was deliberately
> not widened** (Gap 474, founder go pending), so provenance reaches the cache, the telemetry and
> any in-process caller and **not the browser**. §6 step 6 says provenance is "attached to the
> response for the FE's existing citation rendering"; that half is built and not yet reachable,
> and the task stays `[~]` until Gap 474 is decided. The larger half of the test file is the
> half that proves the gate does **not** fire — on dates in three renderings, bare years, counts
> under ten, identifiers, and figures rendered differently from the row — because a gate with
> false positives replaces correct answers with abstentions.
>
> **29.12.** The bypass was removed by removing its premise. `_attachment_dimension()` folds the
> sorted attachment ids into the key, so the collision Feature 26's B1 protected against cannot
> happen; a turn with no attachment keeps a byte-identical key, so nothing in Redis is orphaned.
> The caching decision moved **up** to `_run_query_agent()`, above the attachment gate, where the
> ids are known and where `_attachment_answer_is_cacheable()` can refuse a confirm or clarify card
> — a card is a question, and replaying it after the user has answered is a loop. B1's test was
> amended rather than deleted: it now pins the new behaviour and still pins that the branch
> functions themselves contain no cache call.
>
> **29.5's golden re-run, reported as measured.** pass **22.2%** (8/36), judge accuracy 0.611,
> faithfulness 0.751, latency median 9.7 s, **$0.00248/turn**. Accuracy and latency beat both
> as-is baselines; the pass rate does not, and it is far from the 52.8% full-record result. This
> is **not** read as "29.5 failed", for two filed reasons: **Gap 478** — the harness grades
> against `recorder.context()` and never sees the full-record block, so 0 of 36 turns show it on
> a build that attaches it on three routes — and **29.2's κ of 0.151**, which says the pass metric
> itself is not currently trustworthy. The honest statement is that *the golden harness cannot
> presently measure this task*, and both blockers are filed rather than worked around.

**Track D — grounding and the generic layer**
- **29.11** `resolve_entities()`; automatic clarify on 0/>1; keyword lists demoted to fallback behind
  `ENABLE_CHAT_PLANNER=false` (still on) — measured by clarify-card rate on the probe → 0 for
  resolvable questions.

  > **29.11 built 2026-09-07 (phase-2 P2.1, Gap 490), unit tests only per the founder's 18:16
  > scope.** `agents/entity_resolver.py::resolve_entities(question, tenant_id, db_session,
  > attachments=None, recent_invoice_ids=None) -> ResolutionResult`. Four deterministic resolvers,
  > no model call: (1) invoice numbers — exact, case/whitespace-insensitive, parameterised,
  > tenant-scoped; a token that matches nothing exactly is compared with `difflib` against the
  > tenant's numbers and offered as a *suggestion* (`status = suggested`, ratio ≥ 0.80), never
  > bound; (2) vendors — "from / by / vendor / supplier / of X" and "X's invoices" matched by
  > substring, then `difflib` ≥ 0.85; one hit binds, several are `ambiguous`; (3) attachments —
  > "the attached / this document / the contract / the second PO" bound by count, document type
  > or ordinal; (4) session references — "the second one / the last invoice / that one" bound
  > against the previous turn's invoice ids. `ResolutionResult.needs_clarification` and
  > `.clarify_message()` build the clarify card that lists the candidates.
  > **Wiring** — `_run_query_agent()` calls it before `classify_query()` when
  > `ENABLE_ENTITY_RESOLVER` is on: an unresolved invoice or vendor mention returns a turn with
  > `content` = the clarify card and a new `entity_clarification` key (message + entities +
  > candidates), `stop_reason = awaiting_entity_clarification`, no model consulted; bound ids are
  > added to the RAG and CHAT routes' full-record lookups alongside 29.5's
  > `invoice_ids_named_in()`. Flag off (default, dev and prod) the block is skipped and routing is
  > unchanged. The keyword lists are **not** deleted (spec §4.2: fallback for one release).
  > **Not done, and said so:** the attachment resolver is unit-tested but not wired — the
  > attachment branches already receive explicit `attachment_ids` from the FE; the FE does not
  > yet render `entity_clarification` (it shows `content`, which carries the same text);
  > "probe clarify-card rate" was not measured (no live runs, founder 18:16).
  > **Evidence:** `tests/test_entity_resolver.py` **17 passed** on real Postgres
  > (`localhost:5433/invoice_db`) — exact, typo → suggestion, unknown → none, cross-tenant never
  > bound, substring vendor, fuzzy vendor above/below threshold, ambiguous vendor listed, invoice
  > number after "from" is not a vendor, attachment by count/type/ordinal, session ordinal, fail-soft
  > on a broken session, flag defaults False, and two flag-ON turns through `_run_query_agent`
  > (clarify stops the turn with no LLM call; a bound invoice goes through to the route).
- **29.13** `plan_turn()` + `CAPABILITIES` registry, flag-gated, **attachment branches first**
  (decision 8), gated by the 16-turn probe; then all routes once the golden set shows no regression and
  the 100-turn calibration (decision 4) is in; keyword lists deleted one release after the flag defaults on.
- **29.14** Semantic layer: 4 views + `METRICS` + `query_metric()` with a parameterised
  `WHERE tenant_id = :t` enforced by the AST guard, no RLS (decision 6); schema link prefers a metric;
  `alembic upgrade head` once. Target on the golden SQL set: +15 pts exec-correct vs 29.4's baseline.
- **29.15** Certified examples: table + Chroma index + `retrieve_examples()` (certified only) replacing
  the C4 static examples tail; seeded from every golden case whose SQL is verified; `certify_example()`.
  **Global rows only at first; `tenant_id` nullable for the flywheel** (decision 5).
- **29.16** Knowledge layer: `knowledge_{tenant}` collection, `KnowledgeDoc`, `index_knowledge()`,
  `lookup_glossary()`, `lookup_rule()`; glossary seeded (total / grand total / net / tax / due).
- **29.17** Regional rule cards — **India first** — one paragraph each with `source_url`,
  `effective_from`, `owner = founder`, `review_at`; the session drafts each card from a primary
  source it has fetched and cites (CBIC/GSTN), indexes it, and the founder spot-checks a sample
  (decision 7); then EU (EN 16931, mandates), then US. Playbooks (20–40) alongside. Compliance
  `verify` capability: deterministic field checks against a rule card's checklist.
- **29.18** Reranker (Cohere rerank-v4 on Foundry) between bge-m3 and the LLM — **only after** RAG
  recall@k is instrumented in 29.5 and shows ranking, not retrieval, as the limit. Chat tier pinned to
  minimal reasoning effort.
- **29.19** Flywheel: `chat_correction` table, `record_correction()` on thumbs-down,
  `promote_to_example()`; control-tower workbook panel "chat quality trend" (pass %, abstain %,
  bucket counts by week) fed from `agent_eval_summary`.

**Track E — rollout**
- **29.20** Rollout plan dev → soak → prod written (not applied); prod params untouched.

  > **29.20 written 2026-09-07 — see §10.1 below.** Not applied. `params.prod.json` untouched.

> **Phase-2 capability flags (P0.6, Gap 482, 2026-09-07).** Every capability in tasks
> 29.11 / 29.14 / 29.15 / 29.16 / 29.18 is gated by its own setting —
> `ENABLE_ENTITY_RESOLVER`, `ENABLE_SEMANTIC_VIEWS`, `ENABLE_CERTIFIED_EXAMPLES`,
> `ENABLE_KNOWLEDGE_LAYER`, `ENABLE_RERANK`, all default False, all wired through the three
> compute bicep modules and pinned false in both params files. The reason is arithmetic, not
> caution: the 2026-09-07 golden run took **7h39m** for 36 cases, so localising a CP2
> regression by re-running with one capability off at a time is not affordable. Instead each
> golden turn record now carries `route` and `capability_flags`, and attribution comes out of
> a single run. `ENABLE_SEMANTIC_VIEWS` gates *use* of the views, never their existence — the
> migration is add-only and runs regardless, so the flag can be turned off without leaving a
> query pointing at a view that is not there.

---

## 9. Verification Plan

Every DB- or API-touching task is verified against real Postgres (`localhost:5433/invoice_db`) and
the evidence line is written into the tracker at the time (hard rule 2). Every correctness decision —
arithmetic, sign handling, reconciliation, rate application, entity resolution, the answer-contract
gate — is deterministic code with its own tests; no prompt rule decides correctness (hard rule 3).

| task | check |
|---|---|
| 29.1 | `tests/test_model_registry.py` (context, recall_note, long_doc fallback); `az bicep build` clean; `az containerapp job show` on the 6 jobs shows the three env vars |
| 29.2 | `run_agent_eval.py --calibration-set` prints κ with n and rater count; recorded in the tracker; **gate: κ ≥ 0.6** |
| 29.3 | taxonomy output has one line per failed golden turn, every line tagged; counts sum to the failure count |
| 29.4 | `tests/test_extraction_benchmark.py` + harness on the 27 PDFs on fresh tenants; Status/Alert columns score again; SQL eval reports n and failure reasons |
| 29.5 | `tests/test_full_records.py` (all columns present, JSON parsed, cap respected, chunks attached, tenant-scoped); golden re-run: `no_evidence` = 0; cost/latency per turn recorded |
| 29.6 | `tests/test_compare_documents.py` line-arithmetic cases (match, understated, overstated, missing qty, half-cent tolerance); the 3 golden line-check cases pass with the computed figure in the payload |
| 29.7 | `tests/test_chat_attachments.py`: two docs + invoice question → two per-document comparisons merged; explicit "compare these two" → doc-to-doc; A4 payload carries the ledger from the per-document path |
| 29.8 | `attach_chat_eval.py` JSON per model committed under `runs/`; probe pass counts recorded; Gaps 470/472/473 evidence lines updated |
| 29.9 | `tests/test_answer_contract.py`: a narration with a figure not in the payload is regenerated once then abstains; provenance keys present on every claim; no false positive on dates/ids/percentages that *are* in the payload |
| 29.10 | `golden_long_doc.json` run on Terra and Luna, judged by the calibrated judge; decision recorded with the 2-pt rule applied — **done 2026-09-07, hand-graded (Gap 488), Luna kept, Terra deleted, role removed; `tests/test_model_registry.py` + `tests/test_model_role_env_wiring.py` 79 passed** |
| 29.11 | `tests/test_entity_resolver.py` (exact, fuzzy above threshold, typo → suggestion not invention, 0 → abstain, N → clarify with candidates, session reference "the second one"); probe clarify-card rate — **done 2026-09-07: 17 passed on real Postgres; probe rate not measured (no live runs)** |
| 29.12 | `tests/test_answer_cache.py`: same question, different attachment → different entry; content-branch bypass test removed with its invariant |
| 29.13 | `tests/test_chat_planner.py`: plan validated against registry; unknown capability rejected; planner never receives document text (asserted on the prompt); golden set no regression with flag on |
| 29.14 | migration applied, single head; each view returns tenant-scoped rows only (cross-tenant test); `query_metric()` results equal a hand-written query on seeded data; golden SQL delta vs 29.4 baseline |
| 29.15 | uncertified row never retrieved (test); top-5 retrieval deterministic for a fixed embedding; the C4 source-guard test updated to the new tail |
| 29.16 | `tests/test_knowledge_layer.py`: metadata filter by kind/region/tenant/effective_from; global vs tenant precedence; no cross-tenant leakage |
| 29.17 | each rule card has all five metadata fields non-empty (schema test); `lookup_rule()` returns the card whose `effective_from` ≤ today; compliance golden set (new, ≥10 cases) passes |
| 29.18 | recall@k before/after rerank on the golden RAG cases; adopt only if recall@5 improves |
| 29.19 | `tests/test_chat_corrections.py`; workbook JSON validates; a promoted example is retrievable |
| 29.20 | document only — **done 2026-09-07, §10.1** |

Track-boundary checkpoints: full backend suite `pytest -q --ignore=tests/us` at the end of Tracks
A, B, C and D, compared file-for-file against the standing 43-failure baseline; no new failure.

---

## 10. Rollout to Azure — the steps, in order

Dev only. Every step is gated by the previous one's evidence; nothing here touches `params.prod.json`.

1. **Land Step 5** — 29.7 (B5), 29.8 (probe re-run). Gaps 470–473 tick. Full suite. **Commit** (founder
   says when). `deploy-dev.yml` fires on push to the dev branch for changed paths → `ca-invoice-be-dev`
   and `ca-queue-worker-dev` rebuild via `_deploy-service.yml` (immutable tag = SHA, rollback target
   captured).
2. **Registry + jobs** — 29.1: `az containerapp job update` ×6 with the three model env vars;
   `az bicep build` on `08-apps`, `sweep-jobs-only`, the three compute modules; `params.dev.json`
   gains `azureOpenAiLongDocDeploymentName` (empty until 29.10). Deploy via `deploy-dev.yml`
   `workflow_dispatch` for infra-only changes.
3. **Measure before changing** — 29.2 (κ), 29.3 (taxonomy), 29.4 (harness + Luna baseline). Local
   only; burns Azure tokens on the dev OpenAI account; founder starts each run.
4. **Full records + line arithmetic + contract gate** — 29.5, 29.6, 29.9, 29.12. Golden re-run
   locally against dev DB; commit; push → dev deploy. Soak: the nightly quality job (never the deploy
   pipeline — Gap 312 rule) runs the golden set on the dev stack; the control-tower workbook shows
   pass %, abstain %, p95, $/turn.
5. **Long-doc role** — ~~29.10 decides Terra vs Luna~~ **decided 2026-09-07: Luna; Terra deleted; the role and its
   env var removed (Gap 489)**. Nothing to deploy for this step beyond the bicep cleanup.
6. **Resolver, then planner** — 29.11 ships with keywords still on; soak one week of nightly runs;
   29.13 behind `ENABLE_CHAT_PLANNER=false`, flipped in `params.dev.json` only after the golden set
   shows no regression with it on.
7. **Semantic layer + certified examples** — 29.14 migration: `alembic upgrade head` against dev
   Postgres from the deploy job's migration step (the existing pattern); 29.15 seeds examples via a
   one-off script run locally against dev; commit; deploy. Golden SQL delta recorded.
8. **Knowledge layer** — 29.16 collection created on first index; 29.17 India cards authored and
   verified, indexed by `index_knowledge()` from a versioned YAML under `docs/knowledge/`; deploy;
   compliance golden set on the nightly job.
9. **Reranker** — 29.18 only if 29.5's recall instrumentation says ranking is the limit; Cohere
   rerank-v4 deployed on Foundry via `04-ai.bicep`; env `COHERE_RERANK_DEPLOYMENT_NAME`.
10. **Flywheel + workbook** — 29.19; from here the weekly taxonomy drives the next task.
11. **Prod** — 29.20 writes the plan (§10.1): prod deployment of luna/luna/gpt-5-mini via
    `params.prod.json` and `deploy-prod.yml` (release tag, required-reviewer environment), preceded by
    a 2-week dev soak with the nightly job green and the workbook trend flat-or-up. **Not applied in
    this feature.**

---

### 10.1 Task 29.20 — the rollout plan as written (2026-09-07, not applied)

**What ships from Feature 29.** Model roles `primary`/`fast` = `gpt-5.6-luna`, `judge` =
`gpt-5-mini`, `chat_summary` = `gpt-5-mini` (falls back to judge), api-version `2024-10-21`;
full-record chat context (29.5), Python line arithmetic (29.6), the answer-contract gate (29.9),
attachment-keyed answer cache (29.12), `provenance` / `abstention` on `MessageResponse` (Gap 474),
the entity resolver behind `ENABLE_ENTITY_RESOLVER` (29.11), and the five capability flags all
default False (Gap 482). No schema migration. No prompt-only correctness rule.

**Stage 1 — dev (now).** Founder commits and pushes on their word; `deploy-dev.yml` rebuilds
`ca-invoice-be-dev` / `ca-queue-worker-dev` on the changed paths and the infra `workflow_dispatch`
re-applies `08-apps.bicep` (drops the `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME` env from be, worker
and the six jobs; nothing else changes in the container env). Verify: `az containerapp show` env
lists no `LONG_DOC` key; `az cognitiveservices account deployment list` = gpt-5-mini, gpt-4o,
gpt-5.6-luna. `ENABLE_ENTITY_RESOLVER` stays **false** in `params.dev.json`.

**Stage 2 — dev soak (7 days).** The nightly quality job (never the deploy pipeline — Gap 312)
runs the golden set; the control-tower workbook shows pass %, abstain %, p95 and $/turn. Exit
gate: pass % on the 36 no-attachment cases within 2 pts of the 2026-09-07 interim
(`runs/f29-baseline-20260907/`, 75.0 % / SQL 66.7 % n=39) and no new `judge`-bucket failures.
Blocked until Gaps 478 / 480 / 488 are worked: today the harness cannot see the full-record
block, fails correct abstentions, and cannot score the long-doc cases, so the soak number is
not yet trustworthy — that is the honest precondition, not a formality.

**Stage 3 — resolver on, dev only.** Flip `enableEntityResolver` to true in `params.dev.json`
alone; re-run the golden set; exit gate is the clarify-card rate on resolvable questions = 0 and
no pass-% regression. Rollback is the same param back to false.

**Stage 4 — prod (not in this feature).** `params.prod.json` diff, listed here and **not
applied**: `azureOpenAiDeploymentName` gpt-5-mini → `gpt-5.6-luna`; add
`azureOpenAiFastDeploymentName` = `gpt-5.6-luna`, `azureOpenAiJudgeDeploymentName` =
`gpt-5-mini`; `azureOpenAiChatSummaryDeploymentName` stays empty (judge fallback); all five
`enable*` flags false. Prod OpenAI deployments to create: `gpt-5.6-luna`, `gpt-5-mini`
(no Terra). Preceded by a green Stage 2, `deploy-prod.yml` with the required-reviewer
environment, and a release tag. Rollback: previous image tag + previous params.

**Out of scope for this plan.** `gpt-4o` deletion (unused; catalog row kept for pricing),
`tests/test_a3_streaming.py` and the other pre-existing suite failures noted in the tasklist,
and everything moved to Feature 30.

## 11. Decisions — all nine ruled by the founder, 2026-09-06

| # | question | decision | where it lands |
|---|---|---|---|
| 1 | Full-record cap | **25 invoices** per turn; beyond that, ids + count and a prompt to narrow | `Settings.CHAT_FULL_RECORD_MAX_INVOICES = 25` (29.5) |
| 2 | Chat summary model per route | **Split**: gpt-5-mini narrates the full-record route, Luna narrates the attachment branches; revisit after 29.8's probe re-run | 29.5, 29.10 |
| 3 | Abstain wording | **Name the gap and offer a next step** — "I can't confirm X: <what is on file>. Want me to <nearest thing>?" | `_abstain_payload()` (29.9) |
| 4 | Judge calibration size | **30 hand-graded turns now** (unblocks Tracks B/C); **100 with two raters before `ENABLE_CHAT_PLANNER` flips on**; κ ≥ 0.6 at both points | 29.2, gate on 29.13 |
| 5 | Certified-example scope | **Global now, tenant-specific later** — `tenant_id` ships nullable; tenant rows only via the flywheel | 29.15, 29.19 |
| 6 | View tenant filter | **Parameterised `WHERE tenant_id = :t`** from `query_metric()`, enforced by the existing AST tenant guard (Gap 414); no RLS | 29.14 |
| 7 | Rule-card verification | **Session drafts from a fetched primary source and cites it; founder spot-checks a sample** — never authored from model memory; `owner = founder` on every card | 29.17 |
| 8 | Planner rollout order | **Attachment branches first**, gated by the 16-turn probe; SQL route after the golden set shows no regression | 29.13 |
| 9 | Terra | **Keep Terra until 29.10 runs; delete Sol and Astra now** — *29.10 ran 2026-09-07: Terra deleted, role removed (Gap 489)* | 29.1, 29.10 |

No open decisions remain. The spec is ready for the founder's build go.

### Build note — the judge (Gap 479, 2026-09-07)

§2.5 said the judge was noisy. Reading the 36 judged answers showed it was **biased down**, not
noisy: 28 reference-correct answers, 8 judge passes, zero false passes, κ 0.151. Four mechanisms,
all in `services/agent_eval.py`: a 3-valued accuracy with the floor above its middle value; prose
references whose bonus notes and negative instructions were graded as required facts; faithfulness
judged against the recorder's evidence rather than the app's (Gap 478); and an AND of three floors.
The founder confirmed ~80% by reading the answers and approved all four fixes.

What changed, and what did not:
- **References are now structured** in `benchmarks/agent_eval_golden_facts.json` (`required` /
  `forbidden` / `notes`); the prose `expected_answer` is untouched and stays the human reference.
- **Accuracy is a checklist**: met ÷ required, forbidden hit → 0. The prose is not shown to the judge.
- **Pass = accuracy ≥ 0.70**, with faithfulness 0.0 still a fail. Faithfulness and relevance are
  diagnostics.
- **Evidence = `judge_evidence.context`** (Gap 478), unioned with the recorder's.
- Judge deployment, floors, and the 36 questions are unchanged.

Consequence for §2.3's numbers: the "pass %" column of every run before 2026-09-07 was produced
by the old rule and is not comparable to runs after it. Task 29.2's calibration must be re-run on
the new rule, and decision 4's 100-turn set is still owed.


### Scope note — split to Feature 30 (2026-09-07)

**Tasks 29.14–29.19 have moved out of this feature**, verbatim, into BE Feature 30
"Business Intelligence" (`feature_30_business_intelligence.md`), where they appear in §5 as
**30.3–30.4, 30.8, 30.7, 30.9–30.11, 30.14 and 30.13**. Nothing was deleted here and nothing
above this line was rewritten — the task text stays in §8 as the record of where the work was
first specified, and Feature 30 is now the place it is built.

The founder's framing, which is what re-scoped it:

> "the separate spec is for giving additional intelligence to end user while a document is
> uploaded … by upload I mean the chat area document upload only … temp intelligence only
> when a financial document is attached in chat which are not invoice type"

That is a different product surface from this feature. Feature 29 is about **how the model is
grounded and what it may claim**; Feature 30 is a **temporary insight block posted into the
chat when a non-invoice financial document — PO, quotation, contract, credit or debit note,
statement, remittance, delivery note — is attached**. The semantic views, certified examples,
knowledge layer, regional rule cards, reranker and correction flywheel are the substrate that
insight block needs, so they belong with it.

**What stays here.** Feature 29 now closes at **29.1–29.13 + 29.20**, plus **Gap 474** and the
**CP1 baseline**. Tasks **29.11** (entity resolver) and **29.13** (planner + capability
registry) deliberately stay: they are what make attachment chat *generic* rather than a stack
of keyword branches, and Feature 30's insight block is a consumer of that generality, not a
replacement for it.

**Consequences for the checkpoints in the phase-2 tasklist.** CP2's live eval becomes
100 golden + SQL eval with **the entity resolver as the only flag on**; CP3's becomes
100 golden with **the planner on**. The flags for the moved tasks
(`ENABLE_SEMANTIC_VIEWS`, `ENABLE_CERTIFIED_EXAMPLES`, `ENABLE_KNOWLEDGE_LAYER`,
`ENABLE_RERANK`) were added by phase-2 P0.6 and **stay in `config.py` and in bicep, all
default False** — they are Feature 30's switches now, and removing them would only have to be
undone.

**29.13 moved to Feature 30 as 30.16 on 2026-09-07 (founder: "29.11 only, then close").** The
planner and the capability registry leave this feature as well, deferred into Feature 30.
**29.11 (entity resolver) stays** — it is what lets attachment chat resolve *what the user
meant* without a keyword list, and Feature 30's insight block is a consumer of that, not a
replacement for it. Feature 29's remaining path is therefore: **CP1 baseline → 29.11 entity
resolver → the 100-turn golden set → CP2 (100 golden, resolver flag on, κ against the founder)
→ 29.20 rollout plan → close.**

**Re-scoped again 2026-09-07 18:16 (founder: "once luna and terra is compared and finalised we
will code accordingly and mark feature completed, i dont want your nonsense testing and
baselining").** CP1, CP2, the 100-turn set and every further live run were removed. The path
became: 29.10 comparison → code the result → 29.11 (unit tests only) → 29.20 → close. **Closed
2026-09-07**: 29.10 (Luna kept, Terra deleted, role removed — Gap 489), 29.11 (Gap 490), 29.20
(§10.1). Left open and filed, not hidden: Gaps 477 (mock/re-baseline/fix split), 478, 480, 488
(harness), and the FE half of Gap 474 (FE Gap 470).


### Amendment to decision 4 — calibration raters (2026-09-07)

Appended, not a rewrite; the table above stands as it was ruled on 2026-09-06.

Decision 4 originally required **two raters** on the 100-turn calibration set. The founder
ruled on 2026-09-07 (**"Me alone, 100 turns"**) that calibration is **judge versus the
founder — one rater, 100 turns, gate unchanged at κ ≥ 0.6**. No second rater is sought, and
task 29.2 / phase-2 P2.7 no longer waits on naming one; the founder grades each turn from the
case's expected text.

The bias a second rater existed to remove is still real, and is now handled by *who* the rater
is rather than by how many there are: the 2026-09-07 calibration file records that its verdicts
came from the same session that wrote the code under test, which is precisely the conflict the
founder is not subject to.
