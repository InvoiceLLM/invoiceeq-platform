# Feature 23: AI Control Tower

One place that answers, for every AI call this application makes: what ran, who triggered it, how
often, how well it performed, what it cost, and whether a cheaper/faster model could have done the
same job. Scoped to this application only — not an org-wide platform.

## The real call sites (the registry)

Confirmed by reading the code, not assumed:

| Agent | File | Model | Volume driver |
|---|---|---|---|
| Extraction (inbound) | `agents/extraction_agent.py` | Azure OpenAI gpt-5-mini | Every ingested invoice |
| Extraction (outbound) | `agents/outbound_extraction_agent.py` | Azure OpenAI gpt-5-mini | Every outbound invoice |
| Chat classify + SQL/RAG/CHAT fork | `agents/query_agent.py` | Azure OpenAI gpt-5-mini | Every chat turn (live default path) |
| SAGE orchestrator (Phase 2) | `agents/sage_orchestrator.py` | Azure OpenAI gpt-5-mini | Every chat turn once `ENABLE_AGENTIC_SAGE` is on (off today) |
| Trainer / EVOLVE correction loop | Feature 18 | Azure OpenAI gpt-5-mini | Each alert-anchored correction |
| SENTINEL audit checks | tax/payment-status detectors | **No LLM** — corrected 2026-08-21 during Phase 1. Both named detectors (`detect_tax_component_term`, `detect_payment_status_question`) are pure regex, and no other audit path calls a model. SENTINEL's model cost is the `extraction.*` calls it audits. | Every extracted invoice |
| Dashboard insights | `routers/dashboard.py` | Azure OpenAI gpt-5-mini | Every cache miss on the Actionable Insights panel (1h TTL per tenant) |
| Trainer QA-panel summary | `routers/trainer.py` | Azure OpenAI gpt-5-mini | Every QA-test turn against a not-yet-ingested uploaded sample |
| Embeddings | `chroma_client.py` | BAAI/bge-m3 (local, not billed per-call) | Every indexed page |

The last two rows (dashboard insights, trainer QA-panel summary) were added 2026-08-21 after Phase 1
found them: two real, billable call sites the original registry had missed. Both are now
instrumented, so nothing this application sends to a model is outside the cost rollup.

This table is small enough to stay a static doc section, not a dynamic registry service.

## What already exists — reuse, don't rebuild

- **Structured request logging**: every request already emits JSON logs with `request_id`,
  `trace_id`, `duration_ms` (`logging_config` module) — confirmed live in Azure. Missing only the
  agent name, model name, and token counts.
- **Application Insights**: `appi-invoicellm-dev` already exists, backed by `law-invoicellm-dev`,
  90-day retention. This is the right home for LLM-call-level telemetry (`customEvents` /
  `dependencies`), not raw container stdout parsing.
- **Quality feedback**: `ChatFeedback` table (Gap 54) already captures thumbs up/down per chat
  answer.
- **Golden-question regression banks**: `tests/test_chat_sql_quality.py` (71 cases),
  `tests/test_rag.py` (56 cases) already exist as accuracy baselines for the chat path.
  **Corrected 2026-08-21, after reading them to build Phase 3**: they are not accuracy baselines.
  Both are mocked unit tests of pipeline *mechanics* against a scripted LLM, with no expected
  natural-language answer anywhere in either file — nothing in them can be scored for accuracy as-is.
  Their question *phrasings* are real and reusable, and Phase 3 reuses 9 of them. The repo's actual
  answer-bearing banks are `tests/{us,india,eu}/chat_question_bank.md` (question + reference answer +
  grading rubric), which need a live seeded tenant to run against.
- **A parity-harness pattern already being built**: `tests/test_agentic_sage.py` +
  `tests/agentic_sage_parity_cases.py` (Feature 21 Phase 2) are the same shape a substitution
  test needs — replay a fixed case set against a candidate, compare output.

## Architecture

1. **Telemetry**: each agent call wraps its LLM invocation and emits one Application Insights
   custom event — `agent_name`, `model`, `tokens_in`, `tokens_out`, `latency_ms`, `status`,
   `tenant_id`, `request_id` (ties back to the existing structured log line via the same ID).
2. **Cost**: a scheduled query (KQL, run nightly) multiplies `tokens_in`/`tokens_out` by that
   model's published Azure OpenAI rate, rolled up by agent/day/tenant. No new storage — this is a
   query over the telemetry already landing in Application Insights.
