# Backend Feature 12: Alembic Database Migrations

## Overview
This feature introduces formal database migration management using Alembic. It replaces the early-prototyping `SQLModel.metadata.create_all()` approach, ensuring that schema changes (e.g. adding new columns, altering tables) can be safely deployed without destroying existing data.

## Target Architecture

1. **Alembic Initialization (`alembic/` & `alembic.ini`)**:
   - The backend includes an `alembic` directory tracking all schema versions.
   - `alembic/env.py` is configured to import `SQLModel` and all database entities from `models.py`.
   - `alembic.ini` configuration is decoupled from hardcoded credentials, relying strictly on the `DATABASE_URL` environment variable.

2. **Migration Scripts (`alembic/versions/*.py`)**:
   - The initial migration (`xxxx_initial_schema.py`) maps out the baseline `Tenant`, `User`, `Invoice`, `AuditLog`, and `ExtractionTemplate` tables.

3. **Execution Context (`entrypoint.sh`)**:
   - The Docker image utilizes an `entrypoint.sh` bash script as its `CMD`.
   - Before starting Uvicorn, the script runs `alembic upgrade head`.
   - This prevents race conditions where multiple backend replicas attempt to migrate concurrently, while isolating database structure logic from the core application startup.

## Task Breakdown
- `[ ]` Task 12.1: Initialize Alembic configuration files.
- `[ ]` Task 12.2: Configure `alembic/env.py` for dynamic environment variable URL loading and `SQLModel` metadata attachment.
- `[ ]` Task 12.3: Generate the baseline "Initial schema" migration.
- `[ ]` Task 12.4: Create `entrypoint.sh` and update `Dockerfile` to execute migrations dynamically in the deployment environment.
