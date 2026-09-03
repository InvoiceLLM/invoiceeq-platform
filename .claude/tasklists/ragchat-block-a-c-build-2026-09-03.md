# RAG chat — A4, C3, A3, C4 build

**Founder instruction 2026-09-03 (~16:55 IST):** complete rows 7, 10, 8, 11 in that
order — full development, testing, and push to `master`. No hard stop given. Guard
hook removed by the founder earlier today; pushes are authorised.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

## Standing constraints (from the founder's Feature 6.1 brief)

- Hard rule 3: no model decides a figure.
- Hard rule 2: "verified" means a recorded Postgres run (local compose, port 5433).
- Tenant isolation never weakens. The AST guard (Gap 414/417) stays the backstop.
- The Feature 26 pre-route attachment gate is untouched.
- Every existing chat test keeps passing; the regression set is derived by grepping
  the changed function names, not chosen.
- Golden-set before/after in `docs/test_evidence/` for every item that touches an
  LLM call — A4 and C4 do; C3 partly; A3 does not change what the model is asked.
- Every defect found gets a tracker gap in the same change, collision-checked
  against `origin/master` at commit time (the Gap 419 lesson).

## Tasks

| # | item | status |
|---|---|---|
| 7 | **A4** — reorder `build_sql_system_prompt` so a ≥1,024-token static prefix precedes every per-tenant / per-turn block | `[~]` code + tests green (10 + 333 passed); shared prefix 1,809 → 5,002 tokens; golden before/after pending |
| 10 | **C3** — zero rows → deterministic diagnosis → vector probe → "Did you mean X?" proposal (BE + FE) | `[x]` Gap 424; 19 + 17 e2e; 572-test regression, 5 old-contract tests updated |
| 8 | **A3** — stream the summary and F26 narration (BE SSE + FE) | `[~]` patch + tests written; applying after C3 is pushed |
| 11 | **C4** — rules → structure; write SQL for the golden cases; golden before/after | `[ ]` |

## A4 — design, written before code

**Why the prefix is not cacheable today.** Azure prompt caching needs a ≥1,024-token
byte-identical prefix. `build_sql_system_prompt` puts `tenant_id = '{tenant_id}'`
inline in **rule 1** — a few hundred tokens in — so the identical prefix ends there
for every tenant. Rule 5's example repeats it. The three per-question blocks
(`tax_term`, `payment_status`, `attribute_term`) sit between rule 6c and rule 7,
splitting the static rules in half.

**What moves.** Everything the request cannot change comes first, everything it can
comes last:

1. `CHAT_PERSONA_BLOCK`, the SQL-step preamble, `_HAND_TYPED_SCHEMA_BLOCK`,
   `_derived_schema_supplement()` (ORM-derived, stable per process)
2. Rules 1–11 **with no interpolated values** — rule 1 and rule 5 refer to the
   tenant id by name ("the TENANT_ID given in the TENANT section below") instead
   of inlining it
3. `_line_item_rule()` — per-dialect, stable per deployment
4. `_INJECTION_GUARD_INSTRUCTION`
5. — end of static prefix —
6. **TENANT section**: the literal tenant id, `tenant_stats`, `rules_block`,
   `chat_rules_block`
7. **QUESTION section**: `tax_term_block`, `payment_status_block`,
   `attribute_term_block` — each empty unless the question triggers it
8. `prior_sql_block`, conversation history

**What must not change.** Rule text is byte-identical apart from the two tenant
references. Nothing is deleted (that is C4's job). `_computed_figures_block_for` and
`_full_record_block_for` are untouched. The AST guard still rejects any query
missing the tenant predicate, so if the model reads the tenant id less reliably
from the tail, the failure is a loud retry, never a leaked row.

**Proof, two halves.**
- *Deterministic, now:* a test renders the prompt for two different tenants and two
  different questions and asserts the text before the `TENANT` marker is
  byte-identical and ≥ 1,024 `tiktoken` tokens (o200k_base — the encoding the
  gpt-5 family reports against).
- *Measured, after turns exist:* `cached_tokens` on `llm_agent_call` for
  `chat.sql_generation` rises from 0 to ≥ the prefix size on the second turn of any
  tenant. Rows 3/4 gate this half; recorded in `docs/test_evidence/` when it lands.

## A4 — measured baseline (before the change, o200k_base)

| quantity | value |
|---|---|
| total prompt | 6,694 tokens |
| prefix shared across two tenants, same question | **1,809 tokens** — ends at rule 1's inline tenant id |
| prefix shared across two questions, same tenant | 5,278 tokens — ends at the per-question blocks between 6c and 7 |
| Azure minimum for a cache hit | 1,024 tokens |

So the cache already *could* fire across tenants today, but for 27% of the prompt.
Golden "before" run started against Azure `gpt-5-mini` on the pre-A4 prompt:
`docs/test_evidence/f6_a4_prompt_prefix_2026-09-03/before.json`.

## Azure changes in this build

None yet.

**Status: in progress.** Created 2026-09-03.
