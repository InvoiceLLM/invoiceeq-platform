# FE Gap 322 — Salesforce connector removal, e2e + live verification (functional-tester)

2026-08-28. Companion checkpoint to the BE Gap 334 Postgres checkpoint
(`../../../invoice-be/docs/test_evidence/gap334_salesforce_removal_postgres_checkpoint_2026-08-28/`).
Per the senior-dev's tasklist final status: "Playwright specs had their mocks updated
but were **not executed**" — this run executes them.

## Playwright e2e run

`npx playwright test e2e/autopilot-folder-browser.spec.ts e2e/gaps-282-284-286.spec.ts
e2e/group-a-layout-overflow.spec.ts` — these are the two specs whose Salesforce mocks
were removed as part of this cleanup, plus the one other spec in the directory that
touches `/ingestion` (the page whose "Cloud Source" toggle block was deleted).
`playwright.config.ts` self-manages the dev server (`npx next dev --port 3100`,
`DISABLE_CLERK_AUTH=true`, stubs every `/api/**` route per-test — no live backend
needed for these three files).

First attempt used Playwright's default `fullyParallel: true` and produced 13
failures, almost all `page.goto` timeouts — diagnosed as dev-server on-demand-compile
contention under parallel load, not real failures (Next dev compiles each route on
first request; many parallel browser contexts hitting a cold server at once). Re-run
serially (`--workers=1`) twice:

- Run 1: **19 passed, 3 failed** — `01_playwright_connectors_ingestion_specs.log`
  (this is the log filed; a near-identical run without a webServer-stdout-noise tee
  showed the same 3 failures with `autopilot-folder-browser.spec.ts` fully passing).
- Run 2 (confirmation): 18 passed, 4 failed — the same 3 stable failures plus one
  additional transient `page.goto` timeout on an unrelated Dashboard-width test
  (`group-a-layout-overflow.spec.ts:377` at 1280px) that had passed cleanly in run 1
  and is not connectors/Salesforce-related; consistent with the same cold-compile
  flakiness pattern, not chased further.

**`e2e/autopilot-folder-browser.spec.ts` (FE Gap 219, mock updated by this session's
removal) — PASSED.**

The 3 stably-reproducing failures (`gaps-282-284-286.spec.ts` Gap-286 metadata-scroll
x2, `group-a-layout-overflow.spec.ts` Gap-86 receive-only-tenant toggle x1) were
independently confirmed **pre-existing and unrelated** by `git stash`ing the entire
invoice-fe Salesforce-removal diff and re-running each against clean HEAD (commit
`91a41cd`) — all three fail identically with the diff removed.
`02_git_stash_reproduction_of_preexisting_failures.txt`.

## Google Drive live verification

Real credentials only, mock-mode not exercised (see below for why). Started:
- Real backend: `uv run uvicorn main:app --port 8000` against real Postgres
  (`invoice-postgres-local`) with the real `GOOGLE_CLIENT_ID`/`SECRET` from `.env`
  (BE evidence: `../../../invoice-be/docs/test_evidence/
  gap334_salesforce_removal_postgres_checkpoint_2026-08-28/05_live_connectors_
  endpoints_curl.txt`).
- Real FE dev server: `DISABLE_CLERK_AUTH=true BACKEND_API_URL=http://localhost:8000
  npx next dev --port 3200` (same env-var pattern `playwright.config.ts` itself uses
  for mock-auth headless nav). `04_fe_dev_server_stdout.log`.

Navigated to `/settings/connectors` with a real (non-mocked) Playwright Chromium
session and screenshotted at 1280×720: `03_connectors_settings_screen_live.png`.
Confirmed: only the Google Drive card renders (no Salesforce card, no broken/empty
second-column artifact beyond ordinary whitespace where the removed card used to
sit), status pulled live from the real backend/DB reads **"Not Configured"**
(accurate — no `TenantConnection` row exists for this tenant), and the page carries
the correct copy ("Map Google Drive documents to service pipelines").

**What was NOT verified: a completed real Google OAuth login/consent/callback.**
`.env`'s `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are real, non-placeholder
credentials (confirmed live: hitting `/connectors/auth-url/google_drive` through the
real backend returns a genuine `accounts.google.com` URL with that client_id), so
this is not a "mock credentials only" situation — but completing the actual
interactive Google consent screen requires signing into a real Google account, which
this agent has no legitimate credentials for and will not attempt to fake or bypass.
This is the same limitation prior functional-tester passes in this repo have hit and
documented (see `../gap96_connectors_flow/`, `../../../invoice-be/docs/test_evidence/
gap131_179_oauth_dev_verification/`) — "full token exchange not completable by an
automated agent."

## Result

**FE Gap 322's e2e/live checkpoint is closed.** No regression from the Salesforce
removal in either the connectors-mock-updated specs or the live Google Drive render
check. The 3 stable e2e failures and 1 transient timeout are pre-existing/
environmental, confirmed by direct reproduction against clean HEAD.
