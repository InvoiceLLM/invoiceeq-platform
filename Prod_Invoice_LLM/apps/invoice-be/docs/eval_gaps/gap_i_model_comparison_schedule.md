# GAP-I: Schedule Recurring Model Comparison Runs
**Priority:** P4-LOW  
**Infra already exists:** `infra/ollama-eval-only.bicep`, `infra/gpt4o-deployment.bicep`  
**Prerequisite:** GAP-F (golden bank expansion) should be done first

---

## Why This Matters

The eval infrastructure supports running the golden bank against **multiple models simultaneously**:
- `gpt-5-mini` (current production model)
- `gpt-4o` (higher quality, higher cost)
- `ollama/llama3.2` (self-hosted, zero API cost)

Tests already exist:
- `tests/agent_eval_output_3way_gpt5_mini.json`
- `tests/agent_eval_output_ollama_llama3_2_latest.json`
- `tests/agentic_sage_live_output.json`

**Why model comparison matters:**
- Azure updates `gpt-5-mini` silently. A score drop week-over-week may be a model update, not your code.
- Before promoting SAGE agentic path to more tenants, you need to know if `gpt-4o` gives meaningfully better answers
- Ollama (self-hosted) is free — if it's within 5% quality of `gpt-5-mini`, you save 100% of LLM API cost for dev/test

**Why it's P4 (not higher):**
- It's a "nice to know" — not a blocker for ship quality
- Requires GAP-F golden bank first — a 5-case bank isn't meaningful enough for model comparison
- The infra exists but isn't wired to a schedule yet

---

## DEV Environment

### Step 1: Run comparison manually first

```bash
cd Prod_Invoice_LLM/apps/invoice-be

# Run against gpt-5-mini (default):
python scripts/run_agent_eval.py --no-persist --output tests/eval_gpt5mini.json

# Run against gpt-4o (if deployed in dev):
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o \
python scripts/run_agent_eval.py --no-persist --output tests/eval_gpt4o.json

# Compare results:
python -c "
import json
a = json.load(open('tests/eval_gpt5mini.json'))
b = json.load(open('tests/eval_gpt4o.json'))
# Compare pass rates, average faithfulness, average relevance
"
```

### Step 2: Run against Ollama (local, needs Ollama running)

```bash
# Start Ollama locally:
ollama run llama3.2

# Run eval against it:
LLM_PROVIDER=ollama \
python scripts/run_agent_eval.py --no-persist --output tests/eval_ollama.json
```

### Step 3: Build a simple comparison script

```python
# scripts/compare_model_eval.py (new file)
"""Compare agent eval results across two model runs."""
import json, sys, argparse

def load(path):
    return json.load(open(path))

def summary(results):
    pass_count = sum(1 for r in results if r.get("passed"))
    faithfulness = [r["faithfulness_score"] for r in results if r.get("faithfulness_score")]
    relevance = [r["relevance_score"] for r in results if r.get("relevance_score")]
    return {
        "total": len(results),
        "pass_rate": pass_count / len(results) if results else 0,
        "avg_faithfulness": sum(faithfulness)/len(faithfulness) if faithfulness else None,
        "avg_relevance": sum(relevance)/len(relevance) if relevance else None,
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file_a", help="Baseline eval output JSON")
    parser.add_argument("file_b", help="Comparison eval output JSON")
    args = parser.parse_args()
    
    a = load(args.file_a)
    b = load(args.file_b)
    print("Baseline:", json.dumps(summary(a), indent=2))
    print("Comparison:", json.dumps(summary(b), indent=2))
```

---

## PROD Environment

### When to set up scheduled model comparison

**Trigger condition:** After GAP-F is done (20+ golden bank cases) AND after baseline quality is stable for 1 week.

### Step 1: The Bicep infra already exists — review it

```bash
cat infra/ollama-eval-only.bicep
cat infra/gpt4o-deployment.bicep
```

These deploy the Ollama and GPT-4o resources needed for comparison. Confirm they're deployed:
```bash
az resource list \
  --resource-group invoice-llm-prod \
  --query "[?contains(name,'gpt4o') || contains(name,'ollama')]" \
  -o table
```

### Step 2: Create a scheduled comparison job

The pattern follows `benchmark-eval-job-only.bicep`. Create:
```bicep
// infra/model-comparison-job.bicep
// Runs every Sunday at 2 AM — after the nightly golden bank run
// Runs run_agent_eval.py against both gpt-5-mini and gpt-4o
// Emits agent_eval_summary events tagged by model name
// Outputs comparison to blob storage
```

### Step 3: Track comparison results in workbook

Add a "Model Comparison" panel to `ai_control_tower_workbook.json`:
```kql
customEvents
| where name == "agent_eval_summary"
| where timestamp > ago(30d)
| project timestamp,
    model = tostring(customDimensions.model),
    pass_rate = todouble(customDimensions.pass_rate),
    avg_faithfulness = todouble(customDimensions.avg_faithfulness)
| render timechart
```

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Running comparison | Manual scripts | Scheduled ACA Job (weekly) |
| Models available | gpt-5-mini only (unless Ollama running) | gpt-5-mini + gpt-4o + Ollama |
| Cost | Free (--no-persist, local) | ~$2-5 per weekly comparison run |
| Results | Local JSON files | App Insights events + blob artifacts |
| Decision point | Not needed until GAP-F done | After GAP-F + 1 stable week |

---

## Files Involved (all to be CREATED)

| File | Status |
|------|--------|
| `scripts/compare_model_eval.py` | Create (simple comparison util) |
| `infra/model-comparison-job.bicep` | Create (scheduled job Bicep) |
| `infra/monitoring/ai_control_tower_workbook.json` | Update (add model comparison panel) |

---

## Definition of Done (not urgent — do after GAP-F)

- [ ] Manual comparison run completed: gpt-5-mini vs gpt-4o (if GPT-4o deployed in dev)
- [ ] `compare_model_eval.py` script created
- [ ] Results documented: quality delta, cost delta
- [ ] Decision: stick with gpt-5-mini or promote gpt-4o for SAGE?
- [ ] Scheduled weekly comparison job in prod (after GAP-F complete)
- [ ] Workbook model comparison panel shows weekly trend
