# BE Feature 17 / FE Feature 20 — Invoice Builder (live, 20.6) — Local Stack + Real Azure AI

Run environment: local stack, real Azure Document Intelligence + Azure OpenAI, NOT the
deployed dev stack. This closes the "20.6 (live)" row that both feature_17 and
feature_20 docs explicitly note is "owed" — every existing Playwright spec stubs
`/api/**`, so this is the first observation of the real backend contract.

BE Gap 462 context: substitution renderer was deleted; every clone now goes through
`render_invoice()` (`render_mode: "rerender"`) — this run confirms that path end to end.

## Source invoice used

Existing seeded **VERIFIED** outbound invoice `a2e6283d-8c59-4005-ada2-beff58d9612a`
(`IEQ-US-9003`), tenant `528daa2c-9c2c-46a9-b61c-d46144d03a57`.

## Commands

```
GET /api/v1/outbound-invoices/a2e6283d-8c59-4005-ada2-beff58d9612a/build-defaults
  -> 200, prefilled BuildRequest with invoice_number incremented to IEQ-US-9004
POST /api/v1/outbound-invoices/build/preview  (build_request.json)
  -> 200 application/pdf, 1 page, 2361 bytes (build_preview.pdf, this dir)
POST /api/v1/outbound-invoices/build  (same body)
  -> 201 {"batch_id":"675445fb-...","invoice_id":"3ed1fa44-314b-4a9f-8939-9a14a7dcc860"}
```

## DB result (real Postgres)

```sql
SELECT id, status, invoice_number, source_invoice_id, sa_alerts, builder_intent
FROM invoice WHERE id='3ed1fa44-314b-4a9f-8939-9a14a7dcc860';
```
Result: `status=VERIFIED`, `invoice_number=IEQ-US-9004`,
`source_invoice_id=a2e6283d-8c59-4005-ada2-beff58d9612a`, `sa_alerts=[]` (zero alerts,
including zero `builder_render_mismatch`), `builder_intent.render_mode = "rerender"`
confirming the re-render-only path (BE Gap 462) was exercised, not the deleted
substitution path.

Stored PDF fetched via `GET /api/v1/invoices/{id}/pdf` → 200, `application/pdf`,
valid 1-page PDF (`clone_invoice.pdf`, this dir).

## FE screenshot

`clone_review_console.png` — `/invoices/outbound-review/3ed1fa44-...` (Playwright,
chromium, 1280x900, `DISABLE_CLERK_AUTH=true`, no route stubbing): VERIFIED badge,
SENTINEL "No alerts", Extracted Fields showing the cloned customer/number/dates/total
all correctly carried over and incremented, 1 line item at correct subtotal ($12,000.00),
"New invoice from this" clone action present on the header.

Same headless-Chromium PDF-iframe rendering caveat as the Feature 28 evidence applies
to the PDF viewer panel (blank in the screenshot; underlying blob and route both verified
independently via curl/DOM inspection) — not re-litigated here.

## Result

- Real clone through BE endpoints (build-defaults → build/preview → build) reaches
  **VERIFIED with zero alerts**: **PASS**
- `render_mode="rerender"` confirms BE Gap 462's "substitution deleted" design is what
  actually executes on a real clone: **PASS**
- FE outbound-review page renders the built clone correctly: **PASS**
- This closes the "20.6 (live)" / "dev-stack owed" row for **local-stack-with-real-Azure**
  only — the spec's literal wording is "dev stack", which remains unreachable per task
  scope (no Clerk login to the deployed environment). Tracker/spec should record this run
  explicitly as local-stack, and the dev-stack-specific row stays `[~]`.
