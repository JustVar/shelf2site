"""Contract tests for the SKU-requirements editor + Assign/Ship panel slice.

Covers: PUT sku_requirements validation + normalization, the fulfillment
panel-state endpoint, assign-items guards + effects, ship status/unit
transitions, item-linked loaner return, and the intake required-field
guard. All rows are CONTRACT-TEST-prefixed and cleaned by the fixture.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def sku_order(admin_client, db):
    """A pilot order + one Ready-to-Deploy edge box carrying a catalog SKU."""
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST SKU Corp",
        "order_type": "pilot",
        "expected_return": "2026-08-15",
    })
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status, brand_sku) "
        "VALUES ('CONTRACT-TEST SKU Box', 'CONTRACT-TEST-SKU-BOX-1', 'edge_box', "
        "'Ready to Deploy', 'PVA-100-30NR') RETURNING id")).scalar()
    db.commit()
    yield {"order_id": order_id, "item_id": item_id}
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM device_provisioning WHERE customer_order_id = :o OR item_id = :i"),
        {"o": order_id, "i": item_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.commit()


def _stored_reqs(db, order_id):
    db.commit()
    return db.execute(sqltext(
        "SELECT sku_requirements FROM customer_orders WHERE id = :o"), {"o": order_id}).scalar()


def _item_status(db, item_id):
    db.commit()
    return db.execute(sqltext(
        "SELECT item_status FROM item_schema.items WHERE id = :i"), {"i": item_id}).scalar()


# ── sku_requirements editor route (PUT /api/orders/{id}) ────────────────────

def test_sku_requirements_rejects_bad_shapes(admin_client, sku_order):
    oid = sku_order["order_id"]
    for bad in (
        "not-a-list",
        ["just-a-string"],
        [{"model": "", "qty": 1}],
        [{"model": "X", "qty": 0}],
        [{"model": "X", "qty": "many"}],
        [{"model": "X", "qty": 1, "source": "bogus"}],
    ):
        r = admin_client.put(f"/api/orders/{oid}", json={"sku_requirements": bad})
        assert r.status_code == 400, (bad, r.text)


def test_sku_requirements_normalizes_to_canonical_model_key(admin_client, db, sku_order):
    oid = sku_order["order_id"]
    r = admin_client.put(f"/api/orders/{oid}", json={
        "sku_requirements": [{"sku": "PVA-100-30NR", "qty": "2"}],
    })
    assert r.status_code == 200, r.text
    assert _stored_reqs(db, oid) == [{"model": "PVA-100-30NR", "qty": 2, "source": "tbd"}]


def test_sku_requirements_free_text_allowed(admin_client, db, sku_order):
    oid = sku_order["order_id"]
    r = admin_client.put(f"/api/orders/{oid}", json={
        "sku_requirements": [{"model": "CONTRACT-TEST not-in-catalog", "qty": 1, "source": "oem"}],
    })
    assert r.status_code == 200, r.text
    assert _stored_reqs(db, oid)[0]["model"] == "CONTRACT-TEST not-in-catalog"


# ── panel state endpoint ─────────────────────────────────────────────────────

def test_panel_404_on_unknown_order(admin_client):
    assert admin_client.get("/api/fulfillment/panel/999999").status_code == 404


def test_panel_state_names_requirements_and_candidates(admin_client, sku_order):
    oid = sku_order["order_id"]
    r = admin_client.put(f"/api/orders/{oid}", json={
        "sku_requirements": [{"model": "PVA-100-30NR", "qty": 1}]})
    assert r.status_code == 200, r.text
    data = admin_client.get(f"/api/fulfillment/panel/{oid}").json()
    assert data["order"]["id"] == oid
    assert data["requirements"] == [{"model": "PVA-100-30NR", "qty": 1, "source": "tbd"}]
    assert sku_order["item_id"] in [c["item_id"] for c in data["candidates"]]
    assert data["devices"] == []
    assert data["ship"]["shipped_date"] is None


# ── assign-items ─────────────────────────────────────────────────────────────

def test_assign_items_guards(admin_client, viewer_client, db, sku_order):
    oid, iid = sku_order["order_id"], sku_order["item_id"]
    assert admin_client.post(f"/api/orders/{oid}/assign-items",
                             json={"item_ids": []}).status_code == 400
    assert admin_client.post("/api/orders/999999/assign-items",
                             json={"item_ids": [iid]}).status_code == 404
    assert viewer_client.post(f"/api/orders/{oid}/assign-items",
                              json={"item_ids": [iid]}).status_code != 200
    db.execute(sqltext("UPDATE item_schema.items SET item_status = 'Pending' WHERE id = :i"),
               {"i": iid}); db.commit()
    r = admin_client.post(f"/api/orders/{oid}/assign-items", json={"item_ids": [iid]})
    assert r.status_code == 409 and "not Ready to Deploy" in r.json()["error"]
    db.execute(sqltext("UPDATE item_schema.items SET item_status = 'Ready to Deploy' WHERE id = :i"),
               {"i": iid}); db.commit()


def test_assign_ship_return_round_trip(admin_client, db, sku_order):
    oid, iid = sku_order["order_id"], sku_order["item_id"]
    admin_client.put(f"/api/orders/{oid}", json={
        "sku_requirements": [{"model": "PVA-100-30NR", "qty": 1}]})

    # assign: creates an item-linked provisioning row, candidate disappears
    r = admin_client.post(f"/api/orders/{oid}/assign-items", json={"item_ids": [iid]})
    assert r.status_code == 200, r.text
    data = admin_client.get(f"/api/fulfillment/panel/{oid}").json()
    assert iid not in [c["item_id"] for c in data["candidates"]]
    assert [d["serial"] for d in data["devices"]] == ["CONTRACT-TEST-SKU-BOX-1"]

    # double-assign blocked while still out
    r = admin_client.post(f"/api/orders/{oid}/assign-items", json={"item_ids": [iid]})
    assert r.status_code == 409, r.text

    # loaner unit appears on Pilots Due Back (item-linked derivation)
    page = admin_client.get("/fulfillment/pilots-due-back").text
    assert "CONTRACT-TEST-SKU-BOX-1" in page

    # ship: a 'new' order advances to shipped, the unit goes Deployed
    r = admin_client.post(f"/fulfillment/{oid}/ship", json={
        "ship_method": "carrier", "carrier": "FedEx",
        "tracking_number": "CONTRACT-TEST-TRK-1", "shipped_date": "2026-07-11"})
    assert r.status_code == 200 and r.json()["status"] == "shipped", r.text
    assert _item_status(db, iid) == "Deployed"

    # return: stamps returned_date, unit becomes assignable again
    prov_id = db.execute(sqltext(
        "SELECT id FROM device_provisioning WHERE item_id = :i AND returned_date IS NULL"),
        {"i": iid}).scalar()
    r = admin_client.post(f"/fulfillment/c2c/{prov_id}/return", json={})
    assert r.status_code == 200, r.text
    db.commit()
    returned = db.execute(sqltext(
        "SELECT returned_date FROM device_provisioning WHERE id = :p"), {"p": prov_id}).scalar()
    assert returned is not None
    # status does NOT auto-reset on return (return-as-ending, same as C2C) —
    # stage the unit back to stock explicitly, then it is assignable again
    db.execute(sqltext(
        "UPDATE item_schema.items SET item_status = 'Ready to Deploy' WHERE id = :i"),
        {"i": iid}); db.commit()
    r = admin_client.post(f"/api/orders/{oid}/assign-items", json={"item_ids": [iid]})
    assert r.status_code == 200, r.text


def test_return_rejects_legacy_non_item_row(admin_client, db, sku_order):
    oid = sku_order["order_id"]
    prov_id = db.execute(sqltext(
        "INSERT INTO device_provisioning (customer_order_id, "
        "current_stage, stages, is_complete) "
        "VALUES (:o, 'registered', '[]'::jsonb, false) RETURNING id"),
        {"o": oid}).scalar()
    db.commit()
    r = admin_client.post(f"/fulfillment/c2c/{prov_id}/return", json={})
    assert r.status_code == 400 and "item-linked" in r.json()["error"]


# ── intake required fields (ghost-item guard) ────────────────────────────────

def test_intake_rejects_empty_name_and_category(editor_client, db):
    before = db.execute(sqltext("SELECT count(*) FROM item_schema.items")).scalar()
    r = editor_client.post("/intake", data={"item_name": "  ", "item_category": ""})
    assert r.status_code == 400
    assert "Item name and category are required" in r.text
    db.commit()
    after = db.execute(sqltext("SELECT count(*) FROM item_schema.items")).scalar()
    assert after == before
