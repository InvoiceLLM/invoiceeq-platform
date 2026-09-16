# GAP-A — Implementation & Testing Plan
## Enable Production Quality Judge

**Date:** 2026-08-25
**Prereq:** Fresh pull done (latest commit 2409a4b)
**Time estimate:** 4 hours total (2h dev testing + 2h monitoring before prod enable)

---

## What We Are Actually Testing

When you send a chat message, this is what happens now vs. after enabling:

```
RIGHT NOW (flag=false):
User types question
       |
query_agent runs → generates SQL → gets answer
       |
routers/chat.py line 471: submit_turn_judgement(...)
       |
online_quality_judge.py line 167:
    if not get_settings().ENABLE_PRODUCTION_QUALITY_JUDGE:
        return   <-- STOPS HERE. Nothing scored.
       |
User gets answer. Zero quality data written anywhere.

─────────────────────────────────────────

AFTER ENABLING (flag=true):
User types question
       |
query_agent runs → generates SQL → gets answer
       |
[line 462] db_session.commit()  <-- answer saved to DB first
       |
[line 471] submit_turn_judgement(...)  <-- submitted to background thread
       |
Background thread runs judge_turn():
    |─── score_soft_metrics_combined()
    |       → faithfulness: did it hallucinate?
    |       → relevance: did it answer what was asked?
    |       → tone: does it sound like SAGE?
    |       → helpfulness: was it useful?
    |       → completeness: did it cover the full question?
    |
    |─── score_persona()
    |       → did it use correct GST/tax domain terminology?
    |
    └─── _persist() writes to:
            → Postgres: agent_eval_run table (run_source=production)
            → App Insights: agent_eval_run custom event

User ALREADY has their answer. Background thread is invisible to them.
```

Key point: User sees no difference. No extra latency. Judge runs silently.

---

## Phase 1: Run Existing Tests First (Before Any Change)

These tests are already written. Run them first to confirm everything passes.

```bash
cd Prod_Invoice_LLM/apps/invoice-be
pytest tests/test_online_quality_judge.py -v
```

Expected: 20 tests, all pass. If any fail — stop and fix before proceeding.

Tests in this file:
1. test_a_production_row_stores_scores_and_a_message_id_but_no_customer_text
2. test_notes_carry_no_text_lifted_out_of_the_answer
3. test_accuracy_and_context_are_null_because_live_traffic_has_no_reference
4. test_the_check_constraint_still_forbids_a_row_with_neither_text_nor_pointer
5. test_pass_is_decided_on_faithfulness_and_relevance_only
6. test_an_unreachable_judge_writes_no_row_at_all
7. test_an_empty_answer_is_not_judged
8. test_a_turn_with_no_evidence_payload_is_not_judged
9. test_a_persistence_failure_is_swallowed
10. test_a_judge_that_returns_garbage_is_swallowed
11. test_the_telemetry_mirror_is_tagged_as_production
12. test_the_flag_is_off_by_default_and_nothing_is_submitted
13. test_the_flag_on_submits_to_the_existing_chat_background_pool
14. test_submitting_never_raises_even_if_the_pool_is_broken
15. test_the_appended_results_table_and_citations_are_not_graded
16. test_the_sql_route_returns_its_db_result_as_judge_evidence
17. test_the_rag_route_returns_chunk_text_as_judge_evidence
18. test_judge_evidence_is_attached_after_the_cache_write_not_before
19. test_a_cached_turn_carries_no_evidence_and_is_therefore_skipped
20. test_judge_evidence_is_not_written_to_the_chat_message

---

## Phase 2: What Each Test Actually Proves

### Test Group 1 — What Is Stored

test_a_production_row_stores_scores_and_a_message_id_but_no_customer_text
  Proves:
  - agent_eval_run row has run_source = 'production'
  - faithfulness_score, relevance_score, persona_score are actual numbers
  - question = None       (customer text NOT stored — privacy decision)
  - actual_answer = None  (same reason)
  - message_id points to the chatmessage row

test_accuracy_and_context_are_null_because_live_traffic_has_no_reference
  Proves:
  - accuracy_score = NULL on production rows (correct, needs reference answer)
  - context_score = NULL (correct, needs known-correct invoice set)
  - orchestration_score and persona_score ARE populated
  IMPORTANT: Do NOT compare production pass rate with golden bank pass rate.
             Production = faithfulness + relevance only.
             Golden bank = faithfulness + relevance + accuracy.

### Test Group 2 — Judge Outage Handling

test_an_unreachable_judge_writes_no_row_at_all
  Proves: If judge LLM fails → NO row written at all
  Watch in prod: if rows stop arriving → judge may be failing
                 (workbook shows "missing data", not "quality collapse")

