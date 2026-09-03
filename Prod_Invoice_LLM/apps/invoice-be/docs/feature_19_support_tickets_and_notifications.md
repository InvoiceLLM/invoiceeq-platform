# Feature 19: Support Ticket Engine, AI Support Agent & Notification Email Dispatch

**Status:** Built 2026-08-17 (commit `fc48ef0`) — all 5 tasks landed, with two deviations from this spec recorded in §4. Status/verification state lives in `be_features_tracker.md` (Gaps 246/247/248); this doc is the design record.  
**Target Application:** `invoice-be`  
**Related Frontend Specs:** `apps/invoice-fe/docs/feature_15_help_center_support_bot_and_tickets.md`, `apps/invoice-website/website_features/feature_5_contact_us.md`  
**Primary Notification Inbox:** `sbanerji@admsofttech.com` (alias: `invoice@admsofttech.com`, migrated from legacy `Application@infinevocloud.com` on 2026-08-26)

---

## 1. Overview & Objective

Provide the backend support ticketing, conversational AI troubleshooting agent, and email dispatch services:
1. **`SupportTicket` Data Model & Alembic Migration**: Persist customer inquiries and escalations with tenant isolation, unique ticket numbering (`TICK-YYYY-XXXX`), and chat transcript attachments.
2. **AI Support Agent (`agents/support_agent.py`)**: Knowledge base agent equipped with platform documentation context that evaluates confidence and outputs ticket suggestion triggers when an issue cannot be resolved.
3. **Multi-Channel Email Dispatch Service (`services/support_email.py`)**: Sends rich HTML & plain-text email alerts to `Application@infinevocloud.com` and auto-acknowledgement receipts to users.
4. **Support Router (`routers/support.py`)**: Endpoints for public website contact, authenticated chat, and ticket creation.

---

## 2. File Coordinates

