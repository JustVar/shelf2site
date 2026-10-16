"""Contract tests for edge box provisioning on items (item 30 S4).

Provisioning creates, lists, shows and advances edge box ITEMS; the legacy
edge_boxes table is no longer read. All rows are CONTRACT-TEST-prefixed and
removed by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext

SERIAL = "CONTRACT-TEST-PROV-EB-1"


@pytest.fixture
def prov_item(db):
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status, attributes) "
        "VALUES ('CONTRACT-TEST Prov Edge', :sn, 'edge_box', 'Ready to Deploy', "
        "'{\"sku_version\": \"2026\"}'::jsonb) RETURNING id"), {"sn": SERIAL}).scalar()
    cam_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Prov Cam', 'CONTRACT-TEST-PROV-CAM-1', 'camera', 'Unassigned') "
        "RETURNING id")).scalar()
    db.commit()
    yield item_id, cam_id
    db.rollback()
    db.execute(sqltext("DELETE FROM device_provisioning WHERE item_id IN (:a, :b)"),
               {"a": item_id, "b": cam_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id IN (:a, :b)"),
               {"a": item_id, "b": cam_id})
    db.commit()


def _devices(client):
    r = client.get("/api/provisioning/devices/edge_boxes")
    assert r.status_code == 200, r.text
    return {d["id"]: d for d in r.json()["devices"]}


def test_device_list_offers_edge_box_items_only(admin_client, prov_item):
    item_id, cam_id = prov_item
    devices = _devices(admin_client)
    assert item_id in devices
    assert SERIAL in devices[item_id]["name"]
    assert devices[item_id]["sku_version"] == "2026"
    assert cam_id not in devices
    assert admin_client.get("/api/provisioning/devices/cameras").status_code == 400


def test_create_refuses_a_non_edge_box_item(admin_client, prov_item):
    _item_id, cam_id = prov_item
    r = admin_client.post("/api/provisioning", json={"item_id": cam_id})
    assert r.status_code == 400, r.text
    r = admin_client.post("/api/provisioning", json={})
    assert r.status_code == 400, r.text


def test_create_show_and_advance_an_edge_box_item(admin_client, db, prov_item):
    item_id, _cam_id = prov_item
    r = admin_client.post("/api/provisioning", json={"item_id": item_id, "deployment_type": "pilot"})
    assert r.status_code == 200, r.text
    prov_id = r.json()["id"]

    row = db.execute(sqltext(
        "SELECT item_id, jsonb_array_length(stages), current_stage FROM device_provisioning "
        "WHERE id = :i"), {"i": prov_id}).one()
    assert row[0] == item_id and row[1] > 0 and row[2] == "staged"
    attrs = db.execute(sqltext("SELECT attributes FROM item_schema.items WHERE id = :i"),
                       {"i": item_id}).scalar()
    assert attrs["deployment_type"] == "pilot"
    assert attrs["sku_version"] == "2026", "the attribute update must keep other keys"

    # one active record per item, and the dropdown stops offering it
    assert admin_client.post("/api/provisioning", json={"item_id": item_id}).status_code == 409
    assert item_id not in _devices(admin_client)

    page = admin_client.get(f"/provisioning/{prov_id}")
    assert page.status_code == 200
    assert SERIAL in page.text
    assert "Missing" in page.text, "no UUID yet, so the page must say it is missing"

    # staged -> building advances; building -> registered needs the UUID
    assert admin_client.post(f"/api/provisioning/{prov_id}/advance").status_code == 200
    r = admin_client.post(f"/api/provisioning/{prov_id}/advance")
    assert r.status_code == 400 and "UUID" in r.text, r.text
    db.execute(sqltext("UPDATE item_schema.items SET platform_uuid = 'contract-test-uuid' WHERE id = :i"),
               {"i": item_id})
    db.commit()
    r = admin_client.post(f"/api/provisioning/{prov_id}/advance")
    assert r.status_code == 200 and r.json()["current_stage"] == "registered", r.text


def test_a_label_only_row_cannot_advance(admin_client, db, prov_item):
    _item_id, cam_id = prov_item
    prov_id = db.execute(sqltext(
        "INSERT INTO device_provisioning (item_id, current_stage, stages) "
        "VALUES (:i, 'acquired', '[]'::jsonb) RETURNING id"), {"i": cam_id}).scalar()
    db.commit()
    r = admin_client.post(f"/api/provisioning/{prov_id}/advance")
    assert r.status_code == 400, r.text
