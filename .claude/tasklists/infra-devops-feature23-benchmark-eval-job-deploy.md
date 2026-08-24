# infra-devops: Deploy caj-benchmark-eval-dev (Feature 23, Wave 2)

Deploying `Prod_Invoice_LLM/infra/benchmark-eval-job-only.bicep`. User explicitly confirmed "Yes, deploy it."

## Step 0 — Read prerequisites
- [x] Read `benchmark-eval-job-only.bicep` header in full (prereqs, cost, second caller design)
- [x] Read `be_features_tracker.md` Feature 23 entries
- [x] Read `.github/workflows/deploy-dev.yml`'s `benchmark-gate` job (override command pattern)
- [x] Read `.claude/tasklists/infra-devops-feature23-ollama-build.md` as the standalone-deploy pattern reference

## Step 1 — Confirm job does not exist yet (live)
- [x] `az containerapp job show --name caj-benchmark-eval-dev` -- confirmed `ResourceNotFound` before deploy

## Step 2 — Verify prerequisites live
- [x] ACR image `acrinvoicellmdev2.azurecr.io/invoice-be:latest` (pushed 2026-08-24T09:12:28Z) contains `benchmarks/` + eval scripts -- `docker run ... python -c "import benchmarks.extraction.harness; ..."` -> `IMPORTS OK`; `scripts/run_extraction_benchmark.py`/`run_agent_eval.py` confirmed present too
- [x] `id-invoicellm-dev` role assignments confirmed live via `az role assignment list`: Key Vault Secrets User (`kv-invoicellm-dev`), Cognitive Services User (`openai-invoicellm-dev`, `docintel-invoicellm-dev`), AcrPull, Storage Blob Data Contributor (`stinvoicellmdev2`)

## Step 3 — Deploy
- [x] `az bicep build` clean
- [x] `az deployment group what-if` -- **1 to create, 52 to ignore**, confirmed narrow/additive
- [x] `az deployment group create` -- `provisioningState: Succeeded`

## Step 4 — Live verification of deployed job
- [x] `az containerapp job show` -- exists, `triggerType: Schedule`, cron `0 3 * * *`, `replicaTimeout: 5400`, container args byte-identical to bicep/08-apps.bicep's canonical declaration

## Step 5 — Real test run
- [x] Found real blocker: `az containerapp job start --command /bin/sh -c --args "..."` (the exact syntax `deploy-dev.yml`'s `benchmark-gate` job uses) fails with `unrecognized arguments: -c` -- reproduced with `--debug`, confirmed it is a genuine argparse limitation (nargs`+` rejects a hyphen-prefixed value), independent of argument order/Windows path mangling. `--yaml` override was also tried as a workaround and found to silently no-op (both schema variants) on this az CLI (2.88.0) -- both attempts fell through to the persisted job template unmodified, causing 2 accidental full real-nightly-cost executions (1 stopped immediately, 1 let run to completion as valid broader evidence)
- [x] Working alternative found and proven live: direct ARM `az rest --method post .../jobs/{name}/start?api-version=2024-03-01` with an unwrapped `StartJobExecutionTemplate` body -- correctly applies command/args override, proven with a cheap `echo` execution (Succeeded, log confirmed)
- [x] Ran the real scoped benchmark-gate command (Track 1 `--mode verify --tolerate-fp`, Track 2 5-case `--no-persist`) via the working `az rest` method
- [x] Polled to completion, pulled logs
- [x] Also let the accidental full-nightly-config execution run to completion as additional real evidence (Track 1 recall 1.0, tolerated FP present as expected; Track 2 real judge-scored turns)
- [x] Recorded actual duration / compute cost for both runs

## Step 6 — Report
- [x] Report live evidence, log output, cost/duration, and whether deploy-dev.yml's benchmark-gate would work as-is -- **finding: it would not, as written**, due to the `--command /bin/sh -c` argparse issue; job/container names and identity RBAC otherwise match exactly
- [x] Leave all files uncommitted

**Final status:** Complete. `caj-benchmark-eval-dev` deployed and live-verified. Two real defects found live, neither pre-existing knowledge: (1) `deploy-dev.yml`'s `benchmark-gate` `az containerapp job start --command /bin/sh -c` invocation fails with `unrecognized arguments: -c` (Python argparse nargs`+` cannot take a hyphen-prefixed value) -- a genuine CLI-level bug, reproduced with `--debug` independent of Windows path mangling/argument order, working alternative proven (`az rest` direct ARM POST with the full persisted `env` array included, since a bare override drops env/secrets and crashes the script on missing settings). (2) The nightly job's own persisted args (`run_agent_eval.py --paths default --run-label nightly`, no `--out`) crash with `FileNotFoundError: tests/agent_eval_output.json` after completing all real work (both tracks scored, 20 DB rows persisted, Track 1 telemetry claimed-mirrored) because `.dockerignore` strips `**/tests/` from the production image -- the deployed 03:00 UTC nightly schedule will fail every night until fixed. Confirmed job's own persisted template untouched by all test overrides.
