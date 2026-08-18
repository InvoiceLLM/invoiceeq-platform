# Feature 19: Support Ticket Engine, AI Support Agent & Notification Email Dispatch

**Status:** Built 2026-08-17 (commit `fc48ef0`) — all 5 tasks landed, with two deviations from this spec recorded in §4. Status/verification state lives in `be_features_tracker.md` (Gaps 246/247/248); this doc is the design record.  
**Target Application:** `invoice-be`  
**Related Frontend Specs:** `apps/invoice-fe/docs/feature_15_help_center_support_bot_and_tickets.md`, `apps/invoice-website/website_features/feature_5_contact_us.md`  
**Primary Notification Inbox:** `Application@infinevocloud.com`

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

* `KNOWLEDGE_TOPICS: list[dict]` — the hardcoded platform knowledge base. Each entry is `{id, keywords, category, title, guidance}`, where `guidance` is a pre-written Markdown answer. Covers account/auth, Trainer rules, Auditor console, email ingestion, webhooks, and billing.
* `ERROR_TRIGGERS: list[dict]` — regex-matched severe-failure patterns (`{pattern, message, category, priority, subject, error_code}`) for things like 504 gateway timeouts, PayU billing exceptions, and stalled OCR processing. A match is what produces an escalation with a pre-filled `error_code`.
* `evaluate_support_query(message: str, history: list[dict] | None = None) -> dict` — **the only public entry point.** Returns `{answer, suggest_escalation, escalation_context}`. Resolution order, solution-first by design: (1) empty input → SAGE greeting, no escalation; (2) score the query against every `KNOWLEDGE_TOPICS` entry by counting keyword hits and return the highest-scoring topic's `guidance` with **no** escalation — a question that the knowledge base can answer never becomes a ticket; (3) `ERROR_TRIGGERS` regex match → that trigger's message plus `suggest_escalation=True` and a fully populated `escalation_context`; (4) an explicit human-help request (`human|agent|raise ticket|support ticket|contact support|speak to someone|talk to human`) → escalate as `TECHNICAL_SUPPORT`/`NORMAL`; (5) fallback → generic guidance plus escalation as `GENERAL`/`NORMAL`. The `history` parameter is accepted for interface stability but is not currently read.

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
* Request/response models: `ContactInquiryRequest`, `AppTicketRequest`, `SupportChatRequest`, `SupportChatResponse`, `TicketResponse`.
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
1. `POST /api/v1/support/contact`: Public endpoint for website inquiries. **Built, but not rate-limited** — the "rate-limited" wording here describes intent that was never implemented; it is tracked by the separate security review, not by a gap in `be_features_tracker.md`.
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
- [x] **Task 19.4: Implement `routers/support.py` Endpoints and Register in `main.py`** — Done 2026-08-17 for **4 of the 5** endpoints in §3.2; `GET /support/tickets/{ticket_id}` was not built. Router registered in `main.py` at `/api/v1`.
- [x] **Task 19.5: Automated Test Suite (`tests/test_support.py`)** — Done 2026-08-17. 20 test functions / 22 collected cases against in-memory SQLite with the email dispatcher mocked, covering contact-form validation and persistence, ticket-number format for both prefixes, transcript persistence, tenant-scoped listing, chat escalation triggers, and the email-failure-still-returns-201 path.

---

## 5. Verification Plan

* **Automated Tests:** Run `pytest tests/test_support.py` verifying contact inquiry creation, authenticated ticket dispatch, chat evaluation, and email formatting.
* **Manual Verification:** Submit test ticket and verify DB persistence, ticket number generation, and receipt in `Application@infinevocloud.com`. *(§5 originally said "sequential ticket number generation" — the shipped `_generate_ticket_number()` is deliberately **random**, not sequential, so there is nothing sequential to verify.)*

### 5.1 Actual verification state (recorded 2026-08-18)

* **Reported by the branch author, 2026-08-17:** `tests/test_support.py` 22/22 passing.
* **Re-run status:** not re-run during the 2026-08-18 merge-prep pass — that pass had no Python environment with this app's dependencies available, so it verified the module structure and behaviour by reading the code and confirmed only that the suite does collect 22 cases (20 functions, one parametrized over 3 values).
* **Never done, for either pass:** no live run against a real Postgres, a real Clerk session, or a real SendGrid key. Every test mocks `dispatch_support_ticket_email`, so no email has actually been delivered to `Application@infinevocloud.com` by this code, and the migration has not been applied to a real database.
