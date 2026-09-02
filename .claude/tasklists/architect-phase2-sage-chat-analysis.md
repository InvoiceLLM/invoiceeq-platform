# architect — Phase 2 SAGE/Chat detailed review

Founder-approved scope, 2026-09-01. **Analysis only — no code, no infra changes.**
Deep technical + business review of 5 requirements for Phase 2's Chat/SAGE
enhancement, grounded in the actual current architecture, producing a
discussion-ready writeup. Hard stop 45 minutes from start, status emailed to
sbanerji@admsofttech.com every 15 minutes by the orchestrating session.

## Progress

- [x] 1. Upload button for arbitrary financial document types (reconciliation,
      PO, quotation) in the Chat/SAGE screen — current upload UI/pipeline,
      what's reusable vs net-new
      - BACKEND: `agents/extraction_agent.py` is already parameterised on a
        `_DirectionProfile` dataclass (L386-427) selecting schema + prompts +
        required_fields + status vocabulary; `run_extraction_agent` L823-841 takes
        `flow_direction` and its docstring states classification, dynamic QA, the
        verify->extract retry loop and every math check are direction-identical.
        A third profile is the natural extension point, NOT a new pipeline.
        `InvoiceExtractionSchema` L110-134 is invoice-shaped but its spine (party
        name / doc number / date / line items / subtotal / tax / total / currency /
        po_number L121) transfers cleanly to a PO or quotation.
      - `pdf_to_base64_images` L216 and `run_extraction_agent` L847 gate images on
        `.pdf` only — the same boundary phase_2 §2's fitz/PyMuPDF conversion targets.
      - FE: exactly FOUR type=file inputs exist app-wide, all PDF-only.
        `components/ingestion/DropZone.tsx` L24 is the ONLY genuinely shared one
        (accept=".pdf" L121, multiple L120, drag-drop L106-109, 25MB cap L22,
        .pdf guard L58); it is a pure controlled picker that POSTs nothing — the
        parent owns the request (`app/ingestion/page.tsx` L340-349 inbound,
        L244-249 outbound, one file per request).
        `components/trainer/TrainerEntryPanel.tsx` L293 is a second single-file
        variant. `components/trainer/TrainerUploader.tsx` is dead code (zero
        imports; fe tracker L672 says deliberately orphaned). A bulk folder picker
        is inlined in `app/ingestion/page.tsx` L550-589 with no accept attribute at
        all, filtered in JS L569-571.
      - FE chat composer: `InputBar` is co-located INSIDE
        `components/chat/ChatWindow.tsx` L352-437 (not its own file). Whole prop
        surface is onSend(text)/isSending/disabled (L346-350) — no paperclip, no
        file input, no drag-drop, no Paperclip/Upload icon import (L21-34).
        `types/chat.ts` L52-76 has no attachment field on ChatMessage.
        The upload button is genuinely net-new UI; DropZone is liftable.
      - Every BE upload entry point hard-rejects non-PDF by filename suffix:
        `routers/invoices.py` L258, `routers/outbound_invoices.py` L96,
        `routers/trainer.py` L605, `routers/email_ingestion.py` L452 — the same four
        boundaries phase_2 §2 already named.

