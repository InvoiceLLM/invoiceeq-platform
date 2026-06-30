# Month 3 Implementation Plan (Days 41–60)

* **Goal**: Configure the local vector store (ChromaDB), build the conversational Query Agent, design Next.js frontend dashboards, integrate Stripe billing and Clerk SSO, run E2E browser tests, configure WAF rules, and deploy the entire platform to Production.

---

## Week 9: Local Vector Store & Query Agent (RAG Chat)
* **Goal**: Build local embeddings, set up ChromaDB, and implement conversational RAG chat.

### Day 41: Local Embedding Configuration
* **Prerequisite Study**: Read about sentence-transformers, BAAI/bge-m3 model dimensions, and CPU optimization.
* **Daily Schedule (8 Hours)**:
  * **Hour 1–2**: Study local embedding setup concepts.
  * **Hour 3–5**: Initialize `SentenceTransformer("BAAI/bge-m3")` in `chroma_client.py`.
  * **Hour 6–7**: Write `calculate_embeddings(chunks)` running locally on CPU.
  * **Hour 8**: Write unit tests checking output dimension sizes (exactly 1024 dimensions).
* **Verification**: Verify that the calculated embedding matches 1024 floating-point numbers.

### Day 42: ChromaDB Client Construction
* **Prerequisite Study**: Read about ChromaDB collection management and metadata indexing.
* **Daily Schedule**:
  * **Hour 1–2**: Study ChromaDB indexing parameters.
  * **Hour 3–5**: Write `add_documents_to_collection` inside `chroma_client.py`.
  * **Hour 6–7**: Add mandatory metadata fields (`tenant_id`, `invoice_id`, `vendor_name`) to every chunk.
  * **Hour 8**: Test inserting and querying chunks locally on a ChromaDB Docker instance.
* **Verification**: Verify that querying the collection returns matching text chunks.

### Day 43: ChromaDB Provisioning in Azure
* **Prerequisite Study**: Read about containerized database storage and Azure Managed Disks (Premium SSD).
* **Daily Schedule**:
  * **Hour 1–2**: Study Bicep templates for container apps with storage mounts.
  * **Hour 3–5**: Create `infra/modules/chromadb.bicep` declaring a Container App for ChromaDB.
  * **Hour 6–7**: Link Private Endpoints mapping to `snet-ai` and mount Azure Managed Disks.
  * **Hour 8**: Validate the updated main infra Bicep deployment templates.
* **Verification**: Validate ChromaDB Bicep syntax using `az bicep build --file infra/modules/chromadb.bicep`.

### Day 44: Query Agent Graph Development
* **Prerequisite Study**: Read about RAG system prompt designs and conversational context retrieval.
* **Daily Schedule**:
  * **Hour 1–2**: Study LangGraph checkpointers for session memory.
  * **Hour 3–5**: Write `agents/query_agent.py` setting up the Query Agent graph.
  * **Hour 6–7**: Bind tools: `query_chroma_vector_store` and `query_postgresql_aggregates`.
  * **Hour 8**: Test querying the agent locally with conversation threads.
* **Verification**: Verify that the agent uses history checkpoints to answer follow-up questions.

### Day 45: Week 9 Integration & Testing Gate
* **Prerequisite Study**: Learn how to test RAG pipelines and verify tenant boundaries in vectors.
* **Daily Schedule**:
  * **Hour 1–2**: Review the code changes with a teammate.
  * **Hour 3–4**: Write integration tests in `tests/test_query_agent.py`.
  * **Hour 5–6**: Deploy the updated Query Agent containers to UAT.
  * **Hour 7–8**: Trigger the chat API in UAT and confirm it retrieves the correct invoice details.
* **Verification**: Verify that query results are strictly isolated by `tenant_id` on UAT.

---

## Week 10: Next.js Frontend Dashboard & Auditor UI
* **Goal**: Build the Next.js workspace, upload interfaces, and the split-screen auditor panel.

