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

    Unit A resolves through the item path (item_id set), unit B through the
    legacy path (item_id NULL, device_table naming a per-category table), so
    the captured unit list exercises both shapes.
    """
    order_id = _mk_order(admin_client, "CONTRACT-TEST Cancel Corp")

    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Cancel Cam', 'CONTRACT-TEST-CXL-1', 'camera_c2c', "
        "'Ready to Deploy') RETURNING id")).scalar()
    prov_item = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(device_table, device_id, item_id, customer_order_id, current_stage, stages) "
        "VALUES ('items', :i, :i, :o, 'acquired', '[]'::jsonb) RETURNING id"),
        {"i": item_id, "o": order_id}).scalar()
    prov_legacy = db.execute(sqltext(
        "INSERT INTO device_provisioning "
        "(device_table, device_id, customer_order_id, current_stage, stages) "
        "VALUES ('edge_boxes', 424242, :o, 'acquired', '[]'::jsonb) RETURNING id"),
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
    assert by_id[cancel_order["prov_legacy"]]["device_table"] == "edge_boxes"


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

def test_status_modal_omits_cancelled(admin_client, cancel_order):
    """Reachability, not existence: the option arrives through a loop over
    ORDER_STATUSES, so the RENDERED page is asserted rather than the source.

    Scoped to the order status select on purpose. The OEM purchase order
    modal on this same page legitimately offers a cancelled option -- OEM
    POs carry their own cancelled status and are out of scope here -- so a
    page-wide assertion would fail on a correct build.
    """
    html = admin_client.get(f"/orders/{cancel_order['order_id']}").text
    m = re.search(r'<select id="status-select".*?</select>', html, re.S)
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

    This is the regression guard for the columns dict. If cancelled were
    missing from ACTIVE_STATUSES + ARCHIVED_STATUSES, the fallback in
    fulfillment.py would assign it to "new" and the cancelled order would
    render in the New column instead of disappearing.
    """
    before = admin_client.get("/fulfillment/").text
    assert "CONTRACT-TEST Cancel Corp" in before
    assert _cancel(admin_client, cancel_order["order_id"]).status_code == 200
    after = admin_client.get("/fulfillment/").text
    assert "CONTRACT-TEST Cancel Corp" not in after


def test_active_statuses_derive_from_the_vocabulary():
    """The drift guard. ARCHIVED is hand-held; ACTIVE derives from it, so the
    union always covers ORDER_STATUSES and no status can fall through."""
    from app.models import CustomerOrder
    from app.routes.fulfillment import ACTIVE_STATUSES, ARCHIVED_STATUSES

    assert "cancelled" in ARCHIVED_STATUSES
    assert "cancelled" not in ACTIVE_STATUSES
    assert ACTIVE_STATUSES == [s for s in CustomerOrder.ORDER_STATUSES
                               if s not in ARCHIVED_STATUSES]
    assert set(ACTIVE_STATUSES) | set(ARCHIVED_STATUSES) >= set(CustomerOrder.ORDER_STATUSES)
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
