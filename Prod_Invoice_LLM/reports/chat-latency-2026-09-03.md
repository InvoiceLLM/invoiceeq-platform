# Chat latency measurement — 2026-09-03

Read-only. No code or config changed. Numbers only; decisions are the founder's.

**Data window.** `chat_turn` events in `appi-invoicellm-dev` exist for **one session
only: 9 turns, 2026-09-03 05:01–05:07 UTC** (the founder's own test after the flag
flip). 7d / 14d / 30d / 90d windows all return the same 9. Every percentile below is
over ≤ 9 turns — they are bounds, not distributions. No `attachment`-route or
`CHAT`-route turn exists in the window.

All nine turns ran on revision `ca-invoice-be-dev--0000117` (created 04:22 UTC,
39 min before the first turn). The current revision is `--0000120` (05:49 UTC).

---

## 1. Telemetry

### 1a. Per route (n = 9)

| route | n | p50 latency | p95 latency | p50 LLM calls | p95 LLM calls | p50 per call | p95 per call |
|---|---|---|---|---|---|---|---|
| SQL | 4 | 27,834 ms | 89,209 ms | 3 | 3 | 9,278 ms | 29,736 ms |
| cached | 4 | 1,290 ms | 1,812 ms | 0 | 0 | — | — |
| RAG | 1 | 16,048 ms | — | 2 | — | 8,024 ms | — |
| CHAT | 0 | — | — | — | — | — | — |
| attachment | 0 | — | — | — | — | — | — |

"per call" = `latency_ms ÷ llm_call_count`, i.e. it includes the non-LLM time of the
turn spread across the calls.

### 1b. SQL turns split

| bucket | status | n | p50 latency | p95 latency | LLM calls | tokens in | tokens out |
|---|---|---|---|---|---|---|---|
| `sql_attempts = 1` | success | 3 | 27,834 ms | 32,286 ms | 3 | 10,341 / 10,558 / 11,995 | 2,190 / 2,189 / 3,040 |
| `sql_attempts = 3` (repair fired twice) | declined | 1 | 89,209 ms | 89,209 ms | 3 | 28,149 | 10,354 |
| cache hit | cache_hit | 4 | 1,290 ms | 1,812 ms | 0 | 0 | 0 |

Every SQL miss made exactly 3 LLM calls (classify → generate → summary, or
generate ×3 on the declined turn). The four cache hits each immediately followed
a miss for the same question (05:02:45 after 05:02:41, etc.).

### 1c. Per call site — `llm_agent_call` events (n = 15 chat calls + 10 eval-judge calls)

| agent_name | n | p50 | p95 | p50 tokens in | p50 tokens out |
|---|---|---|---|---|---|
| `chat.sql_generation` | 6 | **15,570 ms** | 35,348 ms | **8,498** | **1,688** |
| `chat.classify` | 4 | 3,092 ms | 4,395 ms | 268 | 243 |
| `chat.sql_summary` | 3 | 3,620 ms | 12,835 ms | 1,947 | 258 |
| `chat.rag_answer` | 1 | 7,691 ms | 7,691 ms | 2,809 | 824 |
| `chat.conversational` | 0 | — | — | — | — |
| `chat.attachment_compare` | 0 | — | — | — | — |
| `eval.combined_soft` (judge, off-path) | 5 | 25,407 ms | 31,382 ms | 2,460 | 2,720 |
| `eval.persona` (judge, off-path) | 5 | 7,535 ms | 10,994 ms | 825 | 808 |

Reconciliation against 1a: classify 3.1 s + generation 15.6 s + summary 3.6 s ≈ 22.3 s
of a 27.8 s median SQL turn → **≈ 5.5 s per turn is non-LLM** (history, stats,
Postgres, full-record fetch, telemetry). Not instrumented further — see §3.

Output tokens: `chat.sql_generation` emits **1,688 tokens (p50) to produce a
~100-token SELECT**; `chat.classify` emits 243 to produce `{route, reasoning}`. These
counts are consistent with a reasoning model's hidden reasoning tokens being
billed as output. The declined turn consumed 28,149 in / 10,354 out across three
attempts.

### 1d. HTTP layer (`requests` table)

| request | n | p50 | p95 |
|---|---|---|---|
| `POST /api/v1/chat/sessions/{id}/message` | 5 | 789 ms | 16,495 ms |
| `GET /api/v1/chat/jobs/{id}/stream` (SSE) | 4 | 28,824 ms | 60,540 ms |
| `GET /api/v1/chat/jobs/{id}/status` | 1 | 579 ms | — |

