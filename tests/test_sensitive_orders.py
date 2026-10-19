"""A sensitive order and its work do not exist for a user without
sensitive-customer access, even one who can manage fulfillment. Reads
answer 404 or leave the order out of lists; writes answer 404. The admin
sees everything, which proves each check can fail (app/sensitive.py)."""
import secrets

import httpx
import pytest
from sqlalchemy import text as sqltext

from app.auth import hash_password
from app.models import User

NAME = "CONTRACT-TEST Hidden Clinic"


@pytest.fixture
def sensitive_order(db):
    oid = db.execute(sqltext(
        "INSERT INTO customer_orders (order_number, customer_name, order_type, status, is_sensitive) "
        "VALUES ('AT-999931', :n, 'pilot', 'new', true) RETURNING id"), {"n": NAME}).scalar()
    pid = db.execute(sqltext(
        "INSERT INTO device_provisioning (customer_order_id, current_stage, stages, is_complete) "
        "VALUES (:o, 'registered', '[]'::jsonb, false) RETURNING id"), {"o": oid}).scalar()
    db.commit()
    yield {"order_id": oid, "prov_id": pid}
    db.rollback()
    db.execute(sqltext("DELETE FROM device_provisioning WHERE customer_order_id = :o"), {"o": oid})
    db.execute(sqltext("DELETE FROM customer_orders WHERE id = :o"), {"o": oid})
    db.commit()


@pytest.fixture
def fulfillment_manager(db):
    password = "contract-test-" + secrets.token_urlsafe(12)
    u = User(username="contract-test-fl-manager", display_name="Contract test fulfillment manager",
             role="editor", password_hash=hash_password(password), is_active=True,
             must_change_password=False, can_view_provisioning="grant", can_manage_provisioning="grant")
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


def _reads(o):
    return [f"/api/fulfillment/panel/{o['order_id']}", f"/api/orders/{o['order_id']}/availability",
            f"/api/provisioning/{o['prov_id']}/validation-report"]


def test_hidden_order_reads_are_404(sensitive_order, fulfillment_manager, admin_client):
    for path in _reads(sensitive_order):
        assert fulfillment_manager.get(path).status_code == 404, path
    assert admin_client.get(f"/api/fulfillment/panel/{sensitive_order['order_id']}").status_code == 200


def test_hidden_provisioning_detail_redirects(sensitive_order, fulfillment_manager, admin_client):
    path = f"/provisioning/{sensitive_order['prov_id']}"
    assert fulfillment_manager.get(path).status_code == 302
    assert admin_client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/api/orders/open", "/provisioning/queue", "/fulfillment/"])
def test_hidden_order_left_out_of_lists(sensitive_order, fulfillment_manager, admin_client, path):
    r = fulfillment_manager.get(path)
    assert r.status_code == 200, r.status_code
    assert NAME not in r.text
    assert NAME in admin_client.get(path).text


def test_hidden_order_writes_are_404(sensitive_order, fulfillment_manager):
    o = sensitive_order
    assert fulfillment_manager.put(f"/api/orders/{o['order_id']}", json={"notes": "x"}).status_code == 404
    assert fulfillment_manager.post(f"/api/orders/{o['order_id']}/cancel", json={"reason": "x"}).status_code == 404
    assert fulfillment_manager.post(f"/api/provisioning/{o['prov_id']}/advance").status_code == 404
    assert fulfillment_manager.delete(f"/api/provisioning/{o['prov_id']}").status_code == 404
