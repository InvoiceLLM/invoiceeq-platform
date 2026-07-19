#!/usr/bin/env python3
"""
Automated cleanup script for stuck PROCESSING records.
Deletes invoice records that have been in PROCESSING status for more than 30 minutes
and their corresponding PDF files from storage.
Intended for CI/CD pipeline integration.
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
            logger.info("No stuck records found. Exiting.")
            return
        
        # Display records that will be deleted
        logger.info("Records to be deleted:")
        for record in stuck_records:
            logger.info(f"  - ID: {record.id}, Batch: {record.batch_id}, Created: {record.created_at}, File: {record.file_path}")
        
        if dry_run:
            logger.info("DRY RUN - No actual deletions performed")
            return
        
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

def main():
    parser = argparse.ArgumentParser(
        description="Cleanup stuck PROCESSING records and their PDF files"
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
    
    args = parser.parse_args()
    
    try:
        cleanup_stuck_records(minutes_threshold=args.minutes, dry_run=args.dry_run)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Cleanup failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
