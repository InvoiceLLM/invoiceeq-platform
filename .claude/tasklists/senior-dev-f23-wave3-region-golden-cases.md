# senior-dev — Feature 23 Wave 3: port the regional chat question banks into `benchmarks/`

Goal: expand the shipped golden bank (`benchmarks/agent_eval_golden_sample.py`, 20 cases)
with India/US/EU material from `tests/{india,us,eu}/chat_question_bank.md`, adapted to the
in-memory SQLite + MOCK_EMBEDDINGS harness so it actually ships and runs in the nightly job.

## Steps

- [x] Read `.claude/CONVENTIONS.md`, `benchmarks/agent_eval_golden_sample.py`,
      `benchmarks/sage_seed_fixtures.py`, `benchmarks/large_invoice_fixture.py`,
      `scripts/run_agent_eval.py`.
- [x] Read all four source banks: `tests/india`, `tests/us`, `tests/eu`,
      `tests/realworld_tenant` + their `ground_truth_line_items.md`.
- [x] Read `tests/_extraction_data.json` for per-invoice expected status / alert type.
- [x] Confirm the schema the SQL prompt actually exposes (`agents/query_agent.py`
      `_build_sql_system_prompt`) — decides what is portable and what is not.
- [x] Decide the isolation mechanism: region rows go in their **own tenant ids** in the
      same SQLite DB, so the existing 20 cases' fixture (and every computed reference
      answer over `ALL_ROWS`) is untouched.
- [x] `benchmarks/region_seed_fixtures.py` — India/US/EU rows + chunks + per-tenant stats.
- [x] `benchmarks/sage_seed_fixtures.py::_seed` — accept a `tenant_id` and the extra
      columns region rows need (`po_number`, `subtotal`, `sa_alerts`, `tags`).
- [x] `benchmarks/agent_eval_golden_sample.py` — `GoldenCase.tenant_id` (defaulted, so the
      existing 20 keep their exact schema) + the ported cases.
- [x] `scripts/run_agent_eval.py` — seed the region tenants, pick stats/chunks per case,
      run each turn against `case.tenant_id`, persist the turn's own tenant.
- [x] `ruff check` every touched file.
- [x] Run the ported cases through the real harness (`scripts/run_agent_eval.py`).
- [x] Run the existing suite for regressions (`uv run pytest`).
- [x] Update `docs/feature_23_ai_control_tower.md` + `docs/be_features_tracker.md` +
      `docs/feature_20_23_24_implementation_status.md` (Wave 3 row).

- [x] File the findings the run produced (Gap 306; Gap 294 reproduction; the one fixture correction).

Final status: **done, 2026-08-24.** 15 cases added (5 India / 5 US / 5 EU), bank **20 → 35**.
Live `run_agent_eval.py --paths default --judge combined` against Azure gpt-5-mini: **15/15 turns,
0 harness errors**, pass rate 0.333 (base set's own baseline 0.35), persona scored on **15/15**
turns. `uv run pytest --ignore=tests/realworld_tenant`: **1414 passed / 7 failed / 7 skipped** —
all 7 failures belong to other in-flight workstreams (Redis ×2, `post_chat_message` signature ×1,
chat-queue judge ×3, `turn_telemetry` key ×1), none touching `benchmarks/`. `ruff check` clean on
all 5 touched files. Opened **Gap 306** (rule 6b drops `items`, reproduced on two tenants).
