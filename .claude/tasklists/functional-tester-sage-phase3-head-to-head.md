# Feature 21 SAGE Phase 3 — live head-to-head vs Feature 6 default path

Goal: one number — how many of the NovaTech 25-question bank does SAGE get right that the
*current* default path (Gap 310 full-record + Gap 315 deterministic compute + Gap 313 persona
already applied) gets wrong, and vice versa. Real Azure OpenAI, real Postgres, real Chroma.

## Discovery
- [x] Read CONVENTIONS.md + active-work.md. NOTE CONFLICT: active-work.md "Frozen / do not touch"
      lists "SAGE Phase 3 — gated on Gap 310's real-world result ... Do not start". Gap 310 shipped
      2026-08-25 (commit f985ee9), which is the stated gate; task brief says founder asked for this
      run explicitly. Proceeding, flagged in final report.
- [x] Found tenant: NovaTech Solutions `787a5d06-82ee-452e-b76b-f8a1983bfed2`
      (`.claude/tasklists/functional-tester-novatech-seed.md`).
- [x] Found question bank: `tests/realworld_tenant/chat_question_bank.md` — 25 questions, 4 sessions
      (7/6/5/7), each with a computed exact expected answer + a grading rubric.
- [x] Found ground truth: `tests/realworld_tenant/ground_truth_line_items.md` (78 line rows / 15 invoices).
- [x] Read `tests/run_agentic_sage_live.py` in full — SQLite-seeded, 8 incident questions, SAGE only,
      no judge, no default-path comparison. Its own docstring says the live-tenant run is Phase 3's job.
- [x] Read `scripts/run_agent_eval.py` — already has both-path support (`--paths default,sage`),
      `_agentic_sage_enabled()` in-process flag flip, `_LlmCallCounter`, `_ToolOutputRecorder`,
      `summarise()`. But it is hard-wired to the seeded in-memory SQLite golden sample.
- [x] Read `services/agent_eval.py::score_answer` — the judge to reuse.
- [x] Confirmed Gap 310 / 315 / 313 are live in `agents/query_agent.py`'s default path:
      `_full_record_block_for()` (l.1452, `MAX_FULL_RECORD_INVOICES=3`),
      `_computed_figures_block_for()` (l.1596), `CHAT_PERSONA_BLOCK` (l.1136) on all four
      prompts. All three are `[x]` in the tracker, shipped 2026-08-25.

## Environment
- [x] BLOCKER FOUND: docker had zero containers AND zero volumes — the NovaTech Postgres data and
      Chroma collection from 2026-08-19 no longer exist. Re-seed required before any comparison.
- [x] `docker compose up -d` (postgres 5433, chroma 8001, redis 6379, azurite) — all healthy.
- [x] `alembic upgrade head` → head reached (a7c3d5e91f04).
- [x] `tests/seed_test_tenants_local.py` → NovaTech re-created with a NEW id
      `ec675d22-bd53-49dd-b428-31b743be88d3` (the 2026-08-19 id `787a5d06-...` died with the volume).
- [x] `tests/seed_novatech_realworld_ingest.py` → 15/15 PDFs, real Doc Intelligence OCR + real
      Azure OpenAI extraction. 14 COMPLETED + 1 AUDIT_REQUIRED (Synthex INV-2025-0040) — identical
      to the 2026-08-19 seed. Every grand_total matches ground_truth_line_items.md.
- [x] Verified: 15 invoices in Postgres, 15 chunks in Chroma, 1024-dim, norm 1.0 (real bge-m3).

## Harness
- [x] `tests/realworld_tenant/run_sage_vs_default_live.py` (new sibling; `run_agentic_sage_live.py`
      is SQLite-fixture-bound end to end and its own docstring defers the live run to Phase 3 —
      reason recorded in the new file's docstring). `run_agentic_sage_live.py` left untouched.
- [x] Both paths through the real `run_query_agent()` entry point (SAGE via its own
      `ENABLE_AGENTIC_SAGE` branch), separate ChatSession per (bank session, path).
- [x] Real token/cost/latency per turn via `run_agent_eval._LlmCallCounter`.
- [x] Judge = `services/agent_eval.score_answer`, separate mode.
- [x] HAZARD FOUND + handled: importing `scripts/run_agent_eval.py` does
      `os.environ.setdefault("MOCK_EMBEDDINGS","true")` at module scope, and an env var beats
      `.env` in pydantic-settings — that would have silently mocked every Chroma query in a live
      run against real stored vectors. Forced to "false" before all imports and asserted at start.
- [x] METHODOLOGY: the bank's own Grading Rubric is prepended verbatim to every reference answer.
      Without it the judge deducts for omitting material the bank marks "bonus, not required"
      (measured: Q3 smoke, both paths exactly right, both scored accuracy 0.5 for not volunteering
      that it was the only ByteForce invoice). Applied uniformly to both paths.

## Run + report
- [x] Ran all 25 x 2 = 50 live turns + 249 judge calls. 0 harness errors, 0 judge errors,
      0 cache-served turns (every default turn made >=2 real LLM calls).
      Output: `tests/realworld_tenant/sage_vs_default_live_output.json`.
- [x] Reported per-question correctness, the SAGE-only-right / default-only-right sets, fresh
      cost/latency/token deltas, defects found, judge caveats.

## Result
- Default 23/25 pass, SAGE 19/25 pass.
- **SAGE right where default wrong: 0 questions.**
- **Default right where SAGE wrong: 4** (Q11, Q15, Q19, Q24). Both wrong: 2 (Q9, Q25).
- Cost/latency (fresh, post Gap 310/315/313): SAGE +137% LLM calls, +91% tokens-in,
  +85% tokens-out, +87% cost/turn, +90% median latency. Supersedes the pre-Gap-310
  +38%/+22% figure quoted in `feature_21_sage.md` B4 and the tracker's Feature 21 entry.
- 4 real defects found (2 SAGE-only, 1 shared, 1 judge/methodology). Reported, none fixed.

Status: DONE (2026-08-25). No product code changed. `sage_orchestrator.py`,
`ENABLE_AGENTIC_SAGE` and `run_agentic_sage_live.py` all untouched. Keep/delete decision
deliberately NOT taken here — that is the founder's call on this evidence.
