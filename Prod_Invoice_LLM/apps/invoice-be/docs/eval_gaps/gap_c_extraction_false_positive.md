# GAP-C: Fix Extraction Benchmark False Positive
**Priority:** P1-CRITICAL  
**Current result:** 25% false-positive rate (1/4 clean docs fires a wrong alert)  
**Document offending:** `outbound_trade_discount__clean` fires `tax_mismatch`

---

## Why This Matters

The extraction benchmark measures two things:
1. **Alert Recall** — did we catch real problems? (currently 100% — GOOD)
2. **False Positive Rate** — are we crying wolf on clean invoices? (currently 25% — BAD)

A 25% false positive rate means **1 in 4 clean invoices gets incorrectly flagged for human audit**. In production with 100+ invoices per day, that's 25 invoices/day sent to the audit queue unnecessarily. This:
- Wastes auditor time on non-issues
- Erodes trust in the SAGE audit system ("it flags everything anyway")
- Reduces meaningful signal from real audit alerts

The benchmark document `docs/extraction_benchmark/runs/live-latest.md` shows:
```
outbound_trade_discount__clean → NEEDS_REVIEW → tax_mismatch fired (WRONG)
```

This is the one known false positive. Target: **0 false positives on clean documents**.

---

## DEV Environment

### Step 1: Read the offending document

```bash
cat "Prod_Invoice_LLM/apps/invoice-be/docs/extraction_benchmark/documents/outbound_trade_discount__clean.txt"
```

Understand:
- What type of invoice is this? (Outbound invoice with a trade discount)
- What does the tax structure look like?
- What does `tax_amount` field show?

### Step 2: Run benchmark in verify mode to reproduce

```bash
cd Prod_Invoice_LLM/apps/invoice-be
python scripts/run_extraction_benchmark.py --mode verify --cases outbound_trade_discount__clean
```

This runs without calling Azure OpenAI (free). It should reproduce the `tax_mismatch` alert.

### Step 3: Understand WHY tax_mismatch fires

**File to investigate:** `utils/verification_tools.py`

Look at `verify_tax_amount_in_source_text()` and `verify_totals_math()`. The likely cause is one of:

**Hypothesis A — Trade discount affects tax base calculation:**
The invoice has a trade discount that reduces the subtotal. The verification logic may be computing:
```
expected_tax = subtotal * tax_rate
```
But the actual `subtotal` printed on the invoice is BEFORE discount, while `tax_amount` is computed AFTER discount. So the numbers don't match.

**Hypothesis B — Tolerance too tight:**
The tax figure on a trade-discount invoice may involve rounding that falls outside the current tolerance window.

**Hypothesis C — Missing field in verification:**
The `discount_amount` field exists in the schema but the tax verification may not account for it.

### Step 4: Fix the verification logic

Once root cause is found, fix in `utils/verification_tools.py`:

```python
# Example fix if Hypothesis A is correct:
def verify_tax_amount_in_source_text(extracted, source_text):
    # If trade discount is present, tax is on discounted subtotal
    if extracted.get("discount_amount"):
        taxable_base = extracted.get("subtotal", 0) - extracted.get("discount_amount", 0)
    else:
        taxable_base = extracted.get("subtotal", 0)
    # ... rest of verification
```

### Step 5: Re-run benchmark to confirm fix

```bash
# Verify mode first (free):
python scripts/run_extraction_benchmark.py --mode verify

# Expected: 0 false positives, recall still 100%
# Document result: should update live-latest.md

# Then live mode (costs tokens):
python scripts/run_extraction_benchmark.py --mode live
```

### Step 6: Update benchmark baseline

The `live-latest.md` file will auto-update after a live run. Commit the new results.

---

## PROD Environment

### What to do after dev fix is validated

**Step 1: Deploy with the normal release cycle**
The fix is in `utils/verification_tools.py` — it goes out with the next tagged release.

**Step 2: Run benchmark against prod after deploy**
```bash
# From the nightly benchmark job (already scheduled):
# Or manually trigger:
python scripts/run_extraction_benchmark.py --mode live --run-label post-fix-validation
```

**Step 3: Check existing invoices in prod**
The false positive may have caused real invoices in production to be incorrectly flagged. After fixing:

```sql
-- Find invoices that might have been incorrectly flagged for tax_mismatch
SELECT id, invoice_number, vendor_name, status, alerts
FROM invoice
WHERE status = 'AUDIT_REQUIRED'
AND alerts::text LIKE '%tax_mismatch%'
AND created_at > '2026-08-01'  -- since benchmark was built
ORDER BY created_at DESC;
```

Review these manually — some may need to be re-audited with the corrected verification.

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Fix location | `utils/verification_tools.py` | Same file, via deploy |
| Testing | Run benchmark locally | Run benchmark via nightly job |
| Impact of fix | No historical invoices affected | May retroactively fix past false flags |
| Rollback | Revert the file | Revert the release tag |

---

## Files Involved

| File | Change |
|------|--------|
| `utils/verification_tools.py` | Fix `verify_tax_amount_in_source_text()` or `verify_totals_math()` |
| `docs/extraction_benchmark/runs/live-latest.md` | Auto-updated after re-run |
| `tests/test_extraction.py` | Add a unit test for trade-discount invoice tax verification |

---

## Definition of Done

- [ ] Root cause of false positive identified (which function, which logic)
- [ ] Fix applied and unit test added in `tests/test_extraction.py`
- [ ] Benchmark verify mode: 0 FP on 4 clean docs
- [ ] Benchmark live mode: Alert Recall still 100%, FP rate = 0%
- [ ] New `live-latest.md` committed
- [ ] Prod deploy + post-deploy benchmark run confirms fix
- [ ] Past incorrectly-flagged prod invoices reviewed
