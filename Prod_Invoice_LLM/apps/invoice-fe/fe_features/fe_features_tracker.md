# Frontend Features Progress Tracker

This document tracks the implementation progress of all frontend features for the `invoice-fe` Next.js client, including theme, layouts, and page routing. Feature spec files (`feature_1..7_*.md`) describe the target design only — every open item and pending build task is tracked here instead, so status doesn't drift out of sync across files.

**Current Status:** ~71% complete (5 of 7 features done) against the feature specs below, with 19 open gap items remaining. Feature 5 core implementation completed 2026-07-22.

---

## Feature Tracker

- `[x]` [Feature 1: Global Theme & Core Shell Layout](feature_1_layout_theme.md)
- `[x]` [Feature 2: Dashboard Analytics Command Center](feature_2_dashboard.md)
- `[x]` [Feature 3: File Ingestion Portal & Active Tagging](feature_3_ingestion.md)
- `[x]` [Feature 4: Split-Screen Auditor Review Console](feature_4_auditor.md)
- `[x]` [Feature 5: Semantic Chat Assistant & SQL Audit Drawer](feature_5_chat.md)
- `[ ]` [Feature 6: AI Trainer Interactive Sandbox](feature_6_trainer.md)
- `[ ]` [Feature 7: Third-Party Connectors & Explorer View](feature_7_connectors.md)
- `[ ]` [Feature 8: Email Ingestion Settings](feature_8_email_ingestion.md) — spec only, added 2026-07-22; backend (`be_features/feature_14_email_ingestion.md`) blocked on a vendor decision before implementation starts
- `[ ]` [Feature 9: Webhooks Settings](feature_9_webhooks.md) — spec only, added 2026-07-22

---

## Open Items / Gaps

Gaps below are grouped by the feature file whose target design they still need to catch up to.

**Ingestion portal** ([feature_3_ingestion.md](feature_3_ingestion.md)):
- `[ ]` **Gap 1: Directory Watcher (Bulk Processing)** — input field for a local folder path to process thousands of files without per-file drag-and-drop
- `[ ]` **Gap 2: Live Terminal Feed** — scrolling console window with colored status logs (Completed, Duplicate, Failed) alongside the ingestion queue table
- `[ ]` **Gap 14: Live Statistics Counters** — header counters for Total Found, Processed, Duplicates, and Failed

**Dashboard** ([feature_2_dashboard.md](feature_2_dashboard.md)):
- `[ ]` **Gap 4: Actionable Insights Panel** — AI-generated text readout with strategic recommendations alongside the metric cards; blocked until the backend exposes a generation endpoint (see `be_features_tracker.md` Gap 30)
- `[ ]` **Gap 5: Status-Based Sub-Tabs** — tabs (All, Paid, Pending, Rejected) on the recent invoices table
- `[ ]` **Gap 11: Scroll-Lock Container** — wrap the recent invoices table in a fixed-height card (`max-height: 320px`) with internal scroll
- `[ ]` **Gap 12: Client-Side Pagination** — dynamic `◀ Previous` / `Next ▶` controls on the recent invoices table
- `[ ]` **Gap 21: Trainer Impact Panel** — Task 2.5; render rules-trained count, audit-rate trend, and vendors-needing-rules from the dashboard metrics endpoint, once the backend ships it (see `be_features_tracker.md` Gap 28)

> Note: `RecentInvoicesTable.tsx`'s duplicate badge, vendor-name fallback, and hover-only tag row CSS (`be_features/feature_3.1_fix_ftr2_3.md` Task 3.1.3) are already implemented — verified directly against the component source 2026-07-13, not just tracker bookkeeping.

**Auditor console** ([feature_4_auditor.md](feature_4_auditor.md)):
- `[ ]` **Gap 10: Line Items Table** — tabular view of individual line items (Description, Qty, Unit Price, Total) in the metadata inspector
- `[ ]` **Gap 15: Confidence-based field highlighting** — Task 4.5; flag low-confidence fields in the metadata inspector once the backend supplies per-field confidence scores (see `be_features_tracker.md` Gap 17)
- `[ ]` **Gap 19: Editable Metadata Inspector & Correction Capture** — Task 4.6; make the metadata inspector editable and send the `corrections` diff on resolve, closing the loop for `be_features_tracker.md` Gap 26
- `[ ]` **Gap 20: Rule Suggestion Prompt** — Task 4.7; surface "Want to save this as a rule?" from the resolve response's `suggested_rule` and hand off into a pre-seeded Trainer session (Task 6.8), closing the loop for `be_features_tracker.md` Gap 27

