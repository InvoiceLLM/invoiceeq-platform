# Feature 28 — Non-PDF Invoice Upload (Image → PDF at the Boundary)

Status lives in `docs/be_features_tracker.md`. This document is the durable design record.
Scoped 2026-09-04 from `docs/phase_2_enhancements.md` item 2; the founder ruled all five open decisions the same day (§8). FE half: `apps/invoice-fe/docs/feature_19_image_upload_accept.md`.

Collision check at creation time (2026-09-04): max BE feature doc is 27 (`feature_27_generic_extraction.md`); max FE feature is 18 (19 and 20 are claimed by this feature's FE half and by Feature 17's). **28 is free.** No Gap is filed by this spec — it is design only; Gap numbers are re-checked at build time (repo-wide max at time of writing: 455).

## 1. Overview

Today every invoice entry point rejects anything that is not a `.pdf` with a `%PDF` header. Tenants routinely have invoices as photos or scans (JPG/PNG from a phone, TIFF from a scanner). This feature accepts those formats by **converting the image to a PDF once, at the moment it enters the system**, so that everything downstream — Blob storage (`tenants/{tenant}/invoices/{id}.pdf`), `_run_ocr()`, the extraction graph, `GET /invoices/{id}/pdf`, `PdfViewerCanvas`, Drive write-back, dedup hashing — continues to see exactly one format. Nothing downstream learns about images.

**No feature flag (D1).** This ships on for every deployment. There is no `ENABLE_IMAGE_UPLOAD_CONVERSION`, no `/config/features` key, and no flag-off branch to keep in sync. A PDF's path through the system is unchanged and byte-identical either way, so the flag would have gated only the widened accept list — a capability with no half-state worth preserving. The consequence to accept knowingly: rolling this back means a redeploy, not a setting.

**What this is not, and the one naming collision.** Feature 27 §4 ("Non-PDF image support") already taught the *extraction* path to read images natively: `agents/extraction_agent.py::document_to_base64_images()` dispatches on suffix and is reachable only on the flag-ON (`ENABLE_GENERIC_EXTRACTION`) graph, and FE Gap 378 widened `DropZone`'s accept list on the same flag. That work is **not** superseded and is not touched. It is also not sufficient: every upload router (`routers/invoices.py:384`, `routers/outbound_invoices.py:107`, `routers/trainer.py:606`, `routers/email_ingestion.py:452`) still hard-rejects non-PDF before any of it runs, `services/storage.py` always writes `{id}.pdf`, and the viewer streams `application/pdf`. Feature 27's approach (teach consumers) and this feature's approach (normalise at the door) are complementary: after this feature, an image never reaches `document_to_base64_images()` from an invoice upload because it is already a PDF by then. `document_to_base64_images()` keeps its image branch for the caller that still needs it — `routers/chat_attachments.py` (Gap 446), which stores reference documents as-is and is **deliberately left alone** (D5: a reference document is not an invoice and never enters the pipeline).

Not in scope: HEIC/HEIF, Office documents, multi-image "one invoice = several photos" stitching, any change to the extraction prompts, the chat-attachment path above, and anything about the `ollama` provider (D4 — this feature targets the Azure Document Intelligence path and adds no provider branch).

## 2. File Coordinates

