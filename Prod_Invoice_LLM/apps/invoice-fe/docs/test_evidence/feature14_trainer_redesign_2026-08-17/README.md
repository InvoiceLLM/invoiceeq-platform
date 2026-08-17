# Feature 14 (FE) - Alert-Anchored Trainer & Chat Correction Lane
## Independent functional-tester verification - 2026-08-17

Companion to apps/invoice-be/docs/test_evidence/feature18_trainer_redesign_2026-08-17/,
which has the full live-backend evidence (permission boundary, dual-format regression,
preview math, chat-lane DB isolation, auto-diff triage, QA memory, and the new BE Gap
235 found during this pass). This file covers the FE-only checks.

## Type check

npx tsc --noEmit: exit 0, no output. Matches the developer claim exactly.

## Playwright suite - three runs, escalating isolation

1. Full suite, default settings (fullyParallel true, default worker count), real
   backend at localhost:8000: 49 passed, 15 failed
   (01_full_playwright_parallel_run.log). All 15 failures are page.goto timeouts or
   content-not-found errors consistent with the dev-server JIT-compile race the FE
   developer already documented in trainer-alert-anchored.spec.ts own comments
   (multiple parallel workers hitting next dev first-compile of different routes at
   once). Only one of Feature 14's own new tests appears anywhere in that failure
   list, and it is the pre-existing, out-of-scope Gap 86 ingestion test.

2. Trainer-relevant specs only (trainer-alert-anchored.spec.ts,
   trainer-loading-state.spec.ts, group-a-layout-overflow.spec.ts), --workers=1
   --timeout=60000: 21 passed, 1 failed (02_trainer_specs_single_worker_rerun.log).
   All 5 new trainer-alert-anchored.spec.ts tests pass, including the permission-gate
   test (FE Gap 232) and the not-computable-never-a-fabricated-zero test. Both
   trainer-loading-state.spec.ts tests pass. All group-a-layout-overflow.spec.ts
   Trainer-scoped tests pass (Gap 76, Gap 69, Gap 85). The 1 failure is
   "Gap 86 - Ingestion header row - toggle is absent for a receive-only tenant" -
   confirmed pre-existing and unrelated: git diff --stat against this uncommitted
   changeset shows zero files under app/ingestion or any PageHeader component were
   touched by this work.

3. rbac-sidebar.spec.ts alone, --workers=1 --timeout=60000: 17 passed, 2 failed on
   the first pass (03_rbac_sidebar_single_worker_rerun.log). The 2 failures (a Help
   nav link and the notification-bell count) are both unrelated to Trainer/chat and
   not touched by this changeset. Re-ran the one Feature-14-relevant test in this
   file alone ("Trainer's actions render in the shared header, not a second bar",
   the test the FE developer specifically updated for the renamed commit button) in
   full isolation: passes cleanly (1 passed, ~58s). This is the single rbac-sidebar
   test Feature 14 doc claims it fixed, and it holds.

## Live-backend checks (not stubbed)

Ran a throwaway Playwright script (not committed, deleted after use) against the real
Next dev server (DISABLE_CLERK_AUTH=true) and the real FastAPI backend at
localhost:8000 - no /api/** stubs, exercising backendProxy.ts's real "inbound
Authorization header wins" path with Bearer test_* tokens:

- can_train=false (Bearer test_viewer) navigating to /trainer: renders "Training
  Permission Required", zero trainer-entry-panel elements. Passed.
- Admin identity (Bearer test_<real tenant id>) navigating to /trainer: renders the
  real TrainerEntryPanel, vendor dropdown populated from the real backend. Passed.
- Selecting a real vendor ("Apex Print Solutions") from the dropdown fires a real
  GET /api/invoices?vendor_name=... request (200) and renders the real invoice
  (APS-410093, Jun 5 2026, USD 453.60, AUDIT_REQUIRED) with a real "1 alert" badge -
  see 02_vendor_invoice_picker_real_alert_counts.png. Confirms the FE Gap 234/§3
  contract deviation (GET /api/invoices?vendor_name=X instead of a dedicated trainer
  endpoint) actually works end to end against the real backend, with real alert
  counts, not just in a stubbed spec.

## Code-level confirmations

- app/trainer/page.tsx: canTrain gate reads from useAuth() and returns
  TrainerPermissionPrompt when false, checked after the billing-plan gate - matches
  doc exactly (grep-verified, not just read).
- components/audit/AlertConsole.tsx: zero references to trainer/Trainer/train-on-this
  anywhere in the file - no rule-creation affordance leaked into the Auditor console.
- components/chat/ThumbsDownTriage.tsx: the bad-tone branch renders a real, prominent
  "Adjust response style" link to /trainer?panel=chat-style, and app/trainer/page.tsx
  genuinely reads that query param (searchParams.get("panel") === "chat-style") to
  open the style tab - confirmed this is wired end to end, not a dead link. Same file:
  the pdf_agrees=false redirect target (/trainer?invoice_id=...&field=...&flag_missed=1)
  is also genuinely read by app/trainer/page.tsx to pre-fill the missed-alert flow.

## Verdict for this file

Every FE-side claim in feature_14_trainer_redesign.md's Verification Plan holds under
independent re-run, including against a real, unstubbed backend for the two flows
worth checking live (permission boundary, vendor invoice picker). The only new defect
found during this whole pass is backend-side (BE Gap 235, the missed-alert LLM
drafting call's token budget) - see the BE evidence file for detail. It has direct FE
consequences: the "Flag as missed" modal and the thumbs-down-triage-to-extraction
redirect both terminate at the same broken backend endpoint in this environment, so a
real user clicking either FE affordance today gets a real 502, not the "Couldn't turn
that into a rule right now" toast is at least honestly worded, so this is a usability
gap, not a data-corruption risk.
