"""Migration 044: Create error_log table for self-hosted error tracking."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

engine = create_engine(os.getenv("DATABASE_URL"))

def run():
    with engine.begin() as conn:
        print("Migration 044: Creating error_log table...")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS error_log (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                source VARCHAR(16) NOT NULL DEFAULT 'frontend',
                level VARCHAR(16) NOT NULL DEFAULT 'error',
                message TEXT NOT NULL,
                stack TEXT,
                url VARCHAR(512),
                user_id INTEGER,
                username VARCHAR(128),
                browser VARCHAR(256),
                context JSONB,
                fingerprint VARCHAR(64)
            )
        """))
        print("  error_log table created")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_error_log_created_at
            ON error_log (created_at DESC)
        """))
        print("  index on created_at created")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_error_log_fingerprint
            ON error_log (fingerprint)
        """))
        print("  index on fingerprint created")

        print("Migration 044 complete.")

if __name__ == "__main__":
    run()
