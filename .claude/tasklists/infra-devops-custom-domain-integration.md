# Custom Domain Integration (invoiceeq.app) — infra-devops tasklist

Status: **DONE (design + bicep), 2026-08-18.** User chose Path B (Azure Front Door + WAF, matching the original architecture doc) over the direct-binding alternative below. The infra-devops agent that started this hit a session limit before writing any files; the work was completed directly in the main session instead — no half-finished agent output was reconciled, this picks up clean from the read-only investigation below.

**What shipped:** `infra/modules/network/front-door.bicep` (new — Front Door Standard profile/endpoint/origin/route/WAF policy with a rate-limit rule on the support-contact path, gated on a new `customDomainName` param, empty by default = no-op), `infra/08-apps.bicep` (param + conditional module wiring + CORS/redirect-URI updates), `apps/invoice-website/website_features/feature_6_custom_domain_integration.md` (new feature doc), `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` §6 (new manual-steps section), `website_features_tracker.md` Gap 185 (opened). `az bicep build` validated clean on both bicep files (one non-blocking BCP081 warning, documented inline). Nothing deployed to real Azure — this is design + compile-verified code only. Full detail in the feature doc.

Superseded status text below (kept for the investigation record):

## Blocking question (raised mid-task, before any files were written)

`Prod_Invoice_LLM/docs/architecture/Cloud_Architecture_Document.md` section 12
documents Azure Front Door + WAF as the intended Layer 1 in front of Container
Apps (DDoS, geo-filtering, WAF), DNS meant to CNAME to Front Door, not
directly to the container. Never built — no bicep references Front Door.
Section 14.1's cost table scopes Front Door+WAF as **prod-tier only**; no prod
environment exists yet (separate roadmap item, not started).

Two paths:
- **(A) Direct Container App custom domain binding** — what this task
  originally scoped: cheap, works for the current dev-only environment, no
  WAF/rate-limiting.
- **(B) Azure Front Door + WAF in front** — matches the documented target
  architecture, adds real monthly cost, needs scoping alongside/ahead of the
  dev/prod split.

Waiting on the user's call before resuming.

## Investigation done so far (read-only, no edits)

- [x] Read `.claude/CONVENTIONS.md`.
- [x] Read `infra/08-apps.bicep` in full — confirmed `frontendFqdn`/`websiteFqdn`
      computed from CAE default domain (lines 149-150), CORS `allowedOrigins`
      (line 175), OAuth redirect URIs (lines 152-156), and the
      `backendPublicUrl`/`publicAppUrl`/`frontendUrl` params passed to
      `invoice-be.bicep` (lines 182-187).
- [x] Read `infra/modules/compute/container-env.bicep` — confirms the CAE
      (`Microsoft.App/managedEnvironments`) is where a managed cert would
      attach (`Microsoft.App/managedEnvironments/managedCertificates`, not
      `.../certificates` which is the bring-your-own-PFX type — a correction
      worth flagging once we resume).
- [x] Read `infra/modules/compute/invoice-website.bicep` in full — only app
      with `external: true` ingress; confirmed no `customDomains` config
      exists yet.
- [x] Read `infra/modules/compute/invoice-be.bicep` in full — confirmed
      `allowedOrigins`, `googleRedirectUri`, `salesforceRedirectUri`,
      `frontendUrl`, `backendPublicUrl`, `publicAppUrl` params and how they
      map to container env vars.
- [x] Read `infra/06-compute-env.bicep` and `infra/04-ai.bicep` to confirm
      this repo's existing pattern for optional/conditional resources:
      `module x '...' = if (cond) { ... }` + output via
      `x.?outputs.?y ?? ''` safe-dereference (seen in `docIntelligence2`/
      `docIntelligence3` in `04-ai.bicep`).
- [x] Read `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` in full — confirmed
      style (numbered steps, dashboard links, concrete field names) for the
      new DNS/Clerk-production section.
- [x] Read `infra/params.dev.json` / `infra/params.prod.json` — confirmed
      param file conventions (only params without a safe default tend to get
      listed explicitly).

## Design notes captured before pausing (not yet acted on)

- Path A design sketch: new `infra/modules/compute/custom-domain-cert.bicep`
  module (`Microsoft.App/managedEnvironments/managedCertificates`, parented
  to an `existing` CAE reference), invoked conditionally from
  `08-apps.bicep` on `customDomainName != ''`; `customDomains` array added to
  `invoice-website.bicep`'s ingress, conditional; CORS additive
  (`allowedOrigins` keeps CAE origins, appends custom domain); OAuth
  redirect URIs / `FRONTEND_URL` / `BACKEND_PUBLIC_URL` / `PUBLIC_APP_URL`
  switch wholesale to the custom domain when set (fallback to CAE FQDN
  otherwise) since a provider's redirect URI is registered as one exact
  string, not a list, from a single bicep param.
- This sketch is not implemented in any file. If path (A) is confirmed, it
  can proceed largely as designed above. If path (B) is chosen, the same
  investigation is still valid background but the actual resources
  (Front Door profile/endpoint/origin group/WAF policy, DNS CNAME target,
  cert model) differ substantially and the sketch above does not apply as-is.

## Remaining steps (blocked until decision)

- [ ] Bicep changes (shape depends on A vs B decision)
- [ ] `az bicep build` validation on every touched file
- [ ] Feature doc `apps/invoice-website/website_features/feature_6_custom_domain_integration.md`
- [ ] `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` new section
- [ ] New gap in `apps/invoice-website/website_features/website_features_tracker.md`
      (next available number, expected ~185, to be reverified before use)

## Final status
Paused before any file was written or edited — safe to resume in either
direction once the user decides. Report given to the coordinator in chat.
