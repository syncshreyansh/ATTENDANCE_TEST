#!/usr/bin/env python3
"""
Database Migration Script
Adds new columns and tables for enhanced features
Run this if upgrading from old version
"""

from main import app
from models import db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Add new columns and tables to existing database"""
    
    with app.app_context():
        logger.info("Starting database migration...")
        
        try:
            # Create all new tables (won't affect existing ones)
            db.create_all()
            logger.info("✓ All tables created/verified")
            
            # Check if we need to add new columns to existing tables
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            
            # Check Student table
            student_columns = [col['name'] for col in inspector.get_columns('student')]
            
            if 'face_hash' not in student_columns:
                logger.info("Adding 'face_hash' column to student table...")
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE student ADD COLUMN face_hash VARCHAR(64) UNIQUE'))
                    conn.commit()
                logger.info("✓ face_hash column added")
            
            # Check Attendance table
            attendance_columns = [col['name'] for col in inspector.get_columns('attendance')]
            
            if 'eye_contact_verified' not in attendance_columns:
                logger.info("Adding 'eye_contact_verified' column to attendance table...")
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE attendance ADD COLUMN eye_contact_verified BOOLEAN DEFAULT 0'))
                    conn.commit()
                logger.info("✓ eye_contact_verified column added")
            
            # Ensure parent_phone is not null (for existing records, set a default)
            logger.info("Checking parent_phone constraints...")
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM student WHERE parent_phone IS NULL OR parent_phone = ''"))
                null_count = result.scalar()
                
                if null_count > 0:
                    logger.warning(f"Found {null_count} students without parent phone")
                    logger.info("Setting default value '0000000000' for students without phone...")
                    conn.execute(text("UPDATE student SET parent_phone = '0000000000' WHERE parent_phone IS NULL OR parent_phone = ''"))
                    conn.commit()
                    logger.info("✓ Default phone numbers set")
            
            logger.info("=" * 60)
            logger.info("DATABASE MIGRATION COMPLETED SUCCESSFULLY")
            logger.info("=" * 60)
            
            # Print summary
            tables = inspector.get_table_names()
            logger.info(f"\nAvailable tables ({len(tables)}):")
            for table in sorted(tables):
                column_count = len(inspector.get_columns(table))
                logger.info(f"  - {table} ({column_count} columns)")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            import traceback
            traceback.print_exc()
            raise

if __name__ == '__main__':
    migrate_database()