test_a_turn_with_no_evidence_payload_is_not_judged
  Proves: Cache hit turns → NOT judged (evidence=None)
          SAGE path turns → NOT judged
          Error fallback turns → NOT judged

### Test Group 3 — Turn Is Never Affected

test_a_persistence_failure_is_swallowed
  Proves: DB going down during judging CANNOT affect user's answer.
          Judge is fire-and-forget. Error is swallowed.

test_the_flag_is_off_by_default_and_nothing_is_submitted
  Proves: With flag=false, pool.submit() is NEVER called.
          Zero extra code runs on request path when flag is off.

### Test Group 4 — Evidence Plumbing

test_the_sql_route_returns_its_db_result_as_judge_evidence
  Proves:
  - judge_evidence['context'] = actual DB result rows
  - judge_evidence['executed_queries'] = actual SQL that was run
  Why this matters:
    "No records found for Nonexistent Holdings" is only faithful
    if judge knows THAT QUERY WAS ACTUALLY RUN for Nonexistent Holdings.

test_judge_evidence_is_attached_after_the_cache_write_not_before
  Proves:
  - Redis cache does NOT contain judge_evidence
  - Only: content, generated_sql, citations, result_invoice_ids
  Why: Cache size stays small. Cache hits served without stale evidence.

---

## Phase 3: Enable the Flag in Dev

Step 3.1 — Change .env (file: apps/invoice-be/.env)

Add at the end:
    ENABLE_PRODUCTION_QUALITY_JUDGE=true

Step 3.2 — Verify config picks it up

```bash
python -c "from config import get_settings; print(get_settings().ENABLE_PRODUCTION_QUALITY_JUDGE)"
# Expected: True
```

---

## Phase 4: Manual Integration Tests

Step 4.1 — Start the backend

```bash
uvicorn main:app --reload --log-level debug
```

Step 4.2 — Baseline count before any message

```sql
SELECT COUNT(*), run_source
FROM agent_eval_run
GROUP BY run_source;
-- Note this count. After each test, production row count should increase.
```

Step 4.3 — Test Case 1: Normal SQL query

Send a normal invoice question through the chat UI, then wait 10 seconds and check:

```sql
SELECT
    agent_name, run_source, passed,
    faithfulness_score, relevance_score,
    accuracy_score,    -- MUST BE NULL
    context_score,     -- MUST BE NULL
    question,          -- MUST BE NULL (privacy)
    actual_answer,     -- MUST BE NULL (privacy)
    latency_ms, notes
FROM agent_eval_run
WHERE run_source = 'production'
ORDER BY created_at DESC LIMIT 1;
```

Pass criteria:
- run_source = 'production'
- question IS NULL
- actual_answer IS NULL
- accuracy_score IS NULL
- faithfulness_score between 0.0 and 1.0 (not NULL for a normal answer)
- relevance_score between 0.0 and 1.0
- passed = true (for a reasonable answer)
- notes contains: "run_source=production", "route=SQL"

Step 4.4 — Test Case 2: Out of scope question (refusal)

Send: "Write me Python code to reverse a list"

```sql
SELECT relevance_score, faithfulness_score, passed
FROM agent_eval_run
WHERE run_source = 'production'
ORDER BY created_at DESC LIMIT 1;
```

Pass criteria:
- relevance_score = 1.0 (refusal = out_of_scope_refusal kind → fixed at 1.0)
- passed = true (refusal IS the correct response)

Step 4.5 — Test Case 3: Nonexistent vendor (empty result)

Send: "What did we spend with ABCXYZ Holdings Ltd that does not exist?"

```sql
SELECT faithfulness_score, passed
FROM agent_eval_run
WHERE run_source = 'production'
ORDER BY created_at DESC LIMIT 1;
```

Pass criteria:
- faithfulness_score > 0.0 (NOT penalized for empty result)
- This was the failure mode 3 bug. If you see 0.0 here → bug still exists.

Step 4.6 — Test Case 4: Cache hit (judge should NOT run)

Send the EXACT SAME question as Test Case 1 again.

```sql
-- Count should NOT have increased:
SELECT COUNT(*)
FROM agent_eval_run
WHERE run_source = 'production';
-- Should be same as after Test Cases 1 + 2 + 3
```

---

## Phase 5: Cost Verification

In backend stdout, find judge call logs:

```bash
grep "eval.combined_soft\|eval.persona" <logs>
```

Expected entries per turn:
  {"agent_name": "eval.combined_soft", "tokens_in": ~850, "tokens_out": ~120}
  {"agent_name": "eval.persona",        "tokens_in": ~420, "tokens_out": ~80}

