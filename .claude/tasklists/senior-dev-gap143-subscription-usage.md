# Gap 143 — Subscription page reachability + broken usage-limit tracker

Checkpoint 4 of the approved defect remediation plan. Gap 143 only.
Out of scope: Gap 188 Pro-tier cap enforcement; client-side invoice counting.

- [x] 1. Read tracker Gap 143 entry + FE subscriptions page + settings nav (recon)
      - Settings tile for /settings/subscriptions already existed (`app/settings/page.tsx:77-84`);
        the real defect was depth + Sidebar having no entry at all.
- [x] 2. Read BE billing router, `models.Tenant`, `config.Settings`, `refresh_free_quota()`
- [x] 3. `GET /billing/usage` in `routers/billing.py` — `get_billing_usage()` + `BillingUsageResponse`
      (plan/metered/used/limit/remaining/resets_at), no Admin gate, allow_unpaid, clamped to [0, limit]
- [x] 4. FE proxy route `app/api/billing/usage/route.ts`
- [x] 5. Subscriptions page rewired; hard-coded `planLimit` and the /api/invoices call both deleted;
      4 render states (loading / error / metered / not metered)
- [x] 6. Sidebar `Subscriptions` entry (Admin-gated) + `activeHref` longest-match so /settings
      and /settings/subscriptions don't both highlight; `e2e/rbac-sidebar.spec.ts` expectations updated
- [x] 7. Verified: `pytest tests/test_billing.py` 28 passed (9 new); free_quota + lapse 49 passed;
      `npx tsc --noEmit` clean. e2e spec updated but NOT executed.
- [x] 8. `fe_features_tracker.md` Gap 143 -> `[x]`; `be_features_tracker.md` Feature 11 entry extended;
      Gap 188's stale `page.tsx:228` citation corrected (text only, status untouched)
- [x] 9. Specs updated: `invoice-be/docs/feature_11_billing.md` (Task 11.10 + Functionality section),
      `invoice-fe/docs/feature_10_settings.md` (File Coordinates, Functionality, Task 10.4)

Final status: complete, uncommitted. Backend tests + tsc are the only real verification run;
no browser/Playwright run was made and nothing claims one.
