# BE Gaps 237 / 241 / 242 -- post-fix live verification + the jsonb-cast fix (senior-dev, 2026-08-18)

Closing pass for the chat-SQL-quality work tracked in
`.claude/tasklists/senior-dev-chat-sql-quality.md`. Two things are measured here:

1. **The jsonb-cast defect found on 2026-08-18** (tasklist step 6d) -- chat
   queries filtering on `tags`/`items`/`sa_alerts` aborted on Postgres with
   `psycopg2.errors.UndefinedFunction: function lower(jsonb) does not exist`.
2. **The step-8 statistical re-run** of `tests/gap237_sql_repro.py` against the
   fully-fixed prompt, same harness and same run count as the 2026-08-17
   baseline.

Everything below was produced by two private uvicorn instances started for this
pass only (fixed prompt on 127.0.0.1:**8100**, deliberately-reverted prompt on
127.0.0.1:**8200**), against the real local Postgres/Redis/Chroma stack. Port
8000 was left free throughout. Both instances were stopped afterwards and
`agents/query_agent.py` was byte-for-byte restored to its fixed state
(md5 verified) before this README was written.

## 1. The jsonb-cast defect

### What was wrong

`agents/query_agent.py`'s SQL system prompt told the model, as its own worked
example:

```
- To check if a specific named tag (e.g. 'hardware') is in tags: LOWER(tags) LIKE LOWER('%"hardware"%') (works in both SQLite and Postgres)
```

The parenthetical is false. `tags`, `items` and `sa_alerts` are declared
`sa_column=Column(JSON_VARIANT)` (models.py lines 82-84), and `JSON_VARIANT` is
`sa.JSON().with_variant(JSONB, "postgresql")` (models.py line 10) -- i.e. **JSONB
on Postgres**, confirmed against the live dev DB:

| Predicate | Postgres (dev, `invoice_db`) | SQLite (in-memory) |
|---|---|---|
| `LOWER(tags) LIKE LOWER('%cloud%')` | **FAIL** -- `function lower(jsonb) does not exist` | OK (untyped storage) |
| `LOWER(tags::text) LIKE LOWER('%cloud%')` | OK | **FAIL** -- `unrecognized token: ":"` |
| `LOWER(CAST(tags AS TEXT)) LIKE LOWER('%cloud%')` | OK | OK |
| `LOWER(CAST(items AS TEXT)) LIKE ...` | OK | OK |
| `LOWER(CAST(sa_alerts AS TEXT)) LIKE ...` | OK | OK |

That table is the reason the fix uses `CAST(... AS TEXT)` and not the `::text`
form the model often reached for on its own: `::text` fixes Postgres and breaks
SQLite, which is what the entire unit suite runs on. SQLite being untyped is
also why this shipped -- the bad form passed every mocked test.

### The fix

`agents/query_agent.py`, SQL `system_prompt`:

- rule **6** rewritten as 6(a) cast rule + 6(b) LOWER rule, with all three JSONB
  examples (`tags`, `items`, `sa_alerts`) now cast, the error string named
  verbatim so the model has the reason, and an explicit "VARCHAR columns must
  NOT be cast" clause;
- rule **6b**'s four-column OR group now shows
  `LOWER(CAST(tags AS TEXT))` / `LOWER(CAST(items AS TEXT))` alongside the
  uncast `LOWER(vendor_name)` / `LOWER(customer_name)`.

No other file changed for this defect. A repo-wide grep found no other
`LOWER(tags|items|sa_alerts)` occurrence in application code.

### Live before/after

`tests/gap6d_jsonb_cast_probe.py`, fresh session per attempt, answer cache
flushed per attempt, two question sets:

