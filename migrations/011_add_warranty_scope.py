"""Migration: Add warranty scope (internal/external) and internal loaner fields.

Splits warranties into:
- external: Manufacturer/third-party warranties (existing behavior)
- internal: Cross-team loaners, equipment shared between departments

New columns on device_warranties:
- warranty_scope: VARCHAR(16) DEFAULT 'external'
- loaner_from_team: VARCHAR(128)  (team that owns the equipment)
- loaner_to_team: VARCHAR(128)    (team currently using it)
- loaner_contact: VARCHAR(128)    (person responsible for the loaner)
- loaner_agreement: VARCHAR(128)  (internal agreement/ticket number)

Run on NUC:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/011_add_warranty_scope.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


NEW_COLUMNS = [
    ("warranty_scope", "VARCHAR(16) NOT NULL DEFAULT 'external'"),
    ("loaner_from_team", "VARCHAR(128)"),
    ("loaner_to_team", "VARCHAR(128)"),
    ("loaner_contact", "VARCHAR(128)"),
    ("loaner_agreement", "VARCHAR(128)"),
]


def run_migration():
    """Add warranty scope and internal loaner columns."""

    with engine.begin() as conn:
        for col_name, col_def in NEW_COLUMNS:
            try:
                conn.execute(text(
                    f"ALTER TABLE device_warranties ADD COLUMN {col_name} {col_def}"
                ))
                print(f"  Added column: device_warranties.{col_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print(f"  Column device_warranties.{col_name} already exists, skipping")
                else:
                    raise

        # Index for scope filtering
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_warranty_scope
            ON device_warranties (warranty_scope)
        """))
        print("  Created index: idx_warranty_scope")

    print("\nMigration 011 complete: warranty scope and loaner fields added.")


if __name__ == "__main__":
    print("Running migration 011: Add warranty scope fields...")
    run_migration()
