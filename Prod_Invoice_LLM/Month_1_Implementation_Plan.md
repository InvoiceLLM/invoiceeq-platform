# Month 1 Implementation Plan (Days 1–20)

* **Goal**: Establish the local environment, define data models, provision secure Azure networks (VNet, Storage, Key Vault, ACR), set up automated CI/CD workflows, and deploy the first functional API (`POST /api/v1/invoices/upload`) to the cloud.

---

## Week 1: Project Scaffolding & Database Foundations
* **Goal**: Establish the local development environment, define schemas, and configure database versioning.

### Day 1: Project Scaffolding with `uv`
* **Prerequisite Study**: Read documentation on `uv` package manager, FastAPI lifespan context, and Pydantic Settings.
* **Daily Schedule (8 Hours)**:
  * **Hour 1–2**: Study prerequisites (FastAPI lifespan configuration and Pydantic validation rules).
  * **Hour 3**: Install the `uv` tool locally and initialize the workspace directory structure.
  * **Hour 4**: Initialize the package layout using `uv init --app` in `/apps/invoice-be`.
  * **Hour 5**: Populate `pyproject.toml` with dependencies and generate `uv.lock`.
  * **Hour 6**: Create `config.py` using Pydantic Settings to validate environment parameters.
  * **Hour 7**: Create `main.py` implementing the async lifespan managers.
  * **Hour 8**: Write test `/health` and `/` endpoints to verify ASGI router functionality.
* **Verification**: Run `uv run uvicorn main:app --reload` and confirm a `200 OK` response from `/health`.

### Day 2: Relational Schemas Design
* **Prerequisite Study**: Read about SQLModel database schemas, primary/foreign keys, and indexes in PostgreSQL.
* **Daily Schedule**:
  * **Hour 1–2**: Learn how SQLModel interfaces with SQLAlchemy and constructs metadata.
  * **Hour 3–5**: Write the `Tenant` and `User` database models inside `apps/invoice-be/models.py`.
  * **Hour 6–7**: Write `Vendor`, `Invoice`, and `InvoiceItem` tables with foreign key constraints.
  * **Hour 8**: Validate the syntax of the schema models using static type checkers (Mypy).
* **Verification**: Run `uv run python -c "from models import SQLModel"` to verify no syntax errors exist.

### Day 3: Alembic Migration Setup
* **Prerequisite Study**: Read Alembic configuration guides and table-alter schema mechanics.
* **Daily Schedule**:
  * **Hour 1–2**: Learn Alembic revision trees and autogenerate parameters.
  * **Hour 3–4**: Run `alembic init migrations` inside `/apps/invoice-be`.
  * **Hour 5–6**: Update `migrations/env.py` to import SQLModel metadata.
  * **Hour 7**: Generate the first migration: `uv run alembic revision --autogenerate -m "initial_schema"`.
  * **Hour 8**: Run `uv run alembic upgrade head` against a local SQLite database to confirm table generation.
* **Verification**: Connect to the local SQLite database and verify all tables exist with correct constraints.

### Day 4: Tenant Scope Middleware
* **Prerequisite Study**: Learn about FastAPI Dependency Injection, HTTP headers parsing, and scoping variables.
* **Daily Schedule**:
  * **Hour 1–2**: Study FastAPI dependency injection patterns and context scoping.
  * **Hour 3–5**: Write the JWT validation dependency inside `apps/invoice-be/dependencies.py`.
  * **Hour 6–7**: Write `get_tenant_context` to parse the `tenant_id` claim from JWT headers.
  * **Hour 8**: Attach this check to a test router endpoint to verify access restriction.
* **Verification**: Request the test endpoint without headers to assert it returns a `401 Unauthorized` response.

### Day 5: Week 1 Integration & Testing Gate
* **Prerequisite Study**: Learn pytest fixtures, mock assertions, and transaction rollbacks.
* **Daily Schedule**:
  * **Hour 1–2**: Study writing integration tests using pytest and AsyncClient.
  * **Hour 3–6**: Write pytest scripts inside `apps/invoice-be/tests/` verifying tenant isolation rules.
  * **Hour 7–8**: Fix failing tests, format files using Ruff, and commit code to `feature/base-setup`.
* **Verification**: Run `uv run pytest` and verify all tests pass.

---

## Week 2: Azure Cloud IaC & Network Architecture
* **Goal**: Write and test Bicep infrastructure files to build the secure Azure network topology.

### Day 6: Virtual Network (VNet) Configuration
* **Prerequisite Study**: Read Azure Virtual Network docs, CIDR subnet allocations, and NSG rules.
* **Daily Schedule**:
  * **Hour 1–2**: Learn Azure Bicep resource parameters.
  * **Hour 3–5**: Create `infra/modules/vnet.bicep` declaring the virtual network address space `10.0.0.0/16`.
  * **Hour 6–7**: Declare subnets: `snet-aca` (`10.0.1.0/24`), `snet-data` (`10.0.2.0/24`), and `snet-ai` (`10.0.3.0/24`).
  * **Hour 8**: Add Network Security Group (NSG) configurations.
