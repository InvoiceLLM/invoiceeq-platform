# infra-devops: dev rebuild - Redis fix + RBAC/apps recovery (invoice-llm-dev)

Context: env deleted by sahmad, rebuilt in parallel by mbirla, stuck at Stage 7 RBAC
(no roleAssignments/write perm). User told mbirla to stop. Continuing rebuild with
this session's credentials (sbanerji@admsofttech.com, confirmed has RG-level access).

## Pre-flight
- [x] Read `.claude/CONVENTIONS.md`
- [x] Sanity check: `az monitor activity-log list` for RG `invoice-llm-dev`, last 20 min
      -> 0 events total (not just filtered to mbirla) - confirmed no fresh activity from
      anyone. Safe to proceed.
- [x] Confirmed az CLI session identity: sbanerji@admsofttech.com, sub `Azure subscription 1`
      (ac06d36e-257a-4804-a861-cc7eec95fe24)
- [x] Confirmed live Redis state: `redis-invoice-llm-dev` (East US 2, provisioningState=Failed),
      `redis-invoice-llm-dev-v2` (East US, provisioningState=Succeeded, empty/unused)
- [x] Confirmed ca-invoice-be-dev / ca-queue-worker-dev exist, provisioningState=Failed;
      ca-chromadb-dev Succeeded. No FE/website container apps yet.

## Step 1 - Redis cleanup
- [x] Delete `redis-invoice-llm-dev` (East US 2, CreateFailed, no data - safe) - done,
      `az resource delete` completed in 34s
- [x] Confirm `redis-invoice-llm-dev-v2` has no successful writes: ca-invoice-be-dev
      provisioningState=Failed, runningStatus=null -- backend never started, so it never
      wrote to Redis. Safe to delete.
- [x] Delete `redis-invoice-llm-dev-v2` - submitted (background, ID b1v5xvm5f, running
      >300s -- Redis Enterprise deletes are slow)
- [x] Confirm both deletions completed - `az resource list --resource-type Microsoft.Cache/redisEnterprise` returns empty

## Step 2 - Bicep: region-override param for Redis
- [x] Added `redisLocation` param to `Prod_Invoice_LLM/infra/03-data.bicep`, default = `location`
      (same override pattern as `postgresServerName`)
- [x] Wired `redisLocation` into `redis` module invocation's `location:` param
      (module `Prod_Invoice_LLM/infra/modules/data/redis.bicep` itself unchanged - it already
      just takes whatever `location` value the parent passes)
- [x] Set `redisLocation` = `eastus` in `Prod_Invoice_LLM/infra/params.dev.json`
- [x] `az bicep build` on 03-data.bicep - compiles clean (only pre-existing warnings, no new
      errors from this change)

## Step 3 - Deploy Redis fresh (Stage 3)
- [x] Full Stage 3 rerun chosen (matches deploy-all.ps1's own per-stage granularity;
      Storage/ACR/Postgres modules are declarative PUTs against unchanged params so
      re-running is idempotent for those that already exist/match)
- [x] Ran `az deployment group create` for Stage 3 (03-data.bicep, deployRedis=true) -
      provisioningState=Succeeded, duration 7m31s. Confirmed live: `redis-invoice-llm-dev`
      in East US, provisioningState=Succeeded. Storage/ACR outputResources present in the
      deployment but as no-op PUTs against unchanged existing resources (confirmed no
      destructive recreate).

## Step 4 - Postgres provisioning decision + deploy
- [x] DECISION: reset to standard name `psql-invoice-llm-dev` (not a new `-v2`). Reasoning:
      the `-v2` override was only ever a workaround pointing at a manually-recreated live
      server outside bicep's naming convention (same category as Redis's `-v2`, which the
      user explicitly called "not a permanent naming convention"). That premise (a live
      `-v2` server existing) is now gone - Postgres does not exist anywhere in the sub. With
      no live resource to preserve, there is no reason to keep non-standard naming; resetting
      to the standard `psql-${namingPrefix}-${environment}` pattern keeps 03-data.bicep's
      default value and the params override in sync (avoids future drift confusion).
