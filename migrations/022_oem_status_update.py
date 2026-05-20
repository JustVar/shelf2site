"""Migration 022: Update OEM PO status values via CHECK constraint.

oem_purchase_orders:
  - Add CHECK constraint enforcing valid status values:
    'ordered', 'in_production', 'acceptance', 'receiving', 'verified', 'cancelled'
  - Old values 'partial' and 'received' are removed (table is empty, no data migration needed)
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

print("Running migration 022: OEM status update...")
with engine.begin() as conn:

    # Drop constraint first if it exists (safe re-run)
    conn.execute(text("""
        ALTER TABLE oem_purchase_orders
            DROP CONSTRAINT IF EXISTS oem_status_check
    """))
    print("  ✓ Dropped existing oem_status_check constraint (if any)")

    conn.execute(text("""
        ALTER TABLE oem_purchase_orders
            ADD CONSTRAINT oem_status_check
            CHECK (status IN (
                'ordered', 'in_production', 'acceptance',
                'receiving', 'verified', 'cancelled'
            ))
    """))
    print("  ✓ Added oem_status_check constraint to oem_purchase_orders")

print("Migration 022 complete.")
