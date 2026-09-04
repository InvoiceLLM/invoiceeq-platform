# Extraction benchmark — case manifest

**Generated file. Do not edit.** Regenerate with `uv run python scripts/run_extraction_benchmark.py --artifacts-only`.

Generated: `2026-09-04T11:41:48+00:00` from `tests/extraction_benchmark/{documents,mutations}.py`.

This is the review artifact for Feature 23 Track 1. It exists so architect and a business analyst can check **what was planted and why** without reading the generator. Every seeded case states the field that was changed, the correct value, the value planted instead, and the exact alert type that must fire for the case to count as detected.

## Mutation sizing policy

Every arithmetic mutation shifts its figure by `max(5% of the amount, 25.00)`. verify_line_items_math / verify_totals_math accept max(0.01, 0.5% relative) (Gap 31). Every arithmetic mutation clears that band with about an order of magnitude of headroom, so a recall miss is never explainable as a near-miss.

## Clean documents

Internally consistent by construction: every line amount equals quantity x unit price, the lines sum to the subtotal, and subtotal - discount + tax + round-off equals the grand total. Every figure in the ground truth is printed verbatim in the document text, so all five source-text faithfulness checks must stay silent on all of them.

| Document | Direction | Region | Currency | Grand total | Why this shape |
|---|---|---|---|---|---|
| `us_flat_sales_tax` | INBOUND | US | USD | 5,517.23 | The baseline shape: single invoice-level flat sales tax, no discount, no per-line tax. If any check fires here the check is miscalibrated. |
| `india_cgst_sgst_round_off` | INBOUND | INDIA | INR | 102,070.00 | The split-tax shape Gaps 263/264 are about: two printed components (CGST 9% + SGST 9%) that must be summed into one `tax_amount` of 15,570.00 -- a figure that is NOT printed anywhere as a single number. This is the case `verify_tax_amount_in_source_text`'s component-aware fallback (Gap 69) exists for, so it is also the case that would false-positive if that fallback ever broke. |
| `eu_reverse_charge_zero_vat` | INBOUND | EU | EUR | 18,170.00 | Zero tax that is CORRECT, not missing -- the reverse-charge case the persona rubric in `services/agent_eval.py` already names as a real past failure. A benchmark that only contains taxed invoices cannot tell a correctly-zero tax from a dropped one. |
| `outbound_trade_discount` | OUTBOUND | US | USD | 11,588.10 | The only OUTBOUND document in the set, and the only one where `missing_required_field` can fire at all -- `_DIRECTION_PROFILES`' `required_fields` is empty for INBOUND by design. It also carries a 5% trade discount, which is arithmetically consistent on the document (11,400.00 - 570.00 + 758.10 = 11,588.10) but which `OutboundInvoiceExtractionSchema` has no field for -- see `docs/extraction_benchmark/README.md`, 'What the first run found'. This case is deliberately left in the clean set rather than sanitised: it is the only reason the false-positive rate is a measurement rather than a formality. |

## Seeded cases

One planted issue per case, deliberately. Two would make *which check caught it* ambiguous, and alert recall is the reason this set exists.

`surface` is load-bearing. **document** = the OCR text was mutated, so the document itself is inconsistent and a faithful extraction should reproduce the problem — gradeable in both run modes. **extraction** = the extracted record was mutated while the text stayed clean, simulating the model going wrong — gradeable in verify mode only, because a correctly-behaving model will not make the planted error on demand.

