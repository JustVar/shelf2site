"""Migration 082: item-only warranties and assignments (legacy slice S4, warranty).

Schema only. See docs/specs/retire-legacy-inventory.md section 9 (S4).

- device_warranties and device_assignments: device_table and device_id stop
  being NOT NULL. New rows link through item_id (migration 080); the legacy
  pair has nothing to hold and drops in legacy slice S5.
- device_warranties gains notes (text, nullable). Warranty tracking is basic
  now (item, vendor, start, end, notes); coverage_details and the other
  unused columns drop in S5.

Both tables held 0 rows when this was written (READ 2026-09-28). The script
aborts if a row count moves.

Idempotent (DROP NOT NULL / ADD COLUMN IF NOT EXISTS). Run:
    docker compose exec -T app python migrations/082_warranty_basic_tracking.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

TABLES = ["device_warranties", "device_assignments"]
LEGACY_COLUMNS = ["device_table", "device_id"]

DDL = []
for t in TABLES:
    for c in LEGACY_COLUMNS:
        DDL.append("ALTER TABLE public." + t + " ALTER COLUMN " + c + " DROP NOT NULL")
DDL.append("ALTER TABLE public.device_warranties ADD COLUMN IF NOT EXISTS notes text")


def counts(conn):
    return {t: conn.execute(text("SELECT count(*) FROM public." + t)).scalar() for t in TABLES}


def columns(conn):
    return conn.execute(text(
        "SELECT table_name, column_name, is_nullable, data_type "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name IN ('device_warranties', 'device_assignments') "
        "AND (column_name IN ('device_table', 'device_id', 'item_id') "
        "OR (table_name = 'device_warranties' AND column_name = 'notes')) "
        "ORDER BY 1, 2"
    )).fetchall()


def main() -> None:
    with engine.begin() as conn:
        before = counts(conn)
    for t in TABLES:
        print(f"{t} rows before: {before[t]}")

    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))

    with engine.begin() as conn:
        after = counts(conn)
        cols = columns(conn)

    for t in TABLES:
        print(f"{t} rows after: {after[t]}")
    for row in cols:
        print(f"column {row[0]}.{row[1]}: nullable={row[2]} type={row[3]}")

    if after != before:
        raise SystemExit("ABORT: a row count moved")
    got = {(r[0], r[1]): (r[2], r[3]) for r in cols}
    for t in TABLES:
        for c in LEGACY_COLUMNS:
            if got.get((t, c), ("NO",))[0] != "YES":
                raise SystemExit(f"ABORT: {t}.{c} is still NOT NULL")
    if got.get(("device_warranties", "notes")) != ("YES", "text"):
        raise SystemExit("ABORT: device_warranties.notes missing or wrong type")
    print("OK: migration 082 complete")


if __name__ == "__main__":
    main()
