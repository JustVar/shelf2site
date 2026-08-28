"""Contract tests for linking provisioned units to deployment visits.

Covers the assign endpoint guards and effects, and the picker's GET feed
including both serial resolution paths. All rows are CONTRACT-TEST-prefixed
and removed by the fixture.

The batch test is the one that matters: assignment validates every id before
writing any of them, so one already-assigned id must reject the whole request
and leave the other id unwritten. A refactor to a per-item loop would break
that silently and nothing else would catch it.
"""

import pytest
from sqlalchemy import text as sqltext


def _mk_order(client, name):
    r = client.post("/api/orders/", json={
        "customer_name": name,
        "order_type": "pilot",
        "expected_return": "2026-08-15",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def dep_units(admin_client, db):
    """One order with a deployment visit and two units, plus a second order.

    Unit A resolves through the item path (item_id set), unit B through the
    legacy path (item_id NULL, device_table naming a per-category table), so
    the picker feed exercises both branches.
    """
    order_id = _mk_order(admin_client, "CONTRACT-TEST Deploy Corp")
    other_id = _mk_order(admin_client, "CONTRACT-TEST Other Corp")

    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Dep Cam', 'CONTRACT-TEST-DEP-CAM-1', 'camera_c2c', "
        "'Ready to Deploy') RETURNING id")).scalar()

    dep_id = db.execute(sqltext(
        "INSERT INTO deployment_records (customer_order_id, status) "
        "VALUES (:o, 'scheduled') RETURNING id"), {"o": order_id}).scalar()

    unit_item = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(device_table, device_id, item_id, customer_order_id, current_stage, stages) "
        "VALUES ('items', :i, :i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"i": item_id, "o": order_id}).scalar()

    unit_legacy = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(device_table, device_id, customer_order_id, current_stage, stages) "
        "VALUES ('edge_boxes', 999999, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"o": order_id}).scalar()

    unit_other = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(device_table, device_id, customer_order_id, current_stage, stages) "
        "VALUES ('edge_boxes', 999998, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"o": other_id}).scalar()

    db.commit()
    yield {
        "order_id": order_id, "other_id": other_id, "dep_id": dep_id,
        "item_id": item_id, "unit_item": unit_item,
        "unit_legacy": unit_legacy, "unit_other": unit_other,
    }
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM device_provisioning WHERE customer_order_id IN (:o, :x)"),
        {"o": order_id, "x": other_id})
    db.execute(sqltext("DELETE FROM deployment_records WHERE customer_order_id = :o"),
               {"o": order_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id IN (:o, :x)"),
               {"o": order_id, "x": other_id})
    db.commit()


def _dep_of(db, pid):
    db.commit()
    return db.execute(sqltext(
        "SELECT deployment_record_id FROM device_provisioning WHERE id = :p"),
        {"p": pid}).scalar()


# -- assign endpoint --------------------------------------------------------

def test_assign_happy_path(admin_client, db, dep_units):
    dep, pid = dep_units["dep_id"], dep_units["unit_item"]
    assert _dep_of(db, pid) is None

    r = admin_client.post(f"/fulfillment/deployments/{dep}/units",
                          json={"provisioning_ids": [pid]})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert _dep_of(db, pid) == dep


def test_assign_rejects_unit_from_another_order(admin_client, db, dep_units):
    dep, pid = dep_units["dep_id"], dep_units["unit_other"]

    r = admin_client.post(f"/fulfillment/deployments/{dep}/units",
                          json={"provisioning_ids": [pid]})
    assert r.status_code == 400, r.text
    assert str(pid) in r.json()["detail"]
    assert _dep_of(db, pid) is None


def test_assign_rejects_reassignment(admin_client, db, dep_units):
    dep, pid = dep_units["dep_id"], dep_units["unit_item"]
    assert admin_client.post(f"/fulfillment/deployments/{dep}/units",
                             json={"provisioning_ids": [pid]}).status_code == 200

    r = admin_client.post(f"/fulfillment/deployments/{dep}/units",
                          json={"provisioning_ids": [pid]})
    assert r.status_code == 409, r.text
    assert _dep_of(db, pid) == dep


def test_assign_batch_rejects_all_when_one_is_taken(admin_client, db, dep_units):
    """Validate-all-before-write. One taken id must not let the other through."""
    dep = dep_units["dep_id"]
    taken, fresh = dep_units["unit_item"], dep_units["unit_legacy"]
    assert admin_client.post(f"/fulfillment/deployments/{dep}/units",
                             json={"provisioning_ids": [taken]}).status_code == 200

    r = admin_client.post(f"/fulfillment/deployments/{dep}/units",
                          json={"provisioning_ids": [taken, fresh]})
    assert r.status_code == 409, r.text
    assert _dep_of(db, fresh) is None, "the untaken id must NOT have been written"
    assert _dep_of(db, taken) == dep


def test_assign_requires_provisioning_manager(viewer_client, dep_units):
    dep = dep_units["dep_id"]
    r = viewer_client.post(f"/fulfillment/deployments/{dep}/units",
                           json={"provisioning_ids": [dep_units["unit_item"]]})
    assert r.status_code in (401, 403), r.text


# -- picker feed (GET) ------------------------------------------------------

def test_units_feed_lists_both_serial_paths(admin_client, dep_units):
    dep = dep_units["dep_id"]
    r = admin_client.get(f"/fulfillment/deployments/{dep}/units")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_order_id"] == dep_units["order_id"]
    assert body["assigned"] == []

    by_id = {u["id"]: u for u in body["available"]}
    assert set(by_id) == {dep_units["unit_item"], dep_units["unit_legacy"]}

    # item path resolves through item_schema.items.item_sn
    assert by_id[dep_units["unit_item"]]["serial"] == "CONTRACT-TEST-DEP-CAM-1"
    # legacy path finds no such device, so it falls back rather than raising
    assert by_id[dep_units["unit_legacy"]]["serial"] == "edge_boxes#999999"
    # an empty stages array means no stage machine, so no chip
    assert by_id[dep_units["unit_item"]]["stage"] is None


def test_units_feed_moves_assigned_out_of_available(admin_client, dep_units):
    dep, pid = dep_units["dep_id"], dep_units["unit_item"]
    assert admin_client.post(f"/fulfillment/deployments/{dep}/units",
                             json={"provisioning_ids": [pid]}).status_code == 200

    body = admin_client.get(f"/fulfillment/deployments/{dep}/units").json()
    assert [u["id"] for u in body["assigned"]] == [pid]
    assert pid not in [u["id"] for u in body["available"]]


def test_units_feed_404_for_missing_deployment(admin_client):
    r = admin_client.get("/fulfillment/deployments/999999/units")
    assert r.status_code == 404, r.text


def test_units_feed_requires_provisioning_manager(viewer_client, dep_units):
    dep = dep_units["dep_id"]
    r = viewer_client.get(f"/fulfillment/deployments/{dep}/units")
    assert r.status_code in (401, 403), r.text


# -- picker markup on the board ---------------------------------------------

def test_picker_markup_renders_on_fulfillment_board(admin_client):
    """The trigger and modal must reach the page, and only in the active block.

    Compiles is not renders: the endpoints can be green while the button never
    ships. The trigger count is 1 because the completed-block card copy is
    deliberately left without one.
    """
    r = admin_client.get("/fulfillment/")
    assert r.status_code == 200, r.text
    html = r.text

    # One trigger per ACTIVE deployment card and none on the completed copies.
    # data-dep-tab is emitted only by the active-pipeline card, so it is the
    # count to match; a literal number here would drift with the data.
    active_cards = html.count('data-dep-tab="')
    assert active_cards >= 1, "no active deployment cards rendered to gate on"
    assert html.count("Assign Units</button>") == active_cards
    assert html.count('id="unit-picker-modal"') == 1
    assert html.count("function pkSubmit(") == 1
    assert ".pk-body {" in html

    # hx-boost re-executes this block on a boosted return, so a top-level
    # lexical declaration would throw on the second execution. See CLAUDE.md.
    assert "\nlet " not in html
    assert "\nconst " not in html
