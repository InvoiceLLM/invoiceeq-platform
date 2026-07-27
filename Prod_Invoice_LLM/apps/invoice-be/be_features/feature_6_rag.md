# Feature 6: Conversational RAG & Thread Management

Construct document indexers and semantic chat clients utilizing vector similarity models and thread state controllers.

### File Coordinates
* RAG Router: [apps/invoice-be/routers/chat.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/chat.py) → `list_sessions()`, `create_session()`, `get_session_messages()`, `post_chat_message()`, `set_message_feedback()`, `clear_message_feedback()` (Gap 54)
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

**P0 fix (Gap 32, Jul 21, 2026)**: `execute_generated_sql()`'s mutating-keyword check was a raw substring match on lowercased SQL text, which false-triggered on any read-only SELECT referencing a matching column name — e.g. `invoice.created_at` contains "create". Found via `tests/benchmark/` on a simple audit-status question. Fixed with a word-boundary regex (`\bcreate\b` etc.) instead of substring match.

**Task 6.11 implemented (Jul 21, 2026)**: `run_query_agent()` now checks a Redis cache (`get_cached_answer()`/`set_cached_answer()`, keyed on `(tenant_id, normalized_query)`) before doing any routing/retrieval/LLM work, and writes successful SQL/RAG-route results back to it (1-hour TTL). CHAT-route answers and failed lookups are never cached. This supersedes the `chat_qa_shortcuts` Postgres-table plan referenced by the tracker's old Gap 7/10 wording — see `be_features_tracker.md`.

**P0 fix (Gap 34, Jul 22, 2026)**: the Day 1 benchmark's RAG chat sample scored only 12/21 — most failures were the SQL route answering "no records found matching the query criteria" for invoices confirmed to exist in the DB (verified directly against one case). Root cause: `SQLGenerationSchema`'s free-form `WHERE invoice_number = '...'` clause has no guaranteed case/whitespace consistency against the stored value — the LLM generates syntactically valid SQL that just doesn't match. Fixed with two deterministic (non-LLM) layers in `agents/query_agent.py`: (1) `_normalize_string_equality()` rewrites the generated SQL's exact-match filters on `invoice_number`/`vendor_name`/`po_number` (OCR/LLM-sourced columns — `status` is deliberately excluded, it's our own enum) to a case-insensitive, trimmed comparison before execution; (2) `lookup_invoice_by_number_fallback()` — if the generated SQL still returns zero rows and the question names a specific invoice (regex-matched), a direct parameterized lookup runs as a safety net.

**P0 fix (Gap 38, Jul 22, 2026)**: a follow-up clean benchmark re-run showed every failed vendor-name question answering "I can't find this invoice in the provided document extracts," even for invoices confirmed to exist — pointing at misrouting rather than a lookup bug. Root cause: `classify_query()`'s routing prompt described the SQL route as only for "quantitative checks," so a plain field lookup like "who is the vendor on invoice X" doesn't clearly match either route's description and got inconsistently sent to RAG (semantic chunk search — not a reliable way to find one specific invoice's exact field). Fixed by rewriting the routing prompt to state explicitly that SQL covers any structured-field lookup (vendor name, dates, PO number, status), not just aggregates, reserving RAG for genuinely free-text document content; also extended the keyword fallback (`vendor`, `po number`, `purchase order`) used when routing classification itself fails.

**P0 fix (Gap 39, Jul 22, 2026)**: the Day 2 benchmark's RAG chat sample hit two real `500 Internal Server Error` responses on audit_status questions (not grading mismatches). Root cause: the SQL-generation LLM in `run_query_agent()` occasionally hallucinates a column that isn't on `Invoice` (`is_audit_required`, `audit_reason` — the schema prompt only lists real columns; audit info actually lives in `status`/`sa_alerts`). Postgres aborts the whole transaction on the resulting `UndefinedColumn` error, and the SQL-route `except` block built a graceful fallback message but never called `db_session.rollback()` — the poisoned session then broke the *next* operation on it, `chat.py::post_chat_message()` saving that same fallback message, turning a handled failure into an unhandled 500. Fixed with a `db_session.rollback()` in that except block. The column-hallucination itself is a separate, lower-severity prompt-quality issue, not addressed here.

