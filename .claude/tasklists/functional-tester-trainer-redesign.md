# Functional Tester - Trainer/Chat Redesign (Feature 18 BE / Feature 14 FE)

Scope per orchestrator prompt (2026-08-17). Independently confirm dev claims in BE
Gaps 228-232 and FE Gaps 232-238, catch anything that slipped through, focus on the
BE/FE seam. No application-code changes.

## Environment setup
- [x] Started Docker Desktop, brought up docker-compose stack (Postgres/Redis/Chroma/Azurite) - all 4 already running
- [x] Ran invoice-be (real uvicorn, port 8000) and invoice-fe (real next dev, port 3100) against the real stack
- [x] Discovered and fixed (schema migration only, no code change): local invoice_db was not migrated to f18a0c4b7d21 - ran alembic upgrade head against it

## Test plan - all items executed live against real stack unless noted

| # | Item | Result |
|---|---|---|
| 1 | Permission boundary | CONFIRMED - real 403s on every trainer endpoint + chat/rules/commit for a real can_train=false identity; real FE gate confirmed live and via stubbed spec |
| 2 | Dual-format regression + Global-scope still applied | CONFIRMED - 3 real pre-existing legacy templates render byte-identical; Global row still read live by query_agent |
| 3 | Preview-before-commit exact math | CONFIRMED - hand-verified against a real invoice (20.00 mismatch, 25.00 tolerance, exact match); not_computable path blocked by Gap 235 (see below) |
| 4 | Chat-lane DB isolation | CONFIRMED - direct SQL query, committed chat rule absent from every extraction_templates row |
| 5 | Wrong-data auto-diff triage | CONFIRMED - all 4 branches (mismatch, match, pdf_agrees true/false) against a real chat answer |
| 6 | Five source-text alert types 400 | CONFIRMED live, all five |
| 7 | QA-mode memory | CONFIRMED - real multi-turn recall of a planted value, real ChatMessage rows |
| 8 | FE contract workarounds | CONFIRMED - vendor picker live screenshot; bad-tone link wired end to end |
| 9 | FE's 5 fixed regressions re-run | CONFIRMED green (isolated from an unrelated parallel-worker JIT-compile flake) |
| 10 | Migration re-verify on fresh DB | CONFIRMED on a new throwaway DB, matches dev claim |
| 11 | Full BE regression suite | 552 passed / 0 failed / 5 deselected - exact match to claim |
| 12 | Full FE regression + tsc + Gap 86 independent check | tsc clean; Gap 86 independently confirmed pre-existing/unrelated via git diff |

## Defect found
- [x] Filed **BE Gap 235**: missed-alert LLM drafting (`routers/trainer.py` `max_tokens=512`)
      fails against the real deployed `gpt-5-mini` reasoning model - entire token budget
      consumed by reasoning_tokens, 0 accepted_prediction_tokens, real 502 on every attempt.
      Reproduced 3x. Also breaks the wrong-data triage's pdf_agrees=false redirect terminus.

## Cleanup
- [x] Reverted all DB test mutations (committed tolerance rule, chat rule, chat session/messages, can_audit flag) - dev DB left as found (except the now-necessary f18a0c4b7d21 migration, which is a correctness fix, not a mutation to revert)
- [x] Deleted throwaway Playwright script (e2e/_ft_live_check.spec.ts)

## Output
- [x] `apps/invoice-be/docs/test_evidence/feature18_trainer_redesign_2026-08-17/` (README + pytest log + LLM failure log)
- [x] `apps/invoice-fe/docs/test_evidence/feature14_trainer_redesign_2026-08-17/` (README + 3 playwright logs + screenshot)
- [x] `apps/invoice-be/docs/test_coverage_map.md` updated
- [x] `apps/invoice-fe/docs/test_coverage_map.md` updated
- [x] `apps/invoice-be/docs/be_features_tracker.md` - new Gap 235 filed

**Final status: DONE. Verdict: redesign is safe to commit/push structurally and at the
data-integrity level (every claimed guarantee independently reconfirmed live); one
real, reproducible functional defect found (BE Gap 235) that should be fixed before
relying on the "flag a missed alert" feature or the chat-triage extraction redirect in
any environment using this deployed model - does not corrupt data (fails closed
correctly) but the feature is currently non-functional end to end.**
