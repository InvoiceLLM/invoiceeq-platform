# senior-dev — first-login slow data load diagnosis (BE Gap 279)

Symptom: dashboard/invoice list slow on first load after fresh login, fast on repeat navigation in same session.
Ruled out by infra-devops: cold start/scaling, Chroma/bge-m3 lazy load, Clerk JWKS, FE proxy chain.

- [x] 1. Read `apps/invoice-fe/app/dashboard/page.tsx` — fetches are 4 independent `useEffect`s, NOT a waterfall between themselves
- [x] 2. Client-side cache: no React Query/SWR anywhere. Only cache is `hooks/useAuth.ts`'s module-level `cached` var
- [x] 3. Read `apps/invoice-fe/app/invoices/page.tsx` — same shape; fires 2x `/invoices` on mount (limit=100 for dropdowns + limit=8 for table)
- [x] 4. Traced BE endpoints — found `routers/dashboard.py::get_dashboard_insights` does a synchronous LLM call
- [x] 5. `database.py` engine is eager at import, `pool_size=10/max_overflow=10` — pool cold start NOT the cause
- [x] 6. No missing index / N+1 / full-scan problem found; `/dashboard/metrics` is real SQL aggregates, p50 615ms
- [x] 7. Auth path: `/auth/me` p50 242ms / p95 512ms, serialized before page data via the `authLoading` gate — real but minor
- [x] 8. **ROOT CAUSE CONFIRMED with live Log Analytics evidence** (App Insights itself has zero telemetry — `APPLICATIONINSIGHTS_CONNECTION_STRING` unset — but `TracingAndLoggingMiddleware` logs `duration_ms` per request to stdout → `ContainerAppConsoleLogs_CL`)
- [x] 9. Fix implemented: `get_dashboard_insights` `async def` → `def` (one keyword)
- [x] 10. Verified: `uv run --frozen pytest tests/test_dashboard.py -q` → **11 passed** (219.95s)
- [x] 11. Updated `docs/feature_8_dashboard.md` body + `docs/be_features_tracker.md` Gap 279 (placeholder replaced)

## Root cause

`GET /api/v1/dashboard/insights` was declared `async def` but its body is entirely
blocking sync I/O — redis-py get/set, `db_session.exec()`, and
`structured_llm.invoke()` (synchronous Azure OpenAI), with **no `await` anywhere**.
Starlette therefore ran it directly on the uvicorn event loop, so a 13–19.5s
cache-miss LLM call froze the whole worker and every concurrent request stalled
behind it.

The dashboard's default tab is `"insights"`, so `ActionableInsightsPanel` fires this
call on every dashboard mount. Redis cache is keyed per tenant with a 1h TTL:
first login of the hour = miss = 13–19.5s event-loop freeze = *the entire page's*
data (metrics, invoice list, outbound) is slow. Repeat navigation = cache hit
(~0.5s) = no freeze = fast. Exactly the reported symptom.

Live proof, 2026-08-19T07:20:30Z — five requests dispatched ~07:20:13 all completed
within 200ms of each other:
| endpoint | duration |
|---|---|
| /api/v1/dashboard/insights | 16781ms |
| /api/v1/invoices | 16750ms |
| /api/v1/invoices | 16945ms |
| /api/v1/invoices | 16956ms |
| /api/v1/outbound-dashboard/invoices | 16937ms |

/invoices returned to 282ms one second later. Insights duration distribution is
cleanly bimodal: misses 13441/14372/16782/17163/18599/19499ms vs hits 478–902ms.

Status: COMPLETE — root cause confirmed from live telemetry, fix implemented and test-verified.
Follow-ups left unimplemented deliberately (out of approved scope), reported to coordinator:
`get_dashboard_metrics`/`get_trainer_impact` are the same `async def`-with-blocking-sync-DB
pattern (smaller impact, ~0.6–1.1s each); the `useAuth` gate serializes `/auth/me` before
page data on first load only.
