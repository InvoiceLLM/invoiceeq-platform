# infra-devops: Enable ENABLE_PRODUCTION_QUALITY_JUDGE live on ca-invoice-be-dev

## Investigation
- [x] Read CONVENTIONS.md + active-work.md — no conflict with in-flight work (F23 3-way comparison, arch-docs support are unrelated files).
- [x] Confirmed `ENABLE_PRODUCTION_QUALITY_JUDGE` is not declared anywhere in `Prod_Invoice_LLM/infra/` (repo-wide grep, zero hits in bicep).
- [x] Confirmed `ENABLE_AGENTIC_SAGE` (the suggested precedent) was NEVER actually a bicep-declared env var either — only ever appears in code comments/KQL/workbook text (`git log -S` across all `*.bicep` history — zero diff hits, only a comment referencing it in `08-apps.bicep`). No real precedent exists there.
- [x] Confirmed `ENABLE_FE_PROXY` (invoice-website.bicep) is the only other `ENABLE_*` flag in bicep today, but it's hardcoded `'true'` unconditionally in the module — not param-driven per environment, so not a direct pattern match for a dev-only override.
- [x] Found the actual pattern to follow: `08-apps.bicep` declares a top-level param with a safe default (e.g. `payuMode string = 'test'`), threads it into `invoice-be.bicep`'s module params, and `params.dev.json`/`params.prod.json` override per environment (same shape as this session's `sharedAcrName` fix).
- [x] Read `.github/workflows/deploy-dev.yml` + `_deploy-service.yml`: confirmed `deploy-backend` job only runs `az containerapp update --image <tag>` — an image-only bump, NEVER applies bicep-declared env vars. A bicep-only change would sit inert until a real Stage 8 deploy, which is out of scope.
- [x] Decision: use `az containerapp update --set-env-vars ENABLE_PRODUCTION_QUALITY_JUDGE=true` directly against live `ca-invoice-be-dev` as the narrow, safe mechanism for immediate effect, AND add the bicep source (default `false`) + `params.dev.json` override (`true`) so future full deploys stay consistent and don't drift/revert this.

## Implementation
- [x] Add `enableProductionQualityJudge` param to `invoice-be.bicep` (default `false`) + env var entry.
- [x] Thread `enableProductionQualityJudge` param through `08-apps.bicep` (default `false`) into the `backendApp` module call.
- [x] Add `enableProductionQualityJudge: true` to `params.dev.json`.
- [x] `az bicep build` on `08-apps.bicep` to confirm it compiles.
- [x] Apply live via `az containerapp update --set-env-vars ENABLE_PRODUCTION_QUALITY_JUDGE=true` against `ca-invoice-be-dev`.
- [x] Verify via `az containerapp show` that the env var is present with value `true` on the active revision.
- [x] Confirm mechanism note left in `08-apps.bicep`/`_deploy-service.yml`-adjacent comment so a future reader knows this env var was set live out-of-band from a CI image bump.

## Docs
- [x] Append additive note to Gap 304 in `be_features_tracker.md` (mechanism + verification).
- [x] Check `feature_20_23_24_ops_workbook.md` for Production Scores empty-state reference — update additively if present.

## Verification
- [x] Live container env var confirmed present via `az containerapp show` (`ENABLE_PRODUCTION_QUALITY_JUDGE` = `"true"`, revision `ca-invoice-be-dev--0000087`, `Healthy`/`Running`, 100% traffic, provisioningState `Succeeded`).
- [x] Container logs checked — clean startup, health/readiness probes passing, no errors from the new env var.
- [x] Queried `AppEvents` in `law-invoicellm-dev` for `agent_eval_run` rows — confirmed zero `run_source: production` rows exist yet (only `run_source: golden` from concurrent F23 work), as expected since flipping the flag doesn't itself generate a turn.
- [ ] Real chat turn generated against live app / founder to generate one, then check `AppEvents` for a new `agent_eval_run` row with `run_source: production` — NOT completed by this agent; documented as founder follow-up (no direct way for this agent to send an authenticated Clerk-signed chat turn against the internal-only-ingress backend).

## Mid-task correction applied
- [x] Coordinator added a standing rule mid-task: every env var's live value must also be visible in `params.dev.json`, never CLI-only. Already satisfied — `enableProductionQualityJudge: true` was added to `params.dev.json` as part of the bicep changes before this instruction arrived; confirmed present, no rework needed.

## Docs
- [x] Append additive note to Gap 304 in `be_features_tracker.md` (mechanism + verification, dated 2026-08-26).
- [x] `feature_20_23_24_ops_workbook.md` Section G row ("What is real data today vs. structurally empty" table) updated additively with the same note.

## Final status
DONE. `enableProductionQualityJudge` param added to `invoice-be.bicep` (default `false`) and threaded through `08-apps.bicep` (default `false`); `params.dev.json` overrides to `true` for dev only; `params.prod.json` untouched (stays off). `az bicep build` clean on both files. Live `ca-invoice-be-dev` updated in place via `az containerapp update --set-env-vars ENABLE_PRODUCTION_QUALITY_JUDGE=true` for immediate effect, verified present on the live healthy revision, and kept in sync with `params.dev.json` per the founder's standing rule. Judge activity verification (a real `run_source: production` `agent_eval_run` row) is a founder follow-up — needs one authenticated chat turn through the app, which this agent cannot generate against an internal-only-ingress backend.
