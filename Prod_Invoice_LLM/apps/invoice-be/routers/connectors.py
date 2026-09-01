import logging
from urllib.parse import urlencode
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from pydantic import BaseModel

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import TenantConnection, Invoice
from utils.encryption import encrypt_token, decrypt_token
from utils.connector_oauth import (
    has_real_credentials as _has_real_credentials,
    get_valid_access_token,
    GOOGLE_DRIVE_OAUTH_SCOPE,
    GOOGLE_TOKEN_URL,
)
from utils.connector_files import list_google_drive_files
from services.billing_quota import charge_free_quota
import json
from azure.storage.queue import QueueClient
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["Connectors"])

# Gap 334 (2026-08-28): Salesforce removed, so Google Drive is the only
# provider. The PKCE plumbing that used to live here (PKCE_REDIS_PREFIX,
# PKCE_TTL_SECONDS, the `state` query param, and the `import redis` that
# backed them) existed solely for Salesforce Connected Apps and went with it
# -- Google's flow never required PKCE. The per-provider validation lists and
# branches below are deliberately kept in their existing shape rather than
# collapsed away, since they still serve Drive and still have to reject an
# unrecognised provider.

class ImportPayload(BaseModel):
    file_id: str
    folder_id: Optional[str] = None

@router.get("/status")
async def get_connectors_status(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Returns connection statuses (Active / Inactive) for Google Drive.
    """
    statement = select(TenantConnection).where(TenantConnection.tenant_id == context.tenant_id)
    connections = db_session.exec(statement).all()

    status_map = {
        "google_drive": "Not Configured"
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
    Generates OAuth consent screen redirect URL for Google Drive.
    """
    # Gap 361 (security pass, 2026-09-01): this and the other 4 mutating
    # connector endpoints below were reachable by any signed-in tenant
    # member -- the FE's IntegrationCard.tsx already hides Connect/Disconnect/
    # Browse behind isAdmin, but nothing on the backend enforced it, so a
    # non-Admin member could call these directly (e.g. from DevTools) despite
    # never seeing the button. GET /status is deliberately left open to any
    # role -- it's a read-only status display, matching the FE, which never
    # gates it.
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage connector integrations.",
        )
    prov = provider.lower()
    if prov not in ["google_drive"]:
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
            #
            # Gap 338 widened `scope` from bare drive.readonly to
            # readonly + drive.file (GOOGLE_DRIVE_OAUTH_SCOPE) so the
            # `drive_archive` output destination can write results back. Two
            # scopes, not one: drive.file alone cannot READ the tenant's
            # existing PDFs, which is what Features 9/13 do here. Every
            # connection minted before 2026-08-30 holds a readonly-only token
            # and Google never upgrades an existing grant silently -- that is
            # detected at use time, see services/workflow_outputs.py
            # ::drive_archive_readiness().
            params = {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "access_type": "offline",
                # Gap 362, founder-reported: without select_account, Google
                # silently reuses whatever Google account is already signed
                # into the browser (observed live: application@infinevocloud.com
                # -- the account used to set up this GCP project in the first
                # place, never meant for end-user Drive connections) instead of
                # ever asking who to sign in as. Same class of bug Gap 261
                # already fixed for the now-removed Salesforce connector;
                # Google Drive's own flow never got the equivalent fix.
                "prompt": "select_account consent",
                "scope": GOOGLE_DRIVE_OAUTH_SCOPE,
            }
            return {"auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}

    # No real credentials configured yet for this provider -- fall back to a
    # mock consent URL so local/dev testing still works end-to-end.
    mock_auth_urls = {
        "google_drive": (
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=mock_google_id"
            f"&response_type=code&scope={GOOGLE_DRIVE_OAUTH_SCOPE}"
        ),
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
    # Gap 361, see get_auth_url()'s comment above. The Admin who clicked
    # Connect is still the same logged-in Clerk session Google redirects
    # back to, so this does not break the real flow.
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage connector integrations.",
        )
    prov = provider.lower()
    if prov not in ["google_drive"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )

    settings = get_settings()
    access_token: str
    refresh_token: Optional[str]

    if _has_real_credentials(prov, settings):
        token_url = GOOGLE_TOKEN_URL
        token_payload = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
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
        # access_type=offline/prompt=consent above).
        refresh_token = token_data.get("refresh_token")
        expiry_time = datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))
    else:
        # No real credentials configured yet for this provider -- keep the
        # simulated exchange so local/dev testing without a registered OAuth
        # app still works end-to-end.
        access_token = f"mock_access_token_{prov}_{uuid4().hex[:6]}"
        refresh_token = f"mock_refresh_token_{prov}_{uuid4().hex[:6]}"
        expiry_time = datetime.utcnow() + timedelta(hours=1)

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
        )
    else:
        connection.encrypted_access_token = enc_access
        connection.encrypted_refresh_token = enc_refresh
        connection.token_expiry = expiry_time
        connection.status = "active"

    db_session.add(connection)
    db_session.commit()

    # Google redirects the browser here directly (a full-page navigation, not
    # a fetch call) -- so this endpoint must send the user back into the app
    # rather than leaving them on a bare JSON response.
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(url=f"{frontend_url}/settings/connectors?connected={prov}")