Cost estimate (gpt-5-mini):
  Per turn: ~1500 tokens total
  = roughly Rs 0.03 per turn at gpt-5-mini pricing
  100 turns/day = Rs 3/day → negligible

---

## Phase 6: Response Time Verification

Time a request with judge enabled vs normal:
  - Judge is background thread → response time should be unchanged
  - Pass: within +-200ms of normal response time

---

## Phase 7: Run Full Related Test Suite

```bash
pytest tests/test_online_quality_judge.py tests/test_rag.py tests/test_chat_queue.py -v
```

Key tests to watch:
- test_rag.py line 378: runs full chat path with flag=True
- test_chat_queue.py line 340: queue path (async) with judge enabled

---

## Phase 8: Score Interpretation Guide

| Score               | Healthy Range | Low Score → Investigate         |
|---------------------|---------------|---------------------------------|
| faithfulness_score  | > 0.80        | Model hallucinating? Wrong SQL? |
| relevance_score     | > 0.70        | Model going off-topic           |
| persona_score       | > 0.70        | Persona block needs updating    |
| orchestration_score | > 0.80        | SQL failing, tools not called   |
| helpfulness_score   | monitor trend | No action unless < 0.5 average  |
| completeness_score  | monitor trend | No action unless < 0.5 average  |
| tone_score          | monitor trend | No action unless < 0.5 average  |
| passed              | > 80% turns   | ALERT if drops below 65%        |

---

## Phase 9: 48-Hour Monitoring Query

Run this SQL every morning for 2 days:

```sql
SELECT
    DATE(created_at) as day,
    COUNT(*) as turns_judged,
    ROUND(AVG(faithfulness_score::numeric)::numeric, 3) as avg_faith,
    ROUND(AVG(relevance_score::numeric)::numeric, 3) as avg_rel,
    ROUND(AVG(persona_score::numeric)::numeric, 3) as avg_persona,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as pass_rate
FROM agent_eval_run
WHERE run_source = 'production'
  AND created_at > NOW() - INTERVAL '3 days'
GROUP BY DATE(created_at)
ORDER BY day DESC;
```

Check judge is not silently failing:

```sql
SELECT
    (SELECT COUNT(*) FROM chatmessage
     WHERE role='assistant' AND created_at > NOW() - INTERVAL '1 day') as total_turns,
    (SELECT COUNT(*) FROM agent_eval_run
     WHERE run_source='production' AND created_at > NOW() - INTERVAL '1 day') as judged_turns;

-- Healthy: judged_turns = roughly 70% of total_turns
--          (cache hits and SAGE turns are skipped intentionally)
-- Problem: judged_turns = 0 while total_turns > 0
```

---

## Phase 10: Prod Enable Checklist

Before enabling prod, confirm ALL of these:

[ ] All 20 unit tests pass
[ ] Test Case 1 (normal SQL) → row in DB with correct schema
[ ] Test Case 2 (refusal) → relevance = 1.0, passed = true
[ ] Test Case 3 (empty result) → faithfulness > 0.0
[ ] Test Case 4 (cache hit) → no extra row written
[ ] Cost confirmed (~Rs 0.03 per turn)
[ ] Response time unchanged
[ ] 48h monitoring: pass_rate > 0.80
[ ] No judge outage periods (judged_turns not 0)

### Prod Enable Command:

```bash
az containerapp update \
  --name ca-invoice-be-prod \
  --resource-group invoice-llm-prod \
  --set-env-vars ENABLE_PRODUCTION_QUALITY_JUDGE=true
```

### Verify in App Insights within 30 min:

```kql
customEvents
| where name == "agent_eval_run"
| where customDimensions.run_source == "production"
| where timestamp > ago(1h)
| summarize
    count(),
    pass_rate = avg(todouble(customDimensions.pass)),
    avg_faith = avg(todouble(customDimensions.faithfulness_score))
  by bin(timestamp, 15m)
| order by timestamp desc
```

### Permanent Bicep config (infra/modules/compute/invoice-be.bicep):

Add to env vars array:
    {
      name: 'ENABLE_PRODUCTION_QUALITY_JUDGE'
      value: 'true'
    }

### Azure Monitor Alert Rule (create in portal):

Query:
    customEvents
    | where name == "agent_eval_run"
    | where customDimensions.run_source == "production"
    | where timestamp > ago(6h)
    | summarize pass_rate = avg(todouble(customDimensions.pass))
    | where pass_rate < 0.70

Alert email: sbanerji@admsofttech.com
