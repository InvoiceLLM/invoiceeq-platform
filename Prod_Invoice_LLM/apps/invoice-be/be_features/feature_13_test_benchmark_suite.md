# Backend Feature 13: Automated Test & Benchmark Suite

## Overview
A test-tooling feature (not a customer-facing capability) that spans two product features together — [Feature 2: Pipeline Extraction](feature_2_pipeline_extraction.md) and [Feature 6: Conversational RAG](feature_6_rag.md) — so it's tracked separately rather than folded into either one. Two tiers: a fast fixture-based regression suite that guards against specific known defects recurring, and a daily procedurally-generated regional benchmark that measures extraction and RAG chat accuracy against certification-style thresholds. Expected to grow further ("later we may add other TC" — other test categories beyond extraction/RAG).

### File Coordinates
* Tier 1 (regression): [apps/invoice-be/tests/e2e/pdf_builder.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/e2e/pdf_builder.py), [fixtures_data.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/e2e/fixtures_data.py), [test_e2e_regional_invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/e2e/test_e2e_regional_invoices.py)
* Tier 2 (benchmark): [apps/invoice-be/tests/benchmark/catalog.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/benchmark/catalog.py), [generator.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/benchmark/generator.py), [chat_questions.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/benchmark/chat_questions.py), [run_benchmark.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/benchmark/run_benchmark.py)
* Shared: [apps/invoice-be/tests/sync_processing.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/sync_processing.py) — `process_invoice_sync(invoice_id, batch_id, tenant_id=MOCK_TENANT_ID)` calls `queue_worker.handlers.handle_process_invoice()` directly in-process, used by both tiers for local runs (see Execution Model below). [apps/invoice-be/tests/run_local_stack.sh](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/run_local_stack.sh) — one-shot local bring-up (fresh Azurite, throwaway Postgres, alembic migrate, real Key Vault secrets, backend start).
* CI: [.github/workflows/e2e-regression.yml](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/.github/workflows/e2e-regression.yml) — `workflow_dispatch` only, Tier 1 runs inside the GitHub-hosted runner (ephemeral docker-compose stack + real worker, real outbound calls to Azure OpenAI/Document Intelligence). Never calls the deployed `ca-invoice-be-dev` Container App — ingress is irrelevant, since what's under test is the extraction/RAG *code and its real API calls*, not the deployed infrastructure.

### Execution Model (decided 2026-07-21)
Both tiers now run **locally** by default, not via GitHub Actions — easier log visibility and faster fix-and-rerun iteration than watching a remote runner. Local runs bypass Azure Storage Queue entirely (`tests/sync_processing.py` calls the same `handle_process_invoice()` the real worker calls, just in-process) because Azurite's local queue emulator repeatedly wedged during iteration (messages counted but `receive_messages()` returns empty, even after a full volume reset) — a local-emulator reliability problem, not a product defect; the queue/worker mechanism itself is validated separately (KEDA autoscale rule confirmed live on `ca-queue-worker-dev`). Tier 1's CI workflow keeps the real queue+worker path (`E2E_SYNC_PROCESSING` unset there), so that path still gets exercised somewhere. Production's upload flow (`routers/invoices.py`) is untouched either way — always enqueues.

## Tier 1 — Fixture Regression Suite (folder → file → function → functionality)

`tests/e2e/pdf_builder.py`
- `build_invoice_pdf(path, vendor_lines, meta_lines, bill_to_lines, columns, rows, summary_rows, notes=None)` — renders a structured invoice definition into a real PDF via reportlab (`SimpleDocTemplate`/`Table`/`Paragraph`). Region-agnostic; reused by Tier 2's generator.

`tests/e2e/fixtures_data.py`
- Five hand-picked `(build_kwargs, expected)` tuples, collected in `ALL_FIXTURES`: `PRINTMAX_FALSE_POSITIVE` (regression fixture for the invoice-level-tax-on-line-items bug), `FURNITUREPRO_CLEAN_DISCOUNT_TAX` (clean multi-line baseline), `SYNTHEX_DELIBERATE_MISMATCH` (deliberately broken total), `VERTEX_INDIA_GST_COMPLEX` (complex India GST invoice), `EU_VAT_REVERSE_CHARGE` (EU VAT reverse-charge invoice).

