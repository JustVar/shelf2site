"""Contract tests for build certification on edge box items (legacy slice S4).

The certification index, detail page and write routes resolve the unit
through device_provisioning.item_id; the legacy edge_boxes table is no
longer read. All rows are CONTRACT-TEST-prefixed and removed by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext

SERIAL = "CONTRACT-TEST-CERT-EB-1"


@pytest.fixture
def cert_unit(admin_client, db):
    r = admin_client.post("/api/orders/", json={"customer_name": "CONTRACT-TEST Cert Corp",
                                                "order_type": "pilot",
                                                "expected_return": "2026-12-15"})
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    eb_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Cert Edge', :sn, 'edge_box', 'Ready to Deploy') RETURNING id"),
        {"sn": SERIAL}).scalar()
    cam_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Cert Cam', 'CONTRACT-TEST-CERT-CAM-1', 'camera_c2c', "
        "'Ready to Deploy') RETURNING id")).scalar()
    ids = {}
    for key, item_id in (("eb", eb_id), ("cam", cam_id)):
        ids[key] = db.execute(sqltext(
            "INSERT INTO device_provisioning "
            "(item_id, customer_order_id, current_stage, stages) "
            "VALUES (:i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
            {"i": item_id, "o": order_id}).scalar()
    db.commit()
    yield ids
    db.rollback()
    db.execute(sqltext("DELETE FROM device_provisioning WHERE customer_order_id = :o"),
               {"o": order_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id IN (:a, :b)"),
               {"a": eb_id, "b": cam_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.commit()


def test_index_lists_the_edge_box_item(admin_client, cert_unit):
    r = admin_client.get("/fulfillment/certifications")
    assert r.status_code == 200
    assert SERIAL in r.text
    assert "CONTRACT-TEST-CERT-CAM-1" not in r.text


def test_detail_page_resolves_the_item(admin_client, cert_unit):
    r = admin_client.get(f"/fulfillment/certifications/{cert_unit['eb']}")
    assert r.status_code == 200
    assert SERIAL in r.text
    r = admin_client.get(f"/fulfillment/certifications/{cert_unit['cam']}")
    assert r.status_code == 302, "a non edge box row redirects to the index"


def test_write_routes_resolve_the_item_before_validating(admin_client, cert_unit):
    # the edge box row passes the unit check and reaches body validation
    r = admin_client.post(f"/fulfillment/certifications/{cert_unit['eb']}/cancel", json={})
    assert r.status_code == 400 and "reason" in r.text, r.text
    # a camera row stops at the unit check
    r = admin_client.post(f"/fulfillment/certifications/{cert_unit['cam']}/cancel",
                          json={"reason": "contract test"})
    assert r.status_code == 400 and "edge-box only" in r.text, r.text
