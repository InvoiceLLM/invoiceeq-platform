"""
Feature 13: Tenant Autopilot — Core Sync Engine (services/autopilot_sync.py)

This is the shared entrypoint called by BOTH:
  - Manual "Sync Now" API endpoint (POST /api/v1/autopilot/sync)
  - Scheduled Azure Container Apps Job (scripts/autopilot_job.py)

Sync flow per tenant:
  1. Load TenantAutopilotConfig from DB
  2. Resolve a valid OAuth token for the configured provider (Google Drive)
  3. List files from the cloud folder (incremental: since last successful run)
  4. For each file — two-layer deduplication:
       Layer 1: source_file_id in tenant_autopilot_logs → skip if seen
       Layer 2: SHA-256 content hash in tenant_autopilot_logs → skip if seen
  5. Download bytes, upload to Azure Blob Storage
  6. Charge the free-tier quota for the new file (Gap 343) — a refusal here
     stops the run rather than ingesting past the tenant's allowance
  7. Create Invoice DB row + dispatch extraction queue message
  8. Write TenantAutopilotLog row (SUCCESS / SKIPPED_DUPLICATE / FAILED),
     stamped with this run's batch_id, trigger and the source file name
  9. Return summary: { processed, skipped, failed, quota_exhausted }

Gap 429 — history is hideable and pruned. Log rows carry `hidden_at` (a soft
delete driven from the Sync History screen) and `prune_autopilot_history()`
below hard-deletes aged-out noise rows once per scheduler pass. Neither touches
the dedup or watermark queries in run_sync(): those must see hidden rows, and
SUCCESS rows are never hard-deleted at all. See the section comment above
prune_autopilot_history() for why.

Gap 427 — runs, not files. Every log row this module writes now carries the
per-run `batch_id` (which already existed, but was only ever stamped on the
Invoice rows), the `trigger` that started the run ('manual' | 'scheduled') and
the human-readable file name. A run that finds nothing to do writes a single
NO_NEW_FILES marker row so that an empty run is still visible in history rather
than leaving no trace at all. GET /autopilot/history derives run-level totals
by grouping these rows -- there is deliberately no separate "run" table and no
end-of-run summary row to keep in sync with the per-file rows.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status as http_status
from sqlmodel import Session, select

from config import get_settings
from models import (
    Invoice,
    TenantAutopilotConfig,
    TenantAutopilotLog,
    TenantConnection,
)
from services.billing_quota import charge_free_quota
from services.storage import upload_pdf_to_blob_storage
from utils.connector_files import (
    download_google_drive_file,
    list_google_drive_files,
)
from utils.connector_oauth import get_valid_access_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BE Gap 288: Autopilot and Connectors name the same provider differently, and
# the two vocabularies must be translated -- never compared directly.
#
#   TenantAutopilotConfig.source_type  -> 'gdrive'
#   TenantConnection.provider          -> 'google_drive'
#
# routers/connectors.py validates every OAuth callback against
# ["google_drive"] and stores that value, so a real Drive connection is always
# persisted as 'google_drive'. run_sync() below used to filter
# `TenantConnection.provider == config.source_type` directly, which for Drive
# compared 'gdrive' against 'google_drive' and therefore matched nothing:
# every Google Drive sync failed with "No active gdrive connection for tenant
# ..." while the Connectors screen simultaneously showed the account as
# connected (it queries by the 'google_drive' name).
#
# Gap 334 (2026-08-28) removed Salesforce, which was the one provider spelled
# identically in both vocabularies -- which is precisely why the original bug
# presented as Google-Drive-only. The mapping is deliberately KEPT rather than
# inlined now that it has a single entry: the two vocabularies are still
# genuinely independent, and an unrecognised source_type must still fail
# loudly instead of silently matching zero connections.
SOURCE_TYPE_TO_PROVIDER = {
    "gdrive": "google_drive",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_sync(
    tenant_id: UUID,
    db_session: Session,
    trigger: str = "scheduled",
) -> dict:
    """
    Run a full Autopilot sync cycle for one tenant.

    Args:
        trigger: Gap 427 — what started this run, recorded on every log row it
            writes. Defaults to 'scheduled' because the unattended ACA job path
            (run_sync_for_all_due_tenants below) is the one that cannot pass it
            per-call; routers/autopilot.py::trigger_sync() passes 'manual'.

    Returns:
        {"processed": int, "skipped": int, "failed": int, "quota_exhausted": bool}
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
    #
    # Gap 429: this query deliberately does NOT filter on `hidden_at`. Hiding a
    # run is a display action taken in the UI; if a hidden SUCCESS row stopped
    # counting here, the watermark would jump backwards to an older run and the
    # next sync would re-list -- and, with the dedup queries below equally
    # blind, re-import -- everything since. Hidden means "not shown", never
    # "did not happen".
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
        # Gap 360: since_dt was computed above and logged, but never actually
        # reached this call -- every sync re-listed the whole folder from
        # scratch and re-wrote a SKIPPED_DUPLICATE row for every
        # already-ingested file, every run, forever. Dedup Layers 1/2 below
        # still run unconditionally as a safety net (clock skew, the first
        # sync after this fix lands where since_dt may be stale) -- this is
        # what actually stops most of the redundant work from happening.
        remote_files = list_google_drive_files(
            access_token, folder_id=config.source_ref, modified_after=since_dt
        )
        # list_google_drive_files returns dicts with 'id', 'name', 'type', 'size_bytes'
        # filter to actual files (not folders)
        remote_files = [f for f in remote_files if f.get("type") != "folder"]
    else:
        raise ValueError(f"Unsupported source_type: {config.source_type}")

    logger.info("Found %d remote files to evaluate", len(remote_files))

    # 6. Process each file
    processed = 0
    skipped = 0
    failed = 0
    quota_exhausted = False
    batch_id = uuid4()
    newly_imported: list[dict] = []

    # Gap 427: a run that found nothing still happened, and the user pressing
    # "Sync Now" needs to see that it ran and found nothing -- otherwise the
    # screen is indistinguishable from the sync never having fired. One marker
    # row, no file id, no hash. Written before the loop rather than after it so
    # that the "found nothing" case has exactly one row and the "found files"
    # case has none of these; the two are mutually exclusive by construction.
    if not remote_files:
        _write_log(
            db_session, tenant_id, config.source_type,
            source_file_id="", content_hash="", status="NO_NEW_FILES",
            batch_id=batch_id, trigger=trigger, source_file_name=None,
        )

    for remote_file in remote_files:
        file_id = remote_file["id"]
        file_name = remote_file.get("name", file_id)

        try:
            # --- Dedup Layer 1: Check source_file_id ---
            # Gap 429: no `hidden_at` filter, on purpose. A user who hides a run
            # from Sync History has not un-ingested its files, and a hidden
            # SUCCESS row must still block the re-import of the file it
            # records. Same for Layer 2 below.
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
                    batch_id=batch_id, trigger=trigger, source_file_name=file_name,
                )
                skipped += 1
                continue

            # --- Download file bytes ---
            # Unconditional: the listing step above already raised for any
            # source_type other than 'gdrive', so by this line Drive is the
            # only possibility. Gap 334 collapsed what used to be an
            # if-gdrive/else-salesforce pair -- deleting only the else arm
            # would have left a conditional with no fallback.
            file_bytes = download_google_drive_file(access_token, file_id)

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
                    batch_id=batch_id, trigger=trigger, source_file_name=file_name,
                )
                skipped += 1
                continue

            # --- Gap 343: charge the free-tier quota before ingesting ---
            #
            # This door used to create Invoice rows and charge nothing, so a Free
            # Tier tenant at free_invoices_remaining=0 kept ingesting for as long
            # as the scheduler kept polling -- and unattended, so nobody saw it.
            # Charged here, *after* both dedup layers, so a duplicate never burns
            # quota (Gap 189's rule) and *before* the blob upload, so a refused
            # file leaves nothing stored.
            #
            # Exhaustion is mirrored from routers/invoices.py, not reinvented:
            # nothing is ingested. There is no HTTP caller to hand a 402 to on the
            # scheduled path, so the equivalent here is a FAILED log row naming
            # the reason, and stopping -- every remaining file would be refused
            # for the same reason and downloading them anyway spends Drive API
            # calls for nothing. Dedup Layer 1 only skips rows with
            # status == "SUCCESS", so a file refused on quota is retried on the
            # next cycle once Gap 118's refill lands. Nothing is permanently lost.
            try:
                charge_free_quota(db_session, tenant_id, 1)
            except HTTPException as quota_exc:
                if quota_exc.status_code != http_status.HTTP_402_PAYMENT_REQUIRED:
                    raise
                quota_exhausted = True
                logger.warning(
                    "Autopilot: free-tier quota exhausted for tenant %s — stopping "
                    "this run at %s (%d already imported this run)",
                    tenant_id, file_name, processed,
                )
                _write_log(
                    db_session, tenant_id, config.source_type,
                    file_id, content_hash=content_hash, status="FAILED",
                    error_detail=(
                        "Free-tier invoice quota exhausted — this file was not "
                        "imported. It will be retried automatically after the "
                        "monthly quota refill, or immediately on a paid plan."
                    ),
                    batch_id=batch_id, trigger=trigger, source_file_name=file_name,
                )
                failed += 1
                break

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
                batch_id=batch_id, trigger=trigger, source_file_name=file_name,
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
                batch_id=batch_id, trigger=trigger, source_file_name=file_name,
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

    summary = {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        # Gap 343: distinguishes "some files failed" from "we stopped because the
        # tenant is out of allowance", which is the only one of the two the user
        # can act on. Surfaced by POST /autopilot/sync.
        "quota_exhausted": quota_exhausted,
    }
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

    # Gap 429: retention runs once per scheduler pass, before the syncs, so a
    # pass that fails partway through has still trimmed the table.
    prune_autopilot_history(db_session)

    for config in configs:
        try:
            # Gap 427: explicit rather than relying on the default, so the
            # scheduled path stays labelled correctly if that default ever moves.
            summary = run_sync(config.tenant_id, db_session, trigger="scheduled")
            logger.info(
                "Tenant %s sync done: %s", config.tenant_id, summary
            )
        except Exception as exc:
            logger.error(
                "Autopilot job: unhandled error for tenant %s: %s",
                config.tenant_id, exc,
            )


