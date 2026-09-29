"""Contract tests for item decommission and reactivation.

Owner spec: docs/specs/item-decommission.md. Covers the action guards
(editor tier, required reason and date, the active-order-link refusal),
the code-mediated status rule at the hand-edit surfaces, default hiding
on inventory and search with the include toggle, the dedicated view, and
both audit events. All rows are CONTRACT-TEST-prefixed and removed by
the fixtures.
"""

import pytest
from sqlalchemy import text as sqltext


def _cleanup_item(db, item_id):
    db.execute(sqltext(
        "DELETE FROM audit_log WHERE target_table = 'items' AND target_id = :i"),
        {"i": item_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.commit()


@pytest.fixture
def dec_item(db):
    """One plain inventory item, no order links."""
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Dec Item', 'CONTRACT-TEST-DEC-1', 'camera_c2c', "
        "'Unassigned') RETURNING id")).scalar()
    db.commit()
    yield item_id
    _cleanup_item(db, item_id)


@pytest.fixture
def dec_item_linked(db, admin_client):
    """An item on an order through an active device_provisioning row."""
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Dec Corp",
        "order_type": "pilot",
        "expected_return": "2026-10-01",
    })
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]

    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Dec Linked', 'CONTRACT-TEST-DEC-2', 'camera_c2c', "
        "'Deployed') RETURNING id")).scalar()
    prov_id = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(item_id, customer_order_id, current_stage, stages) "
        "VALUES (:i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"i": item_id, "o": order_id}).scalar()
    db.commit()
    yield {"item_id": item_id, "order_id": order_id, "prov_id": prov_id}
    db.execute(sqltext("DELETE FROM device_provisioning WHERE id = :p"),
               {"p": prov_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.commit()
    _cleanup_item(db, item_id)


def _status_of(db, item_id):
    return db.execute(sqltext(
        "SELECT item_status FROM item_schema.items WHERE id = :i"),
        {"i": item_id}).scalar()


def _decommission(client, item_id, reason="test retire"):
    r = client.post(f"/items/{item_id}/decommission",
                    data={"reason": reason, "decommission_date": "2026-09-02"})
    assert r.status_code == 200, r.text


# -- Decommission guards ----------------------------------------------------

def test_decommission_requires_editor_tier(viewer_client, dec_item):
    r = viewer_client.post(f"/items/{dec_item}/decommission",
                           data={"reason": "x", "decommission_date": "2026-09-02"})
    assert r.status_code == 403


def test_decommission_requires_reason(editor_client, db, dec_item):
    r = editor_client.post(f"/items/{dec_item}/decommission",
                           data={"reason": "   ", "decommission_date": "2026-09-02"})
    assert r.status_code == 400
    assert "reason" in r.json()["error"].lower()
    assert _status_of(db, dec_item) == "Unassigned"


def test_decommission_requires_valid_date(editor_client, dec_item):
    r = editor_client.post(f"/items/{dec_item}/decommission",
                           data={"reason": "broken", "decommission_date": "not-a-date"})
    assert r.status_code == 400


def test_decommission_refused_while_unit_active(editor_client, db, dec_item_linked):
    item_id = dec_item_linked["item_id"]
    r = editor_client.post(f"/items/{item_id}/decommission",
                           data={"reason": "broken", "decommission_date": "2026-09-02"})
    assert r.status_code == 409
    assert "order" in r.json()["error"].lower()
    assert _status_of(db, item_id) == "Deployed"


def test_return_releases_the_block(editor_client, db, dec_item_linked):
    item_id = dec_item_linked["item_id"]
    db.execute(sqltext(
        "UPDATE device_provisioning SET returned_date = '2026-09-01' WHERE id = :p"),
        {"p": dec_item_linked["prov_id"]})
    db.commit()
    r = editor_client.post(f"/items/{item_id}/decommission",
                           data={"reason": "end of life", "decommission_date": "2026-09-02"})
    assert r.status_code == 200, r.text
    row = db.execute(sqltext(
        "SELECT item_status, decommission_reason, decommission_date, decommissioned_by "
        "FROM item_schema.items WHERE id = :i"), {"i": item_id}).first()
    assert row.item_status == "Decommissioned"
    assert row.decommission_reason == "end of life"
    assert str(row.decommission_date) == "2026-09-02"
    assert row.decommissioned_by
    audit = db.execute(sqltext(
        "SELECT count(*) FROM audit_log WHERE event_type = 'item_decommissioned' "
        "AND target_table = 'items' AND target_id = :i"), {"i": item_id}).scalar()
    assert audit == 1


def test_decommission_twice_is_refused(editor_client, dec_item):
    _decommission(editor_client, dec_item)
    r = editor_client.post(f"/items/{dec_item}/decommission",
                           data={"reason": "again", "decommission_date": "2026-09-02"})
    assert r.status_code == 409


# -- Reactivation -----------------------------------------------------------

def test_reactivate_requires_editor_tier(editor_client, viewer_client, dec_item):
    _decommission(editor_client, dec_item)
    r = viewer_client.post(f"/items/{dec_item}/reactivate", data={"reason": "x"})
    assert r.status_code == 403


def test_reactivate_requires_reason(editor_client, dec_item):
    _decommission(editor_client, dec_item)
    r = editor_client.post(f"/items/{dec_item}/reactivate", data={"reason": ""})
    assert r.status_code == 400


def test_reactivate_refused_when_not_decommissioned(editor_client, dec_item):
    r = editor_client.post(f"/items/{dec_item}/reactivate", data={"reason": "x"})
    assert r.status_code == 409


def test_reactivate_returns_item_to_pending(editor_client, db, dec_item):
    _decommission(editor_client, dec_item)
    r = editor_client.post(f"/items/{dec_item}/reactivate",
                           data={"reason": "still good"})
    assert r.status_code == 200, r.text
    row = db.execute(sqltext(
        "SELECT item_status, decommission_reason, decommission_date, decommissioned_by "
        "FROM item_schema.items WHERE id = :i"), {"i": dec_item}).first()
    assert row.item_status == "Pending"
    assert row.decommission_reason is None
    assert row.decommission_date is None
    assert row.decommissioned_by is None
    audit = db.execute(sqltext(
        "SELECT count(*) FROM audit_log WHERE event_type = 'item_reactivated' "
        "AND target_table = 'items' AND target_id = :i"), {"i": dec_item}).scalar()
    assert audit == 1


# -- Code-mediated status at the hand-edit surfaces -------------------------

def test_edit_cannot_set_decommissioned(editor_client, db, dec_item):
    r = editor_client.post(f"/items/{dec_item}", data={
        "item_name": "CONTRACT-TEST Dec Item",
        "item_sn": "CONTRACT-TEST-DEC-1",
        "item_category": "camera_c2c",
        "item_status": "Decommissioned",
    })
    assert r.status_code == 303
    assert _status_of(db, dec_item) == "Unassigned"


def test_edit_cannot_clear_decommissioned(editor_client, db, dec_item):
    _decommission(editor_client, dec_item)
    r = editor_client.post(f"/items/{dec_item}", data={
        "item_name": "CONTRACT-TEST Dec Item",
        "item_sn": "CONTRACT-TEST-DEC-1",
        "item_category": "camera_c2c",
        "item_status": "Pending",
    })
    assert r.status_code == 303
    assert _status_of(db, dec_item) == "Decommissioned"


def test_bulk_cannot_set_decommissioned(editor_client, dec_item):
    r = editor_client.post("/inventory/bulk", data={
        "action": "status", "value": "Decommissioned",
        "item_ids": [str(dec_item)],
    })
    assert r.status_code == 400


def test_dropdowns_exclude_decommissioned(editor_client, dec_item):
    """The build-note reachability check: the option arrives through a loop
    variable, so the RENDERED pages are asserted, not the template source."""
    intake_html = editor_client.get("/intake").text
    assert '<option value="Decommissioned"' not in intake_html
    detail_html = editor_client.get(f"/items/{dec_item}?edit=1").text
    assert '<option value="Decommissioned"' not in detail_html
    triage_html = editor_client.get("/triage/").text
    trg_lines = [l for l in triage_html.splitlines() if "TRG_STATUSES" in l]
    assert trg_lines and "Decommissioned" not in trg_lines[0]


# -- Visibility -------------------------------------------------------------

def test_hidden_from_inventory_until_included(editor_client, dec_item):
    # Assert on the item NAME: the page echoes the q= term (tile links,
    # pagination), so the serial appears even when the row is hidden.
    _decommission(editor_client, dec_item)
    plain = editor_client.get("/inventory/?q=CONTRACT-TEST-DEC-1").text
    assert "CONTRACT-TEST Dec Item" not in plain
    included = editor_client.get(
        "/inventory/?q=CONTRACT-TEST-DEC-1&include_decommissioned=1").text
    assert "CONTRACT-TEST Dec Item" in included
    filtered = editor_client.get(
        "/inventory/?q=CONTRACT-TEST-DEC-1&status=Decommissioned").text
    assert "CONTRACT-TEST Dec Item" in filtered


def test_hidden_from_search_until_included(editor_client, dec_item):
    # Same echo problem: the no-results message quotes the search term.
    _decommission(editor_client, dec_item)
    plain = editor_client.get("/search/results?q=CONTRACT-TEST-DEC-1").text
    assert "CONTRACT-TEST Dec Item" not in plain
    included = editor_client.get(
        "/search/results?q=CONTRACT-TEST-DEC-1&include_decommissioned=1").text
    assert "CONTRACT-TEST Dec Item" in included


def test_decommissioned_view_lists_item(editor_client, dec_item):
    _decommission(editor_client, dec_item, reason="dropped in transit")
    html = editor_client.get("/inventory/decommissioned").text
    assert "CONTRACT-TEST-DEC-1" in html
    assert "dropped in transit" in html


# -- Escape paths closed by the review pass ---------------------------------

def test_edit_whitespace_cannot_set_decommissioned(editor_client, db, dec_item):
    # The guard compares the CLEANED value; padded input must not slip past.
    r = editor_client.post(f"/items/{dec_item}", data={
        "item_name": "CONTRACT-TEST Dec Item",
        "item_sn": "CONTRACT-TEST-DEC-1",
        "item_category": "camera_c2c",
        "item_status": " Decommissioned ",
    })
    assert r.status_code == 303
    assert _status_of(db, dec_item) == "Unassigned"


def test_checkout_refuses_decommissioned(editor_client, db, dec_item):
    _decommission(editor_client, dec_item)
    r = editor_client.post("/checkout", data={
        "item_id": str(dec_item),
        "checked_out_to_name": "CONTRACT-TEST Person",
    })
    assert r.status_code == 303
    assert "decommissioned" in r.headers.get("location", "").lower()
    assert _status_of(db, dec_item) == "Decommissioned"
    rows = db.execute(sqltext(
        "SELECT count(*) FROM item_schema.checkouts WHERE item_id = :i"),
        {"i": dec_item}).scalar()
    assert rows == 0


def test_decommission_refused_while_checked_out(editor_client, db, dec_item):
    db.execute(sqltext(
        "UPDATE item_schema.items SET item_status = 'Checked Out' WHERE id = :i"),
        {"i": dec_item})
    db.commit()
    r = editor_client.post(f"/items/{dec_item}/decommission",
                           data={"reason": "x", "decommission_date": "2026-09-02"})
    assert r.status_code == 409
    assert _status_of(db, dec_item) == "Checked Out"


@pytest.fixture
def dec_component_pair(db):
    parent_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Dec Parent', 'CONTRACT-TEST-DEC-P', 'edge_box', "
        "'Unassigned') RETURNING id")).scalar()
    comp_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Dec Comp', 'CONTRACT-TEST-DEC-C', 'gpu', "
        "'Unassigned') RETURNING id")).scalar()
    db.commit()
    yield {"parent_id": parent_id, "comp_id": comp_id}
    for iid in (comp_id, parent_id):
        _cleanup_item(db, iid)


def test_containment_install_refuses_decommissioned(editor_client, db, dec_component_pair):
    comp_id = dec_component_pair["comp_id"]
    _decommission(editor_client, comp_id)
    r = editor_client.post("/api/containment/install", json={
        "parent_item_id": dec_component_pair["parent_id"],
        "component_item_id": comp_id,
    })
    assert r.status_code == 409
    assert "decommissioned" in r.json()["error"].lower()
    assert _status_of(db, comp_id) == "Decommissioned"
