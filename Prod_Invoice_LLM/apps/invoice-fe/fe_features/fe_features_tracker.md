# Frontend Features Progress Tracker

This document tracks the implementation progress of all frontend features for the `invoice-fe` Next.js client, including theme, layouts, and page routing. Feature spec files (`feature_1..7_*.md`) describe the target design only — every open item and pending build task is tracked here instead, so status doesn't drift out of sync across files.

**Current Status:** ~85% complete (6 of 7 features done) against the feature specs below, with 13 open gap items remaining. Feature 5 (Chat) completed 2026-07-22; Feature 6 (AI Trainer) frontend completed 2026-07-22, merged alongside its backend (Feature 10) 2026-07-24.

---

## Feature Tracker

- `[x]` [Feature 1: Global Theme & Core Shell Layout](feature_1_layout_theme.md)
- `[x]` [Feature 2: Dashboard Analytics Command Center](feature_2_dashboard.md)
- `[x]` [Feature 3: File Ingestion Portal & Active Tagging](feature_3_ingestion.md)
- `[x]` [Feature 4: Split-Screen Auditor Review Console](feature_4_auditor.md)
- `[x]` [Feature 5: Semantic Chat Assistant & SQL Audit Drawer](feature_5_chat.md)
- `[x]` [Feature 6: AI Trainer Interactive Sandbox](feature_6_trainer.md)
- `[ ]` [Feature 7: Third-Party Connectors & Explorer View](feature_7_connectors.md)
- `[ ]` [Feature 8: Email Ingestion Settings](feature_8_email_ingestion.md) — spec only, added 2026-07-22; backend (`be_features/feature_14_email_ingestion.md`) blocked on a vendor decision before implementation starts
- `[ ]` [Feature 9: Webhooks Settings](feature_9_webhooks.md) — spec only, added 2026-07-22
- `[ ]` [Feature 10: Settings Screen](feature_10_settings.md) — spec only, added 2026-07-27; first-ever `/settings` route, houses Connectors/Email/Webhooks by reference plus the two new Vendor Flow toggles
- `[ ]` [Feature 3.1: Vendor Flow — Send Invoices Tab](feature_3.1_vendor_flow_ingestion.md) — spec only, added 2026-07-27; extends Feature 3
- `[ ]` [Feature 4.1: Vendor Flow — Outbound Auditor Tab](feature_4.1_vendor_flow_auditor.md) — spec only, added 2026-07-27; extends Feature 4
- `[ ]` [Feature 2.1: Vendor Flow — Outbound Dashboard (Split-Screen)](feature_2.1_vendor_flow_dashboard.md) — spec only, added 2026-07-27; extends Feature 2
- `[x]` [Feature 11: System Flow Visualization](feature_11_flows_visualization.md) — backfilled 2026-07-27; found already built and undocumented at `app/flows/page.tsx`, a standalone animated demo/explainer diagram, not a functional screen or part of Vendor Flow's actual implementation (two of its four tabs visualize Vendor Flow's design, clearly marked spec-only)

---

## Feature 6 Completion Summary (2026-07-22)

Feature 6 frontend was fully implemented and design-refined in session 2026-07-22.
All 6 open gaps are now closed. Below is a summary of every file delivered:

| File | Task | Status |
|---|---|---|
| `components/layout/Sidebar.tsx` | Added `/trainer` nav link (GraduationCap icon) | ✅ Done |
| `lib/trainer-service.ts` | Service layer: data models + 6 methods (live API calls via `/api/trainer/*` as of 2026-07-23) | ✅ Done |
| `components/trainer/ScopeSelector.tsx` | 3-way Global / Existing Vendor / New Vendor tab selector | ✅ Done |
| `components/trainer/TrainerUploader.tsx` | Scope-conditioned vendor dropdown + drag-and-drop PDF uploader | ✅ Done |
| `components/trainer/PdfViewerPanel.tsx` | PDF viewer canvas + Global empty state card (dual mode) | ✅ Done |
| `components/trainer/QnAPanel.tsx` | Chat Assistant + Variables & Rules Inspector (2-tab panel) | ✅ Done |
| `components/trainer/CommitModal.tsx` | Scope-aware registry commit modal with re-audit notice | ✅ Done |
| `components/trainer/RuleHistoryDrawer.tsx` | Rule version history drawer + rollback confirmation | ✅ Done |
| `app/trainer/page.tsx` | Main page orchestrator: state mgmt, toast notifications, audit deep-link | ✅ Done |

