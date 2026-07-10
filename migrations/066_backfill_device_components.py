"""Backfill public.device_components (31 legacy linkage rows, 2026-03-05
import) into item_schema.component_history as 'installed' events.

RE-RUNNABLE BY DESIGN: each legacy row resolves both sides (parent + component)
to item_schema.items via a trimmed, case-insensitive serial join. Rows that do
not resolve are reported loudly and left OUT of the mapping table so a later
re-run — after the referenced devices are imported into items — picks them up.
As of 2026-07-10, 0/31 rows resolve (none of the referenced serials exist in
items yet); the migration still gates on accounting integrity:
resolved + unresolved + already-done == total device_components rows.

Provenance: every created event carries a greppable
'[backfill:device_components:<id>]' notes prefix, and component_migration_map
records old row id -> new event id(s). installed_date on the legacy rows is
the IMPORT-RUN date (2026-03-05), not the physical install date — stated in
each event's notes so the log stays honest.

device_components itself is NOT dropped (kept read-only for rollback +
provenance, per the legacy-retirement plan — same pattern as migration 063).

Run:
    docker compose exec app python migrations/066_backfill_device_components.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

# Serial column per legacy table (gpus is the odd one out).
SERIAL_COL = {"gpus": "gpu_serial"}

MAP_TABLE = """
CREATE TABLE IF NOT EXISTS component_migration_map (
    old_dc_id integer PRIMARY KEY,
    installed_event_id integer NOT NULL,
    uninstalled_event_id integer,
    created_at timestamp DEFAULT now()
)
"""


def _resolve_item_id(conn, legacy_table: str, legacy_id: int):
    """legacy row -> its serial -> items.id (trimmed, case-insensitive).

    Returns (item_id or None, reason). Ambiguous serial matches are treated
    as unresolved — never guess.
    """
    col = SERIAL_COL.get(legacy_table, "serial")
    serial = conn.execute(
        text(f"SELECT {col} FROM public.{legacy_table} WHERE id = :i"),
        {"i": legacy_id},
    ).scalar()
    if not serial or not str(serial).strip():
        return None, f"{legacy_table}#{legacy_id} has no serial"
    matches = conn.execute(
        text("SELECT id FROM item_schema.items WHERE lower(trim(item_sn)) = lower(trim(:s))"),
        {"s": str(serial)},
    ).fetchall()
    if len(matches) == 1:
        return matches[0][0], None
    if len(matches) > 1:
        return None, f"serial '{serial}' matches {len(matches)} items (ambiguous)"
    return None, f"serial '{serial}' not found in items"


def run():
    with engine.begin() as conn:
        conn.execute(text(MAP_TABLE))

        total = conn.execute(text("SELECT count(*) FROM device_components")).scalar()
        rows = conn.execute(text(
            "SELECT id, parent_table, parent_id, component_table, component_id, "
            "slot_label, installed_date, removed_date, installed_by, notes, created_at "
            "FROM device_components ORDER BY id"
        )).fetchall()

        done = conn.execute(text("SELECT old_dc_id FROM component_migration_map")).fetchall()
        done_ids = {r[0] for r in done}

        migrated = skipped_done = unresolved = 0
        for r in rows:
            (dc_id, p_table, p_id, c_table, c_id,
             slot, installed_date, removed_date, installed_by, notes, created_at) = r

            if dc_id in done_ids:
                skipped_done += 1
                continue
            # Belt-and-braces: a provenance-marked event without a map row
            # (e.g. map table dropped by hand) still counts as done.
            marked = conn.execute(text(
                "SELECT 1 FROM item_schema.component_history WHERE notes LIKE :p LIMIT 1"),
                {"p": f"[backfill:device_components:{dc_id}]%"},
            ).scalar()
            if marked:
                skipped_done += 1
                continue

            parent_item, p_err = _resolve_item_id(conn, p_table, p_id)
            comp_item, c_err = _resolve_item_id(conn, c_table, c_id)
            if not parent_item or not comp_item:
                unresolved += 1
                print(f"  UNRESOLVED dc#{dc_id}: parent {p_table}#{p_id} "
                      f"({p_err or 'ok'}); component {c_table}#{c_id} ({c_err or 'ok'})")
                continue

            provenance = (
                f"[backfill:device_components:{dc_id}] {p_table}#{p_id} -> "
                f"{c_table}#{c_id}; installed_date is the 2026-03-05 import-run "
                f"date, not the physical install date"
                + (f"; orig: {notes}" if notes else "")
            )
            action_date = installed_date or (created_at.date() if created_at else None)
            installed_event_id = conn.execute(text(
                "INSERT INTO item_schema.component_history "
                "(item_id, parent_item_id, action, slot_label, action_date, performed_by, notes) "
                "VALUES (:item, :parent, 'installed', :slot, COALESCE(:d, CURRENT_DATE), :by, :n) "
                "RETURNING id"),
                {"item": comp_item, "parent": parent_item, "slot": slot,
                 "d": action_date, "by": installed_by or "backfill", "n": provenance},
            ).scalar()

            uninstalled_event_id = None
            if removed_date:
                uninstalled_event_id = conn.execute(text(
                    "INSERT INTO item_schema.component_history "
                    "(item_id, parent_item_id, action, slot_label, action_date, performed_by, notes) "
                    "VALUES (:item, :parent, 'uninstalled', :slot, :d, :by, :n) "
                    "RETURNING id"),
                    {"item": comp_item, "parent": parent_item, "slot": slot,
                     "d": removed_date, "by": installed_by or "backfill",
                     "n": provenance + " [uninstall leg]"},
                ).scalar()

            conn.execute(text(
                "INSERT INTO component_migration_map "
                "(old_dc_id, installed_event_id, uninstalled_event_id) "
                "VALUES (:o, :i, :u)"),
                {"o": dc_id, "i": installed_event_id, "u": uninstalled_event_id},
            )
            migrated += 1

        # Accounting gate — every legacy row must land in exactly one bucket.
        accounted = migrated + skipped_done + unresolved
        print(f"066 summary: total={total} migrated={migrated} "
              f"already-done={skipped_done} unresolved={unresolved}")
        assert accounted == total, (
            f"ACCOUNTING MISMATCH: {accounted} accounted vs {total} rows — rolling back"
        )
        if unresolved:
            print(f"066 note: {unresolved} rows left for a future re-run "
                  "(their devices are not in item_schema.items yet)")


if __name__ == "__main__":
    print("Running migration 066...")
    run()
    print("Migration complete.")
