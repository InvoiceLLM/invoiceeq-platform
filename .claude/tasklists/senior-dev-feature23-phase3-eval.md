# Feature 23 Phase 3/4 eval infra + Feature 21 B4 measurement (senior-dev)

- [x] Read CONVENTIONS, feature_23_ai_control_tower.md, feature_21_architecture.md, feature_21_rag_faithfulness.md
      — NOTE: neither Feature 21 doc has a section "B4"; no "cost or latency budget" string exists
        anywhere in the repo. Gap 278's 20-40s / 177s baseline is real but lives in the tracker.
- [x] Confirm real alembic head (`alembic heads`) → `f3e8b2a1d6c9` (single head), new rev chains onto it
- [x] Part 1.1: `AgentEvalRun` SQLModel + alembic `b5d2c8a41f30` (col `pass`, attr `passed`)
- [x] Part 1.2: `services/agent_eval.py` — LLM-judge, NOT ragas (Apache-2.0 is fine, but it pulls
      datasets/pyarrow/pandas into a `uv sync --frozen` image shared with production)
- [x] Part 1.3: `scripts/run_agent_eval.py` + `tests/agent_eval_golden_sample.py`
- [x] Part 2 run 1: full 9-case x 2-path run against real Azure gpt-5-mini — BOTH paths ran
      end-to-end, 18/18 turns, 0 harness errors. Found 2 systematic judge defects (empty result read
      as no-evidence; greeting capability text decomposed into claims) → judge prompts fixed
- [x] Part 2 run 2 (final numbers, corrected judge) — 18 turns, 0 errors
- [x] Part 2 numbers (36 turns pooled): default 1/2/4 calls, 3.7/20.0/38.2s; sage 1/3.5/8 calls,
      3.4/22.4/59.5s; +38% calls, +22% cost/turn. Structural worst case 5 vs 18 calls.
- [x] Part 3.1: `infra/monitoring/llm_cost_rollup_nightly.kql` — validated live against App Insights
- [x] Part 3.2: `infra/monitoring/ai_control_tower.workbook.json` — all 6 queries validated live
      (4 x Logs against appi-invoicellm-dev, 2 x ARG alertsmanagementresources). Not imported.
- [x] Unit tests: `tests/test_agent_eval.py` 19 passed (incl. migration DDL up/down on sqlite)
- [x] `agents/README.md` §3.2 corrected (claimed Ragas was in use; it never was)
- [x] Update feature_23 doc: "Phases 2 and 3 as built" section, corrected the stale
      "golden-question regression banks" claim, Tasks checkboxes ([x] cost KQL, [x] eval table+job,
      [x] workbook, [ ] Phase 4 substitution — not started)
- [x] Update tracker: Feature 23 Phase 2 `[~]`, Phase 3 `[~]`, Phase 4 `[ ]`; Feature 21 Phase 2
      `[~]` (corrected stale "flag does not exist yet"); new entry for the live Gaps 263/264 repro
- [x] Update feature_21_architecture.md with REAL measured numbers (new "B4" section; also records
      that no section named B4 ever existed in that file)
- [x] Full suite: **837 passed / 6 failed / 6 skipped** — 818 + 19 new tests, same 6 pre-existing
      failures, no new failure
- [x] Leave uncommitted (root-level scratch .kql/.json probes deleted)

Status: complete. Both chat paths measured for real; the two things that could NOT be done are
stated as such — no schedule/cron exists for either the cost rollup or the eval job, and the
workbook was authored but deliberately not imported. The eval judge's absolute level is not yet
trustworthy (documented, with the two surviving failure modes named).
