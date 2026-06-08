"""Migration: Add pipeline tracking fields to device_provisioning.

Adds date tracking and business pipeline stage fields to support
edge box deployment pipeline board (replaces MS Planner board).

New fields:
- due_date: Target completion/deployment date
- start_date: When provisioning began
- location_note: Current location or disposition notes
- deployment_bucket: Business pipeline stage (customer_po, confirmed_pilot, in_progress, certified, in_inventory)

Run this migration on the server with:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/005_add_provisioning_pipeline_fields.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


ADD_COLUMNS = """
ALTER TABLE device_provisioning
ADD COLUMN IF NOT EXISTS due_date DATE,
ADD COLUMN IF NOT EXISTS start_date DATE,
ADD COLUMN IF NOT EXISTS location_note TEXT,
ADD COLUMN IF NOT EXISTS deployment_bucket VARCHAR(32);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_provisioning_due_date ON device_provisioning(due_date);",
    "CREATE INDEX IF NOT EXISTS idx_provisioning_bucket ON device_provisioning(deployment_bucket);",
]


def run_migration():
    """Add pipeline tracking fields to device_provisioning table."""

    with engine.begin() as conn:
        conn.execute(text(ADD_COLUMNS))
        print("  Added columns: due_date, start_date, location_note, deployment_bucket")

        for idx_sql in INDEXES:
            conn.execute(text(idx_sql))
        print("  Created indexes: idx_provisioning_due_date, idx_provisioning_bucket")

    print("\nMigration 005 complete: Pipeline tracking fields added to device_provisioning.")


if __name__ == "__main__":
    print("Running migration 005: Add pipeline tracking fields to device_provisioning...")
    run_migration()
