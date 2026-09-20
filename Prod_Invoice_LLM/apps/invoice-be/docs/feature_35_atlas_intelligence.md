# Feature 35 — ATLAS Intelligence: the agent over everything already computed

**App:** invoice-be · status lives in `be_features_tracker.md`
· **Counterpart:** FE Feature 24 (`apps/invoice-fe/docs/feature_24_atlas_briefing.md`) — the surface.
· **Builds on:** BE Feature 34 (`feature_34_atlas.md`) — every tool below wraps a Feature 34 service.
Feature 34 is not rewritten (CONVENTIONS hard rule 4); this file is additive.
· **Decision record:** founder rulings of 2026-09-20, recorded in §8 of this file.

---

## 1. Overview

**The founder's framing.** The application has done enough compute. Extraction, alerts,
duplicates, doubts, recon, forecast, ranking, memory, chat SQL and RAG all exist and are
deterministic. What is missing is the layer that looks at all of it *for this user, this
morning*, decides what matters, says why in one paragraph, and asks the one question it cannot
answer from data. That layer is an LLM with tools. It does not compute. It reads what was
computed and reasons over it.

**What ATLAS Intelligence is.** One agent, tool-calling, running on GPT-5.6 Terra, given a
registry of read-only tools that wrap every Feature 34 service plus SAGE. On the first open of
the work screen each day it produces a **briefing**: a few paragraphs, each citing the tool
results it came from. When a tool result is ambiguous it may ask one question; the answer becomes
a memory rule (D31). The deterministic lines from `GET /atlas/lines` are untouched and render
first; the briefing layers above them.

**What it is not.**

- Not new compute. No new check, threshold, baseline, or arithmetic is introduced anywhere in
  this feature. A number the model wants must come back from a tool (hard rule 3).
- Not an automation. No tool in the registry writes. Approve, dismiss, correct, requeue stay on
  the existing human-initiated endpoints (D8, D50).
- Not a background job. The briefing is generated on open, never between sessions (D38), never
  pushed (D36).
- Not a replacement for SAGE. SAGE stays a separate agent, called as one tool, at most once per
  briefing.
- Not Feature 33's report generator. Feature 34 §8 ruled that a plan-then-report loop produces
  reports; this loop has no scratchpad and no plan node.

**Naming.** "ATLAS" already names Feature 34's deterministic engine. This feature is "ATLAS
Intelligence" in specs and "the briefing" on screen. `agents/atlas_agent.py` is new; no
Feature 34 module is renamed.

---

