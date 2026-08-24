# infra-devops: Feature 23 Ollama hosting build (Option A, founder-approved 2026-08-24)

Follow-on to `.claude/tasklists/infra-devops-feature23-gpt4o-ollama-research.md` (research pass, no resource created). This file tracks the actual build.

## Step 1 — Confirm connection wiring
- [x] Confirm `OLLAMA_BASE_URL` (config.py) / `build_llm()` (utils/llm.py) is the setting that needs to point at the new Container App's endpoint
- [x] Confirm known trap: dev machine's local `.env` has `OLLAMA_MODEL=qwen2:0.5b` -- pass `--model llama3.2:latest` explicitly on any eval run

## Step 2 — Confirm real live resource names (avoid params.dev.json drift)
- [x] CAE: `cae-invoicellm-dev` (`az containerapp env list`)
- [x] Storage account: `stinvoicellmdev2` (NOT `stinvoicellmdev` -- same `2`-suffix drift as ACR)
- [x] Confirm existing container apps' ingress posture: `ca-chromadb-dev`/`ca-invoice-be-dev`/`ca-invoice-fe-dev` internal-only, `ca-invoice-website-dev` external -- external ingress is not a new posture for this environment

## Step 3 — Reachability decision
- [x] Confirmed via `feature_23_ai_control_tower.md`'s GPT-4o verification record: `run_agent_eval.py` runs from the LOCAL DEV MACHINE, not from inside the CAE -- external ingress required (internal-only would be unreachable from where the eval script actually runs)
- [x] Locked external ingress down with `ipSecurityRestrictions` (dev machine's public IP, confirmed via ifconfig.me/ipify.org) since Ollama's API has no built-in auth

## Step 4 — Write bicep
- [x] `infra/ollama-eval-only.bicep` -- narrow standalone deploy, same pattern as `gpt4o-deployment.bicep`/`benchmark-eval-job-only.bicep`/`workbook-cost-health-only.bicep`
- [x] Container App: `ollama/ollama:latest`, 4 vCPU / 8 GiB, minReplicas 0 / maxReplicas 1, external ingress on port 11434, IP-restricted
- [x] Persistent Azure Files volume at `/root/.ollama` (same storage account, new file share `ollama-models`) so the model isn't re-pulled on every scale-to-zero cold start
- [x] Startup command overrides default CMD: `ollama serve` backgrounded, poll `ollama list` until ready, `ollama pull llama3.2:latest`, `wait`

## Step 5 — Validate before deploy
- [x] `az bicep build` clean
- [x] `az deployment group what-if` against `rg-invoice-llm-dev` -- confirm narrow/additive. First attempt FAILED live validation: 4.0 vCPU/8.0Gi rejected (`ContainerAppInvalidResourceTotal`) -- `cae-invoicellm-dev` has `workloadProfiles: null` (classic Consumption-only plan, not workload-profile-enabled), real ceiling is 2.0 vCPU/4.0Gi per container app. Corrected bicep defaults, re-ran what-if: **3 to create (containerApp, CAE storage link, file share), 0 to modify** -- confirmed narrow/additive.

## Step 6 — Deploy
- [x] `az deployment group create` -- `provisioningState: Succeeded`. `ca-ollama-eval-dev`, FQDN `ca-ollama-eval-dev.thankfulmeadow-4281ea23.eastus2.azurecontainerapps.io`

## Step 7 — Live verification
- [x] Confirm container app running / revision healthy -- `ca-ollama-eval-dev--tf53li7`, HealthState `Healthy`, `ProvisioningState: Provisioned`, 1 replica
- [x] Confirm model pulled -- `GET /api/tags` returns `llama3.2:latest`, `parameter_size: 3.2B`, `capabilities: ["completion","tools"]` (pull took ~7.5 min for the ~2GB image, watched live via `az containerapp logs show`)
- [x] Real prompt against `/api/generate` -- HTTP 200, real completion ("An invoice is a formal document sent by a supplier...")
- [x] Real run through `scripts/run_agent_eval.py --provider ollama --model llama3.2:latest` against the deployed endpoint (`OLLAMA_BASE_URL` override) -- `llm_calls=1, relevance=1.0 accuracy=1.0 pass=True, errors=0`, output in `tests/agent_eval_output_ollama_llama3_2_latest.json`
- [x] Observe real cost signal -- Azure Retail Prices API confirmed live rate ($0.000024/vCPU-s + $0.000003/GiB-s active = $0.216/hr at the deployed 2.0 vCPU/4.0 GiB; $0 idle at `minReplicas: 0`). Cost Management billing data lags real-time and was not separately queried; this session's own active-replica window (~12-15 min) computes to roughly $0.05 from the confirmed rate.

## Step 8 — Document
- [x] Update `feature_23_ai_control_tower.md` -- new "Ollama candidate — Option A built and live-verified (2026-08-24)" section: endpoint, sizing correction (2.0 vCPU/4.0 GiB, not the approved 4.0/8.0 -- `cae-invoicellm-dev` is the classic Consumption-only plan), external-ingress + IP-restriction rationale, persistent-volume rationale, all live verification evidence, corrected cost estimate (~$1.75/month)
- [x] Update `be_features_tracker.md` Phase 4 entry with the same real deployment details

## Final
- [x] Report back in chat: endpoint/deployment details, verification run + output, real cost if observable, any blocker
- [x] Leave changes uncommitted

**Final status:** Complete. `ca-ollama-eval-dev` deployed, live-verified end-to-end including a real `run_agent_eval.py --provider ollama` run against it. One real blocker/correction hit and resolved: the approved 4 vCPU/8 GiB sizing was rejected live by `cae-invoicellm-dev` (classic Consumption-only plan, ceiling 2.0/4.0) -- deployed at the corrected 2.0 vCPU/4.0 GiB instead, documented in both the bicep comments and the feature doc.
