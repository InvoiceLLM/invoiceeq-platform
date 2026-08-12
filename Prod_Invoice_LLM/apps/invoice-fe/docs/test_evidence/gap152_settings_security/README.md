# Gap 152 — Settings → Security route — dev verification

Checkpoint 1 of the 17-checkpoint remediation plan. Pure verification, no
code changes. Real local dev stack (`invoice-fe` on :3001, Clerk auth bypassed
via `DISABLE_CLERK_AUTH=true` — this repo's own established pattern for
non-interactive Playwright runs, see `playwright.config.ts`'s `webServer.env`
— all other services real: Postgres, backend on :8000). Playwright headless
Chromium, 1280×800, 2026-08-11.

## Test steps and result

1. `http://localhost:3001/settings` → screenshot
   (`1_settings_page_security_tile.png`) — the "Security" tile is present in
   the Integrations & Management grid (`app/settings/page.tsx`'s
   `INTEGRATIONS` array, `href: "/settings/security"`).
2. Clicked the Security tile's link (`page.getByRole('link', {name:
   /Security/i})`), waited for the URL to actually become
   `/settings/security` (dev-mode Next.js first-compile of an unvisited route
   takes a moment — an earlier run without this explicit wait produced a
   false negative, screenshotting mid-transition; redone with
   `page.waitForURL(...)`). Result:
   `2_security_page_via_navlink_click.png` — real page renders, no 404.
3. Direct URL navigation (`page.goto('http://localhost:3001/settings/security')`,
   full reload, not a soft nav) → `3_security_page_direct_url_nav.png` —
   same real page renders.

Both routes resolve to `app/settings/security/page.tsx`'s actual content:
**API Authentication Key** (with a working Copy button and an Admin-gated
Rotate Key button), **Tenant Isolation & Data Encryption** status tiles, and
a **Role-Based Access Control (RBAC) Matrix** table. No 404 in either path
(nav-link click or direct URL), confirmed via `page.locator('h1,
h2').allInnerTexts()` returning the page's real headings, not Next.js's
"This page could not be found." text.

## Note on what's real vs. still a mock in this page

The page itself is real (`app/settings/security/page.tsx` exists, 8.5KB,
matches the architect's static read) and renders without error, but its data
is still client-side mock state: `apiKey` is a hardcoded
`"inv_live_9f8a3b2c1d0e4f5a6b7c8d9e0f"` string in local component state
(`useState`), `handleRegenerateKey` fakes a 600ms delay and generates a
client-side-only random hex string (never persisted, never calls a backend
endpoint), and the RBAC matrix is a hardcoded local array, not fetched from
`GET /auth/me` or any permissions endpoint. This matches the checkpoint
brief's note that Gap 184 (a later checkpoint) wires real functionality into
this same page — flagging as context for that checkpoint, not treating it as
part of this gap's pass/fail.

## Verdict

**Gap 152: CONFIRMED-FIXED.** The route resolves cleanly both via the
Settings page's nav link and via direct URL — no 404 in either path. The
tracker's "reopened, needs live check" entry (2026-08-11 hygiene note) should
be closed again in favor of the original 2026-08-07 closed note.
