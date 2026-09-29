"""Migration 083: drop the legacy inventory tables and link columns (item 30 S5b).

DESTRUCTIVE. See docs/specs/retire-legacy-inventory.md section 9 (S5).
Take a backup first. Dry run by default; --apply commits.

Drops, in one transaction:
- the 22 legacy per-category tables (edge_boxes ... hard_drives);
- device_components (moved to component history by 066 and 081) and the
  empty public.maintenance_log that points at it;
- nas_drives, vendor_trials, device_dispositions, device_assignments,
  warranty_claims, intune_sync_log and the empty public.receipts;
- device_table and device_id on device_provisioning, device_credentials
  and device_warranties (every row links through item_id);
- the unused device_warranties columns (basic tracking keeps item, vendor,
  start, end, notes and the timestamps);
- pending_devices.suggested_table (suggested_category replaces it).

Kept: public.intake_photos (the receive photo routes still write it),
legacy_item_map and component_migration_map (migration history), the
hardware_inventory reference database on the old host.

Guards, checked before any DROP: every provisioning and credential row has
an item_id, every pending row with a suggested_table has a
suggested_category, device_warranties, device_assignments and
warranty_claims are empty. The dry run prints the row count of every
table it would drop.

Run on the host, inside the app container:
    docker compose exec -T app python migrations/083_drop_legacy_inventory.py
    docker compose exec -T app python migrations/083_drop_legacy_inventory.py --apply
Then restart the app. The code from the same commit no longer maps these
tables or columns.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

LEGACY_TABLES = [
    "edge_boxes", "gpus", "monitors", "computers", "phones", "mobile_devices",
    "cameras", "network_equipment", "access_control", "webcams", "printers",
    "office_equipment", "nucs", "ups", "ram_modules", "cpus", "psus",
    "motherboards", "pc_cooling", "pc_accessories", "hard_drives",
]
# Order matters: a table goes before the table its foreign key points at.
OTHER_TABLES = [
    "maintenance_log",      # FK to device_components
    "device_components",
    "nas_drives",           # FK to nas_devices
    "nas_devices",          # the 22nd legacy table
    "warranty_claims",      # FK to device_warranties (kept)
    "vendor_trials",
    "device_dispositions",
    "device_assignments",
    "intune_sync_log",
    "receipts",
]
DROP_TABLES = LEGACY_TABLES + OTHER_TABLES

DROP_COLUMNS = {
    "device_provisioning": ["device_table", "device_id"],
    "device_credentials": ["device_table", "device_id"],
    "device_warranties": [
        "device_table", "device_id", "warranty_scope", "warranty_tier",
        "purchase_date", "warranty_type", "warranty_holder",
        "registration_number", "coverage_details", "auto_renew",
        "renewal_cost", "registration_status", "loaner_from_team",
        "loaner_to_team", "loaner_contact", "loaner_agreement",
        "data_completeness", "discovered_by", "network_segment", "last_seen",
        "purchase_price", "purchase_order", "supplier_invoice",
        "procurement_method",
    ],
    "pending_devices": ["suggested_table"],
}

GUARDS = [
    ("provisioning rows without item_id",
     "SELECT count(*) FROM public.device_provisioning WHERE item_id IS NULL", 0),
    ("credential rows without item_id",
     "SELECT count(*) FROM public.device_credentials WHERE item_id IS NULL", 0),
    ("pending rows with a table but no category",
     "SELECT count(*) FROM public.pending_devices "
     "WHERE suggested_table IS NOT NULL AND suggested_category IS NULL", 0),
    ("device_warranties rows", "SELECT count(*) FROM public.device_warranties", 0),
    ("device_assignments rows", "SELECT count(*) FROM public.device_assignments", 0),
    ("warranty_claims rows", "SELECT count(*) FROM public.warranty_claims", 0),
]


def existing_tables(conn):
    return {r[0] for r in conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"))}


def existing_columns(conn, table):
    return {r[0] for r in conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t"), {"t": table})}


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            tables = existing_tables(conn)
            if not any(t in tables for t in DROP_TABLES):
                print("ALREADY APPLIED: none of the legacy tables exist")
                trans.rollback()
                return
            missing = [t for t in DROP_TABLES if t not in tables]
            if missing:
                raise SystemExit("ABORT: partial state, missing tables: " + ", ".join(missing))

            for label, sql, want in GUARDS:
                got = conn.execute(text(sql)).scalar()
                print(f"guard {label}: {got} (want {want})")
                if got != want:
                    raise SystemExit("ABORT: guard failed: " + label)

            total = 0
            for t in DROP_TABLES:
                n = conn.execute(text("SELECT count(*) FROM public." + t)).scalar()
                total += n
                print(f"drop table {t}: {n} rows")
            print(f"rows in dropped tables: {total}")

            for t, cols in DROP_COLUMNS.items():
                have = existing_columns(conn, t)
                gone = [c for c in cols if c not in have]
                if gone:
                    raise SystemExit(f"ABORT: {t} is missing columns: {', '.join(gone)}")
                print(f"drop columns {t}: {', '.join(cols)}")

            for t in DROP_TABLES:
                conn.execute(text("DROP TABLE public." + t))
            for t, cols in DROP_COLUMNS.items():
                conn.execute(text(
                    "ALTER TABLE public." + t + " "
                    + ", ".join("DROP COLUMN " + c for c in cols)))

            left = [t for t in DROP_TABLES if t in existing_tables(conn)]
            if left:
                raise SystemExit("ABORT: still present: " + ", ".join(left))
            for t, cols in DROP_COLUMNS.items():
                still = set(cols) & existing_columns(conn, t)
                if still:
                    raise SystemExit(f"ABORT: {t} still has {', '.join(sorted(still))}")

            if apply:
                trans.commit()
                print("OK: migration 083 applied")
            else:
                trans.rollback()
                print("DRY RUN OK: rolled back; rerun with --apply to commit")
        except BaseException:
            if trans.is_active:
                trans.rollback()
            raise


if __name__ == "__main__":
    main()