- [x] 2. Extraction + grounding — how a non-invoice document's content gets
      matched against related invoices/vendor for Q&A
      - Matching primitives already exist in `agents/query_agent.py`:
        `_EXACT_FUZZY_COLUMNS = ("invoice_number", "po_number")` L230,
        `_SUBSTRING_FUZZY_COLUMNS = ("vendor_name", "customer_name")` L231, combined
        as `_FUZZY_STRING_COLUMNS` L232, applied at L277. PO number is already both
        an exact-fuzzy match column AND an extracted field
        (`InvoiceExtractionSchema.po_number`, extraction_agent.py L121).
      - BUT `_normalize_string_equality()` (L247-294) is a regex rewriter over
        LLM-generated SQL, not a general entity resolver — it only rewrites
        col = 'x' into TRIM(LOWER(col)) LIKE LOWER('%x%') inside a statement the
        model already wrote. Reuse means lifting the matching semantics, not calling
        the function. Note CONVENTIONS hard rule 3 / Gap 253 killed a different
        execution-time SQL rewriter — worth a founder ruling before leaning harder.
      - RAG cannot do the linking today. `chroma_client.py::query_invoice_chunks()`
        L535-565 passes NO where-filter at all (isolation is structural, one
        collection per tenant, L537-540), and chunk metadata written at L413-418 is
        only tenant_id/invoice_id/vendor_name/page — no po_number. So "find invoices
        for this PO" is a SQL-side lookup, not a vector one, unless the index gains
        new metadata fields.
      - Routing is a closed 3-way enum: `QueryRoutingSchema.route: Literal["RAG",
        "SQL", "CHAT"]` (L102) and `run_query_agent` dispatches if/elif/else
        (L2903 / L3107). An attached-document question is a FOURTH mode with no slot.
        Worse, the free keyword fast path `_SQL_KEYWORDS` L131 contains "vendor",
        "po number", "purchase order", "total" — the exact vocabulary an attached-PO
        question uses — so it routes to SQL before any LLM call and would silently
        ignore the attachment. Concrete, grounded blocker.
      - MISLEADING FILENAME, IMPORTANT: `services/invoice_reconciliation.py` does NOT
        do business reconciliation. It reconciles Invoice rows against the Azure
        Storage queue (stuck-job sweep): `STUCK_STATUSES` L54,
        `find_stuck_invoices()` L128, `reconcile_stuck_invoices()` L152,
        `force_requeue()` L208. Its only caller is a manual CLI,
        `scripts/reconcile_stuck_invoices.py` L37-40; fe tracker L224 confirms
        "nothing schedules the sweep yet". There is NO document-to-document
        reconciliation logic anywhere in this codebase. Point 2 is genuinely new.

- [x] 3. Suggested next actions based on the attached document's content
      - Two existing "look at data, propose something" patterns, and the better one
        is NOT ops_recommendation.
        (a) TENANT-FACING, closest fit: `routers/dashboard.py` L83-108 —
        `INSIGHT_KIND = Literal["spend_concentration","at_risk_amount","audit_rate",
        "vendor_rules_gap","other"]` L83 and `class DashboardInsight` L88 with
        {title, detail, severity, kind}; produced by GET /dashboard/insights L462 via
        with_structured_output over real aggregates L577-618, Redis-cached,
        dismissible via POST /dashboard/insights/dismiss L637, rendered in
        `components/dashboard/ActionableInsightsPanel.tsx`. It has NO action/link
        field — that is precisely the gap point 3 fills.
        (b) INTERNAL/INFRA: `services/ops_recommendation.py` `@dataclass Finding`
        L342 {field, value, severity, detail, recommendation},
        `CategoryRecommendation` L366, `RecommendationPass` L410, deterministic
        threshold bands L457/L466. Only surfaced as `ops_recommendation` customEvents
        for an Azure Workbook (`mirror_recommendation_pass()` L1258, three a night,
        called from `scripts/run_agent_eval.py` L161). Never touches a router or the
        FE. Borrowable as a shape; nothing concrete transfers.
      - Best structural precedent for the DEEP-LINK half is the Feature 18 triage in
        `routers/chat.py` L829-1103 — already a chat-facing "decide the next step and
        hand the FE the endpoint" machine. `_triage_entry_point()` L909-956 returns
        {next, explanation, invoices, categories}; `triage_message()` L959-1049 does a
        DETERMINISTIC value diff (`_normalize_for_diff` L857-880 over
        `_DIFFABLE_FIELDS` L850-854, which already includes po_number and
        grand_total); `triage_source_verdict()` L1088-1103 returns a `redirect` block
        naming concrete endpoints, which the FE turns into a real deep-link
        (`components/chat/ThumbsDownTriage.tsx` L729-731). Chat already deep-links
        elsewhere too: `components/chat/CitationPill.tsx` L37-38 →
        /invoices/review/{invoice_id}?page={page}.
      - WHAT A SUGGESTION COULD ACTUALLY DO TODAY (real endpoints, not invented):
        inbound approve/reject/reopen/dismiss/correct via PUT /audit/resolve/{id}
        (`routers/audit.py` L364; status validated against exactly
        ["PAID","REJECTED","AUDIT_REQUIRED"] L395); outbound confirm-send
        (`routers/outbound_invoices.py` L188, legal only from VERIFIED/NEEDS_REVIEW
        L216-220) and mark-paid (L251, legal only from SENT L272-276); outbound-audit
        resolve (`routers/outbound_audit.py` L196 — explicitly never changes status,
        L264-266); soft-delete (`routers/invoices.py` L791); batch rollback (L669);
        open-in-Trainer (`routers/trainer.py` L785).
      - WHAT DOES NOT EXIST and would be net-new backend surface: flag /
        mark-for-review / dispute / hold / escalate / snooze / assign — no route
        anywhere. No user-triggered re-run-extraction (only `force_requeue()`,
        CLI-only). No HTTP export/download (`services/invoice_export.py` has no route;
        it fires only inside audit/resolve on PAID, `routers/audit.py` L588-603).
      - Status vocabulary is NOT an enum — `models.py` L111 is `status: str =
        Field(default="PROCESSING")`. Two semantics any suggestion copy must respect:
        OVERDUE is computed at read time, never written (`routers/outbound_dashboard.py`
        L114, `models.py` L164-171); and inbound AUDIT_REQUIRED means a math/data flag,
        NOT unpaid (`agents/query_agent.py` L2386).