3. **Quality**: existing `ChatFeedback` thumbs-up/down, plus a scheduled run of the existing golden
   sets against the live model, with pass/fail persisted (new small table, `agent_eval_run`) so
   quality trend is queryable over time, not just "last run passed."

   **Component-level scoring, not one blended number** (decision, 2026-08-21): a single
   faithfulness/relevance/accuracy score per turn tells you *that* an answer was bad, not *which
   part of the pipeline* to fix. `agent_eval_run` scores three pipeline stages separately, each with
   its own mechanism — not the same check run three times:

   | Component | What it isolates | How it's scored |
   |---|---|---|
   | **Context builder** (`identify_invoices`/`get_full_record`/`aggregate`/`search_invoices`) | Did retrieval fetch the *right* underlying data, independent of how the LLM reasoned over it | Deterministic — compare fetched invoice_id(s)/fields against the golden set's known-correct set. Retrieval precision/recall, no LLM judge needed. |
   | **System prompt / orchestration** | Given whatever was fetched (right or wrong), did the model stick to only that data and pick the right tool | Mostly mechanical — the groundedness check already proposed for Feature 21 (extract every number/claim in the answer, verify it traces to a fetched field or a `compute()` output). Traceability, not domain correctness. |
   | **Skilled persona** | Given correct data and correct instruction-following, did the model apply domain expertise correctly (IGST vs. CGST/SGST, RCM's zero-tax being correct not missing, vendor-name-as-category judgment) | Needs its own dedicated golden set of domain-knowledge questions, LLM-judge scored against known-correct reasoning — the one component that genuinely needs judgment, not mechanical checking. |

   A bad answer then decomposes into a diagnosis ("context builder fetched the wrong invoice" vs.
   "right data but an uncited number" vs. "right data, correctly cited, wrong tax reasoning") instead
   of one number that says only "something was wrong." `agent_eval_run` gains three nullable score
   columns (`context_score`, `orchestration_score`, `persona_score`) alongside the existing
   pass/fail, so each is its own trend line on the workbook, not folded into one average.

   **Built 2026-08-21** — see "Component-level scoring as built" for the three mechanisms as
   implemented, the migration, and the one place the table above turned out to be optimistic: the
   persona component's "own dedicated golden set of domain-knowledge questions" does not exist and
   was not written in that pass.
4. **Substitution**: extend the existing parity-harness pattern to every agent in the registry
   table above, not just SAGE. Periodically replay each agent's golden set against one cheaper
   candidate model; report pass-rate delta and cost delta side by side. A model swap is only
   proposed when the golden set still passes at an acceptable rate — cost is never compared without
   the quality floor next to it.
5. **Dashboard**: an Azure Monitor **workbook** against Application Insights — no new tool, no new
   hosting. A small internal admin page in `invoice-fe` is a fallback if a richer UI is wanted
   later, not needed for v1. **The workbook must show trend, not just a current snapshot**
   (decision, 2026-08-21) — cost, quality (faithfulness/relevance/accuracy), and health each get a
   day-over-day line/series, not a single point-in-time number, so a regression on any of the three
   is visible as "changed since yesterday," not something that has to be manually compared across
   separate one-off checks. All three (observation, evaluation, health) share the same time axis in
   the same workbook so a cost spike, a quality drop, and an alert firing on the same day are
   visible together, not three things you'd have to notice separately.
6. **Health/alerts, folded into the same workbook**: this resource group already has 25+ real
   alert rules (Feature 20) — CPU/memory/restart-loop/5xx per Container App, Postgres
   CPU/storage/connections, Azure OpenAI and Document Intelligence client-errors, storage
   availability/egress-anomaly, Key Vault availability, DLQ poison-message — wired to action
   groups `ag-invoicellm-dev` / `ag-invoice-llm-dev` (confirmed live, 2026-08-21; the two
   similarly-named action groups are worth a separate check, not verified here). Add an **Alerts**
   step (built-in Workbooks step type, queries `Microsoft.AlertsManagement` across the resource
   group) plus a Resource Health tile per resource, as one more tab in the same workbook — no new
   alert rules needed, this reuses Feature 20's work rather than duplicating it.

## Phases

- **Phase 1 — Telemetry** — **built 2026-08-21**: add agent/model/token fields to the existing
  structured logger; emit as Application Insights custom events. No behaviour change to any agent.
  See "Phase 1 as built" below.
- **Phase 2 — Cost + quality dashboard** — **built 2026-08-21, not deployed**: nightly cost rollup
  KQL query (`infra/monitoring/llm_cost_rollup_nightly.kql`) and the workbook
  (`infra/monitoring/ai_control_tower.workbook.json`) wiring `customEvents` (cost/latency),
  `agent_eval_run` events (quality) and Azure Resource Graph (alerts) onto one shared time axis.
  See "Phases 2 and 3 as built" below — including what is genuinely blocked on a founder action.
- **Phase 3 — Scheduled golden-set regression** — **built and really run 2026-08-21; the
  *schedule* is not**: `agent_eval_run` table + `services/agent_eval.py` scorer +
  `scripts/run_agent_eval.py` runner, run for real against both chat paths (36 turns, real Azure
  gpt-5-mini). No cron/ACA job is wired yet, so "scheduled" is still a human running the script.
  **Extended later the same day**: the two judge failure modes that run surfaced are fixed, and the
  three component-level scores are built (migration `c4a91e77b208`). Neither change has been run
  against a live model — the scoring changes mean pre-fix and post-fix figures are not comparable,
  and the post-fix numbers do not exist yet.
- **Phase 4 — Substitution testing**: extend the parity-harness pattern to extraction and chat
  first (highest volume/cost), report cost-vs-quality deltas for one cheaper candidate model at a
  time. Recommendation only — a model swap is a founder decision, this feature never auto-switches
  a model in production.

## Observability primitives — Run, Trace, Thread (added 2026-08-21)

The premise: for a non-deterministic agent, the execution trace is the source of truth, not the
code. This isn't new practice here — roughly sixty chat/RAG gaps were each diagnosed by reproducing
the failure live and reasoning from the actual run. What's missing is that none of it is a
**standing asset**: every gap was verified once, at closure, and nothing re-runs them. This section
turns that informal loop into one.

Mapped onto the real graph in `agents/sage_orchestrator.py`:

| Level | What it is in SAGE | Captures |
|---|---|---|
| **Run** | One LLM call — a `_plan_node` invocation, a `_synthesize_node` invocation, or the LLM inside `identify_invoices`/`search_invoices`/`aggregate` | Assembled system prompt, tool definitions offered, model output including tool calls, tokens, latency |
| **Trace** | One full turn — `plan → act → plan → … → synthesize` or `→ clarify` | Node sequence, every tool call with its real result, generated SQL, `stop_reason`, total call count. `MAX_TOOL_CALLS`/`tool_call_budget_exhausted` are trace-level properties, currently invisible outside a debugger |
| **Thread** | A chat session across turns | Where this codebase is weakest — Gap 237 (follow-up dropped rows) and Gap 276 (prior SQL reused after a topic change) are both context-drift failures, and neither is observable today. A thread has to be reconstructed from `ChatMessage` rows plus each turn's trace; "drift" as a signal doesn't exist yet |

Run-level and Trace-level capture are mostly achievable by extending Phase 1's existing
`tracked_llm_call()`/`track_agent_call()` (already real, already wired into `sage.planner`/
`sage.synthesis`) rather than new instrumentation — the primitive already exists, it just doesn't
yet persist the full prompt/tool-call detail a Trace needs, only the summary fields a cost/latency
rollup needs. Thread-level capture needs new work: no mechanism today reconstructs a session's turn
sequence with drift detection.

## Evaluation tiers, seeded from gap history

Rather than inventing synthetic eval cases, mine the gaps this repo already diagnosed —
`docs/test_evidence/`, `tests/realworld_tenant/`, and `tests/us/` already hold reproducible
questions and expected answers/ground truth for a meaningful share of them (confirmed present:
`chat_question_bank.md`, `ground_truth_line_items.md`, and per-gap reproduction folders in both
locations — exact count of how many closed gaps this covers needs a real pass through the tracker,
not estimated here).

**That pass has since been made** (2026-08-21, `scripts/seed_golden_bank.py`), and the estimate the
sentence above declined to give turns out to have been worth declining: the evidence files yield
**87 reusable cases** but attribute only **8 of 53** closed answer-quality gaps. They are rich in
questions and nearly empty of gap linkage — only `live_test_results.md`'s Notes column and
`tests/agent_eval_golden_sample.py` tie any question to a gap number at all. Real numbers and the
reason in "The vendor-agnostic framework as built" below.

| Tier | What it judges | Coverage | Caveat |
|---|---|---|---|
| **Single-step (Run-level)** | Did `plan` choose the right tool? Did `identify_invoices` emit the right filter? | Fast, sharp pass/fail | **Known expiry**: Feature 21's rewrite replaces `query_invoices` with `identify_invoices`/`get_full_record`/`aggregate` — any single-step suite written against today's tool set needs rewriting once that lands (in progress as of this doc). Don't over-invest here before that rewrite settles. |
| **Trace-level** | Full turn — final answer plus trajectory | Where most gap history lives (Gaps 263-276 were all found this way) | Cheapest to author — input is just the user's question, same shape as the eval round already run (36 turns) |
| **Multi-turn (Thread-level)** | Follow-up validity — turn 3 depends on turn 2 being right | Only tier that catches Gaps 237/276-shaped failures | Hardest to automate generally. Scope down to a **bounded** version — fixed 2-3 turn scripts with pinned expectations — rather than promising general multi-turn testing |

**The golden question bank**: one question per closed gap, expected answer or expected property,
runnable pre-merge. Seed from the evidence files above rather than writing fresh where possible.
Gap 287 — a faithfulness change that regressed Gap 263's already-fixed behavior and was only caught
by a user, not a test — is the concrete cost of not having this yet.

**Built 2026-08-21, with the aspiration corrected**: "one question per closed gap" is not what the
seed produces and not what the source data can support. What exists is 87 *tenant-regression*
questions with reference answers, 79 of them directly gradeable — a real standing asset where there
were 9 hand-written cases, but organised per tenant, not per gap. Gap 287 itself has no case: it is
one of the 45 that still need one written.

## Where each tier runs

- **Offline** (golden bank, pre-merge/nightly): a suite requiring real LLM calls is not free per-commit
  — cost and latency need a real number before deciding pre-merge-gate vs. nightly-only. Belongs on
  whichever GitHub Actions workflow already runs the backend test suite, gated by cost, not assumed.
- **Online** (live traces, no ground truth): alert on signal shapes already proven real in this
  repo's own history, not hypothetical — budget-exhaustion rate, clarification rate, zero-result
  rate (Gap 224's false-confident-zero shape), turns exceeding a latency threshold (Gap 278's
  shape), thumbs-down clustering.
- **Ad hoc** (exploratory, over production traces): once Trace-level capture persists real data,
  this is plain SQL over `agent_eval_run`/`ChatMessage` — no new platform needed to start.

## The closed loop: Identify → Extract → Scrub → Codify → Refine

Identify/Extract/Refine already happen manually per gap. Scrub and Codify are the two steps worth
making repeatable — and scrubbing is a hard constraint, not a detail.

**What a captured trace actually contains**: the assembled system prompt (with `tenant_stats`),
real vendor/customer names, invoice numbers, GSTINs, bank details from `payment_instructions`, full
monetary values. This cannot leave the production boundary or enter a committed test fixture
unscrubbed. What must survive scrubbing for the reasoning error to stay reproducible — the shape of
the question, the shape of the wrong answer, the category of mistake — versus what must be
redacted — real names/IDs/amounts — is itself a **Decision required**: too aggressive and the bug
stops reproducing, too light and real customer data ends up in git history.

The two existing simulated test tenants (referenced in prior test-evidence work) may serve as a
scrubbing-free safe corpus for anything reproducible there — worth confirming which gaps can be
reproduced against synthetic tenant data alone versus which only manifested against real tenant
data and therefore need scrubbing or must stay production-only.

**SOC 2 implications**: trace retention period, access control, and whether a trace constitutes
customer data are open questions this doc doesn't resolve — **Decision required**, not assumed.

**Codify**: the mechanical path from a captured failing trace to a permanent golden-bank test case
should be automatic when a gap closes, not dependent on someone remembering to add it — the actual
mechanism (a script, a manual step with a checklist, part of the gap-closing PR template) is a
**Decision required**. The *extraction* half of that path now exists as
`scripts/seed_golden_bank.py` (see below); the trigger — what makes it run when a gap closes — does
not.

## The vendor-agnostic framework as built (2026-08-21)

Three of the pieces the sections above scope are code, not vendor selection, and were built the same
day the sections were written. **No vendor was chosen, no dependency was added, and nothing in
`telemetry.py` / `agents/sage_orchestrator.py` / `agents/query_tools.py` was touched** (concurrent
Feature 21 work owns those files).

### File coordinates

| File | Function / symbol | What it does |
|---|---|---|
| `scripts/seed_golden_bank.py` (new) | `parse_question_bank()` | Parses `Qn[ (annotation)]. <question>` + `Answer:`/`Matching:`/`Computation:` out of the four per-tenant `chat_question_bank.md` files. Also turns each `(follow-up on Qn)` annotation into an ordered thread link. |
| | `parse_live_test_results()`, `attach_live_verdicts()` | The **only** gap-attribution source in the repo's evidence: the `Notes` column of `live_test_results.md`. Splits on unescaped `\|` only, because the `Actual` column embeds markdown tables. Matched to bank questions by number, not text (the tables paraphrase long questions). |
| | `parse_test_evidence()`, `_retrieval_probe_cases()`, `_session_capture_cases()` | Walks `docs/test_evidence/gap*/`. Retrieval probes (`query` + `expected`/`expect`) become deterministic Run-level cases; `raw_turns_*.json` captures become ordered thread scripts. A *post-fix* capture's observed answer becomes a provisional expectation flagged `needs_review`; a *pre-fix* repro's does not — that answer is the bug. |
| | `parse_agent_eval_golden_sample()` | Imports `tests/agent_eval_golden_sample.py`, the one existing source that is committed, answer-bearing *and* gap-tagged. |
| | `extract_gap_numbers()` | All four spellings this repo actually uses: `Gap 263`, `gap270`, `Gaps 263/264`, `BE Gaps 244 / 240 / 243 / 239`, `Gaps 228-232`. |
| | `deduplicate()`, `build_coverage()` | Collapses the 7-8 statistical repeats per evidence session, keeping whichever copy carries an expectation; scores coverage against the tracker (read-only). |
| `tests/golden_bank/golden_bank.json` (generated) | — | The fixture. `question` + `expected_answer` feed `services/agent_eval.py::score_answer()` unchanged. |
| `utils/trace_scrubbing.py` (new) | `scrub_trace()` | Consistent pseudonymisation of a captured trace/prompt dict. Returns a new structure plus a `ScrubReport` holding the re-identification key, which never travels with the trace. |
| | `contains_obvious_pii()` | Post-scrub tripwire, for a test or a pre-commit gate over a generated fixture. |
| | `_short_form()` | Strips legal-entity suffixes so `vendor_name = "Rajesh Steel Pvt Ltd"` also aliases the "Rajesh Steel" that appears in the question, the SQL `LIKE` and the answer. This was the single easiest leak to miss. |
| `services/online_eval_signals.py` (new) | `compute_online_signals()` | All five signals over one window, tenant-scoped or fleet-wide. |
| | `budget_exhaustion_rate()`, `clarification_rate()`, `zero_result_rate()`, `slow_turn_rate()`, `thumbs_down_clustering()` | The five shapes the "Where each tier runs" section names. |
| | `SignalResult.confidence` | Every signal states whether it is `measured`, a `proxy`, a `heuristic`, or `offline_only`. |
| `tests/test_seed_golden_bank.py` (new) | 30 tests | Hermetic — every real source is gitignored, so the fixtures reproduce each format from excerpts. |
| `tests/test_trace_scrubbing.py` (new) | 25 tests | Both halves: specific PII fields gone, specific structural fields survive. |
| `tests/test_online_eval_signals.py` (new) | 34 tests | Seeded SQLite, one test per named failure shape. |

### What the golden-bank seed actually recovered — real numbers, not an estimate

Run for real (`uv run python scripts/seed_golden_bank.py`, 2026-08-21):

| | Count |
|---|---|
| **Total cases** | **87** |
| Directly scorable by `services/agent_eval.py` (question + reference answer) | 79 |
| Deterministic retrieval cases (expected rows, no LLM judge needed) | 6 |
| Provisional, flagged `needs_review` (post-fix observed output, not an authored expectation) | 2 |
| Multi-turn follow-up links recovered from existing `(follow-up on Qn)` annotations | 10 |

Per source, before dedup: `tests/us` 15, `tests/india` 14, `tests/eu` 16,
`tests/realworld_tenant` 25, `docs/test_evidence` 88, `tests/agent_eval_golden_sample.py` 9 —
**80 duplicates dropped**, almost all of them from `docs/test_evidence`, which turned out to be 35
files replaying **one 2-turn session** (Gap 237's statistical repro) plus one retrieval probe set.
That collapse is the honest finding about that directory: it holds a great deal of *evidence* and
very few *distinct questions*.

**Gap coverage — the number the doc asked for:**

| | Count |
|---|---|
| Gap entries in `be_features_tracker.md` | 182 |
| Closed (`[x]`) | 177 |
| Closed **answer-quality** gaps, strict (the gap's own *title* is about chat/answers/SQL/RAG/retrieval) | 53 |
| Closed answer-quality gaps, loose (keyword anywhere in the entry) | 94 |
| **Closed answer-quality gaps with a recovered case** | **8** |
| **Closed answer-quality gaps that still need a case written fresh** | **45** |
| Distinct gaps referenced by any recovered case | 13 — 237, 239, 240, 241, 242, 243, 244, 263, 264, 268, 269, 270, 271 |

Read plainly: **the seed recovers a reproducible case for roughly 15% of the closed answer-quality
gaps (8 of 53), and 45 still need a case authored by hand.** The 87 cases are real and useful — they
are 79 gradeable questions where there were 9 — but they are *tenant regression* questions, not
one-per-gap coverage, because **the source data does not carry gap attribution**. Only two places in
the entire repo link a question to a gap number: the `Notes` column of the two
`live_test_results.md` files (which yielded **2** attributions, since only failing turns get a gap
cited) and `tests/agent_eval_golden_sample.py`'s `why_on_file` field (which yielded **9**). Nothing
else does. That is a property of how the evidence was written, not of the parser.

Two caveats stated rather than buried:

1. **The 53/94 strict-vs-loose split is a keyword classifier over hand-written prose.** Both numbers
   are published in the fixture along with the keyword list. The strict figure still sweeps in a few
   non-chat gaps whose titles mention chat (Gap 252's readiness probe, Gap 248's support router), so
   even 53 is a slight over-count. Neither number is exact; they bracket the real population.
2. **All four question banks are in gitignored directories.** `tests/golden_bank/golden_bank.json`
   is therefore derived from content not currently in version control. The four tenants are
   synthetic/generated corpora (NovaTech's own `ground_truth_line_items.md` documents its generator
   provenance), so this is a repo-hygiene decision, not a PII one — but it is a decision, and it is
   **left to the founder**: the file is written and uncommitted, `--stdout` writes nothing, and the
   `provenance` block travels inside the fixture.

### Scrubbing — the design decision, and what it costs

The doc flagged "what must survive vs. what must be redacted" as a **Decision required**. Here is
the decision as implemented, so it can be accepted or overruled on the evidence rather than in the
abstract:

**Consistent pseudonymisation, not blanket redaction.** Every distinct real value gets a stable
alias — the same vendor is `<VENDOR_1>` in the question, the system prompt, the generated SQL, the
tool result and the answer. Blanket `[REDACTED]` would destroy the property most gap reproductions
turn on: *did the answer talk about the same entity the question asked about?* Gap 270's direction
flip, Gap 276's stale prior-SQL reuse and Gap 263's tax relabelling are all still detectable after
aliasing and all invisible after flattening.

Redacted: vendor/customer names (including short forms), invoice and PO numbers, GSTINs, EU VAT
ids, `payment_instructions[].details`, IBAN/IFSC/labelled account values, email addresses, and every
monetary figure.

Deliberately preserved: every dict **key**; the sentence structure of the question and the answer;
`currency`, `quantity`, `flow_direction`, `status`, `role`, `stop_reason`, `tool`, `method_type`;
and referential identity (equal values share an alias, distinct values do not).

Two carve-outs, because they carry reasoning signal and disclose nothing: the **currency token**
stays verbatim next to the alias (`USD <AMOUNT_1>`), and a **zero** becomes a fixed `<AMOUNT_ZERO>`
rather than joining the alias pool — Gap 224's false-confident-zero is unreproducible if zero is
indistinguishable from any other figure.

**What it costs, stated plainly:** *arithmetic verifiability*. A scrubbed trace can still show that
two figures which should have been identical were not (Gap 269's `5,000 x USD <AMOUNT_1> = USD
<AMOUNT_2>` still reads as wrong), but it cannot be used to check that a sum is right. Any gap whose
reproduction needs real arithmetic must run against a synthetic tenant or stay production-only.
`preserve_amounts=True` exists for inside-the-boundary analysis and must never produce a committed
fixture.

**Known holes, not implied:** postal addresses, phone numbers, and personal names appearing only in
prose are not detected; a document id in prose that carries no 3-or-more-digit run is not matched by
the pattern (the digit requirement is what keeps `CGST-SGST` and `RCM-B2B` — the vocabulary a
tax-reasoning bug is made of — from being redacted). Ids that also appear in an
`invoice_number`/`po_number` field are caught by exact-literal replacement regardless of format.
This module reduces disclosure risk; it does not certify anonymity, and the SOC 2 questions above
stay open.

**One tension the doc raised is now resolved by measurement, in the negative:** a scrubbed corpus
cannot be an answer-bearing golden bank. Scrubbing turns `$450.00` into `<AMOUNT_1>`, which makes the
reference answer unusable as a reference. The two roles are different artefacts — the golden bank
comes from a safe (synthetic) corpus, scrubbing is for production traces.

### Online-eval signals — and the two real gaps they exposed

All five signals the "Where each tier runs" section names are implemented against tables that exist
today (`ChatMessage` + `ChatSession` for tenant scoping, `ChatFeedback`, and the *existing* columns
of `agent_eval_run`). No schema change was made, and none is assumed.

| Signal | Confidence | Source | Default alert |
|---|---|---|---|
| `zero_result_rate` | **measured** | `chat_message.content` contains `agents.query_agent.NO_RECORDS_FOUND` (drift-tested against the product constant). Reports Gap 224's *false-confident-zero* sub-shape separately — a confident `USD 0.00` with no "no records found" anywhere. | 20% |
| `thumbs_down_clustering` | **measured** | `chat_feedback.vote`/`.reason`/`.session_id`, clustered by day/session/reason/tenant | 20% rate **or** any cluster ≥ 3 |
| `slow_turn_rate` | **proxy** | Assistant row `created_at` minus its own user row's. Paired on Gap 280's `job_id` where present, nearest-preceding-user otherwise. | 5% over 45s |
| `budget_exhaustion_rate` | **offline-only** | `agent_eval_run.notes` free text (`stop_reason=tool_call_budget_exhausted`) | 10% |
| `clarification_rate` | **heuristic** | Language heuristic over assistant rows, plus the exact offline figure in `detail` | 25% |

No signal alerts below 20 observations — 1-of-1 is 100%, and that is the commonest way a quality
dashboard cries wolf. A `None` value always means "nothing to measure" and never 0.0, so an empty
window cannot read as a healthy one.

**Two genuine gaps found while building this, reported rather than worked around:**

1. **`stop_reason` never reaches the database on a live turn.** `agents/sage_orchestrator.py`
   computes `tool_call_budget_exhausted` / `clarification_requested` /
   `planner_step_budget_exhausted` and `run_agentic_sage()` returns them in metadata, but
   `ChatMessage` has no column for them and nothing persists them. The only durable copy anywhere is
   the free-text `agent_eval_run.notes` written by `scripts/run_agent_eval.py` — which covers the
   offline harness only. So budget-exhaustion rate is a real measurement of the *eval runner*, not
   of production, and it is parsed out of prose rather than read from a column. Closing this needs
   either a `stop_reason` column on `ChatMessage` or the Trace-level capture scoped under
   "Observability primitives". **Not done here** — `agent_eval_run`'s schema is under concurrent
   Feature 21 work and adding a column to it from this pass would collide.
2. **Turn latency is recorded nowhere.** `ChatMessage` has `created_at` and nothing else
   time-related. The proxy is genuinely end-to-end (under Gap 280's queue path the user row is
   written at enqueue and the assistant row after the agent returns, so it includes queue wait —
   which is exactly what Gap 278's "chat is failing then working again" actually was), but it is a
   row-timestamp delta, not a timer. Negative deltas are discarded, not clamped. An authoritative
   number needs a latency column or Phase 1's telemetry event.

The 45-second default threshold is not a round number: Gap 278 recorded two real turns at ~177s and
noted that "a long tail of otherwise-'normal' chat turns already sits at 20-40s even outside this
bug", so the threshold sits above the documented-normal tail and well below the pathological case.

**Wired to the workbook later the same day, with both gaps carried forward rather than closed.**
`emit_online_signals()` + `telemetry.track_online_signal()` mirror each `SignalResult` onto an
`online_eval_signal` custom event, because the workbook cannot query Postgres. `confidence` is a
field **on the event**, so the panel can label a proxy as a proxy without depending on anyone having
read this doc; a None value emits no `value` field at all rather than a 0.0. Neither gap above is
fixed by this — `stop_reason` still never reaches `ChatMessage`, turn latency is still a
row-timestamp delta — and both statements are reproduced verbatim in workbook section 6's own
header table. **No job calls `emit_online_signals()` on a schedule**, so the panel is empty today,
and it says that empty means "nothing has run", not "no problems found".

### Still open after this pass

* **Thread-level drift detection (Gaps 237/276) is not built, deliberately.** The doc scopes it as
  needing new design work and it does. Nothing in `online_eval_signals.py` detects drift; the seed
  script recovers *ordered multi-turn scripts* (10 follow-up links from the banks' own annotations,
  plus Gap 237's 2-turn capture), which is the bounded input such a detector would need, but no
  detector exists.
* **Vendor selection** — untouched, still the founder's call.
* **The Codify trigger** — extraction exists, but nothing runs it when a gap closes.
* **45 closed answer-quality gaps still need a case written by hand.**
* **A pre-merge vs. nightly decision for the offline suite** still needs a real cost/latency figure;
  none was measured in this pass (no LLM call was made by any of the three modules).

Still open after the *second* pass (2026-08-21, component scoring + workbook):

* **No dedicated domain-knowledge golden set**, so `persona_score` is scored against the general
  sample with a persona rubric and is NULL on most turns. Stated in the code, the workbook panel and
  above — not a thing to discover later from a suspiciously small denominator.
* **Nothing runs `emit_online_signals()` on a schedule**, so workbook section 6 has no data.
* **`stop_reason` still never reaches `ChatMessage`, and turn latency is still recorded nowhere.**
  Unchanged by this pass, deliberately: both need a schema change to a table under concurrent
  Feature 21 work.
* **The judge fixes have not been run against a live model.** Post-fix faithfulness/relevance
  figures do not exist yet, and pre-fix figures are not comparable to them.
* **The absolute level of the LLM-judged scores is still not a quality verdict.** Four identified
  biases are fixed; a human-graded calibration set or a stronger judge model is what would make the
  level (as opposed to the trend) trustworthy.

### Verified how

* `uv run pytest tests/test_trace_scrubbing.py tests/test_seed_golden_bank.py
  tests/test_online_eval_signals.py` — **89 passed** (25 + 30 + 34).
* `uv run python scripts/seed_golden_bank.py` run for real against the actual directories; every
  number in the tables above is that run's output, not an estimate.
* Full suite, same invocation as Phases 1-3
  (`uv run pytest -q --ignore=tests/us --ignore=tests/realworld_tenant -p no:randomly`):
  **977 passed, 3 failed, 6 skipped, 5 deselected** in 400s. The 3 failures are pre-existing and
  unrelated: 2 in `test_connectors.py` needing a live Redis, 1 in `test_rag.py` calling
  `post_chat_message()` without its `background_tasks` argument. The 3 `test_agentic_sage.py`
  prompt-capitalisation failures present in the Phase 3 baseline are no longer failing; that file is
  under concurrent Feature 21 work and the change is not attributable to this pass.
* No dependency added — `re`, `dataclasses`, `sqlmodel` and the standard library only.

## Tooling — options, not a decision

Vendor choice is explicitly not made here — the founder decides. Each option against this codebase:

| Option | Fit | Note |
|---|---|---|
| **Langfuse** | Open source, self-hostable, LangGraph callback integration, datasets/scoring built in | Self-hosting footprint has grown (recent versions want ClickHouse + blob storage alongside Postgres/Redis) — verify current requirements before assuming a light footprint on Container Apps |
| **LangSmith** | Tightest LangGraph integration, hosted-first | Data-residency position needs checking before any customer-data trace could go through it |
| **Arize Phoenix** | Open source, self-host, OpenTelemetry-native | — |
| **OpenTelemetry only** | No new platform — spans into Application Insights, already provisioned | Honest framing: App Insights is provisioned but was receiving nothing until Phase 1 landed. Finishing what's already half-built (deploy Phase 1, set the connection string — already done as of 2026-08-21, verified live) may get most of the value before adding a new platform |
| **Build nothing new** | Extend `ChatMessage`/`agent_eval_run` persistence, query with SQL | Covers Trace-level and ad hoc reasonably; doesn't give Run-level prompt/tool-call detail or Thread-level drift detection without real new work either way |

**One tension flagged explicitly, not resolved**: several of these platforms offer remote prompt
management — prompts stored and versioned outside the repo. `feature_21_architecture.md` requires
prompts to live as named module-level constants **in code**, specifically because a single remote
literal is what caused this codebase's schema-drift bugs. Adopting remote prompt management would
partially reverse that decision. **Decision required** — tracing and prompt management do not have
to arrive together.

## Sequencing and scope warning

Each phase should be independently valuable; state plainly which delivers the most per unit of
effort once scoped (not decided here). **Explicit scope warning**: this can become a platform-
adoption project that displaces the correctness work it exists to serve. The actual open items —
Feature 21's verification/groundedness node, the LLM-call-count measurement (answered, 2026-08-21 —
see `feature_21_architecture.md`'s B4 section), the Gap 280 queue exposures, outstanding schema
migrations — are the point. Observability that doesn't get used to close those is overhead, not
progress.

## Explicitly out of scope

- Org-wide coverage of agents outside this application (e.g. the `.claude/agents/` development
  personas — those are engineering tooling, not part of the product, and are Anthropic-side usage
  with their own separate accounting).
- Automatic model switching. This feature reports and recommends; a human decides.
- Selecting a third-party observability vendor here — see "Tooling" above; that's the founder's
  call, not resolved by this doc.

## Phase 1 as built (2026-08-21)

### File coordinates

| File | Function / symbol | What it does |
|---|---|---|
| `telemetry.py` (new) | `track_agent_call()` | The primitive. Emits one `llm_agent_call` custom event. Never raises. |
| | `tracked_llm_call()` | Context manager wrapping one invocation: times it, captures tokens, sets `status`, calls `track_agent_call()` on exit, re-raises anything the block raised unchanged. |
| | `resolve_model_name()` | Reads the model off the LLM object (unwrapping `RunnableBinding.bound` for SAGE's tool-bound planner), falling back to settings. |
| | `LlmUsage`, `_build_usage_handler()` | Token capture — see below. |
| `agents/extraction_agent.py` | `extract_node()`, `dynamic_qa_node()` | `extraction.INBOUND/OUTBOUND.extract`, `extraction.INBOUND/OUTBOUND.dynamic_qa`. `ExtractionState` gained a `tenant_id` key (telemetry attribution only — no node reads it for any extraction decision). |
| `agents/query_agent.py` | `classify_query()` | `chat.classify`. Only the LLM fallback is instrumented; Gap 182's keyword fast path calls no model. Gained an optional `tenant_id` kwarg. |
| | `run_sql_generation_loop()` | `chat.sql_generation`, one event per attempt (`attempt` on the event). Shared with `query_tools.identify_invoices()`/`aggregate()`, which pass their own `telemetry_agent_name` (`sage.identify`, `sage.aggregate`) so each SAGE tool's round-trips are attributed to it rather than to the chat route -- one event per call either way, never a nested pair. |
| | `run_query_agent()` | `chat.sql_summary`, `chat.rag_answer`, `chat.conversational`. |
| `agents/sage_orchestrator.py` | `_plan_node()`, `_synthesize_node()` | `sage.planner` (with `planner_step`/`tool_calls_made`), `sage.synthesis`. `_plan_node` gained an optional `tenant_id` kwarg, passed from `deps` in `build_sage_graph()`. |
| `agents/trainer_agent.py` | `refine_constraints()` | `trainer.refine_constraints`. Gained an optional `tenant_id` kwarg, passed by `run_trainer_agent()`. |
| `routers/trainer.py` | `_validate_rule_text()` | `trainer.rule_guardrail` (Gap 217's guardrail is a real billable call on every preview/commit). Gained an optional `tenant_id` kwarg. |
| | `flag_missed_alert()` | `trainer.missed_alert_rule` — the Feature 18 alert-anchored correction loop's model call. |
| | `_answer_qa_from_session_data()` | `trainer.qa_summary` (with `field_count`) — Gap 236's upload-path QA answer. Gained an optional `tenant_id` kwarg, passed by `_handle_qa_test_turn()` from its `TenantContext`. |
| `routers/dashboard.py` | `get_dashboard_insights()` | `dashboard.insights` (with `invoice_count`). Only cache misses reach the model, so the event count is the true call count, not the panel's view count. |
| `tests/test_telemetry.py` (new) | 5 tests | Event shape, real token capture off a LangChain run, error status + re-raise, broken-emitter resilience, mock-model naming. |

### Event

One `customEvents` row named `llm_agent_call` per LLM round-trip, with
`agent_name`, `model`, `tokens_in`, `tokens_out`, `tokens_total`, `latency_ms`, `status`
(`success`/`error`), `tenant_id`, `request_id`, `trace_id`, `llm_calls`, plus per-agent extras
(`flow_direction`, `complexity`, `attempt`, `planner_step`, `alert_type`, ...).

### How it reaches Application Insights — nothing new was initialised

Feature 19 (Task 19.2) already calls `configure_azure_monitor(connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"), logger_name=...)`
at import in both `main.py` (`invoice_be_telemetry`) and `queue_worker/main_worker.py`
(`invoice_worker_telemetry`). Phase 1 reuses that rather than standing up a second SDK:
`telemetry._resolve_event_logger()` picks whichever of those two loggers actually carries the
Azure handler in the current process, lazily (at import time neither does — `main.py` imports the
routers on the line above the `configure_azure_monitor` call).

The Azure Monitor exporter routes a log record carrying the `microsoft.custom_event.name`
attribute to `customEvents` rather than `traces` (`_MICROSOFT_CUSTOM_EVENT_NAME` in
`azure/monitor/opentelemetry/exporter/_constants.py`). The same record also propagates to root,
where Feature 19's `StructuredJsonFormatter` writes it to stdout as JSON — so the fields are
visible in container logs and in local dev with no connection string at all.

`request_id`/`trace_id`/`tenant_id` come from the contextvars in `utils/logging_config.py` that the
existing middleware (API) and `main_worker` (queue) already populate — the same IDs as the
structured log lines, not a second scheme. `tenant_id` is additionally passed explicitly at every
call site that has it, because `TracingAndLoggingMiddleware` sets `request_id`/`trace_id` but not
`tenant_id`.

### Token counts — why a callback, not the response object

LangChain's `with_structured_output(...).invoke()` returns the parsed Pydantic object, not the
`AIMessage` — so at the structured call sites (extraction, classification, SQL generation, trainer
rule drafting) there is no response to read `usage_metadata` off. The alternatives all change
behaviour: `include_raw=True` changes the returned shape, and `config={"callbacks": [...]}` changes
a call signature that a dozen test doubles implement as `invoke(self, prompt)`.

Phase 1 uses LangChain's own context-scoped callback mechanism instead —
`register_configure_hook()` + a `ContextVar`, the same thing `get_openai_callback()` is built on.
The framework attaches the handler to every run started inside a `tracked_llm_call` block, so no
call site's arguments or return value change at all, and the test doubles (which never route
through LangChain's callback manager) simply report zero tokens. `LlmUsage` accumulates rather
than overwrites, because a tracked block can legitimately contain more than one round-trip
(`invoke_with_retry`'s backoff, the SQL repair loop) and the block's cost is their sum.

### Deviations from the scoped shape — stated plainly

1. **SENTINEL has no LLM call site to instrument.** The registry names the tax/payment-status
   detectors; both (`detect_tax_component_term`, `detect_payment_status_question` in
   `agents/query_agent.py`) are pure word-boundary regex, deliberately so. There is no third,
   LLM-backed audit check — a repo-wide `get_llm` grep found none under `routers/audit.py`,
   `routers/outbound_audit.py` or `utils/verification_tools.py`. SENTINEL's LLM cost is therefore
   entirely the `extraction.*` events its audit runs on top of.
2. **Inbound and outbound extraction are one code path.** Gap 283 collapsed them into a single
   graph; `agents/outbound_extraction_agent.py` is a thin wrapper over `run_extraction_agent(...,
   flow_direction="OUTBOUND")`. They are still reported as two agents (`extraction.INBOUND.*` /
   `extraction.OUTBOUND.*`) because they are two rows in the registry and two cost drivers, but
   there is one instrumented call site, not two.
3. **Two real LLM call sites were outside the original registry — both are now in it and
   instrumented** (added 2026-08-21, same pass, on founder instruction):
   `routers/dashboard.py::get_dashboard_insights` (`DashboardInsightsSchema` → `dashboard.insights`)
   and `routers/trainer.py::_answer_qa_from_session_data`, the QA-panel upload-path summary
   (→ `trainer.qa_summary`). Both use the same `tracked_llm_call()` wrapper and the same context-var
   callback token capture as the other sites; `get_dashboard_insights` now binds `get_llm()` to a
   local so `resolve_model_name()` can read the model off it instead of the call being anonymous.
   Phase 2's cost rollup therefore covers every LLM call this application makes, with no known
   under-reporting.
4. **`ENABLE_AGENTIC_SAGE` is still off**, so the `sage.*` events are wired but will not appear in
   Application Insights until the flag moves. Verified only against the mocked orchestrator tests.

### Not done here — founder action required

`APPLICATIONINSIGHTS_CONNECTION_STRING` must exist as a **Container App secret of that exact name**
on `invoice-be` and `queue-worker`. `infra/modules/compute/invoice-be.bicep` and
`queue-worker.bicep` already declare the env var + `secretRef`; nothing in this repo sets the
secret's value, and nothing here hardcodes a connection string. Until it is set, the module no-ops
into stdout-only structured logging — it never raises and never blocks an agent call. `verified in
Application Insights` is therefore **not** claimed for Phase 1; the automated evidence is
`tests/test_telemetry.py` plus a full-suite run unchanged from its pre-change baseline
(pre-change 813 passed / 6 pre-existing failures; after Phase 1 including the 5 new telemetry tests,
**818 passed, 6 failed, 6 skipped** — the same 6 failures, re-confirmed 2026-08-21 after the
dashboard/trainer-QA call sites were added:
`pytest -q --ignore=tests/us --ignore=tests/realworld_tenant`; those two dirs are gitignored
local scratch dirs holding two same-named `*_test.py` scripts that collide at collection —
a pre-existing condition, unrelated to this feature).

No dependency change was needed: `azure-monitor-opentelemetry>=1.6.0` was already in
`apps/invoice-be/pyproject.toml` and pinned at 1.8.9 in `uv.lock` (this backend has no
`requirements.txt` — the Dockerfiles install with `uv sync --frozen`).

## Phases 2 and 3 as built (2026-08-21)

### File coordinates

| File | Function / symbol | What it does |
|---|---|---|
| `models.py` | `AgentEvalRun` | The Phase 3 table. Column is `pass` in SQL, attribute is `passed` (Python keyword). Scores nullable so "not scored" never reads as 0.0. |
| `alembic/versions/b5d2c8a41f30_add_agent_eval_run.py` | `upgrade()`/`downgrade()` | Creates `agent_eval_run` + 5 indexes. Chained onto `f3e8b2a1d6c9`, confirmed the real single head by running `alembic heads` first, not assumed. |
| `services/agent_eval.py` (new) | `score_faithfulness()` | RAGAS' definition, implemented: decompose into atomic claims, judge each against the tool context, score = supported/total. |
| | `score_relevance()` | RAGAS' *definition* of answer relevance, judged directly (see deviation 2 below). |
| | `score_accuracy()` | Semantic agreement with the golden set's reference answer. |
| | `score_answer()`, `decide_pass()` | All three plus the pass decision — three independent floors (0.80/0.70/0.70), never averaged. |
| `telemetry.py` | `track_eval_result()`, `EVAL_RESULT_EVENT_NAME`, `_emit_event()` | Emits one `agent_eval_run` custom event mirroring each DB row; `_emit_event()` is the shared emitter both event types now use. |
| `scripts/run_agent_eval.py` (new) | `run_turn()`, `_LlmCallCounter`, `_ToolOutputRecorder`, `_agentic_sage_enabled()` | The runner. Counts real LLM calls off Phase 1's own events, records everything the tools returned as the faithfulness context, and can run either chat path. |
| `tests/agent_eval_golden_sample.py` (new) | `CASES` (9), `tenant_stats_summary()` | The graded sample: real question phrasings from the existing banks, each citing its file:line, with reference answers computed from the seeded fixture. |
| `infra/monitoring/llm_cost_rollup_nightly.kql` (new) | — | Phase 2's cost rollup by agent/day/tenant. |
| `infra/monitoring/ai_control_tower.workbook.json` (new) | — | The workbook definition, for Portal import. |
| `tests/test_agent_eval.py` (new) | 19 tests | Metric mechanics, the pass floors, the `pass` column round-trip, the migration's own DDL up and down, the telemetry mirror, and the per-turn call counter. |

### The scorer: an LLM judge, not the `ragas` package

Checked before deciding: ragas is Apache-2.0 (licensing is not the blocker), but it is not installed
here and pulls `datasets` → `pyarrow`/`dill`/`multiprocess`/`fsspec`, plus `pandas` and
`nest-asyncio`. This backend builds with `uv sync --frozen` from one lockfile shared by the API and
the queue-worker images — there is no separate eval image — so adopting it puts hundreds of MB of
transitive dependencies into production containers for a job that runs nightly and touches no
request path. The two metrics that matter here are ~100 lines of prompt against the model this
application already has configured. Deviations from ragas are stated in
`services/agent_eval.py`'s module docstring and in `agents/README.md` §3.2 (which was itself
corrected in this pass — it had claimed ragas was already in use; it never was).

### Phase 3 was actually run, and here is what it found

Two full runs, 9 cases x 2 chat paths x 2 runs = 36 real turns against Azure `gpt-5-mini`,
0 harness errors, 18 `agent_eval_run` rows persisted per run. The cost/latency half of that run is
Feature 21's deliverable and lives in `feature_21_architecture.md`'s "B4" section; the quality half
is here.

**The judge has measurable failure modes, and they are all in the same direction — under-scoring
correct answers.** Two were found on run 1 and fixed in the prompts (an empty result being read as
*no* evidence; a greeting's capability list being decomposed into "claims" with nothing to support
them). Two survived that fix and were recorded here rather than papered over:

1. **"No records found" still scores 0.0 faithfulness on the default path**, even with an explicit,
   emphatic rule in the verdict prompt saying an empty result is evidence. The answer was correct
   and the accuracy judge scored it 1.0 on the same turn.
2. **Identical behaviour scored differently across paths.** A correct out-of-scope refusal scored
   relevance 1.0 on SAGE and 0.0 on the default path in the same run.

**Both are now fixed** (2026-08-21, later the same day — see "Judge failure modes 3 and 4" below).
The consequence recorded at the time still stands for *figures produced before that fix*: absolute
pass-rate from this scorer was not a quality verdict, only a trend on a fixed question set. The two
fixes remove two specific, identified biases; they do not by themselves make the absolute level
trustworthy, which still needs either a human-graded calibration set or a stronger judge model, and
that is still not done.

**One real product defect the run surfaced**, independent of the judge: asked "whats the CGST we
paid to Rajesh Steel", the current default path answered *"The CGST recorded for Rajesh Steel is INR
18,000.00"* — relabelling the single combined `tax_amount` as CGST. That is Gaps 263/264's failure
mode, live, today. SAGE answered the same question correctly. Full detail in
`feature_21_architecture.md`.

### Deviations from the scoped shape — stated plainly

1. **`test_chat_sql_quality.py` and `test_rag.py` are not golden sets in the sense this feature
   assumed.** The architecture section above calls them "golden-question regression banks ... as
   accuracy baselines", and Phase 3 was scoped as "run the existing test banks". Read directly, both
   are mocked unit tests of pipeline *mechanics* with a scripted `_RecordingLLM` — there is no
   expected natural-language answer anywhere in either file, so there is nothing in them to score an
   answer *against*. What is reusable is their question phrasings, every one a real incident from
   this repo's tracker; `tests/agent_eval_golden_sample.py` takes 9 of them (each citing its
   file:line) and adds the reference answers, computed from the seeded fixture rows. The repo's real
   answer-bearing banks are `tests/{us,india,eu}/chat_question_bank.md` (~15 questions each, with a
   grading rubric) — not used here because each needs its tenant seeded into live Postgres with real
   Chroma embeddings, and no local Postgres/Chroma/Redis is running.
2. **Relevance is ragas' definition, not ragas' estimator.** Ragas computes answer relevance by
   generating N questions from the answer and taking mean embedding cosine similarity against the
   original. That needs an embedding round-trip per generated question against the local BAAI/bge-m3
   model, which is a multi-GB first load and is mocked out in every non-live context here. Relevance
   is judged directly against the same written definition instead. A number from this module is not
   comparable to a published ragas benchmark figure.
3. **Context precision is not implemented.** Ragas' third metric grades the *retriever's* ranking,
   and this feature's question is about the answer. Worth adding when retrieval tuning is the
   subject.
4. **Quality reaches the workbook as telemetry, not from Postgres.** An Azure Monitor workbook
   cannot query Postgres (its data sources are Logs / Azure Resource Graph / ARM / ADX), so
   `agent_eval_run` rows are mirrored as an `agent_eval_run` custom event. Postgres stays the
   durable record; the event exists so the quality trend can share one time axis with cost and
   alerts, which was the explicit design decision for this workbook.
5. **The workbook's health section is an Azure Resource Graph query, not the built-in Alerts step.**
   The built-in step lists alerts *as they are now*; this workbook's whole point is day-over-day
   trend on a shared axis. `alertsmanagementresources` carries `startDateTime`, so alerts can be
   binned by day next to cost and quality. Verified live against this subscription (7 day/severity
   buckets, 23 alerts in 14 days). No alert rule was created or changed — Feature 20's 25+ rules and
   their action groups are untouched.
6. **The eval job's own judge calls are billable and are deliberately inside the cost rollup**,
   under `eval.*` agent names, with a `spend_kind` split in the workbook's cost table. Roughly 3-4
   judge round-trips per graded answer. The per-turn LLM-call counter excludes them, so a measured
   turn cost is the product's, not the grader's.
7. **"Nightly"/"scheduled" is not built.** Both the KQL rollup and the eval runner are artifacts a
   human runs today. No Log Analytics scheduled-query rule, no GitHub Actions cron, no ACA scheduled
   job. Wiring either is a separate infra change.

### Verified how

* `tests/test_agent_eval.py` — 19 passed, including running migration `b5d2c8a41f30`'s own
  `upgrade()`/`downgrade()` DDL against SQLite (not trusting that model metadata and migration
  agree) and asserting the SQL column really is named `pass`.
* All six workbook queries and the cost-rollup `.kql` executed **live** — the four Log Analytics
  queries against `appi-invoicellm-dev` (app id `d2add3c5-...`) and the two Azure Resource Graph
  queries against subscription `2ae37d8b-...`. The ARG queries returned real alert data; the Log
  Analytics queries parsed and returned the right column schema with **zero rows**, because
  `customEvents` has **0 rows over 90 days** — confirmed by direct query, not assumed.
* Two real end-to-end eval runs; raw output at `tests/agent_eval_output.json`.
* Full suite, same invocation as Phase 1's
  (`pytest -q --ignore=tests/us --ignore=tests/realworld_tenant`): **837 passed, 6 failed,
  6 skipped** — 818 + the 19 new tests, and the *same* 6 pre-existing failures as Phase 1's baseline
  (3 in `test_agentic_sage.py` asserting a prompt string's capitalisation that the code does not
  have, 2 in `test_connectors.py` needing a live Redis, 1 in `test_rag.py` calling
  `post_chat_message()` without its `background_tasks` argument). No new failure.

### Not done here — founder action required

1. **Same blocker as Phase 1, now confirmed by measurement rather than inference:**
   `APPLICATIONINSIGHTS_CONNECTION_STRING` is still not set as a Container App secret on
   `invoice-be`/`queue-worker`. `customEvents | summarize count()` over the last 90 days returns
   **0**. Until that secret exists, the workbook's cost and quality sections render empty and the
   cost rollup returns nothing — which is a configuration state, not a zero-cost month. The alerts
   section works today regardless.
2. **Import the workbook**: Portal → Monitor → Workbooks → New → `</>` Advanced Editor → paste
   `infra/monitoring/ai_control_tower.workbook.json` → Apply → Save into `rg-invoice-llm-dev`.
   Deliberately not imported from here.
3. **Re-check the model rates** in the cost KQL against the Azure OpenAI pricing page for this
   deployment's region before treating any figure as real money. They are a hardcoded assumption in
   one editable block, and an unpriced model reports a blank cost rather than zero.

## Judge failure modes 3 and 4, fixed (2026-08-21)

Both were diagnosed from the persisted output of the run that exhibited them
(`tests/agent_eval_output.json`), not reasoned about in the abstract, and both fixes are rubric
corrections rather than special cases for specific questions. Full detail lives in
`services/agent_eval.py`'s module docstring, which is the section that already carried modes 1-2.

### 3. A correct "no records found" scored 0.00 faithfulness — the judge was never shown the query

The run's own record makes the cause plain. The evidence handed to the judge was the whole of
`"DATABASE RESULTS:\nNo records found matching the query criteria."`, while the two claims under
judgement were "No records were found for **Nonexistent Holdings** **last quarter**" and "There were
no recorded spends with **Nonexistent Holdings** during **the period**". Nothing in that evidence
says which vendor or which period was queried, so under the verdict prompt's own rules 1-2 ("judge
only against the context"; "a plausible inference the context does not contain is NOT supported")
the 0/2 verdict was **correct on the evidence it was given**. Rule 5 had already anticipated this —
"supported when the context shows that query was the one executed" — but its precondition could
never be met, because the executed query was not part of the context. This is not judge stubbornness;
it is a scorer that could not distinguish "the vendor does not exist" from "the tool was asked about
a different vendor entirely", which is the same confusion Gap 224's false-confident-zero is made of.

Three changes, all general:

| Change | Where |
|---|---|
| The executed query/tool calls **with their arguments** are now part of the evidence, rendered as their own prompt block. An empty result is finally attributable to a query. | `score_faithfulness(..., executed_queries=)`, `score_answer(..., executed_queries=)`; recorded by `_ToolOutputRecorder.executed_queries()` in `scripts/run_agent_eval.py` (SQL, document-search query, and every `_ToolBox.dispatch` call with its args, recorded *before* the call so a raising tool still leaves a trace) |
| The verdict rubric no longer bolts the empty-result case on as an exception after three absolute rules. Each verdict must first assign a `claim_type` (`positive_fact` / `absence` / `query_scope` / `non_factual`), and the evidence standard is stated **per type**. A rule the judge applies before deciding is obeyed; a carve-out read after forming a verdict is not. | `ClaimVerdict.claim_type` + the rewritten `eval.faithfulness` prompt |
| `non_factual` verdicts leave the denominator instead of counting as unsupported — a third instance of failure mode 2's family, where a pleasantry the decomposition step failed to filter cost real score. | `_UNGRADEABLE_CLAIM_TYPES` |

The hard-coded `return 0.0` on an empty context survives, but with a narrower precondition: it now
fires only when **nothing ran and nothing came back** and the answer asserted facts anyway. That is
still the unfaithful case by definition, and a test pins it so the fix above cannot become a free
pass.

### 4. The same correct refusal scored 1.0 on one path and 0.0 on the other

`out_of_scope_code_request` ("write me a python script to reverse a string") was declined correctly
by both paths in near-identical words and scored relevance 0.0 (default) against 1.0 (SAGE) in the
same run. `greeting_no_tool` showed the same instability at lower amplitude (0.7 against 1.0).

The cause is structural, not random. Every numeric anchor in the relevance rubric was phrased as
*"answers what was asked"* — and a refusal, by construction, does not answer what was asked, so the
anchors themselves drive a judge toward 0.0. The three carve-outs (clarification, no-results,
refusal) sat *after* the anchors as prose and contradicted them, so whether any given call honoured
them was a coin flip. Same shape as failure mode 1: a rule that fights the rubric it is appended to
does not win reliably.

Fixed by making the judge **classify before it scores**. `RelevanceVerdict` carries an `answer_kind`
the model must choose from six named kinds, and for the kinds whose correct relevance is
*definitional* rather than a matter of degree the score is fixed **in code** by
`RELEVANCE_KIND_SCORES`:

| `answer_kind` | Relevance |
|---|---|
| `direct_answer`, `clarifying_question` | the judge's own 0-1 score — here relevance genuinely is a matter of degree |
| `no_results_report`, `out_of_scope_refusal`, `capability_or_greeting` | **1.0, fixed.** These *are* the relevant response to what was asked. Whether they are *correct* is faithfulness/accuracy's job. |
| `off_topic` | **0.0, fixed** |

Two paraphrases of the same refusal can no longer score differently unless the judge disagrees about
what *kind* of response it is looking at — a far more stable judgement than a free-floating number.
An unrecognised or absent `answer_kind` falls back to the raw score rather than losing it, so an
older judge double still produces a usable figure.

### How these two are tested without a live model

The judge is an LLM, so the tests use scripted doubles — but they are pinned to the **real texts from
the run that failed**, copied verbatim out of `tests/agent_eval_output.json`, and they assert the two
things a double cannot fake:

* For mode 3: that `"Nonexistent Holdings"` and the date filter now actually **reach** the verdict
  prompt (the thing that was missing), that the four claim types are named in the rubric, that the
  turn now scores 1.00, that a positive claim against the same empty result is still 0.0, and that
  the no-query/no-results case is still a real 0.0.
* For mode 4: the two real refusal texts are scored by two judges that return *the divergence that
  actually happened* — 0.0 and 1.0 — and both must come out at 1.0. The divergence is fed in
  deliberately; the assertion is that it no longer propagates. `direct_answer` and
  `clarifying_question` are separately asserted to still use the judge's number, so the fix cannot
  have flattened the metric into a category.

**Not re-run against a live model.** These fixes change scoring only, so the 2026-08-21 measurement
round's faithfulness/relevance means are not comparable to anything produced after them, and no new
live round was run in this pass (`ENABLE_AGENTIC_SAGE` is still off and the concurrent Feature 21
round owns the live-run budget). The next real run is what produces post-fix numbers.

## Component-level scoring as built (2026-08-21)

The three columns the "Component-level scoring" decision above specifies now exist, with three
genuinely different mechanisms — not the same check run three times.

| File | Symbol | What it does |
|---|---|---|
| `models.py` | `AgentEvalRun.context_score` / `.orchestration_score` / `.persona_score` | Three nullable floats. NULL means "not scored", never 0.0. |
| `alembic/versions/c4a91e77b208_add_agent_eval_component_scores.py` | `upgrade()`/`downgrade()` | Three `ADD COLUMN`s, nullable, no server default — metadata-only on Postgres, every existing row keeps NULL. Chained onto `b5d2c8a41f30`, confirmed the real single head by running `alembic heads` first (output `b5d2c8a41f30 (head)`), and `alembic heads` after the file existed returns `c4a91e77b208 (head)` — still one head. |
| `services/agent_eval.py` | `score_context()` | **Deterministic.** F1 of fetched invoice ids against the golden case's known-correct set, with precision and recall both in the notes because they mean different things (low precision = over-broad filter, low recall = filter excluded the answer). No judge, no cost, no variance. |
| | `collect_invoice_identifiers()`, `identifiers_from_markdown()` | The two real evidence shapes: the agentic path returns structures (walked by key name), the default path returns a rendered markdown table (read by column header). Neither pattern-matches prose, which would happily collect a PO number or a date. |
| | `score_orchestration()` | **Mechanical, no judge.** Every figure in the answer must appear in the evidence, or be one arithmetic operation over two evidence figures (a `compute()` output). Score = traceable / total. |
| | `extract_figures()`, `_derivable()` | Dates matched whole before bare numbers (so `2026` never leaks out of `2026-08-01`); figures compared to the cent. |
| | `score_persona()`, `PersonaVerdict` | **LLM-judged**, with an explicit `applicable` escape so a turn that needed no domain judgement scores NULL rather than a fabricated number. |
| `telemetry.py` | `track_eval_result(..., context_score=, orchestration_score=, persona_score=)` | Mirrors the three onto the quality event, absent-stays-absent. |
| `scripts/run_agent_eval.py` | `_ToolOutputRecorder.fetched_invoice_numbers()`, `score_turn()`, `persist()`, `summarise()` | Collects the fetched ids, scores, persists, and reports each component mean **with its own denominator**. |
| `tests/agent_eval_golden_sample.py` | `GoldenCase.expected_invoice_numbers` | Three meaningful states: `None` = no declared set, component unscored; `()` = the correct retrieval is *nothing* (a vendor that does not exist, a question that should call no tool) and that is scored; `(...)` = exactly these. All 11 cases populated. |

**Two decisions worth stating rather than leaving to be inferred:**

1. **The component scores do not feed `decide_pass()`.** Additive and inert, by design: folding them
   in would silently redefine what a pass means halfway through a trend series, which is the one
   thing a trend must not do. A test pins this.
2. **Small bare integers are skipped by the orchestration check**, not graded — a bare integer under
   100 with no decimal or separator is as likely to be "3 invoices", a list marker or a page number
   as a fetched figure. They are counted and reported as skipped, not silently dropped. Grading them
   would re-create the exact under-scoring-correct-answers bug this module already has four
   documented instances of. Likewise `_derivable()` exists because "or a `compute()` output" is in
   the design instruction and without it a correct "a difference of USD 14,350.00" would score as a
   fabrication.

### The persona component's real limitation, stated not buried

The doc scopes this component as needing "its own dedicated golden set of domain-knowledge
questions". **No such set exists in this repo** — checked, not assumed:
`tests/agent_eval_golden_sample.py` is nine general chat cases and `tests/golden_bank/golden_bank.json`'s
87 seeded cases are per-tenant regression questions with no domain-reasoning axis. Rather than block
the whole component on authoring a new bank, `score_persona()` scores the **general** sample against
a persona-focused rubric and returns `applicable=False` (score NULL) for every turn that required no
domain judgement.

The consequence is real and is carried into the workbook panel: the denominator is small and
self-selected, so `persona_score` is a signal about the cases that happen to touch tax/category
reasoning, **not** a coverage measure of domain competence. `persona_scored_turns` is published next
to it for exactly that reason. A dedicated domain bank is still the right fix and is still not
written.

The rubric itself is this repo's own closed gaps rather than generic accounting: relabelling a
combined `tax_amount` as CGST (Gaps 263/264), reading document-processing status as payment status
(Gap 270), invoice total vs. line-item figure for a category question (Gap 271), a printed line
amount that does not equal quantity x unit price (Gap 269), RCM's zero tax being a correct value
rather than missing data, and mixing currencies with no rate available.

## Workbook — the second pass (2026-08-21)

`infra/monitoring/ai_control_tower.workbook.json` went from 3 sections to 8, on the same shared time
axis, same day-over-day-not-snapshot rule, and the same "what's live today" honesty table in the
header (extended, not replaced).

| # | Section | New? | Source |
|---|---|---|---|
| 1 | Cost | existing | `llm_agent_call` |
| 2 | **Cost by tool** | new | `llm_agent_call`, `sage.*` only — Priority 4 |
| 3 | **Latency** | new | `llm_agent_call` — its own panel, p50 **and** p95 per agent per day |
| 4 | Quality | existing (renumbered) | `agent_eval_run` |
| 5 | **Component quality** | new | `agent_eval_run` — three separate trend lines |
| 6 | **Online signals** | new | `online_eval_signal` |
| 7 | **Golden-bank coverage** | new | static figure, re-verified against the fixture |
| 8 | Health | existing (renumbered) | Azure Resource Graph |

**The online-signals panel needed a data source that did not exist.** Everything in
`services/online_eval_signals.py` is computed in SQL over Postgres, and an Azure Monitor workbook
cannot query Postgres — the same constraint that already forced the `agent_eval_run` telemetry
mirror. So `emit_online_signals()` (new, in that module) and `telemetry.track_online_signal()` (new)
mirror each `SignalResult` as an `online_eval_signal` custom event, with `confidence` **on the
event**, not just in a doc. `value` is omitted entirely when the module returns None, because None
means "the denominator was empty" and emitting it as 0.0 would render an ingestion outage as a
perfectly healthy day.

The two gaps the signals module reported are carried into the panel's own text verbatim rather than
smoothed over: **`stop_reason` never reaches `ChatMessage` on a live turn** (so
`budget_exhaustion_rate` measures the eval harness, parsed out of prose, not production) and **turn
latency is recorded nowhere** (so `slow_turn_rate` is a row-timestamp delta, not a timer; negative
deltas discarded, not clamped). Both are in the section header table under an explicit
`confidence` column, alongside the 20-observation alert floor and the "blank means not measured"
rule.

**Nothing emits these events yet** — no scheduled job calls `emit_online_signals()`. The panel says
so: an empty panel there means "nothing has run", not "no problems found".

**Golden-bank coverage is a static tile, and says so.** A workbook has no data source that can read a
repo file. The numbers were re-verified against the current `tests/golden_bank/golden_bank.json`
(`generated_at` 2026-08-21T14:16:40Z) rather than copied from this doc: **8 of 53** closed
answer-quality gaps have a recovered case, **45** still need one written, 87 cases / 79 gradeable /
6 deterministic / 2 provisional / 10 multi-turn links, 13 distinct gaps referenced. Unchanged since
the seed run.

### Per-tool cost — and the one thing that makes it answerable

`infra/monitoring/llm_cost_by_tool.kql` (new, alongside the existing nightly rollup) plus workbook
section 2. The five instrumented SAGE call sites, read off the code rather than assumed:
`sage.planner`, `sage.synthesis` (`agents/sage_orchestrator.py`), `sage.identify`, `sage.aggregate`,
`sage.search` (`agents/query_tools.py`).

**`get_full_record` has no event of its own, and that is not an instrumentation gap.** It makes no
LLM call at all — it reads the ORM row and `get_all_invoice_chunks()`, and the planner puts every
chunk it returns into the *next* `sage.synthesis` prompt. So the chunk dump's cost is not missing
from telemetry; it is inside `sage.synthesis`'s `tokens_in` and nowhere else. That makes the
question answerable, and the file says how:

* **Query A / the section-2 table** — cost, tokens and `share_of_sage_tokens_pct` per tool-level
  agent per day. `sage.synthesis`'s share moving is the dump growing.
* **Query B / the turn-composition panel** — `request_id` correlates every call in one turn (Feature
  19's middleware sets it, Phase 1 puts it on every event), so `synthesis_share_pct` is literally
  "what the dump costs relative to the rest of the turn".
* **Query C** — the distribution. A mean hides this completely: most turns never call
  `get_full_record`, so the average synthesis prompt looks fine while the p99 *is* the document
  dump. `tail_over_median` rising is the signal.
* **Query D** — the number that exists **today**, and where it comes from. None of A-C returns a row
  yet, so the file points at the offline harness instead:
  `scripts/run_agent_eval.py::_measure_tool_result()` sizes each tool result directly
  (`chunk_count`/`chunk_chars`/`chunk_tokens`) with the real tokenizer, and the golden sample carries
  a matched pair (`large_invoice_full_detail`, 11 indexed pages, against `small_invoice_full_detail`,
  1 page — same question, same tool path) so the difference between the two turns is the dump and
  nothing else.

Section 2's own header carries the same caveat, so a reader of the workbook cannot mistake the
inference for a direct measurement.

### Verified how — this pass

* **All 10 new Log Analytics queries executed live** against `appi-invoicellm-dev`
  (app id `d2add3c5-9c23-46e2-b896-e7ab299abfbd`) via `az monitor app-insights query`, plus Query A
  of `llm_cost_by_tool.kql`. Every one parses and returns the **correct column schema** with **zero
  rows** — because `customEvents | summarize count()` over 90 days still returns **0**, re-confirmed
  by direct query in this pass, not assumed from the previous one. Zero rows here is a configuration
  state (no connection string), not a zero-cost month.
* The two Azure Resource Graph (health) queries were not re-run: unchanged by this pass.
* The workbook JSON round-trips through `json.load`/`json.dumps` and has 27 items in the order listed
  above.
* `alembic heads` run **before** writing the migration (`b5d2c8a41f30 (head)`) and **after**
  (`c4a91e77b208 (head)`) — one head either way, not assumed from filename ordering.
* `tests/test_agent_eval.py` **19 → 55 passed** (+36: the two judge failure modes, the component
  scorers, the new migration's DDL up and down on top of `b5d2c8a41f30`'s, the component-score
  round-trip, and the telemetry mirror). `tests/test_online_eval_signals.py` **34 → 37 passed**
  (+3: the telemetry mirror, the absent-value-is-not-a-zero rule, and emitter resilience).
* **`score_orchestration()` was run against the 22 real turns in `tests/agent_eval_output.json`**,
  not only against fixtures — which is how the second under-scoring path was found (see the
  component-scoring section) and fixed before filing. That check makes no LLM call, so running it
  over the whole persisted round cost nothing and took 0.01s.
* Full suite, same invocation as every prior phase
  (`pytest -q --ignore=tests/us --ignore=tests/realworld_tenant -p no:randomly`):
  **1024 passed, 3 failed, 6 skipped, 5 deselected** in 479s. The 3 failures are the *same three*
  as the 977-passed baseline and are pre-existing and unrelated: 2 in `test_connectors.py` needing
  a live Redis, 1 in `test_rag.py` calling `post_chat_message()` without its `background_tasks`
  argument. **No new failure.** Of the +47 passing tests against that baseline, **39 are this
  pass's** (36 + 3 above); the remaining 8 landed from the concurrent Feature 21 work running in the
  same tree and are not attributable here.
* No dependency added — `re`, `decimal` and the standard library only.

**Not deployed.** The workbook is still a definition, imported by hand; nothing here creates an
alert rule, a scheduled query rule, or an Azure resource, and no Azure configuration was changed.

## Tasks

- [x] Add `agent_name`/`model`/`tokens_in`/`tokens_out` fields to the existing structured logger,
      emitted as Application Insights custom events, for every agent in the registry table
      — done 2026-08-21, 14 instrumented invocation points (12, plus `dashboard.insights` and
      `trainer.qa_summary` added the same day once the registry was corrected to include them);
      see "Phase 1 as built" for the two registry rows that did not fit the assumed shape
      (SENTINEL has no LLM call; inbound/outbound extraction share one call site)
- [x] Nightly KQL cost-rollup query, by agent/day/tenant — `infra/monitoring/llm_cost_rollup_nightly.kql`,
      executed live against `appi-invoicellm-dev` (parses, correct column schema, 0 rows because
      `customEvents` is empty). **The word "nightly" is not built** — no scheduled query rule exists
- [x] `agent_eval_run` table + a job running golden sets, persisting pass/fail — table + migration
      `b5d2c8a41f30` + `services/agent_eval.py` + `scripts/run_agent_eval.py`, **really run**: 36
      turns across both chat paths, 18 rows persisted per run. Two honest amendments: the "existing
      golden sets" carry no reference answers (see deviation 1), and **no schedule exists** — this
      is a script a human runs
- [x] Azure Monitor workbook combining cost, latency, and quality into one view —
      `infra/monitoring/ai_control_tower.workbook.json`, day-over-day trend for all three on one
      shared time axis, every query validated live. **Not imported/deployed** (founder action).
      **Extended 2026-08-21 from 3 sections to 8**: cost-by-tool, latency as its own panel
      (p50+p95 per agent per day, no longer folded into the cost query), component-level quality,
      online signals, and a golden-bank coverage tile. All 10 new Log Analytics queries executed
      live against `appi-invoicellm-dev` — correct column schema, 0 rows, because `customEvents`
      is still empty. See "Workbook — the second pass"
- [x] Fix the two judge failure modes left unresolved by Phase 3 — both fixed 2026-08-21, both as
      rubric corrections rather than per-question special cases, both diagnosed from
      `tests/agent_eval_output.json` rather than guessed. (3) a correct "no records found" scored
      0.00 because **the executed query was never part of the evidence**, so no absence claim
      naming a vendor or a period could be checked; fixed by threading `executed_queries` through
      the scorer and the runner, and by replacing the bolted-on empty-result carve-out with a
      per-claim `claim_type` the judge must assign before deciding. (4) the same correct refusal
      scored 1.0/0.0 across paths because every relevance anchor was phrased as "answers what was
      asked"; fixed by making the judge classify the `answer_kind` first and fixing the score in
      code for the kinds whose relevance is definitional. 35 new tests, pinned to the real answer
      texts from the run that failed. See "Judge failure modes 3 and 4"
- [x] Component-level scoring — `context_score` / `orchestration_score` / `persona_score` on
      `AgentEvalRun` + migration `c4a91e77b208` (chained onto the real head `b5d2c8a41f30`, single
      head re-verified after), three genuinely different mechanisms (deterministic set comparison /
      mechanical figure traceability / LLM judge), mirrored onto the quality event, and three
      **separate** trend lines in the workbook. Additive and inert: they do not feed the pass
      decision. One honest limitation carried into both the code and the panel — **there is no
      dedicated domain-knowledge golden set**, so persona is scored against the general sample with
      a persona rubric and returns NULL for every turn needing no domain judgement; read
      `persona_scored_turns` before reading `persona`. See "Component-level scoring as built"
- [x] Per-tool cost/token breakdown — `infra/monitoring/llm_cost_by_tool.kql` + workbook section 2,
      by the real `sage.*` agent names in use. Answers "what does `get_full_record`'s chunk dump
      cost relative to the rest of the turn" via `synthesis_share_pct` per `request_id`, with the
      structural reason stated in both places: **`get_full_record` makes no LLM call**, so its cost
      is inside `sage.synthesis`'s `tokens_in` and nowhere else. The direct measurement is the
      offline harness's `large_invoice_full_detail` / `small_invoice_full_detail` pair
- [x] Online-signal telemetry mirror — `emit_online_signals()` +
      `telemetry.track_online_signal()`, so the workbook's online panel has a data source at all
      (it cannot query Postgres). `confidence` travels on the event; a None value emits no `value`
      field rather than a 0.0. **Nothing calls it on a schedule yet** — an empty panel means
      "nothing has run", not "no problems found"
- [x] Golden question bank seeded from gap history — `scripts/seed_golden_bank.py`, **really run**:
      **87 cases** recovered (79 directly scorable, 6 deterministic retrieval, 2 provisional,
      10 multi-turn links) from 5 real source formats across `docs/test_evidence/` and the four
      per-tenant banks. Honest amendment to the section's premise: the evidence directories carry
      almost no **gap attribution** — only 8 of 53 closed answer-quality gaps got a recovered case,
      and **45 still need one written fresh**. See "The vendor-agnostic framework as built"
- [x] Trace scrubbing utility — `utils/trace_scrubbing.py` + 25 tests. The doc's
      "what survives vs. what is redacted" **Decision required** is answered concretely (consistent
      pseudonymisation; currency and zero preserved; arithmetic verifiability lost), and one
      corollary is settled in the negative: **a scrubbed corpus cannot be an answer-bearing golden
      bank**, so the two are different artefacts
- [x] Online-eval signal queries — `services/online_eval_signals.py` + 34 tests, all five shapes the
      "Where each tier runs" section names, over existing tables only. Two real gaps surfaced and
      **left open**: no live turn persists `stop_reason`, and turn latency is recorded nowhere
- [ ] Thread-level drift detection (Gaps 237/276 shape) — **not started, deliberately.** Needs new
      design work per "Evaluation tiers"; the seed script recovers the bounded multi-turn scripts
      such a detector would consume, but no detector exists
- [ ] Codify trigger — the extraction half exists (`scripts/seed_golden_bank.py`); nothing runs it
      when a gap closes. Still a **Decision required** on the mechanism
- [ ] Extend the SAGE parity-harness pattern to extraction and chat classify/SQL-gen, for
      substitution testing against one cheaper candidate model — **not started.** Phase 3's scorer
      and runner are the machinery this needs (`--paths` is already the axis a model-swap
      comparison would use), but no candidate model has been run and no cost-vs-quality delta
      exists. Blocked in practice on the scorer's absolute level being trustworthy — a substitution
      recommendation made on a judge that under-scores correct answers would be a bad
      recommendation. Two of the four known under-scoring biases were fixed 2026-08-21, but the
      fixes have not been run against a live model, so there is still no post-fix baseline for a
      candidate to be compared against
