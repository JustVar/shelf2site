"""Migration 078: the delete_requests table.

Board item 41 slice A; spec at docs/specs/delete-request-queue.md.
One new table, three named CHECK constraints, two user foreign keys that are
ON DELETE SET NULL, and a partial unique index allowing one pending request
per target.

Idempotent: every statement is IF NOT EXISTS or checks the catalog first, so
a rerun, or a run after the app created the bare table from the model,
converges on the same end state. Aborts if an existing table has columns the
spec does not name, or if a user foreign key is not SET NULL. Single
transaction.

Run:
    docker compose exec -T app python migrations/078_delete_requests.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

TABLE = "delete_requests"

COLUMNS = [
    "id", "target_table", "target_id", "target_label", "reason", "status",
    "requested_by", "requested_at", "decided_by", "decided_at",
]

CREATE = """
CREATE TABLE IF NOT EXISTS public.delete_requests (
    id            serial PRIMARY KEY,
    target_table  varchar(32)  NOT NULL,
    target_id     integer      NOT NULL,
    target_label  varchar(256) NOT NULL,
    reason        text         NOT NULL,
    status        varchar(16)  NOT NULL DEFAULT 'pending',
    requested_by  integer REFERENCES users(id) ON DELETE SET NULL,
    requested_at  timestamptz  DEFAULT now(),
    decided_by    integer REFERENCES users(id) ON DELETE SET NULL,
    decided_at    timestamptz
)
"""

CHECKS = {
    "ck_delete_requests_target": "target_table IN ('items', 'vendor_profiles')",
    "ck_delete_requests_status": "status IN ('pending', 'approved', 'rejected', 'withdrawn')",
    "ck_delete_requests_reason": "length(trim(reason)) > 0",
}

INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_delete_requests_one_pending "
    "ON public.delete_requests (target_table, target_id) WHERE status = 'pending'"
)


def exists(conn):
    return conn.execute(text("SELECT to_regclass('public." + TABLE + "')")).scalar() is not None


def columns(conn):
    return [r[0] for r in conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
    ), {"t": TABLE})]


def constraint_names(conn):
    return {r[0] for r in conn.execute(text(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'public." + TABLE + "'::regclass"
    ))}


def user_fk_actions(conn):
    rows = conn.execute(text(
        "SELECT a.attname, c.confdeltype FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.contype = 'f' AND c.conrelid = 'public." + TABLE + "'::regclass "
        "AND c.confrelid = 'public.users'::regclass"
    ))
    return {r[0]: r[1] for r in rows}


def has_index(conn):
    return conn.execute(text(
        "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
        "AND tablename = :t AND indexname = 'uq_delete_requests_one_pending'"
    ), {"t": TABLE}).scalar() == 1


def main() -> None:
    with engine.begin() as conn:
        present = exists(conn)
        print("table before: " + ("present" if present else "absent"))
        if present:
            cols = columns(conn)
            print("columns before: " + ", ".join(cols))
            if cols != COLUMNS:
                raise SystemExit("ABORT: existing columns differ from the spec; nothing changed")
            rows = conn.execute(text("SELECT count(*) FROM " + TABLE)).scalar()
            print("rows before: " + str(rows))
        else:
            conn.execute(text(CREATE))
            print("created " + TABLE)

        have = constraint_names(conn)
        for name, expr in CHECKS.items():
            if name in have:
                print("already present: " + name)
            else:
                conn.execute(text(
                    "ALTER TABLE public." + TABLE + " ADD CONSTRAINT " + name + " CHECK (" + expr + ")"
                ))
                print("added " + name)

        if has_index(conn):
            print("already present: uq_delete_requests_one_pending")
        else:
            conn.execute(text(INDEX))
            print("added uq_delete_requests_one_pending")

        if columns(conn) != COLUMNS:
            raise SystemExit("ABORT: columns after do not match the spec")
        if not set(CHECKS) <= constraint_names(conn):
            raise SystemExit("ABORT: a CHECK constraint is missing after the run")
        fks = user_fk_actions(conn)
        print("user foreign keys: " + ", ".join(k + "=" + v for k, v in sorted(fks.items())))
        if fks != {"requested_by": "n", "decided_by": "n"}:
            raise SystemExit("ABORT: user foreign keys must both be ON DELETE SET NULL")
        if not has_index(conn):
            raise SystemExit("ABORT: partial unique index missing after the run")
        rows = conn.execute(text("SELECT count(*) FROM " + TABLE)).scalar()
        print("rows after: " + str(rows))
    print("OK: migration 078 complete")


if __name__ == "__main__":
    main()
