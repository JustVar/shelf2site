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

print("Running migration 034: create psus table...")

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS psus (
            id SERIAL PRIMARY KEY,
            manufacturer VARCHAR(100),
            model VARCHAR(100),
            serial VARCHAR(64),
            wattage_rating VARCHAR(32),
            energy_efficiency VARCHAR(32),
            status VARCHAR(64),
            location VARCHAR(100),
            associated_device_serial VARCHAR(64),
            notes TEXT,
            last_updated TIMESTAMP,
            discovered_by VARCHAR(64),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """))

print("Migration 034 complete.")