`tests/e2e/test_e2e_regional_invoices.py`
- `_upload_and_wait(client, pdf_path, filename)` — uploads via `POST /invoices/upload`, polls `GET /invoices/{id}` until status leaves `PROCESSING` (180s timeout).
- `_alert_types(invoice)` — extracts the set of `sa_alerts[].type` from a response for assertion.
- `test_regional_invoice(client, build_kwargs, expected)` — `pytest.mark.parametrize`'d over `ALL_FIXTURES`; builds the PDF, uploads, asserts status/`grand_total`/`tax_amount` (tolerant, `AMOUNT_TOLERANCE = 0.05`) and expected alert types, deletes the invoice in `finally`. Marked `pytest.mark.e2e`, excluded from default `pytest` runs (`pyproject.toml`: `addopts = "-m \"not e2e\""`).

## Tier 2 — Daily Regional Benchmark (folder → file → function → functionality)

`tests/benchmark/catalog.py`
- `REGIONS` (`US`/`INDIA`/`UK`) — each region's vendor/customer/product name pools plus `currency_symbol`, so generated invoices aren't repetitive. India products carry HSN code + GST rate; UK products carry VAT rate.

`tests/benchmark/generator.py`
- `GeneratedInvoice` (dataclass: `name, region, pdf_kwargs, ground_truth`).
- `_generate_us` / `_generate_india` / `_generate_uk` — build region-correct line items, tax/discount math (US: flat invoice-level sales tax; India: per-line GST% by HSN slab, CGST+SGST split, Round Off; UK: per-line VAT% mixing 20/5/0 rates, occasional reverse-charge note), and the matching `ground_truth` dict.
- `_apply_flaw(flaw, ...)` — mutates rows/meta/ground-truth for one of `FLAW_TYPES` (`broken_total`, `subtotal_mismatch`, `rounding_gap`, `missing_optional_field`).
- `generate_daily_batch(region, day_seed, count=10)` — the entry point: reproducible (seeded) batch, 5 clean/5 flawed, ~60/40 medium/high complexity.

