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

### Verification Plan
* **Manual Verification**: Create a Global rule with no vendor context and confirm it applies to a brand-new vendor's next upload. Load an Existing Vendor session, submit a correction, commit, and confirm the re-audit toast appears. Open the Rule History drawer and roll back a version.
