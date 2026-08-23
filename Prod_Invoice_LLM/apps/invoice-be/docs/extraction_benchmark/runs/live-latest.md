# Extraction benchmark run — `live` mode

**Generated file. Do not edit.**

Run at: `2026-08-23T08:42:51+00:00`

4 clean documents, 13 seeded cases.

## Confusion matrix (unit: one document)

| | Alert fired | Stayed silent |
|---|---|---|
| **Seeded (issue planted)** | 5 (TP) | 0 (FN) |
| **Clean (no issue)** | 1 (FP) | 3 (TN) |

- **Alert recall** (the number production usage cannot give): 100.0%
- **False-positive rate on clean documents**: 25.0%
- **Document-level precision**: 83.3%
- **Not applicable in this mode**: 8 extraction-surface cases, excluded from the recall denominator (see `case_manifest.md`, 'Seeded cases').

## Recall per check

| Alert type | Seeded | Detected | Recall | Missed |
|---|---|---|---|---|
| `line_item_calculation_mismatch` | 1 | 1 | 100.0% | — |
| `line_items_mismatch` | 1 | 1 | 100.0% | — |
| `missing_required_field` | 1 | 1 | 100.0% | — |
| `tax_mismatch` | 2 | 2 | 100.0% | — |

## Field-level accuracy (clean documents)

**81/81 fields correct = 100.0%**

| Document | Correct | Total | Wrong fields |
|---|---|---|---|
| `us_flat_sales_tax__clean` | 23 | 23 | — |
| `india_cgst_sgst_round_off__clean` | 23 | 23 | — |
| `eu_reverse_charge_zero_vat__clean` | 19 | 19 | — |
| `outbound_trade_discount__clean` | 16 | 16 | — |

### Every field the extraction got wrong

| Document | Field | Expected | Extracted |
|---|---|---|---|
| — | — | — | — |

## False positives on clean documents

- `outbound_trade_discount__clean` fired: `tax_mismatch`

## Per-case detail

| Case | Kind | Status | Alerts fired | Latency (ms) |
|---|---|---|---|---|
| `us_flat_sales_tax__clean` | clean | COMPLETED | — | 25,660.4 |
| `india_cgst_sgst_round_off__clean` | clean | COMPLETED | — | 23,654.7 |
| `eu_reverse_charge_zero_vat__clean` | clean | COMPLETED | — | 21,886.9 |
| `outbound_trade_discount__clean` | clean | NEEDS_REVIEW | `tax_mismatch` | 25,728.9 |
| `us_flat_sales_tax__printed_total_broken` | seeded | AUDIT_REQUIRED | `tax_mismatch` | 37,133.6 |
| `india_cgst_sgst_round_off__printed_total_broken_gst` | seeded | AUDIT_REQUIRED | `tax_mismatch` | 46,154.8 |
| `eu_reverse_charge_zero_vat__printed_subtotal_mismatch` | seeded | AUDIT_REQUIRED | `line_items_mismatch`, `tax_mismatch` | 39,060.1 |
| `us_flat_sales_tax__printed_line_amount_off` | seeded | AUDIT_REQUIRED | `line_item_calculation_mismatch` | 33,975.4 |
| `outbound_trade_discount__required_field_not_printed` | seeded | NEEDS_REVIEW | `missing_required_field`, `tax_mismatch` | 23,767.8 |
| `india_cgst_sgst_round_off__fabricated_total` | seeded | SKIPPED | — | 0.0 |
| `us_flat_sales_tax__tax_silently_corrected` | seeded | SKIPPED | — | 0.0 |
| `india_cgst_sgst_round_off__tax_silently_corrected_split` | seeded | SKIPPED | — | 0.0 |
| `eu_reverse_charge_zero_vat__subtotal_not_in_source` | seeded | SKIPPED | — | 0.0 |
| `india_cgst_sgst_round_off__unit_price_not_in_source` | seeded | SKIPPED | — | 0.0 |
| `us_flat_sales_tax__line_amount_not_in_source` | seeded | SKIPPED | — | 0.0 |
| `outbound_trade_discount__required_field_dropped` | seeded | SKIPPED | — | 0.0 |
| `us_flat_sales_tax__low_field_confidence` | seeded | SKIPPED | — | 0.0 |
