"""Migration 057: add device_provisioning.assignment_type.

Shared, product-agnostic column recording how a provisioned device is assigned:
sale | pilot | demo | internal (see DeviceProvisioning.ASSIGNMENT_TYPES). Only
the C2C 'sale' path is wired at this point; pilot/demo/internal are defined
values without a target flow (the pilot/loan model is a later design session).

Distinct from the two existing deployment_type columns (device classification on
the inventory models, and CustomerOrder.deployment_type = sales channel) - the
name is deliberately different to avoid that three-way collision.

Nullable so existing provisioning rows (edge boxes, and the C2C rows 243/244) are
unaffected. Additive, idempotent (ADD COLUMN IF NOT EXISTS), single transaction.

Run:
    docker compose exec app python migrations/057_add_provisioning_assignment_type.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    """
    ALTER TABLE device_provisioning
        ADD COLUMN IF NOT EXISTS assignment_type varchar(32)
    """,
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    print("057 done: device_provisioning.assignment_type column (idempotent)")


if __name__ == "__main__":
    print("Running migration 057: device_provisioning.assignment_type...")
    run()
    print("Migration 057 complete.")