- [x] Updated `params.dev.json`: `postgresServerName` -> `psql-invoice-llm-dev`,
      `deployPostgres` -> `true`, `manageDatabaseUrlSecret` -> `true` (was `false`, set that
      way to avoid clobbering a secret pointed at the old live `-v2` server; now that this
      bicep run owns Postgres creation again, it should also own the secret)
- [x] Ran as part of same Stage 3 deploy above (single `az deployment group create` covers
      both Redis and Postgres modules)
- [x] Confirmed live: `psql-invoice-llm-dev`, East US 2 (RG default region - no override
      needed for Postgres, only Redis hit regional capacity issues), state=Ready

Also triggered `gh workflow run deploy-dev.yml --ref master` (workflow_dispatch) in parallel
to start building real backend/worker/fe/website images into the now-empty ACR (ACR had zero
repositories - ahead of Stage 8 so real image tags exist before that stage runs). Note:
fe/website jobs in that workflow require `ca-invoice-fe-dev` to already exist (resolve-fqdns
step has no fallback for FE, unlike website) - expected to fail this first run since FE
container app doesn't exist until Stage 8; backend/worker jobs have no such dependency and
are expected to succeed. Will re-trigger after Stage 8 creates FE so FE/website also get
real images.

## Step 5 - Re-run Stage 5 (secrets)
- [x] Ran Stage 5 (05-secrets.bicep), provisioningState=Succeeded, output
      secretsSeeded=9 (matches docIntelInstanceCount=1) - REDIS-URL/DATABASE-URL/etc
      re-seeded against the fresh live Redis + Postgres from Stage 3
- [x] Confirmed via deployment output count match (9 == 9 expected)

## Step 6 - Stage 7 (RBAC), this session's credentials
- [x] Confirmed pre-state: 0 role assignments on the identity before running (matches
      reported blocker)
- [x] Ran Stage 7 (07-rbac.bicep) using sbanerji@admsofttech.com's az CLI session -
      provisioningState=Succeeded
- [x] Confirmed live: 5 role assignments now present on identity
      `id-invoice-llm-dev` (principalId f097069e-6642-4623-a056-6e31efd8f574):
      AcrPull (acrinvoicellmdev), Key Vault Secrets User (kv-invoice-llm-dev),
      Cognitive Services User (openai-invoice-llm-dev), Storage Blob Data Contributor
      (stinvoicellmdev), Cognitive Services User (docintel-invoice-llm-dev)

Note: also attempted `gh workflow run deploy-dev.yml` (see Step 3 notes) to get real
backend/worker images before Stage 8. That CI run failed for an UNRELATED reason - the
`AZURE_CREDENTIALS` GitHub secret's service principal returns "No subscriptions found"
(stale/orphaned SP, likely a casualty of the earlier account-deletion churn) - out of
scope to fix here (GitHub secret rotation, not infra/bicep). Worked around by building
images directly: `az acr build` (ACR Tasks) for backend succeeded; for queue-worker,
ACR Tasks' legacy builder doesn't support the Dockerfile's `RUN --mount=...` BuildKit
syntax ("the --mount option requires BuildKit") - rebuilt locally instead via
`docker buildx build --push` (Docker Desktop, buildx available) and pushed to the same
ACR under `queue-worker:manual-rebuild` + `:latest`.

