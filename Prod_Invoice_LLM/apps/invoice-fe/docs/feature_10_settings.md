# Feature 10: Settings Screen

New feature — the app's first `/settings` route. Confirmed via a full listing of `apps/invoice-fe/app/**/page.tsx` that no Settings, Connectors, Email Ingestion, or Webhooks page exists today. Consolidates those three spec-only features ([feature_7_connectors.md](feature_7_connectors.md), [feature_8_email_ingestion.md](feature_8_email_ingestion.md), [feature_9_webhooks.md](feature_9_webhooks.md)) as sections of one screen, by reference — none of their specs change here — plus the two new Service Flow toggles.

### File Coordinates (as built)
* Page: `apps/invoice-fe/app/settings/page.tsx`.
* Component: `apps/invoice-fe/components/settings/ServiceFlowToggles.tsx` — the two switches (built under this name; the `VendorFlowToggles.tsx` name originally planned here was never built — an orphaned component of that name existed briefly but was dead code, unreferenced anywhere, and was deleted 2026-07-29).
* Nav entry: `apps/invoice-fe/components/layout/Sidebar.tsx` — `/settings` link present.
* Proxy route: `apps/invoice-fe/app/api/settings/service-flow/route.ts` → `GET`/`PUT /settings/vendor-flow` (BE path unchanged). The original `apps/invoice-fe/app/api/settings/vendor-flow/route.ts` path still exists but is now just a backward-compatible re-export of the `service-flow` route.

### Functionality

**`ServiceFlowToggles.tsx`:** two switches, *Receive Invoices* and *Send Invoices*, plus a middle tile linking to **Email Setup** (`/settings/email`) for the single app mailbox and inbound/outbound authorized sets (Feature 8, redesigned 2026-08-10). Disabled (not hidden) for non-Admin roles, with a tooltip explaining why.

**Upgrade / enable gate for Send Invoices**:
* When an Admin toggles *Send Invoices* ON:
  * Checks `billing_plan` via `GET /api/settings/service-flow`. Non-`pro_combined` opens the Combined Pro Upgrade Modal (`COMBINED_PLAN_UPGRADE_URL` → website pricing; Gap 101 closed 2026-08-04).
  * Backend requires ≥1 **outbound-set** authorized email (`TenantEmailSender.email_set='outbound'`) — not the legacy `outbound_sender_email` string. FE surfaces a clear error and links to Email Setup if the BE returns 400.
* Saving calls `PUT /api/settings/service-flow`.

**Page shell (as built):** Service Flow + integration tiles including Email Setup (`/settings/email`), Connectors, Webhooks, Subscriptions, etc.

**Tile visibility (Gap 167, 2026-08-06):** the integration tiles are described by a typed `IntegrationTile[]`, and the Admin Console tile carries `adminOnly: true`. `page.tsx` filters on `role === "Admin"` from `useAuth()` — the same backend-resolved role `ServiceFlowToggles` and `/settings/webhooks` gate on, never Clerk's client-editable metadata. It was previously the only tile on the page with no gate at all, so any role could see it and follow it to `/admin`. Because `role` is `""` until `GET /auth/me` resolves, an admin-only tile stays hidden while identity loads rather than appearing and then vanishing.

**Admin Console (`app/admin/page.tsx`) — role honesty (Gaps 167/168/169, 2026-08-06):** the route now gates itself as well as being hidden from the Settings grid: a non-Admin (or a viewer whose `GET /api/admin/users` comes back 401/403, tracked as `accessDenied`) gets an "Access Restricted" panel naming their real role, instead of the previous behaviour where that 403 was swallowed by `if (!res.ok) return;` and the page rendered as an empty-but-legitimate console. Every label describing the signed-in viewer — the "Organisation Owner" subtitle, the role badge, the permissions cell — is read from `useAuth()` (`role`, `canTrain`/`canAudit`/`canLoad`) rather than hardcoded, and other users' rows show their stored `role` instead of a literal "User". The "Remove" button is backed by a real `DELETE /api/admin/users/{ref}` (see `feature_7_connectors.md`'s sibling note and the tracker's Gap 168 entry for the full vertical slice): the FE route calls the backend's Admin-only, tenant-scoped `remove_tenant_user` first and only then deletes the Clerk account, which is what actually revokes sign-in; a Clerk failure is reported as partial success, not as a clean removal. The onboarding banner links `${NEXT_PUBLIC_WEBSITE_URL}/login` instead of the never-existent `localhost:3000/admin/login`.

**Consumption elsewhere:** `GET /settings/vendor-flow`'s response is what Ingestion ([feature_3.1](feature_3.1_vendor_flow_ingestion.md)), Dashboard ([feature_2.1](feature_2.1_vendor_flow_dashboard.md)), and Auditor ([feature_4.1](feature_4.1_vendor_flow_auditor.md)) each read to decide their single-view/split/tab rendering.

### Explicitly out of scope
- Webhooks UI implementation — Feature 9 remains separately scoped, unstarted; this page just reserves its place with a "Coming soon" chip. (Connectors and Email Ingestion & Delivery, originally out of scope here too, were subsequently implemented as Features 7 and 8 and are now live sub-pages linked from this screen.)
- Invoice Builder branding/logo/template UI — belongs to `feature_17_invoice_builder.md` once that gets its own scoping pass.

### Tasks
- [x] **Task 10.1:** Build `ServiceFlowToggles.tsx` — two switches, Admin-only enable, save via the proxy route.
- [x] **Task 10.2:** Build `app/settings/page.tsx` + Sidebar nav entry.
- [x] **Task 10.3:** Build the proxy route (`/api/settings/service-flow`).

### Verification Plan
* **Manual Verification:**
  - As Admin, toggle *Send Invoices* on; confirm Ingestion/Dashboard/Auditor immediately reflect the new tab/split behavior on next navigation.
  - As Auditor/Viewer role, confirm the toggles render disabled with an explanatory tooltip, and a direct `PUT` attempt (if somehow triggered) surfaces the `403` as a toast, not a silent no-op.
  - As Admin, leave *Outbound Sender Email* empty and try to enable *Send Invoices*; confirm it's blocked client-side with an inline message, no network call made.
