"""Safely reset inventory tables while preserving critical system data.

This script drops ONLY inventory device tables, preserving:
  - users (user accounts and authentication)
  - audit_log (full audit trail)
  - device_credentials (encrypted credential vault)
  - scanner_logs (network scanner history)
  - oui_allowlist (OUI prefix configuration)
  - pending_devices (device approval queue)
  - receiving_events (shipment intake tracking)
  - intake_photos (label photos)
  - device_warranty (warranty tracking)
  - warranty_claim (RMA claims)
  - vendor_trial (try & buy trials)
  - device_disposition (disposal/EOL records)
  - nas_drive (NAS bay management)

Use this script instead of Base.metadata.drop_all() to avoid losing user accounts
and audit history during inventory re-imports.

Usage:
    python scripts/reset_inventory_safe.py
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Ensure repo root is on sys.path (for absolute imports)
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.database import SessionLocal, engine
from app.models import TABLE_MODELS


def reset_inventory_tables():
    """Drop and recreate all inventory tables, preserving system tables."""

    # List of inventory table names to drop (from TABLE_MODELS)
    inventory_tables = list(TABLE_MODELS.keys())

    print("Safe Inventory Reset")
    print("=" * 60)
    print("\nThis will DROP the following inventory tables:")
    for table in sorted(inventory_tables):
        print(f"  - {table}")

    print("\nThe following CRITICAL tables will be PRESERVED:")
    critical_tables = [
        "users",
        "audit_log",
        "device_credentials",
        "scanner_logs",
        "oui_allowlist",
        "pending_devices",
        "receiving_events",
        "intake_photos",
        "device_warranty",
        "warranty_claim",
        "vendor_trial",
        "device_disposition",
        "nas_drive",
    ]
    for table in sorted(critical_tables):
        print(f"  - {table}")

    print("\n" + "=" * 60)
    confirm = input("\nType 'yes' to proceed with inventory reset: ").strip().lower()

    if confirm != "yes":
        print("Aborted.")
        return

    print("\nDropping inventory tables...")

    with engine.begin() as conn:
        # Drop tables in reverse dependency order (to handle foreign keys)
        # Since most inventory tables are independent, we can drop them directly
        for table_name in inventory_tables:
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
                print(f"  ✓ Dropped {table_name}")
            except Exception as e:
                print(f"  ✗ Failed to drop {table_name}: {e}")

    print("\nRecreating inventory tables...")

    # Import all inventory models to register them with Base.metadata
    from app.models import (
        AccessControl, Camera, Computer, EdgeBox, GPU,
        MobileDevice, Monitor, NetworkEquipment, NASDevice, OfficeEquipment,
        PartNumber, Phone, Printer, Webcam,
    )
    from app.database import Base

    # Create only the inventory tables (Base.metadata will skip existing tables)
    Base.metadata.create_all(engine)

    print("\n✅ Inventory reset complete!")
    print("\nCritical system tables preserved:")
    print("  - User accounts intact")
    print("  - Audit log intact")
    print("  - Credentials vault intact")
    print("  - Scanner logs intact")
    print("  - Warranty & lifecycle data intact")

    # Show current database status
    db = SessionLocal()
    try:
        from app.models import User
        user_count = db.query(User).count()
        print(f"\n{user_count} user account(s) still active")
    except Exception as e:
        print(f"\nWarning: Could not verify user count: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    reset_inventory_tables()
