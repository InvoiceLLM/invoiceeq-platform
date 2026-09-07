# Invoice AI SaaS Platform

> Production-Grade, Multi-Tenant AI Invoice Processing System on Azure

*Last reconciled against the codebase: 2026-09-07. Build status for every feature lives in the three trackers linked under [What the product does](#what-the-product-does) — this file is the map, not the status board.*

## Overview

Invoice AI is an enterprise SaaS platform that automates invoice processing using LLM-powered agents. It reads the invoices a company receives from its vendors (accounts payable) and the invoices it sends to its own customers (accounts receivable), extracts and verifies the data, routes discrepancies to an audit queue, learns vendor-specific corrections, and answers questions about the whole ledger in a conversational chat — all with strict multi-tenant data isolation.

The four named AI agents you will see across the code, the UI and the marketing site: **NOVA** (extraction), **SENTINEL** (risk detection / audit), **SAGE** (chat), **EVOLVE** (trainer / continuous learning).

## Repository Structure (Mono-Repo)

```
Prod_Invoice_LLM/
│
├── apps/
│   ├── invoice-website/        # Public marketing site, pricing + PayU checkout, Clerk login/signup, Contact Us (Next.js)
│   │   └── website_features/   # Feature specs + tracker (app-specific docs)
│   ├── invoice-fe/             # The signed-in app: Dashboard, Ingest, Audit Queue, History, AI Trainer, Chat, Settings, Help, Admin (Next.js)
│   │   ├── e2e/                # Ad hoc Playwright verification scripts (not run in CI)
│   │   └── docs/               # Feature specs + tracker (app-specific docs)
│   └── invoice-be/             # FastAPI API, Azure Storage Queue worker, AI agents (Python)
│       ├── agents/             # NOVA extraction graph, SAGE query agent, trainer agent, support agent
│       ├── services/           # Domain services (billing, webhooks, autopilot sync, document comparison, invoice builder, ...)
│       ├── routers/            # One FastAPI router per API surface
│       ├── queue_worker/       # Background extraction worker (polls Azure Storage Queues)
│       ├── utils/              # LLM factory + model registry, verification tools
│       ├── scripts/            # Scheduled-job entry points, benchmark + eval harnesses
│       ├── benchmarks/         # Extraction and chat golden sets
│       ├── tests/              # Automated pytest suite (runs against real Postgres)
│       ├── alembic/            # DB migrations (live — migrations/ is not used)
│       └── docs/               # Feature specs + tracker (app-specific docs)
│
├── infra/                      # Infrastructure as Code (Azure Bicep, live IaC)
│   ├── 01-network … 10-budget  # Ten staged deployment templates, orchestrated by deploy-all.ps1
│   ├── modules/                # VNet, PostgreSQL, Redis, Storage, OpenAI, Front Door, Container Apps, Monitoring
│   ├── monitoring/             # Azure Workbook JSON (Cost + Health, AI Control Tower, Ops Summary)
│   └── *-only.bicep            # Standalone templates for scheduled jobs, alerts and workbooks
│
├── docker/                     # Dockerfiles for be / worker / fe / website (compose file stays at root)
├── scripts/                    # run-local.ps1 — starts everything locally in separate windows
├── reports/                    # Filed evidence from audits, load and security test runs
├── docs/                       # Repo-wide docs (not app-specific)
│   ├── architecture/           # Technical / Cloud / Database architecture docs + developer journey
│   ├── guides/                 # Local setup, secrets sync, workflow, user & admin journey, reading order
│   ├── test_cases/             # Manual QA test case references
│   ├── screenshots/            # UI reference screenshots
│   └── phase_2_enhancements.md # Forward-looking idea index (capture only, not scoped)
│
├── docker-compose.yml          # Local dev stack (Postgres/Redis/Chroma/Azurite)
└── README.md                   # ← You are here
```

Two things live one level *above* this folder, in the `Invoice_LLM/` workspace root, and are referenced from here:

- `.github/workflows/` — the GitHub Actions pipelines (`deploy-dev.yml`, `deploy-prod.yml`, `_deploy-service.yml`, `e2e-regression.yml`). They are not inside `Prod_Invoice_LLM/`.
- `.claude/` — the AI-agent persona system used to develop this repo (`CONVENTIONS.md`, `agents/*.md`, `skills/*`), plus the doc- and code-dependency-graph scripts described in the workspace `CLAUDE.md`.

## Tech Stack

| Layer            | Technology                                     |
|------------------|------------------------------------------------|
| **Backend**      | FastAPI, Python 3.12, SQLModel/SQLAlchemy, Pydantic settings |
| **Agent runtime**| LangGraph (extraction graph and the SAGE query agent) |
| **Frontend**     | Next.js (App Router), TypeScript, Tailwind CSS, Lucide icons |
| **Website**      | Next.js, Tailwind CSS, PayU hosted checkout      |
| **Database**     | PostgreSQL (Azure Flexible Server), Alembic migrations |
| **Vector DB**    | ChromaDB (per-tenant collections for invoice chunks, chat attachments and non-invoice documents) |
| **Queues / cache** | Azure Storage Queues (extraction jobs + dead-letter queue); Redis (chat job queue, SSE pub/sub, answer cache, trainer sessions) |
| **AI/LLM**       | Azure OpenAI via a role-based model registry (`apps/invoice-be/utils/model_registry.py`): `gpt-5.6-luna` for primary extraction/chat and fast calls, `gpt-5-mini` for judge and chat-summary roles; API version `2024-10-21`. Embeddings: Hugging Face `BAAI/bge-m3` (local, sentence-transformers) |
| **OCR**          | Azure Document Intelligence (`prebuilt-invoice`); images (PNG/JPG/TIFF/WEBP/BMP) are converted to PDF at every intake door |
| **Auth**         | Clerk (organisations, email/password with OTP second factor, password reset) |
| **Email**        | SendGrid — Inbound Parse for the receive mailbox, Mail Send for staff notifications and support tickets |
| **Payments**     | PayU (hosted checkout redirect; Free / Pro / Pro Combined plans) |
| **Cloud**        | Microsoft Azure — Container Apps (be, worker, fe, website, ChromaDB), VNet, Blob + Queue storage, Key Vault, Front Door + WAF on the custom domain `invoicellm.admsofttech.com` |
| **Ops**          | Application Insights custom events, Azure Workbooks (Cost + Health, AI Control Tower, Ops Summary), alert rules, nightly benchmark/eval Container App jobs |
| **IaC**          | Azure Bicep only (staged `01`–`10` templates + `*-only.bicep` add-ons) |
| **CI/CD**        | GitHub Actions — build + deploy only; pipelines never run tests or benchmarks |

## What the product does

Headline features per app. Status here is a snapshot as of 2026-09-07; the trackers are the single source of truth and win if they disagree with this list.

**Backend — `apps/invoice-be`** ([tracker](./apps/invoice-be/docs/be_features_tracker.md))

- Live: multi-tenant Clerk auth and granular RBAC; NOVA extraction pipeline (classify document type → classify complexity → extract → verify, with retry) for inbound *and* outbound invoices; real-time status over SSE; two-layer duplicate detection; SENTINEL audit resolution (inbound and outbound) with Review Later / Needs Resubmission deferrals; dashboard and outbound-dashboard metrics with dismissable insights; SAGE conversational chat (SQL route, RAG route, full-record route, answer cache, direction-aware); chat attached documents (upload a PO/quotation PDF, match it to invoices, deterministic field-by-field comparison); generic document extraction (14 document types — non-invoices are stored separately and never enter the payables queue); EVOLVE trainer with alert-anchored rules; Google Drive connector + Tenant Autopilot scheduled sync with run history; email-in ingestion through a platform mailbox with per-tenant authorised sender sets; HMAC-signed outbound webhooks (7 event types); settings (service-flow toggles, API keys, widget tokens, workflow policy); PayU billing with a lifecycle sweep; support tickets + AI support agent; observability events feeding the Azure Workbooks; durable Ingestion History across every intake door.
- Partial / in progress: Invoice Builder (clone-and-edit an outbound invoice, server-rendered PDF) — built, Azure-path verification not yet run; image → PDF at the boundary — built, Azure-path verification not yet run; Plug & Play workflows — backend complete, sandbox keys behind a flag that defaults off; AI Control Tower nightly eval — live, judge calibration still failing its own gate; LLM optimisation (Feature 29) — in progress.

**Frontend — `apps/invoice-fe`** ([tracker](./apps/invoice-fe/docs/fe_features_tracker.md))

- Live screens: Dashboard (inbound, outbound, or split view; Insights and Trainer Impact tabs), Ingest (drag-and-drop upload incl. images, Send Invoices tab, Autopilot tab with sync history), Audit Queue with the inbound and outbound review consoles, History, AI Trainer, Chat with attachments and the SQL audit drawer, Settings (Service Flow, Email, Connectors, Webhooks, Security/API keys, Workflows wizard, Subscriptions), Help Center (guides, AI support assistant, My Tickets), Admin Console.
- Partial: Invoice Builder screen (code-complete, end-to-end run pending), image upload accept, Plug & Play setup wizard. Planned, not started: desktop app (PWA approach; the earlier Tauri attempt was removed).

**Website — `apps/invoice-website`** ([tracker](./apps/invoice-website/website_features/website_features_tracker.md))

- Live: landing page and agent showcase, pricing table + PayU checkout and result pages, Clerk login / signup / forgot-password (OTP with countdown and resend, password show/hide), tenant provisioning, Contact Us, privacy and terms, custom domain through Front Door + WAF, the inbound-mail relay to the backend.
- Partial: Plug & Play marketing surface and sandbox-key onboarding.

### Roles

Three assignable roles — **Admin**, **Auditor**, **Trainer** — plus four per-user permission flags an Admin can grant from the Admin Console: Trainer, Auditor, Loader (can upload), Send Invoices. The old **Viewer** role was retired on 2026-08-28; the system's zero-permission fallback is now an internal value (`Restricted`) that is never offered in any role picker. A user who resolves to it sees only Dashboard, Chat and Help.

### Removed — do not look for these

- Salesforce connector (removed 2026-08-28; Google Drive is the only connector). A few `SALESFORCE_*` parameters still linger in Bicep and are inert.
- Tauri desktop build and its `build-desktop.yml` workflow (removed; a PWA approach is planned instead).
- SAGE tool-calling orchestrator, Feature 21 (deleted 2026-08-25 after a live head-to-head; two helper modules survive as chat dependencies).
- Ops Digest agent, Feature 24 (deleted 2026-08-25; the flat Azure Workbooks replaced it).
- `gpt-4o` / `gpt-4o-mini` deployments and the preview API version `2024-02-15-preview` (replaced by the registry above and `2024-10-21`).
- Local Ollama eval container (removed 2026-09-01).

## Getting Started

The full, ordered walkthrough is [docs/guides/local_uv_setup.md](./docs/guides/local_uv_setup.md). The condensed version follows; if the two ever disagree, the guide wins.

### Prerequisites
- Node.js 20+ (Website, Frontend)
- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (Backend — the backend is managed with `uv`, not `pip`)
- Docker (local Postgres / Redis / Chroma / Azurite)
- Azure CLI (only for infrastructure work)
- Git

### Development Setup

**1. Clone**
```bash
git clone <repo-url>
cd Prod_Invoice_LLM
```

**2. Create env files from the committed templates**

Each app ships a template with working local defaults already filled in. Copy
each one, then paste in the shared `CLERK_SECRET_KEY` — the only value that is
not committed. Ask the repo owner for it.

```bash
# Windows
copy apps\invoice-be\.env.example apps\invoice-be\.env
copy apps\invoice-fe\.env.local.example apps\invoice-fe\.env.local
copy apps\invoice-website\.env.local.example apps\invoice-website\.env.local

# macOS / Linux
cp apps/invoice-be/.env.example apps/invoice-be/.env
cp apps/invoice-fe/.env.local.example apps/invoice-fe/.env.local
cp apps/invoice-website/.env.local.example apps/invoice-website/.env.local
```

Then set `CLERK_SECRET_KEY` in all three files. The Clerk **publishable** key is
already in the templates — it is public by design and safe in git.

**Skipping this step is the most common setup failure.** `.env` and `.env.local`
are gitignored, so a fresh clone has no Clerk keys and both frontends crash on
load with `@clerk/nextjs: Missing publishableKey`.

**3. Start local infrastructure**
```bash
docker compose up -d          # Postgres, Redis, Chroma, Azurite
```

**4. Install the backend and apply database migrations**
```bash
cd apps/invoice-be
uv venv && uv sync
uv run alembic upgrade head
```

**5. Start the four processes (separate terminals)**

Ports matter — the apps reference each other by origin, and the committed
defaults assume this exact assignment. `scripts/run-local.ps1` opens all four
in their own PowerShell windows if you would rather not do it by hand.

| Process           | Port   | Command (from the app directory)                       |
|-------------------|--------|--------------------------------------------------------|
| `invoice-be` API  | `8000` | `uv run uvicorn main:app --reload --port 8000`         |
| queue worker      | —      | `uv run python -m queue_worker.main_worker` (uploads sit in `UPLOADED` forever without it) |
| `invoice-website` | `3000` | `npm install && npm run dev -- --port 3000`            |
| `invoice-fe`      | `3001` | `npm install && npm run dev -- --port 3001`            |

Open http://localhost:3000 for the marketing site and sign-up flow; after
login you are redirected to the app on http://localhost:3001.

Backend tests run against a real Postgres, never SQLite — what is actually
covered, and how it was verified, is recorded per app in
`apps/*/docs/test_coverage_map.md`.

### Troubleshooting

| Symptom | Cause |
|---------|-------|
| `@clerk/nextjs: Missing publishableKey` | `.env.local` was not created — repeat step 2 |
| `The publishableKey passed to Clerk is invalid` | Key is present but malformed; re-copy it from the template |
| Backend exits on startup | `CLERK_SECRET_KEY` or `TOKEN_ENCRYPTION_KEY` empty in `apps/invoice-be/.env` |
| Every API call returns 401 with "Invalid issuer" | `CLERK_JWT_ISSUER` has a trailing slash — it must not |
| API calls return 500 "CLERK_JWKS_URL is not configured" | `CLERK_JWKS_URL` missing from `apps/invoice-be/.env` |
| Every API call returns 401 with no token sent | `ALLOW_MOCK_AUTH` isn't set in `apps/invoice-be/.env` — it now defaults `false`; local dev needs `ALLOW_MOCK_AUTH=true` (already in the `.env.example` template) |
| CORS error in the browser console | Frontend is on a port not listed in `ALLOWED_ORIGINS` |

## Branching and Deployment

```
master        ← default branch; every push auto-deploys the changed services to the Azure dev environment
develop       ← also auto-deploys to dev when pushed
feature/*, fix/*, recover/*  ← individual work, merged into master
v* tags       ← a version tag (or a manual dispatch) deploys to the prod environment
```

`deploy-dev.yml` is path-filtered per service (be, worker, fe, website) and hands off to the reusable `_deploy-service.yml` for build → push → deploy. No test or benchmark step runs in any pipeline by design; quality checks live in the nightly `caj-benchmark-eval` Container App job. There is no `uat` branch. Branch protection and required reviews are deliberately not enabled yet (speed over rigor until prod cutover). The prod parameter file is still a placeholder; only the dev environment (`rg-invoice-llm-dev`) is deployed.

## Team Roles

| Role              | Directory                  | Focus                                         |
|-------------------|----------------------------|-----------------------------------------------|
| Website Dev       | `/apps/invoice-website`    | Marketing, pricing + PayU, Clerk auth pages, Contact Us, mail relay |
| Frontend Dev      | `/apps/invoice-fe`         | Dashboard, Ingest + History, Audit consoles, Chat, Trainer, Settings, Help, Admin |
| Backend Dev (x2)  | `/apps/invoice-be`         | AI agents, APIs, queue worker, Chroma/RAG, billing, webhooks, eval harnesses |
| DevOps Engineer   | `/infra`, workspace `.github/` | Bicep stages, Container Apps + jobs, Front Door, Workbooks/alerts, CI/CD |

## Documentation

Start with [docs/guides/DOCUMENTATION_READING_GUIDE.md](./docs/guides/DOCUMENTATION_READING_GUIDE.md) — the reading order for everything below.

- [Technical Architecture Document](./docs/architecture/Technical_Architecture_Document.md)
- [Cloud Architecture Document](./docs/architecture/Cloud_Architecture_Document.md)
- [Database Schema Document](./docs/architecture/Database_Schema_Document.md)
- [System Journey — Developer Guide](./docs/architecture/System_Journey_Developer_Guide.md) (module-by-module walk of an invoice through the code)
- [System Journey — User & Admin Guide](./docs/guides/System_Journey_User_Admin_Guide.md) (plain-language, per screen and role)
- Feature trackers — the status source of truth: [backend](./apps/invoice-be/docs/be_features_tracker.md), [frontend](./apps/invoice-fe/docs/fe_features_tracker.md), [website](./apps/invoice-website/website_features/website_features_tracker.md)
- [Phase 2 enhancement ideas](./docs/phase_2_enhancements.md) (capture only — nothing there is scoped or started)
- Infra: [infra/README.md](./infra/README.md), [infra/NEW_ENVIRONMENT.md](./infra/NEW_ENVIRONMENT.md), [infra/THIRD_PARTY_INTEGRATIONS_SETUP.md](./infra/THIRD_PARTY_INTEGRATIONS_SETUP.md)

## License

Proprietary — Internal Use Only
