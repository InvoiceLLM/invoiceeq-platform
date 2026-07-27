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
| **Website**      | Next.js, Tailwind CSS, Stripe Checkout          |
| **Database**     | PostgreSQL (Azure Flexible Server)              |
| **Vector DB**    | ChromaDB                                        |
| **Task Queue**   | Redis (caching) + Azure Storage Queues (background jobs) |
| **AI/LLM**      | Azure OpenAI (GPT-4) + Hugging Face `BAAI/bge-m3` (Local) |
| **OCR**          | Azure Document Intelligence                     |
| **Auth**         | Clerk / Auth0 (Google + Microsoft SSO)          |
| **Payments**     | Stripe Checkout                                 |
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
```bash
# Clone the repository
git clone <repo-url>
cd Prod_Invoice_LLM

# Start Backend
cd apps/invoice-be
uv sync
uv run uvicorn main:app --reload

# Start Frontend
cd apps/invoice-fe
npm install
npm run dev

# Start Website
cd apps/invoice-website
npm install
npm run dev
```

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
