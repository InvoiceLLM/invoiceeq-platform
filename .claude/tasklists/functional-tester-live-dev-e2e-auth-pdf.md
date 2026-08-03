# functional-tester: live Azure dev E2E (auth + RBAC + PDF ingestion)

Started: 2026-08-03
Target: `https://ca-invoice-website-dev.niceflower-311871a3.eastus2.azurecontainerapps.io`
(real Azure Container Apps, invoice-llm-dev RG, rebuilt today; Gap 12 FE-proxy fix
commit 7af252d confirmed live on both invoice-fe/invoice-website images)

## Pre-flight
- [x] Read `.claude/CONVENTIONS.md`
- [x] Confirmed az CLI session (sbanerji@admsofttech.com) has access to invoice-llm-dev RG
- [x] Confirmed live images on ca-invoice-fe-dev / ca-invoice-website-dev are tagged
      `7af252d...` (the Gap12 build-arg fix commit), not a stale pre-fix image
- [x] Baseline unauthenticated curl check reproduced: `/flows`=200, `/dashboard`,
      `/invoices`, `/trainer`, `/settings`, `/chat`=404 (matches prior report)
- [x] Found DB access path: no local psql/firewall access to
      `psql-invoice-llm-dev`, so verification uses `az containerapp exec` into
      `ca-invoice-be-dev` (already has network access + DATABASE_URL) running a
      short python/sqlmodel script piped via stdin (avoids writing secrets to
      any file/output)
- [x] Confirmed baseline DB state before testing: 0 tenants, 0 users, 0 invoices
- [x] Read signup/login/admin pages, provision route, admin.py, dependencies.py
      -- noted a real risk: `get_tenant_context` resolves `role` from JWT claim
      `role` or `org_role`, and FE calls `getToken()` with no template, so
      Clerk's default session token's `org_role` (format `org:admin`) may not
      literal-match `"Admin"` -- flagged to verify empirically in Scenario 2/7
- [x] Located real sample PDF fixture: `apps/invoice-be/tests/benchmark/_scratch/day1/us_US-1-001.pdf`

## Scenario 1 - Signup/provisioning
- [ ] Real browser signup via /signup (org + admin creation)
- [ ] Screenshot of post-signup state
- [ ] DB query: tenant row + admin User row created

## Scenario 2 - Admin login
- [ ] Real browser login as admin via Clerk
- [ ] Confirm lands on /dashboard (not 404) -- first real test of the finding
- [ ] Screenshot + HTTP status of /dashboard nav

## Scenario 3 - Create regular user
- [ ] As admin, use Admin Console (/admin) to create second non-admin user
- [ ] DB query: second User row, role != Admin

## Scenario 4 - Regular user login
- [ ] Log out, log in as regular user
- [ ] Confirm Settings (Admin-only) nav item absent
- [ ] Screenshot of sidebar

## Scenario 5 - Core FE screens through proxy
- [ ] Visit /dashboard, /invoices, /trainer, /settings, /chat while authenticated
- [ ] Record real HTTP status + screenshot per page

## Scenario 6 - PDF upload + processing
- [ ] Upload real sample PDF via /ingestion
- [ ] DB query: Invoice row with extracted fields, status

## Scenario 7 - RBAC spot check
- [ ] Regular user blocked from an admin-only action (e.g. POST
      /api/admin/create-user or GET /api/admin/users) -- 403 or hidden
- [ ] Evidence: real HTTP status/response body

## Wrap-up
- [ ] File evidence under `apps/invoice-website/docs/test_evidence/live-dev-e2e-2026-08-03/`
- [ ] Update/create `apps/invoice-website/docs/test_coverage_map.md`
- [ ] Final chat report: pass/fail per scenario + clear answer on /dashboard 404 question
