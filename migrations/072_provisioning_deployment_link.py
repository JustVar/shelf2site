"""Migration 072: add device_provisioning.deployment_record_id.

Links a provisioned unit to the deployment visit that installed it. Until now
units and deployment records were siblings under customer_order_id and were
never joined, so "which serials did this visit install" was an inference through
the shared order. That inference resolves correctly only while each order has
exactly one deployment record, and deployment_records.customer_order_id has no
uniqueness constraint. See docs/specs/link-units-to-deployments.md.

Nullable + ON DELETE SET NULL: units are provisioned before visits are planned,
so NULL is a normal state and not an error, and deleting a visit must not delete
the units that were on it. This mirrors unit_photos.deployment_record_id and
differs deliberately from installation_certification, which cascades because a
certification without its visit is meaningless.

No backfill. The live deployment records are test data, so every row starts NULL.

Additive, idempotent (ADD COLUMN / INDEX IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/072_provisioning_deployment_link.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    ALTER TABLE device_provisioning
        ADD COLUMN IF NOT EXISTS deployment_record_id integer
        REFERENCES deployment_records(id) ON DELETE SET NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_device_provisioning_deployment_record_id "
    "ON device_provisioning (deployment_record_id)",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("072 done: device_provisioning.deployment_record_id FK -> deployment_records + index (idempotent)")


if __name__ == "__main__":
    print("Running migration 072: device_provisioning.deployment_record_id...")
    run()
    print("Migration 072 complete.")
