# Month 2 Implementation Plan (Days 21–40)

* **Goal**: Implement real-time bulk notification streams using Redis Pub/Sub, configure Celery workers to parse OCR details, set up the multi-modal Extraction Agent (including logic/math verification), and Trainer Agent template learning logic.

---

## Week 5: Polling & SSE Streaming APIs (Flows 2 & 3)
* **Goal**: Build status retrieval APIs and establish Server-Sent Events (SSE) push streaming.

### Day 21: Status Polling Router Integration
* **Prerequisite Study**: Read about writing fast select queries in SQLAlchemy/SQLModel and optimizing index searches.
* **Daily Schedule (8 Hours)**:
  * **Hour 1–2**: Study database select optimizations.
  * **Hour 3–5**: Write the endpoint `GET /api/v1/invoices/status/{job_id}` in `routers/invoices.py`.
  * **Hour 6–7**: Apply tenant verification checks to prevent cross-tenant lookup leaks.
  * **Hour 8**: Write unit tests for the status polling endpoint.
* **Verification**: Verify that polling the endpoint for an active job ID returns `PROCESSING` status.

### Day 22: Redis Connection Setup
* **Prerequisite Study**: Read about Redis Pub/Sub architecture, connection pooling in Python, and connection timeouts.
* **Daily Schedule**:
  * **Hour 1–2**: Study Python redis-py library settings.
  * **Hour 3–5**: Create `apps/invoice-be/redis_client.py` configuring connection pools.
  * **Hour 6–7**: Write publish and subscribe helpers.
  * **Hour 8**: Test publishing and receiving messages locally on a Redis Docker instance.
* **Verification**: Verify local terminal logs show messages are published and received successfully.

### Day 23: SSE Streaming Router Construction
* **Prerequisite Study**: Read about Server-Sent Events (SSE) protocol, MIME types (`text/event-stream`), and async generators in Python.
* **Daily Schedule**:
  * **Hour 1–2**: Study the differences between WebSockets and SSE.
  * **Hour 3–5**: Implement `GET /api/v1/invoices/stream/{batch_id}` in `routers/invoices.py`.
  * **Hour 6–7**: Write an async generator subscribing to Redis Pub/Sub channels (`batch:{batch_id}`).
  * **Hour 8**: Test yielding structured SSE string chunks locally.
* **Verification**: Run a local HTTP request and verify that the output stream remains open and returns message blocks.

### Day 24: Redis Provisioning in Azure
* **Prerequisite Study**: Read Azure Cache for Redis documentation, access firewall configurations, and private endpoints.
* **Daily Schedule**:
  * **Hour 1–2**: Study Bicep templates for Redis.
  * **Hour 3–5**: Create `infra/modules/redis.bicep` declaring standard Redis SKU resources.
  * **Hour 6–7**: Link Private Endpoints mapping to `snet-data` and update Key Vault credentials.
  * **Hour 8**: Validate the updated main infra Bicep deployment templates.
* **Verification**: Validate Redis Bicep syntax using `az bicep build --file infra/modules/redis.bicep`.

### Day 25: SSE Stream Deployment & Integration Test
* **Prerequisite Study**: Read about connection lifetime parameters, Keep-Alive settings, and HTTP load balancer limitations.
* **Daily Schedule**:
  * **Hour 1–2**: Study SSE proxy configurations.
  * **Hour 3–5**: Merge code to `uat` and verify that the CI/CD pipeline deploys the Container App with Redis credentials.
  * **Hour 6–7**: Write an integration script sending a payload to the status endpoint and streaming events.
  * **Hour 8**: Run the verification script on the UAT network.
* **Verification**: Confirm that the SSE stream stays open and pushes database status logs correctly on UAT.

---

## Week 6: Background Workers & OCR Ingestion (Flow 4 - Part A)
* **Goal**: Build background worker tasks and integrate Azure Document Intelligence OCR.

### Day 26: Celery App Setup
* **Prerequisite Study**: Read about Celery task distribution, serialization formats (JSON), and worker concurrency limits.
* **Daily Schedule**:
  * **Hour 1–2**: Study configuring Celery with Redis backend.
  * **Hour 3–5**: Create `apps/invoice-be/workers/celery_app.py` configuring queues.
  * **Hour 6–7**: Write `process_invoice_task` placeholder inside `workers/tasks.py`.
  * **Hour 8**: Test launching Celery workers locally: `celery -A workers.tasks worker --loglevel=info`.
* **Verification**: Verify that the Celery logs register the tasks successfully on launch.

