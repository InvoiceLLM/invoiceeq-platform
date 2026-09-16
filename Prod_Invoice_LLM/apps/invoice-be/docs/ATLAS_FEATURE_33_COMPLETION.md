# BE Feature 33 — ATLAS Analyst Agent: Completion Summary

**Branch:** `feature/33-atlas-analyst-agent-be`  
**Completed:** 2026-09-16  
**Counterpart Spec:** `apps/invoice-be/docs/feature_33_analyst_agent.md`  
**Tracker Entry:** `apps/invoice-be/docs/be_features_tracker.md` — Feature 33 marked `[x]`  

---

## What Was Built

ATLAS is a **proactive AI Analyst Agent** that runs autonomously in a background loop. Unlike SAGE (which answers on demand), ATLAS observes the business, finds problems and opportunities, and surfaces them on the **Today** screen without being asked.

### The 7-Step ATLAS Loop

```
run_analyst(scope, db_session, budget)
  │
  ├─ 1. observe()        → Builds Observation: documents, facts, invoices, business profile
  ├─ 2. plan()           → One LLM call → ordered list of capability calls to run
  ├─ 3. act()            → Executes capabilities → InsightCards (PASSED / FAILED / NOT_CHECKED)
  ├─ 4. investigate()    → Findings above threshold: up to budget.follow_ups deeper capability calls
  ├─ 5. say()            → Narrates sentences, each gated by _answer_contract_gate()
  ├─ 6. ask()            → missing_inputs() → InputRequest list ranked by unlock_value()
  └─ 7. persist/learn()  → Writes Insight rows, TodayItems, InputRequests; feeds learn() on dismiss
```

**Three scopes:**
| Scope | Trigger | Produces |
|---|---|---|
| `attachment` | Document attached in chat | Insight bubble under the assistant turn |
| `tenant` | Weekly job (Mon 06:00 UTC) + significant events | Today lines + briefing |
| `onboarding` | After first 10 extractions settle | Business profile + convention proposals |

---

## New Files Created

### Database / Migration
| File | Purpose |
|---|---|
| `alembic/versions/a1b2c3f33001_analyst_agent.py` | Adds: `fact`, `today_item`, `input_request`, `action_log`, `tenant_profile_rule` tables; `chat_session.clearance`, `insight.scope/clearance`, `user.ui_prefs` columns |
| `alembic/versions/a1b2c3f33002_fact_views.py` | DB views: `v_vendor_spend`, `v_overdue`, `v_currency_exposure`, `v_fpa_lines`, `v_fact_ledger` |

### Core Agent
| File | Purpose |
|---|---|
| `agents/analyst_agent.py` | Main 7-step loop: `run_analyst()`, `observe()`, `plan()`, `act()`, `investigate()`, `say()`, `ask()`, `learn()` |
| `agents/atlas_prompts.py` | All LLM prompt templates for ATLAS (mirrors `sage_prompts.py`) |
| `agents/capabilities.py` | The 10+ capability registry (PO match, duplicate, overdue, GST, FX, budget variance, …) |

### Services (Deterministic Engines)
| File | Purpose |
|---|---|
| `services/facts.py` | Facts Ledger: `emit_facts()`, `facts_for()`. 6 emitters: commitment, delivery, payment, terms, period_accounts, budget. TTL-safe (ON DELETE SET NULL). |
| `services/forecast.py` | Cashflow engine: 4 tiers (certain/committed/recurring/estimated), multi-currency, `scenario()` what-if |
| `services/dependency.py` | Coverage engine: `missing_inputs()`, `unlock_value()`, phrasing contract (`_answer_contract_gate()`) |
| `services/clearance.py` | Clearance filter: `clearance_filter(stmt, model, clearance)` — `ops` vs `exec` on every read path |
| `services/conventions.py` | Convention proposal generator: `propose_conventions()`, `accept_convention()`, `reject_convention()` |
| `services/business_profile.py` | Tenant business profile builder: `profile_tenant()` |
| `services/tenant_profile_rules.py` | 6-question routine questionnaire: `next_routine_question()`, `save_routine_answer()`, `routine_answers()`, `detect_routine_contradiction()` |
| `services/action_log.py` | Role-gated action execution + audit log: `execute_action()`, `ActionPermissionError`, `ActionExecutionError` |
| `services/overlap.py` | Overlap / 3-way match engine |

### API Router
| File | Purpose |
|---|---|
| `routers/today.py` | All Today endpoints: `GET /today`, `POST /today/{id}/open|dismiss|confirm|scenario|accept|edit|reject`, `POST /today/run`, `GET|POST /today/questionnaire*`, `GET|PATCH /today/routine-answers*` |

### Queue Worker
| File | Purpose |
|---|---|
| `queue_worker/analyst_handlers.py` | Redis queue handler for async analyst jobs: `enqueue_analyst_job()`, `handle_analyst_job()` |

### Infra
| File | Purpose |
|---|---|
| `infra/analyst-weekly-job-only.bicep` | Azure Container App scheduled job (Mon 06:00 UTC) for the weekly tenant analyst run |

