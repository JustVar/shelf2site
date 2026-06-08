"""Migration: Create user_tour_progress table.

Tracks which guided tours each user has completed or dismissed.
Server-side progress so it survives browser cache clears.

Run this migration on the server with:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/004_add_user_tour_progress.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS user_tour_progress (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tour_id VARCHAR(64) NOT NULL,
    completed_at TIMESTAMP DEFAULT NOW(),
    dismissed BOOLEAN DEFAULT FALSE,
    CONSTRAINT unique_user_tour UNIQUE (user_id, tour_id)
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tour_progress_user ON user_tour_progress(user_id);",
]


def run_migration():
    """Create user_tour_progress table and indexes."""

    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE))
        print("  Created table: user_tour_progress")

        for idx_sql in INDEXES:
            conn.execute(text(idx_sql))
        print("  Created index: idx_tour_progress_user")

    print("\nMigration 004 complete: user_tour_progress table created.")


if __name__ == "__main__":
    print("Running migration 004: Create user_tour_progress table...")
    run_migration()
