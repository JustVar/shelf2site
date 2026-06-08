"""Migration: Create notifications table for in-app + Slack notification system.

Run this migration on the server with:
    cd /opt/asset_tracker
    source venv/bin/activate
    python migrations/010_add_notifications.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run_migration():
    """Create the notifications table."""

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                notification_type VARCHAR(64) NOT NULL,
                title VARCHAR(256) NOT NULL,
                message TEXT NOT NULL,
                link VARCHAR(512),
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                dismissed BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        print("  Created table: notifications")

        # Index for fast unread queries
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_notifications_unread
            ON notifications (is_read, dismissed, created_at DESC)
        """))
        print("  Created index: idx_notifications_unread")

    print("\nMigration 010 complete: notifications table created.")


if __name__ == "__main__":
    print("Running migration 010: Add notifications table...")
    run_migration()
