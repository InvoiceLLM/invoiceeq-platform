# Flags & Infra Checklist

One page to read before and after any deploy or flag change. Sources: `apps/invoice-be/config.py` (defaults), `infra/params.dev.json` / `infra/params.prod.json` (per-env values), `infra/08-apps.bicep` + `infra/modules/compute/*.bicep` (which app carries which env var). Written 2026-09-07 from the committed (HEAD) state; the working tree that day also held uncommitted Feature 29 phase 2 flag additions (`ENABLE_ENTITY_RESOLVER`, `ENABLE_SEMANTIC_VIEWS`, `ENABLE_CERTIFIED_EXAMPLES`, …) which are **not** listed here until they land.

Rule of thumb: a flag only does what `config.py` says **if every process that reads it carries the env var**. Backend, queue-worker and every scheduled job are separate container apps with separate `env:` blocks; setting a flag on one does not set it on the others.

## 1. Application switches

| Flag (`config.py`) | Default | `params.dev.json` | `params.prod.json` | Carried by (bicep env) | Notes |
|---|---|---|---|---|---|
| `ENABLE_GENERIC_EXTRACTION` (F27) | `True` | `true` | not set → bicep param default `false` | BE, Worker | **Do not disable** (pinned 2026-09-05). Off = non-invoices silently become invoices. Prod params must add `enableGenericExtraction: true` before cutover. |
| `ENABLE_GENERIC_DOC_CHAT` (F26 Part 2) | `False` | `true` | not set → `false` | BE, Worker | Dev has it on; config default is off. Content-chat over attached documents. |
| `ENABLE_ASYNC_CHAT_QUEUE` (Gap 280) | `True` | `true` | not set → `false` | BE, Worker | Bicep param default is `false`, opposite of config. Prod params must set it explicitly or chat falls back to the sync path. |
| `ENABLE_CHAT_STREAMING` (F6.1 A3) | `False` | `true` | not set → `false` | BE, Worker | Shipped OFF by default; dev is the only place it is on. |
| `ENABLE_PRODUCTION_QUALITY_JUDGE` (F23) | `False` | `true` | not set → `false` | BE only | Judge runs in the request path on BE; worker/jobs do not carry it. |
| `ENABLE_ANSWER_CONTRACT_GATE` (F29) | `True` | — | — | none (config default only) | Not in any bicep env block; cannot be changed per env without a bicep change. |
| `SANDBOX_KEYS_ENABLED` (F25) | `False` | — | — | none | Public `inv_test_` key issuance. Off everywhere; not in bicep. |
| `ALLOW_MOCK_AUTH` | `False` | — | — | none | Mock-auth prod guard (Gap 359). Must never appear in a bicep env block. |
| `MOCK_EMBEDDINGS` | `False` | — | — | none | Tests only. |
| `CHROMA_USE_SSL` | `False` | — | — | BE, Worker, Jobs = hard-coded `true` | Live Chroma is reached through the CAE ingress on 443 (Gap 422). |
| `AZURE_COST_CLI_FALLBACK` | `False` | — | — | none | Cost workbook fallback. |
| `BENCHMARK_ARTIFACT_UPLOAD` | `True` | — | — | none | Nightly benchmark job uploads artifacts. |

Bicep param defaults (`08-apps.bicep` lines 92-104) are all `false`. Anything not named in a params file therefore deploys as **off**, regardless of `config.py`. That is the single most common way a "working on dev" feature goes dark on a new environment.

## 2. Model deployments (Gaps 465/466, Feature 29)

| Param | dev | prod | Env var on BE / Worker / Jobs |
|---|---|---|---|
| `azureOpenAiDeploymentName` (primary) | `gpt-5.6-luna` | `gpt-5-mini` | `AZURE_OPENAI_DEPLOYMENT_NAME` |
| `azureOpenAiFastDeploymentName` | `gpt-5.6-luna` | not set | `AZURE_OPENAI_FAST_DEPLOYMENT_NAME` |
| `azureOpenAiJudgeDeploymentName` | `gpt-5-mini` | not set | `AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME` |
| `azureOpenAiApiVersion` | `2024-10-21` | `2024-10-21` | `AZURE_OPENAI_API_VERSION` |
| `openAiCapacity` | 300 | 500 | — |

Role → deployment mapping lives in `apps/invoice-be/utils/model_registry.py` (roles primary / fast / judge / chat_summary / long_doc). `gpt-4o`, `astra`, `sol` deployments are gone; any doc or script still naming them is stale. Prod params lack the fast and judge deployment names: fill them in before a prod deploy or the registry falls back to primary for every role.

## 3. Scheduled jobs: declared vs deployed

| Job (bicep module in `08-apps.bicep`) | Standalone template | Deployed on dev? |
|---|---|---|
| `caj-benchmark-eval-<env>` (nightly golden-bank eval) | `benchmark-eval-job-only.bicep` | Yes |
| online-signals job (F23 online quality) | `emit-online-signals-job-only.bicep` | Yes (2026-08-28) |
| chat-doc TTL sweeper (F26 R8) | `chat-doc-ttl-job-only.bicep` | Yes (2026-09-03, Gap 400) |
| `caj-billing-lifecycle-<env>` | `sweep-jobs-only.bicep` | **No** – declared only |
| `caj-overdue-sweep-<env>` | `sweep-jobs-only.bicep` | **No** – declared only |
| `caj-sandbox-sweep-<env>` | `sweep-jobs-only.bicep` | **No** – declared only |
| Autopilot Drive sync (`scripts/autopilot_job.py`) | none | not scheduled by any bicep job; runs from the backend scheduler path only |

