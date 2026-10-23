"""Contract tests for fulfillment and orders on items (legacy slice S4).

Assignable stock, the order panel, the order page and SKU availability read
item_schema.items; the legacy per-category tables are no longer read. All
rows are CONTRACT-TEST-prefixed and removed by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext


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
        "item_pn, item_model) VALUES ('CONTRACT-TEST Ful Edge', :sn, 'edge_box', "
        "'Ready to Deploy', :pn, :m) RETURNING id"), {"sn": SERIAL, "pn": PN, "m": MODEL}).scalar()
    db.commit()
    yield {"order_id": order_id, "item_id": item_id}
    db.rollback()
    db.execute(sqltext("DELETE FROM device_provisioning WHERE item_id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.commit()


def _link(db, unit):
    pid = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(item_id, customer_order_id, current_stage, stages, is_complete) "
        "VALUES (:i, :o, 'acquired', '[]'::jsonb, false) RETURNING id"),
        {"i": unit["item_id"], "o": unit["order_id"]}).scalar()
    db.commit()
    return pid


def test_order_page_offers_ready_stock_until_it_is_linked(admin_client, db, ful_unit):
    """The order page's Assign from stock list (docs/specs/one-board-two-tracks.md)
    offers the matching ready item, and stops offering it once it is on an order."""
    cb = f'class="assign-cb" value="{ful_unit["item_id"]}"'
    assert cb in admin_client.get(f"/orders/{ful_unit['order_id']}").text
    _link(db, ful_unit)
    assert cb not in admin_client.get(f"/orders/{ful_unit['order_id']}").text


def test_availability_counts_ready_items(admin_client, ful_unit):
    r = admin_client.get(f"/api/orders/{ful_unit['order_id']}/availability")
    assert r.status_code == 200, r.text
    line = [a for a in r.json()["availability"] if a["model"] == MODEL][0]
    assert (line["available"], line["status"]) == (1, "partial")
    assert (line["linked"], line["remaining"]) == (0, 2)


def _line(client, order_id):
    r = client.get(f"/api/orders/{order_id}/availability")
    assert r.status_code == 200, r.text
    return [a for a in r.json()["availability"] if a["model"] == MODEL][0]


def _set_line(db, order_id, qty, source):
    db.execute(sqltext("UPDATE customer_orders SET sku_requirements = CAST(:r AS jsonb) WHERE id = :o"),
               {"r": f'[{{"model": "{MODEL}", "qty": {qty}, "source": "{source}"}}]', "o": order_id})
    db.commit()


def test_a_linked_unit_counts_toward_its_line(admin_client, db, ful_unit):
    """A unit already on the order fills its line: an installed order never
    reads as short of stock because its units left the shelf."""
    _link(db, ful_unit)
    line = _line(admin_client, ful_unit["order_id"])
    assert (line["linked"], line["remaining"], line["available"], line["status"]) == (1, 1, 0, "none")
    _set_line(db, ful_unit["order_id"], 1, "stock")
    assert _line(admin_client, ful_unit["order_id"])["status"] == "linked"


def test_a_vendor_built_line_does_not_need_stock(admin_client, db, ful_unit):
    _set_line(db, ful_unit["order_id"], 5, "oem")
    line = _line(admin_client, ful_unit["order_id"])
    assert (line["remaining"], line["status"]) == (5, "vendor")


def test_panel_and_order_page_show_the_item(admin_client, db, ful_unit):
    _link(db, ful_unit)
    r = admin_client.get(f"/api/fulfillment/panel/{ful_unit['order_id']}")
    assert r.status_code == 200, r.text
    dev = r.json()["devices"]
    assert [(d["serial"], d["kind"]) for d in dev] == [(SERIAL, "item")]
    page = admin_client.get(f"/orders/{ful_unit['order_id']}")
    assert page.status_code == 200
    # The units table shows the unit name with its serial under it.
    assert "CONTRACT-TEST Ful Edge" in page.text and SERIAL in page.text
    assert admin_client.get("/fulfillment/").status_code == 200
