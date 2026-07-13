# Backend Features Progress Tracker

This document tracks the implementation progress of the reconciled backend features for the `invoice-be` component, aligned with the frontend screen requirements. Feature spec files (`feature_1..11_*.md`) describe the target design only — every open item, bug, and pending build task is tracked here instead, so status doesn't drift out of sync across files.

**Current Status:** ~75% complete against [Technical_Architecture_Document.md](../../../Technical_Architecture_Document.md), with 32 open items below.

---

## Feature Tracker

- `[x]` [Feature 1: Multi-Tenant Authentication & Security Scoping](feature_1_auth.md)
- `[x]` [Feature 2: Ingestion, Storage & Extraction Pipeline](feature_2_pipeline_extraction.md) *(merged with former Feature 5 — see doc header)* — ⚠️ known regression, see Gap 24
- `[x]` [Feature 3: Status Tracking & Real-Time SSE Streams](feature_3_sse.md)
- `[ ]` [Feature 3.1: Duplicate Detection & Ingestion UI Refinements](feature_3.1_fix_ftr2_3.md)

- `[x]` [Feature 4: Invoice Queries & PDF Delivery API](feature_4_queries_pdf.md)
- `[x]` [Feature 6: Conversational RAG & Thread Management](feature_6_rag.md)
- `[x]` [Feature 7: Audit Resolution & finalization](feature_7_audit.md)
- `[x]` [Feature 8: Dashboard Metrics & Analytics API](feature_8_dashboard.md)
- `[x]` [Feature 9: Third-Party Connectors & Ingestion](feature_9_connectors.md)
- `[x]` [Feature 10: AI Trainer Sandbox & Rules Registry](feature_10_trainer.md) *(redesigned 2026-07-13 into Global / existing-production-vendor / new-vendor rule scopes — see doc header)*
- `[ ]` [Feature 11: Stripe Billing & Subscriptions API](feature_11_billing.md) — `routers/billing.py` not yet implemented, see Gap 14

> Note: Features 4, 5, 6, 7, 8, 9, 10 are marked `[x]` because the corresponding routers/agents are implemented and functioning — the per-task checkboxes inside those individual files were simply never ticked off after the work landed. That's cosmetic bookkeeping, not a real gap, and has been left as-is rather than backfilled.

---

## Open Items / Gaps

Gaps below are grouped by the feature file whose target design (in `Technical_Architecture_Document.md` and the corresponding `feature_N_*.md`) they still need to catch up to.

**Extraction pipeline** ([feature_2_pipeline_extraction.md](feature_2_pipeline_extraction.md)):
- `[x]` **Gap 1: Complexity Classification Node** — invoice classifier with weighted scoring, routes standard vs. dynamic-schema extraction
- `[x]` **Gap 2: Evaluator Router** — retry logic with feedback-driven fallback to re-extraction
- `[x]` **Gap 3: Critic Node** — field-level confidence review and self-correction feedback loop
- `[x]` **Gap 4: Dynamic QA Node** — custom Q&A generation per invoice on the dynamic-schema path


- `[x]` **Gap 9: Layer 2 Duplicate Detection** — post-extraction `invoice_number` + `vendor_name` match (Layer 1 SHA-256 hash match is done)

- `[x]` **Gap 15: OCR model switch** — move `workers/tasks.py::_run_ocr()` from `prebuilt-layout` to `prebuilt-invoice` (solves Gap 16/17 for free, cuts LLM token volume)
- `[x]` **Gap 16: Bounding-box coordinates** — populate `invoices.coordinates`; the FE auditor UI (`PdfViewerCanvas.tsx`) already renders the overlay and has no data source
- `[x]` **Gap 17: Field-level confidence scores** — populate `invoices.field_confidence` to drive Gap 3's per-field audit routing

- `[x]` **Gap 18: Per-line-item tax/discount math** — extend `verify_line_items_math` beyond top-level totals to `qty × rate × (1 − discount) × (1 + tax)` per line

- `[x]` **Gap 19: Remove fallback fake data** — `get_fallback_extracted_data()` currently returns a mock invoice on LLM/parsing failure instead of routing to `AUDIT_REQUIRED` with an `extraction_failed` alert
- `[x]` **Gap 24: P0 bug — upload endpoint 500s** — `routers/invoices.py` passes `upload_pdf_to_blob_storage(...)`'s return value into `run_in_threadpool` instead of the callable + args; fix by passing them separately. Confirmed via `pytest tests/test_ingestion.py::test_upload_single_pdf`

**Chat / RAG** ([feature_6_rag.md](feature_6_rag.md)):
- `[ ]` **Gap 7: Chat Q&A Registry table** — create `chat_qa_shortcuts` (see `Database_Schema_Document.md`)
- `[ ]` **Gap 10: Custom Q&A Training Registry wiring** — serve instant answers from `chat_qa_shortcuts` before running retrieval
- `[ ]` **Gap 11: Self-Healing SQL Repair Loop** — `execute_generated_sql()` is single-shot; add a bounded (≤3 attempt) LLM-repair retry on SQL errors
- `[ ]` **Gap 13: Global Database Stats in Context** — feed tenant-wide stats into the LLM context for better aggregate answers
- `[ ]` **Gap 20: Harden SQL tenant-isolation guardrail** — `execute_generated_sql()` checks isolation via substring match (`str(tenant_id) not in sql_clean`); validate the parsed predicate structure instead (security-relevant)
- `[ ]` **Gap 21: Enforce cosine-distance relevance threshold** — `chroma_client.query_invoice_chunks()` always returns top-5 regardless of score, despite the documented `0.4` cutoff
- `[ ]` **Gap 22: Hybrid retrieval + reranking** — add a keyword/BM25 pass alongside vector search plus a reranker; invoice data is entity/number-heavy, where exact match often beats pure semantic similarity
- `[ ]` **Gap 23: Real conversational memory** — replace the raw "last 10 messages" fetch with a token-aware, LangGraph-checkpointer-backed history
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
