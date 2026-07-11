"""H14 RBAC contract tests for the receiving/scan surface.

Pins: scan accepts receiving users AND provisioning viewers (fulfillment
scan-to-find) but NOT bare viewers; check-duplicate is receiving-only (the
F15 enumeration oracle is closed); flag-only receiving users can use every
API the receive page calls (F10); direct-to-inventory is approval-gated per
target table (F9). The kiosk 403 stays pinned in test_auth_census.py.
"""

import secrets

import httpx
import pytest
from sqlalchemy import text as sqltext

from app.auth import hash_password
from app.models import User

BASE_URL = "http://127.0.0.1:8081"


@pytest.fixture(scope="module")
def receiving_flag_client(db):
    """A viewer-role user with ONLY the can_access_receiving grant (F10)."""
    username = "contract-test-recv-flag"
    password = "contract-test-" + secrets.token_urlsafe(12)
    u = db.query(User).filter(User.username == username).first()
    if u is None:
        u = User(username=username, display_name="Contract recv flag", role="viewer",
                 password_hash=hash_password(password), is_active=True,
                 must_change_password=False)
        db.add(u)
    else:
        u.password_hash = hash_password(password)
        u.role = "viewer"
        u.is_active = True
        u.must_change_password = False
    db.commit()
    db.execute(sqltext(
        "UPDATE users SET can_access_receiving = 'grant' WHERE username = :u"),
        {"u": username})
    db.commit()
    db.refresh(u)
    c = httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False)
    r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 302, r.text
    yield c
    c.close()
    db.rollback()
    uid = u.id
    db.execute(sqltext("DELETE FROM audit_log WHERE user_id = :i"), {"i": uid})
    db.execute(sqltext("DELETE FROM error_log WHERE user_id = :i"), {"i": uid})
    db.execute(sqltext("DELETE FROM users WHERE id = :i"), {"i": uid})
    db.commit()


# ── oracle lockdown ──────────────────────────────────────────────────────────

def test_bare_viewer_cannot_scan_or_enumerate(viewer_client):
    assert viewer_client.post("/api/receive/scan",
                              json={"barcode": "CONTRACT-TEST-X"}).status_code == 403
    assert viewer_client.get(
        "/api/receive/check-duplicate?serial=CONTRACT-TEST-X").status_code == 403
    assert viewer_client.get("/api/receive/photo/1").status_code == 403


# ── receiving-flag users get a working page (F10) ───────────────────────────

def test_flag_only_user_can_use_the_receive_apis(receiving_flag_client, db):
    r = receiving_flag_client.post("/api/receive/scan",
                                   json={"barcode": "CONTRACT-TEST-FLAG-NOPE"})
    assert r.status_code == 200 and r.json()["status"] == "unknown"

    r = receiving_flag_client.get(
        "/api/receive/check-duplicate?serial=CONTRACT-TEST-FLAG-NOPE")
    assert r.status_code == 200 and r.json()["exists"] is False

    ev = receiving_flag_client.post("/api/receive/events", json={
        "vendor": "CONTRACT-TEST-FLAG", "expected_quantity": 1})
    assert ev.status_code == 200, ev.text
    ev_id = ev.json()["event_id"]

    # pending path works; direct path is approval-gated for this user
    r = receiving_flag_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-FLAG-1", "target_table": "cameras",
        "direct_to_inventory": False, "receiving_event_id": ev_id})
    assert r.status_code == 200 and r.json()["status"] == "pending_review", r.text

    r = receiving_flag_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-FLAG-2", "target_table": "cameras",
        "direct_to_inventory": True})
    assert r.status_code == 403 and "approval rights" in r.json()["error"]

    db.rollback()
    db.execute(sqltext("DELETE FROM pending_devices WHERE serial LIKE 'CONTRACT-TEST-FLAG%'"))
    db.execute(sqltext("DELETE FROM receiving_events WHERE vendor = 'CONTRACT-TEST-FLAG'"))
    db.commit()


# ── provisioning viewers can scan-to-find, but cannot enumerate ──────────────

@pytest.fixture(scope="module")
def prov_view_client(db):
    """A viewer-role user with ONLY can_view_provisioning (fulfillment board)."""
    username = "contract-test-prov-view"
    password = "contract-test-" + secrets.token_urlsafe(12)
    u = db.query(User).filter(User.username == username).first()
    if u is None:
        u = User(username=username, display_name="Contract prov view", role="viewer",
                 password_hash=hash_password(password), is_active=True,
                 must_change_password=False)
        db.add(u)
    else:
        u.password_hash = hash_password(password)
        u.role = "viewer"
        u.is_active = True
        u.must_change_password = False
    db.commit()
    db.execute(sqltext(
        "UPDATE users SET can_view_provisioning = 'grant' WHERE username = :u"),
        {"u": username})
    db.commit()
    db.refresh(u)
    c = httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False)
    r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 302, r.text
    yield c
    c.close()
    db.rollback()
    uid = u.id
    db.execute(sqltext("DELETE FROM audit_log WHERE user_id = :i"), {"i": uid})
    db.execute(sqltext("DELETE FROM error_log WHERE user_id = :i"), {"i": uid})
    db.execute(sqltext("DELETE FROM users WHERE id = :i"), {"i": uid})
    db.commit()


def test_provisioning_viewer_scan_yes_enumerate_no(prov_view_client):
    """The fulfillment board's scan-to-find works for its viewers (F8), but
    the receive-side duplicate oracle stays closed to them."""
    r = prov_view_client.post("/api/receive/scan",
                              json={"barcode": "CONTRACT-TEST-PV-NOPE"})
    assert r.status_code == 200 and r.json()["status"] == "unknown"
    assert prov_view_client.get(
        "/api/receive/check-duplicate?serial=CONTRACT-TEST-PV-NOPE").status_code == 403


# ── direct-intake approval gate (F9) ─────────────────────────────────────────

def test_editor_direct_intake_gated_on_sites_admin_tables(editor_client, db):
    r = editor_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-F9-EB", "target_table": "edge_boxes",
        "direct_to_inventory": True})
    assert r.status_code == 403, r.text
    assert "approval rights" in r.json()["error"]

    # non-sites-admin categories still work for editors
    r = editor_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-F9-GPU", "target_table": "gpus",
        "direct_to_inventory": True})
    assert r.status_code == 200 and r.json()["status"] == "created", r.text
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM item_schema.receipt_items WHERE item_id IN "
        "(SELECT id FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-F9-GPU')"))
    db.execute(sqltext("DELETE FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-F9-GPU'"))
    db.commit()


def test_admin_direct_intake_into_edge_boxes_allowed(admin_client, db):
    r = admin_client.post("/api/receive/device", json={
        "serial": "CONTRACT-TEST-F9-ADM", "target_table": "edge_boxes",
        "direct_to_inventory": True})
    assert r.status_code == 200 and r.json()["status"] == "created", r.text
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM item_schema.receipt_items WHERE item_id IN "
        "(SELECT id FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-F9-ADM')"))
    db.execute(sqltext("DELETE FROM item_schema.items WHERE item_sn = 'CONTRACT-TEST-F9-ADM'"))
    db.commit()