- `category` -- the shapes from the reported failing run ("cloud", "office
  supplies", "furniture", a line-item keyword, an sa_alerts search), 5 questions x 2
- `tag_literal` -- named-tag phrasings that map straight onto rule 6's own
  worked example ("invoices with the tag 'hosting'"), 3 questions x 2

**The API's `generated_sql` is the query that finally succeeded**, and the SQL
route retries up to 3 times feeding the DB error back to the model. So the
chat-visible result hides this defect almost entirely -- the retry loop repairs
it. The server log is the ground truth:

| Instance | Prompt | Chat messages served | SQL executions that aborted | `function lower(jsonb) does not exist` |
|---|---|---|---|---|
| :8200 | pre-fix (rule 6/6b reverted for this measurement) | 16 | **13** | **13** |
| :8100 | fixed | 32 | **0** | **0** |

All 13 pre-fix aborts were on attempt 1 (`grep -c "failed on attempt 2"` = 0),
each one repaired on attempt 2 by the error-feedback loop -- so the user-visible
answers looked fine, at the cost of one wasted LLM round-trip, one failed
statement and a session rollback on roughly **every** JSON-column question. A
representative log line (`backend_log_before_port8200.txt`):

```
SQL execution failed on attempt 1: (psycopg2.errors.UndefinedFunction) function lower(jsonb) does not exist
LINE 17:   AND LOWER(tags) LIKE LOWER('%"cloud"%');
```

That literal is the prompt's own example, copied through.

Post-fix, every generated query used the cast form on the first attempt
(`jsonb_cast_probe_after.json`, `jsonb_cast_probe_tagliteral_after.json`), 0
retries, 0 aborts across 32 messages.

Honest caveats, since the numbers could be over-read:

- The probe's own `uncast_lower` counter reads **0/16 pre-fix as well** -- for
  the reason above (it sees post-repair SQL). Don't quote that counter as
  evidence either way; quote the log.
- "office supplies" and "furniture" return **0 rows on this tenant**, correctly:
  rule 6c keeps the phrase whole, and no seeded row contains the literal string
  "office supplies" (the control invoice is vendor "Office Depot Supplies" with
  tags `["office","supplies"]`). The probe measures whether the query *runs*,
  not recall.
- 3 of 10 `category` attempts post-fix produced no SQL at all (2x the toner
  line-item question routed to RAG, 1x an office-supplies attempt answered from
  the tenant-stats snapshot). That is routing/null-sql behaviour on a *first*
  turn, outside Gap 237's follow-up retry path, and is unchanged by this fix --
  noted, not claimed as fixed.

## 2. Step 8 -- Gap 237 repro re-run, fixed prompt vs. baseline

Harness `tests/gap237_sql_repro.py`, unchanged, run 8 times against :8100
(`GAP237_BASE_URL` / `GAP237_EVIDENCE_DIR` overrides). Same tenant
(`gap237-chat-sql-repro-test.invalid`, reseeded per run), same two turns:

1. "What are the total invoices related to cloud?"
2. "Can you explain the 3 USD ones in detail?"

Scored mechanically by `score_runs.py` in this directory (turn 2 counts as
`correct` only if its reply names all three seeded USD invoices -- CNH-1001
vendor-only, ACM-2002 tags-only, ZEN-3003 items-only):

| Run set | n | correct | no_sql | branch_drop | sql_error | hedge fired |
|---|---|---|---|---|---|---|
| **Before** (2026-08-17 baseline, `../gap237_step2_fix_2026-08-17/raw_turns_before_*.json`) | 8 | **3/8** | **5/8** | 0/8 | 0/8 | 0/8 |
| Mid-pass (2026-08-17, after steps 3-6, `../gap237_step2_fix_2026-08-17/raw_turns_fixed_*.json`) | 8 | 8/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| **After** (2026-08-18, incl. the jsonb cast, `raw_turns_after_*.json` here) | 8 | **8/8** | **0/8** | 0/8 | 0/8 | 0/8 |

Reading of that: the dominant baseline failure -- the follow-up returning no
SQL at all and answering from the previous turn's prose (5/8) -- is gone, and
the branch-drop the gap was opened over did not recur. The 2026-08-18 re-run
reproduces the 2026-08-17 mid-pass result with the cast change on top, i.e. the
cast change did not regress follow-up behaviour.

The step-3 hedge fired 0/8, correctly: it is a safety net for a turn-2 answer
that surfaces fewer invoices than the user referenced, and all 8 runs surfaced
all 3. Its trigger-condition fix is covered by unit tests
(`tests/test_chat_sql_quality.py`), not by this run set -- no live run in this
pass produced the shape it exists to catch.

## Files in this directory

- `raw_turns_after_0.json` .. `raw_turns_after_7.json` -- step-8 repro runs, full request/response per turn plus DB-level `result_invoice_ids`
- `jsonb_cast_probe_before.json` / `jsonb_cast_probe_after.json` -- `category` question set, pre-fix (:8200) and fixed (:8100)
- `jsonb_cast_probe_tagliteral_before.json` / `jsonb_cast_probe_tagliteral_after.json` -- `tag_literal` question set, same two instances
- `backend_log_before_port8200.txt` / `backend_log_after_port8100.txt` -- full uvicorn logs; the 13-vs-0 abort counts above come from these
- `score_runs.py` -- the scorer behind the before/after table, so the numbers can be recomputed rather than trusted

## Reproducing

```
# fixed backend on a private port
python -m uvicorn main:app --host 127.0.0.1 --port 8100

GAP237_BASE_URL=http://127.0.0.1:8100/api/v1 \
GAP237_EVIDENCE_DIR=<this dir> \
  python tests/gap237_sql_repro.py after_0          # x8

GAP6D_BASE_URL=http://127.0.0.1:8100/api/v1 GAP6D_SET=category \
  python tests/gap6d_jsonb_cast_probe.py after 2

python docs/test_evidence/gap237_jsonb_cast_2026-08-18/score_runs.py <this dir>
```
