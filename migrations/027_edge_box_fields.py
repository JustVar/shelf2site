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

print("Running migration 027: add location, form_factor, partner, incomplete_reason to edge_boxes...")

with engine.begin() as conn:

    print("  Adding location column...")
    conn.execute(text("""
        ALTER TABLE edge_boxes ADD COLUMN IF NOT EXISTS location VARCHAR(100)
    """))

    print("  Adding form_factor column...")
    conn.execute(text("""
        ALTER TABLE edge_boxes ADD COLUMN IF NOT EXISTS form_factor VARCHAR(20)
    """))

    print("  Adding partner column...")
    conn.execute(text("""
        ALTER TABLE edge_boxes ADD COLUMN IF NOT EXISTS partner VARCHAR(100)
    """))

    print("  Adding incomplete_reason column...")
    conn.execute(text("""
        ALTER TABLE edge_boxes ADD COLUMN IF NOT EXISTS incomplete_reason TEXT
    """))

print("Migration 027 complete.")
