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
* **Not yet done — needs real Clerk keys (Gap 2), tracked as Gap 9**: full real-key walkthrough, run in this order:
  1. **Setup**: real Secret Key + Publishable Key into `invoice-be/.env`, `invoice-fe/.env.local`, `invoice-website/.env.local`; real `CLERK_JWT_ISSUER`/`CLERK_JWKS_URL` into `invoice-be/.env`; restart all 3 dev servers (env vars only load at process start).
  2. **Backend JWT verification, isolated**: `GET /auth/me` with no `Authorization` header still falls back to `MOCK_TENANT_ID` (Gap 4 not yet closed, so this should still work); with a real Clerk session token (grab from browser devtools after a real login) it returns real `tenant_id`/`user_id`/`role` from the JWT, not the mock; a deliberately tampered/expired token returns `401`, not a `500`.
  3. **Website signup**: `/signup` → submit → confirm Clerk actually creates the user (Clerk Dashboard → Users) and organization (Clerk Dashboard → Organizations); confirm `POST /auth/provision` creates a real `Tenant` row with `clerk_org_id` populated (`SELECT * FROM tenant WHERE clerk_org_id IS NOT NULL`); re-submit/re-call with the same `clerk_org_id` and confirm it returns the existing tenant, doesn't duplicate.
  4. **Website login**: log in as the admin just created, selecting "Admin" → confirm redirect to `${NEXT_PUBLIC_FE_URL}/dashboard`; log in selecting a role that doesn't match the account's `unsafeMetadata.role` → confirm the Access Denied state shows rather than silently logging in; if the Clerk instance has second-factor enabled, confirm the OTP screen appears and completes sign-in.
  5. **invoice-fe post-login**: `Header.tsx` shows the real signed-in user's name/email/org, not the "Alex R." placeholder fallback; Sign Out fires `POST /api/auth/logout` (check network tab), actually clears the Clerk session, and redirects to `${NEXT_PUBLIC_WEBSITE_URL}/login`.
  6. **Regression**: re-run `uv run pytest` (still 78+ passing, no regressions from real keys replacing placeholders); re-verify dashboard/chat/ingestion/trainer/flows/settings all still load with real keys in place instead of placeholders.
