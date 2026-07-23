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
  queue-worker, frontend. Live.
  **Update (Jul 23, 2026, Gap 41 scaling work)**: `ca-queue-worker-dev`
  updated live and reconciled in `queue-worker.bicep` — CPU/memory
  1vCPU/2Gi→2vCPU/4Gi, scale rule `queueLength` 2→15 (bicep previously
  said 5, drifted from live's 2 the whole time — see Gap 41 in
  `be_features_tracker.md`), `maxReplicas` reconciled 5→10 to match live,
  rule renamed `azure-queue-scale-rule`→`queue-depth-scaler` to match
  live's actual name, 4 new Doc Intelligence secrets/env vars wired in.
- **[ ] Stage 9: Monitoring** (`09-monitoring.bicep`) — Log Analytics
  (existing `law-invoice-llm-dev` gets reconciled), Application Insights
  (new), action group, diagnostic settings, ~16 health/availability alert
  rules. Not yet deployed.
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
