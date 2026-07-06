"""Migration 059: C2C cert append-only log - cancel event fields.

Adds cancel_reason / cancelled_by / cancelled_at to c2c_certification. In the
append-only cert log a cancel is recorded as a NEW row with status='cancelled'
carrying these fields; certify events leave them NULL. The provisioning-row index
(idx_c2c_cert_provisioning) is already NON-unique, so many events per provisioning
row are already allowed - no index change. is_complete is never touched (option D).

Additive, idempotent (ADD COLUMN IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/059_c2c_cert_cancel_fields.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE c2c_certification ADD COLUMN IF NOT EXISTS cancel_reason text",
    "ALTER TABLE c2c_certification ADD COLUMN IF NOT EXISTS cancelled_by varchar(128)",
    "ALTER TABLE c2c_certification ADD COLUMN IF NOT EXISTS cancelled_at timestamp",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("059 done: c2c_certification.cancel_reason + cancelled_by + cancelled_at")


if __name__ == "__main__":
    print("Running migration 059: C2C cert cancel event fields...")
    run()
    print("Migration 059 complete.")