## 2. File Coordinates

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `services/atlas_tools.py` | `ToolSpec`, `TOOL_REGISTRY`, `tools_for(grants)`, `run_tool(name, args, ctx)`, `ToolResult` | new | The registry. Each `ToolSpec` names the wrapped Feature 34 callable, its args schema, the capability required to see it, and a serialiser that returns JSON rows each carrying `record_kind`, `record_id`, `tenant_id`, `as_of`. `tools_for()` filters by `GrantSet` **before** schemas are sent to the model — a tool the caller may not use is absent, not refused (`visible_to()` precedent). `run_tool()` dispatches, times, and records the emitted record ids on the run |
| `services/atlas_tools.py` | `tool_list_lines`, `tool_cash_position`, `tool_forecast`, `tool_vendor_baseline`, `tool_doubts`, `tool_reconcile`, `tool_action_log`, `tool_memory_rules`, `tool_orientation`, `tool_ask_sage` | new | Ten thin adapters. Inventory in §3.2. None writes |
| `agents/atlas_agent.py` | `BriefingRun`, `run_briefing(db, ctx, grants, user_id)`, `_loop()`, `_budget` | new | The tool-calling loop on `AzureChatOpenAI.bind_tools`. Max 6 rounds, 12 invocations, 20 s wall clock; on any cap it emits what it has with a `truncated` event. Keeps the set of record ids every tool result emitted this run. Yields `BriefingEvent`s |
| `agents/atlas_prompts.py` | `BRIEFING_SYSTEM`, `briefing_user_prompt(role, grants, rules, today)`, `INTERVIEW_INSTRUCTION` | new | Prompt text only. Role, grants, memory rules, date. Explicitly instructs: cite every paragraph, never state a figure a tool did not render, ask at most one question and only about an ambiguous tool result. No rule that decides correctness lives here (hard rule 3) |
| `services/atlas_contract.py` | `Citation`, `BriefingParagraph`, `BriefingEvent`, `assert_paragraph_cited(paragraph, emitted_ids)`, `assert_briefing_no_undeclared_numbers(paragraph, rendered_figures)` | edit (additive) | The briefing wire contract and its two deterministic guards. A paragraph whose citations are empty or name a `record_id` not emitted this run is **dropped before the SSE frame**, logged, counted. A paragraph containing a numeric token not present in any rendered tool figure is dropped the same way (reuses `numeric_tokens()`) |
| `services/atlas_briefing_cache.py` | `get_cached(db, tenant_id, user_id, today)`, `store(db, run)`, `invalidate(db, tenant_id, user_id)` | new | Postgres cache keyed `(tenant_id, user_id, briefing_date)`. `invalidate()` is called by dismiss, act, memory add and interview answer. Regeneration happens only on the next `GET /atlas/briefing` |
| `models.py` | `AtlasBriefing` | edit (additive) | Table `atlas_briefings`: id, tenant_id, user_id, briefing_date, model, paragraphs JSONB, citations JSONB, question JSONB nullable, tool_calls JSONB, tokens_in, tokens_out, cost_usd, truncated bool, stale bool, created_at |
| `alembic/versions/<rev>_atlas_briefings.py` | `upgrade()` | new | Add-only migration, no backfill (dev-phase rule) |
| `routers/atlas.py` | `get_atlas_briefing()` at `GET /atlas/briefing` (SSE) · `post_atlas_briefing_answer()` at `POST /atlas/briefing/answer` | edit (additive) | SSE stream of `BriefingEvent`s from cache or a fresh run. Answer endpoint writes the interview answer as a memory rule via `atlas_memory.add_rule(source=RuleSource.INTERVIEW)` and invalidates the cache |
| `routers/atlas.py` | `dismiss_atlas_line()`, `act_on_atlas_line()`, `post_atlas_memory()` | edit (one line each) | Call `atlas_briefing_cache.invalidate()` after their existing work |
| `services/atlas_memory.py` | `RuleSource.INTERVIEW` | edit (additive) | New source value so an interview answer is distinguishable from a chat-derived or dismissal-derived rule |
| `utils/model_registry.py` | `resolve_model("atlas")` | edit (additive) | New role. Reads `AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME`, falls back to primary. Catalog entry for `gpt-5.6-terra` already exists |
| `config.py` | `AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME` | edit (additive) | Default empty; set to the Terra deployment name per environment |
| `utils/llm.py` | `MockInvoiceLLM.bind_tools()`, `MockInvoiceLLM._scripted_tool_calls` | edit (additive) | The mock has no tool-call surface today. Adds a scripted sequence so every test below runs without Azure |
| `routers/chat.py` | `run_sync_chat_turn()` | none | Called as a function by `tool_ask_sage`, exactly as `resolve_audit_invoice` is called in Feature 34 §17.3. Not modified |
| `tests/test_atlas_tools.py`, `tests/test_atlas_agent.py`, `tests/test_atlas_briefing_contract.py`, `tests/test_atlas_briefing_router.py` | — | new | §6 |

---

## 3. Functionality

### 3.1 The runtime path

1. **Open.** The FE opens `GET /atlas/briefing`. The router resolves `SkillContext` and
   `GrantSet` exactly as `get_atlas_lines()` does. If `tenant_has_history()` is false the router
   streams one `welcome` event carrying the role-based welcome text (§3.5) and `done`. No LLM call.
2. **Cache.** `get_cached()` looks up `(tenant_id, user_id, today)`. A row that exists and is not
   stale is replayed as SSE frames. Zero LLM cost.
