# Infrastructure Deployment Tracker

This file tracks the status of the Azure Bicep infrastructure deployment
for `invoice-llm-dev`. Rebuilt 2026-07-22 into 10 sequential, independently
verifiable stages (see `README.md` for the verification command per stage)
— replaces the old 4-stage `main-step1..4.bicep` layout, which never
completed a clean end-to-end run.

## Deployment Stages

- **[x] Stage 1: Network** (`01-network.bicep`) — VNet, 4 subnets, 7 private
  DNS zones + links, 3 NSGs. Live and matches bicep.
- **[x] Stage 2: Security** (`02-security.bicep`) — Managed identity, Key
  Vault (+ private endpoint). Live vault (`kv-invoice-llm-dev`) currently has
  `publicNetworkAccess: Enabled` for benchmark testing — bicep target is
  `Disabled`; re-run this stage once testing is done to lock it back down.
- **[x] Stage 3: Data Services** (`03-data.bicep`) — PostgreSQL, Redis
  Enterprise, Storage, ACR. Live.
- **[x] Stage 4: Cognitive AI Services** (`04-ai.bicep`) — OpenAI, Doc
  Intelligence. Live, currently manually flipped to `publicNetworkAccess:
  Enabled` for benchmark testing — bicep target is `Disabled`.
  **Update (Jul 23, 2026, Gap 41 scaling work)**: `gpt-5-mini` capacity
  raised live 20→500 (also updated in `openai.bicep`), and 2 more Doc
  Intelligence resources provisioned (`docintel-invoice-llm-dev-2`/`-3`,
  each with its own private endpoint, `publicNetworkAccess: Disabled` from
  creation — these were provisioned correctly private-by-default, unlike
  the original resource's manual public-access override). Also added as
  2 more module instances in `04-ai.bicep`. Applied directly via `az`
  CLI, not through `deploy-all.ps1` (this stage's "do not run until
  benchmark testing is done" caveat above still applies to the *original*
  resource's public-access flip — running the full stage now would
  correctly reconcile that, but wasn't done as part of this change to
  avoid disrupting in-progress benchmark testing on the primary resource).
- **[x] Stage 5: Secret Seeding** (`05-secrets.bicep`) — 7 secrets in Key
  Vault. Decoupled from Stage 2 so it can run after the resources it
  describes actually exist.
  **Update (Jul 23, 2026)**: 4 more secrets added live and in bicep
  (`AZURE-DOC-INTEL-KEY-2`/`-3`, `AZURE-DOC-INTEL-ENDPOINT-2`/`-3`) for
  the 2 new Doc Intelligence resources above.
- **[x] Stage 6: Compute Environment** (`06-compute-env.bicep`) — Container
  Apps Environment + ChromaDB. Live.
- **[x] Stage 7: RBAC** (`07-rbac.bicep`) — 5 role assignments for the
  managed identity. Live.
- **[x] Stage 8: Application Containers** (`08-apps.bicep`) — Backend,
  queue-worker, frontend, and website. Deployment `provisioningState: Succeeded`
  as of 2026-08-03 (full env rebuild after the RG's Aug 2026 deletion/recovery —
  see `.claude/tasklists/infra-devops-dev-rebuild-redis-fix.md` for the full
  chain). **Both real problems previously found here are now fixed and verified
  live (2026-08-03/04):**
  - **Backend crash-loop — FIXED.** Root cause was `apps/invoice-be/alembic/env.py`
    passing `DATABASE_URL` through Python `configparser` (which treats `%` as
    interpolation syntax) with a password that percent-encoded to include `%`
    (`P@ssw0rd12345!` → `P%40ssw0rd12345%21`). Fix: rotated `dbAdminPassword` to
    a pure-alphanumeric value (`Passw0rd1234X`, in `params.dev.secrets.json`,
    gitignored) via a Stage 3 re-run (`03-data.bicep`, `deployPostgres=true` PUTs
    the new password onto the existing `psql-invoice-llm-dev` in place;
    `deployRedis=false` override used since Redis Enterprise was already Running
    and cannot be redeployed in place), then a Stage 5 re-run (`05-secrets.bicep`)
    to re-seed `DATABASE-URL`. Note: a bare Container App revision restart does
    NOT re-fetch an updated Key-Vault-referenced secret value — had to
    `az containerapp secret set` (re-declare the same `keyvaultUrl` ref, which
    forces a resync and explicitly warns a restart is needed) before restarting.
    Confirmed via logs: alembic migration runs clean, Uvicorn starts, healthy
    and stable through a subsequent full CI redeploy.
  - **Gap 12 FE-proxy inert in built images — FIXED**, plus **a second bug found
    during live verification and also fixed**. `docker/Dockerfile.fe` /
    `docker/Dockerfile.website` now declare `ARG`/`ENV ENABLE_FE_PROXY` (website
    also `FE_INTERNAL_URL`), and `.github/workflows/deploy-dev.yml`'s
    deploy-frontend/deploy-website jobs now pass them as `build_args` — mirrors
    the existing Gap 6 pattern for `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`. Verified
    live in the rebuilt images: `invoice-website:latest`'s `routes-manifest.json`
    now has real `rewrites` (was `[]`); `invoice-fe:latest`'s
    `required-server-files.json` now has `"assetPrefix":"/fe-static"` (was `""`).
    Second bug (found via a real logged-in user's `/dashboard` rendering data but
    zero CSS/JS): `apps/invoice-website/next.config.js`'s
    `{ source: "/fe-static/:path*", destination: `${feUrl}/_next/:path*` }` rule
    double-prepended `/_next/` (since `assetPrefix="/fe-static"` already produces
    asset URLs like `/fe-static/_next/static/...`, so `:path*` already contained
    `_next/static/...`), producing a `${feUrl}/_next/_next/static/...` 404 on
    every asset. Fixed by changing the source to
    `/fe-static/_next/:path*` so `:path*` only captures what's after the literal
    `_next/` segment. Verified live: 5 different real `/fe-static/_next/...`
    asset URLs (pulled from the actual rendered `/flows` page) now return 200.
    **Third bug found on real-user retest (page displayed data but zero buttons
    clickable — a hydration failure): FIXED.** Root cause: Next.js's App Router
    does not apply `assetPrefix` uniformly — per-page/layout chunks correctly got
    `/fe-static`, but the App-Router-wide bootstrap set (`rootMainFiles` in
    `build-manifest.json`: webpack runtime, the "23"/"fd9d1056" framework chunks,
    main-app, `polyfillFiles`, and the root layout's own CSS) were emitted as bare
    `/_next/static/...` with no prefix at all — confirmed via the live HTML's
    client-hydration payload literally embedding `"assetPrefix":""` for this
    specific rendering path, even though the same build's
    `required-server-files.json` has `"/fe-static"`. Without the webpack runtime,
    React never initializes client-side. This is a genuine Next.js App Router
    limitation, not an invoice-fe/invoice-website config mistake, so fixed at the
    proxy layer instead: added a fallback rewrite in
    `apps/invoice-website/next.config.js` for bare `/_next/static/:path*` → FE,
    using the **object-form `{ afterFiles: [...] }`** return (not a plain array,
    which Next checks before the filesystem) — `afterFiles` is checked only
    after invoice-website's own local static files, so invoice-website's own
    homepage/login/signup JS+CSS (same generic path, different content hashes)
    always wins locally, and this rule only ever fires as a genuine fallback for
    a hash invoice-website doesn't have (i.e., one of FE's chunks). Verified
    live: all 11 unique asset URLs on a fresh `/flows` load now return 200 with
    correct content-type/size, reproduced on a second independent page load, and
    confirmed invoice-website's own 11 homepage assets are unaffected (still
    served locally) and that a genuinely-fake nonexistent path still 404s (rules
    out an accidental always-200 catch-all).
  Ingress split confirmed correct: FE + backend FQDNs both `.internal.`
  (internal-only, external curl gets a generic 404 from the CAE edge, never
  reaches the app), website's is external; CLERK_SECRET_KEY via Key Vault
  secretRef on both FE and website; BACKEND_API_URL correct. All 4 apps
  (`ca-invoice-be-dev`, `ca-queue-worker-dev`, `ca-invoice-fe-dev`,
  `ca-invoice-website-dev`) confirmed Healthy.
  **CI/CD note**: the `AZURE_CREDENTIALS` service principal (`invoiceeq-dev-cicd`)
  was missing a role assignment on the RG (caused "No subscriptions found" in
  `resolve-fqdns`) — user added Contributor at RG scope manually via Portal
  (confirmed via `az role assignment list`, `createdOn: 2026-08-03T16:34:29Z`).
  Verified fixed via two real `gh run` executions after that point (one
  push-triggered, one explicit `workflow_dispatch`) — both completed
  successfully end-to-end, `resolve-fqdns`'s Azure Login step succeeded both
  times ("Azure CLI login succeeds by using service principal with secret").
