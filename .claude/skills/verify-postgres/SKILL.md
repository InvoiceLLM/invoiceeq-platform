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

## 4. Keep the result line verbatim

The exact `N passed, M failed` line is what gets cited in the tracker, the spec and the
coverage map. A paraphrase is not a citation. If it fails, report the failure output as it
came out — never soften it, never call a partial pass a pass.

## 5. What this does not cover

Chat, RAG and queue paths also need real Redis and Chroma (`docker compose up -d` brings up
all three). If a verification needed a service that was not running, say which, and mark the
work `[~]` rather than `[x]`.
