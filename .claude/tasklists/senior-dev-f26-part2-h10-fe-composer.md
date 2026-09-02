# senior-dev — Feature 26 Part 2, task H10 (FE §P2.6.1–P2.6.3)

Scope: composer paperclip + guards in `ChatWindow.tsx`, new `AttachmentChip.tsx`,
new `AttachmentMatchConfirm.tsx`. **Not** H11 (MessageBubble/DocumentEvidence/
types contract rendering) and **not** H12 (useChatSession + proxy routes).

- [x] 1. Read CONVENTIONS + active-work; checked in-flight tasklists — the four
      touched in the last day are BE (F26 H2/H3/H4, F27 G1–G4); no FE overlap
- [x] 2. Read feature_26 §P2.6.1–P2.6.3, §P2.8, §P2.11; ChatWindow.tsx (587 lines,
      as the spec says), DropZone.tsx, types/chat.ts, useChatSession.ts (406)
- [x] 3. Verified the REAL contract shapes — `build_confirmation_payload()` and
      `AttachmentOut`. **§P2.8's sketch is stale**: candidates carry `party_name`
      not `vendor_name`, plus `kind`/`requires_manual_entry`/`flow_direction`,
      and `truncated` only on the populated branch. Tier 3 **not built** (H6)
- [x] 4. Test harness decided — no Jest/RTL/vitest in invoice-fe; Playwright only,
      and its babel transform rewrites JSX so `react-dom/server` in a spec fails
      ("Objects are not valid as a React child"). Spiked both ways to confirm.
      Consequence: pure logic lives in `lib/chatAttachments.ts` and is tested for
      real; component DOM assertions deferred to H11/H12 and stated as uncovered
- [x] 5. `components/chat/AttachmentChip.tsx` — uploading / extracting / ready / failed
- [x] 6. `components/chat/AttachmentMatchConfirm.tsx` — tier label, truncation,
      zero-candidate manual entry, confirm, inline 400
- [x] 7. `ChatWindow.tsx` — paperclip `id="chat-attach-btn"`, hidden input,
      10 MB / `.pdf` / 5-per-session guards, optional props (renders only when
      `onAttach` is supplied, so nothing ships dead before H12)
- [x] 8. Tests — `e2e/chat-attachment-guards.spec.ts`, 13 tests incl. one real
      browser pass over `/chat` and a backend-constant drift check
- [x] 9. `npx tsc --noEmit` exit 0; spec 13 passed; negative control run (25 MB cap
      + render gate removed → exactly the 2 defect-shaped tests failed, restored)
- [x] 10. Fresh collision check (repo-wide max 375) → **Gap 376** filed in
      `fe_features_tracker.md`
- [x] 11. feature_26: H10 ticked with a Built note, "Built" subsection added under
      §P2.6.3, §P2.7 rows added, Part 1's C6 annotated as closed-by-H10

Final status: **complete.** H10 built, tested, documented, left uncommitted.
Known-uncovered and stated in both docs: no DOM assertion or screenshot of the
two new components (no harness reachable; unreachable from any page until
H11/H12), Tier 3 rendering unverified (H6 unbuilt), no end-to-end upload through
the UI. Pre-existing `e2e/chat-async-queue.spec.ts` /
`e2e/chat-thread-rename.spec.ts` failures confirmed to predate this change.