### Day 27: Document Intelligence SDK Integration
* **Prerequisite Study**: Read Azure AI Document Intelligence API, prebuilt model specifications, and layout coordinates format.
* **Daily Schedule**:
  * **Hour 1–2**: Study the Prebuilt-Invoice model structure.
  * **Hour 3–5**: Write a client helper script `apps/invoice-be/services/ocr.py`.
  * **Hour 6–7**: Implement the layout text extraction API call using Azure SDK.
  * **Hour 8**: Test extracting text structures from local sample invoices.
  * **Verification**: Confirm that Document Intelligence extracts line items and outputs clean text blocks.

### Day 28: Azure Document Intelligence Provisioning
* **Prerequisite Study**: Read Azure Cognitive Services, private subnets mapping, and Azure Key Vault access integrations.
* **Daily Schedule**:
  * **Hour 1–2**: Study Bicep templates for Cognitive Services.
  * **Hour 3–5**: Create `infra/modules/cognitive.bicep` declaring the AI resource.
  * **Hour 6–7**: Link Private Endpoints mapping to `snet-ai` and record secrets in Key Vault.
  * **Hour 8**: Update top-level deployment parameter configurations.
* **Verification**: Run Bicep validate checks to confirm Cognitive service configurations are correct.

### Day 29: OCR Worker Pipeline Stitching
* **Prerequisite Study**: Learn about PDF file streaming, base64 image parsing, and saving file records.
* **Daily Schedule**:
  * **Hour 1–2**: Study converting PDF pages to base64 images inside Python.
  * **Hour 3–5**: Update `process_invoice_task` in `workers/tasks.py` to download PDFs and fetch OCR coordinates.
  * **Hour 6–7**: Store extracted text files to the database as initial layout structures.
  * **Hour 8**: Test local task executions using sample PDFs.
* **Verification**: Run the task locally and confirm that the OCR text blocks are written to PostgreSQL.

### Day 30: Week 6 UAT Deployment & Testing Gate
* **Prerequisite Study**: Read pipeline deployment logs and Celery monitoring configurations (Flower).
* **Daily Schedule**:
  * **Hour 1–2**: Study Celery worker containerization rules.
  * **Hour 3–4**: Create the Celery container app configurations in `infra/modules/aca.bicep`.
  * **Hour 5–6**: Deploy the updated worker backend to UAT.
  * **Hour 7–8**: Trigger the ingestion API in UAT and confirm Celery worker logs show successful OCR parsing.
* **Verification**: Verify that UAT PostgreSQL records have the parsed layout text populated.

---

## Week 7: Extraction Agent Graph Development (Flow 4 - Part B)
* **Goal**: Build the multi-modal Extraction Agent graph using LangGraph.

### Day 31: LangGraph Setup & System Prompts
* **Prerequisite Study**: Read LangGraph state definitions, system prompts design, and JSON schema constraints.
* **Daily Schedule**:
  * **Hour 1–2**: Study defining schemas in Pydantic.
  * **Hour 3–5**: Define the `InvoiceSchema` Pydantic model inside `agents/extraction_agent.py`.
  * **Hour 6–7**: Write the core ExtractionAgent class and prompt instructions.
  * **Hour 8**: Verify system prompts locally using simple model configurations.
* **Verification**: Confirm that the Pydantic schema contains fields for vendor, tax, amount, line items, and currency.

### Day 32: Multi-Modal Base64 Input Processing
* **Prerequisite Study**: Read about gpt-4o multi-modal capabilities and sending JPEG payloads to OpenAI.
* **Daily Schedule**:
  * **Hour 1–2**: Study formatting image streams for API calls.
  * **Hour 3–5**: Write methods inside the Extraction Agent to pack base64 images alongside OCR texts.
  * **Hour 6–7**: Call the Azure OpenAI client with the structured payload using temperature=0.0.
  * **Hour 8**: Test extracting layout values from a simple invoice image.
* **Verification**: Confirm that the LLM call succeeds and returns the parsed JSON.

### Day 33: Schema Validation Tool
* **Prerequisite Study**: Read about LangChain tool construction using `@tool` and validating JSON outputs.
* **Daily Schedule**:
  * **Hour 1–2**: Study error mapping logic for Pydantic models.
  * **Hour 3–5**: Implement `@tool("validate_extracted_schema")` in `agents/extraction_agent.py`.
  * **Hour 6–7**: Add self-correction retry blocks (the agent attempts to correct the JSON if validation fails).
  * **Hour 8**: Test the validation tool locally with invalid JSON payloads.
* **Verification**: Verify that the tool returns validation errors to the agent for self-correction.

