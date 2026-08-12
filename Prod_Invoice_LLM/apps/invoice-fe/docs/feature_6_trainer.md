# Feature 6: AI Trainer Interactive Sandbox — **EVOLVE Agent**

**EVOLVE** (Continuous Learning) powers this screen. Develop the rule-scope selector, training document loader, chat verification panel, and registry commit workflows.

*(Redesigned 2026-07-13 to match `docs/feature_10_trainer.md` — supersedes the previous flat "one uploader, one commit button" design. See Rule Scope Selector below.)*

### Rule Scope Selector *(redesigned Aug 12, 2026 — FE Gaps 220/221)*
The sandbox entry point is now two sections, not a 3-tab scope bar:
1. **Global Rules** — tenant-wide extraction rules. Sub-tabs: **Extraction Rules** (chat-only or optional PDF grounding) and **Chat Response Style** (length/tone/custom instructions via `ChatResponseStylePanel` → `POST commit-behavior`).
2. **Vendor Rules** — select an existing vendor from a dropdown **or** upload a new PDF. Sub-tabs: **Test Chat** (`qa_test` — routes to Chat/RAG, no rule mutation) and **Add Rules** (`rule_creation` — existing trainer correction flow).

Committing a Global or Existing Vendor session still queues re-audit per the rules above. `TrainerControlBar.tsx` replaces the old `ScopeSelector.tsx` 3-tab control; `ScopeSelector.tsx` is retained but no longer the primary entry UI.

### Rule Scope Selector (legacy — pre Aug 12, 2026)
The sandbox entry point was a 3-way choice, not a single uploader:
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
* Control Bar (Global / Vendor sections): [apps/invoice-fe/components/trainer/TrainerControlBar.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/TrainerControlBar.tsx)
* Chat Response Style panel: [apps/invoice-fe/components/trainer/ChatResponseStylePanel.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/ChatResponseStylePanel.tsx)
* Scope Selector (legacy): [apps/invoice-fe/components/trainer/ScopeSelector.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/ScopeSelector.tsx)
* Training Uploader: [apps/invoice-fe/components/trainer/TrainerUploader.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/TrainerUploader.tsx)
* Q&A Console: [apps/invoice-fe/components/trainer/QnAPanel.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/QnAPanel.tsx)
* Rule History Drawer: [apps/invoice-fe/components/trainer/RuleHistoryDrawer.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/trainer/RuleHistoryDrawer.tsx)
* Commit Confirmation Modal: `apps/invoice-fe/components/trainer/CommitModal.tsx`
* Document Viewer Panel: `apps/invoice-fe/components/trainer/PdfViewerPanel.tsx`
* Shared trainer API client: `apps/invoice-fe/lib/trainer-service.ts`
* Proxy Routes (**corrected 2026-08-01 — this section was badly stale**, all 8 exist and are live): `app/api/trainer/sessions/[id]/chat/route.ts`, `app/api/trainer/sessions/[id]/commit/route.ts`, `app/api/trainer/sessions/from-production/route.ts`, `app/api/trainer/sessions/global/route.ts`, `app/api/trainer/templates/[id]/rollback/[version]/route.ts`, `app/api/trainer/templates/history/route.ts`, `app/api/trainer/upload/route.ts`, `app/api/trainer/vendors/route.ts`. *(Aug 12, 2026 — added: `app/api/trainer/chat-style/route.ts`, `app/api/trainer/sessions/[id]/commit-behavior/route.ts`, `app/api/trainer/sessions/[id]/mode/route.ts`.)*

### Tasks
**Status corrected 2026-08-01**: all of Tasks 6.1–6.8 below were shown unchecked (`[ ]`), implying nothing was built — false, and self-contradicting given this same doc's own "P0 Fixes" and "Gap 76" sections below describe real bugs found and fixed in this already-shipped code. `fe_features_tracker.md` (the actual status source of truth) has correctly tracked this feature as built for some time; this doc's own checkboxes were simply never brought current. Marking `[x]` to match reality.
- [x] **Task 6.1: Build Rule Scope Selector**
  - Segmented control switching between Global / Existing Vendor / New Vendor. Switching scope resets the sandbox session state.
