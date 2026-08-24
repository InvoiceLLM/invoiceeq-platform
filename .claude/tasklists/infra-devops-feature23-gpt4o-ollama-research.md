# infra-devops: Feature 23 model comparison — GPT-4o deploy + Ollama hosting research

## Task 1 — GPT-4o deployment (approved, execute)
- [x] Identify `openai-invoicellm-dev` resource, region, resource group — `rg-invoice-llm-dev`, `eastus2`
- [x] Check current deployments + TPM usage under the resource — `gpt-5-mini` (300K TPM) already there; `gpt-4o` deployment (10K TPM) found already live, created 2026-08-23 via `infra/gpt4o-deployment.bicep` (prior session, undocumented/unverified until now)
- [x] Check GPT-4o model quota/SKU availability in the resource's region — `OpenAI.GlobalStandard.gpt-4o` regional quota 450K TPM, only 10K in use, comfortable headroom
- [x] Deploy GPT-4o model deployment under existing resource (API version supporting strict mode, `2024-08-01-preview`+) — already deployed (`gpt-4o`, `2024-11-20`, `GlobalStandard`, 10K TPM); confirmed no redeploy needed, bicep re-validated (`az bicep build`, exit 0)
- [x] Verify deployment live with a real test call (not just `az` success) — 3 real calls: raw chat completion, strict-mode `json_schema` structured output, and `run_agent_eval.py --provider azure --model gpt-4o --api-version 2024-08-01-preview` (pass=True, 0 errors)
- [x] State ongoing cost implication (GPT-4o list pricing) plainly — $2.50/1M input, $10.00/1M output tokens, confirmed live via Azure Retail Prices API for `eastus2` `GlobalStandard`
- [x] Update `feature_23_ai_control_tower.md` model-comparison section with real deployment name + verification evidence
- [x] Update `be_features_tracker.md` Phase 4 entry to drop the stale "no GPT-4o deployment exists" claim

## Task 2 — Ollama hosting research (research + proposal only, NO deployment)
- [x] Research llama3.2:latest (3B) CPU-only feasibility for periodic tool-calling comparison
- [x] Check Azure Container Apps GPU support/region availability (real, not assumed) — confirmed eastus2 has NO GPU workload profiles; eastus/westus3/northeurope/swedencentral/australiaeast/uksouth do
- [x] Draft 2-3 sized/costed options (CPU-only on-demand Container App, always-on Container App, GPU-backed Container App) — 3 options documented
- [x] Real Azure pricing per option (monthly/hourly) — confirmed live via Azure Retail Prices API (Container Apps Consumption vCPU/memory/GPU meters, eastus/eastus2)
- [x] Report findings + recommendation in chat, stop — no resource created (confirmed: no `az containerapp create`/`az deployment group create` run for Ollama)

## Final
- [x] Report back in chat: GPT-4o deployment name + live verification, Ollama options awaiting founder decision
- [x] Leave changes uncommitted

**Final status:** Task 1 complete and verified live (deployment name `gpt-4o`). Task 2 is research-only, delivered in chat and in the doc, no resource created — awaiting founder decision on which Ollama hosting option (if any) to build.
