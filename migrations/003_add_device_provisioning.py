"""Migration: Create device_provisioning table.

Tracks pre-deployment provisioning workflow stages for devices.
Uses JSONB for flexible stage tracking (customizable per device).

Run this migration on the server with:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/003_add_device_provisioning.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS device_provisioning (
    id SERIAL PRIMARY KEY,
    device_table VARCHAR(64) NOT NULL,
    device_id INTEGER NOT NULL,
    site_id INTEGER REFERENCES sites(id),
    current_stage VARCHAR(32) NOT NULL DEFAULT 'staged',
    stages JSONB NOT NULL,
    assigned_to INTEGER REFERENCES users(id),
    notes TEXT,
    priority VARCHAR(16) DEFAULT 'normal',
    is_complete BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id)
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_provisioning_device ON device_provisioning(device_table, device_id);",
    "CREATE INDEX IF NOT EXISTS idx_provisioning_stage ON device_provisioning(current_stage) WHERE NOT is_complete;",
]


def run_migration():
    """Create device_provisioning table and indexes."""

    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE))
        print("  Created table: device_provisioning")

        for idx_sql in INDEXES:
            conn.execute(text(idx_sql))
        print("  Created indexes: idx_provisioning_device, idx_provisioning_stage")

    print("\nMigration 003 complete: device_provisioning table created.")


if __name__ == "__main__":
    print("Running migration 003: Create device_provisioning table...")
    run_migration()
