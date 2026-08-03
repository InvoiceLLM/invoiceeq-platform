# Feature 1: Multi-Tenant Authentication & Security Scoping

Ensure secure, isolated access for multiple tenant organizations and support user roles (Admin, Auditor, Loader, Trainer, Viewer).

### File Coordinates
* Router: [apps/invoice-be/routers/auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/auth.py) → `GET /auth/me` → `get_current_user_context()`
* Dependency Injection: [apps/invoice-be/dependencies.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/dependencies.py) → `get_tenant_context()`, `get_db_session()`, `TenantContext` schema

### Functionality
Every tenant-scoped router depends on `dependencies.py::get_tenant_context()` to decode the bearer JWT (Clerk/Auth0 JWKS) into a `TenantContext{tenant_id, user_id, role, billing_plan, can_train, can_audit, can_load}`, and blocks with `402` if `billing_plan == 'unpaid'`. **Local/test fallback** *(gated since Clerk-list Gap 4 — see below)*: a missing/invalid header, or one starting `Bearer test_`, yields a mock context (`tenant_id: 00000000-...`, `role: Admin`, `billing_plan: active`) instead of failing.

> **Feature 1.1 update (2026-08-02):** the role set this feature named from the
> start (Admin, Auditor, Loader, Trainer, Viewer) is now actually enforced — see
> [feature_1.1_rbac.md](feature_1.1_rbac.md). `TenantContext` carries
> `can_train`/`can_audit`/`can_load`, resolved by `dependencies.py::resolve_permissions()`
> **from the `User` row rather than from the JWT** (permissions are our own data, so
> an Admin's grant applies on the caller's very next request without a token
> refresh); `role == "Admin"` implies all three, which is what keeps the mock/test
> context — and therefore the whole existing pytest suite — passing unchanged. A
> user with all three `False` *is* the design's "Viewer", so no separate Viewer
> flag was needed. Enforcement is via `require_permission()`-built dependencies on
> the Trainer, Audit and ingestion-upload routers.
>
> The same change closed **Clerk-list Gap 4's B1 blocker**: `invoice-fe` now sends
> a real `Authorization` header. `lib/backendProxy.ts::forwardedHeaders()` mints a
> bearer token server-side from the Clerk session when no inbound header is
> present, so `ALLOW_MOCK_AUTH` is no longer structurally required in a deployed
> environment. It has **not** been flipped anywhere — that remains a deployment
> decision — and route-level protection (`middleware.ts` `.protect()`) is still
> absent, so nav hiding hides links, not routes.
>
> Correspondingly, `Sidebar.tsx` no longer hardcodes the all-zero tenant UUID; it
> renders the real `tenant_id` from `GET /auth/me`, and `hooks/useAuth.ts` no
> longer reads `localStorage` at all.

> **Gap 4 update (2026-07-29):** that fallback is no longer unconditional. It now
> requires `ALLOW_MOCK_AUTH=true`, which defaults to `false`, so a deployed
> backend returns `401` instead of a mock Admin context. Set `ALLOW_MOCK_AUTH=true`
> in `apps/invoice-be/.env` to keep the zero-config local workflow described here;
> the pytest suite enables it itself via `tests/conftest.py`. Incomplete Clerk JWT
> config (`CLERK_JWKS_URL` / `CLERK_JWT_ISSUER` unset) now fails closed with a
> `500` rather than skipping issuer validation. Full detail, including why
> enforcement cannot yet be switched on in Azure, is in
> [GAP_4_AUTH_ENFORCEMENT.md](GAP_4_AUTH_ENFORCEMENT.md). `get_current_user_context()` in `routers/auth.py` just echoes that resolved context back for the FE's `/auth/me` call. `get_db_session()` yields a scoped SQLModel `Session`; every router is expected to filter its own queries by `context.tenant_id` — there is no query-level enforcement, it's a per-router convention. See "Detailed Implementation Plan" below for the full walkthrough.

