# Feature Website 4 Test Suite: Clerk Auth Gateway & Company Provisioning

Spec source: [`website_features/feature_4_auth_gateway.md`](../../../apps/invoice-website/website_features/feature_4_auth_gateway.md).
Scope: `app/{signup,login,forgot-password}/page.tsx`, `app/api/auth/provision/route.ts`, `apps/invoice-be/routers/auth.py`, `apps/invoice-be/dependencies.py::get_tenant_context`, plus the `invoice-fe` side (`app/admin/page.tsx`, `app/api/admin/create-user/route.js`, `Header.tsx` sign-out).

**Status flag**: real Clerk keys are not yet in place anywhere (Gap 2) — everything below is currently only structurally verified (placeholder keys let the app render without crashing). The real-key walkthrough is tracked separately as Gap 9 in `website_features_tracker.md`; run this suite against real keys once that's unblocked, and against placeholder keys for the structural/DB/log checks that don't require a real Clerk round-trip.

---

## 1. Screen Alignment Check

| TC ID | Element | Expected Visual Spec |
|---|---|---|
| TC-WEB4-01 | Login page role toggle | Admin/User toggle, matches site design tokens |
| TC-WEB4-02 | Signup form | Org name/type/country + email/password fields, dark theme, emerald primary CTA (matches Feature 1 button spec) |
| TC-WEB4-03 | OTP second-factor screen | Renders when Clerk's `signIn.create()` demands a second factor |
| TC-WEB4-04 | Access Denied state | Distinct visual state (not a silent redirect) when selected role ≠ `unsafeMetadata.role` |
| TC-WEB4-05 | Forgot-password flow | Two-step UI (request code → enter code + new password), matches login/signup design tokens |
| TC-WEB4-06 | Admin console (`invoice-fe/app/admin/page.tsx`) | Org member list + `CreateUserModal` (name/email/password fields) |

---

## 2. Functionality Check

| TC ID | Action | Expected Behavior |
|---|---|---|
| TC-WEB4-07 | Submit signup form (`SignupPage`/`handleSignup`) | `signUp.create()` → Clerk session activated → `window.Clerk.createOrganization()` → metadata written (`orgId`, `orgName`, `orgType`, `country`, `role: "admin,user"`) → `POST /auth/provision` → redirect to `/login`. Org creation and provision are best-effort/non-fatal — confirm a provision failure still leaves the Clerk account intact. |
| TC-WEB4-08 | Log in (`LoginPage`/`processSignIn`) | Role selection + `signIn.create()`; OTP path if required; role mismatch (`unsafeMetadata.role` vs. selected) → Access Denied, no login; success → resolves/activates org membership → redirect to `${NEXT_PUBLIC_FE_URL}/dashboard` |
| TC-WEB4-09 | `POST /auth/provision` called twice with the same `clerk_org_id` | Second call returns the **existing** tenant — idempotent, no duplicate row |
| TC-WEB4-10 | `POST /auth/provision` for an org whose email domain matches a pre-Clerk tenant | Links to that existing tenant (backfills `clerk_org_id`) instead of creating a new one |
| TC-WEB4-11 | `get_tenant_context()` resolution order | `clerk_org_id` → `tenant_id` → email domain; **no** `Authorization` header → falls back to `MOCK_TENANT_ID`/`role="Admin"` (Gap 4, still open by design for dev testing — confirm this is still current behavior) |
| TC-WEB4-12 | Click Sign Out (`invoice-fe` `Header.tsx`) | `POST /api/auth/logout` proxy → backend `POST /auth/logout` → Clerk `signOut()` → redirect to `${NEXT_PUBLIC_WEBSITE_URL}/login` |
| TC-WEB4-13 | Forgot-password flow (`ForgotPasswordPage`) | `signIn.create({strategy: "reset_password_email_code"})` sends a code → `signIn.attemptFirstFactor()` verifies code + sets new password in the same call |
| TC-WEB4-14 | Admin creates a user (`CreateUserModal` → `POST /api/admin/create-user`) | Calls Clerk's REST API directly (not the SDK) with `unsafe_metadata: {role: "user"}`, immediately marks email verified so the new user can sign in without a confirmation step |
| TC-WEB4-15 | **Security regression test (Gap 10, open)** | Call `POST /api/admin/create-user` directly with no session / a non-admin session. Today this route has **no server-side auth/role check** — expect it to incorrectly succeed. This test should be treated as a known-failing security case, tracked until Gap 10 is closed, not a pass. |
| TC-WEB4-16 | Attempt signup with no org name | Blocked client-side (`orgName` is a `required` field) — confirm there is no code path to a standalone, company-less account (Gap 11, by design, not yet built) |

---

## 3. Database Validation

| TC ID | Check |
|---|---|
| TC-WEB4-17 | After a successful signup: `SELECT * FROM tenant WHERE clerk_org_id = :org_id` returns exactly one row, populated from the new org. |
| TC-WEB4-18 | Repeat-provision with the same `clerk_org_id` (TC-WEB4-09): row count for that `clerk_org_id` stays at 1. |
| TC-WEB4-19 | Domain-fallback link (TC-WEB4-10): the pre-existing tenant's `clerk_org_id` column flips from `NULL` to the new value — confirm no second `Tenant` row was created for the same `domain`. |
| TC-WEB4-20 | Admin-created user (Gap 10 route): confirm whatever tenant association the created Clerk user ends up with server-side actually scopes to the calling admin's own org — and, given Gap 10's missing auth check, explicitly try to make it attach to a **different** tenant than the caller's to see how far the gap extends. |

---

## 4. Flow Validation via Log Files

| TC ID | Check |
|---|---|
| TC-WEB4-21 | **Gap, not a pass/fail**: `apps/invoice-be/routers/auth.py` and `dependencies.py` currently have **no `logger`/`logging.getLogger` calls at all**. Signup, login, provisioning, and JWT resolution produce **zero** backend log lines today — confirmed by grep, not just by not finding one in a sample run. Trigger a provisioning failure (e.g. malformed `clerk_org_id`) and confirm invoice-be's console genuinely shows nothing about it. This is worth flagging as a monitoring gap: auth failures are currently invisible from logs alone. |
| TC-WEB4-22 | If/when logging is added to close TC-WEB4-21 (tracked alongside Gap 9's real-key verification plan step 2 — tampered/expired token should return `401` not `500`), assert level correctness once it exists: successful auth = INFO/DEBUG, invalid/expired/mismatched-role token = WARNING, unexpected exception = ERROR. |

Same stdout-only caveat as the other three suites applies here too — there is no file-based log handler configured in `invoice-be` yet.
