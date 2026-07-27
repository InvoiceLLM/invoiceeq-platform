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
- `[ ]` **Gap 14: Live Statistics Counters** — header counters for Total Found, Processed, Duplicates, and Failed
- `[ ]` **Gap 26: "Report an issue" action on any invoice** — currently only `AUDIT_REQUIRED` invoices get a correction UI (`AlertConsole`); a wrong-but-confident extraction on a `COMPLETED` invoice has no way to be flagged. Needs a new action reachable from any invoice row, wired into the same correction-capture flow as the Auditor console. Backend: `be_features_tracker.md` Gap 53. *(Raised Jul 27, 2026.)*

**Dashboard** ([feature_2_dashboard.md](feature_2_dashboard.md)):
- `[ ]` **Gap 4: Actionable Insights Panel** — AI-generated text readout with strategic recommendations alongside the metric cards; blocked until the backend exposes a generation endpoint (see `be_features_tracker.md` Gap 30)
- `[ ]` **Gap 5: Status-Based Sub-Tabs** — tabs (All, Paid, Pending, Rejected) on the recent invoices table
- `[ ]` **Gap 11: Scroll-Lock Container** — wrap the recent invoices table in a fixed-height card (`max-height: 320px`) with internal scroll
- `[ ]` **Gap 12: Client-Side Pagination** — dynamic `◀ Previous` / `Next ▶` controls on the recent invoices table
- `[x]` **Gap 21: Trainer Impact Panel** — Task 2.5; Fixed Jul 27, 2026. New `components/dashboard/TrainerImpactPanel.tsx`, fetching its own `GET /dashboard/trainer-impact` (backend: `be_features_tracker.md` Gap 28) independently of the main metrics call. Renders 3 rule-count tiles (Global/Vendor/Total), a hand-built weekly audit-rate bar trend (no chart library, matching the rest of this dashboard), and a "Vendors Needing a Rule" list with deep-links straight into Trainer (`/trainer?from=audit&scope=existing_vendor&vendor_name=X`, reusing the existing Task 6.8 deep-link handler). Wired into `app/dashboard/page.tsx` below `ClientPerformanceChart`. Verified live: real data from this session's actual Trainer commits rendered correctly.

> Note: `RecentInvoicesTable.tsx`'s duplicate badge, vendor-name fallback, and hover-only tag row CSS (`be_features/feature_3.1_fix_ftr2_3.md` Task 3.1.3) are already implemented — verified directly against the component source 2026-07-13, not just tracker bookkeeping.

**Auditor console** ([feature_4_auditor.md](feature_4_auditor.md)):
- `[ ]` **Gap 10: Line Items Table** — tabular view of individual line items (Description, Qty, Unit Price, Total) in the metadata inspector
- `[x]` **Gap 15: Confidence-based field highlighting** — Fixed Jul 25, 2026. Added an amber warning icon to fields below 60% OCR confidence in the `AlertConsole` UI. *(Task 4.5)*
- `[x]` **Gap 19: Editable Metadata Inspector & Correction Capture** — Fixed Jul 25, 2026. Built `EditableField` component allowing metadata fields to be click-to-edit. The `AlertConsole` now tracks a `corrections` diff and sends it on save. *(Task 4.6)*
- `[x]` **Gap 20: Rule Suggestion Prompt** — Fixed Jul 25, 2026. Added a purple "Want to save this as a rule?" banner to `AlertConsole` when `suggested_rule` is present. Clicking it navigates to `/trainer?from=audit&scope=...` using the existing Trainer deep-link handler. *(Task 4.7)*

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
- `[ ]` **Gap 27: Per-answer thumbs up/down** — vote UI on each `MessageBubble`, tied to that turn's SQL/citations. Signal-only, no auto-fix from votes. Backend: `be_features_tracker.md` Gap 54 (new `chat_feedback` table). *(Raised Jul 27, 2026.)*

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
