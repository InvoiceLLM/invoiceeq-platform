# Invoice AI — Backend API (`/apps/invoice-be`)

## Purpose
Core backend service powering the Invoice AI platform.  
Handles authentication, invoice processing, AI agent orchestration, audit workflows, semantic search, and multi-tenant data isolation.

## Tech Stack
| Layer          | Technology                                  |
|----------------|---------------------------------------------|
| Framework      | FastAPI (Python)                            |
| ORM            | SQLAlchemy / SQLModel                       |
| Task Queue     | Celery + Redis                              |
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
│   └── dashboard.py             # Metrics & Filtering
├── agents/
│   ├── extraction_agent.py      # JSON Schema Enforcer
│   ├── verification_agent.py    # Math/Vendor Verification Tools
│   ├── query_agent.py           # RAG Logic & Citation Handler
│   └── trainer_agent.py         # Rule-based Structural Tags
├── workers/
│   ├── celery_app.py            # Celery Configuration
│   └── tasks.py                 # Background Tasks (Chunking, Vectorization, Parsing)
├── mcp_servers/
│   ├── ingestion_mcp.py         # Connector for SharePoint/Drive
│   └── action_mcp.py            # Webhooks/Notification Logic
├── tests/                       # Unit & integration tests
├── models.py                    # SQLAlchemy/SQLModel Definitions (Tenant-Isolated)
├── chroma_client.py             # Vector DB Connection Logic
├── config.py                    # Application configuration & settings
├── dependencies.py              # FastAPI dependencies (tenant extraction, auth)
├── main.py                      # FastAPI Entry Point
├── pyproject.toml               # Python project configuration and dependencies
└── uv.lock                      # Lockfile for reproducible builds
```

## Local Development Setup

To run the backend locally, we use the **`uv`** package manager for fast, reproducible dependency resolution:

```bash
# Install dependencies and sync virtual environment
uv sync

# Run FastAPI app in development mode
uv run uvicorn main:app --reload
```

## API Endpoints
| Method | Endpoint                               | Description                                          |
|--------|----------------------------------------|------------------------------------------------------|
| POST   | `/api/v1/invoices/upload`              | Upload PDF(s) with pre-applied tags. Uploads are never blocked; errors are flagged as non-blocking alerts |
| GET    | `/api/v1/invoices/status/{job_id}`     | Poll processing status (single upload, 1–5 PDFs)    |
| GET    | `/api/v1/invoices/stream/{batch_id}`   | **SSE stream** for bulk upload status (6+ PDFs)      |
| PUT    | `/api/v1/audit/resolve/{invoice_id}`   | Save manual modifications, dismiss/clear alerts, and mark as PAID or REJECTED |
| POST   | `/api/v1/chat/query`                   | Semantic search with PDF citations                   |
| GET    | `/api/v1/dashboard/metrics`            | Aggregated metrics by tenant & status                |
| POST   | `/api/v1/trainer/chat`                 | Conversational training interface to submit layout rules in plain English |
| POST   | `/api/v1/trainer/rules`                | Commit and save structured layout rules under `#VendorName` template registry |

## Real-Time Notification Strategy (Hybrid)
| Scenario       | Mechanism                  | How It Works                                                     |
|----------------|----------------------------|------------------------------------------------------------------|
| 1–5 PDFs       | **Polling** (React Query)  | Frontend polls `GET /status/{job_id}` every 2 seconds            |
| 6+ PDFs (bulk) | **SSE** (Server-Sent Events)| Frontend opens `GET /stream/{batch_id}` — backend pushes updates |

- Celery workers publish completion events to **Redis Pub/Sub** (`batch:{batch_id}` channel)
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
```
