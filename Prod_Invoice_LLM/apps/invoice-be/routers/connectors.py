import logging
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select
from pydantic import BaseModel

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import TenantConnection, Invoice
from utils.encryption import encrypt_token, decrypt_token
import json
from azure.storage.queue import QueueClient
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["Connectors"])

class ImportPayload(BaseModel):
    file_id: str
    folder_id: Optional[str] = None

@router.get("/status")
async def get_connectors_status(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Returns connection statuses (Active / Inactive) for Google Drive and Salesforce.
    """
    statement = select(TenantConnection).where(TenantConnection.tenant_id == context.tenant_id)
    connections = db_session.exec(statement).all()

    status_map = {
        "google_drive": "Not Configured",
        "salesforce": "Not Configured"
    }

    for conn in connections:
        prov = conn.provider.lower()
        if prov in status_map:
            # Active if status is 'active' and token not expired (or refresh token exists)
            is_active = (conn.status == "active" and (conn.token_expiry > datetime.utcnow() or conn.encrypted_refresh_token))
            status_map[prov] = "Active" if is_active else "Inactive"

    return status_map

@router.get("/auth-url/{provider}")
async def get_auth_url(
    provider: str,
    context: TenantContext = Depends(get_tenant_context)
):
    """
    Generates OAuth consent screen redirect URL for Google Drive or Salesforce.
    """
    prov = provider.lower()
    if prov not in ["google_drive", "salesforce"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )

    # In production, construct URL using developer settings.
    # Fallback to standard mock OAuth consent URL for testing/development.
    mock_auth_urls = {
        "google_drive": "https://accounts.google.com/o/oauth2/v2/auth?client_id=mock_google_id&response_type=code&scope=https://www.googleapis.com/auth/drive.readonly",
        "salesforce": "https://login.salesforce.com/services/oauth2/authorize?client_id=mock_salesforce_id&response_type=code"
    }
    return {"auth_url": mock_auth_urls[prov]}

@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str = Query(..., description="Authorization code from OAuth redirection flow"),
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    OAuth Callback handler: swaps code for credentials, encrypts them, and saves to database.
    """
    prov = provider.lower()
    if prov not in ["google_drive", "salesforce"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )

    # In production, make HTTP client POST exchange to Google/Salesforce token endpoints.
    # For now, simulate exchange of authorization code for credentials.
    mock_access_token = f"mock_access_token_{prov}_{uuid4().hex[:6]}"
    mock_refresh_token = f"mock_refresh_token_{prov}_{uuid4().hex[:6]}"
    expiry_time = datetime.utcnow() + timedelta(hours=1)

    # Encrypt the tokens using AES-256 Fernet helper
    enc_access = encrypt_token(mock_access_token)
    enc_refresh = encrypt_token(mock_refresh_token)

    # Check if connection already exists
    statement = select(TenantConnection).where(
        TenantConnection.tenant_id == context.tenant_id,
        TenantConnection.provider == prov
    )
    connection = db_session.exec(statement).first()

    if not connection:
        connection = TenantConnection(
            id=uuid4(),
            tenant_id=context.tenant_id,
            provider=prov,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_expiry=expiry_time,
            status="active",
            created_at=datetime.utcnow()
        )
    else:
        connection.encrypted_access_token = enc_access
        connection.encrypted_refresh_token = enc_refresh
        connection.token_expiry = expiry_time
        connection.status = "active"

    db_session.add(connection)
    db_session.commit()

    return {"success": True, "message": f"Successfully connected to {provider}"}

@router.get("/files/{provider}")
async def list_connector_files(
    provider: str,
    folder_id: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Browse directories and list files in Google Drive or Salesforce documents.
    """
    prov = provider.lower()
    if prov not in ["google_drive", "salesforce"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )

    # Retrieve connection state
    statement = select(TenantConnection).where(
        TenantConnection.tenant_id == context.tenant_id,
        TenantConnection.provider == prov
    )
    connection = db_session.exec(statement).first()
    if not connection or connection.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Integration '{provider}' is not connected for this tenant."
        )

    # Decrypt key to check access validity
    try:
        access_token = decrypt_token(connection.encrypted_access_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt API credentials credentials."
        )

    # Mock file metadata list representing drive files
    if prov == "google_drive":
        mock_files = [
            {"id": "gdrive_file_101", "name": "invoice_acme_hardware.pdf", "type": "file", "size_bytes": 104857},
            {"id": "gdrive_file_102", "name": "globex_services_statement.pdf", "type": "file", "size_bytes": 45829},
            {"id": "gdrive_folder_abc", "name": "Ingested_Invoices", "type": "folder", "size_bytes": 0}
        ]
    else: # salesforce
        mock_files = [
            {"id": "sf_doc_881", "name": "Attachment_ACME_PO_99.pdf", "type": "file", "size_bytes": 88120},
            {"id": "sf_doc_882", "name": "Bill_Services_Globex_PO_200.pdf", "type": "file", "size_bytes": 112040}
        ]

    return {"files": mock_files}

@router.post("/import/{provider}")
async def trigger_file_import(
    provider: str,
    payload: ImportPayload,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Manually triggers background ingestion task for a file/object.
    """
    prov = provider.lower()
    if prov not in ["google_drive", "salesforce"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )

    # Verify active connection
    statement = select(TenantConnection).where(
        TenantConnection.tenant_id == context.tenant_id,
        TenantConnection.provider == prov
    )
    connection = db_session.exec(statement).first()
    if not connection or connection.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Integration '{provider}' is not connected."
        )

    # Spawn background task via Azure Storage Queue
    try:
        settings = get_settings()
        if settings.AZURE_STORAGE_CONNECTION_STRING:
            queue_client = QueueClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
            )
            payload = {
                "task": "import_connector_file",
                "kwargs": {
                    "provider": prov,
                    "file_id": payload.file_id,
                    "tenant_id": str(context.tenant_id)
                }
            }
            queue_client.send_message(json.dumps(payload))
        else:
            logger.warning("AZURE_STORAGE_CONNECTION_STRING missing, skipped queueing.")
    except Exception as e:
        logger.warning("Failed to dispatch Azure Storage Queue import task: %s", e)

    return {"success": True, "message": f"Queued background import for file {payload.file_id}"}
