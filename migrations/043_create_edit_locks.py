"""Migration 043: Create edit_locks table for DB-backed lock management."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

engine = create_engine(os.getenv("DATABASE_URL"))

def run():
    with engine.begin() as conn:
        print("Migration 043: Creating edit_locks table...")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS edit_locks (
                resource_key VARCHAR(128) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username VARCHAR(128) NOT NULL,
                display_name VARCHAR(256) NOT NULL,
                level VARCHAR(16) NOT NULL DEFAULT 'viewing',
                acquired_at DOUBLE PRECISION NOT NULL,
                last_activity DOUBLE PRECISION NOT NULL
            )
        """))
        print("  edit_locks table created")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_edit_locks_user_id
            ON edit_locks (user_id)
        """))
        print("  index on user_id created")

        print("Migration 043 complete.")

if __name__ == "__main__":
    run()