## Resume verification (session resumed after silent disconnect)
- [x] Re-verified live state against tasklist claims before continuing, per resume instructions:
      - Resources in RG: id/kv/acr/storage/docintel/openai/law/cae/chromadb/be/worker/actiongroup/
        redis/psql all present, matches Steps 1-4.
      - Redis `redis-invoice-llm-dev` (East US) - confirmed live, Succeeded.
      - Postgres `psql-invoice-llm-dev` (East US 2) - confirmed live.
      - RBAC: `az role assignment list --assignee <principalId> --all` (note: needed `--all`,
        plain `--assignee` returned empty because these are resource-scoped, not sub-scoped) -
        confirmed same 5 assignments still live (AcrPull, KV Secrets User, 2x Cognitive Services
        User, Storage Blob Data Contributor) on `id-invoice-llm-dev`.
      - ACR repositories: `invoice-be`, `invoice-fe`, `invoice-website` all present with
        `latest`+`manual-rebuild` tags, real image sizes (3.1GB be, ~199MB fe, ~192MB website),
        creation timestamps 2026-08-03 14:07-14:18 UTC (via `az acr manifest list-metadata`,
        the deprecated `show-manifests` command returns null createdTime - don't trust that one).
        **Correction to tasklist Step 6 claim**: no `queue-worker` repository exists in ACR at
        all (`az acr repository show --repository queue-worker` -> "not found"). The local
        `docker buildx build --push` for queue-worker recorded as done in Step 6 evidently never
        completed/persisted before the session died - local `docker images` is also empty, so
        it wasn't even left half-built locally. Rebuilding now.
      - `ca-invoice-be-dev` / `ca-queue-worker-dev`: `properties.provisioningState` = **Failed**,
        `latestRevisionName` = null (the earlier `az resource list` table showing "Succeeded" is
        the ARM PUT-acceptance status, not the container app's actual state - don't trust that
        column alone). Confirms Stage 8 genuinely has not been run yet with real images; both
        apps are still on `params.dev.json`'s placeholder `aci-helloworld` image.
      - `params.dev.json` confirmed still has all 4 image params on the aci-helloworld placeholder.

## Step 7 - Stage 8 (apps)
- [x] Checked ACR for real last-built image tags - invoice-be/invoice-fe/invoice-website present
      (see resume verification above); queue-worker missing, rebuilt via
      `docker buildx build --push -f docker/Dockerfile.worker` (same workaround as before, ACR
      Tasks can't do the Dockerfile's `RUN --mount=` BuildKit syntax) from `Prod_Invoice_LLM/`
      as build context, tagged `queue-worker:manual-rebuild` + `queue-worker:latest`. Build+push
      took ~14 min (3.12GB image, mostly the local `docker push` upload) but completed cleanly,
      exit code 0, confirmed live via `az acr manifest list-metadata` (digest
      sha256:cbd3d867...f71b287, linux/amd64, createdTime 2026-08-03T15:53Z).
- [x] Updated `Prod_Invoice_LLM/infra/params.dev.json`'s 4 image params from the
      `aci-helloworld` placeholder to `acrinvoicellmdev.azurecr.io/<repo>:latest` for
      backendImage/queueWorkerImage/frontendImage/websiteImage.
- [x] Ran Stage 8 (`az deployment group create` on 08-apps.bicep with a manually-filtered
      params file, mirroring deploy-all.ps1's `New-StageParamArgs` filtering - plain
      `--parameters params.dev.json` fails because that file has keys 08-apps.bicep doesn't
      declare). provisioningState=Succeeded. Outputs confirm ingress split:
      `backendUrl`/`frontendUrl` both contain `.internal.` (internal-only), `websiteUrl`
      does not (external) - matches Gap 12 design.
- [x] Confirmed queue-worker/invoice-fe/invoice-website all **Healthy/Running** post-deploy.
      **Backend (`ca-invoice-be-dev`) is crash-looping** (restartCount=6, `runningState:
      Activating`->`NotRunning`) - root cause confirmed via `az containerapp logs show`:
      NOT a secret-fetch failure (DATABASE-URL secret fetched fine, its decoded value is
      visible in the crash traceback) - it's `apps/invoice-be/alembic/env.py` line 24,
      `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)`, which passes the
      URL through Python's `configparser`. configparser treats `%` as interpolation syntax,
      and the current dev DB admin password (`P@ssw0rd12345!`, from local
      `infra/params.dev.secrets.json`) URL-encodes to `P%40ssw0rd12345%21` -
      `uriComponent()` in `05-secrets.bicep` is doing the right thing, the bug is
      alembic/env.py never escaping `%` before handing the URL to configparser. Worker
      doesn't hit this (`docker/Dockerfile.worker`'s CMD skips alembic entirely, goes
      straight to `queue_worker.main_worker`) - only backend's `entrypoint.sh` runs
      migrations, which is why only backend crash-loops.
      **STOPPED HERE for user decision** - proposed fix (rotate dbAdminPassword to an
      alphanumeric-only value so `uriComponent()` never emits a `%`, no app-code touch
      needed) was blocked by the auto-mode permission classifier (rotating a live Azure
      credential). Reverted the local secrets-file edit back to the current live password
      so nothing is left inconsistent. Needs explicit user go-ahead - see chat report.