@router.get("/files/{provider}")
async def list_connector_files(
    provider: str,
    direction: str = "inbound",
    folder_id: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Browse directories and list files in Google Drive.
    direction: 'inbound' (AP supplier PDFs) or 'outbound' (AR verified exports).
    """
    # Gap 361, see get_auth_url()'s comment above.
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage connector integrations.",
        )
    prov = provider.lower()
    if prov not in ["google_drive"]:
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
        # provider's real Client ID is configured.
        try:
            access_token = get_valid_access_token(connection, settings, db_session)
        except RuntimeError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

        try:
            files = list_google_drive_files(access_token, folder_id)
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

    mock_files = [
        {"id": "gdrive_file_101", "name": "invoice_acme_hardware.pdf", "type": "file", "size_bytes": 104857},
        {"id": "gdrive_file_102", "name": "globex_services_statement.pdf", "type": "file", "size_bytes": 45829},
        {"id": "gdrive_folder_abc", "name": "Ingested_Invoices", "type": "folder", "size_bytes": 0}
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
    # Gap 361, see get_auth_url()'s comment above.
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage connector integrations.",
        )
    prov = provider.lower()
    if prov not in ["google_drive"]:
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

    # Gap 266: same "never claim success unless it's actually true" reasoning
    # as Gap 179 below, one layer earlier. get_valid_access_token() already
    # raises a clear, specific RuntimeError for exactly the two conditions
    # that were producing "works for some accounts, not others" reports --
    # no refresh token stored, or the provider rejected the refresh call
    # (revoked/expired) -- but until now that error only ever surfaced in
    # queue-worker logs, invisible to the user, because this endpoint queued
    # the download unconditionally regardless of whether the stored token
    # could actually be used. Checking synchronously here turns a silent
    # background failure into an immediate, actionable "please reconnect"
    # for the one account that actually needs it, while every other file/
    # account in the same batch is unaffected (Gap 267 fixed the FE loop to
    # attempt each file independently either way).
    try:
        get_valid_access_token(connection, get_settings(), db_session)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{provider} connection needs to be reconnected: {e}",
        )

    # Gap 343: charge the free-tier quota here, before anything is queued.
    #
    # Until now this door created Invoice rows (via
    # queue_worker/handlers.py::handle_import_connector_file) and charged
    # nothing, so a Free Tier tenant sitting at free_invoices_remaining=0 could
    # ingest without limit simply by importing from Drive instead of using the
    # upload button. Same helper, same `SELECT tenant … FOR UPDATE`, same
    # 402 "Limit reached" as routers/invoices.py -- the refusal is mirrored, not
    # reinvented, and it lands *before* the queue message so a refused import
    # leaves nothing behind.
    #
    # A flat 1, not count_billable_uploads(): this endpoint genuinely has no file
    # bytes to hash -- the download happens later, in the queue worker. That is
    # accurate rather than approximate for this door, because the connector path
    # never persists Invoice.file_hash, so every import already creates a
    # distinct invoice row regardless of content. Charging in the worker instead
    # was rejected: the worker cannot return a 402 to anyone, so a quota refusal
    # there would be an invisible background failure -- the exact class of bug
    # Gaps 179/180/266 were opened for on this same code path.
    charge_free_quota(db_session, context.tenant_id, 1)

    # Gap 179: never tell the FE "queued" unless the queue message actually landed.
    # Previously returned success=True even when AZURE_STORAGE_CONNECTION_STRING was
    # missing or send_message failed — green "Import request queued!" with nothing
    # on the queue.
    queued = False
    queue_error: str | None = None
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
            queued = True
        else:
            queue_error = "AZURE_STORAGE_CONNECTION_STRING is not configured."
            logger.error(
                "Connector import skipped queueing for file %s — %s",
                payload.file_id, queue_error,
            )
    except Exception as e:
        queue_error = str(e)
        logger.error(
            "Failed to dispatch Azure Storage Queue import task for file %s: %s",
            payload.file_id, e,
        )

    if not queued:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not queue the connector import for processing. "
                f"{queue_error or 'Storage queue unavailable.'}"
            ),
        )

    return {"success": True, "message": f"Queued {direction} import for file {payload.file_id}"}

@router.delete("/{provider}")
async def disconnect_connector(
    provider: str,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Deletes the TenantConnection database row for the specified provider,
    effectively revoking access from the platform.
    """
    # Gap 361, see get_auth_url()'s comment above.
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage connector integrations.",
        )
    prov = provider.lower()
    if prov not in ["google_drive"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connector provider '{provider}'."
        )

    statement = select(TenantConnection).where(
        TenantConnection.tenant_id == context.tenant_id,
        TenantConnection.provider == prov
    )
    connection = db_session.exec(statement).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No connection found for provider '{provider}'."
        )

    db_session.delete(connection)
    db_session.commit()

    return {"detail": f"Successfully disconnected provider '{provider}'."}
