# Frontend Features Progress Tracker

This document tracks the implementation progress of all frontend features for the `invoice-fe` Next.js client, including theme, layouts, and page routing. Feature spec files (`feature_1..7_*.md`) describe the target design only — every open item and pending build task is tracked here instead, so status doesn't drift out of sync across files.
**Current Status:** ~68% complete against the feature specs below (updated 2026-07-22 after Feature 6 full frontend delivery), with 14 open items remaining.

---

## Feature Tracker

- `[x]` [Feature 1: Global Theme & Core Shell Layout](feature_1_layout_theme.md)
- `[x]` [Feature 2: Dashboard Analytics Command Center](feature_2_dashboard.md)
- `[x]` [Feature 3: File Ingestion Portal & Active Tagging](feature_3_ingestion.md)
- `[x]` [Feature 4: Split-Screen Auditor Review Console](feature_4_auditor.md)
- `[ ]` [Feature 5: Semantic Chat Assistant & SQL Audit Drawer](feature_5_chat.md)
- `[x]` [Feature 6: AI Trainer Interactive Sandbox](feature_6_trainer.md)
- `[ ]` [Feature 7: Third-Party Connectors & Explorer View](feature_7_connectors.md)

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
- `[ ]` **Gap 6: Suggestion Chips** — clickable chips that auto-fill and submit common queries
- `[ ]` **Gap 13: Typing Indicators** — "Thinking..." animation while waiting for the LLM response

**Trainer sandbox** ([feature_6_trainer.md](feature_6_trainer.md)):
- `[x]` **Gap 3: Rule Scope Selector** — Tasks 6.1–6.4; ✅ 3-way Global / Existing Vendor / New Vendor entry point implemented in `ScopeSelector.tsx` + `TrainerUploader.tsx` (2026-07-22)
- `[x]` **Gap 7: Active Rules Registry** — ✅ Active rule candidates list with `Active` status badges rendered in `QnAPanel.tsx` Variables & Rules Inspector tab (2026-07-22)
- `[x]` **Gap 8: Always-Enabled Chat Input** — ✅ Chat input bar always active; Global-scope sessions with no seed PDF start chat-only with empty variables list (2026-07-22)
- `[x]` **Gap 9: Active Validation Alerts Panel** — ✅ Low-confidence field warnings (< 80%) shown with amber `AlertCircle` icons in `QnAPanel.tsx` Variables Inspector; corrected fields shown with emerald `CheckCircle2` (2026-07-22)
- `[x]` **Gap 16: Rule History & Rollback UI** — Task 6.7; ✅ Full `RuleHistoryDrawer.tsx` implemented with version timeline, `isCurrent` badge, rollback confirmation bar, and loading state (2026-07-22)
- `[x]` **Gap 17: Audit-Seeded Trainer Session Entry** — Task 6.8; ✅ URL parameter parsing (`?from=audit&scope=...&vendor_name=...&correction=...`) handled in `page.tsx` `useEffect` — pre-seeds scope, vendor, and sends an initial chat correction automatically (2026-07-22)
