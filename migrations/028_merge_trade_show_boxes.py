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

print("Running migration 028: merge trade_show_boxes into edge_boxes...")

with engine.begin() as conn:

    print("  Adding external_id column to edge_boxes...")
    conn.execute(text("""
        ALTER TABLE edge_boxes ADD COLUMN IF NOT EXISTS external_id VARCHAR(64)
    """))

    print("  Copying trade_show_boxes rows into edge_boxes (skip MAC conflicts)...")
    conn.execute(text("""
        INSERT INTO edge_boxes
          (org, serial, status, part_number, external_id, mac_address,
           location, last_updated, deployment_type, discovered_by)
        SELECT
          org, serial, status, part_number, external_id,
          CASE WHEN mac_address IN (SELECT mac_address FROM edge_boxes WHERE mac_address IS NOT NULL)
               THEN NULL ELSE mac_address END,
          location, last_updated, 'trade_show', 'spreadsheet_import'
        FROM trade_show_boxes
    """))

    print("  Dropping trade_show_boxes table...")
    conn.execute(text("DROP TABLE trade_show_boxes"))

print("Migration 028 complete.")
