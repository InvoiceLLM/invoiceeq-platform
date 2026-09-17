---
name: verify-postgres
description: Run backend tests against real Postgres — the only test evidence this repo accepts. Use before claiming any DB-touching or API change works, when asked to verify or test the backend, or before marking a task done.
---

# Verify against real Postgres

`.claude/CONVENTIONS.md` hard rule 2: a fix may not be claimed working on a SQLite-only run.
The SQLite/Postgres fidelity gap has been the root cause of 4+ incidents here.

Local Postgres runs on **port 5433** (not 5432), container `invoice-postgres-local`,
credentials from `docker-compose.yml`.

## 1. Bring it up

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM" && docker compose up -d postgres && docker inspect -f '{{.State.Health.Status}}' invoice-postgres-local
```

Wait for `healthy`. If Docker Desktop is not running, start it before retrying — a second
identical failure means stop and diagnose, not retry again.

## 2. Apply migrations

A migration that was written but never applied is not verified. `alembic/env.py` reads
`settings.DATABASE_URL`, so the env var is what points it at Postgres:

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be" && DATABASE_URL="postgresql://postgres:localpassword123@localhost:5433/invoice_db" ./.venv/Scripts/python.exe -m alembic upgrade head
```

## 3. Run the smallest relevant test first

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be" && DATABASE_URL="postgresql://postgres:localpassword123@localhost:5433/invoice_db" ./.venv/Scripts/python.exe -m pytest tests/<file>.py -q
```

One test file per task. The full suite is for track-boundary checkpoints only, or when the
founder asks. Widen only after the targeted run passes and the widening is justified.

## 3b. The chat suites need a SECOND, virgin database

The suites ported by BE Gap 570 (`test_chat_*.py`, `test_widget_token.py`, `test_gap5*.py`,
`test_c2_cache_correctness.py`) read `TEST_DATABASE_URL`, and their fixtures drop every table
after each test. They therefore need a **throwaway database that is empty**, separate from the
`DATABASE_URL` one the migrations were applied to:

```bash
docker exec invoice-postgres-local psql -U postgres \
  -c "DROP DATABASE IF EXISTS chat_test WITH (FORCE);" -c "CREATE DATABASE chat_test;"

DATABASE_URL="postgresql://postgres:localpassword123@localhost:5433/invoice_db" \
TEST_DATABASE_URL="postgresql://postgres:localpassword123@localhost:5433/chat_test" \
  ./.venv/Scripts/python.exe -m pytest tests/<file>.py -q
```

Two traps, both real and both cost a review round on 2026-09-17:
- **The name must contain `test`** and the host must be `localhost`/`127.0.0.1`, or the BE Gap 570
  guard aborts collection. `chat_t` is rejected; `chat_test` is fine.
- **Pointing `TEST_DATABASE_URL` at a database already migrated to head** produces
  `61 failed, 559 passed, 308 errors` from residual rows and constraint collisions — not a code
  defect. Recreate it empty. On a virgin DB the same suites run together clean.

Consequence worth knowing: the chat migrations are exercised by `alembic upgrade head`, never by
the suite (BE Gap 642).

## 4. Keep the result line verbatim

The exact `N passed, M failed` line is what gets cited in the tracker, the spec and the
coverage map. A paraphrase is not a citation. If it fails, report the failure output as it
came out — never soften it, never call a partial pass a pass.

## 5. What this does not cover

Chat, RAG and queue paths also need real Redis and Chroma (`docker compose up -d` brings up
all three). If a verification needed a service that was not running, say which, and mark the
work `[~]` rather than `[x]`.