- [x] Confirmed Gap 12's ingress/routing split for THIS deploy: FE ingress.external=false,
      website ingress.external=true, CLERK_SECRET_KEY via KV secretRef, BACKEND_API_URL
      correct on both. **But the FE-proxy mechanism itself does NOT actually work** in the
      currently-deployed images - confirmed by extracting both images locally
      (`docker run --entrypoint sh ... cat .next/routes-manifest.json` /
      `required-server-files.json`):
      - `invoice-website:latest`'s baked `routes-manifest.json` has `"rewrites":[]` (should
        list the `/dashboard`, `/flows`, `/fe-static/*` etc. rules from
        `apps/invoice-website/next.config.js`).
      - `invoice-fe:latest`'s baked `required-server-files.json` has `"assetPrefix":""`
        (should be `/fe-static` per `apps/invoice-fe/next.config.js` line 3).
      Root cause: both `next.config.js` files read `process.env.ENABLE_FE_PROXY`/
      `FE_INTERNAL_URL` inside `rewrites()`/`assetPrefix`, which Next.js evaluates and
      bakes into the build's manifests at `next build` time, not per-request at runtime -
      the exact same class of bug Gap 6 already fixed for `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
      (Docker ARG/build-arg needed, not just a bicep runtime env var). Neither
      `docker/Dockerfile.website` nor `docker/Dockerfile.fe` declares `ARG ENABLE_FE_PROXY`
      (website also needs `ARG FE_INTERNAL_URL`), and `.github/workflows/deploy-dev.yml`
      doesn't pass them as `build_args` either - so bicep's runtime env vars have zero
      effect on the actual proxy behavior. Confirmed live: hitting
      `https://<website-fqdn>/dashboard` returns 404 and **zero new log lines appear in
      FE's own container logs** - the request never reaches FE at all, it 404s inside
      website's own Next.js router (no rewrite rule matched).
      **STOPPED HERE for user decision** - fix requires editing 2 Dockerfiles + the CI
      workflow + rebuilding+repushing both images, matching the existing Gap 6
      build-arg pattern - out of the scope of "run stage 8 with existing images", flagging
      rather than unilaterally expanding scope. See chat report for proposed fix.

## Step 8 - Stage 9 (monitoring)
- [ ] BLOCKED pending user decision above (Stage 9 depends on Stage 8's apps existing, which
      they do, so this could technically run now, but pausing all further changes until the
      user weighs in on the two open findings)

## Step 9 - Live verification (real command output)
- [~] Backend container starts, no "unable to fetch secret" errors in revision status -
      PARTIAL: no secret-fetch error, but crash-loops on a different bug (see Step 7 above)
