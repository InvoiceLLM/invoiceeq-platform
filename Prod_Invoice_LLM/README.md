# Invoice AI SaaS Platform

> Production-Grade, Multi-Tenant AI Invoice Processing System on Azure

## Overview

Invoice AI is an enterprise SaaS platform that automates invoice processing using LLM-powered agents. It provides automated data extraction, verification, audit workflows, and semantic search — all with strict multi-tenant data isolation.

## Repository Structure (Mono-Repo)

```
Prod_Invoice_LLM/
│
├── apps/
│   ├── invoice-website/        # Marketing site, Pricing, SSO Auth (Next.js)
│   │   └── website_features/   # Feature specs + tracker (app-specific docs)
│   ├── invoice-fe/             # Dashboard, Auditor Tab, Semantic Chat (Next.js)
│   │   ├── tests/manual/       # Ad hoc Playwright verification scripts (not CI)
│   │   └── docs/               # Feature specs + tracker (app-specific docs)
│   └── invoice-be/             # FastAPI API, Queue Workers, AI Agents (Python)
│       ├── tests/              # Automated pytest suite
│       ├── alembic/            # DB migrations (live — migrations/ is not used)
│       └── docs/               # Feature specs + tracker (app-specific docs)
│
├── infra/                      # Infrastructure as Code (Azure Bicep, live IaC)
│   └── modules/                # VNet, PostgreSQL, Storage, AI, Security, Monitoring
│
├── docker/                     # Dockerfiles for all services (compose file stays at root)
├── scripts/                    # One-off dev/ops scripts (run-local.ps1, queue debug scripts)
├── .github/workflows/          # CI/CD Pipeline configurations (GitHub Actions)
├── docs/                       # Repo-wide docs (not app-specific)
│   ├── architecture/           # Technical/Cloud/Database architecture docs + diagrams
│   ├── guides/                 # Setup, secrets-sync, workflow, onboarding guides
│   ├── test_cases/             # Manual QA test case references
│   └── screenshots/            # UI reference screenshots
│
├── docker-compose.yml          # Local dev stack (Postgres/Redis/Chroma/Azurite)
└── README.md                   # ← You are here
```

## Tech Stack

| Layer            | Technology                                     |
|------------------|------------------------------------------------|
| **Backend**      | FastAPI, Python, Azure Storage Queues, SQLAlchemy |
| **Frontend**     | Next.js, TypeScript, Shadcn/UI, Tailwind CSS   |
| **Website**      | Next.js, Tailwind CSS, PayU Checkout            |
| **Database**     | PostgreSQL (Azure Flexible Server)              |
| **Vector DB**    | ChromaDB                                        |
| **Task Queue**   | Redis (caching) + Azure Storage Queues (background jobs) |
| **AI/LLM**      | Azure OpenAI (GPT-4) + Hugging Face `BAAI/bge-m3` (Local) |
| **OCR**          | Azure Document Intelligence                     |
| **Auth**         | Clerk / Auth0 (Google + Microsoft SSO)          |
| **Payments**     | PayU (hosted checkout redirect)                  |
| **Cloud**        | Microsoft Azure (Container Apps, VNet, Blob)    |
| **IaC**          | Azure Bicep / Terraform                         |
| **CI/CD**        | GitHub Actions                                  |

## Getting Started

### Prerequisites
- Node.js 20+ (Website, Frontend)
- Python 3.12+ (Backend)
- Docker (Containerization)
- Azure CLI (Infrastructure)
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

**4. Apply database migrations**
```bash
cd apps/invoice-be
alembic upgrade head
```

**5. Start the three apps (separate terminals)**

Ports matter — the apps reference each other by origin, and the committed
defaults assume this exact assignment.

| App               | Port   | Command                                        |
|-------------------|--------|------------------------------------------------|
| `invoice-be`      | `8000` | `uv run uvicorn main:app --reload --port 8000` |
| `invoice-website` | `3000` | `npm install && npm run dev -- --port 3000`     |
| `invoice-fe`      | `3001` | `npm install && npm run dev -- --port 3001`     |

Open http://localhost:3000 for the marketing site and sign-up flow.

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

## Branching Strategy

```
main          ← Production (manual approval required)
  └── uat     ← User Acceptance Testing (auto-deploy)
      └── develop   ← Integration branch
          └── feature/*  ← Individual developer work
```

## Team Roles

| Role              | Directory                  | Focus                                         |
|-------------------|----------------------------|-----------------------------------------------|
| Website Dev       | `/apps/invoice-website`    | Marketing, Pricing, SSO                       |
| Frontend Dev      | `/apps/invoice-fe`         | Dashboard, Audit, Chat UI                     |
| Backend Dev (x2)  | `/apps/invoice-be`         | AI Agents, APIs, Workers, Vector DB           |
| DevOps Engineer   | `/infra`, `/.github`       | IaC, CI/CD, Security, Monitoring              |

## Documentation

- [Technical Architecture Document](./docs/architecture/Technical_Architecture_Document.md)
- [Cloud Architecture Document](./docs/architecture/Cloud_Architecture_Document.md)

## License

Proprietary — Internal Use Only
