# FE Feature 21: Business Intelligence — intelligence bubble in chat — build
Spec: Prod_Invoice_LLM/apps/invoice-fe/docs/feature_21_business_intelligence.md (§1–§7 as amended by §8; §8 wins; NO pin, NO hold/dispute/paid — information only, BE Gap 492)
BE counterpart (built, pushed 3415840): Prod_Invoice_LLM/apps/invoice-be/docs/feature_30_business_intelligence.md §8–§10; endpoints in routers/chat.py (`GET /chat/insights`, `POST /chat/insights/{id}/transition`, `GET /chat/insights/{id}/discuss`, SSE `insight_update`), `MessageResponse.insights`, `AttachmentOut.insights`
Mockup the founder saw: scratchpad insight_bubble_mockup.html (verdict line; ≤3 findings with amount / confidence chip / evidence links; "Not checked" line; Discuss · Add a note · Dismiss; thumbs)
Approval: founder 2026-09-08 — "Start now in background"
Started: 2026-09-08 17:25
Hard stop: 2026-09-08 21:25 (4 h default)
Definition of done: every task checked or marked not-done with a reason; Vitest per task; Playwright spec with a screenshot in docs/test_evidence/; spec body + fe tracker updated; changes uncommitted.
Status: CLOSED 2026-09-08 19:50 - 6 of 8 tasks done, 1 partial (21.7, blocked by FE Gap 474), 1 not done (21.3, superseded - founder call). Feature marked [~] not [x]: the /done gate's item 2 fails, because the Playwright leg was run against stubs, not against a local backend with ENABLE_ATTACHMENT_INSIGHTS=true as the spec's SS6 asks. Everything uncommitted.

- [x] 21.1 Types (`InsightBlock`, `InsightFinding`, `Insight`, `insights_version`) + `fetchAttachmentInsights`; render-nothing guard when `insights` absent (byte-identical snapshot)
- [x] 21.6 `InsightBubble.tsx` + `InsightActions.tsx` (verdict, ≤3 findings + collapsed rest, confidence chip with reason, evidence links to History, "Not checked" line, Discuss / Add a note / Dismiss, thumbs). No pin, no invoice actions.
- [x] 21.2 (folded into 21.6) skipped/blocked cards collapse with reason
- [~] 21.3 NOT DONE (superseded, founder call needed) — Suggested-question click → composer submit
- [x] 21.8 Discuss → `GET /chat/insights/{id}/discuss` seeds the composer; Add a note / Dismiss → `POST /chat/insights/{id}/transition`; History screen "Open findings" chip fed by `GET /chat/insights?status=OPEN`
- [x] 21.4 Thumbs + `InsightCorrectionDialog` → `POST /chat/messages/{id}/insight-feedback` (check the BE route name in routers/chat.py and use what exists)
- [~] 21.7 (FE half done; cannot fire end-to-end — FE Gap 474) SSE `insight_update` handling → refetch message, redraw bubble in place, ignore stale `insights_version`
- [x] 21.5/21.9 Playwright `e2e/chat-insights.spec.ts`: attach PO → bubble → (mock SSE) update → Add a note → Dismiss; screenshot in docs/test_evidence/