- [x] 4. Live/runtime display of backend processing as it happens
      - The streaming mechanism ALREADY EXISTS END TO END, on both sides, and is dark.
        BE: `routers/chat.py::stream_chat_job()` L665-757 — real SSE StreamingResponse
        over Redis Pub/Sub, 120s cap L716, polling fallback when Redis is down
        L700-708, tenant ownership enforced (`_require_owned_chat_job` L595-646,
        Gap 341). `services/chat_queue.py::publish_progress()` L95-131 is the publish
        side. FE proxy: `app/api/chat/jobs/[jobId]/stream/route.ts` L32-40 re-emits
        text/event-stream with X-Accel-Buffering: no.
      - FE IS ALREADY WIRED TOO: `hooks/useChatSession.ts` POSTs L292-295, branches on
        a job_id envelope L300-320, opens an EventSource on the stream route L86-88,
        handles processing/completed/failed L95/L112/L122, falls back to a 2s poll
        (60 attempts, 120s cap) L145-158 + L210, and re-attaches to an in-flight job
        after a page reload L232-241. It already renders the step string as a
        "thinking" label (L95).
      - THE REAL GAP IS CONTENT, NOT TRANSPORT: `queue_worker/handlers.py` publishes
        exactly TWO hardcoded steps — "routing" L1019-1023 and "synthesizing"
        L1038-1042 — one before and one after run_query_agent() L1029. Nothing inside
        the agent publishes anything. tracked_llm_call goes to Azure customEvents, not
        to the job channel.
      - AND IT IS ALL OFF: `ENABLE_ASYNC_CHAT_QUEUE: bool = False` (`config.py` L32),
        deliberately; docstring L26-31 says flip per-environment only once the
        queue/worker/SSE path has real live evidence.
      - EXACT IN-REPO BLUEPRINT FOR THE CONTENT HALF: ingestion already does per-node
        live logging. `extraction_agent.py` L893-902 runs
        graph.stream(initial_state, stream_mode="updates") instead of .invoke()
        specifically so each node transition becomes a real log line
        (`_NODE_LOG_MESSAGES` L815), threaded out via an `on_log` callback param L829;
        `queue_worker/handlers.py` L594-600 implements that callback as an SSE
        log_line publish, plus coarse stage events L618-624. FE consumes it in
        `components/ingestion/LogTerminal.tsx` L66 and `StatusTable.tsx` L142 (backend
        `routers/invoices.py::stream_invoice_status` L482-506, generator L400-479 with
        heartbeats L465 and a Gap 186 ownership check L494-505).
      - CAVEAT THAT SIZES THE WORK: `run_query_agent` (query_agent.py L2742) is a plain
        imperative function, NOT a LangGraph — only extraction is a graph. The
        graph.stream() trick does not transfer. Chat needs explicit publish_progress()
        calls at ~8-10 seams (classify, SQL gen, each SQL retry, execution, summary
        synthesis, RAG retrieve, rerank) plus threading a progress callback into a
        signature that today takes only (session_id, user_message, tenant_id,
        db_session). Mechanical, not architectural.