> Note: `PdfViewerCanvas.tsx`'s bounding-box overlay (Task 4.2) is fully built but has no backend data source yet — see `be_features_tracker.md` Gap 16.

**Chat assistant** ([feature_5_chat.md](feature_5_chat.md)):

> ✅ **Core Feature 5 implemented 2026-07-22** — 10 new files created, 0 existing files modified, TypeScript compile: **0 errors**.

**Completed Tasks (from `feature_5_chat.md`):**

- `[x]` **Task 5.1: Build Conversational Message Thread Interface** — scroll-to-bottom chat bubble container with markdown formatting, thread selector sidebar with `+ New Chat` action, active thread highlighting, and empty state guidance.
  - Files: `components/chat/ChatWindow.tsx`, `components/chat/MessageBubble.tsx` (includes `MessageStream` with auto-scroll)
- `[x]` **Task 5.2: Integrate Interactive Citations** — parse `citations[]` from the backend RAG response and render as clickable pills. Each pill navigates to `/audit?invoice_id={id}&page={n}`.
  - File: `components/chat/CitationPill.tsx`
- `[x]` **Task 5.3: Build Expandable SQL Drawer** — collapsible accordion titled "Executed SQL Query & Data Sources" with emerald-green formatted code block and one-click copy-to-clipboard.
  - File: `components/chat/SqlAuditDrawer.tsx`
- `[x]` **Task 5.4: Bind Chat Queries to Backend** — async submit hook (`useChatSession`) with optimistic user bubble, error rollback, and session title auto-update. Three Next.js API proxy routes forward to the FastAPI backend.
  - Files: `hooks/useChatSession.ts`, `app/api/chat/sessions/route.ts`, `app/api/chat/sessions/[sessionId]/route.ts`, `app/api/chat/sessions/[sessionId]/message/route.ts`

**Supporting files created:**

- `[x]` `types/chat.ts` — TypeScript interfaces for `ChatSession`, `ChatMessage`, `Citation`, and all request/response shapes matching the backend API contract.
- `[x]` `app/chat/page.tsx` — `/chat` page entry point wiring `useChatSession` hook to `ChatWindow`. Uses `-m-8` to fill the full viewport edge-to-edge.

**Completed Gaps:**

- `[x]` **Gap 13: Typing Indicators** — three bouncing dots animation in `MessageBubble.tsx` `MessageStream` component while `isSending` is true, matching WhatsApp/Slack UX convention.

**Remaining Gaps:**

- `[ ]` **Gap 6: Suggestion Chips** — clickable preset query chips (e.g. "Total spend this month", "Show flagged invoices") that auto-fill and submit common queries. Not part of `feature_5_chat.md` task list — tracked as a separate enhancement.

**Trainer sandbox** ([feature_6_trainer.md](feature_6_trainer.md) — redesigned 2026-07-13 into Global / Existing Vendor / New Vendor rule scopes, matching `be_features/feature_10_trainer.md`):
- `[ ]` **Gap 3: Rule Scope Selector** — Tasks 6.1–6.4; 3-way Global / Existing Vendor / New Vendor entry point, replacing the old single uploader
- `[ ]` **Gap 7: Active Rules Registry** — list of generated extraction/validation rules with checkbox selection
- `[ ]` **Gap 8: Always-Enabled Chat Input** — sandbox correction chat active without a loaded PDF (applies to Global-scope sessions with no seed PDF)
- `[ ]` **Gap 9: Active Validation Alerts Panel** — display triggered warnings in real time
- `[ ]` **Gap 16: Rule History & Rollback UI** — Task 6.7; list committed rule versions and roll back a bad Global or vendor rule (see `be_features_tracker.md` Gap 29)
- `[ ]` **Gap 17: Audit-Seeded Trainer Session Entry** — Task 6.8; accept a session pre-populated from the Auditor console's rule-suggestion prompt (Task 4.7 / Gap 20) instead of starting blank

**Connectors** ([feature_7_connectors.md](feature_7_connectors.md)):
- **Note (2026-07-22):** SAP and QuickBooks were deferred from Task 7.1's integration grid, not forgotten — no confirmed customer/system needs them today. Re-add if real demand shows up.
