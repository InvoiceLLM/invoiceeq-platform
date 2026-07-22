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
- **[x] Stage 5: Secret Seeding** (`05-secrets.bicep`) — 7 secrets in Key
  Vault. Decoupled from Stage 2 so it can run after the resources it
  describes actually exist.
- **[x] Stage 6: Compute Environment** (`06-compute-env.bicep`) — Container
  Apps Environment + ChromaDB. Live.
- **[x] Stage 7: RBAC** (`07-rbac.bicep`) — 5 role assignments for the
  managed identity. Live.
- **[x] Stage 8: Application Containers** (`08-apps.bicep`) — Backend,
  queue-worker, frontend. Live.
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
