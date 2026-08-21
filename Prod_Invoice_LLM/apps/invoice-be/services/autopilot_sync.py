"""
Feature 13: Tenant Autopilot — Core Sync Engine (services/autopilot_sync.py)

This is the shared entrypoint called by BOTH:
  - Manual "Sync Now" API endpoint (POST /api/v1/autopilot/sync)
  - Scheduled Azure Container Apps Job (scripts/autopilot_job.py)

Sync flow per tenant:
  1. Load TenantAutopilotConfig from DB
  2. Resolve a valid OAuth token for the configured provider (Drive / Salesforce)
  3. List files from the cloud folder (incremental: since last successful run)
  4. For each file — two-layer deduplication:
       Layer 1: source_file_id in tenant_autopilot_logs → skip if seen
       Layer 2: SHA-256 content hash in tenant_autopilot_logs → skip if seen
  5. Download bytes, upload to Azure Blob Storage
  6. Create Invoice DB row + dispatch extraction queue message
  7. Write TenantAutopilotLog row (SUCCESS / SKIPPED_DUPLICATE / FAILED)
  8. Return summary: { processed, skipped, failed }
"""

import hashlib
import json
import logging
from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Session, select

from config import get_settings
from models import (
    Invoice,
    TenantAutopilotConfig,
    TenantAutopilotLog,
    TenantConnection,
)
from services.storage import upload_pdf_to_blob_storage
from utils.connector_files import (
    download_google_drive_file,
    download_salesforce_file,
    list_google_drive_files,
    list_salesforce_files,
)
from utils.connector_oauth import get_valid_access_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BE Gap 288: Autopilot and Connectors name the same provider differently, and
# the two vocabularies must be translated -- never compared directly.
#
#   TenantAutopilotConfig.source_type  -> 'gdrive'      | 'salesforce'
#   TenantConnection.provider          -> 'google_drive'| 'salesforce'
#
# routers/connectors.py validates every OAuth callback against
# ["google_drive", "salesforce"] and stores that value, so a real Drive
# connection is always persisted as 'google_drive'. run_sync() below used to
# filter `TenantConnection.provider == config.source_type` directly, which for
# Drive compared 'gdrive' against 'google_drive' and therefore matched nothing:
# every Google Drive sync failed with "No active gdrive connection for tenant
# ..." while the Connectors screen simultaneously showed the account as
# connected (it queries by the 'google_drive' name).
#
# Salesforce is spelled identically in both vocabularies, which is precisely
# why this presented as a Google-Drive-only failure and why the existing tests
# did not catch it -- tests/test_autopilot.py's _make_connection() fixture
# built its connection with provider='gdrive', matching the buggy query rather
# than what routers/connectors.py actually writes.
#
# The frontend already performs this exact mapping when it checks connector
# status (app/ingestion/page.tsx: source_type === "gdrive" ? "google_drive" :
# "salesforce"); this is the same translation, on the side that acts on it.
SOURCE_TYPE_TO_PROVIDER = {
    "gdrive": "google_drive",
    "salesforce": "salesforce",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_sync(tenant_id: UUID, db_session: Session) -> dict:
    """
    Run a full Autopilot sync cycle for one tenant.

    Returns:
        {"processed": int, "skipped": int, "failed": int}
    """
    settings = get_settings()

    # 1. Load config — raise clearly if none configured
    config = db_session.exec(
        select(TenantAutopilotConfig).where(
            TenantAutopilotConfig.tenant_id == tenant_id
        )
    ).first()

    if not config:
        raise ValueError(f"No Autopilot config found for tenant {tenant_id}")

    logger.info(
        "Autopilot sync starting — tenant=%s source=%s folder=%s",
        tenant_id, config.source_type, config.source_ref,
    )

    # 2. Load the OAuth TenantConnection for this provider.
    # BE Gap 288: translate source_type -> provider; the two vocabularies are
    # independent (see SOURCE_TYPE_TO_PROVIDER above). An unknown source_type
    # is rejected here rather than silently matching no connection, so a bad
    # config value reads as a config error instead of "not connected".
    provider = SOURCE_TYPE_TO_PROVIDER.get(config.source_type)
    if provider is None:
        raise ValueError(
            f"Unsupported Autopilot source_type {config.source_type!r} for tenant "
            f"{tenant_id}. Expected one of: {sorted(SOURCE_TYPE_TO_PROVIDER)}."
        )

    connection = db_session.exec(
        select(TenantConnection).where(
            TenantConnection.tenant_id == tenant_id,
            TenantConnection.provider == provider,
            TenantConnection.status == "active",
        )
    ).first()

    if not connection:
        # Names the provider as Connectors spells it, so the message points at
        # the row the user actually has to create rather than at Autopilot's
        # internal source_type.
        raise ValueError(
            f"No active {provider} connection for tenant {tenant_id}. "
            "Please connect the account in Settings → Connectors."
        )

    # 3. Get a fresh, valid access token (handles token refresh automatically)
    access_token = get_valid_access_token(connection, settings, db_session)

    # 4. Find the last successful sync timestamp for incremental polling
    last_run = db_session.exec(
        select(TenantAutopilotLog)
        .where(
            TenantAutopilotLog.tenant_id == tenant_id,
            TenantAutopilotLog.source_type == config.source_type,
            TenantAutopilotLog.status == "SUCCESS",
        )
        .order_by(TenantAutopilotLog.ingested_at.desc())  # type: ignore[union-attr]
    ).first()

    since_dt: datetime | None = last_run.ingested_at if last_run else None
    logger.info("Incremental polling since: %s", since_dt)

    # 5. List files from cloud source
    if config.source_type == "gdrive":
        remote_files = list_google_drive_files(
            access_token, folder_id=config.source_ref
        )
        # list_google_drive_files returns dicts with 'id', 'name', 'type', 'size_bytes'
        # filter to actual files (not folders)
        remote_files = [f for f in remote_files if f.get("type") != "folder"]
    elif config.source_type == "salesforce":
        instance_url = connection.instance_url or ""
        remote_files = list_salesforce_files(access_token, instance_url)
    else:
        raise ValueError(f"Unsupported source_type: {config.source_type}")

    logger.info("Found %d remote files to evaluate", len(remote_files))

    # 6. Process each file
    processed = 0
    skipped = 0
    failed = 0
    batch_id = uuid4()
    newly_imported: list[dict] = []

    for remote_file in remote_files:
        file_id = remote_file["id"]
        file_name = remote_file.get("name", file_id)

        try:
            # --- Dedup Layer 1: Check source_file_id ---
            existing_by_id = db_session.exec(
                select(TenantAutopilotLog).where(
                    TenantAutopilotLog.tenant_id == tenant_id,
                    TenantAutopilotLog.source_file_id == file_id,
                    TenantAutopilotLog.status == "SUCCESS",
                )
            ).first()

            if existing_by_id:
                logger.debug("Skipping %s — already ingested by file ID", file_name)
                _write_log(
                    db_session, tenant_id, config.source_type,
                    file_id, content_hash="", status="SKIPPED_DUPLICATE",
                )
                skipped += 1
                continue

            # --- Download file bytes ---
            if config.source_type == "gdrive":
                file_bytes = download_google_drive_file(access_token, file_id)
            else:
                file_bytes = download_salesforce_file(
                    access_token, connection.instance_url or "", file_id
                )

            # --- Dedup Layer 2: Check content hash ---
            content_hash = hashlib.sha256(file_bytes).hexdigest()

            existing_by_hash = db_session.exec(
                select(TenantAutopilotLog).where(
                    TenantAutopilotLog.tenant_id == tenant_id,
                    TenantAutopilotLog.content_hash == content_hash,
                    TenantAutopilotLog.status == "SUCCESS",
                )
            ).first()

            if existing_by_hash:
                logger.debug(
                    "Skipping %s — content hash already ingested (renamed/moved file)", file_name
                )
                _write_log(
                    db_session, tenant_id, config.source_type,
                    file_id, content_hash=content_hash, status="SKIPPED_DUPLICATE",
                )
                skipped += 1
                continue

            # --- Upload to Azure Blob Storage ---
            invoice_id = uuid4()
            file_path = upload_pdf_to_blob_storage(
                file_bytes, str(tenant_id), str(invoice_id)
            )

            # --- Create Invoice DB row ---
            db_invoice = Invoice(
                id=invoice_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                file_path=file_path,
                file_hash=content_hash,
                status="PROCESSING",
                flow_direction=config.flow_direction,
                tags=[],
            )
            db_session.add(db_invoice)
            db_session.commit()
            db_session.refresh(db_invoice)

            # --- Dispatch extraction queue message ---
            _dispatch_queue(str(batch_id), file_path, str(tenant_id), str(invoice_id), settings)

            # --- Write SUCCESS log ---
            _write_log(
                db_session, tenant_id, config.source_type,
                file_id, content_hash=content_hash, status="SUCCESS",
            )
            processed += 1
            newly_imported.append({
                "invoice_id": str(invoice_id),
                "file_name": file_name,
                "flow_direction": config.flow_direction,
            })
            logger.info("Autopilot: ingested %s → invoice %s", file_name, invoice_id)

        except Exception as exc:
            logger.error("Autopilot: failed to process %s: %s", file_name, exc)
            _write_log(
                db_session, tenant_id, config.source_type,
                file_id, content_hash="", status="FAILED",
                error_detail=str(exc),
            )
            failed += 1

    if newly_imported and (config.notify_emails or []):
        from services.staff_notify import notify_autopilot_sync_summary

        notify_autopilot_sync_summary(
            db_session,
            tenant_id=tenant_id,
            notify_emails=config.notify_emails or [],
            imported=newly_imported,
            send_approval_links=bool(config.send_approval_links),
            frontend_base_url=settings.FRONTEND_URL or settings.PUBLIC_APP_URL or "",
        )

    summary = {"processed": processed, "skipped": skipped, "failed": failed}
    logger.info("Autopilot sync complete — tenant=%s summary=%s", tenant_id, summary)
    return summary


def run_sync_for_all_due_tenants(db_session: Session) -> None:
    """
    Called by the ACA Job script. Queries all TenantAutopilotConfig rows
    and runs sync for each. In MVP, all configured tenants run on every
    invocation (the ACA Job cron controls frequency).
    """
    configs = db_session.exec(select(TenantAutopilotConfig)).all()
    logger.info("Autopilot job: found %d tenants configured", len(configs))

    if not configs:
        logger.info("No tenants configured for Autopilot. Nothing to do.")
        return

    for config in configs:
        try:
            summary = run_sync(config.tenant_id, db_session)
            logger.info(
                "Tenant %s sync done: %s", config.tenant_id, summary
            )
        except Exception as exc:
            logger.error(
                "Autopilot job: unhandled error for tenant %s: %s",
                config.tenant_id, exc,
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_log(
    db_session: Session,
    tenant_id: UUID,
    source_type: str,
    source_file_id: str,
    content_hash: str,
    status: str,
    error_detail: str | None = None,
) -> None:
    """Write a single row to tenant_autopilot_logs."""
    log_entry = TenantAutopilotLog(
        tenant_id=tenant_id,
        source_type=source_type,
        source_file_id=source_file_id,
        content_hash=content_hash,
        status=status,
        error_detail=error_detail,
    )
    db_session.add(log_entry)
    db_session.commit()


def _dispatch_queue(
    batch_id: str,
    file_path: str,
    tenant_id: str,
    invoice_id: str,
    settings,
) -> None:
    """Dispatch an extraction task to the Azure Storage Queue."""
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        logger.warning(
            "AZURE_STORAGE_CONNECTION_STRING not set — skipping queue dispatch "
            "for invoice %s. It will remain at PROCESSING.", invoice_id
        )
        return

    try:
        from azure.storage.queue import QueueClient
        queue_client = QueueClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING,
            "extraction-tasks-queue",
        )
        payload = {
            "task": "process_invoice",
            "kwargs": {
                "batch_id": batch_id,
                "file_path": file_path,
                "tenant_id": tenant_id,
            },
        }
        queue_client.send_message(json.dumps(payload))
        logger.info("Dispatched extraction queue task for invoice %s", invoice_id)
    except Exception as exc:
        logger.error(
            "Failed to dispatch queue task for invoice %s: %s", invoice_id, exc
        )
