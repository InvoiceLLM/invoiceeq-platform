#!/usr/bin/env bash
# Brings up a clean local invoice-be stack for running the e2e regression
# suite / benchmark from tests/e2e and tests/benchmark.
#
# No queue worker is started here: both test suites process invoices
# synchronously in-process (tests/sync_processing.py) rather than via Azure
# Storage Queue + a separately-running worker, because Azurite's queue
# emulator repeatedly wedges during local iteration (messages stuck,
# approximate_message_count > 0 but receive_messages() always returns empty,
# even after a full volume wipe). The queue/worker mechanism itself is
# already validated separately (KEDA autoscale rule confirmed live on
# ca-queue-worker-dev) — these suites exist to check extraction/RAG
# accuracy, not re-prove the queue works. Run tests/e2e's suite with
# E2E_SYNC_PROCESSING unset (default) if you specifically want to exercise
# the real queue path against a real worker instead.
#
# Also handles: local .env tuned for LLM_PROVIDER=ollama with placeholder
# Azure OpenAI/Doc Intel endpoint+key values (never filled in, since local
# dev normally doesn't need them); the long-running docker-compose Postgres
# has drifted alembic history; Azurite's API-version check rejects the
# current SDK.
#
# Usage: bash tests/run_local_stack.sh
# Requires: docker, az cli logged in with Key Vault read access, uv-managed
# .venv already synced (uv sync --group dev).
set -euo pipefail
cd "$(dirname "$0")/.."   # apps/invoice-be
REPO_ROOT="$(cd ../.. && pwd)"
PG_PORT=5434
LOG_DIR="/tmp"

echo "== Resetting Azurite (fresh volume, --skipApiVersionCheck) =="
cd "$REPO_ROOT"
if ! grep -q skipApiVersionCheck docker-compose.yml; then
  echo "ERROR: docker-compose.yml's azurite command is missing --skipApiVersionCheck. Add it first." >&2
  exit 1
fi
docker compose stop azurite >/dev/null 2>&1 || true
docker compose rm -f azurite >/dev/null 2>&1 || true
docker volume rm prod_invoice_llm_azurite_data >/dev/null 2>&1 || true
docker compose up -d azurite chromadb >/dev/null

echo "== Starting throwaway Postgres (port $PG_PORT, avoids touching your long-running local DB) =="
docker rm -f bench-sanity-pg >/dev/null 2>&1 || true
docker run -d --name bench-sanity-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=localpassword123 \
  -e POSTGRES_DB=invoice_db -p ${PG_PORT}:5432 postgres:16-alpine >/dev/null
for i in $(seq 1 15); do
  docker exec bench-sanity-pg pg_isready -U postgres -d invoice_db >/dev/null 2>&1 && break
  sleep 1
done

cd "$REPO_ROOT/apps/invoice-be"
export DATABASE_URL="postgresql://postgres:localpassword123@localhost:${PG_PORT}/invoice_db"
echo "== Running alembic upgrade head =="
.venv/Scripts/python.exe -m alembic upgrade head

echo "== Fetching real secrets from Key Vault =="
export TOKEN_ENCRYPTION_KEY=$(.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export AZURE_OPENAI_API_KEY=$(az keyvault secret show --vault-name kv-invoice-llm-dev --name AZURE-OPENAI-API-KEY --query value -o tsv)
export AZURE_DOC_INTEL_KEY=$(az keyvault secret show --vault-name kv-invoice-llm-dev --name AZURE-DOC-INTEL-KEY --query value -o tsv)
export AZURE_OPENAI_ENDPOINT="https://openai-invoice-llm-dev.openai.azure.com/"
export AZURE_DOC_INTEL_ENDPOINT="https://docintel-invoice-llm-dev.cognitiveservices.azure.com/"
export AZURE_OPENAI_DEPLOYMENT_NAME="gpt-5-mini"
export AZURE_OPENAI_API_VERSION="2025-08-07"
export LLM_PROVIDER="azure"

echo "== NOTE: Azure OpenAI / Doc Intelligence must have publicNetworkAccess=Enabled for this to work =="
echo "   (they're private-endpoint-only by default; ask before flipping, and flip back after)"

echo "== Killing any previous local backend/worker =="
for pid in $(netstat -ano | grep ":8000" | grep LISTENING | awk '{print $5}'); do taskkill //PID "$pid" //F >/dev/null 2>&1 || true; done

echo "== Starting backend =="
rm -f "$LOG_DIR/local_backend.log"
nohup .venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/local_backend.log" 2>&1 &
disown
for i in $(seq 1 20); do
  curl -sf http://localhost:8000/docs -o /dev/null 2>&1 && break
  sleep 1
done
curl -sf http://localhost:8000/docs -o /dev/null 2>&1 || { echo "Backend failed to start, see $LOG_DIR/local_backend.log" >&2; exit 1; }
echo "Backend up. No worker started — tests process synchronously in-process (see header comment)."

echo ""
echo "Stack ready. E2E_BASE_URL / --base-url = http://localhost:8000/api/v1"
echo "Run regression: uv run pytest -m e2e tests/e2e   (add E2E_SYNC_PROCESSING=true, or the regression suite will hang waiting for a worker that isn't running)"
echo "Run benchmark:  .venv/Scripts/python.exe -m tests.benchmark.run_benchmark --base-url http://localhost:8000/api/v1 --regions US,INDIA,UK --count 10 --day-seed <N>"