### Day 34: Azure OpenAI Provisioning
* **Prerequisite Study**: Read about Azure OpenAI service deployment, TPM/RPM limits, and opt-out data privacy rules.
* **Daily Schedule**:
  * **Hour 1–2**: Study Bicep OpenAI configurations.
  * **Hour 3–5**: Create `infra/modules/openai.bicep` declaring the Azure OpenAI service.
  * **Hour 6–7**: Link Private Endpoints mapping to `snet-ai` and configure gpt-4o deployments.
  * **Hour 8**: Save API endpoints and keys in Key Vault.
* **Verification**: Run Bicep validate checks to confirm OpenAI configuration registry is correct.

### Day 35: Week 7 UAT Deployment & Testing Gate
* **Prerequisite Study**: Read about unit testing LLM outputs and mock prompt runs.
* **Daily Schedule**:
  * **Hour 1–2**: Study writing pytest mock templates for OpenAI.
  * **Hour 3–4**: Write tests inside `tests/test_extraction_agent.py`.
  * **Hour 5–6**: Deploy the updated Extraction Agent container to UAT.
  * **Hour 7–8**: Trigger the ingestion pipeline in UAT and confirm that gpt-4o parses the uploaded PDF into JSON.
* **Verification**: Verify that the database stores the structured JSON data accurately in UAT.

---

## Week 8: Extraction Verification Tools, Trainer, & Analytics APIs
* **Goal**: Build the Extraction Agent verification tools, Trainer template learning logic, and Dashboard metrics APIs.

### Day 36: Extraction Agent Verification Tools
* **Prerequisite Study**: Learn about decimal rounding rules, local calculations, and flagging policies.
* **Daily Schedule**:
  * **Hour 1–2**: Study the verification logic rules.
  * **Hour 3–5**: Write `@tool("validate_math_totals")` in `agents/extraction_agent.py`.
  * **Hour 6–7**: Implement calculations checking line items sum against subtotal and grand totals.
  * **Hour 8**: Test validation locally with correct and incorrect invoice JSON samples.
* **Verification**: Confirm that math errors return warning status codes.

### Day 37: Extraction Agent Exception Handling & Alert Logging
* **Prerequisite Study**: Learn about error classification, exception handling, and JSONB alert formatting.
* **Daily Schedule**:
  * **Hour 1–2**: Study standard finance error flags and status routing.
  * **Hour 3–5**: Write error handling blocks to catch parsing errors and map them to alert objects.
  * **Hour 6–7**: Implement the logic that updates status to `AUDIT_REQUIRED` and writes warning comments when math or schema validations fail.
  * **Hour 8**: Write unit tests verifying that formatting and parsing exceptions are correctly saved as alerts.
* **Verification**: Verify that corrupted or incorrect invoice uploads generate appropriate alerts on PostgreSQL.

### Day 38: Trainer Agent Template Generator
* **Prerequisite Study**: Read about layout parsing offsets and saving layout templates.
* **Daily Schedule**:
  * **Hour 1–2**: Study how the Trainer Agent creates layout templates.
  * **Hour 3–5**: Write `agents/trainer_agent.py` to compare auditor corrections against failed extractions.
  * **Hour 6–7**: Synthesize coordinate-based layout rules.
  * **Hour 8**: Save rules to the database and link them to the Extraction Agent prompt.
* **Verification**: Confirm that the Trainer Agent persists rule parameters to PostgreSQL.

### Day 39: Dashboard Analytics APIs
* **Prerequisite Study**: Learn aggregate query optimization in SQLAlchemy/SQLModel.
* **Daily Schedule**:
  * **Hour 1–2**: Study group-by query optimizations.
  * **Hour 3–5**: Implement `/api/v1/dashboard/metrics` in `routers/dashboard.py`.
  * **Hour 6–7**: Fetch KPI metrics (Total Spend, Ingestion Queue, Audited Invoices) filtered by tenant.
  * **Hour 8**: Write unit tests for the dashboard metrics endpoint.
* **Verification**: Verify that the metrics endpoint returns correct aggregated data.

### Day 40: Week 8 Integration & Testing Gate
* **Prerequisite Study**: Learn how to write integration tests for complex agent pipelines.
* **Daily Schedule**:
  * **Hour 1–2**: Review the code changes with a teammate.
  * **Hour 3–4**: Write integration tests in `tests/test_verification_flow.py`.
  * **Hour 5–6**: Deploy the updated verification containers to UAT.
  * **Hour 7–8**: Trigger the ingestion API in UAT and confirm that the Extraction and Trainer agents execute correctly.
* **Verification**: Verify that UAT PostgreSQL records update to `AUDIT_REQUIRED` status when math checks fail.