Jobs deploy through `scheduled-job.bicep`, which carries Chroma, OpenAI and model env vars but **not** the feature flags in section 1. A job that needs a flag needs the var added to that module.

A full `08-apps` redeploy is blocked by Gap 298 (ACR naming); use the `*-only.bicep` templates for single-resource changes until that is cleared.

## 4. Known gotchas (each has bitten at least once)

- **Chroma port**: `CHROMA_PORT` must be the CAE ingress port (443, SSL on), not the container targetPort (Gap 422). Applies to BE, worker and every job.
- **Key Vault secret refresh**: a Container App revision restart does not re-read a changed Key Vault secret; re-run `az containerapp secret set` with the same `keyvaultUrl` first (deployment_tracker.md, Stage 8).
- **`deploy-all.ps1`** has never completed a clean bicep run end to end; deploy stages individually. Full rebuild + monitoring reconciliation is deliberately deferred until after benchmark and RAG work.
- **Stages 9 (monitoring) and 10 (budget)** are not deployed by the staged runner; the three workbooks and the alert rules went in through their `*-only.bicep` templates. `09-monitoring.bicep` still has no diagnostic coverage for `ca-invoice-website-<env>`.
- **CI/CD must never run tests or benchmarks** (Gap 312). Quality checks are the nightly job only. Do not re-add a benchmark gate to `deploy-dev.yml`.
- **Salesforce residue**: connector removed 2026-08-28 (Gap 334), but `SALESFORCE_CLIENT_ID` / `SALESFORCE_CLIENT_SECRET` / `SALESFORCE_REDIRECT_URI` env vars, the `salesforceClientId` param and the `SALESFORCE-CLIENT-SECRET` Key Vault entry still exist in bicep and both params files. Harmless; remove with the next bicep tidy, never re-wire.
- **Front Door custom domain** (`invoicellm.admsofttech.com`) is on in dev via `customDomainName`; prod params do not set it. Clerk allowed origins, Google OAuth redirect URIs and `ALLOWED_ORIGINS` are all computed from it (THIRD_PARTY_INTEGRATIONS_SETUP.md §6).
- **Email**: inbound on `receive.invoicellm.admsofttech.com`, outbound on `notify.invoicellm.admsofttech.com` via SendGrid; `SENDGRID_*`, `EMAIL_APP_*` vars must be on **both** BE and worker (Gap 124/125 follow-up 2026-08-27 added the worker half). Prod params carry none of these yet.
- **Placeholder prod values**: `params.prod.json` still has `REPLACE_WITH_PROD_*` for Clerk, Google and Salesforce, and `aci-helloworld` images for all four apps. It is a skeleton, not a deployable environment.
- **Key Vault / OpenAI / Doc Intel public access** are manually flipped to Enabled on dev for benchmark work; bicep says Disabled. Re-running Stages 2 and 4 locks them back down (deployment_tracker.md).
- **Live drift not in bicep**: orphaned `kv-invoice-llm-dev-rb6z` vault and duplicate `pe-queue-stinvoicellmdev` private endpoint (deployment_tracker.md).

## 5. Pre-deploy checklist

1. Every flag you expect on is named in the target `params.<env>.json` (section 1). Bicep defaults are off.
2. Primary, fast and judge deployment names are set and exist in the OpenAI account; api-version is `2024-10-21`.
3. `params.<env>.secrets.json` exists locally and has every secret in `05-secrets.bicep` (SendGrid, Clerk, Google, PayU, token encryption, DB password with no `%`-encoding characters).
4. Any new env var was added to **all** of `invoice-be.bicep`, `queue-worker.bicep` and `scheduled-job.bicep` that need it.
5. Alembic head in the image matches `alembic/versions/` (single head; add-only migrations in dev).
6. You are deploying a single stage or a `*-only.bicep` template, not `deploy-all.ps1`.

## 6. Post-deploy checklist

1. `GET /health/readiness` on BE: Postgres, Redis, Chroma all report healthy (Chroma degraded = port/SSL wrong).
2. `GET /config/features` returns the flag set you intended (that is what the FE reads).
3. Worker log shows the extraction queue being polled and `classify_doc_type` running on a test upload.
4. One chat turn completes on the async path (job id present on the message) and, if streaming is on, the SSE stream opens.
5. Nightly benchmark-eval and online-signals jobs show a successful execution within 24 h; production-judge faithfulness alert is quiet.
6. Cost + Health, AI Control Tower and Ops Summary workbooks render with fresh data.
7. Update `deployment_tracker.md` with the date and what moved.

Related: `deployment_tracker.md` (stage status and drift), `THIRD_PARTY_INTEGRATIONS_SETUP.md` (credentials), `NEW_ENVIRONMENT.md` (standing up an env), `docs/architecture/Cloud_Architecture_Document.md` §4.4 and Appendix B (every secret and env var).
