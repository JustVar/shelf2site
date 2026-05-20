"""Migration 020: Fulfillment — add fields for unified PCO view.

CustomerOrder:
  - is_sensitive      BOOLEAN — hides order from users without view_sensitive_customers
  - contract_value    NUMERIC(12,2) — total contract value (shown to users with financial access)
  - hardware_cost     NUMERIC(12,2) — internal hardware BOM cost

User:
  - view_sensitive_customers BOOLEAN (nullable, three-state) — permission flag
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

print("Running migration 020: Fulfillment fields...")
with engine.begin() as conn:

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS is_sensitive BOOLEAN NOT NULL DEFAULT FALSE
    """))
    print("  ✓ Added is_sensitive to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS contract_value NUMERIC(12, 2)
    """))
    print("  ✓ Added contract_value to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS hardware_cost NUMERIC(12, 2)
    """))
    print("  ✓ Added hardware_cost to customer_orders")

    conn.execute(text("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS view_sensitive_customers BOOLEAN DEFAULT NULL
    """))
    print("  ✓ Added view_sensitive_customers to users")

print("Migration 020 complete.")
