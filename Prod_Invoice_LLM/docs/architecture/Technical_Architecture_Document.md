# Technical Architecture Document

![User Journey and Data Flow](./user_data_flow_1782387729047.png)

## Invoice AI SaaS Platform — Production-Grade Architecture

| Attribute         | Detail                                      |
|-------------------|----------------------------------------------|
| **Project**       | Invoice AI SaaS (Multi-Tenant LLM Platform)  |
| **Version**       | 1.0                                          |
| **Date**          | 25 June 2026                                 |
| **Last reconciled** | **2026-09-07 against trackers + code** (`be_features_tracker.md`, `fe_features_tracker.md`, `website_features_tracker.md`, `apps/invoice-be` source, `infra/params.dev.json`). Where an older statement in this document disagreed with the code, the code won. |
| **Classification**| Internal — Engineering Team                  |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Context & High-Level Architecture](#2-system-context--high-level-architecture)
3. [Repository Structure (Mono-Repo)](#3-repository-structure-mono-repo)
4. [Backend Architecture (`/apps/invoice-be`)](#4-backend-architecture-appsinvoice-be)
5. [Frontend Architecture (`/apps/invoice-fe`)](#5-frontend-architecture-appsinvoice-fe)
6. [Marketing Website (`/apps/invoice-website`)](#6-marketing-website-appsinvoice-website)
7. [AI / Agentic Pipeline](#7-ai--agentic-pipeline)
8. [Database Design](#8-database-design)
9. [Embedding & Vectorization](#9-embedding--vectorization)
10. [API Inventory & Contracts](#10-api-inventory--contracts)
11. [Authentication & Multi-Tenancy](#11-authentication--multi-tenancy)
12. [Payment & Billing Integration](#12-payment--billing-integration)
13. [Development Workflow & Branching Strategy](#13-development-workflow--branching-strategy)
14. [Testing & Quality Assurance](#14-testing--quality-assurance)
15. [Operational & Licensing Costs](#15-operational--licensing-costs)
16. [Glossary](#16-glossary)
17. [Service Flow (Outbound) — Live](#17-service-flow-outbound--live)

---

## 1. Executive Summary

The Invoice AI SaaS platform is a **multi-tenant, AI-powered invoice processing system** built on Microsoft Azure. It provides automated invoice extraction, verification, audit workflows, and semantic search capabilities powered by LLM agents. The system is designed for **enterprise-grade data isolation**, where every tenant's data is strictly segregated at both the application and database layers.

**Core Value Proposition:**
- **Automated Extraction** — **NOVA** (Smart Invoice Extraction agent) parses PDF invoices into structured JSON.
- **Verification Engine** — **SENTINEL** (Invoice Risk Detection agent) automatically flags arithmetic discrepancies, duplicate invoices, and low-confidence fields.
- **Auditor Control** — **SENTINEL** drives human-in-the-loop approval/rejection workflow with suggested Trainer rules.
- **Semantic Chat** — **SAGE** (Invoice Intelligence Chat agent) answers natural language queries over ingested invoice data with source citations.
- **Continuous Learning** — **EVOLVE** (Continuous Learning agent) learns from approved corrections and improves extraction for similar vendor invoices.

Added since the original blueprint (all live unless marked):
- **Bidirectional** — the same pipeline handles the tenant's own outbound (AR) invoices: verify → send → paid, with an AR dashboard and pre-send auditor (Service Flow, §17) and clone-and-edit Invoice Builder (Feature 17, PARTIAL).
- **Any business document, not only invoices** — a deterministic document-type step classifies each upload into one of 14 types; non-invoices (POs, quotations, delivery notes, statements…) are stored and searchable without polluting the invoice ledger (Feature 27). Images are accepted at every door and converted to PDF once (Feature 28).
- **Grounded chat over a document you are holding** — attach a PO/quotation/delivery note in Chat and SAGE matches it to the right invoice(s) and produces a deterministic reconciliation (Feature 26).
- **Every intake door** — browser upload, directory watcher, Google Drive connector, scheduled Autopilot sync, email-in (Feature 14), REST API with tenant API keys — with one durable Ingestion History (Gap 464).
- **Plug & Play** — tenant API keys with a workflow policy (full automation vs strict review), sandbox tenants, an embeddable chat widget, outbound webhooks and CSV/JSON/Drive outputs (Features 15 / 25).
- **Operated, not just shipped** — App Insights telemetry on every LLM call, nightly golden-bank evaluation with an LLM judge, a production-turn judge, and Azure Workbooks for cost, health and AI quality (Features 20 / 23).

---

## 2. System Context & High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL USERS / CLIENTS                           │
│                                                                            │
│  ┌─────────────┐    ┌─────────────────┐    ┌──────────────────────────┐     │
│  │  Marketing   │    │   Dashboard     │    │   SSO / Auth Provider   │     │
│  │  Website     │    │   (invoice-fe)  │    │   (Clerk)              │     │
│  │ (invoice-    │    │                 │    │                        │     │
│  │  website)    │    │                 │    └──────────┬─────────────┘     │
│  └──────┬───────┘    └────────┬────────┘               │                   │
│         │                     │                        │                   │
└─────────┼─────────────────────┼────────────────────────┼───────────────────┘
          │                     │                        │
          ▼                     ▼                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        AZURE CLOUD (VNet / Private Endpoints)              │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    FastAPI Backend (/apps/invoice-be)                │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────────┐  │   │
│  │  │  Auth.py   │  │ Invoices.py  │  │ Audit.py │  │   Chat.py    │  │   │
│  │  │  (SSO/JWT) │  │ (Upload/     │  │ (Flag/   │  │  (Semantic   │  │   │
│  │  │            │  │  Status)     │  │  Resolve)│  │   Query)     │  │   │
│  │  └────────────┘  └──────────────┘  └──────────┘  └──────────────┘  │   │
│  │  ┌────────────────────────────────────────────────────────────────┐ │   │
│  │  │                   AI AGENT LAYER                               │ │   │
│  │  │  extraction_agent (doc-type → classify → extract → verify)     │ │   │
│  │  │  query_agent (SQL/RAG/attachments) │ trainer_agent │ support  │ │   │
│  │  └────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────┬───────────────────────────────────────────┘   │
│                             │                                              │
│         ┌───────────────────┼───────────────────┐                          │
│         ▼                   ▼                   ▼                          │
│  ┌─────────────┐   ┌───────────────┐   ┌───────────────────┐              │
│  │  PostgreSQL  │   │  Redis /      │   │  Azure Blob       │              │
│  │  (Tenant-    │   │  Azure Queue  │   │  Storage (PDFs)   │              │
│  │   Isolated)  │   │  Workers      │   │                   │              │
│  └─────────────┘   └───────────────┘   └───────────────────┘              │
│                                                                            │
│  ┌─────────────────┐   ┌───────────────────┐   ┌────────────────────┐     │
│  │  ChromaDB        │   │  Azure OpenAI     │   │  Azure Document    │     │
│  │  (Vector Store)  │   │  (Embeddings +    │   │  Intelligence      │     │
│  │                  │   │   LLM Inference)  │   │  (OCR / PDF Parse) │     │
│  └─────────────────┘   └───────────────────┘   └────────────────────┘     │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  PayU (Payment Gateway — External, hosted checkout redirect)        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Repository Structure (Mono-Repo)

All services reside in a single monolithic repository to provide full context for AI-assisted development and cross-service alignment.

```
Invoice_LLM/                          # git root
├── .github/workflows                 # deploy-dev.yml (push master/develop, path-filtered), deploy-prod.yml (tag v*),
│                                     #   _deploy-service.yml (reusable build+push+deploy), e2e-regression.yml (dispatch only)
├── .claude/agents, .claude/skills    # agent personas + repo skills used for development
└── Prod_Invoice_LLM/
    ├── apps
    │   ├── invoice-website           # Marketing, pricing, Clerk auth gateway, sandbox onboarding, public relays
    │   ├── invoice-fe                # Dashboard, Ingestion, History, Invoices/Auditor, Chat, Trainer, Help, Admin, Settings
    │   └── invoice-be                # FastAPI, queue worker, AI agents, ACA job scripts, Alembic
    ├── infra                         # Staged Bicep 01-network … 10-budget, modules/, *-only.bicep templates,
    │                                 #   monitoring/*.json workbooks, params.{dev,prod}.json, deploy-all.ps1
    ├── docker, docker-compose.yml    # Local stack (Postgres, Redis, Chroma, Azurite)
    ├── docs                          # architecture/ (this doc, Cloud + Database docs, System Journey), extraction benchmarks
    ├── reports                       # load / security test reports (reserved)
    └── scripts
```

Feature specs and trackers live with their app: `apps/invoice-be/docs/feature_N_*.md` + `be_features_tracker.md`, `apps/invoice-fe/docs/` + `fe_features_tracker.md`, `apps/invoice-website/website_features/`.

---

## 4. Backend Architecture (`/apps/invoice-be`)

### 4.1 Directory Structure

The backend follows a **clean separation of concerns** with an async/agentic workflow pattern. Listing reconciled against the tree on 2026-09-07:

```
/apps/invoice-be/
├── main.py                      # FastAPI entry point; mounts every router below under /api/v1 (auth unprefixed)
├── config.py                    # Pydantic settings — every ENABLE_* flag and model deployment name (see §4.5)
├── dependencies.py              # Clerk JWT → TenantContext; inv_live_/inv_test_ API-key auth (§11)
├── models.py                    # SQLModel tables (§8)
├── chroma_client.py             # Per-tenant Chroma collections, embeddings, indexing (§9)
├── telemetry.py                 # App Insights custom events + dependency spans (§7.5)
├── routers/
│   ├── auth.py                  # /auth/me, /auth/provision, /auth/logout (Clerk)
│   ├── admin.py                 # /admin — tenant user administration (Feature 1.1)
│   ├── invoices.py              # /invoices — upload, watcher, status, SSE stream, batches, PDF, delete
│   ├── outbound_invoices.py     # /outbound-invoices — AR upload, confirm-send, mark-paid, Invoice Builder (F17)
│   ├── audit.py                 # /audit/resolve/{id} (SENTINEL)
│   ├── outbound_audit.py        # /outbound-audit/resolve/{id} (Feature 7.1)
│   ├── dashboard.py             # /dashboard — metrics, trainer-impact, insights
│   ├── outbound_dashboard.py    # /outbound-dashboard — AR metrics (Feature 8.1)
│   ├── chat.py                  # /chat — sessions, messages, async jobs (status + SSE), feedback, triage, chat rules
│   ├── chat_attachments.py      # /chat/sessions/{id}/attachments — Feature 26 PO/quotation attachments
│   ├── documents.py             # /documents — Feature 27 non-invoice documents (list, get, soft-delete)
│   ├── ingestion_history.py     # /ingestion-history — Gap 464 durable run log, archive/unarchive
│   ├── config_features.py       # GET /config/features — read-only ENABLE_* flags for the FE
│   ├── connectors.py            # /connectors — Google Drive OAuth + import (Salesforce removed 2026-08-28, Gap 334)
│   ├── autopilot.py             # /autopilot — scheduled Drive folder sync config, sync, history (Feature 13)
│   ├── email_ingestion.py       # /email — mailbox settings, sender allow-list, POST /mailintegration (Feature 14)
│   ├── trainer.py               # /trainer — EVOLVE sandbox sessions, corrections, commit, template history
│   ├── settings.py              # /settings — vendor-flow toggles, API key, widget tokens, workflow policy (F16/F25)
│   ├── webhooks.py              # /webhooks — subscription CRUD + delivery logs (Feature 15)
│   ├── webhook_docs.py          # OpenAPI-only schemas for the 7 webhook event payloads
│   ├── billing.py               # /billing — PayU checkout, usage, cancel/reactivate, surl/furl (Feature 11)
│   ├── support.py               # /support/contact (public), /support/ticket, /tickets, /chat (Feature 19)
│   ├── sandbox.py               # /sandbox — public inv_test_ key issuance/claim (Feature 25)
│   └── widget.py                # /widget/chat/message + WidgetCORSMiddleware (Feature 25)
├── agents/
│   ├── extraction_agent.py      # NOVA LangGraph: classify_doc_type → classify → dynamic_qa → extract → verify
│   ├── outbound_extraction_agent.py  # Thin AR wrapper over the same graph (Gap 283) — no second graph
│   ├── query_agent.py           # SAGE chat: SQL / RAG / CHAT / full-record / attachment routes
│   ├── query_tools.py           # LLM-free helpers (get_full_record, compute) — Feature 21 remnant
│   ├── sage_prompts.py          # PERSONA_BLOCK + schema reflection constants
│   ├── support_agent.py         # Deterministic keyword matcher + Chroma vector fallback (no LLM)
│   └── trainer_agent.py         # Rule constraint extraction for EVOLVE
├── queue_worker/
│   ├── main_worker.py           # Azure Storage Queue poller, per-tenant fair-share, DLQ after 5 dequeues
│   ├── handlers.py              # process_invoice, import_connector_file, reaudit_templates, deliver_webhook,
│   │                            #   process_chat_job, extract_attachment
│   └── outbound_handlers.py     # process_outbound_invoice
├── services/                    # file_intake (F28), document_type_classifier + doc_attributes (F27),
│                                #   document_comparison / chat_document_search / attachment_extraction (F26),
│                                #   full_records (F29), chat_queue (Gap 280), ingestion_batches (Gap 464),
│                                #   invoice_builder + pdf_render (F17), api_keys / sandbox / widget_tokens /
│                                #   workflow_outputs / invoice_export (F25), autopilot_sync (F13),
│                                #   webhooks + outbound_overdue (F15), billing_lifecycle (F11),
│                                #   agent_eval / online_quality_judge / online_eval_signals / ops_recommendation (F23),
│                                #   chat_rules + rule_impact (F18), trainer_sessions (F10), support_email (F19)
├── utils/                       # llm.py (build_llm/get_llm/get_llm_for_role), model_registry.py (roles + catalog),
│                                #   verification_tools.py, token_management.py, alert_registry.py, connector_oauth.py
├── scripts/                     # ACA job entry points: autopilot_job, sweep_* (billing, overdue, sandbox,
│                                #   chat_attachments), run_extraction_benchmark, run_agent_eval, emit_online_signals_job
└── alembic/versions/            # Single head e7f8a9b0c1d2 (Gap 467 invoice.notes)
```

Deleted since the previous revision of this document and therefore absent above: `agents/sage_orchestrator.py` (Feature 21, Gap 316, 2026-08-25), the Ops Digest agent `services/ops_digest*.py` / `scripts/ops_digest_job.py` (Feature 24, Gap 311, 2026-08-25), `services/pdf_substitute.py` (Gap 462) and the Salesforce connector code paths (Gap 334). Feature 22 never existed.

### 4.2 Tech Stack

| Layer             | Technology                                     |
|-------------------|------------------------------------------------|
| **Framework**     | FastAPI (Python), OpenTelemetry `FastAPIInstrumentor` (Gap 292) |
| **ORM**           | SQLAlchemy / SQLModel, Alembic migrations (head `e7f8a9b0c1d2`) |
| **Task Queue**    | Azure Storage Queue `extraction-tasks-queue` (+ `extraction-tasks-deadletter-queue`) for extraction, connector import, re-audit, webhook delivery, chat jobs and attachment extraction |
| **Memory / Cache**| Redis — chat job queue + progress pub/sub, answer cache, SSE pub/sub, Trainer sessions, per-tenant in-flight ceilings |
| **Database**      | PostgreSQL (Azure Flexible Server, tenant-isolated)    |
| **Vector DB**     | ChromaDB (self-hosted container app `ca-chromadb-{env}`, Azure Files volume) |
| **LLM Provider**  | Azure OpenAI, api-version `2024-10-21` (Gap 465), through `utils/model_registry.py` roles — see §7.6. Dev deployments: `gpt-5.6-luna` (primary/fast), `gpt-5-mini` (judge/chat_summary) |
| **Embedding**     | Local Hugging Face `BAAI/bge-m3` (`sentence-transformers`)  |
| **OCR/Parsing**   | Azure Document Intelligence `prebuilt-invoice` (`DOC_INTEL_MODEL_ID`) |
| **Blob Storage**  | Azure Blob Storage (Encrypted at Rest)         |

### 4.3 Async Processing Flow

Every intake door — browser upload, directory watcher, Google Drive import, Autopilot sync, email-in, outbound upload, Trainer upload — converges on the same shape: normalise the file (Feature 28), persist a row, push one message onto the Azure Storage Queue, let the worker do the rest.

#### Single/Small Upload Flow (1–5 PDFs) — Polling

```
User Upload (PDF or PNG/JPG/TIFF/WEBP/BMP)
       │
       ▼
POST /api/v1/invoices/upload
       │
       ├── services/file_intake.py::normalize_upload() — images → PDF once, here (Feature 28, no flag)
       ├── SHA-256 file hash → Layer-1 duplicate check (status DUPLICATE, duplicate_of_invoice_id)
       ├── Save PDF → Azure Blob Storage
       ├── Create Invoice record (status: PROCESSING); record_ingestion_batch(trigger="manual") (Gap 464)
       ├── Return batch_id + job_ids to Frontend
       │
       ▼
Queue Worker (queue_worker/main_worker.py → handlers.handle_process_invoice)
       │
       ├── 1. _run_ocr() — Azure Document Intelligence prebuilt-invoice (bounded retry, resource rotation)
       ├── 2. Extraction graph (agents/extraction_agent.py)
       │       ├── classify_doc_type → one of 14 DOC_TYPES (Feature 27; ENABLE_GENERIC_EXTRACTION pinned True)
       │       ├── classify (STANDARD/COMPLEX) → dynamic_qa → extract → verify (retry ≤ 2)
       │       ├── money family (INVOICE, PROFORMA_INVOICE, CREDIT_NOTE, DEBIT_NOTE) → Invoice row
       │       │       ├── ✅ no alerts → status: COMPLETED
       │       │       └── ❌ alerts    → status: AUDIT_REQUIRED
       │       └── any other known doc_type → `documents` row (_persist_non_invoice_document), Invoice row removed
       ├── 3. Indexing → ChromaDB (`invoice_chunks_{tenant}` or `docs_{tenant}`), SSE status INDEXING
       ├── 4. Webhooks `invoice.completed` / `invoice.audit_required` enqueued (Feature 15)
       │
       ▼
Frontend polls GET /invoices/status/{job_id}  (or subscribes to the SSE stream below)
```

#### Autopilot Folder Sync Flow (Scheduled / Manual)

The Autopilot feature runs bulk ingestion deterministically from a Google Drive folder, sharing the exact same backend entrypoint logic as a manual upload.

```
Autopilot Trigger
       │
       ├── Trigger A: scripts/autopilot_job.py — services/autopilot_sync.py::run_sync_for_all_due_tenants()
       │              (written as an Azure Container Apps Job entry point; NO ACA Job module for it exists in
       │               infra/08-apps.bicep as of 2026-09-07 — scheduling on dev is unverified)
       ├── Trigger B: POST /api/v1/autopilot/sync ("Sync Now", Ingestion → Autopilot tab)
       │
       ▼
services/autopilot_sync.py::run_sync()
       │
       ├── 1. Scan files in the mapped Google Drive folder modified since last sync
       │       (valid_sources = {"gdrive"}; Salesforce removed 2026-08-28, Gap 334)
       ├── 2. Deduplicate: Drive file ID in tenant_autopilot_logs → skip; SHA-256 hash → skip
       ├── 3. For each unique file: normalize_upload() → Blob → Invoice(PROCESSING) → queue message
       │       → tenant_autopilot_logs row (SUCCESS | SKIPPED_DUPLICATE | FAILED | NO_NEW_FILES)
       └── 4. prune_autopilot_history() — rows older than history_retention_days (default 90; Gap 429)
       │
       ▼
Queue Worker — identical to the manual path above
```

History is read back through `GET /autopilot/history`, `/history/{batch_id}/files`; runs can be hidden (`DELETE /autopilot/history[/{batch_id}]` sets `hidden_at`, Gaps 427-434) and appear merged into the Ingestion History screen (§5.2).

#### Bulk Upload Flow (6+ PDFs) — Server-Sent Events (SSE)

When uploading many PDFs at once, polling each individually would generate excessive requests (e.g., 100 PDFs × 1 request every 2 seconds = 50 req/sec). Instead, the system uses **SSE** — a single persistent HTTP connection where the backend pushes status updates as each PDF completes.

```
Frontend                              Backend                        Queue Worker
   │                                     │                               │
   ├── POST /invoices/upload (bulk) ────▶│  (accepts N files)            │
   │                                     ├── Save all → Blob Storage     │
   │                                     ├── Create N records (PROCESSING)
   │◀── { batch_id: "xyz", job_ids: [] }┤                               │
   │                                     ├── Drop N Messages to Queue ──▶│
   │                                     │                               │
   ├── GET /invoices/stream/{batch_id} ─▶│  (opens SSE connection)       │
   │                                     │                               │
   │◀── PROCESSING_OCR ─────────────────┤◀── _publish_sse_events() ────┤
   │◀── EXTRACTING_DATA ────────────────┤                               │
   │◀── INDEXING ───────────────────────┤                               │
   │◀── COMPLETED / AUDIT_REQUIRED / FAILED per invoice ────────────────┤
   │                                     │                               │
   └── Connection closes ✅              │                               │
```

**SSE Implementation Details:**
- Backend uses **Redis Pub/Sub** — `queue_worker/handlers.py::_publish_sse_events()` publishes to channel `invoice.update.{batch_id}` on each status transition
- SSE endpoint `GET /invoices/stream/{batch_id}` (`routers/invoices.py`) subscribes to that channel and streams events to the browser
- Frontend uses the native browser `EventSource` API (no additional libraries required)

#### Email-In Flow (Feature 14, live 2026-08-26)

SendGrid Inbound Parse → website relay `apps/invoice-website/app/api/v1/email/mailintegration/route.ts` → `POST /api/v1/email/mailintegration` (shared secret, fail-closed, `services/inbound_mail_security.py`) → per-tenant sender allow-list (`tenant_email_senders`) → same normalise → Blob → Invoice → queue path, `record_ingestion_batch(trigger="email")`. Rejected mail lands in `dropped_inbound_emails` (Admin Console `GET /admin/dropped-emails`). Addresses and DNS are documented in `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` §4; `config.py` defaults still carry the placeholder `invoiceeq.app` domain and are overridden by bicep parameters on Azure.

### 4.4 Chat Job Flow (Gap 280 — async queue is the default)

`ENABLE_ASYNC_CHAT_QUEUE` defaults **True** in `config.py` (some older docstrings in `routers/chat.py` still say False — code wins). `POST /chat/sessions/{id}/message` enqueues a job through `services/chat_queue.py` (Redis list `chat_tasks_queue`, status `chat_job_status:{job}`, progress channel `chat_job_channel:{job}`, per-tenant ceiling `chat_inflight:{tenant}` = 3 concurrent, Gap 364 → HTTP 429 + `Retry-After`) and returns a `job_id`; the worker's `handle_process_chat_job` runs `run_query_agent()` under a per-session Redis lock (`chat_session_lock`) and publishes step-level progress; the browser follows `GET /chat/jobs/{job_id}/stream` (SSE) or polls `GET /chat/jobs/{job_id}/status`. Feature 26 attachment extraction rides the same queue (`handle_extract_attachment`, stages reading → extracting → matching). `ENABLE_CHAT_STREAMING` (Feature 6.1 item A3, token streaming of the phrasing calls) is **False by default and `true` on dev**; it is inert without the queue path.

### 4.5 Feature Flags (`config.py` defaults vs dev Azure `infra/params.dev.json`)

| Flag | Default | Dev Azure | Gates |
|---|---|---|---|
| `ENABLE_ASYNC_CHAT_QUEUE` | True | true | Redis chat job queue (§4.4) — only path with progress SSE |
| `ENABLE_CHAT_STREAMING` | **False** | **true** | F6.1 A3 streaming of chat phrasing calls |
| `ENABLE_GENERIC_EXTRACTION` | True — pinned, **do not disable** (flag-off removes `classify_doc_type` from the compiled graph and every non-invoice becomes an "invoice" again) | true | Feature 27 doc-type routing |
| `ENABLE_GENERIC_DOC_CHAT` | **False** | **true** | Feature 26 Part 2 — chat over attached-document content (`chat_docs_{tenant}`) |
| `ENABLE_ANSWER_CONTRACT_GATE` | True | not in bicep (default applies) | Feature 29 §29.9 every-figure-in-evidence gate |
| `ENABLE_PRODUCTION_QUALITY_JUDGE` | **False** | **true** | LLM judge on every real chat turn (Feature 23 Phase 3) |
| `ENABLE_ENTITY_RESOLVER`, `ENABLE_SEMANTIC_VIEWS`, `ENABLE_CERTIFIED_EXAMPLES`, `ENABLE_KNOWLEDGE_LAYER`, `ENABLE_RERANK` | False | parameterised in bicep | Feature 29 knowledge-layer items — **in progress, uncommitted 2026-09-07**; not shipped |
| `SANDBOX_KEYS_ENABLED` | False | not in bicep → False | Feature 25 public `inv_test_` sandbox keys |
| `CHAT_ATTACHMENT_TTL_DAYS` | 30 | — | Feature 26 attachment expiry (`scripts/sweep_chat_attachments.py`) |
| `ALLOW_MOCK_AUTH`, `MOCK_EMBEDDINGS` | False | — | test-only |

`GET /api/v1/config/features` exposes the read-only `ENABLE_*` view the FE consumes (`apps/invoice-fe/lib/featureFlags.ts`).

### 4.6 Scheduled Jobs (Azure Container Apps Jobs over `infra/modules/compute/scheduled-job.bicep`)

| Job | Script | Notes |
|---|---|---|
| `caj-billing-lifecycle` | `scripts/sweep_billing_lifecycle.py` | cron `0 6 * * *`; not deployed on dev (tracker 2026-08-30) |
| `caj-overdue-sweep` | `scripts/sweep_outbound_overdue.py` | `outbound_invoice.overdue` webhooks; not deployed on dev |
| `caj-sandbox-sweep` | `scripts/sweep_sandbox_tenants.py` | expired unclaimed sandboxes; not deployed on dev (Gap 357 open) |
| `caj-benchmark-eval` | `run_extraction_benchmark.py --mode live --no-gate` + `run_agent_eval.py --run-label nightly` | nightly; deployed on dev (`benchmark-eval-job-only.bicep`) |
| `caj-online-signals` | `scripts/emit_online_signals_job.py` | 6-hourly online quality signals; deployed on dev (`emit-online-signals-job-only.bicep`) |
| `caj-chat-doc-ttl` | `scripts/sweep_chat_attachments.py` | Feature 26 TTL sweep (`chat-doc-ttl-job-only.bicep`) |
| Autopilot | `scripts/autopilot_job.py` | script exists; **no ACA Job module in bicep** (unverified) |

None of these jobs run tests or gate a deploy — the CI/CD `benchmark-gate` job was removed (Gap 312).

---

## 5. Frontend Architecture (`/apps/invoice-fe`)

### 5.1 Tech Stack

| Layer                  | Technology                              |
|------------------------|-----------------------------------------|
| **Framework**          | Next.js (App Router)                    |
| **Language**           | TypeScript                              |
| **UI Components**      | Shadcn/UI + Tailwind CSS                |
| **Forms/Validation**   | Zod + React Hook Form                   |
| **API/State**          | TanStack Query (React Query)            |

### 5.2 Screen-Level Specifications

Route inventory (`apps/invoice-fe/app`, reconciled 2026-09-07):

| Route | Screen | Notes |
|---|---|---|
| `/dashboard` | Command Center | KPI grid; splits AP/AR side by side when `send_invoices_enabled` (Feature 2.1 FE) |
| `/ingestion` | Ingestion portal | Upload tab (PDF **and** PNG/JPG/TIFF/WEBP/BMP, Feature 28 / FE F19), Autopilot tab (FE F13), Send Invoices tab (FE F3.1) |
| `/history` | Ingestion History | Gap 464 durable run log across every door, archive/unarchive (`components/ingestion/IngestionHistoryTable.tsx`), added 2026-09-05 |
| `/invoices`, `/invoices/review/[id]`, `/invoices/outbound-review/[id]` | Ledgers + review consoles | Auditor (SENTINEL) inbound and outbound |
| `/invoices/outbound-builder` | Invoice Builder | Clone-and-edit an outbound invoice (FE F20 / BE F17, added 2026-09-05, PARTIAL) |
| `/chat` | SAGE chat | Attachments (`AttachmentChip`, `AttachmentMatchConfirm`, `DocumentEvidence`, `ReconciliationTable`), async job progress |
| `/trainer` | EVOLVE sandbox | Alert-anchored sessions (FE F14 / BE F18) |
| `/flows` | Flow explainer | Animated demo diagram (FE F11) |
| `/help` | Help Center | 7 guides, support bot, `TicketHistoryPanel` (FE F15 / BE F19) |
| `/admin`, `/debug-org` | Admin Console | User permissions, dropped emails (FE F16 / BE F1.1) |
| `/settings`, `/settings/{connectors,email,security,subscriptions,webhooks,workflows}` | Settings | Security = API key + `WidgetTokenSection`; Workflows = Plug & Play wizard (FE F17, 2026-08-30, PARTIAL) |

#### A. Dashboard (Command Center)
- **Layout**: Grid / Bento-box layout
- **KPI Cards**: Processed Invoices, Total Spend (Live/Paid), Audit Queue Count; AR mirror (collected, outstanding, at-risk) from `GET /outbound-dashboard/metrics`
- **Filter Bar**: Date Range Picker, Vendor Dropdown, Payment Status (All/Paid/Unpaid/Rejected)
- **Navigation**: Sidebar (Left) + Main Widget Grid (Right)

#### B. File Ingestion (The Gateway)
- **Top Section**: Drag & Drop upload area (dashed border, supports multi-file selection; accepted extensions come from `lib/featureFlags.ts` → `GET /api/config/features`)
- **Bottom Section**: Real-time status table; the durable per-run view lives on `/history`
- **Columns**: File Name, Upload Date, Status (Processing/Completed/Audit Required/Duplicate/Failed), Actions
- **Logic (1–5 files)**: On drop → `POST /api/v1/invoices/upload` → poll `GET /invoices/status/{job_id}` via React Query
- **Logic (6+ files / bulk)**: On drop → `POST /api/v1/invoices/upload` (bulk) → open SSE via `GET /invoices/stream/{batch_id}` → real-time row-by-row status updates as each file completes

#### C. Auditor Tab (The Safety Net)
- **Layout**: Split-screen (flex/grid)
- **Left Panel**: PDF Preview (`react-pdf` viewer) with bounding-box overlay from `invoice.coordinates`
- **Right Panel**: Editable extracted data form (JSON fields)
- **Bottom Bar**: [Reject] [Approve/Pending] [Mark as Paid]
- **Logic**: Buttons call `PUT /api/v1/audit/resolve/{invoice_id}` (inbound) or `PUT /api/v1/outbound-audit/resolve/{invoice_id}` (outbound) → Shadcn Toast on success

#### D. Semantic Chat (The Analyst)
- **Layout**: Message-style (chat bubbles)
- **Top**: Scrollable history area; attachment chips per session
- **Bottom**: Input bar with Send icon + attach control (PO / quotation / other document, Feature 26)
- **Logic**: `POST /api/v1/chat/sessions/{session_id}/message` → `job_id` → `GET /chat/jobs/{job_id}/stream` progress → render markdown, computed-figure tables, reconciliation tables, clickable PDF citation links

### 5.3 FE-BE Communication Rule

> **The Golden Rule**: The Frontend **never** interacts with the queue (Redis/Azure Storage Queues) directly. It only communicates with the FastAPI Backend.

The browser never calls `invoice-be` directly — the backend has no public ingress (§2, §4.1 of `Cloud_Architecture_Document.md`). All calls are same-origin (`/api/**`) against Next.js Route Handlers running inside the `invoice-fe` container (`app/api/*`, one group per backend router), which forward to the backend server-side using a runtime-only `BACKEND_API_URL` env var. This is also what makes the internal-only backend reachable at all: Route Handlers run inside the same Container Apps Environment as `invoice-be` and can reach it over the internal network regardless of its external-ingress setting, whereas a public user's browser could not.

`middleware.ts` exempts `/api/(.*)` from Clerk route protection (FE Gap 358) so the same proxy routes also serve external `inv_live_` API-key callers (Gaps 358/359); the backend's `dependencies.py` decides who the caller is (§11.4). When the website's `ENABLE_FE_PROXY` is on, `apps/invoice-website/next.config` rewrites the app pages and `/api/{admin,audit,auth,autopilot,chat,connectors,dashboard,docs,email,ingestion-history,invoices,outbound-*,settings,support,trainer,webhooks}` to `FE_INTERNAL_URL` so the custom domain fronts both (Gaps 187/469).

### 5.4 Callback/State Tracking Mechanism (Hybrid: Polling + SSE)

The system uses a **hybrid approach** based on upload volume:

#### Mode A: Polling (1–5 PDFs)
For small uploads, polling keeps things simple:
1. **Trigger**: After `POST /invoices/upload`, store `job_id` in React Query
2. **Monitor**: `useQuery` with `refetchInterval` (every 2 seconds) hits `GET /invoices/status/{job_id}`
3. **Completion**: When status returns `COMPLETED`, `AUDIT_REQUIRED`, `DUPLICATE` or `FAILED`, stop polling and update UI

#### Mode B: Server-Sent Events (6+ PDFs / Bulk)
For bulk uploads, SSE avoids excessive polling:
1. **Trigger**: After `POST /invoices/upload` (bulk), receive `batch_id`
2. **Connect**: Open SSE stream via `GET /invoices/stream/{batch_id}` using browser-native `EventSource`
3. **Receive**: Backend pushes a status event as each individual file moves through `PROCESSING_OCR → EXTRACTING_DATA → INDEXING → COMPLETED/AUDIT_REQUIRED/FAILED`
4. **Update**: Frontend updates the specific row in the status table for each event received
5. **Completion**: When every job in the batch has a terminal status, close the SSE connection

Chat uses the same pattern on its own channel: `GET /chat/jobs/{job_id}/stream` (§4.4).

#### Why This Hybrid?
| Scenario | Mechanism | Reason |
|----------|-----------|--------|
| 1–5 PDFs | Polling | Simple, no persistent connections needed |
| 6+ PDFs (bulk) | SSE | Prevents 50+ req/sec polling overhead |
| WebSockets | Not used | Adds unnecessary complexity (sticky sessions, reconnection) |

---

## 6. Marketing Website (`/apps/invoice-website`)

### 6.1 Tech Stack

| Layer           | Technology                             |
|-----------------|----------------------------------------|
| **Framework**   | Next.js (App Router, SSR enabled)      |
| **Styling**     | Tailwind CSS                           |
| **Components**  | Shadcn/UI (shared with dashboard)      |
| **Payment**     | PayU (hosted checkout redirect)        |
| **Auth**        | Clerk (`@clerk/nextjs`; `middleware.ts` guard) |
| **Edge**        | Azure Front Door + WAF on `invoicellm.admsofttech.com` (dev, Gap 185); `ENABLE_FE_PROXY` rewrites app routes to `FE_INTERNAL_URL` |

### 6.2 Directory Structure

```
/apps/invoice-website/
├── app/
│   ├── layout.tsx                    # Root Layout (Fonts, Providers, Navbar, Footer)
│   ├── page.tsx                      # Main Landing Page (Hero, Features, Pricing)
│   ├── login/page.tsx                # SSO / Clerk Auth Entry Point
│   ├── signup/page.tsx               # Clerk sign-up + org creation + server-side provision call
│   ├── forgot-password/page.tsx      # Two-step Clerk password reset
│   ├── contact/page.tsx              # Contact Us form — category/urgency/message (Website Feature 5, Gap 183)
│   ├── billing/{success,failed}/     # PayU return pages (public, deliberately not Clerk-gated)
│   ├── privacy/page.tsx              # Privacy Policy
│   ├── terms/page.tsx                # Terms of Service
│   └── api/
│       ├── auth/provision/route.ts   # Server-side proxy → backend /auth/provision
│       ├── contact/route.ts          # Server-side proxy → backend POST /api/v1/support/contact
│       │                             # (honeypot + edge rate limit, Gap 249)
│       ├── billing/create-checkout-session/route.ts
│       ├── v1/billing/payu/{success,failure}/route.ts   # PayU surl/furl pass-through
│       └── v1/email/mailintegration/route.ts            # SendGrid Inbound Parse pass-through
├── globals.css                       # Tailwind & Shadcn setup
├── components/
│   ├── ui/                           # Shadcn/UI components (Buttons, Cards, etc.)
│   └── marketing/
│       ├── Header.tsx, Footer.tsx, Hero.tsx, HeroModeTabs.tsx, BenefitsStrip.tsx
│       ├── AITeamSection.tsx, FlowsShowcaseSection.tsx, FlowsModal.tsx, WorkspaceShowcase.tsx
│       ├── SageChatPreview.tsx                       # Feature 2 showcase (NOVA/SENTINEL/SAGE/EVOLVE)
│       ├── WorkflowRecipeSelector.tsx, SandboxKeyCta.tsx   # Feature 7 Plug & Play onboarding (PARTIAL)
│       └── PricingTable.tsx
├── app/api/sandbox/{keys,claim}/route.ts   # Feature 7 → backend /sandbox (needs SANDBOX_KEYS_ENABLED)
├── lib/
│   └── utils.ts                      # Tailwind class merger
└── middleware.ts                     # Auth guard (redirects logged-in users to app)
```

> Billing is owned entirely by the backend (`/apps/invoice-be/routers/billing.py`) since it needs direct write access to `tenants.billing_plan`. The website has no PayU SDK of its own — it calls the backend's checkout-session endpoint, which returns a fully hash-signed set of form fields; the website renders these as a hidden auto-submitting HTML form POSTing directly to PayU's hosted payment page (`_payment`) — a **full-page redirect**, not a client-side overlay (this is the one meaningful UX difference from the Stripe/Razorpay model considered earlier).

### 6.3 Functional Sections

| Section               | Purpose                                          | Key Details                                                                      |
|-----------------------|--------------------------------------------------|----------------------------------------------------------------------------------|
| **Hero**              | Immediate value proposition                       | "Production-Grade AI Invoice Processing" — CTA redirects to SSO registration     |
| **Feature Teaser**    | Build confidence in tech capability               | 3-column grid: Extraction, Verification Engine, Auditor Control (with hover FX)  |
| **Security & Trust**  | Overcome enterprise data-safety objections        | Azure AI Foundry, VNet, Private Endpoints, RBAC, "No Data Training" guarantee    |
| **Pricing Plans**     | Drive paid upgrades                               | Free (₹0, 50 invoices), Pro Standard (₹4,999/mo), Pro Combined (₹8,999/mo — required for outbound) — `components/marketing/PricingTable.tsx` |
| **Auth Gateway**      | Seamless transition to the app                    | Clerk sign-in / sign-up / forgot-password pages; sign-up provisions the tenant via `/api/auth/provision` |
| **Plug & Play onboarding** | Let a developer try the API before signing up | `WorkflowRecipeSelector` + `SandboxKeyCta` → `/api/sandbox/keys` (Website Feature 7, PARTIAL; backend `SANDBOX_KEYS_ENABLED` is False) |
| **Contact Us (`/contact`)** | Capture pre-sale and support inquiries from anonymous visitors | Dedicated route (Website Feature 5, Gap 183), linked from Header + Footer. Category (Sales / Technical Support / Billing / Partnership / General), urgency pills (Low / Normal / Urgent with SLA copy), message. Posts to `/api/contact`, which proxies to the backend's public `POST /api/v1/support/contact` → `supportticket` row + SendGrid staff alert to `SUPPORT_NOTIFY_EMAIL` (`config.py` default `sbanerji@admsofttech.com`; the earlier `Application@infinevocloud.com` address is retired). Hardened with a hidden honeypot field and a sliding-window rate limit at both the proxy and the backend (Gaps 249–251). **Distinct from the Footer's "Contact Sales"** below, which is landing-page pricing copy, not this route. |
| **Footer**            | Compliance                                        | Privacy Policy, Terms of Service, Contact Sales                                  |

### 6.4 Payment Flow (PayU)

```
User clicks "Upgrade"
       │
       ▼
POST /api/v1/billing/create-checkout-session   (invoice-be)
       │      generates txnid + SHA-512 hash: key|txnid|amount|productinfo|firstname|email|<5 udf>||||||salt
       ▼
Receive signed form fields (key, txnid, amount, productinfo, hash, surl, furl, ...)
       │
       ▼
Browser full-page redirect: hidden form auto-POSTs to PayU's hosted /_payment page
       │
       ▼
User completes payment on PayU's page (card/UPI/netbanking + any 3DS/OTP step)
       │
       ▼
PayU POSTs the result to surl (success) or furl (failure)   (invoice-be)
       │
       ▼
Backend verifies the response hash AND cross-checks server-to-server via
PayU's verify_payment API (defends against a spoofed client-side POST to
surl/furl) — then updates Tenant billing_plan in PostgreSQL
```

> **Key**: The website **never** stores credit card/UPI info. The backend's `surl`/`furl` handler — cross-verified against PayU's `verify_payment` API rather than trusted on its own — acts as the "source of truth" for payment state, since a bare POST to a public return URL can't be trusted by itself.
>
> **Recurring billing note**: PayU's classic hash-based flow (verified working end-to-end against PayU's own sandbox as of 2026-07-31) is a **one-time payment** mechanism, not a native subscription API like Stripe/Razorpay. The MVP therefore re-runs this same one-time flow each billing cycle (tenant re-pays monthly, prompted by the app) rather than true auto-debit recurring. PayU does offer a separate Standing Instruction (SI) / recurring-payments product for real auto-renewal — deliberately out of scope until this manual-renewal MVP is live and that product's setup is separately researched.

---

## 7. AI / Agentic Pipeline

The backend employs a **multi-agent architecture** where specialized AI agents handle distinct processing stages, each built as a LangGraph state machine (or a plain router) with a topology suited to its role rather than a generic, open-ended ReAct loop. The Feature 21 "SAGE orchestrator" (a tool-calling ReAct layer over the query agent) was built and then deleted on 2026-08-25 (Gap 316); the Feature 24 Ops Digest agent was deleted the same day (Gap 311). Neither is part of the pipeline below.

### 7.1 Agent Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENTIC AI PIPELINE (2026-09-07)                  │
│                                                                            │
│  ┌──────────────────────────────┐      ┌─────────────────────────────┐     │
│  │ Extraction Graph — NOVA      │─────▶│ Trainer Agent — EVOLVE      │     │
│  │ agents/extraction_agent.py   │      │ agents/trainer_agent.py     │     │
│  │ classify_doc_type → classify │      │ • alert-anchored sessions   │     │
│  │ → dynamic_qa → extract       │      │ • rule constraints → templates│   │
│  │ → verify (retry ≤ 2)         │      │ Trigger: POST /trainer/      │     │
│  │ Trigger: any intake door     │      │   sessions/{id}/commit       │     │
│  └──────────────┬───────────────┘      └─────────────────────────────┘     │
│                 │ Invoice rows + documents rows + Chroma chunks             │
│                 ▼                                                          │
│  ┌──────────────────────────────┐      ┌─────────────────────────────┐     │
│  │ Query Agent — SAGE           │      │ Support Agent               │     │
│  │ agents/query_agent.py        │      │ agents/support_agent.py     │     │
│  │ SQL │ RAG │ CHAT │ full-record│     │ keyword + vector match,     │     │
│  │ │ attached-document branches │      │ no LLM (Feature 19)         │     │
│  │ Trigger: POST /chat/sessions/│      │ Trigger: POST /support/chat │     │
│  │   {id}/message (async job)   │      └─────────────────────────────┘     │
│  └──────────────────────────────┘                                          │
│  Judges (Feature 23): services/agent_eval.py (nightly golden bank),        │
│  services/online_quality_judge.py (production turns, flag-gated)           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Extraction Graph — `classify_doc_type → classify → dynamic_qa → extract → verify`

`extraction_agent.py` compiles **one** deterministic **LangGraph State Graph** (`_build_extraction_graph(include_doc_type_classifier=...)`) with a self-correcting validation loop. Since Gap 283 (2026-08-21) the outbound (AR) path uses this same graph parameterised by `flow_direction`; `agents/outbound_extraction_agent.py` is a thin entry-point wrapper, not a second graph.

1. **`classify_doc_type_node`** (Feature 27, present only when `ENABLE_GENERIC_EXTRACTION` is on — it is pinned on) — `services/document_type_classifier.py` assigns one of the 14 `DOC_TYPES`: `QUOTATION, PROFORMA_INVOICE, PURCHASE_ORDER, ORDER_CONFIRMATION, CONTRACT, DELIVERY_NOTE, GRN, INVOICE, RECEIPT, CREDIT_NOTE, DEBIT_NOTE, REMITTANCE_ADVICE, STATEMENT_OF_ACCOUNT, OTHER`, with `doc_type_evidence`. The type selects the schema, prompt and verification rubric via `resolve_extraction_profile(flow_direction, doc_type)`.
2. **`classify_node`** — STANDARD vs COMPLEX via `services/invoice_classifier.py` (layout irregularity, tax/discount structure, line-item count).
3. **`dynamic_qa_node`** — COMPLEX documents only: a pre-analysis LLM pass asking document-specific questions (multi-rate tax, holdbacks, e-invoicing identifiers) before the main extraction call.
4. **`extract_node`** — the primary-role LLM (`utils/llm.get_llm(max_tokens=profile.max_tokens)`) with structured output over the profile's schema, given OCR layout text + page-by-page base64 page images + the tenant's Trainer rules (§7.4).
5. **`verify_node`** — the critic. Pure checks from `utils/verification_tools.py`: `verify_line_items_math`, `verify_totals_math`, `verify_grand_total_in_source_text`, `verify_line_item_amounts_in_source_text` (a silently self-corrected number fails faithfulness even if internally consistent), plus per-field OCR confidence → `low_confidence_field` alerts. Alert vocabulary is registered in `utils/alert_registry.py`.
6. **`route_after_verification`** — loops back to `extract` with the alerts as feedback while `retry_count < 2` and at least one alert is outside `NON_RETRYABLE_ALERT_TYPES`; otherwise ends. `queue_worker/handlers.py` then persists `COMPLETED` (no alerts) or `AUDIT_REQUIRED`, or — for a known non-money `doc_type` — writes a `documents` row instead (`_routes_to_documents_table`).

**OCR**: `handlers._run_ocr()` calls Azure Document Intelligence `prebuilt-invoice` (bounded retry with resource rotation) — structured fields, bounding boxes and per-field confidence are persisted to `invoice.coordinates` / `invoice.field_confidence` for the auditor UI overlay (`_should_persist_coordinates` keeps this to the money family).

**Multi-Modal Integration**: visual channel (page renderings as `image/jpeg` base64) + structured channel (Doc Intelligence fields and layout text); spatial cues resolve OCR column-shift ambiguity on line items.

**LLM**: role `primary` from `utils/model_registry.py` (§7.6) — `gpt-5.6-luna` on dev, `gpt-5-mini` in `config.py` defaults and prod params. No `gpt-4o` deployment remains.

**Token Guardrails**: `utils/token_management.py::check_token_guardrails` counts text + image tokens against the registry's context limit for the resolved deployment; over-limit documents route to `AUDIT_REQUIRED` with a `token_limit_exceeded` alert without calling the LLM.

**Template System**: `extraction_templates` / `extraction_template_versions` hold per-tenant Global and per-vendor rule constraints committed by EVOLVE. `handlers._get_template_rules()` applies the Global template first, then re-runs extraction with the vendor template merged in once `vendor_name` is known (vendor wins on conflict). There is no static `default_templates.json` fallback in the codebase.

**Failure Handling**: an OCR/LLM failure writes an explicit `extraction_failed` alert and routes to `AUDIT_REQUIRED` (or `FAILED` when nothing could be persisted) — never `COMPLETED`. Messages that fail 5 dequeues are moved to `extraction-tasks-deadletter-queue`; `services/invoice_reconciliation.py` / `scripts/reconcile_stuck_invoices.py` re-enqueue rows stuck in `PROCESSING`/`UPLOADED`.

**Duplicate Detection (2-layer, Feature 3.1)**: Layer 1 — SHA-256 `file_hash` match at upload → status `DUPLICATE`, `duplicate_of_invoice_id` set. Layer 2 — post-extraction `invoice_number` + `vendor_name` match.

**Image intake (Feature 28)**: `services/file_intake.py::normalize_upload()` converts PNG/JPG/TIFF/WEBP/BMP to PDF once at every door (`invoices`, `outbound_invoices`, `trainer`, `email_ingestion`, `autopilot_sync`, connector import) with a 50-megapixel decompression guard; nothing downstream sees an image. Ships without a flag. The Azure-path manual verification is still outstanding (tracker `[~]`).

### 7.3 Query Agent — Router-Based Chat (SAGE)

`query_agent.py::run_query_agent()` routes each turn to a dedicated execution path rather than an open-ended tool loop:

1. **Route** — `classify_query()` on the `fast` role (Feature 6.1 item A2) labels the turn **SQL** (structured lookups/aggregates over `invoice`), **RAG** (semantic search over `invoice_chunks_{tenant}`), **CHAT** (casual), or — when the session holds Feature 26 attachments — an **attached-document branch** (`_run_attached_document_turn`, `_compare_attachment_to_invoices`).
2. **SQL path** — schema linking block (`_schema_linking_block_for`, Feature 6.1 C4) precedes generation; the system prompt keeps a stable **cacheable prefix** so Azure prompt caching applies (item A4); generation honours `AZURE_OPENAI_SQL_REASONING_EFFORT` / `..._MAX_COMPLETION_TOKENS` (item A1); a bounded 3-attempt repair loop; **tenant isolation asserted on the SQL parse tree** with `sqlglot` (`assert_tenant_isolation_on_ast`, Gap 414) — not a regex over the text; `execute_generated_sql` runs it. Zero rows trigger `_diagnose_zero_rows` + `_zero_rows_clarification` (Gap 424) instead of a confident "none found".
3. **Full records (Feature 29 §29.5)** — `services/full_records.py::fetch_full_records()` attaches the complete invoice record(s) named by the SQL result (`items`, `taxes`, `sa_alerts`, `notes`, chunks) so the narration is not limited to the projected columns; `_computed_figures_block_for()` and `services/document_comparison.check_line_arithmetic()` (§29.6) do every calculation in Python before the model speaks.
4. **RAG path** — `chroma_client.query_invoice_chunks` (k=5, cosine distance ≤ `0.49`, Gap 244) with hybrid keyword boosting; citations `{invoice_id, vendor_name, page}`.
5. **Synthesis** — phrasing on the `primary` role (`chat_summary` role for full-record narration via `_chat_summary_llm()`), with the tenant's Trainer rules injected (`_get_global_business_rules`, `_get_vendor_business_rules`) plus Feature 18 chat-correction rules (`_chat_rules_block`, table `tenant_chat_rules`) and the tenant's chat style (`_get_chat_style_block`). Feature 6.1 A3 streams these phrasing calls when `ENABLE_CHAT_STREAMING` is on.
6. **Answer contract (Feature 29 §29.9)** — `_answer_contract_gate()` requires every figure in the prose to exist in the evidence (numeric comparison); one regeneration that names the offending figure, then an abstain payload. Gated by `ENABLE_ANSWER_CONTRACT_GATE` (default True).

**Answer Cache**: Redis `chat_answer_cache:{tenant_id}:{normalized_query}` (1 h TTL), keyed additionally on the sorted attachment ids (§29.12), **skipped for narrowing follow-ups** so one session's answer is never served to another's (Gap 423), and invalidated on every Trainer commit/rollback (`routers/trainer.py::_invalidate_chat_answer_cache`). There is no `chat_qa_shortcuts` table.

**Conversational Memory**: `chatmessage` rows are the transcript; older turns are condensed into `chatsession.history_summary` and the current focus snapshot into `chatsession.focus` (migration `c3d4e5f6a9b0`). No LangGraph checkpointer is used.

**Guardrails**: `_wrap_user_input()` and `_wrap_retrieved_document_text()` fence untrusted text before it reaches the prompt; `redact_query_internals()` / `user_safe_error_detail()` keep SQL and tenant identifiers out of user-visible errors (Gap 294); the AST isolation check above is the tenant boundary.

**Feature 26 — attached documents (PO / quotation / other)**: `POST /chat/sessions/{id}/attachments` stores the file (table `chat_attachments`, TTL `CHAT_ATTACHMENT_TTL_DAYS`=30); the worker's `handle_extract_attachment` runs `extract_attachment → index_attachment → match_attachment` (`services/attachment_extraction.py`): `_run_ocr` + `run_extraction_agent` on the attachment (so its `doc_type` comes from the Feature 27 classifier node, Gap 430), then its pages are indexed into `chat_docs_{tenant}`. Matching (`services/document_comparison.find_candidate_invoices`) is tiered — Tier 1 normalised PO-number exact match, Tier 2 party name + date window, Tier 3 extended candidates — and anything ambiguous goes back as a confirmation card (`build_confirmation_payload`, `POST /chat/attachments/{id}/confirm-matches`). The comparison mode is a function of the attachment's `doc_type` (`resolve_comparison_mode`, e.g. quantity mode for delivery notes, `list_reconcile` for statements); `compare_reference_to_invoices` + `build_suggested_actions` produce a deterministic header/line diff stored in `document_comparisons` (`match_policies` holds tenant tolerances). Content questions over the attachment's own text (`services/chat_document_search.py`) are behind `ENABLE_GENERIC_DOC_CHAT` (default False, on in dev).

### 7.4 Trainer Agent (EVOLVE)

`trainer_agent.py` turns human corrections into extraction constraints; `routers/trainer.py` + `services/trainer_sessions.py` (Redis `trainer:session:*`, TTL-bound, multi-replica safe) run the sandbox:

1. **Session entry** — `POST /trainer/upload` (transient parse, never written to `invoice`) or `POST /trainer/sessions/from-invoice` (Feature 18: opens one already-processed invoice on its stored extraction and `sa_alerts`, no OCR re-run). The former `sessions/global` and `sessions/from-production` routes return **410 Gone** — free-text Global rule creation was retired; Global template rows and every read of them remain.
2. **Corrections** — `corrections/{tolerance,confidence-threshold,alert-override,missed-alert}` and `sessions/{id}/chat` refine constraints; `sessions/{id}/preview` replays the candidate rule over historical invoices (`services/rule_impact.py`) before anything is persisted.
3. **Commit** — `sessions/{id}/commit` writes `extraction_templates` + a new `extraction_template_versions` row, enqueues `reaudit_templates` (re-runs `COMPLETED`/`AUDIT_REQUIRED` invoices for that vendor or all vendors) and invalidates the chat answer cache. `templates/history` and `templates/{id}/rollback/{version}` give history/rollback.
4. **Chat-side corrections (Feature 18)** — `/chat/rules/{categories,preview,commit}` + `GET/DELETE /chat/rules` manage `tenant_chat_rules`, injected into SAGE prompts (§7.3). The tracker marks Feature 18 "CANCELLED 2026-08-20" but the code above is live and imported — code wins here.

**LLM**: role `primary` via `utils/llm.get_llm()`.

### 7.5 Evaluation, Guardrails & Observability (Features 20 / 23)

Earlier revisions of this section described LangSmith tracing and the Ragas package; neither is wired into the codebase. What is live:

#### A. Telemetry (`telemetry.py` → Application Insights)
Custom events `llm_agent_call` (every LLM call, with role/deployment/tokens/cost from the registry), `chat_turn`, `agent_eval_summary`, `extraction_benchmark_run`, `azure_cost_snapshot`, `online_eval_signal`, `ops_recommendation`; dependency spans via `track_dependency` (Gap 300); request instrumentation via `FastAPIInstrumentor` (Gap 292). FE RUM through `components/monitoring/AppInsightsProvider.tsx`.

#### B. Judges and workbooks
* `services/agent_eval.py` — LLM-as-judge over the golden bank (faithfulness / answer relevance / accuracy, ragas *definitions* judged directly, not the package), run nightly by `caj-benchmark-eval` alongside `scripts/run_extraction_benchmark.py`; `scripts/run_agent_eval.py --taxonomy` tags failures (`no_route, no_evidence, wrong_evidence, no_computation, narration, judge`, Feature 29 §29.3); `--calibration-set tests/golden_calibration.json` computes Cohen's κ for the judge (§29.2, Gap 479).
* `services/online_quality_judge.py` — judges real production turns when `ENABLE_PRODUCTION_QUALITY_JUDGE` is on (dev: on); alert `alert-production-judge-only.bicep` (Gap 450). `services/online_eval_signals.py` + `caj-online-signals` emit 6-hourly signals; `services/ops_recommendation.py` emits recommendations on the nightly run.
* Azure Workbooks (settled: never an in-app dashboard) — Cost + Health (27 items), AI Control Tower (51 items, sections A–H), Ops Summary — all flat/tab-less, deployed to `rg-invoice-llm-dev`; definitions in `infra/monitoring/*.json`, Bicep in `infra/workbook-*-only.bicep`. Spec: `apps/invoice-be/docs/feature_20_23_24_ops_workbook.md`.

#### C. Semantic Guardrails
* **Input Guard**: `_wrap_user_input()` fences user text; the SQL route only executes statements whose parse tree carries the caller's `tenant_id` predicate (Gap 414).
* **Output Guard**: every figure is computed in Python first and the answer-contract gate (§7.3) rejects prose that states a figure absent from the evidence; `redact_query_internals()` strips SQL/UUIDs from errors.

### 7.6 Model Layer — roles and registry (Gaps 465/466, Feature 29)

`utils/model_registry.py` defines `Role = primary | fast | judge | chat_summary | long_doc` and a `MODEL_CATALOG` keyed by deployment-name prefix (longest-prefix match; unknown names fall back to `DEFAULT_SPEC`, 128k context) carrying context window, usable input budget, tokenizer encoding and per-token prices for cost telemetry. `resolve_model(role)` reads the deployment for that role from `config.py`:

| Role | Setting | Default (`config.py`) | Dev (`params.dev.json`) | Prod params | Used by |
|---|---|---|---|---|---|
| `primary` | `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-5-mini` | `gpt-5.6-luna` (model version 2026-07-09) | `gpt-5-mini` | extraction, SQL generation, trainer, doc-type classifier |
| `fast` | `AZURE_OPENAI_FAST_DEPLOYMENT_NAME` | "" (= primary) | `gpt-5.6-luna` | — | `classify_query`, short narrations (A2) |
| `judge` | `AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME` | "" (= primary) | `gpt-5-mini` | — | `agent_eval`, `online_quality_judge` |
| `chat_summary` | `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME` | "" (= judge) | `gpt-5-mini` | "" | full-record narration (§29.5) |
| `long_doc` | `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME` | "" (inert) | "" | "" | reserved for §29.10; `gpt-5.6-terra` is the candidate, not measured |

`utils/llm.py` exposes `build_llm()`, `get_llm()`, `get_llm_for_role()`, `get_chat_summary_llm()`, `get_long_doc_llm()` over providers `azure` / `ollama` (`OLLAMA_MODEL`, local only) / `mock` (tests). Data-plane `AZURE_OPENAI_API_VERSION = "2024-10-21"` is one value threaded through `config.py`, both params files and `modules/compute/invoice-be.bicep`. Retired: `gpt-4o` / `gpt-4o-mini` as deployments (catalog rows kept only so historical events still price), `gpt-6-astra` and `gpt-5.6-sol` (deleted from dev 2026-09-06), api-version `2024-02-15-preview`, the Ollama eval container.

---

## 8. Database Design

### 8.1 The Tenant Rule

> **Every tenant-owned table MUST contain `tenant_id` (UUID)**, and every query is filtered by the caller's tenant. This is strictly enforced at the application layer (`dependencies.py`) and asserted on generated SQL (§7.3).

### 8.2 Schema

> Full field-level detail (types, constraints, indexes) lives in [Database_Schema_Document.md](./Database_Schema_Document.md); this is the summary view. Table names are the SQLModel defaults (lower-cased class names) unless a `__tablename__` is set; the DDL below is illustrative, the live schema is whatever Alembic head `e7f8a9b0c1d2` produces.

Table inventory (`models.py`, 2026-09-07):

| Area | Tables |
|---|---|
| Tenancy & auth | `tenant` (billing_plan, `receive_invoices_enabled`, `send_invoices_enabled`, `api_key_hash`, `api_key_scope`, `cancel_requested_at`), `users` (role + `can_train/can_audit/can_load/can_send_invoices`), `audit_logs` |
| Documents | `invoice` (both directions; `flow_direction`, `doc_type`, `doc_type_evidence`, `doc_attributes`, `duplicate_of_invoice_id`, `source_invoice_id`, `builder_intent`, `notes`, `deleted_at`, `completed_at`, `sent_at`, `paid_at`), `documents` (Feature 27 non-invoice documents, same shape minus money fields), `ingestion_batches` (Gap 464), `tenant_autopilot_configs`, `tenant_autopilot_logs` (`batch_id`, `trigger`, `hidden_at`) |
| Chat | `chatsession` (`focus`, `history_summary`), `chatmessage` (`status`, `job_id`, `error_message`, `attachment_payload`), `chat_attachments` (Feature 26: `doc_type`, `match_tier`, `chunk_count`, `expires_at`), `match_policies`, `document_comparisons`, `chat_feedback`, `tenant_chat_settings`, `tenant_chat_rules` (Feature 18) |
| Training | `extraction_templates`, `extraction_template_versions`, `auto_golden_cases` (Feature 23) |
| Integrations | `tenantconnection` (Google Drive OAuth), `tenant_email_senders`, `dropped_inbound_emails`, `webhook_subscriptions`, `webhook_delivery_logs` |
| Plug & Play (Feature 25) | `tenant_workflow_configs`, `sandbox_tenants`, `widget_tokens` |
| Ops | `agent_eval_run` (Feature 23 judge runs), `supportticket` (Feature 19) |

```sql
-- Tenants
CREATE TABLE tenant (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    VARCHAR NOT NULL,
    domain                  VARCHAR UNIQUE NOT NULL,   -- company email domain, used for SSO auto-provisioning
    billing_plan            VARCHAR NOT NULL DEFAULT 'free',
    free_invoices_remaining INTEGER NOT NULL DEFAULT 50,
    receive_invoices_enabled BOOLEAN NOT NULL DEFAULT TRUE,   -- AP (inbound)
    send_invoices_enabled    BOOLEAN NOT NULL DEFAULT FALSE,  -- AR (outbound), Feature 16
    api_key_hash            VARCHAR(255),                     -- PBKDF2-HMAC-SHA256 of the inv_live_ key
    api_key_scope           VARCHAR(20) NOT NULL DEFAULT 'readonly',  -- 'readonly' | 'actions' (Gap 335)
    cancel_requested_at     TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Users
CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID REFERENCES tenant(id),  -- nullable during onboarding/invite phase
    email          VARCHAR NOT NULL UNIQUE,
    first_name     VARCHAR,
    last_name      VARCHAR,
    role           VARCHAR NOT NULL,   -- assignable: 'Admin' | 'Auditor' | 'Trainer'; unrecognised/none → 'Restricted' (Gap 337; 'Viewer' retired)
    can_train      BOOLEAN, can_audit BOOLEAN, can_load BOOLEAN, can_send_invoices BOOLEAN,
    clerk_user_id  VARCHAR UNIQUE NOT NULL,       -- external Clerk identity
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login     TIMESTAMPTZ
);

-- Invoices (inbound AP and outbound AR share one table)
CREATE TABLE invoice (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenant(id),
    batch_id         UUID,               -- groups one ingestion run (SSE stream, ingestion_batches)
    file_path        VARCHAR NOT NULL,   -- Azure Blob URL (always a PDF after Feature 28)
    file_hash        VARCHAR(64),        -- SHA-256, Layer-1 duplicate detection
    duplicate_of_invoice_id UUID REFERENCES invoice(id),
    flow_direction   VARCHAR(20) NOT NULL DEFAULT 'INBOUND',   -- 'INBOUND' | 'OUTBOUND'
    doc_type         VARCHAR(32),        -- Feature 27 money-family type (INVOICE, PROFORMA_INVOICE, CREDIT_NOTE, DEBIT_NOTE)
    doc_type_evidence TEXT,
    doc_attributes   JSONB,              -- direction/party attributes derived from the document text
    invoice_number   VARCHAR,
    vendor_name      VARCHAR,            -- AP counterparty
    customer_name    VARCHAR,            -- AR counterparty (Feature 2.1)
    invoice_date     DATE,
    due_date         DATE,
    tax_amount       DECIMAL(12, 2),
    grand_total      DECIMAL(12, 2),
    po_number        VARCHAR,
    tags             JSONB,
    items            JSONB,              -- extracted line items
    coordinates      JSONB,              -- per-field bounding boxes for the auditor PDF overlay
    field_confidence JSONB,              -- per-field OCR confidence
    sa_alerts        JSONB,              -- active alert objects
    notes            TEXT,               -- Gap 467
    source_invoice_id UUID REFERENCES invoice(id),  -- Feature 17: clone origin
    builder_intent   JSONB,                          -- Feature 17: what the builder intended to print
    status           VARCHAR NOT NULL DEFAULT 'PROCESSING',   -- see §8.4
    completed_at     TIMESTAMPTZ, sent_at TIMESTAMPTZ, paid_at TIMESTAMPTZ,
    deleted_at       TIMESTAMPTZ,        -- soft delete
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Non-invoice documents (Feature 27) — separate table so the 39 tenant-scoped Invoice
-- query sites never need a doc_type predicate; page chunks live in Chroma docs_{tenant}
CREATE TABLE documents (
    id UUID PRIMARY KEY, tenant_id UUID NOT NULL, batch_id UUID, file_path VARCHAR NOT NULL, file_hash VARCHAR(64),
    doc_type VARCHAR(32), doc_type_evidence TEXT, doc_type_confidence FLOAT, doc_attributes JSONB,
    notes TEXT, status VARCHAR, completed_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL
);

-- Audit Logs
CREATE TABLE audit_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id),
    invoice_id     UUID NOT NULL REFERENCES invoice(id),
    actor_user_id  UUID NOT NULL REFERENCES users(id),
    actor_role     VARCHAR NOT NULL,
    action         VARCHAR NOT NULL,   -- e.g. 'RESOLVE_INVOICE'
    details        JSONB,              -- action-specific context
    timestamp      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Extraction Templates (Trainer output) + versions for history/rollback
CREATE TABLE extraction_templates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    vendor_name VARCHAR,               -- NULL = Global template
    flow_direction VARCHAR,            -- Feature 7.1 outbound standing rules
    rules       JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chat Sessions / Messages
CREATE TABLE chatsession (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    user_id     UUID NOT NULL REFERENCES users(id),
    title       VARCHAR(255) NOT NULL DEFAULT 'New Chat',
    focus       JSONB,                 -- current focus snapshot (Feature 6.1)
    history_summary TEXT,              -- condensed older turns
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE chatmessage (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID NOT NULL REFERENCES chatsession(id),
    role           VARCHAR NOT NULL,   -- 'user' | 'assistant'
    content        TEXT NOT NULL,
    generated_sql  TEXT,
    citations      JSONB,
    status         VARCHAR, job_id VARCHAR, error_message TEXT,   -- async chat job (Gap 280)
    attachment_payload JSONB,                                      -- Feature 26 confirmation/reconciliation payload
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chat attachments (Feature 26)
CREATE TABLE chat_attachments (
    id UUID PRIMARY KEY, tenant_id UUID NOT NULL, session_id UUID NOT NULL, file_path VARCHAR NOT NULL,
    doc_type VARCHAR(32) NOT NULL DEFAULT 'OTHER', extracted JSONB, match_tier INTEGER, match_summary JSONB,
    chunk_count INTEGER, indexed_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL
);

-- Tenant Connections (third-party OAuth credentials)
CREATE TABLE tenantconnection (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                UUID NOT NULL REFERENCES tenant(id),
    provider                 VARCHAR NOT NULL,   -- 'google_drive' ('salesforce' removed 2026-08-28, Gap 334)
    encrypted_access_token   TEXT NOT NULL,
    encrypted_refresh_token  TEXT,
    token_expiry             TIMESTAMPTZ NOT NULL,
    status                   VARCHAR NOT NULL DEFAULT 'active',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ingestion runs (Gap 464) — one row per run from the manual / email / connector doors;
-- Autopilot runs are merged in from tenant_autopilot_logs at read time
CREATE TABLE ingestion_batches (
    batch_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, trigger VARCHAR NOT NULL, flow_direction VARCHAR NOT NULL,
    file_count INTEGER NOT NULL, started_at TIMESTAMPTZ NOT NULL, archived_at TIMESTAMPTZ
);
```

The earlier `chat_qa_shortcuts` table described in this section was never created; the answer cache is Redis-only (§7.3).

### 8.3 Denormalization & JSONB Strategy
The platform uses JSONB selectively — for data that's always read as a unit with its parent row — while keeping relational structure where records need independent querying or FK integrity:
* **Denormalized (JSONB)**: invoice line items (`items`), bounding-box coordinates (`coordinates`), field confidence (`field_confidence`), anomaly alerts (`sa_alerts`), document attributes (`doc_attributes`) and the builder's intent (`builder_intent`) all live inline on the `invoice` row — fetching an invoice never requires a join for these.
* **Normalized (relational)**: chat threads are two tables (`chatsession` + `chatmessage`), not an embedded array, since messages need independent pagination and per-message metadata (`generated_sql`, `citations`, `attachment_payload`); attachments and their comparisons are their own tables so a session can hold several and each can expire independently.
* **Separate table rather than a discriminator** for `documents`: adding a `doc_type` predicate to every tenant-scoped `Invoice` query site was judged riskier than a second table with the same tenant rule.
* **Indexed Queries**: PostgreSQL handles JSONB indexing natively; composite indexes `(tenant_id, flow_direction)`, `(tenant_id, source_invoice_id)`, `(tenant_id, doc_type)` back the dashboards.

### 8.4 Invoice Status State Machine

```
INBOUND (AP)                                    OUTBOUND (AR)
  upload ──▶ DUPLICATE (Layer-1 hash hit)         UPLOADED
     │                                               │  (worker: PROCESSING_OCR → EXTRACTING_DATA)
  PROCESSING                                         ├──────────────┐
     │  (SSE: PROCESSING_OCR → EXTRACTING_DATA       ▼              ▼
     │        → INDEXING)                         VERIFIED     NEEDS_REVIEW ──▶ (outbound audit) ──▶ VERIFIED
     ├──────────────┬──────────┐                     │
     ▼              ▼          ▼                     ▼  confirm-send
  COMPLETED   AUDIT_REQUIRED  FAILED               SENT ──▶ PAID (mark-paid)
     │              │                                 └──▶ OVERDUE is computed at read time
     ├──────┐       ├──────┐                               (SENT + due_date < today), never stored
     ▼      ▼       ▼      ▼
   PAID  REJECTED  PAID  REJECTED
```

Non-invoice documents (Feature 27) never enter this machine: a known non-money `doc_type` is persisted to `documents` with its own `status`/`completed_at`, and the provisional `invoice` row is removed.

---

## 9. Embedding & Vectorization

### 9.1 Ingestion & Chunking Specification
The RAG pipeline handles document loading and vectorization as follows (`chroma_client.py`):
* **Loader**: PyMuPDF (`fitz`) opens the stored PDF page by page (`page.get_text()`); Azure Document Intelligence output is used for extraction, not for chunking.
* **Chunking Strategy**: **one chunk per page**, prefixed with a structured header `[Vendor: <vendor> | Document ID: <id> | Page <n>]` so every chunk carries its own provenance. There is no recursive token-window splitter and no overlap.
* **Vector Transformation**: chunks are embedded locally with `sentence-transformers` running `BAAI/bge-m3` (`EMBEDDING_MODEL_NAME`), a 1024-dimensional representation per chunk; `scripts/reembed_chroma_collections.py` re-embeds after a model change.
* **Indexing functions**: `index_invoice_document()` (invoices, ids `{invoice_id}_page_{n}`), `index_document_chunks()` (Feature 27 documents), `services/chat_document_search.index_attachment_chunks()` (Feature 26 attachments). Only rows whose status passes `should_index_status()` are indexed.

### 9.2 Collections, Retrieval & Distance Calculations
* **Vector Store**: ChromaDB (`ca-chromadb-{env}` container app), **one collection per tenant and per corpus**: `invoice_chunks_{tenant_id}` (RAG over invoices), `docs_{tenant_id}` (Feature 27 non-invoice documents), `chat_docs_{tenant_id}` (Feature 26 attachment pages); plus the tenant-less `support_knowledge_topics` used by the support agent's vector fallback (Gap 403). Per-tenant collections are the isolation boundary — there is no shared collection filtered by metadata.
* **Semantic Search & Thresholds**: matches are retrieved by cosine distance; chunks beyond **`RELEVANCE_DISTANCE_THRESHOLD = 0.49`** (empirically re-derived 2026-08-17 in Gap 244 — was `0.4`) are discarded.
* **Top K selection**: `query_invoice_chunks(limit=5)` per query; `search_attachment_chunks` for attachments.
* **Lifecycle**: `delete_invoice_chunks`, `delete_document_chunks` (called by `DELETE /documents/{id}` soft-delete, Feature 27 R6), `delete_attachment_chunks` (TTL sweeper), `delete_tenant_document_collection`.

### 9.3 Metadata Injection Rule
Every invoice chunk stored in ChromaDB **must** include the following metadata:

```json
{
  "tenant_id": "uuid-value",
  "invoice_id": "uuid-value",
  "vendor_name": "Vendor Co.",
  "page": 1
}
```

Document chunks (`docs_{tenant}`) carry `document_id` and `doc_type` and deliberately **no** `invoice_id`; attachment chunks carry `attachment_id`. `tenant_id` is redundant with the per-tenant collection name but is kept on every chunk as a second line of defence.

---

## 10. API Inventory & Contracts

### 10.1 Backend API Definitions

All routers mount under `/api/v1` except `/auth` (`main.py`). App-level: `GET /`, `/health`, `/health/liveness`, `/health/readiness`. Authentication is a Clerk JWT **or** a platform API key (§11.4) unless marked public.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/auth/me` | Current JWT-derived tenant/user context (`TenantContext`) |
| `POST` | `/auth/provision` | Website sign-up → tenant + Admin user |
| `POST` | `/auth/logout` | Session logout |
| `POST` | `/api/v1/invoices/upload` | Accept PDF/image file(s) + tags, Feature 28 normalisation, SHA-256 dedup, enqueue → `{ batch_id, job_ids[] }` |
| `POST` | `/api/v1/invoices/watcher/start` | Directory watcher for automated ingestion |
| `GET`  | `/api/v1/invoices/status/{job_id}` | Polling endpoint for one invoice |
| `GET`  | `/api/v1/invoices/stream/{batch_id}` | **SSE** stream for a batch (`text/event-stream`) |
| `GET`  | `/api/v1/invoices`, `/{invoice_id}`, `/{invoice_id}/pdf` | Paginated list with filters; single record; inline PDF |
| `GET` / `DELETE` | `/api/v1/invoices/batches`, `/batches/{batch_id}` | Batch summaries; delete a batch |
| `DELETE` | `/api/v1/invoices/{invoice_id}` | Soft delete (`deleted_at`) |
| `PUT`  | `/api/v1/audit/resolve/{invoice_id}` | Set `PAID`/`REJECTED`, dismiss alerts, field corrections → `audit_logs`; may return `suggested_rule` (Gap 27); API keys need `actions` scope |
| `GET`  | `/api/v1/dashboard/metrics`, `/trainer-impact`, `/insights` · `POST /insights/dismiss` | AP metrics, EVOLVE impact, insight cards |
| `GET`  | `/api/v1/documents`, `/{document_id}` · `DELETE /{document_id}` | Feature 27 non-invoice documents; delete = soft-delete + Chroma chunk removal |
| `GET`  | `/api/v1/ingestion-history`, `/{run_id}/files` · `POST /archive-all`, `/{run_id}/archive`, `/{run_id}/unarchive` | Gap 464 run log across manual/email/connector/autopilot doors |
| `GET`  | `/api/v1/config/features` | Read-only `ENABLE_*` flags for the FE |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/v1/chat/sessions`, `/sessions/{id}` | Session list/create/rename/delete; `GET /sessions/{id}` = message history |
| `POST` | `/api/v1/chat/sessions/{session_id}/message` | Enqueue a SAGE turn → `{ job_id }` (async default; sync fallback) |
| `GET`  | `/api/v1/chat/jobs/{job_id}/status`, `/jobs/{job_id}/stream` | Job status; SSE progress + final answer |
| `POST` | `/api/v1/chat/sessions/{session_id}/attachments` · `POST /chat/attachments/{id}/confirm-matches` · `GET /chat/attachments/{id}` | Feature 26 upload (worker extracts/matches), confirm candidate invoices, read state |
| `PUT`/`DELETE` | `/api/v1/chat/messages/{id}/feedback` · `POST /messages/{id}/triage`, `/triage/source-verdict` | Thumbs feedback and triage (Feature 23 auto-golden cases) |
| `GET`/`POST`/`DELETE` | `/api/v1/chat/rules`, `/rules/categories`, `/rules/preview`, `/rules/commit`, `/rules/{rule_id}` | Feature 18 chat-correction rules (`tenant_chat_rules`) |
| `GET`  | `/api/v1/connectors/status`, `/auth-url/{provider}`, `/callback/{provider}`, `/files/{provider}` · `POST /import/{provider}` · `DELETE /{provider}` | Google Drive only (Salesforce removed, Gap 334) |
| `GET`/`PUT` | `/api/v1/autopilot/config` · `POST /sync` · `GET /history`, `/history/{batch_id}/files`, `/history/legacy/files` · `DELETE /history`, `/history/{batch_id}` | Feature 13 scheduled Drive sync; hide runs (Gap 429) |
| `GET`  | `/api/v1/email/settings/mailbox` · `GET`/`POST`/`DELETE` `/email/settings/email-senders[/{id}]` · `POST /email/mailintegration` | Feature 14; `mailintegration` is the shared-secret SendGrid relay target (public, fail-closed) |
| `POST` | `/api/v1/trainer/upload`, `/sessions/from-invoice` · `GET /sessions/{id}/pdf`, `/alert-types`, `/vendors`, `/chat-style` · `POST /sessions/{id}/{chat,preview,commit,commit-behavior}`, `/sessions/{id}/corrections/{tolerance,confidence-threshold,alert-override,missed-alert}` · `PUT /sessions/{id}/mode` · `GET /templates/history` · `POST /templates/{id}/rollback/{version}` | EVOLVE sandbox (§7.4). `/sessions/global` and `/sessions/from-production` return **410 Gone** |
| `GET`/`PUT` | `/api/v1/settings/vendor-flow` | Feature 16 `receive_invoices_enabled` / `send_invoices_enabled` (Admin) |
| `GET`  | `/api/v1/settings/security/api-key`, `/api-key/verify` · `POST /api-key/rotate` | Feature 25 `inv_live_` key status/identity/rotation |
| `GET`/`POST`/`DELETE` | `/api/v1/settings/security/widget-tokens[/{token_id}]` | Feature 25 embeddable chat widget tokens |
| `GET`/`PUT` | `/api/v1/settings/workflow` | Feature 25 workflow policy (`tenant_workflow_configs`: full_automation ↔ `api_key_scope=actions`, strict_review ↔ `readonly`; CSV/JSON export, email summary, Drive archive) |
| `POST` | `/api/v1/outbound-invoices/upload` · `PUT /{id}/confirm-send`, `/{id}/mark-paid` | Feature 2.1 AR ingestion (`UPLOADED → VERIFIED/NEEDS_REVIEW → SENT → PAID`) |
| `GET`  | `/api/v1/outbound-invoices/{id}/build-defaults` · `POST /build/preview`, `/build` | Feature 17 Invoice Builder — clone-and-edit, structured re-render (`services/invoice_builder.py`, `services/pdf_render.py`) |
| `PUT`  | `/api/v1/outbound-audit/resolve/{invoice_id}` | Feature 7.1 pre-send validation + outbound standing rule |
| `GET`  | `/api/v1/outbound-dashboard/metrics`, `/invoices` | Feature 8.1 AR metrics and list |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/v1/webhooks`, `/{webhook_id}` · `GET /{webhook_id}/deliveries` | Feature 15 HMAC-signed subscriptions; events `invoice.completed`, `invoice.audit_required`, `invoice.approved`, `invoice.rejected`, `outbound_invoice.sent`, `outbound_invoice.overdue`, `outbound_invoice.approved` (schemas in `routers/webhook_docs.py`) |
| `POST` | `/api/v1/billing/create-checkout-session` | PayU hash-signed form fields |
| `POST` | `/api/v1/billing/payu/success`, `/payu/failure` | `surl`/`furl` callbacks (relayed by the website) — hash + `verify_payment` cross-check, update `tenant.billing_plan` |
| `GET`  | `/api/v1/billing/usage` · `POST /cancel`, `/reactivate` | Plan usage, cancellation lifecycle (`services/billing_lifecycle.py`) |
| `GET`/`PUT`/`DELETE` | `/api/v1/admin/users`, `/users/{user_ref}/permissions`, `/users/{user_ref}` · `GET /admin/dropped-emails` | Feature 1.1 tenant administration (Admin) |
| `POST` | `/api/v1/support/contact` | **Public.** Website contact form → `supportticket` (`INQ-…`), staff alert + receipt; Redis rate limit 5 / 5 min per IP and per email (Gap 249) |
| `POST` | `/api/v1/support/ticket` · `GET /support/tickets` | Authenticated ticket (`TICK-…`, `HELP_CHATBOT` or `DIRECT_TICKET`); tenant's last 50 tickets |
| `POST` | `/api/v1/support/chat` | Support Assistant turn — `agents/support_agent.py` is a deterministic keyword matcher over a curated knowledge base with a Chroma `support_knowledge_topics` vector fallback for zero-hit queries (Gap 403); **no LLM call** (recorded deviation, Feature 19) |
| `POST` | `/api/v1/sandbox/keys` · `GET /sandbox/keys/me` · `POST /sandbox/claim` | Feature 25 public `inv_test_` sandbox tenant issuance/claim — gated by `SANDBOX_KEYS_ENABLED` (False) |
| `POST` | `/api/v1/widget/chat/message` | Feature 25 embeddable widget turn, `inv_widget_` token + origin allow-list (`WidgetCORSMiddleware`) |

---

## 11. Authentication & Multi-Tenancy

### 11.1 Auth Flow

```
User lands on Website → Click "Login" / "Start Free Trial"
       │
       ▼
Clerk (email/password or SSO) — apps/invoice-website/app/{login,signup,forgot-password}
       │
       ▼
Sign-up: website /api/auth/provision → BE POST /auth/provision
       │
       ├── Existing tenant (org) → user joins with the Clerk org role → JWT
       │
       └── New organisation
               │
               ├── Create new Tenant record
               ├── Assign user as "Admin"
               └── Issue JWT with new tenant_id
       │
       ▼
Redirect to the app (custom domain invoicellm.admsofttech.com on dev via Front Door, Gap 185)
```

### 11.2 Tenant Enforcement (Backend)

The **FastAPI dependency** `dependencies.get_tenant_context` (and `get_tenant_context_allow_unpaid`) resolves `tenant_id` on every request — from the Clerk JWT (`verify_clerk_jwt`, JWKS cached) or from a platform API key (§11.4). **Every database query** is filtered by this tenant_id; generated chat SQL is additionally checked on its parse tree (§7.3). This is non-negotiable.

### 11.3 User Roles (Feature 1.1, Gap 337)

`models.RoleMapper` maps Clerk org roles onto three assignable roles plus a fallback; per-user permission columns (`can_train`, `can_audit`, `can_load`, `can_send_invoices`) can be adjusted by an Admin (`PUT /admin/users/{ref}/permissions`).

| Role       | Permissions                                           |
|------------|-------------------------------------------------------|
| **Admin**  | Full access, user management, billing, settings        |
| **Auditor**| Review, approve/reject invoices, view audit logs       |
| **Trainer**| Trainer sandbox and rule commits (`can_train`)        |
| **Restricted** | Not assignable — the fallback for an unrecognised or missing role; zero permissions. Replaces the retired **Viewer** name (data migration `e9f0a1b2c3d4`) |

### 11.4 Programmatic Access (Feature 25, Gaps 335/358/359)

* **`inv_live_…` tenant API key** — one per tenant, only its PBKDF2-HMAC-SHA256 digest is stored (`tenant.api_key_hash`); rotated from Settings → Security. Sent as `X-API-Key: <key>` or `Authorization: Bearer <key>` (`dependencies._extract_api_key`, X-API-Key wins). `tenant.api_key_scope` decides what it may do: `readonly` (read + upload) or `actions` (approve/reject/verify/send/mark-paid — enforced by `require_actions_scope` on the mutating routes). Requests run as a per-tenant service user (`resolve_api_key_service_user`) so audit logs show "a machine, via key …".
* **`inv_test_…` sandbox key** — a throw-away sandbox tenant issued from the website (`sandbox_tenants`, swept when expired and unclaimed); off unless `SANDBOX_KEYS_ENABLED`.
* **`inv_widget_…` widget token** — origin-bound token for the embeddable chat widget (`widget_tokens`, `services/widget_tokens.py`), accepted only by `/widget/chat/message`.

The FE's Next.js proxy exempts `/api/(.*)` from Clerk so external key holders can use the same public URLs (FE Gap 358).

---

## 12. Payment & Billing Integration

| Aspect              | Implementation                                                 |
|---------------------|----------------------------------------------------------------|
| **Provider**        | PayU (hash-based hosted checkout, classic integration)          |
| **Card/UPI Storage**| None — fully offloaded to PayU's hosted payment page             |
| **Confirmation**    | `POST /api/v1/billing/payu/success`\|`/failure` (`surl`/`furl`) — response hash + `verify_payment` server-to-server cross-check acts as source of truth for payments |
| **Plans**           | Free Trial (50 invoices), Pro Standard (₹4,999/mo), Pro Combined (₹8,999/mo) |
| **Billing Toggle**  | Monthly vs Yearly on pricing page                              |
| **Renewal model**   | Manual monthly re-payment (MVP) — PayU's classic API is one-time-payment, not native recurring; see §6.4 note |
| **Callback relay**  | PayU posts to the public website (`apps/invoice-website/app/api/v1/billing/payu/{success,failure}/route.ts`), which relays to the internal backend; the browser lands on `/billing/{success,failed}` |
| **Lifecycle**       | `GET /billing/usage`, `POST /billing/cancel` (`tenant.cancel_requested_at`), `POST /billing/reactivate`; `services/billing_lifecycle.py` + `scripts/sweep_billing_lifecycle.py` (ACA job `caj-billing-lifecycle`, not yet deployed on dev); quota via `services/billing_quota.py` |
| **Env Variables**   | `PAYU_MERCHANT_KEY`, `PAYU_MERCHANT_SALT`, `PAYU_MODE` (`test`/`live`) |

---

## 13. Development Workflow & Branching Strategy

### 13.1 IDE & Tooling

| Tool              | Detail                                                         |
|-------------------|----------------------------------------------------------------|
| **IDE**           | Cursor (VS Code compatible)                                     |
| **AI Model**      | Claude 3.5 Sonnet (shared across all developers)                |
| **Workspace**     | Entire mono-repo opened as a single workspace                   |

### 13.2 Branching Strategy

```
main          ← Production-ready code ONLY (manual merge approval required)
  │
  uat         ← Integration testing (User Acceptance Testing)
    │
    develop   ← Integration branch (all feature branches merge here first)
      │
      feature/* ← Individual work (e.g., feature/auditor-ui)
```

> **Rule**: Developers **never** commit directly to `main`. Merging to Production requires DevOps engineer sign-off after successful UAT.

> **As practised on 2026-09-07**: the repository's default branch is `master`; `deploy-dev.yml` deploys on every push to `master`/`develop` (path-filtered per service) and `deploy-prod.yml` on a `v*` tag or manual dispatch. There is no `uat` branch or environment yet, and branch protection / required PR review / CI test gates are deliberately deferred until the production cutover. Nothing is committed on the founder's behalf — every task ends uncommitted for review.

### 13.3 Developer Roles & Domain Ownership

| Role                 | Repository Folder          | Responsibility                                      |
|----------------------|----------------------------|-----------------------------------------------------|
| **Website Dev**      | `/apps/invoice-website`    | Marketing site, Pricing pages, SSO Auth integration  |
| **Frontend Dev**     | `/apps/invoice-fe`         | Dashboard, File Ingestion, Auditor Tab, Semantic Chat|
| **Backend Dev (x2)** | `/apps/invoice-be`         | Extraction agents, Queue workers, API contracts, Vector DB |
| **DevOps Engineer**  | `/bicep`, `/.github/workflows` | Bicep, CI/CD pipelines, WAF, Cloud Security |

---

## 14. Testing & Quality Assurance

| Phase                    | Responsibility                                                        |
|--------------------------|-----------------------------------------------------------------------|
| **Unit Testing**         | Each developer runs tests for their own modules before pushing a PR    |
| **Integration Testing**  | Verify new API endpoints against the existing system before merging to `develop` |
| **Peer Review**          | Every PR requires approval from at least one other developer           |
| **UAT Gate**             | DevOps engineer approves merge to `uat` → auto-deploys to UAT env     |
| **Production Gate**      | Only after successful UAT sign-off does DevOps merge to `main`        |

What actually runs today (2026-09-07): the backend suite (`apps/invoice-be/tests`, ~3,000 tests) is run locally against a real Postgres before any DB-touching change is claimed done; the CI/CD pipelines **never** run tests or benchmarks — the `benchmark-gate` job was removed from `deploy-dev.yml` (Gap 312) and quality checks live only in the nightly `caj-benchmark-eval` job (§4.6, §7.5). Extraction ground truth and benchmark runs live under `apps/invoice-be/docs/extraction_benchmark/` (Feature 13 test & benchmark suite); ad-hoc Playwright checks live in `apps/invoice-fe/e2e/`.

---

## 15. Operational & Licensing Costs

| Item               | Cost                         |
|--------------------|------------------------------|
| **Cursor License** | $20 USD (~₹1,680) / month per developer |
| **Team Total**     | $100 USD (~₹8,400) / month (5 developers) |

> Additional Azure infrastructure costs (compute, storage, AI services) are documented separately in the Cloud Architecture Document.

---

## 16. Glossary

| Term                     | Definition                                                                      |
|--------------------------|---------------------------------------------------------------------------------|
| **Tenant**               | An isolated customer organization within the SaaS platform                       |
| **RAG**                  | Retrieval Augmented Generation — combining vector search with LLM inference      |
| **VNet**                 | Azure Virtual Network — private network boundary for cloud resources             |
| **ChromaDB**             | Open-source vector database for embedding storage and similarity search          |
| **Shadcn/UI**            | Copy-paste UI component library built on Radix primitives                        |
| **TanStack Query**       | Data-fetching and caching library for React (formerly React Query)               |
| **IaC**                  | Infrastructure as Code — provisioning cloud resources via version-controlled code |
| **UAT**                  | User Acceptance Testing — pre-production validation environment                  |
| **NOVA / SENTINEL / SAGE / EVOLVE** | Product names for the extraction graph, the verification + auditor layer, the chat agent, and the trainer respectively |
| **doc_type**             | One of the 14 Feature 27 document types assigned before extraction; the money family (INVOICE, PROFORMA_INVOICE, CREDIT_NOTE, DEBIT_NOTE) lands in `invoice`, everything else in `documents` |
| **Door**                 | Any intake path that creates ingestion work: manual upload, watcher, connector import, Autopilot, email-in, API key, outbound upload, Trainer upload |
| **Role (model)**         | `primary` / `fast` / `judge` / `chat_summary` / `long_doc` in `utils/model_registry.py` — a purpose, resolved to an Azure OpenAI deployment per environment |
| **Plug & Play**          | Feature 25 — tenant API keys with a workflow policy, sandbox tenants, widget tokens and output destinations |
| **Gap N**                | A numbered defect/decision entry in the per-app feature trackers; every code change is tied to one |

---

## 17. Service Flow (Outbound) — Live

**Status: built 2026-07-29 (Features 2.1 / 6.1 / 7.1 / 8.1 / 16 on the backend, 2.1 / 3.1 / 4.1 / 10 on the frontend), refactored 2026-08-21 (Gap 283).** Full detail lives in the feature docs listed below; this section is the architecture-level summary.

### 17.1 What it is
The bidirectional counterpart to §7-9 above. Inbound (AP) handles invoices coming *into* the tenant from vendors; Service Flow adds the outbound (AR) side: the tenant uploads their own pre-made invoice PDFs addressed to their customers, verified through the same pipeline before being marked sent and tracked to payment. Upload-only for the original release; Feature 17 (Invoice Builder, §10) has since added **clone-and-edit** of an existing outbound invoice with a structured re-render — the FE screen `/invoices/outbound-builder` landed 2026-09-05 and the Azure-path verification is still outstanding (tracker `[~]`).

### 17.2 Design principle: new files, one narrow exception
Every outbound capability was built as new routers/handlers/components (`routers/outbound_invoices.py`, `outbound_audit.py`, `outbound_dashboard.py`, `settings.py`, `queue_worker/outbound_handlers.py`), importing existing pure logic rather than editing it. The one deliberate exception was `agents/query_agent.py`, which gained the direction-aware SQL schema and combined/net question support so Chat remains one screen.

### 17.3 Data model (additive columns only)
- `invoice`: `flow_direction` (`INBOUND`/`OUTBOUND`, default `INBOUND`), `customer_name`, `sent_at`, `paid_at`; later `source_invoice_id` + `builder_intent` (Feature 17).
- `extraction_templates`: `flow_direction`, enabling a Global-only "standing rule" for the tenant's one consistent outbound document format.
- `tenant`: `receive_invoices_enabled`, `send_invoices_enabled` (Admin-only toggles, `GET/PUT /settings/vendor-flow`).

### 17.4 Extraction: one graph, parameterised by direction (Gap 283)
The original design called for a separate, simpler outbound graph. It was built, then removed on 2026-08-21 because it silently missed every inbound improvement (classify/dynamic-QA, the retry loop, faithfulness checks). Today `agents/outbound_extraction_agent.py::run_outbound_extraction_agent` is a thin wrapper over the single compiled graph in `extraction_agent.py`; everything outbound-specific — schema (`OutboundInvoiceExtractionSchema`), prompts, required fields and the `VERIFIED`/`NEEDS_REVIEW` status vocabulary — lives in that file's `_DIRECTION_PROFILES["OUTBOUND"]` entry. `queue_worker/outbound_handlers.py::handle_process_outbound_invoice` applies the tenant's outbound Global standing rules and indexes both `VERIFIED` and `NEEDS_REVIEW` invoices for chat (Gap 243).

### 17.5 Screen-level behavior
Visibility of every outbound surface follows the two Settings toggles, never showing an empty half for a single-service tenant:
- **Ingestion, Auditor**: tab pattern (one side visible at a time) — action screens.
- **Dashboard**: split-screen (both halves visible simultaneously) when both services are active. No combined/net figure is rendered here.
- **Chat**: single screen, no visibility gating — an inactive direction just has no data to answer from.
- **Trainer**: unaffected — outbound's "standing rule" is set from the outbound Auditor, not a Trainer sandbox scope.

### 17.6 Full spec index
| Screen/Concern | Backend spec | Frontend spec |
|---|---|---|
| Ingestion (Send Invoices) | `docs/feature_2.1_vendor_flow_ingestion.md` | `docs/feature_3.1_vendor_flow_ingestion.md` |
| Auditor (pre-send validation + standing rules) | `docs/feature_7.1_vendor_flow_auditor.md` | `docs/feature_4.1_vendor_flow_auditor.md` |
| Dashboard (split-screen) | `docs/feature_8.1_vendor_flow_dashboard.md` | `docs/feature_2.1_vendor_flow_dashboard.md` |
| Chat (direction-aware) | `docs/feature_6.1_vendor_flow_chat.md` | — (UI is the existing Chat screen) |
| Settings | `docs/feature_16_settings.md` | `docs/feature_10_settings.md` |
| Invoice Builder (clone & edit) | `docs/feature_17_invoice_builder.md` — PARTIAL | `docs/feature_20_*` (FE), `/invoices/outbound-builder` |
| Overdue sweep + webhooks | `docs/feature_15_webhooks.md` (`outbound_invoice.*` events, `scripts/sweep_outbound_overdue.py`) | — |
| Pricing | `apps/invoice-website/website_features/feature_3.1_vendor_flow_pricing.md` — Pro Combined ₹8,999/mo is the live tier for both directions | — |
