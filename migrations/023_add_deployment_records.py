"""Migration 023: Create deployment_records table.

Tracks the post-ship installation journey for customer orders:
  - customer_order_id  FK → customer_orders (CASCADE)
  - site_id            FK → sites (SET NULL)
  - se_assigned_id     FK → users (SET NULL)
  - created_by         FK → users (SET NULL)
  - status CHECK: scheduled | in_transit | on_site | installing | complete | cancelled
  - Indexes on customer_order_id and status
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

print("Running migration 023: Add deployment_records table...")
with engine.begin() as conn:

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS deployment_records (
            id                  SERIAL PRIMARY KEY,
            customer_order_id   INTEGER NOT NULL REFERENCES customer_orders(id) ON DELETE CASCADE,
            site_id             INTEGER REFERENCES sites(id) ON DELETE SET NULL,
            address             TEXT,
            status              VARCHAR(32) NOT NULL DEFAULT 'scheduled',
            scheduled_date      DATE,
            installed_date      DATE,
            se_assigned_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            integrator_name     VARCHAR(256),
            integrator_contact  VARCHAR(256),
            notes               TEXT,
            created_at          TIMESTAMP NOT NULL DEFAULT now(),
            updated_at          TIMESTAMP NOT NULL DEFAULT now(),
            created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT deployment_status_check CHECK (
                status IN ('scheduled','in_transit','on_site','installing','complete','cancelled')
            )
        )
    """))
    print("  ✓ Created deployment_records table")

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_deployment_records_customer_order_id
            ON deployment_records(customer_order_id)
    """))
    print("  ✓ Created index on customer_order_id")

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_deployment_records_status
            ON deployment_records(status)
    """))
    print("  ✓ Created index on status")

print("Migration 023 complete.")
