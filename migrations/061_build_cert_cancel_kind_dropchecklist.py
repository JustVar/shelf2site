"""061 - Build cert C2C-mimic port (B1): cancel fields + file kind + drop dead column.

Brings build_certification onto the C2C append-only pattern:
- cancel event fields (cancel_reason / cancelled_by / cancelled_at) mirroring c2c
  migration 059. A cancel is recorded as a NEW append-only row with
  cert_status='cancelled' carrying these; certify rows leave them NULL.
  cert_status is a free varchar(20) with no CHECK (051), so 'cancelled' needs no
  type change.
- build_certification_files.kind ('source' | 'composite') mirroring c2c migration
  060, so the finalized composite PDF can be persisted as a kind='composite' row
  and the report merge can filter to kind='source'.
- drops the dead checklist_file_path column (confirmed zero reads/writes).

Additive plus one drop, idempotent (ADD COLUMN IF NOT EXISTS / DROP COLUMN IF
EXISTS / CREATE INDEX IF NOT EXISTS), single all-or-nothing transaction.

Run:
    docker compose exec app python migrations/061_build_cert_cancel_kind_dropchecklist.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    # cancel event fields on build_certification (mirror c2c 059)
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS cancel_reason text",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS cancelled_by varchar(128)",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS cancelled_at timestamp",
    # source/composite kind on the files child table (mirror c2c 060)
    "ALTER TABLE build_certification_files ADD COLUMN IF NOT EXISTS kind varchar(16) NOT NULL DEFAULT 'source'",
    "CREATE INDEX IF NOT EXISTS idx_bcf_kind ON build_certification_files (build_certification_id, kind)",
    # drop the dead column (confirmed zero reads/writes in the scoping pass)
    "ALTER TABLE build_certification DROP COLUMN IF EXISTS checklist_file_path",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("061 done: build_certification cancel_* + files.kind + dropped checklist_file_path")


if __name__ == "__main__":
    print("Running migration 061: build cert cancel fields + file kind + drop checklist_file_path...")
    run()
    print("Migration 061 complete.")
