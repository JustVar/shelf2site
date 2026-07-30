"""071 - Restore one installation certification per deployment record.

Undoes migration 070. Re-adds the unique constraint on deployment_record_id and
drops the reason and recert_reason columns, restoring the schema ratified in
docs/specs/installation-certification.md ("one cert per deployment record ...
no in row history or reason field"). Migration 070 stays in history because it
ran; this undoes its effect.

Refuses to run if any deployment record carries more than one certification,
since the unique constraint could not be created in that state. Idempotent:
the constraint is added only when absent, the columns dropped only if present.

Run:
    docker compose exec app python migrations/071_restore_single_installation_cert.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

UNIQ = "installation_certification_deployment_record_id_key"


def run():
    with engine.begin() as conn:
        dupes = conn.execute(text(
            "SELECT count(*) FROM ("
            "  SELECT deployment_record_id FROM installation_certification"
            "  GROUP BY deployment_record_id HAVING count(*) > 1"
            ") d")).scalar()
        if dupes:
            raise SystemExit(
                "ABORT: %s deployment record(s) carry more than one certification. "
                "The unique constraint cannot be restored. No change made." % dupes)

        before = conn.execute(text(
            "SELECT count(*) FROM installation_certification")).scalar()

        present = conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = :n"),
            {"n": UNIQ}).scalar()
        if not present:
            conn.execute(text(
                "ALTER TABLE installation_certification "
                "ADD CONSTRAINT " + UNIQ + " UNIQUE (deployment_record_id)"))

        conn.execute(text(
            "ALTER TABLE installation_certification DROP COLUMN IF EXISTS reason"))
        conn.execute(text(
            "ALTER TABLE installation_certification DROP COLUMN IF EXISTS recert_reason"))

        after = conn.execute(text(
            "SELECT count(*) FROM installation_certification")).scalar()
        uniq = conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = :n"),
            {"n": UNIQ}).scalar()
        cols = conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name IN (:a, :b)"),
            {"t": "installation_certification", "a": "reason", "b": "recert_reason"}).scalar()

    print("071 done: rows %s -> %s, unique constraint %s, 070 columns remaining %s"
          % (before, after, uniq, cols))


if __name__ == "__main__":
    run()