* **Verification**: Validate the Bicep template syntax using `az bicep build --file infra/modules/vnet.bicep`.

### Day 7: Azure Blob Storage IaC
* **Prerequisite Study**: Read Azure Storage Accounts, Private Endpoints, and Blob container lifecycle policies.
* **Daily Schedule**:
  * **Hour 1–2**: Study private link configurations.
  * **Hour 3–5**: Create `infra/modules/storage.bicep` declaring the Storage Account resource.
  * **Hour 6–7**: Add private endpoints mapping to `snet-data` and link the Private DNS Zone.
  * **Hour 8**: Configure lifecycle policies to move older invoices to Cool storage.
* **Verification**: Verify that the storage Bicep compiles cleanly.

### Day 8: Manual Azure Container Registry (ACR) Portal Setup
* **Prerequisite Study**: Read Azure Container Registry docs and Admin User security considerations.
* **Daily Schedule**:
  * **Hour 1–2**: Learn about ACR security models.
  * **Hour 3–4**: Open `portal.azure.com`, navigate to **Container Registries**, and click **Create**.
  * **Hour 5**: Select Resource Group, name it `acrinvoiceai`, choose the Premium SKU (required for private endpoints), and disable "Admin User".
  * **Hour 6–7**: In the networking tab, link a Private Endpoint to your VNet.
  * **Hour 8**: Verify network configurations and record the ACR login server name.
* **Verification**: Run `az acr check-name -n acrinvoiceai` and confirm the configuration registry is active.

### Day 9: Azure Key Vault IaC
* **Prerequisite Study**: Read Azure Key Vault, secrets management, and Managed Identities RBAC models.
* **Daily Schedule**:
  * **Hour 1–2**: Study RBAC guidelines for Key Vault.
  * **Hour 3–5**: Create `infra/modules/keyvault.bicep` with access policies restricted to application managed identities.
  * **Hour 6–7**: Declare secret placeholders for database URLs and OpenAI API keys.
  * **Hour 8**: Link Key Vault to Private DNS Zones.
* **Verification**: Validate the Bicep templates compile without error.

### Day 10: Top-Level main.bicep & Environment Parity
* **Prerequisite Study**: Read about Bicep parameter files and multi-environment deploy practices.
* **Daily Schedule**:
  * **Hour 1–2**: Learn about Bicep modules orchestration.
  * **Hour 3–5**: Create the parent deployment orchestrator `infra/main.bicep` linking the VNet, storage, registry, and Key Vault.
  * **Hour 6–7**: Create environment parameter files: `params.dev.json` and `params.uat.json`.
  * **Hour 8**: Run dry-run deployments using `az deployment group validate`.
* **Verification**: Confirm that Bicep validation passes for both dev and uat environments.

---

## Week 3: CI/CD Pipeline & Initial ACA Deployment
* **Goal**: Configure GitHub Actions to automate image builds and deploy to Azure Container Apps.

### Day 11: GitHub Build & Test Workflow
* **Prerequisite Study**: Read GitHub Actions syntax, runner environments, and caching mechanisms.
* **Daily Schedule**:
  * **Hour 1–2**: Study workflow caching to speed up Docker builds.
  * **Hour 3–5**: Create `.github/workflows/build-test.yml` running tests on every pull request.
  * **Hour 6–7**: Configure Ruff linter and Pytest checks inside the runner.
  * **Hour 8**: Verify that testing triggers automatically on a test PR.
* **Verification**: Check the GitHub repository actions tab and confirm build steps execute.

### Day 12: Docker Containerization
* **Prerequisite Study**: Read multi-stage Docker builds, Alpine/Slim base images, and container security.
* **Daily Schedule**:
  * **Hour 1–2**: Study Python Docker performance optimization.
  * **Hour 3–5**: Create `docker/Dockerfile.be` utilizing a multi-stage `python:3.12-slim` setup.
  * **Hour 6–7**: Configure non-root users inside the container for security.
  * **Hour 8**: Run a local Docker build: `docker build -f docker/Dockerfile.be -t invoice-be:local .`.
* **Verification**: Run `docker run -p 8000:8000 invoice-be:local` and verify `/health` responds correctly.

### Day 13: GitHub Deployment Workflow
* **Prerequisite Study**: Read about OpenID Connect (OIDC) authentication between GitHub and Azure.
* **Daily Schedule**:
  * **Hour 1–2**: Learn OIDC setup steps.
  * **Hour 3–5**: Create `.github/workflows/deploy-uat.yml` triggered on merges to the `uat` branch.
  * **Hour 6–7**: Configure steps to authenticate with Azure using federated credentials and log in to ACR.
  * **Hour 8**: Set up steps to build and push tagged images.
