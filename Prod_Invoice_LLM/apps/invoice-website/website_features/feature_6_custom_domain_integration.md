# Feature Website 6: Custom Domain Integration (Azure Front Door + WAF)

**Status:** Bicep written and validated 2026-08-18, deployed nowhere yet — a real domain purchase and the manual steps below have not been done. Status lives in `website_features_tracker.md` (Gap 185); this doc is the design record.
**Target Application:** `infra/` (primarily), with config changes flowing into `invoice-website`, `invoice-fe`, and `invoice-be`.
**Intended domain:** `invoiceeq.app` — already hardcoded as `EMAIL_APP_DOMAIN` in `apps/invoice-be/config.py` for the email flows (Gap 124/125), but never bound to anything reachable in a browser.

---

## 1. Overview & Objective

Today the app has no custom domain anywhere — every environment is reachable only at its Azure Container Apps default domain (`ca-invoice-website-{env}.<CAE-default-domain>`, an `azurecontainerapps.io` subdomain). `Cloud_Architecture_Document.md` section 12 documented **Azure Front Door + WAF** as Layer 1 of this app's security architecture from the start (DDoS protection, geo-filtering, a managed WAF ruleset, with DNS meant to CNAME to Front Door rather than directly to the container) — it was never actually built. This feature closes that gap: it adds the Front Door + WAF layer as parameterized, opt-in Bicep, and documents the exact manual sequence (domain purchase → DNS at the registrar → Azure verification → Clerk production cutover → OAuth app updates) needed to actually go live on a real domain once one is purchased.

Only `invoice-website`'s Container App is externally reachable (`external: true`); `invoice-fe` and `invoice-be` are both internal-only (`external: false`), reverse-proxied through the website (the "Multi-Zone" architecture, Gap 12 — built specifically because `azurecontainerapps.io` sits on the Public Suffix List and can't share cookies across its own subdomains). **Only `invoice-website` needs a custom domain / Front Door origin** — `invoice-fe` and `invoice-be`'s ingress are untouched by this feature.

This is additive infra, not a rebuild: with the new `customDomainName` param left at its default (empty), every file this feature touches deploys byte-identical to before. Nothing here forces a cutover.

---

## 2. File Coordinates

