# Feature 33 — The Analyst Agent (ATLAS): one investigative loop at three scopes — the chat bubble, the owner's intelligence, and onboarding

**App:** invoice-be (+ FE counterpart `apps/invoice-fe/docs/feature_22_today_ask_records.md`) · **Status:** spec approved in founder interview 2026-09-15; **amended 2026-09-15 (walkthrough rulings 1–10, §8.2)**; build not started; slices A→B→C (§6) · lives in `be_features_tracker.md` · **Depends on:** `feature_30_business_intelligence.md` (§11 tasks 30.19 / 30.20 — the three-state check result and the claim renderer are prerequisites, not part of this feature), ~~`feature_31_credit_debit_notes.md`~~ (cancelled 2026-09-14: only invoices are ingested, by user training; notes / proformas / receipts arrive as chat attachments, whose Feature 30 cards this agent plans over — **corrected 2026-09-15:** the credit note `BHF-CN-2010` is therefore **demo attachment turn 11**, a Feature 30 `card_net_position` bubble plus a Feature 33 `auto_apply_credit_notes` convention proposal, not an excluded document; Feature 31's lifecycle, routing and schema stay cancelled), `feature_29_llm_optimisation.md` (L3 planner, the answer-contract gate, §12's open L1 decision), `feature_26_chat_attached_documents.md` (rulings D2 / D3, revisited in §4). **Absorbs the former Feature 32 placeholder (founder 2026-09-14):** business-profile discovery and guided configuration are this agent's onboarding scope, §3.7 — one agent gets to know the business, then helps it see its priorities.

**Agent name — ATLAS (ruled 2026-09-15).** The placeholder is resolved: the analyst agent is **ATLAS**. ATLAS pairs with SAGE — SAGE answers what was asked, ATLAS carries the business. The name lives in a new `agents/atlas_prompts.py`, a mirror of `agents/sage_prompts.py` (persona block, narration prompts, the boundary sentence); it is the only place the name is authored, and it is listed in §2.

**Founder framing, 2026-09-09/10 (the spec is written to this):**
- "this application was primarily built to extract invoice pdf and show its problem for audit and answer in chat … we are extracting data without manual intervention, we are creating knowledge bank by answering questions not asking user to see details in screen, now we want to give them intelligence to help them understand the business. **data → knowledge → intelligence using LLM and agentic AI**."
- "chat is for regular users and intelligence is for higher authority to make better decisions."
- "few attached documents are at low level users also like PO, challan … they should also get the intelligence of recon; few documents are needed for company level insights which can be given by higher authorities … the higher authority can go to chat, attach document and get the insight and if needed make more chat to get better suggestions."
- "will the system be able to get so smart from just seeing bunch of invoices over time, since all other docs are just attached in chat area" → no, not as built; the fix is §4.
- "the business intelligence part is not happening through any agent" / "for the bubble chat as well as business insight this agent will be utilised" → one agent, two scopes (§3).
- "already there are too much complicated application with so many screens" → FE counterpart, Feature 22.

## 1. Overview

**What this is.** One agent loop — *observe → plan → act through deterministic tools → investigate → say through the answer-contract gate → ask for what is missing → learn* — invoked at three scopes:

| Scope | Trigger | Observes | Produces | Audience |
|---|---|---|---|---|
| **attachment** | a document is attached in chat (Feature 26 path) | this document + everything on file it resolves to | the insight bubble — Feature 30's bubble, now planned rather than dispatched by doc type | whoever attached it |
| **tenant** | scheduled (weekly) + event-driven (a statement lands, a deviation crosses a threshold) | everything that arrived since the last run, open findings, the business profile | the owner's **Today** lines and briefing; input requests | Admin (§6) |
| **onboarding** (§3.7) | **after the first ingest batch settles** (`ANALYST_ONBOARD_MIN_DOCS`, default 10 extractions complete) — not first login (ruled 2026-09-15) — and again whenever coverage changes materially (a new doc type, vendor cluster or currency appears — **at most once per hour per tenant**, ruled 2026-09-15), **and the routine questionnaire (§3.7 *Ask the owner*) at first login on the Setup path or immediately after the first Discover on the Ingest path** | everything on file for the tenant, read as a whole | the **business profile** (`BusinessProfile`), a ranked list of proposed conventions surfaced as Today lines, the first priorities list, **and the six routine answers** | Admin |

Same code, same tools, different scope object and budget. The bubble is a one-document investigation; the briefing is a tenant-wide one; onboarding is the tenant-wide one run before there is a profile to consume, producing the profile itself.

**The one rule, unchanged from Feature 30.** The model **plans, prioritises, investigates, explains and asks**. It never produces a number. Every figure comes from a tool; every sentence passes `_answer_contract_gate()`; a rejected sentence falls back to the template. This is what makes an agent that speaks first trustworthy enough to speak to a CFO. Feature 29 §12 records that the gate validates figures, not claims — that limitation is inherited here and not solved here (§7 Q6).

**What changes, by component.**

| Component | Today | After |
|---|---|---|
| `CARDS_BY_DOC_TYPE` dispatch (Feature 30) | fixed tuple per doc type; `OTHER` gets nothing | the agent's plan step chooses cards from what the document **resolves to**; type is a hint and a fast path, never the gate (§3.2) |
| Chat attachments (Feature 26 D2/D3) | temporary; TTL deletes the row and the insight with it | the document may still expire; the **facts it leaves behind persist** (§4). This is the change that lets the system get smarter over time |
| Dashboard "Actionable Insights" (Gap 30, `get_dashboard_insights()`) | the LLM authors recommendations from four aggregates, 13–19 s, free text | **removed**. Its aggregates become tools; the tenant-scope run produces Today's lines from findings with stable keys and lifecycle |
| Insight lifecycle (`services/insights.py`) | per attachment | shared by both scopes; tenant-scope findings roll up per counterparty |
| Visibility | tenant only | tenant **and** clearance on sessions, attachments, facts, findings (§5) |
| Input requests | none | generated from the dependency table — "attach last quarter's bank statement → 90-day cash forecast" (§3.5) |
| Forecast | none | four labelled tiers: certain / committed / recurring / estimated (§3.4), plus a P&L projection line alongside cash runway (FP&A, ruled 2026-09-15) |
| Acting | nothing; every change is a screen the user finds | ATLAS proposes an **action** (§3.8) as a Today line; the user confirms; the existing endpoint runs and the call is logged. Never autonomous in v1 |
| **Owner's routines** (ruled 2026-09-15) | unknown — the system never asks how the business actually runs | six answers captured once (§3.7 *Ask the owner*), stored as `tenant_profile_rule` rows with `source="atlas_onboarding"`, read and edited in the Trainer, **re-asked only when Discover observes contradicting behaviour**; five deterministic Today effects |
| **Upload** (ruled 2026-09-15) | a separate Ingestion screen the user must find | Today's `Upload` / `Attach` open the **browser's native file picker** and post to the existing ingestion and chat-attachment endpoints; asking for it in words returns an `attach_prompt` bubble (§3.9). ATLAS never opens the disk |

**What this is not.**
- Not SAGE. SAGE answers a question about records the user asked; ATLAS investigates and advises, unprompted or from a launch point, and may act on confirmation (§3.8). The boundary is stated in §3.6 and tested.
- **Formerly split from Feature 32 — merged 2026-09-14, founder ruling** ("the analyst agent is for getting the user's business profile along with helping the user understand priorities better"). Discovering the tenant's conventions, proposing them, and consuming the accepted profile at runtime are one loop with one owner (§3.7); a second spec would have described the same `observe()` over the same data.
- Not a dashboard. Founder ruling stands (`project_dashboard_is_workbook_not_inapp`): operational monitoring is Azure Workbooks. Today (FE Feature 22) is a ranked list of things that expect an action, not a metrics page.
- Not a second BI system. The card engine, `Insight` table, thresholds, semantic views, bank ledger and matcher, entity resolver, doc linking and the gate are all **reused**. This feature adds a loop, a planner call, a facts ledger, a scope predicate, a dependency table, a forecast engine, the FP&A capabilities and the action registry — and removes one LLM-authored panel.
- **Scope is full FP&A (ruled 2026-09-15).** Not "AP/AR + cash only": P&L by period, margin per customer and per item, budget variance per account and expense-category trend are capabilities in the registry (§3.4). Each is `NOT_CHECKED` → an input request until its input kind is on file; an FP&A card is **never an empty tile**.
- Not multi-agent. Feature 29 §4.3's progression is router → planner → verifier → multi-agent; this feature is the planner and the first verifier-shaped behaviour (investigate before you speak). It does not orchestrate agents.
- **Not a file manager (ruled 2026-09-15).** ATLAS has no filesystem access. `Upload` and `Attach` are browser-native file pickers posting to the existing ingestion and chat-attachment endpoints; there is no new upload endpoint and no directory picker. The Ingestion page stays, under Records (§3.9).