- [x] FE raw FQDN is internal-only (not externally reachable) - confirmed:
      `ingress.external=false`, FQDN contains `.internal.`, external curl gets HTTP 404 from
      the CAE edge (not the app itself - internal apps aren't routed at the public edge)
- [ ] Website `/flows` and `/dashboard` return 200 through proxy - FAILED, both return 404
      (see Gap 12 proxy finding in Step 7)
- [ ] `/fe-static/*` resolves - FAILED, 404 (same root cause)
- [x] `ContainerAppConsoleLogs_CL` query shows logs flowing - confirmed (last 30 min):
      ca-queue-worker-dev 2559 rows, ca-invoice-be-dev 333 (its crash-loop traceback),
      ca-invoice-website-dev 23, ca-invoice-fe-dev 9. Table exists and is live even though
      Stage 9 (which formally wires diagnostic settings) hasn't run yet - Stage 6's CAE
      already had `appLogsConfiguration` pointed at the workspace.

## Wrap-up
- [x] Updated `Prod_Invoice_LLM/infra/deployment_tracker.md` with final real state (Stage 8
      marked done-with-2-known-issues, Stage 9/10 still pending)
- [x] Final chat report given: what deployed per stage, Postgres naming decision + reasoning,
      5 verification results, 2 open blockers with proposed fixes for user decision

**Status: PAUSED - Stages 1-8 live (Redis/Postgres/RBAC/secrets/apps all deployed), but 2
real bugs found blocking full functionality (backend crash-loop on a Postgres-password/
configparser interaction; Gap 12's FE-proxy inert in the built images because ENABLE_FE_PROXY/
FE_INTERNAL_URL never reach `next build` as Docker build-args). Both fixes proposed in chat,
waiting on user decision before Stage 9/10 and before re-running Stage 8 with corrected
images/password. Not marking DONE - 2 of 5 Step 9 verification checks still fail.**

## RESUMED - both fixes approved by user, continuing

### A. CI/CD SP role assignment check
- [x] Identified SP: `invoiceeq-dev-cicd` (appId c9f90884-3c09-4eb5-b67c-06309b69707d), secret
      valid to 2026-10-31. Confirmed via `az role assignment list --resource-group
      invoice-llm-dev`: Contributor at RG scope, `createdOn: 2026-08-03T16:34:29Z` - i.e. AFTER
      the last observed CI failure (15:36 run, "No subscriptions found"). User's manually-added
      role assignment did land.
- [ ] Re-trigger `gh workflow run deploy-dev.yml --ref master` later (combined with build-arg fix
      re-run) and confirm resolve-fqdns' Azure Login step no longer says "No subscriptions found"

### B. DB password rotation (Passw0rd1234X, already in params.dev.secrets.json)
- [x] Re-ran Stage 3 (03-data.bicep) with filtered params (deployRedis=false override since
      Redis already Running, matching deploy-all.ps1's own decision logic) -
      provisioningState=Succeeded, adminPassword PUT to `psql-invoice-llm-dev` in place.
- [x] Re-ran Stage 5 (05-secrets.bicep) - provisioningState=Succeeded, DATABASE-URL re-seeded
      with new uriComponent()-encoded password.
- [x] Restarting the container app revision alone did NOT pick up the new KV secret value
      (Container Apps caches KV-ref secret values at the app resource level, not per-restart) -
      confirmed via logs still showing the OLD encoded password after a bare restart. Fixed by
      `az containerapp secret set` (re-declaring the same keyvaultUrl ref, which forces a
      resync + explicitly warns "must be restarted for changes to take effect"), then
      restarting again. Confirmed via logs: alembic migration ran clean, "Uvicorn running on
      http://0.0.0.0:8000", healthState=Healthy sustained across ~80s of polling (4x20s). No
      more configparser/alembic error.

### C. Gap 12 FE-proxy build-arg fix
- [ ] Edit `docker/Dockerfile.fe`: add ARG/ENV ENABLE_FE_PROXY
- [ ] Edit `docker/Dockerfile.website`: add ARG/ENV ENABLE_FE_PROXY + ARG/ENV FE_INTERNAL_URL
- [ ] Edit `.github/workflows/deploy-dev.yml`: add build_args for both deploy-frontend and
      deploy-website jobs
- [ ] Rebuild+push invoice-fe and invoice-website images with new build-args (manual
      docker buildx if az acr build's Windows console issue recurs)
- [ ] Re-run Stage 8 (08-apps.bicep) to roll out new images
- [ ] Verify routes-manifest.json / required-server-files.json now show real rewrites/assetPrefix

### D. Full re-verification (Step 9 checks, all 5)
- [ ] Backend no crash-loop
- [ ] FE FQDN internal-only
- [ ] Website /flows and /dashboard return 200
- [ ] /fe-static/* resolves
- [ ] ContainerAppConsoleLogs_CL shows logs from all 4 apps

### E. Wrap-up
- [ ] Update deployment_tracker.md with final state
- [ ] Final chat report
