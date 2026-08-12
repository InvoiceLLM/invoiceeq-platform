# Gap 184 — Programmatic API tokens + Docs Hub (Checkpoint 14)

Scope: backend hashed API key storage + rotation + token auth dependency; FE wiring of
`/settings/security` (remove the `Math.random()` mock); Docs Hub tab loading the backend
OpenAPI/Swagger UI. Out of scope: new public API surface, rate limiting, any other gap.

- [x] 1. `models.py:39-56` — Tenant API key columns (hash, salt, indexed prefix, rotated_at, last_used_at)
- [x] 2. Alembic migration `c9d0e1f2a3b4_add_tenant_api_key_columns.py` on head `f9a0b1c2d3e4`
      (renamed out of an id collision with a concurrent checkpoint; multi-head branch flagged, not resolved)
- [x] 3. `services/api_keys.py` — generate / PBKDF2-HMAC-SHA256 hash w/ per-key salt / `compare_digest` verify
- [x] 4. `dependencies.py:739-858` — `resolve_api_key_context` + `get_api_key_context`
      (Authorization: Bearer <key> OR X-API-Key), parallel to Clerk path, nothing rewired
- [x] 5. `routers/settings.py:180-314` — GET api-key metadata, POST api-key/rotate (Admin), GET api-key/verify
- [x] 6. `main.py:58-64` + `routers/webhook_docs.py` — 7 webhook payload schemas in `app.webhooks` for /docs
- [x] 7. `tests/test_api_keys.py` — 22 tests: hashing, rotation revokes old key, raw key returned once only,
      both header variants, tenant isolation, 402/403 gates, OpenAPI webhooks section
- [x] 8. FE proxy routes: `/api/settings/security/api-key`, `.../rotate`, `/api/docs/openapi`, `/api/docs/ui`
      (+ `backendRootUrl()` in `lib/backendProxy.ts` for the un-prefixed FastAPI root paths)
- [x] 9. FE `app/settings/security/page.tsx` — real fetch, API Access / API Docs tabs, `Math.random()` mock deleted
- [x] 10. Verified: `pytest tests/test_api_keys.py` 22 passed; 5-suite regression 122 passed; `npx tsc --noEmit` exit 0
- [x] 11. Docs updated: be/fe trackers Gap 184 -> `[x]`, `feature_16_settings.md`, `feature_15_webhooks.md`,
      `feature_10_settings.md` (FE)

Status: COMPLETE. Left uncommitted per repo convention. Two things flagged in the final report:
(a) recommend a follow-up security review of the token hashing/rotation path;
(b) the three-way Alembic multi-head off `f9a0b1c2d3e4` needs an owner before any `upgrade head`.
