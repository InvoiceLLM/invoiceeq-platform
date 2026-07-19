import os
import logging
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from config import settings

logger = logging.getLogger(__name__)

# Local temp storage folder fallback path
LOCAL_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_storage")

def upload_pdf_to_blob_storage(file_data: bytes, tenant_id: str, invoice_id: str) -> str:
    """
    Uploads invoice PDF bytes to Azure Blob Storage under:
    tenants/{tenant_id}/invoices/{invoice_id}.pdf
    
    If Azure Storage fails or is not configured properly, it falls back to storing 
    the file locally inside a workspace 'temp_storage' directory to allow offline development.
    """
    blob_name = f"tenants/{tenant_id}/invoices/{invoice_id}.pdf"
    
    # 1. Attempt Azure Blob Storage upload
    if settings.AZURE_STORAGE_CONNECTION_STRING and "your_azure_storage" not in settings.AZURE_STORAGE_CONNECTION_STRING:
        try:
            logger.info("Attempting upload to Azure Blob Storage: %s", blob_name)
            blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
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
            logger.warning("Azure Blob Storage upload failed, falling back to local storage: %s", e)
            
    # 2. Local Fallback (for offline testing)
    local_path = os.path.join(LOCAL_STORAGE_DIR, tenant_id, "invoices", f"{invoice_id}.pdf")
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    logger.info("Writing PDF file locally for offline fallback: %s", local_path)
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
            
            blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
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

        blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        try:
            blob_client.delete_blob()
        except ResourceNotFoundError:
            logger.info("Blob already absent for %s, nothing to delete.", file_path)
    else:
        if os.path.exists(file_path):
            os.remove(file_path)

