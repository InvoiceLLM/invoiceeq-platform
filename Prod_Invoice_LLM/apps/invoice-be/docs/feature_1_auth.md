# Feature 1: Multi-Tenant Authentication & Security Scoping

Ensure secure, isolated access for multiple tenant organizations and support user roles (Admin, Auditor, Loader, Trainer, Viewer).

### File Coordinates
* Router: [apps/invoice-be/routers/auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/auth.py) → `GET /auth/me` → `get_current_user_context()`; `POST /auth/provision` → `provision_tenant()` + `_create_tenant_with_unique_domain()` + `_tenant_adoption_blockers()` / `_TENANT_SCOPED_TABLES`; `POST /auth/logout` → `logout()`
* Dependency Injection: [apps/invoice-be/dependencies.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/dependencies.py) → `get_tenant_context()`, `get_tenant_context_allow_unpaid()`, `get_authenticated_clerk_identity()` + `AuthenticatedClerkIdentity` (was `get_authenticated_clerk_user_id()` until Gap 133 Checkpoint 3c), `verify_clerk_jwt()`, `require_clerk_jwt_config()`, `resolve_permissions()`, `reconcile_role_with_org()`, `get_db_session()`, `TenantContext` schema
* Sign-up caller (website): [apps/invoice-website/app/signup/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-website/app/signup/page.tsx) → `handleSignup()`, `provisionTenant()`, `handleRetryProvision()` via [app/api/auth/provision/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-website/app/api/auth/provision/route.ts)

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

> **Gap 133 update (2026-08-11) — tenant identity is provisioned once, explicitly, and never inferred at request time.**
>
> `get_tenant_context_allow_unpaid()` used to resolve a tenant for a *new* user
> through a three-step chain: `clerk_org_id` → `tenant_id` claim → **email domain**,
> and if all three missed it created a tenant on the spot. The third step was an
> identity decision made from data that is frequently not real: when Clerk's JWT
> Template omits the `email` claim, the fallback address is literally
> `user_<clerkid>@domain.com`, so every such user shares the domain `domain.com`
> and they were all merged into one unrelated "Domain Workspace" tenant.
> **Priority 3 and the request-time tenant creation are both gone for real
> tokens.** When neither `clerk_org_id` nor a `tenant_id` claim resolves an
> existing tenant, the request is refused with **`409 Conflict`** naming the org
> id, rather than silently placing the user somewhere. The mock/test identities
> (`ALLOW_MOCK_AUTH`, default off) keep the old auto-provision behaviour, which is
> what the pytest suite runs on; the gate is tracked by the local
> `is_mock_identity` flag. `email_is_placeholder` is now computed at the claim
> source and reported, with `email_present=`, on the `[jwt-diag]` stdout line —
> diagnostic only, no longer a gating input.
>
> **`POST /auth/provision` is authenticated.** It previously took no auth
> dependency at all: an anonymous caller could post any `clerk_org_id`/`org_name`
> and rename or claim an existing tenant (reproduced over HTTP, see the tracker's
> Gap 133 entry). `get_authenticated_clerk_user_id()` verifies a real Clerk token
> through `verify_clerk_jwt()` — the decode/verify body extracted verbatim out of
> `get_tenant_context_allow_unpaid()`, so both paths pin the issuer and fail
> closed identically — and the handler rejects with `403` unless the token's `sub`
> equals `clerk_user_id` in the body. The website mints that token client-side
> right after `setActive` and forwards it through its proxy route.
>
> Two more defects in the same handler: a duplicate `Tenant.domain` (the second
> organisation to sign up from any shared email domain) raised `IntegrityError`
> as a bare `500`; `_create_tenant_with_unique_domain()` now rolls back and
> retries once with `org-<clerk_org_id>.invalid`, returning an explicit `409`
> only if that also conflicts. And the pre-Clerk-Organizations domain-adoption
> branch checked only for a missing `clerk_org_id`, so a domain-matched tenant
> **with real users and invoices** could be renamed and claimed by an unrelated
> org; adoption now additionally requires the tenant to have no users at all.
>
> `TenantContext` gained `tenant_name`, populated from the Tenant row the request
> has already loaded. It exists so the FE can display the tenant the backend
> actually resolved instead of Clerk's `unsafeMetadata.orgName`, which is written
> once at sign-up and never reconciled — the two silently diverging is what made
> this class of failure invisible in the UI.
>
> **Not done here (deliberately):** no backfill or migration of users/tenants
> already mis-assigned by the old fallback, and no Clerk Dashboard JWT Template
> change. Both are separate, out-of-scope work.

