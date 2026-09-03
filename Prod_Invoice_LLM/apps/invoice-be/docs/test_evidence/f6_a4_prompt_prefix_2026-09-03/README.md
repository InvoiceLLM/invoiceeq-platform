# Feature 6.1 item A4 — cacheable static prefix for the SQL system prompt

**Date:** 2026-09-03 · **Persona:** senior-dev (build), functional-tester (runs)

## What A4 claims

Azure OpenAI prompt caching serves the longest prefix that is byte-identical to an
earlier request, if it is ≥ 1,024 tokens, in 128-token steps. `build_sql_system_prompt`
interpolated the tenant id inline in **rule 1**, a few hundred tokens in, so the
identical prefix ended there for every tenant. A4 moves every per-tenant and
per-turn value below one marker line, so the prefix Azure can serve from cache is
most of the prompt.

## Deterministic half — measured, before and after

Encoding: `o200k_base` (what the gpt-5 family reports against). Two tenants, same
question; two questions, same tenant. Script: `scratchpad/a4_baseline.py`, run on a
throwaway SQLite session (dialect only affects rule 6d, identically for both).

| quantity | before | after |
|---|---|---|
| total prompt, one tenant, one question | 6,694 | 6,797 |
| **prefix shared across two tenants** | **1,809** (27%) — ends at rule 1's inline tenant id | **5,002** (74%) — ends at the marker |
| prefix shared across two questions, same tenant | 5,278 — ends at the per-question blocks between 6c and 7 | 6,786 |
| clears Azure's 1,024 minimum | yes | yes |

The +103 tokens on the total are the marker line and the restated rule-1 predicate
in the tail. Nothing was deleted; no rule's wording changed except rules 1 and 5,
which now name the tenant id instead of inlining it.

Pinned by `tests/test_a4_prompt_prefix.py` — **10 passed**:
prefix byte-identical across tenants, questions and turn state; ≥ 1,024 tokens;
≥ 2 × the pre-A4 figure; no tenant literal above the marker; every rule number
1–11 (incl. 4a/6a/6b/6c/6d/8a) present exactly once and in order, with 6d
deliberately in the tail (its executable example embeds the tenant literal and 12
tests run that example as-is through `_line_item_rule()`, which is untouched).

Regression across every suite that touches the SQL prompt — `test_chat_sql_quality`,
`test_rag`, `test_a1_generation_budget`, `test_a2_fast_deployment`,
`test_c2_cache_correctness`, `test_rag_chunk_provenance`, `test_chat_training`,
`test_agent_eval_multiturn`, `test_direction_aware_chat` — on real Postgres
(`localhost:5433`): **333 passed, 0 failed in 99.71s**.

## Measured half — golden set before/after against Azure `gpt-5-mini`

Runner: `scripts/run_agent_eval.py --paths default --provider azure --model gpt-5-mini`.

| run | file | status |
|---|---|---|
| before (pre-A4 prompt) | `before.json` / `before.log` | started 2026-09-03, on the pre-A4 code |
| after (A4 prompt) | `after.json` / `after.log` | to run once `before` completes |

**What the after-run must show, or A4 does not ship:** `summary.default.pass_rate`,
`faithfulness_mean` and `accuracy_mean` within noise of `before` — the prompt's
rules are unchanged, so the model's SQL should be unchanged. Any drop is a real
finding (most likely the model reading the tenant id less reliably from the tail;
the AST guard would surface that as retries, visible in `sql_attempts`).

**What this evidence cannot show:** that Azure actually serves the prefix from
cache. That is `cached_tokens` on the `chat.sql_generation` event rising on a
tenant's second turn — the B1 field, live on revision `--0000125` — and it needs
real traffic. Recorded here when it exists.

## Out of A4's scope, stated

`agents/sage_prompts.py` builds a separate aggregate/tool prompt for the `sage.*`
agents that also embeds `{line_item_rule}`. It is a different call site with its
own caching story and is not touched here.
