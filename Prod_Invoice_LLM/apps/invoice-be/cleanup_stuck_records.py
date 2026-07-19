#!/usr/bin/env python3
"""
One-time cleanup script for stuck PROCESSING records and orphaned files.
Deletes invoice records that have been in PROCESSING status for more than 30 minutes
and their corresponding PDF files from storage.
Also cleans up orphaned PDF files in storage that have no corresponding database records.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from uuid import UUID
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

def cleanup_stuck_records(minutes_threshold: int = 30, dry_run: bool = False):
    """
    Find and delete invoice records that have been in PROCESSING status
    for more than the specified threshold (default 30 minutes).
    
    Args:
        minutes_threshold: Minutes threshold for considering a record as stuck
        dry_run: If True, only report what would be deleted without actually deleting
    """
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    
    # Calculate the cutoff time
    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_threshold)
    logger.info(f"Looking for PROCESSING records older than {minutes_threshold} minutes (before {cutoff_time})")
    
    with Session(engine) as session:
        # Find stuck records
        statement = select(Invoice).where(
            Invoice.status == "PROCESSING",
            Invoice.created_at < cutoff_time
        )
        stuck_records = session.exec(statement).all()
        
        logger.info(f"Found {len(stuck_records)} stuck PROCESSING records")
        
        if not stuck_records:
            logger.info("No stuck records found.")
            return 0
        
        # Display records that will be deleted
        logger.info("Records to be deleted:")
        for record in stuck_records:
            logger.info(f"  - ID: {record.id}, Batch: {record.batch_id}, Created: {record.created_at}, File: {record.file_path}")
        
        if dry_run:
            logger.info("DRY RUN - No actual deletions performed")
            return len(stuck_records)
        
        # Delete records and their files
        deleted_count = 0
        storage_errors = []
        
        for record in stuck_records:
            try:
                # Delete from storage first
                try:
                    delete_pdf_from_storage(record.file_path)
                    logger.info(f"  ✓ Deleted from storage: {record.file_path}")
                except Exception as e:
                    error_msg = f"Failed to delete from storage: {record.file_path} - {str(e)}"
                    logger.error(f"  ✗ {error_msg}")
                    storage_errors.append(error_msg)
                
                # Delete from database
                session.delete(record)
                deleted_count += 1
                logger.info(f"  ✓ Deleted database record: {record.id}")
                
            except Exception as e:
                logger.error(f"  ✗ Error processing record {record.id}: {str(e)}")
                session.rollback()
        
        try:
            session.commit()
            logger.info(f"Successfully deleted {deleted_count} stuck records")
        except Exception as e:
            logger.error(f"Failed to commit transaction: {str(e)}")
            session.rollback()
            raise
        
        # Summary
        logger.info("=== SUMMARY ===")
        logger.info(f"Total records deleted: {deleted_count}")
        logger.info(f"Storage deletion errors: {len(storage_errors)}")
        if storage_errors:
            logger.warning("Storage errors:")
            for error in storage_errors:
                logger.warning(f"  - {error}")
        
        return deleted_count

def cleanup_orphaned_files(dry_run: bool = False):
    """
    Find and delete PDF files in Azure Blob Storage that have no corresponding database records.
    
    Args:
        dry_run: If True, only report what would be deleted without actually deleting
    """
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    
    logger.info("Looking for orphaned PDF files in storage...")
    
    try:
        blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client("invoices")
        
        # Get all PDF files from storage
        blob_list = container_client.list_blobs(name_starts_with="tenants/")
        pdf_files = [blob.name for blob in blob_list if blob.name.endswith('.pdf')]
        
        logger.info(f"Found {len(pdf_files)} PDF files in storage")
        
        # Get all file paths from database
        with Session(engine) as session:
            statement = select(Invoice.file_path)
            db_files = session.exec(statement).all()
            db_file_paths = set()
            for fp in db_files:
                if fp.startswith("azure://"):
                    # Convert azure://container/path to container/path
                    db_file_paths.add(fp.replace("azure://", ""))
        
        # Find orphaned files
        orphaned_files = []
        for pdf_file in pdf_files:
            storage_path = f"invoices/{pdf_file}"
            if storage_path not in db_file_paths:
                orphaned_files.append(pdf_file)
        
        logger.info(f"Found {len(orphaned_files)} orphaned PDF files")
        
        if not orphaned_files:
            logger.info("No orphaned files found.")
            return 0
        
        # Display orphaned files
        logger.info("Orphaned files to be deleted:")
        for file in orphaned_files:
            logger.info(f"  - {file}")
        
        if dry_run:
            logger.info("DRY RUN - No actual deletions performed")
            return len(orphaned_files)
        
        # Delete orphaned files
        deleted_count = 0
        for file in orphaned_files:
            try:
                blob_client = container_client.get_blob_client(file)
                blob_client.delete_blob()
                logger.info(f"  ✓ Deleted orphaned file: {file}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"  ✗ Failed to delete {file}: {str(e)}")
        
        logger.info(f"Successfully deleted {deleted_count} orphaned files")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned files: {str(e)}")
        return 0

def main():
    parser = argparse.ArgumentParser(
        description="One-time cleanup of stuck PROCESSING records and orphaned files"
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="Minutes threshold for considering a record as stuck (default: 30)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--orphaned-only",
        action="store_true",
        help="Only cleanup orphaned files, skip stuck records"
    )
    
    args = parser.parse_args()
    
    try:
        total_deleted = 0
        
        if not args.orphaned_only:
            stuck_deleted = cleanup_stuck_records(minutes_threshold=args.minutes, dry_run=args.dry_run)
            total_deleted += stuck_deleted
        
        orphaned_deleted = cleanup_orphaned_files(dry_run=args.dry_run)
        total_deleted += orphaned_deleted
        
        logger.info(f"=== TOTAL DELETED ===")
        logger.info(f"Total items deleted: {total_deleted}")
        
        sys.exit(0)
    except Exception as e:
        logger.error(f"Cleanup failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
