"""Contract tests for the two fulfillment tracks (docs/specs/one-board-two-tracks.md):
the status-to-column map, the advance route, vendor documents, and the gaps
closed on the way (ship on a cancelled order, OEM PO status). Rows are
CONTRACT-TEST-prefixed and removed here.
"""
import uuid

import pytest
from sqlalchemy import text as sqltext

from app.models import CustomerOrder
from app.order_tracks import COLUMNS, NEXT_STEP, STATUS_COLUMN, STOCK, VENDOR


# ── the map is total ────────────────────────────────────────────────────────

@pytest.mark.parametrize("track", [VENDOR, STOCK])
def test_every_stored_status_has_a_place_on_each_track(track):
    assert set(STATUS_COLUMN[track]) == set(CustomerOrder.ORDER_STATUSES)
    keys = {k for k, _ in COLUMNS[track]}
    assert {c for c in STATUS_COLUMN[track].values() if c} <= keys
    for frm, to in NEXT_STEP[track].items():
        assert frm in keys and to in keys


# ── fixtures ────────────────────────────────────────────────────────────────

def _cleanup(db, order_ids, item_ids=()):
    db.rollback()
    for oid in order_ids:
        db.execute(sqltext("DELETE FROM device_provisioning WHERE customer_order_id = :o"), {"o": oid})
        db.execute(sqltext("DELETE FROM order_documents WHERE customer_order_id = :o"), {"o": oid})
        db.execute(sqltext("DELETE FROM audit_log WHERE target_table = 'customer_orders' AND target_id = :o"),
                   {"o": oid})
        db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": oid})
    for iid in item_ids:
        db.execute(sqltext("DELETE FROM device_provisioning WHERE item_id = :i"), {"i": iid})
        db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": iid})
    db.commit()


@pytest.fixture
def vendor_order(admin_client, db):
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Vendor Corp", "order_type": "sale",
        "po_number": "CONTRACT-TEST-PO-" + uuid.uuid4().hex[:8], "due_date": "2026-12-01",
    })
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    yield oid
    _cleanup(db, [oid])


@pytest.fixture
def pilot_order(admin_client, db):
    r = admin_client.post("/api/orders/", json={
        "customer_name": "CONTRACT-TEST Pilot Corp", "order_type": "pilot",
        "expected_return": "2026-12-15",
    })
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    iid = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Track Box', 'CONTRACT-TEST-TRACK-1', 'edge_box', 'Ready to Deploy') "
        "RETURNING id")).scalar()
    db.commit()
    yield {"order_id": oid, "item_id": iid}
    _cleanup(db, [oid], [iid])


def _order(db, oid):
    db.commit()
    return db.execute(sqltext(
        "SELECT status, shipped_date IS NOT NULL, delivered_date IS NOT NULL "
        "FROM customer_orders WHERE id = :o"), {"o": oid}).one()


def _go(client, oid, to):
    return client.post(f"/api/orders/{oid}/advance", json={"to": to})


# ── vendor track ────────────────────────────────────────────────────────────

def test_vendor_order_walks_ordered_building_shipped_installed(admin_client, db, vendor_order):
    oid = vendor_order
    assert _go(admin_client, oid, "shipped").status_code == 409      # skips Building
    r = _go(admin_client, oid, "building")
    assert r.status_code == 200 and r.json()["label"] == "Building"
    assert _order(db, oid) == ("building", False, False)
    assert _go(admin_client, oid, "shipped").status_code == 200
    assert _order(db, oid) == ("shipped", True, False)
    assert _go(admin_client, oid, "installed").status_code == 200
    assert _order(db, oid) == ("installed", True, True)
    r = _go(admin_client, oid, "installed")
    assert r.status_code == 409 and "already Installed" in r.json()["error"]
    db.commit()
    assert db.execute(sqltext(
        "SELECT count(*) FROM audit_log WHERE event_type = 'order_advanced' AND target_id = :o"),
        {"o": oid}).scalar() == 3


def test_a_sale_without_a_po_cannot_start_the_build(admin_client, db, vendor_order):
    db.execute(sqltext("UPDATE customer_orders SET po_number = NULL WHERE id = :o"), {"o": vendor_order})
    db.commit()
    r = _go(admin_client, vendor_order, "building")
    assert r.status_code == 409 and "customer PO" in r.json()["error"]
    assert _order(db, vendor_order)[0] == "new"


def test_a_viewer_cannot_advance(viewer_client, db, vendor_order):
    assert _go(viewer_client, vendor_order, "building").status_code == 403
    assert _order(db, vendor_order)[0] == "new"


