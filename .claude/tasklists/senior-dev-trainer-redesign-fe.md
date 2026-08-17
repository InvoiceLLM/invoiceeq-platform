# senior-dev — Trainer/Chat redesign, FE half (Feature 14)

BE half: `apps/invoice-be/docs/feature_18_trainer_alert_anchored_training.md` (authoritative contract).

## Recon
- [x] Read `.claude/CONVENTIONS.md`
- [x] Read BE feature_18 spec (contract + deviations)
- [x] Read BE `routers/trainer.py`, `routers/chat.py`, `utils/alert_registry.py`, `services/rule_impact.py`, `services/chat_rules.py` for real request/response shapes
- [x] Read FE `app/trainer/page.tsx`, `lib/trainer-service.ts`, all `components/trainer/*`, `components/chat/MessageBubble.tsx`, `hooks/useAuth.ts`, `lib/backendProxy.ts`
- [x] Confirm `/trainer` gates on billing plan only, NOT `canTrain` — CONFIRMED (page.tsx:157-158, 627-637)
- [x] Confirm Chat Response Style already lives under Vendor branch, not Global — CONFIRMED (TrainerControlBar.tsx:149-193); FE Gap 221 entry is stale
- [x] Find the vendor→invoice picker source. BE has no trainer-side list endpoint; `GET /invoices?vendor_name=&limit=` is the real picker (routers/invoices.py:484)

## Service layer
- [x] `lib/trainer-service.ts` — Feature 18 rewrite (from-invoice, upload, alert-types, 4 corrections, preview, commit+token, vendor invoice list); drop global/from-production
- [x] `lib/chat-training-service.ts` — feedback+reason, triage, source-verdict, chat rule categories/preview/commit/list/delete

## Proxy routes (`app/api/**`)
- [x] `trainer/sessions/from-invoice/route.ts`
- [x] `trainer/sessions/[id]/pdf/route.ts` (binary stream, mirrors invoices/[id]/pdf)
- [x] `trainer/alert-types/route.ts`
- [x] `trainer/sessions/[id]/corrections/{tolerance,confidence-threshold,alert-override,missed-alert}/route.ts`
- [x] `trainer/sessions/[id]/preview/route.ts`
- [x] `chat/messages/[messageId]/triage/route.ts` + `triage/source-verdict/route.ts`
- [x] `chat/rules/{route.ts,categories,preview,commit,[ruleId]}`
- [x] DELETE `trainer/sessions/global/route.ts` and `trainer/sessions/from-production/route.ts`

## Components
- [x] `components/trainer/TrainerEntryPanel.tsx` — unified entry (upload PDF | vendor → real invoice picker)
- [x] `components/trainer/AlertListPanel.tsx` — alert list + "Train on this" + "Flag as missed"
- [x] `components/trainer/AlertCorrectionModal.tsx` — unnecessary (tolerance / threshold / excluded) vs severity+message
- [x] `components/trainer/FlagMissedAlertModal.tsx` — registry dropdown + field + optional secondary context
- [x] `components/trainer/CommitModal.tsx` — reworked into the preview-before-commit gate
- [x] `components/trainer/QaChatPanel.tsx` — QA chat, structurally separate, states it creates no extraction rule
- [x] `components/chat/ThumbsDownTriage.tsx` — shared triage modal (reason → invoice pick → diff → PDF verdict → category → preview → confirm)
- [x] `components/chat/MessageBubble.tsx` — FeedbackVote opens the triage flow
- [x] `components/trainer/TrainerControlBar.tsx` — Global section removed
- [x] `app/trainer/page.tsx` — `canTrain` route gate (Gap 115 pattern), new orchestration

## Docs
- [x] New `docs/feature_14_trainer_redesign.md`
- [x] `docs/feature_6_trainer.md` — File Coordinates only
- [x] `docs/fe_features_tracker.md` — Gaps **232-238** + Gap 221 stale-claim correction sentence
  - Coordinator concurrently opened FE Gaps 222-231 on the same file; re-checked the
    real highest number before writing (231) and started at 232. Renumbered the
    in-code `FE Gap 222` references (page.tsx, both trainer specs) to 232 to match.

## Verification
- [x] `npx tsc --noEmit` — clean (exit 0). Had to clear `.next/types` for the two
      deleted proxy routes first; it regenerates.
- [x] Update `e2e/trainer-loading-state.spec.ts` for the removed global/from-production entry points
- [x] New `e2e/trainer-alert-anchored.spec.ts` (5 tests)
- [x] Fix 5 real regressions the rename/removal caused in `group-a-layout-overflow.spec.ts`
      (4 Trainer tests) and `rbac-sidebar.spec.ts` (1)
- [x] **Playwright actually run** — full suite: 63 passed, 1 failed
- [x] Prove the 1 failure is pre-existing — re-ran it with `app/`+`components/`+`lib/`
      stashed; fails identically. It is `/ingestion`'s Gap 86 test, untouched by this work.

---
FINAL STATUS: Complete. `npx tsc --noEmit` exit 0. Playwright WAS runnable in this
environment (contrary to the initial assumption in this file) and was run: 63 passed /
1 failed, with the single failure proven pre-existing and unrelated by a stashed re-run.
Two BE contract gaps found and documented rather than worked around: no trainer-side
per-vendor invoice list (worked around with `GET /invoices?vendor_name=`), and no
session-free `POST /trainer/chat-style` (bad-tone triage links to the Trainer tab
instead of saving inline). Three components orphaned by the redesign were left on
disk and named as a follow-up.
