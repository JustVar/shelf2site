"""H15 event-lifecycle contract tests: close endpoint, auto-complete, and
submit-time counting for the pending path (approve never double-counts,
dismiss gives the count back). CONTRACT-TEST data, cleaned by fixtures.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def cleanup_events(db):
    yield
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM item_schema.receipt_items WHERE item_id IN "
        "(SELECT id FROM item_schema.items WHERE item_sn LIKE 'CONTRACT-TEST-H15%')"))
    db.execute(sqltext(
        "DELETE FROM item_schema.receipts WHERE purchase_order LIKE 'CT-H15%' "
        "AND id NOT IN (SELECT receipt_id FROM item_schema.receipt_items)"))
    db.execute(sqltext("DELETE FROM item_schema.items WHERE item_sn LIKE 'CONTRACT-TEST-H15%'"))
    db.execute(sqltext("DELETE FROM pending_devices WHERE serial LIKE 'CONTRACT-TEST-H15%'"))
    db.execute(sqltext("DELETE FROM receiving_events WHERE vendor LIKE 'CONTRACT-TEST-H15%'"))
    db.commit()


def _mk_event(client, expected):
    r = client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H15", "purchase_order": "CT-H15-PO",
        "expected_quantity": expected})
    assert r.status_code == 200, r.text
    return r.json()["event_id"]


def _event(db, event_id):
    db.commit()
    return db.execute(sqltext(
        "SELECT received_quantity, status FROM receiving_events WHERE id = :i"),
        {"i": event_id}).fetchone()


def test_close_partial_and_idempotent(admin_client, db, cleanup_events):
    ev = _mk_event(admin_client, 3)
    r = admin_client.post(f"/api/receive/events/{ev}/close")
    assert r.status_code == 200 and r.json()["status"] == "partial"
    again = admin_client.post(f"/api/receive/events/{ev}/close")
    assert again.status_code == 200 and again.json()["already_closed"] is True


def test_direct_intake_autocompletes_at_expected(admin_client, db, cleanup_events):
    ev = _mk_event(admin_client, 1)
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H15-D1", "target_table": "gpus",
        "direct_to_inventory": True, "receiving_event_id": ev})
    assert r.status_code == 200, r.text
    got = _event(db, ev)
    assert got[0] == 1 and got[1] == "complete"


def test_pending_path_counts_at_submit_not_approve(admin_client, db, cleanup_events):
    ev = _mk_event(admin_client, 2)
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H15-P1", "target_table": "cameras",
        "direct_to_inventory": False, "receiving_event_id": ev})
    assert r.status_code == 200 and r.json()["status"] == "pending_review", r.text
    pending_id = r.json()["pending_id"]
    assert _event(db, ev)[0] == 1, "pending submit must count"

    # approving must NOT count again
    r = admin_client.post(f"/api/pending/{pending_id}/approve",
                          json={"target_table": "cameras"})
    assert r.status_code in (200, 303), r.text
    assert _event(db, ev)[0] == 1, "approve must not double-count"


def test_dismiss_gives_the_count_back(admin_client, db, cleanup_events):
    ev = _mk_event(admin_client, 1)
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H15-P2", "target_table": "cameras",
        "direct_to_inventory": False, "receiving_event_id": ev})
    pending_id = r.json()["pending_id"]
    got = _event(db, ev)
    assert got[0] == 1 and got[1] == "complete", "expected auto-complete at 1/1"

    r = admin_client.post(f"/api/pending/{pending_id}/dismiss", json={"reason": "scan mistake"})
    assert r.status_code in (200, 303), r.text
    got = _event(db, ev)
    assert got[0] == 0, "dismiss must decrement"
    assert got[1] == "open", "count-based auto-complete must reopen"
