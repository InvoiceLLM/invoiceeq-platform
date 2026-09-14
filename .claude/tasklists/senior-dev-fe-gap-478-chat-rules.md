# senior-dev — FE Gap 478: Chat Rules panel

- [x] Re-read gap entry + verify proxy/BE shapes (GET /chat/rules, DELETE /chat/rules/{id})
- [x] components/settings/ChatRulesPanel.tsx (presentational, permission-gated delete, empty state)
- [x] app/settings/chat-rules/page.tsx (fetch rules + categories, confirm-delete, error/loading)
- [x] Register tile on app/settings/page.tsx
- [x] tests/unit/chat-rules-panel.test.tsx (property assertions + mutated fixture)
- [x] npx tsc --noEmit
- [x] npm test (vitest run)
- [x] Spec body update (FE feature doc owning chat training)
- [x] Tracker FE Gap 478 marker + evidence


## Follow-up pass — founder decisions, 2026-09-14 (sidebar entry + Settings as the home)

- [x] Sidebar entry `Chat Rules` → `/settings/chat-rules`, `visible: canTrain` (FE Gap 143 pattern, `components/layout/Sidebar.tsx`)
- [x] `e2e/rbac-sidebar.spec.ts`: new `Sidebar — Chat Rules (FE Gap 478)` block (shows for `can_train`, hidden otherwise, href asserted); exact-set cases extended; stale FE Gap 464 `History` expectation repaired
- [x] `npx playwright test e2e/rbac-sidebar.spec.ts` → 22 passed (1.5m)
- [x] `npx tsc --noEmit` → exit 0 · `npm test` → 5 files / 44 tests passed
- [x] `feature_22_today_ask_records.md`: `Records › Rules` links to `/settings/chat-rules`; "closes FE Gap 478" claim removed (§2 table, §3.3, task 22.8, verification 22.8)
- [x] `feature_14_trainer_redesign.md` §11 + File Coordinates: sidebar entry, live-evidence verification block, boundary corrected
- [x] `docs/test_coverage_map.md`: live-run row + e2e row for FE Gap 478
- [x] `/done` gate applied → tracker FE Gap 478 flipped `[~]` → `[x]`

Final status 2026-09-14: **FE Gap 478 closed `[x]`.** Built, unit-verified (tsc exit 0, vitest 44/44), e2e-verified (rbac-sidebar 22/22), and live-verified against real backend + real Postgres + real Azure AI by the functional-tester (`docs/test_evidence/fe_gap478_chat_rules_2026-09-14/README.md`). Everything uncommitted.
