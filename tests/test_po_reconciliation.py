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
    db.execute(sqltext(
        "DELETE FROM item_schema.receipts WHERE purchase_order LIKE 'CT H16%' "
        "AND id NOT IN (SELECT receipt_id FROM item_schema.receipt_items)"))
    db.execute(sqltext("DELETE FROM item_schema.items WHERE item_sn LIKE 'CONTRACT-TEST-H16%'"))
    db.execute(sqltext("DELETE FROM pending_devices WHERE serial LIKE 'CONTRACT-TEST-H16%'"))
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


# ── H17: event lines, received_devices, check-off, tracking auto-select ─────

def test_event_create_snapshots_po_lines(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1",
        "tracking_number": "1Z999AA10100000001"}).json()["event_id"]
    got = admin_client.get(f"/api/receive/events/{ev}").json()
    assert got["tracking_number"] == "1Z999AA10100000001"
    lines = {l["sku"]: l for l in got["lines"]}
    assert lines["PVA-100-30NR"]["qty_expected"] == 2
    assert lines["EDGE-2000"]["qty_expected"] == 1
    assert all(l["state"] == "open" for l in got["lines"])


def test_intake_checks_off_lines_and_links_received_devices(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1"}).json()["event_id"]

    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H16-L1", "target_table": "edge_boxes",
        "part_number": "PVA-100-30NR",
        "direct_to_inventory": True, "receiving_event_id": ev})
    assert r.status_code == 200, r.text
    item_id = r.json()["device_id"]

    got = admin_client.get(f"/api/receive/events/{ev}").json()
    line = next(l for l in got["lines"] if l["sku"] == "PVA-100-30NR")
    assert line["qty_received"] == 1 and line["state"] == "open"

    db.commit()
    rd = db.execute(sqltext(
        "SELECT item_id, sku, line_id FROM received_devices WHERE receiving_event_id = :e"),
        {"e": ev}).fetchone()
    assert rd is not None and rd[0] == item_id and rd[1] == "PVA-100-30NR" and rd[2] is not None


def test_pending_intake_syncs_and_dismiss_gives_everything_back(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1"}).json()["event_id"]
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H16-L2", "target_table": "edge_boxes",
        "part_number": "EDGE-2000",
        "direct_to_inventory": False, "receiving_event_id": ev})
    assert r.status_code == 200 and r.json()["status"] == "pending_review", r.text
    pending_id = r.json()["pending_id"]

    got = admin_client.get(f"/api/receive/events/{ev}").json()
    line = next(l for l in got["lines"] if l["sku"] == "EDGE-2000")
    assert line["qty_received"] == 1 and line["state"] == "full"
    assert _oem(db, oem_po[1])[0] == 1, "pending intake ticks the OEM line too"

    r = admin_client.post(f"/api/pending/{pending_id}/dismiss", json={"reason": "mistake"})
    assert r.status_code in (200, 303), r.text
    got = admin_client.get(f"/api/receive/events/{ev}").json()
    line = next(l for l in got["lines"] if l["sku"] == "EDGE-2000")
    assert line["qty_received"] == 0
    assert _oem(db, oem_po[1])[0] == 0, "dismiss reverses the OEM tick"
    db.commit()
    assert db.execute(sqltext(
        "SELECT count(*) FROM received_devices WHERE pending_device_id = :p"),
        {"p": pending_id}).scalar() == 0


def test_lines_autocomplete_and_short_close(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1"}).json()["event_id"]
    # fill only the EDGE-2000 line (1 of 1); PVA line stays 0 of 2
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-H16-L3", "target_table": "edge_boxes",
        "part_number": "EDGE-2000",
        "direct_to_inventory": True, "receiving_event_id": ev})
    assert r.status_code == 200, r.text
    got = admin_client.get(f"/api/receive/events/{ev}").json()
    assert got["status"] == "open", "one short line must hold auto-complete back"

    closed = admin_client.post(f"/api/receive/events/{ev}/close").json()
    assert closed["status"] == "partial"
    states = {l["sku"]: l["state"] for l in closed["lines"]}
    assert states["PVA-100-30NR"] == "short" and states["EDGE-2000"] == "full"


def test_over_receipt_flags_over(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1"}).json()["event_id"]
    for i in (1, 2):
        r = admin_client.post("/api/receive/device", json={
            "serial": f"CONTRACT-TEST-H16-O{i}", "target_table": "edge_boxes",
            "part_number": "EDGE-2000",
            "direct_to_inventory": True, "receiving_event_id": ev})
        assert r.status_code == 200, r.text
    got = admin_client.get(f"/api/receive/events/{ev}").json()
    line = next(l for l in got["lines"] if l["sku"] == "EDGE-2000")
    assert line["qty_received"] == 2 and line["state"] == "over"


def test_tracking_scan_selects_the_event(admin_client, db, oem_po):
    ev = admin_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-H16", "purchase_order": "CT H16 PO 1",
        "tracking_number": "1Z999AA10100000077"}).json()["event_id"]
    r = admin_client.post("/api/receive/scan", json={"barcode": "1z999aa10100000077"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event_id"] == ev
    assert "event selected" in body["guidance"]
