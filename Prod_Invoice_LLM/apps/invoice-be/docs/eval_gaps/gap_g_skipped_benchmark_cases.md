# GAP-G: Investigate and Fix 8 SKIPPED Benchmark Cases
**Priority:** P3-MEDIUM  
**Evidence:** `docs/extraction_benchmark/runs/live-latest.md` shows 8 of 13 seeded cases as SKIPPED

---

## Why This Matters

The live benchmark ran on 23 Aug 2026 with 13 seeded (fault-planted) cases. Only 5 actually ran; 8 showed `SKIPPED` status with `0ms` latency.

**Skipped cases:**
```
india_cgst_sgst_round_off__fabricated_total
us_flat_sales_tax__tax_silently_corrected
india_cgst_sgst_round_off__tax_silently_corrected_split
eu_reverse_charge_zero_vat__subtotal_not_in_source
india_cgst_sgst_round_off__unit_price_not_in_source
us_flat_sales_tax__line_amount_not_in_source
outbound_trade_discount__required_field_dropped
us_flat_sales_tax__low_field_confidence
```

These case names reveal **3 categories of faults that were never tested:**
1. `fabricated_total` / `silently_corrected` / `silently_corrected_split` — faults where the source document number was silently altered
2. `*_not_in_source` — faults where a field value exists in extraction but has no source text to match against
3. `required_field_dropped` / `low_field_confidence` — extraction surface issues

**Why this matters:** You have 100% recall on the 5 cases that ran — but the 8 skipped cases represent fault types that may NOT be caught. You don't know because they were never run.

---

## DEV Environment

### Step 1: Run in verify mode to see what happens

```bash
cd Prod_Invoice_LLM/apps/invoice-be
python scripts/run_extraction_benchmark.py --mode verify 2>&1 | head -100
```

`verify` mode is deterministic and free (no LLM calls). If these cases are also skipped in verify mode, the skip is in the script logic, not an API timeout.

### Step 2: Run the script with verbose output for a specific skipped case

```bash
python scripts/run_extraction_benchmark.py \
  --mode verify \
  --cases india_cgst_sgst_round_off__fabricated_total \
  --verbose
```

Look for why it's being skipped. Common reasons:
- A flag like `--cases` that filters by a subset
- A mode-specific case filter (e.g., `live` mode only runs some case types)
- An exception that silently marks the case as SKIPPED
- The case document text format being unparseable

### Step 3: Read the script to understand SKIPPED logic

```bash
cat scripts/run_extraction_benchmark.py | grep -A 5 -i "skip"
```

Find where a case gets marked SKIPPED. Is it intentional or a bug?

### Step 4: Read the case document files

```bash
# Look at a skipped vs a passing case:
cat "docs/extraction_benchmark/documents/us_flat_sales_tax__clean.txt"          # PASSES
cat "docs/extraction_benchmark/documents/us_flat_sales_tax__tax_silently_corrected.txt"  # SKIPPED
```

Are the skipped case documents formatted differently?

### Step 5: Fix or document

**If it's a bug:** Fix the script and re-run.  
**If it's intentional:** The case manifest needs to say WHY these are skipped — today the markdown just shows SKIPPED with no explanation.

Update `docs/extraction_benchmark/case_manifest.md` (if it exists) or create it.

---

## PROD Environment

### What to do after fix

**Run the full benchmark against prod to establish a real baseline:**
```bash
python scripts/run_extraction_benchmark.py \
  --mode live \
  --run-label nightly \
  --all-cases   # if such a flag exists
```

**Expected outcome after fix:**
- 13/13 seeded cases run (no SKIPPED)
- Recall may drop from 100% — that's okay, it's honest
- False positive rate may also change — document the new baseline

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Fix location | `scripts/run_extraction_benchmark.py` | Same, via deploy |
| Testing | `--mode verify` (free) | `--mode live` (costs tokens) |
| Impact on nightly | None until deployed | Nightly job runs more cases |
| Risk | Low — only adds more tests | Low — but may reveal previously unknown failures |

---

## Files Involved

| File | Change |
|------|--------|
| `scripts/run_extraction_benchmark.py` | Fix SKIPPED logic (if bug) |
| `docs/extraction_benchmark/case_manifest.md` | Document why each case is/isn't run |
| `docs/extraction_benchmark/runs/` | Will have new results after fix |

---

## Definition of Done

- [ ] Root cause of SKIPPED identified (bug vs. intentional)
- [ ] If bug: fix applied and all 13 seeded cases run in verify mode
- [ ] If intentional: documented in case_manifest.md with reason
- [ ] Full live benchmark run after fix — new baseline established
- [ ] Recall and FP rate after including all 13 cases documented
