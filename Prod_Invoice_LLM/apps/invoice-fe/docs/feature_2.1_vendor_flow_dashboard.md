# Feature 2.1: Service Flow — Outbound Dashboard (Split-Screen)

Extends [feature_2_dashboard.md](feature_2_dashboard.md). Spec only — no implementation yet, pending approval of the full Service Flow document set.

Adds the AR mirror of the existing metrics grid, consuming [feature_8.1_vendor_flow_dashboard.md](../../invoice-be/docs/feature_8.1_vendor_flow_dashboard.md)'s new endpoint. The one screen in Service Flow that splits rather than tabs — see the design reasoning in the BE doc.

### File Coordinates (planned)
* Edited (small, additive): `apps/invoice-fe/app/dashboard/page.tsx` — wraps the existing content in a conditional split-layout container.
* New component: `apps/invoice-fe/components/dashboard/OutboundMetricsGrid.tsx` — mirrors `MetricsGrid.tsx`'s card layout for AR metrics; not a fork of the file, since the underlying data/labels differ enough (`amount_collected` vs `paid_amount`, `top_customers` vs `top_vendors`) to warrant a clean new component rather than prop-branching one component two ways.
* Existing, imported-not-edited: `apps/invoice-fe/components/dashboard/ClientPerformanceChart.tsx` — actually reused as-is for `top_customers`, since it already just takes a `{name, amount}[]`-shaped list and renders bars; no vendor-specific logic inside it to fork.
* New proxy route: `apps/invoice-fe/app/api/dashboard/outbound-metrics/route.ts` → `GET /outbound-dashboard/metrics`.

**Correction (2026-07-29):** an earlier pass of this doc also added an `OutboundInvoicesTable.tsx`/`OutboundFilterBar.tsx` invoice list here, split-screen alongside the metrics grid. That's been pulled back out — see the Dashboard/Audit split decision below. The full outbound invoice list + filters now live in `feature_4.1_vendor_flow_auditor.md`, not here.

### Functionality

**Dashboard/Audit split decision (2026-07-29):** invoice-level lists (both inbound and outbound) no longer live on Dashboard at all — Dashboard is overview-only (metrics, trends, top vendors/customers). The full paginated invoice list + filters, for both directions, moved to a new unified Invoices/Audit queue screen (closes FE Gap 28) — see `feature_4_auditor.md` (inbound tab) and `feature_4.1_vendor_flow_auditor.md` (outbound tab). Dashboard keeps only a small **"Needs Attention"** widget (top 5-10 `AUDIT_REQUIRED`/`NEEDS_REVIEW` rows across both directions, each linking straight to the relevant review screen) as its one piece of invoice-level detail.

**Layout logic in `page.tsx`:**
- Only *Receive* enabled: renders exactly as today's overview — `MetricsGrid.tsx`, `ClientPerformanceChart.tsx`, `ActionableInsightsPanel.tsx`, `TrainerImpactPanel.tsx`, `NeedsAttentionWidget.tsx` — no invoice list.
- Only *Send* enabled: same single-column overview, showing `OutboundMetricsGrid.tsx` + `ClientPerformanceChart.tsx` (fed `top_customers`) + the same shared `NeedsAttentionWidget.tsx` (filtered to outbound `NEEDS_REVIEW` rows).
- Both enabled: `page.tsx` wraps the two metrics halves in a two-column grid (`grid-cols-2` on wide viewports, stacking on narrow ones) — left: `MetricsGrid.tsx`, right: `OutboundMetricsGrid.tsx`. `NeedsAttentionWidget.tsx` sits below, showing both directions' flagged rows together. No tab, no click needed for the metrics split — matches the "tenant wants to see in totality" requirement from design review.

**`NeedsAttentionWidget.tsx`** (new, shared across both directions): fetches top N `AUDIT_REQUIRED` (inbound) + `NEEDS_REVIEW` (outbound) rows via the same list endpoints used by the Invoices/Audit screen (just `limit=8`, no pagination needed here), each row linking to `/invoices/review/{id}` or `/invoices/outbound-review/{id}` respectively — a teaser/CTA, not a working queue.

**`OutboundMetricsGrid.tsx` cards:** total invoiced out, amount collected, outstanding receivables, at-risk (overdue) receivables, verification accuracy (server-computed, avoiding the same client-side-approximation mistake `MetricsGrid.tsx`'s current accuracy card makes), average days to payment (real `paid_at`-`sent_at`, not estimated).

**No combined/net card anywhere on this page** — reinforced from the BE doc: that comparison is Chat-only.

### Explicitly out of scope
- Any invoice-level filtering (vendor/customer, date, status, tag) on this page — that's the Invoices/Audit screen's job now (`feature_4_auditor.md`/`feature_4.1_vendor_flow_auditor.md`). Dashboard's `FilterBar.tsx` continues to filter only the metrics cards/chart, unchanged from today.
- Full invoice list/pagination of any kind — moved entirely to the Invoices/Audit screen (see Dashboard/Audit split decision above).

### Tasks
- [ ] **Task 2.1.1:** Build `OutboundMetricsGrid.tsx`.
- [ ] **Task 2.1.2:** Add the conditional split-layout wrapper to `page.tsx`, gated on `GET /settings/vendor-flow`.
- [ ] **Task 2.1.3:** Build the new metrics proxy route.
- [ ] **Task 2.1.4:** Wire `ClientPerformanceChart.tsx` to accept `top_customers` alongside its existing `top_vendors` usage (a prop-shape check only — confirm no vendor-specific assumption is baked into the component before treating this as zero-touch).
- [ ] **Task 2.1.5:** Build `NeedsAttentionWidget.tsx` (shared, direction-agnostic) and wire it into `page.tsx` below the metrics split.
- [ ] **Task 2.1.6 (redundant-code removal):** once the Invoices/Audit screen (Task 4.9 in `feature_4_auditor.md`) ships, remove `dashboard/page.tsx`'s own invoice-pagination state (`activeTab`, `currentPage`, `totalCount`, `fetchInvoicesPage`, `PAGE_SIZE`, `tabToStatusParams`) and its `RecentInvoicesTable` import — that logic is fully superseded by the new screen and would otherwise be dead/duplicated code left behind on Dashboard.

### Verification Plan
* **Manual Verification:**
  - Receive-only tenant: confirm Dashboard is pixel-identical to today's metrics/chart/insights, minus the invoice table (moved out).
  - Both enabled: confirm both metrics halves render side-by-side with correct, independent data, and that resizing to a narrow viewport stacks them instead of squeezing both into unreadable columns.
  - `NeedsAttentionWidget`: confirm it shows both inbound and outbound flagged rows together, and each row's link opens the correct review screen for its direction.
  - Confirm no net/combined figure appears anywhere on this page.
  - After Task 2.1.6: confirm `dashboard/page.tsx` no longer imports `RecentInvoicesTable`/`FilterBar` and has no leftover pagination state — grep clean.
