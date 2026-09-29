"""Contract tests for the delete request queue.

Spec: docs/specs/delete-request-queue.md, slice A. Covers who may file,
withdraw, approve and reject; the one-pending rule; the clean check at
request time and again at approval; the item delete and its import map
mark; the vendor delete; the audit rows; and the admin page gate. Every
record is CONTRACT-TEST prefixed and removed by the fixtures.
"""

import secrets

import pytest
from sqlalchemy import text as sqltext

MAP_SOURCE = "contract-test-delete-requests"


def _cleanup(db, table, target_id):
    db.execute(sqltext(
        "DELETE FROM delete_requests WHERE target_table = :t AND target_id = :i"),
        {"t": table, "i": target_id})
    db.execute(sqltext(
        "DELETE FROM audit_log WHERE target_table = :t AND target_id = :i"),
        {"t": table, "i": target_id})
    db.commit()


def _new_item(db, suffix):
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES (:n, :s, 'camera_c2c', 'Unassigned') RETURNING id"),
        {"n": "CONTRACT-TEST DR " + suffix, "s": "CONTRACT-TEST-DR-" + suffix}).scalar()
    db.commit()
    return item_id


@pytest.fixture
def dr_item(db):
    """A clean item with an import map row, as most live items have."""
    item_id = _new_item(db, "CLEAN")
    csv_id = secrets.randbelow(10 ** 9)
    db.execute(sqltext(
        "INSERT INTO item_schema.csv_import_map (source, csv_id, item_id, action) "
        "VALUES (:s, :c, :i, 'created')"),
        {"s": MAP_SOURCE, "c": csv_id, "i": item_id})
    db.commit()
    yield {"item_id": item_id, "csv_id": csv_id}
    _cleanup(db, "items", item_id)
    db.execute(sqltext("DELETE FROM item_schema.csv_import_map WHERE source = :s"),
               {"s": MAP_SOURCE})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.commit()


