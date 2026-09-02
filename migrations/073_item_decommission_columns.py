"""Migration 073: item decommission columns.

Adds the three decommission fields to item_schema.items per
docs/specs/item-decommission.md: the reason, the effective date, and who
acted. Set by the decommission action, cleared by reactivation; the row
survives either way (decommission is not deletion).

Additive, idempotent (ADD COLUMN IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/073_item_decommission_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE item_schema.items ADD COLUMN IF NOT EXISTS decommission_reason text",
    "ALTER TABLE item_schema.items ADD COLUMN IF NOT EXISTS decommission_date date",
    "ALTER TABLE item_schema.items ADD COLUMN IF NOT EXISTS decommissioned_by varchar(128)",
]


def main() -> None:
    with engine.begin() as conn:
        before = conn.execute(text("SELECT count(*) FROM item_schema.items")).scalar()
        print(f"item_schema.items rows before: {before}")
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
        cols = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'item_schema' AND table_name = 'items' "
            "AND column_name IN ('decommission_reason', 'decommission_date', 'decommissioned_by')"
        )).fetchall()
        print(f"decommission columns present: {sorted(c[0] for c in cols)}")
        after = conn.execute(text("SELECT count(*) FROM item_schema.items")).scalar()
        print(f"item_schema.items rows after: {after}")
        if len(cols) != 3:
            raise SystemExit("ABORT: expected all 3 decommission columns present")
    print("OK: migration 073 complete")


if __name__ == "__main__":
    main()
