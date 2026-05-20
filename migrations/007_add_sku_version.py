"""Migration: Add SKU version tracking to edge_boxes.

Tracks whether edge boxes use legacy SKUs (PVA-*) or new 2026 SKUs (EDGE*).
Enables filtering, conversion, and clear visual differentiation in the UI.

New field:
- sku_version: VARCHAR(16) - "legacy" or "2026"

Run this migration on the NUC with:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/007_add_sku_version.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


ADD_COLUMN = """
ALTER TABLE edge_boxes
ADD COLUMN IF NOT EXISTS sku_version VARCHAR(16) DEFAULT 'legacy';
"""

# Update existing records based on part_number pattern
UPDATE_EXISTING = """
UPDATE edge_boxes
SET sku_version = CASE
    WHEN part_number LIKE 'PVA-%' THEN 'legacy'
    WHEN part_number LIKE 'EDGE%' THEN '2026'
    ELSE 'legacy'
END
WHERE sku_version IS NULL OR sku_version = '';
"""

CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_edge_boxes_sku_version
ON edge_boxes(sku_version);
"""


def run_migration():
    """Add SKU version field to edge_boxes table."""

    with engine.begin() as conn:
        conn.execute(text(ADD_COLUMN))
        print("  Added column: sku_version")

        conn.execute(text(UPDATE_EXISTING))
        print("  Updated existing records based on part_number pattern")

        conn.execute(text(CREATE_INDEX))
        print("  Created index: idx_edge_boxes_sku_version")

    print("\nMigration 007 complete: SKU version tracking added to edge_boxes.")


if __name__ == "__main__":
    print("Running migration 007: Add SKU version tracking to edge_boxes...")
    run_migration()
