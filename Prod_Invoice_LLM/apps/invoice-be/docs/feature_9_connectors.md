# Feature 9: Third-Party Connectors & Ingestion

Integrate secure API credentials exchanges and import pipelines to retrieve files from Google Drive or Salesforce.

### File Coordinates
* Router: [apps/invoice-be/routers/connectors.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/connectors.py) → `get_connectors_status()`, `get_auth_url()`, `oauth_callback()`, `list_connector_files()`, `trigger_file_import()`
* Encryption Helper: [apps/invoice-be/utils/encryption.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/encryption.py) → `encrypt_token()` / `decrypt_token()`

### Functionality
`get_connectors_status()` reads the tenant's `TenantConnection` rows and reports `Active`/`Inactive`/`Not Configured` per provider. `get_auth_url()` returns a mock OAuth consent URL. `oauth_callback()` simulates code-for-token exchange, encrypts tokens via AES-256 Fernet, and stores them. 

* **Bi-directional Support**:
  * **Inbound (AP)**: `list_connector_files()` and `trigger_file_import()` pull supplier invoice PDFs into the inbound extraction pipeline.
  * **Outbound (AR)**: Connectors can be pointed to outbound directories to import pre-made outbound invoices or auto-export verified outbound PDFs to Google Drive/Salesforce once finalized.

### Tasks
- `[x]` **Task 9.1: Code Connection Status Check Route** — `GET /api/v1/connectors/status` implemented in `routers/connectors.py`.
- `[x]` **Task 9.2: Implement Secured OAuth Credentials Flow (Google Drive & Salesforce)** — `GET /connectors/auth-url/{provider}` and `GET /connectors/callback/{provider}` with AES-256 Fernet token encryption.
- `[x]` ~~Task 9.3: Build Ingestion MCP Server & Directory Explorer APIs~~ — **Removed (Gap 35, 2026-07-22)**: the MCP server was never wired into any agent and duplicated `routers/connectors.py`'s own logic; decided not to build it out. Directory listing already lives directly on the router (`list_connector_files()`), which is where new directory-listing work belongs going forward.
- `[x]` **Task 9.4: Implement Background Import Tasks** — `handle_import_connector_file()` added to `queue_worker/handlers.py` (2026-07-28). Supports `direction=inbound` (downloads, uploads to `{tenant_id}/inbound/` blob prefix, enqueues `process_invoice`) and `direction=outbound` (uploads to `{tenant_id}/outbound/` blob prefix, no extraction). Graceful no-op if `AZURE_STORAGE_CONNECTION_STRING` missing (local dev). `direction` kwarg forwarded through router → queue message → worker dispatch → handler.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_connectors.py` with mock OAuth tokens, validating encryption/decryption routines, state checks, and directory explorers.
* **Manual Verification**: Authorize the application via the UI connectors dashboard, browse folders, and import a test file.

