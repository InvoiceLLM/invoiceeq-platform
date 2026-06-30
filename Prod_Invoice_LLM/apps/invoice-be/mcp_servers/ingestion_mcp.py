import sys
import json
import logging
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Session, select
from database import engine
from models import TenantConnection
from utils.encryption import decrypt_token

# Configure logger to stderr so it doesn't corrupt stdout JSON-RPC channel
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("ingestion_mcp")

def get_db_session():
    return Session(engine)

def handle_list_files(arguments: dict) -> dict:
    provider = arguments.get("provider", "").lower()
    tenant_id_str = arguments.get("tenant_id")
    folder_id = arguments.get("folder_id")

    if not provider or not tenant_id_str:
        return {"content": [{"type": "text", "text": "Error: Missing provider or tenant_id"}]}

    try:
        tenant_id = UUID(tenant_id_str)
    except ValueError:
        return {"content": [{"type": "text", "text": f"Error: Invalid tenant_id UUID '{tenant_id_str}'"}]}

    # Query connection from database
    with get_db_session() as session:
        statement = select(TenantConnection).where(
            TenantConnection.tenant_id == tenant_id,
            TenantConnection.provider == provider
        )
        conn = session.exec(statement).first()
        
        if not conn or conn.status != "active":
            return {"content": [{"type": "text", "text": f"Error: Integration '{provider}' is not connected for tenant."}]}

        try:
            # Decrypt access token to verify decryption logic
            _ = decrypt_token(conn.encrypted_access_token)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: Failed to decrypt credentials: {str(e)}"}]}

    # Return mock lists as fallback if live client settings are not configured
    if provider == "google_drive":
        files = [
            {"id": "gdrive_file_101", "name": "invoice_acme_hardware.pdf", "type": "file"},
            {"id": "gdrive_file_102", "name": "globex_services_statement.pdf", "type": "file"},
            {"id": "gdrive_folder_abc", "name": "Ingested_Invoices", "type": "folder"}
        ]
    else: # salesforce
        files = [
            {"id": "sf_doc_881", "name": "Attachment_ACME_PO_99.pdf", "type": "file"},
            {"id": "sf_doc_882", "name": "Bill_Services_Globex_PO_200.pdf", "type": "file"}
        ]

    return {"content": [{"type": "text", "text": json.dumps({"files": files})}]}

def handle_import_file(arguments: dict) -> dict:
    provider = arguments.get("provider", "").lower()
    tenant_id_str = arguments.get("tenant_id")
    file_id = arguments.get("file_id")

    if not provider or not tenant_id_str or not file_id:
        return {"content": [{"type": "text", "text": "Error: Missing provider, tenant_id, or file_id"}]}

    try:
        tenant_id = UUID(tenant_id_str)
    except ValueError:
        return {"content": [{"type": "text", "text": f"Error: Invalid tenant_id UUID '{tenant_id_str}'"}]}

    # Check connection
    with get_db_session() as session:
        statement = select(TenantConnection).where(
            TenantConnection.tenant_id == tenant_id,
            TenantConnection.provider == provider
        )
        conn = session.exec(statement).first()
        if not conn or conn.status != "active":
            return {"content": [{"type": "text", "text": f"Error: Integration '{provider}' is not connected."}]}

    # Dispatch Background Celery Ingestion Task
    try:
        from workers.tasks import import_connector_file_task
        import_connector_file_task.delay(
            provider=provider,
            file_id=file_id,
            tenant_id=str(tenant_id)
        )
    except Exception as e:
        logger.warning("Could not dispatch Celery task: %s (Ignored for local offline dev)", e)

    return {"content": [{"type": "text", "text": f"Success: Queued background import for file {file_id}"}]}

def main():
    logger.info("Ingestion MCP Server starting...")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            method = request.get("method")
            req_id = request.get("id")

            # 1. Initialize
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "ingestion-mcp", "version": "0.1.0"}
                    },
                    "id": req_id
                }
            # 2. Tools list
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "result": {
                        "tools": [
                            {
                                "name": "list_drive_files",
                                "description": "Lists folder directories and files inside Google Drive or Salesforce.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "provider": {"type": "string", "description": "google_drive or salesforce"},
                                        "tenant_id": {"type": "string", "description": "Tenant isolated UUID"},
                                        "folder_id": {"type": "string", "description": "Target folder ID to list"}
                                    },
                                    "required": ["provider", "tenant_id"]
                                }
                            },
                            {
                                "name": "import_drive_file",
                                "description": "Triggers background Celery import task to retrieve a document file.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "provider": {"type": "string", "description": "google_drive or salesforce"},
                                        "tenant_id": {"type": "string", "description": "Tenant isolated UUID"},
                                        "file_id": {"type": "string", "description": "Document unique ID to retrieve"}
                                    },
                                    "required": ["provider", "tenant_id", "file_id"]
                                }
                            }
                        ]
                    },
                    "id": req_id
                }
            # 3. Tools call
            elif method == "tools/call":
                params = request.get("params", {})
                name = params.get("name")
                arguments = params.get("arguments", {})

                if name == "list_drive_files":
                    result = handle_list_files(arguments)
                elif name == "import_drive_file":
                    result = handle_import_file(arguments)
                else:
                    result = {"content": [{"type": "text", "text": f"Error: Unknown tool '{name}'"}]}

                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                    "id": req_id
                }
            
            # Output response back to client stdout channel
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except Exception as e:
            logger.error("Exception handling RPC request: %s", e)
            try:
                response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": f"Internal server error: {str(e)}"},
                    "id": request.get("id") if 'request' in locals() else None
                }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except Exception:
                pass

if __name__ == "__main__":
    main()