> **Gap 133 update (2026-08-12, Checkpoint 3c) — the caller is bound to what they may claim, and a role claim is only usable for the org it came from.**
>
> Checkpoint 3b authenticated *who* was calling `POST /auth/provision`. It never
> checked *what* they were entitled to claim: `clerk_org_id` and `admin_email`
> were still whatever the request body said. Five residual holes, all reproduced
> over real HTTP before and after fixing (RS256-signed tokens against a local
> JWKS, `ALLOW_MOCK_AUTH=false`, throwaway SQLite):
>
> 1. **`clerk_org_id` is bound to the token's own `org_id` claim** — a mismatch
>    is `403`. Any signed-in user could previously POST an org id they had
>    nothing to do with and claim it as their tenant. This also closes the
>    cross-tenant read that the *idempotent early return* provided: posting an
>    org id that already existed echoed back that tenant's UUID, name, billing
>    plan and remaining free quota (confirmed live: `Victim Holdings`,
>    `pro_combined`, quota `13`, all returned to an unrelated caller). The claim
>    is satisfiable in the real flow because `signup/page.tsx` calls
>    `setActive` for the new org before minting the `invoice-app` token —
>    **which makes an `org_id` claim on that template a hard deployment
>    dependency: without it every provision now `403`s.**
> 2. **`TenantContext.role` is reconciled against the resolved tenant** via the
>    new `reconcile_role_with_org()`. Gap 173 already computed `org_matches`,
>    but used it only to gate *persisting* `user.role` — the role used for the
>    request still came off the token, so the escalation it was written to stop
>    worked anyway: a Viewer creates a throwaway Clerk Organization (its creator
>    is `org:admin` by default), switches active org to it, and gets Admin
>    `TenantContext` plus all three permissions on their real tenant
>    (confirmed live: `role: Admin`, `can_train/can_audit/can_load: true`). A
>    token role claim is now only used when the token's `org_id` is the org the
>    resolved tenant is actually tied to; otherwise the persisted `User.role`
>    governs, and `Viewer` if there is none. The same clamp is applied on the
>    first-login write path so a distrusted role is never persisted either.
>    Side effect, deliberate: an org-less/stale-cookie request now keeps the
>    user's persisted role instead of clamping to Viewer — the Gap 157 symptom,
>    at context level.
> 3. **`admin_email` comes from the token's own `email`/`email_address` claim**,
>    never the body (which stays on the schema, ignored for real tokens, still
>    used on the mock path). `User.email` is globally unique, so a
>    caller-controlled address let an attacker provision as `ceo@bigcorp.com` —
>    squatting it *and* turning the real owner's later sign-up into an unhandled
>    `IntegrityError`/bare `500`, which item 3 of the 3b write-up claimed could
>    no longer happen. The admin `User` INSERT is now `IntegrityError`-guarded
>    too (rollback, re-read for a concurrent winner, else an explicit `409`).
>    Missing `email` claim → the same `user_<id>@domain.com` placeholder
>    `get_tenant_context_allow_unpaid()` uses, and the domain-adoption lookup is
>    **skipped entirely** for a placeholder, since every such caller shares the
>    literal domain `domain.com`.
> 4. **Adoption requires the domain tenant to be genuinely empty.** "No
>    `clerk_org_id` and no `User` rows" is not the same as empty: a user-less
>    legacy tenant can hold a paid plan, a PayU customer id, OAuth connections
>    and invoices, and adopting it hands all of that over (confirmed live: a
>    `pro_combined` tenant with an invoice was renamed and claimed, and its plan
>    returned to the caller). `_tenant_adoption_blockers()` now also rejects a
>    non-default `billing_plan`, any PayU id or `paid_through`, and any row in
>    `_TENANT_SCOPED_TABLES` (invoices, connections, audit logs, extraction
>    templates + versions, chat sessions, chat feedback, email senders, webhook
>    subscriptions). Falling through to a fresh isolated tenant is the safe
>    outcome, so this being strict enough to essentially never fire is fine.
> 5. **No raw DB constraint text in the response.** The unresolvable-collision
>    `409` interpolated `e.orig`, which on Postgres names the table, the
>    constraint and the colliding value. It now returns a generic detail (the
>    caller's own org id only) and prints the exception to stdout as
>    `[provision-diag]`, matching the `[jwt-diag]` convention.
>
> **Still open, not addressed here:** the adoption branch has a TOCTOU window —
> two concurrent provisions can both see the same domain tenant as adoptable.
> Confirming it needs real Postgres concurrency testing. A cheap partial
> mitigation is in place (the adoption commit is `IntegrityError`-guarded and
> falls through to creating a fresh tenant rather than 500ing), but the race
> itself is not closed.
>
> **Gap 344 update (2026-08-30) — a tenant holding a live API key is not "unclaimed".**
>
> Additive to finding 4 above, and the *only* change to that function since. Every
> condition Checkpoint 3c added is about **rows this schema can see**. An API key
> is not a row — it is a credential that lives outside the database, in whoever's
> integration was handed the raw value — and `_tenant_adoption_blockers()` never
> looked at `Tenant.api_key_hash`. A domain-matched tenant with no `clerk_org_id`,
> the `free` plan, no PayU state, no users and not one row in
> `_TENANT_SCOPED_TABLES` was adoptable by every check that existed, **and could
> still hold a minted key**. Adoption sets `clerk_org_id`, renames the tenant and
> commits while leaving `api_key_hash`/`api_key_salt`/`api_key_prefix` untouched —
> nothing anywhere clears them — so the old holder keeps authenticating, with the
> key they already have, against what is now a different real company's live
> workspace, reading its invoices through Gap 335's `X-API-Key` channel.
>
> The blocker list now includes **`"a live API key"`, ORed across all three
> columns** rather than just the digest: a row half-written by a crash between the
> assignments in `_mint_provisioning_api_key()` or `routers/settings.py::rotate_api_key()`
> (the only two writers) is a reason to be more suspicious of it, not less. All
> three are declared nullable with no default on `models.py::Tenant`, so NULL
> genuinely means "never minted". `api_key_scope` is deliberately **not** the
> signal — it is NOT NULL with a `"readonly"` default, so keying off it would
> disable the adoption path for every tenant that has ever existed.
>
> **This does not make new tenants un-adoptable.** `provision_tenant()` decides
> adoption-vs-create *first*, the adoption branch returns, and Gap 342's
> `_mint_provisioning_api_key()` runs only on the create branch afterwards — a
> tenant is never evaluated for adoption in the same request that mints its key,
> and a tenant provisioning created carries a `clerk_org_id` that already trips
> the first blocker. The only rows newly refused are key-holding, org-less ones:
> exactly the bad state.
>
> **Found during Feature 25's security review**, but not part of it — this is
> Checkpoint 3c code that predates plug-and-play; Gap 335/342 are merely what put
> a credential on the `Tenant` row for the function to have missed. Tracked as
> **Gap 344 against this feature**, not against Feature 25.
>
> **Still open, unchanged by this:** the TOCTOU window below. Adding a condition
> to the check does not close the race.

> **Also documented, no functional change:** the `tenant_id` JWT claim check
> carries a comment that if that claim is ever added to the Clerk JWT Template
> it must be sourced from `public_metadata` or an org shortcode — never
> `unsafe_metadata`, which the `role` claim precedent (Gap 173) proves is
> user-writable from a browser console. No such claim is emitted today, so the
> branch is inert.

> **Gap 4 update (2026-07-29):** that fallback is no longer unconditional. It now
> requires `ALLOW_MOCK_AUTH=true`, which defaults to `false`, so a deployed
> backend returns `401` instead of a mock Admin context. Set `ALLOW_MOCK_AUTH=true`
> in `apps/invoice-be/.env` to keep the zero-config local workflow described here;
> the pytest suite enables it itself via `tests/conftest.py`. Incomplete Clerk JWT
> config (`CLERK_JWKS_URL` / `CLERK_JWT_ISSUER` unset) now fails closed with a
> `500` rather than skipping issuer validation. Full detail, including why
> enforcement cannot yet be switched on in Azure, is in
> [GAP_4_AUTH_ENFORCEMENT.md](GAP_4_AUTH_ENFORCEMENT.md).

> **Gap 359 update (2026-09-01):** the default being `false` was the only
> thing standing between `ALLOW_MOCK_AUTH` and a full auth bypass reaching
> real traffic — nothing at startup stopped a deployment from setting it
> `true` by accident. `config.py` now refuses to import at all if
> `ALLOW_MOCK_AUTH=True` and `ENVIRONMENT` is not one of
> `NON_PRODUCTION_ENVIRONMENTS` (`dev`, `development`, `local`, `test`,
> `testing`, `qa`, `staging`) — a hard failure at import time, before the
> process ever binds a port, not a log warning. The flag itself is
> unchanged and still needed for local dev and the ~130+ header-less
> `TestClient` calls across the suite; removing it entirely was considered
> and explicitly rejected as out of scope for this gap. `.env`,
> `.env.example` and `tests/conftest.py` now all declare `ENVIRONMENT`
> alongside `ALLOW_MOCK_AUTH=true`, which none of them needed to before this
> guard existed.

`get_current_user_context()` in `routers/auth.py` just echoes that resolved context back for the FE's `/auth/me` call. `get_db_session()` yields a scoped SQLModel `Session`; every router is expected to filter its own queries by `context.tenant_id` — there is no query-level enforcement, it's a per-router convention. See "Detailed Implementation Plan" below for the full walkthrough.

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
  - Add the `User` SQLModel (see `Database_Schema_Document.md`) and provision a row on first SSO login.
  - *Gap 133 (2026-08-11) revised this task's own design: the "domain-based tenant matching" it originally called for is exactly what merged unrelated users into a shared tenant and has been removed. A `User` row is still created on first login, but only once `clerk_org_id` (or a `tenant_id` claim) resolves a tenant that `POST /auth/provision` created at sign-up; otherwise the request is `409`d.*
  - Switch `AuditLog.actor_user_id` to a real foreign key into `users(id)` instead of a raw JWT claim string.
  - Retire the ad-hoc tenant auto-creation fallback in `routers/invoices.py` once this flow owns tenant/user provisioning.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_auth.py` verifying that JWTs from different tenants return status-isolated responses, and `'unpaid'` users are blocked.
* **Postgres-only cases** (Hard rule 2 — these assert row-state/locking behaviour SQLite cannot represent, and `pytest.skip` themselves when `DATABASE_URL` is not PostgreSQL): `test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres` (Gap 133 sub-item 1 + Gap 342 — two concurrent provisions, one tenant, one surviving key, one sender row) and `test_api_key_blocks_adoption_on_postgres` (Gap 344 — an A/B where a keyless domain tenant of identical shape is still adopted while the key-holding one is refused, so the outcome is attributable to the key and not to some other blocker). A run that reports these as skipped is not evidence.
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

