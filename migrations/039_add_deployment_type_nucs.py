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

print("Running migration 039: add deployment_type to nucs...")

with engine.begin() as conn:

    print("  Adding deployment_type column...")
    conn.execute(text("""
        ALTER TABLE nucs ADD COLUMN IF NOT EXISTS deployment_type VARCHAR(32) DEFAULT 'internal'
    """))

    print("  Setting existing NULL values to 'internal'...")
    conn.execute(text("""
        UPDATE nucs SET deployment_type = 'internal' WHERE deployment_type IS NULL
    """))

print("Migration 039 complete: deployment_type added to nucs, existing records set to 'internal'")
