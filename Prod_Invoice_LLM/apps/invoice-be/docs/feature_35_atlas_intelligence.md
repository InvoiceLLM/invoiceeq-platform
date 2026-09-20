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
| `services/atlas_tools.py` | `tool_list_lines`, `tool_invoices` (BE Gap 716), `tool_cash_position`, `tool_forecast`, `tool_vendor_baseline`, `tool_doubts`, `tool_reconcile`, `tool_action_log`, `tool_memory_rules`, `tool_orientation`, `tool_ask_sage` | new | Eleven thin adapters (ten, plus `invoices` from BE Gap 716 — see §12). Inventory in §3.2. None writes |
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

**Amendment 2026-09-20 — ruled Luna.** After Gaps 716–718 landed, the same three-role VPI
input was run on Terra, gpt-5-mini, Luna and GPT-6 Astra (Astra only reachable through the
v1 Responses endpoint the factory does not use). Luna covered every Admin item (4/4) and
every Auditor item (3/3), fastest, at ~$0.003 per open against Terra's ~$0.03 and Astra's
~$0.08 at list price; zero dropped or invented on all four. Founder: "Let's go with luna"
and "drop other for atlas admin". `AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME` = `gpt-5.6-luna` in
`params.dev.json` and `.env.example`; the Terra and Astra deployments are deleted. The
`atlas` role stays a separate role so the model can be changed per environment without
touching code. Evidence: this session's four-model runs (`out_*.json` in the session
scratchpad) and `docs/test_evidence/atlas_intelligence_2026-09-20/rerun_after_717_719/`.

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
| 2b | Model: Terra for every ATLAS Intelligence call; nothing else changes model. **Superseded same day: Luna** (see §3.4 amendment) |
| 3 | `ask_sage`: one call per briefing |
| 4 | Cache invalidated on dismiss, act, interview answer; regenerated only on next open of the work screen; never in background |
| 5 | SAGE stays a separate agent, called as a tool |
| 6 | BE Gaps 707–711 deleted from the tracker; ids retired; new gaps from 712 |
| 7 | No Feature 36 (regulations feed, nightly learning). Not needed |

---

## 9. As built — Track 1 (tasks 35.1–35.3), 2026-09-20

Additive record of what was actually built, including where it deviates from §2/§3.2 above.
Nothing in §1–§8 is rewritten (CONVENTIONS hard rule 4).

### 9.1 What landed

| file | what is in it |
|---|---|
| `services/atlas_tools.py` (new) | `BriefingRun`, `ToolContext`, `ToolResult`, `ToolSpec`, `TOOL_REGISTRY`, `tools_for()`, `tool_schemas()`, `run_tool()`, `emitted_ids_of()`, and the ten adapters `tool_list_lines`, `tool_cash_position`, `tool_forecast`, `tool_vendor_baseline`, `tool_doubts`, `tool_reconcile`, `tool_action_log`, `tool_memory_rules`, `tool_orientation`, `tool_ask_sage` |
| `utils/llm.py` (edit, additive) | `MockInvoiceLLM.tool_script`, `MockInvoiceLLM.SCRIPT_EXHAUSTED_TEXT`, `MockInvoiceLLM.bind_tools()`, and `_BoundMockLLM` |
| `utils/model_registry.py` (edit, additive) | `atlas` in `Role`, its branch in `resolve_model()`, and `atlas` in `registry_snapshot()` |
| `config.py` (edit, additive) | `AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME: str = ""` |
| `tests/test_atlas_tools.py`, `tests/test_atlas_mock_tools.py` (new) | §9.4 |
| `tests/test_model_registry.py` (edit, one line) | the pinned `Role` set in `test_there_is_no_long_doc_role_after_29_10` gained `atlas` |

### 9.2 Signatures, as built

* `run_tool(name, args, ctx, run)` — four arguments, not §2's three. The emitted-id set and the
  `ask_sage` budget both live on the run, and a dispatcher that cannot see the run cannot enforce
  either. `ctx` is a new `ToolContext(db, skill: SkillContext, grants: GrantSet, user_id,
  sage_session_id)` rather than a bare `SkillContext`: an adapter needs the session and the grants,
  and re-deriving grants inside a tool would make `tools_for()`'s filter decorative.
* `BriefingRun(tenant_id, user_id, emitted_ids: set[str], tool_calls: list[dict], sage_calls: int)`
  — defined here as §2 says task 35.4 will consume it. `tool_calls` entries are
  `{tool, args, ms, rows, refused}`, which is §4's column plus the refusal flag.
* Adapters are `(ctx, args) -> list[dict]`. Every row is built by one private `_row()` helper that
  writes the four identity fields **last**, so an adapter cannot shadow `record_id` by accident.
* `tools_for()` iterates `TOOL_REGISTRY.values()`, and `run_tool()` re-checks visibility through
  the same call, so the schema list the model was given and the dispatcher's own test can never
  disagree — and a hallucinated tool name reaches no service.

### 9.3 Deviations from §3.2, and why

1. **`cash_position` rows carry counts, not "the invoice ids summed".** `atlas_skills.CashPosition`
   returns `payable_count` / `receivable_count` and no ids. Re-querying the invoices in the adapter
   to manufacture ids would be new compute in a feature whose first rule is that it adds none, so
   the rows carry what the service produced. Consequence for task 35.5: a paragraph about cash
   cites `cash-<CURRENCY>`, not individual invoices.
2. **`vendor_baseline` rows carry the range and the count, not invoice ids** — same reason:
   `atlas_doubt.VendorBaseline` is `(vendor, currency, invoice_count, low, high, median)` by D39's
   compute-and-throw-away design.
3. **`list_lines` does not fold in forecast or doubt lines**, even though `GET /atlas/lines` adds
   both. Each has its own tool; a model given them from two places would cite one shortfall twice.
   The collapse rows §3.2 asks for are included, as `record_kind = "collapsed_area"` with the
   composed id `area-<capability>` (a collapsed area is not a stored row and has no id of its own).
