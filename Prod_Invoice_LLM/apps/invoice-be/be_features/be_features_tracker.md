# Backend Features Progress Tracker

This document tracks the implementation progress of the reconciled backend features for the `invoice-be` component, aligned with the frontend screen requirements. Feature spec files (`feature_1..11_*.md`) describe the target design only — every open item, bug, and pending build task is tracked here instead, so status doesn't drift out of sync across files.

**Current Status:** ~75% complete against [Technical_Architecture_Document.md](../../../Technical_Architecture_Document.md), with 21 open items below. *(Recalculated Jul 19, 2026 — the count had drifted stale after several gaps were closed without the header being updated; Gaps 3 and 4 were also reopened after being found miscredited as done, see below.)*

---

## Feature Tracker

- `[x]` **MAJOR REFACTOR**: Replace Celery with Azure Storage Queues, retain Redis for caching. *(Jul 19, 2026 — closed the last loose end: `main.py` was also running an embedded copy of the queue poller alongside the dedicated `queue-worker` Container App; removed, see `feature_2_pipeline_extraction.md`.)*

- `[x]` [Feature 1: Multi-Tenant Authentication & Security Scoping](feature_1_auth.md)
- `[x]` [Feature 2: Ingestion, Storage & Extraction Pipeline](feature_2_pipeline_extraction.md) *(merged with former Feature 5 — see doc header)*
- `[x]` [Feature 3: Status Tracking & Real-Time SSE Streams](feature_3_sse.md)
- `[ ]` [Feature 3.1: Duplicate Detection & Ingestion UI Refinements](feature_3.1_fix_ftr2_3.md)

