"""Contract tests for values the database would otherwise reject or misfile.

Order status: an unknown string used to be stored and then shown in the New
column, and a blank status stored NULL, which dropped the order off every
board. Item create (intake form and scan intake share create_item): an
unknown category, status, SKU or location used to reach the database and
fail the flush with a 500. Each case below now answers 400 with a message.

Rows are CONTRACT-TEST-prefixed and removed here.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def order(admin_client, db):
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Status Corp",
        "order_type": "pilot",
        "expected_return": "2026-12-15",
    })
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    yield oid
    db.rollback()
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :i"), {"i": oid})
    db.commit()


def _status(db, oid):
    db.commit()
    return db.execute(sqltext("SELECT status FROM customer_orders WHERE id = :i"),
                      {"i": oid}).scalar()


def test_create_refuses_an_unknown_status(admin_client, db):
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Status Corp",
        "order_type": "pilot",
        "status": "almost-done",
    })
    assert r.status_code == 400, r.text
    assert "Unknown order status" in r.json()["error"]
    db.commit()
    assert db.execute(sqltext(
        "SELECT count(*) FROM customer_orders WHERE status = 'almost-done'")).scalar() == 0


@pytest.mark.parametrize("bad", ["almost-done", "", "   "])
def test_update_refuses_an_unknown_or_blank_status(admin_client, db, order, bad):
    r = admin_client.put(f"/api/orders/{order}", json={"status": bad})
    assert r.status_code == 400, r.text
    assert _status(db, order) == "new"


def test_update_accepts_a_known_status(admin_client, db, order):
    r = admin_client.put(f"/api/orders/{order}", json={"status": "building"})
    assert r.status_code == 200, r.text
    assert _status(db, order) == "building"


@pytest.mark.parametrize("field,value,message", [
    ("item_category", "spaceship", "Unknown category"),
    ("item_status", "Lost at sea", "Unknown status"),
    ("brand_sku", "CONTRACT-TEST-NO-SUCH-SKU", "not in the part numbers list"),
    ("location_id", "987654321", "location does not exist"),
])
def test_intake_explains_a_value_the_database_would_reject(editor_client, db, field, value, message):
    form = {"item_name": "CONTRACT-TEST Validation", "item_category": "monitor",
            "item_sn": "CONTRACT-TEST-VAL-1"}
    form[field] = value
    r = editor_client.post("/intake", data=form)
    assert r.status_code == 400, r.status_code
    assert message in r.text
    db.commit()
    assert db.execute(sqltext(
        "SELECT count(*) FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-VAL-1'")).scalar() == 0


def test_scan_intake_explains_an_unknown_location(admin_client, db):
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-VAL-2",
        "target_table": "monitors",
        "direct_to_inventory": True,
        "location_id": 987654321,
    })
    assert r.status_code == 400, r.text
    assert "location does not exist" in r.json()["error"]
    db.commit()
    assert db.execute(sqltext(
        "SELECT count(*) FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-VAL-2'")).scalar() == 0


# -- maintenance log entries (the panel had no writer before) ----------------

@pytest.fixture
def maint_item(db):
    iid = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Maint', 'CONTRACT-TEST-MAINT-1', 'monitor', 'Unassigned') "
        "RETURNING id")).scalar()
    db.commit()
    yield iid
    db.rollback()
    db.execute(sqltext("DELETE FROM item_schema.maintenance_log WHERE item_id = :i"), {"i": iid})
    db.execute(sqltext("DELETE FROM audit_log WHERE target_table = 'items' AND target_id = :i"), {"i": iid})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": iid})
    db.commit()


def _maint_rows(db, iid):
    db.commit()
    return db.execute(sqltext(
        "SELECT entry_type, description, maintenance_date::text, performed_by "
        "FROM item_schema.maintenance_log WHERE item_id = :i"), {"i": iid}).all()


def test_editor_adds_a_maintenance_entry_and_the_page_shows_it(editor_client, db, maint_item):
    r = editor_client.post(f"/items/{maint_item}/maintenance", data={
        "entry_type": "firmware_update", "description": "Flashed BIOS 1.14",
        "maintenance_date": "2026-09-30", "performed_by": "CONTRACT-TEST Tech"})
    assert r.status_code == 303, r.status_code
    assert _maint_rows(db, maint_item) == [
        ("firmware_update", "Flashed BIOS 1.14", "2026-09-30", "CONTRACT-TEST Tech")]
    page = editor_client.get(f"/items/{maint_item}")
    assert "Flashed BIOS 1.14" in page.text and "Firmware Update" in page.text
    assert 'id="add-maintenance-form"' in page.text


@pytest.mark.parametrize("form", [
    {"entry_type": "teleport", "description": "x"},
    {"entry_type": "repair", "description": "   "},
    {"entry_type": "repair", "description": "x", "maintenance_date": "yesterday"},
])
def test_a_bad_maintenance_entry_writes_nothing(editor_client, db, maint_item, form):
    r = editor_client.post(f"/items/{maint_item}/maintenance", data=form)
    assert r.status_code == 303
    assert "toast_type=warning" in r.headers["location"]
    assert _maint_rows(db, maint_item) == []


def test_a_viewer_cannot_add_a_maintenance_entry(viewer_client, db, maint_item):
    r = viewer_client.post(f"/items/{maint_item}/maintenance", data={
        "entry_type": "repair", "description": "viewer write"})
    assert r.status_code == 403
    assert _maint_rows(db, maint_item) == []
