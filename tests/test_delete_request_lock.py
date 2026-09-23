"""The delete request lock (docs/specs/delete-request-queue.md, slice B).

A pending request freezes its item or vendor for every role until an admin
approves or rejects it. Two kinds of test live here.

Structural: every route that can change an existing item or vendor is
listed below and must call locked_ids, the one helper. Every write route
that names Item or VendorProfile must be listed somewhere, so a new one
fails here until someone decides which list it belongs in.

Behaviour: a few guarded routes are driven against the live app with a
pending request, then again after the request is rejected. Every record is
CONTRACT-TEST prefixed and removed by the fixtures.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import text as sqltext

from app.delete_requests import LOCK_MESSAGE

ROUTES = Path(__file__).resolve().parents[1] / "app" / "routes"

# (file, function): the call that proves the guard. retag_unit_photo adds
# tags only through _tag_serials, which carries the guard itself.
GUARDED = {
    ("item_detail.py", "item_update"): "locked_ids",
    ("item_detail.py", "add_receipt"): "locked_ids",
    ("item_detail.py", "item_decommission"): "locked_ids",
    ("item_detail.py", "item_reactivate"): "locked_ids",
    ("inventory.py", "quick_view_save"): "locked_ids",
    ("inventory.py", "inventory_bulk_update"): "locked_ids",
    ("triage.py", "triage_fix_save"): "locked_ids",
    ("triage.py", "triage_bulk_update"): "locked_ids",
    ("checkout.py", "do_checkout"): "locked_ids",
    ("checkout.py", "do_bulk_checkout"): "locked_ids",
    ("containment.py", "install_component"): "locked_ids",
    ("containment.py", "move_component"): "locked_ids",
    ("c2c.py", "c2c_acquire"): "locked_ids",
    ("orders.py", "assign_items_to_order"): "locked_ids",
    ("unit_photos.py", "upload_unit_photo"): "locked_ids",
    ("unit_photos.py", "_tag_serials"): "locked_ids",
    ("unit_photos.py", "retag_unit_photo"): "_tag_serials",
    ("vendors.py", "update_vendor"): "locked_ids",
    ("vendors.py", "delete_vendor"): "locked_ids",
}

# Write an item only through a link the clean check forbids, so a locked
# item can never reach them. A request is filed only for a clean item, and
# every route that could add such a link is in GUARDED.
EXEMPT = {
    ("checkout.py", "do_checkin"): "needs a checkout row",
    ("checkout.py", "do_bulk_checkin"): "needs a checkout row",
    ("containment.py", "uninstall_component"): "needs a component history row",
    ("fulfillment.py", "update_ship_details"): "needs a device_provisioning row",
    ("provisioning.py", "update_provisioning"): "needs a device_provisioning row",
}

# Name Item or VendorProfile but never change an existing one.
NOT_A_TARGET = {
    ("admin.py", "delete_part_number"): "refuses while items use the part number",
    ("c2c.py", "c2c_certify"): "writes the certification; reads the item serial",
    ("c2c.py", "c2c_upload_cert_file"): "writes the certification; reads the item serial",
    ("map.py", "map_set_location"): "writes the place coordinates, not the item",
    ("sites.py", "delete_site"): "refuses while items are placed there",
    ("vendors.py", "create_vendor"): "creates a new vendor",
    ("vendors.py", "auto_create_vendors"): "creates new vendors",
}

# A write route whose body uses any of these can touch an existing item or vendor.
TOUCHES = {"Item", "VendorProfile", "_get_item", "_tag_serials"}
WRITE_METHODS = {"post", "put", "patch", "delete"}


def _functions():
    """Every top-level function in app/routes, with whether it is a write route."""
    found = {}
    for path in sorted(ROUTES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_write = any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr in WRITE_METHODS
                for d in node.decorator_list
            )
            found[(path.name, node.name)] = (node, is_write)
    return found


def _calls(node):
    return {
        n.func.id for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


FUNCTIONS = _functions()


@pytest.mark.parametrize("key", sorted(GUARDED), ids=lambda k: "%s:%s" % k)
def test_guarded_function_calls_the_helper(key):
    assert key in FUNCTIONS, "%s:%s no longer exists; update GUARDED" % key
    node, _ = FUNCTIONS[key]
    assert GUARDED[key] in _calls(node), "%s:%s stopped calling %s" % (key + (GUARDED[key],))


def test_lists_do_not_overlap():
    assert not (set(GUARDED) & set(EXEMPT))
    assert not (set(GUARDED) & set(NOT_A_TARGET))
    assert not (set(EXEMPT) & set(NOT_A_TARGET))


def test_listed_functions_exist():
    missing = [k for k in list(EXEMPT) + list(NOT_A_TARGET) if k not in FUNCTIONS]
    assert not missing, "listed but gone: %s" % missing


def test_every_item_or_vendor_write_route_is_classified():
    known = set(GUARDED) | set(EXEMPT) | set(NOT_A_TARGET)
    unlisted = sorted(
        key for key, (node, is_write) in FUNCTIONS.items()
        if is_write and _names(node) & TOUCHES and key not in known
    )
    assert not unlisted, (
        "write routes that touch items or vendors but are in no list: %s. "
        "Guard them with locked_ids, or add them to EXEMPT or NOT_A_TARGET "
        "with the reason." % unlisted
    )


# -- Behaviour -------------------------------------------------------------------

def _new_item(db, suffix):
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES (:n, :s, 'camera_c2c', 'Unassigned') RETURNING id"),
        {"n": "CONTRACT-TEST LOCK " + suffix, "s": "CONTRACT-TEST-LOCK-" + suffix}).scalar()
    db.commit()
    return item_id


def _cleanup(db, table, target_id):
    db.execute(sqltext(
        "DELETE FROM delete_requests WHERE target_table = :t AND target_id = :i"),
        {"t": table, "i": target_id})
    db.execute(sqltext(
        "DELETE FROM audit_log WHERE target_table = :t AND target_id = :i"),
        {"t": table, "i": target_id})
    db.commit()


@pytest.fixture
def lock_items(db):
    ids = [_new_item(db, "A"), _new_item(db, "B")]
    yield ids
    for item_id in ids:
        _cleanup(db, "items", item_id)
        db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.commit()


@pytest.fixture
def lock_vendor(db):
    vendor_id = db.execute(sqltext(
        "INSERT INTO vendor_profiles (name, is_oem) VALUES ('CONTRACT-TEST LOCK Vendor', false) "
        "RETURNING id"
    )).scalar()
    db.commit()
    yield vendor_id
    _cleanup(db, "vendor_profiles", vendor_id)
    db.execute(sqltext("DELETE FROM vendor_profiles WHERE id = :i"), {"i": vendor_id})
    db.commit()


def _file(client, table, target_id):
    r = client.post("/api/delete-requests", json={
        "target_table": table, "target_id": target_id, "reason": "duplicate record"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _reject(admin_client, request_id):
    assert admin_client.post(f"/api/delete-requests/{request_id}/reject").status_code == 200


def _item_field(db, item_id, column):
    db.expire_all()
    return db.execute(sqltext(
        "SELECT " + column + " FROM item_schema.items WHERE id = :i"), {"i": item_id}).scalar()


def test_item_edit_is_refused_until_the_request_is_rejected(
        editor_client, admin_client, db, lock_items):
    item_id = lock_items[0]
    rid = _file(editor_client, "items", item_id)

    r = admin_client.post(f"/items/{item_id}", data={"item_name": "CONTRACT-TEST LOCK changed"})
    assert r.status_code == 303
    assert "toast_type=warning" in r.headers["location"]
    assert _item_field(db, item_id, "item_name") == "CONTRACT-TEST LOCK A"

    _reject(admin_client, rid)
    r = admin_client.post(f"/items/{item_id}", data={"item_name": "CONTRACT-TEST LOCK changed"})
    assert r.status_code == 303
    assert "toast_type" not in r.headers["location"]
    assert _item_field(db, item_id, "item_name") == "CONTRACT-TEST LOCK changed"


def test_decommission_is_refused_for_an_admin_too(editor_client, admin_client, db, lock_items):
    item_id = lock_items[0]
    _file(editor_client, "items", item_id)
    r = admin_client.post(f"/items/{item_id}/decommission",
                          data={"reason": "broken", "decommission_date": "2026-09-23"})
    assert r.status_code == 409
    assert r.json()["error"] == LOCK_MESSAGE
    assert _item_field(db, item_id, "item_status") == "Unassigned"


def test_quick_view_save_is_refused(editor_client, db, lock_items):
    item_id = lock_items[0]
    _file(editor_client, "items", item_id)
    r = editor_client.post(f"/inventory/quick-view/{item_id}",
                           data={"item_name": "CONTRACT-TEST LOCK changed"})
    assert r.status_code == 409
    assert r.text == LOCK_MESSAGE
    assert _item_field(db, item_id, "item_name") == "CONTRACT-TEST LOCK A"


def test_bulk_update_skips_the_locked_item(editor_client, db, lock_items):
    locked, free = lock_items
    _file(editor_client, "items", locked)
    r = editor_client.post("/inventory/bulk", data={
        "action": "department", "value": "CONTRACT-TEST LOCK dept",
        "item_ids": [str(locked), str(free)]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 1
    assert body["skipped_ids"] == [locked]
    assert _item_field(db, locked, "department_or_owner") is None
    assert _item_field(db, free, "department_or_owner") == "CONTRACT-TEST LOCK dept"


def test_vendor_edit_and_delete_are_refused_until_rejected(
        editor_client, admin_client, db, lock_vendor):
    rid = _file(editor_client, "vendor_profiles", lock_vendor)

    r = admin_client.put(f"/api/vendors/{lock_vendor}", json={"notes": "CONTRACT-TEST LOCK note"})
    assert r.status_code == 409
    assert r.json()["error"] == LOCK_MESSAGE
    r = admin_client.delete(f"/api/vendors/{lock_vendor}")
    assert r.status_code == 409
    assert db.execute(sqltext("SELECT count(*) FROM vendor_profiles WHERE id = :i"),
                      {"i": lock_vendor}).scalar() == 1

    _reject(admin_client, rid)
    r = admin_client.put(f"/api/vendors/{lock_vendor}", json={"notes": "CONTRACT-TEST LOCK note"})
    assert r.status_code == 200, r.text
