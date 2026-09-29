"""Contract tests for fulfillment and orders on items (item 30 S4).

Stock health, the order panel, the order page and SKU availability read
item_schema.items; the legacy per-category tables are no longer read. All
rows are CONTRACT-TEST-prefixed and removed by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext

from app.database import SessionLocal
from app.routes.fulfillment import _stock_snapshot

SERIAL = "CONTRACT-TEST-FUL-EB-1"
PN = "CONTRACT-TEST-FUL-PN"
MODEL = "CONTRACT-TEST-FUL-MODEL"


@pytest.fixture
def ful_unit(admin_client, db):
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Ful Corp", "order_type": "pilot",
        "expected_return": "2026-12-15",
        "sku_requirements": [{"model": MODEL, "qty": 2, "source": "stock"}]})
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status, "
        "brand_pn, item_model) VALUES ('CONTRACT-TEST Ful Edge', :sn, 'edge_box', "
        "'Ready to Deploy', :pn, :m) RETURNING id"), {"sn": SERIAL, "pn": PN, "m": MODEL}).scalar()
    db.commit()
    yield {"order_id": order_id, "item_id": item_id}
    db.rollback()
    db.execute(sqltext("DELETE FROM device_provisioning WHERE item_id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.commit()


def _group(pn):
    s = SessionLocal()
    try:
        known, unclassified = _stock_snapshot(s)
    finally:
        s.close()
    return {g["model"]: g for g in known + unclassified}.get(pn)


def _link(db, unit):
    pid = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(device_table, device_id, item_id, customer_order_id, current_stage, stages, is_complete) "
        "VALUES ('items', :i, :i, :o, 'acquired', '[]'::jsonb, false) RETURNING id"),
        {"i": unit["item_id"], "o": unit["order_id"]}).scalar()
    db.commit()
    return pid


def test_stock_snapshot_counts_edge_box_items(db, ful_unit):
    g = _group(PN)
    assert g is not None and (g["total"], g["available"]) == (1, 1)
    _link(db, ful_unit)
    g = _group(PN)
    assert (g["total"], g["available"]) == (1, 0), "an active record makes the item busy"


def test_availability_counts_ready_items(admin_client, ful_unit):
    r = admin_client.get(f"/api/orders/{ful_unit['order_id']}/availability")
    assert r.status_code == 200, r.text
    line = [a for a in r.json()["availability"] if a["model"] == MODEL][0]
    assert (line["available"], line["status"]) == (1, "partial")


def test_panel_and_order_page_show_the_item(admin_client, db, ful_unit):
    _link(db, ful_unit)
    r = admin_client.get(f"/api/fulfillment/panel/{ful_unit['order_id']}")
    assert r.status_code == 200, r.text
    dev = r.json()["devices"]
    assert [(d["serial"], d["kind"]) for d in dev] == [(SERIAL, "item")]
    page = admin_client.get(f"/orders/{ful_unit['order_id']}")
    assert page.status_code == 200
    assert f"CONTRACT-TEST Ful Edge ({SERIAL})" in page.text
    assert admin_client.get("/fulfillment/").status_code == 200