- [x] 5. Concurrent question handling while a prior question is still processing
      - Sync path (today's default): `post_chat_message()` L340-464 falls through to
        `run_sync_chat_turn()` L467-592, which blocks for the whole turn. Two questions
        = two independent blocking requests; both write ChatMessage rows ordered only
        by created_at (read back created_at.asc() L321-325). Nothing rejects, queues or
        serialises them. The FE prevents it by UI only — the send button is
        disabled while isSending (`components/chat/ChatWindow.tsx` L387-430).
      - Async path (flag-off): enqueue + HTTP 202 at L444-452 is already
        concurrency-shaped; `_chat_background_pool` is a
        ThreadPoolExecutor(max_workers=8) at L37. The FE's `activeStreamRef`
        (useChatSession.ts L41) holds ONE EventSource — a second in-flight job would
        need a listener map, not a single ref.
      - STALE TRACKER CLAIM — the sharpest finding of the review.
        `be_features_tracker.md` L897 says ChatQueueService "limits in-flight chat jobs
        per tenant (PER_TENANT_MAX_ACTIVE_CHAT = 3) via Redis atomic counters
        (chat_inflight:{tenant_id}) to prevent tenant noisy-neighbor starvations and
        Azure OpenAI 429 rate limit spikes." It does not. PER_TENANT_MAX_ACTIVE_CHAT is
        defined at `services/chat_queue.py` L21 and referenced NOWHERE else in the
        application (repo-wide grep, 2026-09-01). `enqueue_chat_job()` L69-89
        increments chat_inflight:{tenant_id} without ever comparing it to the ceiling;
        `get_tenant_inflight_count()` L248-258 is called only from
        `scripts/verify_gap280_architecture.py` L157. The counter is bookkeeping, not a
        limiter. Direct precedent: Gap 352 was exactly this class of defect — a
        declared sandbox meter that did not meter.

- [x] Writeup structured for discussion (not a build plan) — findings + open questions
      per point, cross-referenced against docs/phase_2_enhancements.md §1
      - Delivered as the final chat message to the orchestrating session, per the brief
        (no new file; founder decides where it lands, likely appended to §1).

## Notes / discrepancies found along the way

- `agents/sage_orchestrator.py` (named in the task brief) DOES NOT EXIST. The SAGE
  tool-calling orchestrator was deleted 2026-08-25 (Gap 316) after a live head-to-head;
  its closing record moved into `feature_6_rag.md`. The live SAGE brain is
  `agents/query_agent.py` (3357 lines) + `agents/query_tools.py` + `agents/sage_prompts.py`.
  Confirmed in `agents/query_tools.py` L4-8.
- `services/telemetry.py` (named in the brief) does not exist either — telemetry is a
  top-level module, `apps/invoice-be/telemetry.py`.
- `active-work.md` L18 still points "Frozen / do not touch — SAGE Phase 3" at
  `feature_21_sage.md`, a file the doc summary says was deleted 2026-08-25. The freeze is
  presumably still real; the pointer is stale. Founder to reconcile.
- `apps/invoice-fe/README.md` L75/L108/L127 still describe `hooks/useSSEStream.ts` and
  `hooks/usePolling.ts` with a "6-file threshold". Neither file exists; `hooks/` holds
  only `useAuth.ts` and `useChatSession.ts`, and the 6-file split was removed by Gap 207
  (`components/ingestion/StatusTable.tsx` L122-126).
- `be_features_tracker.md` L897's PER_TENANT_MAX_ACTIVE_CHAT claim is unsupported by code
  (see item 5). senior-dev should either enforce it or correct the tracker — needs its own
  Gap either way, per the no-code-without-gap rule.
- `services/invoice_reconciliation.py` is named for stuck-queue reconciliation, not
  business reconciliation. Anyone scoping point 2 from the filename alone will be misled.
- `components/trainer/TrainerUploader.tsx` is dead code (zero imports, fe tracker L672).

**FINAL STATUS: complete.** All 5 points reviewed against live code with file:line
grounding; writeup returned in chat. No files changed except this tasklist. Two files
named in the brief do not exist and five stale doc claims were found — recorded above
rather than silently worked around.