The POST returns 202 in ~0.8 s (async path, `ENABLE_ASYNC_CHAT_QUEUE=true` since
today); the user-perceived turn time is the SSE stream duration.

### 1e. What telemetry does NOT carry

The `dependencies` table has **zero rows** for `invoice-be` in 90 days: Postgres,
Chroma HTTP and embedding calls are not auto-instrumented. `tracked_llm_call` spans
carry LLM duration only. Non-LLM steps therefore need instrumentation to measure
(§3).

---

## 2. Model and prompt facts

| Fact | Value | Source |
|---|---|---|
| Provider | `azure` | live env `LLM_PROVIDER`; `config.py:344` |
| Deployment | **`gpt-5-mini`** | live env `AZURE_OPENAI_DEPLOYMENT_NAME` (config default `gpt-4o-mini`, `config.py:358`, is overridden) |
| API version | `2024-02-15-preview` | live env; `config.py:357` |
| Reasoning model? | Yes — GPT-5 family; token pattern in §1c is consistent with billed reasoning tokens | inference from tokens_out; not a documented field |
| `reasoning_effort` | **not set anywhere** | `grep reasoning` in `utils/llm.py`, `agents/query_agent.py` → 0 hits |
| `max_tokens` on chat calls | **not set** — all four chat sites call `get_llm()` with no args | `query_agent.py:248, 3599, 3867, 4142` |
| `temperature` | not set (provider default) | `utils/llm.py::build_llm` kwargs: endpoint, key, api_version, deployment only |
| Second deployment in chat | none; eval judges use the same `get_llm()` | `telemetry` agent names |
| Summary / narration streamed? | **No** — `llm.invoke(summary_prompt)` awaited whole; no `.stream(`/`.astream(` in `query_agent.py` | `query_agent.py:4114` (SQL), `:4466` (RAG) |

### 2a. SQL system prompt — `build_sql_system_prompt`, question "discount amount for apex consulting group"

Measured with tiktoken `o200k_base` on a 6-invoice SQLite tenant with one prior
turn (±5% vs the unpublished gpt-5-mini vocabulary). **Total: 7,019 tokens.** Live
telemetry shows 8,498 in (p50) for the same call site — the difference is the
wrapped user message, real history and real tenant stats.

| component | tokens | share |
|---|---|---|
| numbered rules 1–11 + framing text | **3,231** | 46% |
| rule 6d (`_line_item_rule`, dialect-built) | **1,734** | 25% |
| persona (`CHAT_PERSONA_BLOCK`) | 947 | 13% |
| schema: hand-typed block | 460 | 7% |
| schema: ORM-derived supplement (Gap 413) | 283 | 4% |
| attribute grounding block (Gap 413) | 141 | 2% |
| tenant stats | 88 | 1% |
| prior-turn SQL block | 73 | 1% |
| chat history (1 turn) | 31 | <1% |
| style block (default) | 31 | <1% |
| tax grounding block | 0 (not triggered) | — |
| payment-status block | 0 (not triggered) | — |
| trainer rules / chat rules | 0 (none for this tenant) | — |

Rules text (numbered rules + 6d) is **4,965 tokens, 71% of the prompt**. It is
identical on every SQL turn.

### 2b. Summary prompt (SQL route)

| component | tokens |
|---|---|
| persona | 947 |
| full record block (1 invoice, `_full_record_block_for`) | **986** |
| style + rules + attribute note | 172 |
| results table (1 row) | 8 |
| computed figures block | 0 (no aggregate) |
| summary instructions + line-item template | not isolated — inline f-string at `query_agent.py:4301`; by subtraction from live 1,947 in: **≈ 100–300** |

Live: 1,947 in / 258 out (p50). The full record block is ~half of it for a
single-invoice answer; it is capped at 3 invoices / 12,000 chars
(`MAX_FULL_RECORD_INVOICES`, `MAX_FULL_RECORD_BLOCK_CHARS`).

### 2c. RAG system prompt

| component | tokens |
|---|---|
| persona | 947 |
| 5 retrieved chunks (~1 page each) | **≈ 2,510** (synthetic pages; real pages vary 300–900 tokens each) |
| tenant stats + rules + style + history | 150 |

Live: 2,809 in / 824 out for the one RAG turn.

---

## 3. Non-LLM steps

**Not measured on a real turn.** Telemetry carries no dependency spans (§1e), and
the local stack (`invoice-postgres-local`, `-chromadb-local`, `-redis-local`) was
down for the whole measurement window; it was started at the end of this pass and
had not reached healthy when the report was concluded (Redis refused at 6379
during the token measurement). Measuring these requires either the local stack
healthy plus a timing wrapper script, or one temporary instrumented turn in dev —
both are actions beyond "read-only", so they are left for the founder to authorise.

