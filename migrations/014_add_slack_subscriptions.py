"""Migration: Add Slack bot DM support + notification subscriptions.

Changes:
- users: add email, slack_user_id, slack_auto_match columns
- Create notification_subscriptions table for per-user event subscriptions

Subscription model:
- event_type NULL = all events for the resource
- resource_type/resource_id NULL = global subscription to all events of event_type
- UNIQUE constraint prevents duplicate subscriptions

Run on NUC:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/014_add_slack_subscriptions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        # --- Add email + Slack fields to users ---
        for col_sql in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(256)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_user_id VARCHAR(64)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_auto_match BOOLEAN NOT NULL DEFAULT TRUE",
        ]:
            conn.execute(text(col_sql))
        print("  ✓ Added email, slack_user_id, slack_auto_match to users")

        # --- Create notification_subscriptions table ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                -- NULL event_type means all events for the given resource
                event_type VARCHAR(64),
                -- NULL resource_type/resource_id means global subscription to event_type
                resource_type VARCHAR(64),
                resource_id INTEGER,
                deliver_slack BOOLEAN NOT NULL DEFAULT TRUE,
                deliver_inapp BOOLEAN NOT NULL DEFAULT TRUE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, event_type, resource_type, resource_id)
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nsub_user
            ON notification_subscriptions(user_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nsub_resource
            ON notification_subscriptions(resource_type, resource_id)
        """))

        print("  ✓ Created notification_subscriptions table")


if __name__ == "__main__":
    print("Running migration 014: Add Slack subscriptions...")
    run()
    print("Migration 014 complete.")