def test_a_cancelled_order_cannot_advance_or_ship(admin_client, db, vendor_order):
    db.execute(sqltext("UPDATE customer_orders SET status = 'cancelled' WHERE id = :o"), {"o": vendor_order})
    db.commit()
    assert _go(admin_client, vendor_order, "building").status_code == 409
    r = admin_client.post(f"/fulfillment/{vendor_order}/ship", json={"shipped_date": "2026-10-01"})
    assert r.status_code == 409
    assert _order(db, vendor_order) == ("cancelled", False, False)


# ── pilots and demos ────────────────────────────────────────────────────────

def test_pilot_walks_assigned_shipped_at_site_returned(admin_client, db, pilot_order):
    oid, iid = pilot_order["order_id"], pilot_order["item_id"]
    r = _go(admin_client, oid, "shipped")
    assert r.status_code == 409 and "Assign at least one unit" in r.json()["error"]
    assert admin_client.post(f"/api/orders/{oid}/assign-items", json={"item_ids": [iid]}).status_code == 200
    r = _go(admin_client, oid, "shipped")
    assert r.status_code == 200 and r.json()["units_deployed"] == 1
    db.commit()
    assert db.execute(sqltext("SELECT item_status FROM item_schema.items WHERE id = :i"),
                      {"i": iid}).scalar() == "Deployed"
    r = _go(admin_client, oid, "at_site")
    assert r.status_code == 200 and r.json()["label"] == "Out at site"
    assert _order(db, oid) == ("delivered", True, True)
    r = _go(admin_client, oid, "returned")
    assert r.status_code == 200 and r.json()["units_returned"] == 1
    db.commit()
    assert db.execute(sqltext(
        "SELECT returned_date IS NOT NULL FROM device_provisioning WHERE customer_order_id = :o"),
        {"o": oid}).scalar() is True
    r = _go(admin_client, oid, "returned")
    assert r.status_code == 409 and "already Returned" in r.json()["error"]


# ── vendor documents ────────────────────────────────────────────────────────

def test_a_document_round_trips_and_is_removed(admin_client, db, vendor_order):
    body = b"%PDF-1.4 CONTRACT-TEST certificate\n"
    r = admin_client.post(f"/api/orders/{vendor_order}/documents",
                          data={"kind": "certification", "note": "CONTRACT-TEST"},
                          files={"file": ("cert.pdf", body, "application/pdf")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    got = admin_client.get(f"/orders/documents/{doc_id}")
    assert got.status_code == 200 and got.content == body
    assert admin_client.delete(f"/api/orders/documents/{doc_id}").status_code == 200
    assert admin_client.get(f"/orders/documents/{doc_id}").status_code == 404
    db.commit()
    assert db.execute(sqltext("SELECT count(*) FROM order_documents WHERE customer_order_id = :o"),
                      {"o": vendor_order}).scalar() == 0


@pytest.mark.parametrize("kind,name,status", [
    ("certification", "cert.exe", 400),
    ("receipt", "cert.pdf", 400),
    ("certification", "empty.pdf", 400),
])
def test_a_bad_document_is_refused(admin_client, db, vendor_order, kind, name, status):
    content = b"" if name == "empty.pdf" else b"data"
    r = admin_client.post(f"/api/orders/{vendor_order}/documents", data={"kind": kind},
                          files={"file": (name, content, "application/octet-stream")})
    assert r.status_code == status
    db.commit()
    assert db.execute(sqltext("SELECT count(*) FROM order_documents WHERE customer_order_id = :o"),
                      {"o": vendor_order}).scalar() == 0


def test_a_viewer_cannot_upload_a_document(viewer_client, vendor_order):
    r = viewer_client.post(f"/api/orders/{vendor_order}/documents", data={"kind": "other"},
                           files={"file": ("a.pdf", b"x", "application/pdf")})
    assert r.status_code == 403


# ── OEM PO status ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"vendor_name": "CONTRACT-TEST Vendor", "sku": "X", "status": "received"},
    {"vendor_name": "CONTRACT-TEST Vendor", "sku": "X", "qty_ordered": "lots"},
])
def test_an_oem_po_the_database_would_reject_gets_a_400(admin_client, db, vendor_order, payload):
    r = admin_client.post(f"/api/orders/{vendor_order}/oem-pos", json=payload)
    assert r.status_code == 400, r.text
    db.commit()
    assert db.execute(sqltext("SELECT count(*) FROM oem_purchase_orders WHERE customer_order_id = :o"),
                      {"o": vendor_order}).scalar() == 0


# ── shipping details ────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload,status", [
    ({"shipped_date": "2026-10-05", "delivered_date": "2026-10-01"}, 400),
    ({"ship_method": "pigeon"}, 422),
])
def test_bad_shipping_details_are_refused(admin_client, db, vendor_order, payload, status):
    r = admin_client.post(f"/fulfillment/{vendor_order}/ship", json=payload)
    assert r.status_code == status, r.text
    assert _order(db, vendor_order) == ("new", False, False)
