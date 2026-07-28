# Feature 10: Settings Screen

New feature — the app's first `/settings` route. Confirmed via a full listing of `apps/invoice-fe/app/**/page.tsx` that no Settings, Connectors, Email Ingestion, or Webhooks page exists today. Consolidates those three spec-only features ([feature_7_connectors.md](feature_7_connectors.md), [feature_8_email_ingestion.md](feature_8_email_ingestion.md), [feature_9_webhooks.md](feature_9_webhooks.md)) as sections of one screen, by reference — none of their specs change here — plus the two new Service Flow toggles.

### File Coordinates (planned)
* New page: `apps/invoice-fe/app/settings/page.tsx`.
* New component: `apps/invoice-fe/components/settings/VendorFlowToggles.tsx` — the two switches.
* New nav entry: `apps/invoice-fe/components/layout/Sidebar.tsx` — one new link (existing pattern, same as the Trainer nav link added when Feature 6 shipped).
* New proxy route: `apps/invoice-fe/app/api/settings/vendor-flow/route.ts` → `GET`/`PUT /settings/vendor-flow` ([feature_16_settings.md](../../invoice-be/docs/feature_16_settings.md) BE).

### Functionality

**`VendorFlowToggles.tsx`:** two switches, *Receive Invoices* and *Send Invoices*, each independently toggleable, plus a text input for *Outbound Sender Email* (shown once, above the *Send Invoices* switch, since the switch depends on it). Disabled (not hidden) for non-Admin roles, with a tooltip explaining why. 

**Upgrade Verification Gate**:
* When an Admin toggles *Send Invoices* ON:
  * The component checks the current tenant's `billing_plan` (fetched from session context or `/api/settings/vendor-flow`).
  * If the plan is `'pro_combined'`, the toggle behaves normally.
  * If the plan is `'free'` or `'pro'` (standard), the toggle remains off and opens the **Combined Pro Upgrade Modal**. The modal prompts the user to upgrade to the ₹8,999/month Combined Pro plan (calculating proration delta if on standard Pro) and provides a checkout redirection button.
* Attempting to save the toggle state with the sender email field empty is blocked client-side before any save call is made. Saving calls `PUT /settings/vendor-flow`.

**Page shell for v1:** since Connectors/Email/Webhooks have no built FE pages yet, `page.tsx`'s v1 only needs to render `VendorFlowToggles.tsx`; the other three sections get their own component slots added when each of those features is actually implemented, not built as empty placeholders now.

**Consumption elsewhere:** `GET /settings/vendor-flow`'s response is what Ingestion ([feature_3.1](feature_3.1_vendor_flow_ingestion.md)), Dashboard ([feature_2.1](feature_2.1_vendor_flow_dashboard.md)), and Auditor ([feature_4.1](feature_4.1_vendor_flow_auditor.md)) each read to decide their single-view/split/tab rendering.

### Explicitly out of scope
- Any Connectors/Email/Webhooks UI implementation — those remain separately scoped, unstarted features; this page just reserves their place.
- Invoice Builder branding/logo/template UI — belongs to `feature_17_invoice_builder.md` once that gets its own scoping pass.

### Tasks
- [ ] **Task 10.1:** Build `VendorFlowToggles.tsx` — two switches, Admin-only enable, save via the new proxy route.
- [ ] **Task 10.2:** Build `app/settings/page.tsx` (v1: toggles only) + Sidebar nav entry.
- [ ] **Task 10.3:** Build the new proxy route.

### Verification Plan
* **Manual Verification:**
  - As Admin, toggle *Send Invoices* on; confirm Ingestion/Dashboard/Auditor immediately reflect the new tab/split behavior on next navigation.
  - As Auditor/Viewer role, confirm the toggles render disabled with an explanatory tooltip, and a direct `PUT` attempt (if somehow triggered) surfaces the `403` as a toast, not a silent no-op.
  - As Admin, leave *Outbound Sender Email* empty and try to enable *Send Invoices*; confirm it's blocked client-side with an inline message, no network call made.