### Day 46: Next.js Project & Tailwind Setup
* **Prerequisite Study**: Read Next.js App Router, Tailwind CSS configuration, and Shadcn/UI setup.
* **Daily Schedule**:
  * **Hour 1–2**: Study Next.js page structure and layouts.
  * **Hour 3–5**: Set up Next.js app in `/apps/invoice-fe` and configure Tailwind.
  * **Hour 6–7**: Initialize Shadcn/UI and add basic UI layout components.
  * **Hour 8**: Verify that running `npm run dev` displays the homepage locally.
* **Verification**: Access `localhost:3000` and confirm the Next.js welcome page displays.

### Day 47: Main Dashboard Bento Grid & Sticky Filter Bar
* **Prerequisite Study**: Study Tailwind CSS layout grids, React state management for filters (comboboxes and calendar date ranges), and Chart.js/Recharts integrations in Next.js.
* **Daily Schedule**:
  * **Hour 1–2**: Design the local component architecture for state bindings (syncing the date range, status, and vendor parameters to query keys).
  * **Hour 3–5**: Build the **Sticky Filter Bar**:
    * Date Range Picker (presets: Last 30 Days, Year-to-Date, Custom calendar inputs).
    * Multi-select Vendor Dropdown combobox.
    * Status Checklist Dropdown (`PROCESSING`, `COMPLETED`, `AUDIT_REQUIRED`, `PAID`, `REJECTED`).
    * Advanced Config: Amount Threshold Slider (filtering `grand_total > limit`) and Payment Toggle.
  * **Hour 6–7**: Build the **Bento Grid KPI Cards**:
    * *Card A (PDF Volume)*: Shows date-filtered PDF counts + small subtext label displaying "Total PDFs Processed Lifetime".
    * *Card B (Total Spend)*: Shows accumulated invoice total amounts (excluding `REJECTED`).
    * *Card C (Paid Summary)*: Shows total dollar amount and transaction count for invoices marked as `PAID`.
    * *Card D (Rejected Summary)*: Shows total counts and estimated discrepancy savings for invoices set to `REJECTED`.
  * **Hour 8**: Integrate React Query hooks pulling metrics data from `/api/v1/dashboard/metrics`.
* **Verification**: Verify that changing the filter criteria (e.g. selecting only "REJECTED" or setting a minimum amount) sends correct query arguments to the backend API.

### Day 48: Loader PDF Screen — Ingestion Sub-Tabs & Manual Tagging
* **Prerequisite Study**: Study React state routers (sub-tabs configuration), multi-select row checkboxes, state mapping for bulk tags, and event hooks for Server-Sent Events (SSE).
* **Daily Schedule**:
  * **Hour 1–2**: Design the two sub-tabs: `[Upload & Tag]` and `[Ingestion History]`.
  * **Hour 3–5**: Build **Sub-Tab 1: Upload & Tag**:
    * Implement **Row-Level Checkboxes**: Let users select multiple queued files to bulk-add classification `#tags` (e.g. `#Q1-2026`, `#Hardware`) **before uploading** them to Azure Storage or triggering extraction.
    * Implement the **No-Block Ingestion Uploader**: Drop PDFs directly and trigger processing. Ensure that nothing can be rejected from uploading; any processing anomalies (e.g. math errors, unknown vendor) are displayed as non-blocking alerts instead of stopping the pipeline.
    * Add the `[Submit for Ingestion]` trigger, passing coordinate parameters and pre-applied tags to the extraction API.
  * **Hour 6–7**: Build **Sub-Tab 2: Ingestion History**:
    * Add a Date Range Picker and Vendor Filter Bar.
    * Build the read-only historical table displaying: Ingestion Date, File Name, Calculated Totals, Warning Counts, and Ingestion Badges.
  * **Hour 8**: Integrate SSE triggers to animate progress lines on active uploads.
* **Verification**: Verify that selecting multiple rows allows bulk tagging before upload, dragging a file uploads it as `PROCESSING` without blockages, and sub-tab 2 filters history by date correctly.