### Tasks
- [x] **Task 1.1: Setup Auth JWT Decoding**
  - Verify and decode JWT tokens from the Authorization header using PyJWT or python-jose.
  - Pull JWKS (JSON Web Key Sets) dynamically from Clerk/Auth0 domains specified in settings.
- [x] **Task 1.2: Implement `get_tenant_context()` Dependency**
  - Extract `tenant_id`, `user_id`, `role`, and `billing_plan` from the decoded JWT.
  - Return a structured schema representing the current request's tenant/user context.
  - Raise `401 Unauthorized` if the token is invalid, and `403 Forbidden` if permissions do not match.
  - *Gap 4 (2026-07-29): the mock fallback below is now gated behind `ALLOW_MOCK_AUTH` (default `false`), so a missing/invalid header raises `401` in deployed environments rather than returning a mock Admin context.*
- [x] **Task 1.3: Enforce Tenant-Isolated Database Queries**
  - Create a FastAPI dependency `get_db_session()` in `dependencies.py` that yields a session.
  - Ensure all database queries in backend routers automatically filter by `tenant_id` context parameter.
- [x] **Task 1.4: Block Unpaid Subscription Accounts**
  - Inside `get_tenant_context()`, check the tenant's plan status. If it is `'unpaid'`, raise a `402 Payment Required` exception to block all app interactions until payment is updated.
- [ ] **Task 1.5: Persist Users to the `users` Table**
  - Add the `User` SQLModel (see `Database_Schema_Document.md`) and provision a row on first SSO login via domain-based tenant matching.
  - Switch `AuditLog.actor_user_id` to a real foreign key into `users(id)` instead of a raw JWT claim string.
  - Retire the ad-hoc tenant auto-creation fallback in `routers/invoices.py` once this flow owns tenant/user provisioning.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_auth.py` verifying that JWTs from different tenants return status-isolated responses, and `'unpaid'` users are blocked.
* **Manual Verification**: Use Postman/cURL with invalid, expired, and correct tenant JWTs to verify HTTP return codes.

### Detailed Implementation Plan

#### 1. Dependencies Setup
- Add `pyjwt` dependency in [pyproject.toml](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/pyproject.toml).
- Install using `uv` (once approved).

#### 2. Database Integration (`database.py`)
- Define the SQLAlchemy/SQLModel database engine (`engine`) and a session creation helper (`get_session`).
- Location: [apps/invoice-be/database.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/database.py).

#### 3. Authentication & Scope Dependency Injection (`dependencies.py`)
- Define a `TenantContext` Pydantic model with fields: `tenant_id` (UUID), `user_id` (str), `role` (str), and `billing_plan` (str).
- Implement FastAPI dependency `get_tenant_context()`:
  - Try to retrieve the Authorization header bearer token.
  - Decode and verify the JWT (using Clerk certificate keys if available).
  - **Local Development / Test Fallback** *(requires `ALLOW_MOCK_AUTH=true` since Gap 4; default is `false`)*: If the header is missing, is invalid, or begins with `Bearer test_`, yield a mock test context (e.g., `tenant_id: 00000000-0000-0000-0000-000000000000`, `user_id: user_test_default`, `role: Admin`, `billing_plan: active`). With the flag disabled, all three cases raise `401` instead.
  - Block with HTTP `402 Payment Required` if the `billing_plan` is `'unpaid'`.
- Implement `get_db_session()` dependency yielding a session.

#### 4. Auth Router Setup (`auth.py`)
- Implement a router containing `/auth/me` to return the current `TenantContext`.
- Location: [apps/invoice-be/routers/auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/auth.py).

#### 5. Main App Setup (`main.py`)
- Include the new `/auth` router in the FastAPI instance.

#### 6. Unit Testing (`test_auth.py`)
- Implement a pytest client test file [apps/invoice-be/tests/test_auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/test_auth.py).
- Verify mock login, tenant isolation, role validation, and unpaid plan blocking.