3. **Run.** Otherwise `run_briefing()` starts. It builds the system prompt, the user prompt with
   the caller's role, grants, active memory rules and today's date, and the tool schema list from
   `tools_for(grants)`. It binds the tools to the Terra model resolved by `resolve_model("atlas")`.
4. **Loop.** Each round the model either calls tools or writes. Tool calls are dispatched through
   `run_tool()`, which serialises the result to JSON rows with record ids and adds those ids to the
   run's emitted set. The loop stops at 6 rounds, 12 invocations, 20 seconds, or when the model
   writes without calling. `tool_ask_sage` is dispatched at most once; a second request returns a
   refusal row, not an answer.
5. **Guard.** Every paragraph the model writes passes `assert_paragraph_cited()` against the
   emitted set and `assert_briefing_no_undeclared_numbers()` against the figures the tools
   rendered. A failing paragraph is dropped, logged with its citations, and counted on the run.
   Nothing the model says reaches the wire uncited.
6. **Question.** If the model emitted a question, it is validated the same way: it must cite the
   ambiguous tool result it is about. One question maximum; extras are dropped.
7. **Stream and store.** Surviving paragraphs stream as `paragraph` events, the question as
   `question`, then `done` (or `truncated` then `done`). The run is stored via `store()` with its
   tool call log, token counts and cost from `cost_usd()`.
8. **Later that day.** A dismiss, act, memory add or interview answer calls `invalidate()`, which
   sets `stale = true`. The screen is not refreshed. The next `GET /atlas/briefing` finds the stale
   row and runs again.

### 3.2 The tool inventory

Every tool is read-only, tenant-scoped through `SkillContext`, and returns JSON rows. Record ids
are what citations point at.

| tool | wraps | args | rows carry |
|---|---|---|---|
| `list_lines` | `atlas_lines()` → `rank()` → `drop_dismissed()` → `collapse()` | none | `Recommendation.id`, `what.entity_id`, capability, rendered figures |
| `cash_position` | `cash_position()` | none | per-currency position, the invoice ids summed |
| `forecast` | `shortfalls()`, `forecast_recommendations()` | none | shortfall date, amount, levers, invoice ids |
| `vendor_baseline` | `vendor_baseline()` | vendor, currency | range, count, invoice ids |
| `doubts` | `doubts_for_invoice()` | invoice_id | claim, witness, verdict |
| `reconcile` | `statement_lines_from_items()` + `reconcile()` | document_id, vendor | the five groups with invoice numbers and ids |
| `action_log` | `recent_actions()` | limit | action log row ids |
| `memory_rules` | `list_rules()` | none | rule ids, text, source |
| `orientation` | `orientation()` | none | parts. No ids; a paragraph citing only orientation is dropped, because orientation is not evidence |
| `ask_sage` | `run_sync_chat_turn()` | question | SAGE's answer, its generated SQL, the invoice ids it returned. Once per run |

Visibility: `list_lines` is already capability-filtered inside `atlas_lines()`. `cash_position`
and `forecast` are Admin-only. `reconcile`, `doubts`, `vendor_baseline` require `can_audit`.
`action_log`, `memory_rules`, `orientation`, `ask_sage` follow the caller's existing access to the
matching endpoints.

### 3.3 The briefing wire contract

Owned here, consumed by FE Feature 24. FE 24 references it and never restates it.

```
GET /api/v1/atlas/briefing                     Content-Type: text/event-stream

event: welcome     data: { "role": "auditor", "text": "..." }
event: paragraph   data: { "text": "...", "citations": [Citation, ...] }   citations non-empty
event: question    data: { "text": "...", "citations": [Citation], "answer_kind": "free_text" }
event: truncated   data: { "reason": "rounds" | "invocations" | "wall_clock" }
event: error       data: { "message": "..." }
event: done        data: { "cached": bool, "model": "gpt-5.6-terra", "dropped_paragraphs": n }

Citation { "tool": "list_lines", "record_kind": "recommendation" | "invoice" | "rule" | "action" | "shortfall" | "recon_row", "record_id": "..." }

POST /api/v1/atlas/briefing/answer   { "question_text": "...", "answer": "..." }  → 201 MemoryRuleOut
```

