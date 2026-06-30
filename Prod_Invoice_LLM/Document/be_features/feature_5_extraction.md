# Feature 5: Multi-Modal Extraction & Verification Agent

Utilize LLM extraction graphs with validation checks to pull structured details from invoice files.

### File Coordinates
* Extraction Agent: [apps/invoice-be/agents/extraction_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/extraction_agent.py)
* Verification Tools: [apps/invoice-be/utils/verification_tools.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/verification_tools.py)
* Token Management Service: [apps/invoice-be/utils/token_management.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/token_management.py)

### Tasks
- [x] **Task 5.1: Construct LangGraph State Graph**
  - Define node states and transitions for the Extraction Agent using LangGraph.
  - Implement Pydantic structured output mapping (`LLM.with_structured_output()`) to guarantee layout matching.
- [x] **Task 5.2: Build Multi-Modal visual channel processing**
  - Convert PDF pages into base64 visual image strings to support table/column layout mapping.
  - Pipe visual streams and OCR text layout content into the agent model.
- [x] **Task 5.3: Implement Calculation Check Tools**
  - Code mathematical check tools: `verify_line_items_math` confirming `sum(line_items.amount) == subtotal`.
  - Validate that `subtotal + tax_amount == grand_total`.
- [x] **Task 5.4: Enforce Flag Warnings & Alerts System**
  - Save warnings to the database `sa_alerts` JSONB array column as structured objects containing details: `{"type": "tax_mismatch", "message": "...", "field": "tax_amount"}`.
  - Mark matching database invoices as `AUDIT_REQUIRED` if validation checks fail, or `COMPLETED` if they pass.
- [x] **Task 5.5: Implement Token Management & Pre-Flight Guardrails**
  - Count OCR text tokens with `tiktoken` and base64 image tokens matching model visual pricing detail levels.
  - Assert that estimated prompt + expected output length is within the model context limit (`check_token_guardrails`).
  - Gracefully redirect to `AUDIT_REQUIRED` with a `token_limit_exceeded` alert if guardrails are violated, bypassing the LLM.
  - Log token usage metrics alongside `tenant_id` for cost tracking.

### Verification Plan
* **Automated Tests**: 
  - Execute `uv run pytest tests/test_extraction.py` to verify math checks, token limits, and DB persistence.
  - Run `uv run pytest` to check for zero regressions, ensuring compatibility with `test_sse.py`'s `"audit"` file path trigger.
* **Manual Verification**: Run extraction on test PDFs and inspect generated database alerts.

