# Feature 9: Third-Party Connectors & Ingestion

Integrate secure API credentials exchanges, MCP tools, and import pipelines to retrieve files from Google Drive or Salesforce.

### File Coordinates
* Router: [apps/invoice-be/routers/connectors.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/connectors.py)
* Ingestion MCP Server: [apps/invoice-be/mcp_servers/ingestion_mcp.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/mcp_servers/ingestion_mcp.py)

### Tasks
- [ ] **Task 9.1: Code Connection Status Check Route**
  - Implement `GET /api/v1/connectors/status` querying the `tenant_connections` table to determine configured credentials states (`Active` / `Inactive` / `Not Configured`) for both Google Drive and Salesforce.
- [ ] **Task 9.2: Implement Secured OAuth Credentials Flow (Google Drive & Salesforce)**
  - Implement authorization link generator endpoints: `GET /api/v1/connectors/auth-url/{provider}`.
  - Implement OAuth redirect handling endpoints: `GET /api/v1/connectors/callback/{provider}` to exchange code for tokens.
  - Encrypt stored credentials (access & refresh tokens) using AES-256 Fernet (leveraging `TOKEN_ENCRYPTION_KEY` in environment variables) when storing in `tenant_connections` table.
- [ ] **Task 9.3: Build Ingestion MCP Server & Directory Explorer APIs**
  - Implement Model Context Protocol (MCP) server `mcp_servers/ingestion_mcp.py` exposing standard directory tools (`list_drive_files`, `import_drive_file`) to the agent context.
  - Create directory listing API functions querying Salesforce Attachments/Documents or Google Drive folder lists with decrypter logic.
- [ ] **Task 9.4: Implement Background Import Tasks**
  - Build Celery background tasks to retrieve files from Google Drive / Salesforce folders, upload to Azure Blob Storage, and queue Feature 2 ingestion tasks.
  - Code robust fallback behaviors returning simulated data lists if client developer credentials are missing in the `.env` settings.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_connectors.py` with mock OAuth tokens, validating encryption/decryption routines, state checks, and directory explorers.
* **Manual Verification**: Authorize the application via the UI connectors dashboard, browse folders, and import a test file.

