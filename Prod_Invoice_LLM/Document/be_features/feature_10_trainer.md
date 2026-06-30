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
  - Support saving to the static global file [apps/invoice-be/config/default_templates.json](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/config/default_templates.json) if the commit request specifies global/developer mode.
- [ ] **Task 10.4: Integrate Static Global Template Fallback**
  - Create the static fallback configuration file [apps/invoice-be/config/default_templates.json](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/config/default_templates.json) to store version-controlled base templates trained by developers (e.g. from 1,000+ base PDFs).
  - Update the parsing pipeline to first query the tenant's database `extraction_templates` table. If no tenant-specific match is found, fallback to loading layout rules from the static `default_templates.json` file.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_trainer.py` validating transient upload parsing, prompt rule creations, and static fallback file lookups.
* **Manual Verification**: Upload an invoice in the Trainer UI console, correct the date extraction value in the chat panel, commit as a global template, and verify that the rules are written to `default_templates.json` and correctly applied to other tenants' default ingestion flows.
