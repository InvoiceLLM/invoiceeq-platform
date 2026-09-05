# Gap 462 — delete the substitution renderer from the Invoice Builder

Founder-approved 2026-09-05. Substitution is deleted, not fixed: a clone always
re-renders through `services/pdf_render.py::render_invoice()`.

Gap number collision-checked repo-wide immediately before writing: max in use was
**461** (BE tracker). 463/464 reserved for follow-on work, not touched here.

## Backend

- [x] Move the number-formatting helpers that survive (`format_like`,
      `_number_renderings` → public `number_renderings`, `_NUM_RE`, `_GROUP_CHARS`)
      out of `pdf_substitute.py` into `services/pdf_render.py` — both are needed by
      `render_invoice()` and by the router's `_number_style_from_source()`.
      **Not in the brief; found by grep. Deleting the module without this breaks the
      re-render path outright.**
- [x] Delete `services/pdf_substitute.py`.
- [x] `services/invoice_builder.py` — delete `plan_render_mode()`, `RenderMode`,
      `Substitution`, `_num_sub()`, `_plain_number()`, `plan_substitutions()`;
      `builder_intent()` hardcodes `render_mode = "rerender"`.
- [x] `routers/outbound_invoices.py` — `_render_build()` always re-renders; delete
      `UnlocatedFieldsError` and both 422 branches. 409 duplicate-number contract and
      `_assert_invoice_number_unused()` untouched.
- [x] `models.py` — stale `builder_intent` comment naming `pdf_substitute.py`.
- [x] `utils/verification_tools.py::verify_builder_readback` — checked: does not branch
      on render mode, left unchanged (one stale docstring clause about substitution).

## Tests (BE)

- [x] Remove substitution cases from `tests/test_invoice_builder.py`.
- [x] Delete the `date_twice` fixture (substitution-only). `us_style`/`eu_style` are
      the shared source rows for the re-render and prefill tests and stay; `raster_logo`
      and `vector_text_only` stay for `harvest_branding`.

## Frontend

- [x] `components/builder/BuilderPreview.tsx` — delete 422 handling + revert-to-source
      copy; keep 409.
- [x] `components/builder/LineItemGrid.tsx` — delete the layout pill + `predictRenderMode()`.
- [x] `components/builder/BuilderForm.tsx` — delete the `unlocatedFields` prop and the
      `flagged` field state. **Deviation:** the per-field "Revert to source" button is
      KEPT — it is an ordinary undo-an-edit affordance the 422 leaned on but did not
      own, so deleting it would have removed working UI outside this gap's scope.
- [x] `app/invoices/outbound-builder/page.tsx` — drop `unlocatedFields` state, the 422
      branch on Create, and the `renderMode` mirror.
- [x] `types/invoice.ts` — drop `unlocated_fields` / `BuilderRenderMode`.
- [x] `app/api/outbound-invoices/build/preview/route.ts` — comment only.
- [x] `e2e/outbound-builder.spec.ts` — drop the pill and 422 specs.

## Verification

- [x] `verify-postgres`, narrow: `tests/test_invoice_builder.py`,
      `tests/test_outbound_ingestion.py`, `tests/test_outbound_extraction.py`.
- [x] Full BE suite; baseline `43 failed, 3080 passed` (27 of the 43 are Gap 461's
      flag-OFF parity tests, not regressions).
- [x] FE `node node_modules/typescript/bin/tsc --noEmit`.
- [x] FE Playwright `e2e/outbound-builder.spec.ts` only.
- [x] Same-row-count clone: preview + create both succeed (the exact failing case)
      — `test_preview_and_build_both_succeed_on_a_same_row_count_clone`, 200 + 201.

## Docs

- [x] `apps/invoice-be/docs/feature_17_invoice_builder.md` — additive section only
      (hard rule 4): D1 and D3 superseded 2026-09-05, why, tradeoff accepted.
- [x] `apps/invoice-fe/docs/feature_20_invoice_builder.md` — same.
- [x] BE tracker Gap 462 entry + FE tracker Gap 462 entry.
- [x] `done` skill before any `[x]`.

### Not done — owed, not rounded up

- [ ] Feature 20 `20.6 (live)` end-to-end on the dev stack. Unchanged by this
      gap and still not run: every `/api/**` call in the Playwright spec is
      stubbed. Needs a dev-stack session.

## Result

- `pytest tests/test_invoice_builder.py -q` → `45 passed in 28.90s` (real Postgres)
- `pytest tests/test_outbound_ingestion.py tests/test_outbound_extraction.py -q` → `24 passed in 13.58s`
- `pytest -q --ignore=tests/us` → `43 failed, 3075 passed, 3 skipped, 5 deselected in 167.42s`
  — the same 43 as the 2026-09-04 baseline, name for name; no new failure.
- `node node_modules/typescript/bin/tsc --noEmit` → exit 0
- `npx playwright test e2e/outbound-builder.spec.ts` → `16 passed (1.2m)`

Status: complete. Gap 462 marked `[x]` in both trackers; the Feature 17 and
Feature 20 rows stay `[~]` because the live end-to-end row is still owed.
Changes left uncommitted in the working tree.
