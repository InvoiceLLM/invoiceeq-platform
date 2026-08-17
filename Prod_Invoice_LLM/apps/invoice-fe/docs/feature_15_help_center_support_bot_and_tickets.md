# Feature 15: Help Center Knowledge Base & AI Support Assistant with Direct Ticket Escalation

**Status:** Planned / Architecture Verified  
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

* **Main Page Route:** `apps/invoice-fe/app/help/page.tsx`
* **AI Support Chatbot Component:** `apps/invoice-fe/components/help/SupportChatWindow.tsx`
* **Support Ticket Modal:** `apps/invoice-fe/components/help/SupportTicketModal.tsx`
* **Guide Content Registry:** `apps/invoice-fe/app/help/content/*.tsx`
* **API Proxy Routes:** `apps/invoice-fe/app/api/support/ticket/route.ts`, `apps/invoice-fe/app/api/support/chat/route.ts`
* **Interactive Demo Prototype:** `demo_screens/frontend_help_center_demo.html`

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

- [ ] **Task 15.1: Redesign `/help/page.tsx` with Tabs**
  - Make Knowledge Base Guides default view on load, with tab switcher to AI Support Assistant.
- [ ] **Task 15.2: Build `SupportChatWindow.tsx`**
  - Implement conversation stream, prompt chips, and inline escalation card.
- [ ] **Task 15.3: Build `SupportTicketModal.tsx`**
  - Implement form fields (Subject, Category, Priority, Description, Submitter Email), pre-filling logic, and animated success state.
- [ ] **Task 15.4: Create API Proxy Routes**
  - Implement `app/api/support/ticket/route.ts` and `app/api/support/chat/route.ts` with Clerk session token forwarding.
- [ ] **Task 15.5: Automated E2E Tests**
  - Add Playwright spec in `e2e/help-support.spec.ts` covering guide navigation, chat assistance, ticket suggestion trigger, and modal submission.

---

## 5. Verification Plan

* **Automated E2E:** Run Playwright suite verifying default guide rendering, search filtering, chat turn handling, ticket escalation trigger, and modal submission.
* **Manual Verification:** Test asking questions in SAGE Bot, verify 1-click ticket pre-fill, submit ticket, and confirm email alert at `Application@infinevocloud.com`.
