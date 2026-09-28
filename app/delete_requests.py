"""Delete request queue: the rules shared by the routes and the pages.

Spec: docs/specs/delete-request-queue.md. Editors and above file a request
to delete an item or a vendor profile; admins approve or reject it. An item
is deleted only when clean (no rows in any table in ITEM_LINKS). Its CSV
import map row is kept and marked so a rerun of migration 067 skips it.
"""

from sqlalchemy import text

from .config import settings
from .models import DeleteRequest, Item, VendorProfile

BP = settings.ROOT_PATH.rstrip("/")

TARGETS = ("items", "vendor_profiles")

# Every reference to item_schema.items.id in the live catalog (2026-09-23,
# plus the three links migration 080 added).
# (table, column, what the user is told)
ITEM_LINKS = (
    ("item_schema.checkouts", "item_id", "checkouts"),
    ("item_schema.component_history", "item_id", "component history"),
    ("item_schema.component_history", "parent_item_id", "component history"),
    ("item_schema.receipt_items", "item_id", "receipts"),
    ("item_schema.maintenance_log", "item_id", "maintenance log"),
    ("item_schema.intake_photos", "item_id", "intake photos"),
    ("public.device_provisioning", "item_id", "order units"),
    ("public.received_devices", "item_id", "receiving records"),
    ("public.unit_photo_items", "item_id", "unit photos"),
    ("public.device_credentials", "item_id", "credentials"),
    ("public.device_warranties", "item_id", "warranties"),
    ("public.device_assignments", "item_id", "site assignments"),
)

IMPORT_MAP_ACTION = "deleted_by_request"


def item_blockers(db, item_id):
    """The kinds of history that stop an item from being deleted, in order."""
    found = []
    for table, column, label in ITEM_LINKS:
        hit = db.execute(
            text("SELECT 1 FROM " + table + " WHERE " + column + " = :i LIMIT 1"),
            {"i": item_id},
        ).first()
        if hit and label not in found:
            found.append(label)
    return found


def pending_for(db, target_table, target_id):
    """The pending request for a target, or None."""
    return (
        db.query(DeleteRequest)
        .filter(
            DeleteRequest.target_table == target_table,
            DeleteRequest.target_id == target_id,
            DeleteRequest.status == "pending",
        )
        .first()
    )


def load_target(db, target_table, target_id, lock=False):
    model = Item if target_table == "items" else VendorProfile
    q = db.query(model).filter(model.id == target_id)
    if lock:
        q = q.with_for_update()
    return q.first()


def target_label(target_table, obj):
    if target_table == "items":
        name = obj.item_name or "Unnamed item"
        label = name + (" (SN " + obj.item_sn + ")" if obj.item_sn else "")
    else:
        label = obj.display_name or obj.name or "Unnamed vendor"
    return label[:256]


def target_path(target_table, target_id):
    if target_table == "items":
        return BP + "/items/" + str(target_id)
    return BP + "/vendors/" + str(target_id)


def delete_item(db, item_id):
    """Delete a clean item. The caller has checked item_blockers and commits."""
    if db.execute(text("SELECT to_regclass('item_schema.csv_import_map')")).scalar():
        db.execute(
            text(
                "UPDATE item_schema.csv_import_map SET item_id = NULL, action = :a "
                "WHERE item_id = :i"
            ),
            {"a": IMPORT_MAP_ACTION, "i": item_id},
        )
    db.execute(text("DELETE FROM edit_locks WHERE resource_key = :k"),
               {"k": "items:" + str(item_id)})
    db.execute(text("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})


def delete_vendor(db, profile):
    """The same delete as DELETE /api/vendors/{id}. The caller commits."""
    db.delete(profile)


# The lock (spec: The lock). A pending request freezes its target for every
# role until an admin approves or rejects it.
LOCK_MESSAGE = (
    "A delete request is pending for this record. "
    "It cannot be changed until an admin decides."
)


def locked_ids(db, target_table, ids):
    """The ids among ids that have a pending delete request.

    Every route that changes an existing item or vendor calls this before it
    writes. tests/test_delete_request_lock.py lists those routes and fails if
    one stops calling it."""
    wanted = {int(i) for i in ids if i is not None}
    if not wanted:
        return set()
    rows = (
        db.query(DeleteRequest.target_id)
        .filter(
            DeleteRequest.target_table == target_table,
            DeleteRequest.target_id.in_(sorted(wanted)),
            DeleteRequest.status == "pending",
        )
        .all()
    )
    return {r[0] for r in rows}
