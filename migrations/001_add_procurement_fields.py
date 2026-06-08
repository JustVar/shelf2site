"""Migration: Add procurement tracking fields to all inventory tables.

Run this migration on the server with:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/001_add_procurement_fields.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine
from app.models import Base, TABLE_MODELS


def run_migration():
    """Add procurement fields to all inventory tables."""

    # List of ALL tables with InventoryMixin (includes inventory + lifecycle tables)
    inventory_tables = [
        # Core inventory tables
        "edge_boxes",
        "trade_show_boxes",
        "gpus",
        "part_numbers",
        "monitors",
        "computers",
        "phones",
        "mobile_devices",
        "cameras",
        "network_equipment",
        "access_control",
        "webcams",
        "printers",
        "office_equipment",
        "nas_devices",
        # Lifecycle tracking tables (also inherit InventoryMixin)
        "device_warranties",
        "vendor_trials",
        "device_dispositions",
        "nas_drives",
    ]

    # SQL to add procurement columns
    add_columns_sql = """
    ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS vendor VARCHAR(128),
    ADD COLUMN IF NOT EXISTS purchase_date DATE,
    ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS purchase_order VARCHAR(64),
    ADD COLUMN IF NOT EXISTS supplier_invoice VARCHAR(128),
    ADD COLUMN IF NOT EXISTS procurement_method VARCHAR(32);
    """

    print("=" * 70)
    print("PROCUREMENT FIELDS MIGRATION")
    print("=" * 70)
    print("\nAdding procurement tracking fields to all inventory tables...\n")

    with engine.connect() as conn:
        for table in inventory_tables:
            print(f"  Updating {table}...", end=" ")
            try:
                conn.execute(text(add_columns_sql.format(table_name=table)))
                conn.commit()
                print("✓")
            except Exception as e:
                print(f"✗ (Error: {e})")
                conn.rollback()

    print("\n" + "=" * 70)
    print("Migration complete!")
    print("=" * 70)
    print("\nNew fields added to all inventory tables:")
    print("  - vendor (VARCHAR 128)")
    print("  - purchase_date (DATE)")
    print("  - purchase_price (NUMERIC 10,2)")
    print("  - purchase_order (VARCHAR 64)")
    print("  - supplier_invoice (VARCHAR 128)")
    print("  - procurement_method (VARCHAR 32)")
    print("\nRestart the asset tracker service to use the new fields:")
    print("  sudo systemctl restart hardware.asset.tracker.service")
    print()


if __name__ == "__main__":
    run_migration()
