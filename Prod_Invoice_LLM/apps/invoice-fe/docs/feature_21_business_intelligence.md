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

---

## 8. Amendment — intelligence bubble, founder 2026-09-07 (evening)

Matches BE Feature 30 §8. Where this and §1–§7 disagree, this wins.

- **No pin.** `PinButton` / `pinInsight` are dropped (BE R1/R7). Durability is the BE insight lifecycle; the bubble scrolls like any message.
- **Bubble shape** (`InsightBubble.tsx` replaces `InsightCards.tsx`): verdict line; up to 3 findings (currency impact, confidence chip with reason, evidence links to document fields and invoice rows in History); "checks not run" collapsed list; action row.
- **Actions** (`InsightActions.tsx`) — **information only (BE Gap 492, founder 2026-09-08): no control on the bubble changes an invoice; the user acts offline.** Add note (inline, `POST /insights/{id}/transition` with `outcome: note`); **Discuss** → seeds the composer with the finding text as a quoted prefix and focuses it; Dismiss. Thumbs-down still opens `InsightCorrectionDialog`.
- **Two-stage rendering.** The sync bubble renders from the upload response. The chat SSE stream gains an `insight_update` event `{message_id, attachment_id, insights_version}`; `ChatWindow` refetches that message and redraws the bubble in place with a brief "updated" pulse. A stale `insights_version` is ignored.
- **Persona.** Plain-verb copy, tenant currency formatting via the existing `formatMoney`; no internal terms (tier, delta, 3-way) in any string.
- **Dashboard.** None in-app (Workbook rule); the History screen gets an "Open findings" filter chip fed by `GET /insights?status=OPEN`.

| id | task |
|---|---|
| 21.6 | `InsightBubble` + `InsightActions`; remove `PinButton`; types for `Insight`, `insights_version` |
| 21.7 | SSE `insight_update` handling + in-place redraw |
| 21.8 | Discuss seed into composer; transition calls; History "Open findings" chip |
| 21.9 | Playwright: attach PO → sync bubble → (mock SSE) update → Hold → History row shows the status |

---

## 9. Build note — 2026-09-08 (what was actually built)

Built against the live backend (`routers/chat.py`, `routers/chat_attachments.py`,
`services/attachment_insights.py`, `services/insights.py`,
`queue_worker/handlers.py`), not against §2's table — which turned out to be stale
in four places. §8 governs the rendered shape; §1–§7's card grid was not built.

### 9.1 Named components and functions

