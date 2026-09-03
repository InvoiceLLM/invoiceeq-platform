# senior-dev — Feature 26 Part 2, task H11 (FE answer-contract rendering)

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_26_chat_attached_documents.md`
§P2.6.4 / §P2.6.5. Predecessor: H10 (Gap 376). Successor: H12 (`useChatSession`
+ proxy routes) — deliberately not touched here.

- [ ] Read H5's real answer-contract shape in `agents/query_agent.py` (not §P2.8's prose)
- [ ] Read `services/document_comparison.py` for the real comparison/suggested-action field names
- [ ] Read H10's `AttachmentMatchConfirm.tsx` props + `lib/chatAttachments.ts`
- [ ] Extend `lib/chatAttachments.ts` with the contract shapes + pure render helpers
- [ ] `types/chat.ts` — optional contract fields on `ChatMessage`, `attachment_id` on `SendMessageRequest`
- [ ] NEW `components/chat/DocumentEvidence.tsx`
- [ ] `components/chat/MessageBubble.tsx` — render the contract
- [ ] `e2e/chat-attachment-contract.spec.ts`
- [ ] `npx tsc --noEmit`
- [ ] `npx playwright test e2e/chat-attachment-contract.spec.ts`
- [ ] Negative control on the two defect-shaped tests
- [ ] FE tracker Gap entry (collision-check fresh)
- [ ] Feature 26 §P2.6.4 Built note + §P2.11 H11 checkbox
