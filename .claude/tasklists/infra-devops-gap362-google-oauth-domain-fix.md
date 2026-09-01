# Gap 362 — Google Drive OAuth session-loss root-cause fix + blast-radius audit — infra-devops tasklist

Founder-approved scope (from conversation): fix `customDomainName` never being set in
`infra/params.dev.json`, causing `GOOGLE_REDIRECT_URI`/`FRONTEND_URL`/`ALLOWED_ORIGINS`
(bicep-derived) and `NEXT_PUBLIC_WEBSITE_URL` (CI build-arg) to point at the internal CAE
FQDN instead of `invoicellm.admsofttech.com`, even though Front Door already serves that
domain live.

## Part 1 — the fix
- [x] Read `infra/08-apps.bicep` in full, confirm `publicOrigin`/`googleRedirectUri`/
      `corsAllowedOrigins`/`frontendUrl` derivation (root cause confirmed).
- [x] Read `.github/workflows/deploy-dev.yml` `resolve-fqdns` step — confirmed
      `NEXT_PUBLIC_WEBSITE_URL` is built from `ca-invoice-website-dev`'s own ingress FQDN
      (internal), not the custom domain.
- [x] Read `.github/workflows/deploy-prod.yml` — confirmed identical pattern at its own
      `resolve-fqdns` step; prod has no `customDomainName` set yet (placeholder-free but
      empty), so this is a latent bug there too, fix workflow only, no prod deploy.
- [x] Verify live Azure state (not docs) for Front Door: found `invoiceeq-fd-profile` /
      `invoiceeq-fd-endpoint` / route `default-website-route`, custom domain
      `invoicellm.admsofttech.com` Approved and serving 200 OK — confirms task's claim.
      **Also found**: this live Front Door's resource names do NOT match what
      `infra/modules/network/front-door.bicep` would generate from `namingPrefix`/
      `environment` (`afd-invoicellm-dev` etc.) — it was created outside of bicep. Running
      a full Stage 8 bicep deploy with `customDomainName` set would create a **second,
      duplicate** Front Door profile, not update the live one. Flagged to founder;
      deliberately avoided in this fix's deploy step.
- [x] Add `customDomainName` to `infra/params.dev.json` (source-of-truth fix for any
      future full deploy).
- [x] Fix `.github/workflows/deploy-dev.yml`'s `resolve-fqdns` step: `website_url` for
      `NEXT_PUBLIC_WEBSITE_URL` now hardcoded to the custom domain, not
      `ca-invoice-website-dev`'s ingress FQDN.
- [x] Fix `.github/workflows/deploy-prod.yml`'s equivalent step, same pattern, dev domain
      value obviously not applicable — used a placeholder/param-file-driven value, not
      deployed.
- [x] `az bicep build --file infra/08-apps.bicep` — compiles clean with the new param
      value (no bicep source changes needed; the conditional logic already existed).
- [x] Apply the 3 backend env vars live via `az containerapp update --set-env-vars`
      (narrow path, matching the Gap 361/F4 storage-TLS precedent) rather than a full
      Stage 8 `az deployment group create` (which would trigger the duplicate-Front-Door
      side effect above).
- [x] Rebuild+redeploy invoice-fe via `workflow_dispatch` on deploy-dev.yml (forces the
      `fe=true` path per its own `Decide what to deploy` step) so the new
      `NEXT_PUBLIC_WEBSITE_URL` build-arg bakes in.
- [x] Verify live: re-pull `GOOGLE_REDIRECT_URI`/`FRONTEND_URL`/`ALLOWED_ORIGINS` from
      `ca-invoice-be-dev`, confirm custom domain. Re-pull `NEXT_PUBLIC_WEBSITE_URL` from
      the freshly built invoice-fe bundle.
- [x] File Gap in `be_features_tracker.md` (fresh collision check first).

## Part 2 — blast-radius audit
- [x] `services/outbound_email.py` / webhook dispatch sites — check for `FRONTEND_URL`-built
      links.
- [x] `services/support_email.py`/staff notify emails — same check.
- [x] CORS — check FE/website code for any direct browser-to-backend calls bypassing the
      proxy layer.
- [x] SendGrid inbound-parse webhook — confirm still functionally fine as-is, external
      dashboard config, out of scope to change.
- [x] Repo-wide grep for `thankfulmeadow-4281ea23` across `apps/` and `infra/`.

## Final status
Done, 2026-09-01. Filed as tracker Gap 363 (Gap 362 was already taken by a concurrent,
related-but-distinct fix — the `select_account` OAuth prompt bug — found while doing the
fresh collision check). All 3 backend env vars + the FE build-arg verified live via direct
`az` inspection (not assumed). Founder's GCP Console step (add new redirect URI, remove old
one only after confirming) is still outstanding — Drive connect stays broken until then.
Two incidental findings flagged to founder, not actioned: (1) live Front Door was hand-built
outside bicep under different names — a full Stage 8 deploy would have created a duplicate
profile, confirmed via `what-if`, avoided; (2) 3 of 4 "deployed" scheduled jobs
(billing-lifecycle, overdue-sweep, sandbox-sweep) don't actually exist in the resource group.
