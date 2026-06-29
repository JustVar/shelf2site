"""053 - Installation Certification (I1): per-deployment install cert table.

Creates installation_certification: one cert per deployment record (UNIQUE
deployment_record_id, CASCADE). The post-install PDF is stored as columns on
the row (single required artifact); bytes live on disk under
INSTALL_CERT_UPLOAD_DIR. Idempotent (CREATE TABLE / INDEX IF NOT EXISTS),
single all-or-nothing transaction.

Run:
    docker compose exec app python migrations/053_create_installation_certification.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS installation_certification (
        id serial PRIMARY KEY,
        deployment_record_id integer NOT NULL UNIQUE
            REFERENCES deployment_records(id) ON DELETE CASCADE,
        status varchar(16) NOT NULL DEFAULT 'pending',
        installer_name varchar(128),
        installer_company varchar(128),
        notes text,
        completion_date date,
        pdf_original_name varchar(256),
        pdf_stored_name varchar(256),
        pdf_content_type varchar(128),
        pdf_size_bytes integer,
        certified_by varchar(128),
        certified_at timestamp,
        created_at timestamp NOT NULL DEFAULT now(),
        created_by varchar(128)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ic_status ON installation_certification (status)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("053 done: installation_certification table + status index (idempotent)")


if __name__ == "__main__":
    run()
