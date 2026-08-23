# Extraction & alert benchmark — methodology (Feature 23, Track 1)

**This is the review document.** Architect and a business analyst read this, plus
`case_manifest.md` next to it, before any figure produced here is treated as the
real benchmark. It is hand-written and maintained; everything else in this
folder is generated.

Built 2026-08-23. Prior to this date the repo could measure alert *precision*
(from Review Console dismiss-vs-correct actions on real documents) but not alert
*recall* — nobody flags what wasn't flagged. That is the gap this track closes.

## What is in this folder

| Path | Generated? | What it is |
|---|---|---|
| `README.md` | no | This file. Methodology, limits, findings. |
| `case_manifest.md` | **yes** | Every case as review prose + tables: what was mutated, correct value vs. planted value, which alert must fire, and why the issue is worth planting. |
| `case_manifest.json` | **yes** | The same content machine-readable, including full OCR text and full extracted record per case. |
| `documents/*.txt` | **yes** | Rendered document text, one file per case. A seeded file and its clean parent differ by exactly the mutation named in the manifest, so any diff tool shows the planted issue. |
| `runs/<mode>-<timestamp>.json` | **yes** | One measurement run: raw observations plus scores. |
| `runs/<mode>-latest.md` | **yes** | The most recent run of that mode as a readable summary. |

Regenerate everything:

```
uv run python scripts/run_extraction_benchmark.py --artifacts-only
```

There is no randomness anywhere in the generator, so regenerating over an
unchanged tree reproduces the corpus byte for byte (asserted by
`tests/test_extraction_benchmark.py::test_regenerating_the_corpus_is_byte_identical`).

## How to re-run each measurement

```
# deterministic, free, no network. 4 clean documents + 13 seeded cases.
uv run python scripts/run_extraction_benchmark.py --mode verify

# real Azure OpenAI extraction end to end. Costs real tokens.
uv run python scripts/run_extraction_benchmark.py --mode live

# one case only
uv run python scripts/run_extraction_benchmark.py --mode live --cases us_flat_sales_tax__clean
```

Exit code is 1 on any missed seeded issue, any clean-document false positive, or
any error, so the script is usable as the pre-deploy gate the feature doc's
cadence section names without further work. `--no-gate` reports without failing.

`--mode verify` also runs as an ordinary pytest
(`uv run pytest tests/test_extraction_benchmark.py`), so the recall floor is
enforced by the normal suite and not only by someone remembering to run a
script.

**It cannot run inside a deployed container today.**
`Prod_Invoice_LLM/.dockerignore` excludes `**/tests/` and `docs/` from every
image built from this repo, and this whole harness lives in `tests/`. A GitHub
Actions pre-deploy gate works (the checkout has the full tree); a scheduled ACA
job does not, and would fail on import. That is the same thing that made the
deleted `caj-agent-eval-dev` nightly job unrunnable, re-confirmed against the
file rather than assumed. See `feature_23_ai_control_tower.md`, "The cadence
blocker", for the three ways out — the choice is a packaging decision and is not
made here.

## Where the code lives

| File | What it holds |
|---|---|
| `tests/extraction_benchmark/documents.py` | `InvoiceSpec`, `render_ocr_text()`, `ground_truth()`, `initial_extraction()`, and the four clean documents. |
| `tests/extraction_benchmark/mutations.py` | The eleven named mutators, `_PLAN` (the frozen seeded set), `build_seeded_cases()`, `_replace_money_in_text()`. |
| `tests/extraction_benchmark/metrics.py` | `compare_fields()`, `values_match()`, `score_seeded()`, `ConfusionMatrix`, `recall_by_alert_type()`. |
| `tests/extraction_benchmark/harness.py` | `run_benchmark()` and the two run modes over the real `agents/extraction_agent.py`. |
| `tests/extraction_benchmark/artifacts.py` | Everything in this folder that is generated. |
| `scripts/run_extraction_benchmark.py` | CLI. |
| `tests/test_extraction_benchmark.py` | 116 tests of the harness itself. |

## The design, and why it is shaped this way

### One spec, two derived halves

The unit is an `InvoiceSpec` — the invoice as data. From one spec both halves of
a case are derived, from the same numbers:

* `render_ocr_text()` produces the text the extraction pipeline is fed, shaped
  like Document Intelligence's `content` output (header block,
  whitespace-aligned line-item table, totals block).
* `ground_truth()` produces the known-correct extraction of that same text.

There is therefore no transcription step in which ground truth could drift from
the document. A mutation changes exactly one of the two and records which,
which is what makes "the planted issue" a precise claim rather than a
description.

`tests/benchmark/generator.py` (the pre-existing procedural PDF generator) was
read before this was written rather than duplicated by accident. It is not
reusable here: it renders to PDF and its consumer uploads through the live
`/invoices/upload` endpoint, so it needs a running API, Postgres, Blob storage
and Document Intelligence; and its ground truth is six scalar fields, where
field-level accuracy needs the whole record because three of the ten alert types
are line-item checks.

### Two mutation surfaces — the load-bearing distinction

