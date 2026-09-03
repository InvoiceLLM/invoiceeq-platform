# Feature 1.1: Granular Role-Based Access Control

> **Additive note — 2026-09-02, BE Gap 405.** A 4th permission, `can_send_invoices`,
> was added following exactly this feature's existing shape (own column, own
> `RoleMapper` default per role, own `require_can_send_invoices` dependency, own
> Admin-console checkbox) — nothing about `can_train`/`can_audit`/`can_load` changed.
> It layers on top of (does not replace) `Tenant.send_invoices_enabled`'s tenant-wide
> plan/email gate (`feature_16_settings.md`) — both must be true for a user to see/use
> Send Invoices. Also gates `POST /outbound-invoices/upload` alongside the existing
> `can_load` check (two separate `Depends`, not a combined one, matching this file's
> existing one-permission-per-dependency convention). Details in this feature's own
> "Known follow-ups" section below, which is where this was originally flagged.

> **Additive note — 2026-08-29, BE Gap 337 (Feature 25).** The role *vocabulary*
> described below changed; the permission model did not. The user-facing roles are
> now **Admin, Auditor, Trainer** — "Viewer" is retired as a name. Trainer already
> existed with exactly the permissions it keeps (`can_train` only), so this was a
> retirement, not a rename.
>
> The one thing to know before reading anything below: **"Viewer" was doing two
> unrelated jobs** — an assignable role *and* the system's zero-permission
> fallback (unmapped IDP role strings, a missing role, Gap 173's org-mismatch
> escalation clamp, and Gap 335's API-key requests all resolved to it). Job two
> still exists and now has its own never-assignable name,
> `RoleMapper.NO_ROLE == "Restricted"`, deliberately kept **out** of
> `RoleMapper.USER_FACING_ROLES` so the fallback slot can never inherit a real
> role's permissions. Every statement below about a permission-less user still
> holds exactly; only the label changed. Data migration `e9f0a1b2c3d4` rewrites
> existing `users.role = 'Viewer'` rows. Details:
> [feature_25_plug_and_play_workflows.md](feature_25_plug_and_play_workflows.md).

Extends Feature 1 (`feature_1_auth.md`), which named the target role set — Admin, Auditor, Loader, Trainer, Viewer — from the start but never implemented enforcement beyond a handful of ad-hoc `role == "Admin"` checks (`settings.py`, `billing.py`) and a fully mocked FE `useAuth()` hook (`fe_features_tracker.md` Gap 99). This feature closes that gap: real, per-user, per-area permissions instead of "Admin or not."

### Access Model

| Area | Access |
|---|---|
| Dashboard | All signed-in users |
| Chat | All signed-in users |
| Help | All signed-in users |
| Settings | Admin only |
| Admin console (`/admin`) | Admin only |
| Trainer | Granted individually, default **off** |
| Auditor (Audit Queue / review console) | Granted individually, default **off** |
| Loader (Ingestion) | Granted individually, default **off** |

**Default for a newly created user: nothing beyond the 3 universal screens.** Least-privilege by design — Trainer rules affect every future extraction for a vendor, and Auditor actions (Mark Paid, Reject, corrections) are real financial actions; a new user shouldn't have either until an Admin decides they need it. This also means the original design's "Viewer" role needs no separate flag — a user with all three permissions off *is* a Viewer (Dashboard + Chat + Help only).

Admin is a role, not a 4th permission — Admins implicitly have all three and are the only ones who can grant/revoke them for others, via the existing Admin console (`app/admin/page.tsx`, already built under Gap 10's auth-check fix).

### File Coordinates
* Schema: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py) → `User.can_train` / `User.can_audit` / `User.can_load` (bool, non-null, default `False`). Migration `f6a7b8c9d0e1_add_rbac_permissions_to_users.py` (parent `e5f6a7b8c9d0`, taken from a real `alembic heads` run).
* Dependency: [apps/invoice-be/dependencies.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/dependencies.py) → `TenantContext` carries the same 3 booleans; `resolve_permissions(role, user)` derives them from the `User` row (not the JWT — permissions are our own data, not Clerk's) with `role == "Admin"` implying all three; `require_permission(name)` factory plus the `require_can_train` / `require_can_audit` / `require_can_load` / `require_admin` dependencies it produces.
* Enforcement: `routers/trainer.py` (router-level `require_can_train`), `routers/audit.py` + `routers/outbound_audit.py` (router-level `require_can_audit`), `routers/invoices.py::upload_invoices` and `::start_directory_watcher`, `routers/outbound_invoices.py::upload_outbound_invoice` (per-endpoint `require_can_load`).
* Admin API: [apps/invoice-be/routers/admin.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/admin.py) → `list_tenant_users` (`GET /api/v1/admin/users`), `set_user_permissions` (`PUT /api/v1/admin/users/{user_ref}/permissions`), schemas `AdminUserOut` / `PermissionsUpdate`. Mounted in `main.py`.
* FE token wiring: `apps/invoice-fe/lib/backendProxy.ts` → `forwardedHeaders()` (now async; mints a bearer token from the Clerk session when no inbound header is present) and `clerkSessionToken()`.
* FE identity source: `apps/invoice-fe/app/api/auth/me/route.ts` (proxies the **unprefixed** backend `GET /auth/me`) and `apps/invoice-fe/hooks/useAuth.ts` → `useAuth()` / `refreshAuth()` — no `localStorage` reads remain.
* FE nav filtering: `apps/invoice-fe/components/layout/Sidebar.tsx` → `Sidebar()`'s `menuItems[].visible` / `visibleItems`.
* Admin UI: [apps/invoice-fe/app/admin/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/admin/page.tsx) → `AdminDashboardPage()` (`loadUsers`, `handleTogglePermission`), `CreateUserModal()`, module helpers `PERMISSIONS` / `savePermissions`. Proxy routes `app/api/admin/users/route.ts` and `app/api/admin/users/[userRef]/permissions/route.ts`. Spec document: [feature_16_admin_console.md](../../invoice-fe/docs/feature_16_admin_console.md).

### Tasks
- [x] **Task 1.1.1: Schema** — `can_train`/`can_audit`/`can_load` on `User`, non-null, default `False`. Migration `f6a7b8c9d0e1` branches off the verified single head `e5f6a7b8c9d0` and backfills existing rows to `False` via `server_default=sa.false()`. Admins are deliberately **not** backfilled to `True`: Admin implies all three at context-resolution time, so storing it would duplicate the rule and strand stale flags on anyone later demoted from Admin. Verified up and down against a scratch SQLite DB (columns added, then removed); the full `alembic upgrade head` chain still requires PostgreSQL because an *earlier* migration (`71d18e2c3349`) uses `drop_constraint`, which SQLite can't do — pre-existing, unrelated to this feature.
- [x] **Task 1.1.2: Backend enforcement** — `require_permission(name)` builds a dependency that 403s with a human-readable reason, mirroring the existing inline `context.role != "Admin"` checks in `settings.py`/`billing.py` but attachable once per router. Applied at **router level** for `trainer.py`, `audit.py` and `outbound_audit.py` (their whole surface is uniformly permissioned — there is no read-only subset a non-Trainer/non-Auditor should reach), and **per-endpoint** for `invoices.py` (`/upload`, `/watcher/start`) and `outbound_invoices.py` (`/upload`) so the `GET` list/detail/pdf routes stay open and the Dashboard remains reachable for a permission-less user. Settings/billing stay on their existing `role == "Admin"` checks, unchanged. `email_ingestion.py`'s SendGrid webhook and `webhooks.py`'s HMAC-signed deliveries are deliberately **not** gated — machine-to-machine, gating them would break Features 14/15.
- [x] **Task 1.1.3: `TenantContext` carries permissions** — `resolve_permissions()` returns `(True, True, True)` for Admin and otherwise reads the `User` row. `GET /auth/me` returns `TenantContext` verbatim, so the 3 booleans fall out with no change to `routers/auth.py` (confirmed). The mock-auth path resolves to `role == "Admin"`, so the suite-wide `ALLOW_MOCK_AUTH=true` in `tests/conftest.py` keeps all ~130 header-less `TestClient` calls passing rather than 403ing.
- [x] **Task 1.1.4: FE — real `useAuth()`** — rewritten to fetch `GET /api/auth/me`; every `localStorage` read deleted. Exposes `{ tenantId, userId, role, canTrain, canAudit, canLoad, billingPlan, loading }` plus a `refreshAuth()` escape hatch. Deduping is done with a module-level cache + shared in-flight promise + subscriber set rather than a React context provider, because `app/layout.tsx` is a server component and adding a provider there would have meant a new client wrapper around the whole tree for no behavioural gain. On any failure (network, 401, 402) it resolves to a least-privilege anonymous identity — never to a full menu.
  - **Gap 138 (2026-08-11):** cache no longer lives for the whole tab without refresh — debounced focus/visibility re-fetch, `clearAuth()` on sign-out, and call-site `refreshAuth()` after billing success / self permission saves / Trainer upgrade gate. See `fe_features_tracker.md` Gap 138.
  - Unblocked by the Clerk-list Gap 4 B1 work that landed in the same change: `lib/backendProxy.ts::forwardedHeaders()` is now async and mints a bearer token from the Clerk session (`auth()` → `getToken()`) when no inbound `Authorization` header is present, preferring an inbound header when there is one so `Bearer test_*` tooling keeps working. Server-side minting was chosen over a client-side axios interceptor because 37 of 39 `app/api/**` handlers already funnel through this module, whereas an interceptor on `lib/apiClient.ts` would have missed the 11 components calling `fetch("/api/...")` directly. `app/api/auth/me/route.ts` hand-rolls its fetch because the backend's auth router is mounted **unprefixed** and `proxyJson()` unconditionally appends `/api/v1` — same reason `app/api/auth/logout/route.ts` does.
- [x] **Task 1.1.5: FE — `Sidebar.tsx` filtering** — each nav item carries a `visible` predicate: Dashboard/Chat/Help always; Ingest → `canLoad`; Audit Queue → `canAudit`; AI Trainer → `canTrain`; Settings → `role === "Admin"`. While identity is in flight only the 3 universal items render, so nothing a user isn't allowed to see is ever flashed. `/admin` was not added to the sidebar (it never was there). Two small riders in the same file: the footer's hardcoded all-zeroes "Tenant Isolation ID" now shows the real `tenantId` (it was the same fabricated identity this feature exists to remove), and the `<aside>` carries `data-auth-loading` so e2e specs can distinguish "still loading" from "permission-less" instead of racing the fetch.
- [x] **Task 1.1.6: Admin console UI** — 3 checkboxes (Trainer/Auditor/Loader) in `CreateUserModal` and per-row in the users table, each PUT-ing immediately with optimistic update and rollback on failure. Backed by a **new** `routers/admin.py` rather than an extension of an existing router: `settings.py` is tenant *configuration* and `auth.py` is deliberately unprefixed, so neither is a natural home for tenant-user administration, and a dedicated `/api/v1/admin` prefix keeps the Admin gate uniform at router level. Every endpoint is `require_admin` **and** scoped to the caller's own tenant (cross-tenant refs 404 rather than leaking existence). See [feature_16_admin_console.md](../../invoice-fe/docs/feature_16_admin_console.md) for frontend spec.
  - Two additions beyond the original one-endpoint sketch, both needed to make the task functional: (a) `GET /api/v1/admin/users` — the Admin page's user list was ephemeral client state that vanished on reload, so edit-time checkboxes had nothing real to edit; (b) `PUT .../{user_ref}/permissions` accepts a **Clerk user ID** as well as a backend UUID and pre-provisions a `users` row (role `Viewer`) when given a Clerk ID plus an email. Without that, permissions ticked at create time would be silently dropped, because `get_tenant_context()` only writes a `users` row on the user's *first API call* — which happens long after the Admin finishes the create flow.

### Verification Plan
* **Automated Tests**: a non-permissioned user hitting Trainer/Audit/Ingestion-upload endpoints directly gets a real `403`; an Admin can grant/revoke and the effect is immediate on the next request; Dashboard/Chat/Help remain reachable regardless of permission state.
  * **Result (2026-08-02)**: `invoice-be/tests/test_rbac.py` — 24 cases, all passing, covering all three claims plus the Admin endpoints (Admin-only, by-UUID, by-Clerk-ID, pre-provisioning, 404 unknown, cross-tenant 404). Full backend suite: **184 passed, 1 failed, 5 deselected** (baseline before this change: 160 passed, 1 failed, 5 deselected). The single failure is `tests/test_connectors.py::test_salesforce_pkce_flow`, which needs a local Redis on :6379 — pre-existing and environmental, identical before and after.
  * `invoice-fe/e2e/rbac-sidebar.spec.ts` — 9 cases asserting the rendered nav set against a stubbed identity per role. Full e2e suite: **31 passed** (baseline 22). `tsc --noEmit` clean; `next build` compiles and generates all 23 pages.
* **Manual Verification**: create a user with no permissions granted, confirm the FE only shows Dashboard/Chat/Help; grant Trainer via the Admin console, confirm it appears without requiring a fresh login; confirm Settings/Admin console stay invisible/blocked for a non-Admin regardless of granted permissions.
  * **Not performed.** Real Clerk sign-in is blocked on a human Cloudflare Turnstile click-through (`website_features_tracker.md` Gap 9), so the end-to-end path *browser → Clerk session → minted bearer token → backend* has never been exercised against a live Clerk instance. The e2e specs stub `GET /api/auth/me`, which proves the FE consumes the contract correctly but not that Clerk issues a token the backend accepts.

### Known follow-ups (not in this feature)
* **Gap 405, filed 2026-09-02, built same day**: a 4th permission, `can_send_invoices`, was added — see the additive note at the top of this document and `be_features_tracker.md` Gap 405 for the full build record.
* **Route protection — fixed 2026-09-03 by Gap 431, at the render layer, not middleware.** `invoice-fe/middleware.ts` still remains bare `clerkMiddleware()` with no `.protect()` calls — that part of this bullet is unchanged, and enabling it is still a separate decision with its own blast radius (`/flows` must stay a public no-login demo, see FE Gap 62's `STANDALONE_ROUTES`). What changed: a permission-less user who types `/trainer` no longer loads the page shell and watches its API calls 403 — `components/layout/RouteGuard.tsx`, wrapped once in `Shell.tsx` and driven by a route→permission map (`lib/routePermissions.ts`) shared with `Sidebar.tsx`, now renders a full-page "Access restricted" screen instead. **Not a security boundary** — the backend's `require_can_*`/`require_admin` gates remain the only actual enforcement; this closes the product-behaviour gap this bullet originally described. Full build record: `be_features_tracker.md` Gap 431.
* **`ALLOW_MOCK_AUTH` has not been flipped anywhere.** Nothing in `.env`, `config.py`, `infra/params.*.json` or any bicep was touched. Turning enforcement on in a deployed environment is a deployment decision.
* **`outbound_invoices.py`'s `confirm-send` / `mark-paid` are ungated** — outbound lifecycle transitions rather than ingestion, so they fall outside `can_load`; whether they belong under `can_audit` is an open question.
