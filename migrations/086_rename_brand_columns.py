"""Migration 086: rename the columns and values named after the old company.

The app was renamed Shelf2Site, and the code in the same commit only knows
the new names, so an existing database must be migrated before the app
restarts. Renames, in place, no data copied:

    item_schema.items.brand_sku                 -> item_sku
    item_schema.items.brand_pn                  -> item_pn
    item_schema.items.item_associated_brand_pn  -> item_associated_pn
    item_schema.items.appliance_uuid                 -> platform_uuid
    item_schema.part_numbers.brand_sku          -> item_sku
    build_certification.appliance_version            -> software_version
    customer_orders.owner value 'brand'         -> 'in_house' (and its default)

plus every index and constraint whose name carries brand_sku. A fresh
install already has the new names (the schema is built from app/models.py).

Dry run by default: prints each change it would make. --apply makes them all
in one transaction. Rerunning after apply prints ALREADY APPLIED.

Run inside the app container:
    docker compose exec -T app python migrations/086_rename_brand_columns.py
    docker compose exec -T app python migrations/086_rename_brand_columns.py --apply
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

COLUMNS = [
    ("item_schema", "items", "brand_sku", "item_sku"),
    ("item_schema", "items", "brand_pn", "item_pn"),
    ("item_schema", "items", "item_associated_brand_pn", "item_associated_pn"),
    ("item_schema", "items", "appliance_uuid", "platform_uuid"),
    ("item_schema", "part_numbers", "brand_sku", "item_sku"),
    ("public", "build_certification", "appliance_version", "software_version"),
]


def plan(conn):
    steps = []
    for schema, table, old, new in COLUMNS:
        found = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t AND column_name = :c"),
            {"s": schema, "t": table, "c": old}).first()
        if found:
            steps.append(("ALTER TABLE " + schema + "." + table + " RENAME COLUMN "
                          + old + " TO " + new))
    # Constraints first: renaming a unique or primary key constraint renames
    # its index too, so the index pass below skips those.
    cons = conn.execute(text(
        "SELECT n.nspname, c.relname, k.conname FROM pg_constraint k "
        "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE k.conname LIKE '%brand%' ORDER BY 1, 2, 3")).all()
    con_names = set()
    for schema, table, name in cons:
        con_names.add(name)
        steps.append("ALTER TABLE " + schema + "." + table + " RENAME CONSTRAINT "
                     + name + " TO " + name.replace("brand", "item"))
    idx = conn.execute(text(
        "SELECT schemaname, indexname FROM pg_indexes "
        "WHERE indexname LIKE '%brand%' ORDER BY 1, 2")).all()
    for schema, name in idx:
        if name in con_names:
            continue
        new = name.replace("brand_sku", "item_sku").replace("brand", "item")
        steps.append("ALTER INDEX " + schema + "." + name + " RENAME TO " + new)
    default = conn.execute(text(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'customer_orders' AND column_name = 'owner'")).scalar()
    if default and "brand" in default:
        steps.append("ALTER TABLE public.customer_orders ALTER COLUMN owner SET DEFAULT 'in_house'")
    owned = conn.execute(text(
        "SELECT count(*) FROM public.customer_orders WHERE owner = 'brand'")).scalar()
    if owned:
        steps.append("UPDATE public.customer_orders SET owner = 'in_house' WHERE owner = 'brand'")
    return steps


def main(apply: bool) -> None:
    with engine.begin() as conn:
        steps = plan(conn)
        if not steps:
            print("ALREADY APPLIED: no old names or values remain")
            return
        for s in steps:
            print(("apply: " if apply else "would run: ") + s)
        if not apply:
            print("dry run: " + str(len(steps)) + " step(s); rerun with --apply")
            return
        for s in steps:
            conn.execute(text(s))
        left = plan(conn)
        if left:
            raise SystemExit("ABORT: " + str(len(left)) + " step(s) still pending; rolled back")
        print("applied " + str(len(steps)) + " step(s)")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