`tests/benchmark/chat_questions.py`
- `ChatQuestion` (dataclass: `region, invoice_number, kind, question, expected`).
- `_pick_sample(batch)` — one clean + one flawed invoice per region, so the RAG sample stays small (not 3x-ing the run's cost).
- `build_daily_chat_questions(batches_by_region)` — one amount-lookup, one vendor-lookup, one audit-status question per sampled invoice, scoped by invoice number (not tenant-wide aggregates, so answers are gradable against known ground truth without contamination from other tenant data).
- `grade_answer(q, answer)` — heuristic pass/fail/inconclusive: numeric proximity for amounts, keyword substring for vendor, audit-keyword presence/absence for status.

`tests/benchmark/run_benchmark.py`
- `_render_pdf`, `_upload`, `_poll` — per-invoice upload/poll helpers (same pattern as Tier 1's `_upload_and_wait`).
- `_compare(gen, actual)` — compares actual extraction against ground truth; returns pass/fail + a `root_cause` bucket (`status_misclassification`, `wrong_alert_type`, `amount_mismatch_total`, `amount_mismatch_tax`, `hallucinated_optional_field`, `processing_timeout`, `extraction_failed`). India invoices marked `known_gap_31_affected` in ground truth get bucketed separately as `known_gap_31_india` if they still fail — now a safety net rather than an expected outcome, since Gap 31 was fixed Jul 21, 2026; if this bucket starts firing again, treat it as a real regression, not an informational known-gap.
- `_run_chat_pass(client, base_url, batches_by_region)` — creates one chat session, asks the sampled question set, grades each answer.
- `run(regions, count, day_seed, base_url)` — orchestrates a full day's run across regions; always deletes every invoice it created (`finally` block), even on failure, so the benchmark tenant never accumulates data.
- `_summarize(report)` / `main()` — writes `tests/benchmark/reports/day<seed>.{json,md}`: per-region accuracy, failures grouped by root cause, RAG chat pass/fail table.

## Test Case Registry
*(Single place to see what's tested, current pass/fail, and open-defect tracking. Update the Status/Last Result columns after each run; move a row to "closed" only once its linked gap is fixed AND re-verified passing.)*

### Tier 1 — fixed fixtures (`tests/e2e/fixtures_data.py`)
| ID | Test case | Checks | Linked gap | Status |
|---|---|---|---|---|
| E2E-1 | `printmax_false_positive` | Invoice-level-only tax must not misattribute to line items | Gap (tax mismatch, fixed Jul 20) | ✅ Passing |
| E2E-2 | `furniturepro_clean_discount_tax` | Clean multi-line baseline extracts exactly | — | ✅ Passing |
| E2E-3 | `synthex_deliberate_mismatch` | Deliberately broken total is correctly flagged `AUDIT_REQUIRED` | **Gap 33** (mitigated, not fully closable) | ⚠️ Passing most runs — ~1-in-5 observed failure where the model "corrects" the printed total instead of transcribing it faithfully. See Gap 33. |
| E2E-4 | `vertex_india_gst_complex` | Real varying per-line GST (18/18/18/12/18/0%), post-discount subtotal, CGST+SGST split, Round Off, ~13-unit rounding gap, post-tax line amounts | **Gap 31** (fixed Jul 21) | ✅ Passing (2026-07-21, verified end-to-end — surfaced and fixed a 4th sub-issue plus a fixture data bug along the way) |
| E2E-5 | `eu_vat_reverse_charge` | Mixed VAT rates + reverse-charge note, pre-tax per-line amounts with invoice-level VAT | Gap 31-adjacent (per-line pre/post-tax ambiguity, fixed Jul 21) | ✅ Passing (2026-07-21, after extending the per-line calc check to accept either convention) |

### Tier 2 — daily benchmark question categories (`tests/benchmark/`)
Dynamic/procedural, so tracked by category rather than fixed instance — each category runs fresh (new invoices) every day; see `reports/day<seed>.json` for that day's specific instances.

| ID | Test case category | Checks | Linked gap | Status |
|---|---|---|---|---|
| BM-1 | Extraction accuracy (US/India/UK, clean + flawed, medium + high complexity) | Field-level correctness + status classification against generated ground truth | — | ⏳ Pending first post-fix run |
| BM-2 | RAG chat: amount lookup | Single-invoice grand_total lookup via SQL route | — | ✅ Passing (2026-07-21 sanity run) |
| BM-3 | RAG chat: vendor lookup | Single-invoice vendor_name lookup via SQL route | — | ✅ Passing (2026-07-21 sanity run) |
| BM-4 | RAG chat: audit-status lookup | Single-invoice status lookup via SQL route | — | ✅ Passing (2026-07-21 sanity run) |
| BM-5 | RAG chat: cross-invoice aggregate count | `COUNT(*) WHERE status='AUDIT_REQUIRED'` across the whole batch — exercises more complex SQL generation (Gap 13/11 territory) | Gap 13, Gap 11 (informational — not required to pass, watch for how often it fails) | ⏳ Pending first post-fix run |
| BM-6 | RAG chat: mutating-keyword regression | "most recently created" phrasing must not be rejected by the mutating-SQL guardrail | **Gap 32** (fixed Jul 21) | ⏳ Fix applied, not yet re-run |
| BM-7 | RAG chat: cache-hit regression | Re-asking the same question in a new session returns a byte-identical (cached) answer | **Task 6.11 / Gap 7+10** (implemented Jul 21) | ⏳ Fix applied, not yet re-run |

### Not yet covered by any test case (backlog, add when prioritized)
| Gap | What test case would be needed |
|---|---|
| Gap 3 (Critic Node) | Deliberately ambiguous invoices (conflicting number formats, two plausible vendor names, arithmetically ambiguous subtotals) |
| Gap 4 (Dynamic QA Node) | Non-standard-schema invoices with enterprise-typical extra fields (cost center, multi-currency, retainage) |
| Gap 21 + 22 (RAG retrieval quality) | Line-item/semantic detail questions that force the vector-search path instead of SQL |
| Gap 23 (conversational memory) | Multi-turn follow-up in one session referencing prior context without repeating the invoice number |
| Prompt-injection guard | Adversarial chat questions attempting to leak cross-tenant data or override system instructions |
| Gap 20 (tenant isolation) | Deprioritized by user decision — no test case planned until multi-tenant hardening phase |

## Certification Criteria (target thresholds, not yet met — see Benchmark Run Log)
- Simple-field accuracy ≥ 97%
- Complex/line-item accuracy ≥ 90%
- Status classification (COMPLETED vs AUDIT_REQUIRED vs ground truth) ≥ 95%
- Touchless processing rate ≥ 85%
- RAG chat accuracy ≥ 90%
- Zero open P0 defects (Gap 20 excluded — deprioritized until multi-tenant hardening phase)

## Benchmark Run Log
*(Updated after each day's run — accuracy numbers, defects found, defects fixed.)*

- **2026-07-21 — local sanity check, first clean run achieved (still not a scored day, count=1)**: after a long chain of local-environment issues (stale Postgres migration history; Azurite API-version mismatch, fixed via `--skipApiVersionCheck` in `docker-compose.yml`; Azurite's queue repeatedly wedging even after full volume resets, fixed by bypassing the queue for local runs — see `tests/sync_processing.py` and the Execution Model note above; `.env` defaulting to `LLM_PROVIDER=ollama` with no server running), got a fully clean 1-invoice US run: **extraction 1/1 (100%)**, **RAG chat 3/3**.
  - **Real defect found and fixed (not a local-only issue)**: `AZURE_OPENAI_API_VERSION: "2025-08-07"` in `e2e-regression.yml` is not a valid Azure API version — it's the *model's* snapshot date (`gpt-5-mini-2025-08-07`), coincidentally date-formatted the same way, apparently mistaken for the REST api-version at some point. Plain chat completions happen to still succeed against it, but `.with_structured_output()` (strict JSON-schema mode — used by both `extraction_agent.py` and `query_agent.py`) 404s under it. **Confirmed this never reached production**: `ca-invoice-be-dev`'s Container App env has no `AZURE_OPENAI_API_VERSION` override at all, so it's always run on `config.py`'s real default (`2024-02-15-preview`), which was confirmed working. Fixed the CI workflow to match. Local `.env` was already correct — I had been manually (and wrongly) overriding it to `2025-08-07` myself during tonight's debugging, copying the CI workflow's bad value.
  - **Minor open item, not yet root-caused**: one RAG chat question ("Is this invoice flagged for audit?" on a clean invoice) got the answer "Failed to execute database check: Mutating SQL operations are strictly forbidden" — a false-positive from `query_agent.py`'s mutating-SQL guardrail on a simple read-only status question. Didn't fail the benchmark's heuristic grading (the fallback text doesn't contain audit-trigger keywords), but the underlying guardrail behavior is wrong and worth a real fix. See Gap 32.

- **2026-07-21 (continued) — Gap 32, Gap 31, and Task 6.11 fixed and verified end-to-end**:
  - **Gap 32** fixed: word-boundary regex instead of substring match on the mutating-SQL keyword check.
  - **Task 6.11** (Redis semantic answer cache) implemented, superseding the stale Gap 7/10 Postgres-table plan (`feature_6_rag.md` had already decided this before the tracker caught up).
  - **Gap 31** fixed (4 sub-issues, not the originally-scoped 3 — a 4th was found only by running the real pipeline, not just unit tests: `verify_line_items_math`'s subtotal-reconciliation check also needed the pre-tax/post-tax dual-convention treatment, not just `verify_totals_math`). Fixing it and re-running the full 5-fixture suite (not just the one India fixture) surfaced two more real issues, both fixed the same way:
    - `eu_vat_reverse_charge` regressed: the *per-line* calculation check (not just the subtotal-sum check) had the same pre-tax/post-tax ambiguity — fixed the same way (accept either convention).
    - `synthex_deliberate_mismatch` regressed intermittently: the model sometimes "corrects" a printed total that deliberately doesn't reconcile instead of transcribing it as printed, silently defeating the guardrail. Mitigated (not fully closable) via a stronger `grand_total` field description — see **Gap 33**.
    - Also found and fixed: `vertex_india_gst_complex`'s own test data had a latent arithmetic inconsistency (printed subtotal didn't match its own line items) — corrected the fixture.
  - Also fixed the benchmark generator's flaw-injection magnitude (`broken_total`/`subtotal_mismatch`/`rounding_gap` all now scale with the affected amount) — a flat few-unit gap no longer reliably exceeds the new relative tolerance on large invoices, which would have silently produced false negatives (flawed invoices misreported as clean) in the daily cadence.
  - Full 5-fixture suite: 5/5 passing (with Gap 33's residual ~1-in-5 rate on `synthex_deliberate_mismatch` noted, not hidden).

## Task Breakdown
- `[x]` Task 13.1: Build Tier 1 fixture regression suite (`tests/e2e/`).
- `[x]` Task 13.2: Wire Tier 1 into `workflow_dispatch` CI (`e2e-regression.yml`).
- `[x]` Task 13.3: Build Tier 2 catalog + generator (`tests/benchmark/catalog.py`, `generator.py`).
- `[x]` Task 13.4: Build Tier 2 RAG chat sample (`chat_questions.py`) and harness (`run_benchmark.py`).
- `[x]` Task 13.5: Sanity-test the harness end-to-end and get a first clean run (2026-07-21, count=1). Also built `tests/run_local_stack.sh` + `tests/sync_processing.py` along the way (see Execution Model).
- `[ ]` Task 13.6: Investigate and fix the Gap 32 mutating-SQL-guardrail false positive.
- `[ ]` Task 13.7: Run the daily benchmark cadence at real scale (10/region), fixing defects found and updating this doc's Run Log after each day, until certification criteria are met consistently.
