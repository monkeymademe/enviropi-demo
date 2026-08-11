#!/usr/bin/env python3
"""
Database cleanup script for Enviro+ sensor data.
Removes all data older than 8 days, keeping only recent readings.
"""

import sqlite3
from datetime import datetime, timedelta
import logging

DB_PATH = "sensor_data.db"
DAYS_TO_KEEP = 8

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def cleanup_old_data():
    """Remove sensor readings older than DAYS_TO_KEEP days."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Calculate cutoff timestamp (8 days ago)
        cutoff_time = datetime.now().timestamp() - (DAYS_TO_KEEP * 24 * 3600)
        cutoff_date = datetime.fromtimestamp(cutoff_time)
        
        logger.info(f"Starting database cleanup...")
        logger.info(f"Keeping data from the last {DAYS_TO_KEEP} days")
        logger.info(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Count records before deletion
        cursor.execute("SELECT COUNT(*) FROM sensor_readings")
        total_before = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM sensor_readings WHERE timestamp < ?", (cutoff_time,))
        records_to_delete = cursor.fetchone()[0]
        
        if records_to_delete == 0:
            logger.info("No old data to clean up.")
            conn.close()
            return
        
        # Delete old records
        cursor.execute("DELETE FROM sensor_readings WHERE timestamp < ?", (cutoff_time,))
        deleted_count = cursor.rowcount
        
        # Count records after deletion
        cursor.execute("SELECT COUNT(*) FROM sensor_readings")
        total_after = cursor.fetchone()[0]
        
        # Vacuum database to reclaim space
        logger.info("Vacuuming database to reclaim disk space...")
        conn.execute("VACUUM")
        
        conn.commit()
        conn.close()
        
        logger.info(f"✓ Cleanup complete!")
        logger.info(f"  Records before: {total_before}")
        logger.info(f"  Records deleted: {deleted_count}")
        logger.info(f"  Records remaining: {total_after}")
        logger.info(f"  Disk space reclaimed")
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise

if __name__ == "__main__":
    cleanup_old_data()

