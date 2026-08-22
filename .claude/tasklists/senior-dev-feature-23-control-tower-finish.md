# Feature 23 (AI Control Tower) — finish the remaining build

Working state for the run of 2026-08-21. Four priorities, in order.

## Priority 1 — fix the eval judge's two remaining known bugs
- [x] Read `services/agent_eval.py` + `tests/agent_eval_output.json` to find the real cause of each
- [x] (a) "no records found" scoring 0.0 faithfulness — root cause + rubric fix.
      Cause was **not** judge stubbornness: the executed query was never part of the evidence, so
      no absence claim naming a vendor/period could be checked. Fixed with `executed_queries` +
      a per-claim `claim_type` the judge assigns before deciding.
- [x] (b) identical refusal scoring 1.0 / 0.0 across paths — root cause + rubric fix.
      Cause was structural: every relevance anchor was phrased as "answers what was asked", which a
      refusal never does. Fixed with `answer_kind` classified first, score fixed in code for the
      definitional kinds.
- [x] Wire the runner to feed whatever the fix needs (`_ToolOutputRecorder.executed_queries()`)
- [x] Tests proving each failure mode, using the real texts from the failing run
- [x] Document in the module's "judge failure modes found by running it" section, dated 2026-08-21

## Priority 2 — wire built-but-unwired pieces into the workbook
- [x] Online-signals panel (5 signals) + the `stop_reason` / latency-proxy caveats carried verbatim.
      Needed a data source that did not exist — added `emit_online_signals()` +
      `telemetry.track_online_signal()`, since a workbook cannot query Postgres.
- [x] Golden-bank coverage tile — re-verified against the current `golden_bank.json`: still 8/53,
      45 needing a case, fixture `generated_at` 2026-08-21T14:16:40Z
- [x] Latency as its own trended panel (p50 **and** p95 per agent per day, chart + table)

## Priority 3 — three-component scoring
- [x] `context_score` / `orchestration_score` / `persona_score` on `AgentEvalRun` + migration
      `c4a91e77b208` chained onto the real head `b5d2c8a41f30`
- [x] Scoring logic in `services/agent_eval.py` (deterministic / mechanical / LLM-judged)
- [x] Workbook panel — three separate trend lines + a denominator table + a diagnosis table
- [x] Tests, including running the new migration's DDL up and down

## Priority 4 — per-tool cost/token breakdown
- [x] `infra/monitoring/llm_cost_by_tool.kql`, by the real `sage.*` agent names in use
- [x] Answers the `get_full_record` question via `synthesis_share_pct` per `request_id`, with the
      structural reason stated: that tool makes no LLM call, so its cost is inside
      `sage.synthesis`'s `tokens_in`
- [x] Workbook section 2 (two panels + a header carrying the same caveat)

## Close-out
- [x] Full suite: **1024 passed, 3 failed, 6 skipped, 5 deselected** — the *same 3* pre-existing
      failures as the 977/3/6 baseline (2 Redis, 1 `background_tasks`). 39 of the +47 are this pass.
- [x] `alembic heads` → `c4a91e77b208 (head)`, single head
- [x] All 10 new Log Analytics queries executed live against `appi-invoicellm-dev` — correct schema,
      0 rows, `customEvents` re-confirmed empty over 90 days
- [x] Updated `feature_23_ai_control_tower.md` (three new sections + Tasks) and the tracker
- [x] Left uncommitted

**Final status: all four priorities complete.** Two things deliberately not done and reported as
such: the judge fixes have not been re-run against a live model (so post-fix quality figures do not
exist), and no dedicated domain-knowledge golden set was written, so `persona_score` is scored
against the general sample and is NULL on most turns.
