# Feature 2.1: Vendor Flow — Outbound Dashboard (Split-Screen)

Extends [feature_2_dashboard.md](feature_2_dashboard.md). Spec only — no implementation yet, pending approval of the full Vendor Flow document set.

Adds the AR mirror of the existing metrics grid, consuming [feature_8.1_vendor_flow_dashboard.md](../../invoice-be/be_features/feature_8.1_vendor_flow_dashboard.md)'s new endpoint. The one screen in Vendor Flow that splits rather than tabs — see the design reasoning in the BE doc.

### File Coordinates (planned)
* Edited (small, additive): `apps/invoice-fe/app/dashboard/page.tsx` — wraps the existing content in a conditional split-layout container.
* New component: `apps/invoice-fe/components/dashboard/OutboundMetricsGrid.tsx` — mirrors `MetricsGrid.tsx`'s card layout for AR metrics; not a fork of the file, since the underlying data/labels differ enough (`amount_collected` vs `paid_amount`, `top_customers` vs `top_vendors`) to warrant a clean new component rather than prop-branching one component two ways.
* Existing, imported-not-edited: `apps/invoice-fe/components/dashboard/ClientPerformanceChart.tsx` — actually reused as-is for `top_customers`, since it already just takes a `{name, amount}[]`-shaped list and renders bars; no vendor-specific logic inside it to fork.
* New proxy route: `apps/invoice-fe/app/api/dashboard/outbound-metrics/route.ts` → `GET /outbound-dashboard/metrics`.

### Functionality

**Layout logic in `page.tsx`:**
- Only *Receive* enabled: renders exactly as today — `MetricsGrid.tsx`, `ClientPerformanceChart.tsx`, `RecentInvoicesTable.tsx`, untouched, full width.
- Only *Send* enabled: same single-column layout, but showing `OutboundMetricsGrid.tsx` + `ClientPerformanceChart.tsx` (fed `top_customers`) as the page's sole content.
- Both enabled: `page.tsx` wraps both halves in a two-column grid (`grid-cols-2` on wide viewports, stacking on narrow ones) — left: today's `MetricsGrid.tsx` unchanged, right: `OutboundMetricsGrid.tsx`. Both render simultaneously, no tab, no click needed — matches the "tenant wants to see in totality" requirement from design review.

**`OutboundMetricsGrid.tsx` cards:** total invoiced out, amount collected, outstanding receivables, at-risk (overdue) receivables, verification accuracy (server-computed, avoiding the same client-side-approximation mistake `MetricsGrid.tsx`'s current accuracy card makes), average days to payment (real `paid_at`-`sent_at`, not estimated).

**No combined/net card anywhere on this page** — reinforced from the BE doc: that comparison is Chat-only.

### Explicitly out of scope
- Forking `FilterBar.tsx`/`localStorage` filter persistence for the outbound side in v1 — the split-screen shows unfiltered current totals only; filtering can be added to both sides symmetrically later if needed.

### Tasks
- [ ] **Task 2.1.1:** Build `OutboundMetricsGrid.tsx`.
- [ ] **Task 2.1.2:** Add the conditional split-layout wrapper to `page.tsx`, gated on `GET /settings/vendor-flow`.
- [ ] **Task 2.1.3:** Build the new metrics proxy route.
- [ ] **Task 2.1.4:** Wire `ClientPerformanceChart.tsx` to accept `top_customers` alongside its existing `top_vendors` usage (a prop-shape check only — confirm no vendor-specific assumption is baked into the component before treating this as zero-touch).

### Verification Plan
* **Manual Verification:**
  - Receive-only tenant: confirm Dashboard is pixel-identical to today.
  - Both enabled: confirm both halves render side-by-side with correct, independent data, and that resizing to a narrow viewport stacks them instead of squeezing both into unreadable columns.
  - Confirm no net/combined figure appears anywhere on this page.
