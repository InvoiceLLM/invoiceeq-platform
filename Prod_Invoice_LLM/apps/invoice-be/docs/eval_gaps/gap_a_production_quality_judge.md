# GAP-A: Enable Production Quality Judge
**Priority:** P1-CRITICAL  
**File:** `services/online_quality_judge.py` (already built)  
**Config flag:** `ENABLE_PRODUCTION_QUALITY_JUDGE` (default: `False`)

---

## Why This Matters

Right now every live user chat turn goes **unscored**. The golden bank eval only runs offline against fixed Q&A pairs — it tells you if the model *can* answer correctly, not if it *is* answering correctly in production traffic today.

**Without this enabled:**
- A model degradation (e.g. after Azure OpenAI updates their model) is invisible until users complain
- The AI Control Tower workbook's "Production Quality" panel has **no data**
- `faithfulness` and `relevance` scores in App Insights show only golden/predeploy rows, never real users

**With this enabled:**
- Every live turn gets `faithfulness` + `relevance` + `tone` + `helpfulness` + `completeness` scored
- Scores land in `agent_eval_run` (Postgres) tagged `run_source=production`
- Scores mirror to `agent_eval_run` event in App Insights
- Workbook can compare: "golden bank quality vs. live production quality"

**Cost:** 2 extra LLM calls per turn (`eval.combined_soft` + `eval.persona`). Both tracked in telemetry.

---

## DEV Environment

### What to do

**Step 1: Set the flag in `.env`**
```ini
# apps/invoice-be/.env
ENABLE_PRODUCTION_QUALITY_JUDGE=true
```

**Step 2: Run a few test chat turns locally, check logs**
```bash
cd Prod_Invoice_LLM/apps/invoice-be
# Start the API and send a chat message
# Then check logs for:
grep "agent_eval_run" logs/  # or stdout
```

**Step 3: Verify the row is written to Postgres**
```sql
SELECT agent_name, passed, faithfulness_score, relevance_score, run_source, created_at
FROM agent_eval_run
WHERE run_source = 'production'
ORDER BY created_at DESC
LIMIT 5;
```

**Step 4: Check cost impact**
```bash
# In App Insights logs (or local stdout), look for eval.* agent calls:
# agent_name = "eval.combined_soft" and "eval.persona"
# tokens_in + tokens_out on those = your extra cost per turn
```

**Step 5: Run for 2 days in dev, monitor**
- Does it add > 3 seconds latency to any turn? → Problem
- Does faithfulness score look reasonable (> 0.7 average)? → Good
- Are there any null scores (judge failures)? → Investigate

---

## PROD Environment

### What to do ONLY after dev validation passes

**Step 1: Set via Azure Container App secret/env**
```bash
az containerapp update \
  --name ca-invoice-be-prod \
  --resource-group invoice-llm-prod \
  --set-env-vars ENABLE_PRODUCTION_QUALITY_JUDGE=true
```

**Step 2: Monitor App Insights for 24h**
```kql
// Verify production rows are arriving
customEvents
| where name == "agent_eval_run"
| where customDimensions.run_source == "production"
| summarize count(), avg(todouble(customDimensions.faithfulness_score)) by bin(timestamp, 1h)
| order by timestamp desc
```

**Step 3: Set alert if pass rate drops below 70%**
```kql
// Alert query for Azure Monitor scheduled query rule
customEvents
| where name == "agent_eval_run"
| where customDimensions.run_source == "production"
| where timestamp > ago(6h)
| summarize pass_rate = avg(todouble(customDimensions.pass))
| where pass_rate < 0.70
```

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Flag value | `true` for testing | `true` after validation |
| Log retention | 30 days | 90 days |
| Score rows | Disposable (test DB) | Real audit trail |
| Cost impact | Small (low traffic) | Monitor carefully |
| Rollback | Just set flag to `false` | Same — instant rollback |

---

## Files Involved

| File | Change Needed |
|------|--------------|
| `apps/invoice-be/.env` | Add `ENABLE_PRODUCTION_QUALITY_JUDGE=true` |
| `apps/invoice-be/.env.example` | Document the new flag |
| `infra/modules/compute/invoice-be.bicep` | Add env var for prod |
| `services/online_quality_judge.py` | **Already built — no code change** |
| `routers/chat.py` | **Already wired — no code change** |

---

## Definition of Done

- [ ] Flag tested in dev for 2+ days
- [ ] No latency regression > 500ms p95
- [ ] `agent_eval_run` rows appearing with `run_source=production`
- [ ] Faithfulness score average > 0.70
- [ ] Flag enabled in prod
- [ ] Alert rule set in Azure Monitor
- [ ] `.env.example` updated with flag + documentation
