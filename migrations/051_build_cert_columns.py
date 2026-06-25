"""051 - Build Certification (F3/S6a): add cert audit columns + indexes.

Adds 9 columns and 3 indexes to build_certification for the per-device,
append-only, OEM-serial-keyed certification audit trail. No data backfill
(table is empty). Idempotent: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF
NOT EXISTS, single all-or-nothing transaction.

Run:
    docker compose exec app python migrations/051_build_cert_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS oem_serial      varchar(64)",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS reason          varchar(20) NOT NULL DEFAULT 'initial'",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS qa_status       varchar(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS hw_status       varchar(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS cert_status     varchar(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS co_certified_at timestamp",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS customer_name   varchar(256)",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS order_number    varchar(64)",
    "ALTER TABLE build_certification ADD COLUMN IF NOT EXISTS sku             varchar(128)",
    "CREATE INDEX IF NOT EXISTS idx_build_cert_oem_serial  ON build_certification (oem_serial)",
    "CREATE INDEX IF NOT EXISTS idx_build_cert_cert_status ON build_certification (cert_status)",
    "CREATE INDEX IF NOT EXISTS idx_build_cert_created_at  ON build_certification (created_at)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("051 done: 9 columns + 3 indexes (idempotent)")


if __name__ == "__main__":
    run()