## Log
- 2026-09-08 17:25 tasklist created; senior-dev dispatched in background.
- 2026-09-08 18:19 21.1 DONE. Added a Vitest harness (invoice-fe had none: `vitest.config.mts`, `vitest.setup.ts`, `npm test`, devDeps vitest/@vitejs/plugin-react/@testing-library/react/user-event/jsdom). New `lib/chatInsights.ts` (types + pure render helpers + endpoint calls, verified against routers/chat.py + services/attachment_insights.py, NOT the FE spec), `ChatMessage.insights?` in types/chat.ts, four proxy routes under app/api/chat/**. Three BE-contract deviations found -> FE Gaps 481/482 (filed with 21.6).
  Command: `npx vitest run` -> `Test Files 1 passed (1) / Tests 11 passed (11)`.
- 2026-09-08 18:31 21.6 + 21.2 DONE. `components/chat/InsightBubble.tsx` (verdict, <=3 findings with tabular-nums impact + confidence chip + reason + evidence links, "N more findings" collapse, "Not checked: ..." line), `components/chat/InsightActions.tsx` (Discuss / Add a note / Dismiss from `block.actions` = BE `BUBBLE_ACTIONS`, plus thumbs), `components/chat/InsightCorrectionDialog.tsx`, rendered from `MessageBubble.tsx` behind the existing settled-assistant guard. 21.2's skipped/blocked collapse is the `checks_not_run` line (the BE keeps cards as compute units, not a rendered grid). No pin, no invoice control — asserted by a test. FE Gaps 471/472/473 filed in `docs/fe_features_tracker.md`.
  Command: `npx tsc --noEmit` -> clean (no output). `npx vitest run` -> `Test Files 2 passed (2) / Tests 20 passed (20)`.
- 2026-09-08 18:36 21.3 NOT DONE, deliberately. The BE card DOES exist (`services/attachment_insights.py::card_suggested_questions`, task 30.8, `evidence: {questions: [...]}`), so the data is on the wire. But spec §8.3's bubble anatomy has exactly five parts and suggested questions is not one of them, and the founder-approved mockup has no question chips either — §8 wins over §1-§7 (which is where 21.3 came from). Rendering them would be chrome the founder has not seen. Plumbing them without rendering would be dead code. FOUNDER CALL: add a question-chip row to the bubble, or drop 21.3 from the spec.
- 2026-09-08 18:52 21.8 DONE. Discuss -> `GET /chat/insights/{id}/discuss`, seed goes up through `MessageStream` -> `ChatWindow` (`seedComposer`, `{text, nonce}`) -> `InputBar` which fills and focuses the textarea and NEVER sends. Add a note / Dismiss -> `POST /chat/insights/{id}/transition` with `{status: ACTED|DISMISSED, outcome: note|dismissed}`. History chip: `components/insights/OpenFindingsChip.tsx` mounted on `app/history/page.tsx`, fed by `GET /chat/insights?status=OPEN`; built as a count-that-opens rather than a filter chip because the History screen lists ingestion runs and has nothing finding-shaped to filter (deviation recorded in the spec body + FE Gap 473). No invoice-website proxy change needed — `chat` is already in `feApiPrefixes`.
- 2026-09-08 18:52 21.4 DONE. Bubble thumbs; thumbs-down opens `InsightCorrectionDialog` (4 reasons + optional free text) which writes the vote WITH its reason to `POST /chat/messages/{id}/insight-feedback` — the route name was checked in routers/chat.py (`InsightFeedbackIn`) and matches the spec.
  Command: `npx tsc --noEmit` -> clean. `npx vitest run` -> `Test Files 3 passed (3) / Tests 30 passed (30)`.
- 2026-09-08 19:10 21.7 FE HALF DONE, blocked end-to-end. `hooks/useChatSession.ts` handles `step === "insight_update"` on the attachment extraction stream, re-reads the session, redraws the bubble in place and pulses it for 4s (`updatedInsightMessageIds` -> ChatWindow -> MessageStream -> MessageBubble -> InsightBubble `justUpdated`); stale/replayed versions dropped by `isStaleInsightUpdate()`. It CANNOT fire today: `notify_insight_update()` publishes on the insight job's own job_id, which is minted inside `enqueue_insight_job()` and never returned to the browser — traced through 4 files and filed as FE Gap 474 with two proposed BE fixes. Also caught and fixed a latent bug on the way: without the interception, the generic `data.step` branch would print the literal string "insight_update" as the attachment chip's stage label.
  Command: `npx tsc --noEmit` -> clean. `npx vitest run` -> `Test Files 3 passed (3) / Tests 30 passed (30)`.
- 2026-09-08 19:35 21.5/21.9 DONE. `e2e/chat-insights.spec.ts` — 7 tests, `/api/**` stubbed the way the neighbouring chat specs do it (no BE, no DB, no flag). Covers the anatomy, information-only, note, dismiss, Discuss-seeds-without-sending (asserted by failing if a message POST fires), the async redraw as one bubble, and the no-insights control turn. Screenshots in `docs/test_evidence/fe21_business_intelligence/` (insight-bubble.png, chat-with-insight-bubble.png) — visually checked against the founder's mockup: verdict, 3 findings + amounts right-aligned tabular, confidence chips with reasons, evidence chips, "Not checked", Add a note / Discuss / Dismiss + thumbs.
  Command: `npx playwright test e2e/chat-insights.spec.ts` -> `7 passed (1.0m)`.
  Regression: `npx playwright test e2e/chat-attachment-contract.spec.ts e2e/chat-attachment-guards.spec.ts e2e/chat-async-queue.spec.ts e2e/chat-thread-rename.spec.ts e2e/ingestion-history.spec.ts` -> `41 passed (1.1m)` (MessageBubble / ChatWindow / useChatSession / history page all changed; the "renders exactly as it does today" test is in that set).

## /done gate — 2026-09-08 19:50

| # | check | answer |
|---|---|---|
| 1 | every spec task implemented | **NO.** 21.3 not built (superseded by §8's anatomy — founder call); 21.7 built but inert (FE Gap 474). 21.1, 21.2, 21.4, 21.5/21.9, 21.6, 21.8 done. |
| 2 | every verification-plan item run | **PARTIAL.** 21.1 / 21.2 / 21.4: `npx vitest run` -> `Test Files 3 passed (3) / Tests 30 passed (30)`. 21.3 not run (not built). **21.5 asks for Playwright "against local BE with `ENABLE_ATTACHMENT_INSIGHTS=true`" — NOT DONE; the `7 passed (1.0m)` run is fully stubbed via `page.route()`.** |
| 3 | Postgres, not SQLite | **N/A** — FE only, no DB code touched. |
| 4 | migration applied | **N/A** — no migration in this change. |
| 5 | spec body updated with deviations | **YES** — `docs/feature_21_business_intelligence.md` §9, with §9.3 naming all seven deviations. |
| 6 | tracker marker + gap entries, prefixed | **YES** — Feature 21 row now `[~]`; FE Gaps 471 / 472 / 473 / 474 filed, all written with the `FE Gap` prefix. |
| 7 | test evidence filed | **YES** — `docs/test_evidence/fe21_business_intelligence/` (2 screenshots). Not functional-tester work, so no coverage-map row applies. |
| 8 | uncommitted | **YES** — `git log --oneline -1` still `3415840`; 10 modified + 12 untracked paths in the Changes panel. |

**Verdict: `[~]` code-complete, not verified against a real backend.** Items 1 and 2 failed; deliberately not rounded up to `[x]`.

Incident during close-out, recorded rather than hidden: one shell command's unescaped backticks
executed `npx vitest` from the repo root, which installed a stray root `node_modules/`. It ran
tests only (read-only) and changed no project file; the directory was deleted and the root is
clean. No project code or doc was affected.
- 2026-09-08 evening: founder rulings — action row as built (top finding); 21.3 DROPPED; FE Gap 474 → BE Gap 497 (extraction channel); evidence = plain text (FE Gap 473 closed); commit + push now, live check on dev later. CI failure on 3415840 diagnosed and recovered (Gap 498).
