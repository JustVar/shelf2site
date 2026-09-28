"""Migration 080: item links and four new item categories (item 30 S1).

Schema only, additive. See docs/specs/retire-legacy-inventory.md sections 6,
6a and 9 (slice S1).

- public.item_categories gains 'phone', 'webcam', 'printer' and 'nas'.
- device_credentials, device_warranties and device_assignments gain a
  nullable item_id FK to item_schema.items(id), ON DELETE SET NULL (the
  migration 056 pattern), each with an index. The legacy device_table and
  device_id columns stay until item 30 S5.
- pending_devices gains suggested_category (public.item_categories,
  nullable). suggested_table stays until item 30 S5.

No row is written. The new columns stay NULL until item 30 S2.

Postgres note: ALTER TYPE ... ADD VALUE gets its own transaction block, and
nothing here uses the new values (SQLSTATE 55P04), as in migration 065.

Idempotent (ADD VALUE / ADD COLUMN / INDEX IF NOT EXISTS). Run:
    docker compose exec -T app python migrations/080_item_links_and_categories.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

NEW_CATEGORIES = ["phone", "webcam", "printer", "nas"]
LINK_TABLES = ["device_credentials", "device_warranties", "device_assignments"]
COUNT_TABLES = LINK_TABLES + ["pending_devices", "item_schema.items"]

ENUM_STATEMENTS = [
    "ALTER TYPE public.item_categories ADD VALUE IF NOT EXISTS '" + c + "'"
    for c in NEW_CATEGORIES
]

DDL = []
for t in LINK_TABLES:
    DDL.append(
        "ALTER TABLE public." + t + " ADD COLUMN IF NOT EXISTS item_id integer"
        " REFERENCES item_schema.items(id) ON DELETE SET NULL"
    )
    DDL.append(
        "CREATE INDEX IF NOT EXISTS idx_" + t + "_item_id ON public." + t + " (item_id)"
    )
DDL.append(
    "ALTER TABLE public.pending_devices ADD COLUMN IF NOT EXISTS"
    " suggested_category public.item_categories"
)


def counts(conn):
    return {t: conn.execute(text("SELECT count(*) FROM " + t)).scalar() for t in COUNT_TABLES}


def enum_labels(conn):
    return [r[0] for r in conn.execute(text(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = 'public' AND t.typname = 'item_categories' "
        "ORDER BY e.enumsortorder"
    )).fetchall()]


def main() -> None:
    with engine.begin() as conn:
        before = counts(conn)
        labels_before = enum_labels(conn)
    for t in COUNT_TABLES:
        print(f"{t} rows before: {before[t]}")
    print(f"item_categories values before: {len(labels_before)}")

    with engine.begin() as conn:
        for stmt in ENUM_STATEMENTS:
            conn.execute(text(stmt))

    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))

    with engine.begin() as conn:
        after = counts(conn)
        labels = enum_labels(conn)
        fks = conn.execute(text(
            "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "WHERE c.contype = 'f' AND c.confrelid = 'item_schema.items'::regclass "
            "AND c.conrelid::regclass::text IN "
            "('device_credentials', 'device_warranties', 'device_assignments') "
            "ORDER BY 1"
        )).fetchall()
        idx = conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname IN ('idx_device_credentials_item_id', "
            "'idx_device_warranties_item_id', 'idx_device_assignments_item_id') "
            "ORDER BY 1"
        )).fetchall()
        sc = conn.execute(text(
            "SELECT data_type, udt_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'pending_devices' "
            "AND column_name = 'suggested_category'"
        )).fetchall()
        filled = {
            t: conn.execute(text("SELECT count(*) FROM public." + t + " WHERE item_id IS NOT NULL")).scalar()
            for t in LINK_TABLES
        }
        filled_sc = conn.execute(text(
            "SELECT count(*) FROM public.pending_devices WHERE suggested_category IS NOT NULL"
        )).scalar()

    for t in COUNT_TABLES:
        print(f"{t} rows after: {after[t]}")
    print(f"item_categories values after: {len(labels)}")
    print(f"item_categories tail: {labels[-4:]}")
    for tbl, name, definition in fks:
        print(f"fk {tbl}.{name}: {definition}")
    print(f"indexes: {[r[0] for r in idx]}")
    print(f"pending_devices.suggested_category: {sc}")
    print(f"item_id filled: {filled}; suggested_category filled: {filled_sc}")

    if after != before:
        raise SystemExit("ABORT: a row count moved")
    if any(c not in labels for c in NEW_CATEGORIES):
        raise SystemExit("ABORT: a new category value is missing")
    if len(labels) != len(set(labels_before) | set(NEW_CATEGORIES)):
        raise SystemExit("ABORT: unexpected item_categories value count")
    if len(fks) != 3 or any("ON DELETE SET NULL" not in r[2] for r in fks):
        raise SystemExit("ABORT: expected three item_id FKs with ON DELETE SET NULL")
    if len(idx) != 3:
        raise SystemExit("ABORT: expected three item_id indexes")
    if sc != [("USER-DEFINED", "item_categories", "YES")]:
        raise SystemExit("ABORT: pending_devices.suggested_category missing or wrong type")
    if any(filled.values()) or filled_sc:
        raise SystemExit("ABORT: a new column holds data")
    print("OK: migration 080 complete")


if __name__ == "__main__":
    main()
