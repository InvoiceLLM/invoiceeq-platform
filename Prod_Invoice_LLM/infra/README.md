# Multi-Stage Deployment Strategy

Dependency Resolution: To circumvent circular dependency locks (e.g. key vault needing database endpoints while databases need key vault roles/identities), the codebase features split orchestration templates:

* **Step 1 (main-step1.bicep)**: Core infrastructure (VNet, Identities, Databases, Storage, ACR).
* **Step 2 (main-step2.bicep)**: Cognitive AI resources (OpenAI, Document Intelligence) and key seeding.
* **Step 3 (main-step3.bicep)**: ACA environment setup and ChromaDB.
* **Step 4 (main-step4.bicep)**: App containers deployment and RBAC roles mapping.

This 4-stage process is executed automatically via the `deploy-all.ps1` script.