| Path | Named function / component | New or edit | What it does |
|---|---|---|---|
| `services/file_intake.py` | `sniff_format(data: bytes) -> str \| None` | new | Magic-byte detection: `%PDF`, PNG (`\x89PNG`), JPEG (`\xff\xd8\xff`), TIFF (`II*\x00` / `MM\x00*`), WEBP (`RIFF….WEBP`), BMP (`BM`). Returns a canonical suffix or `None`. Never trusts the client filename or `content_type`. |
| `services/file_intake.py` | `ACCEPTED_IMAGE_SUFFIXES: frozenset` = `{".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}`; `ACCEPTED_UPLOAD_SUFFIXES = {".pdf"} \| ACCEPTED_IMAGE_SUFFIXES` | new | Single source of truth for what the door accepts. Every router imports this; no router keeps its own `.endswith(".pdf")`. |
| `services/file_intake.py` | `convert_image_to_pdf(data: bytes, fmt: str) -> bytes` | new | Pure function. Opens the image with `fitz.open(stream=data, filetype=fmt)`, one PDF page per image frame (multi-page TIFF → multi-page PDF), page size = pixel size at 72 dpi (so the Document Intelligence coordinates map 1:1 to the rendered page), writes with fixed metadata (`creationDate`/`modDate` = epoch constant, `producer`="invoice-intake") and `garbage=4, deflate=True` so the same input bytes always yield the same output bytes (required for dedup, see §3). Enforces `MAX_IMAGE_PIXELS = 50_000_000` via Pillow's decompression-bomb check before handing to fitz. |
| `services/file_intake.py` | `normalize_upload(filename: str, data: bytes) -> NormalizedUpload` | new | The one call every entry point makes. Returns a dataclass `NormalizedUpload(pdf_bytes, pdf_filename, source_format, was_converted)`. Rules: sniffed `pdf` → passthrough unchanged (byte-identical to today's path); sniffed image → `convert_image_to_pdf`, filename suffix rewritten to `.pdf`; sniffed `None` → `UnsupportedUploadError`. Filename and byte disagreement is always resolved in favour of the bytes. Raises `UnsupportedUploadError(detail)` / `ImageTooLargeError(detail)` — plain exceptions, mapped to HTTP by the routers. |
| `services/file_intake.py` | `ACCEPTED_FORMATS_DETAIL: str` | new | The literal `"Only PDF, PNG, JPG, TIFF, WEBP or BMP is allowed."`, used in every 400 so the five doors cannot describe different rules. Replaces today's `"Only PDF is allowed."`. |
| `routers/invoices.py` | `upload_invoices()` | edit | Replace the two-loop `.endswith(".pdf")` + `startswith(b"%PDF")` validation (L381–406) with one loop calling `normalize_upload()`; `payloads` receives `(pdf_filename, pdf_bytes)`. Everything after (Gap 189 billing, `_ingest_single_file`) is untouched. |
| `routers/invoices.py` | `start_directory_watcher()` | edit | Directory listing filter (L483) widens from `.pdf` to `ACCEPTED_UPLOAD_SUFFIXES`; each file is read then passed through `normalize_upload()` before `_ingest_single_file`. |
| `routers/outbound_invoices.py` | `upload_outbound_invoice()` | edit | Same substitution at L107 and L128. |
| `routers/trainer.py` | `upload_transient_file()` | edit | Same substitution at L606 and L616; the transient file is still written as `{session_id}.pdf` so `get_session_pdf()` and `_run_ocr_split` are unchanged. |
| `routers/email_ingestion.py` | `sendgrid_inbound_webhook()` attachment filter | edit | `pdf_files` selection (L452) becomes "attachments whose sniffed format is accepted"; the `REASON_NO_PDF_ATTACHMENT` drop reason keeps its constant name (it is persisted and reported on) but its detail text becomes "none of them a PDF or supported image". Each attachment is normalised before `_ingest_single_file` / `_ingest_outbound_email_pdf`. |
| `utils/connector_files.py` | `list_google_drive_files()` | edit | Drive query `mimeType = 'application/pdf'` becomes an `or` over `application/pdf` + `image/png` + `image/jpeg` + `image/tiff` + `image/webp` + `image/bmp` (D3: for every tenant, no opt-in). The returned dict gains `mime_type` so the file browser can show it. |
| `services/autopilot_sync.py` | Drive sync loop (around L328) | edit | After `download_google_drive_file`, call `normalize_upload(file_name, file_bytes)` before hashing/quota/`upload_pdf_to_blob_storage`. `content_hash` is computed on the **normalised** bytes (see §3). |
| `queue_worker/handlers.py` | connector import handler (around L695) | edit | Same `normalize_upload()` call before the blob write; `file_name` already ends `.pdf`. |
| `tests/test_file_intake.py` | — | new | Unit tests for §6. |
| `tests/test_invoice_upload_formats.py` | — | new | Router-level tests for §6 (all five entry points). |

Unchanged on purpose: `config.py` (no flag, D1), `services/storage.py` (still receives PDF bytes only), `queue_worker/handlers.py::_run_ocr()`, `agents/extraction_agent.py`, `routers/chat_attachments.py`, `routers/config_features.py`, `GET /invoices/{id}/pdf`.

## 3. Functionality

**Entry.** A file arrives at any of the five doors: multipart upload (inbound or outbound), Trainer sample upload, SendGrid inbound email attachment, Google Drive (manual connector import or Autopilot sync), or the server-side directory watcher.

**Normalisation.** The door calls `normalize_upload(filename, bytes)`.
1. `sniff_format` reads the first bytes. Client filename and `content_type` are advisory only; a `.pdf`-named PNG is treated as a PNG, a `.jpg`-named PDF as a PDF. This closes the existing gap where the filename check and the `%PDF` check could disagree (Gap 355's two-step validation is subsumed).
2. PDF → returned as-is. The path a PDF takes after this feature is byte-for-byte the path it takes today.
3. Image → `convert_image_to_pdf`. PyMuPDF (`pymupdf>=1.28.0`, already a dependency) renders each frame onto a page whose size equals the image's pixel size in points, so nothing is rescaled and Document Intelligence's returned polygons line up with what `PdfViewerCanvas` draws. Metadata is pinned so the output is deterministic. Multi-page TIFF produces a multi-page PDF; a JPEG produces one page. Pillow's pixel cap rejects decompression bombs before fitz allocates anything.
4. Anything else → `UnsupportedUploadError`, surfaced as a 400 carrying `ACCEPTED_FORMATS_DETAIL`.

**Two size ceilings, not one (BE Gap 458, found and fixed during the build).** `MAX_IMAGE_PIXELS` (50 M) is read from the image header before any decode, so an oversized file is refused without allocating its pixels — but Pillow independently refuses anything above roughly twice its *own* `Image.MAX_IMAGE_PIXELS` (~89 M) from inside `Image.open()`, before `probe.size` can be read. As first written, that `DecompressionBombError` fell through to the malformed-file handler and came back as `UnsupportedUploadError`: a valid but enormous PNG was told its *format* was wrong. `_frames_as_streams()` now catches `Image.DecompressionBombError` explicitly and re-raises `ImageTooLargeError`, so both ends of the range report the same, true reason.

**Storage and identity.** The door then proceeds exactly as today with `(pdf_filename, pdf_bytes)`: `_ingest_single_file` / the outbound router hash the bytes, check `Invoice.file_hash` (and `Document.file_hash`, BE Gap 385) for duplicates, charge quota, write `tenants/{tenant}/invoices/{id}.pdf`, create the `Invoice` row, enqueue. Because conversion is deterministic, the same photo uploaded twice hashes identically and is caught by the existing dedup. **The original image bytes are discarded (D2)** — not stored, not referenced, no `source_format` column. `Invoice.file_path` always ends in `.pdf`.

**Downstream.** `_run_ocr()` downloads the PDF and Document Intelligence reads an image-only PDF as a scan, which it does today for scanned PDFs, so nothing changes. The extraction graph, verification, RAG indexing, the viewer, Drive write-back (`drive_archive`) and webhook payloads all receive a PDF and are unchanged.

**What the caller gets back.** The same `{batch_id, job_ids}` / `{batch_id, invoice_id}` bodies. The 400 for a refused file names the accepted list.

**FE.** `lib/featureFlags.ts::acceptedUploadExtensions()` always includes this feature's image set, unioned with Feature 27's set when `ENABLE_GENERIC_EXTRACTION` is on; a copy audit replaces every user-facing "only PDF" string. Detail in FE Feature 19.

## 4. Data & schema changes

None. No new columns, no migration, no config key. The original image bytes are discarded after conversion (D2).

## 5. Tasks

- [x] **28.1** `services/file_intake.py`: `sniff_format`, `ACCEPTED_*` constants, `ACCEPTED_FORMATS_DETAIL`, `convert_image_to_pdf` (deterministic output, pixel cap, multi-frame TIFF), `normalize_upload`, the two exception classes. Pure functions, no DB, no I/O beyond bytes.
- [x] **28.2** `routers/invoices.py::upload_invoices()` and `start_directory_watcher()` onto `normalize_upload()`; 400 mapping for both exception classes.
- [x] **28.3** `routers/outbound_invoices.py::upload_outbound_invoice()` onto `normalize_upload()`.
- [x] **28.4** `routers/trainer.py::upload_transient_file()` onto `normalize_upload()`.
- [x] **28.5** `routers/email_ingestion.py`: attachment filter by sniffed format, normalise per attachment, updated drop-reason detail text (constant name unchanged).
- [x] **28.6** Google Drive: `utils/connector_files.py::list_google_drive_files()` mime widening; `services/autopilot_sync.py` and `queue_worker/handlers.py` connector import normalise after download.
- [x] **28.7** Tests: `tests/test_file_intake.py` (unit) and `tests/test_invoice_upload_formats.py` (router-level, five doors), plus a fixture set under `tests/fixtures/image_uploads/` (one PNG, one JPEG, one 2-page TIFF, one WEBP, one PNG renamed `.pdf`, one PDF renamed `.jpg`, one 10×10 GIF as the rejected case, one oversized synthetic PNG for the pixel cap).
- [x] **28.8** Existing-test sweep: every test asserting the literal `"Only PDF is allowed."` or a non-PDF 400 (`tests/test_outbound_ingestion.py`, `tests/test_ingestion.py`, trainer tests) updated to the new message and to the new accept rule. This is the task that proves nothing silently kept the old behaviour.
- [x] **28.9** Doc + tracker close-out: this file's §6 gets the recorded runs; `feature_2_pipeline_extraction.md` / `feature_2.1_vendor_flow_ingestion.md` / `feature_14_email_ingestion.md` / `feature_9_connectors.md` each get one additive "accepts images since Feature 28" line.

## 6. Verification Plan

All correctness decisions here — format sniffing, size cap, determinism, filename/byte precedence — are deterministic code (hard rule 3). No prompt is involved anywhere in this feature.

| Task | Check |
|---|---|
| 28.1 | `tests/test_file_intake.py`: every fixture sniffs to the expected format; renamed files follow bytes not name; GIF → `UnsupportedUploadError`; oversized PNG → `ImageTooLargeError` **before** fitz is called (assert via patch); 2-page TIFF → 2-page PDF; page size == pixel size; converting the same bytes twice yields identical `bytes` (this is the dedup guarantee). |
| 28.2–28.4 | `tests/test_invoice_upload_formats.py`, **run against real Postgres via `/verify-postgres`**: for each of `/invoices/upload`, `/outbound-invoices/upload`, `/trainer/upload` — a PNG returns 201, the stored blob at `Invoice.file_path` starts with `%PDF`, `file_path` ends `.pdf`, `file_hash` equals sha256 of the *converted* bytes; uploading the same PNG twice → second is DUPLICATE and quota is charged once (Gap 189/343 paths); a GIF returns 400 carrying `ACCEPTED_FORMATS_DETAIL`; a real PDF's stored bytes and `file_hash` are identical to a pre-change baseline captured on the same fixture (proves passthrough is byte-identical). |
| 28.5 | Same file: SendGrid multipart with one JPEG attachment → one `Invoice` row; with one GIF only → `dropped_emails` row with `REASON_NO_PDF_ATTACHMENT` and the new detail text. |
| 28.6 | Unit: the Drive query string contains all six mime clauses; Autopilot loop with a mocked `download_google_drive_file` returning PNG bytes writes a `%PDF` blob and an `Invoice` row (Postgres). |
| 28.8 | `uv run pytest tests/test_outbound_ingestion.py tests/test_ingestion.py tests/test_trainer*.py` green, with no test still asserting the retired `"Only PDF is allowed."` string (grep proves zero hits). |
| Manual, Azure path | One phone photo of a real invoice uploaded on the dev stack reaches `COMPLETED`/`AUDIT_REQUIRED` with non-empty `ocr_text`, and `PdfViewerCanvas` shows the page with field highlights aligned. Recorded under `docs/test_evidence/f28_image_upload_<date>/`. |
| Full suite | `uv run pytest -q --ignore=tests/us/run_chat_live_test.py` at the track checkpoint, per the narrow-then-full rule. |

### Recorded runs — 2026-09-04 (real Postgres, `localhost:5433/invoice_db`)

Command shape for every row below:
`DATABASE_URL="postgresql://postgres:localpassword123@localhost:5433/invoice_db" ./.venv/Scripts/python.exe -m pytest <file> -q`

| Task | File | Result |
|---|---|---|
| 28.1 | `tests/test_file_intake.py` (32 tests) | **`32 passed in 34.47s`** |
| 28.2–28.6 | `tests/test_invoice_upload_formats.py` (22 tests) | **`22 passed in 65.99s`** |
| 28.8 | `tests/test_outbound_ingestion.py tests/test_ingestion.py tests/test_trainer.py tests/test_email_ingestion.py` | **`122 passed in 22.98s`** |
| 28.8 (grep) | `grep -rn "Only PDF is allowed\|Only valid PDF documents\|Only PDF files are supported\|Only PDF attachments are ingested\|Invalid PDF content" --include=*.py --include=*.ts --include=*.tsx Prod_Invoice_LLM/apps` | One hit, and it is the comment in `services/file_intake.py:50` recording that the string was retired. Zero assertions. |
| Full suite | `pytest -q --ignore=tests/us/run_chat_live_test.py -p no:randomly` | **`43 failed, 3027 passed, 3 skipped, 5 deselected in 227.54s`.** None of the failures is in a file this feature touches. They fall in six untouched files — `test_generic_extraction.py` (27, Feature 27 flag-off), `test_ops_recommendation.py` (8, workbook threshold bands), `test_connectors.py` (1, `/connectors/status` returning `Not Configured` — an OAuth-credential/env dependency, not the Drive listing), `test_workflow_drive_archive.py` / `test_workflow_email_summary.py` (1 each, 404 `Invoice not found` on the shared-Postgres mock-tenant hazard described below) and `test_c4_examples_retrieval.py` (1, prompt prefix). No BE source file outside this feature is modified in the working tree (`git status --porcelain`), and the subjects of all six — `agents/extraction_agent.py`, the workbook JSON, `routers/connectors.py`, `routers/workflows.py` — are untouched, so these are pre-existing. **No pre-change baseline was captured**, because taking one would have required stashing the working tree, which is forbidden here; the argument above is from the diff's contents, not from a green baseline run. |
| Manual, Azure path | One phone photo through the dev stack to `COMPLETED`/`AUDIT_REQUIRED`, viewer highlights aligned | **Not run, and not claimed.** No dev-stack run was performed in this session, so `docs/test_evidence/f28_image_upload_<date>/` does not exist. §7 makes this a pre-merge gate, so the tracker row stays `[~]` until it is done. |

**What the router-level file actually asserts**, since "22 passed" alone does not say: a PNG upload stores `%PDF` bytes at a `.pdf` `file_path` with `file_hash` = sha256 of the *converted* bytes; the same JPEG twice yields `PROCESSING` + `DUPLICATE` with quota decremented once (10 → 9); a GIF, and a GIF renamed `.pdf`, both 400 with `ACCEPTED_FORMATS_DETAIL` and store nothing; a real PDF and a PDF named `.jpg` are stored byte-identical to what was sent; a 2-page TIFF becomes a 2-page PDF; the directory watcher lists the PNG and the PDF and ignores the `.gif` without failing the batch; outbound refusals burn no quota; the trainer writes `%PDF` to `{session_id}.pdf`; a mailed JPEG produces one `Invoice` while a GIF-only mail produces a `REASON_NO_PDF_ATTACHMENT` drop whose detail names the image formats; a mail carrying both ingests only the photo; the Drive query contains all six mime clauses and the listing returns `mime_type`; Autopilot converts a Drive photo and logs the converted hash, and logs `FAILED` for a GIF; and `handle_import_connector_file` both converts a photo and raises on a GIF.

**Two test-infrastructure findings worth keeping.** (1) `tests/test_invoice_upload_formats.py` deliberately does **not** use `dependencies.MOCK_TENANT_ID`. On this repo's shared local Postgres the mock-auth `user_test_default` row is already attached to a seeded tenant (`phase3-t1c`), so a test written against `MOCK_TENANT_ID` reads an empty tenant while the router writes into that other one — every assertion passes vacuously or, worse, hits that tenant's existing file hashes and silently takes the DUPLICATE branch. The file creates its own tenant and overrides `require_can_load`, `require_can_load_or_api_key`, `require_can_send_invoices` and `routers.trainer.require_paid_plan` instead. (2) Teardown must null `invoice.duplicate_of_invoice_id` before deleting, or `fk_invoice_duplicate_of_invoice_id_invoice` (a self-referencing FK) rejects the delete and every subsequent test errors at setup under `pytest-randomly`.

## 7. Rollout note

Because there is no flag (D1), the first deployment carrying this code accepts images everywhere at once, including Drive folders that already contain photos (D3) — those will be ingested and charged on the next Autopilot cycle. The manual Azure check above is therefore a **pre-merge** gate, not a post-deploy one.

## 8. Founder decisions (2026-09-04)

| # | Question | Ruling |
|---|---|---|
| D1 | Feature flag or unconditional? | **Unconditional.** No `ENABLE_IMAGE_UPLOAD_CONVERSION`, no `/config/features` key, no flag-off branch. Rollback is a redeploy. |
| D2 | Keep the original image alongside the PDF? | **Discard it.** No second blob, no `source_format` column, dedup on the converted bytes. |
| D3 | Widen the Google Drive listing to images? | **Yes, for every tenant, no opt-in.** Accepted consequence: a watched folder already holding photos ingests them on the next cycle and is charged quota for each. |
| D4 | Refuse images when `LLM_PROVIDER=ollama`? | **No provider branch.** This feature targets the Azure Document Intelligence path only. Verified at scoping time that the ollama path is still live in four places (`config.py:369`, `utils/llm.py:165,200`, `queue_worker/handlers.py:151`, `routers/chat_attachments.py:69`) despite being described as deleted; removing it is separate work and is not blocked by this feature. |
| D5 | Route chat attachments through `normalize_upload` too? | **No.** They stay on Feature 27's native image path. A reference document is not an invoice and never enters the pipeline, so the two paths may differ. |
