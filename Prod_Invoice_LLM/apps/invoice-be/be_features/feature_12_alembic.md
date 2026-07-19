# Backend Feature 12: Alembic Database Migrations

## Overview
This feature introduces formal database migration management using Alembic. It replaces the early-prototyping `SQLModel.metadata.create_all()` approach, ensuring that schema changes (e.g. adding new columns, altering tables) can be safely deployed without destroying existing data.

### File Coordinates
* Config: [apps/invoice-be/alembic.ini](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/alembic.ini) — `script_location = %(here)s/alembic`
* Env: [apps/invoice-be/alembic/env.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/alembic/env.py) → imports `models` (registers every `SQLModel` table onto `target_metadata`), reads the real DB URL from `config.settings.DATABASE_URL`
* Revision template: [apps/invoice-be/alembic/script.py.mako](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/alembic/script.py.mako) — includes `import sqlmodel` (SQLModel's `AutoString` column type needs it; autogenerate omits this import by default, which otherwise produces a migration that fails with `NameError: name 'sqlmodel' is not defined` the moment it runs)
* Baseline migration: [apps/invoice-be/alembic/versions/7504f993dd7e_initial_schema.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/alembic/versions/7504f993dd7e_initial_schema.py) — creates all 8 tables (`tenant`, `users`, `invoice`, `audit_logs`, `extraction_templates`, `chatsession`, `chatmessage`, `tenantconnection`)
* Entrypoint: [apps/invoice-be/entrypoint.sh](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/entrypoint.sh) → `alembic upgrade head` then `exec uvicorn main:app`

## Target Architecture

1. **Alembic Initialization (`alembic/` & `alembic.ini`)**:
   - The backend includes an `alembic` directory tracking all schema versions.
   - `alembic/env.py` is configured to import `SQLModel` and all database entities from `models.py`.
   - `alembic.ini` configuration is decoupled from hardcoded credentials, relying strictly on the `DATABASE_URL` environment variable.

2. **Migration Scripts (`alembic/versions/*.py`)**:
   - The initial migration (`7504f993dd7e_initial_schema.py`) maps out the baseline `Tenant`, `User`, `Invoice`, `AuditLog`, and `ExtractionTemplate` tables (plus `ChatSession`, `ChatMessage`, `TenantConnection`).

3. **Execution Context (`entrypoint.sh`)**:
   - The Docker image utilizes an `entrypoint.sh` bash script as its `CMD`.
   - Before starting Uvicorn, the script runs `alembic upgrade head`.
   - This prevents race conditions where multiple backend replicas attempt to migrate concurrently, while isolating database structure logic from the core application startup.

### Known caveat — local & Azure dev DBs are not blank
This baseline migration was generated and verified against an *empty* database (`alembic revision --autogenerate` + `alembic upgrade head`, confirmed idempotent on a throwaway local Postgres). Two live databases are **not** empty and need manual reconciliation before `alembic upgrade head` will apply cleanly there:
- **Local `docker-compose` Postgres** (`invoice_db`): has 7 of the 8 tables already, at an old schema (`invoice` is missing 13 columns added since — `coordinates`, `field_confidence`, `taxes`, etc. — and the `users` table doesn't exist at all yet), stamped at an orphaned `alembic_version` (`c6e338d84981`) with no matching migration file in the repo. Simplest fix: `docker compose down -v` to wipe the local volume, then let `alembic upgrade head` create everything fresh from this baseline.
- **Azure dev Postgres** (`psql-invoice-llm-dev`): unknown state — never verified against this migration. The container's `entrypoint.sh` has been failing at the `alembic upgrade head` step on every cold start until this fix (Alembic was an unconfigured `alembic init` skeleton), so it's plausible nothing has been created there via Alembic yet; if some tables already exist from manual/ad-hoc setup, `alembic upgrade head` will fail on `relation already exists` and need `alembic stamp head` instead — check before deploying.

## Task Breakdown
- `[x]` Task 12.1: Initialize Alembic configuration files.
- `[x]` Task 12.2: Configure `alembic/env.py` for dynamic environment variable URL loading and `SQLModel` metadata attachment.
- `[x]` Task 12.3: Generate the baseline "Initial schema" migration.
- `[x]` Task 12.4: Create `entrypoint.sh` and update `Dockerfile` to execute migrations dynamically in the deployment environment.