- [x] **Task 6.2: Global Scope Entry**
  - Chat-only entry with an optional PDF drop for grounding. Dispatch `POST /trainer/sessions/global`, per `docs/feature_10_trainer.md` Task 10.2.
- [x] **Task 6.3: Existing Vendor Scope Entry**
  - Vendor dropdown (sourced from the tenant's known vendors) loads a real production invoice into the sandbox. Dispatch `POST /trainer/sessions/from-production?vendor_name=X`, per Task 10.3.
- [x] **Task 6.4: New Vendor Scope Entry**
  - Carried over from the prior design: file uploader dispatches to `POST /trainer/upload`, renders the PDF on the left, per Task 10.4.
- [x] **Task 6.5: Build Q&A Validation Panel**
  - Training chat panel on the right. Display the key-value extraction list alongside conversational bubbles.
  - Bind chat input to send corrections (e.g., *"No, read the date as DD-MM-YYYY"*) and update the extracted variables view dynamically. For Global-scope sessions, the panel has no extraction list to show until/unless a grounding PDF is present — chat input stays active regardless (see Gap 8 in the tracker).
- [x] **Task 6.6: Scope-Aware Commit Handler**
  - `Commit to Template Registry` action dispatches to `POST /trainer/sessions/{session_id}/commit`, per Task 10.6.
  - On success, show a toast reflecting the scope: Global → "Queued re-audit across all vendors"; Existing Vendor → "Queued re-audit for {vendor}"; New Vendor → plain success, no re-audit toast.
- [x] **Task 6.7: Rule History & Rollback Drawer**
  - List committed rule versions for the active template (Global or the selected vendor) with `changed_by` / `changed_at`, per Task 10.10.
  - `Rollback` action on a version calls `POST /trainer/templates/{id}/rollback/{version}`.
- [x] **Task 6.8: Audit-Seeded Session Entry**
  - Accept a deep-link/query param carrying `{scope, field, sample_correction}` from the "Want to save this as a rule?" prompt (`feature_4_auditor.md` Task 4.7), per Task 10.11.
  - Pre-select the given scope, skip the vendor/PDF picker if already resolved, and pre-populate the chat with the sample correction instead of an empty session.

### P0 Fixes from live end-to-end testing (Jul 25, 2026)
This trainer code was only merged from a feature branch the day before (Jul 24) and had never been run against a live backend in a real browser until this pass. Three issues found and fixed:

* **Gap 23 — screen not cleared after commit, left pointing at a dead session**: the backend deletes the session immediately on commit, but `page.tsx::handleConfirmCommit()` never reset FE state — the same chat/PDF/variables stayed on screen looking live, so any further interaction with it would 404. Fixed: clear state per scope after a successful commit (Global auto-starts a fresh session, matching initial page-load behavior; Existing/New Vendor reset to their empty picker state).
* **Gap 24 — document viewer panel was a hardcoded mock, not the real document**: `PdfViewerPanel.tsx`'s "MODE 1" canvas rendered literal sample data (`"Acme Logistics Corp"`, `"INV-2026-00742"`) regardless of what was actually uploaded — its own code comment called it a "simulated invoice body." This defeated the whole point of the split-screen sandbox (visually comparing extraction against the source). Fixed: real `<iframe src={pdfUrl}>` render (works for both a freshly-uploaded file's client-side blob URL and the real backend-served invoice for Existing Vendor sessions) plus a live summary strip built from the session's actual `variables`.
* **Gap 25 — chat correction had no progress feedback during its ~25-30s round-trip**: a correction re-runs extraction (2 real sequential LLM calls: refine constraints, then re-extract), and the UI showed only a static "Refining rules..." spinner the whole time — long enough to look hung even though it wasn't (confirmed via network capture: the response always lands correctly, the UI just gave no sense of progress). Added a client-side elapsed-time-estimated progress bar + stage text ("Analyzing correction..." → "Re-extracting with updated rules..." → "Finalizing...") in `QnAPanel.tsx`, capped short of 100% until the real response arrives.

See `be_features_tracker.md` Gaps 50/51 and `fe_features_tracker.md` Gaps 23-25 for the full writeups.

### Gap 90 — missing production sample PDF (closed 2026-08-04)

