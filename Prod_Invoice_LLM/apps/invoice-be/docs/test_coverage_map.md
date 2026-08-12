# invoice-be Test Coverage Map

Live record of what's actually automated vs. manually verified, and when. Maintained by `functional-tester` per `.claude/CONVENTIONS.md`. Not the same as a `feature_N_*.md`'s Verification Plan (stable design intent) — this is the running log of real test execution.

Automated suite lives at `apps/invoice-be/tests/` (pytest, see `docs/feature_13_test_benchmark_suite.md`).

| Gap / Feature | Test type | Automated or manual | Last verified | Evidence |
|---|---|---|---|---|
| Gap 131 (Google Drive / Salesforce `redirect_uri_mismatch`) | Manual, real backend, real dev Google/Salesforce OAuth client IDs, Playwright headless nav to real authorize URLs | Manual | 2026-08-12 | `test_evidence/gap131_179_oauth_dev_verification/` (2 screenshots + README + log) — CONFIRMED-FIXED in dev: `GET /connectors/auth-url/{provider}` returns the correct `.env`-configured `redirect_uri`, both Google and Salesforce accept it (real sign-in screens render, no `redirect_uri_mismatch`). Full token exchange not completable by an automated agent (same limitation as FE's Gap 96 evidence). Prod out of scope (placeholder OAuth creds, no prod RG yet) |
| BE Gaps 217–218, 221 (Trainer structured rejection, session mode, commit-behavior) | Unit/API | Automated — `tests/test_trainer.py` | 2026-08-12 | 60 passed in gap-resolution run; new: `test_commit_rejects_instruction_like_rule_end_to_end`, `test_set_session_mode_qa_test`, `test_commit_behavior_persists_chat_style` |
| BE Gap 219 (Chat conciseness + style injection) | Unit | Automated — code path in `agents/query_agent.py` | 2026-08-12 | `_CONCISENESS_INSTRUCTION` + `_get_chat_style_block()`; full `test_rag.py` suite not re-run (torch access violation on Windows in vector test) |
| BE Gap 220 (Autopilot notify emails) | Unit | Automated — `tests/test_autopilot.py::test_T19_autopilot_sends_notify_email_after_import` | 2026-08-12 | Mocks `send_email`; asserts review deep link in body when `send_approval_links=True`. Live SendGrid blocked on Gap 125 |
| *(remaining gaps — populate as functional-tester runs scenarios)* | | | | |
