# senior-dev — Gaps 419 + 420: parked-invoice workflow (Phases 0 + 1)

Scope approved 2026-09-03 (founder gate) from `02-09-2026/fix_plan_v3_executable.md`, Phases 0 and 1 only. **Phase 2 (resubmission replace workflow + migration) is explicitly NOT in this pass** — it awaits confirmation of the billing/visibility assumptions.

**Gap numbers collision-checked fresh:** repo-wide max was **418** (Feature 6.1 work). 419/420 are free.
**In-flight check (hard rule 5):** `active-work.md` lists Feature 27 and Feature 26 Part 2 as in flight. Neither touches `routers/audit.py`, `RecentInvoicesTable.tsx`, `app/invoices/page.tsx` or `app/invoices/review/[id]/page.tsx`. No overlap.

## Gap 419 (Phase 0) — parking an invoice permanently deletes its alerts
- [x] `app/invoices/review/[id]/page.tsx`: `handleResolve()` must not send `dismissed_alerts` for `REVIEW_LATER`/`NEEDS_RESUBMISSION`, and must not `setAlerts([])` for them.
- [x] `tests/test_audit.py`: assert `sa_alerts` survives both statuses; assert PAID/REJECTED still dismiss (no regression).
- [ ] **NOT DONE** — check whether any already-parked invoice in local Postgres lost its alerts. The local Docker stack was stopped at the time of this pass, so no query was run. Any invoice parked during the 2026-09-03 QA session has permanently lost its alerts (the fix prevents recurrence, it cannot restore what was already erased); those invoices need re-ingesting or their alerts re-deriving. Flagged rather than silently skipped.

## Gap 420 (Phase 1) — parked invoices are unreachable and cannot be un-parked
- [x] `routers/audit.py`: allow `AUDIT_REQUIRED` **from** `REVIEW_LATER`/`NEEDS_RESUBMISSION`, non-Admin. Keep Admin-only + terminal-only for PAID/REJECTED.
- [x] `tests/test_audit.py`: un-park works for non-Admin; Admin-only reopen from PAID/REJECTED still enforced.
- [x] `RecentInvoicesTable.tsx::getStatusBadge()`: add both statuses (currently fall to `default:` = spinning "Processing").
- [x] Audit the other status renderers for the same `default:` shape.
- [x] `app/invoices/page.tsx`: add two filter tabs + `tabToStatusParams()` mappings.
- [x] `app/invoices/review/[id]/page.tsx`: "Return to Audit Queue" button on parked invoices.
- [x] Queue navigation: refresh `auditQueueIds` after parking so "N of M" isn't stale.
- [x] Docs: `feature_7_audit.md`, `be_features_tracker.md`, `fe_features_tracker.md`.

## Verification
- [x] `pytest tests/test_audit.py` green.
- [x] Narrow regression: `test_rbac.py`, `test_api_keys.py` (they assert resolve-path shapes).
- [x] `npx tsc --noEmit` clean.
- [x] Report real numbers, not assumed.

**Final status: done.** Backend `tests/test_audit.py` 30 passed; targeted regression (`test_audit` + `test_rbac` + `test_api_keys` + `test_extraction_quality_rollup`) **113 passed, 0 failed**; `npx tsc --noEmit` clean exit 0. Auto-advance after parking deliberately not built (product decision). Phase 2 not in this pass.
