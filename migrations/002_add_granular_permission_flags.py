"""Migration: Add granular page/feature permission flags to users table.

Adds 7 new boolean columns for fine-grained RBAC control:
- can_manage_users: Admin > Users page access
- can_manage_system: OUI, scanner, storage, spreadsheet sync
- can_view_audit_log: Audit log page access
- can_access_receiving: Receiving & Intake page
- can_access_map: Edge box map page
- can_access_disposal: Disposal & EOL page
- can_access_credentials: Credentials vault

Run this migration on the NUC with:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/002_add_granular_permission_flags.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


NEW_COLUMNS = [
    ("can_manage_users", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("can_manage_system", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("can_view_audit_log", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("can_access_receiving", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("can_access_map", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("can_access_disposal", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("can_access_credentials", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def run_migration():
    """Add granular permission flag columns to users table."""

    with engine.begin() as conn:
        for col_name, col_def in NEW_COLUMNS:
            try:
                conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"
                ))
                print(f"  Added column: users.{col_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print(f"  Column users.{col_name} already exists, skipping")
                else:
                    raise

    print("\nMigration 002 complete: granular permission flags added to users table.")


if __name__ == "__main__":
    print("Running migration 002: Add granular permission flags...")
    run_migration()
