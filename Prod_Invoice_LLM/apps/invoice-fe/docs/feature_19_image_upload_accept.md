# Feature 19: Image Upload Accept (FE half of BE Feature 28)

Status lives in `docs/fe_features_tracker.md`. Backend design and the conversion itself: [feature_28_image_upload_pdf_boundary.md](../../invoice-be/docs/feature_28_image_upload_pdf_boundary.md). Scoped 2026-09-04.

### Overview

Let the browser offer image files (PNG/JPG/JPEG/TIFF/WEBP/BMP) wherever it offers PDFs today. The FE does no conversion and no format sniffing; the backend converts at the door and the FE keeps sending bytes as it does now.

**No flag (BE decision D1).** Feature 28 ships unconditionally, so there is no `ENABLE_IMAGE_UPLOAD_CONVERSION` to read and no fail-closed state for this list: the image suffixes are always offered.

Not to be confused with FE Gap 378 / BE Feature 27 G11, which already widened `DropZone` on `ENABLE_GENERIC_EXTRACTION`. That flag and its extension list stay exactly as they are; this feature adds an always-on base list beneath it, so the two compose instead of competing.

### File Coordinates

| Path | Named function / component | New or edit | What it does |
|---|---|---|---|
| `lib/featureFlags.ts` | `IMAGE_UPLOAD_EXTENSIONS` (new const), `acceptedUploadExtensions(flags)` | edit | Returns the union of `IMAGE_UPLOAD_EXTENSIONS` (always: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.webp`, `.bmp`) and `GENERIC_EXTRACTION_EXTENSIONS` when `ENABLE_GENERIC_EXTRACTION` is on. De-duplicated, `.pdf` first. The `flags` argument stays because the generic-extraction flag still matters; a null or failed fetch now degrades to the always-on image list, not to `.pdf` alone, because the backend accepts images regardless of what the flag fetch says. |
| `lib/featureFlags.ts` | `invalidFormatMessage(extensions)` | unchanged | Already derives its copy from the list. |
| `components/ingestion/DropZone.tsx` | `DropZone` | edit (copy only) | The accept logic needs **no** change: it already reads `acceptedUploadExtensions()` for both the `accept` attribute and the suffix guard, so it picks up the wider list for free. What changes is its copy — see the two rows below and the copy audit. Both Receiving and Sending tabs use it. |
| `components/trainer/TrainerUploader.tsx` | `TrainerUploader` | edit | Replace hard-coded `accept=".pdf,application/pdf"` (L141) and its suffix check with `acceptedUploadExtensions(loadFeatureFlags())`, same `useEffect` + `cancelled` pattern as `DropZone`. |
| `components/trainer/TrainerEntryPanel.tsx` | `TrainerEntryPanel` | edit | Same at L293. |
| `components/ingestion/StatusTable.tsx`, `SendInvoiceStatusTable.tsx` | row filename cell | unchanged | The backend returns the `.pdf`-rewritten filename; nothing to do. |
| `app/ingestion/page.tsx` | folder-picker handler (~L567–575) | edit | The "select a folder" path filters `selectedList` by `application/pdf` / `.pdf` and reports "No PDF files found in selected folder." Filter by `acceptedUploadExtensions()` instead; message built from the same list. |
| `lib/featureFlags.ts` | `acceptedFormatsLabel(extensions)` | new | Copy helper: `"PDF"` for the PDF-only list, `"PDF, PNG, JPG, TIFF, WEBP or BMP"` otherwise. Every string in the copy audit below reads from it so the words on screen and the accept list cannot disagree. |
| `components/ingestion/DropZone.tsx` | conversion hint line | edit | Adds one line under the accept text: "Photos and scans are converted to PDF automatically." Founder decision, 2026-09-04 — it explains why a photo later appears in the ledger under a `.pdf` filename. |
| `e2e/ingestion-image-upload.spec.ts` | — | new | Playwright: the picker accepts a `.png` and the upload proxy is called; a `.gif` is rejected with the accepted-formats message. |

#### Copy audit — every user-facing "PDF" string (grep of `app/`, `components/`, `lib/` on 2026-09-04)

Strings that describe **what the user may upload** change to read from `acceptedFormatsLabel()`. Strings that describe **what the system stores or shows** stay "PDF" — after Feature 28 every stored file *is* a PDF, so those are still true.

| Location | Current text | Action |
|---|---|---|
| `components/ingestion/DropZone.tsx:183` | "Drag & drop invoice PDFs here, or browse" | → "Drag & drop invoices here, or browse" |
| `components/ingestion/DropZone.tsx:186` | "Accepts PDF documents only. Max size 25MB." | → `Accepts ${label}. Max size 25MB.` |
| `lib/featureFlags.ts:96` | "Invalid file format. Only PDF documents are allowed." | already list-driven; unchanged |
| `app/ingestion/page.tsx:575` | "No PDF files found in selected folder." | → `No ${label} files found in selected folder.` |
| `components/trainer/TrainerEntryPanel.tsx:276` | "Upload a PDF" | → "Upload a sample invoice" |
| `components/trainer/TrainerEntryPanel.tsx:290` | "Browse PDF" | → "Browse" |
| `components/trainer/TrainerUploader.tsx:138` | "Change PDF" / "Browse PDF" | → "Change file" / "Browse" |
| `components/trainer/ScopeSelector.tsx:79` | "Upload a fresh sample PDF to begin." | → "Upload a fresh sample invoice to begin." |
| `app/trainer/page.tsx:557` | "Pick an invoice or upload a PDF first." | → "Pick an invoice or upload a sample first." |
| `app/help/content/trainer-guide.tsx:137,143,149` | "Upload a sample invoice PDF…", "Check the summary against the PDF", caption | → "sample invoice (PDF or photo)"; the viewer references stay "PDF" |
| `app/help/content/inbound-email-guide.tsx:63` | "Send/forward supplier PDF invoices…" | → "…supplier invoices (PDF or image attachments)…" |
| `app/help/content/outbound-email-guide.tsx:62` | "Email your own invoice PDFs…" | → "…your own invoices (PDF or image)…" |
| `app/admin/page.tsx:81` | dropped-email reason label "No PDF attached" | → "No invoice attachment" (BE reason constant unchanged, see BE 28.6) |
| `components/connectors/IntegrationCard.tsx:127` | "Where supplier PDFs are picked up from" | → "Where supplier invoices are picked up from" |
| `app/flows/page.tsx:63–66, 209–215` | "PDF Upload" nodes and explainers on the Flows diagram | → "Invoice Upload"; the "Loading PDF from Blob Storage" step stays (it is a PDF by then) |
| `app/invoices/review/[id]/page.tsx:1299` | "Illegible Document (Blurred PDF / Corrupted file)" | → "Illegible Document (Blurred scan / Corrupted file)" |
| `components/dashboard/RecentInvoicesTable.tsx:98` | "…permanently removes the PDF, extracted data…" | unchanged (stored file is a PDF) |
| `components/chat/ChatWindow.tsx:503`, `lib/chatAttachments.ts:44,255,258,347` | chat attachment copy and `.pdf` accept | **unchanged** — chat attachments are Feature 27's path, deliberately outside Feature 28 (BE D5) |
| `app/settings/workflows/page.tsx:313` | curl sample `-F "file=@invoice.pdf"` | unchanged (valid example) |
| `invoice-website/components/marketing/Hero.tsx:330` | "PDF · 340KB" demo chip | unchanged; website copy is out of scope here |

### Functionality

On mount `DropZone`/`TrainerUploader`/`TrainerEntryPanel` call `loadFeatureFlags()` (one request per page, cached). `acceptedUploadExtensions()` builds the accept list; the `<input accept>` and the drag-and-drop suffix guard read the same array so they cannot disagree (the property FE Gap 378 established). A selected image is appended to `FormData` and posted to the existing proxy (`/api/invoices/upload`, `/api/outbound-invoices/upload`, `/api/trainer/upload`) unchanged. The response is unchanged, so status polling, SSE and the review pages are untouched. The 25 MB `MAX_FILE_SIZE` stays; the backend's pixel cap is the second guard.

#### As built (2026-09-04)

Built as designed, with four things worth recording because they are not what the
File Coordinates table above would lead a reader to expect.

1. **`acceptedUploadExtensions()` is a de-duplicated union, and `GENERIC_EXTRACTION_EXTENSIONS`
   turns out to be the same set as `IMAGE_UPLOAD_EXTENSIONS`.** Feature 27's list is
   `.pdf .png .jpg .jpeg .tiff .tif .bmp .webp` — the same eight suffixes in a different
   order. So today the flag changes the accept list by nothing at all, and the union is
   the eight-item base list either way. The union is still written as a union rather than
   collapsed: the two lists answer different questions (what the converter takes vs. what
   the generic extractor takes) and either may move independently. `Array.from(new Set(...))`
   with the image list first keeps `.pdf` in position 0 whatever the flag says.
2. **`acceptedFormatsLabel()` folds format aliases.** `.jpeg`→JPG and `.tif`→TIFF via
   `FORMAT_LABEL_ALIASES`, so the eight suffixes render as six names,
   `"PDF, PNG, JPG, TIFF, WEBP or BMP"` — not "JPG, JPEG, TIF, TIFF", which reads as four
   formats. The alias map, not the accept array, is the thing to edit if a format's display
   name changes.
3. **`app/ingestion/page.tsx` needed its own `loadFeatureFlags()` effect.** The folder picker
   is a *third* file entry point, outside `DropZone`, so it could not inherit the component's
   flag state; it now runs the same `useEffect` + `cancelled` shape and filters/messages off
   the same helper.
4. **Two stale code comments were corrected alongside the visible copy** — the
   `TrainerEntryPanel` header comment's "**Upload a PDF**" and `ScopeSelector`'s
   "Browse PDF button" reference both named UI labels this feature renamed. Not user-facing,
   but they are what the 19.3 repo grep finds, and a comment that names a button that no
   longer exists is how the next reader is misled.

**`e2e/feature27-doc-type.spec.ts` was edited, and this is the change to look at hardest.**
That spec asserted `accept=".pdf"` exactly, and asserted a dragged `.png` produced
"Invalid file format. Only PDF documents are allowed." Both assertions were *correct for
Feature 27* and are false under Feature 28, which offers images with no flag. They were
**inverted rather than deleted**: the block now asserts every `ENABLE_GENERIC_EXTRACTION`
suffix is still present in `accept` (composition, not replacement — the property Feature 27
actually depends on), and a **new** second test moves the rejection case to `.gif`, a format
in neither list, so the "both guards agree and something is still refused" claim survives.
Net test count in that file went 6 → 7; nothing Feature 27 relies on lost coverage.

### Data & schema changes

None.

### Tasks

- [x] **19.1** `lib/featureFlags.ts`: `IMAGE_UPLOAD_EXTENSIONS` + union logic in `acceptedUploadExtensions()`; unit test for both `ENABLE_GENERIC_EXTRACTION` states and for a failed flag fetch.
- [x] **19.2** `TrainerUploader.tsx` and `TrainerEntryPanel.tsx` onto the shared helper.
- [x] **19.3** `acceptedFormatsLabel()` + the copy audit rows marked "→" above (DropZone, ingestion folder picker, Trainer panel/uploader/scope selector/page, Flows diagram, review-page reason option, IntegrationCard, admin drop-reason label).
- [x] **19.4** Help Center copy: the three guide files in the audit.
- [x] **19.5** `e2e/ingestion-image-upload.spec.ts`.

### Verification Plan

Runs recorded 2026-09-04, `Prod_Invoice_LLM/apps/invoice-fe`. **invoice-fe has no Jest and no
vitest** — `@playwright/test` is the only runner in `package.json`. The "unit tests" below are
therefore pure-module assertions that import `lib/featureFlags.ts` directly and are executed by
Playwright in the same file as the browser passes, the split
`e2e/chat-attachment-contract.spec.ts` already uses. Deviation from the plan's wording, not from
its intent.

| Task | Check | Result |
|---|---|---|
| 19.1 | Table test: `{}`, `null`, `{ENABLE_GENERIC_EXTRACTION:false}` → `.pdf` plus the seven image suffixes; flag on → union with Feature 27's list, no duplicates, `.pdf` first. | **PASS.** `npx playwright test e2e/ingestion-image-upload.spec.ts` → `10 passed (31.5s)`; the three `acceptedUploadExtensions()` tests cover all three flag states and the union. |
| 19.2 | Playwright: Trainer upload input's `accept` equals the helper output under a mocked `/api/config/features`. | **PASS.** Same run, "the trainer upload input › uses the same helper output as the drop zone" — `accept` equals `.pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp`, and "Upload a sample invoice" is on screen. |
| 19.3 | Unit: `acceptedFormatsLabel([".pdf"])` → `"PDF"`; full list → `"PDF, PNG, JPG, TIFF, WEBP or BMP"`. Playwright: DropZone reads "Accepts …" plus the conversion hint. Repo grep of the "→" literals → zero hits. | **PASS.** Same run, three `acceptedFormatsLabel()` tests + "offers the image suffixes and says so, with the conversion hint". Grep of all 15 audited literals across `app/ components/ lib/` → 0 hits each (two code-comment hits found and fixed first, see As built §4). |
| 19.4 | Manual read of the three Help Center pages; `searchText` updated so help search still matches "pdf". | **PASS (manual).** `trainer-guide.tsx`, `inbound-email-guide.tsx`, `outbound-email-guide.tsx` read end-to-end in diff; every touched `searchText` retains `pdf` and gains `photo`/`scan`/`image`. |
| 19.5 | Playwright spec; **plus** a run against the dev stack with a real PNG confirming a `.pdf`-named row in the ledger. | **PARTIAL — this is why the tracker row is `[~]`.** Spec passes: `10 passed (31.5s)` (6 module + 4 browser, all API routes stubbed). The **real-PNG dev-stack run is NOT done**: it asserts BE Feature 28's conversion and `.pdf` filename rewrite, which is being built concurrently and is not deployed. Owed once BE 28 lands. |
| Regression | Feature 27's spec still green after its accept-list assertions were inverted. | **PASS.** `npx playwright test e2e/feature27-doc-type.spec.ts --workers=1` → `7 passed (40.3s)`. |
| Type safety | Whole app compiles. | **PASS.** `npx tsc --noEmit` → no output (clean). |

**Flake note.** The first full-file run of `ingestion-image-upload.spec.ts` failed 3 of 10 on
the Next **dev** server: three parallel workers compiling `/ingestion` and `/trainer` on demand
starved the slowest page and the file input was "not found" after 90 s. Each of the three passed
in isolation. The file is now `test.describe.configure({ mode: "serial" })` with that reasoning
written above it — recorded here because "it passed the second time" is exactly the shape of a
result that should not be taken on trust.

### Founder decisions (2026-09-04)

- **Show the conversion hint.** `DropZone` carries one line, "Photos and scans are converted to PDF automatically.", under the accept text. Ruled in favour of explaining the `.pdf` filename the user later sees in the ledger.
- **No flag** (inherited from BE decision D1): the image suffixes are always offered, and a failed `/config/features` fetch no longer degrades this list to PDF-only.
