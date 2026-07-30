"""070 - Installation re-certification: allow more than one attempt per deployment.

Drops the UNIQUE constraint on deployment_record_id so a deployment record can
carry several certification attempts, and adds the two columns that tell an
initial certification apart from a re-certification. Existing rows take the
column default and become 'initial'. Idempotent (IF EXISTS / IF NOT EXISTS),
single all-or-nothing transaction.

Run:
    docker compose exec app python migrations/070_installation_recertification.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    ALTER TABLE installation_certification
        DROP CONSTRAINT IF EXISTS installation_certification_deployment_record_id_key
    """,
    """
    ALTER TABLE installation_certification
        ADD COLUMN IF NOT EXISTS reason varchar(20) NOT NULL DEFAULT 'initial'
    """,
    """
    ALTER TABLE installation_certification
        ADD COLUMN IF NOT EXISTS recert_reason text
    """,
]


def run():
    with engine.begin() as conn:
        before = conn.execute(text(
            "SELECT count(*) FROM installation_certification")).scalar()
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
        after = conn.execute(text(
            "SELECT count(*) FROM installation_certification")).scalar()
        initial = conn.execute(text(
            "SELECT count(*) FROM installation_certification WHERE reason = 'initial'")).scalar()
        uniq = conn.execute(text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'installation_certification_deployment_record_id_key'")).scalar()
    print("070 done: rows %s -> %s, reason='initial' on %s, unique constraint remaining %s"
          % (before, after, initial, uniq))


if __name__ == "__main__":
    run()
