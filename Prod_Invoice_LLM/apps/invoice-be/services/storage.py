import os
import logging
import azure.storage.blob as azure_blob
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from config import settings

logger = logging.getLogger(__name__)

# Local temp storage folder fallback path
LOCAL_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_storage")


class StorageUploadError(RuntimeError):
    """Raised when blob storage upload fails or storage is unconfigured in production."""
    pass


def is_storage_configured() -> bool:
    """Returns True if AZURE_STORAGE_CONNECTION_STRING is set and not a placeholder."""
    cs = settings.AZURE_STORAGE_CONNECTION_STRING
    if not cs or not cs.strip():
        return False
    lower = cs.lower()
    if "your_azure_storage" in lower or "<your" in lower or "placeholder" in lower:
        return False
    return True


def upload_pdf_to_blob_storage(
    file_data: bytes,
    tenant_id: str,
    invoice_id: str,
    custom_blob_path: str | None = None,
) -> str:
    """
    Uploads invoice PDF bytes to Azure Blob Storage under:
    tenants/{tenant_id}/invoices/{invoice_id}.pdf
    or custom_blob_path if specified.

    Gap 673:
    - If Azure Storage is configured, attempts upload with SDK retries. If it fails,
      raises StorageUploadError (NEVER silently falls back to local container disk,
      which is ephemeral and loses customer files).
    - If Azure Storage is NOT configured:
      - In non-production environments (dev, test, local), allows writing locally
        to temp_storage for offline development.
      - In production, raises StorageUploadError immediately (fail-closed, Decision D3).
    """
    from config import NON_PRODUCTION_ENVIRONMENTS

    if custom_blob_path:
        blob_name = custom_blob_path
        local_rel_path = custom_blob_path
    else:
        blob_name = f"tenants/{tenant_id}/invoices/{invoice_id}.pdf"
        local_rel_path = os.path.join(tenant_id, "invoices", f"{invoice_id}.pdf")

    # 1. Attempt Azure Blob Storage upload when configured
    if is_storage_configured():
        try:
            logger.info("Attempting upload to Azure Blob Storage: %s", blob_name)
            # BE Gap 673: the storage SDK reads its own retry policy, not azure-core's
            # `retry_backoff_factor` / `retry_mode` kwargs (silently ignored). Its default
            # ExponentialRetry starts at a 15 s backoff, which would hold a user's upload
            # request for about a minute before the 503. Short, explicit backoff instead.
            blob_service_client = azure_blob.BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING,
                retry_policy=azure_blob.ExponentialRetry(initial_backoff=1, increment_base=2, retry_total=3),
            )
            container_name = "invoices"

            # Create container if it does not exist
            container_client = blob_service_client.get_container_client(container_name)
            try:
                container_client.create_container()
            except Exception:
                # Container already exists, ignore
                pass

            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
            blob_client.upload_blob(file_data, overwrite=True)

            return f"azure://{container_name}/{blob_name}"
        except Exception as e:
            logger.error("Azure Blob Storage upload failed for %s: %s", blob_name, e)
            raise StorageUploadError(f"Azure Blob Storage upload failed: {e}") from e

    # 2. Azure Storage is NOT configured:
    env = (settings.ENVIRONMENT or "").strip().lower()
    if env not in NON_PRODUCTION_ENVIRONMENTS:
        logger.error(
            "Azure Storage is not configured in production environment (%s). Refusing local disk fallback.",
            settings.ENVIRONMENT,
        )
        raise StorageUploadError(
            f"Azure Storage is not configured in {settings.ENVIRONMENT} environment."
        )

    # Local fallback for offline non-production testing
    local_path = os.path.join(LOCAL_STORAGE_DIR, local_rel_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    logger.info("Writing PDF file locally for offline fallback (non-production): %s", local_path)
    with open(local_path, "wb") as f:
        f.write(file_data)

    return local_path


def download_pdf_from_storage(file_path: str) -> bytes:
    """
    Downloads invoice PDF bytes from storage (Azure Blob Storage or Local Filesystem).
    
    If the path starts with 'azure://', it fetches from Azure. Otherwise, it loads
    from the local fallback path.
    """
    if file_path.startswith("azure://"):
        try:
            logger.info("Attempting download from Azure Blob Storage: %s", file_path)
            # Format: azure://{container}/{blob_name}
            # e.g. azure://invoices/tenants/{tenant_id}/invoices/{invoice_id}.pdf
            parts = file_path.replace("azure://", "").split("/", 1)
            container_name = parts[0]
            blob_name = parts[1]
            
            blob_service_client = azure_blob.BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
            download_stream = blob_client.download_blob()
            return download_stream.readall()
        except Exception as e:
            logger.error("Failed to download PDF from Azure Blob Storage: %s", e)
            raise e
    else:
        # Local filesystem path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Local file not found: {file_path}")
        logger.info("Reading PDF locally from: %s", file_path)
        with open(file_path, "rb") as f:
            return f.read()


def delete_pdf_from_storage(file_path: str) -> None:
    """
    Deletes an invoice PDF from storage (Azure Blob Storage or Local Filesystem).
    Mirrors download_pdf_from_storage's azure:// vs. local path branching.
    A missing blob/file is treated as already-deleted, not an error.
    """
    if file_path.startswith("azure://"):
        parts = file_path.replace("azure://", "").split("/", 1)
        container_name = parts[0]
        blob_name = parts[1]

        blob_service_client = azure_blob.BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        try:
            blob_client.delete_blob()
        except ResourceNotFoundError:
            logger.info("Blob already absent for %s, nothing to delete.", file_path)
    else:
        if os.path.exists(file_path):
            os.remove(file_path)
