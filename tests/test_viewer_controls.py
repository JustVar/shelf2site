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


@pytest.mark.parametrize("path,control", BOARD_CONTROLS)
def test_provisioning_viewer_gets_no_board_writes(provisioning_viewer, admin_client, path, control):
    r = provisioning_viewer.get(path)
    assert r.status_code == 200, r.status_code
    assert control not in r.text
    assert control in admin_client.get(path).text


@pytest.mark.parametrize("path,control", CUSTODY_CONTROLS)
def test_viewer_gets_no_custody_submit(viewer_client, admin_client, path, control):
    r = viewer_client.get(path)
    assert r.status_code == 200, r.status_code
    assert control not in r.text
    assert control in admin_client.get(path).text
