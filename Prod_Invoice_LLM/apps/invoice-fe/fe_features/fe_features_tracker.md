# Frontend Features Progress Tracker

This document tracks the implementation progress of all frontend features for the `invoice-fe` Next.js client, including theme, layouts, and page routing. Feature spec files (`feature_1..7_*.md`) describe the target design only — every open item and pending build task is tracked here instead, so status doesn't drift out of sync across files.

**Current Status:** ~55% complete against the feature specs below (scope expanded 2026-07-13 to match the finalized backend specs), with 20 open items below.

---

## Feature Tracker

- `[x]` [Feature 1: Global Theme & Core Shell Layout](feature_1_layout_theme.md)
- `[x]` [Feature 2: Dashboard Analytics Command Center](feature_2_dashboard.md)
- `[x]` [Feature 3: File Ingestion Portal & Active Tagging](feature_3_ingestion.md)
- `[x]` [Feature 4: Split-Screen Auditor Review Console](feature_4_auditor.md)
- `[ ]` [Feature 5: Semantic Chat Assistant & SQL Audit Drawer](feature_5_chat.md)
- `[ ]` [Feature 6: AI Trainer Interactive Sandbox](feature_6_trainer.md)
- `[ ]` [Feature 7: Third-Party Connectors & Explorer View](feature_7_connectors.md)

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

**Trainer sandbox** ([feature_6_trainer.md](feature_6_trainer.md) — redesigned 2026-07-13 into Global / Existing Vendor / New Vendor rule scopes, matching `be_features/feature_10_trainer.md`):
- `[ ]` **Gap 3: Rule Scope Selector** — Tasks 6.1–6.4; 3-way Global / Existing Vendor / New Vendor entry point, replacing the old single uploader
- `[ ]` **Gap 7: Active Rules Registry** — list of generated extraction/validation rules with checkbox selection
- `[ ]` **Gap 8: Always-Enabled Chat Input** — sandbox correction chat active without a loaded PDF (applies to Global-scope sessions with no seed PDF)
- `[ ]` **Gap 9: Active Validation Alerts Panel** — display triggered warnings in real time
- `[ ]` **Gap 16: Rule History & Rollback UI** — Task 6.7; list committed rule versions and roll back a bad Global or vendor rule (see `be_features_tracker.md` Gap 29)
- `[ ]` **Gap 17: Audit-Seeded Trainer Session Entry** — Task 6.8; accept a session pre-populated from the Auditor console's rule-suggestion prompt (Task 4.7 / Gap 20) instead of starting blank
