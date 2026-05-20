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

print("Running migration 029: drop storage_drives table...")

with engine.begin() as conn:

    print("  Dropping storage_drives...")
    conn.execute(text("DROP TABLE IF EXISTS storage_drives"))

print("Migration 029 complete.")