| path | named export | what it does |
|---|---|---|
| `lib/chatInsights.ts` | `InsightBlock`, `InsightFinding`, `InsightCardResult`, `InsightCheckNotRun`, `InsightAction`, `Insight`, `InsightUpdateEvent` | The wire shapes, mirrored from `build_insight_block()`, `finding()`, `InsightCard.as_dict()`, `BUBBLE_ACTIONS` and `InsightOut` |
| `lib/chatInsights.ts` | `hasRenderableInsights()`, `splitFindings()`, `confidenceLabel()`, `confidenceTone()`, `findingImpact()`, `cardLabel()`, `checksNotRunLine()`, `evidenceInvoiceNumbers()`, `insightForFinding()`, `isStaleInsightUpdate()` | Every render decision, as pure functions a test can call without a DOM |
| `lib/chatInsights.ts` | `fetchAttachmentInsights()`, `fetchOpenInsights()`, `transitionInsight()`, `fetchInsightDiscussSeed()`, `postInsightFeedback()` | The five calls. None of them touches an invoice |
| `components/chat/InsightBubble.tsx` | `InsightBubble`, `ConfidenceChip`, `FindingRow` | The §8.3 anatomy: verdict, ≤3 findings, collapsed rest, "Not checked" line, action row |
| `components/chat/InsightActions.tsx` | `InsightActions`, `outcomeLine()` | Discuss · Add a note · Dismiss (rendered from `block.actions`, i.e. the BE's own `BUBBLE_ACTIONS`) + thumbs |
| `components/chat/InsightCorrectionDialog.tsx` | `InsightCorrectionDialog` | Thumbs-down: 4 reasons + optional corrected text, sent with the vote |
| `components/insights/OpenFindingsChip.tsx` | `OpenFindingsChip` | The History screen's open-findings count and list |
| `components/chat/MessageBubble.tsx` | `MessageBubble`, `MessageStream` | New render surface behind `isSettledAssistant && message.insights`; `onInsightDiscuss` / `updatedInsightMessageIds` threaded through |
| `components/chat/ChatWindow.tsx` | `ChatWindow`, `InputBar` | `seedComposer()` → `InputBar`'s `seed={text, nonce}` effect: fills and focuses, never sends |
| `hooks/useChatSession.ts` | `applyInsightUpdate()`, `insightVersionsRef`, `updatedInsightMessageIds` | The `insight_update` handler and its staleness guard |
| `types/chat.ts` | `ChatMessage.insights?` | Optional, so a turn without it is unchanged |
| `app/api/chat/insights/**`, `app/api/chat/messages/[messageId]/insight-feedback` | `GET`, `POST` | Four same-origin proxies. No invoice-website change needed — `chat` is already in `feApiPrefixes` |
| `tests/unit/*.test.tsx`, `e2e/chat-insights.spec.ts` | — | 30 Vitest + 7 Playwright, screenshots in `docs/test_evidence/fe21_business_intelligence/` |

`vitest.config.mts` / `vitest.setup.ts` / `npm test` were added with this feature:
invoice-fe had no unit harness at all, and §6's 21.1 proof ("renders
byte-identical") cannot be made by a Playwright spec, whose babel transform
rewrites JSX in any `.tsx` it imports.

### 9.2 Functionality as built

1. The block arrives on `MessageResponse.insights` and renders under the
   assistant turn that follows the attachment. A turn without the key takes no
   new branch — proved by rendering the same message twice and comparing the
   HTML, not by a snapshot file that would go green on unrelated edits.
2. Findings: at most 3, each with its currency impact right-aligned in
   `tabular-nums` (via the existing `formatCurrency`, tenant currency), a
   plain-word confidence chip carrying its reason ("Sure" / "Fairly sure" / "Not
   sure" — never "med"), and one evidence link per invoice number. The rest
   collapse behind "N more findings". A finding with no amount shows no amount,
   not a zero.
3. §8.3.3 is one line — "Not checked: bank match (no bank statement on file); …" —
   built from `block.checks_not_run`. **This is where task 21.2's "skipped/blocked
   cards collapse with their reason" went.** `block.cards[]` is deliberately not
   drawn one-per-card: the BE kept cards as compute units, and their findings are
   already flattened and ranked into `block.findings`.
4. **Information only (BE Gap 492).** No pin, no hold/dispute/paid, nothing that
   changes an invoice. Add a note → `POST /chat/insights/{id}/transition`
   `{status: "ACTED", outcome: "note", note}`; Dismiss → `{status: "DISMISSED",
   outcome: "dismissed"}`; Discuss → `GET /chat/insights/{id}/discuss`, a read
   whose text seeds and focuses the composer and is never sent. Both a unit test
   and a Playwright test fail if a send fires, and one asserts the bubble's text
   contains none of "pin / keep this / hold / dispute / mark paid / tier / delta".
5. A finding the user already closed renders as "You dismissed this finding."
   rather than offering the buttons again after a reload.

### 9.3 Deviations from §1–§8, each with its reason

- **No `AttachmentOut.insights`, no `GET /chat/attachments/{id}/insights`.** Neither
  exists in the backend; §2's row would never have been populated. The block comes
  on the message; the lifecycle rows come from `GET /chat/insights?attachment_id=…`.
  **FE Gap 471.**
- **The bubble makes an extra read to get an id.** A finding carries `finding_key`,
  not the `insight` row id the transition endpoint needs, so `InsightBubble` fetches
  the rows on mount and joins on `finding_key` + `card`. The two write actions stay
  disabled until it resolves. **FE Gap 472.**
- **Evidence links land on an unfiltered History screen.** The link is
  `/history?invoice=<number>`; the History screen lists ingestion runs and has no
  invoice-number filter, so the parameter is currently ignored. **FE Gap 473.**
- **The "Open findings" filter chip is a count-that-opens, not a filter.** Same
  reason: there is nothing finding-shaped in that table to filter. It renders
  nothing when there is nothing open, which is also the flag-off shape.
- **The action row acts on the top-ranked finding** — the one the verdict line is
  written from. §8.3 puts one action row at the bottom of the bubble and the
  founder's mockup shows one row, but every endpoint is per-finding. **Open: the
  founder should confirm this reading, or ask for a row per finding.**
- **Task 21.3 (suggested-question click) was not built.** The BE card exists
  (`card_suggested_questions`, task 30.8), but §8.3's anatomy has five parts and
  question chips are not one of them, and the approved mockup has none. **Open:
  add a chip row, or drop 21.3.**
- **Task 21.7's SSE leg is built but cannot fire.** `notify_insight_update()`
  publishes on the insight job's own id, which is minted inside
  `enqueue_insight_job()` and never returned to the browser. The FE handler,
  in-place redraw, pulse and staleness guard are all in place and inert.
  **FE Gap 474**, with two proposed BE fixes.

### 9.4 Verification

- `npx tsc --noEmit` → clean.
- `npm test` (`npx vitest run`) → **Test Files 3 passed (3), Tests 30 passed (30)**.
- `npx playwright test e2e/chat-insights.spec.ts` → **7 passed**; screenshots filed
  under `docs/test_evidence/fe21_business_intelligence/`.
- Regression over the five specs touching the changed files
  (`chat-attachment-contract`, `chat-attachment-guards`, `chat-async-queue`,
  `chat-thread-rename`, `ingestion-history`) → **41 passed**.
- Not verified: anything against a real backend with `ENABLE_ATTACHMENT_INSIGHTS=true`
  — §6's 21.5 asks for it, and it was not run. Every proof above is stubbed.

### 8.1 Rulings on the build's open items — founder 2026-09-08 evening

| item | ruling |
|---|---|
| Action row | **One row per bubble, acting on the top-ranked finding** (as built). Other findings are handled from the History "Open findings" count. |
| Suggested-question chips (21.3) | **Dropped.** The BE card stays; nothing renders it. |
| Live second-pass update (FE Gap 474) | BE fix chosen: **publish on the extraction job's channel** — BE Gap 497; the FE half already listens for `insight_update` on that stream. |
| Evidence links (FE Gap 473) | **Plain text, no link.** `insight-evidence` spans replace the `insight-evidence-link` anchors; the `/history?invoice=` parameter is gone. |
| Live check | **Commit and push now, verify on dev later.** |
