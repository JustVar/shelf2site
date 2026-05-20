"""Migration 019: Add email delivery channel to notification subscriptions.

Adds deliver_email column to notification_subscriptions so users can opt-in
to receive email notifications alongside (or instead of) Slack DMs.
User.email already exists from migration 014.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

print("Running migration 019: Add deliver_email to notification_subscriptions...")
with engine.begin() as conn:

    conn.execute(text("""
        ALTER TABLE notification_subscriptions
            ADD COLUMN IF NOT EXISTS deliver_email BOOLEAN NOT NULL DEFAULT FALSE
    """))
    print("  ✓ Added deliver_email column to notification_subscriptions")

print("Migration 019 complete.")
