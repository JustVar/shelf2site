"""Migration: Add Zendesk ticket ID to device_provisioning.

Links edge box provisioning records to Zendesk deployment request tickets.
Enables fetching ticket context (subject, requester, organization) to pre-populate
customer information and track deployment requests from ticket to deployment.

New field:
- zendesk_ticket_id: Integer ticket ID from Zendesk (nullable)

Run this migration on the NUC with:
    cd /opt/hardware_inventory
    source venv/bin/activate
    python migrations/006_add_zendesk_ticket_id.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import engine


ADD_COLUMN = """
ALTER TABLE device_provisioning
ADD COLUMN IF NOT EXISTS zendesk_ticket_id INTEGER;
"""

CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_provisioning_zendesk_ticket
ON device_provisioning(zendesk_ticket_id);
"""


def run_migration():
    """Add Zendesk ticket ID field to device_provisioning table."""

    with engine.begin() as conn:
        conn.execute(text(ADD_COLUMN))
        print("  Added column: zendesk_ticket_id")

        conn.execute(text(CREATE_INDEX))
        print("  Created index: idx_provisioning_zendesk_ticket")

    print("\nMigration 006 complete: Zendesk ticket ID field added to device_provisioning.")


if __name__ == "__main__":
    print("Running migration 006: Add Zendesk ticket ID to device_provisioning...")
    run_migration()
