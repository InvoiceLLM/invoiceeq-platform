#!/usr/bin/env python3
"""
FULL CLEANUP SCRIPT - DESTRUCTIVE OPERATION
This script will delete ALL invoice records from the database and ALL PDF files from Azure Blob Storage.
Use with extreme caution. This is intended for starting fresh.
"""

import os
import sys
import logging
from sqlmodel import Session, select, create_engine
from config import get_settings
from models import Invoice
from services.storage import delete_pdf_from_storage
from azure.storage.blob import BlobServiceClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def full_cleanup(dry_run: bool = False):
    """
    Delete all invoice records from database and all PDF files from storage.
    
    Args:
        dry_run: If True, only report what would be deleted without actually deleting
    """
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    
    logger.warning("=== FULL CLEANUP - DESTRUCTIVE OPERATION ===")
    logger.warning("This will delete ALL invoice records and ALL PDF files")
    
    if dry_run:
        logger.info("DRY RUN MODE - No actual deletions will be performed")
    
    # Part 1: Delete all database records
    with Session(engine) as session:
        # Count all records
        count_statement = select(Invoice)
        all_records = session.exec(count_statement).all()
        total_records = len(all_records)
        
        logger.info(f"Found {total_records} invoice records in database")
        
        if not dry_run:
            # Delete all records
            for record in all_records:
                session.delete(record)
            
            session.commit()
            logger.info(f"Deleted {total_records} database records")
        else:
            logger.info(f"Would delete {total_records} database records (dry run)")
    
    # Part 2: Delete all PDF files from storage
    try:
        blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client("invoices")
        
        # Get all blobs
        blob_list = container_client.list_blobs()
        all_blobs = list(blob_list)
        total_blobs = len(all_blobs)
        
        logger.info(f"Found {total_blobs} files in Azure Blob Storage")
        
        if not dry_run:
            # Delete all blobs
            for blob in all_blobs:
                blob_client = container_client.get_blob_client(blob.name)
                blob_client.delete_blob()
                logger.info(f"Deleted: {blob.name}")
            
            logger.info(f"Deleted {total_blobs} files from storage")
        else:
            logger.info(f"Would delete {total_blobs} files from storage (dry run)")
            
    except Exception as e:
        logger.error(f"Failed to cleanup storage: {str(e)}")
        if not dry_run:
            logger.error("Storage cleanup failed but database cleanup may have succeeded")
    
    logger.warning("=== FULL CLEANUP COMPLETE ===")
    if dry_run:
        logger.info("Dry run completed. No changes were made.")
    else:
        logger.warning("ALL DATA HAS BEEN DELETED. SYSTEM IS NOW FRESH.")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="FULL CLEANUP - Delete all invoice records and PDF files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be deleted without actually deleting"
    )
    
    args = parser.parse_args()
    
    # Safety confirmation
    if not args.dry_run:
        print("⚠️  WARNING: This will delete ALL invoice records and ALL PDF files")
        print("This operation cannot be undone.")
        print("")
        confirm = input("Type 'DELETE ALL DATA' to confirm: ")
        if confirm != "DELETE ALL DATA":
            print("Operation cancelled.")
            sys.exit(0)
    
    try:
        full_cleanup(dry_run=args.dry_run)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Full cleanup failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
