"""Migration 060: c2c_certification_files child table (cert source files + composite).

Mirrors build_certification_files. FK to c2c_certification (the cert EVENT row) ON DELETE
CASCADE, so files/composite are removed with their event. kind = 'source' | 'composite'.
Bytes live on disk under C2C_CERT_UPLOAD_DIR; the DB stores only metadata + stored_name.
Idempotent (CREATE TABLE / CREATE INDEX IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/060_create_c2c_certification_files.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS c2c_certification_files (
        id serial PRIMARY KEY,
        c2c_certification_id integer NOT NULL
            REFERENCES c2c_certification(id) ON DELETE CASCADE,
        camera_serial varchar(64),
        kind varchar(16) NOT NULL DEFAULT 'source',
        original_name varchar(512) NOT NULL,
        stored_name varchar(512) NOT NULL,
        content_type varchar(128),
        size_bytes integer,
        uploaded_by varchar(128),
        uploaded_at timestamp NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ccf_cert_id ON c2c_certification_files (c2c_certification_id)",
    "CREATE INDEX IF NOT EXISTS idx_ccf_kind ON c2c_certification_files (c2c_certification_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_ccf_camera_serial ON c2c_certification_files (camera_serial)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("060 done: c2c_certification_files table + indexes")


if __name__ == "__main__":
    print("Running migration 060: c2c_certification_files...")
    run()
    print("Migration 060 complete.")
