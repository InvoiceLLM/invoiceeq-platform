# Invoice AI SaaS Platform — Presentation, Demo & ER Architecture Master Guide

> **Audience:** Solution Architects, Sales Engineers, Product Managers, and Enterprise Clients.  
> **Purpose:** Comprehensive guide for presenting, demonstrating, and understanding every page, functionality, workflow, and database entity-relationship (ER) structure in the Invoice AI platform.  
> **Last Updated:** 2026-09-09

---

## Table of Contents

1. [Executive Summary & Platform Narrative](#1-executive-summary--platform-narrative)
2. [Global System Architecture Context](#2-global-system-architecture-context)
3. [Master Entity-Relationship (ER) Overview](#3-master-entity-relationship-er-overview)
4. [Page 1: Dashboard (`/dashboard` & `/outbound-dashboard`)](#4-page-1-dashboard-dashboard--outbound-dashboard)
5. [Page 2: Ingestion & Ingestion History (`/ingestion` & `/history`)](#5-page-2-ingestion--ingestion-history-ingestion--history)
6. [Page 3: Audit & Review Cockpit (`/invoices/review/[id]` & `/outbound-review/[id]`)](#6-page-3-audit--review-cockpit-invoicesreviewid--outbound-reviewid)
7. [Page 4: Trainer & Continuous Learning (`/trainer`)](#7-page-4-trainer--continuous-learning-trainer)
8. [Page 5: Chat, Analyze & Business Intelligence Insights (`/chat`)](#8-page-5-chat-analyze--business-intelligence-insights-chat)
9. [Page 6: Settings Control Plane & Integrations (`/settings`)](#9-page-6-settings-control-plane--integrations-settings)
10. [End-to-End Client Demo Script & Presentation Flow](#10-end-to-end-client-demo-script--presentation-flow)

---

## 1. Executive Summary & Platform Narrative

### What is Invoice AI?
Invoice AI is an **enterprise-grade autonomous accounts-payable (AP) and accounts-receivable (AR) financial intelligence platform**. It eliminates manual document entry, mathematically validates every figure against source scans, continuously learns vendor layout variations, and enables finance teams to converse with their financial data in real time.

### Why do organizations need it?
1. **The Cost of Manual Processing**: Manual AP processing costs $12–$15 per invoice and takes 8–15 minutes of human effort.
2. **The Fragility of Traditional OCR**: Legacy optical character recognition relies on rigid zonal coordinate templates that break whenever a vendor shifts a column or updates a logo.
3. **The Risk of Financial Leakage**: 2–4% of invoices contain subtle arithmetic, rounding, duplicate, or tax overbilling discrepancies that go unnoticed.
4. **Dispute Resolution Gridlock**: Resolving purchase order (PO) discrepancies requires hours of cross-referencing paper trails across disparate systems.

### Quantifiable Client ROI
- **85% Reduction** in end-to-end invoice turnaround time (from 15 minutes to under 5 seconds).
- **100% Elimination** of arithmetic and overbilling leakage via zero-LLM deterministic math verification.
- **Zero Ongoing Template Setup**: Multimodal foundation models parse unseen layouts out-of-the-box.
- **Continuous Learning**: Auditor corrections automatically synthesize vendor rules without engineering intervention.

---

## 2. Global System Architecture Context

The platform is architected as a cloud-native, multi-tenant microservices deployment on Microsoft Azure:

```mermaid
graph TB
    subgraph Client_Tier [Client & User Access]
        Web[Marketing Website :3000<br/>Next.js Multi-Zone]
        App[Web Application :3001<br/>Next.js Dashboard & Cockpit]
        Clerk[Clerk Auth & SSO<br/>JWT + Org ID]
    end

    subgraph Edge_Tier [Network & Security Edge]
        AFD[Azure Front Door + WAF]
    end

    subgraph App_Tier [Compute Services - Azure Container Apps]
        BE[FastAPI Backend :8000<br/>ca-invoice-be]
        Worker[Queue Worker<br/>ca-invoice-worker]
        Chroma[ChromaDB Vector Store<br/>ca-chroma]
    end

    subgraph AI_Tier [Managed AI Services]
        AzureDI[Azure Document Intelligence<br/>OCR + Bounding Boxes]
        AOAI[Azure OpenAI Service<br/>GPT-5.6-Luna / GPT-5-Mini]
    end

    subgraph Data_Tier [Persistence & Messaging]
        PG[(Azure Database for PostgreSQL<br/>Flexible Server)]
        Redis[(Azure Cache for Redis<br/>Sessions & Fair-Share Throttling)]
        Blob[(Azure Blob Storage<br/>Raw PDFs & Assets)]
        Queue[(Azure Storage Queue<br/>Background Task Pipeline)]
    end

    Web --> AFD
    App --> AFD
    Clerk -.-> App
    AFD --> BE
    BE --> PG
    BE --> Redis
    BE --> Blob
    BE --> Queue
    BE --> Chroma
    BE --> AOAI
    BE --> AzureDI

    Queue --> Worker
    Worker --> PG
    Worker --> Blob
    Worker --> Chroma
    Worker --> AOAI
    Worker --> AzureDI
```

---

## 3. Master Entity-Relationship (ER) Overview

Below is the high-level relationship between the fundamental database entities enforced across PostgreSQL:

```mermaid
erDiagram
    TENANT ||--o{ USER : "employs"
    TENANT ||--o{ INVOICE : "owns"
    TENANT ||--o{ DOCUMENT : "archives"
    TENANT ||--o{ CHAT_SESSION : "hosts"
    TENANT ||--o{ EXTRACTION_TEMPLATE : "defines"
    TENANT ||--o{ TENANT_EMAIL_SENDER : "registers"
    TENANT ||--o{ WEBHOOK_SUBSCRIPTION : "configures"
    TENANT ||--o| TENANT_WORKFLOW_CONFIG : "governs"
    TENANT ||--o{ WIDGET_TOKEN : "issues"
    TENANT ||--o{ VENDOR : "manages"

    INVOICE ||--o{ AUDIT_LOG : "generates"
    INVOICE ||--o{ DOCUMENT_COMPARISON : "matched_in"
    
    CHAT_SESSION ||--o{ CHAT_MESSAGE : "contains"
    CHAT_SESSION ||--o{ CHAT_ATTACHMENT : "receives"
    CHAT_ATTACHMENT ||--o{ DOCUMENT_COMPARISON : "compares"

    EXTRACTION_TEMPLATE ||--o{ EXTRACTION_TEMPLATE_VERSION : "versions"
    WEBHOOK_SUBSCRIPTION ||--o{ WEBHOOK_DELIVERY_LOG : "dispatches"
    VENDOR ||--o{ VENDOR_ALIAS : "has"

    TENANT {
        uuid id PK
        string name
        string domain
        string billing_plan
        int free_invoices_remaining
        string api_key_hash
        string api_key_prefix
        boolean receive_invoices_enabled
        boolean send_invoices_enabled
    }

    INVOICE {
        uuid id PK
        uuid tenant_id FK
        string invoice_number
        string vendor_name
        date invoice_date
        decimal grand_total
        string currency
        string status
        string flow_direction
        jsonb items
        jsonb alerts
        string file_hash
    }

    CHAT_SESSION {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string title
        datetime created_at
    }

    CHAT_ATTACHMENT {
        uuid id PK
        uuid session_id FK
        uuid tenant_id FK
        string file_name
        string doc_type
        string status
        jsonb extracted_data
        jsonb candidate_matches
        jsonb insights_data
    }
```

---

## 4. Page 1: Dashboard (`/dashboard` & `/outbound-dashboard`)

### 4.1 Why We Use It & Business Purpose
The Dashboard is the operational command center for financial controllers and CFOs. It provides real-time visibility into working capital, pending liabilities, processing throughput, invoice accuracy ratios, and cash-flow obligations without requiring manual data roll-ups.

### 4.2 Functionality & How It Works
- **Dual Directional Views**: Seamless toggle between **Inbound AP (Accounts Payable)** and **Outbound AR (Accounts Receivable)**.
- **Computed Platform KPIs**:
  - *Total Spend / Revenue*: Aggregated from `SUM(grand_total)` of completed invoices for the filtered period.
  - *Autonomous Accuracy %*: Calculated as `(clean_invoices / total_completed) * 100`. Demonstrates how many invoices bypassed human audit without discrepancies.
  - *Processing Velocity*: Average time taken from upload timestamp (`created_at`) to completion timestamp (`completed_at`).
  - *Overdue Liabilities*: Real-time identification of invoices whose `due_date < CURRENT_DATE` where status is not `PAID`.
- **Time-Series Charts**: Spend trends by vendor, volume by day/week, and breakdown of discrepancies.

### 4.3 Entity-Relationship (ER) Diagram: Dashboard Domain

```mermaid
erDiagram
    TENANT ||--o{ INVOICE : "tracks"
    TENANT ||--o{ VENDOR : "categorizes"
    TENANT ||--o| TENANT_INSIGHT_SETTING : "configures_bi"
    INVOICE ||--o{ AUDIT_LOG : "records_resolution"

    TENANT {
        uuid id PK
        string name
        string billing_plan
    }

    INVOICE {
        uuid id PK
        uuid tenant_id FK
        string flow_direction "INBOUND or OUTBOUND"
        string status "COMPLETED, AUDIT_REQUIRED, PAID"
        decimal grand_total
        decimal tax_amount
        string currency
        date invoice_date
        date due_date
        datetime created_at
        datetime completed_at
        jsonb alerts "Flags math discrepancies or low confidence"
    }

    VENDOR {
        uuid id PK
        uuid tenant_id FK
        string name
        string tax_id
        decimal total_spend_to_date
    }

    TENANT_INSIGHT_SETTING {
        uuid tenant_id PK, FK
        string default_currency
        int fiscal_year_start_month
        jsonb dashboard_preferences
    }
```

### 4.4 Functional Workflow Diagram

```mermaid
sequenceDiagram
    autonumber
    actor CFO as Finance Controller / CFO
    participant UI as Next.js Dashboard UI
    participant Router as routers/dashboard.py
    participant DB as PostgreSQL (Views & Tables)
    participant Redis as Redis Cache

    CFO->>UI: Navigate to /dashboard
    UI->>Router: GET /api/v1/dashboard/metrics?period=30d
    Router->>Redis: Check cached KPI metrics
    alt Cache Hit (<50ms)
        Redis-->>Router: Return serialized JSON KPIs
    else Cache Miss
        Router->>DB: Execute aggregated SQL queries
        Note over DB: Compute SUM(grand_total), AVG(duration),<br/>Accuracy %, and v_overdue rows
        DB-->>Router: Raw metric aggregations
        Router->>Redis: Store in Redis (TTL: 120s)
    end
    Router-->>UI: Return metrics payload
    UI-->>CFO: Render KPI cards, spend charts, and overdue alerts
```

### 4.5 Demo & Presentation Script
> **Presenter Action**: Open `/dashboard`.  
> **Talking Point**: *"Here, leadership gets instant visibility into cash outlays. Notice that every figure here is computed directly from our PostgreSQL database—zero AI hallucinations. Our autonomous accuracy rating is at 98.4%, meaning over 98 out of 100 vendor invoices pass our automated arithmetic checks and get processed in under 5 seconds without a human touching them."*

---

## 5. Page 2: Ingestion & Ingestion History (`/ingestion` & `/history`)

### 5.1 Why We Use It & Business Purpose
The Ingestion portal solves the chaos of multi-channel invoice intake. Enterprises receive invoices via emails, cloud storage, manual uploads, and APIs. This portal provides a unified entry gate with automatic deduplication, format normalization, and batch tracking.

### 5.2 Functionality & How It Works
- **Multi-File Drag & Drop**: Accepts single and multi-page PDFs, TIFFs, PNGs, and JPEGs.
- **Google Drive Shortcut**: One-click browsing of connected Google Drive folders mapped in Settings.
- **Layer-1 Deduplication**: Generates a cryptographic `SHA-256` hash of the file bytes on upload. If that file hash already exists for the tenant, it is immediately marked as `DUPLICATE` without consuming AI extraction tokens.
- **Ingestion History (`/history`)**: Complete audit trail showing batch IDs, document counts, ingestion door (`manual`, `email`, `drive`, `api`, `autopilot`), and real-time processing status.

### 5.3 Entity-Relationship (ER) Diagram: Ingestion Domain

```mermaid
erDiagram
    TENANT ||--o{ INGESTION_BATCH : "initiates"
    TENANT ||--o{ INVOICE : "receives"
    TENANT ||--o{ DOCUMENT : "stores_non_invoices"
    TENANT ||--o| TENANT_AUTOPILOT_CONFIG : "configures"
    TENANT_AUTOPILOT_CONFIG ||--o{ TENANT_AUTOPILOT_LOG : "logs"
    INGESTION_BATCH ||--o{ INVOICE : "contains"

    INGESTION_BATCH {
        uuid id PK
        uuid tenant_id FK
        string batch_source "manual, email, drive, api"
        int total_files
        int processed_files
        int failed_files
        string status "pending, in_progress, completed"
        datetime created_at
    }

    INVOICE {
        uuid id PK
        uuid tenant_id FK
        uuid batch_id FK
        string file_name
        string file_hash "SHA-256 unique per tenant"
        string status "UPLOADED, PROCESSING_OCR, COMPLETED, DUPLICATE"
        string blob_path "Azure Blob URI"
    }

    DOCUMENT {
        uuid id PK
        uuid tenant_id FK
        string file_name
        string doc_type "CONTRACT, QUOTATION, RECEIPT"
        string blob_path
    }
```

### 5.4 Functional Workflow Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User as AP Specialist
    participant UI as /ingestion Web UI
    participant IngestRouter as routers/invoices.py
    participant Blob as Azure Blob Storage
    participant DB as PostgreSQL
    participant Queue as Azure Storage Queue
    participant Worker as Background Queue Worker

    User->>UI: Drag & Drop 10 Invoice PDFs
    UI->>IngestRouter: POST /api/v1/invoices/upload (Multipart)
    loop For Each File
        IngestRouter->>IngestRouter: Compute SHA-256 Hash
        IngestRouter->>DB: Check existing file_hash for Tenant
        alt Duplicate Hash Found
            IngestRouter->>DB: Create Invoice (Status: DUPLICATE)
            Note over IngestRouter: Bypasses OCR & LLM queue
        else New Unique File
            IngestRouter->>Blob: Upload PDF bytes to tenant blob container
            IngestRouter->>DB: Create Invoice (Status: UPLOADED)
            IngestRouter->>Queue: Enqueue message: process_invoice
        end
    end
    IngestRouter-->>UI: Return Batch ID & Provisional IDs
    UI-->>User: Show live progress bars
    Queue->>Worker: Dequeue message
    Worker->>Worker: Trigger NOVA LangGraph Extraction
```

### 5.5 Demo & Presentation Script
> **Presenter Action**: Drag and drop 3 invoices on `/ingestion`. Re-drop one of the same invoices to demonstrate deduplication.  
> **Talking Point**: *"Watch how seamless intake is. You don't need to specify vendors or templates. When I drop an identical file a second time, our Layer-1 SHA-256 deduplication instantly catches it, protecting the client from paying the same bill twice and saving LLM compute."*

---

## 6. Page 3: Audit & Review Cockpit (`/invoices/review/[id]` & `/outbound-review/[id]`)

### 6.1 Why We Use It & Business Purpose
The Audit Cockpit enforces **Zero-Trust Financial Governance**. When an invoice triggers an alert (e.g., math discrepancies, low OCR confidence, missing mandatory GST/tax data), it is quarantined here. It turns painful manual error hunting into a high-speed, side-by-side verification workflow.

### 6.2 Functionality & How It Works
- **Side-by-Side PDF Viewer**: Displays the original scanned document alongside extracted structured fields with bounding-box highlights.
- **SENTINEL Verification Badges**:
  - *Totals Math Check*: Deterministically validates that $\text{Subtotal} + \text{Tax} - \text{Discount} \pm \text{Roundoff} = \text{Grand Total}$.
  - *Line Items Math Check*: Validates that each line's $\text{Quantity} \times \text{Unit Price} = \text{Amount}$.
  - *Faithfulness Check*: Verifies that the extracted grand total appears verbatim in the source OCR text.
  - *Tax Split Check*: Validates CGST + SGST = Total GST for Indian compliance.
- **One-Click Audit Actions**: Approve, Reject, or Edit fields. Editing records a before/after diff in `AuditLog`. If an auditor corrects the same field 3 times for a vendor, the system suggests a permanent rule for EVOLVE.

### 6.3 Entity-Relationship (ER) Diagram: Audit Domain

```mermaid
erDiagram
    INVOICE ||--o{ AUDIT_LOG : "maintains_history"
    INVOICE ||--o{ EXTRACTION_ALERT : "triggers"
    USER ||--o{ AUDIT_LOG : "performs_action"
    TENANT ||--o{ INVOICE : "owns"

    INVOICE {
        uuid id PK
        uuid tenant_id FK
        string invoice_number
        string vendor_name
        decimal subtotal
        decimal tax_amount
        decimal grand_total
        string status "NEEDS_REVIEW, VERIFIED, REJECTED"
        jsonb alerts "Detailed error payloads"
        jsonb verification_badges "Boolean status of SENTINEL checks"
    }

    EXTRACTION_ALERT {
        uuid id PK
        uuid invoice_id FK
        string alert_type "math_discrepancy, faithfulness_failure"
        string field_name
        string message
        boolean is_resolved
    }

    AUDIT_LOG {
        uuid id PK
        uuid invoice_id FK
        uuid user_id FK
        string action "APPROVE, REJECT, FIELD_CORRECTION"
        jsonb field_diff "before: {}, after: {}"
        string reason
        datetime created_at
    }

    USER {
        uuid id PK
        string email
        string role "Admin, Auditor, Trainer"
    }
```

### 6.4 Functional Workflow Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Auditor as Human Auditor
    participant UI as /invoices/review/[id]
    participant AuditRouter as routers/audit.py
    participant DB as PostgreSQL
    participant Evolve as services/rule_impact.py
    participant Webhook as services/workflow_outputs.py

    Auditor->>UI: Opens flagged invoice in Review Cockpit
    UI->>AuditRouter: GET /api/v1/audit/invoices/{id}
    AuditRouter->>DB: Fetch invoice + raw OCR + alerts
    DB-->>AuditRouter: Invoice details & alerts
    AuditRouter-->>UI: Render PDF viewer + field error badges
    Auditor->>UI: Modifies incorrectly parsed Tax Amount & clicks "Approve"
    UI->>AuditRouter: PUT /api/v1/audit/resolve/{id}
    Note over AuditRouter: Validates corrected math via Python Decimal
    AuditRouter->>DB: Update Invoice status -> VERIFIED
    AuditRouter->>DB: Insert AuditLog record (field_diff)
    AuditRouter->>Evolve: Check correction frequency for vendor
    alt Field corrected >= 3 times
        Evolve->>DB: Flag candidate rule for EVOLVE Trainer
    end
    AuditRouter->>Webhook: Trigger webhook (event: invoice.approved)
    AuditRouter-->>UI: Return Success & next queued invoice
```

### 6.5 Demo & Presentation Script
> **Presenter Action**: Open an invoice with an intentional math discrepancy alert.  
> **Talking Point**: *"Look at this red alert badge. The vendor's printed grand total is ₹10,500, but the sum of line items is ₹10,000. Our SENTINEL agent caught this automatically. The auditor didn't have to pull out a calculator. With one click, we can correct the amount, log the audit trail, and approve it. Furthermore, every correction is tracked so the system learns from it."*

---

## 7. Page 4: Trainer & Continuous Learning (`/trainer`)

### 7.1 Why We Use It & Business Purpose
The EVOLVE Trainer represents the **self-improving brain** of the platform. In traditional OCR, when a vendor changes their invoice format, customers must wait weeks for an engineer to update coordinate scripts. The Trainer allows business users to teach the AI vendor-specific extraction rules in seconds with zero coding.

### 7.2 Functionality & How It Works
- **Redis-Backed Sandbox**: Isolates testing in a Redis session (`trainer:session:{id}`) so candidate rules never corrupt live production data.
- **Session Types**:
  - *From-Invoice Session*: Anchored to an existing flagged invoice; re-uses stored OCR text without re-running Document Intelligence.
  - *Upload Session*: Transient document testing for upcoming vendor templates.
- **Rule Impact Simulation**: Replays candidate rules against historical invoices from that vendor to verify that fixing one invoice doesn't break ten others.
- **Template Versioning & Rollback**: Every committed template increments an `ExtractionTemplateVersion`. If a rule behaves poorly in production, the admin can roll back to a previous version with a single click.

### 7.3 Entity-Relationship (ER) Diagram: Trainer Domain

```mermaid
erDiagram
    TENANT ||--o{ EXTRACTION_TEMPLATE : "owns"
    VENDOR ||--o{ EXTRACTION_TEMPLATE : "applies_to"
    EXTRACTION_TEMPLATE ||--o{ EXTRACTION_TEMPLATE_VERSION : "tracks_history"
    USER ||--o{ EXTRACTION_TEMPLATE : "creates"

    EXTRACTION_TEMPLATE {
        uuid id PK
        uuid tenant_id FK
        uuid vendor_id FK
        string name
        string template_scope "GLOBAL or VENDOR_SPECIFIC"
        jsonb extraction_rules "Field hints, regex, anchors"
        int current_version
        datetime updated_at
    }

    EXTRACTION_TEMPLATE_VERSION {
        uuid id PK
        uuid template_id FK
        int version_number
        jsonb snapshot_rules
        string change_summary
        uuid created_by FK
        datetime created_at
    }

    VENDOR {
        uuid id PK
        string name
        string tax_id
    }

    USER {
        uuid id PK
        string email
    }
```

### 7.4 Functional Workflow Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Trainer as Super User / Trainer
    participant UI as /trainer Cockpit
    participant Router as routers/trainer.py
    participant Redis as Redis (Session Cache)
    participant EvolveAgent as agents/trainer_agent.py
    participant DB as PostgreSQL

    Trainer->>UI: Selects invoice to train rule
    UI->>Router: POST /api/v1/trainer/sessions/from-invoice/{id}
    Router->>Redis: Initialize session with OCR text & current schema
    Router-->>UI: Session ID & live draft view
    Trainer->>UI: Inputs prompt correction: "Vendor prints PO in footer notes"
    UI->>Router: POST /api/v1/trainer/sessions/{id}/test-rule
    Router->>EvolveAgent: Synthesize rule & re-run extraction in sandbox
    EvolveAgent-->>Router: Extracted JSON diff
    Router-->>UI: Display before vs after extraction diff
    Trainer->>UI: Click "Simulate Impact Across History"
    UI->>Router: POST /api/v1/trainer/sessions/{id}/simulate-impact
    Router->>DB: Replay rule on past 20 invoices of this vendor
    DB-->>Router: Simulation accuracy score (e.g., 100% pass)
    Router-->>UI: Impact report
    Trainer->>UI: Click "Commit Rule to Production"
    UI->>Router: POST /api/v1/trainer/sessions/{id}/commit
    Router->>DB: Create/Update ExtractionTemplate
    Router->>DB: Insert ExtractionTemplateVersion
    Router-->>UI: Template committed successfully
```

### 7.5 Demo & Presentation Script
> **Presenter Action**: Open `/trainer`. Type a natural language rule like *"Extract the vendor's Tax ID from the bottom right corner"*. Click Test.  
> **Talking Point**: *"This is our EVOLVE engine. When a vendor formats their documents abnormally, you don't submit a support ticket or hire developers. You instruct EVOLVE in plain English. The sandbox verifies it immediately, tests it across past invoices, and commits a versioned template. The platform literally gets smarter every single day."*

---

## 8. Page 5: Chat, Analyze & Business Intelligence Insights (`/chat`)

### 8.1 Why We Use It & Business Purpose
The Chat and Insights page transforms static financial ledgers into an **interactive conversation**. Instead of navigating complex ERP menus, finance executives can ask questions in natural language. Furthermore, via **Feature 26 (Chat with Attachment)** and **Feature 30 (BI Insights Bubble)**, users can drag-and-drop a Purchase Order or Bank Statement and instantly receive an automated 3-way match and discrepancy breakdown.

### 8.2 Functionality & How It Works
- **SAGE Query Routing**: Automatically routes user queries into three execution branches:
  1. *Structured Financial Queries* $\rightarrow$ Synthesizes secure SQL queries, validates AST tenant isolation, and executes against PostgreSQL.
  2. *Unstructured Context Queries* $\rightarrow$ Vector retrieval over ChromaDB (`invoice_chunks_{tenant_id}`) using BAAI/bge-m3 embeddings.
  3. *Chitchat & Platform Help* $\rightarrow$ Answers usability and documentation questions.
- **Feature 26: Chat with Attachment**:
  - 6-stage asynchronous pipeline: OCR $\rightarrow$ Extract $\rightarrow$ Vector Index $\rightarrow$ 3-Tier Match $\rightarrow$ Proactive BI Bubble $\rightarrow$ Ready.
  - **3-Tier Invoice Matching**:
    - *Tier 1*: Exact normalized PO number match.
    - *Tier 2*: Vendor name token Jaccard overlap within a 90-day date window.
    - *Tier 3*: Cosine vector similarity proposal (requires user confirmation before diffing).
- **Feature 30: Business Intelligence (BI) Bubble**:
  - Automatically renders proactive insight cards: *Agreed vs Billed*, *Terms Check*, *Net Position*, *Delivery vs Order*, *Cash Impact*, and *Discrepancy Table*.
  - **Deterministic Diffing**: Line items are compared using exact Python Decimal arithmetic—the LLM only narrates the findings.

### 8.3 Entity-Relationship (ER) Diagram: Chat & Intelligence Domain

```mermaid
erDiagram
    TENANT ||--o{ CHAT_SESSION : "owns"
    USER ||--o{ CHAT_SESSION : "conducts"
    CHAT_SESSION ||--o{ CHAT_MESSAGE : "contains"
    CHAT_SESSION ||--o{ CHAT_ATTACHMENT : "attaches"
    CHAT_ATTACHMENT ||--o{ DOCUMENT_COMPARISON : "analyzed_in"
    INVOICE ||--o{ DOCUMENT_COMPARISON : "matched_against"
    TENANT ||--o{ TENANT_CHAT_RULE : "enforces"

    CHAT_SESSION {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string title
        datetime created_at
    }

    CHAT_MESSAGE {
        uuid id PK
        uuid session_id FK
        string role "user, assistant, tool"
        string content
        string generated_sql
        jsonb tool_calls
        jsonb citations
        datetime created_at
    }

    CHAT_ATTACHMENT {
        uuid id PK
        uuid session_id FK
        uuid tenant_id FK
        string file_name
        string doc_type "PURCHASE_ORDER, STATEMENT_OF_ACCOUNT, etc."
        string status "uploading, extracting, ready"
        jsonb extracted_data
        jsonb candidate_matches
        jsonb insights_data "Feature 30 BI Bubble Cards"
    }

    DOCUMENT_COMPARISON {
        uuid id PK
        uuid attachment_id FK
        uuid invoice_id FK
        string comparison_mode "header_and_line_diff, quantity_mode"
        decimal delta_amount
        string status "match, discrepancy, overbilled"
        jsonb diff_table
    }

    TENANT_CHAT_RULE {
        uuid id PK
        uuid tenant_id FK
        string rule_text "e.g., Always format currency in lakhs"
        boolean is_active
    }
```

### 8.4 Functional Workflow Diagram: Chat with Attachment & Insights

```mermaid
sequenceDiagram
    autonumber
    actor User as Purchasing Manager
    participant UI as /chat Interface
    participant AttachRouter as routers/chat_attachments.py
    participant Queue as Azure Queue
    participant Worker as Background Worker
    participant AzureDI as Document Intelligence
    participant NovaAgent as agents/extraction_agent.py
    participant DiffEngine as services/document_comparison.py
    participant InsightsEngine as services/attachment_insights.py
    participant DB as PostgreSQL

    User->>UI: Uploads PO-2024-991.pdf into Chat
    UI->>AttachRouter: POST /chat/sessions/{id}/attachments
    AttachRouter->>DB: Create ChatAttachment (status: extracting)
    AttachRouter->>Queue: Enqueue message: extract_attachment
    AttachRouter-->>UI: Return attachment_id (UI shows live status badge)
    
    Queue->>Worker: Dequeue extract_attachment
    Worker->>AzureDI: Run OCR & Bounding Box extraction
    Worker->>NovaAgent: Run ReferenceDocExtractionSchema
    Worker->>DB: Update ChatAttachment with extracted_data & doc_type
    
    Worker->>DiffEngine: Execute 3-Tier Match against tenant invoices
    Note over DiffEngine: Tier 1 matches PO-2024-991 in invoice table
    DiffEngine->>DiffEngine: Compute Python Decimal diff on line items
    
    Worker->>InsightsEngine: Generate Feature 30 BI Cards (Agreed vs Billed)
    Worker->>DB: Update ChatAttachment status -> ready + insights_data
    
    UI->>UI: Polls status -> receives "ready"
    UI-->>User: Displays Feature 30 BI Bubble with overbilling diff table!
```

### 8.5 Demo & Presentation Script
> **Presenter Action**: Open `/chat`.  
> 1. Type: *"What was our total spend with Dell Technologies in Q3 broken down by month?"* $\rightarrow$ SAGE generates SQL, displays a clean summary table.  
> 2. Upload a Purchase Order PDF in chat. Within seconds, show the proactive BI Bubble popping up with the discrepancy card.  
> **Talking Point**: *"This is our SAGE intelligence engine. Anyone in finance can ask questions without knowing SQL. And look at what happens when I drop a vendor Purchase Order: SAGE automatically reads it, locates the corresponding invoice in our database, compares line items down to quantity and price, and alerts us if the vendor charged more than the agreed PO price."*

---

## 9. Page 6: Settings Control Plane & Integrations (`/settings`)

### 9.1 Why We Use It & Business Purpose
The Settings Control Plane gives enterprise IT and finance administrators granular control over system behavior, automation policies, security parameters, ingestion channels, and third-party webhooks.

### 9.2 Functionality & Structure of the 7 Integration Tiles

```
+---------------------------------------------------------------------------------+
|                                 /settings TILES                                 |
+---------------------------------------------------------------------------------+
|  [ Workflows ]     -> 4-Step Plug & Play Setup Wizard (Inputs/Policy/Outputs)   |
|  [ Connectors ]    -> Google Drive OAuth 2.0 & Directory Folder Mapping         |
|  [ Email Setup ]   -> Shared App Mailbox & Inbound/Outbound Authorized Sets     |
|  [ Admin Console ] -> Clerk User Management, Roles, and Permission Grants      |
|  [ Subscriptions ] -> Pricing Plans (Free/Pro/Pro Combined), PayU Quotas       |
|  [ Webhooks ]      -> Signed HMAC-SHA256 HTTP Callbacks for 9 Lifecycle Events  |
|  [ Security ]      -> Salted SHA-256 API Keys, CORS Widget Tokens, Audit Logs   |
+---------------------------------------------------------------------------------+
```

- **Tile 1: Workflows (`/settings/workflows` — Features 17 & 25)**:
  - *Inputs*: Multi-select between Email, Drive, API, or Manual upload.
  - *Audit Policy*:
    - **Full Automation**: API key has `actions` scope; clean invoices finalize autonomously.
    - **Strict Review**: API key has `readonly` scope; human must approve every invoice.
  - *Outputs*: Webhooks, Email Summaries, Google Drive Archives, or Dashboard only.
  - *Chat Access*: Dashboard, API, or Embeddable Web Widget.
- **Tile 2: Connectors (`/settings/connectors`)**:
  - Google Drive integration using `FolderTreeExplorer` for browsing remote directory trees.
  - Configures default shortcuts for Inbound AP and Outbound AR storage.
- **Tile 3: Email Setup (`/settings/email`)**:
  - Configures the shared platform mailbox (`invoices@invoiceeq.app`).
  - Manages **Inbound Authorized Senders** (vendors sending AP bills) and **Outbound Authorized Senders** (internal accounting sending AR invoices).
- **Tile 4: Security & Access Control (`/settings/security`)**:
  - Management of live tenant API keys (`inv_live_...`). Hashed via salted SHA-256 with one-time reveal upon rotation.
  - Management of public Chat Widget Tokens (`inv_wgt_...`) with CORS domain whitelisting.
- **Tile 5: Webhooks (`/settings/webhooks`)**:
  - Subscribes external ERPs to 9 invoice lifecycle events.
  - Every payload is signed with HMAC-SHA256 (`X-InvoiceAI-Signature`).

### 9.3 Entity-Relationship (ER) Diagram: Settings & Governance Domain

```mermaid
erDiagram
    TENANT ||--o| TENANT_WORKFLOW_CONFIG : "governed_by"
    TENANT ||--o{ TENANT_EMAIL_SENDER : "authorizes"
    TENANT ||--o{ TENANT_CONNECTION : "links_drive"
    TENANT ||--o{ WEBHOOK_SUBSCRIPTION : "registers"
    TENANT ||--o{ WIDGET_TOKEN : "issues"
    TENANT ||--o{ USER : "seats"
    WEBHOOK_SUBSCRIPTION ||--o{ WEBHOOK_DELIVERY_LOG : "records"

    TENANT_WORKFLOW_CONFIG {
        uuid tenant_id PK, FK
        jsonb input_channels "email, drive, api, manual"
        string audit_policy "full_automation, strict_review"
        jsonb output_destinations "email_summary, webhook, drive_archive"
        string chat_access "dashboard, api, widget"
        datetime completed_at
    }

    TENANT_EMAIL_SENDER {
        uuid id PK
        uuid tenant_id FK
        string email_address
        string email_set "inbound or outbound"
        boolean is_active
    }

    TENANT_CONNECTION {
        uuid id PK
        uuid tenant_id FK
        string provider "google_drive"
        string refresh_token
        string access_token
        string mapped_folder_id
    }

    WEBHOOK_SUBSCRIPTION {
        uuid id PK
        uuid tenant_id FK
        string target_url
        string secret "HMAC secret"
        jsonb subscribed_events
        boolean enabled
        int consecutive_failures
    }

    WIDGET_TOKEN {
        uuid id PK
        uuid tenant_id FK
        string token_hash
        string allowed_origin "CORS Domain"
        boolean is_active
    }
```

### 9.4 Functional Workflow Diagram: Plug & Play Policy Execution

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Tenant Administrator
    participant UI as /settings/workflows
    participant SettingsRouter as routers/settings.py
    participant DB as PostgreSQL
    participant AuthContext as dependencies.py

    Admin->>UI: Selects "Full Automation" & "Webhook Output"
    UI->>SettingsRouter: PUT /api/v1/settings/workflow
    SettingsRouter->>SettingsRouter: Validate destination readiness (check webhooks registered)
    SettingsRouter->>DB: Update TenantWorkflowConfig row
    SettingsRouter->>DB: Update Tenant.api_key_scope = "actions"
    DB-->>SettingsRouter: Commit transaction
    SettingsRouter-->>UI: Return updated configuration
    
    Note over AuthContext: Next API Key request now receives 'actions' scope,<br/>allowing machine approval of clean invoices!
```

### 9.5 Demo & Presentation Script
> **Presenter Action**: Open `/settings`. Navigate to `/settings/workflows`.  
> **Talking Point**: *"Here, an enterprise sets their governance boundaries in four clicks. Do you want machines to approve invoices with 100% clean math? Select 'Full Automation'. Do you require a human sign-off on every dollar? Select 'Strict Review'. And when invoices are approved, our webhooks engine instantly pushes the structured data directly into your SAP or NetSuite ERP via signed HMAC payloads."*

---

## 10. End-to-End Client Demo Script & Presentation Flow

Follow this chronological script for a 15-minute winning client demonstration:

| Timeline | Page / Feature | Action & Visual | Key Message to Deliver |
|---|---|---|---|
| **00:00 – 02:00** | **Executive Intro** | Show [Master Architecture](#2-global-system-architecture-context) diagram | Introduce Invoice AI as an autonomous AP/AR platform that eliminates 85% of processing time with zero math leakage. |
| **02:00 – 05:00** | **Ingestion (`/ingestion`)** | Drag & drop 3 multi-page PDFs. Drop duplicate file. Show `/history`. | Multi-channel intake. Explain Layer-1 SHA-256 deduplication that blocks duplicate billing before touching the AI. |
| **05:00 – 08:00** | **Audit Cockpit (`/invoices/review/[id]`)** | Open an invoice with an alert. Point to SENTINEL math badges. | Zero-Trust Verification. The LLM never does math—hardcoded Python Decimal logic catches vendor arithmetic errors and tax splits. |
| **08:00 – 10:00** | **Trainer (`/trainer`)** | Correct a vendor field. Click "Test in Sandbox" and view historical replay. | Continuous learning (EVOLVE). The system learns vendor layout exceptions without code or engineering tickets. |
| **10:00 – 13:00** | **Chat & Insights (`/chat`)** | Ask a natural language spend query. Upload a Purchase Order PDF. | Conversational finance (SAGE). Show instant text-to-SQL spend breakdown, followed by automated 3-way matching and the Feature 30 BI Bubble. |
| **13:00 – 15:00** | **Settings (`/settings`)** | Show Workflow Wizard (Strict vs Auto) & Webhook integrations. | Enterprise governance and ERP plug-and-play readiness. |

---
*Generated 2026-09-09 — Complete Architecture & Presentation Guide.*
