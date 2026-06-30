# Feature 6: Conversational RAG & Thread Management

Construct document indexers and semantic chat clients utilizing vector similarity models and thread state controllers.

### File Coordinates
* RAG Router: [apps/invoice-be/routers/chat.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/chat.py)
* Query Agent: [apps/invoice-be/agents/query_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py)
* Chroma Client: [apps/invoice-be/chroma_client.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/chroma_client.py)

### Tasks
- [x] **Task 6.1: Setup Chat Sessions & Threads API**
  - Implement endpoints:
    - `GET /api/v1/chat/sessions` (returns lists of previous sessions).
    - `POST /api/v1/chat/sessions` (creates new sessions with unique IDs).
    - `GET /api/v1/chat/sessions/{session_id}` (retrieves historical messages).
- [x] **Task 6.2: Create Document Chunking Pipeline**
  - Implement page-level chunking using PyMuPDF (`fitz`) to extract text page-by-page.
  - Prepend context headers: `[Vendor: {vendor_name} | Document ID: {invoice_id} | Page {page_number}]` to preserve tabular boundaries.
- [x] **Task 6.3: Configure Embedding Calculations**
  - Code local embedding vectors generation using the `BAAI/bge-m3` model via the `sentence-transformers` library.
- [x] **Task 6.4: Setup ChromaDB Collections & Metadata Isolation**
  - Create the `invoice_chunks` collection.
  - Insert chunk vectors with metadata: `tenant_id`, `invoice_id`, and `vendor_name`.
  - Filter queries strictly by `tenant_id` to prevent cross-tenant data leaks.
- [x] **Task 6.5: Build Query Agent with Memory Checkpointer & SQL Drawer**
  - Build the RAG Query Agent routing queries between Vector search, SQL metadata searches, or casual chat.
  - Returns `generated_sql` query syntax inside response payloads if database aggregates were run.
  - Format response mapping list of citations to PDF pages.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_rag.py` verifying that cross-tenant queries return empty context responses.
* **Manual Verification**: Submit queries in the UI chat window and confirm markdown citation links point to correct source documents.
