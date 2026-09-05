# Gap 463 — the Invoice Builder can edit every field an invoice prints

Founder-approved 2026-09-05: "while building new invoice from an existing user can
change everything... so all the fields address, anything thats there in the invoice".

Follows BE Gap 462 (substitution deleted): because a clone is now re-rendered rather
than painted over the source page, this gap is what restores the un-carried fields to
the output at all.

- [x] Evidence: read `invoice_builder.py`, `pdf_render.py`, `models.py::Invoice`,
      `agents/extraction_agent.py` schemas, router, `verify_builder_readback`, FE files.
- [x] Collision-check 463 repo-wide immediately before writing the tracker entries.
- [x] BE: widen `BuildItem` (hsn_sac_code, uom, per-line discount/tax).
- [x] BE: widen `BuildRequest` (vendor_name, po_number, addresses, references,
      payment_instructions, tax_ids, taxes, discounts, deductions, discount_percent,
      discount_amount, compliance_metadata, notes).
- [x] BE: `compute_totals()` — line discount, line tax, invoice discount, multi-rate
      tax, deductions. Decimal, half-up, backward compatible.
- [x] BE: `default_build_from_source()` copies all of it from the source row.
- [x] BE: `render_invoice()` prints all of it.
- [x] BE: `verify_builder_readback()` widened to what the outbound extractor can report.
- [x] BE tests: extend `tests/test_invoice_builder.py`.
- [x] FE: `types/invoice.ts`, `lib/invoiceBuilderMath.ts`, `BuilderForm.tsx`,
      `LineItemGrid.tsx`, builder page wiring.
- [x] Verify: Postgres narrow files, then full suite vs `43 failed, 3075 passed`.
- [x] FE verify: `node node_modules/typescript/bin/tsc --noEmit` + narrow Playwright.
- [x] Docs: additive sections in `feature_17_invoice_builder.md` /
      `feature_20_invoice_builder.md`; tracker entries in both trackers (re-read first,
      Gap 464 agent is editing the same files).
- [x] `/done`, then `/hand-back`. Nothing committed.

Notes (resumed 2026-09-05 after the process exited mid-run):
- BE narrow runs already green: `tests/test_invoice_builder.py` 58 passed;
  `tests/test_outbound_ingestion.py tests/test_outbound_extraction.py` 24 passed.
- FE already green: `tsc --noEmit` clean; `e2e/invoice-builder-math.spec.ts` 14 passed;
  `e2e/outbound-builder.spec.ts` 16 passed (2 environmental browser/port flakes re-run
  individually and passed).
- Remaining: full BE suite, doc sections, tracker entries, /done, /hand-back.

Status: complete (code + docs + trackers), nothing committed.

Final evidence:
- `pytest tests/test_invoice_builder.py -q` -> `58 passed in 30.76s` (real Postgres 5433).
- `pytest tests/test_outbound_ingestion.py tests/test_outbound_extraction.py -q` -> `24 passed in 14.11s`.
- `pytest -q --ignore=tests/us` -> `43 failed, 3123 passed, 3 skipped, 5 deselected in 239.78s`
  — same 43 as the baseline, file for file; no new failure.
- `node node_modules/typescript/bin/tsc --noEmit` -> exit 0, no output.
- `npx playwright test e2e/invoice-builder-math.spec.ts` -> `14 passed (18.5s)`.
- `npx playwright test e2e/outbound-builder.spec.ts` -> `16 passed`.

Gap numbers: BE/FE Gap 463 `[x]`; new **BE Gap 467** filed `[ ]` (open) for the outbound
extraction schema being too narrow to read the widened fields back. 466 was already taken
by the paused model-migration work, so the coverage-hole gap took 467.

Features 17/20 stay `[~]`: the live dev-stack end-to-end row is still owed and could not be
run here.
