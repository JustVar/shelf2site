"""The pending delete request badge (docs/specs/delete-request-queue.md, slice C).

Admins see the count of pending requests on the Admin section header, the
Data and logs subgroup header and the Delete requests link. Nobody else
sees it. The count is not cached, so it is right on the next page load
after a request is filed or decided, whichever worker serves the page.
Every record is CONTRACT-TEST prefixed and removed by the fixture.
"""

import re

import pytest
from sqlalchemy import text as sqltext

BADGE_IDS = ("sx-nav-dr-admin-badge", "sx-nav-dr-data-badge", "sx-nav-dr-badge")


@pytest.fixture
def badge_item(db):
    item_id = db.execute(sqltext(
        "INSERT INTO item_schema.items (item_name, item_sn, item_category, item_status) "
        "VALUES ('CONTRACT-TEST BADGE', 'CONTRACT-TEST-BADGE', 'camera_c2c', 'Unassigned') "
        "RETURNING id")).scalar()
    db.commit()
    yield item_id
    for table in ("delete_requests", "audit_log"):
        db.execute(sqltext(
            "DELETE FROM " + table + " WHERE target_table = 'items' AND target_id = :i"),
            {"i": item_id})
    db.execute(sqltext("DELETE FROM item_schema.items WHERE id = :i"), {"i": item_id})
    db.commit()


def _pending(db):
    db.expire_all()
    return db.execute(sqltext(
        "SELECT count(*) FROM delete_requests WHERE status = 'pending'")).scalar()


def _badges(client):
    html = client.get("/dashboard", headers={"accept": "text/html"}).text
    return {
        badge_id: (int(m.group(1)) if m else None)
        for badge_id in BADGE_IDS
        for m in [re.search('id="' + badge_id + r'">(\d+)<', html)]
    }


def _file(client, item_id):
    r = client.post("/api/delete-requests", json={
        "target_table": "items", "target_id": item_id, "reason": "duplicate record"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_admin_sees_the_pending_count_in_all_three_places(
        editor_client, admin_client, db, badge_item):
    _file(editor_client, badge_item)
    expected = _pending(db)
    assert expected >= 1
    assert _badges(admin_client) == {badge_id: expected for badge_id in BADGE_IDS}


def test_editor_never_sees_the_badge(editor_client, db, badge_item):
    _file(editor_client, badge_item)
    assert _badges(editor_client) == {badge_id: None for badge_id in BADGE_IDS}


def test_count_is_current_right_after_a_decision(editor_client, admin_client, db, badge_item):
    request_id = _file(editor_client, badge_item)
    before = _pending(db)
    assert admin_client.post(f"/api/delete-requests/{request_id}/reject").status_code == 200
    after = _pending(db)
    assert after == before - 1
    shown = _badges(admin_client)
    if after:
        assert shown == {badge_id: after for badge_id in BADGE_IDS}
    else:
        assert shown == {badge_id: None for badge_id in BADGE_IDS}
