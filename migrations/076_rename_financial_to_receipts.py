"""Migration 076: rename can_view_financial to can_view_receipts.

users.can_view_financial and departments.can_view_financial become
can_view_receipts. Same ENUM types (user_permission_state,
department_permission_state), same defaults, every value carries over.
Board item 40; spec at docs/specs/receipts-permission-and-financial-drop.md.

Idempotent: each RENAME runs only when the old column exists and the new
one does not; a table already renamed is reported and skipped. Any other
column state aborts before the first statement. Single transaction.

Run:
    docker compose exec -T app python migrations/076_rename_financial_to_receipts.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

OLD = "can_view_financial"
NEW = "can_view_receipts"
TABLES = ["users", "departments"]


def has_column(conn, table, column):
    return conn.execute(text(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar() == 1


def state_counts(conn, table, column):
    rows = conn.execute(text(
        "SELECT " + column + "::text AS s, count(*) FROM " + table
        + " GROUP BY 1 ORDER BY 1"
    )).fetchall()
    return {s: n for s, n in rows}


def total(conn, table):
    return conn.execute(text("SELECT count(*) FROM " + table)).scalar()


def main() -> None:
    with engine.begin() as conn:
        plan = {}
        for t in TABLES:
            old, new = has_column(conn, t, OLD), has_column(conn, t, NEW)
            if old and not new:
                plan[t] = "rename"
            elif new and not old:
                plan[t] = "already"
            else:
                raise SystemExit("ABORT: " + t + " has old=" + str(old) + " new=" + str(new))
            print("plan " + t + ": " + plan[t])

        before = {}
        for t in TABLES:
            col = OLD if plan[t] == "rename" else NEW
            before[t] = (total(conn, t), state_counts(conn, t, col))
            print("before " + t + ": rows=" + str(before[t][0]) + " states=" + str(before[t][1]))

        for t in TABLES:
            if plan[t] == "rename":
                conn.execute(text("ALTER TABLE " + t + " RENAME COLUMN " + OLD + " TO " + NEW))
                print("renamed " + t + "." + OLD + " to " + NEW)

        for t in TABLES:
            if has_column(conn, t, OLD) or not has_column(conn, t, NEW):
                raise SystemExit("ABORT: " + t + " column state wrong after rename")
            after = (total(conn, t), state_counts(conn, t, NEW))
            print("after  " + t + ": rows=" + str(after[0]) + " states=" + str(after[1]))
            if after != before[t]:
                raise SystemExit("ABORT: " + t + " counts moved")

        for t in TABLES:
            typ = conn.execute(text(
                "SELECT udt_name, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
            ), {"t": t, "c": NEW}).fetchone()
            print("column " + t + "." + NEW + ": type=" + str(typ[0]) + " default=" + str(typ[1]))
    print("OK: migration 076 complete")


if __name__ == "__main__":
    main()
