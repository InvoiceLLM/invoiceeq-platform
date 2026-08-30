# senior-dev — BE Gap 343 (free-tier quota bypass) + BE Gap 342 (provisioning completion)

Started 2026-08-30. Two independent, contained fixes. Gap 343 is filed under Feature 11
(billing), Gap 342 under Feature 25 (Plug & Play Workflows).

## Ground truth established before writing code

- [x] Read `.claude/CONVENTIONS.md`, `active-work.md`, `feature_25_plug_and_play_workflows.md`
- [x] Read `services/billing_quota.py` — real names are `count_billable_uploads()` +
      `charge_free_quota()` + `locked_tenant_select()`; exhaustion = `HTTPException 402 "Limit reached"`
- [x] Read the two existing call sites: `routers/invoices.py::upload_invoices()` (line ~277) and
      `::start_directory_watcher()` (line ~362) — pattern is read bytes → count → charge → ingest
- [x] Read `routers/connectors.py::trigger_file_import()` — has NO file bytes (the download happens
      in the queue worker), so it can only charge a flat 1 per import request
- [x] Read `services/autopilot_sync.py::run_sync()` — bytes ARE available, after both dedup layers
- [x] Read `routers/outbound_invoices.py::upload_outbound_invoice()` — bytes available at line ~112
- [x] Read `routers/auth.py::provision_tenant()` — idempotency = `pg_advisory_xact_lock` +
      `select(Tenant).where(clerk_org_id == ...)` early return with `is_new=False`
- [x] Read `services/api_keys.py` + `routers/settings.py::rotate_api_key()` for the key-mint shape
- [x] Read `routers/email_ingestion.py::add_email_sender()` for the `TenantEmailSender` shape
- [x] Fresh gap-number collision check on all three trackers (BE max 337, FE max 322 excl. in-flight,
      website 345-348 with 335-344 reserved). Repo-wide grep for `Gap 342`/`Gap 343`: only
      `PLUG_AND_PLAY_STATUS.md` pre-assigns them. Both free.
- [x] `invoice-postgres-local` already up (42h, healthy) — reused, not restarted

## Gap 343 — free-tier quota bypass

- [x] File the Gap 343 entry in `be_features_tracker.md` (Feature 11 / billing)
- [x] `services/billing_quota.py::charge_free_quota()` — `populate_existing=True` on the locked
      SELECT so a caller that already loaded the Tenant row cannot read a stale counter
- [x] `routers/connectors.py::trigger_file_import()` — charge 1 before queueing
- [x] `services/autopilot_sync.py::run_sync()` — charge 1 after dedup, before blob upload;
      402 → FAILED log + break; `quota_exhausted` added to the summary
- [x] `routers/autopilot.py` — surface `quota_exhausted` on `AutopilotSyncResponse`
- [x] `routers/outbound_invoices.py::upload_outbound_invoice()` — count + charge before blob upload
- [x] Tests: `tests/test_billing_free_quota.py` (7 new cases)
- [x] Postgres evidence for the FOR UPDATE behaviour on the new call sites
- [x] Update `docs/feature_11_billing.md` (additive)

## Gap 342 — provisioning completion

- [x] File the Gap 342 entry in `be_features_tracker.md` (Feature 25)
- [x] `routers/auth.py` — `_mint_provisioning_api_key()` + `_seed_admin_email_sender()`,
      both condition-guarded so a webhook retry cannot re-mint
- [x] `TenantProvisionResponse.api_key: str | None` — shown once, never stored/logged in plaintext
- [x] Tests in `tests/test_auth.py` (6 new cases incl. the double-provision case)
- [x] Postgres evidence for the idempotency check under real concurrency
- [x] Update `docs/feature_25_plug_and_play_workflows.md` (Task 25.5 / File Coordinates /
      Verification Plan)

## Final status

Both gaps built and verified, 2026-08-30.

- Gap 343: `tests/test_billing_free_quota.py` **41 passed** (33 pre-existing + 8 new);
  neighbours `test_ingestion.py test_autopilot.py test_connectors.py test_outbound_ingestion.py`
  **62 passed**, no failures. Two pre-existing exact-dict assertions in `test_autopilot.py`
  updated for the new `quota_exhausted` summary key (still exact comparisons).
- Gap 342: `tests/test_auth.py` **53 passed** (47 pre-existing + 6 new);
  `test_settings.py test_api_keys.py test_email_ingestion.py` **59 passed**.
- Combined run across all 9 affected files: **215 passed**, exit 0, nothing skipped.
- Real Postgres (`localhost:5433/invoice_db`, container `invoice-postgres-local`, reused not
  restarted): Gap 343 throwaway script proved the `FOR UPDATE` lock (second connection refused
  with `LockNotAvailable` on `NOWAIT`), the stale identity-map read reproduced (stale `2` vs the
  DB's `0`) and fixed by `populate_existing=True`, 402-on-exhaustion with the row unchanged, and
  `run_sync()` stopping with `quota_exhausted` and zero invoices; probe rows cleaned up.
  Gap 342 reused and extended the existing Postgres concurrency test — two concurrent provisions
  produce one tenant, one raw key (verifying against the surviving stored credential), and one
  sender row. Confirmed running, not skipped.
- No schema change and no migration for either gap.
- Left uncommitted, per this repo's convention.
