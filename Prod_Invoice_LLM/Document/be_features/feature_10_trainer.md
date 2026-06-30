# Feature 10: AI Trainer Sandbox & Rules Registry

Enable interactive sandbox learning for invoice layout extraction templates, transient file parsing, and Q&A chat adjustments.

### File Coordinates
* Router: [apps/invoice-be/routers/trainer.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/trainer.py)
* Trainer Agent: [apps/invoice-be/agents/trainer_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/trainer_agent.py)

### Tasks
- [ ] **Task 10.1: Code Transient Training Upload Route**
  - Implement `POST /api/v1/trainer/upload` accepting PDF file uploads.
  - Parse layout strings immediately via OCR + Extraction Agent.
  - Return transient parsed key-value properties and a generated `session_id`. **Do not** write records to the permanent `invoices` table.
- [ ] **Task 10.2: Code Interactive Training Chat Route**
  - Implement `POST /api/v1/trainer/sessions/{session_id}/chat` processing conversational corrections (e.g. *"The invoice date is 2026-06-25, not 2026-05-25"*).
  - Update layout constraints in the Trainer Agent context, re-extract fields, and return revised parsed variables.
- [ ] **Task 10.3: Code Rules Registry Commit Route**
  - Implement `POST /api/v1/trainer/sessions/{session_id}/commit` saving customized extraction rules or templates to the PostgreSQL `extraction_templates` table.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_trainer.py` validating transient upload parsing and prompt rule creations.
* **Manual Verification**: Upload an invoice in the Trainer UI console, correct the date extraction value in the chat panel, and click Commit to check template records inside PostgreSQL.
