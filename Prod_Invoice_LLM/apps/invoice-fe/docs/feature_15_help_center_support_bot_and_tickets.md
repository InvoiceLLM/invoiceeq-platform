# Feature 15: Help Center Knowledge Base & AI Support Assistant with Direct Ticket Escalation

**Status:** Built 2026-08-17 (commit `fc48ef0`) — all 5 tasks landed, with two deviations from this spec recorded in §4. Status/verification state lives in `fe_features_tracker.md` (Gaps 246/247/248); this doc is the design record.  
**Target Application:** `invoice-fe`  
**Related Backend Spec:** `apps/invoice-be/docs/feature_19_support_tickets_and_notifications.md`  
**Primary Notification Inbox:** `Application@infinevocloud.com`

---

## 1. Overview & Objective

Upgrade the Help Center (`/help`) into a dual-mode support and troubleshooting hub:
1. **Knowledge Base Guides (Default View)**: Opens on first load with 11 complete, illustrated platform guides containing actual application screenshots (AI Trainer sandbox, Auditor review, Inbound email ingestion, Outbound AR audit, and Webhooks).
2. **AI Support Assistant ("SAGE Bot")**: Conversational assistant powered by platform documentation. When the bot cannot answer or detects a backend error, it automatically presents a 1-click **`[ 🎫 Raise Support Ticket ]`** card.
3. **Direct Ticket Escalation**: A single dedicated **`[ 🎫 Raise Ticket Directly ]`** action button inside the chat header allowing users to submit tickets at any time.

---

## 2. File Coordinates

* **Main Page Route (rewritten by this feature):** `apps/invoice-fe/app/help/page.tsx` — `HelpPage` client component. Holds `activeTab` (`"guides" | "assistant"`, initialised to `"guides"` so the Knowledge Base is the landing view), `query` for the `#help-guide-search` filter, and `activeId` for the selected guide. Composes the five guide registries into one `HELP_SECTIONS` array and filters it on each section's `searchText`.
* **AI Support Chatbot Component (new):** `apps/invoice-fe/components/help/SupportChatWindow.tsx` — `SupportChatWindow`. Renders the SAGE conversation, prompt chips, the inline escalation card, the neutral low-confidence card (FE Gap 243 / BE Gap 254 — `#low-confidence-card`), and the `[ 🎫 Raise Ticket Directly ]` header button; posts to `/api/support/chat` and opens `SupportTicketModal` with pre-filled context.
* **Support Ticket Modal (new):** `apps/invoice-fe/components/help/SupportTicketModal.tsx` — `SupportTicketModal`. Validated ticket form, priority pills, pre-fill from an escalation context or the conversation transcript, animated success state showing the returned `TICK-YYYY-XXXX`.
* **Guide Content Registry (pre-existing, not touched by this feature):** `apps/invoice-fe/app/help/content/{trainer,auditor,webhooks,inbound-email,outbound-email}-guide.tsx`, exporting `HELP_SECTIONS`, `AUDITOR_HELP_SECTIONS`, `WEBHOOKS_HELP_SECTIONS`, `INBOUND_EMAIL_HELP_SECTIONS`, `OUTBOUND_EMAIL_HELP_SECTIONS` — 15 sections total. Screenshots live in `apps/invoice-fe/public/help/{trainer,auditor}/`, also pre-existing.
* **API Proxy Routes (new):** `apps/invoice-fe/app/api/support/ticket/route.ts`, `apps/invoice-fe/app/api/support/chat/route.ts` — each a single `POST` handler delegating to `proxyJson()` in the pre-existing `apps/invoice-fe/lib/backendProxy.ts`, which is what attaches the Clerk session token.

---

## 3. Functionality & User Flows

1. **Default Knowledge Base View on `/help`**:
   - Opens immediately on page load with real-time search filter over guide titles, keywords, and text.
   - Left topic sidebar organized by *AI Trainer & Extraction*, *Auditor Review Console*, and *Integrations & Delivery*.
   - Right article pane displaying rich text, callouts, code snippets, and embedded screenshots from `/help/trainer/` and `/help/auditor/`.
2. **AI Support Assistant Tab (`Ask SAGE`)**:
   - Conversational assistant with quick prompt chips.
   - Streams answers using platform RAG context.
   - **Smart Fallback & Ticket Suggestion**: When confidence is low or when an error is diagnosed (e.g. ERP batch sync timeout), renders an inline escalation box with a 1-click **`[ 🎫 Raise Support Ticket from this Issue ]`** button.
