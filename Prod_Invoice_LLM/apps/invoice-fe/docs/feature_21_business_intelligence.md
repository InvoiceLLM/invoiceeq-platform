# Feature 21 — Business Intelligence cards in chat

**App:** invoice-fe · **Status:** lives in `fe_features_tracker.md` · **Counterpart:** BE Feature 30 (`apps/invoice-be/docs/feature_30_business_intelligence.md`)

## 1. Overview

When a user attaches a **non-invoice financial document** (PO, quotation, contract, credit/debit note, statement, remittance, delivery note) in the chat composer (Feature 5 chat, Gap 376 attachment control), the backend posts an assistant turn carrying a temporary **insight block** before any question is asked. Invoices attached in chat get no block. The block expires with the session unless the user pins it. This feature renders that block as cards under the bubble, lets the user click a suggested question, and captures thumbs per card. It is not a new page, not the dashboard, and not the Audit screen.

## 2. File coordinates

| path | named component / function | new or edit | what it does |
|---|---|---|---|
| `types/chat.ts` | `InsightCard`, `InsightBlock`, `ChatMessage.insights?: InsightBlock` | edit | Wire types matching BE `MessageResponse.insights` |
| `lib/chatAttachments.ts` | `ChatAttachmentSummary.insights?`, `fetchAttachmentInsights(id)` | edit | Reload path via `GET /chat/attachments/{id}/insights` |
| `components/chat/InsightCards.tsx` | `InsightCards({ block, onFeedback, onAskSuggested })` | new | Card grid: one card per block entry; `skipped`/`blocked` cards render collapsed with their reason |
| `components/chat/InsightCard.tsx` | `InsightCard`, `CardFigures`, `CardEvidence` | new | Figures table + evidence links (invoice ids → History screen) + thumbs |
| `components/chat/MessageBubble.tsx` | render `message.insights` after the existing attachment surfaces | edit | Fifth render surface on an assistant turn |
| `components/chat/ChatWindow.tsx` | `onAskSuggested(question)` → composer submit | edit | Clicking a suggested question sends it as the next turn |
| `lib/apiClient.ts` | `postInsightFeedback(messageId, card, vote, correction?)` | edit | `POST /chat/messages/{id}/insight-feedback` |
| `components/chat/InsightCorrectionDialog.tsx` | `InsightCorrectionDialog` | new | On thumbs-down: optional free-text correction, sent with the vote |
| `components/chat/InsightCards.tsx` | `PinButton` → `pinInsight(attachmentId)` | new | "Keep this" pins the block (`POST /chat/attachments/{id}/insights/pin`); unpinned blocks expire with the session |
| `e2e/chat-insights.spec.ts` | Playwright | new | Attach a fixture PO → cards appear → click suggested question → thumbs-down → dialog |

## 3. Functionality

1. The attachment upload response (`AttachmentOut`) and the session history (`MessageResponse`) both carry `insights`. `MessageBubble` renders `InsightCards` when present; older turns without it render exactly as today.
2. Card order follows the block. `ok` cards open; `skipped`/`blocked` cards collapse to one line with the reason (from the BE confidence-gaps card).
3. Suggested-question card: three buttons; click submits the text through the composer, so it is an ordinary chat turn.
4. Thumbs on each card call `postInsightFeedback`; thumbs-down opens `InsightCorrectionDialog`. The vote survives reload (stored on the message, same pattern as Gap 54).
5. Dark mode, mobile width and the existing `data-testid` conventions of `MessageBubble` apply.

## 4. Data & schema changes

None in the FE. Types only.

## 5. Tasks

| id | task |
|---|---|
| 21.1 | Types + `fetchAttachmentInsights`; render-nothing guard when `insights` absent |
| 21.2 | `InsightCards` / `InsightCard` with figures, evidence links, collapsed skipped state |
| 21.3 | Suggested-question click → composer submit |
| 21.4 | Card thumbs + `InsightCorrectionDialog` + `postInsightFeedback`; pin button + `pinInsight` |
| 21.5 | Playwright `chat-insights.spec.ts` + screenshot evidence in `docs/test_evidence/` |

## 6. Verification plan

| id | proof |
|---|---|
| 21.1 | Vitest: a message without `insights` renders byte-identical snapshot |
| 21.2 | Vitest: block with one `ok`, one `skipped`, one `blocked` card renders three cards, two collapsed, reasons visible |
| 21.3 | Vitest: click dispatches the composer submit with the question text |
| 21.4 | Vitest: thumbs-down opens the dialog; submit calls `postInsightFeedback` with `vote: "down"` and the text |
| 21.5 | Playwright against local BE with `ENABLE_ATTACHMENT_INSIGHTS=true`; screenshot filed |

## 7. Open decisions

1. Cards inline under the bubble (spec assumes) or in a right-hand panel like `DocumentEvidence`?
2. Show `blocked` cards to end users, or only to admins?