| Case | Parent | Surface | Field | Correct | Planted | Must fire |
|---|---|---|---|---|---|---|
| `us_flat_sales_tax__printed_total_broken` | `us_flat_sales_tax` | document | `grand_total` | 5,517.23 | 5,793.09 | `tax_mismatch` |
| `india_cgst_sgst_round_off__printed_total_broken_gst` | `india_cgst_sgst_round_off` | document | `grand_total` | 102,070.00 | 107,173.50 | `tax_mismatch` |
| `eu_reverse_charge_zero_vat__printed_subtotal_mismatch` | `eu_reverse_charge_zero_vat` | document | `subtotal` | 18,170.00 | 17,261.50 | `line_items_mismatch` |
| `us_flat_sales_tax__printed_line_amount_off` | `us_flat_sales_tax` | document | `items[1].amount` | 3,324.00 | 3,490.20 | `line_item_calculation_mismatch` |
| `outbound_trade_discount__required_field_not_printed` | `outbound_trade_discount` | document | `customer_name` | `Ridgeway Components Corp.` | _(absent)_ | `missing_required_field` |
| `india_cgst_sgst_round_off__fabricated_total` | `india_cgst_sgst_round_off` | extraction | `grand_total` | 102,070.00 | 107,173.87 | `total_not_verified_in_source` |
| `us_flat_sales_tax__tax_silently_corrected` | `us_flat_sales_tax` | extraction | `tax_amount` | 432.23 | 457.36 | `tax_amount_not_verified_in_source` |
| `india_cgst_sgst_round_off__tax_silently_corrected_split` | `india_cgst_sgst_round_off` | extraction | `tax_amount` | 15,570.00 | 16,348.63 | `tax_amount_not_verified_in_source` |
| `eu_reverse_charge_zero_vat__subtotal_not_in_source` | `eu_reverse_charge_zero_vat` | extraction | `subtotal` | 18,170.00 | 19,078.61 | `subtotal_not_verified_in_source` |
| `india_cgst_sgst_round_off__unit_price_not_in_source` | `india_cgst_sgst_round_off` | extraction | `items[1].unit_price` | 7,800.00 | 8,190.07 | `unit_price_not_verified_in_source` |
| `us_flat_sales_tax__line_amount_not_in_source` | `us_flat_sales_tax` | extraction | `items[0].amount` | 600.00 | 630.03 | `line_item_not_verified_in_source` |
| `outbound_trade_discount__required_field_dropped` | `outbound_trade_discount` | extraction | `customer_name` | `Ridgeway Components Corp.` | _(absent)_ | `missing_required_field` |
| `us_flat_sales_tax__low_field_confidence` | `us_flat_sales_tax` | extraction | `ocr_result.field_confidence.InvoiceTotal` | 0.97 | 0.31 | `low_confidence_field` |

### Why each issue was planted

**`us_flat_sales_tax__printed_total_broken`** — A vendor totals block that does not add up. The commonest real audit finding, and the reason `verify_totals_math` is the first check.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `total_not_verified_in_source`.

**`india_cgst_sgst_round_off__printed_total_broken_gst`** — The same break on a split-tax invoice, where the tax figure being summed from two components gives the check one more way to go wrong.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `total_not_verified_in_source`.

**`eu_reverse_charge_zero_vat__printed_subtotal_mismatch`** — A subtotal that does not equal the lines above it. Planted on the zero-VAT invoice specifically: with tax at 0.00 the totals check and the line-sum check cannot cover for each other.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`, `subtotal_not_verified_in_source`.

**`us_flat_sales_tax__printed_line_amount_off`** — Gap 269's shape: a printed line amount that is not quantity x unit price. The out-of-tolerance line-item mismatch the feature doc names.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `line_items_mismatch`, `tax_mismatch`, `line_item_not_verified_in_source`.

**`outbound_trade_discount__required_field_not_printed`** — An outbound invoice with no customer name printed on it at all. The missing-required-field case from the feature doc's table.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`.

**`india_cgst_sgst_round_off__fabricated_total`** — The fabricated total from the feature doc's table. Nothing but the Gap 33 source-text check can see a number the document never printed.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`.

**`us_flat_sales_tax__tax_silently_corrected`** — 'A tax figure that doesn't match the OCR text', verbatim from the feature doc. Gap 46: the model recalculating rather than transcribing.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`.

**`india_cgst_sgst_round_off__tax_silently_corrected_split`** — The same fabrication on the CGST+SGST invoice, where the correct summed figure is itself never printed. This is the case that tells a working Gap 69 component fallback apart from one that just never fires -- the clean version of this document must stay silent and this one must not.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`.

**`eu_reverse_charge_zero_vat__subtotal_not_in_source`** — Gap 43's check, on the invoice where subtotal and grand total are equal -- so a check that accidentally matched the grand total instead would pass here for the wrong reason and be caught by nothing else.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`, `line_items_mismatch`.

**`india_cgst_sgst_round_off__unit_price_not_in_source`** — Gap 44's check. A wrong unit price with a correct line amount is the quiet version of a transcription error: every total still balances.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `line_item_calculation_mismatch`.

**`us_flat_sales_tax__line_amount_not_in_source`** — Gap 36's check: a line amount the document never printed.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `line_item_calculation_mismatch`, `line_items_mismatch`, `tax_mismatch`.

**`outbound_trade_discount__required_field_dropped`** — The extraction-side twin of `required_field_not_printed`: the name IS on the document and the model returned nothing.

  Tolerated side effects (the same planted issue legitimately trips these too, and they are not counted against the case): `tax_mismatch`.

**`us_flat_sales_tax__low_field_confidence`** — Gap 3's confidence router. The only alert whose input is neither the OCR text nor the extracted record but Document Intelligence's own per-field confidence, so it is the only one that would go untested by a benchmark built purely on documents and extractions.

## Document text

Full rendered text for every document, clean and seeded, is written to `documents/`. A seeded file and its clean parent differ by exactly the mutation named above, so any diff tool shows the planted issue directly.
