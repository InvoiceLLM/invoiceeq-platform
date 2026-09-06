# Gaps 465 + 466 — model registry, GA api-version, harness gate (migration plan steps 0/1/2/4)

Founder-directed 2026-09-05 ("do the real work now") from the model-selection audit and
the GPT-5.6 migration plan. Gap numbers collision-checked: max in use 462, 463/464
reserved → 465 (registry/api-version/infra) and 466 (harness gate).

## Step 0 — fix now
- [x] `utils/token_management.py`: delete `MODEL_CONTEXT_LIMITS`; limits/encodings from the registry; default 128k not 8k.
- [x] `AZURE_OPENAI_API_VERSION` → `2024-10-21` GA in `config.py`, `.env`, `.env.example`, `e2e-regression.yml`; verified live with strict json_schema against gpt-5-mini.
- [x] One bicep param `azureOpenAiApiVersion` (params.dev/prod → 08-apps + 4 job-only files → 3 compute modules); literals removed.

## Step 1 — harness as gate (Gap 466)
- [x] `tests/run_extraction_harness.py`: field scoring, Scores sheet, `InvoiceEQ_Scores_<label>.json`, p50/p95, tokens + USD via registry, `--min-accuracy` exit code.
- [ ] **Baseline run on gpt-5-mini** — founder to start (real tokens, backend up with ALLOW_MOCK_AUTH).

## Step 2 — registry (Gap 465)
- [x] `utils/model_registry.py` (catalog, longest-prefix match, roles, cost).
- [x] `config.py`: `AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME`, `DOC_INTEL_MODEL_ID`, `EMBEDDING_MODEL_NAME`; defaults `gpt-5-mini` / `2024-10-21`.
- [x] Consumers: `build_llm` (reasoning guard, `get_llm_for_role`), `handlers._run_ocr`, `chroma_client` (model + cache prefix), `run_agent_eval` cost basis, workbook KQL price rows (gpt-5.6 ×3).
- [x] `04-ai.bicep`: `azureOpenAiModelName` split from deployment name; `params.*.json` carry both.
- [x] `tests/test_model_registry.py` (19 tests).

## Step 3 — swap (NOT DONE, needs founder go)
- [ ] `az deployment group create … -f infra/model-deployment.bicep -p deploymentName=gpt-5.6-luna modelName=gpt-5.6-luna modelVersion=2026-07-09` on dev.
- [ ] Set `AZURE_OPENAI_FAST_DEPLOYMENT_NAME=gpt-5.6-luna` (params.dev.json + live app env).
- [ ] Harness runs with Luna and Terra as primary; pick by numbers.

## Step 4 — cleanup
- [x] `infra/gpt4o-deployment.bicep` deleted → `infra/model-deployment.bicep`.
- [x] `gpt-4o-mini` default replaced.
- [x] CI: e2e workflow api-version matches params (still a literal there; workflow does not read params.json).

## Step 5 — SAGE re-eval after swap: not started (depends on step 3).

## Docs
- [x] Tracker Gaps 465/466; `feature_2` §"Model registry"; `feature_6` §8; `feature_13` §"Model-swap gate"; infra comments.

## Status
**PAUSED by the founder 2026-09-05** ("other code changes happening; once done we will do the audit and migration").
Code complete for steps 0/1/2/4, uncommitted, sitting in the Changes panel. Targeted tests 248 passed / 1 skipped.
Full-suite checkpoint was stopped at 22% (4 failures seen, all in files this work does not touch; baseline is 43 known) —
re-run `uv run pytest -q --ignore=tests/us` on resume and fill the `FULL_SUITE_PLACEHOLDER` line in tracker Gap 466.
On resume: (1) re-audit against whatever the other changes touched (utils/llm.py, config.py, handlers.py, chroma_client.py,
bicep compute modules are the collision points), (2) full-suite checkpoint, (3) founder go for step 3 deployment + baseline run.

## Founder plan for resume (given 2026-09-05, supersedes the old step 3/5 lines above)

STEP 2 — deploy candidates on the DEV account only, capacity 50 each, delete after:
  gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol, gpt-6-astra (if in region; else note + skip).
  Record each in Gap 466 with capacity + price. Uses infra/model-deployment.bicep.

STEP 3 — local benchmark matrix (local env → dev Azure), models = [gpt-5-mini baseline, luna, terra, sol, astra]:
  a. Extraction: tests/run_extraction_harness.py --deployment <m>, 27 PDFs → field accuracy, line-item P/R, cost/invoice, p95
     (harness needs a --deployment flag + line-item P/R scoring — not built yet)
  b. Doc-type classification: document_type_classifier LLM-fallback on e2e regional fixtures → accuracy (runner not built yet)
  c. Text-to-SQL: golden_sql_examples via run_agent_eval --model <m> → exec-correctness, repair attempts, p95
  d. Chat/narration: agent_eval_golden_sample via run_agent_eval --model <m> → judge score, p95, cost
  e. Judge stability: score run (d) of gpt-5-mini with each model as judge → variance vs current
  Same prompts, api-version 2024-10-21, same seeds, no prompt edits, run once, rerun only on transient errors.
  Output: docs/extraction_benchmark/runs/matrix-<date>/ — one JSON per (model, task) + summary.md.
  [WAIT for founder]

STEP 4 — analysis, no code changes:
  1. Matrix table rows=tasks a–e, cols=models, cells = primary metric + cost/1k calls + p95.
  2. Per-role recommendation (primary/fast/judge/escalation). Rule: cheapest within 1 point of best wins;
     Astra/Sol only if they beat Terra by >2 points on extraction.
  3. Any field <80% on ALL models → OCR/prompt problem, flag, not a model problem.
  4. Delete deployments not recommended.
  5. Update Gap 466; write rollout plan dev → soak → prod; do NOT apply.
  Also: add a "Model comparison" workbook panel (llm_agent_call + agent_eval_run grouped by model/run_source)
  so cost/p95/judge per model are visible in the AI Control Tower.
  [WAIT — founder decides from the table]

## Matrix run notes (2026-09-05)
- Baseline `gpt-5-mini` extraction ran before the outbound-upload 403 fix (test tenants had `send_invoices_enabled=false`; flipped in DB 10:00 UTC). 9/27 rows errored, none model-related.
- Founder 10:25 UTC: do NOT re-run extraction for every model; re-run the baseline extraction once at the end, then compare.
- Status emails every 10 min to sbanerji@admsofttech.com via SendGrid (scratchpad `send_status_email.py`); hard stop 11:18 UTC for discussion.
- 10:35 UTC founder: run models in parallel. Serial orchestrator killed after baseline + Luna (a,b); Luna (c,d), Terra, Sol, Astra (a–d) now run as 4 concurrent orchestrators into the same matrix dir, staggered 75 s (a concurrent torch weight load segfaulted the first baseline re-run). Task (e) for all models + summary regeneration runs after the parallel phase.
- Follow-up (not built, founder-suggested): cache Document Intelligence output per PDF hash in the harness so every candidate reuses one OCR pass — saves ~5-10 s and ~$0.01/page per model×invoice, and removes OCR variance from the comparison. Needs a Gap entry before coding.
