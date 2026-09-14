# FE Gap 464 — History Screen, non-invoice classification — Local Stack + Real Azure AI

Local stack, real Azure Document Intelligence + Azure OpenAI, not the deployed dev stack.

## Upload

```
curl -X POST http://localhost:8000/api/v1/invoices/upload -H "Authorization: Bearer test_" \
  -F "files=@tests/fixtures/doc_types/purchase_order/us_inbound/US-PO-01_purchase_order.pdf"
```
Result: `{"batch_id":"f6935cf6-e360-40bb-949a-932d264d89b5","job_ids":["28588e55-bddf-4c15-9f5b-7399d1bb0eaa"]}`

## DB (real Postgres)

No `Invoice` row created for job id `28588e55-...` (confirmed 0 rows). Instead a
`documents` row was created:
```sql
SELECT id, doc_type, doc_type_confidence, status, batch_id FROM documents
WHERE batch_id='f6935cf6-e360-40bb-949a-932d264d89b5';
```
`ed2ba5aa-... | PURCHASE_ORDER | 1.0 | EXTRACTED | f6935cf6-...`

Real Azure classification (`doc_type_confidence=1.0`) correctly identified the fixture
as a Purchase Order, not an invoice — this is a real Azure Document Intelligence +
classification run, not a mock.

## API

`GET /api/v1/ingestion-history` → run `f6935cf6-...` shows
`"status":"NOT_LOADED","summary":"1 file: 1 not loaded"`.

`GET /api/v1/ingestion-history/f6935cf6-.../files` → item detail:
`"outcome":"NOT_LOADED","outcome_label":"Not loaded — Purchase order"`, plus full
extracted record (party names, PO number, line items, totals).

## FE screenshots (Playwright, chromium, 1280x900, DISABLE_CLERK_AUTH=true, no stubbing)

- `history_list.png` — `/history` list view: row "Today 08:27 · Upload · Receiving ·
  1 file: 1 not loaded" with a "NOT LOADED" badge.
- `history_expanded.png` — same row expanded: chip "Not loaded — Purchase order",
  evidence "PURCHASE ORDER", issued-by "Northgate Manufacturing Inc.", addressed-to
  "Cascade Industrial Supply LLC", number "PO-US-8841", date "2026-08-12", total
  "34611.5", "2 line items · 1 attribute".

## Result

- Non-invoice upload does not silently disappear (the FE Gap 464 defect): **PASS**
- Ingest classification message and durable `/history` row both confirmed: **PASS**
- Matches the `/api/v1/ingestion-history` durable-record contract described in the
  spec: **PASS**

Run against local stack with real Azure AI services.