**P2 SQL agent schema context hallucination (Gap 45, found Jul 23, 2026, not yet fixed)**: found during the Day 2 benchmark run (seed=2). The SQL-generation LLM in `run_query_agent()` occasionally generates queries referencing non-existent tables (`audit_flags`) or columns (`is_flagged_for_audit`) on the `invoice` table — the schema prompt in `execute_generated_sql()` lists the real `Invoice` columns but doesn't explicitly state which tables/columns do *not* exist, so the model hallucinates plausible-sounding audit infrastructure. The crash path (Gap 39) is already fixed (`db_session.rollback()`), and the agent gracefully falls back to RAG/keyword search (20/21 chat tests still passed), so this is non-blocking. But it wastes a SQL round-trip and degrades answer quality on audit-status questions. **Fix**: update the schema context prompt in `agents/query_agent.py` to (1) explicitly state that audit status/reasons live in `invoice.status` (enum: `PROCESSING`/`COMPLETED`/`AUDIT_REQUIRED`/`DUPLICATE`) and `invoice.sa_alerts` (JSONB array), not in a separate table, and (2) add a negative instruction like "The database has no `audit_flags`, `audit_logs`, or `audit_reasons` table — do not reference them." This kind of explicit negative constraint reliably suppresses schema hallucination without requiring a SQL parser.

**New capability: Trainer-taught rules now inform Chat answers (Gap 48, Jul 25, 2026)**: until now, `run_query_agent()` had zero connection to `ExtractionTemplate` — committing a Trainer rule (e.g. "tax_amount is CGST+SGST summed") only ever affected future extraction, never how Chat interpreted or explained that same data when a user asked about it, even though the underlying fact is exactly as relevant to both. Added `_get_global_business_rules()` (fetches the tenant's committed Global template's `constraints`) and `_business_rules_block()`, injected into the SQL-generation prompt, the SQL result summary/explanation prompt, and the RAG system prompt. Deliberately Global-scope only — at prompt-build time the question's target vendor isn't known yet (that only resolves after the route runs), so there's no reliable way to pick a vendor-specific template ahead of time. Verified end-to-end: committed a distinctive Global rule via the Trainer sandbox, then asked Chat a question touching that data — both the generated SQL and the natural-language answer correctly reflected the trained rule. Also added `routers/trainer.py::_invalidate_chat_answer_cache()`, called on Global commit/rollback, since Task 6.11's Redis answer cache (1hr TTL) had no way to know a rule changed and would otherwise keep serving pre-rule cached answers for up to an hour.

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
- [x] **Task 6.11: Semantic/result caching**
  - Cache answers keyed on `(tenant_id, normalized_query)` in Azure Cache for Redis, serving repeated/near-identical questions instantly instead of re-running retrieval + LLM synthesis. (Replaces the `chat_qa_shortcuts` PostgreSQL table approach).
- [ ] **Task 6.12: Real conversational memory**
  - Replace `get_chat_history()`'s raw "last 10 messages" SQL fetch with a token-aware, `PostgresSaver`-backed LangGraph checkpointer.
- [x] **Task 6.13: Per-answer chat feedback (Gap 54, 2026-07-27)**
  - New `chat_feedback` table (migration `b2c3d4e5f6a7`): `tenant_id`, `session_id`, `message_id` (unique — one vote per message), `vote` ("up"/"down"). `PUT /chat/messages/{message_id}/feedback` upserts a vote (overwrites, doesn't accumulate); `DELETE` clears it. Both validate message ownership via the parent `ChatSession`'s `tenant_id`, same pattern as `get_session_messages()`. Signal-only — no auto-fix from a vote, mirrors the "correction is a signal, Trainer commit is the action" pattern from the Auditor loop (Gap 26/27). `GET /chat/sessions/{id}` now attaches each message's current vote (`feedback: "up" | "down" | null`) so it survives a reload, via one extra query for the whole session rather than N+1 per message.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_rag.py` verifying that cross-tenant queries return empty context responses.
* **Manual Verification**: Submit queries in the UI chat window and confirm markdown citation links point to correct source documents.
