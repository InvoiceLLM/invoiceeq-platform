# GAP-H: Audit All KQL Queries for run_source Filter
**Priority:** P3-MEDIUM  
**Files:** `infra/monitoring/*.kql` and `infra/monitoring/*.json` (workbooks)

---

## Why This Matters

`telemetry.py` (Gap 304) introduced `run_source` field on every event:
- `production` — a real user turn
- `golden` — an offline golden bank eval turn
- `predeploy` — the pre-deploy gate subset

**The problem:** Any KQL query that sums tokens, averages latency, or calculates costs WITHOUT filtering `run_source == "production"` is including eval traffic in production metrics.

**Real-world example of the data pollution:**
```
Nightly eval run: 20 cases × 4 LLM judge calls = 80 extra LLM calls
These all land in customEvents as llm_agent_call with run_source=golden
If your cost KQL doesn't filter: your "production cost per day" includes eval cost
Result: cost dashboard overstates by ~10-30% on nightly run days
```

This was the **exact reason** `run_source` was built (documented in `telemetry.py` lines 314-343). But building the field doesn't automatically fix existing queries.

---

## DEV Environment

### Step 1: Find all KQL files

```bash
find Prod_Invoice_LLM/infra/monitoring/ -name "*.kql" -o -name "*.json"
```

Current files:
- `llm_cost_by_tool.kql`
- `llm_cost_rollup_nightly.kql`
- `chat_thread_sessions.kql`
- `ai_control_tower_workbook.json`
- `cost_health_workbook.json`

### Step 2: Check each .kql file

For each `.kql` file, verify it has this filter:
```kql
| where customDimensions.run_source == "production"
```

**Example of a query that NEEDS the filter:**
```kql
// BAD — includes eval traffic:
customEvents
| where name == "llm_agent_call"
| summarize total_tokens = sum(todouble(customDimensions.tokens_total))
```

**Example of a corrected query:**
```kql
// GOOD — production only:
customEvents
| where name == "llm_agent_call"
| where customDimensions.run_source == "production"      // <- ADD THIS
| summarize total_tokens = sum(todouble(customDimensions.tokens_total))
```

### Step 3: Check workbook JSON files

Workbook JSON files contain embedded KQL queries. Open each and search for `llm_agent_call` and `agent_eval_run` — any query on those events should have the `run_source` filter.

```bash
grep -n "run_source" infra/monitoring/ai_control_tower_workbook.json
grep -n "run_source" infra/monitoring/cost_health_workbook.json
```

Any section that does NOT have `run_source` in it but queries `llm_agent_call` or `agent_eval_run` needs the filter added.

### Step 4: What queries SHOULD NOT have the filter

Some queries are intentionally cross-population:
- Trend charts comparing `golden` vs `production` quality — these SHOULD show all run_sources
- The `agent_eval_summary` event queries — these only have `golden` and `predeploy` rows, no production rows

The rule:
- **Cost/latency KQL → must filter `production` only**
- **Quality score KQL for AI Control Tower → query specific run_source per panel**
- **Signal comparison KQL → may intentionally show multiple run_sources**

---

## PROD Environment

### What to do

**Step 1: Deploy corrected KQL / workbook JSON**

Workbooks in Azure Monitor are ARM resources. The `workbook-ai-control-tower-only.bicep` and `workbook-cost-health-only.bicep` files deploy them:

```bash
# After fixing the JSON files:
az deployment group create \
  --resource-group invoice-llm-prod \
  --template-file infra/workbook-ai-control-tower-only.bicep \
  --parameters infra/params.prod.json
```

**Step 2: Verify the fix in Azure Portal**

Open the AI Control Tower workbook and the Cost Health workbook. Look at:
- LLM Cost by Tool panel — does it drop on days after a nightly eval run?
- Before fix: Cost spike on nightly eval day
- After fix: Cost should be flat (eval cost filtered out)

**Step 3: One-time: check historical data for inflation**

```kql
// Check how much eval traffic was mixing into production numbers:
customEvents
| where name == "llm_agent_call"
| where timestamp > ago(30d)
| summarize
    prod_calls = countif(customDimensions.run_source == "production"),
    eval_calls = countif(customDimensions.run_source in ("golden", "predeploy")),
    no_source = countif(isnull(customDimensions.run_source))
```

If `eval_calls` is significant relative to `prod_calls` — your historical cost numbers were inflated.

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Fix location | `.kql` files + workbook `.json` files | Same files, deployed via Bicep |
| Testing | Run queries in App Insights Logs locally | View workbooks in Azure Portal |
| Historical impact | N/A (dev data is throwaway) | Historical cost numbers may have been inflated |
| Rollback | Revert the files | Redeploy previous workbook JSON |

---

## Files Involved

| File | Change |
|------|--------|
| `infra/monitoring/llm_cost_by_tool.kql` | Add `run_source == "production"` filter |
| `infra/monitoring/llm_cost_rollup_nightly.kql` | Add `run_source == "production"` filter |
| `infra/monitoring/chat_thread_sessions.kql` | Review — may be fine |
| `infra/monitoring/ai_control_tower_workbook.json` | Audit all embedded queries |
| `infra/monitoring/cost_health_workbook.json` | Audit all embedded queries |

---

## Definition of Done

- [ ] All cost/latency KQL queries have `run_source == "production"` filter
- [ ] Quality score queries correctly scope by run_source per panel
- [ ] Workbook JSON files updated with corrected queries
- [ ] Workbooks redeployed to prod
- [ ] Historical data inflation assessed (one-time KQL check)
- [ ] New baseline cost numbers documented after fix
