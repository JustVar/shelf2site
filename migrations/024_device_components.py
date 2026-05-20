import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

print("Running migration 024: device_components table...")

with engine.begin() as conn:

    print("  Creating device_components table...")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_components (
            id               SERIAL PRIMARY KEY,
            parent_table     VARCHAR(50)  NOT NULL,
            parent_id        INTEGER      NOT NULL,
            component_table  VARCHAR(50)  NOT NULL,
            component_id     INTEGER      NOT NULL,
            slot_label       VARCHAR(50),
            installed_date   DATE,
            removed_date     DATE,
            installed_by     VARCHAR(100),
            notes            TEXT,
            created_at       TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_active_component
                UNIQUE (component_table, component_id, removed_date)
        )
    """))

    print("  Creating index idx_dc_parent...")
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_dc_parent
            ON device_components (parent_table, parent_id)
    """))

    print("  Creating index idx_dc_component...")
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_dc_component
            ON device_components (component_table, component_id)
    """))

print("Migration 024 complete.")
