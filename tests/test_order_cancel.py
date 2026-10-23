"""Contract tests for the customer order cancel path.

Owner spec: docs/specs/customer-order-cancel.md. Covers the action guards
(provisioning-manager tier, required reason, already-cancelled refusal),
the hard-unlink of provisioned units, the order_cancelled audit event and
its captured unit list, the code-mediation of the status (a status edit
can neither set nor clear cancelled), and the two board surfaces: the
status modal omits cancelled, and the archived badge counts it.

All rows are CONTRACT-TEST-prefixed and removed by the fixtures.
"""

import re

import pytest
from sqlalchemy import text as sqltext


def _mk_order(client, name):
    r = client.post("/api/orders/", json={
        "customer_name": name,
        "order_type": "pilot",
        "expected_return": "2026-10-15",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def cancel_order(admin_client, db):
    """One pilot order carrying two provisioned units.

    Unit A links an item, unit B has none (item_id NULL), so the captured
    unit list exercises both shapes. The legacy device_table/device_id pair
    dropped in migration 083 (legacy slice S5).
    """
    order_id = _mk_order(admin_client, "CONTRACT-TEST Cancel Corp")

    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Cancel Cam', 'CONTRACT-TEST-CXL-1', 'camera_c2c', "
        "'Ready to Deploy') RETURNING id")).scalar()
    prov_item = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(item_id, customer_order_id, current_stage, stages) "
        "VALUES (:i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"i": item_id, "o": order_id}).scalar()
    prov_legacy = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(customer_order_id, current_stage, stages) "
        "VALUES (:o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"o": order_id}).scalar()
    db.commit()

    yield {
        "order_id": order_id,
        "item_id": item_id,
        "prov_item": prov_item,
        "prov_legacy": prov_legacy,
    }

    db.execute(sqltext("DELETE FROM device_provisioning WHERE id IN (:a, :b)"),
               {"a": prov_item, "b": prov_legacy})
    db.execute(sqltext(
        "DELETE FROM audit_log WHERE target_table = 'customer_orders' AND target_id = :o"),
        {"o": order_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.commit()


def _status_of(db, order_id):
    return db.execute(sqltext(
        "SELECT status FROM customer_orders WHERE id = :o"), {"o": order_id}).scalar()


def _cancel(client, order_id, reason="pilot returned, customer declined"):
    return client.post(f"/api/orders/{order_id}/cancel", json={"reason": reason})


# -- Guards -----------------------------------------------------------------

def test_cancel_requires_provisioning_manager(viewer_client, db, cancel_order):
    r = _cancel(viewer_client, cancel_order["order_id"])
    assert r.status_code == 403
    assert _status_of(db, cancel_order["order_id"]) != "cancelled"


def test_cancel_requires_a_reason(admin_client, db, cancel_order):
    r = admin_client.post(f"/api/orders/{cancel_order['order_id']}/cancel",
                          json={"reason": "   "})
    assert r.status_code == 400
    assert "reason" in r.json()["error"].lower()
    assert _status_of(db, cancel_order["order_id"]) != "cancelled"


def test_cancel_unknown_order_is_404(admin_client):
    r = _cancel(admin_client, 99999999)
    assert r.status_code == 404


def test_cancel_twice_is_refused(admin_client, cancel_order):
    assert _cancel(admin_client, cancel_order["order_id"]).status_code == 200
    r = _cancel(admin_client, cancel_order["order_id"])
    assert r.status_code == 409
    assert "already cancelled" in r.json()["error"].lower()


# -- Effects ----------------------------------------------------------------

def test_cancel_unlinks_units_and_keeps_the_rows(admin_client, db, cancel_order):
    r = _cancel(admin_client, cancel_order["order_id"])
    assert r.status_code == 200, r.text
    assert r.json()["units_unlinked"] == 2

    assert _status_of(db, cancel_order["order_id"]) == "cancelled"

    # Rows survive; only the tie is cut. Found by customer_order_id, so a
    # legacy-path row (item_id NULL) must be unlinked too.
    still_linked = db.execute(sqltext(
        "SELECT count(*) FROM device_provisioning WHERE customer_order_id = :o"),
        {"o": cancel_order["order_id"]}).scalar()
    assert still_linked == 0
    surviving = db.execute(sqltext(
        "SELECT count(*) FROM device_provisioning WHERE id IN (:a, :b)"),
        {"a": cancel_order["prov_item"], "b": cancel_order["prov_legacy"]}).scalar()
    assert surviving == 2


def test_cancel_audit_event_captures_the_unit_list(admin_client, db, cancel_order):
    _cancel(admin_client, cancel_order["order_id"], reason="CONTRACT-TEST reason text")

    nv = db.execute(sqltext(
        "SELECT new_values FROM audit_log WHERE event_type = 'order_cancelled' "
        "AND target_table = 'customer_orders' AND target_id = :o "
        "ORDER BY id DESC LIMIT 1"), {"o": cancel_order["order_id"]}).scalar()
    assert nv, "no order_cancelled audit row"
    assert nv["reason"] == "CONTRACT-TEST reason text"
    assert nv["who"]
    assert nv["prior_status"] == "new"

    # The audit entry is the ONLY place the tie survives, so it must carry
    # both unit shapes.
    prov_ids = sorted(u["provisioning_id"] for u in nv["units"])
    assert prov_ids == sorted([cancel_order["prov_item"], cancel_order["prov_legacy"]])
    by_id = {u["provisioning_id"]: u for u in nv["units"]}
    assert by_id[cancel_order["prov_item"]]["item_id"] == cancel_order["item_id"]
    assert by_id[cancel_order["prov_legacy"]]["item_id"] is None
    assert "device_table" not in by_id[cancel_order["prov_legacy"]]


# -- Cancelled is code-mediated --------------------------------------------

def test_status_edit_cannot_set_cancelled(admin_client, db, cancel_order):
    r = admin_client.put(f"/api/orders/{cancel_order['order_id']}",
                         json={"status": "cancelled"})
    assert r.status_code == 400
    assert "cancel action" in r.json()["error"].lower()
    assert _status_of(db, cancel_order["order_id"]) != "cancelled"
    # The bypass would have skipped the unlink entirely.
    still_linked = db.execute(sqltext(
        "SELECT count(*) FROM device_provisioning WHERE customer_order_id = :o"),
        {"o": cancel_order["order_id"]}).scalar()
    assert still_linked == 2


def test_status_edit_cannot_reopen_a_cancelled_order(admin_client, db, cancel_order):
    assert _cancel(admin_client, cancel_order["order_id"]).status_code == 200
    r = admin_client.put(f"/api/orders/{cancel_order['order_id']}",
                         json={"status": "building"})
    assert r.status_code == 409
    assert "terminal" in r.json()["error"].lower()
    assert _status_of(db, cancel_order["order_id"]) == "cancelled"


def test_create_cannot_start_an_order_cancelled(admin_client, db):
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Cancel OnCreate",
        "order_type": "pilot",
        "status": "cancelled",
    })
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    try:
        assert _status_of(db, oid) == "new"
    finally:
        db.execute(sqltext(
            "DELETE FROM audit_log WHERE target_table = 'customer_orders' AND target_id = :o"),
            {"o": oid})
        db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": oid})
        db.commit()


