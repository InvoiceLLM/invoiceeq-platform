# Feature 9: Third-Party Connectors & Ingestion

Integrate secure API credentials exchanges, MCP tools, and import pipelines to retrieve files from Google Drive or Salesforce.

### File Coordinates
* Router: [apps/invoice-be/routers/connectors.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/connectors.py) → `get_connectors_status()`, `get_auth_url()`, `oauth_callback()`, `list_connector_files()`, `trigger_file_import()`
* Ingestion MCP Server: [apps/invoice-be/mcp_servers/ingestion_mcp.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/mcp_servers/ingestion_mcp.py) → `list_drive_files` / `import_drive_file` JSON-RPC tools, backed by `handle_list_files()` / `handle_import_file()`
* Encryption Helper: [apps/invoice-be/utils/encryption.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/encryption.py) → `encrypt_token()` / `decrypt_token()`

### Functionality
`get_connectors_status()` reads the tenant's `TenantConnection` rows and reports `Active`/`Inactive`/`Not Configured` per provider (active = status `active` and token not expired, or a refresh token exists). `get_auth_url()` returns a hardcoded mock OAuth consent URL per provider — no real client ID/secret wiring yet. `oauth_callback()` simulates the code-for-token exchange (mock tokens, no real HTTP call to Google/Salesforce), encrypts both tokens with `utils/encryption.py`'s AES-256 Fernet helper, and upserts the `TenantConnection` row. `list_connector_files()` and `trigger_file_import()` (which dispatches `workers/tasks.py::import_connector_file_task`) both return **hardcoded mock file lists** after checking the connection is active — same fallback-data pattern as the MCP server's `handle_list_files()`/`handle_import_file()`.
- **Duplication note**: `mcp_servers/ingestion_mcp.py` implements the identical list/import logic as its own standalone JSON-RPC process (stdin/stdout), but `routers/connectors.py` does **not** call into it — the router has its own independent copy of the same mock logic. The MCP server isn't wired into any agent's tool context yet, so it's currently dead code from the running app's perspective (Task 9.3 is still unchecked).

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

