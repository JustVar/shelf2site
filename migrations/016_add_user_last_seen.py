"""Migration: Add last_seen_at to users table.

Tracks when each user last made an authenticated request. Updated (at most once
per 2 minutes) by get_current_user. Used by the maintenance announcement page
to show which users are currently active so admins can decide whether it is safe
to restart without warning anyone.

Run on the server:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/016_add_user_last_seen.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP
        """))
        print("  ✓ Added last_seen_at to users table")


if __name__ == "__main__":
    print("Running migration 016: Add user last_seen_at...")
    run()
    print("Migration 016 complete.")