# ---------------------------------------------------------------------------
# Gap 429 — retention
# ---------------------------------------------------------------------------
#
# The only rows this ever hard-deletes are SKIPPED_DUPLICATE, FAILED and
# NO_NEW_FILES. SUCCESS rows are never deleted at any age, because they are the
# dedup ledger (source_file_id / content_hash) and the incremental watermark in
# run_sync() above -- deleting one re-opens the door for an invoice that was
# already ingested to be downloaded and imported a second time. SUCCESS rows can
# only be *hidden* (routers/autopilot.py::hide_autopilot_run).
#
# The three prunable statuses carry no such meaning: a SKIPPED_DUPLICATE row is
# the record of a decision that was made by looking at a SUCCESS row, a FAILED
# row nothing was ingested from, and NO_NEW_FILES is a marker that a run
# happened. They are also the rows that actually accumulate -- an unattended
# scheduler writes at least one of them on every pass, forever.

_PRUNABLE_STATUSES = ("SKIPPED_DUPLICATE", "FAILED", "NO_NEW_FILES")

# How often the prune is allowed to actually run. The scheduler pass may fire
# every few minutes; scanning and deleting on every one of those would be pure
# overhead, since a day-granularity retention window cannot change faster than
# once a day.
_PRUNE_INTERVAL = timedelta(hours=24)

