# Feature 6: AI Trainer Interactive Sandbox — **EVOLVE Agent**

**EVOLVE** (Continuous Learning) powers this screen. Develop the rule-scope selector, training document loader, chat verification panel, and registry commit workflows.

*(Redesigned 2026-07-13 to match `docs/feature_10_trainer.md` — supersedes the previous flat "one uploader, one commit button" design. See Rule Scope Selector below.)*

### Rule Scope Selector
The sandbox entry point is a 3-way choice, not a single uploader:
1. **Global** — tenant-wide, vendor-agnostic rule (e.g. "VAT is a tax item, applied after discount"). Chat-only; a sample PDF is optional grounding, not required.
2. **Existing Vendor** — refine rules for a vendor with production history. Vendor dropdown loads an already-extracted production invoice into the sandbox instead of a fresh upload.
3. **New Vendor** — cold-start rules for a vendor with no production history. Requires a fresh PDF upload (the prior design's only path).

Committing a Global or Existing Vendor session queues a background re-audit (Global re-audits every vendor; Existing Vendor re-audits just that vendor). New Vendor commits skip re-audit — there's no past data to re-evaluate.

### Theme & Styling Specifications
* Layout: Split screen panel. Left panel is a clean PDF viewer (or an empty state for Global sessions with no seed PDF). Right panel is the chat interface.
* Scope Selector: Segmented control / tab group at the top of the page (`Global` / `Existing Vendor` / `New Vendor`), styled `bg-[#151B26] border border-[#222D3D] rounded-lg`, active tab `bg-[#1E293B] text-white border-b-2 border-[#3B82F6]`.
* Action Buttons: Header registry submit button (`bg-[#10B981] hover:bg-[#059669] text-white font-medium px-4 py-2 rounded-lg`).

### File Coordinates
* Trainer Page: [apps/invoice-fe/app/trainer/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/trainer/page.tsx)
* Scope Selector: [apps/invoice-fe/components/trainer/ScopeSelector.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/ScopeSelector.tsx)
* Training Uploader: [apps/invoice-fe/components/trainer/TrainerUploader.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/TrainerUploader.tsx)
* Q&A Console: [apps/invoice-fe/components/trainer/QnAPanel.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/QnAPanel.tsx)
* Rule History Drawer: [apps/invoice-fe/components/trainer/RuleHistoryDrawer.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/RuleHistoryDrawer.tsx)
* Proxy Routes: none exist yet under `app/api/trainer/`. Backend currently only exposes the pre-redesign endpoints (`POST /trainer/upload` → `upload_transient_file()`, `POST /trainer/sessions/{id}/chat` → `trainer_chat()`, `POST /trainer/sessions/{id}/commit` → `trainer_commit()`) — the scope-aware routes this file's tasks depend on (`/trainer/sessions/global`, `/trainer/sessions/from-production`, rollback) don't exist until `docs/feature_10_trainer.md` Tasks 10.1–10.10 land

### Tasks
- [ ] **Task 6.1: Build Rule Scope Selector**
  - Segmented control switching between Global / Existing Vendor / New Vendor. Switching scope resets the sandbox session state.
- [ ] **Task 6.2: Global Scope Entry**
  - Chat-only entry with an optional PDF drop for grounding. Dispatch `POST /trainer/sessions/global`, per `docs/feature_10_trainer.md` Task 10.2.
- [ ] **Task 6.3: Existing Vendor Scope Entry**
  - Vendor dropdown (sourced from the tenant's known vendors) loads a real production invoice into the sandbox. Dispatch `POST /trainer/sessions/from-production?vendor_name=X`, per Task 10.3.
- [ ] **Task 6.4: New Vendor Scope Entry**
  - Carried over from the prior design: file uploader dispatches to `POST /trainer/upload`, renders the PDF on the left, per Task 10.4.
- [ ] **Task 6.5: Build Q&A Validation Panel**
  - Training chat panel on the right. Display the key-value extraction list alongside conversational bubbles.
  - Bind chat input to send corrections (e.g., *"No, read the date as DD-MM-YYYY"*) and update the extracted variables view dynamically. For Global-scope sessions, the panel has no extraction list to show until/unless a grounding PDF is present — chat input stays active regardless (see Gap 8 in the tracker).
- [ ] **Task 6.6: Scope-Aware Commit Handler**
  - `Commit to Template Registry` action dispatches to `POST /trainer/sessions/{session_id}/commit`, per Task 10.6.
  - On success, show a toast reflecting the scope: Global → "Queued re-audit across all vendors"; Existing Vendor → "Queued re-audit for {vendor}"; New Vendor → plain success, no re-audit toast.
- [ ] **Task 6.7: Rule History & Rollback Drawer**
  - List committed rule versions for the active template (Global or the selected vendor) with `changed_by` / `changed_at`, per Task 10.10.
  - `Rollback` action on a version calls `POST /trainer/templates/{id}/rollback/{version}`.
- [ ] **Task 6.8: Audit-Seeded Session Entry**
  - Accept a deep-link/query param carrying `{scope, field, sample_correction}` from the "Want to save this as a rule?" prompt (`feature_4_auditor.md` Task 4.7), per Task 10.11.
  - Pre-select the given scope, skip the vendor/PDF picker if already resolved, and pre-populate the chat with the sample correction instead of an empty session.

### P0 Fixes from live end-to-end testing (Jul 25, 2026)
This trainer code was only merged from a feature branch the day before (Jul 24) and had never been run against a live backend in a real browser until this pass. Three issues found and fixed:

* **Gap 23 — screen not cleared after commit, left pointing at a dead session**: the backend deletes the session immediately on commit, but `page.tsx::handleConfirmCommit()` never reset FE state — the same chat/PDF/variables stayed on screen looking live, so any further interaction with it would 404. Fixed: clear state per scope after a successful commit (Global auto-starts a fresh session, matching initial page-load behavior; Existing/New Vendor reset to their empty picker state).
* **Gap 24 — document viewer panel was a hardcoded mock, not the real document**: `PdfViewerPanel.tsx`'s "MODE 1" canvas rendered literal sample data (`"Acme Logistics Corp"`, `"INV-2026-00742"`) regardless of what was actually uploaded — its own code comment called it a "simulated invoice body." This defeated the whole point of the split-screen sandbox (visually comparing extraction against the source). Fixed: real `<iframe src={pdfUrl}>` render (works for both a freshly-uploaded file's client-side blob URL and the real backend-served invoice for Existing Vendor sessions) plus a live summary strip built from the session's actual `variables`.
* **Gap 25 — chat correction had no progress feedback during its ~25-30s round-trip**: a correction re-runs extraction (2 real sequential LLM calls: refine constraints, then re-extract), and the UI showed only a static "Refining rules..." spinner the whole time — long enough to look hung even though it wasn't (confirmed via network capture: the response always lands correctly, the UI just gave no sense of progress). Added a client-side elapsed-time-estimated progress bar + stage text ("Analyzing correction..." → "Re-extracting with updated rules..." → "Finalizing...") in `QnAPanel.tsx`, capped short of 100% until the real response arrives.

See `be_features_tracker.md` Gaps 50/51 and `fe_features_tracker.md` Gaps 23-25 for the full writeups.

### Gap 76 — Commit button clipped out of view (fixed 2026-07-31)

Reported live as "the Commit to Template Registry button appears clipped/not visible." Root cause was a container-sizing conflict, not anything in the header markup itself: `app/trainer/page.tsx`'s root was `h-screen` (100vh), but this page renders inside `Shell.tsx`'s `<main className="flex-1 overflow-y-auto p-8">`, which has already spent the global Header's 64px plus 32px of padding top and bottom. A 100vh child inside a container ~128px shorter than the viewport is taller than the space it actually has, so its own contents get pushed past the bottom edge.

Fixed by three changes in `app/trainer/page.tsx`:
1. Root `h-screen` → `h-full`, so the page sizes to its container rather than the viewport.
2. `min-w-0` on the title side and `shrink-0` on the actions side of the trainer's own `<header>`, plus `truncate` on the title text. The EVOLVE badge is `whitespace-nowrap`, so without these the title block could grow past the row and push the Commit button out *horizontally* — a second, independent path to the same reported symptom.
3. The EVOLVE badge is now `hidden sm:flex`, dropping it on very narrow viewports rather than letting decoration compete with an action button for space.

Measured before → after: Shell `<main>`'s scroll overflow on `/trainer` went from **178px to 1px** at 1280×720.

Worth recording how the symptom actually presents, because the obvious test for it doesn't catch it: at `scrollTop=0` the Commit button is on screen *even on the pre-fix code*, so a plain "is the button visible" assertion passes on the bug and proves nothing. The defect is that the page was taller than its container, making Shell's `<main>` scrollable on a screen designed not to scroll — so any scroll at all (wheel over the page frame, keyboard, or a browser restoring a prior scroll position) carries the header and its Commit button off the top. That intermittency is consistent with it being reported as "appears clipped" rather than as a reliably reproducible layout break.

**Left open deliberately:** this page still renders its own `<header>` even though `Shell`'s global `Header` sits directly above it, so `/trainer` shows two stacked header bars. That's arguably intentional (page-specific actions like Commit/Rule History don't belong in a global header), so it was not removed as part of a layout fix — flagged for a product decision instead. Related: Gap 88's broader IA critique of this screen.

Regression coverage: `e2e/group-a-layout-overflow.spec.ts`, 4 tests. Two are the load-bearing ones, deterministically failing pre-fix: *"Commit stays on screen after scrolling the page frame to the bottom"* (scrolls `<main>` to its end, then asserts the button is still fully in the viewport) and *"the page frame itself does not scroll"* (asserts `main.scrollHeight - main.clientHeight <= 2`). The other two check Commit/Rule History are fully inside the viewport on both axes at 1280×720 and 1024×768 — useful post-fix invariants, but weak as proof of *this* bug, since pre-fix they pass or fail depending on whether `<main>` happens to have been scrolled.

Note on the horizontal part of the fix (`min-w-0`/`shrink-0`/`hidden sm:flex`): the buttons were *not* measured overflowing the right edge at either tested width, so that change is defensive hardening against a second path to the same symptom, not a fix for a reproduced defect.

### Verification Plan
* **Manual Verification**: Create a Global rule with no vendor context and confirm it applies to a brand-new vendor's next upload. Load an Existing Vendor session, submit a correction, commit, and confirm the re-audit toast appears. Open the Rule History drawer and roll back a version.