An Existing Vendor session grounds itself on the vendor's latest production invoice, served through `/api/invoices/{id}/pdf` (built by `routers/trainer.py::_serialize_session`). If that blob is gone — e.g. Azurite storage lost across a `docker compose` restart while Postgres survived on its named volume — the pane used to render the backend's raw error JSON (`{"detail":"Failed to retrieve invoice PDF."}`) verbatim, in place of the document.

Both halves of that are now fixed: the backend returns a proper `404` for a missing blob (the Azure SDK's `ResourceNotFoundError` is *not* a Python `FileNotFoundError`, which is exactly why the original catch clause missed it), and `PdfViewerPanel.tsx` probes with `fetch(pdfUrl, {method:"HEAD"})` before rendering the iframe, showing a "Document Unavailable" card instead.

**One non-obvious property of that probe, worth knowing before touching either side.** It only treats a `404` as "missing" and a `>= 500` as "failed"; any other non-ok status is treated as an *inconclusive probe* and the iframe renders anyway. That is deliberate, not defensive noise: the backend route is `@router.get`-only, and FastAPI's `APIRouter` — unlike a bare Starlette `Route`, which adds HEAD alongside GET — does not accept HEAD, so a direct HEAD to the backend is a **405**. The browser's HEAD succeeds only because Next 14 auto-implements HEAD by invoking the exported `GET`, and `app/api/invoices/[id]/pdf/route.ts` forwards a hardcoded `method: "GET"` inward. If that proxy is ever changed to forward the caller's real method, every probe becomes a 405 — and under a naive `!res.ok` check the Trainer would claim "Document Unavailable" for every perfectly good PDF. Pinned by `invoice-be/tests/test_queries.py::test_stream_pdf_is_get_only_and_405s_a_direct_head`.

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

### Gaps 170 & 171 — New Vendor identity and dead chat input (closed 2026-08-06)

**Gap 170 — the New Vendor flow never learned its own vendor's name.** A New Vendor session's vendor is discovered by the backend, not chosen by the user: `routers/trainer.py::upload_transient_file` pulls `vendor_name` out of the extraction result and `_serialize_session` returns it. `page.tsx` never read it, so `selectedVendorName` — which is what `CommitModal`, `RuleHistoryDrawer` and `getRuleHistory` all key off — stayed `""` for the entire flow. Since `GET /templates/history` resolves an empty `vendor_name` to the tenant's **Global** template, Rule History confidently displayed Global's timeline as if it were the new vendor's. `handleUploadFile` now stores `newSess.vendorName` the same way `handleSelectVendor` does, and names the detected vendor in its toast. Scoped to `new_vendor` deliberately: a Global session can also carry a vendor name from its grounding PDF, and tenant-wide rules must not start keying off whichever sample happened to be uploaded. Two guards followed from it: `handleScopeChange` falls back to a known vendor when switching to Existing Vendor (a just-detected new vendor has no production invoices to load), and `handleOpenHistory` refuses a vendor-scoped history request with no vendor name rather than letting the backend silently answer with Global.

**Gap 171 — the chat swallowed corrections when no session existed.** `session` is legitimately null in two ordinary states (New Vendor before a PDF is uploaded; Existing Vendor with no vendor selected), and `QnAPanel` had no awareness of it: it accepted the text, cleared the input as though it had been sent, and `handleSendMessage` dropped it on a bare early return — no toast, no restored text, nothing. `page.tsx` now derives a `chatDisabledReason` (null when usable, otherwise the scope-specific blocker) and passes it as `QnAPanel`'s new `disabledReason` prop. While it is set, the input, send button and suggestion chips are all disabled, the reason is the placeholder/tooltip and is shown inline above the input in the amber "not ready" treatment, and `handleSend` only clears the field after the message has actually been handed over — so nothing typed can be lost. The early return in `handleSendMessage` remains as a backstop for chip clicks and future callers, but now raises an error toast naming the same reason.

### Gap 139 — session loading feedback in the document panel (closed 2026-08-12)

**The symptom.** Uploading a New Vendor sample, or picking a vendor for an Existing Vendor session, changed nothing on screen for the whole round-trip — and that round-trip is real work: `routers/trainer.py` runs `_run_ocr_split` plus `run_extraction_agent` synchronously inside the request. A slow-but-working load and a genuinely stuck one were indistinguishable, which is how it was reported ("new vendor not uploading pdf, neither showing processing").

**Why there was nothing to fix in the upload path.** The proxy routes and backend endpoints were confirmed correct; the defect was purely that no handler tracked a loading state and `PdfViewerPanel` had no mode in which to show one. Chat already did this properly — `handleSendMessage`/`isSending` driving `QnAPanel`'s staged progress indicator — so the fix reuses that, rather than introducing a second loading idiom on one screen.

**What was built.**
* `app/trainer/page.tsx` holds `isLoadingSession` and `loadingFileName`. Both are set around the `await` in `handleUploadFile` (which names the file), `handleSelectVendor`, `handleClearFile`, and — beyond the original plan — `handleScopeChange`, because switching into Existing Vendor auto-selects a vendor and performs the same `from-production` load; omitting it would have left the frozen window intact on the most common way into that scope. `handleSelectVendor` and `handleScopeChange` also null the outgoing `session` before awaiting, so the loading panel never sits on top of the vendor the user just navigated away from. Every setter is in a `finally`, so a failed load returns to a usable panel rather than a permanent spinner.
* `PdfViewerPanel.tsx` takes `isLoadingSession` / `loadingFileName` and gains **MODE 0**, checked ahead of both existing modes. It renders a spinning badge, the filename in flight, and `QnAPanel`'s exact indicator — three `animate-bounce` dots, a named stage, a percentage, and a progress bar — over the same ambient-glow card treatment MODE 2 already uses. Progress is the same client-side elapsed-time estimate `QnAPanel` documents (asymptotic to 92%, completion only when the response actually lands), with a 32s constant instead of 28s because this call is OCR plus extraction rather than two chat LLM calls. Stage names are derived from `scope` and whether a file is being uploaded, so no additional prop was needed: "Uploading document… / Running OCR and page split… / Extracting fields… / Finalizing…" for an upload, "Fetching production invoice…" for Existing Vendor, "Clearing grounding document…" for the clear-file path.
* `chatDisabledReason` gained a loading branch. Clearing `session` up front would otherwise have made the chat panel tell the user to select a vendor they had just selected.

**Deliberately out of scope**: OCR/extraction remains synchronous on the backend. Making it async/backgrounded is an architecture change; this gap is the loading-indicator UX only, and the copy under the progress bar sets the expectation honestly ("this can take up to a minute for a dense invoice") rather than implying the wait was removed.

**Regression coverage**: `e2e/trainer-loading-state.spec.ts`, 2 tests, both passing. Each stubs the session-create route with a fixed delay (the assertion is about what shows *during* a known-length wait, which a real OCR round-trip cannot make deterministic), then drives a real upload via the file input and a real vendor `selectOption`, asserting the panel appears with its stage text, percentage and filename and is gone once the session lands. Navigation is retried inside `gotoTrainer()` — the first hit on `/trainer` in a run can be aborted by the Next dev server mid-compile, which is a dev-server artefact rather than a product behaviour.

### Gaps 220 & 221 — Trainer UI restructure + Chat Response Style (closed 2026-08-12)

**Gap 220 — section-based layout replaces 3-tab scope selector.** `TrainerControlBar.tsx` now exposes **Global Rules** and **Vendor Rules** sections. Vendor Rules: pick existing vendor from dropdown OR upload new PDF. Vendor sub-tabs **Test Chat** (`qa_test`) and **Add Rules** (`rule_creation`) call `PUT /api/trainer/sessions/{id}/mode` via `lib/trainer-service.ts::setSessionMode()`.

**Gap 221 — Chat Response Style panel.** Global Rules → **Chat Response Style** sub-tab renders `ChatResponseStylePanel.tsx` (length/tone toggles, custom instructions textarea, amber disclaimer banner). Save calls `POST /api/trainer/sessions/{id}/commit-behavior` through new proxy routes.

**BE Gap 217 — structured commit rejection.** `app/trainer/page.tsx` commit failure toast surfaces `flagged_rule` and `rejection_reason` from the backend's structured 400 body.

### Verification Plan
* **Manual Verification**: Create a Global rule with no vendor context and confirm it applies to a brand-new vendor's next upload. Load an Existing Vendor session, submit a correction, commit, and confirm the re-audit toast appears. Open the Rule History drawer and roll back a version.
