"""Migration 021: Add shipping fields to customer_orders.

CustomerOrder:
  - shipped_date      DATE     — when the order was shipped
  - delivered_date    DATE     — when the order was delivered
  - carrier           VARCHAR(64)  — shipping carrier name (e.g. FedEx, UPS)
  - tracking_number   VARCHAR(128) — carrier tracking number
  - shipping_address  TEXT     — recipient street address
  - ship_method       VARCHAR(32)  — 'carrier' or 'transferred'
  - recipient_name    VARCHAR(256) — name of the recipient
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

print("Running migration 021: Add shipping fields...")
with engine.begin() as conn:

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS shipped_date DATE
    """))
    print("  ✓ Added shipped_date to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS delivered_date DATE
    """))
    print("  ✓ Added delivered_date to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS carrier VARCHAR(64)
    """))
    print("  ✓ Added carrier to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(128)
    """))
    print("  ✓ Added tracking_number to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS shipping_address TEXT
    """))
    print("  ✓ Added shipping_address to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS ship_method VARCHAR(32)
    """))
    print("  ✓ Added ship_method to customer_orders")

    conn.execute(text("""
        ALTER TABLE customer_orders
            ADD COLUMN IF NOT EXISTS recipient_name VARCHAR(256)
    """))
    print("  ✓ Added recipient_name to customer_orders")

print("Migration 021 complete.")
