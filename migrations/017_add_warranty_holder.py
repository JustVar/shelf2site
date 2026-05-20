"""Migration 017: Add warranty_holder to device_warranties.

warranty_holder distinguishes who holds the warranty obligation:
  brand   — Company shipped the unit and holds the warranty
  oem       — OEM shipped directly and holds the warranty
  vendor    — Generic third-party/manufacturer warranty
  customer  — Customer-held warranty
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

print("Running migration 017: Add warranty_holder to device_warranties...")
with engine.begin() as conn:
    conn.execute(text("""
        ALTER TABLE device_warranties
        ADD COLUMN IF NOT EXISTS warranty_holder VARCHAR(32) DEFAULT 'brand'
    """))
    print("  ✓ Added warranty_holder to device_warranties (default: 'brand')")

print("Migration 017 complete.")
