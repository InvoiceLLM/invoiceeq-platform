# Invoice AI SaaS Platform — Master Technical Guide (Part 1 of 2)

> **Purpose:** Complete knowledge document covering every feature, algorithm, and implementation detail of the Invoice LLM platform.
> **Last updated:** 2026-09-09 · Codebase reconciled 2026-09-07
> **Part 2:** `master_technical_guide_part2.md` — Feature 26, Feature 30, SENTINEL, EVOLVE, RAG, Infra, Settings Architecture, Client Pitch Guide, Accuracy Gaps & Algorithms

---

## Table of Contents — Part 1

1. [Platform Overview](#1-platform-overview)
2. [System Architecture and Tech Stack](#2-system-architecture-and-tech-stack)
3. [The Four AI Agents](#3-the-four-ai-agents)
4. [NOVA — Extraction Pipeline Deep Dive](#4-nova--extraction-pipeline-deep-dive)
5. [SAGE — Chat Agent Deep Dive](#5-sage--chat-agent-deep-dive)

---

## 1. Platform Overview

Invoice AI is a **multi-tenant enterprise SaaS** that automates accounts-payable (AP) and accounts-receivable (AR) document processing.

**What it does:**
- Reads inbound invoices (from vendors to the company — AP direction)
- Reads outbound invoices (from the company to its customers — AR direction)
- Extracts structured data from those PDFs using AI
- Routes discrepancies to a human audit queue
- Learns vendor-specific corrections from auditors
- Answers natural language questions about the entire ledger (SAGE chat)
- Compares chat-attached reference documents (POs, quotations, delivery notes) to the invoice ledger

**Product URL:** `invoicellm.admsofttech.com` — Azure Front Door + WAF, custom domain.

### Key Platform Metrics (all computed in code, not LLM-generated)

| Metric | How computed |
|---|---|
| Extraction accuracy | (invoices with no alerts / total completed) x 100 |
| Average processing time | completed_at - created_at averaged over COMPLETED rows |
| Spend over time | SUM(grand_total) by week/month for INBOUND rows |
| Revenue over time | SUM(grand_total) by week/month for OUTBOUND rows |

---

## 2. System Architecture and Tech Stack

```
 EXTERNAL USERS
   Marketing Website (invoice-website, Port 3000)
   App (invoice-fe, Port 3001)
   Clerk SSO (JWT)
         |
         v
   Azure Front Door + WAF (Custom Domain)
         |
         v
   FastAPI Backend (invoice-be, Port 8000)
     Routers: auth / invoices / chat / audit / trainer / settings
              outbound_invoices / outbound_audit / chat_attachments
              dashboard / outbound_dashboard / ingestion_history
              connectors / autopilot / billing / support / admin

     AI AGENT LAYER:
       NOVA: extraction_agent.py  |  SAGE: query_agent.py
       EVOLVE: trainer_agent.py   |  Support: support_agent.py

     Services: document_comparison / attachment_extraction
               attachment_insights / document_type_classifier
               chat_queue / full_records / billing_lifecycle ...
         |
    _____|_____________________
   |           |               |
PostgreSQL  Redis + Azure    Azure Blob Storage
(SQLModel)  Queue Worker    (PDFs, images)
   |
ChromaDB (per-tenant collections):
  invoice_chunks_{tenant_id}
  docs_{tenant_id}
  chat_docs_{tenant_id}
  knowledge_{tenant_id}
```

### Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.12, SQLModel/SQLAlchemy, Pydantic |
| Agent runtime | LangGraph (state machines, deterministic graph nodes) |
| Frontend | Next.js App Router, TypeScript, Tailwind CSS |
| Database | PostgreSQL (Azure Flexible Server), Alembic migrations |
| Vector DB | ChromaDB — per-tenant collections, cosine distance space |
| Queue | Azure Storage Queues (extraction, dead-letter) + Redis (chat jobs, SSE, answer cache) |
| LLM | Azure OpenAI — gpt-5.6-luna (primary), gpt-5-mini (judge/chat_summary) |
| OCR | Azure Document Intelligence (prebuilt-invoice model) |
| Embeddings | BAAI/bge-m3 (local in container, sentence-transformers, 1024 dims) |
| Auth | Clerk (orgs, email/password + OTP 2FA, JWT validation) |
| Email | SendGrid (Inbound Parse for email-in, Mail Send for notifications) |
| Payments | PayU (hosted checkout redirect) |
| Cloud | Azure — Container Apps, VNet, Key Vault, Front Door |
| IaC | Azure Bicep (10 staged templates) |
| CI/CD | GitHub Actions (build + push to ACR, no test runs in CI) |

---

## 3. The Four AI Agents

The platform names four agents for user-facing branding. Each maps to a specific Python module.

```
FOUR NAMED AGENTS

  NOVA            --> agents/extraction_agent.py
  Smart Invoice       LangGraph state machine
  Extraction Agent    classify -> extract -> verify -> persist

  SENTINEL        --> utils/verification_tools.py + routers/audit.py
  Risk Detection      Arithmetic checks, faithfulness, duplicates
  Agent               Routes failures to AUDIT_REQUIRED status

  SAGE            --> agents/query_agent.py
  Invoice             Routes to SQL / RAG / Attachment branches
  Intelligence        Answer contract gate, Redis answer cache

  EVOLVE          --> agents/trainer_agent.py
  Continuous          Learns from auditor corrections
  Learning Agent      Writes and versions ExtractionTemplate rules
```

---

## 4. NOVA — Extraction Pipeline Deep Dive

### 4.1 How a Document Enters the System

```
Upload (browser / email / Google Drive / API / directory watcher)
        |
        v
services/file_intake.py :: normalize_upload()
   If image (PNG/JPG/TIFF/WEBP/BMP):
     * 50-megapixel decompression guard
     * PIL: open -> convert to PNG -> write as single-page PDF
     * After this, the pipeline only ever sees PDFs
        |
        v
SHA-256 file_hash -> Layer-1 Duplicate Detection
   Hash already in Invoice table?
     YES: status=DUPLICATE, duplicate_of_invoice_id set, NO queue message
     NO: continue
        |
        v
Stream PDF -> Azure Blob Storage
Create Invoice row (status=UPLOADED->PROCESSING)
Create IngestionBatch row (trigger=manual|email|connector|autopilot)
Enqueue "process_invoice" -> Azure Storage Queue
```

### 4.2 NOVA LangGraph — The Extraction State Machine

Defined in `agents/extraction_agent.py :: _build_extraction_graph()`.

**One graph serves INBOUND + OUTBOUND + REFERENCE** — parameterised by `flow_direction` in `ExtractionState`. A separate outbound graph that previously existed was deleted (Gap 283) because it silently missed every inbound improvement.

```
ExtractionState (TypedDict keys):
  file_path, ocr_text, images, extracted_data
  alerts, status, rules, complexity, ocr_result
  retry_count (int), max_retries (int), feedback (List[str])
  dynamic_qa_context
  flow_direction: "INBOUND" | "OUTBOUND" | "REFERENCE"
  tenant_id
  doc_type, doc_type_evidence, doc_type_confidence   (Feature 27)
  doc_attributes                                      (Feature 27 A6)

GRAPH NODES (executed in order):
==============================================================

[NODE 1] classify_doc_type_node
  Present ONLY when ENABLE_GENERIC_EXTRACTION = True
  Service: document_type_classifier.py
  Two-stage: deterministic title-match -> LLM fallback if ambiguous
  Writes: doc_type, doc_type_evidence, doc_type_confidence, doc_attributes
  Calls: resolve_extraction_profile(direction, doc_type)
    -> picks the schema, system prompt, and verification rubric

[NODE 2] classify_node
  Service: invoice_classifier.py
  Heuristic keyword/field-presence check
  Writes: complexity = "STANDARD" | "COMPLEX"
  COMPLEX trigger examples: multi-rate GST, holdback clauses,
    e-invoicing identifiers (IRN/QR), foreign currency with conversion

[NODE 3] dynamic_qa_node  (COMPLEX documents only)
  Pre-extraction LLM pass: asks document-specific questions
    e.g. "Does this invoice apply multiple GST rates?"
         "Is there a withholding or holdback clause?"
  Uses the multimodal channel (base64 page images)
  Output stored in dynamic_qa_context -> fed to extract_node
  Purpose: gives extract_node domain context the schema alone cannot provide

[NODE 4] extract_node   <-- THE CORE EXTRACTION
  Model: get_llm() -> gpt-5.6-luna (primary role)
  Schema: with_structured_output() using one of:
    InvoiceExtractionSchema          (INBOUND invoices)
    OutboundInvoiceExtractionSchema  (OUTBOUND invoices)
    ReferenceDocExtractionSchema     (chat attachments, REFERENCE flow)
    GenericDocExtractionSchema       (non-invoice documents, Feature 27)
  Guarantees: temperature=0, extra="forbid", additionalProperties=false

  Prompt includes:
    * OCR text (Azure Document Intelligence raw output)
    * Base64 page images (multimodal visual channel)
    * GAP_46_VERBATIM_DIRECTIVE:
        "You are a strict document transcriber, NOT a calculator.
         Transcribe all figures verbatim, exactly as printed,
         including wrong vendor math."
    * Trainer rules for this tenant + vendor (merged)
    * Dynamic QA context (if COMPLEX)
    * Schema chosen by resolve_extraction_profile()

  CRITICAL: Negative credit lines, discounts, deductions
            MUST be extracted as negative floats.
            The system depends on this to detect over-billing.

[NODE 5] verify_node   <-- ALL DETERMINISTIC, ZERO LLM
  Checks (all in utils/verification_tools.py):

  verify_totals_math():
    expected_subtotal = SUM(item.amount for item in items)
    expected_grand_total = subtotal + tax_amount - discount_amount + round_off
    Alert if |computed - stated| > tolerance

  verify_line_items_math():
    For each line: expected = quantity x unit_price
    Alert if |item.amount - expected| > tolerance

  verify_grand_total_in_source_text():
    Grand total must appear verbatim in OCR text
    If not -> faithfulness_failure alert
    Catches: OCR mis-read -> LLM auto-corrected -> result "works" but is wrong

  verify_line_item_amounts_in_source_text():
    Each line amount must be traceable to OCR text

  verify_tax_amount_in_source_text(tax_components=[]):
    Component-aware: if CGST=9000 + SGST=9000 -> tax_amount=18000
    Checks that SUM of components equals stated figure
    even if the summed figure 18000 is not printed as-is

  verify_field_confidence():
    Azure OCR assigns per-field confidence scores (0.0 - 1.0)
    Below CONFIDENCE_THRESHOLD -> low_confidence_field alert

[CONDITIONAL EDGE] route_after_verification()
  At least one RETRYABLE alert?
  AND retry_count < max_retries (= 2)?
    -> LOOP BACK to extract_node
       state["feedback"] gets human-readable explanation
       e.g. "grand_total 118.00 was not found in source text"
       Model re-extracts with feedback appended to prompt
  Otherwise -> END

Handler: _persist_result()
  doc_type in MONEY_FAMILY?
  (INVOICE, PROFORMA_INVOICE, CREDIT_NOTE, DEBIT_NOTE, RECEIPT)
    -> Update Invoice row:
         No alerts -> status = COMPLETED
         Has alerts -> status = AUDIT_REQUIRED
  doc_type in non-invoice family?
    -> Write to "documents" table
    -> Delete provisional Invoice row
    -> Index to docs_{tenant_id} in ChromaDB
    -> NEVER appears in AP/AR ledger or audit queue
```

### 4.3 Extraction Schemas — What Gets Extracted

**Inbound Invoice (InvoiceExtractionSchema):**

| Field | Type | Notes |
|---|---|---|
| vendor_name | str | Who issued the invoice |
| invoice_number | str | Document identifier |
| invoice_date | str ISO 8601 | Print date |
| due_date | str ISO 8601 | Payment deadline |
| subtotal | float | Before tax/discount — verbatim as printed |
| tax_amount | float | CGST+SGST summed into single field if split |
| grand_total | float | Verbatim as printed, even if vendor math is wrong |
| round_off | float | Indian GST rounding adjustment line (+/-) |
| po_number | str | Referenced Purchase Order number |
| currency | str | ISO 4217 code: INR, USD, EUR... |
| items | List[InvoiceLineItem] | description, qty, unit_price, amount, hsn_sac_code, uom, tax_percent |
| taxes | List[TaxItem] | Per tax line: tax_type, rate_percent, amount |
| discounts | List[DiscountItem] | Per discount: type, percent, amount |
| deductions | List[DeductionItem] | Holdbacks, TDS deductions |
| tax_ids | List[TaxIdItem] | GSTIN, PAN, EU VAT, EIN |
| payment_instructions | List[PaymentInstructionItem] | IBAN, UPI ID, ACH routing |
| references | List[ReferenceItem] | e-Way Bill, credit note reference |
| addresses | List[AddressItem] | billing/shipping/vendor addresses |
| compliance_metadata | List[ComplianceMetadataItem] | IRN, QR code, Peppol address |

**Reference Document (ReferenceDocExtractionSchema) — used for chat attachments:**

Additional fields beyond invoice schema:
- doc_type: "PURCHASE_ORDER" | "QUOTATION" | "OTHER"
- party_name (who issued), counterparty_name (who addressed to)
- payment_terms, delivery_terms, notes
- referenced_documents[] — for STATEMENT/REMITTANCE: list of referenced invoices
- statement_lines[] — for BANK STATEMENT: per-row transactions with debit/credit/balance

### 4.4 Trainer Rules Feed Extraction (Two Passes)

```
PASS 1 (before vendor known):
  _get_template_rules() -> GlobalExtractionTemplate
  (vendor-agnostic constraints, e.g. "currency is always INR")

PASS 2 (after vendor identified from extract_node output):
  Merge vendor-specific ExtractionTemplate (vendor wins on conflict)
  If template exists -> RE-RUN extract_node with merged rules in prompt

Example rules that change extraction behaviour:
  "Sum CGST line + SGST line into tax_amount field"
  "Invoice number is always in the stamp block top-right"
  "This vendor always uses 2 decimal places; round_off is always null"
  "Treat parenthesised amounts as negative (credit note format)"
```

### 4.5 Invoice Status State Machine

```
UPLOADED -> PROCESSING -> PROCESSING_OCR -> EXTRACTING_DATA -> INDEXING
    |            |                                                  |
    |            +-> FAILED                                   COMPLETED
    |                                                         AUDIT_REQUIRED
    +-> DUPLICATE
```

Real-time broadcast via SSE:
```
_publish_sse_events()
  -> Redis channel "invoice.update.{batch_id}"
  -> GET /invoices/stream/{batch_id}  (SSE endpoint)
  -> Browser EventSource receives status updates live
```

### 4.6 RAG Indexing After Extraction

```python
if should_index_status(status):   # Not: PROCESSING, FAILED, DUPLICATE
    chroma_client.index_invoice_document(tenant_id, invoice_id, blob_path, vendor_name)
    # 1. Download PDF from Azure Blob
    # 2. Open with PyMuPDF (fitz)
    # 3. ONE CHUNK PER PAGE
    # 4. Chunk = "[{vendor_name} | {invoice_id} | Page {n+1}]\n{page_text}"
    # 5. Batch embed: BAAI/bge-m3 (1024 dims)
    # 6. Upsert to invoice_chunks_{tenant_id}
    #    ID = "{invoice_id}_{page_n}" -> re-indexing is idempotent
    #    Metadata: {tenant_id, invoice_id, vendor_name, page}
```

---

## 5. SAGE — Chat Agent Deep Dive

### 5.1 Async Queue Architecture

```
POST /chat/sessions/{id}/message
        |
        v
ENABLE_ASYNC_CHAT_QUEUE = True (default)
        |
        v
services/chat_queue.py :: enqueue_chat_job()
  * Per-tenant inflight cap: chat_inflight:{tenant} = 3 simultaneous turns
  * Over cap -> HTTP 429 with Retry-After header
  * Push job_id -> Redis list "chat_tasks_queue"
  * Return {job_id} immediately (non-blocking)
        |
        v
Browser connections:
  GET /chat/jobs/{job_id}/stream   (SSE progress stream)
  GET /chat/jobs/{job_id}/status   (poll fallback)
        |
        v
Queue Worker (handle_process_chat_job()):
  * Per-session Redis lock (one turn at a time per session)
  * Calls: agents/query_agent.py :: run_query_agent()
```

### 5.2 SAGE Routing Decision Tree

```
run_query_agent(user_message, session, tenant_id, ...)
|
|-- Is there an active chat attachment (attachment_id set)?
|   YES -> _run_attached_document_turn()  [Feature 26 path, see Part 2]
|
|-- Check Redis answer cache
|   Key: chat_answer_cache:{tenant_id}:{normalized_question}
|         :rules={rules_version}:att={att_hash}
|   TTL: 3600 seconds
|   HIT -> serve cached answer immediately (end of turn)
|   SKIP cache for narrowing follow-ups:
|     "the 3 USD ones", "those invoices", "explain them", "those 2"
|     (Detected by _FOLLOWUP_BACKREF_PATTERNS regex list)
|
|-- classify_query(user_message)
|
|   STEP 1 — Keyword fast-path (no LLM, free):
|     SQL_KEYWORDS = ("total", "spent", "sum", "average", "how many",
|                     "count", "mean", "min", "max", "date", "status",
|                     "vendor", "po number", "purchase order", "currency")
|     CHAT_KEYWORDS = ("hello", "hi ", "hey", "who are you", ...)
|     Uses word-boundary regex (not naive substring)
|     -> "summarize" does NOT trigger on "sum"
|
|   STEP 2 — LLM if ambiguous (no keyword match):
|     Model: _fast_llm() -> gpt-5-mini (A2 optimisation)
|     Schema: QueryRoutingSchema { route: Literal["SQL","RAG","CHAT"] }
|     Fallback on LLM failure -> "RAG"
|
|   ROUTE = SQL | RAG | CHAT
|
|-- SQL Route:
|   1. link_question_to_schema() -> deterministic term->column map
|      e.g. "spend"       -> grand_total, direction=INBOUND
|           "revenue"     -> grand_total, direction=OUTBOUND
|           "tax"         -> tax_amount
|           "outstanding" -> due_date + status filter
|   2. _retrieve_sql_examples() -> cosine-nearest curated SQL examples
|      (BAAI/bge-m3 embeddings, similarity floor = 0.45)
|   3. Generate SQL via _generation_llm() -> gpt-5.6-luna (A1 budget)
|      Self-repair loop (3 attempts max):
|        Attempt 1: Generate SQL
|        Error/zero-rows -> feedback message added to prompt
|        Attempt 2: Regenerate with feedback
|        Error/zero-rows -> second feedback
|        Attempt 3: Final attempt or fallback answer
|   4. assert_tenant_isolation_on_ast(sql, tenant_id)
|      Uses sqlglot to PARSE the SQL AST (not regex)
|      Walks the tree looking for tenant_id predicate
|      Rejects if not found (Gap 414)
|   5. _normalize_string_equality(sql) rewrites comparisons:
|      vendor_name / customer_name = 'X'  -> LIKE '%x%' (substring)
|      invoice_number / po_number  = 'X'  -> TRIM(LOWER()) equality
|   6. Execute SQL against PostgreSQL
|   7. Zero rows? -> _diagnose_zero_rows() fallback chain:
|      a. lookup_invoice_by_number_fallback()
|         Regex extracts invoice-number token from user question
|         Direct TRIM(LOWER()) match against invoice_number column
|         No LLM, cannot bind wrong invoice
|      b. category_search_fallback()
|         Fires only when generated SQL was a category/subject query
|         Runs CODE-BUILT SQLAlchemy query over ALL 18 text columns
|         including JSONB columns: tags, items, sa_alerts, references...
|         Reflects models.py live -> new column = instantly searchable
|   8. get_full_records() -> enriches with complete invoice data
|   9. _chat_summary_llm() -> gpt-5-mini narrates the answer
|
|-- RAG Route:
|   1. embed_query(user_message) -> BAAI/bge-m3 -> 1024-dim vector
|   2. query_invoice_chunks(tenant_id, question, limit=10)
|      Collection: invoice_chunks_{tenant_id}
|      Filter: cosine distance <= 0.49 (empirically derived, Gap 244)
|      Also queries docs_{tenant_id} for non-invoice documents
|   3. Keyword boost pass (hybrid lexical + semantic)
|   4. get_full_records() -> enriches retrieved invoice records
|   5. Synthesize answer (phrasing call)
|
+-- CHAT Route:
    Conversational response only, no retrieval
    Uses: ChatSession.history_summary + ChatSession.focus
    Model: _fast_llm() -> gpt-5-mini
```

### 5.3 SQL Generation: Prompt Architecture

```
[STABLE CACHEABLE PREFIX — tenant-agnostic, same for all tenants]
  * Role: "You are a PostgreSQL query expert"
  * Full Invoice table schema (all columns + types)
  * 25+ SQL rules:
      Rule 1: Always filter WHERE tenant_id = '<tenant_id>'
      Rule 2: Only read-only SELECT statements
      Rule 3: INBOUND = bills received, OUTBOUND = invoices sent
      Rule 4: vendor_name for INBOUND, customer_name for OUTBOUND
      Rule 5: Both directions -> UNION or conditional aggregation
      Rule 6b: Category queries must search ALL four columns in ONE OR-group
               (a subset is a bug: silently misses real matches)
      Rule 6d: Line-item searches use JSON unnesting pattern
      ... 25+ total rules covering every observed failure mode

[REQUEST TAIL — per-turn, cannot be prefix-cached]
  * tenant_id: actual UUID
  * Current date (for "this month", "this year" relative queries)
  * Global Trainer rules (ExtractionTemplate, global scope)
  * Vendor-specific Trainer rules
  * Chat correction rules (TenantChatRule table)
  * SCHEMA LINK block: deterministic term->column map for THIS question
  * Retrieved few-shot examples (top-3 cosine-nearest from golden bank)
  * User question
  * Conversation history (last N turns)
  * Previous turn's generated SQL (for follow-up narrowing)
```

### 5.4 Schema Linking (C4.1 — Deterministic Pre-processing)

Before the model runs, `link_question_to_schema(user_message)` does these deterministic regex matches:

```
Named metrics (regex patterns):
  "spend"       -> column=grand_total, direction=INBOUND
  "revenue"     -> column=grand_total, direction=OUTBOUND
  "tax"         -> column=tax_amount (detect_tax_component_term() fires)
  "subtotal"    -> column=subtotal
  "discount"    -> column=discount_amount
  "count"       -> COUNT(*) or COUNT(DISTINCT ...)
  "outstanding" -> due_date < today AND status != PAID

Attribute detection (detect_invoice_attribute_term()):
  "payment terms" -> column=payment_instructions
  "due date"      -> column=due_date
  "PO number"     -> column=po_number

Result injected into prompt tail as FACTS:
  "SCHEMA LINK (computed deterministically before you ran):
   - metric: spend -> grand_total: sum over INBOUND rows..."

Purpose: Model does not have to re-derive "spend = grand_total" from
         prose rules each time. Pre-computed facts = fewer routing errors.
```

### 5.5 Full Records Context (Feature 29 task 29.5)

```python
services/full_records.py :: get_full_records(invoice_ids, tenant_id, db)

Returns per invoice:
  * All scalar fields: invoice_number, dates, amounts, status, etc.
  * items[] (full line-item JSON)
  * taxes[] (tax breakdown)
  * sa_alerts[] (extraction alerts with descriptions)
  * notes
  * OCR text chunks from ChromaDB (first N pages)
  * doc_attributes (from Feature 27 classification)
  * Computed figures: check_line_arithmetic() -- pre-verified math
```

This full context is given to the narration model AFTER all numbers have been computed.

Model selection for narration (measured, not guessed):
```
Full-record route -> _chat_summary_llm() -> gpt-5-mini
  Measured: 22.2% -> 52.8% on 36-case golden set with this model
Attachment route  -> _fast_llm() -> gpt-5.6-luna
  Measured: 16/16 on 16-turn attachment probe
```

### 5.6 Answer Contract Gate (Feature 29 task 29.9)

```
_answer_contract_gate(answer_text, evidence_bundle):
  Enabled by: ENABLE_ANSWER_CONTRACT_GATE = True (default)

  Algorithm:
    1. Extract all numeric figures from LLM prose answer
    2. Check each against evidence (SQL rows + full records + attachment data)
    3. Figure NOT found in evidence -> VIOLATION flag
    4. On violation: one regeneration with violation named explicitly
    5. Still violated -> abstain payload:
       "I found these results but cannot confirm the specific figure"

  Purpose: Prevent hallucinated numbers from reaching the user.
  Hard rule: "The LLM describes what was computed. It never computes."
```

### 5.7 Session Memory and Cache

```
Short-term memory:
  ChatMessage table -- full conversation transcript per session

Long-term context compression:
  ChatSession.history_summary -- gpt-5-mini summarizes old turns
  ChatSession.focus           -- current entity/topic being discussed

Answer cache (Redis):
  Key: chat_answer_cache:{tenant_id}:{normalized_query}
        :rules={rules_version}:att={att_hash}
  TTL: 3600 seconds
  Invalidated by: Trainer commit or rollback (rules_version changes)
  Skipped for: narrowing follow-up questions (those, them, explain them...)

Attachment dimension in cache key (Feature 29 task 29.12):
  att = sha256(sorted(attachment_ids))[:12]
  Ensures "Does this match our invoice?" about PO-A != same about PO-B
  Before 29.12, attachment turns were never cached (every re-ask paid full cost)
```

### 5.8 Progress Events (SSE to Browser)

```
understanding_question  -> query classification starting
cached_answer           -> cache hit; turn ends here
route_selected          -> {route: "SQL" | "RAG" | "CHAT"}
building_query          -> SQL prompt assembled
generating_sql          -> {attempt: 1, max_attempts: 3}
running_query           -> SQL executing against Postgres
summarizing_results     -> synthesis call starting
searching_documents     -> RAG vector search
documents_found         -> {count: N chunks retrieved}
composing_answer        -> phrasing call
streaming               -> {partial: "..."} if ENABLE_CHAT_STREAMING=True
answer_ready            -> turn complete

[Feature 26 attachment branch only]
reading_attachment      -> {doc_type: "PURCHASE_ORDER"}
matching_invoices       -> Tier 1 / 2 / 3 search running
awaiting_confirmation   -> candidates found, user must select
comparing_documents     -> deterministic diff running
searching_attachment    -> content vector search on attachment
reconciling_statement   -> statement-vs-ledger join running
```

---

> Continue reading: master_technical_guide_part2.md covers Feature 26 (Chat with Attachment algorithms),
> Feature 30 (BI Bubble), SENTINEL, EVOLVE, RAG/ChromaDB, Document Type Classification,
> Multi-tenant Isolation, Queue Worker, Intake Doors, Auth/Billing, Observability,
> Infrastructure, and the full Accuracy Gap analysis.
