"""Add show_on_map field to edge_boxes table for map privacy controls.

This migration adds a boolean column to control whether an edge box appears
on the deployment map. Defaults to True for all existing boxes.

Admin-only field for privacy control (hide customer deployments if needed).

Usage:
    python scripts/add_show_on_map_field.py
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Ensure repo root is on sys.path (for absolute imports)
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.database import engine


def add_show_on_map_field():
    """Add show_on_map column to edge_boxes table."""

    print("Adding show_on_map field to edge_boxes table...")
    print("=" * 60)

    with engine.begin() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'edge_boxes'
            AND column_name = 'show_on_map'
        """))

        if result.fetchone():
            print("✓ Column 'show_on_map' already exists, skipping migration.")
            return

        # Add the column with default value True
        print("Adding column: show_on_map (boolean, default=True)...")
        conn.execute(text("""
            ALTER TABLE edge_boxes
            ADD COLUMN show_on_map BOOLEAN NOT NULL DEFAULT TRUE
        """))

        print("✓ Column added successfully")

        # Show count of boxes
        result = conn.execute(text("SELECT COUNT(*) FROM edge_boxes"))
        count = result.scalar()
        print(f"\n✓ All {count} edge boxes set to show_on_map=True by default")
        print("\nAdmins can now hide sensitive customer deployments from the map")
        print("via the edit modal in the web interface.")

    print("\n" + "=" * 60)
    print("✅ Migration complete!")


if __name__ == "__main__":
    add_show_on_map_field()
