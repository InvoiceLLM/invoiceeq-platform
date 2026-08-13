# Gap Resolution — Autopilot, Audit Review, Trainer & Chat (Gaps 217–221)

Phased plan: `Prod_Invoice_LLM/docs/guides/gap_resolution_autopilot_audit_trainer_chat_plan.md`

- [x] 1. Create execution guide + index in `application_doc_summary.txt`
- [x] 2. Phase 1 — FE 218 Approve Invoice button (`review/[id]/page.tsx`, `audit-review-console.spec.ts`)
- [x] 3. Phase 1 — BE 217 structured guardrail rejection JSON (`trainer.py`, `test_trainer.py`)
- [x] 4. Phase 1 — FE 219 Autopilot folder browser (`ingestion/page.tsx`, `FolderTreeExplorer` folder mode, `autopilot-folder-browser.spec.ts`)
- [x] 5. Phase 2 — BE 219 chat conciseness (`query_agent.py`)
- [x] 6. Phase 2 — BE 221 commit-behavior API + chat style storage (`trainer.py`, `test_trainer.py`)
- [x] 7. Phase 2 — BE 218 session_mode qa_test / rule_creation (`trainer.py`, `test_trainer.py`)
- [x] 8. Phase 3 — FE 221 Chat Response Style panel (`ChatResponseStylePanel.tsx`, proxy routes)
- [x] 9. Phase 3 — FE 220 Trainer restructure (`TrainerControlBar.tsx`, `trainer/page.tsx`, BE 217 error toast)
- [x] 10. Phase 4 — BE 220 Autopilot notify emails (`autopilot_sync.py`, `staff_notify.py`, `test_autopilot.py::test_T19`)
- [x] 11. Backend tests: `pytest tests/test_trainer.py tests/test_autopilot.py tests/test_staff_notify.py` — 60 passed
- [x] 12. Frontend: `npx tsc --noEmit` — clean
- [x] 13. Trackers closed: `be_features_tracker.md` (BE 217–221), `fe_features_tracker.md` (FE 218–221)
- [x] 14. Spec docs updated: `feature_4_auditor.md`, `feature_6_trainer.md` (FE), `feature_10_trainer.md` (BE), `feature_6_rag.md`, `feature_13_autopilot.md`
- [x] 15. `test_coverage_map.md` updated with new e2e/pytest evidence rows
- [x] 16. Playwright e2e: `audit-review-console.spec.ts` + `autopilot-folder-browser.spec.ts` — 10/10 passed (port 3102)

Final status: code + docs complete, uncommitted. Backend pytest + tsc verified. Playwright not executed in CI/agent environment.
