"""Migration 050: Create build_certification and install_certification tables.

F1b of the Fulfillment buildout. One row per cert event, keyed to a
device_provisioning row.

- build_certification: device UUID, hardware_validation JSONB, Appliance version,
  license_counts JSONB, qa_checklist JSONB, certifier + co-certifier (text),
  checklist file path, certified_at.
- install_certification: completed_by_type (internal | partner), site designation,
  engineer, handoff date, site_checklist JSONB, deployment summary, checklist file
  path, certified_at.

Both: ON DELETE CASCADE from device_provisioning, free-text signers,
history-friendly (plain index, multiple certs per device allowed). All columns
beyond the FK are nullable, so partner installs and partial certs are fine.

Single transaction, all-or-nothing. Idempotent (IF NOT EXISTS throughout).

Run instructions:
    docker compose exec app python migrations/050_create_certification_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS build_certification (
                id                     SERIAL PRIMARY KEY,
                device_provisioning_id INTEGER NOT NULL
                    REFERENCES device_provisioning(id) ON DELETE CASCADE,
                device_uuid            VARCHAR(64),
                hardware_validation    JSONB,
                appliance_version         VARCHAR(64),
                license_counts         JSONB,
                qa_checklist           JSONB,
                certified_by           VARCHAR(128),
                co_certified_by        VARCHAR(128),
                checklist_file_path    VARCHAR(512),
                certified_at           TIMESTAMP,
                created_at             TIMESTAMP DEFAULT NOW()
            )
        """))
        print("  ok table build_certification")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_build_cert_device
                ON build_certification (device_provisioning_id)
        """))
        print("  ok index idx_build_cert_device")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS install_certification (
                id                     SERIAL PRIMARY KEY,
                device_provisioning_id INTEGER NOT NULL
                    REFERENCES device_provisioning(id) ON DELETE CASCADE,
                completed_by_type      VARCHAR(16),
                site_designation       VARCHAR(256),
                engineer               VARCHAR(128),
                handoff_date           DATE,
                site_checklist         JSONB,
                deployment_summary     TEXT,
                checklist_file_path    VARCHAR(512),
                certified_at           TIMESTAMP,
                created_at             TIMESTAMP DEFAULT NOW()
            )
        """))
        print("  ok table install_certification")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_install_cert_device
                ON install_certification (device_provisioning_id)
        """))
        print("  ok index idx_install_cert_device")


if __name__ == "__main__":
    print("Running migration 050: certification tables...")
    run()
    print("Migration 050 complete.")
