# Extraction benchmark run — `verify` mode

**Generated file. Do not edit.**

Run at: `2026-09-17T15:31:25+00:00`

4 clean documents, 13 seeded cases.

## Confusion matrix (unit: one document)

| | Alert fired | Stayed silent |
|---|---|---|
| **Seeded (issue planted)** | 13 (TP) | 0 (FN) |
| **Clean (no issue)** | 0 (FP) | 4 (TN) |

- **Alert recall** (the number production usage cannot give): 100.0%
- **False-positive rate on clean documents**: 0.0%
- **Document-level precision**: 100.0%

## Recall per check

| Alert type | Seeded | Detected | Recall | Missed |
|---|---|---|---|---|
| `line_item_calculation_mismatch` | 1 | 1 | 100.0% | — |
| `line_item_not_verified_in_source` | 1 | 1 | 100.0% | — |
| `line_items_mismatch` | 1 | 1 | 100.0% | — |
| `low_confidence_field` | 1 | 1 | 100.0% | — |
| `missing_required_field` | 2 | 2 | 100.0% | — |
| `subtotal_not_verified_in_source` | 1 | 1 | 100.0% | — |
| `tax_amount_not_verified_in_source` | 2 | 2 | 100.0% | — |
| `tax_mismatch` | 2 | 2 | 100.0% | — |
| `total_not_verified_in_source` | 1 | 1 | 100.0% | — |
| `unit_price_not_verified_in_source` | 1 | 1 | 100.0% | — |

## Field-level accuracy (clean documents)

Not measured. Only measured in live mode; verify mode is handed the extraction it would be grading, so a figure there would measure nothing.

## Per-case detail

| Case | Kind | Status | Alerts fired | Latency (ms) |
|---|---|---|---|---|
| `us_flat_sales_tax__clean` | clean | COMPLETED | — | 36,858.5 |
| `india_cgst_sgst_round_off__clean` | clean | COMPLETED | — | 2.1 |
| `eu_reverse_charge_zero_vat__clean` | clean | COMPLETED | — | 0.4 |
| `outbound_trade_discount__clean` | clean | VERIFIED | — | 0.5 |
| `us_flat_sales_tax__printed_total_broken` | seeded | AUDIT_REQUIRED | `tax_mismatch` | 0.3 |
| `india_cgst_sgst_round_off__printed_total_broken_gst` | seeded | AUDIT_REQUIRED | `tax_mismatch` | 0.6 |
| `eu_reverse_charge_zero_vat__printed_subtotal_mismatch` | seeded | AUDIT_REQUIRED | `line_items_mismatch`, `tax_mismatch` | 0.3 |
| `us_flat_sales_tax__printed_line_amount_off` | seeded | AUDIT_REQUIRED | `line_item_calculation_mismatch` | 0.3 |
| `outbound_trade_discount__required_field_not_printed` | seeded | NEEDS_REVIEW | `missing_required_field` | 0.1 |
| `india_cgst_sgst_round_off__fabricated_total` | seeded | AUDIT_REQUIRED | `tax_mismatch`, `total_not_verified_in_source` | 0.8 |
| `us_flat_sales_tax__tax_silently_corrected` | seeded | AUDIT_REQUIRED | `tax_mismatch`, `tax_amount_not_verified_in_source` | 0.5 |
| `india_cgst_sgst_round_off__tax_silently_corrected_split` | seeded | AUDIT_REQUIRED | `tax_mismatch`, `tax_amount_not_verified_in_source` | 0.7 |
| `eu_reverse_charge_zero_vat__subtotal_not_in_source` | seeded | AUDIT_REQUIRED | `line_items_mismatch`, `tax_mismatch`, `subtotal_not_verified_in_source` | 0.6 |
| `india_cgst_sgst_round_off__unit_price_not_in_source` | seeded | AUDIT_REQUIRED | `line_item_calculation_mismatch`, `unit_price_not_verified_in_source` | 2.0 |
| `us_flat_sales_tax__line_amount_not_in_source` | seeded | AUDIT_REQUIRED | `line_item_calculation_mismatch`, `line_item_not_verified_in_source` | 0.6 |
| `outbound_trade_discount__required_field_dropped` | seeded | NEEDS_REVIEW | `missing_required_field` | 0.2 |
| `us_flat_sales_tax__low_field_confidence` | seeded | AUDIT_REQUIRED | `low_confidence_field` | 0.3 |
