# Feature 23: AI Control Tower

One place that answers, for every AI call this application makes: what ran, who triggered it, how
often, how well it performed, what it cost, and whether a cheaper/faster model could have done the
same job. Scoped to this application only — not an org-wide platform.

## 2026-08-23 — Full rethink: scope, parameters, audit process, model comparison

The founder and architect fully rescoped this feature on this date, after finding the original build
(3-part LLM-judge scoring, 4-tab workbook split, static "golden-bank coverage" number, a nightly job
that likely couldn't even run — `.dockerignore` excludes `tests/`) didn't match what was actually
wanted. **This section is the current source of truth.** Everything below it in this document is
prior-round design/build history — useful as reference for what was tried, not as the live plan.

**What was deleted the same day** (superseded, not salvageable into the new design): the 9 live
`ai_control_tower_*` Azure Workbooks and their bicep, the 87-case `tests/golden_bank/golden_bank.json`
+ its seed script (confirmed unused by the actual eval script even before deletion — it imported
`tests.agent_eval_golden_sample`'s 11 cases instead), and the `caj-agent-eval-dev` scheduled job
(both the live resource and the `agentEvalJob` module in `08-apps.bicep`). Kept: the 25 real alert
rules, the cost budget, `scheduled-job.bicep` (generic, reusable for whatever scheduler comes next).

### Scope: every real LLM call site in the registry, not just two

**Correction (2026-08-23, same day as the rest of this section):** the first pass of this rethink only
designed parameters for extraction and "SAGE chat," describing SAGE orchestrator's planner→tools→
synthesis shape. Two problems with that, caught the same day: SAGE orchestrator is gated behind
`ENABLE_AGENTIC_SAGE` and is **off today** — the chat path actually live in production is
`agents/query_agent.py`'s classify + SQL/RAG/CHAT fork, which hadn't been given its own treatment at
all — and three other real registry rows (Trainer/EVOLVE, Dashboard insights, Trainer QA-panel
summary) were missed entirely. Corrected scope, against the full registry table below:

**Second correction (2026-08-23, later the same day), on what "missed entirely" meant.** Those three
rows were missed from *this rescope's parameter design*, not from the telemetry itself. A
function-by-function read of the code found all three were **already instrumented in Phase 1** and
needed no new `tracked_llm_call()` at all — see "Lightweight-tier coverage verified" below for which
named function carries each wrapper. Nothing was added to close a hole here, because there was no
hole; what was added is the test coverage that keeps it that way.

| Call site | Unit | Depth of treatment |
|---|---|---|
| Extraction (inbound + outbound) | Per document, one-shot | Full — see below |
| **Chat classify + SQL/RAG/CHAT fork** (`query_agent.py`) — **the live default path today** | Per turn, linked to thread | Full — same shape as "SAGE chat" below, this is the path it actually applies to right now |
| SAGE orchestrator (Phase 2, off by default) | Per turn, linked to thread | Same design, applies once the flag is on |
| Trainer/EVOLVE correction loop | Per correction | Lightweight — hard metrics only (cost, latency, error rate); lower volume/stakes than extraction or chat, doesn't need the full soft-metric judge treatment |
| Dashboard insights | Per cache-miss (1h TTL per tenant) | Lightweight — hard metrics only |
| Trainer QA-panel summary | Per QA-test turn | Lightweight — hard metrics only |
| SENTINEL | — | **None needed** — confirmed no LLM call of its own (pure regex detectors); its cost is the extraction calls it audits, already covered there |

### Finalized parameters

**Extraction** — hard only; this pipeline is verification-based by design, not judgment-based:

| Parameter | Source |
|---|---|
| Doc Intelligence + extraction LLM cost, latency | Existing telemetry |
| Verification pass rate | Existing deterministic check |
| **Field-level correction rate** (overall, by field, by vendor) | Auditor Review Console corrections — real human-caught errors, the best accuracy signal available |
| **Alert precision** (% of alerts leading to an actual correction vs. dismissed with no change) | Review Console's dismiss-vs-correct action |
| Alert volume by check type | Flags a noisy/miscalibrated rule |

**Built 2026-08-23**: `services/extraction_quality_rollup.py` — `field_correction_rollup()` and
`alert_precision_rollup()`. No new event logging needed; both read the audit trail
`routers/audit.py`'s resolve handler already writes to `AuditLog.details` on every
`RESOLVE_INVOICE`/`REOPEN_INVOICE` (`corrections`, `previous_alerts`, `dismissed_alerts_input`) —
verified this carries real per-field before/after values and per-alert dismissal linkage (`field` key),
not just a coarse "resolved" event. Alert precision matches a dismissal to a correction via the alert's
own `field` key (same linkage the FE review console uses, Gap 112 item 4); an alert with no `field` key
present can't be confirmed matched, so it's counted as *uncorrected* rather than assumed — a
deliberate under-count, not a bug. 6 tests, `tests/test_extraction_quality_rollup.py`, all passing.
Not yet wired to a dashboard panel — that's the Cost + Health/Quality Workbook task.

**Chat** (both the live `query_agent.py` fork and SAGE orchestrator once it's on) — hard (trace/cost) +
soft (judged), per turn:

| Type | Parameters |
|---|---|
| Hard | Cost, latency, tokens in/out, tool-call trace, error/retry rate |
| Soft — **one combined judge call**, not five separate ones | Faithfulness, relevance, helpfulness, persona/tone fit, completeness |

**Trainer/EVOLVE, Dashboard insights, Trainer QA-summary** — hard only (cost, latency, error/retry
rate), same reasoning as extraction: lower volume and lower stakes than a multi-turn chat answer,
doesn't justify the same judge-call cost. Revisit if any of these turns out to have its own real
quality problem worth measuring.

**Known, accepted gap**: alert *recall* (missed issues) can't be measured from real usage alone —
nobody flags what wasn't flagged. This is exactly what the benchmark's seeded-document track below
exists to answer.

### Audit / benchmark process — 2 tracks

> **Both tracks were built and really run on 2026-08-23** — see "Track 1 as built" and "Track 2 as
> built" below for the file coordinates, the review-artifact location, the measured numbers, and the
> one real product defect Track 1 found on its first run. The scoping text immediately below is the
> original intent, kept because the as-built sections deviate from it in two places and the deviation
> is easier to read against the original.

**Track 1 — Extraction & alerts (new, doesn't exist yet):**
| Set | Contains | Measures |
|---|---|---|
| Clean documents | Known-correct field values, no real issues | Extraction accuracy (diff vs. known-correct), alert false-positive rate |
| Seeded/mutated documents | Deliberately planted issues (tax figure not matching OCR text, fabricated total, missing field, out-of-tolerance line item) | Alert **recall** — does the right check actually fire for a known-planted problem? |

Together: a real confusion matrix (true/false positive/negative), not just a precision number.

**Track 2 — SAGE chat**: rebuilt case set (successor to `agent_eval_golden_sample.py`'s 11 cases —
that file itself wasn't deleted, still usable as a starting point), judge prompt extended to score all
5 soft metrics in one call.

**Cadence**: nightly (catches drift) **and** a pre-deploy gate (catches a regression before it ships,
not after). Scheduler mechanism: reuse `scheduled-job.bicep` once the new harness exists — same
pattern as the deleted job, new content.

### Optimization suggestions

- Trim tool-result context fed into synthesis (biggest cost lever — same principle as the extraction
  chunk-dump cap already built)
- Model tiering — cheap/fast model for planner + SQL-generation tool calls, strongest model reserved
  for synthesis only
- Prompt caching for repeated persona/schema system-prompt blocks
- De-dupe repeat tool calls within a single turn (a real bug found and fixed earlier this session —
  worth making a standing pattern)
- Batch the 5 soft-metric judge scores into one call, not five

**These are all cost/efficiency-side.** None of the above touches *content* — using the eval's soft-
metric scores to actually fix what's wrong with the persona, system prompt, or context assembly. That's
a distinct, so-far-undesigned optimization axis. Proposed starting map from a low soft-metric score to
the component most likely responsible, so Feature 24 (below) knows where to point a suggestion:

| Soft metric low | Likely area to fix |
|---|---|
| Faithfulness | Context — wrong/incomplete tool results reaching synthesis, or the grounding mandate in the system prompt isn't strong enough |
| Relevance | Trace — the planner routed to the wrong tool, not a wording problem |
| Helpfulness | System prompt — scope/tone instructions |
| Persona/tone fit | Persona block specifically — direct wording issue |
| Completeness | Context (missing rows/fields) or system prompt (not instructed to be thorough) |

### Model comparison — a deliberate periodic exercise, not a live metric

Freeze one fixed test set (both tracks above) → run current baseline (gpt-5-mini) once → run each
candidate through the identical set, swapping only the model → **keep the judge model fixed** across
all candidates (comparability breaks if the judge also changes) → one table of quality/cost/latency
deltas → decide. A benchmark win still deserves a staged/shadow-traffic period before full cutover.

**Candidates** (Claude and Gemini deprioritized for now, cross-provider integration effort not
justified yet):

| Candidate | Setup needed | Verified findings |
|---|---|---|
| **GPT-4o** (new Azure OpenAI deployment) | New model deployment under the *existing* `openai-invoicellm-dev` resource — no new Azure resource type, no code change (`get_llm()`'s `azure` branch already reads the deployment name from config). Just TPM quota for the model in this region. | Structured-output strict-mode compliance is only *guaranteed* from GPT-4o/GPT-4o-mini onward, API version `2024-08-01-preview`+ — confirmed via Microsoft Learn. Only primitive JSON types allowed in strict mode (no DateTime/Uri) — worth checking the extraction schema's date fields before assuming a swap "just works." `response_format` and `tools` are mutually exclusive in one call — relevant to SAGE's tool-calling planner. |
| **Ollama / self-hosted open model** | `langchain-ollama>=1.1.0` is **already installed and declared** in `pyproject.toml` (corrected an earlier wrong "not installed" finding — was checking system Python instead of the project's `.venv`). Needs: (1) Ollama itself downloaded and run locally, (2) a post-3.0 tool-calling tag — `config.py`'s `OLLAMA_MODEL` default **was corrected to `llama3.2:latest` on 2026-08-23**, from the pre-3.1 `llama3:8b` that has no reliable tool-calling support (confirmed via LangChain's own docs), (3) for anything beyond local dev, an actual hosting environment (no Ollama server runs in Azure today). | No hardcoded Azure-specific kwargs in any real `with_structured_output()` call site (`extraction_agent.py`, `query_agent.py`, `query_tools.py`, `trainer_agent.py`, `services/agent_eval.py`, etc.) — nothing will hard-crash from an incompatible parameter. Even on the well-supported Llama 3.1 8B, malformed-JSON rate is well under 1% but non-zero — a real (small) reliability gap vs. Azure OpenAI's strict-mode 100% guarantee, worth knowing going in. **A live smoke test on 2026-08-23 found the gap is not only malformed JSON**: llama3.2 returned *syntactically valid* structured output whose `route` value was invented, i.e. schema-valid and semantically wrong. That is what the routing-enum change below addresses. |

### The candidate-model override as built (2026-08-23)

The mechanism the section above needs — "run each candidate through the identical set, swapping only
the model" — now exists as a **test-time flag on the existing harness**, not a second harness and not
a config change.

| File | Function / symbol | What it does |
|---|---|---|
| `utils/llm.py` | `build_llm(provider, *, model, max_tokens, api_version, allow_mock_fallback)` | The construction logic `get_llm()` always had, parameterised on provider/model instead of reading both off `Settings`. Same three branches (`azure`/`ollama`/`mock`), same fallbacks by default. `model` maps to the Azure **deployment name** and to the Ollama model tag; endpoint/key/API version still come from settings, because a candidate on Azure is a new deployment under the *existing* resource. |
| | `get_llm(max_tokens)` | Now a thin wrapper: resolves `LLM_PROVIDER` (and the provider's configured model) and delegates to `build_llm()`. One construction path, not two that can drift. **Behaviour unchanged**, fail-safe mock fallback included. |
| | `LlmConfigurationError`, `SUPPORTED_LLM_PROVIDERS` | Raised only when a caller passed `allow_mock_fallback=False`, i.e. named a provider deliberately. `get_llm()` never raises it. |
| `scripts/run_agent_eval.py` | `--provider` / `--model` / `--api-version` / `--persist-candidate` | The CLI surface. `--provider` is choice-constrained to the three real providers. |
| | `_candidate_model()` | Context manager. Patches the `get_llm` **binding** in the three chat-path modules for the duration of the case loop and unwinds it after. Constructs the candidate once up front so a bad key/tag fails before any paid turn runs. |
| | `CANDIDATE_LLM_PATCH_TARGETS` | `agents.query_agent` / `agents.query_tools` / `agents.sage_orchestrator` — read off the code. Each does `from utils.llm import get_llm`, so the module attribute is the binding that matters; patching `utils.llm.get_llm` would miss all three. A drift-guard test asserts each target really is that function. |
| | `describe_model_under_test()`, `default_output_path()` | `provider:model` labelling, and a per-candidate output filename so a comparison run cannot overwrite `tests/agent_eval_output.json` — the baseline the candidate is being compared against. |
| `tests/test_model_substitution.py` (new) | 37 tests | The override's mechanics and the routing enum. No test calls a model. |

**Four properties this holds to, each with a test:**

1. **Test-time only.** No `.env` write, no `os.environ` write, no assignment to the `Settings`
   object. A test snapshots both and asserts they are identical inside and after the block.
2. **The judge stays fixed.** `judge_llm` is built from `get_llm()` *before* the override is
   entered, and `services/agent_eval.py` resolves its default judge through `utils.llm` directly —
   deliberately not a patch target. Swap the judge with the candidate and the deltas mean nothing.
3. **A candidate never becomes the mock.** An override run passes `allow_mock_fallback=False`, so a
   missing Azure key or an unpulled Ollama tag raises instead of producing a results table that
   reports `MockInvoiceLLM`'s canned output under a candidate's name.
4. **A candidate's scores do not silently join the baseline trend.** An override run does not write
   `agent_eval_run` rows unless `--persist-candidate` is passed, and rows written that way carry
   `model_under_test=<provider>:<model>` in `notes`.

**Stated rather than left to be discovered:** `summarise()`'s `cost_per_turn_usd` still prices every
run at gpt-5-mini's list rate. On a candidate run that is a *token-normalised* comparison, not the
candidate's real bill; the output payload now says so in a `cost_basis` field.

**Verified how:** `--provider mock` against a `.env` configured for Azure really produced
`MockInvoiceLLM`'s canned greeting with 0 tokens (proving the bypass), and
`--provider azure --model gpt-5-mini --api-version 2024-08-01-preview` really ran a turn against the
live deployment (proving the Azure branch and the API-version override). **No candidate benchmark has
been run** — no GPT-4o deployment exists yet, and no Ollama server was running on this machine
(`localhost:11434` refused connection), so the comparison table this section describes still does not
exist. The flag is the machinery, not the result.

**One local-config trap worth knowing:** `.env` on this machine sets `OLLAMA_MODEL=qwen2:0.5b`, which
takes precedence over `config.py`'s corrected `llama3.2:latest` default. `--provider ollama` with no
`--model` would therefore have benchmarked qwen2 — the run's own `model_under_test` label
(`ollama:qwen2:0.5b`) makes that visible instead of silent, but pass `--model` explicitly.

### `QueryRoutingSchema.route` is now a real `Literal` (2026-08-23) — Gap 296

`agents/query_agent.py`'s routing field was `route: str` with a description *asking* for one of three
values. A description is advice; an `enum` in the emitted JSON schema is a constraint the provider
generates against. The field is now `Literal["RAG", "SQL", "CHAT"]`, plus a `mode="before"` validator
that strips/upper-cases so the case-tolerance the old `.upper()` gave is preserved exactly.

**Why it matters here specifically:** `run_query_agent()` dispatches
`if route == "SQL" / elif route == "RAG" / else: # CHAT`, so *any* unrecognised value fell through to
the conversational branch — the user got a chatty answer, no retrieval ran, and nothing anywhere
recorded that routing had failed. With the enum, an invented value raises, and `classify_query()`'s
existing `except` block falls back to RAG, which does retrieve.

**Regression evidence on the Azure path, measured before and after rather than asserted:**

| Check | Result |
|---|---|
| Live `gpt-5-mini`, 10 questions × 3, all chosen to miss both keyword fast-path lists | 30/30 parsed, 0 validation errors, **before and after**. Every raw value was already exactly one of the three. |
| Same-process A/B (old plain-`str` schema vs. new `Literal` schema, alternating calls, same deployment, so run-to-run drift cannot be mistaken for the change) | 0 validation errors in either arm across 96 live calls. On the 3 clearly-routable questions both arms agreed 6/6 and 6/6. |
| Automated suites | `test_rag.py`, `test_chat_sql_quality.py`, `test_queries.py`, `test_direction_aware_chat.py`, `test_query_tools.py`, `test_agentic_sage.py`, `test_agent_eval.py`, `test_telemetry.py` — 366 passed, 2 failed, neither attributable to this change: `test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message` is the pre-existing `post_chat_message() missing 1 required positional argument: 'background_tasks'` failure already recorded in this doc's 2026-08-21 "Verified how", and `test_agent_eval.py::test_each_new_soft_metric_has_cases_that_can_actually_move_it` is an **uncommitted test from concurrent work on the golden sample** (it asserts on case phrasing in `agent_eval_golden_sample.py`, a file this pass did not touch). Plus `test_trainer.py`, `test_extraction.py`, `test_outbound_extraction.py`, `test_dashboard.py`, `test_chat_queue.py`, `test_chat_training.py`, `test_settings.py`, `test_online_eval_signals.py` — 170 passed, 0 failed. |

**The honest qualification, not buried:** on *genuinely ambiguous* questions the sampled route
distribution does move. `"does any document mention a delivery note number"` went from RAG 7 / SQL 5
under the old typing to SQL 11 / RAG 1 under the enum in one run, and RAG 7 / SQL 5 → SQL 9 / RAG 3 in
a second — reproducible. But the old arm was a coin flip on that question, not a correct baseline, and
the shift is not directional: `"what bank details appear on the Rajesh Steel bill"` went the other way
(SQL 12/12 old → SQL 10 / RAG 2 new). So: **no parse regression, no change on unambiguous routing,
and a measurable redistribution on questions the old schema never answered stably either.** Whether
that redistribution is an improvement is not something this change can claim.

**Not verified:** the actual premise — that the enum fixes llama3.2's invented-route failure — could
not be tested, because no Ollama server was running. The change is sound on first principles
(constrained decoding vs. a description) and is proven not to break Azure; the non-Azure benefit is
still a hypothesis.

---

## The real call sites (the registry)

Confirmed by reading the code, not assumed. **Re-verified function-by-function on 2026-08-23** — the
`Instrumented at` column below is the named function the `tracked_llm_call()` wrapper is actually on,
read out of the code rather than inferred from this table's own earlier claims:

| Agent | Instrumented at (file `::` function) | Telemetry `agent_name` | Model | Volume driver |
|---|---|---|---|---|
| Extraction (inbound) | `agents/extraction_agent.py::extract_node`, `::dynamic_qa_node` | `extraction.INBOUND.extract`, `extraction.INBOUND.dynamic_qa` | Azure OpenAI gpt-5-mini | Every ingested invoice |
| Extraction (outbound) | same two nodes — `agents/outbound_extraction_agent.py` is a thin wrapper over `run_extraction_agent(..., flow_direction="OUTBOUND")` (Gap 283) | `extraction.OUTBOUND.extract`, `extraction.OUTBOUND.dynamic_qa` | Azure OpenAI gpt-5-mini | Every outbound invoice |
| Chat classify + SQL/RAG/CHAT fork | `agents/query_agent.py::classify_query`, `::run_sql_generation_loop`, `::run_query_agent` | `chat.classify`, `chat.sql_generation`, `chat.sql_summary`, `chat.rag_answer`, `chat.conversational` | Azure OpenAI gpt-5-mini | Every chat turn (live default path) |
| SAGE orchestrator (Phase 2) | `agents/sage_orchestrator.py::_plan_node`, `::_synthesize_node`; tool-side in `agents/query_tools.py::identify_invoices`/`::aggregate` (via `telemetry_agent_name`) and `::search_invoices` | `sage.planner`, `sage.synthesis`, `sage.identify`, `sage.aggregate`, `sage.search` | Azure OpenAI gpt-5-mini | Every chat turn once `ENABLE_AGENTIC_SAGE` is on (off today) |
| Trainer / EVOLVE correction loop (Feature 18) | `agents/trainer_agent.py::refine_constraints` (conversational correction turn) and `routers/trainer.py::flag_missed_alert` (alert-anchored "I expected an alert" draft) | `trainer.refine_constraints`, `trainer.missed_alert_rule` | Azure OpenAI gpt-5-mini | Each correction turn / each alert-anchored correction |
| Trainer rule guardrail (Gap 217) | `routers/trainer.py::_validate_rule_text` | `trainer.rule_guardrail` | Azure OpenAI gpt-5-mini | Every rule preview and every commit |
| SENTINEL audit checks | tax/payment-status detectors | **No LLM** — corrected 2026-08-21 during Phase 1. Both named detectors (`detect_tax_component_term`, `detect_payment_status_question`) are pure regex, and no other audit path calls a model. SENTINEL's model cost is the `extraction.*` calls it audits. | — | Every extracted invoice |
| Dashboard insights | `routers/dashboard.py::get_dashboard_insights` | `dashboard.insights` | Azure OpenAI gpt-5-mini | Every cache miss on the Actionable Insights panel (1h TTL per tenant) |
| Trainer QA-panel summary | `routers/trainer.py::_answer_qa_from_session_data` | `trainer.qa_summary` | Azure OpenAI gpt-5-mini | Every QA-test turn against a not-yet-ingested uploaded sample |
| Eval judge (offline harness, not a product path) | `services/agent_eval.py::_invoke_structured` | `eval.claim_decomposition`, `eval.faithfulness`, `eval.relevance`, `eval.accuracy`, `eval.persona` | Azure OpenAI gpt-5-mini | Each graded eval case — only when someone runs `scripts/run_agent_eval.py` |
| Embeddings | `chroma_client.py` | **no event** — local model, not billed per call | BAAI/bge-m3 (local) | Every indexed page |

Two rows (dashboard insights, trainer QA-panel summary) were added 2026-08-21 after Phase 1 found
them: two real, billable call sites the original registry had missed. The trainer rule guardrail and
eval judge rows were added 2026-08-23 for the same reason — both are real `tracked_llm_call()` sites
that existed in code but had no row here, so the table under-stated its own coverage.

**Coverage claim, and how it was checked (2026-08-23):** a repo-wide grep for every LLM invocation
outside `.venv/`, `tests/` and `scripts/` returns **17** call sites — 14 written as `<llm>.invoke(`,
plus extraction's three, which pass the bound method to `invoke_with_retry(structured_llm.invoke,
...)` and so do not match an `.invoke(` pattern at all (worth knowing before anyone re-runs this check
and concludes extraction is uninstrumented). Every one of the 17 is lexically inside a
`tracked_llm_call()` block. There is no un-instrumented LLM call in this application today.

This table is small enough to stay a static doc section, not a dynamic registry service.

## Lightweight-tier coverage verified (2026-08-23)

The scope table above assigns three registry rows a **lightweight** depth of treatment — hard metrics
only (cost, latency, error/retry rate), no soft/judged metrics, because they are lower volume and
lower stakes than extraction or chat. This pass was scoped as "add that missing telemetry". **No
telemetry was missing.** All five call sites behind those three rows already carried the Phase 1
`tracked_llm_call()` wrapper, verified by reading each function rather than trusting the registry
table:

| Registry row | Function actually carrying the wrapper | `agent_name` | Extra attribute | Instrumented |
|---|---|---|---|---|
| Trainer / EVOLVE correction loop | `agents/trainer_agent.py::refine_constraints` | `trainer.refine_constraints` | `scope` | Phase 1, 2026-08-21 — **already present** |
| Trainer / EVOLVE correction loop | `routers/trainer.py::flag_missed_alert` | `trainer.missed_alert_rule` | `alert_type` | Phase 1, 2026-08-21 — **already present** |
| Trainer / EVOLVE correction loop (guardrail) | `routers/trainer.py::_validate_rule_text` | `trainer.rule_guardrail` | `rule_count` | Phase 1, 2026-08-21 — **already present**, but had no registry row until today |
| Dashboard insights | `routers/dashboard.py::get_dashboard_insights` | `dashboard.insights` | `invoice_count` | Phase 1, 2026-08-21 — **already present** |
| Trainer QA-panel summary | `routers/trainer.py::_answer_qa_from_session_data` | `trainer.qa_summary` | `field_count` | Phase 1, 2026-08-21 — **already present** |

`tenant_id` is explicitly threaded to all five (`run_trainer_agent` → `refine_constraints`,
`_handle_qa_test_turn`'s `TenantContext` → `_answer_qa_from_session_data`, the two router endpoints'
own `TenantContext`, and `preview_session_rules`/commit → `_validate_rule_text`), so none of them
relies on the middleware contextvar alone — which matters, because `TracingAndLoggingMiddleware` sets
`request_id`/`trace_id` but not `tenant_id`.

**What this pass actually added: the tests.** The gap was not instrumentation, it was that no test
asserted any of it, so the wrapper could have been dropped from any of these five sites silently and
the cost rollup would have quietly under-reported. `tests/test_telemetry.py` gained **9 tests** in a
new "Call-site coverage — the lightweight (hard-metrics-only) tier" section (5 pre-existing tests
cover the helper's mechanics; 14 total now):

| Test | What it pins |
|---|---|
| `test_dashboard_insights_emits_one_hard_metrics_event` | Exactly one event per cache miss, correct `agent_name`/`model`/`tenant_id`/`invoice_count` |
| `test_dashboard_insights_failure_is_still_measurable_as_an_error` | The handler swallows the exception and returns an empty panel (Gap 30's fail-soft contract), so the event is the **only** place this agent's error rate can be measured at all |
| `test_trainer_qa_summary_emits_one_hard_metrics_event_with_real_tokens` | Real token capture (88/12/100) off a `GenericFakeChatModel` through the production code path — the one lightweight site using an unstructured `llm.invoke()`, so a real LangChain model can stand in |
| `test_trainer_qa_summary_failure_is_still_measurable_as_an_error` | Same fail-soft-swallows-the-error shape as the dashboard |
| `test_trainer_qa_summary_makes_no_call_and_emits_nothing_without_extracted_data` | The early-return branch emits nothing — a spurious event there would inflate this agent's call count with calls that never happened |
| `test_trainer_refine_constraints_emits_one_hard_metrics_event` | EVOLVE's conversational correction turn, with `scope` |
| `test_trainer_refine_constraints_error_is_recorded_before_the_gap_212_reraise` | Gap 212 fails closed and re-raises; the event is emitted anyway |
| `test_trainer_missed_alert_draft_emits_one_hard_metrics_event` | Feature 18's alert-anchored draft, with `alert_type` so a noisy correction path is visible per check |
| `test_trainer_rule_guardrail_emits_one_hard_metrics_event` | Gap 217's guardrail — recurring spend on every preview/commit, not a rare validation branch |

Each test calls the **real** function with a fake model patched over `get_llm()`, not
`tracked_llm_call()` directly, and asserts the six fields a cost/latency/error rollup reads
(`tokens_in`, `tokens_out`, `tokens_total`, `latency_ms`, `status`, `llm_calls`) plus `model` and
`tenant_id`. The fake is a hand-written `_FakeLLM` rather than a `MagicMock` on purpose: a MagicMock
answers every attribute, so `resolve_model_name()` would fall through to settings and the `model`
assertion would prove nothing about attribution at that call site.

**Verified how:** `uv run pytest tests/test_telemetry.py tests/test_trainer.py tests/test_dashboard.py
-p no:randomly -q` → **89 passed** (169s). The two dashboard tests were additionally
mutation-checked — deleting the `tracked_llm_call()` block from `get_dashboard_insights` makes both
fail, and restoring it makes all 14 pass again — so they genuinely detect removal rather than passing
vacuously. No application code was changed by this pass.

**Deliberately not done:** soft/judged metrics for these three rows. The scope table's reasoning
holds — lower volume, lower stakes, doesn't justify the judge-call cost. Revisit only if one of them
develops its own measured quality problem.

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

## Track 1 as built — extraction & alerts (2026-08-23)

Net new. Nothing like it existed before this date: alert **precision** was measurable from Review
Console dismiss-vs-correct actions on real documents, but alert **recall** was not, for the reason
stated above — nobody flags what wasn't flagged.

### Where the review artifacts live — read this first

`docs/extraction_benchmark/` is the review location, and `docs/extraction_benchmark/README.md` is
the methodology record written for architect and business-analyst review before any figure from this
track is trusted. The founder's requirement was that the artifact trail be as important as the test
cases, so the corpus is written out in a form readable without reading any Python:

| Path | Generated? | What it is |
|---|---|---|
| `docs/extraction_benchmark/README.md` | no | Methodology, design rationale, limits, findings. The document to review. |
| `docs/extraction_benchmark/case_manifest.md` | yes | Every case as prose + tables: field changed, correct value, planted value, alert that must fire, why the issue is worth planting. |
| `docs/extraction_benchmark/case_manifest.json` | yes | The same machine-readable, including full OCR text and full extracted record per case. |
| `docs/extraction_benchmark/documents/*.txt` | yes | 17 rendered documents. A seeded file and its clean parent differ by exactly the named mutation, so any diff tool shows the planted issue. |
| `docs/extraction_benchmark/runs/<mode>-<ts>.json` | yes | One run's raw observations + scores. |
| `docs/extraction_benchmark/runs/<mode>-latest.md` | yes | Most recent run of that mode, as a summary. |

No RNG anywhere in the generator, so regenerating over an unchanged tree reproduces the corpus byte
for byte (`test_regenerating_the_corpus_is_byte_identical`).

### File coordinates

| File | Function / symbol | What it does |
|---|---|---|
| `tests/extraction_benchmark/documents.py` (new) | `InvoiceSpec`, `LineSpec`, `TaxLineSpec` | The invoice as data. One spec is the single source for both halves of a case. |
| | `InvoiceSpec.render_ocr_text()` | The OCR text the pipeline is fed, shaped like Document Intelligence's `content` output — whitespace-aligned table cells, not a markdown table, because the `verify_*_in_source_text` checks tokenise on whitespace-adjacent numbers and a pipe table would make them easier than they are in production. |
| | `InvoiceSpec.ground_truth()` | The known-correct extraction of that same text, in the extraction schema's own field names, so the comparison needs no translation layer. |
| | `InvoiceSpec.initial_extraction()` | A perfect extraction as `extract_node` would return it — what verify-mode feeds `verify_node`, and what a field mutation edits. |
| | `CLEAN_DOCUMENTS`, `CLEAN_BY_ID` | The four clean documents (US flat sales tax, India CGST+SGST with round-off, EU reverse-charge zero VAT, outbound with a trade discount). |
| `tests/extraction_benchmark/mutations.py` (new) | `SeededCase` | One clean document plus exactly one planted issue, carrying `field_path`, `correct_value`, `planted_value`, `expected_alert_type`, `tolerated_alert_types`, `rationale`, `surface`. The manifest is generated from these fields — the record *is* the case, not a description of it. |
| | `mutate_printed_total_does_not_reconcile()`, `mutate_printed_subtotal_not_sum_of_lines()`, `mutate_printed_line_amount_off()`, `mutate_required_field_not_printed()` | The four **document-surface** mutators: the OCR text is changed, so the document itself is inconsistent. |
| | `mutate_fabricated_total()`, `mutate_tax_silently_corrected()`, `mutate_subtotal_not_in_source()`, `mutate_unit_price_not_in_source()`, `mutate_line_amount_not_in_source()`, `mutate_required_field_dropped()`, `mutate_low_field_confidence()` | The seven **extraction-surface** mutators: the extracted record (or the Doc Intelligence confidence stub) is changed while the text stays clean. |
| | `_shift()`, `MUTATION_REL`, `MUTATION_ABS_FLOOR` | The one place the tolerance-clearing policy lives: `max(5% of the amount, 25.00)` against Gap 31's `max(0.01, 0.5%)` band. |
| | `_replace_money_in_text(..., on_line_with=)` | Rewrites one printed figure on one identified line, and raises unless exactly one line changes. Line-scoped because the zero-VAT document prints the same figure as subtotal and as total, and a whole-text replace would mutate both — which would make the manifest's "what was changed" entry a lie. |
| | `build_seeded_cases()`, `_PLAN`, `ocr_result_for()`, `SEEDED_ALERT_TYPES` | The frozen 13-case seeded set. |
| `tests/extraction_benchmark/metrics.py` (new) | `values_match()`, `compare_fields()`, `field_accuracy()` | Field comparison with money-to-the-cent, date normalisation, legal-suffix-stripped name matching, and line items matched by description rather than position. A failed extraction is scored as every field missed, never dropped from the denominator. |
| | `score_seeded()`, `SeededOutcome` | A hit requires the **expected type specifically**. Anything fired that is neither expected nor declared-tolerated is reported as `collateral`. |
| | `ConfusionMatrix`, `build_confusion()`, `recall_by_alert_type()` | The confusion matrix the scoping table asks for, unit = one document. Every empty denominator returns `None`, never 0.0. |
| `tests/extraction_benchmark/harness.py` (new) | `run_benchmark()`, `run_clean_case()`, `run_seeded_case()` | The two run modes. |
| | `_verify_only()` | Calls the **real** `agents/extraction_agent.py::verify_node` with a hand-supplied extraction. Deliberately generates a `file_path` with no "audit" substring, because `verify_node`'s `legacy_audit_path_shim` short-circuits the entire check set on an inbound path containing that word. |
| | `_run_live()` | Calls the real `run_extraction_agent()` end to end. |
| | `score_clean_run()`, `score_seeded_run()` | Marks extraction-surface cases `not_applicable` under live mode rather than scoring them. |
| `tests/extraction_benchmark/artifacts.py` (new) | `build_manifest()`, `render_manifest_markdown()`, `write_corpus_artifacts()` | The review corpus. |
| | `summarise()`, `render_run_markdown()`, `write_run_artifacts()` | The run record. |
| `scripts/run_extraction_benchmark.py` (new) | `main()` | `--mode verify|live`, `--cases`, `--artifacts-only`, `--no-gate`, `--json`. Exit 1 on any missed seeded issue, clean-document false positive, or error — so it is usable as the pre-deploy gate the Cadence section names, as-is. |
| `tests/test_extraction_benchmark.py` (new) | 116 tests | Tests the harness, not the fixtures. See below. |

### The one design decision worth arguing about: two mutation surfaces

The scoping table above describes one seeded set. As built there are two, and the distinction is
load-bearing rather than an implementation detail.

* **`surface="document"`** — the OCR text is mutated. The vendor's own arithmetic is wrong, or a
  required field is not printed. A correct extraction transcribes it faithfully and an arithmetic
  check catches it. Gradeable in **both** modes.
* **`surface="extraction"`** — the extracted record is mutated while the text stays clean. This
  simulates the model going wrong: a fabricated total, a silently "corrected" tax figure, a dropped
  field. Gaps 33/36/43/44/46 exist for exactly this and nothing else can catch it. Gradeable in
  **verify mode only**, because a correctly-behaving model will not make the planted error on demand.

Eight of the thirteen seeded cases are extraction-surface. That is the honest reason `--mode verify`
is the primary mode and not a fallback: it is the only mode that can answer "if the model fabricated
a total, would the check catch it?". Live mode is the only mode that can answer "does the model
fabricate totals in the first place?". Neither answers both, and live mode reports the eight as
`not_applicable` and skips them without spending tokens rather than counting them as misses — which
would have made live-mode recall look catastrophic for entirely the wrong reason.

### What was measured — both modes really run, 2026-08-23

**`--mode verify`** (deterministic, no network, 4 clean + 13 seeded):

| | Alert fired | Stayed silent |
|---|---|---|
| **Seeded** | 13 (TP) | 0 (FN) |
| **Clean** | 1 (FP) | 3 (TN) |

* **Alert recall 100%** (13/13) — the number the parameters section above calls a "known, accepted
  gap" because production usage cannot produce it. All ten seeded check types fired on the case they
  were seeded for.
* **Clean-document false-positive rate 25%** (1/4). Document-level precision 92.9%.
* Zero collateral alert types.

**`--mode live`** (real Azure OpenAI `gpt-5-mini`, end to end, 4 clean + 5 gradeable seeded):

* **Field-level accuracy 81/81 = 100%.** Every graded field on all four clean documents, including
  `round_off: 0.00` on the GST invoice (a zero the model had to transcribe rather than drop) and the
  summed `tax_amount` of INR 15,570.00 that appears nowhere on the document as a single figure.
* **Alert recall 100%** on the five document-surface cases; the eight extraction-surface ones
  reported `not_applicable`.
* The same single false positive as verify mode — which is the point of running both: it is a
  property of the check, not of either mode.

**Read the 100% field accuracy carefully.** It is a real measurement of a real model over this
corpus, and what it means is that **the corpus does not currently discriminate on extraction
accuracy** — it is a regression detector and a baseline, not a difficulty measure. Making it
discriminate needs harder documents (noisy OCR, multi-page, rotated tables, genuinely ambiguous
layouts), which is real additional work and is not done. This number must not be reported as
"extraction is 100% accurate"; it is "extraction is 100% accurate on four clean, well-formed
synthetic documents in text-only mode".

### The defect the first run found — Gap 293

`outbound_trade_discount` is internally consistent (11,400.00 − 570.00 + 758.10 = 11,588.10) and
raises `tax_mismatch` in **both** modes. The cause is not the check:
`OutboundInvoiceExtractionSchema` (`agents/extraction_agent.py`) has no `discount_amount`, no
`discount_percent` and no `round_off` field, so a discount printed on an outbound invoice has nowhere
to go. `verify_node` then passes `None` for all three into `verify_totals_math`, which computes
`11,400.00 + 758.10 = 12,158.10` against a printed total of `11,588.10`.

So **every outbound invoice carrying a trade discount or a rounding line lands on `NEEDS_REVIEW` for
a correct extraction of a correct document**, and no tuning of `verify_totals_math` fixes it — the
information is not in the record. The inbound schema has all three fields; this is a Gap-283-era
divergence, not a deliberate difference.

The case is **deliberately left in the clean set** rather than sanitised: it is the only reason the
false-positive rate is a measurement rather than a formality, and a benchmark whose clean set is
curated until it goes quiet is measuring the curation. Pinned by
`test_known_outbound_discount_false_positive_is_still_present`, which should be **deleted, not
edited**, when the schema is fixed. Not fixed in this pass — adding fields to the outbound schema
changes what the model is asked to produce and what `queue_worker/outbound_handlers.py` /
`routers/outbound_audit.py` consume, which is a product change, not a test change.

### Not measured, and why

* **`extraction_failed` and `token_limit_exceeded`** are reachable alert types but neither is a
  document-quality check (one is a parse/LLM failure, the other a pre-flight guardrail that returns
  before the graph runs), so neither belongs in a recall figure and neither is seeded.
* **The multimodal branch.** `extract_node` goes multimodal only when `LLM_PROVIDER=azure` *and*
  `state["images"]` is non-empty; these cases carry no PDF, so live mode exercises the text-prompt
  branch. Real, but not what production uses on a PDF.
* **OCR quality.** Text is rendered from the spec, so real OCR noise — the commonest real source of
  both missed issues and false positives — is absent.
* **Feature 18 tenant tolerance overrides.** Every case runs with `rules=None`.

### Verified how

* `uv run pytest tests/test_extraction_benchmark.py -q -p no:randomly` — **115 passed, 1 skipped**.
  The tests are of the harness, not the fixtures: a test asserting "the clean US invoice totals
  5,517.23" would only restate `documents.py` and would pass just as happily if the whole measurement
  were wrong. What is tested is that the clean documents really are silent through the **real**
  `verify_node`; that every mutation changed what the manifest says and only that; that a document
  mutation changes exactly one line; that every arithmetic mutation clears `REL_TOLERANCE` read from
  the product rather than restated; that a wrong alert type is not a hit; that a not-applicable case
  leaves the recall denominator; that an empty denominator is `None` and not 0.0; and that a dropped
  line item costs every field of that line.
* `uv run python scripts/run_extraction_benchmark.py --mode verify` and `--mode live`, both run for
  real. Every figure in this section is that run's output, written to
  `docs/extraction_benchmark/runs/`.

### The cadence blocker, confirmed and unresolved — applies to both tracks

The Cadence section above asks for nightly **and** a pre-deploy gate. The pre-deploy gate works
today: `scripts/run_extraction_benchmark.py` exits 1 on any miss/false-positive/error, and a GitHub
Actions job checks out the whole repo, so the harness is present.

The **nightly ACA job is still blocked, for the same reason the deleted `caj-agent-eval-dev` job
was** — the reason this document's rescope section flags in passing and which was re-confirmed
against the file, not assumed. `Prod_Invoice_LLM/.dockerignore` lines 37-48 exclude both `docs/` and
`**/tests/` from every image built from this repo. Track 1's entire harness lives in
`tests/extraction_benchmark/` and Track 2's case set is `tests/agent_eval_golden_sample.py`, so
**neither track can run inside a deployed container as things stand**, no matter what scheduler is
pointed at it. `scripts/` is not excluded, so the two entry-point scripts would ship — and would
fail on import.

Three ways out, none of them chosen here because it is a packaging decision with real consequences:
move the benchmark corpora out of `tests/` into a shipped package; narrow the `.dockerignore` rule
to exclude `test_*.py` rather than the whole tree; or build a separate eval image. **Deciding this is
a prerequisite for the nightly half of the cadence** and should not be discovered again the next time
someone tries to wire a scheduled job.

## Track 2 as built — SAGE chat (2026-08-23)

Extended, not rebuilt. The scoping text above says "rebuilt case set"; the instruction as executed
was **more cases, not a full rewrite**, and all eleven original `agent_eval_golden_sample.py` cases
are still present (pinned by `test_the_case_set_was_extended_not_rewritten`).

### What was already there — checked before assuming

`services/agent_eval.py` already scored **faithfulness** and **relevance** (and `accuracy`, which is
not one of the five named soft metrics, and `persona`, which is *domain expertise* — CGST vs. IGST,
RCM's correct zero — not tone). Genuinely missing were **helpfulness**, **completeness** and
**persona/tone fit**, and the fact that the existing scoring took four judge calls where the scope
asks for one.

`persona_score` is deliberately kept as its own separate thing rather than folded into the new
`tone_score`. "Did it reason correctly about tax components" and "does it sound like the product's
assistant" are different questions, and merging them would lose exactly the distinction the
diagnosis table in this document depends on (faithfulness → context, tone → persona block,
completeness → context or system prompt).

### File coordinates

| File | Function / symbol | What it does |
|---|---|---|
| `services/agent_eval.py` | `CombinedSoftVerdict` (new) | One schema carrying all five soft metrics. Field order is the order the judge is asked to work in: claim decomposition and per-claim verdicts first, so the later holistic judgements are formed by a model that has already enumerated what the answer asserts. |
| | `_build_combined_prompt()` (new) | The single prompt. Five numbered dimensions, each told explicitly what it is **not** ("Not 'is it right'", "Correctness is not tone", "not against an ideal answer") — without that they collapse into one another, which is the same failure that made relevance unstable in the first place. |
| | `score_soft_metrics_combined()` (new) | One judge round-trip → `(scores, claims, notes, 1)`. Returns `None` for anything unscored, never 0.0. |
| | `EvalScores` | Gained `helpfulness_score`, `completeness_score`, `tone_score`, and `judge_mode` (`"combined"`/`"separate"`). |
| | `score_answer(..., combined_judge=False)` | The switch. Default False. |
| `tests/agent_eval_golden_sample.py` | `CASES` (extended 11 → 20) | Nine new cases, four for completeness, two for helpfulness, two for persona/tone, one for faithfulness. |
| | `_threshold_reference()`, `_cross_currency_reference()`, `_OVER_20K_USD` (new) | The two cases whose correct answer is a *set* over every seeded row are computed from `ALL_ROWS`, not typed. |
| `scripts/run_agent_eval.py` | `--judge separate\|combined`, `score_turn(..., combined_judge=)` | Runner wiring. `summarise()` gained `helpfulness_mean`/`completeness_mean`/`tone_mean` each with its own `_scored_turns` denominator, plus `judge_llm_calls_total`. |
| | `persist()` | Writes `judge_mode=` into the `agent_eval_run` notes and passes the three new scores through `track_eval_result()`'s `**extra_attributes`. **No migration was added** — see below. |
| `services/agent_eval.py` | `COMPLETENESS_KIND_SCORES` (new) | Classify-then-fix for completeness, added after the first real run — see "Two things found by running it" below. |
| `tests/test_agent_eval.py` | +35 tests (**91 total, all passing**) | Combined-judge mechanics, the completeness kind policy, and the extended case set. |

### The two-step structure survives the merge — that is the point

Failure modes 3 and 4 (recorded in `services/agent_eval.py`'s module docstring) were both fixed by
making the judge **classify before it scores**: a `claim_type` per claim, an `answer_kind` per
answer. The combined schema keeps both, and `RELEVANCE_KIND_SCORES` still fixes the score **in code**
for the three definitional kinds, so two paraphrases of the same correct refusal still cannot land on
different numbers. What is merged is the number of round-trips, not the rubric. Claim decomposition
also moves inside the same call — the judge emits `claim` + `claim_type` + `supported` in one pass
instead of a separate decomposition step, which is where the fourth call went.

Both fixes are re-asserted against the *combined* path by their own tests
(`test_combined_absence_claim_against_an_empty_result_is_supported`,
`test_combined_relevance_is_still_fixed_by_kind_not_by_the_judges_number`), rather than assumed to
have carried over.

### Three deliberate constraints, stated so they are not read as oversights

1. **`combined_judge` defaults to False.** Merging four prompts into one changes what the judge is
   looking at when it forms each verdict, so a faithfulness mean from combined mode is not assumed to
   sit on the same scale as one from separate mode — the same non-comparability this document already
   records for the pre/post failure-mode-3-and-4 figures. Flipping the default is a decision to make
   on measured evidence, not silently mid-series. `judge_mode` travels with every result and into the
   `agent_eval_run` notes so a reader comparing two rows can tell.
2. **The three new metrics have no floor and do not feed `decide_pass()`.** Same rule as the
   component scores: adding a dimension to the pass criterion halfway through a series redefines what
   a pass means. Pinned by `test_the_new_soft_metrics_do_not_change_the_pass_decision`.
3. **Accuracy stays its own call in both modes.** It is not one of the five, it needs the reference
   answer, and the combined prompt is deliberately never shown that reference — otherwise a judge
   could mark a claim supported because the *reference* says so rather than because the *evidence*
   does. Pinned by `test_the_combined_prompt_is_never_shown_the_reference_answer`.

### Cost

Measured by test, not asserted in a comment
(`test_combined_mode_costs_two_calls_where_separate_mode_costs_four`), with the persona component off
on both sides so the figure isolates the merge:

| Mode | Judge calls per graded turn |
|---|---|
| separate | 4 — claim decomposition, faithfulness verdicts, relevance, accuracy |
| combined | 2 — one five-metric call, plus accuracy |

With the persona component on (the runner's default) it is 5 vs. 3. So the combined judge is a ~40%
reduction in judge round-trips **and** scores three metrics the separate path does not score at all.

### The nine new cases, and why each exists

The original eleven were authored before helpfulness/completeness/tone existed as metrics, and are
weighted toward faithfulness failures: a single-fact lookup cannot be *incomplete*, and a
neutrally-phrased question cannot show whether the assistant sounds like itself. The nine run against
the **same** nine seeded rows (`ALL_ROWS`) — no new fixture data, so the whole set still runs against
one in-memory SQLite tenant.

| Case | Axis | What it can catch that nothing else could |
|---|---|---|
| `multi_part_totals_and_dates` | completeness | Three independent facts in one row, so a partial answer cannot be blamed on the evidence. Separates "incomplete" from "unfaithful" directly. |
| `all_vendors_over_twenty_thousand` | completeness + currency | Gap 268's truncation generalised past a two-way comparison, with a currency trap in the same question. |
| `two_vendors_two_questions` | completeness | Two vendors and two different questions in one turn — answering the easy half and dropping the comparison. |
| `line_item_breakdown_completeness` | completeness | Gap 271's invoice asked the opposite way round: an answer that gives one line when it needs the whole invoice. |
| `unsupported_field_asks_for_alternative` | helpfulness | "Not tracked" full stop vs. "not tracked, here is what is" — both faithful, one useless. |
| `zero_result_with_useful_redirect` | helpfulness | Gap 224's shape with *both* filters wrong, so a partial match cannot rescue it. |
| `hostile_user_tone` | persona/tone | A real question wrapped in a complaint. Every other case is neutrally phrased, so nothing measured whether the register survives a hostile user. |
| `internals_probe_no_leak` | persona/tone | Leaked SQL/table/tool names are explicitly a tone failure in the new rubric, and the SQL route generates a real statement nearly every turn, so the material to leak is always present. |
| `cross_currency_total_refused` | faithfulness | The one arithmetic the persona forbids, against a deliberately mixed-currency tenant. |

**A real drift caught while writing these**, worth recording because it is the exact failure
`tenant_stats_summary()`'s own docstring warns about: `ALL_ROWS` is **nine** rows, not the seven the
incident history contributes — `tests/large_invoice_fixture.py` adds two more, one of them a USD
271,019.63 invoice. A hand-typed "vendors over USD 20,000" reference answer named two vendors and
silently omitted it. Both set-valued reference answers are now **computed** from `ALL_ROWS`, and
`test_the_threshold_case_is_computed_over_every_seeded_row_not_a_typed_subset` re-derives the set
independently so the same drift cannot recur.

### What was measured — three real runs, 2026-08-23

All against the live Azure OpenAI `gpt-5-mini`, default chat path, the same 20 cases, no persistence.
Output files: `tests/agent_eval_output_separate_20case.json`, `tests/agent_eval_output_combined.json`.

| | separate | combined (run 1, pre-fix) | combined (run 2, post-fix) |
|---|---|---|---|
| turns | 20 | 20 | 20 |
| **judge calls, total** | **97** | **60** | **60** |
| pass rate | 0.35 | 0.35 | 0.35 |
| faithfulness mean | 0.819 | 0.806 | 0.880 |
| relevance mean | 0.985 | 0.970 | 0.970 |
| accuracy mean | 0.59 | 0.60 | 0.60 |
| **helpfulness mean** | — | 0.910 (20/20) | 0.925 (20/20) |
| **completeness mean** | — | 0.925 (20/20) | 0.975 (20/20) |
| **persona/tone mean** | — | 0.970 (20/20) | 0.985 (20/20) |
| context mean (deterministic) | 0.765 | 0.765 | 0.765 |
| orchestration mean (deterministic) | 0.905 | 0.889 | 0.878 |
| cost/turn (USD, gpt-5-mini list) | 0.00441 | 0.00441 | 0.00424 |
| errors | 0 | 0 | 0 |

Three things this actually establishes, and one it does not:

1. **The judge-call reduction is real**: 97 → 60, a 38% cut, while adding three metrics the separate
   path does not produce at all. Both are measured, not projected.
2. **The three new metrics discriminate.** All three scored on 20/20 turns and none saturated at
   1.0: helpfulness landed 0.4 on the turns whose correct answer was a negative with no offered next
   step, completeness landed 0.5 on `freight_per_vendor` (a per-vendor question answered without the
   vendor), tone landed 0.7 and 0.4 on real register/leak failures. A metric that returned 1.0
   everywhere would have been worth deleting.
3. **No scale shift was detected between the two judges** — faithfulness 0.819 vs. 0.806/0.880,
   relevance 0.985 vs. 0.970, identical pass rate.

**What it does not establish, and this is the important caveat: these are not paired
measurements.** Each run regenerated the answers, so every delta above mixes the judge's scale with
the product's own run-to-run non-determinism. The size of that confounder is visible in the table
itself: **two combined runs of the same 20 cases, with no change to the faithfulness path between
them, moved faithfulness from 0.806 to 0.880** — a 0.074 swing that is entirely product variance.
The separate-vs-combined difference (0.013) is an order of magnitude smaller than that. So the honest
statement is *"no scale shift larger than roughly ±0.08 is detectable this way"*, not *"the two
judges agree"*. A real answer needs a **paired** comparison — score the *same* stored answers with
both judges — which the saved run files already contain everything for (`answer_prose`, `context`,
`executed_queries` per turn) and which no code does yet. That is the right next step before
`combined` becomes the default.

### Two things found by running it

**1. Completeness had failure mode 4's shape, and it was found the same way — by reading real
output.** `internals_probe_no_leak` was declined correctly and scored completeness **0.00**, with the
judge's own reason: *"the user asked for the exact SQL and the table; the assistant refused to
provide them ... so the substantive request is unaddressed."* That verdict is correct on a rubric
phrased as *"does it cover every part of what was asked"* — and a response whose correct content is a
refusal can never satisfy that phrasing. Identical structure to failure mode 4, one metric down.

Fixed with the identical mechanism: `COMPLETENESS_KIND_SCORES` fixes the score **in code** for the
kinds whose completeness is definitional (`out_of_scope_refusal` → 1.0, `capability_or_greeting` →
1.0, `off_topic` → 0.0), reusing the `answer_kind` the same verdict already carries so completeness
and relevance can never disagree about what kind of response they are looking at. The rubric text
also now says a refusal is complete. `direct_answer` / `clarifying_question` / `no_results_report`
still use the judge's number, because for those completeness genuinely is a matter of degree.
Verified live in run 2: the same case went 0.00 → 1.00. Five tests pin it.

**2. Gap 294 — the chat path pastes generated SQL into user-facing answers.** Found on the first
combined run, on `payment_terms_document`: the answer contained a full `SELECT ... FROM invoice WHERE
tenant_id = '00000000-...'` block, including internal column names and the tenant UUID. On
`internals_probe_no_leak` it reproduced in **both** runs, and worse — the SQL it claimed to have run
was *fabricated* (it names a table `invoices`; the real table is `invoice`), which faithfulness caught
as 1/3 claims supported.

**The honest read on which metric caught it**: tone caught the leak once (0.40 on
`payment_terms_document`) and **missed it twice** (1.00 on `internals_probe_no_leak` in both runs),
despite the rubric explicitly listing leaked SQL/table/column names as a 0.4 anchor. So the tone
metric is not a reliable leak detector on this evidence — faithfulness is what actually flagged the
`internals_probe` case, because the fabricated SQL traced to nothing. Reported as observed rather than
written up as a success for the new metric.

Not fixed here. The fix belongs in the SQL-route summary prompt, and Feature 21's history (Gap 287)
is a direct warning against adding a prose mandate to that prompt without regression-testing it
against every other rule already in it. `internals_probe_no_leak` is now a standing case, so once a
mandate lands both the leak and the over-correction are measurable.

### No migration was added, deliberately

`AgentEvalRun` has no column for `helpfulness_score`/`completeness_score`/`tone_score`. They travel
three ways instead: in the row's free-text `notes` (via `score_notes`), on the
`agent_eval_run` custom event through `track_eval_result()`'s existing `**extra_attributes`
(pinned by `test_track_eval_result_carries_the_new_soft_metrics_as_event_extras`), and in the run's
JSON output. The workbook can therefore chart them with no schema change. Adding three more nullable
columns is the right long-term shape and is a deliberate follow-up, not an oversight — it should
happen once combined mode is the decided default, not before, so the columns are not added for a
mode that might not be adopted.

### Verified how

* `uv run pytest tests/test_agent_eval.py -q -p no:randomly` — **91 passed** (35 new).
* Three real runs against live Azure OpenAI gpt-5-mini over all 20 cases, figures above. The
  `--mode verify` gate's exit code was checked directly, not assumed: **1** with the known false
  positive present, **0** with `--no-gate`.
* Full backend suite, same invocation as every prior phase
  (`uv run pytest -q --ignore=tests/us --ignore=tests/realworld_tenant -p no:randomly`):
  **1248 passed, 3 failed, 7 skipped, 5 deselected** in 396s. The 3 failures are the same
  pre-existing, unrelated ones this document already records for the 2026-08-21 rounds: 2 in
  `test_connectors.py` needing a live Redis, 1 in `test_rag.py` calling `post_chat_message()`
  without its `background_tasks` argument.
* No dependency added by either track.

### Still open after this pass — both tracks

* **The nightly cadence is blocked on packaging**, not on a scheduler. See "The cadence blocker"
  above. The pre-deploy gate half works today.
* **A paired judge comparison** (score the same stored answers with both judges) has not been done,
  so the separate-vs-combined comparison is confounded by product non-determinism at roughly four
  times the size of the effect being measured. Prerequisite for making `combined` the default.
* **Track 1's corpus does not discriminate on extraction accuracy** (81/81). Harder documents, real
  PDFs exercising the multimodal branch, and real OCR noise are what would change that.
* **Gap 293** (outbound schema has no discount/round-off field) and **Gap 294** (chat pastes
  generated — and sometimes fabricated — SQL into user-facing answers) are both found, reproduced,
  documented and **not fixed**.
* **Model comparison** (the section below) is now runnable for extraction as well as chat —
  `run_extraction_benchmark.py --mode live` reads the deployment from config — but **no candidate
  model has been run through either track.**
* **Alert *precision* in the feature doc's parameter-table sense** (% of alerts leading to a real
  Review Console correction) is still not measured by anything here. Track 1 reports a
  *document-level* precision, which is a different quantity over a synthetic corpus, and the two must
  not be conflated.

## The nightly scheduler and the pre-deploy gate, as built (2026-08-23)

The "cadence blocker" above — both tracks' harness/data living under `tests/`, which
`.dockerignore` excludes from every image built from this repo — is fixed, and the
scheduler + gate the Cadence section always asked for now exist.

### Step 1: the `.dockerignore` fix — `benchmarks/`, not `tests/`

New top-level package `apps/invoice-be/benchmarks/`, importable at runtime inside the
deployed image. Everything the two scripts need to *import* moved there; everything
that is genuinely pytest-only (test functions, fixtures, `tests/run_agentic_sage_live.py`'s
own manual CLI) stayed in `tests/`.

| Moved to | From | Why |
|---|---|---|
| `benchmarks/extraction/` (`documents.py`, `mutations.py`, `metrics.py`, `harness.py`, `artifacts.py`, `__init__.py`) | `tests/extraction_benchmark/` | Track 1's whole harness — `scripts/run_extraction_benchmark.py` imports it directly. |
| `benchmarks/agent_eval_golden_sample.py` | `tests/agent_eval_golden_sample.py` | Track 2's 20-case set — imported by the runner and by `tests/test_agent_eval.py`/`tests/test_model_substitution.py` (which stayed in `tests/` and now import it back from `benchmarks/`). |
| `benchmarks/large_invoice_fixture.py` | `tests/large_invoice_fixture.py` | The `LARGE`/`SMALL` document-length A/B fixtures `run_agent_eval.py`'s `main()` seeds unconditionally. |
| `benchmarks/sage_seed_fixtures.py` (new) | `tests/run_agentic_sage_live.py`'s `TENANT_ID`/`_TENANT_STATS`/`_ROWS`/`_CHUNKS`/`_seed()` | Extracted, not the whole file — `run_agentic_sage_live.py` itself is a manual exploratory CLI (`QUESTIONS`/`run_once()`/`main()`), not something the scheduled job runs, so only the seed data it and `run_agent_eval.py` both need moved. `run_agentic_sage_live.py` now imports these back from `benchmarks/` rather than defining them twice. |

**A second, less obvious transitive dependency found while verifying this, not assumed
away:** `large_invoice_fixture.py`'s `InvoiceSpec.pdf_path()` lazily imports
`tests/e2e/pdf_builder.py` (reportlab) to render `LARGE`/`SMALL` on a cache miss. Moving
`large_invoice_fixture.py` alone would not have fixed this — `reportlab` is a **dev-only**
dependency (`pyproject.toml`'s `[dependency-groups] dev`, not `[project] dependencies`),
so `uv sync --frozen --no-dev` (`docker/Dockerfile.be`) never installs it in the deployed
image regardless of where `pdf_builder.py` lives, and `tests/e2e/` itself is excluded
either way. Fixed by pre-generating both PDFs once locally (`reportlab`/`fitz` are both
present in a dev environment) and **committing** them under
`benchmarks/fixtures/large_invoice/` (content-hashed filenames, not `tests/fixtures/` —
that path is also excluded) via a new one-off script, `benchmarks/_generate_fixture_pdfs.py`.
`InvoiceSpec.pdf_path()`'s cache-miss branch now raises a clear `ModuleNotFoundError` with
regeneration instructions instead of silently trying (and failing) to build a PDF inside a
container that has neither `tests/e2e/` nor `reportlab`. A cache hit is guaranteed at
runtime as long as `LARGE`/`SMALL`'s shape doesn't change without also regenerating and
committing the PDFs.

**Verified for real, not assumed:**

* `uv run pytest tests/test_extraction_benchmark.py tests/test_agent_eval.py tests/test_model_substitution.py tests/test_run_extraction_benchmark_cli.py -q -p no:randomly` — **251 passed, 1 skipped** (115+1 / 91 / 37 / 8 — the CLI-gate test file is new, see Step 3), same figures the doc already records for the harness itself, confirming the move changed no behaviour.
* Full backend suite: `uv run pytest -q --ignore=tests/us --ignore=tests/realworld_tenant -p no:randomly` → **1248 passed, 3 failed, 7 skipped, 5 deselected** in 406s — the same 3 pre-existing failures already on file (2 need a live Redis, 1 needs `post_chat_message()`'s `background_tasks` arg), none attributable to this move.
* `docker build -f docker/Dockerfile.be -t invoice-be-verify:step1 .` — a real build of the actual Dockerfile against the actual `.dockerignore`, then `docker run --rm invoice-be-verify:step1 python -c "import benchmarks.extraction.harness, benchmarks.agent_eval_golden_sample, benchmarks.large_invoice_fixture, benchmarks.sage_seed_fixtures; import os; print('tests/ present:', os.path.isdir('tests'))"` — {{DOCKER_VERIFY_RESULT}}
* `scripts/run_extraction_benchmark.py --mode verify` and `--mode live` both re-run for real from the new location, reproducing the doc's existing numbers (13/13 recall, the one known Gap 293 false positive; a repeat `--mode live` run scored recall **0.8**, not the earlier-recorded 1.0 — see "A real finding from re-running this" below).

### A real finding from re-running Track 1 live mode while verifying this

Re-running `--mode live` for real (to measure timing for `replicaTimeout`, see Step 2)
missed `outbound_trade_discount__required_field_not_printed` (expected
`missing_required_field`, fired `tax_mismatch` instead) — the earlier-recorded run scored
100% recall on all five document-surface seeded cases; this run scored 80% (4/5). Field
accuracy stayed 81/81 = 100%, and the known Gap 293 false positive reproduced identically.
This is exactly the run-to-run model variance the "nightly (catches drift)" half of the
Cadence section exists to catch — a single manual run cannot tell whether this is noise or
the start of a real drift, only a standing nightly series can, which is the entire
argument for building one rather than treating a single verification run as sufficient.
Not opened as a new Gap (no code changed, no fix implied) — recorded here as the first
real evidence the drift-catching half of this design has something to catch.

### Step 2: the scheduled job — `caj-benchmark-eval-dev`

Two files, following the pattern every scheduled job in this repo has had to use since
Gap 298 (`be_features_tracker.md`, 2026-08-23: a full `08-apps.bicep`/`params.dev.json`
deploy against this environment is not safe — stale ACR/naming-prefix drift would roll
back all four running container apps):

* **`infra/08-apps.bicep`** — a `benchmarkEvalJob` module (canonical declaration, mirrors
  `overdueSweepJob`/`opsDigestJob`), reusing `modules/compute/scheduled-job.bicep`. What a
  clean environment build produces; not what was actually deployed here.
* **`infra/benchmark-eval-job-only.bicep`** (new, actual deployable artifact) — same
  resource, hardcoded to this environment's real live names (`invoicellm` prefix,
  `acrinvoicellmdev2`), same shape as `infra/ops-digest-job-only.bicep`.

One container, two scripts chained with shell `&&` (the job module is single-command):

```
python scripts/run_extraction_benchmark.py --mode live --no-write --no-gate --json \
  --tolerate-fp outbound_trade_discount__clean \
  && python scripts/run_agent_eval.py --paths default
```

| Choice | Why |
|---|---|
| `--mode live` (Track 1) | The nightly's job is catching *model* drift day to day (see the finding above) — `--mode verify` is deterministic and would report the same numbers every night regardless of the deployed model's actual behaviour. |
| `--no-gate` | Gap 293's known, deliberately-not-fixed false positive would otherwise fail this job's execution status every single night on a non-regression, defeating the point of using the job's own status as a signal. |
| `--tolerate-fp outbound_trade_discount__clean` (new flag, `scripts/run_extraction_benchmark.py`) | Belt-and-suspenders with `--no-gate` here (the nightly job doesn't gate on exit code at all), but the same flag is what actually gates the pre-deploy check in Step 3 — added once, used both places. |
| `--no-write` | A Container Apps Job replica's filesystem is ephemeral — no volume is mounted — so `docs/extraction_benchmark/runs/` artifacts written inside the container are discarded on exit. `--json` keeps the scored summary in the execution's own stdout instead, which Container Apps Job execution history / Log Analytics retains. Per-call cost/latency still reaches Application Insights regardless, because `run_extraction_agent()`/`verify_node()` are the real production code paths, already wrapped in `tracked_llm_call()`. |
| `--paths default` only (Track 2) | SAGE orchestrator is off by default in production (`ENABLE_AGENTIC_SAGE`) — measuring `sage` too would add real cost and ~40 more minutes for a path with zero live traffic. |
| Default judge mode (`separate`, not `--judge combined`) | The Track 2 section above explicitly leaves flipping that default as a "decision required" pending a paired judge comparison — not something to decide silently from infra. |
| No `--persist-candidate`/`--provider`/`--model` | This is a baseline run of the application's own configured model, not a substitution comparison — `run_agent_eval.py` persists `agent_eval_run` rows and telemetry by default. |

**`replicaTimeout: 5400`** (90 minutes) — sized off a real measurement, not a guess:
`--mode live` (9 documents) took **4m57s**, timed for real against the live
`openai-invoicellm-dev` deployment. The 20-case default-path suite (separate judge) was
timed over a real partial run (5 of 20 cases completed in 10 minutes before the harness
was stopped, having already produced the timing data needed) at roughly 2 minutes/turn,
extrapolating to **~40 minutes** for all 20. ~45 minutes measured/extrapolated total;
5400s is roughly 2x that, generous but not open-ended.

**`cpu: 1.0` / `memory: 2.0Gi`** — this job imports the same agent/graph/SQL stack as
`ca-invoice-be` itself (`agents.query_agent`, `agents.extraction_agent`, `langgraph`,
`sqlalchemy`, `azure-ai-documentintelligence`), not the "a few queries plus outbound
HTTP" shape `caj-overdue-sweep-dev`'s 0.5 vCPU / 1.0Gi defaults were sized for.

**Verified for real:**

* `az bicep build --file infra/benchmark-eval-job-only.bicep` and `--file infra/08-apps.bicep` — both compile clean (the two warnings on the latter are pre-existing, in `invoice-be.bicep`/`front-door.bicep`, files this change did not touch).
* `az deployment group what-if --resource-group rg-invoice-llm-dev --template-file infra/benchmark-eval-job-only.bicep` — **1 to create, 50 to ignore, 0 to modify, 0 to delete.** The one resource is `Microsoft.App/jobs/caj-benchmark-eval-dev`, cron `0 3 * * *`, `replicaTimeout: 5400`, the exact chained command above, every secret/env reference resolved against the real live Key Vault/OpenAI/Chroma/App Insights resources.
* **Not deployed.** `az deployment group create` was deliberately not run — this creates a new resource that will call real Azure OpenAI on a schedule indefinitely, and that needs an explicit go-ahead, not an infra pass's own initiative.

**Cron:** `0 3 * * *` — after `caj-overdue-sweep-dev`'s `0 2 * * *`, clear of
`caj-ops-digest-dev`'s `0 1,7,13,19 * * *` slots, matching the deleted `caj-agent-eval-dev`
job's old schedule (confirmed free).

**Prerequisite that is not optional, stated in both bicep files' own comments:** the
backend image deployed to `ca-invoice-be-dev`/pulled by this job must already contain
`benchmarks/` and both scripts. They are new/moved as of this pass and, at the time of
writing, uncommitted — deploying this job against an older image produces a job whose
every execution fails with `ModuleNotFoundError`, the exact failure this whole pass exists
to fix. A CI build from a commit containing this change must land first.

### Step 3: the pre-deploy gate — `.github/workflows/deploy-dev.yml`

New job `benchmark-gate`, gated on the same `be`/`worker` path filter as the two deploy
jobs it now blocks (`deploy-backend`, `deploy-worker` both gained it in their `needs:`).
Runs before either image builds.

Deliberately **not** the full nightly suite — scoped down explicitly, not silently:

| Track | Pre-deploy gate | Nightly job | Why the difference |
|---|---|---|---|
| 1 (extraction) | **Full** corpus, `--mode verify` | `--mode live`, same corpus | Verify mode is deterministic and free (no network call) — seconds, not minutes. No reason to sample it; the reason to run `live` separately at night is model-drift detection, which a pre-deploy gate isn't trying to do. |
| 2 (chat) | **5 of 20 cases**, live model, gate on turn-level **error only** | Full 20 cases, live model, scored (not gated) | The full suite measured at ~2 min/turn (separate judge) is ~40 minutes — too slow for every push. |

The 5 cases (`--cases titan_steel_payment_status,rajesh_steel_cgst,internals_probe_no_leak,cross_currency_total_refused,zero_result_with_useful_redirect`) were chosen to span
faithfulness, persona/tone and helpfulness, and to include two real prior incidents (Gap
270's ambiguous-direction routing, Gaps 263/264's CGST relabelling) plus
`internals_probe_no_leak` specifically — the one case that actually caught a real
regression (Gap 294, the chat path pasting generated SQL into a user-facing answer) on the
day this track was built. This is a smoke test ("does the chat pipeline still work end to
end against a live deployment"), not full quality coverage.

**Deliberately gates on errors, not scores.** `run_agent_eval.py` has no built-in gate —
its `main()` always exits 0. The workflow step reads the run's own output JSON with `jq`
and fails only if any turn carries a non-null `error`. Not gating on `pass_rate` or any
soft score: the doc's own three real runs of the full 20-case suite already show
run-to-run score variance (faithfulness 0.806 → 0.880 with **no code change** between
them) an order of magnitude larger than a believable regression delta, and the documented
baseline pass rate itself is 0.35 — a hard score threshold here would false-positive-block
deploys on ordinary model noise rather than catch a real break. This is a scoping decision
worth revisiting once `decide_pass()`'s bar and the paired-judge-comparison prerequisite
above are both settled, not a permanent design.

**`scripts/run_extraction_benchmark.py` gained one new flag for this:** `--tolerate-fp
CASE_ID[,CASE_ID...]` — an explicit allowlist of clean-document case ids permitted to
false-positive without failing the gate, for a known, deliberately-not-fixed defect only.
The case stays *in* the corpus either way (the false-positive rate this run reports is
unaffected), so the allowlist changes only the gate's pass/fail decision, never the
measurement. Any other clean-document false positive, or any missed seeded case, still
fails the gate — pinned by 8 new tests, `tests/test_run_extraction_benchmark_cli.py`,
which call the real `main()` rather than reimplementing its gate logic.

**Azure OpenAI credentials, resolved at runtime rather than hardcoded** — `az
cognitiveservices account show` for the endpoint, `az keyvault secret show` for the key
(same Key Vault `e2e-regression.yml` already reads from), both via the existing
`Azure_Dev_Credentials` service principal. Not hardcoded, because Gap 298 already found
one hardcoded-name/real-name drift in this environment (`invoice-llm` vs. the real
`invoicellm`) — reading names off the live resource avoids adding a second place that can
go stale the same way. `DATABASE_URL`/`REDIS_URL`/`CHROMA_HOST`/`CHROMA_PORT`/
`CLERK_SECRET_KEY`/`TOKEN_ENCRYPTION_KEY` are placeholder values in this job — `config.py`'s
`Settings` requires them non-empty at import time (plain `str`/`int` fields, no format
validation) but `--mode verify` and `run_agent_eval.py --no-persist` open no real
connection with any of them.

**Verified for real:**

* `uv run pytest tests/test_run_extraction_benchmark_cli.py -q -p no:randomly` — **8 passed**, exercising the real `main()` with `sys.argv` patched: the gate fails without `--tolerate-fp`, passes with it, still fails if a different case id is tolerated (not a blanket escape hatch), still fails on a genuine missed case even with `--tolerate-fp` set, `--no-gate` always exits 0, and an empty/whitespace `--tolerate-fp` value behaves as if it were never passed.
* `scripts/run_extraction_benchmark.py --mode verify --no-write --tolerate-fp outbound_trade_discount__clean` run directly — exit 0, with the known Gap 293 case explicitly logged as `(tolerated, not gating: ['outbound_trade_discount__clean'])`; the same command without `--tolerate-fp` — exit 1, confirming the carve-out is specific, not a blanket bypass.
* The workflow YAML parses (`yaml.safe_load`), `benchmark-gate` sits correctly in `deploy-backend`'s and `deploy-worker`'s `needs:`, and the `jq` filter's logic was cross-checked against an equivalent Python computation over fabricated turn data (`jq` itself isn't installed in this local shell; it is present on GitHub-hosted `ubuntu-latest` runners by default, so this is the closest available check short of a real push). **Not run end to end in GitHub Actions** — that requires an actual push/PR, not exercised here.

### Cost and cadence, going forward — stated plainly

Both the nightly job and the pre-deploy gate call **real Azure OpenAI**, indefinitely,
once deployed/merged:

| | Cadence | Real cost driver | Rough cost (gpt-5-mini list price) |
|---|---|---|---|
| Nightly job (`caj-benchmark-eval-dev`) | Every night, 03:00 UTC, once deployed | Track 1 `--mode live` (9 real extractions) + Track 2 full 20-case suite (separate judge, ~97 judge calls per the doc's own earlier measurement) | Extraction: a handful of cents. Chat: 20 turns × ~$0.0044/turn (documented `cost_per_turn_usd`, separate mode) plus judge-call cost on top ≈ well under $1/night. **Not a real invoice reconciliation** — `cost_per_turn_usd` prices every run at gpt-5-mini's list rate, stated as a token-normalised figure in the script's own docstring, not the account's real bill. |
| Pre-deploy gate (`benchmark-gate` in `deploy-dev.yml`) | Every push to `master`/`develop` that touches `apps/invoice-be/**` | Track 1 verify mode: **free** (no network call). Track 2: 5 turns, same per-turn cost as above | A small fraction of the nightly job's Track 2 cost, but recurring on every qualifying push rather than once a night — the more frequent trigger, not the larger one. |

Neither is a one-time cost. Both recur on their own schedule for as long as the job/workflow
step exists, with no spend cap of their own beyond whatever `10-budget.bicep`'s existing
cost alert already watches at the resource-group level.

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
| `tests/test_telemetry.py` (new) | 5 tests | Event shape, real token capture off a LangChain run, error status + re-raise, broken-emitter resilience, mock-model naming. **Extended 2026-08-23 to 14** — the 9 added are per-call-site coverage for the lightweight tier, not more helper mechanics; see "Lightweight-tier coverage verified" above. |

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

**Done since — the founder action above has happened (recorded 2026-08-22).** The secret is set, and
Phase 1 telemetry is live: the first `llm_agent_call` event landed in `appi-invoicellm-dev` at
**2026-08-22T03:48:30Z**, and a direct query over the last 90 days now returns real rows
(`chat.sql_generation`, `chat.sql_summary`, `chat.classify`, `dashboard.insights`, all on
`gpt-5-mini`, one tenant). So `verified in Application Insights` **is** now claimable for Phase 1 —
by observation of the events, not by the test suite. The history is only hours long, which is why
the workbook's Cost and Latency tabs say so on the tab itself rather than letting a mostly-empty
14-day window read as a quiet product. `agent_eval_run` and `online_eval_signal` are still absent,
for their own separate reasons (no scheduled eval job, nothing calls `emit_online_signals()`).

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
| `infra/monitoring/ai_control_tower.workbook.json` (new, since **retired/deleted 2026-08-23** — see "Workbook — split into 9 standalone workbooks" below) | — | Was the single combined tabbed workbook definition, for Portal import. |
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

## Workbook — the usability restructure (2026-08-22)

Founder feedback on the 8-section workbook, verbatim: *"the current workbook is not understandable,
you can't scroll 10 pages to see [everything]."* That is a fair reading of what the second pass
produced — eight sections stacked vertically, each with a long honesty preamble, so the single most
useful number (today's spend) was several screens below the fold. This pass is **layout only**: no
query logic was rewritten, no caveat was removed, no backend code was touched, and no Azure resource
was created or changed.

### What changed

| Before | After |
|---|---|
| 27 items in one vertical stack, ~10 screens | 3 top-level items: the parameter pills, an overview tile row, and one tabbed group |
| Headline numbers buried in tables inside sections | **6 single-stat tiles above the fold**, zero scrolling |
| Sections 1-8 read by scrolling past each other | The same 8 sections as **8 tabs**, one child group per tab (the tab *mechanism* first shipped here was wrong and was corrected the same day — see "The tabs did not render" below) |
| Tenant parameter had to be picked by hand before anything rendered | Tenant resolves to `all` on load |

**The six tiles, and which existing query each one reduces** — every tile is the section query below
it narrowed to the latest/today value, not a new metric:

| Tile | Reduced from | Source |
|---|---|---|
| Cost today (USD) | section 1's `cost-trend` rates + token maths | `llm_agent_call` |
| Latest quality pass rate | section 4's `pass_rate = avg(passed)`, latest day only | `agent_eval_run` |
| Alerts fired today, by severity | section 8's `alert-trend`, `startofday(now())` instead of the window | ARG `alertsmanagementresources` |
| Latest clarification rate | section 6's `online-signals-table` `arg_max`, one signal | `online_eval_signal` |
| Latest zero-result rate | same, one signal | `online_eval_signal` |
| Golden-bank coverage | section 7's static 8-of-53 figure, as a `print` literal | static |

**Every caveat is preserved verbatim, and that is asserted mechanically, not by eye.** The rebuild
script parses the previous file and carries each of the 26 pre-existing items across *by object
reference*, then re-reads the written file from disk and asserts every one is byte-identical. The
honesty table, the Tenant-parameter dependency, the `synthesis_share_pct` inference caveat, the
`persona_score` "not applicable" note, the online-signals confidence column and its 20-observation
floor, the golden-bank numbers, and the ARG-vs-built-in-Alerts-step rationale are all unaltered —
they moved tab, they did not change. The original section numbers (1-8) are also kept exactly as
written, because the preserved text cross-references them ("section 6's `slow_turn_rate` caveat",
"sections 1-6 all depend on..."); a new `restructure-note` markdown block at the top of the
**Read me first** tab maps section number → tab so the numbering stays legible.

### The honesty rule had to be re-established per tile, and one draft failed it

A tile that reads `0.00` when nothing is instrumented would undo the entire point of this
workbook's header table. The first draft did exactly that: **KQL `sum()` over an empty set returns
`0`, not null**, so `summarize value = sum(cost_usd) | where isnotnull(value)` still emitted a row
and the tile rendered a confident `$0.00` on a day with zero telemetry. Caught by running it, not by
reading it.

The shipped tiles guard differently, per source:

* **Cost** — guards on `calls > 0` (no event today → no row → no tile), and separately returns a
  **null** value, never a zero, when events exist but *no* model in them has a hardcoded rate. Both
  behaviours were proved on synthetic rows: a priced + unpriced pair returns `1.25` with detail
  `2 calls - 1 unpriced`; an all-unpriced set returns a null value with the same explanation.
* **Quality / clarification / zero-result** — `summarize ... by day` and `arg_max` over an empty
  input naturally yield no row; `where isnotnull(value)` additionally drops the case where
  `emit_online_signals()` emitted a signal with **no `value` field at all** (its "the denominator was
  empty" case). Verified: such an event produces no tile rather than a 0.0.
* Each tile carries a `noDataMessage` stating *why* it is empty in that specific case — the cost
  tile names the unset `APPLICATIONINSIGHTS_CONNECTION_STRING`, the signal tiles say "nothing has
  run, not no problems found", and the alerts tile says the opposite on purpose: **that** source is
  live ARG, so an empty result there really is zero.

### The Tenant parameter — kept, and now self-defaulting

Kept as-is per the founder's earlier work, with one fix to the reason it needed manual selection:
`isRequired: true` plus a dropdown query over an **empty** `customEvents` table produced a parameter
with no selectable options, so `"value": "all"` matched nothing and every downstream query stayed
blocked until a value was picked by hand. The query now always returns `all` as its first row
(`union (print tenant_id = 'all'), tenants`), so the existing default resolves on load. Downstream
query semantics are untouched — every panel still reads `where '{Tenant}' == 'all' or tenant_id ==
'{Tenant}'`. `additionalResourceOptions: ["value::all"]` was dropped from that parameter, because
`all` is now a genuine row and keeping both would have offered two ways to say the same thing. The
parameter query also now includes `online_eval_signal`, so a tenant that appears only in signal
events is selectable.

### Verified how — and what is *not* verified

* **All 23 queries in the rebuilt file executed live** — 20 Log Analytics against
  `appi-invoicellm-dev` (app id `d2add3c5-9c23-46e2-b896-e7ab299abfbd`) and 3 Azure Resource Graph
  against subscription `2ae37d8b-...`, extracted programmatically from the written JSON rather than
  retyped. **0 failures**, every one returning its expected column schema. The `customEvents` panels
  return 0 rows, unchanged and for the unchanged reason. The ARG panels returned real data
  (`alert-table` 25 alerts in 14 days; the new alerts-today tile returned `Sev2: 1`, a real alert
  fired today) — so the tile is not merely parsing, it is rendering a live number.
* Harness note, because it nearly produced a false pass: invoking `az` from Python on Windows sends
  the query through a `.cmd` wrapper that **truncates the argument at the first newline**, so the
  first run "succeeded" while only executing the query's first line. Caught by checking the returned
  column names against what each query projects. Queries are flattened to one line for execution
  (KQL is newline-insensitive and none of these contain `//` comments — checked).
* JSON re-parsed from disk after writing: 45 items including groups, 8 tabs, 6 tiles, and the
  byte-identity assertion above over all 26 carried-forward items.
* **Not verified: how the tabs and tiles actually render in the portal.** The workbook is still a
  definition imported by hand, and importing it would have created an Azure resource, which this
  pass's constraints excluded. Two specific things a first import should be looked at for: (1) tab
  **labels** are taken from each child group's `name`, with `content.title` set to the same string as
  a fallback, so if a label ever renders blank the content is still self-labelled by its own markdown
  header; (2) the tiles use `customWidth` 15% x5 + 20% for the alerts tile to make one row of six —
  on a narrow window they will wrap to two rows, which costs a little vertical space but nothing
  else. Neither is a correctness risk, and neither can be confirmed without importing.

### The tabs did not render — root cause and fix (2026-08-22)

The caveat directly above ("not verified: how the tabs actually render") was the right caveat and it
caught a real defect. The founder opened the workbook and saw **one continuous scrolling page with
section headers and no clickable tab row** — i.e. exactly the layout the restructure was meant to
replace. The overview tiles were fine (they rendered, including a live `Sev2: 1`); only the tabs
were not tabs.

**Root cause: `"style": "tabs"` on a `type: 12` group is not a thing.** Azure Workbooks has no
group-level tab style. The property was invented, Azure silently ignored the unrecognised key, and
the group fell back to its default rendering — every child group stacked vertically. Confirmed
against the official schema, not inferred: in
[`schema/workbook.json`](https://raw.githubusercontent.com/microsoft/Application-Insights-Workbooks/master/schema/workbook.json),
`definitions.group.content` declares `version`, `groupType`, `loadType`, `loadButtonText`,
`loadFromTemplateId`, `items`, `title`, `exportParameters` — and **no `style`**. `style` with
example value `"tabs"` exists only on `definitions.link`, the `type: 11` step.

**The real mechanism** ([workbooks-create-workbook § Tabs](https://learn.microsoft.com/en-us/azure/azure-monitor/visualize/workbooks-create-workbook#tabs),
worked JSON in [workbooks-sample-links](https://learn.microsoft.com/en-us/azure/azure-monitor/visualize/workbooks-sample-links)):
tabs are two cooperating pieces, not one property.

1. A **links step** — `type: 11`, `content.version: "LinkItem/1.0"`, `content.style: "tabs"`, and one
   entry per tab in `content.links`. Each entry sets a shared parameter when clicked:
   `linkTarget: "parameter"`, `cellValue: "<parameter name>"`, `subTarget: "<this tab's value>"`,
   `linkLabel: "<tab caption>"`, `style: "link"`. (`cellValue` is the parameter *name* and
   `subTarget` the *value* — a naming that is not guessable from the field names, which is how the
   first attempt went wrong.)
2. **`conditionalVisibility`** on each content group, at the group's *top* level (sibling of `type`
   / `content` / `name`, not inside `content`):
   `{"parameterName": ..., "comparison": "isEqualTo", "value": "<that tab's value>"}`.

**What was changed in `infra/monitoring/ai_control_tower.workbook.json`:**

* Deleted `"style": "tabs"` from the `sections` group's `content`.
* Inserted a `type: 11` step named `tab-bar` as the **first child of the `sections` group** — a
  sibling of the 8 content groups, so the parameter it sets and the groups that read it share one
  scope, matching the docs' worked example.
* Added `conditionalVisibility` on all 8 groups, keyed to a parameter named **`SelectedTab`** with
  values `readme` / `cost` / `latency` / `quality` / `component` / `online` / `golden` / `health`.
  `SelectedTab` is deliberately **not** declared in the `shared-parameters` step: per the docs
  ("the first tab is selected by default, invoking whatever action that tab specified") and per every
  shipped Microsoft template checked, the first link fires on load and sets it. Declaring it as well
  would have put a redundant pill in the parameter row. **Read me first** is first, so it is what
  renders on load.
* Nothing else. The overview tiles are untouched (they already worked), and so is every query, table
  and caveat inside the 8 groups.

**Verified how — this fix:**

* **Content byte-identity**: the file is regenerated by re-serialising the parsed document, and that
  serialiser was first proved to round-trip the pre-fix file to an **identical 68,777 bytes**. The
  resulting `diff` is therefore exactly and only the intended change: one `"style": "tabs"` line
  removed, one 74-line `tab-bar` step added, 8 five-line `conditionalVisibility` blocks added. Zero
  other lines differ, so no query needed re-execution to know it is unchanged.
* **Schema-validated** against the official `schema/workbook.json` with `jsonschema` (Draft 7):
  0 errors for the whole document; the `tab-bar` step also validated in isolation against
  `definitions.link` and all 8 groups against `definitions.group`.
* **Structurally diffed against a real, shipped Microsoft tabbed workbook** —
  `Workbooks/Azure Security Center/Containers Security/Containers Security.workbook` from
  `microsoft/Application-Insights-Workbooks`. Its tab bar and ours have identical step keys
  (`type`/`content`/`name`), identical content keys (`version`/`style`/`links`), identical
  `LinkItem/1.0` + `tabs`, identical `linkItem` key sets
  (`cellValue`/`id`/`linkLabel`/`linkTarget`/`style`/`subTarget`), identical `linkTarget: parameter`
  and `style: link` values, and identical `conditionalVisibility` key sets and `isEqualTo`
  comparison. Two independent sources (Microsoft docs, and a template Microsoft actually ships) agree
  on the shape.
* **A real Azure resource was created this time**, closing the gap the previous pass left open. A
  throwaway workbook `AI Control Tower - TAB FIX TEST` was `PUT` to
  `Microsoft.Insights/workbooks` (api-version `2022-04-01`) in `rg-invoice-llm-dev`, name
  `0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6`. `PUT` returned 200; a follow-up `GET` with
  `canFetchContent=true` returned `serializedData` **byte-identical to what was sent** (71,978 chars
  both ways, including the non-ASCII `→` characters), so nothing is lost or escaped in storage. The
  stored copy re-parses with the group-level `style` gone, the `type: 11` tab bar present with all 8
  labels, all 8 `conditionalVisibility` values matching the 8 `subTarget`s 1:1, and the 6 overview
  tiles still above the tab bar.

**Still not verified by this pass, and it cannot be from here:** whether the tab row *looks and
behaves* right when clicked. Every claim above is about JSON structure and what Azure stored, not
about pixels. The test resource exists so the founder can settle that in one click:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
It is a **disposable verification copy**, not the workbook to use going forward, and should be
deleted once the render is confirmed.

**Separate finding, worth knowing:** the live workbook resource `Invoice LLM AI Tower`
(`72843A80-003A-4BA1-AB71-F3F52C355D09`, same resource group) still holds the **pre-restructure**
definition — a flat list of 27 root items, no group, no overview tiles, `timeModified`
`2026-08-22T03:02:03Z`, which is *earlier* than the restructure was written to disk. So that saved
resource never had tabs or tiles to fail at; whatever was viewed with working tiles was an unsaved
paste into the Advanced Editor. It was intentionally left untouched by this pass.

### The tab bar was below the fold — `customWidth` was written in a form workbooks does not accept (2026-08-22)

With the tabs working, the founder's next report was: *"tab is there but its below, why can't you fix
the above part side by side so tabs are visible on the page no scroll down needed."* Two things were
consuming the space above the tab bar, and one of them was a second real defect, not a styling
preference.

**Defect: `"customWidth": "15%"` is not a valid value.** The six tiles were written with
`15%` x5 + `20%`, intending one row. The units belong to grid *column* widths (where `ch`/`px`/`fr`/`%`
are documented), **not** to a step's `customWidth`, which is a bare number meaning percent. Evidence,
counted rather than assumed: across all **708 workbook templates Microsoft ships** in
`microsoft/Application-Insights-Workbooks` there are **5,207 `customWidth` values and not one of them
contains `%`, `px`, or any non-numeric character** — they are `"50"`, `"33"`, `"25"`, `"15"`. The
official [`schema/workbook.json`](https://raw.githubusercontent.com/microsoft/Application-Insights-Workbooks/master/schema/workbook.json)
agrees: `definitions.customWidth` is a string whose only example is `"50"`. A malformed width is
ignored the same way the invented group-level `"style": "tabs"` was ignored, and an item with no
usable width falls back to full width — which puts **each tile on its own row**. That is six stacked
rows of tile where one row was intended, and it is the direct cause of the tab bar sitting below the
fold. Fixed by dropping the `%` from all six: `15, 15, 20, 15, 15, 15` = **95**, deliberately under
100 so inter-item margins have somewhere to go. The proportions are unchanged from what was always
intended — the alerts tile stays the wide one because its subtitle carries the severity breakdown.
`15` with a `tiles` visualization is shipped Microsoft practice, not a guess (`Connection
Performance`, `Vulnerabilities`, `Overview`, `DefenderCSPM` all do exactly that); tile step `size: 4`
was already the most compact option (260 of Microsoft's 595 tile steps use it) and was left alone.

**Second: the caption above the tiles was a heading plus a four-line paragraph.** Cut from 384
characters (an `##` heading, a blank line, and a paragraph that wrapped to roughly four lines) to a
**single 113-character line with no heading**:
`**A blank tile means no data, never a healthy zero** — which sources are live today is the **Read me first** tab.`
No information was lost from the workbook: the honesty rule, the per-source live/empty table and the
reason each source is empty are all stated at length in the **Read me first** tab already, and the
one-liner points at it. The tab's own text was **not** edited to compensate — nothing inside any of
the eight tabs was touched by this pass.

**Net effect on the space above the tab bar**: from `##` heading + ~4 wrapped lines + **six**
full-width tile rows, down to one line of text + **one** tile row. Nothing else moved: the parameter
pills row, the tab bar, and all eight tabs' content are unchanged.

**Verified how — this fix:**

* **Diffed against what Azure actually had stored**, not against a local guess. The test workbook
  resource still held the previous (pre-fix) definition, so it was `GET`-ed and structurally diffed
  against the new local file: **37 diff lines, all seven of them intended** — one caption string, six
  `customWidth` values. Every query, table, `noDataMessage` and caveat is identical, so no query
  needed re-running to know it is unchanged.
* **Schema-validated** against the official `schema/workbook.json` with `jsonschema` Draft 7:
  **0 errors** for the whole document. Structure re-asserted from the parsed file: 46 items including
  groups, tab bar `type: 11` / `style: tabs` with 8 links, 8 `conditionalVisibility` values matching
  the 8 `subTarget`s, 6 tiles above the tab bar, widths summing to 95, no `%` in any width.
* **Re-`PUT` to the same throwaway resource and round-tripped.** `PUT` returned 200
  (`timeModified 2026-08-22T04:03:23Z`); the follow-up `GET` with `canFetchContent=true` returned
  `serializedData` **byte-identical to what was sent** — 72,594 characters both ways, with all 49 em
  dashes and 7 arrows intact. Harness note, because it nearly produced a wrong answer: `az rest`
  piped to a file on Windows encodes its output as cp1252 and **silently discards non-ASCII
  characters** (`WARNING: Unable to encode the output with cp1252 encoding`), which made a first GET
  come back 58 characters short. ARM is called through `urllib` with an `az account get-access-token`
  bearer token instead, which is byte-clean.

**Still not verified, and it cannot be from here:** the rendered pixels. The claim is that six items
at width `15/15/20/15/15/15` lay out in one row; that is inference from Microsoft's own templates and
schema, not a screenshot. Same test resource, same URL as before — refresh it:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
What to look at, in one glance: **one** row of six tiles, one line of text above it, and the tab bar
visible without scrolling. Still a disposable copy; still to be deleted once confirmed.

### "The workbook is not understandable" — every explanation consolidated into one Documentation tab (2026-08-22)

With the tab mechanism and the layout both confirmed working, the remaining complaint was not about
structure at all: *"the workbook is not understandable."* Every panel carried paragraphs of caveats
and data-source explanation interleaved with the actual numbers, so finding one figure meant reading
a wall of text first. The Online signals tab alone was **3,499 characters of prose above three
panels**; Component quality 2,191; Latency 961 for two charts. Six of the six overview tiles had a
multi-sentence essay as their *empty-state message* — the pass-rate tile's was 136 characters
explaining what an empty tile does and does not mean, where the founder wanted `— (not run)`.

The target shape was agreed in chat before anything was written, against two example tables the
founder confirmed directly: **tiles read as one terse line each**, and **the reference material is
one table row per metric with no prose**. This pass implements exactly that.

**What moved where.**

| | Before | After |
|---|---|---|
| Text (`type: 1`) items | 12 | 16 |
| Characters of text **outside** the reference tab | 10,998 across 7 tabs | **2,260** (−79%) |
| Characters of text **in** the reference tab | 5,379 ("Read me first") | 22,170 ("Documentation") |
| Prose paragraphs outside the reference tab | 20 | 9 — and all 9 are the second line of a two-line tab label |
| Table rows in the reference tab | 18 | **79** |
| Named items in the document | 49 | 53 |
| Tabs | 8 | 8 (unchanged) |
| KQL queries | 23 | 23, **byte-identical** |

So: **20 prose paragraphs spread across 7 tabs became 79 table rows on one tab.** Each of the seven
non-documentation tabs is now a `###` heading plus exactly one line of context, then its charts and
tables. Nothing else.

**"Read me first" became "Documentation"** (`linkLabel`, group `title`, group `name`, and the
`subTarget`/`conditionalVisibility` pair `readme` → `documentation`, kept 1:1). It now holds seven
blocks, in reading order:

| Block | What it holds |
|---|---|
| `doc-intro` | One paragraph: this is where all the explanation lives, and the shared parameter pills |
| `doc-metric-reference` | **The new centrepiece** — `Tile/Panel \| What it means \| What makes it move`, one row for each of the 6 overview tiles and each of the 18 panels across all 8 tabs, grouped by tab. 24 rows. The overview-tile rows are the founder's own wording, used verbatim |
| `doc-data-sources` | The pre-existing live/empty honesty table (kept, retargeted from section numbers to tab names), plus the hardcoded `$/1M tokens` rate assumption — now a 5-row model/rate table rather than a paragraph |
| `doc-component-scores` | The context/orchestration/persona mechanism table, and the `persona_scored_turns` "not applicable" limitation |
| `doc-online-signals` | The 5-signal confidence table verbatim (`measured` / `proxy` / `offline-only` / `heuristic` and what each really measures), plus the two reading rules (no alert below 20 observations; a blank value is never 0.0) as their own 2-row table |
| `doc-proxies` | **New consolidation** — a `Number \| Why it is not a direct measurement \| What would make it one` table gathering every proxy disclosure that used to be scattered: `synthesis_share_pct`'s inference-from-prompt-size, latency's one-round-trip scope, the turn-latency row-timestamp delta, `budget_exhaustion_rate`'s eval-harness-only source, `clarification_rate`'s wording match, and golden-bank coverage's staticness. Plus the Gap 278 rationale for latency having its own tab, and the golden-bank "why 8 and not 53" reasoning with its two caveats and Gap 287 |
| `doc-import` | Import instructions, the two import-failure cases as a table, the ARG-vs-built-in-Alerts rationale, and a 4-row layout-history table (which absorbs the old restructure note's section-number → tab mapping, since section numbers no longer appear on any tab) |

**Empty-state messages, before → after.** The multi-sentence explanations are gone from the tiles and
their reasoning now lives in `doc-metric-reference`'s "What makes it move" column:

| Tile | Before | After |
|---|---|---|
| Cost today | 187 chars ("...that is a configuration state — `APPLICATIONINSIGHTS_CONNECTION_STRING` is not set...") | `— (no data)` |
| Quality pass rate | 136 chars | `— (not run)` |
| Alerts today | 170 chars | `0 (none fired today)` |
| Clarification rate | 232 chars | `— (not run)` |
| Zero-result rate | 152 chars | `— (not run)` |
| Golden-bank coverage | 67 chars | `— (query failed)` |

The Alerts tile is deliberately the one that does **not** say `—`: Azure Resource Graph is genuinely
live, so an empty result there really is a zero. That distinction — the single most important reading
rule in the whole workbook — is stated once in `doc-data-sources` instead of once per tile.

Tile titles were shortened to the founder's names (`Latest quality pass rate (%)` → `Quality pass
rate (%)`, `Alerts fired today, by severity` → `Alerts today`, `Golden-bank coverage (of 53)` →
`Golden-bank coverage`). Units were kept as bare parentheticals where they are load-bearing for
reading the number — `(USD)`, `(%)` — because a number with no unit is a worse failure than a
slightly longer label.

**Two caveats were judged load-bearing enough to survive on their own tab**, compressed to one line
each rather than deleted, with the full version in Documentation: `get_full_record` makes no LLM call
so `synthesis_share_pct` is an inference (Cost tab), and the online signals' turn-latency panel title
still carries `(PROXY — row timestamps, not a timer)`.

**The Golden-bank tab keeps its two number tables.** Its content *is* numbers, not caveats — only the
surrounding prose ("why 8 and not 53", the over-counting caveat, the gitignored-source caveat, Gap
287, the regeneration instructions) moved to Documentation.

**Verified how — this pass:**

* **Queries proven untouched three ways, none of which required re-running one.** (1) The build
  script collects every `query` string by JSON path before and after mutation and asserts equality:
  **23 queries, 0 differences.** (2) It then asserts the *entire* before/after maps of `queryType`,
  `resourceType`, `crossComponentResources`, `visualization`, `tileSettings`, `timeContext`,
  `timeContextFromParameter`, `size` and `customWidth` are equal — so no data-source or rendering
  property moved either. (3) Independently of the local file: the **23 query strings Azure had
  stored before this PUT** (the previous round's definition, fetched with `canFetchContent=true`)
  are set-identical to the 23 it stores after.
* **Content-loss audit, mechanical rather than by eye.** Every backtick-delimited identifier and
  every numeric literal in the old workbook text was extracted and checked against the new text:
  **79/79 identifiers and 47/47 numbers present**, plus a hand-listed set of 49 load-bearing claim
  phrases. The first build **failed this check on three items** — the five instrumented SAGE call
  sites with `agents/query_tools.py`, the `infra/monitoring/llm_cost_by_tool.kql` pointer, and the
  `gap_coverage` block name — which were restored into `doc-metric-reference` and the whole build
  re-run from the untouched backup. Worth stating because it is the exact failure mode this task was
  told to avoid, and it was caught by the check rather than by review.
* **Schema-validated** against the official `schema/workbook.json` with `jsonschema` Draft 7:
  **0 errors** for the whole document; the tab bar validates as `definitions.link` and all 8 groups
  as `definitions.group`. Structure re-asserted: 8 `subTarget`s matching 8 `conditionalVisibility`
  values 1:1 on `SelectedTab`, 6 tiles above the tab bar, widths still `15/15/20/15/15/15`.
* **PUT to the same throwaway resource and round-tripped.** `PUT` 200
  (`timeModified 2026-08-22T04:14:13Z`); the follow-up `GET` returned `serializedData`
  **byte-identical to what was sent** — 79,737 characters / 79,903 UTF-8 bytes both ways, with all
  75 em dashes, 7 arrows and the `≥` intact. ARM called through `urllib` with an
  `az account get-access-token` bearer, per the earlier finding that `az rest` piped to a file on
  Windows silently drops non-ASCII via cp1252.
* **File hygiene**: CRLF throughout (924 lines), trailing newline, UTF-8 without BOM — the same
  serialization as before, so the git diff is content only.

**Still not verified, and it cannot be from here:** whether the consolidated tables *read* well on
screen. The claim is that a 24-row reference table is easier to use than 20 paragraphs beside
charts; that is a judgement about the agreed format, not a measurement. Same test resource, same URL
— refresh it:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
What to look at: the first tab is now **Documentation** and every other tab should be a heading, one
line, then charts. Still a disposable copy; still to be deleted once confirmed.

### "Put the insights at top" — and the three things that were still wrong (2026-08-22)

Founder feedback, verbatim: *"put the insights at top then explanation then graph"*, plus, separately
and bluntly, that after three rounds of fixes the workbook is still **"not at all user friendly"** in
one glance. The first is a precise ordering instruction and is implemented exactly. The second was
treated as an instruction to go and *find* what is wrong rather than to polish what was already
asked for, and it turned up three concrete defects — one of which the previous pass created.

**Every non-Documentation tab is now `heading → insight → explanation → charts`.** The charts and
tables are untouched; the insight is genuinely new content, not a relabelled heading.

| Tab | The insight, and where it comes from |
|---|---|
| **Cost** | **Computed, live.** A new `cost-insight` tile over the *same* `llm_agent_call` events and the *same* hardcoded rate table as the chart below it. Renders today as `Biggest spender: chat.sql_generation — 47% of the window` / **0.02** / `USD over 9 calls from 4 agents` |
| **Latency** | **Computed, live.** A new `latency-insight` tile over the same events as the p50/p95 chart. Renders today as `Slowest tail: dashboard.insights — p95 is 1.0x its own median of 14875 ms` / **14875** / `ms p95, worst of 4 agents — 9 calls, 0 errors in the selected time range`. The ratio is the point: a high multiple is a *tail* problem, a high p95 with a multiple near 1 is a uniformly slow agent — which is exactly what `dashboard.insights` is |
| **Health** | **Computed, live.** A new `health-insight` ARG step over the same `alertsmanagementresources` rows as the bar chart. Renders today as `1 of 25 alerts still firing right now` / **25** / `alerts fired — worst severity Sev1 — noisiest of 6 rules: alert-ca-invoice-be-dev-memory-high (9)` |
| **Golden-bank coverage** | The headline number restated in plain words: *"8 of the 53 closed answer-quality gaps have a re-runnable regression test today — the other 45 would not be caught by anything automatic if they came back."* |
| **Quality** | No data yet, so the insight states what a reading will *mean*: read the **change** between runs, not the level, because this judge is known to under-score some correct answers — 100% is not the target |
| **Component quality** | Same shape: the lowest of the three lines is the fix list — `context` = wrong rows fetched, `orchestration` = right rows but an untraceable figure, `persona` = right data, wrong domain reasoning |
| **Online signals** | Same shape: a rate above its own `threshold` with a `denominator` of 20 or more is worth acting on; below 20 observations, 1-of-1 reads as 100% |

On the four no-data tabs the insight is a **bold** line in the same markdown block as the heading and
the existing one-line explanation, so it is visually distinct without costing a second block of
vertical space. On Cost / Latency / Health the insight is a real query step (`size: 4`, full width,
titled *The one-line read*) sandwiched between a heading-only markdown item and the pre-existing
explanation line, because a markdown step cannot hold a computed value.

**Three real problems found beyond the explicit ask.**

1. **The previous pass made Documentation the *first* tab, so the workbook opened on the single
   biggest wall of text in it.** Consolidating all prose into one Documentation tab was right; leaving
   it first was not. The first link in a `type: 11` tab bar fires on load, so every open landed on
   22,170 characters of reference tables before any number. **Fixed: Documentation moved to last, Cost
   is now first**, so the workbook opens on a live figure. This is the highest-confidence item in this
   pass and it is a defect the previous round introduced, not a preference.
2. **`customEvents` is no longer empty, and the Documentation tab still said it was.** As of
   **2026-08-22T03:48:30Z** `llm_agent_call` events are arriving — `APPLICATIONINSIGHTS_CONNECTION_STRING`
   has been set as a Container App secret since then. Every prior pass, and the "Data sources" table
   itself, asserted "**No — empty**, 0 rows over 90 days" for Cost and Latency. A founder reading a
   `$0.02` tile above a table telling him there is no data is a direct contradiction and a real
   contributor to "not understandable". **Fixed:** both rows now read live, dated to that timestamp,
   and the `doc-import` "a tab renders empty" row was narrowed to the three tabs that genuinely are
   still empty (Quality, Component quality, Online signals). One caveat is stated on the Cost row
   rather than left to be discovered: the history is only hours long, so a 14-day window is mostly
   the pre-instrumentation period, not a quiet product.
3. **There was no colour or icon anywhere in the workbook.** Checked rather than assumed: threshold
   formatting *is* real and *is* schema-supported — `formatter: 18` with
   `formatOptions.thresholdsOptions: "icons"` and a `thresholdsGrid`, used **164 times inside
   `tileSettings`** across the 708 workbook templates Microsoft ships, with `representation` values
   including `Sev0`–`Sev4`, `success`, `Blank` and the `text: "{0}{1}"` icon+value form. **Applied to
   exactly one tile — Alerts today** — mapping each severity to its own severity icon, with a
   `tooltipFormat` explaining the rule.

**Why only one tile got an icon, stated plainly rather than sold as more than it is.** A threshold is
a claim about what "bad" means. Alerts have one that this repo did not invent (severity). The other
five tiles do not: there is no cost budget, no target pass rate and no coverage target anywhere in
this codebase, and inventing one to make a tile go red would break the same honesty rule that made
the empty-state messages say `— (no data)` instead of `0`. The two online-signal tiles *do* have real
thresholds — 25% and 20%, carried on the `online_eval_signal` event itself as a `threshold` field, so
no number would have to be hardcoded — and the four-branch status logic for them
(`over` / `under` / `too few` / `no threshold`) was written and **proved live against synthetic rows**
in this pass. It was deliberately **not shipped**, because both tiles are empty and will stay empty
until something calls `emit_online_signals()` on a schedule; adding invisible machinery to an empty
tile does not answer a complaint about what is visible. It is a one-line change when that job exists.

**Two things left for the founder rather than guessed at.** Both are vocabulary, and both were
changed to "the founder's names" in the previous pass, so changing them again unasked would be
overwriting a decision that was already made:

* **Tile titles.** `Clarification rate (%)` and `Zero-result rate (%)` are the product's internal
  signal names. A non-engineer reading them cold learns nothing; the plain-English versions already
  exist in `doc-metric-reference` ("what % the AI answered by asking a follow-up instead of a direct
  answer", "what % got 'no matching records found'"). Promoting those to the tile titles would help a
  first-time reader and cost the vocabulary link to `online_eval_signals.py`, and the titles are
  narrow (`customWidth: 15`) so a longer label costs vertical space above the tab bar — the exact
  thing round three was spent fixing.
* **Tab labels.** `Online signals` and `Component quality` are internal names. `Live traffic` and
  `Which stage is wrong` would read better cold; both are cross-referenced by name throughout the
  Documentation tab, so renaming means editing those references too.

**Verified how — this pass:**

* **The three new queries were written and run live before being put in the file**, not after. All
  three return one sane row against real data (values quoted in the table above). The Health query's
  "still firing" count is `monitorCondition == 'Fired'`, **not** `alertState != 'Closed'` — checked
  against the real rows, where all 25 alerts have `alertState: New` because nobody closes them, so
  the `alertState` reading would have said "25 still open" and been useless. That distinction is
  recorded in `doc-metric-reference`.
* **All 25 query steps in the written file re-executed live** — 22 Log Analytics against
  `appi-invoicellm-dev` and 3 Azure Resource Graph — extracted programmatically from the JSON rather
  than retyped. **0 failures**, every one returning its expected column schema.
* **The diff is provably only what was intended, measured against what Azure had stored** (the test
  resource still held the previous round's definition, so it was `GET`-ed and compared, not trusted
  from a local copy): all **23 pre-existing query strings present and unchanged**, **3 added**,
  **0 removed**; of the 22 pre-existing query *steps*, **exactly one** has any changed property —
  `overview-alerts-today`'s `tileSettings.titleContent`, the severity icon. Every other
  `queryType` / `resourceType` / `crossComponentResources` / `visualization` / `tileSettings` /
  `timeContext*` / `size` / `customWidth` / `title` / `noDataMessage` is byte-identical.
* **Content-loss audit, mechanical.** Every backtick-delimited identifier and every numeric literal
  in the workbook's text before the change was checked against the text after: **88/88 identifiers
  and 43/43 numbers present, 0 missing.** The audit itself was fixed mid-run — its first version
  keyed on `version == "TextItem/1.0"`, which these markdown steps do not carry, so it silently
  audited zero strings and passed vacuously. Worth recording: a green check from a check that
  examined nothing is the same failure class this step exists to catch.
* **Schema-validated** against the official `schema/workbook.json` with `jsonschema` Draft 7:
  **0 errors** for the whole document; the tab bar validates as `definitions.link`, all 8 groups as
  `definitions.group`, and the 3 new insight steps and the changed alerts tile as `definitions.query`.
* **Serialiser proved lossless first**: `json.dumps(indent=2, ensure_ascii=False)` + CRLF reproduces
  the pre-change file byte-for-byte (80,827 bytes), so the git diff is content only.
* **PUT to the same throwaway resource and round-tripped.** `PUT` 200
  (`timeModified 2026-08-22T04:33:06Z`); the follow-up `GET` with `canFetchContent=true` returned
  `serializedData` **byte-identical to what was sent** — 94,466 characters / 94,672 UTF-8 bytes both
  ways, with all 92 em dashes, 10 arrows and the `≥` intact. ARM via `urllib` + an
  `az account get-access-token` bearer, per the standing finding that `az rest` piped to a file on
  Windows drops non-ASCII under cp1252.
* File hygiene unchanged: CRLF throughout (1,120 lines), trailing newline, UTF-8 without BOM.

**Still not verified, and it cannot be from here — plus one honest caveat.** No pixels were seen this
round either. Specifically unverified: that a `size: 4` full-width tile with a sentence as its
`titleContent` reads as an insight rather than as another chart, and that the severity icon renders
at all on the Alerts tile. And the honest part: **three rounds in, this should not be claimed as "now
it is user friendly."** What can be claimed is that three specific, nameable defects are gone — the
workbook no longer opens on a wall of reference tables, the Documentation tab no longer contradicts
the live tiles, and each tab now leads with a takeaway instead of a label. Whether that is *enough*
is the founder's call, and the two vocabulary questions above are genuinely his to settle. Same test
resource, same URL — refresh it:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
What to look at, in one glance: it should open on **Cost**, not Documentation; the first thing under
the heading should be a sentence naming the biggest spender with `$0.02` beside it; Documentation
should be the **last** tab. Still a disposable copy; still to be deleted once confirmed.

One cosmetic caveat rather than a silent one: the Health insight's "noisiest rule" is an `arg_max`
over the per-rule counts, and ties are broken arbitrarily — two rules currently sit at 9 alerts each,
so that name can change between refreshes without anything having changed.

### The file was reverted outside this workstream, and the rebuild that followed (2026-08-22, later the same day)

**The incident.** `infra/monitoring/ai_control_tower.workbook.json` was found back at its **first,
primitive state** — 27 flat root items, no `type: 11` links step anywhere, no `type: 12` group
anywhere, no overview tiles, no Documentation consolidation, `46,472` bytes against the round-4
definition's `95,792` on disk. Confirmed by reading the file, not inferred: a flat alternation of
markdown-header and chart per section, exactly the pre-restructure shape. Nothing in this workstream
wrote it; the founder confirmed another IDE had touched it. The disposable Azure test resource was
checked too and held a matching early copy (`45,962` chars stored), so it was **not** usable as a
recovery source either.

**What made recovery exact rather than reconstructive.** The round-3 backup
(`workbook.before_round4.json`, 80,827 bytes) and the round-4 build script both survived in the
working scratch directory. Replaying that script over that backup reproduced the round-4 definition
at **94,466 chars / 94,672 UTF-8 bytes** — byte-for-byte the figure this doc already recorded for it.
So the 22,170-character Documentation tab, all 23 original queries and every preserved caveat came
back verbatim; **nothing was re-derived from this doc's narrative**, which is what the narrative
would otherwise have been needed for. This section records that as luck partly, and partly as the
reason the previous rounds wrote reproducible build scripts instead of hand-editing JSON.

**The new requirement, which is the actual content of this round.** Founder instruction: every
non-Documentation tab must be **four visible sections, top to bottom, fitting one screen** —
*scores/numbers, then a short explanation, then a compressed graph, then table rows*. That is a
change from round 4's `heading → insight → explanation → charts`: an *insight sentence with one
number in it* is not the same thing as a row of numbers.

| Section | How it is built | Schema mechanism |
|---|---|---|
| 1. **Scores** | A `tiles` step returning **2-3 rows** of `(ord, metric, value, detail)`, one tile each. Every one is a *reduction of that tab's own query* — same events, same hardcoded rate table, same aggregation — never a new metric. The step's `title` carries the tab heading, so no separate heading item costs a row | `visualization: "tiles"`, `size: 4`, `tileSettings.titleContent/leftContent/subtitleContent`, `sortCriteriaField: "ord"` |
| 2. **Explanation** | One markdown line, plain language, saying what those numbers mean. Round 4's computed insight sentences were folded into here and into the tiles' `detail` strings — e.g. "Biggest spender: `chat.sql_generation` — 47% of the window" is now literally the third tile | `type: 1` |
| 3. **Compressed graph** | The **same chart, same query, unchanged** — only `size` moved `0` → `1` | `content.size: 1` |
| 4. **Table rows** | The **same table, same query, unchanged** — capped to the top 5 rows with a filter box for the rest | `gridSettings.rowLimit: 5`, `gridSettings.filter: true` |

**The seven scores queries, and what they show today.** All executed live before being written into
the file, not after:

| Tab | The 2-3 numbers | Live result today |
|---|---|---|
| Cost | Spend today / Spend in window / Biggest spender's share | `0.02` USD over 9 calls · `0.02` · `47%` — `chat.sql_generation` |
| Latency | Worst p95 / its tail ratio / calls in window | `14875` ms — `dashboard.insights` · `1` x its own median · `9` calls, 0 errors |
| Quality | Pass rate / faithfulness mean / accuracy mean | no rows — `— (not run)` |
| Component quality | Context / orchestration / persona, each with its own denominator | no rows — `— (not run)` |
| Online signals | Clarification rate / zero-result rate / signals over threshold | no rows — `— (nothing has run)` |
| Golden-bank | 8 with a test / 45 without / 87 cases | static literals, 3 tiles |
| Health | Alerts fired / still firing now / noisiest rule | `25` from 6 rules · `1` still firing, worst Sev1 · `9` — `alert-ca-invoice-be-dev-memory-high` |

**Two real defects were found by running the new queries rather than by reading them**, both in the
same family as this workbook's earlier `sum()`-returns-`0` finding:

1. **`latest` is a reserved word in KQL.** `let latest = evals | …` fails to parse
   (`SYN0002 … could not be parsed at 'latest'`). Three of the seven queries had it. Renamed to
   `latest_run` / `latest_signals`.
2. **`avg()` over an empty set returns `NaN`, not null, and `isnotnull(NaN)` is `true`.** The Quality
   and Component-quality scores tiles therefore rendered a literal **`NaN`** with a `0 turns` subtitle
   instead of `— (not run)` — a confident-looking non-number where the honesty rule requires nothing
   at all. Fixed by guarding at source (`| where turns > 0` drops the single row a `by`-less
   `summarize` always emits) and again on the value (`not(isnan(value))`). **Both branches were then
   proved on synthetic rows**, the same way the cost tile's guard was: a seeded 2-turn datatable
   returns `Pass rate 50 / Faithfulness 0.74 / Accuracy 0.8`, and an empty datatable of the same
   schema returns **0 rows**. The component check additionally proves the NULL-is-not-zero rule
   survives — persona reports `over 1 scored turns` where context and orchestration report 2.

**Secondary tables moved behind a button rather than below the fold.** Three tabs had a 5th and 6th
panel that no amount of row-capping fits on one screen. Each now sits in a nested `type: 12` group
with `loadType: "explicit"`, which renders as a **single button** until clicked — `Show the
per-SAGE-tool breakdown (2 tables)` on Cost, `Show the worst component per case (1 table)` on
Component quality, `Show turn-latency percentiles (1 table, PROXY)` on Online signals. Not invented:
`loadType`/`loadButtonText` are in the official schema's `definitions.group` and are used by 21
groups across Microsoft's shipped templates. No query, column or caveat inside them changed.

**One tab genuinely cannot have four sections, stated rather than fudged.** **Golden-bank coverage
has three** — scores, explanation, and its two number tables. There is no compressed graph because
there is no series to plot: the source is a repo file (`tests/golden_bank/golden_bank.json`), a
workbook has no data source that can read one, and inventing a time axis for a static figure would be
a fabricated trend. The tab says so on itself.

**Evidence for the layout choices, counted rather than assumed** — re-derived this round against a
shallow clone of `microsoft/Application-Insights-Workbooks` (668 template files parsed):

| Choice | Evidence |
|---|---|
| `customWidth` as a bare number | **4,674 values, not one with `%`, `px` or any unit.** The only 17 non-integers are decimals (`33.3` x13, `33.33` x3, `66.67` x1). Independently confirms the earlier round's finding; the earlier count (5,207 across 708 files) differs only because it globbed a wider file set |
| `type: 11` + `conditionalVisibility` as the tab mechanism | **422** tab bars; `isEqualTo` used **3,462** times. Cross-checked field-by-field against `Azure Security Center/Containers Security`, which puts intro → parameters → tab bar → conditionally-visible groups at **root level**, the same shape used here |
| `size: 1` for the compressed chart | timechart `size: 1` used **50** times against `size: 4`'s **9**; barchart **67** against **21**. `size: 1` is the most compact *well-attested* option; `size: 4` was not taken because a tiny chart drops its axis labels and is thinly used for time series |
| `gridSettings.rowLimit` | used **748** times, including values as low as 1, 10, 15 and 25 |
| `loadType: "explicit"` | **21** groups |

**Verified how — this rebuild:**

* **Concurrent-edit defence, and it was a real check not a formality.** The destination file's
  SHA-256 was recorded at task start (`e0503d11…`, 46,472 bytes) and re-read from disk immediately
  before writing, and again inside the copy step, with the write refusing to proceed on a mismatch.
  It matched both times, so nothing else's edit was silently overwritten.
* **All 30 query steps in the written file executed live** — 26 Log Analytics against
  `appi-invoicellm-dev` and 4 Azure Resource Graph against subscription `2ae37d8b-…` — extracted
  programmatically from the JSON rather than retyped. **0 failures**, every one returning its expected
  column schema. Run through `urllib` with an `az account get-access-token` bearer, per the standing
  finding that `az rest` piped to a file on Windows drops non-ASCII under cp1252 *and* that invoking
  `az` from Python truncates a multi-line query argument at the first newline.
* **Content preserved, checked mechanically**: every backtick identifier and numeric literal in the
  recovered round-4 text was compared against the rebuilt text — **95/95 identifiers and 44/44
  numbers present, 0 missing.** Of 26 pre-existing queries, **26 are byte-identical**; exactly
  **3 are deliberately superseded** (round 4's single-value "one-line read" tiles on Cost, Latency and
  Health, each replaced by a 3-number scores query over the same events), and that allowance is
  pinned to three specific query substrings so nothing else can vanish through it.
* **Schema-validated** against the official `schema/workbook.json` with `jsonschema` Draft 7:
  **0 errors** for the whole document, and 0 for each part checked in isolation — the tab bar as
  `definitions.link`, all 8 tab groups and all 3 collapsed groups as `definitions.group`, and all 7
  scores steps as `definitions.query`.
* **Structure re-asserted from the parsed file**: 6 overview tiles at `15/15/20/15/15/15` = 95, all
  bare numbers; `type: 11` tab bar with 8 links on `cellValue: "SelectedTab"`; 8
  `conditionalVisibility` values matching the 8 `subTarget`s 1:1; **Documentation last, Cost first**.
* **PUT to the same throwaway resource and round-tripped.** `PUT` 200
  (`timeModified 2026-08-22T05:28:57Z`); the follow-up `GET` with `canFetchContent=true` returned
  `serializedData` **byte-identical to what was sent** — **111,428 characters / 111,660 UTF-8 bytes**
  both ways, with all 104 em dashes, 10 arrows and the `≥` intact. The four-section shape was then
  re-read back out of what Azure stored, not just asserted locally.
* File hygiene unchanged: CRLF throughout (1,372 lines), trailing newline, UTF-8 without BOM.
  **113,032 bytes on disk**, against the reverted file's 46,472 and round 4's 95,792.

**Still not verified, and it cannot be from here.** No pixels were seen. The explicit success bar this
round — *do the four boxes actually fit one screen with no scrolling* — is a rendering question, and
the claim here is only that the four steps exist in that order with the most compact schema-supported
settings for each. On a short browser window the fourth section will still need a scroll and that is
arithmetic, not a defect: a `size: 1` chart plus a 5-row table plus a tile row plus the parameter
pills and the tab bar is roughly 540px of the ~580px a 1080p window leaves, with no margin for a
laptop-height window. Same test resource, same URL — refresh it:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
What to look at, in one glance per tab: a **row of 2-3 numbers first**, one line of words under it, a
**short** chart, then a 5-row table — and on Cost / Component quality / Online signals a single
**Show …** button at the bottom rather than more tables. Still a disposable copy; still to be deleted
once confirmed.

### The six overview tiles were abandoned for a plain table (2026-08-22, round 6)

**Founder feedback, verbatim:** *"still same scroll bar, fonts big, not visible some items. cost today
is just visible also scroll bar is there and very big font, quality pass r is just visible and no
value at all, Alerts today unnecessary scroll bar and such big fonts with no alignment, Clarifi is
only shown nothing in the below section visible, Zero-result rat is text nothing visible below empty
still not correct way to show empty, Golden bank lower section scroll bar not needed also showing a
vague partial comment of '53 gaps - static, 2026-08-21'"* — plus, separately: *"for top tiles make
the fonts very very small"*.

**Read as a list, that is one complaint per tile, in tile order** — cost, quality pass rate, alerts,
clarification, zero-result, golden-bank — and the truncations name themselves: "quality pass **r**",
"**Clarifi**", "Zero-result **rat**". Six tiles at `customWidth: 15` are ~15% of the page each, so
the `title` clips mid-word, the `formatter: 12` big-number renderer fills what is left, and the
subtitle gets a scrollbar. That is the *tiles* visualization behaving as designed in a box too small
for it, not a parameter that was set wrongly.

**Three rounds had already tried to fix these same six tiles** — the `customWidth` unit fix (round 3),
the `latest`/`NaN` query fixes and the group re-wrap (round 5), and the width/row rebalancing in
between. Each one passed schema validation, live query execution and a byte-identical round-trip, and
each one still rendered broken in a way nobody predicted. The agreed conclusion, before this round
started, was to **stop using `tiles` for the overview row** rather than tune it a fourth time.

**What replaced them.** The overview group is now a caption line and **two `visualization: "table"`
steps** sharing one column layout — `Metric | Value | Detail`:

| Metric | Value today | Detail |
|---|---|---|
| Cost today (USD) | `0.02` | 9 calls since midnight |
| Quality pass rate (%) | `— (not run)` | no agent_eval_run events in the selected time range |
| Clarification rate (%) | `— (not run)` | nothing calls emit_online_signals() on a schedule yet |
| Zero-result rate (%) | `— (not run)` | nothing calls emit_online_signals() on a schedule yet |
| Golden-bank coverage | `8 of 53` | closed answer-quality gaps with a re-runnable test - static, hand-entered 2026-08-21 |
| Alerts today | `1` | worst Sev2 - Sev2: 1 |

**It is two steps and not one, and that is a hard platform constraint, not a preference.** Five of the
six metrics come from Log Analytics (`customEvents` on `appi-invoicellm-dev`); *Alerts today* comes
from Azure Resource Graph (`alertsmanagementresources`). A workbook query step carries exactly one
`queryType`/`resourceType`, so the two cannot be `union`-ed inside one step. The obvious escape —
Log Analytics' cross-service `arg()` operator — was **tested rather than assumed, and it fails on the
path the portal actually uses**:

* `arg("").alertsmanagementresources | take 1` **succeeds** against `api.applicationinsights.io/v1`.
* The same query against `management.azure.com/{appInsightsResourceId}/query?api-version=2018-04-20`
  — the ARM-proxied path a workbook step runs on — returns
  `BadArgumentError / QueryValidationError: "The 'adx' pattern cannot be used with the current
  authentication scheme"`.

Two other ways to force one step were considered and rejected as *more* exotic than the thing being
removed: a workbook **merge** step over two hidden source steps, and a **hidden ARG-backed parameter**
(`isHiddenWhenLocked`, 3,935 uses across Microsoft's 668 shipped templates, so it is a real pattern)
interpolated into the union query. Both would put all six rows behind a single point of failure; two
independent steps fail independently, which matters more here than the seam. The two grids carry
**identical `customColumnWidthSetting` values on identically-named columns**, so they line up as one
continuous table with a repeated header — which is also the direct answer to "no alignment".

**Empty states cannot be blank, and that is now structural rather than a message.** The old tiles
relied on `noDataMessage`, which only fires when a step returns *zero rows* — in a six-row union a
metric with no data would simply have no row at all, which is worse than a blank tile. Every leg
therefore terminates in a `summarize` with **no `by` clause**, which KQL guarantees emits exactly one
row even over empty input, and the value column is a **string** so it can hold `— (no data)` /
`— (not run)` instead of a number. Verified live, not reasoned about: `summarize` over an empty set
returns 1 row (LA *and* ARG), `max()` over empty returns **null, not NaN**, and `arg_max()` over empty
returns one all-null row. The round-5 fixes are carried forward unchanged — `latest` is still not used
as a `let` name, and every numeric guard is `isnull(x) or isnan(x)`, never `isnotnull(x)` alone.

**All four reachable empty branches were executed live**, not inferred: `Tenant=all`, a real tenant,
a tenant with no data (which drives the cost leg into `— (no data)`), and a forced-empty alerts set
(which drives *Alerts today* to `0` with `none fired today - this source is live, so 0 here is a real
zero`). The alerts row is still the deliberate exception to the dash rule, for the same reason as
before: ARG is genuinely live, so zero there is a real zero.

**The golden-bank wording is now complete rather than a fragment.** `of 53 gaps - static, 2026-08-21`
was the tail of a clipped subtitle; it is now `8 of 53` in **Value** and `closed answer-quality gaps
with a re-runnable test - static, hand-entered 2026-08-21` in **Detail**, in a column sized `1fr` so
it takes all remaining width.

**"Make the fonts very very small" — the honest answer is that no such control exists for a table.**
Checked, not guessed: the word `font` appears **zero times** in Microsoft's official
`schema/workbook.json`; `gridSettings` accepts only `formatters`, `labelSettings`, `filter`,
`rowLimit`, `hierarchySettings` and `sortBy`; and a step's `styleSettings` accepts only `margin`,
`padding`, `maxWidth` and `showBorder`. Across the 668 templates Microsoft ships there are exactly
**three** font-ish keys anywhere — `statSettings.valueFontStyle` (19 uses, the *stat* visualization),
an undocumented `tileSettings.styleSettings.fontSize` (**1** use, and it sets `"large"`), and
`/layout/options/rowHeight` (2 uses, an Azure *dashboard* property, not a workbook one). **None of
them applies to a grid.** What actually made the text huge was `formatter: 12`, the big-number
renderer inside `tileSettings`; a grid cell renders at the portal's standard grid font, which is
already much smaller. So the font complaint is addressed by removing the big-number renderer, not by
setting a size — and if the founder wants it smaller still, the schema offers no way to do it and the
next lever would be browser zoom.

**What was deliberately avoided, because the schema still allows misconfiguring this into the same
failure:** no `formatter: 12` anywhere (the big-number renderer); no `tileSettings` at all; no
`customWidth` on either step, so both are full width and no title can clip; no `gridSettings.rowLimit`
and no `gridSettings.filter` (a filter box is a second row of chrome above a six-row table); and no
fixed-unit width on the longest column — `Detail` is `1fr`, which the grid documentation defines as a
share of the *remaining* space, so it cannot overflow into a horizontal scrollbar the way a `px`/`ch`
value can. Both steps use `size: 4`, the most compact well-attested grid height: every table with
`gridSettings.rowLimit <= 5` in Microsoft's 668 templates uses it (6 of 6, in
`Azure Security Center/Containers Security` — the same template this workbook's tab bar was modelled
on — at `customWidth: 50`, i.e. as compact side-by-side summary panels). The numeric meaning of
`size` is **not documented anywhere public**; the docs only say "the vertical size of the control:
small, medium, large, or full", so this is usage evidence, not a specification.

**One real thing was given up: the severity icons.** Round 4's `formatter: 18` threshold grid mapped
`Sev0`–`Sev4` to their portal icons on the alerts tile, and it was the only colour in the workbook.
Thresholds on a shared string `Value` column that also holds `— (not run)` would be meaningless, so
the icons are gone and severity is now words (`worst Sev2 - Sev2: 1`). The sentence that travelled
with them — *"Sev0/Sev1 are the ones worth interrupting someone for"* — was **kept**, as a
`tooltipFormat` on the alerts grid's `Metric` column (858 grid formatters carry a `tooltipFormat`
across Microsoft's templates, so this is ordinary). It is a hover, which is weaker than an icon; it is
recorded here as a loss rather than dressed up.

**One time-context divergence, stated rather than left to be found.** The six tiles had three
different time contexts (cost: fixed 24h; golden-bank: fixed 1h; the other three: the `TimeRange`
pill). One step can only have one, and it is `timeContextFromParameter: "TimeRange"`. For **all four
values the pill offers** (7/14/30/90 days) every leg returns exactly what its tile returned, because
the cost leg carries its own `where timestamp >= startofday(now())` filter. The pill also allows a
*custom* range, and a custom range shorter than the elapsed part of today would make "Cost today"
under-report. That is the only behavioural difference from the tiles.

**Verified how — this round:**

* **Concurrent-edit defence, and it was load-bearing given what happened in round 5.** The
  destination file's SHA-256 was recorded at task start (`4a93f912…`, 113,032 bytes), asserted before
  the build, and **re-read from disk and re-asserted immediately before the write**, with the write
  refusing to proceed on a mismatch. It matched both times.
* **Both new queries executed live before being written into the file**, in every reachable branch —
  4 parameter/time combinations for the union, 2 for the alerts row. Results are the table above.
* **All 25 query steps in the written file re-executed live** — extracted programmatically from the
  JSON rather than retyped — **0 failures**, every one returning its expected column schema. (The
  first run reported 3 Health failures; the fault was in the *harness*, which did not substitute the
  `{TimeRange:seconds}` workbook formatter, not in the workbook. Recorded because a harness bug that
  looks like a product bug is the same failure class as round 4's vacuously-passing audit.)
* **The diff is provably only the overview**, measured against **what Azure had stored**, not a local
  copy: of 30 query strings held before the PUT, **24 are kept byte-identical, 6 removed (exactly the
  six tile queries), 2 added**. The `shared-parameters` step and the entire `sections` subtree — the
  tab bar and all 8 tabs — are **byte-identical** as JSON.
* **Content-loss audit, mechanical**: every quoted identifier and numeric literal in the old overview
  text (queries, titles, `noDataMessage`s, caption, tooltip) checked against the new — **17/17
  identifiers and 20/20 numbers present, 0 missing** — plus 14 hand-listed load-bearing phrases
  (`gpt-5-mini`, `properties.essentials.severity`, `startofday(now())`, `2026-08-21`, "worth
  interrupting someone for", …), all present.
* **Schema-validated** against the official `schema/workbook.json` with `jsonschema` Draft 7:
  **0 errors** whole-document, plus both new steps validated in isolation as `definitions.query` and
  the overview group as `definitions.group`.
* **Serialiser proved lossless first**: `json.dumps(indent=2, ensure_ascii=False)` + CRLF reproduces
  the pre-change file byte-for-byte, so the git diff is content only.
* **PUT to the same throwaway resource and round-tripped.** `PUT` 200
  (`timeModified 2026-08-22T05:59:38Z`); the follow-up `GET` with `canFetchContent=true` returned
  `serializedData` **byte-identical** to what was sent — 106,862 characters / 107,096 UTF-8 bytes both
  ways, 105 em dashes, 10 arrows and the `≥` intact. The new shape was then re-read **out of what
  Azure stored**: two `table` steps, no `tileSettings`, no `customWidth`.
* File hygiene unchanged: CRLF throughout (1,165 lines), trailing newline, UTF-8 without BOM.
  **107,096 bytes on disk**, against round 5's 113,032.

**Still not verified, and it cannot be from here.** No pixels were seen. That a `table` avoids the
scrollbar and the oversized font is a **reasoned bet, not a measurement**: the big-number renderer is
gone and a grid has no font control to get wrong, but whether `size: 4` gives a five-row grid enough
height to avoid an internal scrollbar is exactly the kind of rendering question the last three rounds
each got wrong in a new way. It is a better bet than the previous three because a grid has far fewer
ways to be misconfigured than a tile — that is the whole argument, and it is worth no more than that.
Same test resource, same URL — refresh it:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
What to look at, in one glance: **one table of six rows** above the tab bar, no big numbers, no
scrollbar, and the golden-bank row reading `8 of 53` with its full sentence beside it.

**One thing left untouched that is worth knowing:** the seven per-tab "scores" steps inside the tabs
(`cost-scores`, `latency-scores`, …) are **still `tiles`**. They were out of scope this round and the
founder's complaints were all traceable to the six overview tiles, but they are the same
visualization with the same failure modes, and if they render badly the same table treatment is the
fix.

### Seven score tiles, one merge step, and every redundant heading deleted (2026-08-22, round 7)

Six founder asks landed during this one round, and the last one **reversed** the decision the round
started from. In the order they arrived: *"show the full table... no scroll bar"*; simplify the Alerts
row's Detail; *"show one table only"*; Latency is missing from the overview; delete the overview
caption and the per-tab headings; and finally *"cant u make 7 score tiles at top like the one in cost
tab"*. The end state is **7 tiles**, not a table — the intermediate table shape is recorded below
because the reasoning that produced it is what made the tiles possible.

**The overview group is now three steps and no caption:**

| name | type | role |
|---|---|---|
| `overview-table` | 3, `queryType: 0` | 6 Log Analytics rows (`ord` 1-6) — **hidden** |
| `overview-alerts-row` | 3, `queryType: 1` | 1 Resource Graph row (`ord` 7) — **hidden** |
| `overview-merged-table` | 3, `queryType: 7` | the only visible step: `union` of the two, rendered as `tiles` |

**1. One step feeding N tiles is exactly why the Cost tab's tiles work, and it needed a merge.** The
founder pointed at `cost-scores` as the example they are happy with. Read rather than assumed, that
step is **one full-width query step whose query returns 3 rows**, and the tiles renderer lays those 3
rows out itself. The six overview tiles that failed three times were the opposite: **six separate
steps at `customWidth: 15`**, each rendering one tile inside a box ~15% of the page wide. That is the
difference that root-caused the clipped titles and the subtitle scrollbars, and it is a property of
the *step layout*, not of `tiles`.

To get 7 tiles out of one step, the two data sources have to become one result set. Round 6's
constraint stands and was not re-litigated — an LA query and an ARG query cannot be `union`-ed inside
one *query*, and LA's `arg()` operator fails on the ARM-proxied path a workbook actually uses. What
round 6 rejected as "more exotic than the thing being removed" turns out to be **ordinary shipped
Microsoft practice**, and the numbers were counted, not assumed: across the 668 templates in
`microsoft/Application-Insights-Workbooks` there are **163 `queryType: 7` merge steps**, **49 of them
`mergeType: "union"`**, and **21 pairing a `queryType: 0` step with a `queryType: 1` step** — exactly
this pair. A merge step consumes the *results* of two earlier steps client-side, so each source keeps
its own `queryType`/`resourceType` and the merge carries neither. Microsoft's own
`Windows Virtual Desktop/AtScale/Overview` does this and then renders the merge as **tiles**, which is
the same shape built here.

Hiding the sources uses that template's idiom: `conditionalVisibility: {parameterName: "nevershow",
comparison: "isNotEqualTo"}`, where `nevershow` is deliberately **not a declared parameter** (checked —
that template declares 7 parameters and `nevershow` is not one of them). `leftTable`/`rightTable`
reference steps by `name`. Both sides' columns map to the **same** `mergedName` in `projectRename`,
which is what makes a union stack rows instead of producing `Metric`/`Metric1`. `ord` is carried
through the merge purely so `tileSettings.sortCriteriaField` can order the tiles, exactly as
`cost-scores` uses its own `ord`.

**Cost of this, stated plainly: the entire overview is now behind one step.** Two grids failed
independently; if this merge does not render, the overview is **blank**, because its sources are
hidden. That is a worse failure mode than round 6's, accepted because the founder asked for one thing
at the top rather than two.

**2. The tile configuration, property by property, against the one the founder approves of.** Every
key was copied from `cost-scores`, and the top-level `tileSettings` key set is asserted **identical**
to it in the build script:

| property | `cost-scores` (the reference) | overview tiles | same? |
|---|---|---|---|
| step `customWidth` | absent (full width) | absent | yes — **this is the fix** |
| step `size` | `4` | `4` | yes |
| `tileSettings.size` | `"auto"` | `"auto"` | yes |
| `titleContent` | `metric`, `formatter: 1` | `Metric`, `formatter: 1` | yes |
| `leftContent.formatter` | `12` (big number) | `12` | yes |
| `leftContent.formatOptions.palette` | `"auto"` | `"auto"` | yes |
| `leftContent.numberFormat` | decimal, 2 dp | **absent** | **no — the one deliberate difference** |
| `subtitleContent` | `detail`, `formatter: 1` | `Detail`, `formatter: 1` | yes |
| `showBorder` / `sortCriteriaField` / `sortOrderField` | `true` / `ord` / `1` | same | yes |

The single difference has a reason: `cost-scores`' `value` column is a **real number** in every row,
so a `numberFormat` applies. The overview's `Value` is a **string** by round 6's honesty fix, because
it has to be able to hold `— (not run)` on a per-row basis (three of the seven metrics have never
run). A `numberFormat` on a string is meaningless. Shipped precedent for this exact combination was
looked for rather than assumed: of **802** tile steps with `leftContent.formatter: 12` across the 668
templates, **3** bind it to a column built by `strcat(...)` — `SapMonitor2.0/AIOpsInsights/
Availability Insights/Auto RCA`, steps `statTiles` / `hanaStatTilesForService` /
`hanaStatTilesWoService` — and all three use `formatter: 12` with **no `numberFormat`**, no
`customWidth`, and `size: 4`. That is the configuration copied.

**Where this could still fail, said before the founder finds it:** 3 shipped uses out of 802 is thin
evidence that the big-number renderer handles a non-numeric string, and `"99.5%"` (what SapMonitor
feeds it) is far more number-like than `— (not run)`. If the renderer blanks those three tiles, the
**`Detail` subtitle still states the reason** on every tile (`no agent_eval_run events in the selected
time range`, etc.), so the failure degrades to "no big number, explanation still there" rather than to
a tile that looks like a healthy zero. The second unknown is layout: 7 tiles across one full-width row
is more than the 3 the Cost tab renders, and whether the renderer wraps them onto two rows or narrows
them is not knowable from JSON. Wrapping would be fine; narrowing to Cost-tab width is fine; narrowing
below that would reproduce the clipping. **This is a fourth attempt at `tiles` in this exact spot, and
the argument for it is one specific structural difference — one full-width step instead of six
15%-wide ones — not a general belief that it will look right.**

**3. The Alerts Detail is a plain severity count list.** The KQL dropped the
`worst_num = min(toint(substring(sev, 3)))` leg and the `strcat('worst Sev', worst_num, ' - ', …)`
framing; `Detail` is now just the breakdown. Run live: today reads `Sev2: 1`; the same query over a
30-day window — the only way to get more than one severity out of the real data right now — reads
`Sev1: 8, Sev2: 18`. The zero branch is unchanged (`none fired today - this source is live, so 0 here
is a real zero`), because with no alerts there are no severities to count and that sentence carries
the one honest exception to the dash rule.

**One real loss:** the tooltip *"Sev0/Sev1 are the ones worth interrupting someone for"* is gone. It
was a `tooltipFormat` on a grid column; grid formatters do not exist on a tiles step at all, and even
in the intermediate table shape that column also held the cost and latency rows, so it would have
attached an alert-severity sentence to the cost row. Recorded as a loss, not dressed up.

**4. Latency is the 6th Log Analytics row, reduced from the Latency tab's own query.** Same
`customEvents | where name == 'llm_agent_call'` base and the same `percentile(latency_ms, 50/95)` and
`top 1 by agent_p95 desc` shape that `latency-scores` and `latency-table` already use — no new metric
was invented. `Value` is the overall median across agents; `Detail` is
`p95 <n> ms, slowest agent <name>, <n> calls in window`. Live today: `7214` /
`p95 14875 ms, slowest agent dashboard.insights, 9 calls in window`. Empty state follows Cost's rule —
`— (no data)`, never a fabricated `0`. Checked live rather than reasoned about: `percentile()` over an
empty set returns **null, not NaN**.

**5. The caption and all 7 tab headings are deleted, and nothing they said was dropped.** The overview
caption (`**A dash means no data, never a healthy zero.** …`) is gone as a step. On every
non-Documentation tab, two strings were removed: the group's `title` (which rendered the `###` heading)
and the first step's `title`, which in all 7 cases began with the tab's own name — `Cost — USD per day,
by agent`, `Latency — p50 and p95 per agent per day`, `Quality — the golden sample, re-asked and
graded`, `Component quality — which stage of the pipeline is wrong`, `Online signals — live traffic, no
ground truth`, `Golden-bank coverage — how much of the gap history is re-runnable`, `Health — alerts
fired per day`. The tab bar already names each tab, so both were repeating it. Documentation keeps its
heading; it is the reference tab and `# Documentation` is its own H1.

Six of those seven titles said nothing the explainer line directly underneath does not already say —
checked one by one. **The seventh did**: `Online signals — live traffic, no ground truth`. That caveat
appears nowhere else in the workbook (grep: zero other occurrences of "ground truth"), so it was moved
into the explainer as its opening words — `**Live traffic, no ground truth.** A rate above its own
threshold…` — which costs no vertical space. The caption's honesty rule was already on the
Documentation tab in substance (`A blank panel means no data, never a healthy zero`); it was widened
to cover the dash convention: `**A dash (—) on an overview tile, and a blank panel on a tab, both mean
no data — never a healthy zero**, except on the Health tab and the overview's Alerts tile.`

**Deviation from the stated scope, flagged rather than buried:** this round was scoped "do not touch
Documentation", and the Documentation tab *was* edited. Three of the edits keep deleted text alive
(above). Two more fix statements that round 6 left stale and that describe the exact thing being
changed: `doc-intro` still said the pills were shared by "the six overview tiles", and
`doc-metric-reference`'s overview table still described `Alerts today` as "one tile per severity, each
with its severity icon" — icons round 6 had already removed. A `Median latency (ms)` row was added to
that reference table because it is a new overview metric. Nothing else on that tab was touched.

**6. The scrollbar question — what was actually checkable, and what still is not.** Checked this time
rather than reasoned about:

* There is **no height property to get wrong**. The official `schema/workbook.json` has **40
  definitions and not one carries a height**, `minHeight`, `maxHeight` or `rowHeight`; `styleSettings`
  accepts only `margin`, `padding`, `maxWidth`, `showBorder`, and no overview step sets it. `size` is
  typed only as `"integer" / "Size of the step"` — no enum, no documented numeric meaning.
* **No `rowLimit`** anywhere in the overview, so nothing truncates rows.
* `size: 4` is the **largest value that occurs anywhere** in the 668 templates (observed values are
  0-4 across 6,376 occurrences, nothing above 4), so there is no "taller" setting to move to.
* Usage evidence that `4` is what Microsoft picks for *short* panels specifically: among table steps
  with a **deliberate** `rowLimit` (not the editor default 10000), the median is **7.5 at `size: 4`**
  (8 of 16 are ≤ 6 rows) against **1000 at `size: 0`** and **1000 at `size: 2`**, where almost none go
  below 20 rows; and 260 of 595 tile steps use `size: 4`. `cost-scores` — the step the founder is
  happy with — is `size: 4` with `tileSettings.size: "auto"`, and the overview now matches it exactly.

**That is as far as it goes, and it is not a measurement.** No pixels were seen. What can be stated:
nothing in the file forces a fixed short height, no `rowLimit` can truncate, and the overview's height
settings are now byte-identical to the tile step the founder has already looked at and accepted. What
cannot be stated: the rendered height of 7 tiles in one full-width row in this browser at this zoom.
That remains an open question and the founder's eyes are the instrument.

**Verified how — this round (five successive writes, each hash-guarded):**

* **Concurrent-edit defence on every write.** Baseline SHA-256 recorded at task start (`487b9b83…`,
  107,096 bytes); each of the four build scripts asserted the expected hash on entry, proved its
  serialiser reproduced the on-disk bytes exactly, and **re-read the file and re-asserted the hash
  immediately before writing**, aborting on mismatch. All ten checks matched.
* **Every new query executed live before being written into the file**: the 6-row LA union in 4
  branches (`Tenant=all`; the one real tenant; a non-existent tenant, which drives both event-backed
  rows to `— (no data)`; a 90-day window) and the alerts query in 3 (today; forced-empty; a 30-day
  window for the multi-severity format). Results are quoted above.
* **All 25 executable query steps in the written file re-executed live after every one of the five writes** — extracted
  from the JSON, not retyped — **0 failures**, expected column schemas, including the final state with
  `ord` added. The 26th step is the merge descriptor: it is `queryType: 7`, **client-side portal logic
  with no query API to call**, so it is skipped. That is a genuine verification gap, not a pass.
* **Diffs measured against what Azure had stored**, not against a local copy. Round 7a: of 25 stored
  queries, 23 byte-identical, 2 removed, 3 added, and everything outside the overview group
  byte-identical as JSON. Round 7b: **all 26 queries byte-identical** (a pure text/title change) —
  29 diff lines, all 7 headings + the caption + 4 markdown strings. Round 7c/d: 23 identical, 3
  replaced (the two sources gaining `ord`, the merge gaining `ord` in `projectRename`). Round 7e:
  **all 26 byte-identical again** — 13 diff lines, all of them the three group expanders plus two
  markdown strings.
* Content-loss audit: **24/24** load-bearing strings present in the overview subtree (all 7 metric
  names, `8 of 53`, both empty-state sentences, `gpt-5-mini`, `properties.essentials.severity`,
  `startofday(now())`, the caption's rule); all three intended removals (`worst Sev`, `worst_num`,
  "worth interrupting someone for") absent **file-wide**; all 7 deleted tab titles absent file-wide;
  "ground truth" still present.
* **Schema-validated** Draft 7 against the official `schema/workbook.json` after every write:
  **0 errors** whole-document, plus each overview step as `definitions.query` and all 8 tab groups
  plus the overview group as `definitions.group`. Structure re-asserted each time: 8 tab groups, 8
  tab-bar links, exactly one group `title` left (Documentation).
* **PUT to the same throwaway resource and round-tripped, four times.** Final `PUT` 200
  (`timeModified 2026-08-22T06:36:14Z`); the follow-up `GET` with `canFetchContent=true` returned
  `serializedData` **byte-identical** to what was sent (106,766 chars / 106,990 UTF-8 bytes both ways,
  101 em dashes, 10 arrows, the `≥` intact). The final shape was re-read **out of what Azure stored**:
  two hidden sources and one `queryType: 7` step at `visualization: tiles`, `size: 4`, no
  `customWidth`; the merge descriptor re-checked there too (`mergeType: union`, both table references
  resolve to real sibling steps, every non-`unknown` `fromId` equals the merge id, merged columns
  exactly `ord`/`Metric`/`Value`/`Detail`).
* File hygiene unchanged: CRLF, trailing newline, UTF-8 no BOM. **108,127 bytes on disk**, against
  round 6's 107,096.

Same test resource, same URL — refresh it:
`https://portal.azure.com/#@/resource/subscriptions/2ae37d8b-3189-474c-9508-4b3d7ceec4dd/resourcegroups/rg-invoice-llm-dev/providers/microsoft.insights/workbooks/0f1e2d3c-4b5a-4c9d-8e7f-a1b2c3d4e5f6/workbook`
What to look at: **seven** score tiles at the top in the Cost tab's style — Cost, Median latency,
Quality, Clarification, Zero-result, Golden-bank, Alerts — with **no caption line above them**; the
Alerts tile reading `1` over `Sev2: 1`; and **no `### Cost` heading inside the Cost tab**, its tiles
now sitting directly under the tab bar with the by-tool detail collapsed into a section you click
to open. The three never-run tiles are the ones to look at hardest: if
their big number is blank rather than `— (not run)`, the string-in-a-big-number-renderer bet did not
come off, and the fix is `formatter: 1` on `leftContent`.

**7. "Can the summary be the 1st tab since it's not visible totally" — measured, and the cause was
not the tab order.** There is no tab named Summary; Cost is already first and already the default. So
the question was turned into a measurement: how many rendered blocks does each tab actually have?

| Tab | Blocks rendered on open (before this round) | After |
|---|---|---|
| **Cost** | **6** — heading, tiles, explainer, timechart, grid, **plus a 3-item detail group** | **3** |
| Latency / Quality / Health | 5 — heading, tiles, explainer, chart, grid | 4 |
| Component quality / Online signals | 6 — the same 5 plus a 1-item detail group | 4 |
| Golden-bank coverage | 4 | 3 |

**Cost was measurably the longest tab in the workbook, and two of the things making it long were
empty.** `cost-by-tool-table` and `cost-by-tool-turn-composition` both return **0 rows** live
(`ENABLE_AGENTIC_SAGE` is off, so no `sage.*` event exists), and both were rendering unconditionally,
under a 221-character header, below the chart and the main table. The Documentation tab has claimed
since the consolidation round that *"detail tables that would not fit sit behind a **Show …** button"*
— checked, and **no such button ever existed**: none of the three `*-detail` groups carried
`conditionalVisibility` or anything else. The doc was describing an intention, not the file.

Fixed with the native group expander rather than by reordering tabs: all three detail groups
(`cost-by-tool-detail`, `component-quality-detail`, `online-signals-detail`) now carry `expandable:
true`, `expanded: false` and a `title` to click. **`expandable` is not in the published schema** — but
neither are `crossComponentResources` or `timeContextFromParameter`, both of which demonstrably work
in this very file, so the schema is known-incomplete rather than authoritative here; the positive
evidence is **198 shipped uses of `expandable` across the 668 templates, 115 with `expanded`, and all
198 carrying a `title`** (the clickable header), which is why the titles were added. The `### Cost by
tool …` markdown heading inside the group was deleted, because the group title now says it — the same
de-duplication as the seven tab headings. `doc-intro`'s "Show … button" sentence was corrected to say
what the file now actually does.

**Net effect on the default tab:** Cost opens as tiles → one explainer line → chart → table, with the
by-tool detail one click away. That is 3 blocks where it was 6. **No tab was renamed or reordered** —
that would have been guessing at what "summary" meant, and the measurable defect was elsewhere.

**Still untouched and worth knowing:** the seven per-tab `*-scores` steps are unchanged — they were
already the good configuration, and they are now the reference the overview copies.

## Workbook — split into 9 standalone workbooks (2026-08-23)

The single combined tabbed workbook (`infra/monitoring/ai_control_tower.workbook.json`) was
**retired and deleted**. Reason: the founder wants each section pinnable to an Azure Dashboard
individually, and Azure lets you pin a whole workbook or an individual visual to a Dashboard, but a
pinned tile does not evaluate the source workbook's own `conditionalVisibility`/`SelectedTab` tab
logic — so a single tab's content could never be reliably pinned out of a combined, tab-gated file.

Replaced by **9 standalone workbook JSON files** in the same folder, none with a tab bar or any
`conditionalVisibility` gating: `ai_control_tower_summary.workbook.json` (from the old overview
score-tile group) and one per former tab — `_cost`, `_latency`, `_quality`, `_component_quality`,
`_online_signals`, `_golden_bank`, `_health`, `_documentation`. Each file carries its own copy of
the shared `TimeRange`/`Subscription`/`Tenant` `type: 9` parameter block, because every KQL query
inline-references `{Tenant}` and most use `timeContextFromParameter: "TimeRange"` — without a local
copy of that block, a standalone file's queries would silently break. Each non-Summary file is its
former tab's `items` array unwrapped — the outer `type: 12` group wrapper and its `SelectedTab`
`conditionalVisibility` dropped, content otherwise untouched. Summary preserves the old overview
group's hidden-query merge mechanism exactly as it was (the two source steps' `nevershow`
`conditionalVisibility`, feeding a `queryType: 7` union into the `tiles` step).

**Founder follow-up, same session:** the flow needed to be "pin Summary's tiles to the Dashboard →
click through → the full Summary workbook opens → Documentation is reachable from there," not a dead
end at the 7 tiles. A cross-workbook deep link was deliberately not built (Azure Workbooks' portal
blade URL format for linking to another saved workbook resource is fragile and version-dependent).
Instead, `ai_control_tower_summary.workbook.json` also **embeds the full Documentation content** as
a collapsed `type: 12` group at the bottom of its `items` array — same collapsible pattern already
used elsewhere in this workbook (the pre-existing "Cost by tool" section): `groupType: "editable"`,
`loadType: "explicit"`, `loadButtonText: "Show full documentation"`, `expandable: true`,
`expanded: false`. Documentation therefore now lives in two places — its own standalone pinnable
workbook (`ai_control_tower_documentation.workbook.json`) and embedded/collapsed inside Summary —
kept textually identical (asserted programmatically at build time) so they cannot drift apart.

New `infra/monitoring/ai_control_tower_workbooks.bicep` deploys all 9 as
`Microsoft.Insights/workbooks@2022-04-01` resources, `serializedData` loaded per file via
`loadTextContent()` rather than hand-translated into a bicep object literal (avoids escaping bugs on
large KQL-heavy JSON), `appi-invoicellm-dev` referenced as `existing` for `sourceId`. Deliberately
not routed through `08-apps.bicep`/`params.dev.json` — same narrow-standalone-deploy rationale as
`infra/agent-eval-job-only.bicep`. `az bicep build` passed; `az deployment group what-if` against
`rg-invoice-llm-dev` returned a clean **9 to create, 0 to modify, 0 to delete**. **Not yet
deployed** — `az deployment group create` was deliberately not run, pending founder go-ahead.

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
      is still empty. See "Workbook — the second pass".
      **Restructured 2026-08-22 on founder feedback** ("you can't scroll 10 pages to see
      everything"): the 8 sections are now 8 **tabs**, with 6 single-stat overview tiles above the
      fold reusing the same queries, and the Tenant parameter now resolves to `all` on load instead
      of needing manual selection. Layout only — all 26 pre-existing items asserted byte-identical
      after the rebuild, and all 23 queries in the new file re-executed live (0 failures; the
      alerts-today tile returned a real `Sev2: 1`). See "Workbook — the usability restructure".
      **Tab mechanism corrected 2026-08-22** after the founder confirmed the restructured workbook
      still rendered as one scrolling page: `"style": "tabs"` on a `type: 12` group is not a
      supported property (verified absent from the official `schema/workbook.json`) and was silently
      ignored. Replaced with the real mechanism — a `type: 11` links step (`style: tabs`,
      `linkTarget: parameter`) plus `conditionalVisibility` on each of the 8 groups, keyed to
      `SelectedTab`. Content byte-identical; schema-validated; structurally identical to a shipped
      Microsoft tabbed template; and **round-trip verified against a real Azure resource** — a
      throwaway test workbook `AI Control Tower - TAB FIX TEST` in `rg-invoice-llm-dev` stores the
      JSON byte-for-byte. Visual confirmation that the tab row renders and switches is still
      **founder action** (open the test URL). See "The tabs did not render — root cause and fix".
      **Content redesigned 2026-08-22** on the founder's "the workbook is not understandable":
      every explanatory paragraph from all 8 tabs consolidated into a single **Documentation** tab
      (renamed from "Read me first") as one table row per metric — 20 prose paragraphs across
      7 tabs became 79 table rows on one tab, text outside that tab fell 10,998 → 2,260 chars,
      and the six tiles' multi-sentence empty-state essays became `— (not run)` / `— (no data)`.
      Relocation and compression, not a cut: a mechanical audit confirms 79/79 identifiers and
      47/47 numbers from the old text survive. All 23 queries byte-identical (proven against what
      Azure had stored, not just locally); schema-validated 0 errors; round-trip byte-identical.
      See "The workbook is not understandable".
      **Insight-first ordering 2026-08-22** on "put the insights at top then explanation then
      graph": all 7 non-Documentation tabs reordered to heading → insight → explanation → charts.
      Cost, Latency and Health got a **computed** insight — three new query steps written and run
      live *before* being added, over the same events as the tab's own chart; the four tabs with no
      data got a plain statement of what a reading will mean once there is. Three further defects
      found and fixed from the "still not at all user friendly" feedback: **Documentation was the
      first tab**, so the workbook opened on its own 22,170-character reference wall (moved to
      last, Cost is now first); **the Data sources table still said `customEvents` was empty** when
      `llm_agent_call` has been arriving since 2026-08-22T03:48:30Z, directly contradicting the live
      `$0.02` tile (corrected and dated); and **there was no colour or icon anywhere** — severity
      icons added to the Alerts tile via `formatter: 18` thresholds, deliberately the only tile,
      because it is the only one with a threshold this repo did not have to invent. 25/25 queries
      re-executed live, 0 failures; exactly one pre-existing step property changed (proven against
      what Azure had stored); 88/88 identifiers and 43/43 numbers survive; schema-validated 0
      errors; round-trip byte-identical (94,466 chars). Two vocabulary questions (tile titles, tab
      labels) left explicitly to the founder rather than guessed. See "Put the insights at top"
      **Reverted outside this workstream and rebuilt 2026-08-22**: the file was found back at its
      first 27-item flat state (46,472 bytes, no tab bar, no tiles, no Documentation tab) — another
      IDE had written it, and the Azure test resource held a matching early copy so it was no help
      either. The round-4 definition was recovered **exactly** (94,466 chars, matching the recorded
      figure) by replaying the surviving round-4 build script over the surviving round-3 backup, so
      no content was reconstructed from prose. On top of it, the founder's new requirement: every
      non-Documentation tab is now **four sections on one screen** — a `tiles` step of 2-3 numbers
      reduced from that tab's own query, one line of explanation, the same chart at `size: 1`, and
      the same table at `gridSettings.rowLimit: 5` with a filter box. Four secondary tables moved
      into collapsed `loadType: "explicit"` groups (one button each). Two real defects found by
      running the seven new queries rather than reading them: **`latest` is a reserved KQL word**,
      and **`avg()` over an empty set returns `NaN` which passes `isnotnull()`**, so two tiles would
      have rendered a literal "NaN" instead of `— (not run)`; both fixed and both branches proved on
      synthetic rows. **Golden-bank coverage has three sections, not four** — no chart is possible
      from a static repo file, and the tab says so. 30/30 queries executed live, 0 failures;
      95/95 identifiers and 44/44 numbers preserved; 26/26 pre-existing queries byte-identical with
      exactly 3 deliberately superseded; schema-validated 0 errors; round-trip byte-identical
      (111,428 chars / 111,660 UTF-8 bytes). Whether the four boxes genuinely fit one browser screen
      is **founder verification** — it is a rendering question and is not claimed here. See "The
      file was reverted outside this workstream"
      **Overview tiles replaced by a table 2026-08-22 (round 6)**: after three rounds of tile fixes
      that each passed every automated check and still rendered broken, the six `tiles` steps above
      the tab bar were **removed** in favour of `visualization: "table"` — six rows of
      `Metric | Value | Detail`. Each of the founder's six complaints maps 1:1 to a tile, and the
      truncations name themselves ("quality pass **r**", "**Clarifi**", "Zero-result **rat**"): a
      `customWidth: 15` box plus the `formatter: 12` big-number renderer is what produced the clipped
      titles, huge fonts and per-tile scrollbars. It is **two** steps rather than one because
      *Alerts today* is Azure Resource Graph and the other five are Log Analytics, and a query step
      carries one `queryType` — the `arg()` escape hatch was tested and **fails on the portal's path**
      (`"The 'adx' pattern cannot be used with the current authentication scheme"`), though it
      succeeds on the v1 App Insights API. Both grids share identical column widths so they align as
      one table. Empty states are now structural instead of a `noDataMessage`: every leg ends in a
      `summarize` with no `by`, which always emits exactly one row, and `Value` is a **string**, so a
      metric with no data reads `— (not run)` rather than vanishing from the union — proven live in
      all four reachable branches, including a tenant with no data and a forced-empty alerts set.
      Golden-bank's clipped `of 53 gaps - static, 2026-08-21` is now `8 of 53` plus the full sentence
      in a `1fr` column. On "make the fonts very very small": **no font-size control exists for a
      grid** — `font` appears 0 times in the official schema, `gridSettings` has no such key,
      `styleSettings` offers only margin/padding/maxWidth/showBorder, and the only three font-ish
      keys in Microsoft's 668 templates belong to the *stat* and *tiles* visualizations or to Azure
      dashboards; removing `formatter: 12` is what shrinks the text. Deliberately avoided: big-number
      formatter, `tileSettings`, `customWidth`, `rowLimit`, a filter box, and any fixed-unit width on
      the longest column. One real loss, recorded not dressed up: the `Sev0`–`Sev4` **severity icons**
      are gone (thresholds on a shared string column would be meaningless); their sentence survives as
      a `tooltipFormat`. 25/25 query steps executed live, 0 failures; 24 of 30 pre-existing queries
      byte-identical with exactly 6 removed and 2 added, measured against what Azure had stored;
      `shared-parameters` and the whole `sections` subtree byte-identical; 17/17 identifiers and 20/20
      numbers preserved; schema-validated 0 errors; round-trip byte-identical (106,862 chars /
      107,096 UTF-8 bytes). **Whether a table actually avoids the scrollbar and the big fonts is a
      reasoned bet, not a measurement** — no pixels were seen. See "The six overview tiles were
      abandoned for a plain table"
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
- [~] Extend the SAGE parity-harness pattern to extraction and chat classify/SQL-gen, for
      substitution testing against one cheaper candidate model — **the substitution axis is built
      2026-08-23, no candidate has been benchmarked.** `utils/llm.build_llm()` +
      `scripts/run_agent_eval.py --provider/--model/--api-version/--persist-candidate` run the
      identical case set against a named provider/model for that run only: no setting is mutated,
      the judge stays on the configured default (comparability), a named provider refuses to
      silently become `MockInvoiceLLM`, and a candidate's rows are labelled and not persisted by
      default. 37 tests in `tests/test_model_substitution.py`; both branches smoke-run for real
      (`--provider mock` produced mock output against an Azure-configured `.env`;
      `--provider azure --model gpt-5-mini --api-version 2024-08-01-preview` ran a live turn).
      Still open: **no GPT-4o deployment exists**, **no Ollama server runs** (localhost:11434
      refused), so no cost-vs-quality delta table exists; and extraction is still not covered —
      the override patches the three **chat**-path modules only, deliberately, since this harness
      does not exercise `extraction_agent.py`. Also still blocked in practice on the scorer's
      absolute level being trustworthy: two of four known under-scoring biases were fixed
      2026-08-21 but never re-run against a live model, so there is no post-fix baseline for a
      candidate to be compared against
- [x] Constrain `QueryRoutingSchema.route` to a real JSON-schema enum — `Literal["RAG","SQL","CHAT"]`
      plus a before-validator that preserves the old case-tolerance, done 2026-08-23 after a live
      llama3.2 smoke test returned schema-valid but invented route values. Closes a silent failure
      mode on the live default chat path: an unrecognised route used to fall through
      `run_query_agent()`'s `else: # CHAT` branch, answering conversationally with no retrieval and
      no signal. Verified on Azure before and after (30/30 live classifications, 0 validation
      errors either way; a same-process old-vs-new A/B over 96 live calls, 0 errors in either arm,
      identical routes on unambiguous questions). The premise it was written for — that the enum
      fixes non-Azure models — is **unverified**, no Ollama server was available