* **New module:** `infra/modules/network/front-door.bicep` — the whole Front Door + WAF resource set, parameterized on `customDomainName`:
  - `frontDoorProfile` (`Microsoft.Cdn/profiles`, Standard tier — see the module's own header comment for why Standard over Premium, and what would change that decision).
  - `frontDoorEndpoint` (`Microsoft.Cdn/profiles/afdEndpoints`) — the `*.azurefd.net` endpoint, kept reachable alongside the custom domain (`linkToDefaultDomain: 'Enabled'`) so it's usable during DNS/cert propagation before cutover.
  - `originGroup` / `origin` (`Microsoft.Cdn/profiles/originGroups[/origins]`) — forwards to `invoice-website`'s existing CAE-domain FQDN. A health probe (`HEAD /`, 60s interval) drives Front Door's origin failover.
  - `customDomain` (`Microsoft.Cdn/profiles/customDomains`) — binds `customDomainName`, TLS via Front Door's own auto-issued **managed certificate** (`certificateType: 'ManagedCertificate'`) — a different, unrelated cert mechanism from `Microsoft.App/managedEnvironments/(managed)certificates`, which stay irrelevant now that the Container App no longer terminates this domain's TLS itself.
  - `route` (`Microsoft.Cdn/profiles/afdEndpoints/routes`) — HTTPS-only, HTTP→HTTPS redirect on, wildcard path match to the website origin group.
  - `wafPolicy` (`Microsoft.Network/frontdoorwafpolicies`) — `Microsoft_DefaultRuleSet` v2.1 in `Prevention` mode, plus one custom rule `RateLimitSupportContact`: rate-limits `/api/contact` and `/api/v1/support/contact` by client IP (`contactEndpointRateLimitThreshold`/`contactEndpointRateLimitDurationSeconds` params, default 20 requests / 5 minutes). This is the edge-level mitigation for **BE Gap 249** (no app-level rate limiting on that endpoint) — it does not close Gap 249 itself, since the endpoint still has zero rate limiting if this WAF layer is ever bypassed or misconfigured, and Gap 250 (email-injection) is untouched by this entirely.
  - `securityPolicy` (`Microsoft.Cdn/profiles/securityPolicies`) — associates the WAF policy with both the custom domain and the default `*.azurefd.net` endpoint.
  - Outputs: `domainValidationToken` (the TXT record value GoDaddy needs), `frontDoorEndpointHostName` (the CNAME target), `frontDoorProfileName`, `wafPolicyName`.

* **Edited:** `infra/08-apps.bicep` —
  - New param `customDomainName` (default `''`).
  - New var `publicOrigin` — `customDomainName` when set, else the existing `websiteFqdn` (CAE domain). Feeds `googleRedirectUri`, `salesforceRedirectUri`, and `backendApp`'s `backendPublicUrl`/`publicAppUrl`/`frontendUrl` params — all switch wholesale to the custom domain once set (OAuth redirect URIs, `BACKEND_PUBLIC_URL`, `PUBLIC_APP_URL`, `FRONTEND_URL` are each a single value in this codebase, not a list, so "prefer custom domain, fall back to CAE FQDN" is the only sane shape — see Gap 131 for the precedent of website-FQDN-based redirect URIs).
  - New var `corsAllowedOrigins` — additive, not a switch: keeps the existing CAE FQDN origins and appends the custom domain when set, so CORS doesn't break mid-cutover or if Front Door is ever bypassed.
  - New conditional module `frontDoor` (`if (!empty(customDomainName))`), invoking the module above with `originHostName: websiteApp.outputs.fqdn`.
  - New outputs: `publicUrl`, `frontDoorDomainValidationToken`, `frontDoorEndpointHostName` (the latter two via the `.?outputs.?x ?? ''` safe-dereference pattern already used for `04-ai.bicep`'s conditional Doc Intelligence scale-out modules, since a `module ... = if (...)` reference is `null`-typed when the condition is false).

* **Not touched by this feature:** `infra/modules/compute/invoice-fe.bicep`, `infra/modules/compute/invoice-be.bicep` (both stay internal-only, no domain binding needed), `infra/modules/compute/container-env.bicep` (no `Microsoft.App/managedEnvironments/certificates` needed — Front Door owns TLS for the custom domain now).

* **Manual-steps reference:** `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` §6 (new section) — the GoDaddy DNS records, Azure verification sequence, and Clerk production-instance cutover, in order.

---

## 3. Functionality

1. **Deploying with no domain (current, default state):** `customDomainName` stays `''`. `frontDoor` module doesn't deploy. `publicOrigin` resolves to the CAE FQDN, `corsAllowedOrigins` is unchanged from before this feature. **Zero behavior change** — this is the safe-no-op guarantee this feature was built to keep.
2. **Cutting over once a domain is purchased**, in order (full detail with exact record names/values in `THIRD_PARTY_INTEGRATIONS_SETUP.md` §6):
   1. **Purchase the domain** at GoDaddy (user-owned, outside this repo's scope).
   2. **First bicep deploy with `customDomainName` set, domain not yet DNS-verified**: Front Door profile/endpoint/origin/route/WAF all deploy successfully (none of them require the domain to be live), but the `customDomain` resource sits in a pending-validation state. Read the `frontDoorDomainValidationToken` output.
   3. **GoDaddy**: add a TXT record `_dnsauth.<domain>` = the validation token from step 2, and a CNAME for the domain (or subdomain, e.g. `www`) pointing at `frontDoorEndpointHostName` from the same output. Azure apex-domain limitations apply if binding the bare `invoiceeq.app` rather than a subdomain — GoDaddy supports ALIAS/forwarding records for this case; see the manual guide for the exact choice made.
   4. **Wait for Azure to validate** (DNS propagation + Front Door's managed-certificate issuance, typically minutes to a few hours) — `customDomain.properties.domainValidationState` reaches `Approved`, then the managed cert issues automatically.
   5. **Clerk production cutover** (manual, Clerk dashboard): register the real domain in Clerk, add Clerk's own generated CNAME/DKIM records at GoDaddy (a *different* set of records from step 3, additive to it), then swap `CLERK_SECRET_KEY`/`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in Key Vault from `pk_test`/`sk_test` to the production keys.
   6. **OAuth app updates** (manual, Google Cloud Console + Salesforce Connected App, following the exact pattern already used for Gap 131): update the registered redirect URIs to `https://<domain>/api/connectors/callback/{google_drive,salesforce}` — the bicep-side values already switch automatically once `customDomainName` is set (see File Coordinates above); only the third-party dashboard registrations need a manual edit to match.
   7. **Live verification**: real HTTPS request to the domain returns a valid cert (not self-signed, not Front Door's default cert) and the actual site; login flow completes end-to-end through Clerk's production instance on the real domain; a rapid-fire test against `/api/contact` gets rate-limited by the WAF rule after the configured threshold.
3. **What this does *not* do**: it does not fix BE Gap 249 (still needs an app-level rate limiter — this WAF rule is a mitigation, not the fix) or Gap 250 (email-injection, unrelated). It does not turn on VNet-level lockdown (the architecture doc's "Allow 443 inbound from Front Door only" NSG rule assumes `networkIsolation: true` in `container-env.bicep`, i.e. prod-mode VNet injection — in the current Consumption/dev mode, the Container App's CAE FQDN stays directly reachable even with Front Door in front, since Consumption-plan Container Apps have no NSG-level ingress restriction available). Closing that gap is a separate, larger piece of the still-not-started dev/prod environment split.

---

## 4. Verification Plan

* **Automated (done):** `az bicep build --file infra/08-apps.bicep` compiles clean (exit 0) with `customDomainName` unset — confirms the no-op default doesn't break the existing deployment template. One pre-existing-pattern warning (`BCP081`, no type schema for `Microsoft.Network/frontdoorwafpolicies` in this Bicep CLI version) is non-blocking, documented inline in the module.
* **Not yet done — needs a real domain purchase, tracked as Gap 185:**
  1. Deploy with a throwaway/test subdomain first if possible (e.g. a `test.invoiceeq.app` CNAME) rather than cutting the production entry point over on the first attempt — confirms the whole DNS/Front Door/WAF chain works before pointing the real domain at it.
  2. Confirm the WAF rate-limit rule actually fires: script N+1 rapid requests at `/api/contact` where N = `contactEndpointRateLimitThreshold`, confirm the last one gets blocked, confirm it un-blocks after `contactEndpointRateLimitDurationSeconds`.
  3. Confirm the managed WAF ruleset doesn't false-positive-block real signup/contact-form traffic (a known risk with the OWASP default ruleset and free-text fields like the support message body) — submit a real contact-form message with typical business language and confirm it isn't blocked before relying on `Prevention` mode in front of real users.
  4. Full regression: existing backend pytest suite + both apps' E2E suites still pass with `corsAllowedOrigins` now carrying three origins instead of two.
  5. Confirm the CAE FQDN is still reachable directly post-cutover (expected, per §3 above) and decide whether that's acceptable long-term or needs the VNet-injection follow-up.