### Day 49: Split-Screen Auditor Review & Trainer Console UI
* **Prerequisite Study**: Study Next.js canvas overlays, click-to-select boundary mappings, Form state validation, and layout templates registries.
* **Daily Schedule**:
  * **Hour 1–2**: Design the component states for Auditor Review (with `Mark Paid` / `Reject` buttons, alerts viewer, and dismiss actions) and Trainer feedback mapping overlays.
  * **Hour 3–4**: Build the **Auditor Console UI**:
    * Split screen: Left panel displays invoice PDF, right panel displays editable metadata fields.
    * Add **Interactive Alerts Panel**: Renders active alerts list (math discrepancies, unknown vendor). Enable the auditor to see alerts, match them against the PDF layout, manually correct values, and click to **remove/dismiss individual alerts**.
    * Add color-coded buttons at the bottom: `Mark Paid` (sends database update to `PAID` state once alerts are matched/handled) and `Reject Invoice` (sets state to `REJECTED` and displays auditor comments input).
  * **Hour 5–7**: Build the **Trainer Template Auditor**:
    * PDF viewer overlays semi-transparent color boxes showing exactly what text blocks the AI extracted (green for correct, red for incorrect values).
    * Click-to-Correct tool: Clicking a box opens a coordinate mapping pop-up: *"Select correct text block | Map to Tag: [Grand Total] | Save to Template Registry"*.
    * Add the Template Rules list panel displaying saved vendor offset rules.
  * **Hour 8**: Integrate the correction overrides and tagging payload to the `PUT /api/v1/audit/resolve/{invoice_id}` API endpoint.
* **Verification**: Verify that clicking correct text regions maps coordinates correctly, Auditor buttons save status states in the database, alerts can be removed/dismissed, and custom template rules save to PostgreSQL.

---

### Day 50: Week 10 Integration & Testing Gate
* **Prerequisite Study**: Read about building Next.js static files and optimizing asset payloads.
* **Daily Schedule**:
  * **Hour 1–2**: Study Next.js build options.
  * **Hour 3–4**: Build the frontend project locally: `npm run build`.
  * **Hour 5–6**: Deploy the updated frontend app to UAT using the CI/CD pipeline.
  * **Hour 7–8**: Open the UAT dashboard and perform a complete ingestion and audit review.
* **Verification**: Confirm that the frontend runs without Javascript exceptions on UAT.

---

## Week 11: Marketing Website, Stripe & Clerk SSO
* **Goal**: Build the public website, checkout integrations, and single-sign-on (SSO).

### Day 51: Marketing Website Setup
* **Prerequisite Study**: Read about SEO tags in Next.js, static site generation, and responsive layouts.
* **Daily Schedule**:
  * **Hour 1–2**: Study Next.js SEO optimization parameters.
  * **Hour 3–5**: Set up the Marketing website in `/apps/invoice-website`.
  * **Hour 6–7**: Build the Hero, Pricing, and Security features pages.
  * **Hour 8**: Verify that the site renders responsively across device sizes.
* **Verification**: Verify that running build commands compiles without routing conflicts.

### Day 52: Clerk SSO Integration
* **Prerequisite Study**: Read Clerk auth flows, middleware protection rules, and JWT user tokens.
* **Daily Schedule**:
  * **Hour 1–2**: Study Clerk API configurations.
  * **Hour 3–5**: Integrate Clerk authentication inside the Next.js website.
  * **Hour 6–7**: Configure login redirections and domain validations.
  * **Hour 8**: Test signing in with Google/Microsoft accounts locally.
* **Verification**: Confirm that authenticated users are correctly redirected to the dashboard.

### Day 53: Stripe Checkout Integration
* **Prerequisite Study**: Read Stripe Checkout API, checkout sessions creation, and customer database schema structures.
* **Daily Schedule**:
  * **Hour 1–2**: Study Stripe pricing IDs setup.
  * **Hour 3–5**: Integrate Stripe Checkout API inside `/apps/invoice-website`.
  * **Hour 6–7**: Create billing session redirects for pricing plans.
  * **Hour 8**: Verify Stripe redirection works locally.
* **Verification**: Verify that clicking upgrade redirects to Stripe hosted payment pages.

