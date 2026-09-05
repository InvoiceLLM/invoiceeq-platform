# Feature 17: Invoice Builder (Logo/Template Invoice Generation)

Placeholder only — deliberately decoupled from Service Flow during design review. Not started, not scoped in detail, blocked on its own dedicated scoping conversation before any task list is written.

### Why this is separate from Service Flow
Service Flow's outbound "Send Invoices" ([feature_2.1_vendor_flow_ingestion.md](feature_2.1_vendor_flow_ingestion.md)) is upload-only: the tenant brings their own already-branded PDF. In-app invoice *generation* — letting a tenant create an outbound invoice from scratch inside this product — was considered and explicitly rejected for that build, because it drags in a materially larger scope: logo upload/storage, a layout/template picker, and a branding settings screen, none of which exist today. Rather than let that scope creep into Service Flow's build, it's parked here as its own future feature.

### Known shape (not yet a task list)
- Logo upload + storage (likely Blob Storage, mirroring `services/storage.py`'s existing pattern).
- One or more invoice layout templates, selectable per tenant.
- A generation endpoint producing a PDF from structured line-item input, plausibly feeding into the same `feature_2.1` verification step once generated (self-check the generated document before send).
- A branding section on the Settings screen ([feature_10_settings.md](feature_10_settings.md) FE / [feature_16_settings.md](feature_16_settings.md) BE) to manage the above.

### Explicitly not decided
- Whether this is a Service Flow tier feature, a separate add-on, or bundled — tied to the same open pricing question as [feature_3.1_vendor_flow_pricing.md](feature_3.1_vendor_flow_pricing.md), not resolved here.
- Template engine/rendering approach (HTML→PDF, a PDF library, or a third-party document API).

### Tasks
- [ ] Not yet broken into tasks — requires its own scoping pass before implementation planning starts.

---

## Solution (scoped 2026-09-04 — additive; the placeholder above is kept verbatim per hard rule 4)

Source: `docs/phase_2_enhancements.md` item 3 — "generate an outbound invoice from an existing one". This section replaces the "known shape" with a concrete design and answers the placeholder's open questions where the founder's framing already decides them. Tasks below are the build tasklist; status stays in `be_features_tracker.md`.

### Overview

An outbound invoice is created by **cloning an existing outbound invoice and editing what changes**, not from a blank form and not from a template engine. The source invoice's own PDF is the template: its logo, layout, fonts and legal footer are kept because the new PDF *is* the old PDF with the changed values substituted in place. This removes the three things the placeholder listed as the expensive part of a builder — logo upload/storage, a layout picker, a branding settings screen — from v1 entirely.

The generated PDF then enters the existing Send Invoices pipeline exactly as an upload would (`routers/outbound_invoices.py` → `process_outbound_invoice` → OCR → extract → verify → `VERIFIED`/`NEEDS_REVIEW` → confirm-send). That is the self-check the placeholder anticipated, and it is strengthened with a deterministic comparison of *what the builder intended to print* against *what the extractor read back*.

**Not this feature:** a from-scratch invoice editor, per-tenant layout templates, a branding screen, a customer master record (`Invoice.customer_id` stays reserved), recurring-invoice scheduling, or sending anything to a customer (Feature 2.1's rule: staff notify only, never customers). Naming: "Invoice Builder" here is unrelated to the Trainer's rule builder and to Feature 25's workflow builder.

### File Coordinates

| Path | Named function / component | New or edit | What it does |
|---|---|---|---|
| `services/invoice_builder.py` | `BuildRequest` (pydantic): `source_invoice_id`, `customer_name`, `invoice_number`, `invoice_date`, `due_date`, `currency`, `items: list[BuildItem]`, `tax_amount`; `BuildItem`: `description`, `quantity`, `unit_price` | new | The editable surface. Everything not listed is copied from the source and is not editable in v1. |
| `services/invoice_builder.py` | `compute_totals(items, tax_amount) -> Totals` | new | **Deterministic (hard rule 3).** `amount = round(qty × unit_price, 2)` per line, `subtotal = Σ amount`, `grand_total = subtotal + tax_amount`, `Decimal` with `ROUND_HALF_UP`. The server always recomputes; client totals are never trusted. |
| `services/invoice_builder.py` | `default_build_from_source(invoice: Invoice, today: date) -> BuildRequest` | new | Prefill: customer/currency/items/tax copied; `invoice_number = next_invoice_number(source)`; `invoice_date = today`; `due_date = today + (source.due_date − source.invoice_date)` when both exist, else `None`. |
| `services/invoice_builder.py` | `next_invoice_number(source_number: str) -> str \| None` | new | Increments the trailing digit run, preserving zero-padding (`INV-0042` → `INV-0043`); no trailing digits → `None` (user must type one). Pure function. |
| `services/invoice_builder.py` | `plan_substitutions(source: Invoice, req: BuildRequest, totals: Totals) -> list[Substitution]` | new | Diffs source vs request field by field and yields `(field, old_text, new_text, align)` for every value that changed, including per-line `quantity`/`unit_price`/`amount` and `subtotal`/`tax_amount`/`grand_total`. Unchanged values produce no substitution, so a clone with only a new number and dates touches two or three spans. |
| `services/pdf_substitute.py` | `locate_field(page, field, old_text, coordinates) -> fitz.Rect \| None` | new | Finds where `old_text` is printed. First uses `Invoice.coordinates` (Document Intelligence bounding polygons already stored per field, Feature 2 / Gap 178) mapped to page points; falls back to `page.search_for(old_text)`; picks the hit closest to the DI polygon when there are several (a date can appear twice). Returns `None` if not found. |
| `services/pdf_substitute.py` | `substitute(pdf_bytes, subs, coordinates) -> tuple[bytes, list[str]]` | new | For each substitution: read the span's font size and colour from `page.get_text("dict")` at the located rect, add a redaction annotation over the rect, `apply_redactions()`, then `insert_textbox(rect, new_text, fontsize, fontname="helv", color, align)` — right-aligned for numeric fields. Returns the new PDF bytes and the list of fields that could not be located. Numeric values are formatted with the source's own thousands/decimal pattern (`format_like(old_text, value)`), so `1,250.00` stays `1,250.00` and `1.250,00` stays `1.250,00`. |
| `services/pdf_substitute.py` | `format_like(sample: str, value: Decimal) -> str` | new | Pure: infers separator style and decimal places from the sample. |
| `routers/outbound_invoices.py` | `GET /outbound-invoices/{id}/build-defaults` | new | Returns `default_build_from_source()` for a source that is this tenant's, `flow_direction == "OUTBOUND"`, has a `file_path`, and is in `VERIFIED`/`SENT`/`PAID`/`OVERDUE` (a `NEEDS_REVIEW` source is refused with 409 — its values are not trusted yet). Gated `require_can_load` + `require_can_send_invoices`, same as upload. |
| `routers/outbound_invoices.py` | `POST /outbound-invoices/build/preview` | new | Body `BuildRequest`. Recomputes totals, plans and applies substitutions, returns the PDF (`application/pdf`) **without persisting anything**. 422 `{"unlocated_fields": [...]}` if any changed field could not be located in the source PDF. |
| `routers/outbound_invoices.py` | `POST /outbound-invoices/build` | new | Same as preview, then hands the bytes to `_store_and_enqueue_outbound()` with `source_invoice_id` and `builder_intent` set. Returns `{batch_id, invoice_id}` like upload. Charges quota exactly like upload (see D2). |
| `routers/outbound_invoices.py` | `_store_and_enqueue_outbound(db, context, tenant, pdf_bytes, *, source_invoice_id=None, builder_intent=None)` | edit (extract) | The tail of `upload_outbound_invoice()` from the Gap 343 quota charge through the queue send, factored out so upload and build share one path. `upload_outbound_invoice()` becomes validation + this call; its behaviour is unchanged. |
| `models.py::Invoice` | `source_invoice_id: UUID \| None`, `builder_intent: dict \| None` (JSON) | edit | Lineage pointer and the intended values (`BuildRequest` + `Totals` as JSON) for the read-back check. Both nullable; upload-created rows leave them `NULL`. |
| `alembic/versions/<rev>_add_invoice_builder_columns.py` | — | new | Adds the two columns; index on `(tenant_id, source_invoice_id)`. |
| `queue_worker/outbound_handlers.py` | `handle_process_outbound_invoice()` | edit | After the graph returns, if `invoice.builder_intent` is set, run `verify_builder_readback(intent, extracted)`: any mismatch appends a `builder_render_mismatch` alert naming the field and forces `NEEDS_REVIEW`. Deterministic; no LLM involvement. |
| `utils/verification_tools.py` | `verify_builder_readback(intent: dict, extracted: dict) -> list[dict]` | new | Compares `invoice_number`, `customer_name`, `invoice_date`, `due_date` (exact, whitespace-normalised), `subtotal`, `tax_amount`, `grand_total` and each line `amount` (0.01 tolerance). Pure function beside the other `verify_*` helpers. |
| `routers/outbound_dashboard.py` | `list_outbound_invoices()` | edit | Response rows gain `source_invoice_id` so the FE can show a "cloned from" link. No filter change. |
| `tests/test_invoice_builder.py` | — | new | See Verification Plan. |

FE surface (to be filed as its own FE spec on approval, per the one-spec-per-app convention — see D6): a **"New invoice from this"** action on `app/invoices/outbound-review/[id]/page.tsx` and on `components/dashboard/OutboundInvoicesTable.tsx` rows, opening `app/invoices/outbound-builder/page.tsx?source=<id>`: a form prefilled from `build-defaults`, an editable line-item grid, totals rendered read-only from the same `compute_totals` rule mirrored in TypeScript for display only, a **Preview** button that posts to `/build/preview` and shows the PDF in `PdfViewerCanvas`, and a **Create** button that posts to `/build` and routes to the new invoice's Sending-tab status row.

### Functionality

1. **Pick a source.** From an outbound invoice that has already been verified (or sent/paid), the user chooses "New invoice from this". The BE returns `build-defaults`: every field copied, the invoice number incremented, dates rolled forward by the source's own payment term.
2. **Edit.** The user changes what differs this time — typically number, dates, quantities, sometimes a unit price or a line description. Line items can be edited in v1 but **not added or removed** (see D3); the count must equal the source's. Totals are recomputed on every change in the FE for display, and again authoritatively on the server.
3. **Preview.** `POST /build/preview` recomputes totals, computes the substitution plan (changed values only), locates each old value on the source PDF using the DI coordinates stored at extraction time, redacts it and prints the new value in place with the source's number format. The user sees the real output PDF before anything is stored. If a changed value cannot be located (the source prints the date in a form the extractor normalised away, say), the response lists the fields and the FE marks them; the user can revert those fields to the source values (no substitution needed) or abandon.
4. **Create.** `POST /build` repeats the render, then does exactly what an outbound upload does: quota classification and charge, blob write to `tenants/{tenant}/invoices/{id}.pdf`, `Invoice` row (`flow_direction="OUTBOUND"`, `status="UPLOADED"`, `source_invoice_id`, `builder_intent`), `process_outbound_invoice` enqueued, `last_enqueued_at` stamped.
5. **Self-check.** The worker runs the shared graph on the generated PDF. The rendered document is OCR'd and extracted like any other, so every existing verification (math, faithfulness, required fields, duplicate `invoice_number` per customer) applies. Then `verify_builder_readback` compares the extracted values with `builder_intent`: any disagreement is a `builder_render_mismatch` alert and the invoice lands `NEEDS_REVIEW` on the existing outbound review screen, where the user sees precisely which printed value the machine could not read back as intended. A clean read-back lands `VERIFIED` and proceeds to confirm-send as today.
6. **Lineage.** `source_invoice_id` is exposed on the outbound list and detail so a user can walk from a clone to its source; RAG indexing, webhooks (`outbound.*` events), Drive archive and the ops workbooks see an ordinary outbound invoice and need no change.

### Data & schema changes

- `Invoice.source_invoice_id: UUID | None` — FK to `invoice.id`; same-tenant enforced in code (the source is always loaded under `tenant_id`).
- `Invoice.builder_intent: dict | None` — JSON (`JSON_VARIANT`), the `BuildRequest` plus computed `Totals`; `NULL` for uploads.
- One Alembic migration, additive, reversible; single head confirmed via the Python API (this machine blocks `alembic.exe`).

### Tasks

- [x] **17.1** `services/invoice_builder.py`: `BuildRequest`/`BuildItem`/`Totals`, `compute_totals`, `next_invoice_number`, `default_build_from_source`, `plan_substitutions`. Pure; unit-tested.
- [x] **17.2** `services/pdf_substitute.py`: `format_like`, `locate_field`, `substitute`. Unit-tested against fixture PDFs.
- [x] **17.3** Migration + `models.py` columns `source_invoice_id`, `builder_intent`.
- [x] **17.4** Factor `_store_and_enqueue_outbound()` out of `upload_outbound_invoice()`; existing `tests/test_outbound_ingestion.py` must pass unchanged before the new endpoints are added.
- [x] **17.5** `GET /outbound-invoices/{id}/build-defaults`, `POST /outbound-invoices/build/preview`, `POST /outbound-invoices/build`, with the source-eligibility rules and the 422 unlocated-fields contract.
- [x] **17.6** `utils/verification_tools.py::verify_builder_readback` + the hook in `handle_process_outbound_invoice()`.
- [x] **17.7** `list_outbound_invoices()` gains `source_invoice_id`.
- [x] **17.8** Fixtures: three real-shape outbound PDFs under `tests/fixtures/invoice_builder/` (US `1,250.00` style, EU `1.250,00` style, one with the date printed twice), each with a stored `coordinates` JSON captured from a DI run.
- [x] **17.9** `tests/test_invoice_builder.py` and the FE spec hand-off (D6).

### Verification Plan

Every decision of correctness in this feature is deterministic code: totals arithmetic, number formatting, invoice-number increment, field location, and the read-back comparison. The LLM only extracts the generated PDF, exactly as it does for an upload; it never decides whether the build is correct.

| Task | Check | Result (2026-09-04) |
|---|---|---|
| 17.1 | Unit: `compute_totals` on `[(3, 19.99), (1, 0.005)]` → amounts `59.97`, `0.01`, subtotal `59.98`; `next_invoice_number("INV-0099")` → `INV-0100`, `("2026/07")` → `2026/08`, `("ACME")` → `None`; `default_build_from_source` rolls due date by the source's term; `plan_substitutions` yields nothing for an unchanged request. | **Pass.** `tests/test_invoice_builder.py` — `compute_totals` on `[(3, 19.99), (1, 0.005)]` → `[59.97, 0.01]`, subtotal `59.98`; `next_invoice_number` parametrised over `INV-0099`→`INV-0100`, `2026/07`→`2026/08`, `ACME`→`None`, `INV-0042-A`→`INV-0043-A`, `None`→`None`; `default_build_from_source` rolls the due date by the source's 30-day term and returns `None` without one; `plan_substitutions` returns `[]` for an unchanged request and exactly `{invoice_number, invoice_date, due_date}` for a plain clone. |
| 17.2 | Unit on the three fixtures: `format_like("1.250,00", Decimal("2000"))` → `2.000,00`; every planned field is located within its DI polygon; the twice-printed date fixture substitutes the header date and not the footer; `substitute()` output re-extracts (`page.get_text`) to the new values and no longer contains the old ones; the unlocatable case returns the field name instead of raising. | **Pass.** `format_like` parametrised (`1.250,00`→`2.000,00`, `1,250.00`→`2,000.00`, `1250.00`→`2000.00`, `$1,250.00`→`$2,000.50`, `5`→`6`); every planned field's located rect intersects its own DI polygon on `us_style`; the `date_twice` fixture rewrites the header date (`01/09/2026` present) while **both** footer repetitions of `15/07/2026` survive; `substitute()` output re-extracts to every new value and contains none of the old ones; `eu_style` comes back as `1.500,00` / `01.09.2026`, never `1,500.00`; the unlocatable case returns the field name `customer_name` instead of raising. |
| 17.3 | Migration up/down on real Postgres via `/verify-postgres`; single Alembic head. | **Pass.** Real Postgres (`localhost:5433/invoice_db`): `alembic upgrade head` → `downgrade -1` → `upgrade head`, all clean; `information_schema` confirms `builder_intent jsonb NULL` and `source_invoice_id uuid NULL`, plus index `ix_invoice_tenant_source_invoice_id`. Single head `f6a1b2c3d4e5` confirmed via `ScriptDirectory.get_heads()` before writing (this machine blocks `alembic.exe`). |
| 17.4 | `tests/test_outbound_ingestion.py` green before and after the extraction, on Postgres. | **Pass.** `tests/test_outbound_ingestion.py` **`14 passed in 11.51s`** on Postgres, file unmodified by this build (`git diff` shows only Feature 28's edits). `tests/test_invoice_upload_formats.py` **`22 passed`** alongside, which is what proves the image-accepting door still behaves. |
| 17.5 | Postgres run: `build-defaults` 404 for another tenant's invoice, 409 for `NEEDS_REVIEW`, 200 with incremented number; `preview` returns `%PDF` bytes and creates **no** `Invoice` row and charges **no** quota; `build` creates a row with `source_invoice_id`, `builder_intent`, `status="UPLOADED"`, `file_path` ending `.pdf`, `last_enqueued_at` set, and charges one billable unit (Gap 343 path); an identical second `build` is caught as DUPLICATE by hash. | **Pass.** Postgres run: `build-defaults` 404 for another tenant's invoice, 409 on `NEEDS_REVIEW`, 200 with `INV-0043` and dates rolled 30 days, accepted on `VERIFIED`/`SENT`/`PAID`; `preview` returns `application/pdf` starting `%PDF`, creates **no** `Invoice` row and leaves `free_invoices_remaining` untouched; `build` creates a row with `source_invoice_id`, `builder_intent` (`render_mode: substitute`), `status` `UPLOADED`, a `.pdf` `file_path`, `last_enqueued_at` set, the stored blob starting `%PDF`, and exactly **one** billable unit charged (Gap 343 path). |
| 17.6 | Handler test with mocked OCR/LLM (as `tests/test_outbound_extraction.py` does): extracted `grand_total` off by `0.02` from intent → `builder_render_mismatch` alert + `NEEDS_REVIEW`; exact match → no alert, status unchanged from the graph's own verdict. | **Pass.** Handler test with `_run_ocr` / `run_outbound_extraction_agent` mocked (the `tests/test_outbound_extraction.py` idiom) on a **real built row**: an extracted `grand_total` off by `0.02` produces a `builder_render_mismatch` alert naming `grand_total` and forces `NEEDS_REVIEW`, persisted (re-read from Postgres); an exact read-back leaves the graph's own `VERIFIED` verdict and raises no alert; an uploaded invoice (`builder_intent` NULL) is untouched. Unit coverage adds whitespace/`T00:00:00` tolerance, a wrong line amount, and a lost line. |
| Manual, Azure path | One real clone on the dev stack from a previously `VERIFIED` outbound invoice: preview renders the source layout with the new number/date; after `build` the worker reaches `VERIFIED` with zero `builder_render_mismatch` alerts, and `PdfViewerCanvas` shows the new values in the old layout. Evidence under `docs/test_evidence/f17_invoice_builder_<date>/`. | **Not run, and not claimed.** No dev-stack session took place, so `docs/test_evidence/f17_invoice_builder_<date>/` does not exist. This is the only open row in this plan, and it is the same gap as FE Feature 20's `20.6 (live)` row seen from the other side — that one is now unblocked, since these endpoints exist. |

### Open decisions

- **D1 — Substitution only, or a structured re-render fallback?** v1 refuses when a changed field cannot be located in the source PDF. The alternative is a second renderer (`reportlab`, already a dependency) that lays the invoice out fresh, harvesting the logo from the source page's largest image. More work, and it gives up "looks exactly like ours". Ship v1 substitution-only and measure how often the 422 fires?
- **D2 — Is a built invoice billable?** The design charges it like an upload, because it goes through the same extraction pipeline. Founder call if generated invoices should be free.
- **D3 — Line items: edit only, or add/remove?** v1 keeps the source's line count fixed because inserting rows into a fixed layout is exactly the template-engine problem this design avoids. Is edit-only acceptable for the first cut, or is add/remove a must-have (which pulls D1's fallback renderer into v1)?
- **D4 — Which sources are eligible?** Proposed: `VERIFIED`, `SENT`, `PAID`, `OVERDUE`. Should a `NEEDS_REVIEW` invoice whose alerts were all resolved (`resolve_outbound_alert` never changes status, Gap 243) also qualify?
- **D5 — Invoice-number auto-increment.** Proposed as a default the user can overwrite, never enforced. Should the BE refuse a number that already exists for the same customer at build time, rather than relying on the pipeline's `duplicate_invoice_number` alert after the fact?
- **D6 — FE spec.** The FE surface is described here for completeness; on approval it is filed as its own `apps/invoice-fe/docs/feature_N` (next free FE number at build time) rather than expanded inside this BE doc.
- **D7 — Pricing tier.** Unchanged from the placeholder: unresolved, tied to `feature_3.1_vendor_flow_pricing.md`. Nothing in this design depends on it; the endpoints sit behind `require_can_send_invoices` only.

### Founder decisions (2026-09-04) — resolve D1–D7 above; the questions stay as written for history

| # | Decision | Effect on the design |
|---|---|---|
| D1 | **Substitution only** when the line count is unchanged. | Unchanged from the solution text. |
| D3 | **Add/remove line items allowed.** Because that conflicts with D1, the ruling is **Hybrid**: in-place substitution when `len(req.items) == len(source.items)`; automatic structured re-render when rows were added or removed. | Adds `services/pdf_render.py` (below) and the renderer selection rule in `plan_render_mode()`. Task list amended: 17.2b, 17.8 fixtures. |
| D2 | **Billable, same as upload.** | Unchanged. |
| D4 | **Sources: `VERIFIED` / `SENT` / `PAID` / `OVERDUE` only.** `NEEDS_REVIEW` → 409. | Unchanged. |
| D5 | **Refuse at build time** if `(tenant_id, customer_name, invoice_number)` already exists. | `POST /build` and `/build/preview` return 409 `{"detail": "Invoice number already used for this customer"}` before rendering. Deterministic query, same predicate the pipeline's `duplicate_invoice_number` check uses. Auto-increment stays a suggestion. |
| D6 | **Own FE spec.** | Filed as `apps/invoice-fe/docs/feature_20_invoice_builder.md`, tracker row added. |
| D7 | **Defer pricing; ship behind Send Invoices.** | Endpoints gated `require_can_load` + `require_can_send_invoices` only. Pricing remains open in `feature_3.1_vendor_flow_pricing.md`. |

#### Hybrid renderer (from D3)

| Path | Named function / component | New or edit | What it does |
|---|---|---|---|
| `services/invoice_builder.py` | `plan_render_mode(source: Invoice, req: BuildRequest) -> Literal["substitute", "rerender"]` | new | `"substitute"` iff the item count is unchanged; otherwise `"rerender"`. Pure. The mode is stored in `builder_intent["render_mode"]` so the read-back check and the review screen can say which path produced the PDF. |
| `services/pdf_render.py` | `harvest_branding(source_pdf_bytes) -> Branding` | new | From page 1 of the source: the largest raster image (`page.get_images()`, by pixel area, top 40% of the page) as the logo, and the text blocks above the first line item as the header block (tenant name/address as printed). Deterministic; returns empty branding if nothing qualifies. |
| `services/pdf_render.py` | `render_invoice(req: BuildRequest, totals: Totals, branding: Branding, number_style: str) -> bytes` | new | `reportlab` (already a dependency) A4/Letter chosen from the source page size. Layout: logo + header block, customer block, number/dates, line-item table (any row count, paginates), subtotal / tax / grand total, footer text harvested from the source's last text block. Numbers formatted with `format_like()` using the source's grand-total string as the sample so separators match the tenant's convention. |
| `routers/outbound_invoices.py` | `/build/preview`, `/build` | edit | Call `plan_render_mode()`; dispatch to `substitute()` or `render_invoice()`. The 422 unlocated-fields contract applies to the substitute path only. |
| `routers/outbound_invoices.py` | `_assert_invoice_number_unused(db, tenant_id, customer_name, invoice_number)` | new | D5. Case-insensitive, whitespace-normalised match on `Invoice.flow_direction == "OUTBOUND"`. 409 on hit. |

#### Tasks amended

- [x] **17.2b** `services/pdf_render.py`: `harvest_branding`, `render_invoice`; `plan_render_mode` in `invoice_builder.py`.
- [x] **17.5** (amended) also `_assert_invoice_number_unused()` on both build endpoints, and render-mode dispatch.
- [x] **17.8** (amended) fixtures gain one source whose logo is a raster image and one whose "logo" is vector text only (branding harvest must not crash on either).

#### Verification amended

| Task | Check | Result (2026-09-04) |
|---|---|---|
| 17.2b | Unit: `plan_render_mode` returns `substitute` for equal counts, `rerender` otherwise; `harvest_branding` on the raster fixture returns the logo with the expected pixel size, on the vector fixture returns no logo and does not raise; `render_invoice` output re-extracts (`page.get_text`) every line description, every amount in the source's separator style, and the grand total; a 40-row request paginates to 2 pages with the totals block on the last. | **Pass.** `plan_render_mode` returns `substitute` for equal counts and `rerender` after both an add and a removal; `harvest_branding` on `raster_logo` returns the logo at `(240, 80)` px on an A4 page, and on `vector_text_only` returns no logo without raising while still harvesting the letterhead; a 40-row EU request renders **2 pages** with the totals block (`9.876,00` / `9.976,00`, source separators) on the last, all 40 descriptions re-extracting and `246,90` appearing exactly 40 times; the harvested logo is placed in the re-rendered output. Plus the metadata-line test from deviation 4 above. |
| 17.5 (D5) | Postgres run: building with an `invoice_number` already used for the same customer → 409 and no row, no quota; same number for a different customer → 201. | **Pass.** Postgres: building with the source's own `invoice_number` for the same customer → **409** with detail `Invoice number already used for this customer`, with **no** new `Invoice` row, **no** quota decrement and **no** blob written (refused before rendering); the same number for a different customer passes the D5 gate. |
| Manual, Azure path (amended) | Two real clones: one unchanged-count (substitute) and one with a row added (re-render). Both reach `VERIFIED` with zero `builder_render_mismatch` alerts. | **Not run, and not claimed** — same reason as the row above. Both clone shapes (unchanged count → substitute, row added → re-render) are covered end-to-end through the HTTP endpoints against Postgres, but not against the live dev stack with real OCR. |

---

## Built (2026-09-04)

All ten tasks are implemented and verified against real Postgres. What was built
matches the design above; this section records what actually happened, including
the four places the implementation deviates from the text and why.

### The FE contract is unchanged

`apps/invoice-fe/docs/feature_20_invoice_builder.md` was built first against the
documented contract, with every `/api/**` call stubbed. **No deviation from that
contract was needed** — the shapes it encodes are the shapes that shipped:

| Endpoint | What ships |
|---|---|
| `GET /outbound-invoices/{id}/build-defaults` | 200 with a `BuildRequest` body (`source_invoice_id`, `customer_name`, `invoice_number`, `invoice_date`, `due_date`, `currency`, `items[]` of `{description, quantity, unit_price}` — no `amount` — and `tax_amount`); 404 for another tenant's or a non-outbound invoice; 409 for a source outside `VERIFIED`/`SENT`/`PAID`/overdue. |
| `POST /outbound-invoices/build/preview` | 200 `application/pdf`; 422 with `{"unlocated_fields": [...]}` **at the top level of the body**, not under `detail` (a `JSONResponse`, deliberately not an `HTTPException`, exactly because FastAPI would nest it); 409 `{"detail": "Invoice number already used for this customer"}`. |
| `POST /outbound-invoices/build` | 201 `{"batch_id", "invoice_id"}`, same envelope as upload; same 409/422 as preview. |
| `GET /outbound-dashboard/invoices` | rows gain `source_invoice_id` (NULL on uploads). |

Money and quantity fields serialise as JSON numbers (FastAPI's `jsonable_encoder`
renders `Decimal` that way); `types/invoice.ts` already types them
`number | string`, so both ends agree.

### Deviations from the design text

1. **`locate_field()` matches whole tokens, not substrings, for numbers.** The
   design said "falls back to `page.search_for(old_text)`". Measured on the
   `us_style` fixture, an unqualified substring search for a *quantity* of
   `5.00` matched the `5.00` inside a different line's `175.00` and rewrote the
   wrong cell while leaving the real quantity untouched. `locate_token()` now
   compares against `page.get_text("words")` tokens (currency symbols and
   trailing punctuation stripped and preserved around the replacement), and
   substring search survives only for text fields and multi-word values such as
   `15 July 2026`. `locate_field()` keeps its documented signature and returns
   the rect.
2. **The redaction rectangle is the middle 70% of the located rect.** A word
   rect spans the whole line box; on the same fixture, redacting the full rect
   for `INV-0042` also deleted the tail of the next line's invoice date, because
   the two line boxes overlap by ~1.7 pt. The inset annotation still intersects
   every glyph of its own token, so the value is genuinely removed rather than
   covered. `fill=None` as well, so no white box is punched into a shaded row.
3. **`Substitution` carries typed old/new values and a candidate list.** The
   design's `(field, old_text, new_text, align)` is intact, but a source prints
   `1.250,00` or `15/07/2026`, not the canonical `1250.00` / `2026-07-15` a
   database row holds. `candidate_renderings()` generates the plausible printed
   forms of the old value, and whichever one the page actually contains becomes
   the `format_like()` sample (numbers) or the renderer reused for the new date.
   That is what makes "the source's own number format" and "the source's own
   date format" true rather than aspirational.
4. **`harvest_branding()` takes an optional `exclude_texts` and filters
   metadata lines.** Harvesting "the text blocks above the first line item"
   verbatim reprinted the *source invoice's own* number and dates in the
   letterhead of the re-rendered clone, above the new ones. Header lines that
   read as invoice metadata (a label from a fixed set plus a colon or a digit),
   the document title, and anything quoting the caller-supplied excluded values
   are dropped; harvesting also stops at the line-item table's column headings.
   The footer is the source's last prose block (>= 4 words) below 40% of the
   page, which is the "last text block" the design named, qualified so a totals
   row cannot be mistaken for a footer.

Two smaller notes: `_store_and_enqueue_outbound()` takes a `filename` argument
the design did not list (it is used for the storage-failure message, and the
builder passes `<invoice number>.pdf`); and Feature 28's normalisation call is
untouched, still sitting between the file read and the Gap 343 quota charge —
the quota charge and everything after it is what moved into the helper, so the
image-accepting behaviour of the upload door is unchanged (`14 passed` on an
unmodified `tests/test_outbound_ingestion.py`).

### One defect found and fixed: BE Gap 459

`reportlab` — imported at runtime by `services/pdf_render.py` — was a **dev-only**
dependency, and both Dockerfiles install with `uv sync --frozen --no-dev`. Every
test would have passed while the re-render branch raised `ModuleNotFoundError`
in every deployed environment. Moved into `[project] dependencies`, `uv.lock`
regenerated. Full entry in `be_features_tracker.md`.

### Fixtures

`tests/fixtures/invoice_builder/` holds five source PDFs and a JSON sidecar each
(the `Invoice` field values a real extraction would have written, plus the seven
Document Intelligence polygons it would have stored, in the 0–100 page
percentages Gap 330 normalises to): `us_style` (`1,250.00`, ISO dates),
`eu_style` (`1.250,00`, `dd.mm.yyyy`), `date_twice` (the invoice date printed in
the header and twice more in the footer), `raster_logo` (an embedded PNG) and
`vector_text_only` (no image at all). `_generate.py` regenerates them.

### Test runs recorded

All against real Postgres (`postgresql://…@localhost:5433/invoice_db`), CONVENTIONS hard rule 2:

| Command | Result |
|---|---|
| `pytest tests/test_invoice_builder.py -q` | `53 passed in 11.22s` |
| `pytest tests/test_outbound_ingestion.py -q` | `14 passed in 11.51s` (file unmodified — task 17.4's precondition) |
| `pytest tests/test_invoice_builder.py tests/test_outbound_ingestion.py tests/test_outbound_extraction.py tests/test_outbound_dashboard.py -q` | `95 passed in 13.14s` |
| `pytest tests/ -q --ignore=tests/us/run_chat_live_test.py` | `43 failed, 3080 passed, 3 skipped, 5 deselected in 223.44s` |
| `alembic upgrade head` / `downgrade -1` / `upgrade head` | clean each time; columns and `ix_invoice_tenant_source_invoice_id` confirmed in `information_schema` |

The 43 full-suite failures are the same count, and in the same six files
(`test_generic_extraction.py`, `test_ops_recommendation.py`, `test_connectors.py`,
`test_workflow_drive_archive.py`, `test_workflow_email_summary.py`,
`test_c4_examples_retrieval.py`), as the Feature 28 build's reference run of
`43 failed, 3027 passed`; the pass count rose by exactly the 53 tests this build
added. None of those six files, nor their subjects, is touched here. The
`--ignore` is required because `tests/us/run_chat_live_test.py` and
`tests/realworld_tenant/run_chat_live_test.py` share a module basename with no
`__init__.py`, which aborts collection — pre-existing, both files tracked,
neither touched by this build.
