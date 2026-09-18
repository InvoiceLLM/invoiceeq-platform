# FE Feature 23: The work screen — build
Spec: `Prod_Invoice_LLM/apps/invoice-fe/docs/feature_23_work_screen.md`
BE counterpart: `apps/invoice-be/docs/feature_34_atlas.md` — **owns every contract**
Rulings: `atlas_discussion.md` D34–D46, spec §13 (2026-09-17)
Started: 2026-09-18
Branch: `feature/atlas`
Definition of done: every task below checked; `npx vitest run` and `tsc --noEmit` green and
cited; the screen renders from a **real backend response**, not a fixture; spec body and
`fe_features_tracker.md` updated; changes uncommitted.
Status: delivered 2026-09-18 — uncommitted

## Preflight findings

- **No BE HTTP endpoint exists.** Slice A and B built services (`atlas_skills.py`,
  `atlas_recon.py`, `atlas_doubt.py`) but nothing in `routers/` exposes them — confirmed by
  grep over `routers/` and `main.py`. BE §12 said endpoints are "declared per skill in Slice B";
  they were not. **Filed as BE Gap 691** and built as task 23.0 below, because building the FE
  against a contract no endpoint serves is precisely the F33/F22 defect this spec exists to end
  (`feedback_end_to_end_is_the_only_done`: Feature 33 had 118/118 passing with 10 dead
  capabilities).
- **Nothing in FE Feature 22 was ever built.** No `PrimaryNav`, no `ScenarioControl`, no
  `NEXT_PUBLIC_FOUR_SURFACES`, no `app/today/`, no `components/today/`. So spec §8's "surviving
  code worth keeping" is wrong and **tasks 1 and 10 are no-ops** — there is nothing to delete.
- **The spec contradicts D44.** §3's table still gives `can_audit` only "the cash consequence of
  a decision". The founder ruled on 2026-09-17 that **Auditors see the full cash position,
  forecast and runway**. The spec is amended additively before the line component is built.
- FE toolchain confirmed: `vitest run`, `tsc --noEmit` (FE Gap 639), Next.js app router.

## Blocked on BE Slice C — not started here

- Spec task 4 (collapsed rows for the Admin) needs BE 34.7 — **not built**
- Spec task 7 (forecast lines with levers) needs BE 34.9 — **not built**
- Spec task 9 (cold-start orientation) needs BE 34.12 — **not built**
- Spec task 8 (batch accept) — **ruled NOT BUILT in v1** (D42). No batch control ships at all.

## Tasks