The extraction pipeline has two genuinely different failure modes, and they can
only be seeded on different sides of it.

**`surface="document"`** — the OCR text is mutated. The document itself is now
inconsistent (the vendor's arithmetic is wrong, or a required field is not
printed). A correct extraction transcribes it faithfully and an arithmetic check
catches it. **Gradeable in both modes**, because a live model reading the
mutated text reproduces the planted inconsistency.

**`surface="extraction"`** — the extracted record is mutated while the text
stays clean. This simulates the model going wrong: a fabricated total, a
silently "corrected" tax figure, a dropped required field. Gaps 33/36/43/44/46
exist for exactly this and nothing else can catch it. **Gradeable in verify mode
only** — a correctly-behaving model will not make the planted error on demand,
so live mode reports these as `not_applicable` and `ConfusionMatrix` keeps them
out of the recall denominator. Counting them as misses would make live-mode
recall look catastrophic for entirely the wrong reason.

Eight of the thirteen seeded cases are extraction-surface. That is the honest
reason `--mode verify` is the primary mode and not a fallback: it is the only
mode that can answer "if the model fabricated a total, would the check catch
it?", which is the question five of this repo's closed gaps were opened for.

### One planted issue per case

Two would make *which check caught it* ambiguous, and alert recall is the reason
the set exists. Where a single planted issue legitimately trips more than one
check (a mis-printed line amount breaks both the per-line check and the subtotal
sum), the extra types are declared per case as `tolerated_alert_types` and are
not counted against it. Anything fired that is neither expected nor tolerated is
reported as **collateral** — the same miscalibration signal as a clean-document
false positive.

### Mutation sizing

`verify_line_items_math` / `verify_totals_math` accept `max(0.01, 0.5%
relative)` (Gap 31). Every arithmetic mutation shifts its figure by
`max(5% of the amount, 25.00)` — about an order of magnitude of headroom — so a
recall miss is never explainable as a near-miss, on a EUR 18,170 invoice or an
INR 102,070 one alike. Asserted by
`test_arithmetic_mutations_clear_the_verification_tolerance`, which reads
`REL_TOLERANCE` from the product rather than restating it.

### What a "hit" is

A hit requires the **expected alert type specifically**. A pipeline that raised
`tax_mismatch` on every document would otherwise score 100% recall while being
useless. `test_a_wrong_alert_type_is_not_a_hit` pins that.

## The corpus

Four clean documents, thirteen seeded cases. Full detail in `case_manifest.md`.

| Document | Direction | Why this shape |
|---|---|---|
| `us_flat_sales_tax` | INBOUND | The baseline: one invoice-level flat sales tax, no discount, no per-line tax. If any check fires here the check is miscalibrated. |
| `india_cgst_sgst_round_off` | INBOUND | CGST 9% + SGST 9% summing to a `tax_amount` that is **never printed as a single number**. This is what Gap 69's component-aware fallback exists for, so it is also what would false-positive if that fallback broke. |
| `eu_reverse_charge_zero_vat` | INBOUND | Zero tax that is *correct*, not missing. A corpus of only taxed invoices cannot tell a correctly-zero tax from a dropped one. Subtotal and grand total are also equal here, which catches a check that matched the wrong field. |
| `outbound_trade_discount` | OUTBOUND | The only outbound document, and the only one where `missing_required_field` can fire at all (`_DIRECTION_PROFILES["INBOUND"].required_fields` is empty by design). Carries a 5% trade discount — see the finding below. |

Ten distinct alert types are seeded: `tax_mismatch`, `line_items_mismatch`,
`line_item_calculation_mismatch`, `missing_required_field`,
`total_not_verified_in_source`, `tax_amount_not_verified_in_source`,
`subtotal_not_verified_in_source`, `unit_price_not_verified_in_source`,
`line_item_not_verified_in_source`, `low_confidence_field`.

**Not seeded, and therefore not measured:** `extraction_failed` (a parse/LLM
failure, not a document property) and `token_limit_exceeded` (a pre-flight
guardrail that returns before the graph runs). Both are reachable but neither is
a document-quality check, so neither belongs in a recall figure.

## What the first run found

Both modes were run for real on 2026-08-23. Full output in `runs/`.

### `--mode verify` — 4 clean, 13 seeded

| | Alert fired | Stayed silent |
|---|---|---|
| **Seeded** | 13 (TP) | 0 (FN) |
| **Clean** | 1 (FP) | 3 (TN) |

* **Alert recall: 100%** (13/13). Every one of the ten seeded check types fired
  on the case it was seeded for.
* **Clean-document false-positive rate: 25%** (1/4) — one document, described
  below.
* Document-level precision: 92.9%.
* No collateral alert types; every alert raised on a seeded case was either the
  expected type or a declared tolerated side effect.

### `--mode live` — real Azure OpenAI `gpt-5-mini`, end to end

| | Alert fired | Stayed silent |
|---|---|---|
| **Seeded (5 document-surface)** | 5 (TP) | 0 (FN) |
| **Clean** | 1 (FP) | 3 (TN) |

