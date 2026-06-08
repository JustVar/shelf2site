"""Migration: Add Intune sync log table.

Creates intune_sync_log to track manual and scheduled sync runs.
The intune_device_id, intune_compliance, and intune_last_checkin columns
already exist on the computers table from prior setup.

Run on the server:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/015_add_intune_sync.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS intune_sync_log (
                id SERIAL PRIMARY KEY,
                synced_at TIMESTAMP NOT NULL DEFAULT NOW(),
                synced_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                devices_found INTEGER NOT NULL DEFAULT 0,
                devices_added INTEGER NOT NULL DEFAULT 0,
                devices_updated INTEGER NOT NULL DEFAULT 0,
                devices_skipped INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                error_message TEXT
            )
        """))
        print("  ✓ Created intune_sync_log table")

        # Ensure intune fields exist on computers (idempotent)
        for col_sql in [
            "ALTER TABLE computers ADD COLUMN IF NOT EXISTS intune_device_id VARCHAR(128)",
            "ALTER TABLE computers ADD COLUMN IF NOT EXISTS intune_compliance VARCHAR(32)",
            "ALTER TABLE computers ADD COLUMN IF NOT EXISTS intune_last_checkin TIMESTAMP",
        ]:
            conn.execute(text(col_sql))
        print("  ✓ Confirmed intune columns on computers table")


if __name__ == "__main__":
    print("Running migration 015: Add Intune sync log...")
    run()
    print("Migration 015 complete.")
