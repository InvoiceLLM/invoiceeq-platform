# senior-dev — ATLAS D47 / D48 / D49

Branch `feature/atlas`. Founder rulings of 2026-09-18 (`atlas_discussion.md` D47–D49).
Ticked as each item actually completes.

## 0. Read before building
- [x] `.claude/CONVENTIONS.md`
- [x] `atlas_discussion.md` — decisions index + 2026-09-18 update entry
- [x] BE `feature_34_atlas.md` §12–§15
- [x] FE `feature_23_work_screen.md` §11–§12
- [x] `components/layout/Header.tsx` — confirmed: bell + theme toggle + profile, **no tab bar**
- [x] `lib/atlas.ts`, `components/atlas/*`, BE verify-question call sites

## 1. D47 — Verify stops promising what it cannot do (closes FE Gap 640)
- [x] BE: `Verify.question` phrasing says attach-and-compare-in-chat — 7 questions reworded (skills x3, doubt x1, recon x3) + `assert_verify_does_not_promise_attachment()` in `atlas_contract.py`, wired into `validate_recommendation()`. `tests/test_atlas_contract.py` → **36 passed** on real Postgres
- [x] FE: Verify affordance wording matches — `VERIFY_ATTACH_HINT` in `lib/atlas.ts`, rendered by `AtlasLine` when the line names a document
- [x] FE tests: `tests/unit/atlas-d47-d49.test.tsx` — 12 tests (3 D47, 6 D48, 3 D49)
- [x] FE Gap 640 closed `[x]` in `fe_features_tracker.md` — D47 named as the resolution, by-id attachment path recorded as **deliberately not built**
- [x] Specs updated additively (BE Feature 34 **§16**, FE Feature 23 **§13**) — bodies untouched

## 2. D48 — ATLAS / traditional toggle beside the bell
- [x] `hooks/useAtlasMode.ts` — localStorage only, no backend
- [x] `components/layout/AtlasModeToggle.tsx` + rendered in `Header.tsx` immediately before the theme switch
- [x] Existing screens untouched; ATLAS mode → `/work`, classic → `/dashboard` only when standing on `/work`
- [x] Unit test for the toggle — covered in `atlas-d47-d49.test.tsx`
- [x] **FE Gap 694** filed and closed + FE §13.3

## 3. D49 — dismiss on every line, persisted
- [x] BE model `AtlasDismissal` (tenant + user + recommendation id), unique on all three
- [x] One add-only migration `b2c3d45e14f6_atlas_dismissals.py`, `alembic upgrade head` run once — a1b2c34d13e5 → b2c3d45e14f6
- [x] `POST /atlas/lines/{recommendation_id}/dismiss` + `services/atlas_dismissals.py`
- [x] `GET /atlas/lines` filters dismissed **server-side, before the response is assembled** — skills path AND doubt path, plus `POST /atlas/recon`'s lines. Drops, never flags
- [x] BE tests (real Postgres): `tests/test_atlas_dismissals.py` 7 tests; all ATLAS BE files → **85 passed**
- [x] FE dismiss control on every line (`AtlasLine`) + `app/api/atlas/lines/[id]/dismiss/route.ts`; WorkScreen posts then **re-reads**, never hides locally
- [x] FE tests — see above
- [x] **BE Gap 695** + **FE Gap 696** filed and closed; `atlas_discussion.md` index marks D47–D49 built

## 4. Proof and close-out
- [x] BE narrow tests green on real Postgres (127.0.0.1:5433) — **85 passed** across the 7 ATLAS files
- [x] **Live end-to-end: dismissed a skill line AND a doubt line against uvicorn on 127.0.0.1:8077 → both absent from the raw JSON on re-fetch, and still absent after a full backend restart**
- [x] `npx tsc --noEmit` clean
- [x] Full FE suite — **90 passed / 4 skipped** (78→90, +12 new); live-backend file 4 passed against 8077
- [x] Uncommitted — `git log -1` still `a603ec3`; everything sits in the Changes panel

**Status: complete.** D47, D48, D49 built on `feature/atlas`, uncommitted.
BE 128 passed (7 ATLAS files + `test_autopilot.py`) on real Postgres · FE 90 passed / 4 skipped · `tsc` clean.
Live proof: a skill line and a doubt line dismissed with `curl` against uvicorn on 127.0.0.1:8077 →
both absent from the raw JSON on a full recompute, and still absent after the backend was restarted.
Seeded rows removed; backend stopped.