4. **`ask_sage` is not write-free in the strictest sense.** `run_sync_chat_turn()` persists the
   chat turn it runs, so one `ChatSession` (titled "ATLAS briefing", reused per tenant+user) and
   two `ChatMessage` rows exist afterwards — exactly the rows a user asking SAGE the same question
   would create. No ATLAS-domain row is written: no dismissal, no action, no rule, no invoice
   change. Stated here rather than left to be discovered.
5. **`orientation` rows carry an empty `record_id`** and are therefore never added to
   `run.emitted_ids`. §3.2's "a paragraph citing only orientation is dropped" is then a property of
   the data rather than a prompt rule — task 35.5's guard drops it without knowing what orientation
   is.
6. **Refusals are rows, not exceptions.** An invisible or unknown tool, a missing required
   argument, a second `ask_sage`, or a wrapped service raising all produce a single
   `record_kind = "refusal"` row with an empty `record_id` and a populated `ToolResult.refused`.
   The loop keeps going; nothing about a refusal is citable.

### 9.4 Verification (real Postgres, `127.0.0.1:5433/invoice_db`, BE Gap 697)

| run | result |
|---|---|
| `tests/test_atlas_tools.py` | `21 passed in 7.75s` |
| `tests/test_atlas_mock_tools.py` | `9 passed in 6.93s` |
| `tests/test_model_registry.py tests/test_no_hardcoding.py` | `37 passed in 7.36s` |
| the eleven existing `tests/test_atlas_*.py` | `163 passed in 14.34s` |

What the tool tests pin, as properties rather than fixture echoes: the four identity fields on
every row of every tool, walked over `TOOL_REGISTRY` (plus a second test that gives the four
normally-empty tools — `forecast`, `reconcile`, `action_log`, `memory_rules` — real rows to find,
so the walk is not vacuous for them); JSON-serialisability; `run.emitted_ids` equalling the
non-empty ids; orientation's uncitable rows; a Trainer's **schema list** omitting `cash_position`,
`forecast`, `reconcile`, `doubts` and `vendor_baseline`; an Auditor's including the audit three but
not the Admin two; an invisible or invented tool name refused at dispatch; a missing argument and a
raising service each becoming a refusal row; the second `ask_sage` refused with the adapter
provably not re-run; and the per-dispatch log.

### 9.5 Not done in Track 1

Tasks 35.4–35.10 are untouched: there is no loop, no prompts module, no briefing contract guard,
no table, no route. `services/atlas_tools.py` has no caller in product code yet — it is imported
only by its tests. `resolve_model("atlas")` is live but nothing calls it.

BE Gap 713 was filed against `registry_snapshot()` (it omits the `chat_summary` role); it was
deliberately not fixed here.

---

## 10. As built — Track 2 (tasks 35.4–35.5), 2026-09-20

Additive record of the loop and the guards as they actually landed. Nothing in §1–§9 is
rewritten (CONVENTIONS hard rule 4).

### 10.1 What landed

| file | what is in it |
|---|---|
| `agents/atlas_agent.py` (new) | `run_briefing()`, `_loop()`, `_bind()`, `_parse()`, `_questions()`, `_citations()`, `_strip_fence()`, `_guarded()`, `_count_tokens()`, `_finish_accounting()`, `_rules_for()`, `_role_from()`, `_text_of()`, and the three caps `MAX_ROUNDS = 6` / `MAX_INVOCATIONS = 12` / `MAX_SECONDS = 20.0` |
| `agents/atlas_prompts.py` (new) | `BRIEFING_SYSTEM`, `OUTPUT_FORMAT`, `INTERVIEW_INSTRUCTION`, `briefing_user_prompt()`, `WELCOME_BY_ROLE`, `welcome_for()`, `_grant_words()` |
| `services/atlas_contract.py` (edit, additive) | `Citation`, `BriefingParagraph`, `BriefingQuestion`, `BriefingEventType`, `BriefingEvent`, `UncitedParagraphError`, `rendered_tokens_of()`, `assert_paragraph_cited()`, `assert_briefing_no_undeclared_numbers()`, `assert_paragraph_no_structure()`, `validate_briefing_paragraph()` |
| `services/atlas_tools.py` (edit, additive) | `BriefingRun` gains `rendered_tokens`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, `dropped`, `truncated`; `_record()` now fills `rendered_tokens` from every non-refused row |
| `tests/test_atlas_agent.py`, `tests/test_atlas_briefing_contract.py` (new) | §10.5 |

### 10.2 Signatures, as built

* `run_briefing(db, ctx, *, today, llm=None, role="", rules=None, run=None) -> Iterator[BriefingEvent]`
  — a **generator**, so task 35.7 can start an SSE response before the briefing finishes.
  Three optional keywords beyond §2's shape, each because the alternative was worse:
  `run` is how the caller that will persist the briefing (35.6) gets the token counts, cost,
  tool-call log and drop count back — a generator's return value is unreachable from a `for`
  loop; `role` and `rules` let a route pass what it has already resolved instead of this module
  re-reading it, and when they are omitted the role is derived from `ctx.grants` and the rules are
  read from `db`. `db` is used for exactly that one read; everything else goes through `ctx`.
* The three caps are module constants, not arguments: §8 ruling 2 calls them starting numbers to
  be measured, and a number that can be overridden per call is not one that gets measured.
* `validate_briefing_paragraph(item, emitted_ids, rendered_figures)` is the single entry point the
  loop calls, mirroring `validate_recommendation()`. It runs the citation check, the structure
  check and the number check, in that order, and is used unchanged for the question.

### 10.3 Decisions and deviations