What is known without measurement:

| step | value | source |
|---|---|---|
| Non-LLM share of a median SQL turn | **≈ 5.5 s** (27.8 s − 22.3 s of LLM spans) | §1c reconciliation |
| Cache-hit turn (no LLM, no DB beyond Redis + session write) | 1,290 ms p50 | §1a — this is the floor of the request path |
| `get_embeddings` warm / Chroma query / Postgres query / `get_full_record` + `compute` / `get_chat_history` | **not measured** | — |
| Async: enqueue → worker pickup | **not measurable** — no Redis in dev; the job is handed to an in-process `ThreadPoolExecutor(max_workers=8)` (`routers/chat.py:37`) synchronously after the 202 | code |
| SSE poll interval | **1.5 s** Redis-status poll (`routers/chat.py:896`); 0.2 s inner loop on the pub/sub path (`:934`) | code |

---

## 4. Hardware

| item | value | source |
|---|---|---|
| `ca-invoice-be-dev` | **2.0 vCPU / 4 Gi**, minReplicas 1, maxReplicas 5 | live `az containerapp show`; `params.dev.json` overrides bicep defaults of 1.0 / 2.0Gi (`08-apps.bicep:109–111`) |
| `ca-queue-worker-dev` | 2.0 vCPU / 4 Gi, max 10 | live; `08-apps.bicep:118–120` |
| bge-m3 device | **CPU** — log line `No device provided, using cpu` at 05:50:48 UTC | BE logs, revision `--0000120` |
| bge-m3 load start | 3.2 s after "Application startup complete"; completion line not present in the 300-line tail, so load duration on 2 vCPU is **unbounded here** (Gap 278 recorded 40 s and 177 s cold stalls before the warm-up existed) | BE logs; tracker Gap 278 |
| Warm-up (Gap 278) complete before the measured turns? | **Almost certainly yes, by inference:** turns ran 39 min after revision `--0000117` started, and the first turn (RAG, 16.0 s, 2 LLM calls ≈ 15.4 s) shows no cold-load stall. Not provable: that revision's logs are no longer in the tail | §1b timestamps + revision list |
| Observation, reported as-is | On the **current** revision `--0000120`, startup logged `Chroma HttpClient failed: timed out. Falling back to PersistentClient` (05:50:48 UTC) after `Initializing Chroma HttpClient at ca-chromadb-dev.internal…:8000`. The API on that revision may be serving RAG from a local on-disk Chroma, not `ca-chromadb-dev`. The nine measured turns predate this revision | BE logs |

---

## 5. Summary table

| step | p50 | p95 | LLM? | fixable by |
|---|---|---|---|---|
| Classify (LLM path only; keyword hits skip it) | 3,092 ms | 4,395 ms | yes | code (keyword coverage) / model |
| SQL generation, attempt 1 | 15,570 ms | 35,348 ms | yes | model choice / code (prompt 7,019 tokens, 71% static rules) |
| SQL repair attempts 2–3 (1 turn) | +~60 s over a 3-attempt turn | — | yes | code (zero-row handling) / model |
| Summary narration | 3,620 ms | 12,835 ms | yes | model choice / code (not streamed) |
| RAG narration | 7,691 ms | — | yes | model choice / code (chunk count) |
| Non-LLM remainder of a SQL turn (history, stats, Postgres, full record, telemetry) | ≈ 5,500 ms (derived) | — | no | code — unmeasured; needs instrumentation |
| Cache-hit turn end to end | 1,290 ms | 1,812 ms | no | code / hardware |
| POST → 202 (async handoff) | 789 ms | 16,495 ms | no | code |
| SSE stream, user-perceived turn | 28,824 ms | 60,540 ms | — | all of the above |
| SSE polling granularity | 1,500 ms | — | no | code |
| bge-m3 embed (warm) / Chroma query / Postgres query / full record + compute / history | not measured | — | no | — |
| bge-m3 cold load on 2 vCPU | not bounded in this window | — | no | hardware / code (warm-up) |
| Tokens: SQL prompt in | 8,498 | — | — | code |
| Tokens: SQL generation out | 1,688 | — | — | model (reasoning) |

Sources: App Insights `customEvents` (`chat_turn`, `llm_agent_call`), `requests`,
`dependencies` (empty); `az containerapp show/logs/revision list` on
`rg-invoice-llm-dev`; `config.py`, `utils/llm.py`, `agents/query_agent.py`,
`routers/chat.py`, `chroma_client.py`, `infra/08-apps.bicep`, `infra/params.dev.json`;
tiktoken measurement script (scratchpad, not committed).