3. **Single Dedicated Direct Ticket Button**:
   - Situated in the chat screen header: `[ 🎫 Raise Ticket Directly ]`.
4. **Support Ticket Creation Modal**:
   - Opens pre-populated with Subject, Category, Priority, and Conversation Transcript when triggered from the bot.
   - Opens clean when triggered directly.
   - Submits payload to `POST /api/support/ticket`, generates ticket number (`TICK-2026-XXXX`), and triggers email dispatch to `Application@infinevocloud.com`.

---

## 4. Tasks

- [x] **Task 15.1: Redesign `/help/page.tsx` with Tabs** — Done 2026-08-17. Two-tab switcher, Knowledge Base default on load, plus the `#help-guide-search` filter. **Scope correction:** §1 and this doc's original wording implied the illustrated guides and their screenshots were part of this work. They were not — `app/help/content/*.tsx` and `public/help/{trainer,auditor}/` already existed at the merge base and are untouched by this commit, which only rewrote `page.tsx`. The real section count is **15**, not the 11 claimed in §1.
- [x] **Task 15.2: Build `SupportChatWindow.tsx`** — Done 2026-08-17. Conversation view, prompt chips, Markdown rendering, inline escalation card, and the direct-ticket header button. **Deviation:** it does **not** stream. §3.2's "streams answers using platform RAG context" was never built — the component makes one plain `fetch("/api/support/chat", { method: "POST" })` per turn and renders the whole reply at once, and the backend behind it (`agents/support_agent.py`) is a deterministic keyword/regex matcher over a hardcoded knowledge base, not a RAG pipeline. There is likewise no confidence score: escalation is triggered by an error-pattern match or an explicit human-help request. **Updated 2026-08-19 (FE Gap 243 / BE Gap 254):** the no-match fallback no longer escalates. It used to, which rendered an unanswered question in the same red *Issue Diagnosis & Recommended Escalation* framing as a genuinely detected incident. A miss now returns `suggest_escalation=False` with a new `low_confidence=true`, and the component renders a third, neutral `#low-confidence-card` — no red styling, no incident wording, just *Didn't find an answer?* and a plain `Raise a Ticket` button (`#low-confidence-ticket-btn`) reusing `handleOpenEscalation` so the modal still prefills from `escalation_context`. `low_confidence` is optional and defaults to `false`, so this is backwards-compatible in both directions.
- [x] **Task 15.3: Build `SupportTicketModal.tsx`** — Done 2026-08-17. Form fields, live validation, priority pills with SLA labels, pre-fill from escalation context / transcript, animated success state showing the returned reference number.
- [x] **Task 15.4: Create API Proxy Routes** — Done 2026-08-17. Both routes are thin `POST` handlers over `proxyJson()` from `lib/backendProxy.ts`; Clerk token forwarding is that helper's existing behaviour rather than anything re-implemented here.
- [x] **Task 15.5: Automated E2E Tests** — Done 2026-08-17. `e2e/help-support.spec.ts`, 6 specs: guides open by default, search filters topics, tab switch to SAGE, chat turn returns a response, escalation card appears on a system error and pre-fills the modal, and the header direct-ticket button opens a clean modal and submits.

---

## 5. Verification Plan

* **Automated E2E:** Run Playwright suite verifying default guide rendering, search filtering, chat turn handling, ticket escalation trigger, and modal submission.
* **Manual Verification:** Test asking questions in SAGE Bot, verify 1-click ticket pre-fill, submit ticket, and confirm email alert at `Application@infinevocloud.com`.

### 5.1 Actual verification state (recorded 2026-08-18)

* **Reported by the branch author, 2026-08-17:** `npx tsc --noEmit` clean, `e2e/help-support.spec.ts` 6/6 passing.
* **Re-run status:** not re-run during the 2026-08-18 merge-prep pass — no `node_modules` was installed in that worktree, so neither `tsc` nor Playwright could be executed. That pass verified the components by reading them and confirmed only that the spec file contains exactly 6 `test(` blocks.
* **Never done, for either pass:** the Playwright specs stub `/api/**`, so nothing here has been exercised against a real backend, a real Clerk session, or a real ticket landing in `Application@infinevocloud.com`. The manual verification bullet above remains outstanding in full.