# -- Surfaces ---------------------------------------------------------------

def test_status_select_omits_cancelled(admin_client, cancel_order):
    """Reachability, not existence: the option arrives through a loop over the
    track's status labels, so the RENDERED page is asserted rather than the
    source. The status select lives in the Edit Order form; moving an order
    forward is the advance button (docs/specs/one-board-two-tracks.md).

    Scoped to the order status select on purpose. The OEM purchase order
    modal on this same page legitimately offers a cancelled option -- OEM
    POs carry their own cancelled status and are out of scope here -- so a
    page-wide assertion would fail on a correct build.
    """
    html = admin_client.get(f"/orders/{cancel_order['order_id']}").text
    m = re.search(r'<select id="edit-status".*?</select>', html, re.S)
    assert m, "order status select not found on the page"
    block = m.group(0)
    assert '<option value="cancelled"' not in block
    assert '<option value="building"' in block
    assert '<option value="cancelled"' in html, (
        "expected the OEM PO select to still offer cancelled; if this fails "
        "the scoping above is no longer needed")


def test_detail_page_shows_the_cancel_reason(admin_client, cancel_order):
    _cancel(admin_client, cancel_order["order_id"], reason="CONTRACT-TEST banner reason")
    html = admin_client.get(f"/orders/{cancel_order['order_id']}").text
    assert "CONTRACT-TEST banner reason" in html
    assert 'id="cancel-banner"' in html
    # The Cancel action is gone once the order is cancelled: it is terminal.
    assert 'id="cancel-order-btn"' not in html


def test_cancelled_order_leaves_the_active_board(admin_client, cancel_order):
    """Discriminating observable: the order is ON the board while active and
    GONE once cancelled, because cancelled is an archived status.

    This is the regression guard for the board query and STATUS_COLUMN: a
    cancelled order must disappear rather than fall into a first column.
    """
    before = admin_client.get("/fulfillment/").text
    assert "CONTRACT-TEST Cancel Corp" in before
    assert _cancel(admin_client, cancel_order["order_id"]).status_code == 200
    after = admin_client.get("/fulfillment/").text
    assert "CONTRACT-TEST Cancel Corp" not in after


