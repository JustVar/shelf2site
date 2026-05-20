"""Migration 018: Add customer_orders, oem_purchase_orders tables.

customer_orders    — a customer order linked to a Salesforce opportunity/order.
                     Tracks SKU requirements, status, responsible SE, due date.
oem_purchase_orders — purchase orders placed with an OEM to fulfil a customer order.
device_provisioning — add customer_order_id FK (nullable) to link provisioning
                      records to the customer order they belong to.
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

print("Running migration 018: Add customer_orders + oem_purchase_orders...")
with engine.begin() as conn:

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS customer_orders (
            id                  SERIAL PRIMARY KEY,
            order_number        VARCHAR(32) UNIQUE NOT NULL,      -- AT-2001, AT-2002, …
            salesforce_order_id VARCHAR(64),                      -- manual entry, optional
            salesforce_opp_id   VARCHAR(64),                      -- SF Opportunity ID
            customer_name       VARCHAR(256) NOT NULL,
            customer_account    VARCHAR(256),                      -- company / org name
            sales_engineer      VARCHAR(128),                      -- person name (not FK — may not have account)
            sales_engineer_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            deployment_type     VARCHAR(32) DEFAULT 'direct',     -- direct | via_integrator | via_distributor
            integrator_name     VARCHAR(256),
            distributor_name    VARCHAR(256),
            due_date            DATE,
            status              VARCHAR(32) DEFAULT 'new',        -- new | sourcing | building | testing | shipped | delivered | installed
            sku_requirements    JSONB DEFAULT '[]'::jsonb,        -- [{model, qty, source: stock|oem|tbd}]
            pre_site_survey     TEXT,
            post_install_notes  TEXT,
            notes               TEXT,
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW(),
            created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL
        )
    """))
    print("  ✓ Created customer_orders table")

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_customer_orders_status
            ON customer_orders(status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_customer_orders_customer
            ON customer_orders(customer_name)
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oem_purchase_orders (
            id                  SERIAL PRIMARY KEY,
            customer_order_id   INTEGER REFERENCES customer_orders(id) ON DELETE SET NULL,
            vendor_name         VARCHAR(128) NOT NULL,
            po_number           VARCHAR(64),
            sku                 VARCHAR(128) NOT NULL,
            qty_ordered         INTEGER NOT NULL DEFAULT 1,
            qty_received        INTEGER NOT NULL DEFAULT 0,
            order_date          DATE,
            expected_delivery   DATE,
            received_date       DATE,
            status              VARCHAR(32) DEFAULT 'ordered',    -- ordered | partial | received | cancelled
            notes               TEXT,
            created_at          TIMESTAMP DEFAULT NOW()
        )
    """))
    print("  ✓ Created oem_purchase_orders table")

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_oem_po_customer_order
            ON oem_purchase_orders(customer_order_id)
    """))

    conn.execute(text("""
        ALTER TABLE device_provisioning
        ADD COLUMN IF NOT EXISTS customer_order_id INTEGER
            REFERENCES customer_orders(id) ON DELETE SET NULL
    """))
    print("  ✓ Added customer_order_id to device_provisioning")

print("Migration 018 complete.")