## 2. File coordinates

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `agents/analyst_agent.py` | `run_analyst(scope: AnalystScope, db_session, budget: Budget) -> AnalystResult` | new | the loop. `observe()` → `plan()` → `act()` → `investigate()` → `say()` → `ask()`; each a named function below; never raises into a caller |
| `agents/analyst_agent.py` | `AnalystScope` (dataclass: `kind: "attachment" \| "tenant" \| "onboarding"`, `tenant_id`, `clearance`, `attachment_id \| None`, `since: datetime \| None`, `profile: BusinessProfile`) | new | what one run is about; every tool call carries it. (Three kinds — §1 and §3.7 always described three; the two-kind annotation here was an inconsistency, fixed 2026-09-15) |
| `agents/analyst_agent.py` | `observe(scope, db_session) -> Observation` | new | attachment scope: the row's extracted JSON + `resolve_overlap()`. tenant scope: arrivals since `scope.since`, open findings, profile, coverage from `coverage_for()` |
| `agents/analyst_agent.py` | `plan(observation, scope, llm) -> Plan` | new | **the one planning call.** Given the overlap graph / arrivals and the capability registry, returns an ordered list of `(capability, args)`; validated against `CAPABILITIES` — a capability the model invents is dropped and logged, never executed. Behind `ENABLE_ANALYST_PLANNER`, **on for tenant and onboarding scopes only** (ruled 2026-09-15); attachment scope stays on `plan_by_rule()` (the Feature 30 type-keyed tuple) until Feature 29 CP2 calibration |
| `agents/analyst_agent.py` | `act(plan, scope, db_session) -> list[InsightCard]` | new | executes each capability in order through the registry; `BLOCKED` on exception, the rest still run (Feature 30 shape) |
| `agents/analyst_agent.py` | `investigate(cards, scope, db_session, llm, budget) -> list[InsightCard]` | new | for each finding above `threshold("investigate_min_amount")` the model may request up to `budget.follow_ups` further capabilities ("check this vendor's other POs", "check payment history") and attach the results as evidence. Same registry, same validation. This is the agentic step Feature 29 staged as "verifier" |
| `agents/analyst_agent.py` | `say(block, scope, llm) -> Narration` | edit of `narrate_insight_block()` | tenant scope narrates a briefing (several sentences, each gated separately); attachment scope is the one-line verdict as today. `_answer_contract_gate()` per sentence; a rejected sentence is replaced by its finding's template text, never dropped silently |
| `agents/analyst_agent.py` | `ask(observation, block, scope) -> list[InputRequest]` | new | from `missing_inputs()`: what could not be computed, which input unlocks it, ranked by `unlock_value()` |
| `agents/analyst_agent.py` | `learn(result, feedback, db_session)` | new | acted / dismissed per `finding_key` feeds `insight_thresholds` suppression per tenant (a kind the owner always dismisses stops surfacing) and `record_correction()` for narration corrections |
| `agents/capabilities.py` | `CAPABILITIES: dict[str, Capability]`, `Capability(name, fn, kind: "read" \| "action", input_schema, output_schema, deterministic: bool, needs: tuple[InputKind, ...], scopes: tuple[str, ...], roles: tuple[str, ...])` | new | Feature 29 §4.2's L2 registry, as a dict, not a framework. Every Feature 30 card registers here; so do the semantic-view metrics, the forecast functions, the FP&A capabilities and the bank matcher. `needs` is what drives the dependency table |
| `agents/capabilities.py` | FP&A capabilities: `pnl_by_period`, `margin_per_customer`, `margin_per_item`, `budget_variance_per_account`, `expense_category_trend` | new | ruled 2026-09-15 (full FP&A). `deterministic=True`, SQL over `v_period_accounts` / `v_budgets` / invoice lines; each `NOT_CHECKED` → input request while its `needs` kind is absent |
| `agents/capabilities.py` | `ACTIONS: dict[str, Capability]` (`kind="action"`), `role_allows(capability, role) -> bool` | new | §3.8. Confirm-then-execute, role-gated; each action's `fn` calls an **existing** endpoint or service — never new business logic |
| `agents/atlas_prompts.py` | `PERSONA_BLOCK`, `PLAN_PROMPT`, `BRIEFING_PROMPT`, `WHY_IT_RANKS_PROMPT` | new | mirror of `agents/sage_prompts.py`; the only place the ATLAS name and voice are authored (ruled 2026-09-15) |
| `services/action_log.py` | `log_action(tenant_id, user_id, capability, args, result, db_session) -> ActionLog` | new | §3.8; one row per executed action, written in the same transaction as the call's own commit |
| `services/overlap.py` | `resolve_overlap(extracted_json, scope, db_session) -> OverlapGraph` | new | the resolve-first gate (§3.2): parties → vendors/customers, doc numbers → invoices/POs, line descriptions → items on file, tax ids → region, amounts+dates → bank lines, tables with periodised accounts → statement shape. Uses `agents/entity_resolver.resolve_entities()`; never a substring match |
| `services/facts.py` | `Fact` model (§4), `emit_facts(attachment_row, extracted_json, overlap, db_session) -> list[Fact]`, `facts_for(subject_kind, subject_id, clearance, db_session)` | new | the facts ledger: what a document asserts, persisted independently of the document |
| `services/facts.py` | `FACT_EMITTERS: dict[str, Callable]` | new | per shape, not per doc type: `emit_commitment` (has agreed lines + counterparty), `emit_delivery_event` (has delivered quantities), `emit_payment_event` (has a settled invoice ref / UTR / matched bank line), `emit_terms` (has rates / payment terms with an effective period), `emit_period_accounts` (has a periodised account table), `emit_budget` (has planned amounts per account for a future period — added 2026-09-15 for FP&A budget variance; consumes the `budgets` input kind, already in `INPUT_KINDS`). A document may fire several |
| `services/dependency.py` | `render_input_request(req) -> str` | new | §3.5, task 33.35 (ruled 2026-09-15): one template per `INPUT_KINDS` entry, each naming the **exact document kind** and the **quantified unlock**; a test asserts no rendered string contains a generic placeholder |
| `services/tenant_profile_rules.py` | `ROUTINE_QUESTIONS: tuple[RoutineQuestion, ...]` (six), `RoutineQuestion(key, prompt, chips, free_text: bool, skippable: bool, answer_kind)`, `save_routine_answer(tenant_id, key, value, source, db_session)`, `routine_answers(tenant_id, db_session) -> dict`, `next_routine_question(tenant_id, path, db_session) -> RoutineQuestion \| None`, `detect_routine_contradiction(tenant_id, db_session) -> list[str]` | new | §3.7 *Ask the owner*; tasks 33.28 / 33.29 / 33.31. Writes `tenant_profile_rule` rows with `source="atlas_onboarding"`. A skip is recorded as `skipped`, never left unanswered, so it is never re-asked on a schedule |
| `services/dependency.py` | `INPUT_KINDS`, `coverage_for(tenant_id, clearance, db_session) -> Coverage`, `missing_inputs(plan_or_capabilities, coverage) -> list[MissingInput]`, `unlock_value(missing, db_session) -> Money \| int` | new | §3.5. Coverage is computed from facts and invoices actually on file (kinds present, months of depth, staleness). `unlock_value` is a count or a sum from the views — never a guess |
| `services/forecast.py` | `forecast(tenant_id, clearance, horizon_days, db_session) -> Forecast`, `Tier = "certain" \| "committed" \| "recurring" \| "estimated"`, `detect_recurrence(facts) -> list[Recurrence]`, `scenario(forecast, change) -> Forecast`, `project_pnl(tenant_id, clearance, horizon_days, db_session) -> PnlProjection` | new | §3.4. Pure arithmetic over facts + views; every line carries its tier and its data depth. `project_pnl` is the P&L projection line alongside cash runway (ruled 2026-09-15). **Multi-currency: per currency, no conversion** — one forecast and one rollup set per currency seen |
| `services/attachment_insights.py` | `build_insight_block()` | edit | becomes `run_analyst(AnalystScope(kind="attachment", …))` behind `ENABLE_ANALYST_AGENT`; the type-keyed tuple survives as `plan_by_rule()`'s attachment branch |
| `services/attachment_extraction.py` | `extract_attachment()` | edit | after matching: `emit_facts()` (always, when `ENABLE_ATTACHMENT_FACTS`) then the analyst run |
| `queue_worker/analyst_handlers.py` | `handle_analyst_tenant_run(tenant_id, trigger: "scheduled" \| "statement_landed" \| "deviation")` | new | tenant scope on the queue; writes `Insight` rows with `scope="tenant"` and a `TodayItem` list; publishes `today_updated` on the tenant channel |
| `infra/` job | `caj-analyst-weekly-dev` | new | **Monday 06:00 UTC** (ruled 2026-09-15; tenant-local scheduling deferred); calls the handler per active tenant. Same shape as `caj-chat-doc-ttl-dev` |
| `routers/today.py` | `GET /today/questionnaire` → `get_next_question(path)`, `POST /today/questionnaire/answer` → `answer_question()` (chip · free text · `skip`), `GET /today/routine-answers` → `list_routine_answers()`, `PATCH /today/routine-answers/{key}` → `edit_routine_answer()` (the Trainer's read/edit surface), `POST /today/run` → `run_now()` (Admin-only, Redis-TTL cooldown, 429 with `retry_after_seconds`) | new | tasks 33.29 / 33.32 (ruled 2026-09-15). `main.py` registers the one `today` router; these paths live on it, not on a second router |
| `routers/me.py` (the module serving `/auth/me` — confirm the real location before adding) | `GET /me/preferences` → `get_preferences()`, `PATCH /me/preferences` → `set_preferences()` | new | task 33.39. Reads / writes `User.ui_prefs` — `layout`, `first_run_seen`, `tour_seen`, `questionnaire_progress`. **Per user, not per tenant**; an unknown key is rejected. This is the store FE 22.14's "shown once per user" and FE 22.21's per-user classic toggle have today (there is none — no preference table, no `first_run_seen` column) |
| `queue_worker/main_worker.py` | the task dispatch chain | **edit** | task 33.15 / 33.24. Dispatch is a **string `if/elif` chain** (~line 197) plus a `data.get("task")` branch (~line 290) — **there is no handler registry**, so `analyst_tenant_run` and `analyst_onboarding_run` each need an explicit branch and an import beside `handle_insight_job` |
| `showcase/vpi_demo/make_financial_docs.py` | `bank_statement()` | **edit** | task 33.38 (ruled 2026-09-15): adds June-2026 and July-2026 statements chaining Jun → Jul → Aug, recurring lines in all three, **without altering the existing Aug PDF's lines or its 355,336.00 closing balance** (byte-stability asserted). Deterministic generator, as today |
| `routers/today.py` | `GET /today` → `get_today(role, clearance)`, `POST /today/{item_id}/open` → `open_in_ask()`, `/accept`, `/edit`, `/reject` → convention decisions (§3.7), `/confirm` → `confirm_action()` (§3.8), `/dismiss` → `dismiss_item()`, `/scenario` → `run_scenario()` | new | the ranked list for FE Feature 22. `GET /today` also returns the **`pre_onboarding`** state below the threshold (§3.10). `open_in_ask` creates or resumes a session with the item's seeded question. `accept`/`edit`/`reject` answer a `ConventionProposal` **on the agent's screen**, not in the Trainer. `confirm` executes one role-allowed action and logs it. `dismiss` clears the line and feeds `learn()`. `scenario` recomputes a forecast line with one change |
| `routers/dashboard.py` | `get_dashboard_insights()` | **remove** | Gap 30's LLM-authored panel; its four aggregates become capabilities |
| `routers/chat.py`, `routers/chat_attachments.py` | `_require_owned_chat_job()`, session list, attachment read | edit | add the clearance predicate (§5) to every read; deny by default |
| `models.py` | `ChatSession.clearance`, `ChatAttachment.clearance`, `Fact`, `Insight.scope`, `Insight.clearance`, `TodayItem`, `InputRequest`, `ActionLog` | edit / new | §5, §4 and §3.8; one add-only migration. Anchors: `ChatSession` (line 420), `ChatAttachment` (line 497), `Insight` (line 1741) |
| `models.py` | `TenantProfileRule` (new table `tenant_profile_rule`: `id`, `tenant_id`, `key`, `value` JSON, `source`, `created_at`, `updated_at`; unique on `(tenant_id, key)`), `TenantChatRule.source`, `User.ui_prefs` | edit / new | tasks 33.28 / 33.23 / 33.39, all in migration `a1b2c3f33001`. **Ruled 2026-09-15 (default, founder to override):** the questionnaire gets its **own small table** — `TenantChatRule` is *not* stretched to hold business facts (its docstring scopes it to how the answering agent reasons, and `models.py:868` warns that mixing rule kinds caused undiagnosable bugs before). `TenantChatRule.source` (`"user"` default / `"atlas"`) is still added, for 33.23's convention writes only. `User` anchor: line 642 |
| `services/semantic_views.py` | `query_metric()` | edit | takes `clearance`; the views gain a `clearance` column where they read facts |
| `services/rag_service.py` (or wherever Chroma collections are named) | collection naming | edit | exec-scoped attachments index into `{tenant}_exec`, a separate collection — a wall, not a metadata filter |
| `config.py` | `ENABLE_ANALYST_AGENT`, `ENABLE_ANALYST_PLANNER`, `ENABLE_ATTACHMENT_FACTS`, `ENABLE_ANALYST_ACTIONS`, `ANALYST_FOLLOWUP_BUDGET: int = 3`, `ANALYST_ATTACHMENT_FOLLOWUP_BUDGET: int = 1`, `ANALYST_SUPPRESS_AFTER: int = 3`, `ANALYST_ONBOARD_MIN_DOCS: int = 10`, `ANALYST_WEEKLY_ENABLED`, **`ANALYST_RUN_NOW_COOLDOWN_SECONDS: int = 600`**, **`ANALYST_DISCOVER_DEBOUNCE_SECONDS: int = 3600`**, **`ANALYST_APPROVAL_THRESHOLD_DEFAULT: int = 100000`** | edit | all default to today's behaviour (off / 0) except the numeric defaults ruled 2026-09-15. The last three are new from the walkthrough rulings: the Run-now cooldown (33.32), the Discover debounce (33.33) and the sixth routine question's default approval threshold (₹1,00,000 **in tenant currency**, 33.28) |
| `agents/sage_prompts.py` | `PERSONA_BLOCK` | edit | one sentence naming the boundary: SAGE answers about records; investigation, advice and (on confirmation) action are ATLAS's, reachable from Today |
| `tests/test_analyst_agent.py`, `tests/test_facts.py`, `tests/test_dependency.py`, `tests/test_forecast.py`, `tests/test_clearance.py`, `tests/test_analyst_actions.py`, `tests/test_tenant_profile_rules.py`, `tests/test_today_routes.py`, `tests/test_user_preferences.py` | see §6 | new | the last three cover the questionnaire (33.28–33.31), Run-now / debounce / pre-onboarding / `attach_prompt` (33.32–33.34, 33.37) and `/me/preferences` (33.39) |

**FE coordinates are not restated here.** The FE-facing file corrections found on 2026-09-15 (no `lib/apiClient.ts` method surface — it is a 7-line axios instance; no `components/chat/Composer.tsx`; no `components/chat/SessionRail.tsx`) are fixed in `apps/invoice-fe/docs/feature_22_today_ask_records.md` §2 only.

## 3. Functionality

### 3.1 The loop

`run_analyst(scope, db_session, budget)`:

1. **observe** — builds an `Observation`. Attachment scope: the row, its extracted JSON, and `resolve_overlap()`. Tenant scope: invoices and facts with `created_at > scope.since`, open `Insight` rows, the `BusinessProfile`, and `coverage_for()`.
2. **plan** — one model call (or `plan_by_rule()` with the flag off). Input: the observation *summarised as entities and counts* — the model never sees document text (Feature 29 §4.4, Gap 439 shape). Output: an ordered list of capability calls. Anything not in `CAPABILITIES`, or with arguments failing the input schema, is dropped and logged.
3. **act** — runs the plan. Each capability is a Feature 30 card, a view metric, a forecast function or the bank matcher. Output: `InsightCard`s with three-state checks (Feature 30 task 30.19).
4. **investigate** — for findings above the investigate threshold, the model may ask for up to `budget.follow_ups` further capabilities per finding. Results attach as `evidence`. A follow-up that contradicts the finding downgrades its confidence and says why. This is where "Rajesh over-billed PO-1041" becomes "Rajesh over-billed 3 of 5 POs this quarter" — or "one-off; the other four are exact".
5. **say** — claims → renderer (Feature 30 task 30.20) → template text; then narration per sentence through the gate. Attachment scope: one verdict line. Tenant scope: a briefing of at most `budget.sentences`, each independently gated.
6. **ask** — `missing_inputs()` over the plan: every capability that returned `NOT_CHECKED` because an input kind is absent or stale becomes an `InputRequest`, ranked by `unlock_value()`.
7. **persist** — `Insight` rows (scope, clearance, lifecycle as today); `TodayItem`s at tenant scope; `InputRequest`s.

Budgets: attachment scope `follow_ups=ANALYST_ATTACHMENT_FOLLOWUP_BUDGET` (default **1**, ruled 2026-09-15), `sentences=1`; tenant and onboarding scope `follow_ups=ANALYST_FOLLOWUP_BUDGET` (default 3), `sentences=6`. All are settings.

### 3.2 The resolve-first gate (attachment scope)

Today `is_insight_doc_type()` decides everything: nine types get a bubble, `OTHER` gets nothing. A supplier price list, a GST circular, a competitor quote, a tender, an email thread printed to PDF — all `OTHER`, all silent. The taxonomy is frozen and a fourteenth type would not help: the space of documents is open.

`resolve_overlap()` replaces the type gate with an **overlap graph**: which entities in this document resolve to which records on file.

| Resolves | Against | Enables |
|---|---|---|
| party names | vendor / customer master, aliases (30.0f) | every counterparty card |
| document numbers | invoices, POs, prior attachments' facts | agreed-vs-billed, delivery, payment application |
| line descriptions | items on invoices of the same party | price drift, quantity checks |
| tax ids | region (`services/region.py`, with the Gap 510 fix) | compliance rule cards |
| amounts + dates | bank ledger lines | reconcile |
| rates / terms with a period | contract facts | terms deviation |
| a periodised account table | (shape only) | P&L → `emit_period_accounts` → forecast |

Type is still extracted and still used — as the **fast path** (`plan_by_rule()` picks the Feature 30 tuple when the type is known and the planner is off) and as a hint to the planner. A document that resolves to **nothing** gets a bubble that says so: "I read this, but nothing in it matches your vendors, invoices or items" — the three-state rule again, never silence.

Resolution is entity-based, never similarity-based: embedding similarity says a price list *looks like* an invoice; entity resolution says it *names three of your vendors*. Only the second is relevance.

### 3.3 Tenant scope

`handle_analyst_tenant_run()` runs the same loop with `scope.kind="tenant"`. The plan step at tenant scope selects from a fixed, certified question set (Feature 30 task 30.8's certified examples, extended) — "which vendor's price moved most", "who pays us latest", "what is due in the next 30 days against what is in the bank" — and the model decides **which are worth asking this week**, given arrivals and the profile. Nothing is invented; the model orders and filters.

Findings roll up per counterparty: reliability = short deliveries + over-billing vs PO + terms adherence, each a fact count over a window; payment behaviour = promised vs actual dates from payment facts. These are `Capability`s with `deterministic=True`; the rollup is SQL.

Output: `TodayItem`s for FE Feature 22, ranked by severity then amount (Gap 519's fix — severity is supplied by the card, never inferred from whether a number exists), one per open finding or input request, each carrying a seeded question for `open_in_ask()`.

Triggers: the weekly job (**Monday 06:00 UTC**, ruled 2026-09-15; tenant-local deferred); `statement_landed` (a bank statement's facts committed); `deviation` (a monthly view crosses `threshold("deviation_pct")`); and **`manual`** — the Admin's "Run now" (ruled 2026-09-15). Event triggers run a narrower plan.

**Admin "Run now" (ruled 2026-09-15).** `POST /today/run` enqueues a tenant-scope run immediately — the demo and the first week both need a way to see Today without waiting for Monday. Rules:

| rule | detail |
|---|---|
| who | **Admin only**; any other role is 403 |
| how often | **once per 10 minutes per tenant** (`ANALYST_RUN_NOW_COOLDOWN_SECONDS`, default 600) |
| mechanism | a **Redis key TTL** — there is no rate-limit library in this backend (`slowapi` is absent, confirmed 2026-09-15); use the existing `queue_worker/handlers.py::_get_redis_sync()` pattern |
| second call inside the window | **429** with `retry_after_seconds` in the body, so the FE can count down on the button (FE 22.23) |
| what it enqueues | the same `analyst_tenant_run` task with `trigger="manual"` — no separate code path |

**Today line lifecycle (ruled 2026-09-15).**

| event | effect |
|---|---|
| the underlying finding resolves | `cleared_at` set; the line disappears on the next `today_updated` |
| the owner dismisses it (`POST /today/{id}/dismiss`) | `cleared_at` set; the dismissal feeds `learn()` |
| the same `finding_key` kind is dismissed `ANALYST_SUPPRESS_AFTER` times (default **3**) by one tenant | that kind stops surfacing for that tenant only |
| the line is a forecast line | `POST /today/{id}/scenario` recomputes it with one change (`scenario()`, arithmetic only) |
| the line is a convention proposal | `/accept` · `/edit` · `/reject` (§3.7) |
| the line is an action | `/confirm` (§3.8) |
| the line is a routine question | chip · free text · `Skip` → `POST /today/questionnaire/answer` (§3.7 *Ask the owner*) |
| the owner runs it manually | `POST /today/run` enqueues a tenant-scope run, subject to the 10-minute cooldown (429 with `retry_after_seconds` inside the window) |

### 3.4 Forecast tiers

`forecast()` returns lines, each with a **tier** and a **depth** (months of data behind it):

| Tier | Source | Example |
|---|---|---|
| certain | due dates on issued invoices | ₹8.5L payable by 15-Sep |
| committed | open commitment facts (PO, contract) | ₹4.4L still to be invoiced on PO-1041 |
| recurring | `detect_recurrence()` over payment facts from statements — same counterparty, period within tolerance, amount within tolerance | salary ≈ ₹14.9L monthly |
| estimated | run-rate / trend from the views, only when `depth >= threshold("estimate_min_months")` | September spend ≈ ₹11L |

Cash runway = balance-on-date (from the latest statement fact) + certain-in − certain-out − recurring, by week. `scenario()` recomputes with one change ("Kaveri pays 20 days late") — arithmetic, no model. Every rendered forecast line names its tier and depth; below the depth threshold the line is `NOT_CHECKED("needs N months")`, which is exactly what `ask()` turns into an input request.

Recurrence is **detected**, never keyword-matched: "salary" is a counterparty with a ~30-day period, learned from the statement and confirmed once as a Today line (§3.7 Configure).

**Multi-currency (ruled 2026-09-15).** Forecast lines and every rollup are computed and reported **per currency**; no conversion, no synthetic base currency. A tenant with INR and USD gets two runways and two P&L projections, never one blended figure.

**P&L projection (ruled 2026-09-15).** `project_pnl()` runs alongside cash runway over the same horizon: revenue from `certain` + `committed` receivables plus `recurring` inflow, cost from payables + recurring outflow + `expense_category_trend`, each line tiered and depth-stamped exactly as the cash lines are. Cash answers "can I pay"; the projection answers "am I earning".

**FP&A capabilities (ruled 2026-09-15 — full FP&A, not AP/AR-only).**

| capability | computes | `needs` | when the kind is absent |
|---|---|---|---|
| `pnl_by_period` | revenue / cost / margin per period from `period_accounts` facts | `period_accounts` | `NOT_CHECKED` → input request "attach last quarter's P&L" |
| `margin_per_customer` | revenue less matched cost per customer | `invoices_out`, `invoices_in` | `NOT_CHECKED` → input request for the missing side |
| `margin_per_item` | per-item sell less buy, from invoice lines on both sides | `invoices_out`, `invoices_in` | as above |
| `budget_variance_per_account` | planned vs actual per account per period | `budgets`, `period_accounts` | `NOT_CHECKED` → "attach this year's budget" |
| `expense_category_trend` | spend by account category over months, with the deviation flag | `period_accounts` | `NOT_CHECKED` → input request |

Each is `deterministic=True` and registered in `CAPABILITIES` (§2). The rule is the three-state rule again: an FP&A card whose input is missing renders as `NOT_CHECKED` with the input request attached — **never an empty tile**.

### 3.5 The dependency table and input requests

Every `Capability` declares `needs: tuple[InputKind, ...]`. `INPUT_KINDS` is the closed set of *what a business can feed the system*: `invoices_in`, `invoices_out`, `purchase_orders`, `delivery_notes`, `bank_statements`, `remittances`, `contracts`, `period_accounts`, `tax_returns`, `loan_schedules`, `budgets`. Rule cards (Feature 30 §10.6) declare needs too — an ITC-reconciliation card needs `tax_returns`.

`coverage_for()` computes, from what is actually on file, per kind: present / absent, months of depth, days since last. `missing_inputs()` intersects the plan's needs with coverage. `unlock_value()` is a real number from the views — "14 invoices with a PO reference and no delivery fact" or "₹18.3L of statement outflows currently invisible" — never a template.

**Bank statements stay a chat attachment in v1 (ruled 2026-09-15).** No email-in or connector ingest door is built for statements in this feature. Instead, statement **staleness is an input request**: `coverage_for()` already computes days-since-last per kind, so once `bank_statements` goes stale past its threshold the loop raises an `InputRequest` ("your last statement is from 12-Jul — attach August's and the runway refreshes") ranked by `unlock_value()` like any other. The standing-feed ingest path is a later feature, not a Feature 33 task.

**FP&A input kinds.** `budgets` and `period_accounts` are the two kinds the FP&A capabilities depend on; both are already in `INPUT_KINDS`. `budgets` is populated by `emit_budget` (§2) from an attached budget sheet, so "full FP&A" needs no new input vocabulary — only the new emitter and the five capabilities.

The result is the "To see more" section of Today and the advisor's onboarding prompts (§3.7). The same agent asks at onboarding ("forward invoices here; what matters most to you?"), weekly ("attach last quarter's statement → cash forecast") and in a bubble ("no GSTIN read — attach the tax invoice and I can run the compliance checks"). One mechanism, three moments.

**Input requests name the kind and the unlock (ruled 2026-09-15).** This amends the paragraph above into a contract, not a description — task 33.35:

| requirement | detail |
|---|---|
| exact document kind | every `InputRequest` renders its `input_kind` as a **named document** — "last quarter's bank statement", "this year's budget sheet", "your Rajesh Steel contract" — **never** "more data", "additional documents" or any generic placeholder |
| quantified unlock | every rendered request carries a figure from `unlock_value()` — a count or a sum from the views, never a guess and never a template variable left unfilled |
| where the text lives | `render_input_request(req) -> str` in `services/dependency.py`, **one template per `INPUT_KINDS` entry** (all eleven); the model never authors this string |
| the test | a test iterates every `INPUT_KINDS` entry and asserts the rendered string contains no generic placeholder and does contain a figure |
| the three moments, asserted | **Day 1 after Discover**, **the weekly run**, and **inside an attachment bubble** — each proven by its own test, not assumed from one code path |

### 3.6 SAGE and ATLAS

| | SAGE | ATLAS |
|---|---|---|
| starts | when the user asks | unprompted (tenant), or when a document arrives (attachment), or from a Today line |
| answers | the question asked, about records | what the user did not know to ask, with evidence |
| tools | SQL, RAG, full records, comparison | the capability registry — cards, views, forecast, FP&A, matcher, actions |
| model calls per turn | one narration (+ planner when 30.16 lands) | one plan + up to `budget.follow_ups` investigate calls + gated narration |
| may compute | never | never |
| may act | never | **on confirmation only** (§3.8) — proposes, the user confirms, the existing endpoint runs, the call is logged |
| prompts live in | `agents/sage_prompts.py` | `agents/atlas_prompts.py` |

A Today line opened in Ask becomes a SAGE session seeded with the finding and its evidence; follow-up questions are SAGE's. ATLAS does not converse; it reports, offers an action, and hands over. The boundary is one sentence in `PERSONA_BLOCK` and one test: a SAGE turn never calls `run_analyst()`, and `run_analyst()` never calls SAGE's SQL tools.

### 3.7 Business profile — discover, propose, configure; then priorities

**Origin.** The former Feature 32 placeholder (founder 2026-09-09: "understand the customer docs well as a first step and then the system should align itself to show what additional is needed and end client can configure it thru trainer"), merged here 2026-09-14: the agent that will advise the business is the agent that should first get to know it.

**Discover.** `handle_analyst_onboarding_run()` runs the loop with `scope.kind="onboarding"`. `observe()` reads everything on file for the tenant as a whole — not since-last-run — and `profile_tenant()` (`services/business_profile.py`) reduces it deterministically to a `BusinessProfile`: document types and their volumes, vendor and customer clusters (`resolve_entities()`), currencies and tax regimes seen, fields consistently present / absent per doc type, payment habits (median days-to-pay per counterparty from `v_payment_events`), document chains actually observed (PO → delivery → invoice → payment coverage), and `coverage_for()` over `INPUT_KINDS`. No model call produces a profile value; the model only narrates it.

**Ask the owner — the routine questionnaire (ruled 2026-09-15).** Discover reads what the documents say; it cannot read how the business chooses to run. Six things are asked once, in the agent's own screen, and nowhere else.

*Trigger.* Two entry points, distinct and separately tested — the path comes from the FE's `PathChoice` (FE 22.14), so `next_routine_question(tenant_id, path, db_session)` takes the path as an argument:

| path | when the first question appears |
|---|---|
| **Set up first** | at **first login**, immediately |
| **Ingest documents first** | **immediately after the first Discover completes** — never at login |

*The six questions, verbatim, with their chip vocabularies.* One question per call. Every question accepts a **chip or free text**, and every question is **skippable**; a skip is persisted as `skipped`, not left unanswered, so it is never re-asked on a schedule.

| # | `key` | question | chips | free text |
|---|---|---|---|---|
| 1 | `payment_run` | "When do you normally pay your suppliers?" | `weekly_run` · `on_due_date` · `month_end` · `when_cash_allows` | yes |
| 2 | `po_before_invoice` | "Do you raise a purchase order before an invoice arrives?" | `always` · `materials_only` · `rarely` | yes |
| 3 | `invoice_approval` | "Who approves an invoice for payment?" | `owner_only` · `accounts_then_owner_above_threshold` · `accounts_alone` | yes |
| 4 | `month_close_day` | "Which day do you close the month on?" | — (a number) | yes |
| 5 | `collections_owner` | "Who chases overdue customer payments?" | a **user picker bound to a `User` row** (ruled 2026-09-15 — the Today line can then address a real person); **free text is an accepted fallback** | yes |
| 6 | `approval_threshold` | "Above what amount does an invoice need your sign-off?" | default **₹1,00,000 in tenant currency** (`ANALYST_APPROVAL_THRESHOLD_DEFAULT`) | yes |

Question 6 is the **sixth question ruled 2026-09-15** (default, founder to override): the approval threshold that question 3's `accounts_then_owner_above_threshold` answer depends on is asked, not derived from observed invoice sizes and not buried in a settings page.

*Store.* A new small table, `tenant_profile_rule` (`id`, `tenant_id`, `key`, `value` JSON, `source`, `created_at`, `updated_at`; unique on `(tenant_id, key)`), added in the same add-only migration `a1b2c3f33001`, written with `source="atlas_onboarding"`. **Ruled 2026-09-15 (default, founder to override):** `TenantChatRule` is deliberately **not** stretched to hold these — its stated purpose is how the answering agent should reason, "when do you pay vendors" is a business fact, and `models.py:868` warns that mixing rule kinds is how undiagnosable bugs happened before. No new rule engine either: the six rows are read by deterministic code, never by a prompt.

*Editing.* The Trainer reads and edits these rows — `GET /today/routine-answers` and `PATCH /today/routine-answers/{key}` — listed beside the hand-written chat rules on the existing `/settings/chat-rules` screen (FE 22.27). The questionnaire is the only place they are *asked*; the Trainer is the register.

*Re-asking.* `detect_routine_contradiction(tenant_id, db_session) -> list[str]` runs inside Discover over payment facts and PO coverage — answered `month_end` but the median payment day is 14; answered `always` for POs but 60% of invoices resolve to no PO. A contradicted key is re-asked **exactly once**, with the contradicting evidence attached to the line. **Only a contradiction re-asks.** The weekly job never re-asks on a schedule.

*The five effects on Today — all deterministic (Hard rule 3).* The model may narrate these lines; it never decides them. Each is a named consumer in `queue_worker/analyst_handlers.py` / `agents/capabilities.py`:

| answer | effect on Today |
|---|---|
| `payment_run` | payables `TodayItem`s are **grouped under a payment-run day header** |
| `po_before_invoice = "materials_only"` | **one line per materials invoice with no resolved PO** (a services invoice gets none) |
| `invoice_approval` + `approval_threshold` | a **"pending sign-off"** line for each invoice above the threshold |
| `month_close_day` | a **month-close countdown** line |
| `collections_owner` | overdue-receivable lines are **addressed to that owner** (the `User` row, or the free-text string) |

**Propose.** From the profile, `propose_conventions()` emits `ConventionProposal` rows: a plain-language rule the system needs a decision on, its default, and the evidence that prompted it — "Rajesh Steel is paid at 47 days on average; set default terms to NET 45?", "3 proformas were followed by a final invoice within 14 days; treat proformas as commitments?", "credit notes arrive for 6% of invoices; auto-apply them to the open invoice?", "two partial payments seen on one invoice; enable partial payments?". Proposals are ranked by `unlock_value()` (§3.5), the same number that ranks input requests, so "what to configure" and "what to feed in" sit on one scale.

**`auto_apply_credit_notes` is a named proposal kind (ruled 2026-09-15, task 33.36).** It was prose above; it is now a registered `ConventionProposal` kind, emitted when credit-note attachments exceed the threshold share of invoices ("credit notes arrive for 6% of invoices; auto-apply them to the open invoice?"), with that share and the affected invoices as its evidence. The bubble side already exists — `card_net_position` (`services/attachment_insights.py:952`) handles the credit-note case; 33.36 verifies it fires for `BHF-CN-2010` against BHA-2003 and registers it in `CAPABILITIES` under the credit-note path. **Feature 31's lifecycle is not revived**: no `Invoice` row is written, no routing, no sub-type schema — the credit note is demo attachment turn 11 and nothing more.

**Configure — answered on the agent's screen, not in the Trainer (ruled 2026-09-15).** Each `ConventionProposal` surfaces as a **Today line** with three affordances — `Accept` / `Edit` / `Reject` (`POST /today/{id}/accept`, `/edit`, `/reject`). The user answers the agent where the agent is talking; nobody is sent to a second screen to configure what was just explained. On accept (or accept-with-edit), ATLAS writes the rule into the **existing** store it belongs to — `ExtractionTemplate.rules` or `TenantChatRule`, whichever the proposal's kind maps to, with `source="atlas"` — no third store and no new rule engine. A rejected proposal is suppressed for that tenant via `learn()` (task 33.19), the same mechanism as a dismissed Today line.

The **Trainer UI only shows the resulting rule** as one it holds (same list, `source="atlas"` alongside the hand-written ones): it is the register of the business's conventions, not the place they get decided. This is the one change to the former Feature 32 design — Discover and Propose are unchanged, Configure moved.

**Priorities.** The onboarding run ends with the first tenant-scope `TodayItem` set (§3.3), ranked severity-first, prefaced by one gated sentence per item saying *why it ranks where it does* against the profile ("largest open exposure is 3 unpaid invoices to your slowest-paying customer"). This is the "help them understand priorities" half: the profile explains the ranking, the ranking is what the owner acts on. Weekly runs re-rank against the same profile; a materially changed profile (new doc type, vendor cluster, currency) re-triggers Discover, so onboarding and continuous learning are the same run at two cadences (§8 Q9, ruled).

**Cadence (ruled 2026-09-15).** Discover runs **after the first ingest batch settles** — `ANALYST_ONBOARD_MIN_DOCS` (default 10) extractions complete for the tenant — **not on first login**. A profile built from zero documents is worthless, and first login is the wrong moment to interrupt: first login is the welcome, checklist and tour (FE Feature 22 `FirstRun`), which is explicitly *not* a Discover run. Re-triggers on material coverage change, as above.

**Debounce (ruled 2026-09-15).** A material coverage change re-runs Discover **at most once per hour per tenant** (`ANALYST_DISCOVER_DEBOUNCE_SECONDS`, default 3600), using the same Redis-key-TTL mechanism as Run-now (§3.3) via `_get_redis_sync()`. A suppressed re-trigger is **logged, never queued for later** — the next real change re-runs it; a backlog of deferred Discovers is not a thing this system keeps.

### 3.8 Actions — propose, confirm, execute, log

**Ruled 2026-09-15.** ATLAS may do more than describe: a second capability class `kind="action"` in `agents/capabilities.py`. Every action is **confirm-then-execute**, **role-gated**, and calls an **endpoint or service that already exists** — an action never contains new business logic, only the proposal, the gate and the call.

| action (examples) | calls | role |
|---|---|---|
| set up the inbound email address for invoice ingest | existing email-setup endpoint | Admin |
| enable auto-load from a connected inbox | existing connector endpoint | Admin |
| set the outbound email sender | existing email-settings endpoint | Admin |
| hold an invoice | existing invoice-hold service | Auditor |
| dismiss a finding | `Insight` transition | Auditor |
| write a rule | `ExtractionTemplate` / `TenantChatRule` (the §3.7 path) | Trainer |

**Role map.** Admin → setup actions · Auditor → record actions (hold, dismiss) · Trainer → rule actions. `role_allows(capability, role)` is the single gate; a confirm from a role outside the action's `roles` tuple is **403**, and the endpoint is not called.

**Flow.** `plan()`/`investigate()` may emit an action alongside a finding → it becomes a `TodayItem` whose affordance is `Confirm` → `POST /today/{id}/confirm` checks the role, executes the capability's `fn` once, and `log_action()` writes an `action_log` row (tenant, user, capability, args, result, timestamp) in the same transaction. Failure is reported on the line, not retried silently.

**Never autonomous in v1.** No action executes without a user confirmation event, behind `ENABLE_ANALYST_ACTIONS`. Auto-execution of a class of actions the tenant has confirmed N times is a later decision, not this feature's.

### 3.9 Getting documents in — ATLAS never opens the disk (ruled 2026-09-15)

Task 33.34. The agent talks about documents; it does not fetch them.

| surface | mechanism | posts to |
|---|---|---|
| Today's `Upload` | the **browser's native file picker** (a real `<input type="file">`, the `components/ingestion/DropZone.tsx` pattern) | the existing `POST /api/v1/invoices/upload` |
| Today's / Ask's `Attach` | the same native picker | the existing `POST /chat/sessions/{id}/attachments` (`routers/chat_attachments.py:247`) |
| a typed "upload my invoices" in Ask | the turn returns a bubble payload of kind **`attach_prompt`**, carrying the **target** (`ingestion` vs `chat_attachment`) and the **accepted extensions** from the existing `_accepted_content_types()` (`routers/chat_attachments.py:65`). Intent is resolved by a **deterministic phrase set first**, a planner hint second | nothing — it renders a button (FE `AttachPromptCard`, 22.24) |

**No new upload endpoint. No filesystem access. No directory picker.** The BE side of this ruling is a contract over existing endpoints, not an uploader. The existing `/ingestion` page stays and is reachable under Records.

### 3.10 Before the threshold — the pre-onboarding Today state (ruled 2026-09-15)

Task 33.37. `ANALYST_ONBOARD_MIN_DOCS` is **10** (confirm the default in `config.py` before relying on it). Below it:

```
GET /today  →  { "state": "pre_onboarding", "docs_seen": N, "docs_required": 10 }
```

and **nothing else** — no findings, no FP&A lines, no input requests, no convention proposals. The only content is "upload to begin" with the progress count (FE `EmptyToday`'s `pre_onboarding` state, 22.25). At the tenth completed extraction the state flips and the onboarding run fires (§3.7 *Cadence*). Non-Admin first login is the welcome and a short tour only (FE 22.14); a login before the threshold triggers no analysis of any kind.

**Non-Admin Today thereafter (ruled 2026-09-15, default, founder to override).** A non-Admin sees the **same ranked list**, filtered server-side by clearance and role — **not a separate section set**. The owner-facing lines are hidden: payment-run grouping, pending sign-off, the setup actions, the convention proposals, and the cash / FP&A lines. This closes FE Feature 22 §7 Q4.

## 4. Data & schema changes — facts persist, documents may expire

**The defect this fixes.** Feature 26 D2 says an attachment is never an `Invoice` row and D3 says it moves no aggregate — both correct and both kept. But the consequence as built is that an attachment leaves **no trace at all** once the TTL job runs: the system reads a challan, reports the short delivery, and forgets a delivery ever happened. Next quarter it cannot say "Rajesh short-delivers" because it has no memory of any delivery. Invoices alone give bounded intelligence (spend trend, price history, terms norms, duplicates); every judgement a decision-maker wants — reliability, payment behaviour, cash — lives in the other documents, and those evaporate.

**The change.** Documents are channels; facts are the ledger. Chat attachment becomes one entry channel like email-in and the connector; the channel no longer decides the lifetime.

```
Fact
  id, tenant_id, clearance
  kind            commitment | delivery_event | payment_event | terms | period_accounts | budget | balance_on_date
  subject_kind    vendor | customer | invoice | po | item | account
  subject_id
  counterparty_id
  as_of           date the fact is about (delivery date, payment date, period end)
  figures         JSON, currency-keyed
  source_kind     chat_attachment | ingest | connector
  source_id       the attachment / document row (nullable after that row is hard-deleted)
  evidence        JSON: page, line, matched bank line id, UTR
  created_at
```

- Emitted by `FACT_EMITTERS` per **shape**, not per doc type (§2): a document with agreed lines and a counterparty emits a commitment whether it calls itself a PO, an order confirmation or a quotation that was accepted.
- **Hard delete holds** (`feedback_delete_means_hard_delete`): deleting the source document deletes its facts, everywhere, in the same transaction. `source_id` nullable exists only so a fact can *name* a source that is gone in an audit trail, never to retain one.
- D2 and D3 are **not** revoked: no `Invoice` row is written, no quota moves. What is revised is the implicit fourth ruling — that an attachment leaves nothing behind. **Ruled yes, 2026-09-15 (§8 Q1):** the `chat_attachments` row expires on TTL as designed, the `Fact` rows it emitted **stay**. A user-initiated hard delete of the document still cascades to its facts in the same transaction — TTL expiry and hard delete are deliberately different, and that difference is the feature.

Other schema, all in one add-only migration `a1b2c3f33001_analyst_agent.py`:

| table / column | purpose |
|---|---|
| `chat_session.clearance` (`"ops"` default, `"exec"`) | §5 |
| `chat_attachments.clearance` | §5; inherited from the session |
| `insight.scope` (`attachment` / `tenant`), `insight.clearance` | both scopes share the lifecycle |
| `today_item` (id, tenant_id, clearance, insight_id \| input_request_id, rank, seeded_question, created_at, cleared_at) | FE Feature 22's list |
| `input_request` (id, tenant_id, clearance, input_kind, unlocks: JSON, unlock_value, status OPEN/DONE/DISMISSED) | §3.5 |
| `action_log` (id, tenant_id, user_id, capability, args: JSON, result, created_at) | §3.8 — one row per confirmed-and-executed action |
| `tenant_profile_rule` (id, tenant_id, key, value: JSON, source, created_at, updated_at; unique `(tenant_id, key)`) | §3.7 *Ask the owner* — the six routine answers, `source="atlas_onboarding"`. **Ruled 2026-09-15 (default, founder to override):** its own table, not a stretched `TenantChatRule` |
| `tenant_chat_rules.source` (`"user"` default / `"atlas"`) | §3.7 *Configure* — marks the rules ATLAS wrote on accept (33.23). The column does not exist today |
| `user.ui_prefs` (JSON: `layout` `"surfaces" \| "classic"`, `first_run_seen` bool, `tour_seen` bool, `questionnaire_progress`) | task 33.39, read/written through `GET` / `PATCH /me/preferences`. **This is what makes FE 22.14's "shown once per user" and FE 22.21's per-user classic toggle persistable — neither has a store today** (no preference table, no `first_run_seen` column, confirmed 2026-09-15). Per user, not per tenant |
| views: `v_vendor_spend`, `v_overdue`, `v_3way_match` gain `clearance`; new `v_commitments`, `v_delivery_events`, `v_payment_events`, `v_recurrence`, and (for FP&A, 2026-09-15) `v_period_accounts`, `v_budgets` over `fact` | successor migration `a1b2c3f33002_fact_views.py` |

No backfill; no downgrade ceremony (dev rule).

## 5. Visibility — one clearance, every read path

Founder: "a higher authority can attach a bank statement or P&L to just understand the forecast so the doc is not seen by others."

**Model — by role, ruled 2026-09-15 (§8 Q3).** `clearance ∈ {ops, exec}`, assigned **by role, not by person**: **every** Admin holds `exec`; Auditor and Trainer hold `ops` (`models.RoleMapper` vocabulary). **No separate Executive role is added** — the role vocabulary stays as it is. Consequence, accepted deliberately: one Admin sees another Admin's private session. A session opened from an exec Today line, or by an Admin choosing "private", is `exec`; its attachments, facts, findings and Chroma chunks inherit it.

**Enforcement.** Every read path that today takes a `tenant_id` takes a clearance predicate; deny by default. This is the Gap 341 / Gap 460 / Gap 507 lesson applied once, deliberately: one predicate, one helper `clearance_filter(stmt, model, clearance)`, tested per path — not discovered leak by leak. Paths: session list, message read, attachment read and stream, `facts_for()`, `query_metric()`, `Insight` reads, Today, RAG retrieval (separate collection `{tenant}_exec` — a wall, not a `where` on metadata), Trainer (never sees exec source rows; may receive *rules* the owner teaches from them), exports and dashboards (never exec).

**Sharing derived facts — Option C, ruled 2026-09-15 (§8 Q2).** The owner attaches August's statement privately. The clerk later asks SAGE "was BHA-2002 paid?" — the answer is on that statement. Ruling proposed: **derived facts about records operations can already see flow down; source rows never do.** A matched bank line produces a `payment_event` fact on the *invoice* with `clearance="ops"` ("paid 06-Aug, UTR …"); the statement itself, and every non-invoice line — salary, loan, charges — stays `exec`. Generic: "facts about records you can already see" is a rule, not a list. **Ruled: Option C** — a payment fact on an invoice operations can already see flows down as `ops`; the statement row itself and every non-invoice line (salary, loan, bank charges) stay `exec`.

## 6. Tasks

Prerequisites, not tasks here: Feature 30 §11.7 sequence (Gap 477, then 30.19, then 30.20), Feature 29 CP2 calibration before the planner flag goes on at attachment scope.

**Phasing — three flagged slices (ruled 2026-09-15).** Task numbers are stable; only the grouping is new. Each slice ends at a **checkpoint: the full backend suite on real Postgres** (Hard rule 2). Nothing in a later slice starts before the previous checkpoint passes.

| slice | tasks | what it lands | checkpoint |
|---|---|---|---|
| **A — the ledger** | 33.7 – 33.11, **33.39** | facts, emitters, fact views, clearance on every read path, and the per-user preference store (33.39's columns ride in the same migration, so it belongs to A) | full BE suite on real Postgres |
| **B — the loop** | 33.1 – 33.6, 33.12 – 33.20, 33.25 – 33.27, **33.32 – 33.35, 33.37** | registry, overlap, loop, planner, dependency + input-request phrasing, forecast + FP&A, tenant job, Today routes, Run-now, Discover debounce, the upload-intent bubble, the pre-onboarding state, actions | full BE suite on real Postgres |
| **C — onboarding** | 33.22 – 33.24, **33.28 – 33.31, 33.36, 33.38, 33.40**, then 33.21 | business profile, the routine questionnaire and its effects, convention proposals on Today, the credit-note convention, the Jun/Jul statements, the onboarding run, then the eleven-scenario eval suite | full BE suite on real Postgres |

**Sub-sequence for Slice B** (24 tasks — the largest slice; a narrow test run at each sub-boundary, the full suite only at Checkpoint B): registry + overlap + loop (33.1 – 33.6) → numbers (33.12, 33.35, 33.13, 33.14, 33.14a) → tenant job + routes (33.15 – 33.17, 33.32 – 33.34, 33.37) → cleanup + actions (33.18 – 33.20, 33.25 – 33.27).

### Slice A — the facts ledger and clearance

| # | task |
|---|---|
| 33.7 | Migration `a1b2c3f33001`: `fact`, `clearance` columns, `insight.scope`, `today_item`, `input_request`, `action_log` (§3.8), **`tenant_profile_rule` (§3.7), `tenant_chat_rules.source`, `user.ui_prefs`** — one add-only migration, single head after `upgrade head`, no backfill, no downgrade ceremony |
| 33.8 | `services/facts.py`: `Fact`, `FACT_EMITTERS` (**six** emitters by shape — the five original plus `emit_budget`), `emit_facts()`, `facts_for()`; hard-delete cascade in the attachment and document delete paths |
| 33.9 | `extract_attachment()` calls `emit_facts()` behind `ENABLE_ATTACHMENT_FACTS`; the TTL job deletes the row and leaves the facts (§8 Q1 ruling) |
| 33.10 | Migration `a1b2c3f33002`: `v_commitments`, `v_delivery_events`, `v_payment_events`, `v_recurrence`, `v_period_accounts`, `v_budgets`; `clearance` on the three existing views; `query_metric(clearance=…)` |
| 33.11 | `clearance_filter()` and its application to every read path in §5; by-role assignment (every Admin `exec`, no new role); Option C fact split; `{tenant}_exec` Chroma collection; session `clearance` set on open. Application points confirmed 2026-09-15: `_require_owned_session` (`routers/chat_attachments.py:217`), `_require_owned_attachment` (:233), `get_chat_attachment` (:429), `get_attachment_links` (:460), the attachment stream, `list_insights` (`services/insights.py:270`), `rank_open_insights` (:315) |
| **33.39** | **Per-user UI preference store** (ruling 6 + 10): `models.py::User.ui_prefs` JSON (add-only, migration `a1b2c3f33001`) plus `GET /me/preferences` and `PATCH /me/preferences` in the module serving `/auth/me`. Holds `layout` (`"surfaces" \| "classic"`), `first_run_seen`, `tour_seen`, `questionnaire_progress`. **Prerequisite for FE 22.14 and FE 22.21, not an optional extra** — there is no preference table and no `first_run_seen` column today. Unknown keys rejected |

**Checkpoint A** — full backend suite on real Postgres before Slice B starts.

### Slice B — the loop, the numbers and the actions

| # | task |
|---|---|
| 33.1 | `agents/capabilities.py`: `Capability` (with `kind`, `roles`), `CAPABILITIES`; register every Feature 30 card, the four `METRICS`, `match_statement_lines`, with `needs` and `scopes`. Validation of a planned call against `input_schema` |
| 33.2 | `services/overlap.py::resolve_overlap()` over `resolve_entities()`; party, doc number, line description, tax id, amount+date, rate/terms, periodised table. Returns `OverlapGraph`; a document resolving to nothing returns an empty graph, not an error |
| 33.3 | `agents/analyst_agent.py`: `AnalystScope` (three kinds), `Budget`, `run_analyst()`, `observe()`, `act()`, `plan_by_rule()`. Attachment scope only, and attachment scope stays on `plan_by_rule()`. `build_insight_block()` delegates behind `ENABLE_ANALYST_AGENT` |
| 33.4 | `plan()` behind `ENABLE_ANALYST_PLANNER`, **enabled for tenant and onboarding scopes only** (§8 Q4): the one planning call; manifest-only input; invented capabilities dropped and logged |
| 33.5 | `investigate()` with `Budget.follow_ups` (attachment = 1); evidence attached; contradiction downgrades confidence with reason |
| 33.6 | `say()` — tenant-scope briefing, per-sentence gate, template fallback per sentence; attachment scope unchanged; narration prompts move to `agents/atlas_prompts.py` |
| 33.12 | `services/dependency.py`: `INPUT_KINDS` (11 kinds), `coverage_for()`, `missing_inputs()`, `unlock_value()`; `ask()` in the loop; `input_request` rows; **statement staleness raises an input request** (§8 Q5 — no ingest door). **Phrasing is 33.35's contract**, which amends this task rather than replacing it |
| 33.13 | `services/forecast.py`: `forecast()` certain + committed tiers, per currency, no conversion; `scenario()`; `project_pnl()` P&L projection line alongside cash runway |
| 33.14 | `detect_recurrence()` and the recurring tier; `estimated` tier gated on `estimate_min_months` |
| 33.14a | FP&A capabilities: `pnl_by_period`, `margin_per_customer`, `margin_per_item`, `budget_variance_per_account`, `expense_category_trend`; each `NOT_CHECKED` → input request when its `needs` kind is absent, never an empty tile (§3.4) |
| 33.15 | Tenant scope: `handle_analyst_tenant_run(tenant_id, trigger)`, the certified question set, per-counterparty rollup capabilities (reliability, payment behaviour), `TodayItem` generation with severity-first ranking (Gap 519's rule). **Register the task branch in `queue_worker/main_worker.py`** — dispatch is a string `if/elif` chain (~line 197) plus a `data.get("task")` branch (~line 290); there is **no handler registry**, so the new task name needs an explicit branch and an import beside `handle_insight_job` |
| 33.16 | `caj-analyst-weekly-dev` job (Bicep + params + `deploy-service`) at **Monday 06:00 UTC**; `statement_landed` and `deviation` triggers |
| 33.17 | `routers/today.py`: `GET /today`, `POST /today/{id}/open` with seeded session, `/dismiss`, `/scenario` |
| 33.18 | Remove `get_dashboard_insights()`'s LLM authoring: the panel endpoint **keeps returning its four aggregates as template text** until FE Feature 22 ships, then the endpoint is removed with the FE panel; register the four aggregates as capabilities (§8 defaults) |
| 33.19 | `learn()`: acted / dismissed → per-tenant suppression at `ANALYST_SUPPRESS_AFTER` (default 3); narration corrections → `record_correction()` |
| 33.20 | SAGE / ATLAS boundary: `agents/atlas_prompts.py` created; `PERSONA_BLOCK` sentence in `sage_prompts.py`; the two boundary tests |
| 33.25 | `ACTIONS` registry (`kind="action"`) and `role_allows()`: the six seed actions of §3.8, each calling an existing endpoint/service; role map Admin setup / Auditor record / Trainer rule; behind `ENABLE_ANALYST_ACTIONS` |
| 33.26 | `action_log` writes via `services/action_log.py::log_action()`; `POST /today/{id}/confirm` — role check, one execution, one log row, failure reported on the line |
| 33.27 | Action tests: an Auditor confirming a setup action → **403 and the endpoint not called**; an Admin confirming the same action → the endpoint called **exactly once** and one `action_log` row written |
| **33.32** | **Admin "Run now"** (ruling 2): `POST /today/run` in `routers/today.py` — enqueues an `analyst_tenant_run` with `trigger="manual"`, **Admin-only (403 otherwise)**, **once per 10 minutes per tenant** via a **Redis key TTL** using `queue_worker/handlers.py::_get_redis_sync()` (**no rate-limit library exists in this backend — `slowapi` is absent**); a second call inside the window returns **429** with `retry_after_seconds`. New setting `ANALYST_RUN_NOW_COOLDOWN_SECONDS = 600` |
| **33.33** | **Discover re-trigger debounce** (ruling 3): in `handle_analyst_onboarding_run()`'s material-coverage-change path, at most **once per hour per tenant**, same Redis-TTL mechanism. New setting `ANALYST_DISCOVER_DEBOUNCE_SECONDS = 3600`. A suppressed re-trigger is **logged, not queued for later** |
| **33.34** | **Upload-intent bubble** (ruling 4, §3.9): when a chat turn's intent resolves to "upload documents" (**deterministic phrase set first, planner hint second**) the turn returns a bubble payload of kind `attach_prompt` carrying the target (`ingestion` \| `chat_attachment`) and the accepted extensions from `_accepted_content_types()` (`routers/chat_attachments.py:65`). **No new upload endpoint** — the FE posts to `POST /api/v1/invoices/upload` or `POST /chat/sessions/{id}/attachments` (`chat_attachments.py:247`). Nothing in the loop touches the filesystem |
| **33.35** | **Input-request phrasing contract** (ruling 5, §3.5) — amends 33.12: `render_input_request(req) -> str` in `services/dependency.py`, one template per `INPUT_KINDS` entry, each naming an **exact document kind** and a **quantified unlock** from `unlock_value()`; a test asserts no rendered string contains a generic placeholder, over all eleven kinds. Three emission moments asserted separately: **Day 1 after Discover**, **the weekly run**, **an attachment bubble** |
| **33.37** | **Pre-onboarding Today state** (ruling 9, §3.10): `GET /today` returns `{state: "pre_onboarding", docs_seen: N, docs_required: ANALYST_ONBOARD_MIN_DOCS}` and **no findings, no FP&A lines, no input requests, no proposals** until the threshold is reached. Confirm `ANALYST_ONBOARD_MIN_DOCS = 10` is the real default in `config.py`. Also implements the ruled non-Admin behaviour: the same ranked list, server-filtered by clearance and role, owner-facing lines hidden — **not a separate section set** |

**Checkpoint B** — full backend suite on real Postgres before Slice C starts.

### Slice C — onboarding, then the scenario suite

| # | task |
|---|---|
| 33.22 | `services/business_profile.py`: `BusinessProfile`, `profile_tenant()` — deterministic reduction over entities, views and `coverage_for()`; Postgres test that the profile is a pure function of the tenant's rows (two tenants, no leakage) |
| 33.23 | `propose_conventions()` → `ConventionProposal`; migration `a1b2c3f33003` (`convention_proposal`); **proposals surface as Today lines** with `POST /today/{id}/accept` · `/edit` · `/reject`, writing to `ExtractionTemplate.rules` (`models.py:682` — mind the `tenant_id/vendor_name/flow_direction` unique constraint) or `TenantChatRule` (`models.py:868` — `category` must be one of `services/chat_rules.py::CHAT_RULE_CATEGORIES`) with `source="atlas"` (the new column from 33.7); the Trainer UI only lists the resulting rule; rejection routed through `learn()` |
| **33.28** | **Questionnaire definition + store** (ruling 1, §3.7): `services/tenant_profile_rules.py` (new) — `ROUTINE_QUESTIONS`, the **six** questions with the chip vocabularies exactly as §3.7 lists them (`payment_run`, `po_before_invoice`, `invoice_approval`, `month_close_day`, `collections_owner`, `approval_threshold`); each answerable by **chip or free text**, each **skippable**, a skip persisted as `skipped`. `save_routine_answer(tenant_id, key, value, source, db_session)`, `routine_answers(tenant_id, db_session)`. **Store: the new `tenant_profile_rule` table** (migration `a1b2c3f33001`) with `source="atlas_onboarding"` — **ruled 2026-09-15 (default, founder to override)**: do **not** stretch `TenantChatRule` and do **not** add questionnaire keys to `services/chat_rules.py::CHAT_RULE_CATEGORIES`. `collections_owner` stores a `User` id when the picker is used and a string when the free-text fallback is; `approval_threshold` defaults to `ANALYST_APPROVAL_THRESHOLD_DEFAULT` (₹1,00,000, tenant currency) |
| **33.29** | **Questionnaire delivery** (ruling 1): `next_routine_question(tenant_id, path, db_session)` + `GET /today/questionnaire` and `POST /today/questionnaire/answer` in `routers/today.py` — **one question per call**, chip · free text · `skip`. Two **distinct, separately tested** entry points driven by the FE's `PathChoice`: **Setup path → first login**; **Ingest path → immediately after the first Discover**, never at login. Plus `GET /today/routine-answers` and `PATCH /today/routine-answers/{key}` for the Trainer's read/edit surface (FE 22.27) |
| **33.30** | **Questionnaire effects on Today** (ruling 1): five deterministic consumers in `queue_worker/analyst_handlers.py` / `agents/capabilities.py` — (a) `payment_run` groups payables `TodayItem`s by payment-run day; (b) `po_before_invoice="materials_only"` emits one line per materials invoice with no resolved PO; (c) `invoice_approval` + `approval_threshold` emits a "pending sign-off" line per invoice above the threshold; (d) `month_close_day` emits a month-close countdown line; (e) `collections_owner` addresses overdue-receivable lines to that owner. **All deterministic (Hard rule 3)** — the model may narrate them, never decide them |
| **33.31** | **Contradiction-driven re-ask** (ruling 1): `detect_routine_contradiction(tenant_id, db_session) -> list[str]` over payment facts and PO coverage (answered `month_end` but median payment day is 14; answered `always` for POs but 60% of invoices resolve to none). A contradicted key is re-asked **exactly once**, with the contradicting evidence attached. **Only a contradiction re-asks** — the weekly job never does |
| **33.36** | **Credit-note convention + card** (ruling 7): register a `ConventionProposal` kind `auto_apply_credit_notes` in `propose_conventions()`, triggered when credit-note attachments exceed the threshold share of invoices. `card_net_position` (`services/attachment_insights.py:952`) already handles the CN bubble — **verify** it fires for `BHF-CN-2010` against BHA-2003 and register it in `CAPABILITIES` under the credit-note path. **Do not build Feature 31's lifecycle** |
| **33.38** | **Demo generator: June + July statements** (ruling 8): `showcase/vpi_demo/make_financial_docs.py::bank_statement()` gains June-2026 and July-2026 statements beside the existing `BankStatement_HDFC_4471_Aug2026.pdf`, with opening/closing balances chaining **Jun → Jul → Aug** and the recurring lines (salary, GST, electricity, AMC, bank charges) present in all three, so `detect_recurrence()` and the `estimated` tier have ≥3 months of depth. **Aug's existing lines and its 355,336.00 closing balance must not change** — assert byte-stability of the Aug PDF before and after. Deterministic generator. The README rewrite is business-analyst's, not this task |
| 33.24 | `handle_analyst_onboarding_run()` (`scope.kind="onboarding"`): triggered **after the first ingest batch settles** (`ANALYST_ONBOARD_MIN_DOCS` extractions complete), not on first login; material-coverage-change re-trigger (debounced per 33.33); first `TodayItem` set with the per-item "why it ranks here" gated sentence |
| 33.21 | Eval: `benchmarks/analyst_golden.json` — the **eleven** `showcase/vpi_demo` §5 scenarios (turn 11 added by 33.40) with expected findings **and expected NOT_CHECKED items**, plus five tenant-scope weeks; `scripts/run_analyst_eval.py`, following the `scripts/run_insight_eval.py` shape. Ground truth is business-analyst's `docs/atlas_vpi_scenario_day1_30.md`, which lands before this task |
| **33.40** | **Demo turn 11 in the eval set** (ruling 7): extend `benchmarks/analyst_golden.json` from ten to **eleven** attachment scenarios; turn 11 = `inbound_creditnote_BharatHardware_BHF-CN-2010.pdf` with the expected `card_net_position` bubble against BHA-2003 plus the `auto_apply_credit_notes` proposal. Folded into 33.21's run |

**Checkpoint C** — full backend suite on real Postgres. Slice C's internal order: 33.22, 33.23, 33.28, 33.29, 33.30, 33.31, 33.36, 33.38, **then** 33.24, **then** 33.21 + 33.40.

### 6.1 Sequencing and checkpoints across specialists (ruled 2026-09-15)

| # | who | what | gate to pass |
|---|---|---|---|
| 0 | senior-dev (BE) | **the spec rewrite only** — this amendment applied to both specs and both trackers, no code | founder reads the diff and approves the build |
| 1 | senior-dev (BE) | verify the Feature 30 prerequisites (Gap 477 → 30.19 → 30.20) actually landed | if not, stop and surface it — Slice B's cards depend on them |
| 2 | senior-dev (BE) | **Slice A** — 33.7, 33.39, 33.8, 33.9, 33.10, 33.11 | **Checkpoint A: full BE suite on real Postgres** (per-task runs stay narrow) |
| 3 | infra-devops | `caj-analyst-weekly-${environment}` job bicep + every `ENABLE_*` env var (BE Gap 524's precedent) + Redis reachability for the cooldown/debounce keys; dev only, `params.prod.json` untouched | `az deployment` on dev succeeds, job visible, one manual execution completes. May run in parallel with Slice B; needed before 33.16 is verifiable |
| 4 | senior-dev (BE) | **Slice B** — in the four sub-sequences above | **Checkpoint B: full BE suite on real Postgres** |
| 5 | senior-dev (FE) | **FE L1 + L2** — 22.1–22.11, 22.17, 22.18, 22.19, 22.20, 22.21, 22.23, 22.24, 22.25, 22.26 | **FE checkpoint 1:** `tsc --noEmit` exit 0, `vitest run` green, Playwright on the touched specs |
| 6 | senior-dev (BE) | **Slice C** in its internal order | **Checkpoint C: full BE suite on real Postgres** |
| 7 | business-analyst | `docs/atlas_vpi_scenario_day1_30.md` + the `showcase/vpi_demo/README.md` rewrite (can start after step 0, must finish before step 9) | founder reads it; it becomes 33.21 / 33.40's ground truth |
| 8 | senior-dev (FE) | **FE L2 remainder + L3** — 22.22 (needs 33.29), 22.27, 22.12, 22.13, 22.14, 22.15, 22.16 | **FE checkpoint 2:** `tsc --noEmit`, full `vitest`, full Playwright incl. 22.16 screenshot regression in both themes |
| 9 | functional-tester | **the VPI demo E2E** on a real stack — Day 1 → Day 30 against the scenario document, plus all 17 README §6 SAGE questions re-asked post-ATLAS as the regression contract | founder reviews; this is the acceptance gate for §9's walkthrough |

Per-task discipline: run **only** the affected test file per task; the full backend suite is reserved for the three slice checkpoints. Every step ends **uncommitted**, visible in the Changes panel.

## 7. Verification plan

Hard rule 3 applies throughout: every number, match, tier, rank and coverage figure is deterministic code with a test; the model's output is validated against a schema and gated, never trusted. Hard rule 2: every task touching Postgres cites a real-Postgres run.

| task | proves it |
|---|---|
| 33.1 | a planned call naming an unregistered capability is dropped and logged; a call failing `input_schema` is dropped; every registered Feature 30 card is reachable by name |
| 33.2 | Postgres: PO-VPI-1041 resolves to Rajesh + RAJ-2008/2009 + PO-linked items; a GST circular fixture resolves to tax-rate + HSN and to nothing else; a random PDF resolves to an empty graph. **No substring matching**: a vendor "Steel Corp" does not resolve from "Rajesh Steel Corporation" (Gap 513's test, inverted) |
| 33.3 | flag off → byte-identical `build_insight_block()` output on the Feature 30 fixtures; flag on, planner off → same cards via `plan_by_rule()` |
| 33.4 | planner on with a fake LLM returning one invented capability and two valid ones → two executed, one logged; the planner prompt contains no document text (assert on the payload) |
| 33.5 | a finding above threshold triggers ≤ `follow_ups` further calls; a contradicting follow-up lowers confidence and the reason names the evidence |
| 33.6 | a six-sentence briefing where sentence 3 carries an unsupported figure → sentence 3 is the template, the other five are the model's; nothing dropped |
| 33.7 | **PG:** migration applies on `upgrade head`; single head; `action_log` / `fact` / `today_item` / `input_request` / `tenant_profile_rule` present, and `tenant_chat_rules.source` + `user.ui_prefs` present |
| 33.8 | Postgres: a challan emits `delivery_event` facts per line; a PO emits `commitment`; a statement emits `payment_event` per matched line and `balance_on_date`; a budget sheet emits `budget` facts per account/period; **hard-deleting** the attachment deletes every fact in the same transaction (count before / after) |
| 33.9 | TTL job on an expired attachment → row gone, facts present (the Q1 ruling); the same attachment hard-deleted → row and facts both gone |
| 33.10 | views return only rows at or below the caller's clearance; `v_period_accounts` / `v_budgets` return per-currency rows with no conversion |
| 33.11 | **per path**: an `ops` caller listing sessions, reading a message, streaming an attachment, calling `facts_for`, `query_metric`, Today, RAG retrieval — never receives an `exec` row; a test per path, and a meta-test that every router function taking `tenant_id` also takes `clearance` (grep-shaped, the Gap 341 lesson). **By role**: a second Admin *does* see the first Admin's exec session (the Q3 ruling, asserted, not a leak). **Option C**: after an exec statement is matched, an `ops` caller sees the invoice's `payment_event` fact and never the statement row, the salary line or the loan line |
| 33.12 | coverage on the VPI demo: `bank_statements` absent → `forecast` capability is `NOT_CHECKED` → one `InputRequest` whose `unlock_value` equals the sum of committed + certain lines it would unlock; Postgres |
| 33.13 | certain + committed on the VPI data: ₹8,52,561.80 payable, ₹4,37,190 committed on PO-1041 less invoiced; `scenario("Kaveri +20 days")` moves exactly the Kaveri receivables; a two-currency tenant returns two forecasts and no blended total; `project_pnl()` returns a tiered projection over the same horizon |
| 33.14 | **PG:** the **new three-month Jun/Jul/Aug series generated by 33.38** (not a synthetic stand-in): salary detected at period 30 ± tolerance; a 2-month slice → `estimated` is `NOT_CHECKED("needs N months")` |
| 33.14a | with `period_accounts` and `budgets` on file: each of the five FP&A capabilities returns figures matching a hand-computed fixture. With the kind absent: each returns `NOT_CHECKED` **and** exactly one `InputRequest` — and the rendered card is never empty |
| 33.15 | Postgres: three short deliveries and one over-billing for one vendor → one rolled-up finding with severity `high`, ranked above a ₹500 rounding finding (Gap 519's test) |
| 33.16 | job fixture: one tenant, one run, `today_item` rows written, `today_updated` published |
| 33.17 | `POST /today/{id}/open` returns a session whose first message is the seeded question; another tenant's item → 404; `/dismiss` sets `cleared_at` and the line is absent from the next `GET /today`; `/scenario` on a forecast line returns the recomputed line with no model call |
| 33.18 | while FE 22 is unshipped: `GET /dashboard/insights` still returns its four aggregates, as **template text with no LLM call** (assert no completion is issued); after FE 22 ships the endpoint is gone → 404. The four aggregates answer as capabilities with the same figures the old handler computed (fixture) |
| 33.19 | a kind dismissed `ANALYST_SUPPRESS_AFTER` (3) times by one tenant is suppressed for that tenant only; a dismissal is recorded through `learn()` |
| 33.20 | a SAGE turn on the VPI fixture never calls `run_analyst`; `run_analyst` never calls `query_tools` SQL |
| 33.21 | **PG:** the **eleven** §5 scenarios: every expected finding present, every expected `NOT_CHECKED` present, **zero** findings on rows the README says are clean; deterministic set comparison, not the judge (Gap 484's rule) |
| 33.22 | `profile_tenant()` on two seeded tenants (India GST + US) on Postgres: each profile lists only its own doc types, counterparties and currencies; re-running on unchanged rows returns an identical profile (pure function); a tenant with no rows returns an empty profile with every `INPUT_KINDS` entry absent, not an error |
| 33.23 | seeded 47-day median payer → a `default_terms` proposal whose evidence names the counterparty and the figure; the proposal appears as a `TodayItem`; `POST /today/{id}/accept` writes the rule to `ExtractionTemplate` (vendor scope) with `source="atlas"` and nothing else; `/reject` suppresses it via `learn()` and it does not reappear on the next run; `/edit` persists the edited text; the Trainer's rule list then shows that rule and offers no second accept affordance; proposals from tenant A never appear for tenant B |
| 33.24 | the onboarding run fires **once**, on the extraction that reaches `ANALYST_ONBOARD_MIN_DOCS` — not on first login (a login before the threshold triggers nothing, asserted); a second settle triggers none; adding a first `BANK_STATEMENT` re-triggers Discover; the first `TodayItem` set carries one gated sentence per item, and a sentence the gate rejects falls back to the template with the item still ranked |
| 33.25 | every action in `ACTIONS` has `kind="action"`, a non-empty `roles`, and an `fn` that resolves to an existing endpoint/service (registry test); with `ENABLE_ANALYST_ACTIONS` off no action is ever planned |
| 33.26 | a confirmed action executes its target **exactly once** (call counted on a spy) and writes exactly one `action_log` row with tenant, user, capability, args and result; a failing target leaves the line in an error state, writes the failed result, and does not retry |
| 33.27 | **role gate, Postgres**: an Auditor confirming a setup action → 403 and the target never called; an Admin confirming the same action → target called once and one `action_log` row. Nothing in the loop executes an action without a confirm event (a full tenant run with actions planned writes zero `action_log` rows) |
| **33.28** | **PG:** the six questions' chip vocabularies are exactly as §3.7 lists them; a **skip** is recorded as `skipped` and the question is **not re-asked**; an answer writes exactly one `tenant_profile_rule` row with `source="atlas_onboarding"` and the unique `(tenant_id, key)` holds on re-answer (update, not a second row); `collections_owner` stores a `User` id from the picker and a string from the fallback; `approval_threshold` defaults to 100000 when skipped |
| **33.29** | **PG:** one question per call, in order; **Setup path** fires at first login; **Ingest path** fires immediately after the first Discover and **not** at login; both entry points tested separately; `GET /today/routine-answers` returns the tenant's six and `PATCH` edits one without creating a duplicate |
| **33.30** | **PG:** each of the five effects, one test each — payables grouped by the answered payment-run day; a materials invoice with no resolved PO gets **exactly one** line while a services invoice gets **none**; an invoice above the answered threshold shows pending sign-off and one below does not; the month-close countdown matches the answered day; an overdue receivable line names the answered collections owner. **Every figure traced to deterministic code — assert no model call** |
| **33.31** | **PG:** answered `month_end` with a seeded 14-day median → the key is re-asked **once**, with the contradicting evidence attached; a consistent tenant is **never** re-asked; the weekly job alone never re-asks |
| **33.32** | **PG + Redis:** Admin `POST /today/run` enqueues once; a second call inside 10 min → **429** with `retry_after_seconds`; after the window → enqueues again; a non-Admin → **403** |
| **33.33** | **PG + Redis:** two material coverage changes inside one hour → **exactly one** Discover run; the second is logged as suppressed and **not** queued for later |
| **33.34** | fixture: "upload my invoices" yields an `attach_prompt` bubble with the correct target and the accepted extensions from `_accepted_content_types()`; **no new upload endpoint is called**; nothing in the loop touches the filesystem |
| **33.35** | **PG:** every rendered input request names an **exact document kind** and a **quantified figure** — asserted over **all eleven `INPUT_KINDS`**, with no generic placeholder; emitted on **Day 1**, in the **weekly run** and in an **attachment bubble**, each asserted separately. Extends 33.12's `unlock_value` assertion rather than replacing it |
| **33.36** | **PG:** `BHF-CN-2010` attached produces a `card_net_position` bubble against BHA-2003 with the correct net figure, plus an `auto_apply_credit_notes` proposal; **no `Invoice` row is written and no aggregate moves** (D2 / D3 still hold) |
| **33.37** | **PG:** below 10 docs `GET /today` returns `pre_onboarding` with `docs_seen` / `docs_required` and **zero** findings; at 10 it flips. A non-Admin on a populated tenant gets the same ranked list minus the owner-facing lines (payment-run grouping, sign-off, setup actions, conventions, cash / FP&A) and **no separate section set** |
| **33.38** | fixture: the three generated statements chain balances **Jun → Jul → Aug** and each carries the recurring lines; regeneration is **byte-deterministic**; the **Aug PDF is byte-identical before and after** (closing balance 355,336.00 unchanged) |
| **33.39** | **PG:** `PATCH /me/preferences` persists **per user, not per tenant** (two users in one tenant with divergent values); an unknown key is rejected; `GET` returns the defaults for a user who has never set one |
| **33.40** | **PG:** the eleven-scenario eval — every expected finding present, every expected `NOT_CHECKED` present, **zero** findings on rows the README calls clean; deterministic set comparison, **not** the LLM judge (Gap 484's rule) |
| **E2E** | **the VPI demo is the end-to-end.** Full `showcase/vpi_demo/README.md` run on a real stack (real Azure DI + real Azure OpenAI + real Postgres): §2 steps A→D including **turn 11**, then the §5 attachment turns, then §6's 17 chat questions re-asked **post-ATLAS** to prove SAGE did not regress, then the Today surface across **Day 1 → Day 30** against `docs/atlas_vpi_scenario_day1_30.md` |

Evidence for every row above is filed by functional-tester under `docs/test_evidence/f33_atlas_<date>/` and linked from `docs/test_coverage_map.md`, never pasted inline.

## 8. Open decisions — founder

**All nine closed in the founder interview, 2026-09-15.** Original questions kept verbatim; the ruling follows each.

1. **Facts persist after the document expires (§4).** This revises Feature 26's implicit "an attachment leaves nothing behind" while keeping D2 (no `Invoice` row) and D3 (no quota). Yes / no?
   **Ruled 2026-09-15:** yes. The `Document` / attachment row expires on TTL; its `Fact` rows stay. A user-initiated **hard delete** still cascades to the facts in the same transaction (`feedback_delete_means_hard_delete`). §4, tasks 33.8 / 33.9.
2. **Sharing rule — Option C (§5).** Derived facts about records operations can already see flow down as `ops`; source rows and non-invoice lines stay `exec`. Yes, or strictly private, or share-whole-document on request?
   **Ruled 2026-09-15:** Option C. A payment fact on an invoice ops can already see flows down as `ops`; the statement itself and every non-invoice line (salary, loan, charges) stay `exec`. §5, task 33.11.
3. **Clearance by role or by person?** By role: every Admin sees every exec session. By person: the owner's statement is the owner's. Role is simpler; person is what "not seen by others" literally says.
   **Ruled 2026-09-15:** **by role.** Every Admin holds `exec`; Auditor and Trainer hold `ops`. **No Executive role is added.** One Admin seeing another Admin's private session is accepted. §5, task 33.11.
4. **Planner on for this feature?** It adds one model round-trip per run. Feature 30 task 30.16 deferred it pending Feature 29's 100-turn calibration. Turn it on for tenant scope only (weekly, latency irrelevant) and leave attachment scope on `plan_by_rule()` until calibrated?
   **Ruled 2026-09-15:** on for **tenant and onboarding** scopes; attachment scope stays on `plan_by_rule()` until Feature 29 CP2 calibration. §2 `plan()`, task 33.4.
5. **Bank statements as a standing input.** Email-in / connector ingest for statements, monthly, rather than chat attachment — so the forecast has a regular feed with no manual step. Build the ingest path in this feature, or leave it as an onboarding input request (§3.7) the owner fulfils by hand?
   **Ruled 2026-09-15:** chat attachment only in v1; **no ingest door is built**. Statement **staleness becomes an input request** (§3.5), ranked like any other. §3.5, task 33.12.
6. **Feature 29 §12 — the gate validates figures, not claims.** This feature inherits it. Accept for v1 (findings carry evidence the reader can check) or block tenant-scope narration on a claim-level verifier first?
   **Ruled 2026-09-15:** accept the figures-only gate for v1; the claim-level verifier is **deferred**, not part of this feature.
7. **Scope statement.** "AP/AR + cash intelligence for an SMB" — or full FP&A (P&L, margin, budget variance tiles)? `period_accounts` facts make the second possible; the first is what invoices + statements support today.
   **Ruled 2026-09-15:** **full FP&A.** Capabilities `pnl_by_period`, `margin_per_customer`, `margin_per_item`, `budget_variance_per_account`, `expense_category_trend`; new `budget` fact kind and `emit_budget` emitter over the existing `budgets` input kind; forecast gains a P&L projection line alongside cash runway. Each FP&A card is `NOT_CHECKED` → input request until its input kind is present — **never an empty tile.** §3.4, §3.5, tasks 33.8 / 33.13 / 33.14a.
8. **Agent name.** `<AGENT_NAME>` throughout; SAGE is the precedent.
   **Ruled 2026-09-15:** **ATLAS.** Every placeholder replaced across this spec, FE Feature 22 and both tracker entries; ATLAS pairs with SAGE; the name is authored in a new `agents/atlas_prompts.py` (mirror of `sage_prompts.py`), listed in §2. Task 33.20.
9. **Onboarding cadence (from the former Feature 32).** §3.7 proposes one mechanism at two cadences: a first-login scan, re-run on material coverage change. Accept, or first-login only, or continuous on every weekly run?
   **Ruled 2026-09-15:** Discover runs **after the first ingest batch settles** — `ANALYST_ONBOARD_MIN_DOCS` (default 10) extractions complete — **not on first login**; re-runs on material coverage change (new doc type, vendor cluster, currency). First login is the welcome / checklist / tour instead (FE Feature 22). §3.7, task 33.24.

### 8.1 Defaults ruled by non-objection, 2026-09-15

| decision | ruling |
|---|---|
| multi-currency | forecast and rollups **per currency**, no conversion, no blended base currency |
| weekly job time | **Monday 06:00 UTC**; tenant-local scheduling deferred |
| Gap 30 dashboard panel | keeps returning its four aggregates as **template text** (no LLM call) until FE Feature 22 ships; removed with the FE panel then (task 33.18) |
| Today line lifecycle | clears when the finding resolves or the owner dismisses it; a dismissal feeds `learn()` |
| suppression threshold | `ANALYST_SUPPRESS_AFTER`, default **3** |
| attachment budget | `follow_ups = 1` (`ANALYST_ATTACHMENT_FOLLOWUP_BUDGET`) |
| new Today routes | `POST /today/{id}/dismiss`, `POST /today/{id}/scenario` (plus `/accept`, `/edit`, `/reject` from §3.7 and `/confirm` from §3.8) |
| actions | never autonomous in v1; confirm-then-execute only, role-gated, every execution logged |
| `AnalystScope.kind` | `"attachment" \| "tenant" \| "onboarding"` — §2's two-kind annotation was an inconsistency, fixed |

### 8.2 Walkthrough rulings, 2026-09-15 (second interview)

Provenance in one lookup — each ruling, where it is specified, and which tasks implement it.

| # | ruling | spec section | tasks |
|---|---|---|---|
| 1 | **Routine questionnaire** — six questions asked once, chip or free text, skippable, stored as `tenant_profile_rule` rows, edited in the Trainer, re-asked only on contradiction, five deterministic Today effects | §3.7 *Ask the owner* | 33.28 – 33.31 (FE 22.22, 22.26, 22.27) |
| 2 | **Admin "Run now"** — immediate tenant-scope run, Admin-only, once per 10 min per tenant, 429 with `retry_after_seconds` | §3.3 | 33.32 (FE 22.23) |
| 3 | **Discover debounce** — material coverage change re-runs Discover at most once per hour per tenant; a suppressed re-trigger is logged, not queued | §3.7 *Cadence* | 33.33 |
| 4 | **Upload mechanics** — browser-native file picker to the existing endpoints; a typed request yields an `attach_prompt` bubble; ATLAS never opens the disk; the Ingestion page stays under Records | §3.9 | 33.34 (FE 22.24) |
| 5 | **Input-request phrasing** — exact document kind + quantified unlock, one template per `INPUT_KINDS` entry, three asserted moments | §3.5 | 33.35 (amends 33.12) |
| 6 | **Classic layout** — per-user switch to the existing sidebar nav plus a `Today` item, landing `/dashboard`; switch beside the theme toggle in the header; persisted through `/me/preferences` | FE §1 / §3.4 | FE 22.21, BE 33.39 |
| 7 | **Credit note is demo turn 11** — `card_net_position` bubble against BHA-2003 plus an `auto_apply_credit_notes` proposal; Feature 31 stays cancelled | §3.7 *Propose* | 33.36, 33.40 |
| 8 | **June + July statements + README rewrite** — three-month series so `recurring` / `estimated` can light up; Aug untouched | §2, 33.38 | 33.38 (README is business-analyst's) |
| 9 | **Onboarding threshold + pre-onboarding Today** — below `ANALYST_ONBOARD_MIN_DOCS`, `GET /today` returns `pre_onboarding` and nothing else | §3.10 | 33.37 (FE 22.25) |
| 10 | **Non-Admin first login** — welcome + short tour only | FE §3.2 | FE 22.14, BE 33.39 (`first_run_seen` / `tour_seen`) |

### 8.3 Founder defaults recorded 2026-09-15 — the architect's five open questions

Each answered as the working default. **"Ruled 2026-09-15 (default, founder to override)"** — build against these; they are not guesses to be re-opened mid-build, but the founder may reverse any of them.

| # | question | ruling |
|---|---|---|
| 1 | questionnaire store | **New small table `tenant_profile_rule`** (`id`, `tenant_id`, `key`, `value` JSON, `source`, `created_at`, `updated_at`) in the same add-only migration. **Do not stretch `TenantChatRule`** and do not add questionnaire keys to `CHAT_RULE_CATEGORIES`. The Trainer lists these rows read/edit. §3.7, 33.28 |
| 2 | approval threshold | a **sixth question**, `approval_threshold`, default **₹1,00,000 in tenant currency** (`ANALYST_APPROVAL_THRESHOLD_DEFAULT`). Not derived from observed invoice sizes. §3.7, 33.28 |
| 3 | collections owner | a **user picker bound to a `User` row**, so the line can address a real person; **free text is an accepted fallback**. §3.7, 33.28 |
| 4 | classic layout retirement | the toggle **stays indefinitely**; **no retirement date and no trigger**. FE §1 / §3.4, FE 22.21 |
| 5 | non-Admin Today | the **same ranked list**, filtered server-side by clearance and role; owner-facing lines (payment-run grouping, sign-off, setup actions, conventions, cash / FP&A) hidden; **no separate section set**. Closes FE Feature 22 §7 Q4. §3.10, 33.37 |

## 9. Founder interview 2026-09-15 — the approved user experience

The six steps below are the walkthrough the founder approved. They are the acceptance narrative for slices A→C: if the built system does not read like this, the build is wrong, not the spec.

1. **First day.** The org creator (Admin) signs in and gets a welcome message, a setup checklist, a short app tour, and a choice of path — *set up first* or *ingest documents first*. Invited non-Admin users get the welcome and the tour only. No Discover run, no profile, no analysis: nothing has arrived yet. **Amended 2026-09-15:** the path choice now leads into the **routine questionnaire** (§3.7 *Ask the owner*) — *Set up first* starts it immediately; *Ingest documents first* starts it right after the first Discover completes. Today itself shows only "upload to begin" with the document count until the threshold (§3.10).
2. **Today, weekly.** Once documents are flowing, ATLAS runs Monday 06:00 UTC and every login lands on **Today** — a ranked list of lines that each expect one action: a finding to decide, a due date, an input to attach, an action to confirm. A line clears when its finding resolves or the owner dismisses it; a kind dismissed three times stops coming back. **Amended 2026-09-15:** an Admin can also run it **on demand** — `POST /today/run`, once per 10 minutes per tenant (§3.3). A non-Admin sees the same ranked list with the owner-facing lines filtered out (§3.10).
3. **Chat attachment, resolve-first.** A user attaches a PO, challan, statement or price list in Ask. ATLAS resolves it against what is on file *first* — vendors, invoices, items, bank lines — then plans which checks to run from what it resolved to, not from the document's type. A document that resolves to nothing is told so; it is never silence. The document may expire; the facts it left stay.
4. **Private documents.** An Admin attaches a bank statement or P&L to a private (`exec`) session. Operations never see the statement, the salary line or the loan line; they do see the **payment fact on an invoice they already had** — "paid 06-Aug, UTR …". Clearance is by role: every Admin holds `exec`.
5. **Conventions on the agent's screen.** After the first ingest batch settles, ATLAS profiles the business and proposes its conventions as Today lines — "Rajesh Steel is paid at 47 days; set default terms to NET 45?" — answered right there with **Accept / Edit / Reject**. The accepted rule is written into the existing rule store with `source="atlas"`; the Trainer simply shows it as a rule it holds. Nobody is sent to a second screen to configure what was just explained. **Amended 2026-09-15:** the **six routine answers** are given the same way — one question at a time on the agent's screen, chip or free text or `Skip` — and the Trainer lists them for read/edit beside the hand-written rules.
6. **Forecast and FP&A.** The owner sees cash runway by tier (certain / committed / recurring / estimated, each with its data depth) alongside a P&L projection, per currency, with margin, budget variance and expense-trend cards beside them. Any card whose input is missing says what to attach and what it would unlock — an FP&A tile is never blank, and ATLAS never produces a number the tools did not compute. Every such request names an **exact document kind** and a **quantified unlock** (§3.5), never "more data".
7. **Getting documents in (added 2026-09-15).** `Upload` and `Attach` are the browser's own file picker, posting to the endpoints that already exist. ATLAS never opens the disk. Asking for it in words — "upload my invoices" — produces a **button**, not a directory listing (§3.9).
