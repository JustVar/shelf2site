"""Migration 055: Create c2c_certification table (C1).

C2C camera cert — one per-camera cert record, keyed to a device_provisioning
row (device_table='cameras'). Mirrors build_certification's provisioning-row
key so the order link and a serial snapshot come along for free.

Checklist + firmware evidence live in JSONB: volatile, point-in-time evidence
(what was on the cam at certification), expected to iterate as OEM firmware
matures. JSONB absorbs that churn with zero further migrations. The cameras
inventory table is not touched.

Additive, idempotent (IF NOT EXISTS throughout), single all-or-nothing
transaction.

Run:
    docker compose exec app python migrations/055_create_c2c_certification.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS c2c_certification (
        id serial PRIMARY KEY,
        device_provisioning_id integer NOT NULL
            REFERENCES device_provisioning(id) ON DELETE CASCADE,
        camera_serial_snapshot varchar(64),
        status varchar(16) NOT NULL DEFAULT 'pending',
        checklist jsonb,
        firmware_evidence jsonb,
        notes text,
        certified_by varchar(128),
        certified_at timestamp,
        created_at timestamp NOT NULL DEFAULT now(),
        created_by varchar(128)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_c2c_cert_provisioning "
    "ON c2c_certification (device_provisioning_id)",
    "CREATE INDEX IF NOT EXISTS idx_c2c_cert_status "
    "ON c2c_certification (status)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("055 done: c2c_certification table + provisioning/status indexes (idempotent)")


if __name__ == "__main__":
    print("Running migration 055: c2c_certification table...")
    run()
    print("Migration 055 complete.")
