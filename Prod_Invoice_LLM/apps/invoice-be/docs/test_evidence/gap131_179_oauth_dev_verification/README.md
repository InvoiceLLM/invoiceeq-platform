# Gap 131 [BE] / Gap 179 [FE] — Google Drive / Salesforce `redirect_uri_mismatch` — dev verification

Checkpoint 1 of the 17-checkpoint remediation plan. Pure verification, no code
changes. Real local dev stack (docker compose Postgres/Redis/Chroma/Azurite +
real `uvicorn` backend on :8000 + real `invoice-fe`/`invoice-website` dev
servers), 2026-08-11. Real, non-placeholder Google/Salesforce OAuth client
credentials configured in `apps/invoice-be/.env` (dev app registrations).

## What was verified and how

Confirming/denying `redirect_uri_mismatch` does **not** require completing a
real human sign-in — both Google and Salesforce validate the `redirect_uri`
parameter against their registered callback URLs synchronously, at the point
the authorize URL is first loaded, before any credentials are entered. This
matches this repo's own established precedent for this exact limitation
(`apps/invoice-fe/docs/test_evidence/gap96_connectors_flow/README.md`,
2026-08-03: "Could not complete a full real sign-in... Google's own sign-in
also expects a live human"). An automated agent cannot complete Google's/
Salesforce's live login (2FA, CAPTCHA, human-click-through), so this
checkpoint verifies everything up to and including that validation step, the
same boundary Gap 96's evidence already established as the practical limit.

Steps:
1. `GET http://localhost:8000/api/v1/connectors/auth-url/google_drive` and
   `.../salesforce` (real backend, mock-auth tenant context) →
   `be_log_excerpt_authurl.txt` — both return real `auth_url`s with
   `redirect_uri=http://localhost:8000/api/v1/connectors/callback/{provider}`,
   sourced directly from `settings.GOOGLE_REDIRECT_URI` /
   `settings.SALESFORCE_REDIRECT_URI` (`routers/connectors.py::get_auth_url`,
   `.env`'s dev values) — not from `websiteFqdn`/FE FQDN construction (that
   logic only exists in `infra/08-apps.bicep`, which does not apply to bare
   local dev; see the "not evaluated" note below).
2. Playwright (headless Chromium) navigated directly to each returned
   `auth_url` (no login attempted) and screenshotted the result.

## Result: no `redirect_uri_mismatch` on either provider

**Google** (`1_google_authorize_screen_no_mismatch.png`): real "Sign in with
Google... to continue to **Invoice-LLM**" screen — Google recognized the
`client_id`/`redirect_uri` pair as valid and registered. A mismatch would have
shown "Error 400: redirect_uri_mismatch" instead of a sign-in form.

**Salesforce** (`2_salesforce_authorize_screen_no_mismatch.png`): real
Salesforce login form rendered (username/password fields, "Salesforce
login"). The "Access Denied" panel visible on the right of that screenshot is
an unrelated Akamai/edge 403 on a static promo asset
(`c.salesforce.com/login-messages/promos.html`) inside an iframe on
Salesforce's own login page — not a rejection of this app's `client_id` or
`redirect_uri`; the login form itself rendered normally, which a genuine
redirect_uri/client mismatch would have prevented.

## What was NOT verified (explicitly out of scope / infeasible for this checkpoint)

- **Completing the actual sign-in and token exchange.** Same limitation as
  Gap 96's evidence. `TenantConnection` table is empty post-test (confirmed
  via `docker exec ... psql -c "SELECT * FROM tenantconnection;"` → 0 rows) —
  no live OAuth flow was completed, by design.
- **Prod-specific verification** — explicitly out of scope per this
  checkpoint's brief (prod OAuth client IDs are still placeholders in
  `params.prod.json`, prod resource group doesn't exist).
- **`infra/08-apps.bicep`'s `websiteFqdn`-based redirect URI construction**
  (lines 143-144, the actual subject of Gap 131's "closed 2026-08-10" tracker
  entry) — this is Container Apps deployment-time logic and does not execute
  in bare local dev at all (local dev reads `GOOGLE_REDIRECT_URI`/
  `SALESFORCE_REDIRECT_URI` straight out of `.env`, no bicep involved). This
  checkpoint confirms the **application code** (`routers/connectors.py`)
  correctly uses whatever redirect URI it's configured with and that a
  correctly-configured redirect URI is accepted by both providers — it does
  **not** re-verify the bicep computation itself, which would require an
  actual Azure dev deployment to observe end-to-end (out of scope here; no
  bash/infra changes were made).

## Related, distinct finding (not Gap 131/179 itself) — local-dev-only post-token redirect target

Not a `redirect_uri_mismatch` and does not affect the verdict above, but
found while tracing the full flow and worth flagging for whoever picks up
Gap 131/179 downstream: `routers/connectors.py::oauth_callback` redirects the
browser to `f"{settings.FRONTEND_URL}/settings/connectors?connected={prov}"`
after a successful token exchange. In this local dev `.env`, `FRONTEND_URL`
is **not set**, so it defaults to `config.py`'s `http://localhost:3000` —
which is `invoice-website`, not `invoice-fe` (`:3001`, where `/settings/*`
actually lives). `invoice-website` does have a same-path FE-proxy rewrite
mechanism (`next.config.js`'s `rewrites()`, gated on `ENABLE_FE_PROXY=true` +
`FE_INTERNAL_URL`), but neither env var is set in this local dev stack's
`.env.local`, so the rewrite is inert here. Confirmed live:
`curl http://localhost:3000/settings/connectors` → `404` (Next.js's own
not-found page, `apps/invoice-website` build). This would only matter for a
real completed local OAuth flow's final bounce-back — the OAuth
authorize/redirect_uri leg itself (this checkpoint's actual scope) is
unaffected. Flagging rather than fixing, per this checkpoint's read-only
scope; whoever picks this up next should decide whether to set
`FRONTEND_URL=http://localhost:3001` in local `.env`, or enable the FE-proxy
vars, so a completed local OAuth connect lands somewhere real.

## Verdict

**Gap 131 [BE] / Gap 179 [FE]: CONFIRMED-FIXED** for the specific claim in
scope — the dev-configured `redirect_uri` sent to Google Drive and
Salesforce for the OAuth authorize step is correct and accepted by both
providers (no `redirect_uri_mismatch`), consistent with the tracker's closed
status and the architect's static read of `08-apps.bicep`. Full token-exchange
completion remains unverified (infeasible for an automated agent, same as
Gap 96's precedent) and prod is out of scope per this checkpoint's own brief.
