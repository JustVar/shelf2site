"""Add 'Installed' to item_statuses and create the current_containment view
(component containment slice, Option A).

- 'Installed' is a containment-managed status: set by the install route,
  cleared by uninstall. It is deliberately absent from the hand-edit status
  lists (same treatment as 'Checked Out').
- item_schema.current_containment is THE read path for containment state:
  the latest component_history event per component, kept only when that
  event is installed/moved. action_date is DATE, so same-day event pairs
  tie-break on id — the view MUST order by (action_date, id).
- One-hop parent resolution is correct BY INVARIANT: the write routes
  forbid installing a unit-category item as a component, so a parent can
  never itself be contained (no chains).

Postgres note: ALTER TYPE ... ADD VALUE runs inside a transaction on PG16,
but the new value must not be USED in the same transaction (SQLSTATE 55P04).
Nothing here uses it, but the ADD VALUE still gets its own transaction block
as the safe convention.

Idempotent. Run:
    docker compose exec app python migrations/065_installed_status_and_containment_view.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

ENUM_STMT = "ALTER TYPE public.item_statuses ADD VALUE IF NOT EXISTS 'Installed'"

VIEW_STMT = """
CREATE OR REPLACE VIEW item_schema.current_containment AS
SELECT component_item_id, parent_item_id, slot_label, installed_date, event_id
FROM (
    SELECT DISTINCT ON (ch.item_id)
        ch.item_id      AS component_item_id,
        ch.parent_item_id,
        ch.slot_label,
        ch.action_date  AS installed_date,
        ch.action,
        ch.id           AS event_id
    FROM item_schema.component_history ch
    ORDER BY ch.item_id, ch.action_date DESC, ch.id DESC
) latest
WHERE latest.action IN ('installed', 'moved')
  AND latest.parent_item_id IS NOT NULL
"""


def run():
    with engine.begin() as conn:
        conn.execute(text(ENUM_STMT))
    with engine.begin() as conn:
        conn.execute(text(VIEW_STMT))
    print("065 done: item_statuses += 'Installed'; item_schema.current_containment view created")


if __name__ == "__main__":
    print("Running migration 065...")
    run()
    print("Migration complete.")
