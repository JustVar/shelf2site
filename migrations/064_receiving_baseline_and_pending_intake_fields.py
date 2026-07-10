"""Baseline receiving_events + pending_devices, and add scan-intake fields
to pending_devices (scanner Phase 2, H3).

Both tables existed only via Base.metadata.create_all at app startup — no
migration file covered them (SCANNER_AUDIT F14 note), so this file is their
baseline: fresh databases now match production without relying on create_all
ordering. The ALTERs stop the pending path from discarding what the scan
knew (serial / model / notes / receiving-event linkage).

Deliberate choice: received_quantity and the status columns carry NO SQL
DEFAULT because the model defaults are Python-side and create_all emits none
— this file matches create_all output exactly rather than diverging.

Idempotent. Run:
    docker compose exec app python migrations/064_receiving_baseline_and_pending_intake_fields.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

STATEMENTS = [
    # Baselines — no-ops on the live DB; parity for fresh databases.
    """
    CREATE TABLE IF NOT EXISTS receiving_events (
        id serial PRIMARY KEY,
        received_date timestamp DEFAULT now(),
        vendor varchar(255),
        purchase_order varchar(64),
        expected_quantity integer,
        received_quantity integer,
        status varchar(32),
        notes text,
        created_by integer REFERENCES users(id),
        created_at timestamp DEFAULT now(),
        updated_at timestamp DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_devices (
        id serial PRIMARY KEY,
        mac_address varchar(64) NOT NULL,
        ip_address varchar(45),
        hostname varchar(128),
        manufacturer varchar(128),
        suggested_table varchar(64),
        scanner_id varchar(64),
        network_segment varchar(32),
        first_seen timestamp DEFAULT now(),
        last_seen timestamp DEFAULT now(),
        status varchar(16),
        reviewed_by integer REFERENCES users(id),
        reviewed_at timestamp,
        dismiss_reason text
    )
    """,
    # H3: preserve what the scan knew.
    "ALTER TABLE pending_devices ADD COLUMN IF NOT EXISTS serial varchar(64)",
    "ALTER TABLE pending_devices ADD COLUMN IF NOT EXISTS model varchar(128)",
    "ALTER TABLE pending_devices ADD COLUMN IF NOT EXISTS notes text",
    (
        "ALTER TABLE pending_devices ADD COLUMN IF NOT EXISTS receiving_event_id "
        "integer REFERENCES receiving_events(id) ON DELETE SET NULL"
    ),
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("064 done: receiving_events/pending_devices baselined; pending intake fields added")


if __name__ == "__main__":
    print("Running migration 064...")
    run()
    print("Migration complete.")