### Scripts & Benchmarks
| File | Purpose |
|---|---|
| `scripts/run_weekly_analyst.py` | CLI entrypoint for the weekly job |
| `scripts/run_analyst_eval.py` | Evaluation harness: runs all golden scenarios, scores pass/fail, prints summary |
| `benchmarks/analyst_golden.json` | 16 golden test scenarios: 11 attachment cases + 5 tenant-week cases (Day 1–30) |

### Test Suite
| File | Tests | Result |
|---|---|---|
| `tests/test_facts.py` | Fact emission, TTL vs hard-delete, clearance isolation | 8 / 8 ✅ |
| `tests/test_forecast.py` | Cashflow tiers, scenario recomputation, multi-currency | 4 / 4 ✅ |
| `tests/test_dependency.py` | Capability registry, unlock value, phrasing contract | 82 / 82 ✅ |
| `tests/test_clearance.py` | `clearance_filter` across roles | 4 / 4 ✅ |
| `tests/test_analyst_agent.py` | Full 7-step loop across all 3 scopes | 5 / 5 ✅ |
| `tests/test_analyst_actions.py` | Role-gated action execution, 403 paths, audit log | 4 / 4 ✅ |
| `tests/test_tenant_profile_rules.py` | Questionnaire flow, contradiction detection | 2 / 2 ✅ |
| `tests/test_today_routes.py` | Today API: pre-onboarding, active feed, dismiss, confirm | 5 / 5 ✅ |
| `tests/test_preferences.py` | `/me/preferences` GET/PATCH, unknown key rejection | 4 / 4 ✅ |
| **Golden Eval Benchmark** | 16 golden scenarios via `run_analyst_eval.py` | **16 / 16 ✅** |
| **TOTAL** | | **134 / 134 ✅** |

> **All tests run against real Postgres (`localhost:5433/invoice_db`), not SQLite — per CONVENTIONS.md Hard Rule 2.**

---

## Modified Files

| File | Change |
|---|---|
| `models.py` | Added `Fact`, `TodayItem`, `InputRequest`, `ActionLog`, `TenantProfileRule` models; updated `User.ui_prefs`, `ChatSession.clearance`, `Insight.scope/clearance` |
| `config.py` | Added `ANALYST_ONBOARD_MIN_DOCS`, `ANALYST_RUN_NOW_COOLDOWN_SECONDS`, `ENABLE_ATTACHMENT_FACTS` settings |
| `dependencies.py` | `get_tenant_context()` now surfaces `clearance` and `db_user_id`; added `get_tenant_context_allow_unpaid()` |
| `main.py` | Mounted `today.router` under `/api/v1` |
| `routers/auth.py` | Added `GET /me/preferences` and `PATCH /me/preferences` (Task 33.39 — per-user UI prefs store) |
| `routers/chat.py` | Wires clearance through to session creation |
| `routers/chat_attachments.py` | Calls `emit_facts()` after successful extraction (behind `ENABLE_ATTACHMENT_FACTS` flag) |
| `services/attachment_extraction.py` | Calls `emit_facts()` post-extraction |
| `services/attachment_insights.py` | `InsightCard` now carries `scope` and `clearance`; adds `card_net_position` for credit notes |
| `services/bank_ledger.py` | Bank statement fact emission support |
| `services/insight_thresholds.py` | Three-state check result (`PASSED / FAILED / NOT_CHECKED`) — Task 30.19 prerequisite |
| `services/insights.py` | `scope` and `clearance` propagation |
| `services/semantic_views.py` | Wires DB views created in migration `a1b2c3f33002` |
| `agents/sage_prompts.py` | `CHAT_PERSONA_BLOCK` updated with ATLAS name (ATLAS pairs with SAGE) |
| `queue_worker/main_worker.py` | Registers `analyst_handlers` |

---

## Design Decisions & Hard Rules Enforced

1. **No numbers from LLM.** Every figure (amount, count, date) comes from deterministic SQL / Python. LLM only narrates, and each sentence is gated by `_answer_contract_gate()`.
2. **TTL ≠ cascade.** The TTL sweeper (`sweep_chat_attachments.py`) deletes attachment rows; the `ON DELETE SET NULL` FK preserves Facts so business intelligence survives document expiry.
3. **Hard delete = cascade wipe.** When a user explicitly deletes a document (privacy/compliance), the API endpoint runs `DELETE FROM facts WHERE source_id = :id` in the same transaction.
4. **Clearance on every read.** `clearance_filter()` is applied to every query that returns `TodayItem`, `Insight`, `InputRequest`, or `Fact`. Never filtered client-side.
5. **No new upload endpoint.** `UploadButton` / `AttachButton` use the browser's native file picker posting to existing ingestion and chat-attachment endpoints.

---

## What Comes Next (FE Feature 22)

The backend exposes all the endpoints this surface needs. The FE implementation plan is in:
- `apps/invoice-fe/docs/feature_22_today_ask_records.md` — Full spec (27 tasks)
- `implementation_plan.md` (agent artifact) — Component-by-component build plan

**FE Checkpoint 1** (build order from spec §5):
Tasks 22.1–22.11, 22.17–22.21, 22.23–22.26 — gate: `tsc --noEmit` exit 0 + `vitest run` green.

**FE Checkpoint 2** (BE-gated tasks after 33.29 / 33.39 verified live):
Tasks 22.12–22.16, 22.22, 22.27 — gate: full vitest + full Playwright including screenshot regression.
