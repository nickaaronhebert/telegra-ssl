#!/usr/bin/env python3
"""
Migration: Add DNS check fields to clients table
Date: 2025-01-13
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.db import engine, SessionLocal

def migrate():
    """Add DNS check fields to clients table"""
    
    migrations = [
        ("dns_check_status", "ALTER TABLE clients ADD COLUMN dns_check_status VARCHAR"),
        ("dns_check_resolved_to", "ALTER TABLE clients ADD COLUMN dns_check_resolved_to VARCHAR"),
        ("dns_check_resolved_ips", "ALTER TABLE clients ADD COLUMN dns_check_resolved_ips TEXT"),
        ("dns_check_error", "ALTER TABLE clients ADD COLUMN dns_check_error TEXT"),
        ("dns_check_last_checked", "ALTER TABLE clients ADD COLUMN dns_check_last_checked TIMESTAMP")
    ]
    
    db = SessionLocal()
    try:
        # Check which columns already exist
        existing_result = db.execute(text("""
            SELECT name FROM pragma_table_info('clients') WHERE name LIKE 'dns_check%'
        """))
        existing_columns = {row[0] for row in existing_result}
        print(f"Existing DNS check columns: {existing_columns}")
        
        for col_name, migration in migrations:
            if col_name in existing_columns:
                print(f"Skipping {col_name} (already exists)")
                continue
            print(f"Executing: {migration}")
            db.execute(text(migration))
        
        db.commit()
        print("✅ Migration completed successfully!")
        
        # Verify columns exist (SQLite compatible)
        result = db.execute(text("""
            SELECT name FROM pragma_table_info('clients') WHERE name LIKE 'dns_check%' ORDER BY name
        """))
        
        print("\n📋 DNS check columns in clients table:")
        for row in result:
            print(f"  - {row[0]}")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