- [x] 23.0 **BE Gap 691** — `routers/atlas.py`: `GET /atlas/lines` returning validated
  `Recommendation`s for the caller's grants, plus the recon attach route 23.6 needs. Registered
  in `main.py`. The FE consumes this; no field is invented on either side
  — **done 2026-09-18.** Gap 691 filed in `be_features_tracker.md` first. `GET /atlas/lines`
  (skills + the §3.3 doubt asks over the audit queue, capped at 50 with the cap reported) and
  `POST /atlas/recon` (34.4's `reconcile()` over an attached statement `Document`). One additive
  service function, `atlas_recon.statement_lines_from_items()`, reads a statement row's invoice
  number out of `GenericLineItem.description` — **refuses rather than guesses** when zero or
  several candidates. `tests/test_atlas_router.py` → **8 passed** on real Postgres; the four
  Slice A/B files + ingestion sources re-run green (**65 passed**), so BE Gap 698 is no longer
  biting on this machine.
- [x] 23.A Amend `feature_23_work_screen.md` additively for D34–D46 — **D44** (Auditor sees the
  full position), D36/D38 (no push, compute on open), D42 (nothing batchable), D45 (Trainer
  before/after), and a note that §8's "surviving code" is wrong. **Never rewrite** the body
- [x] 23.2 The line component — what / why / action / verify (§2), typed off the BE contract
  — `lib/atlas.ts` (types transcribed from BE §12.2/§15.2, nothing invented) +
  `components/atlas/AtlasLine.tsx`. Figures print `Figure.rendered` only; the doubt prints the
  server's words; D45's `Correction` renders as the typed before/after pair; a line missing a part
  renders as a **named defect**, never degraded. `tests/unit/atlas-line.test.tsx` → 15 passed
- [x] 23.3 Capability-filtered rendering and the no-grants empty state (§3)
  — `components/atlas/WorkScreen.tsx` + `app/work/page.tsx` + `app/api/atlas/lines/route.ts`.
  **No capability check exists in the FE**; `ungranted` comes from the server, so "No tasks
  assigned" and "Nothing needs you right now" can never be confused
- [x] 23.5 The verify affordance: chat, on this line, document attached (§2)
  — `/chat?seed=…` seeds the composer through a new optional `ChatWindow.initialSeed`, proven in a
  real browser (composer held the line's own question). **The document is NOT attached**:
  `POST /chat/sessions/{id}/attachments` takes an upload and has no by-id path for a document
  already held. Filed as **FE Gap 640** rather than re-uploading a second copy to fake it
- [x] 23.6 Recon attach and result rendering — four groups (§6), against BE 34.4
  — `components/atlas/ReconPanel.tsx` + `app/api/atlas/recon/route.ts`. The affordance appears
  only because the server sent a line asking for a document. Verified in a real browser against a
  real statement: matched 1 · they show 1 · we show 2 · differs 1 · unreadable 1
- [x] 23.V Verification (below), each invariant cited

## Verification plan (spec §10) — asserted, not assumed

- [x] A no-grants fixture renders **"No tasks assigned"** and **zero** lines — `atlas-work-screen.test.tsx`
- [x] A line whose capability the user lacks is **absent**, not disabled — asserted on both sides:
      `test_atlas_router.py::test_a_line_the_caller_cannot_act_on_is_absent_not_disabled` and the FE test
- [x] **No numeric operator appears in any line component** — grep-shaped over every file in
      `components/atlas/` + `lib/atlas.ts`, comments and strings stripped
      (`atlas-no-client-arithmetic.test.ts`)
- [x] No rendered total spans two currencies — the FE renders no total at all; every money token
      on screen is checked to be one the payload sent, per text node
- [x] An uncertain line is **never** inside a batch control — **vacuous under D42, and stated as
      such**: the test asserts no batch control exists at all (no checkbox in the DOM, no
      select-all/approve-these copy in any source file). The original assertion was not run,
      because there is nothing to run it against
- [x] **No UI path sends more than one outbound message per click** — partly vacuous and said so:
      no action endpoint exists (BE §15.2), so no UI path sends anything. Asserted that opening the
      screen issues one GET and zero writes
- [x] A line missing `why` or `verify` **fails the test** rather than rendering degraded —
      four cases, each asserting the headline does **not** render
- [x] `/invoices/review/:id` and `/trainer` both still render — **checked, not reasoned about**:
      both answered 200 on the running dev server (as did `/chat` and `/dashboard`). Nothing was
      deleted or redirected; task 1 is a no-op
- [x] **End-to-end: the screen renders from a real backend response**, not a fixture — twice:
      `atlas-live-backend.test.tsx` (4 passed against live uvicorn) and a real Chromium browser on
      `/work` via `next dev` → route handler → backend → Postgres: **6 lines, 0 defects, 0 page
      errors**, and the recon flow driven through to its four groups

## Final status

**Done and uncommitted (2026-09-18).** Spec tasks 2, 3, 5 and 6 built on top of a new backend endpoint (BE Gap 691); tasks 1 and 10 are no-ops, task 8 is ruled not built (D42), tasks 4, 7 and 9 need BE Slice C and were left unstubbed. `npx vitest run` → **78 passed / 4 skipped**, `npx tsc --noEmit` → **clean**, ATLAS backend suite → **74 passed** and `test_autopilot.py` → **43 passed** on real Postgres, and the screen rendered **6 real lines with 0 defects in a real browser** against a running invoice-be. Two Gaps filed: **BE Gap 692** (a contract defect the first live call found and 59 backend tests had not) and **FE Gap 640** (Verify seeds the question but cannot attach the document).