* **Verification**: Commit a test change to `uat` and verify that the image builds and pushes to ACR successfully.

### Day 14: Azure Container Apps Deployment
* **Prerequisite Study**: Learn about Azure Container Apps, ingress configurations, and environment variables.
* **Daily Schedule**:
  * **Hour 1–2**: Study ACA scaling rules and Key Vault integrations.
  * **Hour 3–5**: Create `infra/modules/aca.bicep` declaring the container environment and backend app.
  * **Hour 6–7**: Add deployment steps to `.github/workflows/deploy-uat.yml` calling `az deployment group create`.
  * **Hour 8**: Trigger the pipeline and verify deployment logs.
* **Verification**: Access the public URL generated for the UAT Container App and verify it responds.

### Day 15: VNet Security Hardening
* **Prerequisite Study**: Read about private network ingress, NSG inbound flow logs, and Front Door configurations.
* **Daily Schedule**:
  * **Hour 1–2**: Study private ingress restrictions.
  * **Hour 3–5**: Re-configure the container app's ingress to "Internal" so it is only accessible inside the VNet.
  * **Hour 6–7**: Verify that public calls to the app URL are now blocked.
  * **Hour 8**: Configure a temporary VPN or jumpbox VM (`Bastion`) to verify internal network paths.
* **Verification**: Verify that the API is unreachable from the public internet but reachable within the VNet.

---

## Week 4: File Ingestion API & Azure Blob Storage Integration
* **Goal**: Code, test, and deploy the core `POST /api/v1/invoices/upload` API flow to Azure.

### Day 16: File Ingestion Router Skeletal Setup
* **Prerequisite Study**: Learn about FastAPI upload handlers (`UploadFile` and `File`), file parsing, and MIME types.
* **Daily Schedule**:
  * **Hour 1–2**: Learn upload streaming concepts in FastAPI.
  * **Hour 3–5**: Write the upload skeleton in `apps/invoice-be/routers/invoices.py`.
  * **Hour 6–7**: Define input size limits (maximum 10MB per file) and allowed formats (`application/pdf`).
  * **Hour 8**: Run local curl requests to test upload boundary validation.
* **Verification**: Confirm that trying to upload a `.txt` file returns a `400 Bad Request` validation code.

### Day 17: Azure Blob Storage SDK Integration
* **Prerequisite Study**: Read Azure Storage Blob client library documentation for Python.
* **Daily Schedule**:
  * **Hour 1–2**: Learn chunked uploads and client configuration parameters.
  * **Hour 3–5**: Write `apps/invoice-be/services/storage.py` establishing blob container connections using Managed Identity.
  * **Hour 6–7**: Write `upload_pdf_to_blob_storage(file_data, tenant_id)` storing files inside `invoices/{tenant_id}/{invoice_id}.pdf`.
  * **Hour 8**: Write unit tests mocking blob container responses.
* **Verification**: Run `uv run pytest tests/test_storage.py` and verify all mock operations pass.

### Day 18: Ingestion Database Integration
* **Prerequisite Study**: Read about SQLAlchemy Session transactions and autocommit parameters.
* **Daily Schedule**:
  * **Hour 1–2**: Study SQLAlchemy state commits.
  * **Hour 3–5**: Write logic inside `upload_invoice()` to insert a SQL row with status `PROCESSING`.
  * **Hour 6–7**: Link the storage upload function to execute inside the same router endpoint transaction.
  * **Hour 8**: Test local end-to-end upload saving metadata to the database and binary data to storage.
* **Verification**: Assert that uploading a valid PDF inserts a database record and creates a corresponding storage blob.

### Day 19: Local API Integration Testing
* **Prerequisite Study**: Read about writing integration tests using mocked cloud services (Moto, LocalStack, or mocked SDK clients).
* **Daily Schedule**:
  * **Hour 1–2**: Learn testing protocols for hybrid API paths.
  * **Hour 3–6**: Write integration tests in `tests/test_upload_flow.py` checking upload performance and database entry creation.
  * **Hour 7–8**: Execute code formatting checks and resolve any linter warnings.
* **Verification**: Confirm 100% of integration test suites pass locally.

### Day 20: UAT Branch Merge & Cloud Verification Gate
* **Prerequisite Study**: Read git branch merging guidelines and UAT environment verification checklists.
* **Daily Schedule**:
  * **Hour 1–2**: Review the code changes with a teammate.
  * **Hour 3–4**: Merge the `feature/upload-api` branch into `develop` and then into `uat`.
  * **Hour 5–6**: Observe the GitHub Actions pipeline build and deploy the container app.
  * **Hour 7–8**: Use the internal VNet jumpbox to send an upload call to the live UAT container app and verify success.
* **Verification**: Verify that the UAT Azure Blob storage container has received the uploaded test PDF.
