# GAP-D: Verify Online Signals Job is Scheduled and Running
**Priority:** P2-HIGH  
**Script:** `scripts/emit_online_signals_job.py`  
**Expected cadence:** Every 6 hours

---

## Why This Matters

`services/online_eval_signals.py` computes 5 live-traffic quality signals from the database:

| Signal | What it measures | Confidence |
|--------|-----------------|------------|
| `zero_result_rate` | % of SQL turns that returned 0 rows | MEASURED |
| `thumbs_down_clustering` | Thumbs-down votes in a time window | MEASURED |
| `slow_turn_rate` | % of turns exceeding 10s | PROXY |
| `budget_exhaustion_rate` | % of turns hitting tool budget | OFFLINE-ONLY (until GAP-B) |
| `clarification_rate` | % of turns asking clarifying questions | HEURISTIC |

These signals are computed in `emit_online_signals_job.py` and pushed to App Insights as `online_eval_signal` events. The AI Control Tower workbook has a panel that reads these events.

**If the job is not scheduled/running:**
- The "Online Signals" panel of the workbook is empty
- You have no real-time quality visibility on live traffic
- Thumbs-down spikes go undetected
- Zero-result rate anomalies (Gap 224 false-confident-zero pattern) go undetected

---

## DEV Environment

### Step 1: Run the job manually to verify it works

```bash
cd Prod_Invoice_LLM/apps/invoice-be
python scripts/emit_online_signals_job.py
```

**Expected output:**
```
[online_signals] Computing signals for window: last 0.25 days (6 hours)
[online_signals] zero_result_rate: 0.08 (8%) — confidence: measured
[online_signals] thumbs_down_clustering: 0.02 (2%) — confidence: measured
[online_signals] slow_turn_rate: 0.05 (5%) — confidence: proxy
[online_signals] budget_exhaustion_rate: N/A — confidence: offline-only
[online_signals] clarification_rate: 0.03 (3%) — confidence: heuristic
[online_signals] Emitted 5 online_eval_signal events
```

**If it errors:** The script needs a real DB connection. Set `DATABASE_URL` in your `.env` to a DB with real `ChatMessage` and `ChatFeedback` data.

### Step 2: Check events reach local stdout (no App Insights needed in dev)

The telemetry events go to stdout in dev (no App Insights connection string needed):
```bash
python scripts/emit_online_signals_job.py 2>&1 | grep "online_eval_signal"
```

### Step 3: Test with real DB data

If your local DB is empty, seed it:
```bash
# Run a few test chat turns through the API first, then:
python scripts/emit_online_signals_job.py
```

---

## PROD Environment

### Step 1: Check if the job exists in Azure

```bash
az containerapp job list \
  --resource-group invoice-llm-prod \
  --query "[].{name:name, cronSchedule:properties.configuration.scheduleTriggerConfig.cronExpression}" \
  -o table
```

**Look for:** A job that runs `emit_online_signals_job.py` on a cron schedule (e.g., `0 */6 * * *` = every 6 hours).

**If it's missing:** The job infrastructure needs to be created (see Step 3 below).

### Step 2: If the job exists — verify it's actually running

```bash
# Check recent job executions:
az containerapp job execution list \
  --name <job-name> \
  --resource-group invoice-llm-prod \
  --query "[].{name:name, status:properties.status, startTime:properties.startTime}" \
  -o table
```

**Also check App Insights:**
```kql
customEvents
| where name == "online_eval_signal"
| where timestamp > ago(7d)
| summarize count() by signal_name=tostring(customDimensions.signal_name), bin(timestamp, 6h)
| order by timestamp desc
```

If this query returns 0 rows — the job is not running or not emitting to App Insights.

### Step 3: If the job is NOT scheduled — create it

The infra for a benchmark eval job already exists at `infra/benchmark-eval-job-only.bicep` as a template. Create a similar Bicep file for the online signals job:

```bicep
// infra/online-signals-job.bicep (to be created)
resource onlineSignalsJob 'Microsoft.App/jobs@2023-05-01' = {
  name: 'job-online-signals-${environment}'
  location: location
  properties: {
    configuration: {
      scheduleTriggerConfig: {
        cronExpression: '0 */6 * * *'  // every 6 hours
        parallelism: 1
        replicaCompletionCount: 1
      }
      triggerType: 'Schedule'
    }
    template: {
      containers: [
        {
          name: 'online-signals'
          image: '<acr>.azurecr.io/queue-worker:<tag>'
          command: ['python', 'scripts/emit_online_signals_job.py']
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
          ]
        }
      ]
    }
  }
}
```

### Step 4: Verify signals appear in workbook

Open the AI Control Tower workbook in Azure Portal and check the "Online Signals" panel. It should show 5 signal trend lines.

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| How to run | `python scripts/emit_online_signals_job.py` manually | Azure Container App Job on cron |
| App Insights | Logs to stdout only | Full App Insights integration |
| Data source | Local dev DB (may be empty) | Real production ChatMessage data |
| Cadence | Manual / ad-hoc | Every 6 hours automatically |
| Missing job | Just run the script | Must create Bicep + deploy |

---

## Files Involved

| File | Change |
|------|--------|
| `scripts/emit_online_signals_job.py` | No change — already built |
| `infra/online-signals-job.bicep` | **CREATE** this file if job is missing |
| `infra/08-apps.bicep` | **ADD** the job module reference if needed |

---

## Definition of Done

- [ ] Job runs manually in dev without errors
- [ ] `online_eval_signal` events appear in dev stdout
- [ ] Job confirmed running in prod (az containerapp job list)
- [ ] App Insights `customEvents` shows `online_eval_signal` events within last 6 hours
- [ ] Workbook "Online Signals" panel shows live data
- [ ] If job was missing: Bicep created, deployed, and verified