**Design Refinements Applied (2026-07-22):**
- Premium glassmorphism surfaces with `backdrop-blur` on all panels
- Per-scope color glow rings on `ScopeSelector` (blue / emerald / purple)
- Animated drag-pulse overlay on `TrainerUploader` dropzone
- Dual ambient radial glow orbs on `PdfViewerPanel` Global empty state
- Gradient message bubbles (blue gradient for user, glass dark for AI) in `QnAPanel`
- Three-dot `animate-bounce` typing indicator replacing plain pulse dots
- Empty chat state with `Zap` icon prompt in `QnAPanel`
- Scope-adaptive confirm button colors in `CommitModal` (blue / emerald / purple)
- Active bottom indicator line on `ScopeSelector` active tab

**Backend Integration Completed (2026-07-23):** `trainer-service.ts` now calls the live backend through same-origin proxy Route Handlers added under `app/api/trainer/**`; the mock datasets were removed. Wiring:
- `GET /api/trainer/vendors` → `getTenantVendors()`
- `POST /api/trainer/sessions/global` → `startSession("global")` (multipart, PDF optional)
- `POST /api/trainer/sessions/from-production?vendor_name=X` → `startSession("existing_vendor", ...)`
- `POST /api/trainer/upload` → `startSession("new_vendor", ..., file)`
- `POST /api/trainer/sessions/{id}/chat` → `sendChatMessage()`
- `POST /api/trainer/sessions/{id}/commit` → `commitSession()` (wired into `CommitModal` `onConfirm` / `handleConfirmCommit`)
- `GET /api/trainer/templates/history?scope=&vendor_name=` → `getRuleHistory()`
- `POST /api/trainer/templates/{id}/rollback/{version}` → `rollbackTemplate()` (wired into `RuleHistoryDrawer` `onRollback`)

`page.tsx`'s `handleConfirmCommit` and `handleRollback` now perform real network calls with success/error toasts, and New-Vendor sessions start empty until a PDF is uploaded. Matching backend: `be_features_tracker.md` Gaps 1b, 5, 6, 8, 29 (Feature 10).

---

## Open Items / Gaps

Gaps below are grouped by the feature file whose target design they still need to catch up to.

