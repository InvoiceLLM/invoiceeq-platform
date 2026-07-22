# Invoice AI — Backend API (`/apps/invoice-be`)

## Purpose
Core backend service powering the Invoice AI platform.  
Handles authentication, invoice processing, AI agent orchestration, audit workflows, semantic search, and multi-tenant data isolation.

## Tech Stack
| Layer          | Technology                                  |
|----------------|---------------------------------------------|
| Framework      | FastAPI (Python)                            |
| ORM            | SQLAlchemy / SQLModel                       |
| Task Queue     | Azure Storage Queues (background worker), Redis (Pub/Sub + cache) |
| Database       | PostgreSQL (Azure Managed, Tenant-Isolated) |
| Vector DB      | ChromaDB (Managed)                          |
| LLM Provider   | Azure OpenAI (GPT-4 class models)           |
| Embedding      | Local Hugging Face `BAAI/bge-m3`            |
| OCR/Parsing    | Azure Document Intelligence                 |
| Blob Storage   | Azure Blob Storage (Encrypted at Rest)      |

## Directory Structure
```
invoice-be/
├── routers/
│   ├── auth.py                  # SSO, Tenant Registration, User/Role Management
│   ├── invoices.py              # Upload, Status Polling, Delete
│   ├── audit.py                 # Flagging, Approve/Reject/Paid Logic
│   ├── chat.py                  # Semantic Query Interface
│   ├── dashboard.py             # Metrics & Filtering
│   ├── connectors.py            # Google Drive / Salesforce OAuth + import
│   └── trainer.py               # Conversational Feedback Loops & Rule Registry
├── agents/
│   ├── extraction_agent.py      # Data Extraction & Verification Tools
│   ├── query_agent.py           # RAG Logic & Citation Handler
│   └── trainer_agent.py         # Rule-based Structural Tags
├── queue_worker/
│   ├── main_worker.py           # Azure Storage Queue polling loop (standalone process)
│   └── handlers.py              # Background Tasks (OCR, extraction, chunking, vectorization)
├── alembic/                     # Database migrations (env.py + versions/)
├── tests/                       # Unit & integration tests
├── models.py                    # SQLAlchemy/SQLModel Definitions (Tenant-Isolated)
├── chroma_client.py             # Vector DB Connection Logic
├── config.py                    # Application configuration & settings
├── dependencies.py              # FastAPI dependencies (tenant extraction, auth)
├── entrypoint.sh                # Container CMD: runs `alembic upgrade head` then starts uvicorn
├── main.py                      # FastAPI Entry Point (API only — does not process the queue)
├── pyproject.toml               # Python project configuration and dependencies
└── uv.lock                      # Lockfile for reproducible builds
```

## Local Development Setup

To run the backend locally, you must spin up the local isolated databases (PostgreSQL, ChromaDB, and Redis) using Docker and initialize the database schema via Alembic.

### 1. Setup Environment Variables
Clone the `.env.example` template into a local `.env` file (which is git-ignored):
```bash
cp .env.example .env
```
Ensure you fill in your actual developer API keys (such as `AZURE_OPENAI_API_KEY`, `AZURE_DOC_INTEL_KEY`, and `CLERK_SECRET_KEY`) inside the `.env` file. The database and Redis strings are pre-configured to target your local containers.

### 2. Start Local Databases (Docker Compose)
We maintain a shared database environment in the repository root. Run the following command from the project root directory:
```bash
# Start Postgres, ChromaDB, and Redis containers in the background
docker compose up -d
```
You can verify the containers are healthy by running:
```bash
docker compose ps
```

### 3. Apply Schema Migrations (Alembic)
Once the Postgres container is healthy, run the migrations to create the local tables:
```bash
# Navigate to backend directory
cd apps/invoice-be

# Synchronize local packages and dependencies
uv sync

# Apply all migrations to your local Postgres database
uv run alembic upgrade head
```

### 4. Working with Database Changes (For Developers)
If you add or modify database tables in [models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py):
1. **Generate Migration Script**: Run the autogenerate command:
   ```bash
   uv run alembic revision --autogenerate -m "describe_your_changes"
   ```
   This will auto-detect the delta between SQLModel models and your local DB schema and create a new script under `alembic/versions/`.
2. **Apply Local Updates**: Run `uv run alembic upgrade head` to apply it to your local container.
3. **Commit to Git**: Check in the new generated revision script inside your feature branch so other developers get the updates when they pull.

### 5. Run Backend Server + Queue Worker
`main.py` only serves the HTTP API — it no longer processes the background queue itself (it used to run the worker as an embedded thread; that was removed since `queue-worker` is deployed as its own separately-scaled Container App in Azure, and running both in-process locally masked whether the standalone worker actually worked). To get a fully working local pipeline (upload → OCR → extraction), run both in separate terminals:

```bash
# Terminal 1 — API server
uv run uvicorn main:app --reload

# Terminal 2 — Queue worker (polls Azure Storage Queue / Azurite)
uv run python -m queue_worker.main_worker
```

## API Endpoints
| Method | Endpoint                               | Description                                          |
|--------|----------------------------------------|------------------------------------------------------|
| POST   | `/api/v1/invoices/upload`              | Upload PDF(s) with pre-applied tags. Uploads are never blocked; errors are flagged as non-blocking alerts |
| GET    | `/api/v1/invoices/status/{job_id}`     | Poll processing status (single upload, 1–5 PDFs)    |
| GET    | `/api/v1/invoices/stream/{batch_id}`   | **SSE stream** for bulk upload status (6+ PDFs)      |
| PUT    | `/api/v1/audit/resolve/{invoice_id}`   | Save manual modifications, dismiss/clear alerts, and mark as PAID or REJECTED |
| POST   | `/api/v1/chat/sessions/{session_id}/message` | Semantic search / SQL / casual chat, with PDF citations |
| GET    | `/api/v1/dashboard/metrics`            | Aggregated metrics by tenant & status                |
| POST   | `/api/v1/trainer/sessions/{session_id}/chat`   | Conversational training interface to submit layout rules in plain English |
| POST   | `/api/v1/trainer/sessions/{session_id}/commit` | Commit and save structured layout rules under the vendor's template registry |

## Real-Time Notification Strategy (Hybrid)
| Scenario       | Mechanism                  | How It Works                                                     |
|----------------|----------------------------|------------------------------------------------------------------|
| 1–5 PDFs       | **Polling** (React Query)  | Frontend polls `GET /status/{job_id}` every 2 seconds            |
| 6+ PDFs (bulk) | **SSE** (Server-Sent Events)| Frontend opens `GET /stream/{batch_id}` — backend pushes updates |

- `queue_worker` (a separately deployed/scaled process, not `invoice-be` itself) publishes completion events to **Redis Pub/Sub** (`invoice.update.{batch_id}` channel)
- SSE endpoint subscribes to that Redis channel and streams events to the browser
- Frontend uses the browser-native `EventSource` API (no extra libraries)

## Tenant Isolation Rule
> Every table contains `tenant_id` (UUID). A FastAPI Dependency extracts `tenant_id` from the JWT on every request. **Every database query** is filtered by this `tenant_id`.

## Environment Variables
```env
DATABASE_URL=
REDIS_URL=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_STORAGE_CONNECTION_STRING=
AZURE_DOC_INTEL_ENDPOINT=
AZURE_DOC_INTEL_KEY=
CHROMA_HOST=
CHROMA_PORT=
CLERK_SECRET_KEY=
TOKEN_ENCRYPTION_KEY=

# LangSmith AI Agent Tracking & Evaluation
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT="invoice-ai-platform"
```
