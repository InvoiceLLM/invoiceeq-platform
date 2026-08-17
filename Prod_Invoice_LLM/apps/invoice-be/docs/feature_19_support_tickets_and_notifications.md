# Feature 19: Support Ticket Engine, AI Support Agent & Notification Email Dispatch

**Status:** Planned / Architecture Verified  
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

* **Data Model:** `apps/invoice-be/models.py` (`SupportTicket`)
* **Alembic Migration:** `apps/invoice-be/alembic/versions/*_add_support_tickets.py`
* **Support Agent:** `apps/invoice-be/agents/support_agent.py`
* **Email Service:** `apps/invoice-be/services/support_email.py`
* **API Router:** `apps/invoice-be/routers/support.py`
* **Main Application:** `apps/invoice-be/main.py`
* **Configuration:** `apps/invoice-be/config.py` (`SUPPORT_NOTIFY_EMAIL`)
* **Unit & Integration Tests:** `apps/invoice-be/tests/test_support.py`

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

### 3.2 Endpoints (`routers/support.py`)
1. `POST /api/v1/support/contact`: Public rate-limited endpoint for website inquiries.
2. `POST /api/v1/support/chat`: Authenticated Help Center support chatbot query endpoint.
3. `POST /api/v1/support/ticket`: Authenticated ticket creation endpoint (accepts pre-filled transcript from chat).
4. `GET /api/v1/support/tickets`: List tenant's active and historical tickets.
5. `GET /api/v1/support/tickets/{ticket_id}`: Retrieve detailed ticket status.

### 3.3 Email Notification Service (`services/support_email.py`)
- Sends styled HTML notification to `Application@infinevocloud.com` with ticket reference, submitter info, tenant ID, priority, full description, and formatted conversation transcript.
- Sends auto-acknowledgement email to the submitter.

---

## 4. Tasks

- [ ] **Task 19.1: Define `SupportTicket` Model & Alembic Migration**
- [ ] **Task 19.2: Implement `services/support_email.py` Email Engine**
- [ ] **Task 19.3: Build `agents/support_agent.py` Knowledge RAG & Escalation Logic**
- [ ] **Task 19.4: Implement `routers/support.py` Endpoints and Register in `main.py`**
- [ ] **Task 19.5: Automated Test Suite (`tests/test_support.py`)**

---

## 5. Verification Plan

* **Automated Tests:** Run `pytest tests/test_support.py` verifying contact inquiry creation, authenticated ticket dispatch, chat evaluation, and email formatting.
* **Manual Verification:** Submit test ticket and verify DB persistence, sequential ticket number generation, and receipt in `Application@infinevocloud.com`.
