# Gap 183 — per-currency money display + per-currency dashboard aggregates

Combined scope (both slices), approved by user. No FX conversion, no currency filter UI,
no DB migration, no dashboard.py/outbound_dashboard.py unification.

## Backend
- [x] `routers/dashboard.py` — `GET /dashboard/metrics`: totals GROUP BY `COALESCE(currency,'USD')` -> `totals_by_currency[]`; `top_vendors` + `spend_over_time` gain `currency`
- [x] `routers/dashboard.py` — `get_dashboard_insights()` per-currency context blob for the LLM prompt
- [x] `routers/outbound_dashboard.py` — same for `GET /outbound-dashboard/metrics` (written independently, zero-touch rule)
- [x] `routers/outbound_dashboard.py` — `/invoices` list rows return `currency`
- [x] `agents/query_agent.py::_get_tenant_stats_summary` — per-currency spend, drop hardcoded `$`
- [x] `routers/invoices.py` — duplicate-detection path copies `currency` (data-loss bug) + SSE payload
- [x] Any other BE endpoint returning money rows without `currency` (sweep)

## Frontend
- [x] `lib/utils.ts::formatCurrency(amount, currency?)` — backwards compatible, default USD
- [x] `KpiCard` — shrink-to-fit font for multi-currency values
- [x] `MetricsGrid.tsx` / `OutboundMetricsGrid.tsx` — consume `totals_by_currency[]`, per-currency trendline, fix cross-currency `paidPercent`
- [x] `ClientPerformanceChart.tsx` — per-currency bar scaling
- [x] Per-row call sites: RecentInvoicesTable, OutboundInvoicesTable, NeedsAttentionWidget
- [x] `app/invoices/review/[id]/page.tsx` + `outbound-review/[id]/page.tsx` — local hardcoded formatters + `currency` on the type
- [x] `app/dashboard/page.tsx` — response types
- [x] Full sweep: grep `formatCurrency` / `Intl.NumberFormat` / hardcoded `$` / `toFixed` money renders — found 3 extra sites beyond the brief: `StatusTable.tsx` x2, `SendInvoiceStatusTable.tsx` x1 (all `$${n.toFixed(2)}`); fixed, plus BE `/invoices/status/{id}` now returns `currency` to feed them

## Tests
- [x] `pytest tests/test_dashboard.py tests/test_outbound_dashboard.py tests/test_rag.py` — 48/48 passing (run also covered `tests/test_ingestion.py`, which the duplicate-detection test below lives in)
- [x] duplicate-detection currency-copy test — `tests/test_ingestion.py::test_duplicate_upload_copies_currency_from_original`, passing
- [x] `npx tsc --noEmit` in invoice-fe — clean, exit 0
- [x] e2e mocks: dashboard-outbound-split, group-a-layout-overflow, rbac-sidebar — all three rewritten against the real `totals_by_currency[]` response shape (the flat blended keys they used to mock no longer exist)

## Docs
- [x] be: feature_8_dashboard.md, feature_8.1_vendor_flow_dashboard.md, be_features_tracker.md (Gap 185 entry, cross-refs Gap 183)
- [x] fe: feature_2_dashboard.md, feature_2.1_vendor_flow_dashboard.md, fe_features_tracker.md Gap 183 close-out

---
**Final status (2026-08-11): complete.** Both slices shipped and verified — BE 128/128 suite-wide (48/48 across the four affected suites), FE `tsc --noEmit` clean, e2e 44/44 on a warm re-run (42/44 cold, 2 known dev-server-compile timing flakes recorded on Gap 183). Webhook payloads still omit `currency` — deliberately deferred and tracked as `be_features_tracker.md` Gap 215.
