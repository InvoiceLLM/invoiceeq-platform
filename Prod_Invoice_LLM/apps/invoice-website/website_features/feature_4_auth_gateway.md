# Feature Website 4: Clerk Auth Gateway & Company Provisioning

Manage organisation sign-up, Clerk-based authentication, role-scoped login, and redirect users to the `invoice-fe` dashboard.

**Implementation note (2026-07-28):** built via Clerk **Organizations** (one Clerk org per tenant, explicitly created at signup) rather than the domain-auto-detection flow originally spec'd below in Tasks 4.1-4.3 — email-domain matching is kept only as a legacy fallback for tenants that predate Clerk. Reconciled from the `auth-feature-4` branch onto current master; see `website_features_tracker.md` Gap 2/3 for what's still open (real Clerk keys, `/forgot-password`).

### File Coordinates
* Website signup page: `apps/invoice-website/app/signup/page.tsx` — `SignupPage()`, org creation form + `handleSignup()`
* Website login page: `apps/invoice-website/app/login/page.tsx` — `LoginPage()`, role toggle (admin/user) + OTP second-factor + `processSignIn()`
* Website auth middleware: `apps/invoice-website/middleware.ts` — bare `clerkMiddleware()`, no route protection enforced
* invoice-fe auth middleware: `apps/invoice-fe/middleware.ts` — same, plus `ClerkProvider` in `apps/invoice-fe/app/layout.tsx` and real sign-out wiring in `apps/invoice-fe/components/layout/Header.tsx`
* Backend auth router: `apps/invoice-be/routers/auth.py` — `GET /auth/me`, `POST /auth/provision`, `POST /auth/logout`
* Backend JWT/tenant resolution: `apps/invoice-be/dependencies.py` — `get_tenant_context()`
* Tenant schema: `apps/invoice-be/models.py` — `Tenant.clerk_org_id`

### Functionality
1. **Signup** (`SignupPage`/`handleSignup`): admin fills org name/type/country + email/password → `signUp.create()` → Clerk session activated → `window.Clerk.createOrganization()` creates the Clerk org → org metadata (`orgId`, `orgName`, `orgType`, `country`, `role: "admin,user"`) written to the user → backend `POST /auth/provision` called to create the matching `Tenant` row (`clerk_org_id` linked) → redirect to `/login`. Org creation and the provision call are both best-effort/non-fatal — a failure there doesn't block the Clerk account itself from existing.
2. **Login** (`LoginPage`/`processSignIn`): user picks a role (Admin/User) then signs in via `signIn.create()`. Supports email-code second-factor (OTP) if Clerk requires it. After sign-in, checks the user's `unsafeMetadata.role` (comma-separated, e.g. `"admin,user"`) against the selected role — mismatch shows an Access Denied state rather than silently logging in as the wrong role. Resolves and activates the Clerk organization membership, then redirects to `invoice-fe` (`${NEXT_PUBLIC_FE_URL}/dashboard` for both roles today — `invoice-fe` has no separate admin route yet).
3. **Backend provisioning** (`POST /auth/provision`): idempotent — repeat calls with the same `clerk_org_id` return the existing tenant rather than duplicating. Falls back to linking an existing domain-matched tenant (pre-Clerk-org tenants) before creating a new one.
4. **JWT tenant resolution** (`get_tenant_context`): every authenticated backend request decodes the Clerk session JWT, resolves `clerk_org_id`/`tenant_id` claims to a `Tenant` row (priority: `clerk_org_id` → `tenant_id` → email domain), and backfills `clerk_org_id` onto tenants found via the older lookup paths. Falls back to `MOCK_TENANT_ID` when no `Authorization` header is present (local dev / no-auth-yet callers).
5. **Sign-out** (`invoice-fe` `Header.tsx`): calls the backend `POST /auth/logout` (via `invoice-fe`'s own `/api/auth/logout` proxy route) for server-side cleanup, then Clerk's `signOut()`, then redirects to `${NEXT_PUBLIC_WEBSITE_URL}/login`.

### Verification Plan
* **Automated**: full existing `invoice-be` pytest suite (78 tests) passes with these changes; `alembic upgrade head` applies the `clerk_org_id` migration cleanly on top of current head.
* **Structural (done)**: with placeholder Clerk keys, `invoice-fe` (dashboard/chat/ingestion/trainer/flows/settings) and `invoice-website` (`/`, `/login`, `/signup`) all render correctly — confirms the middleware/`ClerkProvider` wiring doesn't break anything.
* **Not yet done — needs real Clerk keys (Gap 2)**: an actual signup → Clerk org creation → `/auth/provision` → login → dashboard redirect walkthrough, since placeholder keys can't complete real Clerk API calls.
