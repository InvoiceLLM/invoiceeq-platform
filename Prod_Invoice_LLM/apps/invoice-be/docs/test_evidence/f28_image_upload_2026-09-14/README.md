# Feature 28 / FE Feature 19 — Image Upload — Local Stack + Real Azure AI

Run environment: **local stack with real Azure Document Intelligence + Azure OpenAI**
(LLM_PROVIDER=azure, ALLOW_MOCK_AUTH=true), NOT the deployed dev stack. Postgres
localhost:5433/invoice_db, Redis 6379, Chroma 8001, Azurite (devstoreaccount1).
BE: `uvicorn main:app --port 8000`. Worker: `queue_worker.main_worker`. FE:
`DISABLE_CLERK_AUTH=true next dev --port 3100`.

Mock identity `user_test_default` resolved (confirmed via DB query) to tenant
`528daa2c-9c2c-46a9-b61c-d46144d03a57` ("InvoiceEQ Test - US (run3)"), not the
all-zero `MOCK_TENANT_ID` — see feature_28 spec's "test-infrastructure findings" note.

## Commands run

```
curl -s -X POST http://localhost:8000/api/v1/invoices/upload \
  -H "Authorization: Bearer test_" \
  -F "files=@tests/fixtures/image_uploads/invoice_photo.png;type=image/png" \
  -F "files=@tests/fixtures/image_uploads/invoice_photo.jpg;type=image/jpeg"
```
Result: `{"batch_id":"c0106960-76b2-4993-9143-82928558b8aa","job_ids":["d9519ba6-027c-4664-adc8-b523c0436e8b","3cf9d199-b580-444d-9740-89ecd6e7c012"]}`

## DB result (real Postgres, after worker processed both jobs)

```sql
SELECT id, file_path, status, file_hash FROM invoice WHERE id IN (
  'd9519ba6-027c-4664-adc8-b523c0436e8b','3cf9d199-b580-444d-9740-89ecd6e7c012');
```
```
 3cf9d199-... | azure://invoices/tenants/528daa2c.../invoices/3cf9d199-....pdf | AUDIT_REQUIRED | 69fadef7...
 d9519ba6-... | azure://invoices/tenants/528daa2c.../invoices/d9519ba6-....pdf | AUDIT_REQUIRED | 1be27e5b...
```
Both `.jpg`/`.png` uploads produced `.pdf`-named blob paths as required by Feature 28.

```sql
SELECT id, vendor_name, invoice_number, grand_total, coordinates IS NOT NULL AS has_coords,
       field_confidence IS NOT NULL AS has_conf FROM invoice WHERE id IN (...);
```
```
 3cf9d199-... | ACME SUPPLIES PVT LTD | INV-2026-0042 | 12500 | t | t
 d9519ba6-... | ACME SUPPLIES PVT LTD | INV-2026-0042 | 12500 | t | t
```
Real Azure Document Intelligence OCR correctly read vendor name, invoice number and
grand total off the photo fixture (`tests/fixtures/image_uploads/invoice_photo.jpg`,
a mostly-blank page with a small text block) — this is a real Azure OCR run, not a mock.

## Blob content check

```
curl http://localhost:8000/api/v1/invoices/3cf9d199-.../pdf -H "Authorization: Bearer test_" -o inv1.pdf
file inv1.pdf
```
Result: `PDF document, version 1.7, 1 page(s)`, response headers
`content-type: application/pdf`, `content-disposition: inline; filename=3cf9d199-....pdf`.
Confirms the stored blob is a real PDF, not the original JPEG bytes — see
`converted_invoice.pdf` in this directory (fetched from the running BE).

## FE Review Console

Playwright (chromium, 1280x900, no route stubbing) navigated to
`http://127.0.0.1:3100/invoices/review/3cf9d199-6845-...` with `DISABLE_CLERK_AUTH=true`.
Page loaded (HTTP 200), Audit Queue console rendered with:
- Status badge "AUDIT REQUIRED"
- Extracted Fields panel populated: Vendor "ACME SUPPLIES PVT LTD", Invoice Number
  "INV-2026-0042" (screenshot: `review_console.png`)
- Sentinel alert panel ("1 open alert", vendor_name threshold) — confirms field_confidence
  data reached the FE
- "INVOICE PDF VIEWER" panel with zoom/rotate controls present; iframe `src` correctly
  set to `/api/invoices/{id}/pdf`, which resolved 200 (confirmed via response listener)

**Caveat, honestly reported:** the PDF page itself renders blank/white in the headless
Chromium screenshot. Investigated: the iframe's `src` attribute and the underlying HTTP
response are both correct (200, `application/pdf`); `page.frames()` reports the PDF
viewer's internal frame with an empty `url()`, a known Playwright/headless-Chromium
limitation with browser-native PDF-viewer frames (they render via an internal plugin
frame that Playwright cannot fully introspect or reliably screenshot). This is a test
tooling limitation, not evidence of an application defect — the underlying blob is a
valid PDF (`file` command confirms) and DB `coordinates`/`field_confidence` data (which
drive the highlight overlay) are populated. Visual on-canvas highlight alignment was
**not** independently confirmed by this run.

## Result

- Both `.png` and `.jpg` fixture uploads → `.pdf`-named `Invoice.file_path`, real PDF
  bytes stored (Feature 28 core contract): **PASS**
- Reached `AUDIT_REQUIRED` (not stuck at UPLOADED/PROCESSING): **PASS**
- Real Azure Document Intelligence OCR extracted correct vendor/invoice number/total
  from the photo: **PASS**
- FE Review Console loads and shows extracted fields for an image-sourced invoice: **PASS**
- Viewer renders the PDF page with visible highlights aligned to fields: **NOT
  independently confirmed** — headless-Chromium PDF-frame screenshot limitation (see
  caveat above), not a code defect found.

Run against **local stack with real Azure AI services**, not the deployed dev stack
(dev stack unreachable per task scope — no Clerk login).
