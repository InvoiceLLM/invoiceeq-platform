# Checkpoint 1 — Gaps 131/179 (OAuth redirect_uri_mismatch), 152 (Settings/Security 404), 180 (Chat find-thread) — live dev verification

Note: this file was written after execution completed rather than before, which
is a deviation from CONVENTIONS.md's "create before starting work" rule — noted
for the record, not repeating on future checkpoints.

- [x] Read CONVENTIONS.md, both trackers (be/fe), relevant code (08-apps.bicep, routers/connectors.py, app/settings/security/page.tsx, app/settings/page.tsx, ChatWindow.tsx, useChatSession.ts, backendProxy.ts, Gap 177 tracker entry)
- [x] Start Docker Desktop + `docker compose up -d` (Postgres/Redis/Chroma/Azurite)
- [x] Run `alembic upgrade head` against fresh dev Postgres (schema was empty)
- [x] Start real backend (`uvicorn`, :8000), queue worker, `invoice-website` (:3000), `invoice-fe` (:3001)
- [x] Gap 131/179: `GET /connectors/auth-url/{google_drive,salesforce}` via mock-auth backend call, capture real redirect_uri sent
- [x] Gap 131/179: Playwright headless nav directly to both real authorize URLs, screenshot — confirm no redirect_uri_mismatch on either provider
- [x] Gap 131/179: found + documented separate local-dev-only issue (FRONTEND_URL defaults to :3000/website, whose FE-proxy rewrite is inert locally — 404 on post-token bounce) — flagged, not fixed, not conflated with the mismatch verdict
- [x] Gap 152: restart invoice-fe with `DISABLE_CLERK_AUTH=true` (this repo's own established Playwright bypass pattern) to drive real UI without live Clerk login
- [x] Gap 152: Playwright — click Security tile from /settings, and direct URL nav to /settings/security — both screenshotted, confirmed no 404
- [x] Gap 180: Playwright — create 3 real chat threads, rename, run 6 search-query variations against the real filter, screenshot results
- [x] Gap 180: delete a thread via real DELETE call, capture the 500 + FE log stack trace, confirm ghost-thread persists in sidebar/search, confirm via direct Postgres query that backend row was actually deleted, confirm reload clears it
- [x] File evidence: `invoice-be/docs/test_evidence/gap131_179_oauth_dev_verification/`, `invoice-fe/docs/test_evidence/gap152_settings_security/`, `invoice-fe/docs/test_evidence/gap180_chat_find_thread/`
- [x] Update `invoice-be/docs/test_coverage_map.md` and `invoice-fe/docs/test_coverage_map.md`
- [x] Clean up: remove temp Playwright scripts, stop dev servers, `docker compose down`

**Final status:** All three gaps verified live against a real dev stack. Gap 131/179 CONFIRMED-FIXED (redirect_uri correct, no mismatch on either provider). Gap 152 CONFIRMED-FIXED (route resolves, no 404). Gap 180 CONFIRMED as a Gap 177 symptom, not an independent search-filter bug. No code changed.
