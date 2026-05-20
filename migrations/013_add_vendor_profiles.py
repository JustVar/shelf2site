"""Migration: Add vendor_profiles table.

Creates a standalone vendor profile table that soft-links to existing
vendor string fields across all inventory tables. No FK changes needed —
matching is done by name at query time.

Run on NUC:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/013_add_vendor_profiles.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        # --- Create vendor_profiles table ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS vendor_profiles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) UNIQUE NOT NULL,
                display_name VARCHAR(128),
                contact_name VARCHAR(128),
                contact_email VARCHAR(256),
                contact_phone VARCHAR(64),
                website VARCHAR(512),
                is_oem BOOLEAN NOT NULL DEFAULT FALSE,
                categories_supplied TEXT,
                notes TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vendor_profiles_name
            ON vendor_profiles(name)
        """))

        print("  ✓ Created vendor_profiles table")


if __name__ == "__main__":
    print("Running migration 013: Add vendor profiles...")
    run()
    print("Migration 013 complete.")
