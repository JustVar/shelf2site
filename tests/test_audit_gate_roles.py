"""Role discrimination on GET /admin/audit (item 33).

The nav boost and auth censuses prove the route is gated. Nothing proved it is
gated to the RIGHT role. The chain: require_audit_viewer (auth.py:234) ->
has_audit_access (models.py:665) = is_admin_tier or can_view_audit_log ==
'grant', a RAW column read that deliberately does NOT resolve through the
department, unlike every neighbouring domain property. d4a93a6 made department
grants inert by exactly that distinction.

Seeds are contract-test prefixed, created with ORM constructors (users has NOT
NULL columns whose defaults live on the model), commit-then-DELETE teardown.
"""

import secrets

import httpx
import pytest
from sqlalchemy import text as sqltext

from app.auth import hash_password
from app.models import Department, User

# Same base URL as conftest: the suite drives the live gunicorn bind.
BASE_URL = "http://127.0.0.1:8081"


@pytest.fixture
def audit_role_users(db):
    """A granting department plus two viewers: one with a user-level grant and
    no department, one at 'inherit' inside the granting department."""
    db.rollback()
    tag = secrets.token_hex(4)
    pw = "contract-test-" + secrets.token_urlsafe(12)

    dept = Department(name=f"contract-test-aud-dept-{tag}",
                      can_view_audit_log="grant")
    db.add(dept)
    db.commit()

    granted = User(username=f"contract-test-aud-grant-{tag}",
                   display_name=f"Contract audit grant {tag}", role="viewer",
                   password_hash=hash_password(pw), is_active=True,
                   must_change_password=False, can_view_audit_log="grant")
    inheritor = User(username=f"contract-test-aud-inherit-{tag}",
                     display_name=f"Contract audit inherit {tag}", role="viewer",
                     password_hash=hash_password(pw), is_active=True,
                     must_change_password=False, can_view_audit_log="inherit",
                     department_id=dept.id)
    db.add_all([granted, inheritor])
    db.commit()

    yield {"pw": pw, "granted": granted.username, "inheritor": inheritor.username,
           "granted_id": granted.id, "inheritor_id": inheritor.id,
           "dept_id": dept.id}

    for uid in (granted.id, inheritor.id):
        db.execute(sqltext("DELETE FROM audit_log WHERE user_id = :i"), {"i": uid})
        db.execute(sqltext("DELETE FROM users WHERE id = :i"), {"i": uid})
    db.execute(sqltext("DELETE FROM departments WHERE id = :d"), {"d": dept.id})
    db.commit()


def _login(username, password):
    c = httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=False)
    r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 302, f"login as {username} failed: HTTP {r.status_code}"
    return c


def test_plain_viewer_is_refused(viewer_client):
    """Case 1: viewer at 'inherit' with no department. 403, and the refusal
    names the missing access rather than being a generic denial."""
    r = viewer_client.get("/admin/audit")
    assert r.status_code == 403, r.text
    assert "Audit Log access" in r.json()["detail"]


def test_user_level_grant_admits(audit_role_users):
    """Case 2: an explicit user-level can_view_audit_log grant admits a plain
    viewer. The one identity besides admin tier that has_audit_access honours."""
    c = _login(audit_role_users["granted"], audit_role_users["pw"])
    try:
        r = c.get("/admin/audit")
        assert r.status_code == 200, r.text
        assert "All Events" in r.text, "the audit page itself must render"
    finally:
        c.close()


def test_department_grant_does_not_admit(audit_role_users):
    """Case 3, the discriminating one: 'inherit' inside a GRANTING department
    is still refused, because has_audit_access reads the raw column and never
    consults the department.

    Routing it through _resolve_perm, the plausible cleanup that would match
    every neighbouring domain property, flips this case to 200. Live data
    holds 5 of 6 departments at 'grant' and 25 of 26 users at 'inherit', so
    that cleanup would immediately admit roughly 25 accounts, which is the
    regression d4a93a6 closed."""
    c = _login(audit_role_users["inheritor"], audit_role_users["pw"])
    try:
        r = c.get("/admin/audit")
        assert r.status_code == 403, r.text
        assert "Audit Log access" in r.json()["detail"]
    finally:
        c.close()
