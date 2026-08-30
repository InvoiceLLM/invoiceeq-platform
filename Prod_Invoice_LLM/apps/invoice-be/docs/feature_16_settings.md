# Feature 16: Settings

**Implemented 2026-07-28.** First formal BE Settings feature. Consolidates by reference: [feature_9_connectors.md](feature_9_connectors.md), [feature_14_email_ingestion.md](feature_14_email_ingestion.md), [feature_15_webhooks.md](feature_15_webhooks.md), plus Service Flow toggles.

### File Coordinates
* Router: `routers/settings.py` — `GET`/`PUT /settings/vendor-flow`; `GET /settings/security/api-key`, `POST /settings/security/api-key/rotate`, `GET /settings/security/api-key/verify` → `get_api_key_status()`, `rotate_api_key()`, `verify_api_key_endpoint()`, `_api_key_status()`, models `ApiKeyStatus` / `ApiKeyRotateResponse` / `ApiKeyIdentity` (Gap 184)
* Model: `Tenant.receive_invoices_enabled`, `send_invoices_enabled`, `outbound_sender_email` (migration `e1f2a3b4c5d6`); `Tenant.api_key_hash`, `api_key_salt`, `api_key_prefix`, `api_key_rotated_at`, `api_key_last_used_at` (migration `c9d0e1f2a3b4`, Gap 184)
* API-key primitives: `services/api_keys.py` → `generate_api_key()`, `generate_salt()`, `hash_api_key()`, `verify_api_key()`, `key_prefix()`, `masked_display()`, `looks_like_api_key()` (Gap 184)
* Auth dependency: `dependencies.py` → `resolve_api_key_context()`, `get_api_key_context()`, `API_KEY_USER_ID` (Gap 184)
* Tests: `tests/test_settings.py`, `tests/test_api_keys.py` (Gap 184)

### Functionality

**Toggles:** `receive_invoices_enabled` (default `True`), `send_invoices_enabled` (default `False`).

**Email setup (redesigned 2026-08-10):** authorized inbound/outbound emails live on `TenantEmailSender.email_set`, not on a single Settings string. See Feature 14 / FE Feature 8.

**`outbound_sender_email`:** legacy nullable column kept for Gap 125 customer-delivery Reply-To experiments; **not** required to enable Send Invoices and **not** edited on the Email Setup screen.

**Validation on `PUT /settings/vendor-flow`** (updated 2026-08-10):
1. Rejects `send_invoices_enabled=True` if the tenant has **zero** `TenantEmailSender` rows with `email_set='outbound'` (`400`).
2. Rejects `send_invoices_enabled=True` if `billing_plan != 'pro_combined'` (`402`).
3. Turning send off does not clear email-set rows or downgrade the plan.

**Admin-only:** `PUT` requires `role == Admin`; `GET` any authenticated role.

**What toggles gate:** Ingestion Send tab, Dashboard split, Auditor outbound tab — unchanged. Chat degrades naturally with no outbound data.

**Programmatic API key (Gap 184, built 2026-08-12):** one key per tenant, stored as a PBKDF2-HMAC-SHA256 digest over a fresh per-issuance 16-byte salt — the raw key is never persisted and is not recoverable from the database. `GET /settings/security/api-key` returns metadata only (`has_key`, `key_prefix`, `masked_key`, `rotated_at`, `last_used_at`, `can_rotate`) and is readable by any authenticated role; `POST /settings/security/api-key/rotate` is **Admin-only** (`403` otherwise) and both issues the first key and rotates a later one through the same write — overwriting hash+salt+prefix in one commit is what revokes the previous key, since nothing remains to verify its digest against. The raw key is in exactly one response in the whole API, the rotate one (same "shown once" rule as `WebhookSubscription.secret`); the rotation log line records the prefix only.

`get_api_key_context()` in `dependencies.py` is a **parallel** auth path to the Clerk session dependency, not a replacement — no existing endpoint was rewired onto it. It accepts `X-API-Key: <key>` or `Authorization: Bearer <key>` (X-API-Key wins if both are sent; the `inv_live_` prefix is what tells a key apart from a Clerk JWT in the shared header), finds the candidate row by indexed `api_key_prefix`, then compares digests with `hmac.compare_digest`. Unknown prefix, wrong key, and "tenant never issued a key" all return the same `401` with the same message, so the response cannot be used to enumerate which tenants hold keys. It runs the same `enforce_lapse`/`refresh_free_quota`/`402` billing gate as the session path, and resolves as role `Viewer` with no `can_train`/`can_audit`/`can_load`: holding a key proves a request comes from the tenant's own system, not that an Admin approved a specific action, so `require_admin`/`require_can_*` routes stay unreachable by key alone. There is no mock-auth fallback on this path. `GET /settings/security/api-key/verify` is authenticated by the key itself and returns identity only (tenant id/name, role, plan), never tenant data — it exists so an integrator can confirm a key works, and it is the route that exercises this path end to end in tests.

> **Additive note (2026-08-29, BE Gap 335 / Feature 25 Phase 0 — the Gap 184 design above is unchanged and not rewritten):** the key-auth path this feature built is now *extended* by [feature_25_plug_and_play_workflows.md](feature_25_plug_and_play_workflows.md), which adds a `Tenant.api_key_scope` column (`readonly` default / `actions`) and a dual-credential `get_tenant_or_api_key_context()` dependency so a key can reach real endpoints — read that document, not this paragraph, for what key-auth may do today.
>
> **Additive note (2026-08-29, BE Gap 336 / Feature 25 Task 25.2):** `routers/settings.py` now also
> serves `GET`/`PUT /api/v1/settings/workflow` (Admin-only on both verbs), backed by the new
> `TenantWorkflowConfig` model. Its `audit_policy` field is the supported way to set
> `Tenant.api_key_scope` — the PUT writes both in one commit and the GET derives the policy back
> from the tenant column. Same document as above for the design; this feature's own body is
> unchanged.

### Tasks
- [x] **Task 16.1–16.2:** Columns + vendor-flow endpoints (2026-07-28).
- [x] **Task 16.3 (2026-08-10):** Gate Send Invoices on outbound authorized-email set instead of `outbound_sender_email`.
- [x] **Task 16.4 (Gap 184, 2026-08-12):** Hashed per-tenant API key storage + rotation endpoint + `X-API-Key`/Bearer auth dependency + key-authenticated verify route. Verified: `pytest tests/test_api_keys.py` → **22 passed**; those plus `test_settings.py` / `test_auth.py` / `test_webhooks.py` / `test_rbac.py` re-run together as regression against the changed `dependencies.py`/`settings.py`/`main.py` → **122 passed**.

### Verification Plan
* Admin enabling send with empty outbound set → `400`.
* Admin with ≥1 outbound-set email + `pro_combined` → enable succeeds.
* **API key (Gap 184):** rotate as Admin → `200` with a raw `api_key`; the same key authenticates `GET /settings/security/api-key/verify` via both header spellings; rotate again → the first key `401`s and the second succeeds; the raw key never appears in any subsequent response; non-Admin rotate → `403` and `can_rotate: false`; a key for one tenant never resolves to another; an `unpaid` tenant's key → `402`.
