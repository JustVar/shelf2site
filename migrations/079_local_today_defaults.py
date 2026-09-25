"""Migration 079: the date column defaults move to the Central date.

Item 42 slice C; spec at docs/specs/local-time.md. The database runs in UTC,
so CURRENT_DATE and now() give tomorrow's date from 7 pm CDT (6 pm CST) on.
Each of the 16 date defaults below becomes
(now() AT TIME ZONE 'America/Chicago')::date. Defaults only: no row changes,
and the row counts before and after must match.

Idempotent: a default that already names America/Chicago is left alone, and a
run with all 16 converted prints "already applied". Aborts with nothing
changed if the date columns with a default are not exactly these 16, or if a
default is neither its old value nor a Central one. Single transaction.

Run:
    docker compose exec -T app python migrations/079_local_today_defaults.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

CENTRAL = "America/Chicago"
NEW_DEFAULT = "(now() AT TIME ZONE 'America/Chicago')::date"

# (schema, table, column) -> the default READ from the live catalog on 2026-09-25.
EXPECTED = {
    ("item_schema", "checkouts", "checkout_date"): "CURRENT_DATE",
    ("item_schema", "checkouts", "created_at"): "CURRENT_DATE",
    ("item_schema", "component_history", "action_date"): "CURRENT_DATE",
    ("item_schema", "component_history", "created_at"): "CURRENT_DATE",
    ("item_schema", "intake_photos", "created_at"): "CURRENT_DATE",
    ("item_schema", "items", "created_at"): "CURRENT_DATE",
    ("item_schema", "items", "last_updated"): "CURRENT_DATE",
    ("item_schema", "location_types", "created_at"): "CURRENT_DATE",
    ("item_schema", "locations", "created_at"): "CURRENT_DATE",
    ("item_schema", "locations", "last_updated"): "CURRENT_DATE",
    ("item_schema", "maintenance_log", "created_at"): "CURRENT_DATE",
    ("item_schema", "maintenance_log", "maintenance_date"): "CURRENT_DATE",
    ("item_schema", "part_numbers", "created_at"): "CURRENT_DATE",
    ("item_schema", "receipts", "created_at"): "CURRENT_DATE",
    ("public", "device_assignments", "assigned_date"): "now()",
    ("public", "maintenance_log", "maintenance_date"): "CURRENT_DATE",
}

# Every date column with a default. tests/test_localtime.py reads the same set.
DATE_DEFAULTS = (
    "SELECT table_schema, table_name, column_name, column_default "
    "FROM information_schema.columns "
    "WHERE data_type = 'date' AND column_default IS NOT NULL "
    "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY table_schema, table_name, column_name"
)

# 00:30 UTC on 2026-09-25 is 19:30 CDT on 2026-09-24.
SANITY = "SELECT ('2026-09-25 00:30+00'::timestamptz AT TIME ZONE 'America/Chicago')::date"


def name(key):
    return ".".join(key)


def date_defaults(conn):
    return {(r[0], r[1], r[2]): r[3] for r in conn.execute(text(DATE_DEFAULTS))}


def row_counts(conn):
    tables = sorted({(schema, table) for schema, table, _column in EXPECTED})
    return {s + "." + t: conn.execute(text("SELECT count(*) FROM " + s + "." + t)).scalar()
            for s, t in tables}


def main() -> None:
    with engine.begin() as conn:
        before = date_defaults(conn)
        for key in sorted(before):
            print("before: " + name(key) + " = " + before[key])
        if set(before) != set(EXPECTED):
            missing = sorted(name(k) for k in set(EXPECTED) - set(before))
            extra = sorted(name(k) for k in set(before) - set(EXPECTED))
            raise SystemExit("ABORT: the date columns with a default are not the 16 expected; "
                             "missing " + str(missing) + ", extra " + str(extra) + "; nothing changed")

        pending = []
        for key in sorted(EXPECTED):
            value = before[key]
            if CENTRAL in value:
                continue
            if value != EXPECTED[key]:
                raise SystemExit("ABORT: " + name(key) + " default is " + value + ", neither "
                                 + EXPECTED[key] + " nor Central; nothing changed")
            pending.append(key)

        counts_before = row_counts(conn)
        if not pending:
            print("already applied: all 16 defaults use " + CENTRAL)
        for schema, table, column in pending:
            conn.execute(text("ALTER TABLE " + schema + "." + table + " ALTER COLUMN " + column
                              + " SET DEFAULT " + NEW_DEFAULT))
            print("set default: " + name((schema, table, column)))
        counts_after = row_counts(conn)
        for table in sorted(counts_before):
            print("rows: " + table + " " + str(counts_before[table]) + " -> " + str(counts_after[table]))
        if counts_after != counts_before:
            raise SystemExit("ABORT: row counts changed; rolled back")

        after = date_defaults(conn)
        for key in sorted(after):
            print("after: " + name(key) + " = " + after[key])
        if set(after) != set(EXPECTED):
            raise SystemExit("ABORT: the date columns with a default changed during the run; rolled back")
        not_central = sorted(name(k) for k in EXPECTED if CENTRAL not in after[k])
        if not_central:
            raise SystemExit("ABORT: not on the Central date after the run: " + str(not_central))
        utc = sorted(name(k) for k, v in after.items() if v.strip() in ("CURRENT_DATE", "now()"))
        if utc:
            raise SystemExit("ABORT: a date default is still CURRENT_DATE or now(): " + str(utc))

        sanity = conn.execute(text(SANITY)).scalar()
        print("sanity: 2026-09-25 00:30 UTC is " + str(sanity) + " in Central (want 2026-09-24)")
        if str(sanity) != "2026-09-24":
            raise SystemExit("ABORT: the Central date sanity check failed; rolled back")
    print("OK: migration 079 complete")


if __name__ == "__main__":
    main()
