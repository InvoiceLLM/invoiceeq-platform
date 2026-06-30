# Feature 9: Third-Party Connectors & Ingestion

Integrate secure API credentials exchanges and import pipelines to retrieve files from Google Drive or SharePoint.

### File Coordinates
* Router: [apps/invoice-be/routers/connectors.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/connectors.py)
* Ingestion MCP Server: [apps/invoice-be/mcp_servers/ingestion_mcp.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/mcp_servers/ingestion_mcp.py)

### Tasks
- [ ] **Task 9.1: Code Connection Status Check Route**
  - Implement `GET /api/v1/connectors/status` querying the `tenant_connections` table to determine configured credentials states (`Active` / `Inactive`).
- [ ] **Task 9.2: Implement Secured OAuth Credentials Flow**
  - Implement OAuth endpoints to retrieve/refresh access tokens.
  - Encrypt storage credentials using AES-256 Fernet using `TOKEN_ENCRYPTION_KEY` in settings.
- [ ] **Task 9.3: Build Directory Explorer APIs**
  - Create directory listing functions querying SharePoint/Google Drive folders.
- [ ] **Task 9.4: Implement Background Import Tasks**
  - Build Celery background tasks to retrieve files from external drives, upload to Azure Blob Storage, and queue Feature 2 ingestion tasks.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_connectors.py` with mock OAuth tokens.
* **Manual Verification**: Authorize the application via the UI connectors dashboard, browse folders, and import a test file.
