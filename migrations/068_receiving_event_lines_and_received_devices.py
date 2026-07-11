"""H17 reconciliation schema (SCANNER_AUDIT §3 full tier, approved):

  * receiving_events.tracking_number — the inbound shipment label, so a
    tracking-class scan can auto-select its event;
  * receiving_event_lines — per-SKU expectations for ONE shipment,
    snapshotted from the matched OEM PO's outstanding lines;
  * received_devices — polymorphic unit↔event link (item_id for direct
    intakes, pending_device_id for the review queue) instead of adding
    receiving_event_id columns to 15+ legacy tables.

Extends the H3 baseline (migration 064) — receiving_events itself is only
ALTERed here, never re-created. Idempotent throughout.

Run:
    docker compose exec app python migrations/068_receiving_event_lines_and_received_devices.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

DDL = [
    "ALTER TABLE receiving_events ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(128)",
    """
    CREATE TABLE IF NOT EXISTS receiving_event_lines (
        id SERIAL PRIMARY KEY,
        receiving_event_id INTEGER NOT NULL REFERENCES receiving_events(id) ON DELETE CASCADE,
        sku VARCHAR(128) NOT NULL,
        qty_expected INTEGER NOT NULL DEFAULT 0,
        qty_received INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rel_event ON receiving_event_lines(receiving_event_id)",
    """
    CREATE TABLE IF NOT EXISTS received_devices (
        id SERIAL PRIMARY KEY,
        receiving_event_id INTEGER NOT NULL REFERENCES receiving_events(id) ON DELETE CASCADE,
        line_id INTEGER REFERENCES receiving_event_lines(id) ON DELETE SET NULL,
        item_id INTEGER REFERENCES item_schema.items(id) ON DELETE SET NULL,
        pending_device_id INTEGER REFERENCES pending_devices(id) ON DELETE SET NULL,
        serial VARCHAR(512),
        sku VARCHAR(128),
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rd_event ON received_devices(receiving_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_rd_pending ON received_devices(pending_device_id)",
]


def main():
    with engine.begin() as conn:
        for ddl in DDL:
            conn.execute(text(ddl))
    print("068 applied: tracking_number + receiving_event_lines + received_devices")


if __name__ == "__main__":
    main()
