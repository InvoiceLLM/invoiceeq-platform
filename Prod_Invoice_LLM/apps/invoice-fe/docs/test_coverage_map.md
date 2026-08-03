# invoice-fe Test Coverage Map

Live record of what's actually automated vs. manually verified, and when. Maintained by `functional-tester` per `.claude/CONVENTIONS.md`. Not the same as a `feature_N_*.md`'s Verification Plan (stable design intent) — this is the running log of real test execution.

Automated suite lives at `apps/invoice-fe/e2e/` (Playwright — `dashboard-outbound-split.spec.ts`, `group-a-layout-overflow.spec.ts`; a separate, larger planned suite in `docs/feature_12_fe_test_suite.md` was never built, don't confuse the two).

| Gap / Feature | Test type | Automated or manual | Last verified | Evidence |
|---|---|---|---|---|
| Gap 89 (dashboard/outbound split-screen) | E2E | Automated — `e2e/dashboard-outbound-split.spec.ts` | 2026-07-29 | 7/7 passing, see spec file |
| Gap 76 (Trainer Commit button clipped) | E2E | Automated — `e2e/group-a-layout-overflow.spec.ts` | 2026-07-31 | 15 tests, see spec file |
| Gap 81 (outbound upload never leaves UPLOADED) | Manual, real backend (worker killed/restarted mid-test) | Manual | 2026-08-02 | `test_evidence/gap81_outbound_worker_liveness.log` — root cause: no worker process supervision, not an enqueue/delivery bug |
| Gap 84 (inbound/outbound stuck at PROCESSING) | Manual, real backend (corrupted-file OCR failure induced deliberately) | Manual | 2026-08-02 | `test_evidence/gap84_stuck_processing_root_cause.log` — root cause: `handle_process_invoice`/`handle_process_outbound_invoice` never persist a terminal DB status on exception |
| Gap 72 (PDF viewer: wrong PDF / zoom / rotate) | Manual, real non-headless Chromium (Playwright `headless:false`) | Manual | 2026-08-02 | `test_evidence/gap72_pdf_viewer/` (4 screenshots + README) — wrong-PDF ruled out, zoom works, rotate confirmed broken with root cause |
| Gap 82 (Auditor Review click-to-edit) | Manual, real non-headless Chromium, all invoice states (AUDIT_REQUIRED/COMPLETED/REJECTED) | Manual | 2026-08-03 | `test_evidence/gap82_click_to_edit/` (4 screenshots + README) — does NOT reproduce as a broken handler; click-to-edit works correctly on every editable state, correctly disabled on resolved invoices |
| Gap 83 (Outbound Audit redundant tab row) | Manual, real non-headless Chromium | Manual | 2026-08-03 | `test_evidence/gap83_outbound_review_double_shell/` (4 screenshots + README) — root cause: `app/invoices/outbound-review/[id]/page.tsx` still double-wraps in `<Shell>`, the Gap 71 bug class, never fixed on this file |
| Gap 96 (Connectors "Configure" button) | Manual, real non-headless Chromium, real Google OAuth client | Manual | 2026-08-03 | `test_evidence/gap96_connectors_flow/` (4 screenshots + README) — does NOT reproduce; Configure link and Connect/OAuth flow both work correctly. Recommend closing as described |
| Gap 105 (new — Connectors swallows broken-connection errors as "empty folder") | Manual, real backend + DB fault injection (fake-but-valid-format token) | Manual | 2026-08-03 | `test_evidence/gap96_connectors_flow/` (screenshot 4 + `be_502_log_excerpt.txt`) — `FolderTreeExplorer.tsx::fetchFiles()` discards fetch errors, real 502 renders identically to a genuinely empty folder |
| Gap 85 (Dashboard Command Center title crowding) | E2E width sweep (1024-1600px) | Automated — `e2e/group-a-layout-overflow.spec.ts` | 2026-07-31 | Not reproducible across sweep; blocked on reporter's actual viewport/screenshot. Not re-swept 2026-08-03 (no new angle available) |
| *(remaining gaps — populate as functional-tester runs scenarios)* | | | | |
