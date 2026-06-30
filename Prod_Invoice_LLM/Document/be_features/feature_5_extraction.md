# Feature 5: Multi-Modal Extraction & Verification Agent

Utilize LLM extraction graphs with validation checks to pull structured details from invoice files.

### File Coordinates
* Extraction Agent: [apps/invoice-be/agents/extraction_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/extraction_agent.py)
* Verification Tools: [apps/invoice-be/utils/verification_tools.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/verification_tools.py)

### Tasks
- [ ] **Task 5.1: Construct LangGraph State Graph**
  - Define node states and transitions for the Extraction Agent using LangGraph.
  - Implement Pydantic structured output mapping (`LLM.with_structured_output()`) to guarantee layout matching.
- [ ] **Task 5.2: Build Multi-Modal visual channel processing**
  - Convert PDF pages into base64 visual image strings to support table/column layout mapping.
  - Pipe visual streams and OCR text layout content into the agent model.
- [ ] **Task 5.3: Implement Calculation Check Tools**
  - Code mathematical check tools: `verify_line_items_math` confirming `sum(line_items.amount) == subtotal`.
  - Validate that `subtotal + tax_amount == grand_total`.
- [ ] **Task 5.4: Enforce Flag Warnings & Alerts System**
  - Save warnings to the database `sa_alerts` JSONB array column as structured objects containing details: `{"type": "tax_mismatch", "message": "...", "field": "tax_amount"}`.
  - Mark matching database invoices as `AUDIT_REQUIRED` if validation checks fail, or `COMPLETED` if they pass.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_extraction.py` with mock invoices that contain math errors, ensuring they status-resolve to `AUDIT_REQUIRED`.
* **Manual Verification**: Run extraction on test PDFs and inspect generated database alerts.
