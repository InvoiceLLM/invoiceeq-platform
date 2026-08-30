# senior-dev — Website Gap 350: sandbox key CTA + claim-at-signup

Filed late (mid-run), after the session restart — recorded honestly rather than
backdated. Items 1–9 were already complete when this file was created.

## Scope
Website-only (`apps/invoice-website`). Wire BE Gap 340's sandbox endpoints into
the anonymous-visitor surface: issue a key from the recipe selector, reveal it
once, and claim the sandbox workspace at real signup. No `invoice-be`/`invoice-fe`
changes, no Admin UI, no widget embed script.

## Steps
- [x] 1. Read CONVENTIONS.md, `feature_7_plug_and_play_workflows.md`,
      `feature_25_plug_and_play_workflows.md` (Gap 340 section in full).
- [x] 2. Read the real backend code, not just the docs: `routers/sandbox.py`,
      `config.py` SANDBOX_* settings, `main.py` route list, `routers/auth.py`
      `provision_tenant()`, `dependencies.py` first-login user creation.
- [x] 3. Answer "can the website know `SANDBOX_KEYS_ENABLED`?" — **no**. No public
      config/status endpoint exists (`main.py` exposes only `/`, `/health`,
      `/health/liveness`, `/health/readiness`), and the sandbox router 404s
      wholesale when off. Issuance has side effects so it cannot be used as a
      probe. Decision: env mirror for rendering + runtime 404→`sandbox_disabled`.
- [x] 4. Gap collision check, fresh: repo max is **349**, no `Gap 35x` anywhere.
      Taking **350**.
- [x] 5. `lib/clientIp.ts` — move `isValidIp`/`resolveClientIp` out of
      `app/api/contact/route.ts` verbatim; contact imports them.
- [x] 6. `app/api/sandbox/keys/route.ts` — anonymous relay, own rate-limit bucket,
      server-built `X-Client-IP` (never forwarded from the caller), backend 404
      mapped to `code: "sandbox_disabled"`.
- [x] 7. `app/api/sandbox/claim/route.ts` — authenticated relay, modelled on
      `/api/auth/provision` (client-minted token preferred, cookie fallback).
- [x] 8. `lib/sandboxKey.ts` + `components/marketing/SandboxKeyCta.tsx` — storage
      bridge and the CTA/reveal; `WorkflowRecipeSelector` CTA slot swapped.
- [x] 9. `app/signup/page.tsx` — `claimSandboxWorkspace()` before
      `provisionTenant()`, never throws, both call sites (initial + retry).
- [x] 10. Coordinator check-in: confirm the `X-Client-IP` forgery requirement is
      met. It is — fresh header literal, no spread, incoming `x-client-ip` never
      read. Comment expanded to record the reasoning.
- [x] 11. `npx tsc --noEmit` clean; `npx next build` clean (15 routes, +2 API).
- [x] 12. Live backend verification: second uvicorn on :8010 with
      `SANDBOX_KEYS_ENABLED=true` against real Postgres → 201 + real `inv_test_`
      key. Default :8000 (flag off) → 404. Relay on :3211 → 201 passthrough.
- [x] 13. Browser click-through of the CTA + reveal + localStorage persistence.
- [x] 14. Verify the flag-off degrade in a real browser (default build, backend
      with the flag off).
- [x] 15. Clean up: revert Next's tsconfig.json edit, delete `.next-sandbox` and
      the temp script, stop background servers.
- [x] 16. Update `feature_7_plug_and_play_workflows.md` (§4, §5 Task 7.5, §6, §7).
- [x] 17. Update `website_features_tracker.md` — Gap 350 entry + Feature 7 index line.

**Final status:** complete. Gap 350 built, typechecked, built, and verified
against a real local backend + real Postgres in both flag states. Not verified:
a full real-Clerk signup end-to-end (no usable Clerk credentials in this
environment — the dev instance loops on the handshake), so the claim call was
exercised through its relay rather than from a completed signup. Stated as such
in the doc and the tracker; not claimed as more than it is.