1. **JSON parsed deterministically, not `with_structured_output()`.** §2/35.4 allowed either.
   The wrapper does not compose with `bind_tools()` here (and `MockInvoiceLLM`'s version of it
   bypasses the bound tool surface entirely), so the loop asks for the small object in
   `OUTPUT_FORMAT` and parses it itself. Unparseable output produces **zero paragraphs and an
   `error` event** — never a fallback that writes prose, because a fallback that writes sentences
   about money is the failure this feature exists to prevent. A markdown fence is tolerated
   (stripped); nothing else is salvaged.
2. **`truncated` is emitted before the surviving text**, per the track-2 brief, where §3.3's
   table lists it after the paragraphs. A reader learns the briefing is partial before reading it
   rather than after. In practice a cap fires with no text yet written, so the frame order the FE
   sees is `truncated`, `done`.
3. **The number guard is stricter than the line-level one.** `assert_no_undeclared_numbers()`
   tests only money-shaped tokens, because a skill composed its "12 days" in code.
   `assert_briefing_no_undeclared_numbers()` tests **every** numeric token, because the writer is
   a model and the founder's rule for it is absolute: no arithmetic, no number a tool did not
   render. A count read off a row passes; a count the model worked out does not.
4. **`run.rendered_tokens` is built in `run_tool()`, not in the loop** (spec §2 did not say where).
   It is `BriefingRun`'s second set and the exact companion of `emitted_ids`: that one decides what
   may be *cited*, this one decides what may be *stated*. `rendered_tokens_of()` walks a row
   recursively (a line's amounts live inside `figures`, a reconciliation's inside its groups) and
   **excludes ids and timestamps** — a UUID is full of digit runs, and letting them declare numbers
   would make the guard satisfiable by noise, which is the mistake BE Gap 704 records. Refusal rows
   contribute nothing: a refusal explains, it does not license a number.
5. **Orientation-only citations are rejected twice over.** Orientation rows carry no id, so they
   already fail the membership rule; the explicit all-orientation check is kept so the rule
   survives orientation ever gaining one. Orientation *alongside* real evidence is allowed.
6. **Extra questions are counted as drops.** A model that answers with a list of questions has one
   kept and the rest dropped onto `run.dropped`, which is what the `done` event reports — from the
   user's side an extra question that never arrives is the same event as a dropped paragraph.
7. **`ask_sage` persisting chat rows is ACCEPTED as-is** (founder ruling 2026-09-20), confirming
   §9.3 deviation 4. One `ChatSession` titled "ATLAS briefing" per tenant+user and two
   `ChatMessage` rows per briefing that asks SAGE something — the same rows the user would have
   created by asking the question themselves. No ATLAS-domain row is written by any tool.
8. **Prompt text holds no correctness rule.** `agents/atlas_prompts.py` states the cite-everything,
   no-arithmetic and one-question rules because a model told them produces prose the guards mostly
   pass; the guards decide correctness whether it obeyed or not (hard rule 3). The module docstring
   says exactly that, so the next reader does not mistake the instructions for controls.

### 10.4 Not done in Track 2

Tasks 35.6–35.10 are untouched: no `AtlasBriefing` table, no migration, no cache, no route, no
`POST /atlas/briefing/answer`, no `RuleSource.INTERVIEW`. `run_briefing()` has no caller in
product code yet — it is imported only by its tests. `WELCOME_BY_ROLE` exists but nothing streams
a `welcome` event; that is 35.7's history check.

### 10.5 Verification (real Postgres, `127.0.0.1:5433/invoice_db`, BE Gap 697)

| run | result |
|---|---|
| `tests/test_atlas_agent.py` | `19 passed in 9.38s` |
| `tests/test_atlas_briefing_contract.py` | `20 passed in 8.73s` |
| `tests/test_atlas_agent.py` + `test_atlas_briefing_contract.py` + `test_atlas_mock_tools.py` + `test_no_hardcoding.py` + `test_model_registry.py` | `85 passed in 11.91s` |
| all `tests/test_atlas_*.py` | `230 passed, 2 failed in 32.10s` — both failures are `tests/test_atlas_tools.py`'s two identity walks, filed as **BE Gap 714** (a random vendor-name suffix containing four consecutive digits makes a Feature 34 line unconstructable). Pre-existing and unrelated to track 2: the raise is inside `atlas_lines()`, on a code path this track did not touch. Not fixed here |

What the agent tests pin, as properties rather than fixture echoes: the loop invokes exactly six
times and emits `truncated{rounds}` against a script that never stops calling; the twelfth tool
call runs and the thirteenth does not, asserted on the dispatch log itself, with the cap falling
*mid-round* so a per-round check would not pass; a sleeping adapter trips `truncated{wall_clock}`
inside a single round and the next round never starts; `run.emitted_ids` and `run.rendered_tokens`
equal what a second independent dispatch of the same tools produced; the model, token counts and
cost are recorded consistently; a Trainer's bound schema list omits the Admin tools; a correctly
cited paragraph reaches the wire and an uncited, an unknown-id, an invented-number and an
orientation-only paragraph do not, each counted on `dropped` and reported by `done`; only the
first question survives; prose instead of JSON produces an `error` and no paragraphs.

