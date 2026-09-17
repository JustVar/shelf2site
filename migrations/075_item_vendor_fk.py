"""Migration 075: item and receipt vendor foreign keys.

Item.vendor_id and ItemReceipt.vendor_id become real foreign keys to
public.vendor_profiles(id) with ON DELETE SET NULL, so a deleted profile
clears the link rather than leaving a dangling id. Board item N11.

Orphan values are nulled first: no profile carries the ids two items hold,
and a FOREIGN KEY cannot be added while they remain. The free-text
item_vendor column is untouched and keeps the vendor name.

Idempotent (each constraint is dropped before it is added), single
transaction.

Run:
    docker compose exec -T app python migrations/075_item_vendor_fk.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

ITEMS = "item_schema.items"
RECEIPTS = "item_schema.receipts"
ORPHAN_PRED = ("WHERE vendor_id IS NOT NULL AND vendor_id NOT IN (SELECT id FROM public.vendor_profiles)")

NULL_ORPHANS = [
    "UPDATE " + ITEMS + " SET vendor_id = NULL " + ORPHAN_PRED,
    "UPDATE " + RECEIPTS + " SET vendor_id = NULL " + ORPHAN_PRED,
]

DDL = [
    "ALTER TABLE " + ITEMS + " DROP CONSTRAINT IF EXISTS items_vendor_id_fkey",
    "ALTER TABLE " + ITEMS + " ADD CONSTRAINT items_vendor_id_fkey"
    " FOREIGN KEY (vendor_id) REFERENCES public.vendor_profiles(id)"
    " ON DELETE SET NULL",
    "ALTER TABLE " + RECEIPTS + " DROP CONSTRAINT IF EXISTS receipts_vendor_id_fkey",
    "ALTER TABLE " + RECEIPTS + " ADD CONSTRAINT receipts_vendor_id_fkey"
    " FOREIGN KEY (vendor_id) REFERENCES public.vendor_profiles(id)"
    " ON DELETE SET NULL",
]

WANT_CONSTRAINTS = ["items_vendor_id_fkey", "receipts_vendor_id_fkey"]


def count(conn, table, extra=""):
    return conn.execute(text("SELECT count(*) FROM " + table + extra)).scalar()


def main() -> None:
    with engine.begin() as conn:
        items_before = count(conn, ITEMS)
        receipts_before = count(conn, RECEIPTS)
        orphan_items_before = count(conn, ITEMS, " " + ORPHAN_PRED)
        orphan_receipts_before = count(conn, RECEIPTS, " " + ORPHAN_PRED)
        print(f"items rows before: {items_before}")
        print(f"receipts rows before: {receipts_before}")
        print(f"orphan item vendor_id before: {orphan_items_before}")
        print(f"orphan receipt vendor_id before: {orphan_receipts_before}")

        for stmt in NULL_ORPHANS:
            result = conn.execute(text(stmt))
            print(f"nulled {result.rowcount} row(s): {stmt[:46]}")
        for stmt in DDL:
            conn.execute(text(stmt))

        items_after = count(conn, ITEMS)
        receipts_after = count(conn, RECEIPTS)
        orphan_items_after = count(conn, ITEMS, " " + ORPHAN_PRED)
        orphan_receipts_after = count(conn, RECEIPTS, " " + ORPHAN_PRED)
        print(f"items rows after: {items_after}")
        print(f"receipts rows after: {receipts_after}")
        print(f"orphan item vendor_id after: {orphan_items_after}")
        print(f"orphan receipt vendor_id after: {orphan_receipts_after}")

        rows = conn.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname IN ('items_vendor_id_fkey', 'receipts_vendor_id_fkey')"
        )).fetchall()
        for name, definition in sorted(rows):
            print(f"constraint {name}: {definition}")
        found = sorted(r[0] for r in rows)

        if items_after != items_before:
            raise SystemExit("ABORT: items row count moved")
        if receipts_after != receipts_before:
            raise SystemExit("ABORT: receipts row count moved")
        if orphan_items_after or orphan_receipts_after:
            raise SystemExit("ABORT: orphan vendor_id values remain")
        if found != WANT_CONSTRAINTS:
            raise SystemExit("ABORT: expected both vendor foreign keys present")
    print("OK: migration 075 complete")


if __name__ == "__main__":
    main()
