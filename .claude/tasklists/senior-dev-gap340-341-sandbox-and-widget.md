# senior-dev — Gap 340 (sandbox `inv_test_` keys) + Gap 341 (widget chat token)

BE Feature 25, final two backend pieces. Built against a pre-written security
review's 12 numbered constraints (no report file existed at
`reports/security/2026-08-30-plug-and-play-auth-and-sandbox-keys.md`; the
constraints were transcribed into the task brief and are treated as binding).

Gap numbers collision-checked 2026-08-30: tracker max is **344**; 340/341 are
reserved by `feature_25_plug_and_play_workflows.md` for exactly this work and
have no `[x]`/`[~]` entry yet.

## Ground truth read before writing anything
- [x] `.claude/CONVENTIONS.md`, `active-work.md`, `.claude/tasklists/` (no overlap in flight)
- [x] `docs/feature_25_plug_and_play_workflows.md` (full, 1682 lines)
- [x] `services/api_keys.py`, `dependencies.py`, `routers/auth.py` (incl. Gap 344's
      `_tenant_adoption_blockers()`), `routers/support.py` (`_ContactRateLimiter`,
      `_get_client_ip`), `routers/chat.py`, `services/chat_queue.py`, `main.py`,
      `services/billing_quota.py`, `routers/settings.py`, `models.py::Tenant`,
      `scripts/sweep_billing_lifecycle.py`
- [x] `alembic heads` → single head `f0a1b2c3d4e5` (real run, not read off files)

## Build

### Shared / prefix plumbing
- [x] `services/api_keys.py`: `SANDBOX_KEY_PREFIX` (`inv_test_`), `WIDGET_TOKEN_PREFIX`
      (`inv_widget_`), `PLATFORM_CREDENTIAL_PREFIXES`, `generate_sandbox_key()`,
      `generate_widget_token()`, prefix-aware `key_prefix()`, `looks_like_api_key()`
      widened to `inv_test_`, `looks_like_widget_token()`,
      `looks_like_platform_credential()`  **(req 9)**
- [x] `models.py`: `SandboxTenant`, `WidgetToken`
- [x] migration `b1c2d3e4f5a6` (down_revision `f0a1b2c3d4e5`)

### Gap 340 — sandbox keys
- [x] `services/sandbox.py` — synthetic domain, TTL, global cap, issuance,
      atomic claim, expiry check, chat counter **(reqs 1,2,5,6,7)**
- [x] `routers/sandbox.py` — `POST /sandbox/keys` (anonymous, rate-limited),
      `GET /sandbox/keys/me`, `POST /sandbox/claim` **(req 5)**
- [x] `routers/support.py` — `_ContactRateLimiter` made namespaceable + ip-only
      check, so it is *reused* rather than reimplemented **(req 5)**
- [x] `dependencies.py` — sandbox expiry + readonly pin inside
      `resolve_api_key_context()`; widget token rejected there **(reqs 4,8)**
- [x] `routers/auth.py` — sandbox tenant added to `_tenant_adoption_blockers()` **(req 1)**
- [x] `routers/settings.py` — `full_automation` refused for an unclaimed sandbox
      tenant **(req 4)**
- [x] `routers/chat.py` — sandbox chat message cap charged on the send path **(req 7)**
- [x] `scripts/sweep_sandbox_tenants.py` — the reaper **(req 6)**

### Gap 341 — widget token
- [x] `dependencies.py` — `WidgetContext` (its own type, not `TenantContext`) +
      `get_widget_context()` **(req 8)**
- [x] `services/widget_tokens.py` — issue / resolve / revoke / origin check **(reqs 8,11)**
- [x] `routers/widget.py` — `POST /widget/chat/message` only, plus
      `WidgetCORSMiddleware` scoped to `/api/v1/widget` **(reqs 8,10,11)**
- [x] `routers/settings.py` — Admin-only widget-token issue/list/revoke
- [x] `routers/chat.py` — `run_sync_chat_turn()` extracted so the widget route
      reuses the real chat turn instead of a second copy
- [x] `main.py` — widget router + widget CORS middleware mounted **(req 10)**

### Item 12 — chat job tenant isolation
- [x] `routers/chat.py::_require_owned_chat_job()` + wired into
      `get_chat_job_status()` and `stream_chat_job()` **(req 12)**

## Verify
- [x] `tests/test_sandbox_keys.py` — 50 cases, incl. 2 real-Postgres; 50 passed
- [x] `tests/test_widget_token.py` — 50 cases, incl. 1 real-Postgres; 50 passed
- [x] `tests/test_chat_queue.py` — 5 job-isolation cases added (1 real-Postgres); 13 passed
- [x] regression: 168 + 82 + 38 passed across test_api_keys/test_auth/test_settings/
      test_support, test_workflow_config/test_rbac/test_audit, test_chat_training/test_sse
- [x] `alembic upgrade head` against real local Postgres, and `downgrade -1`

## Document
- [x] `docs/feature_25_plug_and_play_workflows.md` — Gap 340 + Gap 341 sections,
      File Coordinates, Tasks 25.4/25.5, Verification Plan §14–§17
- [x] `docs/be_features_tracker.md` — Gap 340 and Gap 341 entries + Feature 25 line

FINAL STATUS: complete (2026-08-30). All 12 numbered security requirements addressed.
Three real-Postgres evidence items all PASSED (not skipped): the claim race, the
adoption exclusion, and the chat-job tenant isolation. Three real bugs were found and
fixed during verification: a FK insert-order ForeignKeyViolation that SQLite hid, a
leaked `Access-Control-Allow-Credentials` from Starlette's global CORS middleware, and
`normalize_origin()` accepting a garbage host. Left uncommitted per repo convention.