**Ingestion portal** ([feature_3_ingestion.md](feature_3_ingestion.md)):
- `[x]` **Gap 1: Directory Watcher (Bulk Processing)** — Fixed Jul 27, 2026. Added a "Bulk Directory Scan" card to `app/ingestion/page.tsx` — a folder-path text input + Scan button, calling the new `POST /api/invoices/watcher` proxy route (`be_features_tracker.md` Gap 12). Successful scans feed the found job_ids into the existing `StatusTable`, same as a normal upload; a `501` response (watcher not configured) and path-traversal `400` both surface clear inline error messages rather than a silent failure.
- `[x]` **Gap 2: Live Terminal Feed** — Fixed Jul 27, 2026. New `components/ingestion/LogTerminal.tsx` — a scrolling console subscribing to the same SSE stream `StatusTable` uses, opening its own `EventSource` regardless of batch size (log visibility isn't tied to StatusTable's polling/SSE transport choice), filtering for the new `type === "log_line"` event (backend: `be_features_tracker.md` Gap 57) and rendering real per-stage lines (OCR, classify, dynamic_qa, extract, verify, chunking, embedding) instead of just status transitions. Wired into `app/ingestion/page.tsx` alongside `StatusTable`. Verified end-to-end with a real upload — log lines rendered in order, including a genuine retry-loop repeat.
- `[x]` **Gap 14: Live Statistics Counters** — Fixed Jul 27, 2026. `StatusTable.tsx` now computes and shows Found/Processed/Duplicates/Failed counts in its header, derived from the same `items` state driving the table rows. Found and fixed a real bug along the way: `pollJobStatus()` (used for batches under 6 files) had no branch for a `DUPLICATE` status at all — a duplicate upload silently stayed on "Processing" forever instead of stopping and showing a Duplicate badge, since none of the existing `if`/`else if` branches matched it. Added the missing branch, a `DUPLICATE` badge (matching `RecentInvoicesTable.tsx`'s existing amber styling), and extended the `StatusItem` status union to include it.

**Dashboard** ([feature_2_dashboard.md](feature_2_dashboard.md)):
- `[x]` **Gap 4: Actionable Insights Panel** — Fixed Jul 27, 2026. New `components/dashboard/ActionableInsightsPanel.tsx`, fetching its own `GET /dashboard/insights` (backend: `be_features_tracker.md` Gap 30) independently of the main metrics call, same pattern as the Trainer Impact Panel. Renders each AI-generated recommendation as a severity-colored card (critical/warning/info). Wired into `app/dashboard/page.tsx` below `ClientPerformanceChart`. Verified live against real Azure OpenAI + real invoice data.
- `[x]` **Gap 5: Status-Based Sub-Tabs** — Fixed Jul 27, 2026. Added All/Paid/Pending/Rejected tabs above the table in `RecentInvoicesTable.tsx`, client-side filtered against the already-fetched invoice list. "Pending" covers everything not yet finalized (Processing, Completed, Audit Required, Duplicate) rather than mapping 1:1 to a raw status enum, matching the AP mental model of "still in the pipeline" vs. closed out.
- `[x]` **Gap 11: Scroll-Lock Container** — Fixed Jul 27, 2026. Wrapped the table in a `max-height: 320px`, `overflow-y-auto` container with a `sticky` header row, so a long invoice list scrolls internally instead of pushing the rest of the dashboard down.
- `[x]` **Gap 12: Client-Side Pagination** — Fixed Jul 27, 2026. Added Previous/Next controls (8 rows/page) below the table, operating on the tab-filtered list; resets to page 1 whenever the active tab or the underlying invoice count changes so a stale page number can't point past the end of a newly-filtered/shrunk list.
- `[ ]` **Gap 30: Pagination Controls Not Rendered** — `RecentInvoicesTable.tsx` calculates `totalPages` and imports `ChevronLeft`/`ChevronRight`, but no Previous/Next controls are rendered. Users therefore remain on the first 8 rows. Render a pager below the table that updates `currentPage`, displays the current page and total pages, and disables Previous/Next at the first/last page. *(Raised 2026-07-27.)*
- `[ ]` **Gap 29: Dashboard Invoice-List Scalability** — keep a small, paginated Recent Invoices table (with skeleton rows while its page loads), but never load a tenant's entire invoice history into the browser or FastAPI process. Move KPI/chart aggregation to PostgreSQL (`SUM`/`COUNT`/`GROUP BY` scoped by `tenant_id` and active filters), expose the invoice ledger through a bounded `limit` + cursor/offset page API, and add indexes for the common tenant/date/status/vendor filters. A dedicated full Invoices Queue/list page should consume the same paginated API. *(Raised 2026-07-27.)*
- `[x]` **Gap 21: Trainer Impact Panel** — Task 2.5; Fixed Jul 27, 2026. New `components/dashboard/TrainerImpactPanel.tsx`, fetching its own `GET /dashboard/trainer-impact` (backend: `be_features_tracker.md` Gap 28) independently of the main metrics call. Renders 3 rule-count tiles (Global/Vendor/Total), a hand-built weekly audit-rate bar trend (no chart library, matching the rest of this dashboard), and a "Vendors Needing a Rule" list with deep-links straight into Trainer (`/trainer?from=audit&scope=existing_vendor&vendor_name=X`, reusing the existing Task 6.8 deep-link handler). Wired into `app/dashboard/page.tsx` below `ClientPerformanceChart`. Verified live: real data from this session's actual Trainer commits rendered correctly.

> Note: `RecentInvoicesTable.tsx`'s duplicate badge, vendor-name fallback, and hover-only tag row CSS (`be_features/feature_3.1_fix_ftr2_3.md` Task 3.1.3) are already implemented — verified directly against the component source 2026-07-13, not just tracker bookkeeping.

**Auditor console** ([feature_4_auditor.md](feature_4_auditor.md)):
- `[x]` **Gap 10: Line Items Table** — Fixed Jul 27, 2026. The metadata inspector's line items section only ever showed Description + Total in a plain list — `quantity`/`unit_price` were already present on the `LineItem` type and returned by the backend, just never rendered. Converted to a real `<table>` with Description/Qty/Unit Price/Total columns plus a subtotal footer row.
- `[x]` **Gap 15: Confidence-based field highlighting** — Fixed Jul 25, 2026. Added an amber warning icon to fields below 60% OCR confidence in the `AlertConsole` UI. *(Task 4.5)*
- `[x]` **Gap 19: Editable Metadata Inspector & Correction Capture** — Fixed Jul 25, 2026. Built `EditableField` component allowing metadata fields to be click-to-edit. The `AlertConsole` now tracks a `corrections` diff and sends it on save. *(Task 4.6)*
- `[x]` **Gap 20: Rule Suggestion Prompt** — Fixed Jul 25, 2026. Added a purple "Want to save this as a rule?" banner to `AlertConsole` when `suggested_rule` is present. Clicking it navigates to `/trainer?from=audit&scope=...` using the existing Trainer deep-link handler. *(Task 4.7)*
- `[x]` **Gap 26: "Report an issue" action on any invoice** — Fixed Jul 27, 2026, two parts: (1) the review page (`app/invoices/review/[id]/page.tsx`) was unreachable from anywhere in the app — every link to it (Sidebar nav, Dashboard row actions, Ingestion row actions, chat citation pills) pointed at `/audit`, a route that has never existed; fixed all four to point at the real path. (2) added a "Save Correction" button for the case where an invoice has zero alerts (e.g. `COMPLETED` but factually wrong) — previously the only way to submit `corrections` was via `Mark Paid & Finalize`/`Reject Invoice`, both of which forced a status change. Backend: `be_features_tracker.md` Gap 53 (no backend change needed — the endpoint already supported this). See `feature_4_auditor.md` for the full writeup. Verified live against the real running app + a real invoice.
- `[ ]` **Gap 28: No dedicated Invoices Queue / list page** — found while fixing Gap 26. Sidebar's "Invoices" nav item and `RecentInvoicesTable`'s "View all ledger" link both pointed at the same nonexistent `/audit` route; removed rather than repointed, since there's no dedicated list page for a bare (no-id) link to land on — Dashboard's `RecentInvoicesTable` is currently the only invoice-listing surface. *(Raised Jul 27, 2026.)*

> Note: `PdfViewerCanvas.tsx`'s bounding-box overlay (Task 4.2) is fully built but has no backend data source yet — see `be_features_tracker.md` Gap 16.

**Chat assistant** ([feature_5_chat.md](feature_5_chat.md)):

> ✅ **Core Feature 5 implemented 2026-07-22** — 10 new files created, 0 existing files modified, TypeScript compile: **0 errors**.

**Completed Tasks (from `feature_5_chat.md`):**

- `[x]` **Task 5.1: Build Conversational Message Thread Interface** — scroll-to-bottom chat bubble container with markdown formatting, thread selector sidebar with `+ New Chat` action, active thread highlighting, and empty state guidance.
  - Files: `components/chat/ChatWindow.tsx`, `components/chat/MessageBubble.tsx` (includes `MessageStream` with auto-scroll)
- `[x]` **Task 5.2: Integrate Interactive Citations** — parse `citations[]` from the backend RAG response and render as clickable pills. Each pill navigates to `/invoices/review/{id}?page={n}` (originally `/audit?invoice_id=...`, a route that never existed — fixed 2026-07-27 alongside Gap 26).
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

- `[x]` **Gap 6: Suggestion Chips** — Fixed Jul 27, 2026. New `SuggestionChips` component inside `ChatWindow.tsx`, shown only when an active session has zero messages (a fresh new chat) — clicking a chip calls `onSendMessage` directly, submitting immediately rather than just filling the input box. Not part of `feature_5_chat.md`'s original task list — tracked as a separate enhancement.
- `[x]` **Gap 27: Per-answer thumbs up/down** — Fixed Jul 27, 2026. New `FeedbackVote` component inside `MessageBubble.tsx`, shown on assistant messages next to the timestamp. Optimistic update with rollback on failure; clicking the active thumb again clears the vote instead of re-sending it. Calls the new `PUT`/`DELETE /api/chat/messages/{id}/feedback` proxy route. Backend: `be_features_tracker.md` Gap 54. Verified live through the real proxy route and real backend (vote → reload persists → change vote → clear → reload shows null).

- `[x]` **Gap 22: Chat never actually worked through the real UI — FE/BE contract mismatch on every endpoint** — found + fixed Jul 24, 2026 during live end-to-end testing (the benchmark harness that previously reported "95.2% RAG chat passed" calls the backend directly, bypassing the FE entirely — this exact class of bug was invisible to it). Every message send returned a `422` because `hooks/useChatSession.ts` sent `{message: text}` while the backend's `MessageCreate` requires `{content: text}`; `types/chat.ts::SendMessageRequest` had the wrong field name too, so it wasn't caught at the type level. Three more mismatches found in the same pass, all silent (wrong data or `undefined`, not errors): `GET /chat/sessions` returns a bare array, not `{sessions: [...]}`; `GET /chat/sessions/{id}` returns a bare message array, not `{session, messages}`; `POST .../message`'s response is the flat `ChatMessage`, not `{message: ...}`; and `Citation.page_number` didn't match the backend's `page` field (would have shown "p.undefined" on every RAG citation). Fixed all of them in `useChatSession.ts`, `types/chat.ts`, and `CitationPill.tsx`. Verified live: asked 3 real questions against a real ingested invoice, got correct SQL-routed answers with no console errors.

**Trainer sandbox** ([feature_6_trainer.md](feature_6_trainer.md)):
- `[x]` **Gap 3: Rule Scope Selector** — Tasks 6.1–6.4; ✅ 3-way Global / Existing Vendor / New Vendor entry point implemented in `ScopeSelector.tsx` + `TrainerUploader.tsx` (2026-07-22)
- `[x]` **Gap 7: Active Rules Registry** — ✅ Active rule candidates list with `Active` status badges rendered in `QnAPanel.tsx` Variables & Rules Inspector tab (2026-07-22)
- `[x]` **Gap 8: Always-Enabled Chat Input** — ✅ Chat input bar always active; Global-scope sessions with no seed PDF start chat-only with empty variables list (2026-07-22)
- `[x]` **Gap 9: Active Validation Alerts Panel** — ✅ Low-confidence field warnings (< 80%) shown with amber `AlertCircle` icons in `QnAPanel.tsx` Variables Inspector; corrected fields shown with emerald `CheckCircle2` (2026-07-22)
- `[x]` **Gap 16: Rule History & Rollback UI** — Task 6.7; ✅ Full `RuleHistoryDrawer.tsx` implemented with version timeline, `isCurrent` badge, rollback confirmation bar, and loading state (2026-07-22)
- `[x]` **Gap 17: Audit-Seeded Trainer Session Entry** — Task 6.8; ✅ URL parameter parsing (`?from=audit&scope=...&vendor_name=...&correction=...`) handled in `page.tsx` `useEffect` — pre-seeds scope, vendor, and sends an initial chat correction automatically (2026-07-22)
- `[x]` **Gap 23: Screen not cleared after commit, left pointing at a dead session** — found + fixed Jul 25, 2026 during live UI testing (this trainer code was only merged from a feature branch the same day and had never run end-to-end before). The backend deletes the session immediately on commit, but `page.tsx::handleConfirmCommit()` never reset FE state — the same chat/PDF/variables stayed on screen looking live. Fixed: clear state per scope after commit (Global auto-starts a fresh session; Existing/New Vendor reset to their empty picker state). See `be_features_tracker.md` Gap 50.
- `[x]` **Gap 24: Document viewer panel was a hardcoded mock, not the real document** — found + fixed Jul 25, 2026. `PdfViewerPanel.tsx` showed literal sample data (`"Acme Logistics Corp"`) no matter what was actually uploaded — its own comment called it a "simulated invoice body." Fixed: real `<iframe src={pdfUrl}>` render plus a live summary strip from the session's actual `variables`. See `be_features_tracker.md` Gap 51.
- `[x]` **Gap 25: Chat correction had no progress feedback during its ~25-30s round-trip** — found + fixed Jul 25, 2026; initially looked like a hung/stuck bug (a message sat on "Refining rules..." well past a 20s+6s test wait) until a network-level check confirmed the backend genuinely takes that long (two sequential real LLM calls: refine constraints, then re-extract) and the UI updates correctly the moment the response lands — not a correctness bug, just no indication of how long to expect. Added a client-side elapsed-time-estimated progress bar + stage text ("Analyzing correction..." → "Re-extracting with updated rules..." → "Finalizing...") in `QnAPanel.tsx`, capped short of 100% until the real response arrives so it never falsely claims completion early.

**Connectors** ([feature_7_connectors.md](feature_7_connectors.md)):
- **Note (2026-07-22):** SAP and QuickBooks were deferred from Task 7.1's integration grid, not forgotten — no confirmed customer/system needs them today. Re-add if real demand shows up.
