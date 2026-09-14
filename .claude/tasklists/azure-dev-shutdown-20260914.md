# Azure dev environment — stopped 2026-09-14 (founder: "Stop the azure environment also")

Resource group `rg-invoice-llm-dev`, subscription `InvoiceLLM`.
Everything below is REVERSIBLE. Nothing was deleted.

## What was stopped

| Resource | Before | After |
|---|---|---|
| ca-invoice-be-dev | min 1 / max 5 | min 0 / max 1 |
| ca-invoice-fe-dev | min 1 / max 2 | min 0 / max 1 |
| ca-invoice-website-dev | min 1 / max 3 | min 0 / max 1 |
| ca-queue-worker-dev | min 1 / max 10 | min 0 / max 1 |
| ca-chromadb-dev | min 1 / max 1 | min 0 / max 1 |
| psql-invoicellm-dev | Ready | **Stopped** |

`az containerapp stop` does not exist in this CLI version and `--max-replicas 0` is rejected
(valid range [1,1000]), so scale-to-zero via `--min-replicas 0` is the available stop.

## Scheduled jobs — parked, originals recorded here

All six had their cron replaced with `0 0 31 2 *` (31 February — never fires), because they run
between 02:00 and 06:00 and would otherwise hit a stopped database overnight and trip the alert
rules. Original expressions:

| Job | Original cron |
|---|---|
| caj-overdue-sweep-dev | `0 2 * * *` |
| caj-benchmark-eval-dev | `0 3 * * *` |
| caj-sandbox-sweep-dev | `0 4 * * *` |
| caj-chat-doc-ttl-dev | `0 5 * * *` |
| caj-billing-lifecycle-dev | `0 6 * * *` |
| caj-online-signals-dev | `15 0,6,12,18 * * *` |

## RESTORE — paste this to bring the environment back

```bash
RG=rg-invoice-llm-dev
az postgres flexible-server start -g $RG -n psql-invoicellm-dev

az containerapp update -g $RG -n ca-invoice-be-dev      --min-replicas 1 --max-replicas 5
az containerapp update -g $RG -n ca-invoice-fe-dev      --min-replicas 1 --max-replicas 2
az containerapp update -g $RG -n ca-invoice-website-dev --min-replicas 1 --max-replicas 3
az containerapp update -g $RG -n ca-queue-worker-dev    --min-replicas 1 --max-replicas 10
az containerapp update -g $RG -n ca-chromadb-dev        --min-replicas 1 --max-replicas 1

az containerapp job update -g $RG -n caj-overdue-sweep-dev     --cron-expression "0 2 * * *"
az containerapp job update -g $RG -n caj-benchmark-eval-dev    --cron-expression "0 3 * * *"
az containerapp job update -g $RG -n caj-sandbox-sweep-dev     --cron-expression "0 4 * * *"
az containerapp job update -g $RG -n caj-chat-doc-ttl-dev      --cron-expression "0 5 * * *"
az containerapp job update -g $RG -n caj-billing-lifecycle-dev --cron-expression "0 6 * * *"
az containerapp job update -g $RG -n caj-online-signals-dev    --cron-expression "15 0,6,12,18 * * *"
```

A redeploy of `infra/` also restores every value above from `params.dev.json`, so this drift is
self-healing — it does not need to be reverted by hand before the next deploy.

## STILL RUNNING AND STILL BILLING — these cannot be stopped, only deleted

Not touched, because deleting them is destructive and was not asked for:
- `redis-invoicellm-dev` (Redis Enterprise) — **no stop operation exists**; delete is the only way
  to stop the charge, and it would have to be recreated and re-secreted.
- `invoiceeq-fd-profile` (Front Door) — fixed cost; the endpoint can be disabled but the profile bills.
- `acrinvoicellmdev2` (Container Registry) — holds every image the environment deploys from.
- `openai-invoicellm-dev`, `docintel-invoicellm-dev` — pay-per-call, so ~zero while idle.
- Log Analytics / App Insights — ingestion-based, ~zero while nothing is running.

Founder decision needed if the goal is to cut cost to the floor rather than to stop the app.