* **Data Model:** `apps/invoice-be/models.py` — `SupportTicket` (SQLModel table, `__tablename__ = "supportticket"`), appended at end of file.
* **Alembic Migration:** `apps/invoice-be/alembic/versions/6c60f6e907a0_add_support_ticket_table.py` — creates the `supportticket` table. *(Spec originally guessed the filename as `*_add_support_tickets.py`; the real revision is `6c60f6e907a0`.)*
* **Main Application:** `apps/invoice-be/main.py` — imports `support` and calls `app.include_router(support.router, prefix="/api/v1")`.
* **Configuration:** `apps/invoice-be/config.py` — `SUPPORT_NOTIFY_EMAIL: str = "Application@infinevocloud.com"` on the settings model, overridable by env var.
* **Unit & Integration Tests:** `apps/invoice-be/tests/test_support.py` — 20 test functions, 22 collected cases (`test_missing_required_field` is `@pytest.mark.parametrize`'d over `name`/`email`/`message`).

### `agents/support_agent.py` — what's actually in it

The whole module is **one public function plus two module-level data tables**. It is deliberately deterministic: there is no LLM call, no embedding, and no vector store anywhere in this file.

* `KNOWLEDGE_TOPICS: list[dict]` — the hardcoded platform knowledge base. Each entry is `{id, keywords, category, title, guidance}`, where `guidance` is a pre-written Markdown answer. **12 topics as of Gap 254 (2026-08-19), up from 7**: account/auth, Trainer rules, Auditor console, email ingestion, connectors/webhooks, billing, export/reports, plus the five added for Gap 254 — `ingestion_upload`, `invoice_statuses`, `dashboard_analytics`, `user_management`, `security_retention`.
* `ERROR_TRIGGERS: list[dict]` — regex-matched severe-failure patterns (`{pattern, message, category, priority, subject, error_code}`) for things like 504 gateway timeouts, PayU billing exceptions, and stalled OCR processing. A match is what produces an escalation with a pre-filled `error_code`. **These are matched *after* `KNOWLEDGE_TOPICS` and the KB path returns early, so a KB keyword that overlaps an error phrasing makes that trigger unreachable** — that is not a theoretical risk, it was live: `billing`'s `"payu"` and `"checkout"` keywords meant `ERR_PAYU_BILLING_FAILURE` could never fire (fixed in Gap 254, both keywords removed). `tests/test_support.py::test_error_triggers_are_not_shadowed_by_kb_keywords` is a standing screen over every trigger phrasing so a future keyword addition fails there instead of in production.
* `_score_topic(topic, lower_query) -> tuple[int, int]` — `(number of keywords matched, total length of those matched keywords)`. Matching is **word-boundary regex with a `MIN_KEYWORD_LENGTH` of 3**, not substring: the original `kw in lower_query` matched `"id"` inside "confidence"/"provide" and `"pro"` inside "processing", making `account_auth` the de facto wrong-answer default. The second tuple element is the tie-break and is the other half of that fix — hit count alone is not a confidence measure, so a topic winning on one very generic hit used to beat an equally-scoring topic with a longer, more specific phrase match purely because it sat earlier in the list ("Is my data encrypted at rest?" → the CSV export guide). Total matched-keyword length is a cheap specificity proxy: `"at rest"` beats a bare `"data"`. The over-generic `"data"` keyword was also dropped from `export_reports` outright.
* `evaluate_support_query(message: str, history: list[dict] | None = None, last_topic_id: str | None = None) -> dict` — **the only public entry point.** Returns `{answer, topic_id, suggest_escalation, low_confidence, escalation_context}`. Resolution order, solution-first by design, **5 steps as of Gap 256 (2026-08-19)**: (1) empty input → SAGE greeting, no escalation; (2) score the query against every `KNOWLEDGE_TOPICS` entry via `_score_topic()` and return the highest-scoring topic's `guidance` with `topic_id` set and **no** escalation — a question the knowledge base can answer never becomes a ticket; (3) if no direct match and `last_topic_id` is present and the query is an anaphoric follow-up (`_FOLLOW_UP_PHRASES` / `_is_anaphoric_follow_up()`), return that topic's `guidance` with its `topic_id`; (4) `ERROR_TRIGGERS` regex match → that trigger's message plus `suggest_escalation=True` and a fully populated `escalation_context`; (5) an explicit human-help request (`human|agent|raise ticket|support ticket|contact support|speak to someone|talk to human`) → escalate as `TECHNICAL_SUPPORT`/`NORMAL`; (6) fallback → an honest "I couldn't find a specific help article" with `suggest_escalation=False` **and `low_confidence=True`**.
  * **`suggest_escalation` and `low_confidence` are separate flags on purpose (Gap 254).** The fallback used to set `suggest_escalation=True`, so an unanswered question rendered in the same red "Issue Diagnosis & Recommended Escalation" framing as a genuinely detected incident. Setting it to `False` alone would have removed the only *contextual* in-chat way to raise a ticket from a miss, so `low_confidence` now drives a separate neutral "Didn't find an answer? / Raise a Ticket" card in `apps/invoice-fe/components/help/SupportChatWindow.tsx`. The fallback still returns a populated `escalation_context` (`TECHNICAL_SUPPORT`/`NORMAL`, subject = the user's own question) purely so that card can prefill the ticket modal. `SupportChatResponse.low_confidence` defaults to `False`, so an FE build that ignores it behaves exactly as before.
  * **`topic_id` / `last_topic_id` follow-up contract (Gap 256, fixed 2026-08-19).** `SupportChatResponse.topic_id` echoes which `KNOWLEDGE_TOPICS` entry matched (or `None`). `SupportChatRequest.last_topic_id` carries it forward from `SupportChatWindow.tsx` on the next turn so anaphoric follow-ups ("how do I do that?", "tell me more") resolve against the prior topic after the direct keyword pass misses. **`history` remains accepted but unread** — only `last_topic_id` resolves follow-ups. A removed Gap 254 workaround that re-matched the assistant's own prior guidance text against `KNOWLEDGE_TOPICS` was rejected because guidance blobs are keyword-dense and would resolve to the wrong topic. **Verification:** `tests/test_support.py::TestSupportChatEndpoint` 15 passed including 4 Gap 256 cases; FE stores `topicId` per assistant message and sends `last_topic_id` on the next request.

### `services/support_email.py` — what's actually in it

* `dispatch_support_ticket_email(ticket) -> dict` — **the only public function.** Sends both emails for one `SupportTicket` and returns `{"staff_alert": {...}, "user_receipt": {...}}`, each sub-dict being `{"status": "sent"|"skipped"|"error", ...}`. Calls `sendgrid_configured()` first and short-circuits to `"skipped"` when there's no API key; each of the two sends is independently wrapped in `try/except` so a failure is reported as `"error"` and never raised at the caller. The ticket row is already committed before this is called, so mail never rolls back a ticket.
* `_ticket_html(ticket) -> str` — builds the staff-alert HTML body: priority badge, submitter/tenant/company metadata table, the description block, and the chat transcript table when `ticket.chat_transcript` is non-empty.
* `_receipt_html(ticket) -> str` — builds the submitter acknowledgement body: reference number and the SLA line (2 hours for `URGENT`, 24 hours otherwise).
* `_priority_badge(priority: str) -> str` — inline-CSS pill span for the priority; falls back to grey for an unknown value.
* `_PRIORITY_STYLES`, `_CATEGORY_LABELS`, `_SOURCE_LABELS` — module-level lookup dicts for badge colours and human-readable category/source names.
* Dependencies: `send_email()` and `sendgrid_configured()` from the pre-existing `services/outbound_email.py`; `get_settings()` from `config.py` for `SUPPORT_NOTIFY_EMAIL`.

### `routers/support.py` — what's actually in it

* `router = APIRouter(tags=["Support"])`; registered under `/api/v1` in `main.py`.
* `_generate_ticket_number(prefix: str) -> str` — `"{prefix}-{year}-{4 random digits}"`. Random, not sequential, so total ticket volume isn't publicly enumerable.
* `_unique_ticket_number(db, prefix, max_attempts=10) -> str` — retries `_generate_ticket_number()` until the value is unused.
* Request/response models: `ContactInquiryRequest`, `AppTicketRequest`, `SupportChatRequest` (gained `last_topic_id: str | None = None` in Gap 256), `SupportChatResponse` (gained `low_confidence: bool = False` in Gap 254; gained `topic_id: str | None = None` in Gap 256), `TicketResponse`.
* `submit_contact_inquiry()` — `POST /support/contact`, **public/unauthenticated**, `source="WEBSITE_CONTACT"`, `INQ-` prefix.
* `support_chat_assistant()` — `POST /support/chat`, auth via `get_tenant_context_allow_unpaid`; thin wrapper over `evaluate_support_query()`.
* `submit_app_ticket()` — `POST /support/ticket`, same auth; `source` is `HELP_CHATBOT` or `DIRECT_TICKET`, `TICK-` prefix, persists `chat_transcript`.
* `list_support_tickets()` — `GET /support/tickets`, same auth; returns the calling tenant's own tickets only.
* Both ticket-creating endpoints (`submit_contact_inquiry`, `submit_app_ticket`) call `dispatch_support_ticket_email()` inside a `try/except`, so an email outage still returns 201 with `email_dispatched: false` on the `TicketResponse`.

---

## 3. Schema & API Specification

### 3.1 Data Model: `SupportTicket`
```python
class SupportTicket(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    ticket_number: str = Field(max_length=32, unique=True, index=True)
    tenant_id: UUID | None = Field(default=None, index=True, nullable=True)
    user_id: UUID | None = Field(default=None, nullable=True)
    user_email: str = Field(max_length=255, index=True)
    user_name: str | None = Field(default=None, max_length=255)
    
    source: str = Field(default="DIRECT_TICKET", max_length=32) # WEBSITE_CONTACT | HELP_CHATBOT | DIRECT_TICKET
    category: str = Field(default="GENERAL", max_length=64)     # BILLING | EXTRACTION | TRAINER | INGESTION | BUG | etc.
    priority: str = Field(default="NORMAL", max_length=32)      # LOW | NORMAL | HIGH | URGENT
    
    subject: str = Field(max_length=255)
    description: str
    invoice_id: UUID | None = Field(default=None, nullable=True)
    chat_transcript: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    
    status: str = Field(default="OPEN", max_length=32)          # OPEN | IN_PROGRESS | RESOLVED | CLOSED
    admin_notes: str | None = Field(default=None)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

> **As-built correction, 2026-08-18.** The block above is the original target schema; the shipped `SupportTicket` in `models.py` differs in two places: there is **no `invoice_id`** column, and there **is** a `company_name: str | None` column (fed by the website contact form's optional Company field). Shipped `category` values are the 5 in `_VALID_CATEGORIES` (`SALES | TECHNICAL_SUPPORT | BILLING | PARTNERSHIP | GENERAL`), not the `BILLING | EXTRACTION | TRAINER | INGESTION | BUG` set sketched in the comment; shipped `priority` is `LOW | NORMAL | URGENT` with no `HIGH`.

### 3.2 Endpoints (`routers/support.py`)
1. `POST /api/v1/support/contact`: Public endpoint for website inquiries. **Built and rate-limited** (Gap 249, closed 2026-08-18 after a hardening pass on the same day — the first attempt was implemented but bypassable). Two layers:
   - **Backend (authoritative).** `_ContactRateLimiter` in `routers/support.py` enforces a sliding window of 5 submissions per 5 minutes, keyed on *both* origin IP and submitter email, returning `429` with `Retry-After: 300`. State lives in Redis (one sorted set per key, `ZREMRANGEBYSCORE`/`ZCARD` to read, `ZADD`+`EXPIRE` to record), so the window is shared across all backend replicas — the app scales to `maxReplicas: 5`, and a purely in-process limiter would have meant an effective limit 5x the configured one. The `EXPIRE` on every write is also what bounds the keyspace. If Redis is unreachable the limiter degrades to a bounded in-process window (same `_get_redis`-with-fallback pattern as `services/trainer_sessions.py`) rather than failing open or 500-ing; that fallback prunes out-of-window keys on every check and caps total tracked keys at `_MEMORY_MAX_TRACKED_KEYS`, so it cannot become a memory-exhaustion vector. **Caveat:** while running on that fallback the window is per-replica again, so the effective limit is up to `replicas x 5` until Redis returns.
   - **Website proxy (best-effort edge shedding).** `apps/invoice-website/app/api/contact/route.ts` keeps its own 5-per-10-minutes in-memory window, now with the same pruning and a `PROXY_MAX_TRACKED_IPS` cap. This layer is explicitly *not* authoritative: the website scales 0–3 with scale-to-zero, so a cold start wipes it.

   **The rate-limit key.** Both layers resolve the client IP via `_get_client_ip` / `resolveClientIp`, which deliberately do **not** take the leftmost `X-Forwarded-For` entry — that is the value the client supplied, so rotating it per request reset both windows and defeated the limiter entirely. Order of trust: (1) `X-Azure-ClientIP`, but only when `X-Azure-FDID` matches a configured `FRONT_DOOR_ID` (unset today — Front Door is gated on `customDomainName` in `infra/08-apps.bicep` and is not deployed, so these headers are currently ignored as forgeable); (2) `X-Client-IP`, which the website proxy sets from its own resolution and never forwards from the browser — needed because on the proxy→backend hop the platform-appended `X-Forwarded-For` entry is the website's pod IP, which would bucket every visitor together; (3) the **rightmost** valid `X-Forwarded-For` entry, i.e. the hop Container Apps' Envoy ingress actually observed; (4) the socket peer. `X-Real-IP` is deliberately not consulted. Every candidate must parse as a real IP (`_parse_ip`), so junk cannot become an unbounded-cardinality key.

   **Subject length.** The subject is built as `f"[{category}] Contact inquiry from {name}"` and truncated to `_SUBJECT_MAX_LENGTH` (255) at construction, matching `SupportTicket.subject`'s `max_length=255`. `name` is independently capped at 255, but the category prefix adds another 31–41 characters on top, so a long-but-legal name previously produced an over-length subject and a Postgres `StringDataRightTruncation` → uncaught 500. Truncation is done at the point of construction rather than by lowering `name`'s cap so that a future change to the prefix format cannot silently reintroduce it.
2. `POST /api/v1/support/chat`: Authenticated Help Center support chatbot query endpoint. **Built.**
3. `POST /api/v1/support/ticket`: Authenticated ticket creation endpoint (accepts pre-filled transcript from chat). **Built.**
4. `GET /api/v1/support/tickets`: List tenant's active and historical tickets. **Built.**
5. `GET /api/v1/support/tickets/{ticket_id}`: Retrieve detailed ticket status. **Not built** — the router has four routes, not five. Nothing on the frontend calls a single-ticket endpoint today, so this was left for whenever a ticket-detail view is actually needed.

### 3.3 Email Notification Service (`services/support_email.py`)
- Sends styled HTML notification to `Application@infinevocloud.com` with ticket reference, submitter info, tenant ID, priority, full description, and formatted conversation transcript.
- Sends auto-acknowledgement email to the submitter.

---

## 4. Tasks

- [x] **Task 19.1: Define `SupportTicket` Model & Alembic Migration** — Done 2026-08-17. `SupportTicket` added to `models.py`; migration `6c60f6e907a0_add_support_ticket_table.py` creates `supportticket`. Deviations from §3.1 recorded there: no `invoice_id`, added `company_name`.
- [x] **Task 19.2: Implement `services/support_email.py` Email Engine** — Done 2026-08-17. `dispatch_support_ticket_email()` plus the three private template helpers, layered on the pre-existing `services/outbound_email.py` SendGrid client rather than a new one. Degrades to `{"status": "skipped"}` with no API key, and reports per-message `"error"` instead of raising, so a mail outage can't fail a ticket that's already persisted.
- [x] **Task 19.3: Build `agents/support_agent.py` Knowledge RAG & Escalation Logic** — Done 2026-08-17, **but not as "Knowledge RAG"**. This is the one substantive design deviation in the feature: `evaluate_support_query()` is a deterministic keyword-scoring + regex matcher over the hardcoded `KNOWLEDGE_TOPICS` / `ERROR_TRIGGERS` tables. There is no retrieval, no embedding, no vector store and no LLM call in the module. Escalation logic itself works as specced (solution-first: a knowledge-base hit never escalates; error triggers and explicit human-help requests always do). Anywhere this feature's docs say the assistant is "RAG-powered" or "streams answers", read it as target design that was not built.
  - **Gap 403 (filed 2026-09-02, built 2026-09-02) — hybrid vector fallback, not full RAG.** External defect review item H-04 (A) asked for real vector search / prompt-context retrieval in place of the keyword-scoring matcher above. **Scoped down from the original "Knowledge RAG" ask, by explicit founder decision**: this is a semantic **fallback**, not a replacement — the keyword pass above is completely untouched and still decides first. Only a query that scores **zero** keyword hits, and that is not an error trigger or an explicit human-help request (both of those are also checked first and remain exactly as deterministic as before), now gets one more chance: `_vector_match_topic()` embeds the query, queries a new shared (non-tenant — platform documentation is identical for every tenant) Chroma collection (`support_knowledge_topics`, cosine space, reusing `chroma_client.py`'s client/embedding singletons) seeded from `KNOWLEDGE_TOPICS`' titles + keywords, and returns the best match if it clears `SUPPORT_RELEVANCE_DISTANCE_THRESHOLD` (0.35). There is still **no LLM call** anywhere in this module — a semantic hit returns the same pre-written `guidance` text a keyword hit would have, just resolved by a different matching mechanism. Any Chroma/embedding failure degrades to the pre-Gap-367 behaviour (falls through to the generic miss) rather than raising.
  - **Threshold is a stated starting point, not an empirical derivation.** Unlike Gap 244's `RELEVANCE_DISTANCE_THRESHOLD` (0.49, derived from a labelled invoice-retrieval dataset), there is no equivalent labelled dataset for support topics — `SUPPORT_RELEVANCE_DISTANCE_THRESHOLD = 0.35` was chosen as a deliberately conservative (only-accept-a-confident-match) default and documented in-code as needing live tuning against real traffic, not presented as scientifically grounded.
  - **Verified — `tests/test_support.py`, 75 passed** (all pre-existing cases unmodified, plus 5 new in `TestSupportAgentVectorFallback`), run in isolation against in-memory SQLite with `MOCK_EMBEDDINGS=true` (this file's existing convention did not previously need to set that flag; it does now). The new tests prove, not just assert: (1) the mock embedding path's high-dimensional random vectors never produce a false-positive semantic match, which is why every pre-existing "should miss" test still passes unmodified; (2) a paraphrase sharing zero keywords with any topic resolves to the correct topic once semantic distance is controlled to be small (monkeypatched embeddings — real mock vectors carry no semantic meaning to test against, per Gap 244's process lesson); (3) and (4) a call-counter proof that the vector step is never even invoked when a keyword match or an error trigger already decided the response; (5) a Chroma/embedding failure degrades to the existing miss rather than raising. **Not done, not claimed**: no live/manual run against the real `BAAI/bge-m3` model — whether real embeddings actually resolve real-world paraphrased domain questions well in practice (as opposed to the mechanism being wired correctly) has not been measured, and the threshold above is exactly the kind of value that run would need to validate or correct. No Postgres involved in this change (Chroma + static in-memory topic data only, no DB model/migration touched), so this repo's Hard Rule 2 (Postgres is the only test evidence) does not apply here.
  - **Full backend suite re-run for regression, 2026-09-02: 25 failed, 1773 passed, 3 skipped, 4 errors, 177.65s.** Checked every failure individually against this change's actual diff (`agents/support_agent.py` + `tests/test_support.py` only, zero DB/model/router edits) before concluding none are caused by it: the bulk are pre-existing `*_on_postgres` tests across unrelated files (`test_auth.py`, `test_autopilot.py`, `test_chat_queue.py`, `test_connectors.py`, `test_sandbox_keys.py`, `test_widget_token.py`, `test_workflow_drive_archive.py`, `test_workflow_email_summary.py`) failing with `column tenant.api_key_scope does not exist` — this local Postgres instance's schema is behind a migration, an environment issue this task did not create and does not touch; `test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message` is the already-documented pre-existing failure recorded under Gap 354 above; the rest (`test_benchmark_artifacts.py`, `test_ops_recommendation.py`, two more `test_connectors.py` cases) are unrelated telemetry/ops-workbook/Google-Drive subsystems. `tests/test_support.py` itself contributed zero failures to this run.
  - **Superseded 2026-09-03 by Gap 422 — the untuned threshold above never actually fired.** Manual QA found the semantic fallback silently dead: measured against the real `BAAI/bge-m3` model (the "not done, not claimed" live run flagged directly above), genuine paraphrase matches sit at **0.31–0.53** distance, so nothing could ever clear `SUPPORT_RELEVANCE_DISTANCE_THRESHOLD = 0.35` and every non-keyword query fell through to the generic miss. A second, independent fault in the same code: `_topic_embedding_text()` embedded `title + keyword list`, so ranking followed shared vocabulary rather than topic relevance. Gap 422 re-embedded topics as **title + prose guidance**, empirically derived the threshold at **0.52** with a **0.012 margin guard** (`scripts/measure_support_retrieval.py`, committed), and fixed a related bug where the seeded Chroma index could never be refreshed after a `KNOWLEDGE_TOPICS` edit. Full write-up: `be_features_tracker.md` Gap 422.
- [x] **Task 19.4: Implement `routers/support.py` Endpoints and Register in `main.py`** — Done 2026-08-17 for **4 of the 5** endpoints in §3.2; `GET /support/tickets/{ticket_id}` was not built. Router registered in `main.py` at `/api/v1`.
- [x] **Task 19.5: Automated Test Suite (`tests/test_support.py`)** — Done 2026-08-17. 20 test functions / 22 collected cases against in-memory SQLite with the email dispatcher mocked, covering contact-form validation and persistence, ticket-number format for both prefixes, transcript persistence, tenant-scoped listing, chat escalation triggers, and the email-failure-still-returns-201 path.

---

## 5. Verification Plan

* **Automated Tests:** Run `pytest tests/test_support.py` verifying contact inquiry creation, authenticated ticket dispatch, chat evaluation, and email formatting.
* **Manual Verification:** Submit test ticket and verify DB persistence, ticket number generation, and receipt in `Application@infinevocloud.com`. *(§5 originally said "sequential ticket number generation" — the shipped `_generate_ticket_number()` is deliberately **random**, not sequential, so there is nothing sequential to verify.)*

### 5.1 Actual verification state (recorded 2026-08-18, updated 2026-08-26)

* **Reported by the branch author, 2026-08-17:** `tests/test_support.py` 22/22 passing.
* **Live SendGrid Delivery Verified (2026-08-26):** Dispatched live notifications to `sbanerji@admsofttech.com` using active SendGrid production API key with sender `invoices@outbound.invoicellm.admsofttech.com` and `Reply-To: invoice@admsofttech.com` (`HTTP 202 Accepted`, Message ID `LbvTNInKRuafc7A2jHXORw`, 0 bounces). Live email delivery to staff confirmed operational.

### 5.2 Gap 254 verification (2026-08-19)

* `tests/test_support.py` — **66 passed**, run with `.venv/Scripts/python.exe -m pytest tests/test_support.py -q`. New behavioural cases: `test_word_boundary_matching_prevents_substring_collisions`, `test_new_knowledge_topics` (one probe per added topic), `test_generic_keyword_does_not_beat_a_more_specific_topic` (the "Is my data encrypted at rest?" case from the gap report, verified against that exact wording), `test_low_confidence_fallback_is_not_framed_as_a_diagnosed_incident`, `test_answered_and_escalated_paths_are_not_low_confidence`, `test_history_is_accepted_but_deliberately_unread`, `test_error_triggers_are_not_shadowed_by_kb_keywords`. The pre-existing `test_error_keyword_triggers_escalation` ("504 gateway timeout during batch sync") still passes — none of the five new topics uses a keyword that shadows it, which was screened explicitly before finalising the keyword lists.
* Full backend suite: **691 passed, 2 failed, 6 skipped**. Both failures are `tests/test_connectors.py` Salesforce OAuth tests requiring a local Redis on `:6379`; confirmed identical against a stashed clean tree, so they are environmental and pre-existing.
* FE: `npx tsc --noEmit` clean in `apps/invoice-fe` after the `SupportChatWindow.tsx` change. **No visual/click-through verification of the new neutral card has been done** — it is type-checked, not seen. ESLint is not configured in this app (`next lint` prompts for first-time setup), so no lint result is claimed.