def test_cancelled_is_off_both_tracks():
    """The drift guard. The board places orders through STATUS_COLUMN
    (app/order_tracks.py); cancelled must map to no column on either track,
    and every other status must map to one (test_order_tracks checks totality)."""
    from app.models import CustomerOrder
    from app.order_tracks import STATUS_COLUMN

    for track, mapping in STATUS_COLUMN.items():
        assert mapping["cancelled"] is None, track
        assert all(mapping[s] for s in CustomerOrder.ORDER_STATUSES if s != "cancelled"), track
    # STATUS_COLORS is the third hand-maintained site; a missing key renders a
    # muted grey badge rather than failing, so assert the pairing explicitly.
    assert sorted(CustomerOrder.STATUS_COLORS) == sorted(CustomerOrder.ORDER_STATUSES)


def test_cancelled_order_is_not_offered_for_provisioning(admin_client, cancel_order):
    """The provisioning create modal lists open orders. A cancelled order is
    ended, so it must drop out of that picker; present before, gone after."""
    before = admin_client.get("/provisioning/queue").text
    assert "CONTRACT-TEST Cancel Corp" in before
    assert _cancel(admin_client, cancel_order["order_id"]).status_code == 200
    after = admin_client.get("/provisioning/queue").text
    assert "CONTRACT-TEST Cancel Corp" not in after


# -- Terminal-order controls ------------------------------------------------

def test_delete_refuses_a_cancelled_order(admin_client, db, cancel_order):
    """Cancelled orders are retained as the historical record.

    Discriminating on purpose: this order has ZERO deployment records, so the
    pre-existing deployment guard cannot fire and the 409 can only come from
    the cancelled guard. The error text is the observable that tells them
    apart -- a test against an order carrying deployment records would pass
    whether or not the cancelled guard exists.
    """
    order_id = cancel_order["order_id"]
    assert _cancel(admin_client, order_id).status_code == 200

    records = db.execute(sqltext(
        "SELECT count(*) FROM deployment_records WHERE customer_order_id = :o"),
        {"o": order_id}).scalar()
    assert records == 0, "fixture must carry no deployment records to discriminate"

    r = admin_client.delete(f"/api/orders/{order_id}")
    assert r.status_code == 409
    err = r.json()["error"].lower()
    assert "cancelled" in err and "historical record" in err
    assert "deployment record" not in err, (
        "this 409 came from the deployment guard, so the test proves nothing")

    assert _status_of(db, order_id) == "cancelled", "the order must survive"


def test_edit_status_select_omits_cancelled(admin_client, cancel_order):
    """The edit modal status select loops ORDER_STATUSES, so the eighth member
    propagated into it automatically. Offering it there posts a value the PUT
    route refuses, which made Edit Order dead on every cancelled order."""
    html = admin_client.get(f"/orders/{cancel_order['order_id']}").text
    m = re.search(r'<select id="edit-status".*?</select>', html, re.S)
    assert m, "edit status select not found on an active order"
    assert '<option value="cancelled"' not in m.group(0)
    assert '<option value="building"' in m.group(0)
    # The OEM PO select keeps its own cancelled option: a different vocabulary.
    assert '<option value="cancelled"' in html


def test_active_order_offers_edit_status_and_delete(admin_client, cancel_order):
    """The other half of the pair below: these controls must be present while
    the order is live, or the absence assertions prove nothing."""
    html = admin_client.get(f"/orders/{cancel_order['order_id']}").text
    assert 'onclick="openEditModal()"' in html
    assert 'id="advance-btn"' in html
    assert 'onclick="deleteOrder()"' in html
    assert 'id="edit-order-modal"' in html
    assert 'id="cancel-order-btn"' in html


def test_cancelled_order_hides_edit_status_and_delete(admin_client, cancel_order):
    """A cancelled order is terminal: every control that the server refuses is
    absent from the DOM entirely, not merely hidden."""
    assert _cancel(admin_client, cancel_order["order_id"]).status_code == 200
    html = admin_client.get(f"/orders/{cancel_order['order_id']}").text

    assert 'id="cancel-banner"' in html, "page did not render as cancelled"
    assert 'onclick="openEditModal()"' not in html
    assert 'id="advance-btn"' not in html
    assert 'onclick="deleteOrder()"' not in html
    assert 'id="edit-order-modal"' not in html
    assert 'id="cancel-order-btn"' not in html
