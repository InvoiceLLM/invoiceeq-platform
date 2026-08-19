# invoice-website Test Coverage Map

Live record of what's actually automated vs. manually verified, and when. Maintained by `functional-tester` per `.claude/CONVENTIONS.md`. Not the same as a `feature_N_*.md`'s Verification Plan (stable design intent) — this is the running log of real test execution.

**Automated suite:** `e2e/` (smoke, billing, email relay, proxy mode). Proxy pass (`npm run test:e2e:proxy`) covers Multi-Zone `ENABLE_FE_PROXY` behaviour including Website Gap 184.

| Gap / Feature | Test type | Automated or manual | Last verified | Evidence |
|---|---|---|---|---|
| Website Gap 184 — Multi-Zone proxy rewrites (`/api/billing/usage`, `/api/support/*`) | E2E (proxy mode) | Automated — `e2e/billing-proxy-mode.spec.ts` (Gap 184 block) + `e2e/fe-proxy-stub.mjs` | 2026-08-19 | `npm run test:e2e:proxy` → **6/6 passed**. Stub upstream on `FE_INTERNAL_URL` :3399; website on :3201 with `ENABLE_FE_PROXY=true`. Both paths return `200` + `x-fe-stub: gap-184` — not website 404 / Clerk handshake |
| Feature 3/3.1 pricing cards + signed-out redirect | Manual (interactive Playwright MCP session) | Manual | 2026-07-31 | No committed artifact — see `feature_3_pricing_payu.md` Verification Plan for what was checked |
| *(remaining gaps — populate as functional-tester runs scenarios)* | | | | |
