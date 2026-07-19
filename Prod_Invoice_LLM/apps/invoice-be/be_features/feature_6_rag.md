# Feature 6: Conversational RAG & Thread Management

Construct document indexers and semantic chat clients utilizing vector similarity models and thread state controllers.

### File Coordinates
* RAG Router: [apps/invoice-be/routers/chat.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/chat.py) → `list_sessions()`, `create_session()`, `get_session_messages()`, `post_chat_message()`
* Query Agent: [apps/invoice-be/agents/query_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py) → `run_query_agent()`, `classify_query()`, `execute_generated_sql()`, `get_chat_history()`
* Chroma Client: [apps/invoice-be/chroma_client.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/chroma_client.py) → `query_invoice_chunks()`

### Functionality (folder → file → function → functionality)
1. `routers/chat.py` → `post_chat_message()` — the FE's only write endpoint (`POST /chat/sessions/{id}/message`): saves the user's message row, calls `agents/query_agent.py::run_query_agent()`, then saves the returned assistant message (`content`, `generated_sql`, `citations`).
2. `run_query_agent()` — the orchestrator, not a LangGraph (no graph/state machine here, just sequential Python calls):
   - `get_chat_history(session_id, db_session)` — raw SQL fetch of the last 10 `ChatMessage` rows for this session, formatted as a `Role: content` transcript string. No summarization, no token budget — see Task 6.12.
   - `classify_query(user_message)` — one LLM call with `.with_structured_output(QueryRoutingSchema)` returning `RAG` / `SQL` / `CHAT`; on LLM failure it falls back to a keyword heuristic (`"total"`, `"spent"` → SQL; `"hello"`, `"hi"` → CHAT; else RAG).
   - **SQL route**: one structured-output LLM call generates a SELECT statement (told the `invoice` table schema and the caller's `tenant_id` inline in the prompt), then `execute_generated_sql(sql, tenant_id, db_session)` runs three checks before executing — no mutating keywords, must start with `select`, and `str(tenant_id)` must appear somewhere in the query text (Task 6.6 flags this last check as spoofable, e.g. via a comment) — then formats rows as a Markdown table and asks the LLM for a one-line friendly summary on top.
   - **RAG route**: `chroma_client.py::query_invoice_chunks(tenant_id, user_message, limit=5)` always returns the top 5 chunks (Task 6.7 — no distance cutoff applied yet), which get concatenated into the LLM's context along with dedup'd citation links (`[Source: {vendor} (Page {n})](file:///api/v1/invoices/{id}/pdf)`) appended to the answer text.
   - **CHAT route**: a plain LLM call with the chat-history transcript, no retrieval.

**P0 fix (Jul 19, 2026)**: `QueryRoutingSchema` and `SQLGenerationSchema` were missing `model_config = {"extra": "forbid"}`, meaning their structured-output calls had no `additionalProperties: false` on the generated JSON schema — the same OpenAI strict-mode rejection found in `InvoiceExtractionSchema` (see `feature_2_pipeline_extraction.md`). Fixed by adding `extra="forbid"` to both.

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
- [ ] **Task 6.6: Harden the SQL tenant-isolation guardrail**
  - Replace `execute_generated_sql()`'s substring-match check (`str(tenant_id) not in sql_clean`) with validation against the parsed predicate structure, so an LLM-generated query can't satisfy the check while filtering on something else (e.g. the UUID appearing only in a comment).
- [ ] **Task 6.7: Apply the cosine-distance relevance threshold**
  - `chroma_client.query_invoice_chunks()` must discard chunks past the `0.4` cosine-distance cutoff described in `Database_Schema_Document.md`, instead of always returning the top-5 regardless of score.
- [ ] **Task 6.8: Hybrid retrieval + reranking**
  - Add a keyword/BM25 pass alongside vector search, plus a reranker, before finalizing the top-K context — invoice data is entity/number-heavy (invoice #s, PO #s, exact totals), where exact match often beats pure semantic similarity.
- [ ] **Task 6.9: Self-healing SQL repair loop**
  - Add a bounded retry loop (up to 3 attempts) to `execute_generated_sql()` that feeds a SQL error back to the LLM for repair instead of surfacing it directly to the user.
- [ ] **Task 6.10: Prompt-injection input guard**
  - Add an input filter/classifier in `run_query_agent()` to catch injection attempts (e.g. "ignore previous instructions") before user text reaches the system prompt.
- [ ] **Task 6.11: Semantic/result caching**
  - Cache answers keyed on `(tenant_id, normalized_query)` in Azure Cache for Redis, serving repeated/near-identical questions instantly instead of re-running retrieval + LLM synthesis. (Replaces the `chat_qa_shortcuts` PostgreSQL table approach).
- [ ] **Task 6.12: Real conversational memory**
  - Replace `get_chat_history()`'s raw "last 10 messages" SQL fetch with a token-aware, `PostgresSaver`-backed LangGraph checkpointer.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_rag.py` verifying that cross-tenant queries return empty context responses.
* **Manual Verification**: Submit queries in the UI chat window and confirm markdown citation links point to correct source documents.