# Module-level rather than a DB row on purpose: this is an optimisation, not a
# correctness guarantee. The job container is restarted regularly and each
# restart simply prunes once more than strictly needed, which is harmless --
# a second prune inside the same day deletes nothing, because the first one
# already removed everything past the cutoff.
_last_prune_at: datetime | None = None


def prune_autopilot_history(db_session: Session, force: bool = False) -> int:
    """Hard-delete aged-out NOISE log rows for every tenant with a config.

    Args:
        force: skip the once-per-24h guard. Used by tests, and available for a
            manual one-off run; the scheduler never passes it.

    Returns:
        The number of rows deleted (0 when the 24h guard skipped this call).
    """
    global _last_prune_at

    now = datetime.utcnow()
    if not force and _last_prune_at is not None and now - _last_prune_at < _PRUNE_INTERVAL:
        logger.debug(
            "Autopilot retention: skipped, last prune was %s", _last_prune_at
        )
        return 0

    configs = db_session.exec(select(TenantAutopilotConfig)).all()
    total_deleted = 0

    for config in configs:
        # Defensive: a row written before the column had a default, or edited
        # directly in the database, must not turn into a cutoff of "now".
        retention_days = config.history_retention_days or 90
        cutoff = now - timedelta(days=retention_days)

        stale = db_session.exec(
            select(TenantAutopilotLog).where(
                TenantAutopilotLog.tenant_id == config.tenant_id,
                TenantAutopilotLog.ingested_at < cutoff,
                TenantAutopilotLog.status.in_(_PRUNABLE_STATUSES),  # type: ignore[union-attr]
            )
        ).all()

        for row in stale:
            db_session.delete(row)

        if stale:
            logger.info(
                "Autopilot retention: deleted %d row(s) older than %s "
                "(%d day window) for tenant %s",
                len(stale), cutoff.isoformat(), retention_days, config.tenant_id,
            )
        total_deleted += len(stale)

    db_session.commit()
    _last_prune_at = now
    logger.info(
        "Autopilot retention pass complete — %d tenant(s), %d row(s) deleted",
        len(configs), total_deleted,
    )
    return total_deleted


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
    batch_id: UUID | None = None,
    trigger: str | None = None,
    source_file_name: str | None = None,
) -> None:
    """Write a single row to tenant_autopilot_logs.

    Gap 427: batch_id/trigger/source_file_name are what turn these rows into a
    readable *run* in GET /autopilot/history. They keep None defaults so the
    signature stays compatible with any caller outside this module, but every
    call site inside run_sync() passes all three -- a row written without a
    batch_id would silently fall into the endpoint's legacy bucket instead of
    the run it actually belongs to.
    """
    log_entry = TenantAutopilotLog(
        tenant_id=tenant_id,
        source_type=source_type,
        source_file_id=source_file_id,
        source_file_name=source_file_name,
        content_hash=content_hash,
        batch_id=batch_id,
        trigger=trigger,
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
