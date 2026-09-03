# Feature 6.1 item A3 — stream the phrasing calls

**Date:** 2026-09-03 · **Personas:** senior-dev (build), functional-tester (runs)

| run | command | result |
|---|---|---|
| A3 unit | `pytest tests/test_a3_streaming.py -p no:randomly -q` | **11 passed in 15.87s** |
| FE types | `npx tsc --noEmit` | exit 0 |
| FE e2e (async queue incl. new streaming case) | `npx playwright test e2e/chat-async-queue.spec.ts` | **3 passed (37.7s)** |
| wide regression, 19 suites (Postgres `localhost:5433`) | `pytest ... -p no:randomly -q` | **587 passed in 167.75s (0:02:47)** |

## What the unit tests pin

Streams and emits monotonically growing partials with a final `final=True` event;
flushes at most every 48 characters (200 one-char chunks → 5 events, not 200);
list-shaped content blocks are joined; an exception mid-stream propagates
unchanged. Each of the three conditions alone forces `.invoke()`: flag off, no
listener (the synchronous HTTP path), a model without `.stream` (mocks, recording
LLMs). Exactly the four phrasing sites use the helper and SQL generation does not.
`build_llm` passes `stream_usage=True`.

## What the e2e pins

With an SSE body carrying only `streaming` progress events (no `completed`), the
bubble shows the partial answer text (`data-testid="chat-streaming-partial"`) and
not the "Analyzing…" status line.

## What this evidence does not show

Time-to-first-visible-token on the live async path with the flag on. That needs
real traffic; the flag is declared but not set live.
