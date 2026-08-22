# senior-dev — Feature 23 observability/evaluation framework (vendor-agnostic parts)

Scope: three new-file-only deliverables from `feature_23_ai_control_tower.md`'s 2026-08-21 sections.
Hard constraint: do **not** edit `telemetry.py`, `agents/sage_orchestrator.py`, `agents/query_tools.py`,
`docs/be_features_tracker.md`, `docs/feature_21_*.md` — another agent owns those concurrently.

## Recon (read-only)

- [x] Read `.claude/CONVENTIONS.md` and `feature_23_ai_control_tower.md` in full
- [x] Read `services/agent_eval.py` (scorer input shape) + `tests/agent_eval_golden_sample.py` (GoldenCase shape)
- [x] Inventory the real source data: `docs/test_evidence/` (7 dirs), `tests/{us,india,eu,realworld_tenant}/`
- [x] Confirm real formats: `chat_question_bank.md` (Qn./Answer:/Matching:/Computation:),
      `live_test_results.md` (results table w/ Expected + Verdict + gap-citing Notes),
      per-gap evidence JSON (`turns[].query/.expected`, `raw_turns_*.json` turn sequences)
- [x] Confirm all four question-bank dirs are **gitignored** (tests/.gitignore + Prod_Invoice_LLM/.gitignore)
- [x] Read `models.py` for `ChatMessage`/`ChatFeedback`/`AgentEvalRun` real columns (read-only)
- [x] Read `sage_orchestrator.py` stop_reason vocabulary + `run_agent_eval.py` notes format (read-only)

## 1. Golden question bank seed

- [x] `scripts/seed_golden_bank.py` — parsers for the 4 real formats found
- [x] Emit JSON fixture consumable by `services/agent_eval.py::score_answer` (question/expected_answer/context-free)
- [x] Gap attribution: parse gap numbers out of evidence dir names + `live_test_results.md` Notes
- [x] Coverage report against the real tracker (read-only): closed chat/RAG gaps vs. gaps with a recovered case
- [x] Run it for real, record the true numbers

## 2. Scrubbing utility

- [x] `utils/trace_scrubbing.py` — redact vendor/customer names, invoice numbers, GSTINs,
      payment_instructions bank details, monetary values; preserve field names + question/answer shape
- [x] `tests/test_trace_scrubbing.py` — prove specific PII fields redacted AND specific structure survives
- [x] No new dependency

## 3. Online-eval signal queries

- [x] `services/online_eval_signals.py` — 5 signals over `ChatMessage`/`ChatFeedback`/existing `AgentEvalRun` columns
- [x] `tests/test_online_eval_signals.py` — seeded SQLite, real assertions per signal
- [x] Record honestly which signals are proxies/offline-only and what is a genuine schema gap

## 4. Verify + document

- [x] Run the new tests
- [x] Run the full backend suite; confirm the same 6 pre-existing failures, no new ones
- [x] Update `feature_23_ai_control_tower.md` with what was built + the real seed numbers + what stays open
- [x] Leave uncommitted

Final status: **complete.** New files only: `utils/trace_scrubbing.py`,
`services/online_eval_signals.py`, `scripts/seed_golden_bank.py`, 3 test files, and the generated
`tests/golden_bank/golden_bank.json`. **89 new tests, all passing** (25 scrubbing + 30 seed +
34 signals). Full suite `-q --ignore=tests/us --ignore=tests/realworld_tenant -p no:randomly`:
**977 passed / 3 failed / 6 skipped**, the 3 failures pre-existing and unrelated (2 need a live
Redis, 1 is `test_rag.py`'s `background_tasks` signature).

Golden-bank seed recovered **87 cases** (79 directly scorable) but attributed only **8 of 53**
closed answer-quality gaps — **45 still need a case written fresh**. That sparseness is the source
data's, not the parser's: only two places in the repo tie a question to a gap number.

Thread-level drift detection deliberately left unbuilt and flagged open. No vendor chosen, no
dependency added, no forbidden file touched.
