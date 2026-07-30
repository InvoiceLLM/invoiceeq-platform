import logging
from urllib.parse import urlencode
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select
from pydantic import BaseModel

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import TenantConnection, Invoice
from utils.encryption import encrypt_token, decrypt_token
from utils.connector_oauth import (
    has_real_credentials as _has_real_credentials,
    get_valid_access_token,
    GOOGLE_TOKEN_URL,
    SALESFORCE_TOKEN_URL,
)
from utils.connector_files import list_google_drive_files, list_salesforce_files
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

    settings = get_settings()

    if _has_real_credentials(prov, settings):
        if prov == "google_drive":
            # access_type=offline + prompt=consent: Google only issues a
            # refresh_token when consent is freshly granted, so without these
            # a re-connect would silently stop returning one after the first time.
            params = {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "scope": "https://www.googleapis.com/auth/drive.readonly",
            }
            return {"auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}
        else:  # salesforce
            params = {
                "client_id": settings.SALESFORCE_CLIENT_ID,
                "redirect_uri": settings.SALESFORCE_REDIRECT_URI,
                "response_type": "code",
            }
            return {"auth_url": f"https://login.salesforce.com/services/oauth2/authorize?{urlencode(params)}"}

    # No real credentials configured yet for this provider -- fall back to a
    # mock consent URL so local/dev testing still works end-to-end.
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

    settings = get_settings()
    access_token: str
    refresh_token: Optional[str]

    if _has_real_credentials(prov, settings):
        if prov == "google_drive":
            token_url = GOOGLE_TOKEN_URL
            token_payload = {
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
        else:  # salesforce
            token_url = SALESFORCE_TOKEN_URL
            token_payload = {
                "code": code,
                "client_id": settings.SALESFORCE_CLIENT_ID,
                "client_secret": settings.SALESFORCE_CLIENT_SECRET,
                "redirect_uri": settings.SALESFORCE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                token_response = await http_client.post(token_url, data=token_payload)
        except httpx.HTTPError as e:
            logger.error("Token exchange request to %s failed for provider %s: %s", token_url, prov, e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not reach {provider}'s token endpoint."
            )

        if token_response.status_code != 200:
            logger.error(
                "Token exchange rejected by %s for provider %s: %s %s",
                token_url, prov, token_response.status_code, token_response.text,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"{provider} rejected the authorization code."
            )

        token_data = token_response.json()
        access_token = token_data["access_token"]
        # Google only returns a refresh_token on fresh consent (see
        # access_type=offline/prompt=consent above); Salesforce always
        # returns one for the web-server OAuth flow used here.
        refresh_token = token_data.get("refresh_token")
        expiry_time = datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))
        # Salesforce's API base is per-org and comes back as instance_url on
        # every token response; Google never returns this key.
        instance_url = token_data.get("instance_url")
    else:
        # No real credentials configured yet for this provider -- keep the
        # simulated exchange so local/dev testing without a registered OAuth
        # app still works end-to-end.
        access_token = f"mock_access_token_{prov}_{uuid4().hex[:6]}"
        refresh_token = f"mock_refresh_token_{prov}_{uuid4().hex[:6]}"
        expiry_time = datetime.utcnow() + timedelta(hours=1)
        instance_url = None

    # Encrypt the tokens using AES-256 Fernet helper
    enc_access = encrypt_token(access_token)
    enc_refresh = encrypt_token(refresh_token) if refresh_token else None

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
            created_at=datetime.utcnow(),
            instance_url=instance_url,
        )
    else:
        connection.encrypted_access_token = enc_access
        connection.encrypted_refresh_token = enc_refresh
        connection.token_expiry = expiry_time
        connection.status = "active"
        if instance_url:
            connection.instance_url = instance_url

    db_session.add(connection)
    db_session.commit()

    return {"success": True, "message": f"Successfully connected to {provider}"}

@router.get("/files/{provider}")
async def list_connector_files(
    provider: str,
    direction: str = "inbound",
    folder_id: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Browse directories and list files in Google Drive or Salesforce.
    direction: 'inbound' (AP supplier PDFs) or 'outbound' (AR verified exports).
    """
    prov = provider.lower()
    if prov not in ["google_drive", "salesforce"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )
    direction = direction.lower()
    if direction not in ["inbound", "outbound"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="direction must be 'inbound' or 'outbound'."
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

    settings = get_settings()

    if _has_real_credentials(prov, settings):
        # Real listing (Gap 98): stays inert for a provider until that
        # provider's real Client ID is configured (Google today; Salesforce
        # once a real Connected App exists to test against).
        try:
            access_token = get_valid_access_token(connection, settings, db_session)
        except RuntimeError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

        try:
            if prov == "google_drive":
                files = list_google_drive_files(access_token, folder_id)
            else:  # salesforce
                if not connection.instance_url:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Salesforce connection is missing instance_url; reconnect this integration."
                    )
                files = list_salesforce_files(access_token, connection.instance_url)
        except httpx.HTTPError as e:
            logger.error("Real %s file listing failed: %s", prov, e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not list files from {provider}."
            )
        return {"files": files}

    # No real credentials configured yet for this provider -- fall back to a
    # mock file list so local/dev testing still works end-to-end.
    try:
        decrypt_token(connection.encrypted_access_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt API credentials credentials."
        )

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
    direction: str = "inbound",
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Manually triggers a background import task for a connector file.
    direction: 'inbound' feeds the AP extraction pipeline;
               'outbound' stores the file for AR record-keeping only.
    """
    prov = provider.lower()
    if prov not in ["google_drive", "salesforce"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )
    direction = direction.lower()
    if direction not in ["inbound", "outbound"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="direction must be 'inbound' or 'outbound'."
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
            msg_payload = {
                "task": "import_connector_file",
                "kwargs": {
                    "provider": prov,
                    "file_id": payload.file_id,
                    "tenant_id": str(context.tenant_id),
                    "direction": direction,
                }
            }
            queue_client.send_message(json.dumps(msg_payload))
        else:
            logger.warning("AZURE_STORAGE_CONNECTION_STRING missing, skipped queueing.")
    except Exception as e:
        logger.warning("Failed to dispatch Azure Storage Queue import task: %s", e)

    return {"success": True, "message": f"Queued {direction} import for file {payload.file_id}"}
