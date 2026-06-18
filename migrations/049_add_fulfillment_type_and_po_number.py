"""Migration 049: Add fulfillment_type, order-level default, and the PO gate.

F1a of the Fulfillment buildout. Additive and nullable, no backfill.

Changes:
- device_provisioning.fulfillment_type  VARCHAR(32) NULL
    Per-device authoritative type: build | prebuilt_software | prebuilt_finished.
    NULL means the device is not yet in the fulfillment pipeline.
- customer_orders.default_fulfillment_type  VARCHAR(32) NULL
    Order-level convenience default that pre-fills new device rows.
- customer_orders.po_number  VARCHAR(64) NULL + UNIQUE index
    Salesforce PO, entered manually. One PO maps to one order. UNIQUE allows
    many NULLs so existing and draft orders are unaffected. The
    required-to-enter-pipeline rule is enforced in application logic, not as
    NOT NULL.

Single transaction, all-or-nothing. Idempotent (IF NOT EXISTS throughout).

Run instructions:
    docker compose exec app python migrations/049_add_fulfillment_type_and_po_number.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        # device_provisioning: per-device authoritative type
        conn.execute(text(
            "ALTER TABLE device_provisioning "
            "ADD COLUMN IF NOT EXISTS fulfillment_type VARCHAR(32)"
        ))
        print("  ok device_provisioning.fulfillment_type VARCHAR(32) NULL")

        # customer_orders: order-level default
        conn.execute(text(
            "ALTER TABLE customer_orders "
            "ADD COLUMN IF NOT EXISTS default_fulfillment_type VARCHAR(32)"
        ))
        print("  ok customer_orders.default_fulfillment_type VARCHAR(32) NULL")

        # customer_orders: PO gate
        conn.execute(text(
            "ALTER TABLE customer_orders "
            "ADD COLUMN IF NOT EXISTS po_number VARCHAR(64)"
        ))
        print("  ok customer_orders.po_number VARCHAR(64) NULL")

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_orders_po_number "
            "ON customer_orders (po_number)"
        ))
        print("  ok unique index uq_customer_orders_po_number")


if __name__ == "__main__":
    print("Running migration 049: fulfillment_type + po_number...")
    run()
    print("Migration 049 complete.")
