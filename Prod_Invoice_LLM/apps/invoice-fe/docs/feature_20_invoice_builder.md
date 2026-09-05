# Feature 20: Invoice Builder — Clone & Edit Screen (FE half of BE Feature 17)

Status lives in `docs/fe_features_tracker.md`. Backend design, rendering rules and the founder decisions D1–D7: [feature_17_invoice_builder.md](../../invoice-be/docs/feature_17_invoice_builder.md). Filed 2026-09-04 per decision D6.

### Overview

A screen that creates a new outbound invoice by starting from an existing verified one. The user picks a source from the outbound review page or the outbound invoices table, edits what changes (number, dates, customer, line items — rows may be added or removed per D3), previews the real PDF the backend will produce, and creates it. The new invoice then appears in the Sending tab's status ledger like any upload and goes through verification before confirm-send.

Not this feature: any branding/logo/template UI (none exists in v1 by design), a customer picker (no customer master), sending to customers, and the BE rendering itself.

### File Coordinates

| Path | Named function / component | New or edit | What it does |
|---|---|---|---|
| `app/invoices/outbound-builder/page.tsx` | `OutboundBuilderPage` | new | Reads `?source=<id>`, fetches `/api/outbound-invoices/[id]/build-defaults`, owns form state, totals display, preview and create actions. Redirects to `/invoices` with a toast if the source is ineligible (BE 409/404). |
| `components/builder/BuilderForm.tsx` | `BuilderForm` | new | Header fields: customer name, invoice number (prefilled with the BE's suggested next number, editable), invoice date, due date, currency (read-only, copied). Same `EditableField` styling as the outbound review page. |
| `components/builder/LineItemGrid.tsx` | `LineItemGrid` | new | Editable rows (description, quantity, unit price, computed amount), **Add row** / **Remove row**. A visible "Layout: exact copy" vs "Layout: re-rendered" pill driven by whether the row count differs from the source, mirroring BE `plan_render_mode()`, so the user knows before preview which look they will get. |
| `lib/invoiceBuilderMath.ts` | `computeTotals(items, taxAmount)` | new | Display-only mirror of BE `compute_totals` (2 dp, half-up). Never sent to the BE; the BE recomputes. |
| `components/builder/BuilderPreview.tsx` | `BuilderPreview` | new | Posts the form to `/api/outbound-invoices/build/preview`, renders the returned PDF in the existing `PdfViewerCanvas`; on 422 marks the listed `unlocated_fields` in `BuilderForm` with a "revert to source value" action; on 409 shows the duplicate-number message next to the number field. |
| `app/api/outbound-invoices/[id]/build-defaults/route.ts` | `GET` | new | `proxyJson` to BE `GET /outbound-invoices/{id}/build-defaults`. |
| `app/api/outbound-invoices/build/preview/route.ts` | `POST` | new | Proxies JSON in, streams `application/pdf` out (same pattern as `app/api/invoices/[id]/pdf/route.ts`). |
| `app/api/outbound-invoices/build/route.ts` | `POST` | new | `proxyJson` to BE `POST /outbound-invoices/build`. |
| `app/invoices/outbound-review/[id]/page.tsx` | header action "New invoice from this" | edit | Visible only when `status ∈ {VERIFIED, SENT, PAID, OVERDUE}` (D4). Links to the builder with `?source=<id>`. |
| `components/dashboard/OutboundInvoicesTable.tsx` | row action "Clone" + "cloned from" link | edit | Same eligibility rule; renders a small link to the source when the row carries `source_invoice_id`. |
| `types/invoice.ts` | `BuildRequest`, `BuildItem`, `BuildDefaults` | edit | Mirrors the BE pydantic shapes. |
| `e2e/outbound-builder.spec.ts` | — | new | Playwright: defaults load, totals update on edit, preview shows a PDF, create routes to the Sending ledger with a new row. |
| `components/audit/PdfViewerCanvas.tsx` | `PdfViewerCanvas` | edit *(added during build)* | `invoiceId` became optional and an `srcUrl` prop was added. A preview PDF is the body of a `POST` and has never been stored, so it has no id to fetch by — the builder hands over an object URL for a blob it already holds. `srcUrl ?? /api/invoices/{id}/pdf`; every existing call site is unchanged. |
| `types/invoice.ts` | `CLONE_ELIGIBLE_STATUSES`, `canCloneSource(status, isOverdue)` | edit *(added during build)* | One shared implementation of founder decision D4 so the review-page header and the table row cannot drift apart. `isOverdue` is a separate argument because the outbound list models overdue as a boolean on an otherwise `SENT` row, not as a stored status. |
| `app/ingestion/page.tsx` | `IngestionPageContent` (was `IngestionPage`), + `IngestionPage` `Suspense` wrapper | edit *(FE Gap 457, 2026-09-04)* | Reads the hand-off query params `tab` / `builtInvoice` / `batch` / `name` via `useSearchParams()`: opens the Sending tab and seeds one `outboundInvoices` row so the new invoice is watched by `SendInvoiceStatusTable` + `LogTerminal` on arrival. Without this the redirect above was inert. |

### Functionality

1. User clicks "New invoice from this" on an eligible outbound invoice. The builder page loads defaults: everything copied, number incremented, dates rolled by the source's payment term.
2. User edits. `computeTotals` updates the read-only totals block on every change. Adding or removing a row flips the layout pill to "re-rendered".
3. **Preview** posts the form; the PDF renders inline. A 422 (substitute path, unlocatable field) highlights the fields and offers one-click revert; a 409 (duplicate number, D5) focuses the number field.
4. **Create** posts the same body to `/build`, receives `{batch_id, invoice_id}`, and routes to `/ingestion` on the Sending tab where `SendInvoiceStatusTable` picks the new invoice up through the existing `GET /api/invoices/[id]` polling. A `builder_render_mismatch` alert, if the pipeline raises one, appears on the ordinary outbound review page with no FE change.

### Built (2026-09-04)

All six tasks are implemented. What was built matches the design above, with these things worth recording:

- **Layout pill.** `predictRenderMode(itemCount, sourceItemCount)` is exported from `LineItemGrid` and mirrors BE `plan_render_mode()`: equal row counts → `substitute` ("Layout: exact copy"), anything else → `rerender` ("Layout: re-rendered"). It is a *prediction* of the server's decision, never an instruction to it — render mode is not part of the build request. The pill carries a `data-render-mode` attribute so the E2E asserts the rule rather than the label text. Removing a row back to the source count returns the pill to "exact copy".
- **Preview branches on content-type first, status second.** `/api/outbound-invoices/build/preview` can answer with a PDF or with JSON on the same route, so `BuilderPreview` checks `content-type` before it checks `response.ok`. The proxy route therefore cannot use `proxyJson` (which reads the body as text and would corrupt binary); it follows `app/api/invoices/[id]/pdf/route.ts` and streams the body through, preserving the backend's own content-type. Object URLs are revoked on swap and on unmount — a preview is a multi-megabyte blob on a screen used iteratively.
- **409 is field-local; 422 is field-local plus a summary.** The duplicate-number message (D5) renders under the invoice-number input rather than as a page banner, because that is the field the user has to change. A 422's `unlocated_fields` both marks each named header field and lists them once in the preview pane, so the user does not have to hunt the form. "Revert to source" restores the value the source PDF actually prints, which by definition needs no substitution, so it always clears that particular failure.
- **Totals are never sent.** The create body is the `BuildRequest` only — no `amount`, no `subtotal`, no `grand_total`. The E2E asserts their absence explicitly, because a silent regression there would make the FE's arithmetic look authoritative when it is not.
- **Eligibility lives in one place.** `canCloneSource()` in `types/invoice.ts` backs both entry points. The review-page header action is `Link`-based (no client handler needed); the table row action reuses the icon-button rhythm of the existing Gap 282 delete.
- **Lineage** renders under the invoice number in `OutboundInvoicesTable` rather than in its own column — `source_invoice_id` is present on a minority of rows and a mostly-empty column costs every row. `app/invoices/page.tsx` passes the endpoint's rows straight through, so the field needs no further FE plumbing once BE task 17.7 lands.

**The Sending hand-off — FE Gap 457, closed 2026-09-04.** After a successful create the page routes to `/ingestion?tab=sending&builtInvoice=<id>&batch=<id>&name=<label>`. When this screen was built, `app/ingestion/page.tsx` read no query parameters at all, so the user landed on the Receiving tab with an idle outbound ledger; the fix was deferred only because a concurrent Feature 19 build owned that file. It has since been applied there: `IngestionPageContent` calls `useSearchParams()` and an effect keyed on `[searchParams, sendVisible]` sets `activeTab` to `"sending"` and seeds one `outboundInvoices` row `{ id, batchId, name }` from `builtInvoice` / `batch` / `name`. That reuses the upload path's render verbatim — `SendInvoiceStatusTable` polls `GET /invoices/{id}` and `LogTerminal` subscribes to the batch id, and both work for a builder-created invoice because it is an ordinary outbound row. Two deviations from the fix as proposed in the gap entry, both deliberate: the effect is keyed on `sendVisible` rather than run once on mount (that flag is false until `GET /settings/service-flow` resolves, and Gap 405 forbids landing a user without `canSendInvoices` on a tab they cannot see), and the `name` param is used as `useSearchParams()` returns it rather than passed through `decodeURIComponent` a second time (which would throw `URIError` on an invoice number containing a literal `%`). `useSearchParams()` also required the page's default export to become a `Suspense` wrapper around `IngestionPageContent`, the same shape `app/trainer/page.tsx` and this builder page already use. Asserted by `e2e/outbound-builder.spec.ts` → "the Sending hand-off opens the Sending tab with the new invoice in the ledger".

### Data & schema changes

None on the FE. Reads `source_invoice_id` that BE task 17.7 adds to the outbound list response.

### Tasks

- [x] **20.1** Proxy routes (`build-defaults`, `build/preview`, `build`) and `types/invoice.ts` shapes.
- [x] **20.2** `lib/invoiceBuilderMath.ts` + unit test against the same cases as BE 17.1.
- [x] **20.3** `BuilderForm`, `LineItemGrid` (add/remove, layout pill), `OutboundBuilderPage`.
- [x] **20.4** `BuilderPreview` with the 422 / 409 handling.
- [x] **20.5** Entry points on the outbound review page and `OutboundInvoicesTable`, plus the "cloned from" link.
- [x] **20.6** `e2e/outbound-builder.spec.ts`.

### Verification Plan

| Task | Check | Result (2026-09-04) |
|---|---|---|
| 20.1 | Each route proxies status codes through unchanged (404/409/422 reach the page); the preview route returns `content-type: application/pdf`. | **Pass, via the E2E's stubs.** `build-defaults` 409 reaches the page, `/build` 409 reaches the create banner *and* the number field, `/build/preview` 409 and 422 reach their components, and a 200 `application/pdf` reaches `PdfViewerCanvas` as a `blob:` URL. Not exercised against a real backend — see the caveat below. |
| 20.2 | Unit: identical outputs to BE 17.1's cases (`[(3, 19.99), (1, 0.005)]` → `59.98` subtotal). | **Pass.** `npx playwright test e2e/invoice-builder-math.spec.ts` → **10 passed (13.0s)**, including the BE 17.1 case (`amounts [59.97, 0.01]`, subtotal `59.98`) and the half-up tie cases `Math.round` gets wrong. |
| 20.3–20.4 | Playwright: defaults populate; removing a row flips the pill; preview renders a PDF page; 409 on a reused number is shown inline. | **Pass.** Eleven of the sixteen tests in `e2e/outbound-builder.spec.ts`, incl. totals recomputing on keystroke (`$159.97` → `$179.96` after a quantity edit), the pill flipping in both directions, the stale-preview marker, and the 422 revert-to-source round trip. |
| 20.5 | Playwright: action hidden on a `NEEDS_REVIEW` row, visible on `VERIFIED`. | **Pass.** Table: Clone present on both `VERIFIED` rows, absent on the `NEEDS_REVIEW` row; "Cloned from" present only on the row carrying `source_invoice_id`, pointing at the source's review page. Review header: parameterised across `VERIFIED`/`SENT`/`PAID` (visible, correct `href`) and `NEEDS_REVIEW` (absent). |
| 20.6 | `npx playwright test e2e/outbound-builder.spec.ts` | **Pass — 17 passed (1.5m)** (2026-09-04, re-run after the FE Gap 457 fix added a seventeenth test; 16 passed at first build). `node node_modules/typescript/bin/tsc --noEmit` exit 0 (`npx tsc` resolves to the wrong package in this checkout), and `npx next build` completes — every route reports `ƒ (Dynamic)`, so the new `useSearchParams()` is not prerendered. |
| 20.6 (live) | End-to-end on the dev stack (Azure path): create → Sending ledger row appears → reaches `VERIFIED`. Evidence under `docs/test_evidence/f20_invoice_builder_<date>/`. | **Not run, and not claimed.** BE Feature 17's three endpoints were being built in parallel and had not landed, so there was nothing live to call — every `/api/**` route in the spec is stubbed with `page.route()`. This row stays open until the backend half ships. FE Gap 457, which blocked the final step of this scenario ("Sending ledger row appears"), is now closed — but that removes only the FE-side blocker; the row itself stays **not run** until BE Feature 17's endpoints exist. |

**Standing caveat on the stubs.** The fixtures encode BE Feature 17's documented contract rather than observe it, so this spec keeps passing if the backend answers with different shapes. The live row above is the only thing that closes that hole; it is owed, not done.

### Founder decisions (2026-09-04)

- **Entry points stay on an existing invoice only** — the outbound review page header and the outbound table row. No "Start from a previous invoice" button on the Sending tab and no source-picker component: the user chooses the source first, then builds. Revisit only if the picker is asked for after real use.
