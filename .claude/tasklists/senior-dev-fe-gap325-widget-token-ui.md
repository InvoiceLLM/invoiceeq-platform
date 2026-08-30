# senior-dev — FE Gap 325 (widget-token half): Settings → Security widget token UI

Scope: `apps/invoice-fe` only. Widget tokens (BE Gap 341). **No** sandbox-key UI here
(that is anonymous-visitor-facing, being built on `invoice-website` in parallel).
No `invoice-be` / `invoice-website` files touched.

- [x] 1. Read BE ground truth: `routers/settings.py` widget-token endpoints,
      `services/widget_tokens.py`, `routers/widget.py`, `models.py::WidgetToken`.
      **Two findings that changed the plan**: (a) there is no update endpoint, so
      `allowed_origins` is issue-time-only; (b) there is no embeddable JS bundle
      anywhere — `routers/widget.py` serves one JSON route and nothing static.
- [x] 2. Read FE conventions: `app/settings/security/page.tsx`,
      `app/settings/workflows/page.tsx`, `lib/backendProxy.ts`, existing proxy routes.
- [x] 3. Collision-check Gap 325 in `fe_features_tracker.md` — referenced by the Gap 323
      and Gap 326 entries but never filed as its own entry. No duplicate to merge.
      (The `infra-devops-gap325-*` tasklist is a *different* tracker's Gap 325.)
- [x] 4. New proxy routes: `app/api/settings/security/widget-tokens/route.ts` (GET/POST)
      and `.../[tokenId]/route.ts` (DELETE).
- [x] 5. New component `components/settings/WidgetTokenSection.tsx`.
- [x] 6. Wired into `app/settings/security/page.tsx` under the API-key card.
- [x] 7. `app/settings/workflows/page.tsx` widget option **enabled** with a
      `configuredAt` link, plus a live "no token issued yet" advisory note.
- [x] 8. `npx tsc --noEmit` → exit 0, clean.
- [~] 9. Live click-through — **NOT ACHIEVED, and not claimed.** Backend contract
      verified directly against real FastAPI + real local Postgres (200/403/422).
      The Next dev server in this environment will not register **any** route under
      `app/api/**` — a 5-line stock probe route 404s identically to routes that
      shipped and were verified working in a previous session — after an initial
      webpack `ERR_MEMORY_ALLOCATION_FAILED`. Pages resolve; route handlers do not.
      Production `next build` attempted as a second route to a real click-through.
- [x] 10. Update `feature_17_plug_and_play_workflows.md`.
- [x] 11. File FE Gap 325 in `fe_features_tracker.md`; update the Feature 17 index line.

Final status: code complete and typecheck-clean; backend contract verified live;
in-browser click-through blocked by a local Next dev-server fault and explicitly
NOT claimed.
