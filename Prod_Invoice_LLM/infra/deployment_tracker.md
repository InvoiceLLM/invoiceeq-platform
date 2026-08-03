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
  chain: Redis+Postgres recreated, RBAC re-granted, real images built manually
  via `az acr build`/`docker buildx build --push` since CI's `AZURE_CREDENTIALS`
  is currently a dead service principal — out of scope to fix here).
  **Two real problems found live, both currently unresolved, need a decision
  before re-running anything further:**
  - `ca-invoice-be-dev` is **crash-looping** (restartCount 6+). Root cause:
    `apps/invoice-be/alembic/env.py`'s `config.set_main_option("sqlalchemy.url",
    settings.DATABASE_URL)` runs the URL through Python `configparser`, which
    treats `%` as interpolation syntax — the current dev DB password
    (`P@ssw0rd12345!`) percent-encodes to `P%40ssw0rd12345%21` via
    `05-secrets.bicep`'s (correct) `uriComponent()` call, and configparser
    chokes on the `%`. `ca-queue-worker-dev` doesn't hit this (its entrypoint
    skips alembic) so it's Healthy/Running; FE and website are also
    Healthy/Running (neither touches Postgres directly).
  - Gap 12's FE-proxy mechanism (invoice-website reverse-proxying invoice-fe)
    **does not work** in the currently-built images even though bicep wires
    `ENABLE_FE_PROXY`/`FE_INTERNAL_URL` correctly as container runtime env vars.
    Both `apps/invoice-website/next.config.js`'s `rewrites()` and
    `apps/invoice-fe/next.config.js`'s `assetPrefix` are evaluated by Next.js
    at `next build` time, not per-request — the same class of bug Gap 6 already
    fixed for `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (needs a Docker build-arg, a
    runtime env var arrives too late). Neither `docker/Dockerfile.website` nor
    `docker/Dockerfile.fe` declares these as `ARG`s, and
    `.github/workflows/deploy-dev.yml` doesn't pass them as `build_args`.
    Confirmed live: `invoice-website:latest`'s baked `routes-manifest.json` has
    `"rewrites":[]`, `invoice-fe:latest`'s baked `required-server-files.json`
    has `"assetPrefix":""`; hitting `/dashboard` through the website returns
    404 with zero new request log lines in FE's own container logs (request
    never reaches FE).
  Ingress split itself (the part that doesn't need a rebuild) is confirmed
  correct: FE + backend FQDNs both `.internal.` (internal-only), website's is
  not (external); CLERK_SECRET_KEY via Key Vault secretRef on both FE and
  website; BACKEND_API_URL correct.
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
