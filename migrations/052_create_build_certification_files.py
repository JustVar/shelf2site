"""052 - Build Certification files (F3/S6d): report uploads child table.

Creates build_certification_files: multiple report files per cert, keyed to
both the cert row (build_certification_id, CASCADE) and the box (oem_serial,
lifetime anchor). Stores file metadata only; bytes live on disk under
CERT_UPLOAD_DIR. Idempotent (CREATE TABLE / INDEX IF NOT EXISTS), single
all-or-nothing transaction.

Run:
    docker compose exec app python migrations/052_create_build_certification_files.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS build_certification_files (
        id serial PRIMARY KEY,
        build_certification_id integer NOT NULL
            REFERENCES build_certification(id) ON DELETE CASCADE,
        oem_serial varchar(64),
        original_name varchar(512) NOT NULL,
        stored_name varchar(512) NOT NULL,
        content_type varchar(128),
        size_bytes integer,
        uploaded_by varchar(128),
        uploaded_at timestamp NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bcf_cert_id ON build_certification_files (build_certification_id)",
    "CREATE INDEX IF NOT EXISTS idx_bcf_oem_serial ON build_certification_files (oem_serial)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("052 done: build_certification_files table + 2 indexes (idempotent)")


if __name__ == "__main__":
    run()
