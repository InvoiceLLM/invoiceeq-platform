# Feature 33 — The Analyst Agent (`<AGENT_NAME>`): one investigative loop at two scopes — the chat bubble and the owner's intelligence

**App:** invoice-be (+ FE counterpart `apps/invoice-fe/docs/feature_22_today_ask_records.md`) · **Status:** lives in `be_features_tracker.md` · **Depends on:** `feature_30_business_intelligence.md` (§11 tasks 30.19 / 30.20 — the three-state check result and the claim renderer are prerequisites, not part of this feature), ~~`feature_31_credit_debit_notes.md`~~ (cancelled 2026-09-14: only invoices are ingested, by user training; notes / proformas / receipts arrive as chat attachments, whose Feature 30 cards this agent plans over), `feature_29_llm_optimisation.md` (L3 planner, the answer-contract gate, §12's open L1 decision), `feature_26_chat_attached_documents.md` (rulings D2 / D3, revisited in §4). **Absorbs the former Feature 32 placeholder (founder 2026-09-14):** business-profile discovery and guided configuration are this agent's onboarding scope, §3.7 — one agent gets to know the business, then helps it see its priorities.

**Agent name.** `<AGENT_NAME>` is a placeholder throughout — founder 2026-09-10: "just keep a placeholder for the name in feature". The only persona name in the codebase today is SAGE (`agents/sage_prompts.py`); the extraction, trainer and support agents are file names. Whatever name is chosen replaces the placeholder in one pass; nothing in this spec depends on it.

**Founder framing, 2026-09-09/10 (the spec is written to this):**
- "this application was primarily built to extract invoice pdf and show its problem for audit and answer in chat … we are extracting data without manual intervention, we are creating knowledge bank by answering questions not asking user to see details in screen, now we want to give them intelligence to help them understand the business. **data → knowledge → intelligence using LLM and agentic AI**."
- "chat is for regular users and intelligence is for higher authority to make better decisions."
- "few attached documents are at low level users also like PO, challan … they should also get the intelligence of recon; few documents are needed for company level insights which can be given by higher authorities … the higher authority can go to chat, attach document and get the insight and if needed make more chat to get better suggestions."
- "will the system be able to get so smart from just seeing bunch of invoices over time, since all other docs are just attached in chat area" → no, not as built; the fix is §4.
- "the business intelligence part is not happening through any agent" / "for the bubble chat as well as business insight this agent will be utilised" → one agent, two scopes (§3).
- "already there are too much complicated application with so many screens" → FE counterpart, Feature 22.

## 1. Overview

**What this is.** One agent loop — *observe → plan → act through deterministic tools → investigate → say through the answer-contract gate → ask for what is missing → learn* — invoked at two scopes:

| Scope | Trigger | Observes | Produces | Audience |
|---|---|---|---|---|
| **attachment** | a document is attached in chat (Feature 26 path) | this document + everything on file it resolves to | the insight bubble — Feature 30's bubble, now planned rather than dispatched by doc type | whoever attached it |
| **tenant** | scheduled (weekly) + event-driven (a statement lands, a deviation crosses a threshold) | everything that arrived since the last run, open findings, the business profile | the owner's **Today** lines and briefing; input requests | Admin (§6) |
| **onboarding** (§3.7) | first login, and again whenever coverage changes materially (a new doc type, vendor cluster or currency appears) | everything on file for the tenant, read as a whole | the **business profile** (`BusinessProfile`), a ranked list of proposed conventions for the Trainer, and the first priorities list | Admin |

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
| Forecast | none | four labelled tiers: certain / committed / recurring / estimated (§3.4) |

**What this is not.**
- Not SAGE. SAGE answers a question about records the user asked; `<AGENT_NAME>` investigates and advises, unprompted or from a launch point. The boundary is stated in §3.6 and tested.
- **Formerly split from Feature 32 — merged 2026-09-14, founder ruling** ("the analyst agent is for getting the user's business profile along with helping the user understand priorities better"). Discovering the tenant's conventions, proposing them, and consuming the accepted profile at runtime are one loop with one owner (§3.7); a second spec would have described the same `observe()` over the same data.
- Not a dashboard. Founder ruling stands (`project_dashboard_is_workbook_not_inapp`): operational monitoring is Azure Workbooks. Today (FE Feature 22) is a ranked list of things that expect an action, not a metrics page.
- Not a second BI system. The card engine, `Insight` table, thresholds, semantic views, bank ledger and matcher, entity resolver, doc linking and the gate are all **reused**. This feature adds a loop, a planner call, a facts ledger, a scope predicate, a dependency table and a forecast engine — and removes one LLM-authored panel.
- Not multi-agent. Feature 29 §4.3's progression is router → planner → verifier → multi-agent; this feature is the planner and the first verifier-shaped behaviour (investigate before you speak). It does not orchestrate agents.

## 2. File coordinates

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `agents/analyst_agent.py` | `run_analyst(scope: AnalystScope, db_session, budget: Budget) -> AnalystResult` | new | the loop. `observe()` → `plan()` → `act()` → `investigate()` → `say()` → `ask()`; each a named function below; never raises into a caller |
| `agents/analyst_agent.py` | `AnalystScope` (dataclass: `kind: "attachment" \| "tenant"`, `tenant_id`, `clearance`, `attachment_id \| None`, `since: datetime \| None`, `profile: BusinessProfile`) | new | what one run is about; every tool call carries it |
| `agents/analyst_agent.py` | `observe(scope, db_session) -> Observation` | new | attachment scope: the row's extracted JSON + `resolve_overlap()`. tenant scope: arrivals since `scope.since`, open findings, profile, coverage from `coverage_for()` |
| `agents/analyst_agent.py` | `plan(observation, scope, llm) -> Plan` | new | **the one planning call.** Given the overlap graph / arrivals and the capability registry, returns an ordered list of `(capability, args)`; validated against `CAPABILITIES` — a capability the model invents is dropped and logged, never executed. Behind `ENABLE_ANALYST_PLANNER`; when off, `plan_by_rule()` — the Feature 30 type-keyed tuple at attachment scope, a fixed question set at tenant scope |
| `agents/analyst_agent.py` | `act(plan, scope, db_session) -> list[InsightCard]` | new | executes each capability in order through the registry; `BLOCKED` on exception, the rest still run (Feature 30 shape) |
| `agents/analyst_agent.py` | `investigate(cards, scope, db_session, llm, budget) -> list[InsightCard]` | new | for each finding above `threshold("investigate_min_amount")` the model may request up to `budget.follow_ups` further capabilities ("check this vendor's other POs", "check payment history") and attach the results as evidence. Same registry, same validation. This is the agentic step Feature 29 staged as "verifier" |
| `agents/analyst_agent.py` | `say(block, scope, llm) -> Narration` | edit of `narrate_insight_block()` | tenant scope narrates a briefing (several sentences, each gated separately); attachment scope is the one-line verdict as today. `_answer_contract_gate()` per sentence; a rejected sentence is replaced by its finding's template text, never dropped silently |
| `agents/analyst_agent.py` | `ask(observation, block, scope) -> list[InputRequest]` | new | from `missing_inputs()`: what could not be computed, which input unlocks it, ranked by `unlock_value()` |
| `agents/analyst_agent.py` | `learn(result, feedback, db_session)` | new | acted / dismissed per `finding_key` feeds `insight_thresholds` suppression per tenant (a kind the owner always dismisses stops surfacing) and `record_correction()` for narration corrections |
| `agents/capabilities.py` | `CAPABILITIES: dict[str, Capability]`, `Capability(name, fn, input_schema, output_schema, deterministic: bool, needs: tuple[InputKind, ...], scopes: tuple[str, ...])` | new | Feature 29 §4.2's L2 registry, as a dict, not a framework. Every Feature 30 card registers here; so do the semantic-view metrics, the forecast functions and the bank matcher. `needs` is what drives the dependency table |
| `services/overlap.py` | `resolve_overlap(extracted_json, scope, db_session) -> OverlapGraph` | new | the resolve-first gate (§3.2): parties → vendors/customers, doc numbers → invoices/POs, line descriptions → items on file, tax ids → region, amounts+dates → bank lines, tables with periodised accounts → statement shape. Uses `agents/entity_resolver.resolve_entities()`; never a substring match |
| `services/facts.py` | `Fact` model (§4), `emit_facts(attachment_row, extracted_json, overlap, db_session) -> list[Fact]`, `facts_for(subject_kind, subject_id, clearance, db_session)` | new | the facts ledger: what a document asserts, persisted independently of the document |
| `services/facts.py` | `FACT_EMITTERS: dict[str, Callable]` | new | per shape, not per doc type: `emit_commitment` (has agreed lines + counterparty), `emit_delivery_event` (has delivered quantities), `emit_payment_event` (has a settled invoice ref / UTR / matched bank line), `emit_terms` (has rates / payment terms with an effective period), `emit_period_accounts` (has a periodised account table). A document may fire several |
| `services/dependency.py` | `INPUT_KINDS`, `coverage_for(tenant_id, clearance, db_session) -> Coverage`, `missing_inputs(plan_or_capabilities, coverage) -> list[MissingInput]`, `unlock_value(missing, db_session) -> Money \| int` | new | §3.5. Coverage is computed from facts and invoices actually on file (kinds present, months of depth, staleness). `unlock_value` is a count or a sum from the views — never a guess |
| `services/forecast.py` | `forecast(tenant_id, clearance, horizon_days, db_session) -> Forecast`, `Tier = "certain" \| "committed" \| "recurring" \| "estimated"`, `detect_recurrence(facts) -> list[Recurrence]`, `scenario(forecast, change) -> Forecast` | new | §3.4. Pure arithmetic over facts + views; every line carries its tier and its data depth |
| `services/attachment_insights.py` | `build_insight_block()` | edit | becomes `run_analyst(AnalystScope(kind="attachment", …))` behind `ENABLE_ANALYST_AGENT`; the type-keyed tuple survives as `plan_by_rule()`'s attachment branch |
| `services/attachment_extraction.py` | `extract_attachment()` | edit | after matching: `emit_facts()` (always, when `ENABLE_ATTACHMENT_FACTS`) then the analyst run |
| `queue_worker/analyst_handlers.py` | `handle_analyst_tenant_run(tenant_id, trigger: "scheduled" \| "statement_landed" \| "deviation")` | new | tenant scope on the queue; writes `Insight` rows with `scope="tenant"` and a `TodayItem` list; publishes `today_updated` on the tenant channel |
| `infra/` job | `caj-analyst-weekly-dev` | new | Monday 06:00 tenant-local; calls the handler per active tenant. Same shape as `caj-chat-doc-ttl-dev` |
| `routers/today.py` | `GET /today` → `get_today(role, clearance)`, `POST /today/{item_id}/open` → `open_in_ask()` | new | the ranked list for FE Feature 22; `open_in_ask` creates or resumes a session with the item's seeded question and returns its id |
| `routers/dashboard.py` | `get_dashboard_insights()` | **remove** | Gap 30's LLM-authored panel; its four aggregates become capabilities |
| `routers/chat.py`, `routers/chat_attachments.py` | `_require_owned_chat_job()`, session list, attachment read | edit | add the clearance predicate (§5) to every read; deny by default |
| `models.py` | `ChatSession.clearance`, `ChatAttachment.clearance`, `Fact`, `Insight.scope`, `Insight.clearance`, `TodayItem`, `InputRequest` | edit / new | §5 and §4; one add-only migration |
| `services/semantic_views.py` | `query_metric()` | edit | takes `clearance`; the views gain a `clearance` column where they read facts |
| `services/rag_service.py` (or wherever Chroma collections are named) | collection naming | edit | exec-scoped attachments index into `{tenant}_exec`, a separate collection — a wall, not a metadata filter |
| `config.py` | `ENABLE_ANALYST_AGENT`, `ENABLE_ANALYST_PLANNER`, `ENABLE_ATTACHMENT_FACTS`, `ANALYST_FOLLOWUP_BUDGET: int = 3`, `ANALYST_WEEKLY_ENABLED` | edit | all default to today's behaviour (off / 0) |
| `agents/sage_prompts.py` | `PERSONA_BLOCK` | edit | one sentence naming the boundary: SAGE answers about records; investigation and advice are `<AGENT_NAME>`'s, reachable from Today |
| `tests/test_analyst_agent.py`, `tests/test_facts.py`, `tests/test_dependency.py`, `tests/test_forecast.py`, `tests/test_clearance.py` | see §6 | new | |

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

Budgets: attachment scope `follow_ups=1, sentences=1`; tenant scope `follow_ups=ANALYST_FOLLOWUP_BUDGET, sentences=6`. Both are settings.

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

Triggers: the weekly job; `statement_landed` (a bank statement's facts committed); `deviation` (a monthly view crosses `threshold("deviation_pct")`). Event triggers run a narrower plan.

### 3.4 Forecast tiers

`forecast()` returns lines, each with a **tier** and a **depth** (months of data behind it):

| Tier | Source | Example |
|---|---|---|
| certain | due dates on issued invoices | ₹8.5L payable by 15-Sep |
| committed | open commitment facts (PO, contract) | ₹4.4L still to be invoiced on PO-1041 |
| recurring | `detect_recurrence()` over payment facts from statements — same counterparty, period within tolerance, amount within tolerance | salary ≈ ₹14.9L monthly |
| estimated | run-rate / trend from the views, only when `depth >= threshold("estimate_min_months")` | September spend ≈ ₹11L |

Cash runway = balance-on-date (from the latest statement fact) + certain-in − certain-out − recurring, by week. `scenario()` recomputes with one change ("Kaveri pays 20 days late") — arithmetic, no model. Every rendered forecast line names its tier and depth; below the depth threshold the line is `NOT_CHECKED("needs N months")`, which is exactly what `ask()` turns into an input request.

Recurrence is **detected**, never keyword-matched: "salary" is a counterparty with a ~30-day period, learned from the statement and confirmable once in the Trainer (§3.7 Configure).

### 3.5 The dependency table and input requests

Every `Capability` declares `needs: tuple[InputKind, ...]`. `INPUT_KINDS` is the closed set of *what a business can feed the system*: `invoices_in`, `invoices_out`, `purchase_orders`, `delivery_notes`, `bank_statements`, `remittances`, `contracts`, `period_accounts`, `tax_returns`, `loan_schedules`, `budgets`. Rule cards (Feature 30 §10.6) declare needs too — an ITC-reconciliation card needs `tax_returns`.

`coverage_for()` computes, from what is actually on file, per kind: present / absent, months of depth, days since last. `missing_inputs()` intersects the plan's needs with coverage. `unlock_value()` is a real number from the views — "14 invoices with a PO reference and no delivery fact" or "₹18.3L of statement outflows currently invisible" — never a template.

The result is the "To see more" section of Today and the advisor's onboarding prompts (§3.7). The same agent asks at onboarding ("forward invoices here; what matters most to you?"), weekly ("attach last quarter's statement → cash forecast") and in a bubble ("no GSTIN read — attach the tax invoice and I can run the compliance checks"). One mechanism, three moments.

### 3.6 SAGE and `<AGENT_NAME>`

| | SAGE | `<AGENT_NAME>` |
|---|---|---|
| starts | when the user asks | unprompted (tenant), or when a document arrives (attachment), or from a Today line |
| answers | the question asked, about records | what the user did not know to ask, with evidence |
| tools | SQL, RAG, full records, comparison | the capability registry — cards, views, forecast, matcher |
| model calls per turn | one narration (+ planner when 30.16 lands) | one plan + up to `budget.follow_ups` investigate calls + gated narration |
| may compute | never | never |

A Today line opened in Ask becomes a SAGE session seeded with the finding and its evidence; follow-up questions are SAGE's. `<AGENT_NAME>` does not converse; it reports and hands over. The boundary is one sentence in `PERSONA_BLOCK` and one test: a SAGE turn never calls `run_analyst()`, and `run_analyst()` never calls SAGE's SQL tools.

### 3.7 Business profile — discover, propose, configure; then priorities

**Origin.** The former Feature 32 placeholder (founder 2026-09-09: "understand the customer docs well as a first step and then the system should align itself to show what additional is needed and end client can configure it thru trainer"), merged here 2026-09-14: the agent that will advise the business is the agent that should first get to know it.

**Discover.** `handle_analyst_onboarding_run()` runs the loop with `scope.kind="onboarding"`. `observe()` reads everything on file for the tenant as a whole — not since-last-run — and `profile_tenant()` (`services/business_profile.py`) reduces it deterministically to a `BusinessProfile`: document types and their volumes, vendor and customer clusters (`resolve_entities()`), currencies and tax regimes seen, fields consistently present / absent per doc type, payment habits (median days-to-pay per counterparty from `v_payment_events`), document chains actually observed (PO → delivery → invoice → payment coverage), and `coverage_for()` over `INPUT_KINDS`. No model call produces a profile value; the model only narrates it.

**Propose.** From the profile, `propose_conventions()` emits `ConventionProposal` rows: a plain-language rule the system needs a decision on, its default, and the evidence that prompted it — "Rajesh Steel is paid at 47 days on average; set default terms to NET 45?", "3 proformas were followed by a final invoice within 14 days; treat proformas as commitments?", "credit notes arrive for 6% of invoices; auto-apply them to the open invoice?", "two partial payments seen on one invoice; enable partial payments?". Proposals are ranked by `unlock_value()` (§3.5), the same number that ranks input requests, so "what to configure" and "what to feed in" sit on one scale.

**Configure.** Each proposal is accepted, edited or rejected in the Trainer (FE Feature 22 `FirstRun`, then the Trainer's rules surface). An accepted proposal becomes an `ExtractionTemplate` rule or a `TenantChatRule`, whichever store it belongs to — no third store. A rejected proposal is suppressed for that tenant via `learn()` (task 33.19), the same mechanism as a dismissed Today line. The Trainer remains where the business's conventions live.

**Priorities.** The onboarding run ends with the first tenant-scope `TodayItem` set (§3.3), ranked severity-first, prefaced by one gated sentence per item saying *why it ranks where it does* against the profile ("largest open exposure is 3 unpaid invoices to your slowest-paying customer"). This is the "help them understand priorities" half: the profile explains the ranking, the ranking is what the owner acts on. Weekly runs re-rank against the same profile; a materially changed profile (new doc type, vendor cluster, currency) re-triggers Discover, so onboarding and continuous learning are the same run at two cadences (§8 Q9).

## 4. Data & schema changes — facts persist, documents may expire

**The defect this fixes.** Feature 26 D2 says an attachment is never an `Invoice` row and D3 says it moves no aggregate — both correct and both kept. But the consequence as built is that an attachment leaves **no trace at all** once the TTL job runs: the system reads a challan, reports the short delivery, and forgets a delivery ever happened. Next quarter it cannot say "Rajesh short-delivers" because it has no memory of any delivery. Invoices alone give bounded intelligence (spend trend, price history, terms norms, duplicates); every judgement a decision-maker wants — reliability, payment behaviour, cash — lives in the other documents, and those evaporate.

**The change.** Documents are channels; facts are the ledger. Chat attachment becomes one entry channel like email-in and the connector; the channel no longer decides the lifetime.

```
Fact
  id, tenant_id, clearance
  kind            commitment | delivery_event | payment_event | terms | period_accounts | balance_on_date
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
- D2 and D3 are **not** revoked: no `Invoice` row is written, no quota moves. What is revised is the implicit fourth ruling — that an attachment leaves nothing behind. **Founder's call (§7 Q1).**

Other schema, all in one add-only migration `a1b2c3f33001_analyst_agent.py`:

| table / column | purpose |
|---|---|
| `chat_session.clearance` (`"ops"` default, `"exec"`) | §5 |
| `chat_attachments.clearance` | §5; inherited from the session |
| `insight.scope` (`attachment` / `tenant`), `insight.clearance` | both scopes share the lifecycle |
| `today_item` (id, tenant_id, clearance, insight_id \| input_request_id, rank, seeded_question, created_at, cleared_at) | FE Feature 22's list |
| `input_request` (id, tenant_id, clearance, input_kind, unlocks: JSON, unlock_value, status OPEN/DONE/DISMISSED) | §3.5 |
| views: `v_vendor_spend`, `v_overdue`, `v_3way_match` gain `clearance`; new `v_commitments`, `v_delivery_events`, `v_payment_events`, `v_recurrence` over `fact` | successor migration `a1b2c3f33002_fact_views.py` |

No backfill; no downgrade ceremony (dev rule).

## 5. Visibility — one clearance, every read path

Founder: "a higher authority can attach a bank statement or P&L to just understand the forecast so the doc is not seen by others."

**Model.** `clearance ∈ {ops, exec}`. Admin holds `exec`; Auditor and Trainer hold `ops` (`models.RoleMapper` vocabulary; whether a separate Executive role is wanted is §7 Q3). A session opened from an exec Today line, or by an Admin choosing "private", is `exec`; its attachments, facts, findings and Chroma chunks inherit it.

**Enforcement.** Every read path that today takes a `tenant_id` takes a clearance predicate; deny by default. This is the Gap 341 / Gap 460 / Gap 507 lesson applied once, deliberately: one predicate, one helper `clearance_filter(stmt, model, clearance)`, tested per path — not discovered leak by leak. Paths: session list, message read, attachment read and stream, `facts_for()`, `query_metric()`, `Insight` reads, Today, RAG retrieval (separate collection `{tenant}_exec` — a wall, not a `where` on metadata), Trainer (never sees exec source rows; may receive *rules* the owner teaches from them), exports and dashboards (never exec).

**Sharing derived facts — Option C.** The owner attaches August's statement privately. The clerk later asks SAGE "was BHA-2002 paid?" — the answer is on that statement. Ruling proposed: **derived facts about records operations can already see flow down; source rows never do.** A matched bank line produces a `payment_event` fact on the *invoice* with `clearance="ops"` ("paid 06-Aug, UTR …"); the statement itself, and every non-invoice line — salary, loan, charges — stays `exec`. Generic: "facts about records you can already see" is a rule, not a list. **Founder's call (§7 Q2).**

## 6. Tasks

Prerequisites, not tasks here: Feature 30 §11.7 sequence (Gap 477, then 30.19, then 30.20), Feature 29 CP2 calibration if the planner flag is to be turned on.

| # | task |
|---|---|
| 33.1 | `agents/capabilities.py`: `Capability`, `CAPABILITIES`; register every Feature 30 card, the four `METRICS`, `match_statement_lines`, with `needs` and `scopes`. Validation of a planned call against `input_schema` |
| 33.2 | `services/overlap.py::resolve_overlap()` over `resolve_entities()`; party, doc number, line description, tax id, amount+date, rate/terms, periodised table. Returns `OverlapGraph`; a document resolving to nothing returns an empty graph, not an error |
| 33.3 | `agents/analyst_agent.py`: `AnalystScope`, `Budget`, `run_analyst()`, `observe()`, `act()`, `plan_by_rule()` (planner off). Attachment scope only. `build_insight_block()` delegates behind `ENABLE_ANALYST_AGENT` |
| 33.4 | `plan()` behind `ENABLE_ANALYST_PLANNER`: the one planning call; manifest-only input; invented capabilities dropped and logged |
| 33.5 | `investigate()` with `Budget.follow_ups`; evidence attached; contradiction downgrades confidence with reason |
| 33.6 | `say()` — tenant-scope briefing, per-sentence gate, template fallback per sentence; attachment scope unchanged |
| 33.7 | Migration `a1b2c3f33001`: `fact`, `clearance` columns, `insight.scope`, `today_item`, `input_request` |
| 33.8 | `services/facts.py`: `Fact`, `FACT_EMITTERS` (five emitters by shape), `emit_facts()`, `facts_for()`; hard-delete cascade in the attachment and document delete paths |
| 33.9 | `extract_attachment()` calls `emit_facts()` behind `ENABLE_ATTACHMENT_FACTS`; the TTL job deletes the row and leaves the facts |
| 33.10 | Migration `a1b2c3f33002`: `v_commitments`, `v_delivery_events`, `v_payment_events`, `v_recurrence`; `clearance` on the three existing views; `query_metric(clearance=…)` |
| 33.11 | `clearance_filter()` and its application to every read path in §5; `{tenant}_exec` Chroma collection; session `clearance` set on open |
| 33.12 | `services/dependency.py`: `INPUT_KINDS`, `coverage_for()`, `missing_inputs()`, `unlock_value()`; `ask()` in the loop; `input_request` rows |
| 33.13 | `services/forecast.py`: `forecast()` certain + committed tiers; `scenario()` |
| 33.14 | `detect_recurrence()` and the recurring tier; `estimated` tier gated on `estimate_min_months` |
| 33.15 | Tenant scope: `handle_analyst_tenant_run()`, the certified question set, per-counterparty rollup capabilities (reliability, payment behaviour), `TodayItem` generation with severity-first ranking |
| 33.16 | `caj-analyst-weekly-dev` job (Bicep + params + `deploy-service`), `statement_landed` and `deviation` triggers |
| 33.17 | `routers/today.py`: `GET /today`, `POST /today/{id}/open` with seeded session |
| 33.18 | Remove `get_dashboard_insights()` and its FE panel (with FE 22); register its four aggregates as capabilities |
| 33.19 | `learn()`: acted / dismissed → per-tenant suppression; narration corrections → `record_correction()` |
| 33.20 | SAGE boundary: `PERSONA_BLOCK` sentence; the two boundary tests |
| 33.21 | Eval: `benchmarks/analyst_golden.json` — the ten `showcase/vpi_demo` §5 scenarios with expected findings **and expected NOT_CHECKED items**, plus five tenant-scope weeks; `scripts/run_analyst_eval.py` |
| 33.22 | `services/business_profile.py`: `BusinessProfile`, `profile_tenant()` — deterministic reduction over entities, views and `coverage_for()`; Postgres test that the profile is a pure function of the tenant's rows (two tenants, no leakage) |
| 33.23 | `propose_conventions()` → `ConventionProposal`; migration `a1b2c3f33003` (`convention_proposal`); accept / edit / reject endpoints writing to `ExtractionTemplate` or `TenantChatRule`; rejection routed through `learn()` |
| 33.24 | `handle_analyst_onboarding_run()` (`scope.kind="onboarding"`): first-login trigger + material-coverage-change re-trigger; first `TodayItem` set with the per-item "why it ranks here" gated sentence |

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
| 33.7 | migration applies on `upgrade head`; single head |
| 33.8 | Postgres: a challan emits `delivery_event` facts per line; a PO emits `commitment`; a statement emits `payment_event` per matched line and `balance_on_date`; deleting the attachment deletes every fact in the same transaction (count before / after) |
| 33.9 | TTL job on an expired attachment → row gone, facts present |
| 33.10 | views return only rows at or below the caller's clearance |
| 33.11 | **per path**: an `ops` caller listing sessions, reading a message, streaming an attachment, calling `facts_for`, `query_metric`, Today, RAG retrieval — never receives an `exec` row; a test per path, and a meta-test that every router function taking `tenant_id` also takes `clearance` (grep-shaped, the Gap 341 lesson) |
| 33.12 | coverage on the VPI demo: `bank_statements` absent → `forecast` capability is `NOT_CHECKED` → one `InputRequest` whose `unlock_value` equals the sum of committed + certain lines it would unlock; Postgres |
| 33.13 | certain + committed on the VPI data: ₹8,52,561.80 payable, ₹4,37,190 committed on PO-1041 less invoiced; `scenario("Kaveri +20 days")` moves exactly the Kaveri receivables |
| 33.14 | a synthetic 6-month statement series: salary detected at period 30 ± tolerance; a 2-month series → `estimated` is `NOT_CHECKED("needs N months")` |
| 33.15 | Postgres: three short deliveries and one over-billing for one vendor → one rolled-up finding with severity `high`, ranked above a ₹500 rounding finding (Gap 519's test) |
| 33.16 | job fixture: one tenant, one run, `today_item` rows written, `today_updated` published |
| 33.17 | `POST /today/{id}/open` returns a session whose first message is the seeded question; another tenant's item → 404 |
| 33.18 | `GET /dashboard/insights` → 404; the four aggregates answer as capabilities with the same figures the old handler computed (fixture) |
| 33.19 | a kind dismissed three times by one tenant is suppressed for that tenant only |
| 33.20 | a SAGE turn on the VPI fixture never calls `run_analyst`; `run_analyst` never calls `query_tools` SQL |
| 33.21 | the ten §5 scenarios: every expected finding present, every expected `NOT_CHECKED` present, **zero** findings on rows the README says are clean; deterministic set comparison, not the judge (Gap 484's rule) |
| 33.22 | `profile_tenant()` on two seeded tenants (India GST + US) on Postgres: each profile lists only its own doc types, counterparties and currencies; re-running on unchanged rows returns an identical profile (pure function); a tenant with no rows returns an empty profile with every `INPUT_KINDS` entry absent, not an error |
| 33.23 | seeded 47-day median payer → a `default_terms` proposal whose evidence names the counterparty and the figure; accept writes the rule to `ExtractionTemplate` (vendor scope) and nothing else; reject suppresses it via `learn()` and it does not reappear on the next run; edit persists the edited text; proposals from tenant A never appear for tenant B |
| 33.24 | first login triggers exactly one onboarding run; a second login triggers none; adding a first `BANK_STATEMENT` re-triggers Discover; the first `TodayItem` set carries one gated sentence per item, and a sentence the gate rejects falls back to the template with the item still ranked |

## 8. Open decisions — founder

1. **Facts persist after the document expires (§4).** This revises Feature 26's implicit "an attachment leaves nothing behind" while keeping D2 (no `Invoice` row) and D3 (no quota). Yes / no?
2. **Sharing rule — Option C (§5).** Derived facts about records operations can already see flow down as `ops`; source rows and non-invoice lines stay `exec`. Yes, or strictly private, or share-whole-document on request?
3. **Clearance by role or by person?** By role: every Admin sees every exec session. By person: the owner's statement is the owner's. Role is simpler; person is what "not seen by others" literally says.
4. **Planner on for this feature?** It adds one model round-trip per run. Feature 30 task 30.16 deferred it pending Feature 29's 100-turn calibration. Turn it on for tenant scope only (weekly, latency irrelevant) and leave attachment scope on `plan_by_rule()` until calibrated?
5. **Bank statements as a standing input.** Email-in / connector ingest for statements, monthly, rather than chat attachment — so the forecast has a regular feed with no manual step. Build the ingest path in this feature, or leave it as an onboarding input request (§3.7) the owner fulfils by hand?
6. **Feature 29 §12 — the gate validates figures, not claims.** This feature inherits it. Accept for v1 (findings carry evidence the reader can check) or block tenant-scope narration on a claim-level verifier first?
7. **Scope statement.** "AP/AR + cash intelligence for an SMB" — or full FP&A (P&L, margin, budget variance tiles)? `period_accounts` facts make the second possible; the first is what invoices + statements support today.
8. **Agent name.** `<AGENT_NAME>` throughout; SAGE is the precedent.
9. **Onboarding cadence (from the former Feature 32).** §3.7 proposes one mechanism at two cadences: a first-login scan, re-run on material coverage change. Accept, or first-login only, or continuous on every weekly run?
