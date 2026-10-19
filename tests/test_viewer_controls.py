"""Read-only users see the fulfillment and custody pages without their write
controls (the routes refuse those writes as well). The fulfillment pages need
provisioning view, so that viewer is created with that one grant."""
import secrets

import httpx
import pytest
from sqlalchemy import text as sqltext

from app.auth import hash_password
from app.models import User

BOARD_CONTROLS = [
    ("/fulfillment/c2c", 'onclick="openC2cAcquire(null, null)"'),
    ("/fulfillment/pilots-due-back", 'onclick="pilotsMarkAll('),
]
CUSTODY_CONTROLS = [
    ("/checkout", '<button type="submit" class="fl-cta">Check Out</button>'),
    ("/checkin", '<button type="submit" class="fl-cta">Check In</button>'),
]


@pytest.fixture
def provisioning_viewer(db):
    password = "contract-test-" + secrets.token_urlsafe(12)
    u = User(username="contract-test-prov-viewer", display_name="Contract test provisioning viewer",
             role="viewer", password_hash=hash_password(password), is_active=True,
             must_change_password=False, can_view_provisioning="grant")
    db.add(u); db.commit(); db.refresh(u)
    c = httpx.Client(base_url="http://127.0.0.1:8081", timeout=30, follow_redirects=False)
    assert c.post("/login", data={"username": u.username, "password": password}).status_code == 302
    yield c
    c.close()
    db.rollback()
    db.execute(sqltext("DELETE FROM audit_log WHERE user_id = :i"), {"i": u.id})
    db.execute(sqltext("DELETE FROM error_log WHERE user_id = :i"), {"i": u.id})
    db.execute(sqltext("DELETE FROM users WHERE id = :i"), {"i": u.id})
    db.commit()


@pytest.fixture
def work_to_act_on(db):
    """The pilots page and the check-in form show their controls only when
    there is something to act on, so give them one loaned unit still out and
    one open checkout. Without this the suite would lean on the demo data."""
    ids = {}
    ids["order"] = db.execute(sqltext(
        "INSERT INTO customer_orders (order_number, customer_name, order_type, status, is_sensitive) "
        "VALUES ('AT-999932', 'CONTRACT-TEST Loan Co', 'pilot', 'new', false) RETURNING id")).scalar()
    ids["cam"] = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Loan Cam', 'CONTRACT-TEST-LOAN-CAM', 'camera_c2c', 'Ready to Deploy') "
        "RETURNING id")).scalar()
    ids["prov"] = db.execute(sqltext(
        "INSERT INTO device_provisioning (item_id, customer_order_id, current_stage, stages, is_complete) "
        "VALUES (:i, :o, 'acquired', '[]'::jsonb, false) RETURNING id"),
        {"i": ids["cam"], "o": ids["order"]}).scalar()
    ids["box"] = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST Lent Computer', 'CONTRACT-TEST-LENT-1', 'computer', 'Checked Out') RETURNING id")).scalar()
    ids["checkout"] = db.execute(sqltext(
        "INSERT INTO item_schema.checkouts (item_id, checked_out_to_name) "
        "VALUES (:i, 'CONTRACT-TEST borrower') RETURNING id"), {"i": ids["box"]}).scalar()
    db.commit()
    yield ids
    db.rollback()
    db.execute(sqltext("DELETE FROM item_schema.checkouts WHERE id = :i"), {"i": ids["checkout"]})
    db.execute(sqltext("DELETE FROM device_provisioning WHERE id = :i"), {"i": ids["prov"]})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id IN (:a, :b)"), {"a": ids["cam"], "b": ids["box"]})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :i"), {"i": ids["order"]})
    db.commit()


@pytest.mark.parametrize("path,control", BOARD_CONTROLS)
def test_provisioning_viewer_gets_no_board_writes(provisioning_viewer, admin_client, work_to_act_on, path, control):
    r = provisioning_viewer.get(path)
    assert r.status_code == 200, r.status_code
    assert control not in r.text
    assert control in admin_client.get(path).text


@pytest.mark.parametrize("path,control", CUSTODY_CONTROLS)
def test_viewer_gets_no_custody_submit(viewer_client, admin_client, work_to_act_on, path, control):
    r = viewer_client.get(path)
    assert r.status_code == 200, r.status_code
    assert control not in r.text
    assert control in admin_client.get(path).text
