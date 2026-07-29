# Feature 10: Settings Screen

New feature — the app's first `/settings` route. Confirmed via a full listing of `apps/invoice-fe/app/**/page.tsx` that no Settings, Connectors, Email Ingestion, or Webhooks page exists today. Consolidates those three spec-only features ([feature_7_connectors.md](feature_7_connectors.md), [feature_8_email_ingestion.md](feature_8_email_ingestion.md), [feature_9_webhooks.md](feature_9_webhooks.md)) as sections of one screen, by reference — none of their specs change here — plus the two new Service Flow toggles.

### File Coordinates (as built)
* Page: `apps/invoice-fe/app/settings/page.tsx`.
* Component: `apps/invoice-fe/components/settings/ServiceFlowToggles.tsx` — the two switches (built under this name; the `VendorFlowToggles.tsx` name originally planned here was never built — an orphaned component of that name existed briefly but was dead code, unreferenced anywhere, and was deleted 2026-07-29).
* Nav entry: `apps/invoice-fe/components/layout/Sidebar.tsx` — `/settings` link present.
* Proxy route: `apps/invoice-fe/app/api/settings/service-flow/route.ts` → `GET`/`PUT /settings/vendor-flow` (BE path unchanged). The original `apps/invoice-fe/app/api/settings/vendor-flow/route.ts` path still exists but is now just a backward-compatible re-export of the `service-flow` route.

### Functionality

**`ServiceFlowToggles.tsx`:** two switches, *Receive Invoices* and *Send Invoices*, each independently toggleable, plus a text input for *Outbound Sender Email* (shown once, above the *Send Invoices* switch, since the switch depends on it). Disabled (not hidden) for non-Admin roles, with a tooltip explaining why. 

**Upgrade Verification Gate**:
* When an Admin toggles *Send Invoices* ON:
  * The component checks the current tenant's `billing_plan` (fetched via `GET /api/settings/service-flow` on mount).
  * If the plan is `'pro_combined'`, the toggle behaves normally.
  * If the plan is anything else (e.g. `'free'` or standard `'pro'`), the toggle remains off and opens the **Combined Pro Upgrade Modal**, which links out to `/billing/upgrade` (no proration-delta calculation is actually shown — that part of the original plan wasn't built).
* Attempting to save the toggle state with the sender email field empty is blocked client-side before any save call is made. Saving calls `PUT /api/settings/service-flow` (proxying to BE `PUT /settings/vendor-flow`).

**Page shell (as built):** `page.tsx` renders the Service Flow section (`ServiceFlowToggles.tsx`) plus Connectors and Email Ingestion & Delivery sections, each linking out to their own sub-pages (`/settings/connectors`, `/settings/email`, built as Features 7 and 8 respectively). Only Webhooks (Feature 9, still spec-only) remains a "Coming soon" chip.

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
