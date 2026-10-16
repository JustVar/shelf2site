"""Contract tests: the C2C camera board and quota count cameras only.

Edge boxes link to orders through device_provisioning.item_id the same way
cameras do (migration 056). The C2C board listed every item-linked row as a
camera and the acquire quota counted every one, so on a mixed order (edge
boxes plus cameras) the edge boxes appeared as pending cameras and used up
the camera quota: an order needing two cameras with one edge box refused the
second camera as "2 of 2" already assigned.

Rows are CONTRACT-TEST-prefixed and removed here.
"""

import pytest
from sqlalchemy import text as sqltext

SKU = "CONTRACT-TEST-C2C-SKU"


@pytest.fixture
def mixed_order(admin_client, db):
    db.execute(sqltext(
        "INSERT INTO item_schema.part_numbers (item_sku, item_category) VALUES (:s, 'camera_c2c')"),
        {"s": SKU})
    box = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Mixed Box', 'CONTRACT-TEST-MIXED-BOX', 'edge_box', 'Pending') RETURNING id")).scalar()
    cams = [db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status, item_sku) "
        "VALUES (:n, :s, 'camera_c2c', 'Ready to Deploy', :k) RETURNING id"),
        {"n": f"CONTRACT-TEST Mixed Cam {i}", "s": f"CONTRACT-TEST-MIXED-CAM-{i}", "k": SKU}).scalar()
        for i in (1, 2, 3)]
    db.commit()

    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Mixed Corp", "order_type": "sale",
        "po_number": "CONTRACT-TEST-MIXED-PO"})
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    r = admin_client.put(f"/api/orders/{oid}", json={"sku_requirements": [{"model": SKU, "qty": 2, "source": "stock"}]})
    assert r.status_code == 200, r.text
    r = admin_client.post("/api/provisioning", json={"item_id": box, "customer_order_id": oid})
    assert r.status_code == 200, r.text

    yield {"order_id": oid, "box": box, "cams": cams}

    db.rollback()
    ids = [box] + cams
    db.execute(sqltext("DELETE FROM c2c_certification WHERE device_provisioning_id IN "
                       "(SELECT id FROM device_provisioning WHERE item_id = ANY(:i))"), {"i": ids})
    db.execute(sqltext("DELETE FROM device_provisioning WHERE item_id = ANY(:i)"), {"i": ids})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": oid})
    db.execute(sqltext("DELETE FROM audit_log WHERE target_table = 'items' AND target_id = ANY(:i)"), {"i": ids})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = ANY(:i)"), {"i": ids})
    db.execute(sqltext("DELETE FROM item_schema.part_numbers WHERE item_sku = :s"), {"s": SKU})
    db.commit()


def _acquire(client, order_id, cam_id):
    return client.post("/fulfillment/c2c/acquire", json={"device_id": cam_id, "customer_order_id": order_id})


def test_an_edge_box_on_the_order_does_not_use_the_camera_quota(admin_client, mixed_order):
    oid, cams = mixed_order["order_id"], mixed_order["cams"]
    assert _acquire(admin_client, oid, cams[0]).status_code == 200
    second = _acquire(admin_client, oid, cams[1])
    assert second.status_code == 200, second.text      # was 409 "2 of 2" with the box counted
    third = _acquire(admin_client, oid, cams[2])
    assert third.status_code == 409, third.text         # the quota itself still holds
    assert "(2 of 2)" in third.json()["error"]


def test_the_camera_board_lists_cameras_not_edge_boxes(admin_client, mixed_order):
    oid, cams = mixed_order["order_id"], mixed_order["cams"]
    assert _acquire(admin_client, oid, cams[0]).status_code == 200
    page = admin_client.get("/fulfillment/c2c")
    assert page.status_code == 200
    assert "CONTRACT-TEST-MIXED-CAM-1" in page.text
    assert "CONTRACT-TEST-MIXED-BOX" not in page.text


def test_an_edge_box_cannot_take_a_camera_certification(admin_client, db, mixed_order):
    db.commit()
    pid = db.execute(sqltext("SELECT id FROM device_provisioning WHERE item_id = :b"),
                     {"b": mixed_order["box"]}).scalar()
    r = admin_client.post(f"/fulfillment/c2c/{pid}/certify", json={
        "checklist": {"powered_on": True, "firmware_verified": True,
                      "qr_site_connected": True, "registered": True}})
    assert r.status_code == 400, r.text
    db.commit()
    assert db.execute(sqltext("SELECT count(*) FROM c2c_certification WHERE device_provisioning_id = :p"),
                      {"p": pid}).scalar() == 0


def test_vendor_supplied_cameras_are_not_a_stock_shortfall(admin_client, db, mixed_order):
    """Camera lines the vendor supplies (source oem) arrive with the vendor's
    build, so they never show short on the camera page or fill the quota."""
    oid, cams = mixed_order["order_id"], mixed_order["cams"]
    r = admin_client.put(f"/api/orders/{oid}", json={"sku_requirements": [
        {"model": SKU, "qty": 2, "source": "oem"}]})
    assert r.status_code == 200, r.text
    page = admin_client.get("/fulfillment/c2c").text
    assert "CONTRACT-TEST Mixed Corp" not in page
    assert _acquire(admin_client, oid, cams[0]).status_code == 409
