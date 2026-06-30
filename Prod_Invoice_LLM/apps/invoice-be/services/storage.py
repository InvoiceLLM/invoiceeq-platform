import os
import logging
from azure.storage.blob import BlobServiceClient
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
