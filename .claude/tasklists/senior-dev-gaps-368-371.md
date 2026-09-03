# senior-dev — Gaps 368, 369, 370, 371

Scope approved 2026-09-02 (founder gate, via the implementation plan `Prod_Invoice_LLM/docs/gap_368_371_implementation_plan_2026-09-02.md`). Gap 405 proceeds with the plan's recommended default (4th hardcoded permission flag `can_send_invoices`, not a generic feature-visibility mechanism) since no objection was raised. Full test suites deferred to the end per explicit instruction; narrow sanity checks allowed along the way.

## Gap 406 (FE) — Remove Ingestion Directory Scan Field — DONE
- [x] Remove `directoryPath`/`isScanning` state, `handleWatchDirectory()`, and the "OR SERVER PATH" form from `app/ingestion/page.tsx`. Verified zero remaining references via grep.
- [x] Update `feature_3_ingestion.md`.
- [x] Flip Gap 406 in `fe_features_tracker.md`.
- [x] Left BE `POST /invoices/watcher/start` untouched per plan recommendation (a).

## Gap 407 (BE+FE) — Invoice "Review Later" & "Needs Resubmission" States — DONE
- [x] Checked `outbound_invoices.py`: has its own separate status machine (`NEEDS_REVIEW`/`VERIFIED`/`SENT`/`PAID`, `confirm-send`/`mark-paid` endpoints) — decided **inbound only** for this pass, documented as an explicit follow-up.
- [x] Extended `resolve_audit_invoice()`'s accepted status list (`routers/audit.py`) + added a terminal-state guard so neither new status can be set on an already-PAID/REJECTED invoice; confirmed webhook/staff-notify/Drive/email side-effect blocks are untouched (all key on `("PAID","REJECTED")` literally).
- [x] FE: found Gap 318 had already removed `RecentInvoicesTable.tsx`'s row-actions dropdown — added the two new actions to `app/invoices/review/[id]/page.tsx` instead (where finalization actions actually live now), plus status badge colors.
- [x] Updated `feature_7_audit.md`.
- [x] New `tests/test_audit.py` cases (5 new, parametrized): valid transition from AUDIT_REQUIRED; rejected from PAID/REJECTED with correct message; no webhook/staff-notify side effects; 400 message lists all 5 valid statuses. **21/21 passed** (caught and fixed one unrelated stray leftover line from the original file during this run).
- [x] Flipped Gap 407 in `be_features_tracker.md`; added FE cross-reference entry in `fe_features_tracker.md`.

## Gap 404 (FE) — Help Center Ticket History & Status Portal — DONE
- [x] Checked for an existing support service module — none exists; also found `app/api/support/ticket/route.ts` **already has a GET handler** proxying to `GET /support/tickets` (built in Feature 15's Task 15.4, never called). No new proxy route needed — corrected the plan's assumption.
- [x] Checked the actual `GET /support/tickets` response shape (`routers/support.py::list_support_tickets`) — it does **not** return `admin_notes`/`description`/`updated_at`, only `ticket_number`/`subject`/`category`/`priority`/`status`/`source`/`created_at`. Corrected the plan's assumption; panel shows exactly these 7 fields.
- [x] Third tab in `app/help/page.tsx`; new `TicketHistoryPanel.tsx` (loading/error/empty states).
- [x] Updated `feature_15_help_center_support_bot_and_tickets.md` (new Task 15.6 + a correction to Task 15.4's stale "both routes are POST-only" claim).
- [x] Extended `e2e/help-support.spec.ts` with 2 new specs (list + empty state).
- [x] Flipped Gap 404 in `fe_features_tracker.md`.

## Gap 405 (BE+FE) — Granular Role-Based Feature Visibility (`can_send_invoices`) — DONE
- [x] `models.py`: `User.can_send_invoices` column + Alembic migration `dfcfbb60ef1c` (down_revision confirmed via real `alembic heads`; up/down verified against a scratch table).
- [x] `RoleMapper` default dict + `resolve_permissions()` (both `models.py` and `dependencies.py` wrapper) + `permissions_for_key_scope()` + `TenantContext` + `require_can_send_invoices` — all 3/4-tuple unpacking sites found via the type checker's own errors, not a manual grep alone.
- [x] `routers/admin.py`: schemas + assignment.
- [x] Gated `routers/outbound_invoices.py::upload_outbound_invoice` with a second, independent `Depends(require_can_send_invoices)` alongside the existing `require_can_load`.
- [x] FE: `app/admin/page.tsx` 4th checkbox (free via the existing generic `PERMISSIONS.map()`), `useAuth.ts` new field, gated `app/ingestion/page.tsx`'s Sending tab/content/auto-switch via a new `sendVisible = sendEnabled && canSendInvoices`. Deliberately did NOT gate `dashboard/page.tsx`/`invoices/page.tsx`/`NeedsAttentionWidget.tsx` (outbound data visibility, governed by `can_audit` + the tenant flag, not this permission) — documented as a scope boundary, not an oversight.
- [x] Updated `feature_1.1_rbac.md`, `feature_16_settings.md`.
- [x] `tests/test_rbac.py` + `tests/test_api_keys.py`: **77 passed** (4 new). Caught and fixed a real test bug along the way: the positive "both permissions granted" case still 403'd on a separate, pre-existing, unrelated check (`Tenant.send_invoices_enabled` defaulting False) — fixed the test's tenant seeding, not the code.
- [x] Flipped Gap 405 in `be_features_tracker.md` (+ FE tracker cross-ref).

## Final verification (after all four) — DONE
- [x] Full backend `pytest tests/`: **25 failed, 1785 passed, 3 skipped, 5 deselected, 4 errors, 209.84s**. Compared line-by-line against the pre-Gap-368 baseline (25 failed, 1773 passed, 3 skipped, 4 errors, 177.65s, recorded in Gap 403's verification) — **identical set of 25 failures and 4 errors**, all pre-existing/environmental (local Postgres missing a migrated column across unrelated `*_on_postgres` tests; the documented Gap 354 `test_rag.py` failure; unrelated benchmark-telemetry/ops-workbook/connector tests). The +12 passed (1773 -> 1785) is exactly this session's new tests: 9 in `test_audit.py` (Gap 407) + 3 in `test_rbac.py` (Gap 405). Zero regressions.
- [x] `npx tsc --noEmit` on invoice-fe: **clean, exit 0, zero errors** — covers all FE changes across Gaps 368, 369, 370, 371.
- [x] Playwright specs: 2 new in `e2e/help-support.spec.ts` (Gap 404) written and reviewed; not executed in this pass (no `next dev`/browser run in this environment) — same standing caveat this feature's specs have always carried per its own tracker entries.
- [x] Reported real results throughout, including two genuine bugs the tests themselves caught and required fixing (a stray leftover line in `test_audit.py` from an off-by-one file read; a test-setup gap in `test_rbac.py`'s positive Gap 405 case that was hitting a real, unrelated, pre-existing tenant-flag check).

**Final status: ALL FOUR GAPS DONE.** Gap 406 (remove directory scan field), Gap 407 (Review Later / Needs Resubmission states), Gap 404 (ticket history portal), Gap 405 (can_send_invoices permission) all built, documented, and verified. No regressions in the full backend suite; clean frontend typecheck.
