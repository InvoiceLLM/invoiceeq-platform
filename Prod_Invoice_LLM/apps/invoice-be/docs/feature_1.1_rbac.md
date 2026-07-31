# Feature 1.1: Granular Role-Based Access Control

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
* Schema: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py) → `User` — add `can_train: bool`, `can_audit: bool`, `can_load: bool` (all default `False`)
* Dependency: [apps/invoice-be/dependencies.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/dependencies.py) → `TenantContext` gains the same 3 booleans, resolved from the `User` row (not the JWT — permissions are our own data, not Clerk's)
* Enforcement: `routers/trainer.py`, `routers/audit.py`, `routers/invoices.py` (upload endpoint) — new permission-check dependencies, same shape as the existing `context.role != "Admin"` checks in `routers/settings.py`/`routers/billing.py`
* FE nav filtering: `apps/invoice-fe/components/layout/Sidebar.tsx` (currently shows every item unconditionally — see `fe_features_tracker.md` Gap 99)
* FE identity source: `apps/invoice-fe/hooks/useAuth.ts` (currently reads `localStorage`, fully mocked — must be rewritten to fetch real `GET /auth/me` first; this feature's FE half is blocked on Clerk-list Gap 4's B1 — invoice-fe sending a real token at all — landing first)
* Admin UI: `apps/invoice-fe/app/admin/page.tsx` — add 3 checkboxes (Trainer/Auditor/Loader) per user, at creation and edit time

### Tasks
- [ ] **Task 1.1.1: Schema** — `can_train`/`can_audit`/`can_load` columns on `User`, Alembic migration, all default `False`.
- [ ] **Task 1.1.2: Backend enforcement** — permission-check dependency (parallel to the existing Admin-role pattern) wired into Trainer, Audit, and Ingestion-upload routers. Settings stays gated on `role == "Admin"` as it already is — no change needed there.
- [ ] **Task 1.1.3: `TenantContext` carries permissions** — `get_tenant_context()` resolves the 3 booleans from the `User` row alongside `role`, so `GET /auth/me` returns them for the FE to consume.
- [ ] **Task 1.1.4: FE — real `useAuth()`** — rewrite to call `GET /auth/me` instead of reading `localStorage`. Depends on Clerk-list Gap 4's B1 (real token wiring) landing first — no real permission data exists client-side until the FE actually sends a real session token.
- [ ] **Task 1.1.5: FE — `Sidebar.tsx` filtering** — hide Trainer/Auditor/Ingestion nav items when the corresponding permission is `false`; Settings/Admin hidden for non-Admins; Dashboard/Chat/Help always shown.
- [ ] **Task 1.1.6: Admin console UI** — add the 3 permission checkboxes to `app/admin/page.tsx`'s create/edit user flow, wired to a new `PUT /api/v1/admin/users/{id}/permissions`-style endpoint (Admin-only, same auth pattern as `create-user`).

### Verification Plan
* **Automated Tests**: a non-permissioned user hitting Trainer/Audit/Ingestion-upload endpoints directly gets a real `403`; an Admin can grant/revoke and the effect is immediate on the next request; Dashboard/Chat/Help remain reachable regardless of permission state.
* **Manual Verification**: create a user with no permissions granted, confirm the FE only shows Dashboard/Chat/Help; grant Trainer via the Admin console, confirm it appears without requiring a fresh login; confirm Settings/Admin console stay invisible/blocked for a non-Admin regardless of granted permissions.