- **[ ] Stage 9: Monitoring** (`09-monitoring.bicep`) — Log Analytics
  (existing `law-invoice-llm-dev` gets reconciled), Application Insights
  (new), action group, diagnostic settings, ~16 health/availability alert
  rules. Not yet (re-)deployed this rebuild — `ContainerAppConsoleLogs_CL` is
  already live/flowing regardless (Stage 6's CAE `appLogsConfiguration` alone
  is enough for that), Stage 9 adds the alerting/App Insights layer on top.
  Also note: 09-monitoring.bicep does not currently reference
  `ca-invoice-website-dev` at all (added after this stage's diagnostic-settings
  list was last written) — website has no alert/diagnostic coverage yet,
  pre-existing gap, not introduced by this rebuild.
- **[ ] Stage 10: Budget** (`10-budget.bicep`) — $150/month consumption
  budget with 80%/100% notifications. Not yet deployed.

## Known live drift to clean up manually (not managed by any bicep stage)

- `kv-invoice-llm-dev-rb6z` — orphaned duplicate Key Vault, unused, zero
  RBAC assignments. Delete via Portal.
- `pe-queue-stinvoicellmdev` — duplicate private endpoint for the storage
  account's queue service (twin of `stinvoicellmdev-queue-pe`, which is the
  one Stage 3's bicep declares). Delete via Portal.

## Prerequisites Check

- [x] Azure CLI logged in
- [x] `infra/params.dev.secrets.json` created locally from
      `params.dev.secrets.json.example` (gitignored — never commit real
      values)