### 3.4 Model

Every ATLAS Intelligence call runs on **GPT-5.6 Terra** through the new `atlas` registry role.
SAGE, extraction, trainer and every other call site are untouched and stay on their current
deployments. The catalog note that Terra's deployment was deleted means the deployment must be
recreated before the first live run (§7, open decision 1).

### 3.5 Cold tenant

When the tenant has no history the briefing is a static welcome per role, from
`atlas_prompts.WELCOME_BY_ROLE`: what ATLAS will do for an Admin, an Auditor, a Trainer, a
Loader, in three sentences each. It carries no citations because it makes no claims. It is
replaced by a real briefing on the first open after history exists.

### 3.6 Cost

To be measured, not asserted. Estimate at Terra list price ($2 / $12 per 1M): about 30k input
tokens across rounds and 1.5k output per uncached run, roughly $0.08 per open, once per user per
day plus one regeneration per day of activity. Stored per run in `atlas_briefings.cost_usd` so
the real figure is on record from the first run.

---

## 4. Data & schema changes

One table, add-only migration, no backfill.

```
atlas_briefings
  id              uuid pk
  tenant_id       uuid, indexed
  user_id         uuid
  briefing_date   date
  model           text
  paragraphs      jsonb        -- surviving paragraphs with citations
  question        jsonb null
  tool_calls      jsonb        -- [{tool, args, ms, rows}]
  tokens_in       int
  tokens_out      int
  cost_usd        numeric(10,6)
  truncated       bool
  dropped         int          -- paragraphs the guard removed
  stale           bool default false
  created_at      timestamptz
  unique (tenant_id, user_id, briefing_date)
```

`atlas_memory_rules.source` gains the value `interview`. No column change.

---

## 5. Tasks

- **35.0** Terra deployment (infra-devops). Create the `gpt-5.6-terra` deployment on the dev Azure OpenAI account first, by CLI, so the first live run is unblocked; then codify it in `infra/model-deployment.bicep` (the existing per-model deployment module, not a new file), add `AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME` to the compute bicep modules, `.env.example`, `params.dev.json` / `params.prod.json`, and update `infra/README` and the cost table in `infra/monitoring/ai_control_tower_workbook.json` with Terra's price. Record capacity and price in the tracker.
- **35.1** `services/atlas_tools.py` — `ToolSpec`, registry, `tools_for(grants)`, `run_tool()`, and the ten adapters with record-id serialisers. `ask_sage` limited to one call per run inside `run_tool()`.
- **35.2** `MockInvoiceLLM.bind_tools()` with a scripted tool-call sequence, so the loop is testable without Azure. Blocks every later test.
- **35.3** `utils/model_registry.py` `atlas` role + `config.py` setting.
- **35.4** `agents/atlas_agent.py` — the loop with the three caps and the emitted-id set; `agents/atlas_prompts.py`.
- **35.5** `services/atlas_contract.py` — `Citation`, `BriefingParagraph`, `BriefingEvent`, the two guards.
- **35.6** `models.AtlasBriefing` + migration + `services/atlas_briefing_cache.py`.
- **35.7** `GET /atlas/briefing` SSE route: history check → welcome, cache replay, fresh run, store.
- **35.8** Cache invalidation hooks in dismiss, act, memory add.
- **35.9** Interview: question validation in the loop, `POST /atlas/briefing/answer`, `RuleSource.INTERVIEW`.
- **35.10** End-to-end on the VPI tenant, three roles, real Terra: cited-id set comparison, cost recorded.

---

## 6. Verification Plan

All DB and API checks run against real Postgres at `127.0.0.1:5433/invoice_db` (never
`localhost`, BE Gap 697), VPI tenant `00000000-0000-0000-0000-000000000000`, existing 26
invoices, no reseed, no rows left behind. Everything that decides correctness below is
deterministic code, never a prompt rule (hard rule 3): the guards, the grant filter, the caps, the
cache key, the single `ask_sage` limit.

