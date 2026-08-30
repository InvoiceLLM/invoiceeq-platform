# senior-dev — FE Feature 17: Plug & Play Setup Wizard + role-vocabulary fix (Gaps 324, 323)

Scope: `apps/invoice-fe` only. BE Feature 25 Gaps 335/336/337 are already built in the
working tree. Do NOT touch `apps/invoice-be` or `apps/invoice-website`.

## Ground-truth reads (before any code)
- [x] Read `.claude/CONVENTIONS.md`, `active-work.md`
- [x] Read `apps/invoice-be/docs/feature_25_plug_and_play_workflows.md` in full
- [x] Read the real endpoint: `apps/invoice-be/routers/settings.py` lines 295–589
      (`GET`/`PUT /api/v1/settings/workflow`) — exact schema, validation, write-through
- [x] Read `models.py::RoleMapper` — `NO_ROLE = "Restricted"`,
      `USER_FACING_ROLES = ("Admin","Auditor","Trainer")`, real permission defaults
- [x] Fresh Gap-number collision check in `fe_features_tracker.md` — max is **322**,
      so 323 and 324 are both free
- [x] Verify website Multi-Zone proxy whitelist (`apps/invoice-website/next.config.js`)
      — `settings` IS already in both `fePages` and `feApiPrefixes`; no website change needed
- [x] Repo-wide grep of `apps/invoice-fe` for the literal `Viewer`

## Docs first (no-code-without-gap)
- [x] Write `apps/invoice-fe/docs/feature_17_plug_and_play_workflows.md`
- [x] File Gap 324 + Gap 323 in `apps/invoice-fe/docs/fe_features_tracker.md` (max was 322)

## Gap 324 — role vocabulary (small, first)
- [x] `app/settings/security/page.tsx` — role matrix rows (drop Viewer + the
      non-existent "Loader" row, correct Auditor's permissions), and the
      `{role || "Viewer"}` display fallback
- [x] `app/help/content/settings-guide.tsx` — 3-role list → Admin/Auditor/Trainer
- [x] `e2e/rbac-sidebar.spec.ts` — 7 `role: "Viewer"` stubs
- [x] `app/settings/page.tsx`, `app/admin/page.tsx` comment vocabulary
- [x] `tests/manual/test_settings_service_flow.md` — NOT edited. Functional-tester-owned,
      following the precedent FE Gap 322 set for exactly this path; flagged in the
      tracker + spec instead.

## Gap 323 — the Setup Wizard
- [x] `app/api/settings/workflow/route.ts` — GET/PUT via `proxyJson`
- [x] `app/settings/workflows/page.tsx` — 4-step wizard
- [x] `app/settings/page.tsx` — add "Workflows" entry to the `INTEGRATIONS` array
- [x] First-run trigger keyed off `completed_at === null`
- [x] Honest treatment of unbuilt options (email_summary / drive_archive / widget)

## Verification
- [x] `npx tsc --noEmit` — clean, exit 0 (run twice: after the build, and after both live-found fixes)
- [x] Live backend reachable? **Yes** — local Postgres was already up on 5433; started
      `uvicorn` + `next dev` for the run and stopped both afterwards. Full click-through
      done in headless Chromium against the real stack, no stubs: first-run banner, all
      4 steps, disabled unbuilt options (unselectable even under a forced click), a real
      200 save, and a **real backend 422** rendered verbatim in the UI with the draft
      intact. Also rendered the Gap 324 surfaces (role matrix, Admin vs Restricted
      Active Role tile) and the non-Admin Access Restricted panel. Probe tenant restored
      to its pre-test state afterwards (verified by query).
- [x] Update spec body + tracker with what actually got built

---
**Final status (2026-08-30): both gaps built and verified live.** `npx tsc --noEmit`
clean. Verified against a real local stack (real `next dev` -> real proxy route ->
real FastAPI -> real Postgres), not just typechecked. **Two real bugs were found by
that run and fixed**: (1) a failed save left the green "Workflow activated" banner
above the red error, claiming both at once; (2) the Security page's Active Role tile
told an Admin they were "Unassigned" while `/auth/me` was still loading. Website
proxy whitelist verified already correct -- no website file touched. Not done and not
claimed: anything against a deployed environment (the Azure dev DB is still three
alembic revisions behind, so this page will 500 there until it is migrated), a
committed automated spec for the wizard, and a run of `e2e/rbac-sidebar.spec.ts`.
