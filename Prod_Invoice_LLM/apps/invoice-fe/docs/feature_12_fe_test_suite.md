# Frontend Feature 12: Automated FE Test Suite

## Overview
**Correction, 2026-08-01**: this doc's premise ("frontend has none") is now stale. Since it was written, real Playwright coverage was added ad hoc as individual gap fixes landed — `apps/invoice-fe/e2e/dashboard-outbound-split.spec.ts` (7 tests, Gap 89) and `e2e/group-a-layout-overflow.spec.ts` (15 tests, the Gap 76 regression guard cited elsewhere in this repo). Both are real, checked-in, CI-unwired for now. What's described below (`tests/e2e/`, `playwright.config.ts`, FE-E2E-1 through FE-E2E-10) is a **separate, more structured suite that was never built** — the two aren't the same thing, and a reader of just this doc would wrongly conclude zero E2E coverage exists at all. Treat this doc's own scope as still fully open; the `e2e/` directory's existing specs are tracked via `fe_features_tracker.md` Gap 89, not here.

The backend has real automated coverage (`invoice-be/docs/feature_13_test_benchmark_suite.md`: a fixture regression tier plus a daily procedural benchmark, 130+ pytest tests). Every one of `fe_features_tracker.md`'s "Live Testing Gaps (2026-07-29)" entries (Gaps 68-89: clipped buttons, dead click handlers, redundant tabs, stuck processing states, a screen that never renders past a loading spinner) is exactly the class of regression this kind of suite exists to catch automatically, before a human has to click through every screen by hand to find them.

Tooling proven usable tonight: Playwright (`chromium` headless already installed locally, driven via both the CLI and a Node script against the real dev server). No new tool evaluation needed — use what's already proven.

## Scope decision
Start with **one tier**: real-browser E2E smoke tests against a running dev server (FE :3000 + BE :8000 + real Postgres/Redis/Azurite, same local stack used all session), not component-level unit tests. Reasoning: nearly every bug found tonight was a *layout/integration* bug (clipping, wrong button for the wrong invoice type, a proxy chain silently breaking) — the kind that only shows up when the real DOM renders against real data, not in an isolated component render. Component-level tests (React Testing Library) can be added later for pure-logic pieces (e.g. `EditableField`'s edit-toggle logic) but shouldn't be the first investment.

## File Coordinates (planned)
* `apps/invoice-fe/tests/e2e/` — new directory, mirrors `invoice-be/tests/e2e/`'s naming.
* `apps/invoice-fe/tests/e2e/fixtures.ts` — shared helpers: launch browser, seed a known invoice via the real BE API (reuses `invoice-be/tests/benchmark/generator.py`-produced PDFs or a small fixed set checked into the repo), tenant/mock-auth bypass (already zero-login in local dev).
* `apps/invoice-fe/tests/e2e/dashboard.spec.ts`
* `apps/invoice-fe/tests/e2e/ingestion.spec.ts`
* `apps/invoice-fe/tests/e2e/audit-review.spec.ts`
* `apps/invoice-fe/tests/e2e/trainer.spec.ts`
* `apps/invoice-fe/playwright.config.ts` — base URL `http://localhost:3000`, single `chromium` project to start (matches what's already installed).
* `package.json`: add `playwright` as a real devDependency (installed ad-hoc into a scratch directory tonight, not yet added to this project) plus a `test:e2e` script.

## Test Case Registry — mapped directly to tonight's real findings
*(Each case is a regression guard for a specific gap found this session — not hypothetical coverage.)*

| ID | Test case | Guards against | Assertion |
|---|---|---|---|
| FE-E2E-1 | Upload one inbound PDF, poll until terminal status | Gap 84 (stuck PROCESSING) | Status reaches `COMPLETED`/`AUDIT_REQUIRED` within a bounded timeout, not left at `PROCESSING` |
| FE-E2E-2 | Upload one outbound PDF, poll until terminal status | Gap 81 (stuck at `UPLOADED`), Gap 84 | Status reaches `VERIFIED`/`NEEDS_REVIEW` within a bounded timeout |
| FE-E2E-3 | Open Audit Review for an `AUDIT_REQUIRED` inbound invoice | Gap 71 (double Shell) | Exactly one Sidebar and one Header render (`page.locator('nav').count() === 1`) |
| FE-E2E-4 | Same page, scroll to bottom | Gap 76 (clipped Commit button, same pattern as the fixed Gap-71-adjacent `min-h-0` bug) | "Mark Paid & Finalize"/"Reject Invoice" bounding box is within the viewport, not partially off-screen |
| FE-E2E-5 | Open Audit Review for an **outbound** invoice | Gap 74 (wrong action buttons for outbound) | Page shows "Send"/"Mark Paid", never "Reject Invoice" |
| FE-E2E-6 | Open Audit Review for an invoice with `sa_alerts: []` but `status: AUDIT_REQUIRED` | Gap 75 (unexplained empty state) | An explanatory message renders, not a bare status pill with nothing under it |
| FE-E2E-7 | Click a correctable field on the Audit Review screen | Gap 82 (click-to-correct does nothing) | Field becomes editable (input loses `readOnly`) and accepts a keystroke |
| FE-E2E-8 | Load the PDF viewer on Audit Review | Gap 72 (PDF blank/broken/half-displayed) | `iframe` element is present with a `src` matching the invoice's PDF proxy route, and the proxy response has `content-type: application/pdf` (network-level check, not just DOM presence — a real-browser-only rendering bug like the PDF plugin question can't be asserted via headless DOM alone, but the proxy chain integrity can) |
| FE-E2E-9 | Load Dashboard at 1280×720 | Gap 68 (regression guard now that it's fixed) | Full page height (`document.querySelector('main').scrollHeight`) fits within the viewport with no overflow |
| FE-E2E-10 | Load Trainer screen, submit a chat correction, commit | Gap 76, Gap 78 | "Commit to Template Registry" is clickable and visible without scrolling |

## Verification Plan
* **CI**: new `workflow_dispatch`-triggered GitHub Actions job (mirrors `invoice-be`'s `e2e-regression.yml` pattern) — spins up the same docker-compose stack, runs `next build && next start` (or `next dev` for speed), then `npx playwright test`.
* **Local**: `npm run test:e2e` against the already-running dev server, same pattern as tonight's manual Playwright CLI usage.
* **First milestone**: get FE-E2E-1 through FE-E2E-10 passing against current `master` *after* Gaps 71-89's fixes land — these tests should fail against tonight's pre-fix code (a good sanity check that they're actually testing the right thing) and pass after.

## Task Breakdown
- [ ] Task 12.1: Add `playwright` as a real devDependency + `playwright.config.ts` + `test:e2e` script.
- [ ] Task 12.2: Build `tests/e2e/fixtures.ts` shared helpers (seed invoice via real API, poll-until-status helper).
- [ ] Task 12.3: Write FE-E2E-1 through FE-E2E-10.
- [ ] Task 12.4: Wire into CI (`workflow_dispatch`, mirrors `e2e-regression.yml`).
- [ ] Task 12.5: Run once against pre-fix code to confirm each test actually fails on the bug it's meant to catch, then again after fixes land to confirm they pass.
