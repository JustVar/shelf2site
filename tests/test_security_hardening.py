"""Contract tests for the security pass (2026-10-19):

- a serial number cannot steer a certification upload outside its folder;
- cross-site browser writes are refused (SameSite=Lax is the first wall);
- bad input is a 400, not a server error: NUL bytes, non-object JSON,
  values too long for their column;
- the login limiter keys on the connecting client, not on a header the
  client can set.
Rows are CONTRACT-TEST-prefixed and removed here.
"""
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text as sqltext

from app.config import settings
from app.upload_paths import safe_segment, serial_dir

BASE = "http://127.0.0.1:8081"


# ── upload paths ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("serial,expected", [
    ("C2C4-0022", "C2C4-0022"),
    ("EBX_EDGE25.0001", "EBX_EDGE25.0001"),
    ("../../etc", "_.._etc"),
    ("/abs/path", "_abs_path"),
    ("..", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_a_serial_becomes_one_safe_segment(serial, expected):
    assert safe_segment(serial) == expected


def test_serial_dir_stays_under_its_root(tmp_path):
    for s in ("../../x", "..", "a/../../b", "C2C4-0001"):
        assert serial_dir(str(tmp_path), s).parent == tmp_path.resolve()


@pytest.fixture
def traversal_camera(admin_client, db):
    sku = "CONTRACT-TEST-TRAV-SKU"
    serial = "../../../contract-test-trav-" + uuid.uuid4().hex[:6]
    db.execute(sqltext("INSERT INTO item_schema.part_numbers (item_sku, item_category) VALUES (:s, 'camera_c2c')"),
               {"s": sku})
    cam = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status, item_sku) "
        "VALUES ('CONTRACT-TEST Trav Cam', :sn, 'camera_c2c', 'Ready to Deploy', :k) RETURNING id"),
        {"sn": serial, "k": sku}).scalar()
    db.commit()
    r = admin_client.post("/api/orders/", json={"customer_name": "CONTRACT-TEST Trav Corp", "order_type": "pilot",
                                                "expected_return": "2026-12-01"})
    oid = r.json()["id"]
    admin_client.put(f"/api/orders/{oid}", json={"sku_requirements": [{"model": sku, "qty": 1, "source": "stock"}]})
    r = admin_client.post("/fulfillment/c2c/acquire", json={"device_id": cam, "customer_order_id": oid})
    assert r.status_code == 200, r.text
    yield {"prov": r.json()["id"], "serial": serial}
    db.rollback()
    db.execute(sqltext("DELETE FROM c2c_certification_files WHERE c2c_certification_id IN (SELECT id FROM c2c_certification "
                       "WHERE device_provisioning_id IN (SELECT id FROM device_provisioning WHERE item_id = :i))"), {"i": cam})
    db.execute(sqltext("DELETE FROM c2c_certification WHERE device_provisioning_id IN "
                       "(SELECT id FROM device_provisioning WHERE item_id = :i)"), {"i": cam})
    db.execute(sqltext("DELETE FROM device_provisioning WHERE item_id = :i"), {"i": cam})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": oid})
    db.execute(sqltext("DELETE FROM audit_log WHERE target_table = 'items' AND target_id = :i"), {"i": cam})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": cam})
    db.execute(sqltext("DELETE FROM item_schema.part_numbers WHERE item_sku = :s"), {"s": sku})
    db.commit()


def test_a_serial_cannot_steer_an_upload_outside_its_folder(admin_client, traversal_camera):
    root = Path(settings.C2C_CERT_UPLOAD_DIR).resolve()
    escaped = (root / traversal_camera["serial"]).resolve()
    r = admin_client.post(f"/fulfillment/c2c/{traversal_camera['prov']}/files",
                          files={"file": ("t.pdf", b"%PDF-1.4 contract-test", "application/pdf")})
    assert r.status_code == 200, r.text
    assert not escaped.exists(), f"upload escaped to {escaped}"
    inside = root / safe_segment(traversal_camera["serial"])
    assert inside.is_dir() and any(inside.iterdir())
    got = admin_client.get(f"/fulfillment/c2c/files/{r.json()['file_id']}")
    assert got.status_code == 200 and got.content.startswith(b"%PDF")
    for f in inside.iterdir():
        f.unlink()
    inside.rmdir()


# ── cross-site writes ───────────────────────────────────────────────────────

@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_a_cross_site_write_is_refused(admin_client, headers):
    r = admin_client.post("/api/tours/progress", data={"tour_id": "x", "dismissed": "true"}, headers=headers)
    assert r.status_code == 403 and r.json()["detail"] == "Cross-site request refused"


def test_a_same_origin_write_passes(admin_client):
    r = admin_client.post("/api/orders/999999999/advance", json={"to": "building"},
                          headers={"Origin": BASE, "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 404


def test_a_cross_site_login_is_refused(anon):
    r = anon.post("/login", data={"username": "x", "password": "y"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ── bad input is a 400 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/inventory/?q=%00", "/api/receive/check-duplicate?serial=a%00b"])
def test_a_nul_byte_in_the_address_is_a_400(admin_client, path):
    assert admin_client.get(path).status_code == 400


@pytest.mark.parametrize("body", [b"[1, 2]", b"\"text\"", b"null", b"{not json"])
def test_a_json_write_needs_an_object(admin_client, body):
    r = admin_client.post("/api/orders/", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_a_nul_byte_in_a_body_is_a_400(admin_client, db):
    r = admin_client.post("/api/orders/", json={"customer_name": "CONTRACT-TEST bad\x00name", "order_type": "pilot"})
    assert r.status_code == 400
    db.commit()
    assert db.execute(sqltext("SELECT count(*) FROM customer_orders WHERE customer_name LIKE 'CONTRACT-TEST bad%'")).scalar() == 0


def test_a_value_too_long_for_its_column_is_a_400(admin_client, db):
    r = admin_client.post("/api/orders/", json={"customer_name": "CONTRACT-TEST Long", "order_type": "pilot"})
    oid = r.json()["id"]
    try:
        r = admin_client.post(f"/api/orders/{oid}/oem-pos", json={"vendor_name": "x" * 500, "sku": "CONTRACT-TEST"})
        assert r.status_code == 400 and "too long" in r.json()["error"]
    finally:
        db.rollback()
        db.execute(sqltext("DELETE FROM oem_purchase_orders WHERE customer_order_id = :o"), {"o": oid})
        db.execute(sqltext("DELETE FROM audit_log WHERE target_table = 'customer_orders' AND target_id = :o"), {"o": oid})
        db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": oid})
        db.commit()


def test_a_non_numeric_audit_user_filter_is_not_an_error(admin_client):
    assert admin_client.get("/admin/audit", params={"user_filter": "' OR 1=1--"}).status_code == 200


# ── login limiter ───────────────────────────────────────────────────────────

def test_a_forwarded_header_does_not_reset_the_login_limiter():
    """Five failures from one client lock it out for a minute, whatever it
    puts in X-Forwarded-For or CF-Connecting-IP. A trusted proxy (here the
    test runs on localhost, which uvicorn trusts) appends the real address on
    the right; the client controls only what is to its left. The real address
    is a documentation one, so the lockout touches no other test."""
    c = httpx.Client(base_url=BASE, timeout=30, follow_redirects=False)
    try:
        codes = []
        for i in range(7):
            r = c.post("/login", data={"username": "contract-test-nobody", "password": "wrong-password-xyz"},
                       headers={"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.77",
                                "CF-Connecting-IP": f"198.51.100.{i}"})
            codes.append(r.status_code)
        assert 429 in codes, codes
    finally:
        c.close()
