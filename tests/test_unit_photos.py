"""Shipment-photos contract tests: RBAC, N:M tagging, caps, sensitive-order
visibility, soft-hide/hard-delete. CONTRACT-TEST data, cleaned by fixtures.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import text as sqltext


def _jpeg(px=32, color=(200, 30, 30)):
    img = Image.new("RGB", (px, px), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def photo_ctx(db):
    """One item + one sensitive order + one receiving event."""
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Photo Box', 'CONTRACT-TEST-PH-1', 'edge_box', 'Unassigned') "
        "RETURNING id")).scalar()
    order_id = db.execute(sqltext(
        "INSERT INTO customer_orders (order_number, customer_name, order_type, status, is_sensitive) "
        "VALUES ('AT-999902', 'CONTRACT-TEST Sensitive Corp', 'sale', 'new', true) "
        "RETURNING id")).scalar()
    event_id = db.execute(sqltext(
        "INSERT INTO receiving_events (vendor, status) VALUES ('CONTRACT-TEST-PH', 'open') "
        "RETURNING id")).scalar()
    db.commit()
    yield {"item_id": item_id, "order_id": order_id, "event_id": event_id}
    db.rollback()
    db.execute(sqltext(
        "DELETE FROM unit_photos WHERE receiving_event_id = :e OR customer_order_id = :o "
        "OR id IN (SELECT photo_id FROM unit_photo_items WHERE item_id = :i)"),
        {"e": event_id, "o": order_id, "i": item_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
    db.execute(sqltext("DELETE FROM receiving_events WHERE id = :e"), {"e": event_id})
    db.commit()


def _upload(client, **form):
    data = {"direction": "inbound", **form}
    return client.post("/api/photos", data=data,
                       files={"file": ("test.jpg", _jpeg(), "image/jpeg")})


# ── RBAC ─────────────────────────────────────────────────────────────────────

def test_viewer_cannot_upload_but_can_view(viewer_client, editor_client, photo_ctx):
    r = viewer_client.post("/api/photos", data={"direction": "inbound"},
                           files={"file": ("t.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 403

    up = _upload(editor_client, serials="CONTRACT-TEST-PH-1")
    assert up.status_code == 200, up.text
    pid = up.json()["photo_id"]

    lst = viewer_client.get(f"/api/photos?item_id={photo_ctx['item_id']}")
    assert lst.status_code == 200
    assert pid in [p["photo_id"] for p in lst.json()["photos"]]
    assert viewer_client.get(f"/api/photos/{pid}/thumb").status_code == 200

    # soft-hide: editor OK, viewer 403; hard delete: editor 403, admin OK
    assert viewer_client.post(f"/api/photos/{pid}/hide").status_code == 403
    assert editor_client.post(f"/api/photos/{pid}/hide").status_code == 200
    assert viewer_client.get(f"/api/photos/{pid}/file").status_code == 404, "hidden = gone"
    assert editor_client.delete(f"/api/photos/{pid}").status_code == 403


def test_admin_hard_delete_removes_row(admin_client, photo_ctx, db):
    pid = _upload(admin_client).json()["photo_id"]
    assert admin_client.delete(f"/api/photos/{pid}").status_code == 200
    db.commit()
    assert db.execute(sqltext("SELECT count(*) FROM unit_photos WHERE id = :p"),
                      {"p": pid}).scalar() == 0


# ── tagging round trip ───────────────────────────────────────────────────────

def test_serial_tagging_and_retag_round_trip(editor_client, photo_ctx):
    up = _upload(editor_client, serials="contract-test-ph-1, NOPE-404")
    assert up.status_code == 200, up.text
    body = up.json()
    tagged = {t.get("serial"): t for t in body["tagged"]}
    assert tagged["contract-test-ph-1"]["item_id"] == photo_ctx["item_id"]
    assert "error" in tagged["NOPE-404"]
    assert [t["item_id"] for t in body["items"]] == [photo_ctx["item_id"]]

    # remove the tag, then add it back by serial
    pid = body["photo_id"]
    r = editor_client.post(f"/api/photos/{pid}/tags",
                           json={"remove": [photo_ctx["item_id"]]})
    assert r.status_code == 200 and r.json()["items"] == []
    r = editor_client.post(f"/api/photos/{pid}/tags",
                           json={"add": ["CONTRACT-TEST-PH-1"]})
    assert r.status_code == 200
    assert [t["item_id"] for t in r.json()["items"]] == [photo_ctx["item_id"]]


# ── caps + type validation ───────────────────────────────────────────────────

def test_heic_gets_a_clear_error(editor_client):
    r = editor_client.post("/api/photos", data={"direction": "inbound"},
                           files={"file": ("t.heic", b"xxxx", "image/heic")})
    assert r.status_code == 400 and "HEIC" in r.json()["error"]


def test_direction_validated(editor_client):
    r = editor_client.post("/api/photos", data={"direction": "sideways"},
                           files={"file": ("t.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 400


def test_non_image_rejected(editor_client):
    r = editor_client.post("/api/photos", data={"direction": "inbound"},
                           files={"file": ("t.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400 and "could not be read" in r.json()["error"]


# ── sensitive-order composition ──────────────────────────────────────────────

def test_sensitive_order_photo_invisible_to_viewer(admin_client, viewer_client, photo_ctx):
    up = _upload(admin_client, direction="outbound",
                 customer_order_id=str(photo_ctx["order_id"]))
    assert up.status_code == 200, up.text
    pid = up.json()["photo_id"]

    # admin sees it; viewer gets masked absence everywhere
    assert admin_client.get(f"/api/photos/{pid}/file").status_code == 200
    assert viewer_client.get(f"/api/photos/{pid}/file").status_code == 404
    assert viewer_client.get(f"/api/photos/{pid}/thumb").status_code == 404
    lst = viewer_client.get(f"/api/photos?order_id={photo_ctx['order_id']}")
    assert lst.status_code == 200 and lst.json()["photos"] == []


def test_gps_exif_is_stripped_on_save(editor_client, db):
    """The re-encode must drop EXIF (incl. GPS) — dossiers leave the building."""
    img = Image.new("RGB", (24, 24), (10, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "CONTRACT-TEST CAMERA"        # Make
    exif.get_ifd(0x8825)[1] = "N"                # GPSLatitudeRef
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    # sanity: the metadata really is in the upload
    probe = Image.open(io.BytesIO(buf.getvalue())).getexif()
    assert probe.get(0x010F) == "CONTRACT-TEST CAMERA"

    r = editor_client.post("/api/photos", data={"direction": "inbound"},
                           files={"file": ("gps.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200, r.text
    pid = r.json()["photo_id"]
    got = editor_client.get(f"/api/photos/{pid}/file")
    assert got.status_code == 200
    saved = Image.open(io.BytesIO(got.content)).getexif()
    assert 0x010F not in saved, "EXIF survived the re-encode"
    assert not dict(saved.get_ifd(0x8825)), "GPS IFD survived the re-encode"
    db.rollback()
    db.execute(sqltext("DELETE FROM unit_photos WHERE id = :p"), {"p": pid})
    db.commit()


# ── dossier export ───────────────────────────────────────────────────────────

def test_item_dossier_pdf_renders_with_photos(editor_client, photo_ctx):
    up = _upload(editor_client, serials="CONTRACT-TEST-PH-1", caption="arrival shot")
    assert up.status_code == 200, up.text
    r = editor_client.get(f"/items/{photo_ctx['item_id']}/dossier.pdf")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    import fitz
    doc = fitz.open(stream=r.content, filetype="pdf")
    assert doc.page_count >= 2, "details page + photo page expected"
    text = "".join(p.get_text() for p in doc)
    assert "CONTRACT-TEST-PH-1" in text
    assert "arrival shot" in text
    doc.close()


def test_dossier_masks_sensitive_photos_for_viewer(admin_client, viewer_client, db, photo_ctx):
    up = _upload(admin_client, direction="outbound",
                 customer_order_id=str(photo_ctx["order_id"]),
                 serials="CONTRACT-TEST-PH-1", caption="SENSITIVE-SHOT")
    assert up.status_code == 200, up.text
    import fitz
    priv = admin_client.get(f"/items/{photo_ctx['item_id']}/dossier.pdf")
    dp = fitz.open(stream=priv.content, filetype="pdf")
    assert "SENSITIVE-SHOT" in "".join(p.get_text() for p in dp)
    dp.close()
    pub = viewer_client.get(f"/items/{photo_ctx['item_id']}/dossier.pdf")
    assert pub.status_code == 200
    dv = fitz.open(stream=pub.content, filetype="pdf")
    assert "SENSITIVE-SHOT" not in "".join(p.get_text() for p in dv)
    dv.close()


def test_order_dossiers_zip(admin_client, db, photo_ctx):
    # link the item to a NON-sensitive order via provisioning, then export
    order_id = db.execute(sqltext(
        "INSERT INTO customer_orders (order_number, customer_name, order_type, status, is_sensitive) "
        "VALUES ('AT-999903', 'CONTRACT-TEST Zip Corp', 'pilot', 'new', false) RETURNING id")).scalar()
    db.execute(sqltext(
        "INSERT INTO device_provisioning (item_id, customer_order_id, "
        "current_stage, stages, is_complete) VALUES (:i, :o, 'acquired', '[]'::jsonb, false)"),
        {"i": photo_ctx["item_id"], "o": order_id})
    db.commit()
    try:
        r = admin_client.get(f"/orders/{order_id}/dossiers.zip")
        assert r.status_code == 200 and r.content[:2] == b"PK"
        import io as _io
        import zipfile as _zf
        z = _zf.ZipFile(_io.BytesIO(r.content))
        names = z.namelist()
        assert names == ["dossier-CONTRACT-TEST-PH-1.pdf"]
        assert z.read(names[0])[:5] == b"%PDF-"
    finally:
        db.rollback()
        db.execute(sqltext("DELETE FROM device_provisioning WHERE customer_order_id = :o"), {"o": order_id})
        db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": order_id})
        db.commit()


def test_sensitive_order_page_now_gated(admin_client, db, photo_ctx):
    """The /orders/{id} page previously had NO sensitive gate (board, panel,
    map and export all did) — pinned closed as part of this slice. The gate
    matters for users WITH provisioning view but WITHOUT sensitive access
    (bare viewers already 403 at require_provisioning_viewer)."""
    import secrets
    import httpx
    from app.auth import hash_password
    from app.models import User
    username = "contract-test-pv-photos"
    password = "contract-test-" + secrets.token_urlsafe(12)
    u = db.query(User).filter(User.username == username).first()
    if u is None:
        u = User(username=username, display_name="pv photos", role="viewer",
                 password_hash=hash_password(password), is_active=True,
                 must_change_password=False)
        db.add(u)
    else:
        u.password_hash = hash_password(password); u.is_active = True
    db.commit()
    db.execute(sqltext(
        "UPDATE users SET can_view_provisioning = 'grant' WHERE username = :u"),
        {"u": username})
    db.commit(); db.refresh(u)
    c = httpx.Client(base_url="http://127.0.0.1:8081", timeout=30, follow_redirects=False)
    try:
        assert c.post("/login", data={"username": username, "password": password}).status_code == 302
        r = c.get(f"/orders/{photo_ctx['order_id']}")
        assert r.status_code == 303, f"sensitive order must mask as redirect, got {r.status_code}"
        r = admin_client.get(f"/orders/{photo_ctx['order_id']}")
        assert r.status_code == 200
    finally:
        c.close()
        db.rollback()
        db.execute(sqltext("DELETE FROM audit_log WHERE user_id = :i"), {"i": u.id})
        db.execute(sqltext("DELETE FROM error_log WHERE user_id = :i"), {"i": u.id})
        db.execute(sqltext("DELETE FROM users WHERE id = :i"), {"i": u.id})
        db.commit()
