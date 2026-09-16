# GAP-B: Persist stop_reason on ChatMessage
**Priority:** P1-CRITICAL  
**Affected file:** `models.py`, `agents/sage_orchestrator.py`, `routers/chat.py`, `queue_worker/handlers.py`

---

## Why This Matters

`agents/sage_orchestrator.py` computes these outcomes on every agentic turn:
- `tool_call_budget_exhausted` — agent hit its tool-call limit without finishing
- `clarification_requested` — agent decided to ask the user a follow-up instead of answering
- `planner_step_budget_exhausted` — planner loop hit its step limit

**These outcomes are never saved anywhere for live turns.** They only exist as:
1. In-memory return value from `run_agentic_sage()`
2. Free-text notes in `AgentEvalRun` — but only for *offline* eval runs, not production

**What this means for observability:**
- `budget_exhaustion_rate` online signal reads from **eval runs only** — it measures your test harness, not your real users
- You cannot ask "how often do real users hit the tool budget?" — that data does not exist
- You cannot detect if a prompt change is causing more clarification requests in production
- `services/online_eval_signals.py` lines 39–51 documents this gap explicitly

---

## DEV Environment

### Step 1: Add column to ChatMessage model

**File:** `apps/invoice-be/models.py`

Find the `ChatMessage` class and add:
```python
# In class ChatMessage(SQLModel, table=True):
stop_reason: Optional[str] = Field(
    default=None,
    description=(
        "Terminal stop reason from the agentic turn. "
        "One of: 'success', 'tool_call_budget_exhausted', "
        "'clarification_requested', 'planner_step_budget_exhausted'. "
        "NULL for non-agentic (classic query_agent) turns."
    )
)
```

### Step 2: Generate Alembic migration

```bash
cd Prod_Invoice_LLM/apps/invoice-be
alembic revision --autogenerate -m "add stop_reason to chat_message"
# Review the generated file in alembic/versions/
alembic upgrade head
```

### Step 3: Write stop_reason in routers/chat.py

Find where the assistant `ChatMessage` is created after `run_agentic_sage()` or `run_query_agent()`. Add:

```python
# After agent call completes:
result_metadata = agent_result.get("metadata", {})
stop_reason = result_metadata.get("stop_reason", "success")

assistant_message = ChatMessage(
    session_id=session.id,
    role="assistant",
    content=agent_response,
    # ... existing fields ...
    stop_reason=stop_reason,   # ADD THIS
)
```

### Step 4: Write stop_reason in queue_worker/handlers.py

Same pattern — find where the assistant message is written in `handle_process_chat_job()`:
```python
stop_reason = result.get("metadata", {}).get("stop_reason", "success")
message.stop_reason = stop_reason
db.add(message)
db.commit()
```

### Step 5: Include in chat_turn telemetry event

**File:** `telemetry.py` — find `track_chat_turn()` and add `stop_reason` as a field on the event:
```python
def track_chat_turn(..., stop_reason: str = "success", ...):
    attributes = {
        ...
        "stop_reason": stop_reason,
    }
```

### Step 6: Update online_eval_signals.py

Once `ChatMessage.stop_reason` exists, the `budget_exhaustion_rate` signal can read from live turns instead of only eval notes. Update the signal to:
```python
# services/online_eval_signals.py
# Replace the eval-notes-only approach with a direct DB query:
budget_turns = session.exec(
    select(ChatMessage)
    .where(ChatMessage.stop_reason == "tool_call_budget_exhausted")
    .where(ChatMessage.created_at >= window_start)
).all()
```

### Verify in Dev

```sql
-- After sending a few chat messages:
SELECT id, content, stop_reason, created_at
FROM chatmessage
WHERE role = 'assistant'
ORDER BY created_at DESC
LIMIT 10;

-- Expected: stop_reason = 'success' for normal turns
-- Send a complex multi-hop question to trigger budget exhaustion
```

---

## PROD Environment

### What to do

**Step 1: Deploy the migration with the release**
- The Alembic migration runs automatically on container startup via `entrypoint.sh`
- Verify prod DB migration ran:
```bash
az containerapp logs show \
  --name ca-invoice-be-prod \
  --resource-group invoice-llm-prod \
  --follow \
  | grep "alembic"
```

**Step 2: Verify stop_reason appears in App Insights**
```kql
// After deploying, chat_turn events should carry stop_reason
customEvents
| where name == "chat_turn"
| where customDimensions.run_source == "production"
| summarize count() by tostring(customDimensions.stop_reason), bin(timestamp, 1h)
| order by timestamp desc
```

**Step 3: Enable the online signal to use live data**
After confirming the column is populated, update `emit_online_signals_job.py` scheduling.

### DEV vs PROD Difference

| Aspect | DEV | PROD |
|--------|-----|------|
| Migration | `alembic upgrade head` locally | Runs in `entrypoint.sh` on startup |
| Data | Test chat messages | Real user turns |
| Rollback | Drop column via migration | Must create rollback migration |
| Risk | Zero — new nullable column | Zero — new nullable column, no existing data affected |

---

## Files Involved

| File | Change |
|------|--------|
| `models.py` | Add `stop_reason: Optional[str]` to `ChatMessage` |
| `alembic/versions/<new>.py` | Generated migration — **review before committing** |
| `routers/chat.py` | Write `stop_reason` on assistant message creation |
| `queue_worker/handlers.py` | Write `stop_reason` in `handle_process_chat_job()` |
| `telemetry.py` | Add `stop_reason` to `track_chat_turn()` |
| `services/online_eval_signals.py` | Update `budget_exhaustion_rate` to read live column |

---

## Definition of Done

- [ ] `ChatMessage.stop_reason` column in models.py
- [ ] Alembic migration reviewed and applied (dev)
- [ ] `stop_reason` written in `routers/chat.py` for sync path
- [ ] `stop_reason` written in `queue_worker/handlers.py` for async path
- [ ] `stop_reason` included in `chat_turn` telemetry event
- [ ] `budget_exhaustion_rate` signal reads live turns (not just eval notes)
- [ ] Migration applied to prod via deploy
- [ ] KQL query confirms live `stop_reason` values in App Insights
