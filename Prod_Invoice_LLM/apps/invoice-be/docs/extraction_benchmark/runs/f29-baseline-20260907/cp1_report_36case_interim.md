# CP1 — Feature 29 phase-2 baseline (live)

Run: `docs/extraction_benchmark/runs/f29-baseline-20260907/agent_eval_output.json`  
Recorded: 2026-09-07T11:36:44.205648  
Model under test: **gpt-5.6-luna** (the app's configured deployment; `model_under_test` is `None`, meaning "the application's own").  
Judge: gpt-5-mini, mode `separate`.  
Phase-2 capability flags active: **none — all five off, as CP1 requires**.

## Headline

| metric | value | n |
|---|---|---|
| golden pass % | **75.0%** | 36 |
| judge accuracy (mean) | 0.81 | 36 |
| faithfulness (mean) | 0.906 | 36 |
| relevance (mean) | 0.992 | 36 |
| errors | 0 | 36 |
| Cohen's κ vs human verdicts | **0.462** (agreement 0.806) | 36 |
| SQL exec-correct % | **66.7%** | 39 |
| — of which errored | 0 | |
| — of which emitted no statement | 6 | |
| SQL graded by | deterministic set comparison (expected <= fetched) | |
| latency median / max (s) | 12.5 / 26.8 | |
| cost per turn | $0.00285 | |

## Failure taxonomy

| bucket | count |
|---|---|
| `no_route` | 2 |
| `no_evidence` | 0 |
| `wrong_evidence` | 12 |
| `no_computation` | 6 |
| `narration` | 1 |
| `judge` | 0 |

## Routes taken

| route | turns |
|---|---|
| `(none)` | 48 |

## Judge vs human, case by case

| case | human | judge | accuracy | faithfulness |
|---|---|---|---|---|
| `titan_steel_payment_status` | PASS | PASS | 1.0 | 0.8 |
| `rajesh_steel_cgst` | FAIL | PASS **DISAGREE** | 1.0 | 0.6666666666666666 |
| `datapipe_vs_stratedge` | PASS | PASS | 1.0 | 1.0 |
| `freight_per_vendor` | PASS | PASS | 1.0 | 1.0 |
| `bolts_reconciliation` | PASS | PASS | 1.0 | 1.0 |
| `zero_result_vendor` | PASS | PASS | 1.0 | 1.0 |
| `zero_result_typo_vendor` | FAIL | FAIL | 0.0 | 1.0 |
| `payment_terms_document` | FAIL | FAIL | 0.0 | 0.5 |
| `out_of_scope_code_request` | PASS | PASS | 1.0 | None |
| `greeting_no_tool` | PASS | PASS | 1.0 | None |
| `large_invoice_full_detail` | FAIL | PASS **DISAGREE** | 1.0 | 0.6 |
| `small_invoice_full_detail` | FAIL | FAIL | 0.0 | 0.6666666666666666 |
| `multi_part_totals_and_dates` | PASS | FAIL **DISAGREE** | 0.6666666666666666 | 1.0 |
| `all_vendors_over_twenty_thousand` | PASS | FAIL **DISAGREE** | 0.0 | 1.0 |
| `two_vendors_two_questions` | PASS | PASS | 1.0 | 1.0 |
| `line_item_breakdown_completeness` | FAIL | FAIL | 0.5 | 1.0 |
| `unsupported_field_asks_for_alternative` | PASS | FAIL **DISAGREE** | 1.0 | 0.0 |
| `zero_result_with_useful_redirect` | PASS | PASS | 1.0 | 0.6666666666666666 |
| `hostile_user_tone` | PASS | PASS | 1.0 | 1.0 |
| `internals_probe_no_leak` | PASS | PASS | 1.0 | None |
| `cross_currency_total_refused` | PASS | PASS | 1.0 | 1.0 |
| `india_mixed_gst_slab_lines` | PASS | PASS | 1.0 | 1.0 |
| `india_ganesh_subtotal_reconciliation` | PASS | PASS | 1.0 | 1.0 |
| `india_reverse_charge_vendor` | PASS | PASS | 1.0 | 1.0 |
| `india_outbound_only_disambiguation` | PASS | PASS | 1.0 | 1.0 |
| `india_no_due_date_refusal` | PASS | PASS | 1.0 | 1.0 |
| `us_zero_tax_exemption_reason` | PASS | FAIL **DISAGREE** | 0.0 | 1.0 |
| `us_flagged_inbound_invoices` | FAIL | PASS **DISAGREE** | 1.0 | 1.0 |
| `us_freight_per_vendor_multi` | PASS | PASS | 1.0 | 1.0 |
| `us_outbound_flagged_and_billed_to` | FAIL | FAIL | 0.0 | 1.0 |
| `us_cross_invoice_grand_total` | PASS | PASS | 1.0 | 1.0 |
| `eu_mixed_vat_rates` | PASS | PASS | 1.0 | 1.0 |
| `eu_currency_confusion_trap` | PASS | PASS | 1.0 | 1.0 |
| `eu_reverse_charge_inbound_line` | PASS | PASS | 1.0 | 1.0 |
| `eu_outbound_reverse_charge_vs_domestic` | PASS | PASS | 1.0 | 1.0 |
| `eu_benelux_line_understated` | PASS | PASS | 1.0 | 1.0 |

