"""Migration 058: pilot/loan model foundation columns.

Adds:
- customer_orders.order_type varchar(32) NOT NULL DEFAULT 'sale' - the single
  source of truth for order classification (sale | pilot | try_and_buy | demo).
  The DEFAULT backfills every existing order to 'sale' (Sale/PO) and gives the
  column a DB-level default so raw inserts get it too. Replaces reliance on
  device_provisioning.assignment_type for classification (retired, not dropped).
- customer_orders.expected_return date null - loan due date for non-sale types.
- device_provisioning.returned_date date null - per-camera return date; the
  order-level return status is derived (returned vs still-out).

Additive, idempotent (ADD COLUMN IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/058_add_order_type_and_returns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE customer_orders ADD COLUMN IF NOT EXISTS order_type varchar(32) NOT NULL DEFAULT 'sale'",
    "ALTER TABLE customer_orders ADD COLUMN IF NOT EXISTS expected_return date",
    "ALTER TABLE device_provisioning ADD COLUMN IF NOT EXISTS returned_date date",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("058 done: customer_orders.order_type (default sale) + expected_return; device_provisioning.returned_date")


if __name__ == "__main__":
    print("Running migration 058: pilot/loan foundation columns...")
    run()
    print("Migration 058 complete.")
