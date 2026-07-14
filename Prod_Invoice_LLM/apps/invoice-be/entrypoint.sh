#!/bin/bash
set -e

echo "Running Alembic Database Migrations..."
# Upgrade the database to the latest schema
alembic upgrade head

echo "Starting FastAPI Server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
