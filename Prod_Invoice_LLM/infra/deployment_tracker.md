# Infrastructure Deployment Tracker

This file tracks the status of the Azure Bicep infrastructure deployment.

## Deployment Stages

- **[ ] Stage 1: Core Infrastructure** (`main-step1.bicep`)
  - Status: *Not Started*
  - Resources: VNet (`snet-aca`, `snet-pe`, `snet-ai`, `snet-postgres`), Managed Identity, Key Vault, PostgreSQL Flexible Server, Redis Enterprise (Managed Redis), Storage Account, ACR.
- **[ ] Stage 2: Cognitive AI Services** (`main-step2.bicep`)
  - Status: *Not Started*
  - Resources: Azure OpenAI, Document Intelligence (OCR), key seeding into Key Vault.
- **[ ] Stage 3: Container Environment & Vector DB** (`main-step3.bicep`)
  - Status: *Not Started*
  - Resources: Container Apps Environment (CAE), ChromaDB container (with Azure File Share mount).
- **[ ] Stage 4: App Container Services** (`main-step4.bicep`)
  - Status: *Not Started*
  - Resources: Backend API container, Celery Worker container, Frontend dashboard container, RBAC role assignments.

## Prerequisites Check

- [x] Azure CLI logged in (`sbanerji@admsofttech.com`)
- [ ] Validated credentials in `params.dev.json` (Clerk secret, publishable key, Fernet encryption key)
