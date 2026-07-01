# Invoice AI — Azure Bicep Infrastructure Guide

This guide describes how the infrastructure-as-code (IaC) files work and explains the contents of each Bicep file in plain English.

---

## 1. How the Infrastructure Works

Azure Bicep is a declarative language used to provision Azure resources. Instead of writing long commands or clicking in the Portal, we specify our desired final state.

### Orchestration & Dependencies
We use a **modular** layout:
* `main.bicep` is the master orchestrator. It calls all other modules.
* Bicep automatically calculates dependencies: if Module B needs an output from Module A (e.g., VNet subnet ID), Bicep ensures Module A is built first.
* All resources are placed behind **Private Endpoints** so that they are inaccessible from the public internet. Communication occurs entirely within the virtual network.

---

## 2. File-by-File Breakdown

### 2.1 Orchestration & Parameters

#### `infra/main.bicep`
* **What it does**: This is the root orchestrator. It imports and coordinates the execution of all modular sub-components.
* **How it works**:
  1. Declares global parameters (e.g., resource prefix, environment name, API keys).
  2. Provisions the **Managed Identity** (to act as the system security profile).
  3. Creates the **Virtual Network** and subnets.
  4. Deploys **Key Vault** and seeds the initial credentials.
  5. Provisions data stores (**PostgreSQL**, **Redis**, **Storage**) and AI services (**OpenAI**, **Doc Intelligence**) inside the VNet.
  6. Deploys the **Container Apps Environment** and launches **ChromaDB**, **Backend API**, **Celery Worker**, and **Frontend UI** containers.
  7. Sets up **RBAC Assignments** (permissions) allowing the containers to securely communicate.

#### `infra/params.dev.json`
* **What it does**: Contains parameter values specific to the **Development** environment.
* **How it works**: Feeds inputs (such as region, naming prefix, mock API keys, and database logins) directly to `main.bicep` during deployment.

---

### 2.2 Core Modules

#### `infra/modules/security/managed-identities.bicep`
* **What it does**: Generates a **User-Assigned Managed Identity**.
* **How it works**: Creates a digital security profile in Azure. The backend and frontend containers assume this identity to log into SQL, Storage, and OpenAI passwordless.

#### `infra/modules/network/vnet.bicep`
* **What it does**: Establishes the private virtual network (VNet) and routing.
* **How it works**:
  * Carves out an address space of `10.0.0.0/16`.
  * Creates three subnets: `snet-aca` (for containers), `snet-pe` (for databases/caches), and `snet-ai` (for OpenAI/OCR).
  * Creates Private DNS Zones (e.g. `privatelink.postgres.database.azure.com`) to allow internal hostnames to resolve to private network IPs.

#### `infra/modules/security/keyvault.bicep`
* **What it does**: Provisions an **Azure Key Vault** to store application secrets.
* **How it works**:
  * Creates a secure vault with RBAC enabled.
  * Writes static secrets passed from parameters (`DATABASE-PASSWORD`, `CLERK-SECRET-KEY`, `TOKEN-ENCRYPTION-KEY`, etc.).
  * Grants Key Vault reading permissions to our Managed Identity.

---

### 2.3 Data Modules

#### `infra/modules/data/postgresql.bicep`
* **What it does**: Deploys an **Azure Database for PostgreSQL (Flexible Server)**.
* **How it works**:
  * Sets up a single database server using a cost-efficient, burstable SKU (`Standard_B2s`).
  * Attaches it directly to the VNet data subnet.
  * Provisions a default database called `invoice_db`.

#### `infra/modules/data/redis.bicep`
* **What it does**: Deploys an **Azure Cache for Redis** instance.
* **How it works**:
  * Configures a standard cache broker (SKU Standard C1) to handle Celery background worker queues and real-time streaming notifications (SSE).
  * Deploys a Private Endpoint to lock it within the VNet.

#### `infra/modules/data/storage.bicep`
* **What it does**: Deploys an **Azure Storage Account** for invoice PDFs.
* **How it works**:
  * Provisions a Standard LRS storage container.
  * Disables all public internet access.
  * Creates a private folder called `/invoices` to capture uploads.
  * Attaches a Private Endpoint so containers can push and pull files securely.

#### `infra/modules/data/chromadb.bicep`
* **What it does**: Runs **ChromaDB** (our vector database).
* **How it works**:
  * Deploys the official `chromadb/chroma:latest` image inside the Container Apps Environment.
  * Exposes port `8000` *internally only* so it cannot be accessed outside the VNet.

---

### 2.4 AI Modules

#### `infra/modules/ai/openai.bicep`
* **What it does**: Deploys **Azure OpenAI** service.
* **How it works**:
  * Instantiates the cognitive account inside the AI subnet.
  * Configures a model deployment for `gpt-4o-mini` with a capacity rate limit of 20k tokens-per-minute (TPM) for local testing.

#### `infra/modules/ai/doc-intelligence.bicep`
* **What it does**: Deploys **Azure AI Document Intelligence** (OCR).
* **How it works**:
  * Registers a FormRecognizer cognitive account with a Private Endpoint.
  * Exposes the endpoint key dynamically so workers can parse and scan receipts.

---

### 2.5 Compute Modules

#### `infra/modules/compute/container-env.bicep`
* **What it does**: Creates the host runtime cluster environment (Azure Container Apps Environment).
* **How it works**: Integrates with the VNet subnet `snet-aca` to host and run our microservices under a managed serverless architecture.

#### `infra/modules/compute/invoice-be.bicep`
* **What it does**: Deploys the FastAPI backend API container.
* **How it works**:
  * Runs on 1 CPU / 2Gi RAM.
  * Sets up internal ingress on port `8000` (accessible to the frontend, but not public).
  * Declares secret bindings linking Key Vault secrets directly to runtime environment variables (e.g. `DATABASE_URL` matches Key Vault secret values).

#### `infra/modules/compute/celery-worker.bicep`
* **What it does**: Deploys the Celery background worker container.
* **How it works**:
  * Runs on 1 CPU / 2Gi RAM.
  * Sets ingress to `null` (it has no open ports; it only listens to Redis).
  * Executes the command `celery -A workers.tasks worker --loglevel=info` to process incoming OCR and embeddings tasks.

#### `infra/modules/compute/invoice-fe.bicep`
* **What it does**: Deploys the Next.js Frontend Dashboard container.
* **How it works**:
  * Runs on 0.5 CPU / 1Gi RAM.
  * Enables **public ingress** on port `3000` so developer/auditor users can open the app in a web browser.
  * Injects public parameters like `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`.

---

### 2.6 Security Integrations

#### `infra/modules/security/rbac-assignments.bicep`
* **What it does**: Configures Azure Role-Based Access Control (RBAC).
* **How it works**:
  * Binds role policies to the Managed Identity principal ID.
  * Grants **Storage Blob Data Contributor** on the storage account.
  * Grants **Cognitive Services User** on the Azure OpenAI and Document Intelligence accounts.
