# MVP 12-Week High-Level Implementation Plan

This document serves as the high-level milestone roadmap for the **Invoice AI SaaS Platform**. For granular day-by-day developer assignments, daily prerequisite study topics, and hourly schedules, please refer to the monthly sub-documents:
* **[Month 1 Implementation Plan (Days 1–20)](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/Month_1_Implementation_Plan.md)**
* **[Month 2 Implementation Plan (Days 21–40)](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/Month_2_Implementation_Plan.md)**
* **[Month 3 Implementation Plan (Days 41–60)](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/Month_3_Implementation_Plan.md)**

---

## 1. Branching & Deployment Strategy

* **`feature/*` Branches**: Individual developer work. Merge validation requires passing unit tests.
* **`develop` Branch**: Main staging branch.
* **`uat` Branch**: Merging auto-deploys all container apps to the Azure UAT environment.
* **`main` Branch (Production)**: Requires manual DevOps approval. Merging applies migrations (`alembic upgrade head`) and deploys to the live production cluster.

---

## 2. High-Level Milestone Schedule

### Phase 1: Local Setup & Azure Infrastructure (Weeks 1–3)
* **Goal**: Define backend frameworks, write databases schemas, provision the private Azure network topology (VNet, Storage, Key Vault, ACR Portal Setup), and establish automated GitHub CD pipelines.
  * **Week 1 (Days 1–5)**: Scaffolding python packaging via `uv`, defining SQLModel database schemas, and setting up Alembic version migrations.
  * **Week 2 (Days 6–10)**: Developing Azure Bicep IaC files (subnets, storage link, Key Vaults) and setting up ACR in the Azure Portal.
  * **Week 3 (Days 11–15)**: Writing GitHub build and deploy actions, building Docker images, and deploying the initial backend container app.

### Phase 2: Core Ingestion, Status & OCR Processing (Weeks 4–6)
* **Goal**: Build file upload routers, configure background task execution queues, and integrate OCR document text extraction.
  * **Week 4 (Days 16–20)**: Coding the upload API (`POST /invoices/upload`) and integrating it with Azure Blob Storage.
  * **Week 5 (Days 21–25)**: Implementing index polling queries and real-time Server-Sent Events (SSE) status streams linked to Redis Pub/Sub channels.
  * **Week 6 (Days 26–30)**: Integrating Celery queues and calling the Azure Document Intelligence Prebuilt-Invoice OCR model.

### Phase 3: AI Agent Operations & Vector Storage (Weeks 7–9)
* **Goal**: Develop the multi-agent reasoning graphs (Extraction, Verification, and Trainer agents) and build local RAG query clients.
  * **Week 7 (Days 31–35)**: Building the multi-modal Extraction Agent graph using `gpt-4o` base64 page streams and Pydantic validation rules.
  * **Week 8 (Days 36–40)**: Implementing the Verification Agent calculations verification tools, Trainer Agent template feedback loops, and dashboard metrics APIs.
  * **Week 9 (Days 41–45)**: Loading local `BAAI/bge-m3` embedding calculations and implementing ChromaDB collections and RAG chat.

### Phase 4: UI Dashboards & Production Deployment (Weeks 10–12)
* **Goal**: Build React dashboards, configure user authorization and Stripe payments, run integration tests, and release to Production.
  * **Week 10 (Days 46–50)**: Building Next.js Frontend Dashboard pages, SSE progress bars, split-screen review layouts, and chat sidebars.
  * **Week 11 (Days 51–55)**: Setting up the Marketing Website, Clerk SSO logins, Stripe billing tables, and webhooks processing.
  * **Week 12 (Days 56–60)**: Writing Playwright integration tests, setting up Azure Web Application Firewall (WAF) rules, and deploying to the Production environment.
