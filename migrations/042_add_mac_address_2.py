"""Migration 042: Add mac_address_2 to edge_boxes and nucs tables."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

engine = create_engine(os.getenv("DATABASE_URL"))

def run():
    with engine.begin() as conn:
        print("Migration 042: Adding mac_address_2 to edge_boxes and nucs...")

        conn.execute(text("""
            ALTER TABLE edge_boxes
            ADD COLUMN IF NOT EXISTS mac_address_2 VARCHAR(64)
        """))
        print("  edge_boxes.mac_address_2 added")

        conn.execute(text("""
            ALTER TABLE nucs
            ADD COLUMN IF NOT EXISTS mac_address_2 VARCHAR(64)
        """))
        print("  nucs.mac_address_2 added")

        print("Migration 042 complete.")

if __name__ == "__main__":
    run()