* **Field-level accuracy: 81/81 = 100%.** Every graded field on all four clean
  documents was extracted correctly, including `round_off: 0.00` on the GST
  invoice (a zero the model had to transcribe rather than drop) and the summed
  `tax_amount` of INR 15,570.00 that appears nowhere on the document as a single
  figure.
* **Alert recall: 100%** on the five document-surface cases. The eight
  extraction-surface cases were reported `not_applicable` and skipped without
  spending tokens.
* Same single false positive as verify mode, which is the point of running both:
  it is a property of the check, not of either mode.

**Read the 100% field accuracy carefully.** It is a real measurement of a real
model over this corpus, and it means the corpus does not currently discriminate
on extraction accuracy — it is a regression detector and a baseline, not a
difficulty measure. Making it discriminate needs harder documents (noisy OCR,
multi-page, rotated tables, genuinely ambiguous layouts), which is real
additional work and is not done. Do not report this number as "extraction is
100% accurate"; report it as "extraction is 100% accurate on four clean,
well-formed synthetic documents in text-only mode".

### Finding: a clean, arithmetically-correct discounted outbound invoice always alerts

`outbound_trade_discount` is internally consistent — 11,400.00 − 570.00 +
758.10 = 11,588.10 — and it raises `tax_mismatch` in **both** modes.

The cause is not the check. `OutboundInvoiceExtractionSchema`
(`agents/extraction_agent.py`) has no `discount_amount`, no `discount_percent`
and no `round_off` field, so a discount printed on an outbound invoice has
nowhere to go. `verify_node` then calls `verify_totals_math(..., discount_amount=
data.get("discount_amount"), ...)`, which is `None` for every outbound document
by construction, and the check computes `11,400.00 + 758.10 = 12,158.10` against
a printed total of `11,588.10`.

So **every outbound invoice carrying a trade discount or a rounding line lands
on `NEEDS_REVIEW` for a correct extraction of a correct document**, and no
amount of tuning `verify_totals_math` fixes it — the information is not in the
record. The inbound schema has all three fields; this is a Gap-283-era
divergence between the two schemas, not a deliberate difference.

This case is **deliberately left in the clean set** rather than sanitised. It is
the only reason the false-positive rate is a measurement rather than a
formality, and a benchmark whose clean set is curated until it goes quiet is
measuring the curation. It is pinned by
`test_known_outbound_discount_false_positive_is_still_present`, which should be
deleted (not edited) when the schema is fixed.

Filed as Gap 293 in `be_features_tracker.md`. Not fixed in this pass: adding
fields to the outbound extraction schema changes what the model is asked to
produce and what `queue_worker/outbound_handlers.py` and
`routers/outbound_audit.py` consume, which is a product change, not a test
change.

## Limits — read before trusting a number from here

1. **Text only.** `extract_node` takes the multimodal branch only when
   `LLM_PROVIDER=azure` *and* `state["images"]` is non-empty. These cases carry
   no PDF, so live mode exercises the text-prompt branch. That is a real branch
   (it is the non-Azure and no-image path), but an accuracy figure from here is
   not a claim about multimodal extraction, which is what production uses on
   PDFs.
2. **No Document Intelligence.** OCR text is rendered from the spec, so nothing
   here measures OCR quality — only what the extraction LLM and the verification
   checks do with already-clean text. Real OCR noise (dropped decimals, merged
   columns, mis-read glyphs) is absent, and it is a real source of both missed
   issues and false positives in production.
3. **Default tolerances only.** Every case runs with `rules=None`. Feature 18
   tenant overrides are a separate axis and are not covered.
4. **Four documents is a small clean set.** A 25% false-positive rate is one
   document. The figure is directionally real and statistically thin; treat the
   *identity* of the false positive as the finding, not the percentage.
5. **Eight of thirteen seeded cases are verify-mode-only** (see "Two mutation
   surfaces"). Live-mode recall is over five cases.
6. **Synthetic vendors and synthetic numbers**, by construction — which is also
   why this corpus can be committed while `tests/{us,india,eu}` cannot.
7. **Recall of 100% is a floor statement about the ten seeded types, not about
   the pipeline.** It says these ten checks fire when the exact issue they were
   written for is present. It says nothing about issue shapes nobody has thought
   to seed, which is the residual of the same blind spot the whole track exists
   to reduce.

## What would make this a stronger benchmark

Listed rather than done, so the gap between what exists and what would be ideal
is visible:

* Harder clean documents — multi-page, noisy OCR, rotated/merged table cells —
  so field accuracy discriminates instead of saturating.
* Real PDFs so the multimodal branch is exercised.
* A second seeded case per alert type on a *different* parent document, so
  per-check recall is over more than one or two cases.
* Seeded cases for `extraction_failed` and `token_limit_exceeded`.
* A model-comparison run (the feature doc's "Model comparison" section):
  identical corpus, swap only the model, keep everything else fixed. The harness
  already supports this — `--mode live` reads the deployment from config — but
  no candidate has been run.
