"""H16 starter-reconciliation contract tests: free-text PO matching,
expected-quantity prefill, OEM line increments and status auto-advance.
(The H17 check-off tests extend this file.) CONTRACT-TEST data throughout.
"""

import pytest
from sqlalchemy import text as sqltext


@pytest.fixture
def oem_po(db):
    """One PO number spanning two SKU line rows (per-SKU line-item shape)."""
    ids = []
    for sku, qty in (("PVA-100-30NR", 2), ("EDGE-2000", 1)):
        ids.append(db.execute(sqltext(
            "INSERT INTO oem_purchase_orders (vendor_name, po_number, sku, qty_ordered, "
            "qty_received, status) VALUES ('CONTRACT-TEST OEM', 'CT H16 PO 1', :s, :q, 0, 'ordered') "
            "RETURNING id"), {"s": sku, "q": qty}).scalar())
    db.commit()
    yield ids
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM item_schema.receipt_items WHERE item_id IN "
        "(SELECT id FROM item_schema.items WHERE item_sn LIKE 'CONTRACT-TEST-H16%')"))
    db.execute(sqltext("DELETE FROM item_schema.items WHERE item_sn LIKE 'CONTRACT-TEST-H16%'"))
    db.execute(sqltext("DELETE FROM receiving_events WHERE vendor LIKE 'CONTRACT-TEST-H16%'"))
    db.execute(sqltext("DELETE FROM oem_purchase_orders WHERE id = ANY(:i)"), {"i": ids})
    db.commit()


def _oem(db, row_id):
    db.commit()
    return db.execute(sqltext(
        "SELECT qty_received, status, received_date FROM oem_purchase_orders WHERE id = :i"),
        {"i": row_id}).fetchone()


def test_event_create_matches_po_and_prefills_expected(admin_client, oem_po):
    r = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "  ct h16 po 1 "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["po_matched"] is True
    assert body["expected_quantity"] == 3, "prefill = outstanding qty across both lines"
    assert sorted(l["sku"] for l in body["po_lines"]) == ["EDGE-2000", "PVA-100-30NR"]

    got = admin_client.get(f"/api/receive/events/{body['event_id']}").json()
    assert got["po_matched"] is True and len(got["po_lines"]) == 2


def test_event_create_unmatched_po_stays_free_text(admin_client, oem_po):
    r = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT-NO-SUCH-PO"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["po_matched"] is False and body["po_lines"] == []
    assert body["expected_quantity"] is None
    assert body["purchase_order"] == "CT-NO-SUCH-PO"


def test_direct_intake_ticks_oem_line_and_advances_status(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1"}).json()["event_id"]

    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H16-U1", "target_table": "edge_boxes",
        "part_number": "PVA-100-30NR",
        "direct_to_inventory": True, "receiving_event_id": ev})
    assert r.status_code == 200, r.text
    got = _oem(db, oem_po[0])
    assert got[0] == 1 and got[1] == "receiving", got

    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H16-U2", "target_table": "edge_boxes",
        "part_number": "pva-100-30nr",   # sku match is case-insensitive
        "direct_to_inventory": True, "receiving_event_id": ev})
    assert r.status_code == 200, r.text
    got = _oem(db, oem_po[0])
    assert got[0] == 2 and got[1] == "verified", got
    assert got[2] is not None, "verified line stamps received_date"

    # the other line is untouched
    other = _oem(db, oem_po[1])
    assert other[0] == 0 and other[1] == "ordered"


def test_intake_with_unknown_sku_never_blocks(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1"}).json()["event_id"]
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H16-U3", "target_table": "edge_boxes",
        "part_number": "NOT-ON-THE-PO",
        "direct_to_inventory": True, "receiving_event_id": ev})
    assert r.status_code == 200, r.text
    assert _oem(db, oem_po[0])[0] == 0 and _oem(db, oem_po[1])[0] == 0
