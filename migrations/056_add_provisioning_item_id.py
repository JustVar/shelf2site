"""Migration 056: add device_provisioning.item_id (C2C option D link).

Adds a nullable FK from device_provisioning to item_schema.items(id) - the link
that lets a provisioning row point at a C2C camera entered as unified inventory
(item_schema.items) instead of a legacy public.* row. Chosen cert-subject grain
is option D (see docs/specs/c2c-catalog-and-accessories.md section 7): keep the
provisioning + cert chain, add this link column, migration 055 untouched.

Nullable + ON DELETE SET NULL: legacy provisioning rows keep item_id NULL and are
unaffected; deleting the items row clears the link without cascading away the
provisioning or cert history. Cross-schema FK is standard within one database
(public.device_provisioning -> item_schema.items, same asset_tracker DB).

Additive, idempotent (ADD COLUMN / INDEX IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/056_add_provisioning_item_id.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    ALTER TABLE device_provisioning
        ADD COLUMN IF NOT EXISTS item_id integer
        REFERENCES item_schema.items(id) ON DELETE SET NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_device_provisioning_item_id "
    "ON device_provisioning (item_id)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("056 done: device_provisioning.item_id FK -> item_schema.items + index (idempotent)")


if __name__ == "__main__":
    print("Running migration 056: device_provisioning.item_id...")
    run()
    print("Migration 056 complete.")