| task | proof |
|---|---|
| 35.0 | `az cognitiveservices account deployment show` returns the Terra deployment; `az deployment group what-if` on the bicep shows no drift against it; `resolve_model("atlas")` on dev resolves to it |
| 35.1 | `tests/test_atlas_tools.py`: every adapter's rows carry `record_kind`, `record_id`, `tenant_id`, `as_of`; `tools_for()` for a Trainer's `GrantSet` omits `cash_position`, `forecast`, `reconcile` from the **schema list**, not merely refuses them; second `ask_sage` in one run returns a refusal row. Real Postgres |
| 35.2 | Mock `bind_tools()` replays a scripted sequence; a test asserts the loop's dispatch order matches |
| 35.3 | `resolve_model("atlas")` returns the Terra deployment when set, primary when blank; `registry_snapshot()` includes it |
| 35.4 | `tests/test_atlas_agent.py`: forced-loop fixture stops at 6 rounds and emits `truncated{rounds}`; 13th invocation stops with `truncated{invocations}`; a slow tool stub trips the wall clock; the emitted-id set equals the union of tool rows |
| 35.5 | `tests/test_atlas_briefing_contract.py`: uncited paragraph dropped; paragraph citing an id not emitted this run dropped; paragraph with a number absent from rendered figures dropped; paragraph citing only `orientation` dropped; `dropped` counter matches. Falsification per Feature 34 §18.8: remove the guard call, assert these go red |
| 35.6 | Migration `upgrade head` on Postgres; unique constraint holds; `invalidate()` sets `stale` |
| 35.7 | `tests/test_atlas_briefing_router.py`: cold tenant streams `welcome` + `done` with no LLM call (mock call count 0); warm tenant first call runs (count 1), second call same day replays (count still 1); different user same tenant runs again (count 2) |
| 35.8 | Dismiss, act, memory POST each flip `stale`; next GET re-runs |
| 35.9 | A scripted question with a valid citation streams as `question`; a second question is dropped; `POST /atlas/briefing/answer` creates a rule with `source = interview` and flips `stale` |
| 35.10 | Live run on VPI, real Terra, Admin / Auditor / Trainer. Evidence in `docs/test_evidence/atlas_intelligence_<date>/`: raw SSE frames, tool call log, the emitted-id set, the citation set, and the set comparison `citations ⊆ emitted`. Cost and token counts from the stored row. No LLM judge grades prose |

Full backend suite at the end of the feature only (checkpoint rule), not per task.

---

## 7. Open decisions

1. ~~Terra deployment.~~ **Ruled 2026-09-20:** deploy first inside this feature (task 35.0), then bicep and docs.
2. ~~Regeneration during a busy session.~~ **Ruled 2026-09-20:** accept for v1, no minimum interval; measure from `atlas_briefings` rows.
3. ~~What the briefing may say about other users.~~ **Ruled 2026-09-20:** prompt-only boundary accepted for v1 — outcomes yes, speed or surveillance never. `action_log` stays in the Admin registry.
4. ~~Ranking arithmetic.~~ **Resolved 2026-09-20:** the founder meant the Trainer skill's arithmetic re-check, filed as BE Gap 712 (remove `_arithmetic_correction()` from ATLAS; the pipeline's `sa_alerts` are the source). `list_lines` keeps `rank()` order.

---

## 8. Rulings record (2026-09-20)

| # | ruling |
|---|---|
| 1 | Cold tenant: welcome plus short role-based explanation, no citations |
| 2 | Caps 6 rounds / 12 invocations / 20 s are starting guesses to measure |
| 2b | Model: Terra for every ATLAS Intelligence call; nothing else changes model |
| 3 | `ask_sage`: one call per briefing |
| 4 | Cache invalidated on dismiss, act, interview answer; regenerated only on next open of the work screen; never in background |
| 5 | SAGE stays a separate agent, called as a tool |
| 6 | BE Gaps 707–711 deleted from the tracker; ids retired; new gaps from 712 |
| 7 | No Feature 36 (regulations feed, nightly learning). Not needed |