@pytest.fixture
def dr_item_linked(db, admin_client):
    """An item on an order through a device_provisioning row: not clean."""
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST DR Corp",
        "order_type": "pilot",
        "expected_return": "2026-10-01",
    })
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    item_id = _new_item(db, "LINKED")
    prov_id = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(item_id, customer_order_id, current_stage, stages) "
        "VALUES (:i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"i": item_id, "o": order_id}).scalar()
    db.commit()
    yield {"item_id": item_id, "order_id": order_id, "prov_id": prov_id}
    db.execute(sqltext("DELETE FROM device_provisioning WHERE id = :p"), {"p": prov_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.commit()
    _cleanup(db, "items", item_id)
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.commit()


@pytest.fixture
def dr_vendor(db):
    vendor_id = db.execute(sqltext(
        "INSERT INTO vendor_profiles (name, is_oem) VALUES ('CONTRACT-TEST DR Vendor', false) "
        "RETURNING id"
    )).scalar()
    db.commit()
    yield vendor_id
    _cleanup(db, "vendor_profiles", vendor_id)
    db.execute(sqltext("DELETE FROM vendor_profiles WHERE id = :i"), {"i": vendor_id})
    db.commit()


def _file(client, table, target_id, reason="duplicate record"):
    return client.post("/api/delete-requests", json={
        "target_table": table, "target_id": target_id, "reason": reason})


def _status(db, request_id):
    db.expire_all()
    return db.execute(sqltext("SELECT status FROM delete_requests WHERE id = :i"),
                      {"i": request_id}).scalar()


def _item_exists(db, item_id):
    return db.execute(sqltext("SELECT count(*) FROM item_schema.items WHERE id = :i"),
                      {"i": item_id}).scalar() == 1


def _events(db, table, target_id):
    return [r[0] for r in db.execute(sqltext(
        "SELECT event_type FROM audit_log WHERE target_table = :t AND target_id = :i "
        "ORDER BY id"), {"t": table, "i": target_id})]


# -- Filing ------------------------------------------------------------------

def test_viewer_cannot_file(viewer_client, dr_item):
    assert _file(viewer_client, "items", dr_item["item_id"]).status_code == 403


def test_reason_is_required(editor_client, dr_item):
    r = _file(editor_client, "items", dr_item["item_id"], reason="   ")
    assert r.status_code == 400
    assert "reason" in r.json()["error"].lower()


def test_unknown_record_type_is_refused(editor_client, dr_item):
    assert _file(editor_client, "users", dr_item["item_id"]).status_code == 400


def test_missing_record_is_404(editor_client):
    assert _file(editor_client, "items", 2000000000).status_code == 404


def test_item_with_history_is_refused(editor_client, dr_item_linked):
    r = _file(editor_client, "items", dr_item_linked["item_id"])
    assert r.status_code == 409
    assert r.json()["links"] == ["order units"]
    assert "decommission" in r.json()["error"].lower()


def test_one_pending_request_per_record(editor_client, admin_client, dr_item):
    assert _file(editor_client, "items", dr_item["item_id"]).status_code == 200
    r = _file(admin_client, "items", dr_item["item_id"])
    assert r.status_code == 409


# -- Withdraw ------------------------------------------------------------------

def test_only_the_requester_can_withdraw(editor_client, admin_client, db, dr_item):
    rid = _file(editor_client, "items", dr_item["item_id"]).json()["id"]
    assert admin_client.post(f"/api/delete-requests/{rid}/withdraw").status_code == 403
    assert _status(db, rid) == "pending"
    assert editor_client.post(f"/api/delete-requests/{rid}/withdraw").status_code == 200
    assert _status(db, rid) == "withdrawn"
    assert editor_client.post(f"/api/delete-requests/{rid}/withdraw").status_code == 409


# -- Reject --------------------------------------------------------------------

def test_editor_cannot_decide(editor_client, dr_item):
    rid = _file(editor_client, "items", dr_item["item_id"]).json()["id"]
    assert editor_client.post(f"/api/delete-requests/{rid}/approve").status_code == 403
    assert editor_client.post(f"/api/delete-requests/{rid}/reject").status_code == 403


def test_reject_keeps_the_item(editor_client, admin_client, db, dr_item):
    item_id = dr_item["item_id"]
    rid = _file(editor_client, "items", item_id).json()["id"]
    assert admin_client.post(f"/api/delete-requests/{rid}/reject").status_code == 200
    assert _status(db, rid) == "rejected"
    assert _item_exists(db, item_id)
    assert _events(db, "items", item_id) == ["delete_requested", "delete_request_rejected"]
    # a rejected request no longer blocks a new one
    assert _file(editor_client, "items", item_id).status_code == 200


# -- Approve -------------------------------------------------------------------

def test_approve_deletes_a_clean_item_and_marks_the_import_map(
        editor_client, admin_client, db, dr_item):
    item_id = dr_item["item_id"]
    rid = _file(editor_client, "items", item_id).json()["id"]
    r = admin_client.post(f"/api/delete-requests/{rid}/approve")
    assert r.status_code == 200, r.text
    assert _status(db, rid) == "approved"
    assert not _item_exists(db, item_id)
    row = db.execute(sqltext(
        "SELECT item_id, action FROM item_schema.csv_import_map "
        "WHERE source = :s AND csv_id = :c"),
        {"s": MAP_SOURCE, "c": dr_item["csv_id"]}).first()
    assert row is not None
    assert row[0] is None
    assert row[1] == "deleted_by_request"
    assert _events(db, "items", item_id) == [
        "delete_requested", "delete_request_approved", "item_deleted"]


def test_approve_checks_again(editor_client, admin_client, db, dr_item):
    """History that appears after filing stops the delete; the request stays pending."""
    item_id = dr_item["item_id"]
    rid = _file(editor_client, "items", item_id).json()["id"]
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST DR Late Corp",
        "order_type": "pilot",
        "expected_return": "2026-10-01",
    })
    order_id = r.json()["id"]
    prov_id = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(item_id, customer_order_id, current_stage, stages) "
        "VALUES (:i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"i": item_id, "o": order_id}).scalar()
    db.commit()
    try:
        r = admin_client.post(f"/api/delete-requests/{rid}/approve")
        assert r.status_code == 409
        assert r.json()["links"] == ["order units"]
        assert _status(db, rid) == "pending"
        assert _item_exists(db, item_id)
    finally:
        db.execute(sqltext("DELETE FROM device_provisioning WHERE id = :p"), {"p": prov_id})
        db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
        db.commit()


def test_approve_deletes_a_vendor(editor_client, admin_client, db, dr_vendor):
    rid = _file(editor_client, "vendor_profiles", dr_vendor).json()["id"]
    assert admin_client.post(f"/api/delete-requests/{rid}/approve").status_code == 200
    assert db.execute(sqltext("SELECT count(*) FROM vendor_profiles WHERE id = :i"),
                      {"i": dr_vendor}).scalar() == 0
    assert _events(db, "vendor_profiles", dr_vendor) == [
        "delete_requested", "delete_request_approved", "vendor_deleted"]


# -- Pages ---------------------------------------------------------------------

def test_admin_page_is_admin_only(editor_client, admin_client, dr_item):
    _file(editor_client, "items", dr_item["item_id"])
    assert editor_client.get("/admin/delete-requests").status_code == 403
    r = admin_client.get("/admin/delete-requests", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "CONTRACT-TEST DR CLEAN" in r.text


def test_item_page_shows_the_pending_request(editor_client, dr_item):
    item_id = dr_item["item_id"]
    before = editor_client.get(f"/items/{item_id}", headers={"accept": "text/html"})
    assert 'id="dr-request-btn"' in before.text
    assert 'id="dr-banner"' not in before.text
    _file(editor_client, "items", item_id)
    after = editor_client.get(f"/items/{item_id}", headers={"accept": "text/html"})
    assert 'id="dr-banner"' in after.text
    assert 'id="dr-withdraw-btn"' in after.text
    assert 'id="dr-request-btn"' not in after.text
