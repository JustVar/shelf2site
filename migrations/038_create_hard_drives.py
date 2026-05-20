import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

print("Running migration 038: create hard_drives table...")

with engine.begin() as conn:

    print("  Creating hard_drives table...")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS hard_drives (
            id               SERIAL PRIMARY KEY,
            manufacturer     VARCHAR(100),
            model            VARCHAR(100),
            drive_type       VARCHAR(32),
            form_factor      VARCHAR(32),
            serial           VARCHAR(64) UNIQUE,
            capacity_tb      FLOAT,
            capacity_gb      INTEGER,
            interface        VARCHAR(32),
            rpm              VARCHAR(16),
            status           VARCHAR(64),
            location         VARCHAR(100),
            associated_device_serial VARCHAR(64),
            notes            TEXT,
            last_updated     TIMESTAMP,
            discovered_by    VARCHAR(64),
            data_completeness FLOAT,
            network_segment  VARCHAR(32),
            last_seen        TIMESTAMP,
            vendor           VARCHAR(255),
            purchase_date    DATE,
            purchase_price   FLOAT,
            purchase_order   VARCHAR(128),
            supplier_invoice VARCHAR(128),
            procurement_method VARCHAR(64),
            created_at       TIMESTAMP DEFAULT NOW(),
            updated_at       TIMESTAMP DEFAULT NOW()
        )
    """))

    print("  Creating index idx_hd_serial...")
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_hd_serial
            ON hard_drives (serial)
    """))

    print("  Creating index idx_hd_associated...")
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_hd_associated
            ON hard_drives (associated_device_serial)
    """))

print("Migration 038 complete.")