### Day 54: Stripe Webhook Implementation
* **Prerequisite Study**: Read Stripe webhook event signatures, webhook payload validation, and database transaction commits.
* **Daily Schedule**:
  * **Hour 1–2**: Study webhook authentication signatures.
  * **Hour 3–5**: Create `/api/webhooks/stripe` inside `/apps/invoice-website`.
  * **Hour 6–7**: Handle subscription checkout completion events and update tenant tables.
  * **Hour 8**: Test database updates locally using Stripe CLI.
* **Verification**: Run `stripe trigger checkout.session.completed` and verify the tenant database updates.

### Day 55: Week 11 Integration & Testing Gate
* **Prerequisite Study**: Learn about multi-app deployments in Azure Container Apps.
* **Daily Schedule**:
  * **Hour 1–2**: Study multi-container ACA templates.
  * **Hour 3–4**: Deploy the website and frontend apps to UAT.
  * **Hour 5–6**: Test authentication, tenant provisioning, and billing checkout in UAT.
  * **Hour 7–8**: Validate that new users are successfully registered in UAT.
* **Verification**: Verify that the entire onboarding flow functions correctly in the UAT cloud environment.

---

## Week 12: End-to-End Testing & Production Release
* **Goal**: Run Playwright integration tests, configure WAF rules, and deploy to Production.

### Day 56: Playwright E2E Test Suite
* **Prerequisite Study**: Read Playwright automation syntax, headless browsers execution, and test fixtures.
* **Daily Schedule**:
  * **Hour 1–2**: Study writing user-journey test scripts.
  * **Hour 3–5**: Write Playwright test suites in `/tests/e2e` simulating user onboarding, invoice uploads, audits, and chat queries.
  * **Hour 6–7**: Execute tests locally against the dev stack.
  * **Hour 8**: Integrate E2E tests into the GitHub CI pipeline.
* **Verification**: Confirm that the Playwright test suite passes successfully.

### Day 57: WAF & Front Door Routing
* **Prerequisite Study**: Read Azure Front Door, Web Application Firewall (WAF) rules, and SSL configuration.
* **Daily Schedule**:
  * **Hour 1–2**: Study WAF OWASP rule sets.
  * **Hour 3–5**: Configure Azure Front Door routing rules mapping requests to ACA instances.
  * **Hour 6–7**: Bind custom domains and SSL certificates.
  * **Hour 8**: Verify WAF prevents SQL injections and basic cross-site scripting (XSS) attacks.
* **Verification**: Verify that the Front Door URL routes traffic correctly to UAT.

### Day 58: Production Infrastructure Provisioning
* **Prerequisite Study**: Read Azure production environment requirements and scaling rules.
* **Daily Schedule**:
  * **Hour 1–2**: Study parameter variations for production.
  * **Hour 3–5**: Execute Bicep deployment templates targeting production parameters (`params.prod.json`).
  * **Hour 6–7**: Verify that PostgreSQL (HA enabled) and Redis (Premium SKU) provision successfully.
  * **Hour 8**: Run connection path checks within the production VNet.
* **Verification**: Confirm that all production Azure resources are active and secured.

### Day 59: Production Database Migration
* **Prerequisite Study**: Read about database backup strategies, migration verifications, and rollback checklists.
* **Daily Schedule**:
  * **Hour 1–2**: Study Alembic production migration parameters.
  * **Hour 3–5**: Run database schema creation inside the production PostgreSQL instance.
  * **Hour 6–7**: Run Alembic migrations and verify table structures match models.
  * **Hour 8**: Verify that initial admin seeding scripts execute.
* **Verification**: Verify that the production database has the complete and correct tables.

### Day 60: Production Deployment & Smoke Tests
* **Prerequisite Study**: Read about production deployment smoke tests and rollback execution.
* **Daily Schedule**:
  * **Hour 1–2**: Study the release smoke test checklist.
  * **Hour 3–4**: Deploy all container apps (website, frontend, backend, workers) to Production.
  * **Hour 5–6**: Perform comprehensive smoke tests (auth, upload, RAG search) in the Production environment.
  * **Hour 7–8**: Hand over documentation, monitor application insights dashboard logs, and declare launch success.
* **Verification**: Verify that the entire SaaS application is live, fully functional, and accessible under the production domain.
