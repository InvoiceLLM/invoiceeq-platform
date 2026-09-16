# GAP-E: Wire LangSmith Tracing
**Priority:** P2-HIGH  
**Effort:** 30 minutes  
**Why deferred so long:** The `.env` already has the keys added — but `LANGCHAIN_API_KEY` is still a placeholder.

---

## Why This Matters

Azure App Insights tells you **what happened** (tokens, latency, cost, pass/fail score).  
LangSmith tells you **why it happened** — the exact prompt that went in, every chain step, every LLM call, the full token breakdown, intermediate outputs.

**Without LangSmith:**
- When a chat answer is wrong, you can see the score (faithfulness 0.2) but not which claim failed or what prompt caused it
- Debugging a bad SQL generation requires adding print statements and re-running locally
- You cannot A/B test two prompt versions and see the effect on actual model outputs

**With LangSmith:**
- Every LangChain/LangGraph invocation is auto-traced (zero code change — just env vars)
- You get a visual timeline of every node in the extraction_agent LangGraph
- You can see the full system prompt + user message + model response for any failed turn
- You can create "datasets" in LangSmith from real production traces and run evals against them
- Free tier: 5,000 traces/month — enough for dev + low-traffic prod

**The catch:** You need a real LangSmith API key. The placeholder `ls__your_langsmith_key_here` in `.env` does nothing.

---

## DEV Environment

### Step 1: Get a real LangSmith API key

1. Go to [smith.langchain.com](https://smith.langchain.com)
2. Sign up / sign in (free)
3. Go to Settings → API Keys → Create API Key
4. Copy the key (starts with `ls__`)

### Step 2: Update .env

**File:** `apps/invoice-be/.env`
```ini
# LangSmith Tracing & Evaluation Configuration
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=ls__your_REAL_key_here        # <-- replace this
LANGCHAIN_PROJECT=invoice-llm-dev               # dev project
```

**Note:** `.env` is gitignored — you put the real key here locally. Never commit the real key.

### Step 3: Restart the backend

```bash
# Just restart — LangSmith is auto-detected by LangChain at startup
uvicorn main:app --reload
```

### Step 4: Send a chat message and verify traces appear

1. Open [smith.langchain.com](https://smith.langchain.com)
2. Go to Projects → `invoice-llm-dev`
3. You should see a trace appear within seconds of the chat message

**What you'll see:**
```
Run: chat_message POST
  └── run_query_agent
        ├── classify_query (LLM call)
        │     input:  "show me top vendors by spend"
        │     output: {"route": "SQL"}
        ├── generate_sql (LLM call)  
        │     input:  [system prompt + schema + question]
        │     output: "SELECT vendor_name, SUM(total_amount) FROM invoice..."
        └── summarize_results (LLM call)
              input:  [SQL results]
              output: "Your top vendor is Acme Corp at $45,230..."
```

---

## PROD Environment

### What to do

**Step 1: Create a separate LangSmith project for production**

In LangSmith UI:
- Project name: `invoice-llm-prod`
- This keeps prod traces separate from dev traces

**Step 2: Store the API key as an Azure Container App secret**

```bash
# First store in Key Vault (do NOT put in params files):
az keyvault secret set \
  --vault-name kv-invoicellm-prod \
  --name LANGCHAIN-API-KEY \
  --value "ls__your_prod_key"

# Then reference it in the Container App:
az containerapp secret set \
  --name ca-invoice-be-prod \
  --resource-group invoice-llm-prod \
  --secrets langchain-api-key=keyvaultref:...

# Then set as env var:
az containerapp update \
  --name ca-invoice-be-prod \
  --resource-group invoice-llm-prod \
  --set-env-vars \
    LANGCHAIN_TRACING_V2=true \
    LANGCHAIN_ENDPOINT=https://api.smith.langchain.com \
    LANGCHAIN_PROJECT=invoice-llm-prod \
    LANGCHAIN_API_KEY=secretref:langchain-api-key
```

**Step 3: Update Bicep for persistent config**

**File:** `infra/modules/compute/invoice-be.bicep`

Add to the environment variables block:
```bicep
{
  name: 'LANGCHAIN_TRACING_V2'
  value: 'true'
}
{
  name: 'LANGCHAIN_ENDPOINT'
  value: 'https://api.smith.langchain.com'
}
{
  name: 'LANGCHAIN_PROJECT'
  value: 'invoice-llm-${environment}'  // auto: invoice-llm-dev / invoice-llm-prod
}
{
  name: 'LANGCHAIN_API_KEY'
  secretRef: 'langchain-api-key'
}
```

And in the `05-secrets.bicep`, document the new required secret.

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Key storage | `.env` file (gitignored) | Azure Key Vault secret |
| LangSmith project | `invoice-llm-dev` | `invoice-llm-prod` |
| Trace visibility | Developer only | Founder + DevOps |
| Trace volume | Low (test calls) | Real user traffic |
| Free tier limit | 5,000 traces/month | May need paid plan |
| Bicep change | Not needed | Add to invoice-be.bicep + 05-secrets.bicep |

### Prod Cost Estimate

LangSmith pricing (2026):
- Free: 5,000 traces/month
- Developer: $39/month → 50,000 traces
- Team: $99/month → unlimited

For low-traffic prod (< 5,000 turns/month) → free tier sufficient.
For medium traffic → Developer plan ($39/month) is fine.

---

## Files Involved

| File | Change |
|------|--------|
| `apps/invoice-be/.env` | Replace placeholder API key with real key |
| `apps/invoice-be/.env.example` | Document the 4 LangSmith vars (keys are already listed) |
| `infra/modules/compute/invoice-be.bicep` | Add 4 LangSmith env vars |
| `infra/05-secrets.bicep` | Document `langchain-api-key` as required secret |

**Zero application code changes needed.** LangChain auto-detects the env vars.

---

## Definition of Done

- [ ] Real LangSmith API key obtained (not placeholder)
- [ ] Dev `.env` updated with real key
- [ ] Dev: traces appear in LangSmith UI after a chat message
- [ ] `.env.example` documents all 4 LangSmith vars
- [ ] Prod: API key stored in Key Vault
- [ ] Prod: Container App env vars set
- [ ] Prod: Bicep updated to include vars persistently
- [ ] Prod: traces appear in `invoice-llm-prod` LangSmith project