- `[x]` [Feature 4: Invoice Queries & PDF Delivery API](feature_4_queries_pdf.md)
- `[x]` [Feature 6: Conversational RAG & Thread Management](feature_6_rag.md)
- `[x]` [Feature 7: Audit Resolution & finalization](feature_7_audit.md)
- `[x]` [Feature 8: Dashboard Metrics & Analytics API](feature_8_dashboard.md)
- `[x]` [Feature 9: Third-Party Connectors & Ingestion](feature_9_connectors.md)
- `[x]` [Feature 10: AI Trainer Sandbox & Rules Registry](feature_10_trainer.md) *(redesigned 2026-07-13 into Global / existing-production-vendor / new-vendor rule scopes — see doc header)*
- `[ ]` [Feature 11: Stripe Billing & Subscriptions API](feature_11_billing.md) — `routers/billing.py` not yet implemented at all; the whole feature is the gap, no dedicated Gap number
- `[x]` [Feature 12: Alembic Database Migrations](feature_12_alembic.md) — verified against a throwaway local Postgres; local/Azure dev DBs still need manual reconciliation before their first `alembic upgrade head`, see doc
- `[ ]` [Feature 13: Automated Test & Benchmark Suite](feature_13_test_benchmark_suite.md) — test tooling spanning Feature 2 (extraction) + Feature 6 (RAG chat); Tier 1 regression suite is built and CI-wired, Tier 2 daily benchmark harness is built but not yet run cleanly (see doc's Benchmark Run Log)

> Note: Features 4, 5, 6, 7, 8, 9, 10 are marked `[x]` because the corresponding routers/agents are implemented and functioning — the per-task checkboxes inside those individual files were simply never ticked off after the work landed. That's cosmetic bookkeeping, not a real gap, and has been left as-is rather than backfilled.

---

## Open Items / Gaps

Gaps below are grouped by the feature file whose target design (in `Technical_Architecture_Document.md` and the corresponding `feature_N_*.md`) they still need to catch up to.

**Extraction pipeline** ([feature_2_pipeline_extraction.md](feature_2_pipeline_extraction.md)):
- `[x]` **Gap 1: Complexity Classification Node** — invoice classifier exists and routes standard vs. complex, but simpler than originally specced: keyword/field-presence match, not weighted layout/tax/line-item scoring *(Task 2.12)*
- `[x]` **Gap 2: Evaluator Router** — retry logic with feedback-driven fallback to re-extraction *(Task 2.16)*
- `[ ]` **Gap 3: Critic Node** — field-level confidence review and self-correction feedback loop. **Reopened Jul 19, 2026**: verified against the actual LangGraph definition — no such node or logic exists. `field_confidence` is populated (Gap 17) but nothing reads it back; this was previously miscredited as done alongside Gap 2 under one combined task. See `feature_2_pipeline_extraction.md` Task 2.32
- `[ ]` **Gap 4: Dynamic QA Node** — custom Q&A generation per invoice on the dynamic-schema path. **Reopened Jul 19, 2026**: verified against the actual code — the `COMPLEX` classification only swaps in a different prompt string against the same fixed schema; no distinct QA-generation step exists. See `feature_2_pipeline_extraction.md` Task 2.33


- `[x]` **Gap 9: Layer 2 Duplicate Detection** — post-extraction `invoice_number` + `vendor_name` match (Layer 1 SHA-256 hash match is done)

- `[x]` **Gap 15: OCR model switch** — move `queue_worker/handlers.py::_run_ocr()` from `prebuilt-layout` to `prebuilt-invoice` (solves Gap 16/17 for free, cuts LLM token volume)
- `[x]` **Gap 16: Bounding-box coordinates** — populate `invoices.coordinates`; the FE auditor UI (`PdfViewerCanvas.tsx`) already renders the overlay and has no data source
- `[x]` **Gap 17: Field-level confidence scores** — populate `invoices.field_confidence` to drive Gap 3's per-field audit routing

- `[x]` **Gap 18: Per-line-item tax/discount math** — extend `verify_line_items_math` beyond top-level totals to `qty × rate × (1 − discount) × (1 + tax)` per line. **Refined Jul 20, 2026**: fixed a false-positive class where invoice-level-only tax got misattributed to every line item — see `feature_2_pipeline_extraction.md` P0 fix log

- `[x]` **Gap 19: Remove fallback fake data** — `get_fallback_extracted_data()` currently returns a mock invoice on LLM/parsing failure instead of routing to `AUDIT_REQUIRED` with an `extraction_failed` alert
- `[x]` **Gap 24: P0 bug — upload endpoint 500s** — `routers/invoices.py` passes `upload_pdf_to_blob_storage(...)`'s return value into `run_in_threadpool` instead of the callable + args; fix by passing them separately. Confirmed via `pytest tests/test_ingestion.py::test_upload_single_pdf`

**Chat / RAG** ([feature_6_rag.md](feature_6_rag.md)):
- `[x]` **Gap 7 + Gap 10: Instant answers for repeated questions**. **Superseded design, Jul 21, 2026**: originally scoped as a `chat_qa_shortcuts` Postgres table (see `Database_Schema_Document.md`), but `feature_6_rag.md`'s Task 6.11 had already decided to replace that with a Redis answer cache — the tracker just never caught up. Implemented Task 6.11 instead: `agents/query_agent.py::get_cached_answer()`/`set_cached_answer()` cache SQL/RAG route results in Redis keyed on `(tenant_id, normalized_query)`, serving repeats instantly without re-running retrieval + LLM synthesis. CHAT-route answers and failed lookups are never cached.
- `[ ]` **Gap 11: Self-Healing SQL Repair Loop** — `execute_generated_sql()` is single-shot; add a bounded (≤3 attempt) LLM-repair retry on SQL errors
- `[ ]` **Gap 13: Global Database Stats in Context** — feed tenant-wide stats into the LLM context for better aggregate answers
- `[ ]` **Gap 20: Harden SQL tenant-isolation guardrail** — `execute_generated_sql()` checks isolation via substring match (`str(tenant_id) not in sql_clean`); validate the parsed predicate structure instead (security-relevant)
- `[ ]` **Gap 21: Enforce cosine-distance relevance threshold** — `chroma_client.query_invoice_chunks()` always returns top-5 regardless of score, despite the documented `0.4` cutoff
- `[ ]` **Gap 22: Hybrid retrieval + reranking** — add a keyword/BM25 pass alongside vector search plus a reranker; invoice data is entity/number-heavy, where exact match often beats pure semantic similarity
- `[ ]` **Gap 23: Real conversational memory** — replace the raw "last 10 messages" fetch with a token-aware, LangGraph-checkpointer-backed history
- `[x]` **Gap 32: Mutating-SQL guardrail false positive** — found and fixed Jul 21, 2026 via `tests/benchmark/`. `execute_generated_sql()`'s mutating-operation check (`agents/query_agent.py`) was a raw substring match on lowercased SQL text, which false-triggered on read-only SELECTs merely referencing a matching column name — e.g. `Invoice.created_at` contains "create". A simple audit-status question got rejected as a forbidden mutating query. Fixed with a word-boundary regex (`\bcreate\b` etc.) instead of substring match — still a keyword check, not a real SQL parser (that class of fix is tracked under Gap 20), but no longer false-triggers on column names.
- Prompt-injection input guard — not yet wired into `run_query_agent()`

**Trainer sandbox** ([feature_10_trainer.md](feature_10_trainer.md) — redesigned 2026-07-13 into Global / existing-production-vendor / new-vendor rule template scopes):
- `[ ]` **Gap 1b: Global rule template scope** — tenant-wide, vendor-agnostic rules (e.g. "VAT is a tax item after discount"); requires nullable `vendor_name` on `ExtractionTemplate` (Task 10.1) + new session/commit routes (Tasks 10.2, 10.6)
- `[ ]` **Gap 5: Session Management** — move `TRAINER_SESSIONS` off the in-process dict onto Redis (TTL-bound), required once `invoice-be` runs multi-replica *(Task 10.9)*
- `[ ]` **Gap 6: Initialize from Production** — load existing production invoices into the sandbox for training *(Task 10.3)*
- `[ ]` **Gap 8: Commit with Re-audit** — `trainer_commit()` saves rules but doesn't yet trigger the documented background re-evaluation of matching production invoices *(Task 10.7)*
- `[ ]` **Gap 29: No rule versioning/rollback** — `ExtractionTemplate` rows are overwritten on commit with no history; a bad Global rule affects every vendor and can't currently be diagnosed or reverted *(Task 10.10)*

**Audit resolution** ([feature_7_audit.md](feature_7_audit.md)):
- `[ ]` **Gap 26: Audit corrections are not captured** — the Auditor console is read-only end-to-end today (no field edits, no correction data captured), so there's no signal for the trainer loop to learn from *(Task 7.3)*
- `[ ]` **Gap 27: No audit→trainer feedback loop** — recurring corrections on the same field aren't detected or surfaced as a rule suggestion; depends on Gap 26 *(Task 7.4, and Task 10.11 in `feature_10_trainer.md`)*

**Dashboard** ([feature_8_dashboard.md](feature_8_dashboard.md)):
- `[ ]` **Gap 28: No trainer impact visibility** — no metrics exist showing rules trained, audit-rate improvement, or which vendors still need a rule, so the trainer's payoff is invisible and adoption stays low *(Task 8.3)*
- `[ ]` **Gap 30: No actionable-insights generation endpoint** — `GET /dashboard/metrics` (Task 8.1) only returns numeric aggregates; nothing generates the AI-written strategic-recommendations text that `fe_features/feature_2_dashboard.md` Gap 4 (Actionable Insights Panel) needs *(new — needed to unblock fe_features_tracker.md Gap 4)*

**Auth & tenancy** ([feature_1_auth.md](feature_1_auth.md), [Database_Schema_Document.md](../../../Database_Schema_Document.md)):
- `[x]` **Gap 14: `users` table** — no `User` SQLModel exists yet; `user_id`/`role` are read from JWT claims only and never persisted, `AuditLog.actor_user_id` isn't FK-backed. Blocks Website Feature 4 (domain-based provisioning) and proper user-attributed audit logs — build this first
- `[x]` **Gap 25: Consolidate tenant auto-provisioning** — `routers/invoices.py` has an undocumented fallback that creates a bare `Tenant` row on first upload; once the real domain-matching/role-assignment login flow (Website Feature 4) lands, remove this fallback to avoid two divergent tenant-creation paths

**API endpoints**:
- `[ ]` **Gap 12: Directory Watcher Start Endpoint** — `POST /api/watcher/start` for bulk/automated ingestion

- `[x]` **Gap 31: India/GST invoice math verification gaps** — found Jul 20, 2026, fixed Jul 21, 2026, verified end-to-end (not just unit tests) via `tests/e2e/test_e2e_regional_invoices.py::vertex_india_gst_complex`. Four issues fixed in `utils/verification_tools.py` + `agents/extraction_agent.py`: (1) added a `REL_TOLERANCE` (0.5%) alongside the flat `0.01` absolute tolerance; (2) `verify_totals_math` accepts either the pre-discount or post-discount subtotal convention; (3) added a `round_off` field to `InvoiceExtractionSchema`, threaded into `verify_totals_math`, plus tightened `tax_amount`/`subtotal` field descriptions (sum CGST+SGST, use printed subtotal as-is); (4) found only via the real end-to-end run: `verify_line_items_math`'s subtotal-reconciliation check now accepts either pre-tax line amounts (matches subtotal directly) or post-tax line amounts (matches subtotal + invoice tax_amount). See `feature_2_pipeline_extraction.md` for the full analysis.
- `[x]` **Gap 33: Extraction faithfulness on internally-inconsistent totals** — found Jul 21, 2026, prompt-only mitigation (tightened `grand_total` field description) left a ~1-in-5 residual rate, confirmed live by the Day 1 benchmark run (Jul 22, 2026: 5/30 invoices showed this exact pattern — expected `AUDIT_REQUIRED`, got `COMPLETED`). Prompt tuning alone can't close this — it's asking the LLM not to do something it's stochastically prone to doing. Closed instead with a deterministic, LLM-independent guardrail: `utils/verification_tools.py::verify_grand_total_in_source_text()` checks whether the extracted `grand_total` (in a few plausible printed forms — with/without thousands separator, 0-2 decimals) appears verbatim anywhere in the raw OCR text, called from `agents/extraction_agent.py::verify_node` alongside the existing math checks. A silently "corrected" total was never actually printed on the document, so it fails this check even when it's internally self-consistent (which is exactly the case `verify_totals_math` alone cannot catch, since a self-corrected total always reconciles with itself). Also benefits from the existing retry loop — a failed faithfulness check routes back to `extract` before finally landing on `AUDIT_REQUIRED`.
- `[x]` **Gap 34: RAG chat SQL-lookup non-determinism** — found Jul 22, 2026 via the Day 1 benchmark's RAG chat sample (12/21 pass rate; most failures were "no records found matching the query criteria" for invoices confirmed to exist in the DB). Root cause: `agents/query_agent.py`'s text-to-SQL generation produces a free-form `WHERE invoice_number = '...'` clause per question, with no guarantee of case/whitespace consistency against the stored value. Fixed two ways, both deterministic (no re-prompting): (1) `_normalize_string_equality()` rewrites LLM-generated exact-match filters on OCR/LLM-sourced text columns (`invoice_number`, `vendor_name`, `po_number` — deliberately excludes `status`, which our own code writes and should stay exact) to a case-insensitive, trimmed comparison before execution; (2) `lookup_invoice_by_number_fallback()` — if the generated SQL still finds zero rows and the user's question plainly names a specific invoice (regex-matched), a direct parameterized lookup runs as a safety net, bypassing free-form SQL generation entirely for that case.