The falsification test is the one that makes the rest evidence: with
`agents.atlas_agent.validate_briefing_paragraph` patched to a no-op, the uncited invented-number
paragraph **leaks to the wire** and `dropped` stays zero. The guard is therefore load-bearing
rather than decorative (Feature 34 §18.8's precedent). The contract tests add the rules one at a
time, plus two Postgres properties: a real `list_lines` run declares the figures its own rows
rendered (stated without naming an expected number — the rendered figure passes, the same figure
with a digit appended does not), and a refused call declares neither an id nor a token.

---

## 11. As built — Track 3 (tasks 35.6–35.9), 2026-09-20

Additive record of the table, the cache, the SSE route and the interview as they actually
landed. Nothing in §1–§10 is rewritten (CONVENTIONS hard rule 4).

### 11.1 What landed

| file | what is in it |
|---|---|
| `models.py` (edit, additive) | `AtlasBriefing` — table `atlas_briefings`, §4's columns, unique `(tenant_id, user_id, briefing_date)` plus `idx_atlas_briefing_tenant_user_date` |
| `alembic/versions/d6e7f8a9b0c1_atlas_briefings.py` (new) | add-only `upgrade()` on head `c5d6e7f8a9b0`; applied, `alembic current` → `d6e7f8a9b0c1 (head)` |
| `services/atlas_briefing_cache.py` (new) | `get_cached()`, `store()`, `invalidate()`, `replay_events()`, `_payload_from()` |
| `routers/atlas.py` (edit, additive) | `get_atlas_briefing()` at `GET /atlas/briefing`, `_briefing_frames()`, `_frame()`, `_briefing_role()`, `BriefingAnswerRequest`, `_interview_rule_text()`, `post_atlas_briefing_answer()` at `POST /atlas/briefing/answer`; one `invalidate_briefing()` line each in `dismiss_atlas_line()`, `act_on_atlas_line()` and `post_atlas_memory()` |
| `services/atlas_memory.py` (edit, additive) | `RuleSource.INTERVIEW = "interview"`, added to `RuleSource.ALL` |
| `tests/test_atlas_briefing_cache.py`, `tests/test_atlas_briefing_router.py` (new) | §11.5 |

### 11.2 Signatures, as built

* `get_cached(db, tenant_id, user_id, today)` — §2's shape. Returns the row **including** a
  stale one; the route tests `row.stale` itself, so the rule that stale means re-run is visible
  where it is applied rather than buried in the lookup. A `get_cached()` that hid stale rows
  would also make `store()`'s upsert unreachable.
* `store(db, run, events, *, today)` — three arguments plus the date, not §2's `store(db, run)`.
  The extra one is the point: `events` is the list of `BriefingEvent`s the **route actually
  streamed**, so tomorrow's replay is what the browser saw today. Taking the paragraphs from the
  model's parsed answer instead would let a guarded-out paragraph reappear on the second open,
  which would make the cache a way round `validate_briefing_paragraph()`. `today` is passed
  rather than read from the clock so the route's `today` and the cache's are the same value.
* `invalidate(db, tenant_id, user_id, *, today=None)` — returns `bool`, whether a row was
  flipped. "Nothing to invalidate" is the ordinary case for a user who has not opened the
  briefing today, so it is a return value and not an exception.
* `replay_events(row)` — added beyond §2. It is `_payload_from()`'s inverse and lives beside it
  so the two halves of the round trip are one file. It does **not** emit `done`: only the route
  knows `cached: true` (§3.3).
* `get_atlas_briefing()` is a **synchronous** `def` returning `StreamingResponse` over a
  synchronous generator, which Starlette iterates in a worker thread. `run_briefing()` blocks —
  the model call and every tool dispatch are synchronous SQLAlchemy and HTTP work — and an
  `async def` would run all of it on the event loop. That is BE Gap 602's defect exactly, where
  one blocking read per iteration in the chat stream stalled every other request in the process.

### 11.3 Decisions and deviations

1. **Four paths, ordered cheapest-first, and two of them never touch a model.** An ungranted
   caller (D3) is answered before the history query; a tenant with no invoices is answered
   before the cache lookup. Both stream `welcome` + `done` and **store nothing** — a stored
   welcome would make a cold tenant look briefed, and `atlas_briefings` is also the cost record
   (§3.6), so a free run in it would corrupt the per-open figure the spec says to measure.
2. **`_briefing_role()` duplicates `agents.atlas_agent._role_from()` rather than importing it.**
   The welcome path must work without the agent module being involved at all, and importing a
   private name across a module boundary is worse than four lines. The duplicate is kept honest
   by a parametrised test that asserts the two functions agree on all five ladder rungs — by
   test, not by import.
3. **The route owns the `done` frame; the agent's is dropped.** `run_briefing()` yields its own
   `done` because it is usable on its own, but only the route knows whether the answer came from
   a cache. The route filters the agent's out and emits one with `cached`, `model` and
   `dropped_paragraphs` (§3.3's three fields, exactly — asserted as a set, so a fourth field
   appearing is a failing test rather than an FE surprise).
4. **The whole stream is inside one `try`, and a failure ends with `error` then `done`.** An SSE
   response's headers are on the wire the moment the first frame is yielded, so an exception
   after that point is not a 500 — it is a stream that stops, which the FE cannot distinguish
   from a briefing that finished. Feature 34 §15.6 (BE Gap 692) is the precedent for what an
   unguarded raise costs on a response path: it took out the whole screen. Here the blast radius
   is the briefing panel.
5. **A storage failure does not truncate a briefing the user already has.** `store()` is called
   after the last content frame, inside its own `try`, and a failure is logged. The alternative —
   letting it propagate — would replace a delivered briefing with an `error` frame appended to it.
6. **Stale rather than delete, for three reasons** (`services/atlas_briefing_cache.py`'s
   docstring states them): "has this user been briefed today" stays answerable; the row is the
   cost record §3.6 says to measure from; and `tool_calls` is the sample §8 ruling 2's caps
   (6 / 12 / 20 s) get tuned against. Deleting superseded runs would throw most of that away.
7. **`store()` upserts on the day's row rather than inserting a second one**, so a regeneration
   keeps `created_at` as the day's first briefing and `stale` is set back to `False` explicitly —
   on the regeneration path the row being written is the stale one that caused it.
8. **The unique constraint is enforced by the database, not by `store()`'s read-then-write.**
   Two tabs opened at the same moment is the ordinary case, and the test asserts it by inserting
   a colliding row **directly**, so the test still fails if the constraint were dropped and the
   check moved into application code.
9. **`RuleSource.INTERVIEW` is a fifth value, not a reuse of `TOLD`** (task 35.9, additive; the
   four existing values are untouched). An interview answer is a lesson the user gave, but they
   gave it because ATLAS asked, about one ambiguous tool result. Folding it into `TOLD` would
   lose the only thing that makes the briefing's one question worth asking: whether answers to it
   turn out to be better or worse lessons than the ones people volunteer.
10. **The interview question is NOT re-validated at `POST /atlas/briefing/answer`, deliberately.**
    Confirmed against track 2's code rather than assumed: `agents/atlas_agent.py::_guarded()`
    runs `validate_briefing_paragraph()` over the question exactly as over a paragraph, and a
    question that cited nothing, cited an id no tool emitted, or stated an undeclared number
    never reached the browser and cannot be answered. Re-checking it at the answer endpoint would
    need the run's emitted-id set, which is gone by the time the user types, and would mean
    re-implementing the guard against a weaker input — one control becoming two that disagree.
    The task brief asked for this to be confirmed and not duplicated; it is.
11. **The stored lesson keeps both halves verbatim** — `"<question> — <answer>"`. Neither is
    paraphrased, for `report_missed()`'s reason (§7.2): the sentence is the evidence, and an
    answer without its question is unjudgeable six weeks later ("yes, always" means nothing on
    its own).
12. **`source` is fixed to `interview` server-side and is not a request field**, mirroring
    `POST /atlas/memory` fixing `told`: a client that could name its own provenance could label a
    lesson it invented as one the user gave.
13. **Invalidation on `act` fires only on success.** A refused or failed action changed nothing
    for the briefing to be stale about, and marking it stale anyway would buy a fresh Terra run
    every time somebody clicked a button that did not work.

### 11.4 Not done in Track 3

Task 35.10 (the live end-to-end on the VPI tenant against real Terra, with the cited-id set
comparison and the recorded cost) is untouched, and so is the whole of FE Feature 24. **No call
has been made to the real Terra deployment by any code in this feature** — every test here
injects `MockInvoiceLLM` through `routers.atlas.get_llm_for_role`. §3.6's cost figure therefore
remains an estimate; `atlas_briefings.cost_usd` is populated from `run.cost_usd` and is real as
soon as the first live run happens.

### 11.5 Verification (real Postgres, `127.0.0.1:5433/invoice_db`, BE Gap 697)

| run | result |
|---|---|
| `alembic upgrade head` then `alembic current` | `d6e7f8a9b0c1 (head)` |
| `tests/test_atlas_briefing_cache.py` | `13 passed in 8.74s` |
| `tests/test_atlas_briefing_router.py` | `23 passed` |
| all `tests/test_atlas_*.py` + `test_no_hardcoding.py` + `test_model_registry.py` | `312 passed in 24.67s` |

What the new tests pin, as properties rather than fixture echoes. **The model is injected by
replacing `routers.atlas.get_llm_for_role` with a counting factory**, so §6's "mock call count 0
/ 1 / still 1" is asserted on the count itself — a cache tested by reading the cache would pass
with the cache bypassed. A cold tenant and an ungranted caller each stream `welcome` + `done`
with **zero** factory calls and leave no row; the four role welcomes differ and carry no
citations; a warm tenant's first open calls the factory once, with role `"atlas"`, and writes a
row whose paragraphs carry the citing record id and whose `tool_calls` log is non-empty; the
second open the same day replays the **same paragraph payloads** with `cached: true` and the
count unchanged; a second user in the same tenant runs again; the frames are named SSE events in
§3.3's shape and `done` carries exactly the three documented fields; an uncited paragraph is
dropped at the HTTP boundary, counted on `dropped_paragraphs`, and is absent from the stored row
so the cache cannot resurrect it; the one question streams with its citation, a second is dropped
and counted, and the replay asks the same question; dismiss, act, memory-add and the interview
answer each flip `stale` through the **real** endpoints and the next open calls the factory a
second time; the answer endpoint writes `source = "interview"` with both halves of the sentence
intact and the rule is readable on `GET /atlas/memory`; a model that raises on `bind_tools()`
yields `error` then `done`, returns 200, and stores nothing; a tool that raises becomes a refusal
row and the briefing still finishes with a cited paragraph and no `error` frame.

The cache tests add the database-level properties: every §4 column round-trips through JSONB
(citations survive as structure, not as a string); only paragraphs and the question are stored,
never an `error` frame; a second run the same day reuses the day's row and keeps its
`created_at`; the unique constraint is asserted by direct insert; two users in one tenant get two
rows; yesterday's briefing is not today's; `invalidate()` sets `stale`, does not delete, is
idempotent, reports whether it changed anything, and does not touch another user's row; storing
again clears `stale`; and a replay reproduces the streamed frames — with a `truncated` frame
first, per track 2's ordering decision, on the cached path exactly as on a fresh run.

### 11.6 Track-3 checkpoint — the full backend suite

`pytest tests -q -p no:cacheprovider` on real Postgres (`invoice_db` for `DATABASE_URL`, a
freshly recreated `chat_test` for `TEST_DATABASE_URL` per the verify-postgres skill §3b):

```
69 failed, 4931 passed, 9 skipped, 5 deselected in 1194.76s (0:19:54)
```

**Zero of the 69 is this feature's.** The tracker's cited baseline (BE Gap 699's "11
pre-existing failures") is stale, so the comparison was made by measurement instead: the same
command, the same two databases and the same `.env` were run against a throwaway `git worktree`
of clean master `ca71223` — the commit *before* any of tracks 1–3 exists — which produced
`69 failed, 4818 passed, 9 skipped, 5 deselected in 901.08s`. The two sorted `FAILED` name lists
are **byte-identical** (`comm` in both directions returns nothing); the only difference is +113
passing tests, which are tracks 1–3's own. The worktree was removed afterwards; the working tree
was never reverted, stashed or reset.

Two modules do not collect at all and were `--ignore`d on **both** runs, so the comparison is
like-for-like: `tests/test_gap674_freight_verification.py` (`cannot import name 'ChargeItem'`)
and `tests/test_gap676_diagnostic_retry.py` (`cannot import name 'RETRY_DIAGNOSTIC_GUIDANCE'`),
both against `agents/extraction_agent.py`, both committed and unmodified here.

The stale baseline, the 69, and the two collection errors are filed together as **BE Gap 715**
(measurement only, deliberately not fixed here). The largest block in it —
`tests/test_telemetry.py`, 40 of the 69 — passes 64/64 in isolation and still passes 64/64 when
run immediately after both new Feature 35 suites, so the pollution is not this feature's either.


---

## 12. Amendment — BE Gap 716 (2026-09-20): the invoice's own record reaches the model

Additive. §3.2's inventory gains one tool and one row change, §3.1's runtime path gains a
pre-fetch step, and nothing above is rewritten.

### 12.1 What the first live run showed

The first real Terra briefing on the VPI tenant (`00000000-0000-0000-0000-000000000000`, Admin,
2026-09-20) wrote about RAJ-2009 and NAT-2007 without ever using the word *duplicate*, although
both invoices carry the pipeline's `possible_duplicate` alert and the Feature 34 line about each
carries that alert's message in `Why.doubt`. VPI-OUT-2014 — outbound, NEEDS_REVIEW, the tenant's
only arithmetic defect — appeared nowhere, and the Admin's model never called `forecast`.

Three separate causes, one class: **what the pipeline already recorded on the invoice never
reached the model.**

1. `tool_list_lines()` emitted the ranked opinion about a line and dropped `why.doubt`; nothing
   in any row carried `sa_alerts` at all.
2. No adapter read an `Invoice` row. `_approval_lines()` is inbound-only, and `forecast` carries
   outbound ids inside a *field* rather than as `record_id`, so an outbound invoice was not
   merely unmentioned — it was uncitable, because its id never entered `run.emitted_ids`.
3. Tool selection was the model's problem. A model that finds the work screen full stops there,
   and the four Admin needs (F34 §2.3) cannot be answered from one tool's rows.

### 12.2 What changed

| change | where | note |
|---|---|---|
| `list_lines` rows gain `doubt` and `alerts` | `services/atlas_tools.py::tool_list_lines()`, `_alerts_by_invoice()` | `why.doubt` verbatim; `alerts` are the invoice's `sa_alerts` messages through `atlas_skills._alert_prose()`, verbatim, and `[]` for a line whose entity is not an invoice |
| new tool `invoices` | `tool_invoices()`, `TOOL_REGISTRY` | one row per live invoice, inbound **and** outbound: `invoice_number`, `party` (vendor or customer), `flow`, `invoice_date`, `due_date`, `amount` (rendered by `atlas_figures`, `None` when there is no total), `currency`, `status`, `alerts`, `low_confidence_fields`. `record_kind="invoice"`, `record_id=<invoice id>`. Read-only, no arithmetic |
| visibility for `invoices` | `AtlasCapability.AUDIT` | the whole ledger is the audit surface, so `can_audit` and Admin see it; a Trainer or Loader is never told it exists (§3.2's absent-not-refused) |
| role pre-fetch | `agents/atlas_agent.py::_PREFETCH`, `_prefetch()`, `_prefetch_block()` | Admin `list_lines` + `invoices` + `cash_position` + `forecast`; Auditor `list_lines` + `invoices`; Trainer/Loader (and any unmapped role) `list_lines`. Dispatched through `run_tool()` before the first model call, so visibility is re-checked, the ids land in `emitted_ids`, the figures in `rendered_tokens`, and each call is logged on `run.tool_calls` |
| the pre-fetch counts | `_loop(..., invocations=len(prefetched))` | `MAX_INVOCATIONS = 12` is the whole briefing's budget, not twelve on top of four |
| one prompt sentence | `agents/atlas_prompts.py::BRIEFING_SYSTEM` | "a row's `alerts`/`doubt` is what the system already concluded, and it is the headline for that invoice" — guidance only; the guards remain the control (hard rule 3) |

**The rows are handed over as a context message, not as `ToolMessage`s.** A tool message must
answer an assistant message that asked for it; synthesising an assistant turn so the shape
typechecks would put words into the model's own history that it never said, and Azure rejects a
`tool` role with no preceding `tool_calls`. The block names each tool and carries its rows as the
same JSON a tool call would have returned, and says they may be cited.

**Boundary — what this does not handle.** `invoices` has no `limit` and no filter: a tenant with
thousands of live invoices puts all of them in one context window. A silently truncated ledger is
worse than a slow one, so the bound to add when such a tenant exists is a filter the model states
(flow, status, a date range), not a cut-off it cannot see. The fix also does not give ATLAS any
new judgement: an alert is repeated, never re-derived, and `M3`, `M4` and `M11` in
`atlas_admin_vpi_expected.md` remain **NO TOOL TODAY**.

### 12.3 Verification (real Postgres, `127.0.0.1:5433/invoice_db`, BE Gap 697)

| command | result |
|---|---|
| `pytest tests/test_atlas_tools.py tests/test_atlas_agent.py -q` | `52 passed in 15.42s` (12 new: 7 on the tools, 5 on the loop) |
| `pytest tests/test_atlas_*.py tests/test_no_hardcoding.py -q` | `291 passed in 49.39s` |
| falsification — `doubt`/`alerts` stubbed back out of `tool_list_lines` | `1 failed, 51 passed`; the alert test fails on the verbatim message |
| falsification — `prefetched = []` in `run_briefing()` | `7 failed, 17 passed` in `test_atlas_agent.py`, including the three existing tests whose counts the pre-fetch changes |

Two existing tests were updated rather than left asserting the old shape, and both say why in
their docstring: `test_the_emitted_set_is_the_union_of_the_rows_the_tools_returned` now includes
the pre-fetched tools in its independent dispatch (they go through `run_tool()`, so they are part
of what the loop recorded), and `test_a_slow_tool_trips_the_wall_clock` runs as a Trainer with a
0.5 s budget, because the wall clock is measured from before the pre-fetch and a 0.05 s budget
would have been a test of how fast this machine reads three invoices.

### 12.4 The same input, run again (founder: "after fix run the same input again")

VPI tenant, Admin, real `gpt-5.6-terra`, real Postgres, `as_of` 2026-09-15 — the anchor
`atlas_admin_vpi_expected.md` grades against. Four paragraphs, **0 dropped**, 8,046 in / 673 out,
**$0.024168**, no truncation. `run.tool_calls` = `list_lines` (7 rows), `invoices` (26 rows),
`cash_position` (1 row), `forecast` (0 rows) — all four pre-fetched, and the model chose to call
nothing further.

> "Possible duplicate: Rajesh Steel Corporation invoice RAJ-2008 has the same date and total
> (437,190.00) but a different number (RAJ-2009). Check whether this is a re-issue. RAJ-2009 is
> waiting on a decision for ₹4,37,190.00, due 15 September."
> — cites `audit-approve-530bd65a-be04-4953-988b-2932f52a6f89`
>
> "Possible duplicate: National MRO Traders invoice NAT-2006 has the same date and total
> (79,956.80) but a different number (NAT-2007). … due 15 September."
> — cites `audit-approve-22490a93-94a8-4511-90ba-52d495e0cc05`
>
> "Vishwa Precision Industries Pvt Ltd invoice VPI-OUT-2014 needs review: Subtotal (409500.00) +
> Tax (73710.00) does not match Grand Total (483850.00). It is due 17 September."
> — cites `invoices` / `13d719a7-c53f-4204-95fc-79f5b73959ba`

Against the ground truth: **M1 and M2 now MATCH** (M2 was previously unreachable by any tool, and
is cited through `invoices`), M10 is PARTIAL (three of the four low-confidence fields named).
Every figure in the VPI-OUT-2014 paragraph is inside the alert's own message, copied out of
`sa_alerts` — no paragraph was dropped, so no number in the run was one a tool had not rendered.
`forecast` returned no rows on this tenant (`bank_statement_line` is empty, so there is no
balance to go short against), which is why M5 is still absent; that is §3 item 6 behaving
correctly, not a regression.


---

## 13. Amendment — BE Gaps 717/718/719 (2026-09-20): the invariants stop depending on the model

Additive. §3.1's runtime path gains two deterministic steps after the guards, §3.2's row shape
gains one field, and §3.1 step 8's invalidation list gains three write sites. Nothing above is
rewritten, and no prompt rule was demoted — §3.5's prompt still says all of this; it now decides
yield rather than correctness (CONVENTIONS hard rule 3).

### 13.1 What the 2026-09-20 live run showed

Six real Terra briefings on the VPI tenant (`docs/test_evidence/atlas_intelligence_2026-09-20/`)
found three things the build could not guarantee:

1. **A flagged invoice can simply go unmentioned.** BE Gap 716 put the pipeline's alert on the
   row; whether the model writes about it was still the model's choice, and on several runs
   VPI-OUT-2014 — the tenant's only arithmetic defect — was left out. Worse in the other
   direction: `sa_alerts` is never cleared, so a **PAID** invoice's historical alert text read
   exactly like an open finding.
2. **The interview never fired.** Zero questions across six runs, with RAJ-2009 vs RAJ-2008 open
   and unresolved in every one. §3.1 step 6 describes a question; nothing made one happen.
3. **A grant change did not date the briefing.** Dismiss, act, memory-add and the interview
   answer all invalidate; changing somebody's role or `can_*` flags — which changes the tool
   schema, the pre-fetch table and the role word the prompt states — did not.

### 13.2 What changed

| change | where | note |
|---|---|---|
| `alert_is_open(status)` + `_ALERT_OPEN_STATUSES` | `services/atlas_skills.py` | the single source. Built as `_AWAITING_AUDIT + ("NEEDS_REVIEW", "NEEDS_RESUBMISSION")` — the inbound auditor queue plus the outbound review queue — deliberately **not** `_OPEN_PAYABLE`/`_OPEN_RECEIVABLE`, which answer "is this money still moving" and include `COMPLETED`/`VERIFIED`/`SENT` |
| `alert_open: bool` on every row | `services/atlas_tools.py::tool_invoices()`, `tool_list_lines()`, `_alerts_by_invoice()` | the alert **text is still carried whatever the status** — provenance is never hidden — and this flag is what says whether anybody still owes a decision. `False` for a line whose entity is not an invoice, and for an invoice with no alert |
| appended paragraph for an uncited open alert | `agents/atlas_agent.py::_uncited_open_alerts()`, `_flagged_rows()`, `_headline_of()`, `_is_dismissed()`, `_dismissed_for()`, `_cited_ids()` | after the model's paragraphs pass the guards: any pre-fetched row with `alert_open=true`, not dismissed by this caller, and cited by **no** surviving paragraph, gets one paragraph built from that row's own strings (party + number, or the line's headline, then the verbatim alert message), cited to that row. One per **invoice**, not per row — an Admin sees the same invoice as a line and as an `invoices` row, and a paragraph citing either form suppresses the append |
| deterministic interview question | `agents/atlas_agent.py::_duplicate_question()`, `_DUPLICATE_ALERT_RE` | only when the model asked none, only from an open duplicate alert whose sentence names both numbers, and only when **no active memory rule mentions either number**. One per briefing. `answer_kind: free_text`, cited to the row it was built from. The answer path is unchanged (`POST /atlas/briefing/answer` → memory rule) |
| the rules are read once | `agents/atlas_agent.py::run_briefing()` | `rule_texts` is computed once and used by both the prompt and the question's memory test, so the two halves of one briefing cannot disagree about what this workspace has been taught |
| invalidate on a grant change | `routers/admin.py::set_user_permissions()`, `routers/admin.py::remove_tenant_user()`, `dependencies.py::get_tenant_context()` (the Clerk `org_role` sync branch) | §8 ruling 4 holds: mark stale, never regenerate. The `dependencies.py` call is local-imported and wrapped — a stale briefing must never fail an ordinary request |

**Both appended paths go through `_guarded()`**, the same entry point a model paragraph goes
through. An appended paragraph that somehow named an unemitted id or an unrendered number would
be dropped and counted exactly as the model's would — this file trusts its own output no more
than it trusts Terra's. In practice it cannot: every string it uses came out of a row
`run_tool()` already recorded in `emitted_ids` and `rendered_tokens`.

**Why the duplicate sentence is parsed rather than recomputed.** `_DUPLICATE_ALERT_RE` matches
the one producer's sentence (`queue_worker/handlers.py::handle_process_invoice`, Gap 503) and
reads the party and the two invoice numbers back out of it. A message it does not match produces
**no question at all**: ATLAS asks a question it can ground in the pipeline's own words, or it
asks nothing. Nothing is re-derived from the invoice rows, and no pair is inferred.

**Known interaction, stated rather than discovered later.** A Trainer's low-confidence line for
RAJ-2009 carries that invoice's alert (BE Gap 716's row change) and `alert_open` is true on it,
so the guarantee and the question both fire for a Trainer, on a duplicate they cannot act on.
Whether Gap 716's row should carry an invoice's alert for a caller who cannot act on it is a
design question about that row; it is recorded in
`test_evidence/atlas_intelligence_2026-09-20/rerun_after_717_719/grading_trainer.md` and was not
changed here.

### 13.3 The three grant write sites, listed (BE Gap 719)

Found by grepping every assignment to `role` / `can_train` / `can_audit` / `can_load` /
`can_send_invoices` outside `tests/`:

| site | what it writes | invalidated |
|---|---|---|
| `routers/admin.py::set_user_permissions()` | `can_train`, `can_audit`, `can_load`, `can_send_invoices` (and creates the row with `RoleMapper.NO_ROLE` on the pre-provisioning path) | yes, for `user.clerk_user_id` in `context.tenant_id` |
| `routers/admin.py::remove_tenant_user()` | on the detach path: all three flags to `False`, `role` to `RoleMapper.NO_ROLE`, `tenant_id` to `None` | yes, keyed on `context.tenant_id` — the tenant the briefing row was written under, which is no longer on the `users` row after the detach |
| `dependencies.py::get_tenant_context()` | `user.role`, synced from a Clerk `org_role` claim when the org matches (Gap 157/173's guarded branch) | yes, only when the role actually changed and the user has a tenant |
| `routers/auth.py` (signup) | creates a row with `role="Admin"` | n/a — a user being created has no briefing to date |

### 13.4 Verification (real Postgres, `127.0.0.1:5433/invoice_db`, BE Gap 697)

| command | result |
|---|---|
| `pytest tests/test_atlas_tools.py -q` | `31 passed in 12.01s` (3 new: the open flag on an `invoices` row, on an outbound NEEDS_REVIEW row, and on a `list_lines` row) |
| `pytest tests/test_atlas_agent.py -q` | `33 passed in 12.82s` (10 new: 5 on the append, 4 on the question, 1 on the Trainer's single tool) |
| `pytest tests/test_atlas_briefing_router.py -q -k "permissions or removing_a_user"` | `2 passed in 14.12s` — both driven through the **real** Admin endpoints |
| all `tests/test_atlas_*.py` + `tests/test_no_hardcoding.py` | `305 passed in 29.63s` |
| `pytest tests/test_rbac.py tests/test_dependency_spans.py -q` | `60 passed in 100.08s` — the two suites over the routers and dependency this change edits |
| falsification — `_uncited_open_alerts()` stubbed to `[]` | the flagged invoice disappears from the briefing again; asserted as its own test, so the guarantee is provably load-bearing (§18.8's precedent in Feature 34) |

### 13.5 The same input, run again — all three roles, real Terra

`docs/test_evidence/atlas_intelligence_2026-09-20/rerun_after_717_719/` — VPI tenant, `as_of`
2026-09-15, `gpt-5.6-terra`, **explicit `GrantSet`s** per role (the mock-auth shared identity
cannot express a role; the README records why and what that replaces). 0 dropped paragraphs on
all three runs.

| role | paragraphs | question | score (corrected §6) | cost |
|---|---|---|---|---|
| Admin | 4, none appended (the model covered all three flagged invoices itself) | fired | 0 MATCH / 7 PARTIAL / 5 MISS of 12 | $0.028376 |
| Auditor | 4, **the fourth appended** (the model left VPI-OUT-2014 out) | fired | 0 MATCH / 3 PARTIAL / 1 MISS of 4 | $0.019330 |
| Trainer | 2, none appended | fired | 0 MATCH / 1 PARTIAL / 2 MISS of 3 | $0.009606 |

The question fired on **three of three** runs, against **zero of six** before this change.

**Why there is still no MATCH, and why that is not this change's failure.** §6 grants MATCH only
when every figure an item lists appears in one paragraph, and several items list derived totals
no tool renders (M1's ₹5,17,146.80, M2's +₹640.00, M6's clean ₹11,07,441.80). ATLAS may not state
a number a tool did not render (§1), so those items are PARTIAL by construction on this build.
The fix, when it is wanted, is a tool that renders the total — never a prompt that permits the
addition.

`docs/atlas_admin_vpi_expected.md` gained §0 in the same change: its *Must cite* ids were bare
uuids and bare composed tokens, while the system emits role-prefixed recommendation ids, so the
2026-09-20 grading scored a correct Admin briefing **0/12** on a documentation defect. §2's cite
lines now carry the ids a live dispatch actually emits, and §6 states the rule explicitly — **a
MUST item is MATCH if ANY listed id is cited and the figures appear**. No figure, ranking,
MUST-NOT or NO-TOOL-TODAY marking was revised.
