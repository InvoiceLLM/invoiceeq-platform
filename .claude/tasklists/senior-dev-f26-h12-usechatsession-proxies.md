# senior-dev — Feature 26 Part 2, task H12 (FE §P2.6.6–§P2.6.7)

Wire H10's composer to a real backend: `useChatSession` upload/confirm/reload,
three Next proxy routes, and `app/chat/page.tsx` so the paperclip is reachable.

Do NOT touch: `MessageBubble.tsx`, `DocumentEvidence.tsx` (H11, parallel),
`lib/chatAttachments.ts` and `types/chat.ts` (H11 is editing both), any BE file.

- [x] 1. Read H10's build note (§P2.6.3), `lib/chatAttachments.ts`,
      `hooks/useChatSession.ts`, `app/chat/page.tsx`, the multipart proxy
      precedent (`app/api/invoices/upload/route.ts`), backend router shapes.
      Found: there is NO list-attachments-for-session endpoint (only POST
      upload, POST confirm-matches, GET by id), and no `attachment_id` column on
      the stored message — so both `attachmentCount` and the reload path have to
      be reconstructed client-side. Recorded as a deviation, not papered over.
- [x] 2. Proxy route: `app/api/chat/sessions/[sessionId]/attachments/route.ts` (POST, multipart).
- [x] 3. Proxy route: `app/api/chat/attachments/[attachmentId]/route.ts` (GET).
- [x] 4. Proxy route: `app/api/chat/attachments/[attachmentId]/confirm-matches/route.ts` (POST, JSON).
- [x] 5. `useChatSession`: `uploadAttachment()` via XMLHttpRequest (upload progress),
      `AttachmentState` machine, cancel/abort, remove. Plus an internal `abortUpload()`
      that detaches handlers first, for the session-switch case.
- [x] 6. `useChatSession`: `attachment_id` on `sendMessage`, cleared on send success
      **except** after an `attachment_confirmation` / `attachment_clarification` turn
      (`turnNeedsSameAttachment()`) — taking §P2.6.6 literally would break the D4 gate
      on its second turn. Deviation recorded in the spec and in FE Gap 383.
- [x] 7. `useChatSession`: `confirmMatches(attachmentId, invoiceIds)` — **built, but it
      has no consumer.** `ChatWindow.tsx` L722 still renders
      `<MessageStream messages isSending />` with no `attachmentHandlers` prop, so
      H11's confirmation card and clarification buttons are still dark. Open.
- [x] 8. `useChatSession`: reload/reattach — `refreshAttachment()` re-reads
      `GET /chat/attachments/{id}` on session select, driven by a per-session
      `sessionStorage` pointer memo with `attachmentIdFromTranscript()` as fallback.
      Client-side reconstruction, per item 1's finding — recorded as the deviation.
- [x] 9. `app/chat/page.tsx`: five props passed to `ChatWindow` (the sixth,
      `confirmMatches`, has nowhere to go yet — see item 7).
- [x] 10. e2e: `e2e/chat-attachment-upload.spec.ts` (12 tests, 5 describes, XHR call
      shape asserted); H10's "stays dark until H12" test inverted and annotated in
      place in `e2e/chat-attachment-guards.spec.ts`.
- [ ] 11. `tsc --noEmit` + run both specs; negative control — **NOT DONE. No result is
      recorded anywhere for either.**
- [x] 12. Docs — filed retroactively 2026-09-02 by the Wave 0 doc-reconciliation pass,
      not by this dispatch: `feature_26_chat_attached_documents.md` §P2.11 H12 is `[x]`
      with a Done note, and **FE Gap 383** is filed in `fe_features_tracker.md`
      (collision-checked fresh: repo-wide max was 380; BE 381/382 were filed in the
      same pass).

**Carried forward, still open and BE-side:** `routers/chat.py::MessageResponse` and the
persisted `ChatMessage` row carry **none** of §P2.8's answer-contract keys, so nothing on
that contract reaches the browser from a real backend regardless of what H11 renders or
H12 wires. Unfiled as its own gap — it needs a founder call on persist-vs-transient.

Final status: **code complete, unverified (no `tsc` or Playwright run recorded), gap
filed retroactively as FE Gap 383 (2026-09-02).** Item 11 is outstanding, as is the
`attachmentHandlers` thread from item 7.
